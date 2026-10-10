"""S9 E4 / R2-US-046 / TC138: retention and legal hold only decide; they never delete."""
import ast
import dataclasses
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from business_ai_gateway.phase2.ops_types import (
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOperatorAuthority,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
)
from business_ai_gateway.phase2.retention_hold import (
    ACTION_APPROVE_DELETION,
    ACTION_PLACE_TENANT_HOLD,
    ACTION_REGISTER_LOW_RETENTION,
    ACTION_RELEASE_HOLD,
    ACTION_RELEASE_TENANT_HOLD,
    ACTION_SET_POLICY,
    ApprovalRequest,
    DeletionApproval,
    DeletionDecision,
    DeletionRequest,
    Hold,
    HoldLevel,
    HoldReason,
    HoldReleaseReceipt,
    ReleaseRequest,
    RetentionLedger,
    RetentionPolicy,
    decide_deletion,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "business_ai_gateway" / "phase2"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)
A1, A3 = OpsScope("t1", "c1", "a1"), OpsScope("t1", "c1", "a3")
BOB_SCOPE = OpsScope("t1", "c1", "bob")
CAROL_SCOPE = OpsScope("t1", "c1", "carol")
B1 = OpsScope("t1", "c9", "b1")  # same tenant, another company
A2 = OpsScope("t2", "c2", "a2")


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Ports:
    def __init__(self):
        self.log = []
        self.owner = FakeOwnership()
        self.ent = FakeEntitlements()
        for actor in ("a1", "a3", "bob", "carol"):
            self.ent.grant("t1", actor, "c1")
        self.ent.grant("t1", "b1", "c9")
        self.owner.add("t1", "c9", "run_id", "RB")
        self.owner.add("t1", "c9", "source_id", "SB")
        self.ent.grant("t2", "a2", "c2")
        for kind, ref in (("run_id", "R1"), ("run_id", "R2"), ("run_id", "R3"), ("source_id", "S1"),
                          ("source_id", "S2")):
            self.owner.add("t1", "c1", kind, ref)
        self.owner.add("t2", "c2", "run_id", "RF")
        self.owner.add("t2", "c2", "source_id", "SF")

    def entitled(self, tenant_id, actor_id, company_id):
        self.log.append(("entitled", tenant_id, actor_id, company_id))
        return self.ent.entitled(tenant_id, actor_id, company_id)

    def owns(self, tenant_id, company_id, kind, ref):
        self.log.append(("owns", tenant_id, company_id, kind, ref))
        return self.owner.owns(tenant_id, company_id, kind, ref)


class World:
    def __init__(self, cap=1000, audit=True, **kw):
        self.ports = Ports()
        self.auth = FakeOperatorAuthority()
        for actor in ("a1", "a2"):
            self.auth.allow(actor, ACTION_SET_POLICY)
            self.auth.allow(actor, ACTION_PLACE_TENANT_HOLD)
            self.auth.allow(actor, ACTION_RELEASE_TENANT_HOLD)
            self.auth.allow(actor, ACTION_REGISTER_LOW_RETENTION)
        for actor in ("bob", "carol"):
            self.auth.allow(actor, ACTION_RELEASE_TENANT_HOLD)
        for actor in ("bob", "carol"):
            self.auth.allow(actor, ACTION_APPROVE_DELETION)
            self.auth.allow(actor, ACTION_RELEASE_HOLD)
        self.clock = Clock(T0)
        self.audit_calls = []
        self.audit_answer = True
        self.ids = FakeCorrelationSource()
        self.ledger = RetentionLedger(self.ids, self.ports, self.ports, self.auth, self.clock,
                                      self._audit if audit else None, cap, **kw)
        assert isinstance(self.ledger.add_policy(A1, RetentionPolicy("fin", 1, 30 * DAY)), RetentionPolicy)
        for oid, src in (("R1", "S1"), ("R2", "S1"), ("R3", "S2"))[: 3 if cap > 2 else 2]:
            assert not isinstance(self.ledger.register_object(A1, "run_id", oid, src, "fin"), OpsRefusal)
        self.clock.t = T0 + 31 * DAY

    def _audit(self, record):
        self.audit_calls.append(record)
        if isinstance(self.audit_answer, Exception):
            raise self.audit_answer
        return self.audit_answer

    def request(self, ids=("R1", "R2"), approval_id="pending"):
        return DeletionRequest("run_id", tuple(ids), approval_id)

    def ask(self, ids=("R1", "R2"), approver="bob", ttl=3 * DAY, scope=A1):
        """Phase 1: the initiator records a request (nothing is approved yet)."""
        return self.ledger.request_approval(scope, self.request(ids), approver, self.clock.t + ttl)

    def confirm(self, pending, ids=("R1", "R2"), scope=BOB_SCOPE):
        """Phase 2: the approver acts under their OWN scope."""
        return self.ledger.confirm_approval(scope, self.request(ids, pending.approval_id))

    def approve(self, ids=("R1", "R2"), approver="bob", ttl=3 * DAY, scope=A1):
        pending = self.ask(ids, approver, ttl, scope)
        assert isinstance(pending, ApprovalRequest), pending
        approval = self.confirm(pending, ids, OpsScope(scope.tenant_id, scope.company_id, approver))
        assert isinstance(approval, DeletionApproval), approval
        return approval

    def release(self, hold, approver="bob", scope=A1):
        pending = self.ledger.request_release(scope, hold.hold_id, approver)
        assert isinstance(pending, ReleaseRequest), pending
        return self.ledger.confirm_release(OpsScope(scope.tenant_id, scope.company_id, approver), hold.hold_id)

    def decide(self, approval, ids=("R1", "R2"), scope=A1):
        return decide_deletion(scope, self.request(ids, approval.approval_id), self.ledger)


