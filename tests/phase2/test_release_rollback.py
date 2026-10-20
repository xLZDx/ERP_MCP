"""S9 E3 (R2-US-045, TC134/TC135): rollback decision, authority, and "rights are never resurrected"."""
# ruff: noqa: DTZ001 - naive datetimes are deliberate hostile inputs in this file
import ast
import dataclasses
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from business_ai_gateway.phase2.evidence_attestation import (
    AttestationDecision,
    AttestationRequest,
    AttestationStore,
    CheckResult,
    Signer,
    SignerKind,
)
from business_ai_gateway.phase2.ops_types import (
    AUTHORITY,
    FakeCorrelationSource,
    FakeOperatorAuthority,
    OpsReason,
    OpsRefusal,
    OpsScope,
    is_valid_refusal,
)
from business_ai_gateway.phase2.release_migration import (
    MigrationStep,
    ObjectClass,
    Phase,
    SchemaName,
    StepKind,
)
from business_ai_gateway.phase2.release_rollback import (
    ACTION_CONTRACT_APPROVE,
    ACTION_ROLLBACK,
    MAX_GRANTS,
    AttestationBinding,
    BlockCause,
    EffectiveGrants,
    FakeGrantRegistry,
    GrantEntry,
    GrantId,
    GrantRecord,
    RegistryView,
    ReleaseState,
    ResurrectionEntry,
    RollbackDecision,
    RollbackPlan,
    SwitchSnapshot,
    decide_rollback,
    effective_after_rollback,
)

T0 = datetime(2026, 6, 1, tzinfo=UTC)
D1, D2 = "a" * 64, "b" * 64
FAR = T0 + timedelta(days=365)
_SRC = Path(__file__).resolve().parents[2] / "src" / "business_ai_gateway" / "phase2"


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


def flag_step():
    return MigrationStep(Phase.SWITCH, StepKind.FEATURE_FLAG, SchemaName.LIVING, ObjectClass.FEATURE_FLAG)


def contract_step():
    return MigrationStep(Phase.CONTRACT, StepKind.RETIRE_ROUTE, SchemaName.LIVING, ObjectClass.ROUTE)


def additive_step():
    return MigrationStep(Phase.EXPAND, StepKind.CREATE_TABLE, SchemaName.LIVING, ObjectClass.TABLE)


def refused(decision, reason):
    assert type(decision) is RollbackDecision and decision.allowed is False
    assert type(decision.refusal) is OpsRefusal and is_valid_refusal(decision.refusal)
    assert decision.reason is reason
    assert decision.plan_digest is None and decision.effective_grants == () and decision.blocked == ()
    assert decision.executed is False


class Env:
    def __init__(self):
        self.now = T0 + timedelta(minutes=1)
        self.registry = FakeGrantRegistry()
        self._n = 0
        self.store = AttestationStore(self.clock, accountants={"t1": ["acct"]}, id_source=self._id)
        self.authority = FakeOperatorAuthority()
        self.authority.allow("op-1", ACTION_ROLLBACK)
        self.approver = "op-2"  # a DIFFERENT person approves contract cleanup
        self.ids = FakeCorrelationSource()
        self.plan = RollbackPlan("v1", 5, (flag_step(),))
        self.state = ReleaseState("rel-1", T0, 3600, 3)

    def clock(self):
        return self.now

    def _id(self):
        self._n += 1
        return f"att-{self._n}"

    def decide(self, actor="op-1", plan=None, state=None, **kw):
        args = {"grants": self.registry, "attestations": self.store, "authority": self.authority,
                "clock": self.clock, "ids": self.ids}
        args.update(kw)
        if plan is not None:
            args.setdefault("contract_approver_id", self.approver)
        return decide_rollback(actor, plan or self.plan, state or self.state, **args)

    def effective(self, snapshot=None):
        return effective_after_rollback(self.registry, self.store, self.clock, self.ids, snapshot)

    def grant(self, name, expires=FAR, evidence=None):
        gid = GrantId(name)
        assert self.registry.issue(GrantRecord(gid, expires, evidence))
        return gid

    def attest(self):
        req = AttestationRequest("t1", D1, "pol-1", D2, "prop", "req", AttestationDecision.PASS)
        res = self.store.sign(req, Signer(SignerKind.HUMAN, "acct"))
        assert res.signed
        return res.attestation.attestation_id, AttestationBinding(
            res.attestation.attestation_id, "t1", D1, "pol-1", D2)

    def revoke_attestation(self, att_id):
        assert self.store.revoke(att_id, "t1", Signer(SignerKind.HUMAN, "acct")).revoked


@pytest.fixture
def env():
    return Env()


DESTRUCTIVE_KINDS = [StepKind.DROP_TABLE, StepKind.DROP_COLUMN, StepKind.DROP_INDEX,
                     StepKind.DROP_FUNCTION, StepKind.DROP_TRIGGER, StepKind.DROP_POLICY,
                     StepKind.DROP_SCHEMA, StepKind.DROP_ROLE, StepKind.TRUNCATE,
                     StepKind.ALTER_TYPE, StepKind.RENAME, StepKind.REVOKE, StepKind.DELETE_ROWS,
                     StepKind.UPDATE_ROWS, StepKind.NARROW_CONSTRAINT]


# ---- TC134: the allowed case ----------------------------------------------------------------------

def test_flag_flip_is_allowed_with_a_plan_digest_and_executed_false(env):
    d = env.decide()
    assert type(d) is RollbackDecision and d.allowed is True and d.refusal is None and d.reason is None
    assert type(d.plan_digest) is str and len(d.plan_digest) == 64
    assert d.executed is False and d.authority == AUTHORITY


def test_additive_steps_are_not_allowed_in_a_rollback_plan(env):
    plan = RollbackPlan("v1", 5, (flag_step(), additive_step()))
    refused(env.decide(plan=plan), OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)


@pytest.mark.parametrize("kind", [StepKind.GRANT, StepKind.ADD_ROLE, StepKind.INSERT_ROWS, StepKind.HARDEN_PRIVILEGES])
def test_a_rollback_plan_cannot_re_issue_rights_through_an_additive_step(env, kind):
    """F1: a re-issued right would bypass 'rollback never resurrects rights'."""
    for phase in Phase:
        step = MigrationStep(phase, kind, SchemaName.LIVING, ObjectClass.TABLE)
        refused(env.decide(plan=RollbackPlan("v1", 5, (flag_step(), step))), OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)


def test_plan_digest_is_deterministic_and_bound_to_plan_state_and_effective_grants(env):
    base = env.decide().plan_digest
    assert env.decide().plan_digest == base
    assert env.decide(plan=RollbackPlan("v2", 5, (flag_step(),))).plan_digest != base
    assert env.decide(plan=RollbackPlan("v1", 5, (flag_step(), flag_step()))).plan_digest != base
    assert env.decide(state=ReleaseState("rel-1", T0, 3600, 4)).plan_digest != base
    env.grant("g-1")
    with_grant = env.decide().plan_digest
    assert with_grant != base
    env.registry.revoke(GrantId("g-1"))
    assert env.decide().plan_digest == base  # the revoked grant is simply not part of the effect


def test_rollback_never_executes_and_never_changes_the_registry(env):
    gid = env.grant("g-1")
    env.decide()
    env.decide()
    view = env.registry.view(env.now)
    assert [e.revoked for e in view.entries] == [False]
    assert gid.value == "g-1"
    assert not any(name in dir(RollbackDecision) for name in ("execute", "apply", "run", "commit"))


# ---- TC134: the fixed denial set ------------------------------------------------------------------

@pytest.mark.parametrize("kind", DESTRUCTIVE_KINDS)
def test_every_destructive_step_denies_the_rollback(env, kind):
    for phase in Phase:  # whatever phase the step claims
        bad = MigrationStep(phase, kind, SchemaName.LIVING, ObjectClass.TABLE)
        plan = RollbackPlan("v1", 5, (flag_step(), bad))
        refused(env.decide(plan=plan), OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)


def test_denial_is_classification_based_so_aliased_or_disguised_steps_are_still_denied(env):
    alias = MigrationStep(Phase.SWITCH, StepKind.DROP_RELATION, SchemaName.LIVING, ObjectClass.FEATURE_FLAG)
    refused(env.decide(plan=RollbackPlan("v1", 5, (alias,))), OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)
    # a destructive step hidden inside an otherwise innocent flag flip, in last position
    hidden = RollbackPlan("v1", 5, (flag_step(),) * 10 + (MigrationStep(
        Phase.SWITCH, StepKind.TRUNCATE, SchemaName.LIVING, ObjectClass.TABLE),))
    refused(env.decide(plan=hidden), OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)


def test_s9_m06_a_step_mutated_by_the_grants_port_during_view_cannot_reach_the_digest(env):
    retained = MigrationStep(Phase.SWITCH, StepKind.ROUTE_SWITCH, SchemaName.LIVING, ObjectClass.ROUTE)
    expected = env.decide(plan=RollbackPlan("v1", 5, (retained,))).plan_digest

    class MutatingGrants:
        def view(self, now):
            object.__setattr__(retained, "kind", StepKind.DROP_TABLE)
            return env.registry.view(now)

    decision = env.decide(plan=RollbackPlan("v1", 5, (retained,)), grants=MutatingGrants())
    assert decision.allowed is True and decision.plan_digest == expected
    # the retained step is now really destructive: a fresh decision denies it
    refused(env.decide(plan=RollbackPlan("v1", 5, (retained,))), OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)


def test_unclassified_steps_are_denied_like_destructive_ones(env):
    for bad in (
        MigrationStep(Phase.SWITCH, "DROP_EVERYTHING", SchemaName.LIVING, ObjectClass.TABLE),
        MigrationStep(Phase.SWITCH, StepKind.FEATURE_FLAG, SchemaName.R1, ObjectClass.FEATURE_FLAG),
        MigrationStep(Phase.SWITCH, StepKind.FEATURE_FLAG, SchemaName.LIVING, ObjectClass.R1_TABLE),
        MigrationStep(Phase.EXPAND, StepKind.FEATURE_FLAG, SchemaName.LIVING, ObjectClass.FEATURE_FLAG),
        object.__new__(MigrationStep),
        "a plain string",
        None,
    ):
        refused(env.decide(plan=RollbackPlan("v1", 5, (flag_step(), bad))),
                OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)


def test_live_head_the_old_version_cannot_read_blocks_the_rollback(env):
    refused(env.decide(state=ReleaseState("rel-1", T0, 3600, 6)), OpsReason.ROLLBACK_HEAD_INCOMPATIBLE)
    assert env.decide(state=ReleaseState("rel-1", T0, 3600, 5)).allowed is True  # equal is readable
    refused(env.decide(plan=RollbackPlan("v1", 0, (flag_step(),)),
                       state=ReleaseState("rel-1", T0, 3600, 1)), OpsReason.ROLLBACK_HEAD_INCOMPATIBLE)