@pytest.fixture
def w():
    return World()


def reason(out):
    assert isinstance(out, OpsRefusal), out
    return out.reason


# ---- the positive plan ---------------------------------------------------------------------------

def test_all_conditions_met_gives_a_plan_that_is_never_executed(w):
    approval = w.approve()
    out = w.decide(approval)
    assert isinstance(out, DeletionDecision)
    assert out.executed is False and out.reason is OpsReason.DELETION_ALLOWED_PLAN
    assert out.authority == "EVALUATION_ONLY" and out.decided_at == w.clock.t
    assert out == w.decide(approval)  # deterministic on the injected clock
    assert repr(out) == "DeletionDecision(<redacted>)" and "executed" not in {f.name for f in dataclasses.fields(out)}
    with pytest.raises((AttributeError, TypeError)):
        out.executed = True  # type: ignore[misc]


def test_decision_cannot_be_forged():
    good = {"object_digest": "a" * 64, "approval_id": "x", "decided_at": T0, "plan_digest": "b" * 64}
    with pytest.raises(ValueError, match="DELETION_DECISION_INVALID"):
        DeletionDecision(**good)
    with pytest.raises(ValueError, match="DELETION_DECISION_INVALID"):
        DeletionDecision(**{**good, "authority": "OTHER"})


# ---- one fixed code per missing condition --------------------------------------------------------

@pytest.mark.parametrize("level,kind,target", [
    (HoldLevel.OBJECT, "run_id", "R1"), (HoldLevel.SOURCE, None, "S1"), (HoldLevel.TENANT, None, None)])
def test_active_hold_at_every_level_blocks_with_hold_active(w, level, kind, target):
    approval = w.approve()
    hold = w.ledger.place_hold(A1, level, HoldReason.LEGAL, kind, target)
    assert isinstance(hold, Hold)
    assert reason(w.decide(approval)) is OpsReason.HOLD_ACTIVE
    other = w.approve()  # a hold placed BEFORE a new approval still blocks
    assert reason(w.decide(other)) is OpsReason.HOLD_ACTIVE


@pytest.mark.parametrize("level,kind,target", [
    (HoldLevel.OBJECT, "run_id", "R3"), (HoldLevel.SOURCE, None, "S2")])
def test_hold_on_an_unrelated_object_or_source_does_not_block(w, level, kind, target):
    approval = w.approve()
    assert isinstance(w.ledger.place_hold(A1, level, HoldReason.AUDIT, kind, target), Hold)
    assert isinstance(w.decide(approval), DeletionDecision)  # an unrelated later hold does not touch it


def test_unrelated_hold_leaves_the_approval_intact(w):
    assert isinstance(w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.AUDIT, None, "S2"), Hold)
    approval = w.approve()  # approved AFTER the unrelated hold
    assert isinstance(w.decide(approval), DeletionDecision)


def test_hold_placed_after_the_approval_blocks_it(w):
    approval = w.approve()
    w.clock.t += timedelta(hours=1)
    w.ledger.place_hold(A1, HoldLevel.OBJECT, HoldReason.DISPUTE, "run_id", "R2")
    assert reason(w.decide(approval)) is OpsReason.HOLD_ACTIVE


def test_released_hold_placed_after_the_approval_still_invalidates_that_approval(w):
    approval = w.approve()
    w.clock.t += timedelta(hours=1)
    hold = w.ledger.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL)
    assert isinstance(w.release(hold), HoldReleaseReceipt)
    assert reason(w.decide(approval)) is OpsReason.APPROVAL_MISSING
    w.clock.t += timedelta(minutes=1)
    fresh = w.approve()  # a new approval after the release works
    assert isinstance(w.decide(fresh), DeletionDecision)


def test_hold_released_before_the_approval_does_not_matter(w):
    hold = w.ledger.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL)
    w.clock.t += DAY
    assert isinstance(w.release(hold), HoldReleaseReceipt)
    w.clock.t += DAY
    assert isinstance(w.decide(w.approve()), DeletionDecision)


def test_retention_not_elapsed_and_unregistered_object(w):
    approval = w.approve()
    w.clock.t = T0 + 29 * DAY
    assert reason(w.decide(approval)) is OpsReason.RETENTION_NOT_ELAPSED
    w.clock.t = T0 + 31 * DAY
    other = w.approve()
    out = w.decide(other, ids=("R1", "R2", "R3"))
    assert reason(out) is OpsReason.APPROVAL_DIGEST_MISMATCH  # R3 is registered, so only the digest differs
    w.ports.owner.add("t1", "c1", "run_id", "R9")
    assert reason(w.decide(other, ids=("R9",))) is OpsReason.RETENTION_NOT_ELAPSED  # owned, never registered


def test_exactly_at_the_boundary_retention_has_elapsed(w):
    approval = w.approve()
    w.clock.t = T0 + 30 * DAY  # registered at T0, min_age 30d
    assert isinstance(w.decide(approval), DeletionDecision)
    w.clock.t = T0 + 30 * DAY - timedelta(seconds=1)
    assert reason(w.decide(approval)) is OpsReason.RETENTION_NOT_ELAPSED