def test_destructive_wins_over_head_incompatibility(env):
    bad = MigrationStep(Phase.CONTRACT, StepKind.DROP_TABLE, SchemaName.LIVING, ObjectClass.TABLE)
    refused(env.decide(plan=RollbackPlan("v1", 0, (bad,)), state=ReleaseState("rel-1", T0, 3600, 9)),
            OpsReason.ROLLBACK_DESTRUCTIVE_DENIED)


def contract_plan():
    return RollbackPlan("v1", 5, (flag_step(), contract_step()))


def test_contract_cleanup_before_the_window_elapsed_is_refused_even_with_approval(env):
    env.authority.allow("op-2", ACTION_CONTRACT_APPROVE)
    env.now = T0 + timedelta(seconds=3599)
    refused(env.decide(plan=contract_plan()), OpsReason.ROLLBACK_WINDOW_OPEN)


def test_contract_cleanup_after_the_window_needs_a_separate_approval(env):
    env.now = T0 + timedelta(seconds=3600)
    refused(env.decide(plan=contract_plan()), OpsReason.CONTRACT_NOT_ALLOWED)
    env.authority.allow("op-2", ACTION_CONTRACT_APPROVE)
    assert env.decide(plan=contract_plan()).allowed is True
    env.authority.deny("op-2", ACTION_CONTRACT_APPROVE)  # deny wins again
    refused(env.decide(plan=contract_plan()), OpsReason.CONTRACT_NOT_ALLOWED)


def test_clock_regression_never_shortens_the_rollback_window(env):
    env.authority.allow("op-2", ACTION_CONTRACT_APPROVE)
    env.now = T0 + timedelta(seconds=3600)
    assert env.decide(plan=contract_plan()).allowed is True
    env.now = T0 + timedelta(seconds=10)  # the clock jumps back: the window is open again, not shorter
    refused(env.decide(plan=contract_plan()), OpsReason.ROLLBACK_WINDOW_OPEN)
    env.now = T0 - timedelta(days=400)  # even before the switch
    refused(env.decide(plan=contract_plan()), OpsReason.ROLLBACK_WINDOW_OPEN)


def test_window_arithmetic_overflow_keeps_the_window_open(env):
    env.authority.allow("op-2", ACTION_CONTRACT_APPROVE)
    state = ReleaseState("rel-1", datetime(9999, 12, 31, tzinfo=UTC), 3600, 3)
    refused(env.decide(plan=contract_plan(), state=state), OpsReason.ROLLBACK_WINDOW_OPEN)


def test_a_plan_without_contract_steps_ignores_the_window(env):
    env.now = T0  # the window is wide open, but nothing is being cleaned up
    assert env.decide().allowed is True


# ---- TC134: authority -----------------------------------------------------------------------------

def test_unknown_or_tenant_actor_is_not_authorized(env):
    for actor in ("tenant-user-1", "op-2", "OP-1"):
        refused(env.decide(actor=actor), OpsReason.NOT_AUTHORIZED)


def test_authority_is_action_specific(env):
    env.authority.allow("tenant-admin", ACTION_CONTRACT_APPROVE)  # another action does not help
    env.authority.allow("tenant-admin", "tenant.read")
    refused(env.decide(actor="tenant-admin"), OpsReason.NOT_AUTHORIZED)


def test_deny_wins_over_allow(env):
    env.authority.deny("op-1", ACTION_ROLLBACK)
    refused(env.decide(), OpsReason.NOT_AUTHORIZED)


def test_authorization_is_checked_before_anything_about_the_release_is_revealed(env):
    bad = MigrationStep(Phase.SWITCH, StepKind.TRUNCATE, SchemaName.LIVING, ObjectClass.TABLE)
    refused(env.decide(actor="stranger", plan=RollbackPlan("v1", 0, (bad,)),
                       state=ReleaseState("rel-1", T0, 3600, 9)), OpsReason.NOT_AUTHORIZED)
    refused(env.decide(actor="stranger", plan=contract_plan()), OpsReason.NOT_AUTHORIZED)


def test_only_an_exact_true_from_the_port_authorizes(env):
    class Port:
        def __init__(self, answer):
            self.answer = answer

        def authorized(self, actor_id, action):
            return self.answer

    class Truthy:
        def __bool__(self):
            return True

        def __eq__(self, other):
            return True

    for answer in (1, "yes", Truthy(), [True], None, 0, "True"):
        refused(env.decide(authority=Port(answer)), OpsReason.NOT_AUTHORIZED)
    assert env.decide(authority=Port(True)).allowed is True


def test_a_failing_authority_port_is_a_dependency_failure_not_an_allow(env):
    class Boom:
        def authorized(self, actor_id, action):
            raise RuntimeError("boom")

    refused(env.decide(authority=Boom()), OpsReason.DEPENDENCY_FAILED)
    refused(env.decide(authority=None), OpsReason.DEPENDENCY_FAILED)
    refused(env.decide(authority=object()), OpsReason.DEPENDENCY_FAILED)