def test_clock_regression_never_shortens_retention_or_revives_an_expired_approval(w):
    approval = w.approve(ttl=2 * DAY)
    assert isinstance(w.decide(approval), DeletionDecision)
    w.clock.t = T0 + 10 * DAY  # the clock regresses: elapsed time shrinks, so deletion is refused
    assert reason(w.decide(approval)) is OpsReason.RETENTION_NOT_ELAPSED
    w.clock.t = T0 + 31 * DAY + 3 * DAY
    assert reason(w.decide(approval)) is OpsReason.APPROVAL_EXPIRED


def test_a_registration_with_a_regressed_clock_is_stamped_no_earlier_than_the_newest_record(w):
    w.clock.t = T0 + 5 * DAY  # regression: earlier than the stamps already recorded (T0)... but later than T0
    w.ports.owner.add("t1", "c1", "run_id", "R7")
    w.clock.t = T0 + 31 * DAY
    late = w.ledger.place_hold(A1, HoldLevel.OBJECT, HoldReason.AUDIT, "run_id", "R3")
    w.clock.t = T0
    record = w.ledger.register_object(A1, "run_id", "R7", "S1", "fin")
    assert record.retained_from >= late.placed_at  # never earlier than what is already recorded


def test_missing_approval_wrong_requester_and_lost_authority(w):
    assert reason(w.decide(DeletionApproval("nope", "a" * 64, "x", "y", T0, T0))) is OpsReason.APPROVAL_MISSING
    approval = w.approve()
    assert reason(w.decide(approval, scope=A3)) is OpsReason.APPROVAL_MISSING  # raised by a1, not a3
    w.auth.deny("bob", ACTION_APPROVE_DELETION)
    assert reason(w.decide(approval)) is OpsReason.APPROVAL_MISSING


def test_expired_approval(w):
    approval = w.approve(ttl=DAY)
    w.clock.t += DAY
    assert reason(w.decide(approval)) is OpsReason.APPROVAL_EXPIRED


def test_approval_is_bound_to_the_exact_object_list(w):
    approval = w.approve(("R1", "R2"))
    assert reason(w.decide(approval, ids=("R1", "R2", "R3"))) is OpsReason.APPROVAL_DIGEST_MISMATCH
    assert reason(w.decide(approval, ids=("R1",))) is OpsReason.APPROVAL_DIGEST_MISMATCH
    assert isinstance(w.decide(approval), DeletionDecision)


def test_approval_is_bound_to_the_policy_version(w):
    approval = w.approve()
    assert isinstance(w.ledger.add_policy(A1, RetentionPolicy("fin", 2, 30 * DAY)), RetentionPolicy)
    assert reason(w.decide(approval)) is OpsReason.APPROVAL_DIGEST_MISMATCH


def test_self_approval_is_refused_when_requested_and_when_the_approver_decides(w):
    out = w.ledger.request_approval(A1, w.request(), "a1", w.clock.t + DAY)
    assert reason(out) is OpsReason.SELF_APPROVAL
    approval = w.approve(approver="bob")
    assert reason(w.decide(approval, scope=BOB_SCOPE)) is OpsReason.SELF_APPROVAL
    out = w.ledger.request_approval(A1, w.request(), "a\u200b1", w.clock.t + DAY)
    assert reason(out) in (OpsReason.SELF_APPROVAL, OpsReason.INPUT_INVALID)


def test_approver_needs_the_platform_authority(w):
    out = w.ledger.request_approval(A1, w.request(), "mallory", w.clock.t + DAY)
    assert reason(out) is OpsReason.NOT_AUTHORIZED


def test_approval_ttl_is_bounded_and_future(w):
    for bad in (w.clock.t, w.clock.t - DAY, w.clock.t + 31 * DAY, "x", None, datetime(2030, 1, 1)):  # noqa: DTZ001
        assert reason(w.ledger.request_approval(A1, w.request(), "bob", bad)) is OpsReason.INPUT_INVALID


# ---- D1: four-eyes is a two-phase process, the approver must really act -------------------------------

def test_naming_an_approver_who_never_acts_yields_no_approval_and_no_plan(w):
    pending = w.ask(approver="bob")
    assert isinstance(pending, ApprovalRequest)
    # only a confirm creates a stored approval: a forged object or the bare pending id decides nothing
    forged = DeletionApproval(pending.approval_id, "a" * 64, "a1", "bob", T0, T0 + DAY)
    assert reason(w.decide(forged)) is OpsReason.APPROVAL_MISSING
    assert reason(w.decide(pending)) is OpsReason.APPROVAL_MISSING


def test_the_named_approver_confirming_under_his_own_scope_creates_the_plan(w):
    pending = w.ask(approver="bob")
    approval = w.confirm(pending, scope=BOB_SCOPE)
    assert isinstance(approval, DeletionApproval) and approval.approver == "bob" and approval.requester == "a1"
    assert isinstance(w.decide(approval), DeletionDecision)


def test_the_initiator_confirming_his_own_request_is_self_approval(w):
    pending = w.ask(approver="bob")
    assert reason(w.confirm(pending, scope=A1)) is OpsReason.SELF_APPROVAL
    assert reason(w.decide(pending)) is OpsReason.APPROVAL_MISSING


def test_confirm_checks_the_confirming_actors_own_right_entitlement_and_ownership(w):
    pending = w.ask(approver="bob")
    assert reason(w.confirm(pending, scope=A3)) is OpsReason.NOT_AUTHORIZED  # entitled, but no approve right
    assert reason(w.confirm(pending, scope=OpsScope("t1", "c1", "stranger"))) is OpsReason.NOT_ENTITLED
    assert reason(w.confirm(pending, scope=B1)) is OpsReason.OBJECT_NOT_OWNED  # another company owns none of them
    w.auth.deny("bob", ACTION_APPROVE_DELETION)
    assert reason(w.confirm(pending, scope=BOB_SCOPE)) is OpsReason.NOT_AUTHORIZED