def test_the_contract_approval_port_failing_denies(env):
    env.now = T0 + timedelta(seconds=3600)

    class Flaky:
        def __init__(self):
            self.calls = 0

        def authorized(self, actor_id, action):
            self.calls += 1
            if action == ACTION_CONTRACT_APPROVE:
                raise RuntimeError("boom")
            return True

    refused(env.decide(plan=contract_plan(), authority=Flaky()), OpsReason.DEPENDENCY_FAILED)


def test_contract_approval_needs_a_different_person_than_the_rollback_operator(env):
    """F3: separation of duties between the rollback authority and the contract approval."""
    env.now = T0 + timedelta(seconds=3600)
    env.authority.allow("op-2", ACTION_CONTRACT_APPROVE)
    env.authority.allow("op-1", ACTION_CONTRACT_APPROVE)  # the operator holds the right too: still not enough
    assert env.decide(plan=contract_plan()).allowed is True
    refused(env.decide(plan=contract_plan(), contract_approver_id="op-1"), OpsReason.CONTRACT_NOT_ALLOWED)
    refused(env.decide(plan=contract_plan(), contract_approver_id=None), OpsReason.CONTRACT_NOT_ALLOWED)
    refused(env.decide(plan=contract_plan(), contract_approver_id="op\u200b1"), OpsReason.CONTRACT_NOT_ALLOWED)
    refused(env.decide(plan=contract_plan(), contract_approver_id="nobody"), OpsReason.CONTRACT_NOT_ALLOWED)
    assert env.decide().allowed is True  # no contract steps: no approver needed


@pytest.mark.parametrize("actor", [None, 5, b"op-1", "", "   ", "op\x001", "op\u200b1", "x" * 10_000,
                                   EvilStr("op-1"), ["op-1"], object(), OpsScope("t1", "c1", "op-1")])
def test_hostile_actor_ids_are_input_invalid(env, actor):
    refused(env.decide(actor=actor), OpsReason.INPUT_INVALID)


# ---- TC134: structure and hostile input -----------------------------------------------------------

@pytest.mark.parametrize("plan", [
    None, 5, "plan", [], object(), object.__new__(RollbackPlan),
    RollbackPlan("v1", 5, ()), RollbackPlan("v1", 5, None), RollbackPlan("v1", 5, "steps"),
    RollbackPlan("v1", 5, (flag_step(),) * 257), RollbackPlan("bad id", 5, (flag_step(),)),
    RollbackPlan(EvilStr("v1"), 5, (flag_step(),)), RollbackPlan("v1", True, (flag_step(),)),
    RollbackPlan("v1", -1, (flag_step(),)), RollbackPlan("v1", 2**80, (flag_step(),)),
    RollbackPlan("v1", 5.0, (flag_step(),)),
])
def test_hostile_plans_are_input_invalid(env, plan):
    refused(decide_rollback("op-1", plan, env.state, grants=env.registry, attestations=env.store,
                            authority=env.authority, clock=env.clock, ids=env.ids), OpsReason.INPUT_INVALID)


@pytest.mark.parametrize("state", [
    None, 5, "state", object(), object.__new__(ReleaseState),
])
def test_hostile_states_are_input_invalid(env, state):
    refused(decide_rollback("op-1", env.plan, state, grants=env.registry, attestations=env.store,
                            authority=env.authority, clock=env.clock, ids=env.ids), OpsReason.INPUT_INVALID)


def test_state_and_plan_constructors_reject_bad_values():
    for bad in (("bad id", T0, 1, 1), ("r", datetime(2026, 1, 1), 1, 1), ("r", T0, True, 1),
                ("r", T0, -1, 1), ("r", T0, 1, -1), ("r", "2026", 1, 1), ("r", T0, 10**12, 1)):
        with pytest.raises(ValueError):
            ReleaseState(*bad)


def test_plan_and_state_are_snapshotted_once(env):
    steps = [flag_step()]
    plan = RollbackPlan("v1", 5, steps)  # type: ignore[arg-type]  # a list is tolerated, read once
    d = env.decide(plan=plan)
    steps.append(MigrationStep(Phase.SWITCH, StepKind.TRUNCATE, SchemaName.LIVING, ObjectClass.TABLE))
    assert d.allowed is True  # the decision was already taken from the entry-time copy


@pytest.mark.parametrize("clock", [None, 5, "now", lambda: None, lambda: "2026", lambda: datetime(2026, 1, 1),
                                   lambda: 5])
def test_unusable_clock_is_a_dependency_failure(env, clock):
    refused(env.decide(clock=clock), OpsReason.DEPENDENCY_FAILED)


def test_a_raising_or_subclass_clock_is_a_dependency_failure(env):
    class Sub(datetime):
        pass

    def boom():
        raise RuntimeError("boom")

    refused(env.decide(clock=boom), OpsReason.DEPENDENCY_FAILED)
    refused(env.decide(clock=lambda: Sub(2026, 1, 1, tzinfo=UTC)), OpsReason.DEPENDENCY_FAILED)


def test_a_failing_id_source_still_yields_a_valid_refusal(env):
    class Boom:
        def next_id(self):
            raise RuntimeError("boom")

    d = env.decide(actor="stranger", ids=Boom())
    assert d.reason is OpsReason.NOT_AUTHORIZED and is_valid_refusal(d.refusal)


def test_refusal_never_echoes_input(env):
    secret = "SECRET-ACTOR-TEXT"
    d = env.decide(actor=secret)
    assert d.reason is OpsReason.NOT_AUTHORIZED
    assert secret not in repr(d) and secret not in repr(d.refusal)
    d2 = env.decide(actor="secret\x00actor")
    assert "secret" not in repr(d2)