def test_a_third_authorized_person_cannot_confirm_a_request_that_named_somebody_else(w):
    pending = w.ask(approver="bob")
    assert reason(w.confirm(pending, scope=CAROL_SCOPE)) is OpsReason.APPROVAL_MISSING


def test_a_pending_request_expires_and_is_confirmed_at_most_once(w):
    pending = w.ask(ttl=DAY)
    assert isinstance(w.confirm(pending), DeletionApproval)
    assert reason(w.confirm(pending)) is OpsReason.DUPLICATE_SUPPRESSED
    late = w.ask(ttl=DAY)
    w.clock.t += DAY
    assert reason(w.confirm(late)) is OpsReason.APPROVAL_EXPIRED


def test_an_unknown_approval_id_and_another_companys_one_read_identically():
    w = World()
    registered = w.ledger.register_object(B1, "run_id", "RB", "SB", "fin")
    assert not isinstance(registered, OpsRefusal), registered
    foreign = w.ledger.request_approval(B1, DeletionRequest("run_id", ("RB",), "x"), "bob", w.clock.t + DAY)
    assert isinstance(foreign, ApprovalRequest)
    outs = []
    for aid in (foreign.approval_id, "unknown-id"):  # a c1 actor probes with it over his OWN objects
        w.ports.log.clear()
        outs.append((w.ledger.confirm_approval(BOB_SCOPE, w.request(approval_id=aid)), [c[:1] for c in w.ports.log]))
    assert reason(outs[0][0]) is OpsReason.APPROVAL_MISSING
    assert outs[0][0].reason == outs[1][0].reason and outs[0][1] == outs[1][1]
    assert reason(decide_deletion(A1, w.request(approval_id=foreign.approval_id), w.ledger)) is OpsReason.APPROVAL_MISSING


# ---- ownership first, foreign == unknown --------------------------------------------------------

def test_foreign_and_unknown_objects_give_the_identical_refusal_and_port_pattern():
    outs, patterns = [], []
    for obj in ("RF", "R-UNKNOWN"):
        w = World()
        w.ports.log.clear()
        outs.append(decide_deletion(A1, DeletionRequest("run_id", (obj,), "x"), w.ledger))
        patterns.append([(c[0], c[1], c[2], c[3] if c[0] == "owns" else None) for c in w.ports.log])
        approve = w.ledger.request_approval(A1, DeletionRequest("run_id", (obj,), "x"), "bob", w.clock.t + DAY)
        assert reason(approve) is OpsReason.OBJECT_NOT_OWNED
        confirm = w.ledger.confirm_approval(BOB_SCOPE, DeletionRequest("run_id", (obj,), "x"))
        assert reason(confirm) is OpsReason.OBJECT_NOT_OWNED
    assert outs[0] == outs[1] and reason(outs[0]) is OpsReason.OBJECT_NOT_OWNED
    assert patterns[0] == patterns[1] and [p[0] for p in patterns[0]] == ["entitled", "owns"]


def test_every_object_is_asked_and_the_unentitled_actor_learns_nothing(w):
    w.ports.log.clear()
    out = decide_deletion(A1, DeletionRequest("run_id", ("RF", "R1", "R2"), "x"), w.ledger)
    assert reason(out) is OpsReason.OBJECT_NOT_OWNED
    assert [c[0] for c in w.ports.log] == ["entitled", "owns", "owns", "owns"]
    w.ports.log.clear()
    stranger = OpsScope("t1", "c1", "stranger")
    assert reason(decide_deletion(stranger, DeletionRequest("run_id", ("R1",), "x"), w.ledger)) is OpsReason.NOT_ENTITLED
    assert [c[0] for c in w.ports.log] == ["entitled"]


def test_the_other_tenants_holds_and_objects_are_invisible(w):
    approval = w.approve()
    other = World()
    assert isinstance(other.ledger.place_hold(A2, HoldLevel.TENANT, HoldReason.LEGAL), Hold)
    assert isinstance(w.decide(approval), DeletionDecision)  # the hold lives in another ledger and tenant
    shared = w.ledger.place_hold(A2, HoldLevel.TENANT, HoldReason.LEGAL)  # t2 in the SAME ledger
    assert isinstance(shared, Hold) and isinstance(w.decide(approval), DeletionDecision)
    assert reason(w.ledger.request_release(A1, shared.hold_id, "bob")) is OpsReason.NOT_FOUND  # not even visible


# ---- release: two phases, a different approver who really acts, audited, atomic ------------------

def _hold(w):
    return w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.REGULATORY, None, "S1")


def test_release_needs_a_different_authorized_approver_and_is_audited_once(w):
    hold = _hold(w)
    assert reason(w.ledger.request_release(A1, hold.hold_id, "a1")) is OpsReason.SELF_APPROVAL
    assert reason(w.ledger.request_release(A1, hold.hold_id, "mallory")) is OpsReason.NOT_AUTHORIZED
    assert w.audit_calls == []  # nothing audited, nothing released
    receipt = w.release(hold, "bob")
    assert isinstance(receipt, HoldReleaseReceipt) and receipt.hold_id == hold.hold_id
    assert len(w.audit_calls) == 1
    record = w.audit_calls[0]
    assert (record.action, record.tenant_id, record.company_id, record.requester, record.approver,
            record.hold_id) == ("HOLD_RELEASED", "t1", "c1", "a1", "bob", hold.hold_id)
    assert reason(w.ledger.request_release(A1, hold.hold_id, "carol")) is OpsReason.DUPLICATE_SUPPRESSED
    assert reason(w.ledger.confirm_release(CAROL_SCOPE, hold.hold_id)) is OpsReason.DUPLICATE_SUPPRESSED
    assert len(w.audit_calls) == 1


def test_a_named_approver_who_never_acts_releases_nothing_and_audits_nothing(w):
    approval = w.approve()
    w.clock.t += timedelta(minutes=1)
    hold = w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.LEGAL, None, "S1")
    assert isinstance(w.ledger.request_release(A1, hold.hold_id, "bob"), ReleaseRequest)
    assert w.audit_calls == [] and reason(w.decide(approval)) is OpsReason.HOLD_ACTIVE
    # the initiator confirming his own request, a stranger and an unnamed authorized person all fail
    assert reason(w.ledger.confirm_release(A1, hold.hold_id)) is OpsReason.SELF_APPROVAL
    assert reason(w.ledger.confirm_release(CAROL_SCOPE, hold.hold_id)) is OpsReason.APPROVAL_MISSING
    assert reason(w.ledger.confirm_release(A3, hold.hold_id)) is OpsReason.NOT_AUTHORIZED
    assert w.audit_calls == [] and reason(w.decide(approval)) is OpsReason.HOLD_ACTIVE
    receipt = w.ledger.confirm_release(BOB_SCOPE, hold.hold_id)
    assert isinstance(receipt, HoldReleaseReceipt) and w.audit_calls[0].approver == "bob"  # the REAL confirming actor


def test_confirming_without_any_request_is_approval_missing(w):
    hold = _hold(w)
    assert reason(w.ledger.confirm_release(BOB_SCOPE, hold.hold_id)) is OpsReason.APPROVAL_MISSING
    assert w.audit_calls == []


def test_the_audit_names_the_confirming_actor_not_the_named_one(w):
    hold = _hold(w)
    assert isinstance(w.ledger.request_release(A1, hold.hold_id, "bob"), ReleaseRequest)
    assert isinstance(w.ledger.request_release(A1, hold.hold_id, "carol"), ReleaseRequest)  # supersedes the first
    assert reason(w.ledger.confirm_release(BOB_SCOPE, hold.hold_id)) is OpsReason.APPROVAL_MISSING
    assert isinstance(w.ledger.confirm_release(CAROL_SCOPE, hold.hold_id), HoldReleaseReceipt)
    assert (w.audit_calls[0].requester, w.audit_calls[0].approver) == ("a1", "carol")


# ---- D2: a hold is bound to its company; foreign and unknown ids are one refusal --------------------

def test_a_hold_of_another_company_is_indistinguishable_from_an_unknown_hold():
    w = World()
    foreign = w.ledger.place_hold(B1, HoldLevel.SOURCE, HoldReason.LEGAL, None, "SB")
    assert isinstance(foreign, Hold) and foreign.company_id == "c9"
    outs = []
    for hold_id in (foreign.hold_id, "no-such-hold"):
        w.ports.log.clear()
        outs.append((w.ledger.request_release(A1, hold_id, "bob"), w.ledger.confirm_release(BOB_SCOPE, hold_id),
                     [(c[0], c[1], c[2]) for c in w.ports.log]))
    assert reason(outs[0][0]) is OpsReason.NOT_FOUND and reason(outs[0][1]) is OpsReason.NOT_FOUND
    assert outs[0][0].reason == outs[1][0].reason and outs[0][1].reason == outs[1][1].reason
    assert outs[0][2] == outs[1][2]  # the identical port-call pattern
    assert w.audit_calls == []
    # the owner company can still address its own hold
    assert isinstance(w.ledger.request_release(B1, foreign.hold_id, "bob"), ReleaseRequest)


def test_the_holds_own_object_ownership_is_checked_before_a_release_request(w):
    hold = _hold(w)
    assert hold.company_id == "c1"
    w.ports.owner._rows.discard(("t1", "c1", "source_id", "S1"))  # the source is no longer owned by the company
    assert reason(w.ledger.request_release(A1, hold.hold_id, "bob")) is OpsReason.NOT_FOUND
    assert reason(w.ledger.confirm_release(BOB_SCOPE, hold.hold_id)) is OpsReason.NOT_FOUND
    assert w.audit_calls == []


def test_a_tenant_level_hold_needs_the_platform_right_to_be_released(w):
    hold = w.ledger.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL)
    w.auth.deny("a1", ACTION_RELEASE_TENANT_HOLD)
    assert reason(w.ledger.request_release(A1, hold.hold_id, "bob")) is OpsReason.NOT_AUTHORIZED
    w.auth.allow("a1", ACTION_RELEASE_TENANT_HOLD)
    w.auth._deny.discard(("a1", ACTION_RELEASE_TENANT_HOLD))
    assert isinstance(w.ledger.request_release(A1, hold.hold_id, "bob"), ReleaseRequest)
    w.auth.deny("bob", ACTION_RELEASE_TENANT_HOLD)
    assert reason(w.ledger.confirm_release(BOB_SCOPE, hold.hold_id)) is OpsReason.NOT_AUTHORIZED
    assert w.audit_calls == []