def test_decision_is_frozen_derived_and_cannot_be_forged_allowed(env):
    d = env.decide()
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.allowed = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        RollbackDecision(None, D1, allowed=True)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        RollbackDecision(None, None)  # allowed without a digest
    with pytest.raises(ValueError):
        RollbackDecision(None, "not-a-digest")
    refusal = env.decide(actor="x").refusal
    with pytest.raises(ValueError):
        RollbackDecision(refusal, D1)  # refused AND a digest
    with pytest.raises(ValueError):
        RollbackDecision(refusal, None, (GrantId("g-1"),))  # a refusal lists no grants
    with pytest.raises(ValueError):
        RollbackDecision("refused", None)  # type: ignore[arg-type]


# ---- registry fake --------------------------------------------------------------------------------

def test_typed_ids_reject_free_text():
    for bad in (None, 5, "", "has space", "a" * 65, "a\nb", "аbc", EvilStr("g-1"), b"g-1"):
        with pytest.raises(ValueError):
            GrantId(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        GrantRecord(GrantId("g-1"), datetime(2030, 1, 1))  # naive
    with pytest.raises(ValueError):
        GrantRecord("g-1", FAR)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        GrantRecord(GrantId("g-1"), FAR, "binding")  # type: ignore[arg-type]
    for bad in (("a", "t", "x" * 63, "p", D2), ("a", "t", D1, "p", "short"), ("", "t", D1, "p", D2),
                ("a", "t", D1, "", D2), ("a", "", D1, "p", D2)):
        with pytest.raises(ValueError):
            AttestationBinding(*bad)
    assert "g-1" not in repr(GrantId("g-1"))


def test_registry_issue_revoke_rules(env):
    rec = GrantRecord(GrantId("g-1"), FAR)
    assert env.registry.issue(rec) is True
    assert env.registry.issue(rec) is False  # an id is never reused
    assert env.registry.issue("g-2") is False and env.registry.issue(None) is False
    assert env.registry.issue(object.__new__(GrantRecord)) is False
    assert env.registry.revoke(GrantId("g-1")) is True
    assert env.registry.revoke(GrantId("g-1")) is True  # idempotent
    assert env.registry.revoke(GrantId("unknown")) is False
    assert env.registry.revoke("g-1") is False and env.registry.revoke(object.__new__(GrantId)) is False
    assert env.registry.issue(rec) is False  # re-issuing a revoked id does not revive it
    out = env.effective()
    assert out.effective == ()


def test_registry_cap(env):
    reg = FakeGrantRegistry()
    for i in range(MAX_GRANTS):
        assert reg.issue(GrantRecord(GrantId(f"g-{i}"), FAR))
    assert reg.issue(GrantRecord(GrantId("one-more"), FAR)) is False


def test_registry_view_high_water_never_goes_back(env):
    env.grant("g-1", expires=T0 + timedelta(hours=1))
    later = env.registry.view(T0 + timedelta(hours=2))
    assert later.effective_now == T0 + timedelta(hours=2)
    assert later.entries[0].expired is True
    earlier = env.registry.view(T0)  # the clock jumped back
    assert earlier.effective_now == T0 + timedelta(hours=2)
    assert earlier.entries[0].expired is True  # expiry is sticky
    assert env.registry.view(datetime(2026, 1, 1)) is None and env.registry.view("now") is None


def test_registry_view_is_an_immutable_snapshot(env):
    env.grant("g-1")
    view = env.registry.view(env.now)
    env.registry.revoke(GrantId("g-1"))
    assert view.entries[0].revoked is False  # the old view does not change ...
    assert env.registry.view(env.now).entries[0].revoked is True  # ... a new one shows the revocation
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.entries = ()  # type: ignore[misc]


def test_registry_is_consistent_under_concurrent_issue_revoke_and_view():
    reg = FakeGrantRegistry()
    errors = []
    names = [f"g-{t}-{i}" for t in range(8) for i in range(50)]

    def worker(t):
        try:
            for i in range(50):
                gid = GrantId(f"g-{t}-{i}")
                assert reg.issue(GrantRecord(gid, FAR))
                if i % 2:
                    assert reg.revoke(gid)
                view = reg.view(T0 + timedelta(seconds=i))
                assert view is not None
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    final = reg.view(T0)
    assert len(final.entries) == len(names)
    assert sum(e.revoked for e in final.entries) == len(names) // 2


# ---- TC135: rights and evidence are never resurrected ---------------------------------------------

def test_grant_issued_switch_revoked_rollback_is_not_effective(env):
    g = env.grant("grant-G")
    snapshot = SwitchSnapshot((g,))  # at switch time G was effective
    assert env.effective().effective == (g,)
    env.registry.revoke(g)
    d = env.decide(switch_snapshot=snapshot)
    assert d.allowed is True and g not in d.effective_grants and d.effective_grants == ()
    assert [(b.grant_id, b.cause) for b in d.blocked] == [(g, BlockCause.REVOKED)]
    assert all(b.reason is OpsReason.RESURRECTION_BLOCKED for b in d.blocked)


def test_second_rollback_and_a_clock_regression_leave_the_grant_revoked(env):
    g = env.grant("grant-G")
    snapshot = SwitchSnapshot((g,))
    env.registry.revoke(g)
    first = env.decide(switch_snapshot=snapshot)
    second = env.decide(switch_snapshot=snapshot)
    assert g not in first.effective_grants and g not in second.effective_grants
    assert first.plan_digest == second.plan_digest
    env.now = T0 - timedelta(days=30)  # clock regression
    third = env.decide(switch_snapshot=snapshot)
    assert g not in third.effective_grants
    assert [b.cause for b in third.blocked] == [BlockCause.REVOKED]
    env.now = T0 + timedelta(days=1)
    assert g not in env.decide().effective_grants


def test_a_stale_switch_time_snapshot_as_input_never_restores_a_grant(env):
    g = env.grant("grant-G")
    h = env.grant("grant-H")
    env.registry.revoke(g)
    stale = SwitchSnapshot((g, h, GrantId("never-existed")))
    out = env.effective(stale)
    assert out.effective == (h,)  # H is still current; G is not restored by the snapshot
    assert [(b.grant_id, b.cause) for b in out.blocked] == [(g, BlockCause.REVOKED)]
    assert out.snapshot_absent_count == 1
    everything = {x.value for x in out.effective} | {b.grant_id.value for b in out.blocked}
    assert "never-existed" not in everything  # absent from the registry: counted, never listed
    assert env.effective().effective == out.effective  # the same answer without any snapshot


def test_an_expired_credential_stays_expired(env):
    e = env.grant("grant-E", expires=T0 + timedelta(hours=1))
    ok = env.grant("grant-OK")
    snapshot = SwitchSnapshot((e, ok))
    env.now = T0 + timedelta(minutes=30)
    assert set(env.effective(snapshot).effective) == {e, ok}
    env.now = T0 + timedelta(hours=1)  # exactly at expiry: expired
    out = env.effective(snapshot)
    assert out.effective == (ok,) and [(b.grant_id, b.cause) for b in out.blocked] == [
        (e, BlockCause.EXPIRED)]
    env.now = T0  # clock regression: the registry already saw the later time
    out2 = env.effective(snapshot)
    assert out2.effective == (ok,) and out2.blocked[0].cause is BlockCause.EXPIRED
    refused_after = env.decide(switch_snapshot=snapshot)
    assert e not in refused_after.effective_grants


def test_an_attestation_revoked_after_the_switch_stays_revoked(env):
    att_id, binding = env.attest()
    g = env.grant("grant-G", evidence=binding)
    snapshot = SwitchSnapshot((g,))
    assert env.effective(snapshot).effective == (g,)
    env.revoke_attestation(att_id)
    out = env.effective(snapshot)
    assert out.effective == () and [(b.grant_id, b.cause) for b in out.blocked] == [
        (g, BlockCause.EVIDENCE_NOT_CURRENT)]
    env.now = T0 - timedelta(days=30)  # regress the shared clock (store and decision)
    out2 = env.effective(snapshot)
    assert out2.effective == () and out2.blocked[0].cause is BlockCause.EVIDENCE_NOT_CURRENT
    assert g not in env.decide(switch_snapshot=snapshot).effective_grants


def test_only_check_current_is_ever_asked_never_check_as_of(env):
    att_id, binding = env.attest()
    g = env.grant("grant-G", evidence=binding)
    env.now = T0 + timedelta(minutes=5)
    env.revoke_attestation(att_id)
    # the trap: a historical query before the revocation says "valid" and would resurrect the grant
    assert env.store.check_as_of(att_id, "t1", D1, "pol-1", D2, T0 + timedelta(minutes=2)).valid is True

    class Spy:
        def __init__(self, inner):
            self.inner = inner
            self.calls = []

        def check_current(self, *args):
            self.calls.append("check_current")
            return self.inner.check_current(*args)

        def check_as_of(self, *args):
            raise AssertionError("check_as_of must never be used for gating")

    spy = Spy(env.store)
    out = effective_after_rollback(env.registry, spy, env.clock, env.ids)
    assert out.effective == () and spy.calls == ["check_current"] and g.value == "grant-G"


def test_evidence_that_is_not_current_for_any_reason_is_not_effective(env):
    _, binding = env.attest()
    wrong_tenant = AttestationBinding(binding.attestation_id, "t2", D1, "pol-1", D2)
    wrong_revision = AttestationBinding(binding.attestation_id, "t1", D2, "pol-1", D2)
    wrong_policy = AttestationBinding(binding.attestation_id, "t1", D1, "pol-2", D2)
    unknown = AttestationBinding("att-unknown", "t1", D1, "pol-1", D2)
    for i, b in enumerate((wrong_tenant, wrong_revision, wrong_policy, unknown)):
        env.grant(f"bad-{i}", evidence=b)
    good = env.grant("good", evidence=binding)
    assert env.effective().effective == (good,)


def test_a_store_that_fails_or_lies_gives_no_evidence(env):
    _, binding = env.attest()
    env.grant("g-1", evidence=binding)

    class Boom:
        def check_current(self, *args):
            raise RuntimeError("boom")

    class Liar:
        def check_current(self, *args):
            return CheckResult.__new__(CheckResult)  # forged: attributes unset

    class Truthy:
        def check_current(self, *args):
            return type("R", (), {"valid": True, "code": "VALID"})()

    for store in (Boom(), Liar(), Truthy(), None, object()):  # F2: a failing store is a dependency failure
        out = effective_after_rollback(env.registry, store, env.clock, env.ids)
        assert type(out) is OpsRefusal and out.reason is OpsReason.DEPENDENCY_FAILED
        refused(env.decide(attestations=store), OpsReason.DEPENDENCY_FAILED)


def test_a_store_that_answers_not_valid_is_not_a_failure(env):
    att_id, binding = env.attest()
    g = env.grant("g-1", evidence=binding)
    other = env.grant("g-2")
    env.revoke_attestation(att_id)
    out = env.effective()
    assert out.effective == (other,) and g not in out.effective
    d = env.decide()
    assert d.allowed is True and d.effective_grants == (other,)


def test_a_grant_without_evidence_needs_none_and_a_late_grant_is_current(env):
    g = env.grant("g-1")
    snapshot = SwitchSnapshot((g,))
    late = env.grant("issued-after-switch")
    out = env.effective(snapshot)
    assert set(out.effective) == {g, late} and out.blocked == ()


def test_output_never_contains_a_grant_absent_from_the_current_registry(env):
    present = [env.grant(f"p-{i}") for i in range(3)]
    env.registry.revoke(present[0])
    ghosts = tuple(GrantId(f"ghost-{i}") for i in range(5))
    for snap in (SwitchSnapshot(ghosts), SwitchSnapshot(tuple(present) + ghosts), SwitchSnapshot(())):
        out = env.effective(snap)
        known = {g.value for g in present}
        listed = {g.value for g in out.effective} | {b.grant_id.value for b in out.blocked}
        assert listed <= known
        d = env.decide(switch_snapshot=snap)
        assert {g.value for g in d.effective_grants} | {b.grant_id.value for b in d.blocked} <= known


def test_resurrection_entries_carry_typed_ids_only(env):
    g = env.grant("g-1")
    env.registry.revoke(g)
    entry = env.effective(SwitchSnapshot((g,))).blocked[0]
    assert type(entry) is ResurrectionEntry and type(entry.grant_id) is GrantId
    assert {f.name for f in dataclasses.fields(ResurrectionEntry)} == {"grant_id", "cause"}
    assert entry.reason is OpsReason.RESURRECTION_BLOCKED
    assert "g-1" not in repr(entry)
    with pytest.raises(ValueError):
        ResurrectionEntry("g-1", BlockCause.REVOKED)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ResurrectionEntry(g, "REVOKED")  # type: ignore[arg-type]


def test_duplicate_snapshot_ids_are_reported_once(env):
    g = env.grant("g-1")
    env.registry.revoke(g)
    out = env.effective(SwitchSnapshot((g, g, g)))
    assert len(out.blocked) == 1


@pytest.mark.parametrize("snapshot", [
    "snap", 5, [], (), object(), object.__new__(SwitchSnapshot), SwitchSnapshot(None),
    SwitchSnapshot("g-1"), SwitchSnapshot(("g-1",)), SwitchSnapshot([None]),
    SwitchSnapshot((object.__new__(GrantId),)), SwitchSnapshot((GrantId("g-1"),) * (MAX_GRANTS + 1)),
])
def test_hostile_switch_snapshots_are_input_invalid_and_restore_nothing(env, snapshot):
    env.grant("g-1")
    out = env.effective(snapshot)
    assert type(out) is OpsRefusal and out.reason is OpsReason.INPUT_INVALID
    refused(env.decide(switch_snapshot=snapshot), OpsReason.INPUT_INVALID)


def test_registry_failures_are_dependency_failures(env):
    class Boom:
        def view(self, now):
            raise RuntimeError("boom")

    class Lying:
        def __init__(self, view):
            self._view = view

        def view(self, now):
            return self._view

    forged_entry = RegistryView((object.__new__(GrantEntry),), T0)
    duck = object.__new__(GrantEntry)  # a duck-typed record whose id is not a real GrantId
    object.__setattr__(duck, "record", SimpleNamespace(grant_id=SimpleNamespace(value="g-duck"),
                                                       credential_expires_at=T0 + timedelta(days=5), evidence=None))
    object.__setattr__(duck, "revoked", False)
    object.__setattr__(duck, "expired", False)
    for reg in (Boom(), None, object(), Lying(None), Lying("view"), Lying(forged_entry), Lying(RegistryView((duck,), T0)),
                Lying(RegistryView(("entry",), T0)), Lying(RegistryView([], T0)),
                Lying(RegistryView((), datetime(2026, 1, 1)))):
        out = effective_after_rollback(reg, env.store, env.clock, env.ids)
        assert type(out) is OpsRefusal and out.reason is OpsReason.DEPENDENCY_FAILED
        refused(env.decide(grants=reg), OpsReason.DEPENDENCY_FAILED)


def test_a_registry_entry_with_a_non_bool_flag_fails_closed(env):
    rec = GrantRecord(GrantId("g-1"), FAR)

    class Lying:
        def __init__(self, revoked, expired):
            self.args = (revoked, expired)

        def view(self, now):
            return RegistryView((GrantEntry(rec, *self.args),), T0)

    assert effective_after_rollback(Lying(False, False), env.store, env.clock, env.ids).effective \
        == (GrantId("g-1"),)
    for flags in ((1, False), (False, 1), ("no", False), (None, False), (False, None)):
        out = effective_after_rollback(Lying(*flags), env.store, env.clock, env.ids)
        assert out.effective == ()


def test_a_registry_cannot_grant_an_already_expired_credential_through_a_stale_flag(env):
    rec = GrantRecord(GrantId("g-1"), T0 + timedelta(hours=1))

    class StaleFlags:
        def view(self, now):
            return RegistryView((GrantEntry(rec, False, False),), T0 + timedelta(hours=2))

    out = effective_after_rollback(StaleFlags(), env.store, env.clock, env.ids)
    assert out.effective == ()  # the module judges expiry itself against the view's high-water


def test_effective_result_is_frozen_derived_and_bounded():
    g = GrantId("g-1")
    out = EffectiveGrants((g,), (), 0)
    assert len(out.digest) == 64 and out.authority == AUTHORITY
    with pytest.raises(TypeError):
        EffectiveGrants((g,), (), 0, digest="0" * 64)  # type: ignore[call-arg]
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.effective = ()  # type: ignore[misc]
    for bad in ((("g-1",), (), 0), ((g,), ("x",), 0), ((g,), (), -1), ((g,), (), True), ([g], (), 0)):
        with pytest.raises(ValueError):
            EffectiveGrants(*bad)  # type: ignore[arg-type]
    assert EffectiveGrants((g,), (), 0).digest == out.digest
    assert EffectiveGrants((), (), 0).digest != out.digest


def test_effective_grants_are_sorted_and_digest_is_order_independent_of_issue_order():
    a, b = Env(), Env()
    for name in ("g-b", "g-a", "g-c"):
        a.grant(name)
    for name in ("g-c", "g-a", "g-b"):
        b.grant(name)
    out_a, out_b = a.effective(), b.effective()
    assert [g.value for g in out_a.effective] == ["g-a", "g-b", "g-c"]
    assert out_a.digest == out_b.digest


def test_decision_with_many_grants_is_bounded_and_correct(env):
    for i in range(2000):
        env.grant(f"g-{i}")
    for i in range(0, 2000, 2):
        env.registry.revoke(GrantId(f"g-{i}"))
    d = env.decide()
    assert d.allowed is True and len(d.effective_grants) == 1000


def test_concurrent_decisions_never_show_a_revoked_grant_as_effective(env):
    gids = [env.grant(f"g-{i}") for i in range(50)]
    revoked_at_least = set()
    lock = threading.Lock()
    errors = []

    def revoker():
        for gid in gids:
            env.registry.revoke(gid)
            with lock:
                revoked_at_least.add(gid)

    def decider():
        try:
            for _ in range(30):
                with lock:
                    before = set(revoked_at_least)
                d = env.decide()
                assert not (set(d.effective_grants) & before)  # revoked before the call: never effective
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=revoker)] + [threading.Thread(target=decider) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert env.decide().effective_grants == ()


def test_no_tenant_data_in_any_e3_type():
    from business_ai_gateway.phase2 import release_migration as rm
    from business_ai_gateway.phase2 import release_rollback as rr

    for module in (rm, rr):
        for obj in vars(module).values():
            if dataclasses.is_dataclass(obj) and isinstance(obj, type):
                names = {f.name for f in dataclasses.fields(obj)}
                assert not names & {"company_id", "actor_id", "payload", "amount", "document",
                                    "counterparty", "inn", "name", "email"}, obj


# ---- import boundary and "no deletion code" -------------------------------------------------------

MODULES = ["release_migration.py", "release_rollback.py"]
FORBIDDEN_IMPORTS = {"httpx", "requests", "socket", "subprocess", "os", "pathlib", "random", "secrets",
                     "time", "shutil", "urllib", "http", "asyncio", "threading_x", "sqlite3", "psycopg",
                     "asyncpg", "ftplib", "smtplib", "ctypes", "glob", "tempfile", "io", "sys"}
FORBIDDEN_CALLS = {"delete", "remove", "unlink", "drop", "truncate", "rmtree", "rmdir", "removedirs",
                   "rename", "system", "popen", "exec", "eval", "open", "now", "utcnow", "today",
                   "urandom", "token_hex", "token_bytes", "randint", "choice", "uuid4", "sleep",
                   "monotonic", "time"}


@pytest.mark.parametrize("name", MODULES)
def test_modules_import_nothing_forbidden_and_no_release1(name):
    tree = ast.parse((_SRC / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
            assert not roots & FORBIDDEN_IMPORTS, (name, roots)
            assert not any(a.name.startswith("business_ai_gateway") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                assert node.module is not None
                assert node.module.split(".")[0] not in FORBIDDEN_IMPORTS, (name, node.module)
                assert not node.module.startswith("business_ai_gateway"), (name, node.module)
            else:  # relative import: must stay inside phase2 (a single dot)
                assert node.level == 1, (name, node.level, node.module)
                assert node.module is not None and "." not in node.module, (name, node.module)


@pytest.mark.parametrize("name", MODULES)
def test_modules_contain_no_deletion_clock_or_io_calls(name):
    tree = ast.parse((_SRC / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            assert called.lower() not in FORBIDDEN_CALLS, (name, called, node.lineno)


@pytest.mark.parametrize("name", MODULES)
def test_modules_import_only_phase2_siblings_that_are_themselves_clean(name):
    tree = ast.parse((_SRC / name).read_text(encoding="utf-8"))
    siblings = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 1}
    assert siblings <= {"_identity", "comparison_snapshot", "evidence_attestation", "ops_types", "release_migration"}


def test_module_level_has_no_mutable_ambient_state():
    for name in MODULES:
        tree = ast.parse((_SRC / name).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and node.targets[0].id != "__all__":
                assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set)), (name, node.lineno)