@pytest.mark.parametrize("answer", [False, None, 1, "yes", RuntimeError("POISON-TEXT")])
def test_audit_failure_means_the_release_is_not_applied(w, answer):
    approval = w.approve()
    w.clock.t += timedelta(minutes=1)
    hold = w.ledger.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL)
    w.audit_answer = answer
    assert isinstance(w.ledger.request_release(A1, hold.hold_id, "bob"), ReleaseRequest)
    out = w.ledger.confirm_release(BOB_SCOPE, hold.hold_id)
    assert reason(out) is OpsReason.AUDIT_UNAVAILABLE and "POISON" not in repr(out)
    assert reason(w.decide(approval)) is OpsReason.HOLD_ACTIVE  # still held
    w.audit_answer = True  # a retry is possible because the failed claim was given back
    assert isinstance(w.ledger.confirm_release(BOB_SCOPE, hold.hold_id), HoldReleaseReceipt)


def test_no_audit_function_means_no_release():
    w = World(audit=False)
    hold = _hold(w)
    assert isinstance(w.ledger.request_release(A1, hold.hold_id, "bob"), ReleaseRequest)
    assert reason(w.ledger.confirm_release(BOB_SCOPE, hold.hold_id)) is OpsReason.AUDIT_UNAVAILABLE
    assert reason(w.ledger.confirm_release(BOB_SCOPE, "unknown")) is OpsReason.NOT_FOUND


def test_concurrent_confirmations_audit_and_apply_exactly_once(w):
    hold = _hold(w)
    assert isinstance(w.ledger.request_release(A1, hold.hold_id, "bob"), ReleaseRequest)
    results, gate = [], threading.Barrier(8)

    def work(_i):
        gate.wait()
        results.append(w.ledger.confirm_release(BOB_SCOPE, hold.hold_id))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(isinstance(r, HoldReleaseReceipt) for r in results) == 1
    assert len(w.audit_calls) == 1


def test_a_pending_release_counts_as_an_active_hold(w):
    approval = w.approve()
    w.clock.t += timedelta(minutes=1)
    hold = w.ledger.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL)
    seen = []

    def slow_audit(record):
        seen.append(reason(w.decide(approval)))
        return True

    w.ledger._audit = slow_audit
    assert isinstance(w.release(hold), HoldReleaseReceipt)
    assert seen == [OpsReason.HOLD_ACTIVE]


# ---- policies, registration, quotas ---------------------------------------------------------------

def test_policy_changes_need_authority_and_can_never_shorten_retention(w):
    assert reason(w.ledger.add_policy(A3, RetentionPolicy("x", 1, DAY))) is OpsReason.NOT_AUTHORIZED
    assert reason(w.ledger.add_policy(A1, RetentionPolicy("fin", 2, 10 * DAY))) is OpsReason.INPUT_INVALID
    assert reason(w.ledger.add_policy(A1, RetentionPolicy("fin", 1, 40 * DAY))) is OpsReason.DUPLICATE_SUPPRESSED
    assert isinstance(w.ledger.add_policy(A1, RetentionPolicy("fin", 3, 60 * DAY)), RetentionPolicy)
    approval = w.approve()
    w.clock.t = T0 + 50 * DAY  # 31..59 days: the longest recorded min_age applies
    assert reason(w.decide(approval)) is OpsReason.RETENTION_NOT_ELAPSED


def test_longest_ever_recorded_min_age_governs():
    w = World()
    assert isinstance(w.ledger.add_policy(A1, RetentionPolicy("fin", 2, 90 * DAY)), RetentionPolicy)
    approval = w.approve()
    assert reason(w.decide(approval)) is OpsReason.RETENTION_NOT_ELAPSED


def test_register_object_requires_ownership_a_known_class_and_a_usable_clock(w):
    assert reason(w.ledger.register_object(A1, "run_id", "RF", "S1", "fin")) is OpsReason.NOT_FOUND
    assert reason(w.ledger.register_object(A1, "run_id", "R9", "S1", "fin")) is OpsReason.NOT_FOUND
    w.ports.owner.add("t1", "c1", "run_id", "R9")
    assert reason(w.ledger.register_object(A1, "run_id", "R9", "S1", "no-such-class")) is OpsReason.NOT_FOUND
    assert reason(w.ledger.register_object(A1, "run_id", "R1", "S1", "fin")) is OpsReason.DUPLICATE_SUPPRESSED
    w.clock.t = "not a datetime"
    assert reason(w.ledger.register_object(A1, "run_id", "R9", "S1", "fin")) is OpsReason.DEPENDENCY_FAILED


def test_quotas_are_per_tenant_and_explicit():
    w = World(cap=2, per_company_hold_cap=2)
    assert isinstance(w.ledger.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL), Hold)
    assert isinstance(w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.LEGAL, None, "S1"), Hold)
    assert reason(w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.LEGAL, None, "S2")) is OpsReason.QUOTA_EXCEEDED
    assert isinstance(w.ledger.place_hold(A2, HoldLevel.TENANT, HoldReason.LEGAL), Hold)  # tenant B untouched
    assert isinstance(w.ledger.request_approval(A1, w.request(), "bob", w.clock.t + DAY), ApprovalRequest)


def test_approvals_are_bounded_per_tenant():
    w = World(cap=2)
    assert isinstance(w.approve(), DeletionApproval) and isinstance(w.approve(), DeletionApproval)
    assert reason(w.ledger.request_approval(A1, w.request(), "bob", w.clock.t + DAY)) is OpsReason.QUOTA_EXCEEDED


# ---- D3: the retention class of an object is not the caller's choice --------------------------------

def test_the_class_of_an_already_known_object_cannot_be_changed_or_lowered(w):
    assert isinstance(w.ledger.add_policy(A1, RetentionPolicy("short", 1, 10 * DAY)), RetentionPolicy)
    # R1 was registered as "fin" (30d): re-registering it under a shorter class is refused and changes nothing
    assert reason(w.ledger.register_object(A1, "run_id", "R1", "S1", "short")) is OpsReason.DUPLICATE_SUPPRESSED
    approval = w.approve()
    w.clock.t = T0 + 20 * DAY
    assert reason(w.decide(approval)) is OpsReason.RETENTION_NOT_ELAPSED  # still the 30 day class


def test_a_class_below_the_platform_floor_needs_the_platform_authority():
    w = World()
    assert isinstance(w.ledger.add_policy(A1, RetentionPolicy("instant", 1, timedelta(0))), RetentionPolicy)
    for oid in ("R7", "R8"):
        w.ports.owner.add("t1", "c1", "run_id", oid)
    assert reason(w.ledger.register_object(A3, "run_id", "R7", "S1", "instant")) is OpsReason.NOT_AUTHORIZED
    assert not isinstance(w.ledger.register_object(A1, "run_id", "R7", "S1", "instant"), OpsRefusal)  # a1 holds it
    assert not isinstance(w.ledger.register_object(A1, "run_id", "R8", "S1", "instant"), OpsRefusal)
    w.ports.owner.add("t1", "c1", "run_id", "R9")
    assert not isinstance(w.ledger.register_object(A3, "run_id", "R9", "S1", "fin"), OpsRefusal)  # 30d >= floor


def test_a_floor_is_configurable_and_a_failing_authority_port_is_a_dependency_failure():
    w = World(min_age_floor=60 * DAY)
    w.ports.owner.add("t1", "c1", "run_id", "R9")
    assert reason(w.ledger.register_object(A3, "run_id", "R9", "S1", "fin")) is OpsReason.NOT_AUTHORIZED  # 30d < 60d
    w.ledger._authority = object()  # no `authorized` method
    assert reason(w.ledger.register_object(A3, "run_id", "R9", "S1", "fin")) is OpsReason.DEPENDENCY_FAILED


# ---- D4: tenant-wide holds are platform-level and per-company quota --------------------------------

def test_a_tenant_hold_needs_the_platform_right(w):
    assert reason(w.ledger.place_hold(A3, HoldLevel.TENANT, HoldReason.LEGAL)) is OpsReason.NOT_AUTHORIZED
    assert reason(w.ledger.place_hold(B1, HoldLevel.TENANT, HoldReason.LEGAL)) is OpsReason.NOT_AUTHORIZED
    approval = w.approve()
    assert isinstance(w.decide(approval), DeletionDecision)  # nothing was placed
    assert isinstance(w.ledger.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL), Hold)
    # a company-scoped hold needs no platform right
    assert isinstance(w.ledger.place_hold(A3, HoldLevel.SOURCE, HoldReason.LEGAL, None, "S1"), Hold)


def test_one_company_cannot_exhaust_the_tenant_hold_quota():
    w = World(cap=4, per_company_hold_cap=2)
    for _ in range(2):
        assert isinstance(w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.AUDIT, None, "S1"), Hold)
    assert reason(w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.AUDIT, None, "S1")) is OpsReason.QUOTA_EXCEEDED
    assert isinstance(w.ledger.place_hold(B1, HoldLevel.SOURCE, HoldReason.AUDIT, None, "SB"), Hold)  # room is left
    assert isinstance(w.ledger.place_hold(B1, HoldLevel.OBJECT, HoldReason.AUDIT, "run_id", "RB"), Hold)
    assert reason(w.ledger.place_hold(B1, HoldLevel.SOURCE, HoldReason.AUDIT, None, "SB")) is OpsReason.QUOTA_EXCEEDED


def test_the_default_per_company_cap_is_below_the_tenant_cap():
    w = World(cap=4)
    placed = [w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.AUDIT, None, "S1") for _ in range(4)]
    assert sum(isinstance(h, Hold) for h in placed) == 2
    assert isinstance(w.ledger.place_hold(B1, HoldLevel.SOURCE, HoldReason.AUDIT, None, "SB"), Hold)


# ---- hostile input -------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, 5, "", "  ", "a\x00b", "x" * 300, EvilStr("e"), b"e", ["e"]])
def test_request_validation_has_a_fixed_code(bad):
    with pytest.raises(ValueError, match="DELETION_REQUEST_INVALID") as info:
        DeletionRequest("run_id", (bad,), "approval")
    assert "xxxx" not in str(info.value)
    with pytest.raises(ValueError, match="DELETION_REQUEST_INVALID"):
        DeletionRequest("run_id", ("R1",), bad)  # type: ignore[arg-type]


def test_request_shape_rules():
    for kind, ids in (("bogus", ("R1",)), ("run_id", ()), ("run_id", ["R1"]), ("run_id", ("R1", "R1")),
                      ("run_id", tuple(f"R{i}" for i in range(65))), (EvilStr("run_id"), ("R1",))):
        with pytest.raises(ValueError, match="DELETION_REQUEST_INVALID"):
            DeletionRequest(kind, ids, "a")  # type: ignore[arg-type]


def test_policy_validation():
    for args in (("", 1, DAY), ("a@b", 1, DAY), ("a", 0, DAY), ("a", True, DAY), ("a", 1, -DAY), ("a", 1, 5),
                 ("a", 1, timedelta(days=40_000)), (EvilStr("a"), 1, DAY), ("a", 10**7, DAY)):
        with pytest.raises(ValueError, match="RETENTION_POLICY_INVALID"):
            RetentionPolicy(*args)  # type: ignore[arg-type]


def test_hostile_calls_never_raise_and_never_echo(w):
    junk = (None, 0, "", object(), [], {}, (), EvilStr("x"), float("nan"), b"x")
    for a in junk:
        for b in junk:
            for out in (decide_deletion(a, b, w.ledger), decide_deletion(A1, b, a), w.ledger.add_policy(a, b),
                        w.ledger.register_object(a, b, a, b, a), w.ledger.place_hold(a, b, a, b, a),
                        w.ledger.request_release(a, b, a), w.ledger.confirm_release(a, b),
                        w.ledger.request_approval(a, b, a, b), w.ledger.confirm_approval(a, b)):
                assert isinstance(out, OpsRefusal)
    forged = object.__new__(DeletionRequest)
    assert isinstance(decide_deletion(A1, forged, w.ledger), OpsRefusal)
    assert isinstance(decide_deletion(object.__new__(OpsScope), w.request(), w.ledger), OpsRefusal)


def test_hold_arguments_are_checked_per_level(w):
    for args in ((HoldLevel.OBJECT, HoldReason.LEGAL, None, "R1"), (HoldLevel.OBJECT, HoldReason.LEGAL, "bogus", "R1"),
                 (HoldLevel.SOURCE, HoldReason.LEGAL, "run_id", "S1"), (HoldLevel.TENANT, HoldReason.LEGAL, None, "S1"),
                 ("OBJECT", HoldReason.LEGAL, "run_id", "R1"), (HoldLevel.TENANT, "LEGAL", None, None),
                 (HoldLevel.SOURCE, HoldReason.LEGAL, None, EvilStr("S1"))):
        assert reason(w.ledger.place_hold(A1, *args)) is OpsReason.INPUT_INVALID
    assert reason(w.ledger.place_hold(A1, HoldLevel.SOURCE, HoldReason.LEGAL, None, "SF")) is OpsReason.NOT_FOUND


def test_ledger_ports_that_raise_are_dependency_failures():
    class Raising:
        def entitled(self, *a):
            raise RuntimeError("POISON")

        owns = entitled

        def authorized(self, *a):
            raise RuntimeError("POISON")

    w = World()
    bad = RetentionLedger(FakeCorrelationSource(), w.ports, w.ports, Raising(), w.clock, w._audit)
    out = bad.add_policy(A1, RetentionPolicy("x", 1, DAY))
    assert reason(out) is OpsReason.DEPENDENCY_FAILED
    bad2 = RetentionLedger(FakeCorrelationSource(), Raising(), Raising(), w.auth, w.clock)
    out = bad2.place_hold(A1, HoldLevel.TENANT, HoldReason.LEGAL)
    assert reason(out) is OpsReason.DEPENDENCY_FAILED and "POISON" not in repr(out)
    with pytest.raises(ValueError, match="RETENTION_LEDGER_INVALID"):
        RetentionLedger(w.ids, w.ports, w.ports, w.auth, None)


def test_a_failing_clock_is_a_dependency_failure_not_a_decision(w):
    approval = w.approve()

    def boom():
        raise RuntimeError("POISON")

    w.ledger._clock = boom
    out = w.decide(approval)
    assert reason(out) is OpsReason.DEPENDENCY_FAILED and "POISON" not in repr(out)


def test_decide_deletion_function_requires_a_real_ledger(w):
    assert reason(decide_deletion(A1, w.request(), object())) is OpsReason.INPUT_INVALID


def test_stored_records_and_ledger_are_redacted(w):
    hold = _hold(w)
    approval = w.approve()
    for obj in (hold, approval, w.ledger, RetentionPolicy("secret-class", 1, DAY)):
        assert "S1" not in repr(obj) and "bob" not in repr(obj) and "secret-class" not in repr(obj)


# ---- no delete anywhere ---------------------------------------------------------------------------

_FORBIDDEN = {"httpx", "requests", "socket", "subprocess", "os", "pathlib", "random", "secrets", "time", "shutil",
              "threading", "sqlite3", "psycopg", "psycopg2", "asyncpg", "urllib", "http", "ctypes", "io"}
_DELETE_WORDS = ("delete", "remove", "unlink", "rmtree", "rmdir", "truncate", "drop")


def test_ast_no_delete_call_no_executed_true_and_only_allowed_imports():
    path = _SRC / "retention_hold.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert not any(w in called.lower() for w in _DELETE_WORDS), called
            for kw in node.keywords:
                assert not (kw.arg == "executed" and isinstance(kw.value, ast.Constant) and kw.value.value is True)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not any(w in node.name.lower() for w in _DELETE_WORDS), node.name
            if node.name == "executed":
                returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
                assert len(returns) == 1 and isinstance(returns[0].value, ast.Constant) \
                    and returns[0].value.value is False
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                name = getattr(t, "id", getattr(t, "attr", ""))
                assert not (name == "executed" and isinstance(node.value, ast.Constant) and node.value.value is True)
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [("." * node.level) + (node.module or "")]
        for name in names:
            low = name.lower()
            assert name.lstrip(".").split(".")[0] not in _FORBIDDEN, name
            assert "release1" not in low and "release_1" not in low and "pdcc" not in low, name
            assert not name.startswith(".."), name
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not any(
                getattr(t, "id", "") == "__all__" for t in getattr(node, "targets", [])):
            assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp))
    text = path.read_text(encoding="utf-8")
    assert "open(" not in text and "executed=True" not in text.replace(" ", "")
