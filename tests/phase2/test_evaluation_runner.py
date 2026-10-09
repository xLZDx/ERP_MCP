"""R2-US-029 / TC085-087: evaluation runner (permit + registered runner + scope).

Claim covered for the mode flag: runner output is LABELLED non-promotable (mode EVALUATION_ONLY,
promotable False). These tests do not prove that downstream code refuses to promote it.
"""
from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from business_ai_gateway.phase2 import evaluation_runner as er
from business_ai_gateway.phase2.capture_permit import (
    CaptureMode,
    Environment,
    Issuer,
    IssuerKind,
    IssueStatus,
    PermitRequest,
    PermitStore,
)
from business_ai_gateway.phase2.evaluation_runner import (
    EvaluationRequest,
    EvaluationResult,
    EvaluationRunner,
    EvaluationStatus,
)
from business_ai_gateway.phase2.reconciliation import (
    BalanceSix,
    Comparison,
    ComparisonState,
    LedgerRow,
    LedgerScope,
    LedgerStatement,
)

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64
OWNER = Issuer(IssuerKind.HUMAN, "owner")
FIXED_CODES = {"COMPUTED", "INVALID_INPUT", "RUNNER_NOT_REGISTERED", "SCOPE_MISMATCH",
               "PERMIT_DENIED", "COMPUTE_FAILED"}


def _six(x: str) -> BalanceSix:
    d = Decimal(x)
    return BalanceSix(d, d, d, d, d, d)


def _statement(tenant: str = "t1", source: str = "s1", amount: str = "10",
               snapshot: str = "snap-1", rows: tuple[tuple[str, str, str], ...] | None = None,
               ) -> LedgerStatement:
    scope = LedgerScope(tenant, source, "co", "60", T0, T0 + timedelta(days=30), "RUB", "UTC", ("cp",))
    spec = rows if rows is not None else (("cpA", "k1", amount),)
    lrows = tuple(LedgerRow(cp, k, _six(v)) for cp, k, v in spec)
    total = sum((Decimal(v) for _, _, v in spec), Decimal(0))
    return LedgerStatement(scope, snapshot, _six(str(total)), lrows, True, "rev-1")


class _Env:
    def __init__(self, *, max_uses: int | None = None, mode: CaptureMode = CaptureMode.READ_SNAPSHOT,
                 tenant: str = "t1", source: str = "s1", compare: object = None) -> None:
        owners = {("t1", "s1"): frozenset({"owner"}), ("t2", "s2"): frozenset({"owner"})}
        self.now = T0
        self.store = PermitStore(lambda: self.now, owners=owners)
        self.runner = EvaluationRunner(self.store, {("t1", "s1"): frozenset({"runner-1"})},
                                       compare=compare)  # type: ignore[arg-type]
        self.permit_id = self.issue(tenant, source, mode, max_uses)

    def issue(self, tenant: str, source: str, mode: CaptureMode = CaptureMode.READ_SNAPSHOT,
              max_uses: int | None = None, digest: str = DIGEST, key: str | None = None) -> str:
        req = PermitRequest(tenant, source, mode, Environment.NON_PROD, T0 - timedelta(hours=1),
                            T0 + timedelta(hours=1), digest, "analyst", max_uses)
        res = self.store.issue(key or f"k-{tenant}-{source}-{mode}-{digest[:4]}-{max_uses}", req, OWNER)
        assert res.status is IssueStatus.ISSUED and res.permit is not None
        return res.permit.permit_id

    def request(self, **over: object) -> EvaluationRequest:
        base: dict[str, object] = {
            "permit_id": self.permit_id, "tenant_id": "t1", "source_id": "s1",
            "runner_id": "runner-1", "params_digest": DIGEST, "requester": "analyst",
            "native": _statement(), "gateway": _statement(),
        }
        base.update(over)
        return EvaluationRequest(**base)  # type: ignore[arg-type]

    def admits(self) -> int:
        return sum(1 for e in self.store.audit() if e.kind == "ADMIT" and e.value == "ADMITTED")


class _Spy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, native: LedgerStatement, gateway: LedgerStatement) -> Comparison:
        self.calls += 1
        return Comparison(ComparisonState.MATCH, "SPY", "p", ())


def _assert_denied(res: EvaluationResult, code: str) -> None:
    assert res.status is EvaluationStatus.DENIED
    assert res.code == code
    assert res.comparison is None and res.result_digest is None
    assert res.mode == "EVALUATION_ONLY" and res.promotable is False


# ---- TC085: scoped permit ---------------------------------------------------------------------

def test_valid_request_computes_and_output_is_labelled_non_promotable() -> None:
    env = _Env()
    res = env.runner.run(env.request())
    assert res.status is EvaluationStatus.COMPUTED and res.code == "COMPUTED"
    assert res.comparison is not None and res.comparison.state is ComparisonState.MATCH
    assert res.mode == "EVALUATION_ONLY" and res.promotable is False
    assert res.result_digest is not None and len(res.result_digest) == 64
    assert env.admits() == 1
    with pytest.raises((AttributeError, TypeError)):
        res.promotable = True  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        res.mode = "ACCEPTED"  # type: ignore[misc]


def test_mismatch_and_inconclusive_results_are_also_labelled_non_promotable() -> None:
    env = _Env()
    mism = env.runner.run(env.request(gateway=_statement(amount="11")))
    assert mism.comparison is not None and mism.comparison.state is ComparisonState.MISMATCH
    assert mism.mode == "EVALUATION_ONLY" and mism.promotable is False
    incon = env.runner.run(env.request(gateway=_statement(snapshot="other")))
    assert incon.comparison is not None and incon.comparison.state is ComparisonState.INCONCLUSIVE
    assert incon.mode == "EVALUATION_ONLY" and incon.promotable is False


def test_out_of_scope_permit_is_denied_and_compare_not_called() -> None:
    spy = _Spy()
    env = _Env(tenant="t2", source="s2", compare=spy)  # a real permit, but for another scope
    res = env.runner.run(env.request())
    _assert_denied(res, "PERMIT_DENIED")
    assert spy.calls == 0


def test_unknown_permit_id_is_denied() -> None:
    spy = _Spy()
    env = _Env(compare=spy)
    _assert_denied(env.runner.run(env.request(permit_id="nope")), "PERMIT_DENIED")
    assert spy.calls == 0


def test_wrong_mode_permit_is_denied_and_compare_not_called() -> None:
    spy = _Spy()
    env = _Env(mode=CaptureMode.READ_INCREMENTAL, compare=spy)
    _assert_denied(env.runner.run(env.request()), "PERMIT_DENIED")
    assert spy.calls == 0


@pytest.mark.parametrize("over", [{"params_digest": "b" * 64}, {"requester": "someone-else"}])
def test_params_or_requester_mismatch_is_denied(over: dict[str, str]) -> None:
    spy = _Spy()
    env = _Env(compare=spy)
    _assert_denied(env.runner.run(env.request(**over)), "PERMIT_DENIED")
    assert spy.calls == 0


def test_exhausted_permit_is_denied_on_second_run() -> None:
    env = _Env(max_uses=1)
    assert env.runner.run(env.request()).status is EvaluationStatus.COMPUTED
    _assert_denied(env.runner.run(env.request()), "PERMIT_DENIED")


def test_expired_permit_is_denied_and_compare_not_called() -> None:
    spy = _Spy()
    env = _Env(compare=spy)
    env.now = T0 + timedelta(hours=2)  # past the permit window (T0 + 1h)
    _assert_denied(env.runner.run(env.request()), "PERMIT_DENIED")
    assert spy.calls == 0 and env.admits() == 0


def test_revoked_permit_is_denied_and_compare_not_called() -> None:
    spy = _Spy()
    env = _Env(compare=spy)
    assert env.runner.run(env.request()).status is EvaluationStatus.COMPUTED
    assert env.store.revoke(env.permit_id, "t1", OWNER).revoked
    _assert_denied(env.runner.run(env.request()), "PERMIT_DENIED")
    assert spy.calls == 1  # only the pre-revocation run computed


def test_all_permit_denials_share_one_code() -> None:
    env = _Env()
    other = _Env(mode=CaptureMode.READ_INCREMENTAL)
    expired = _Env()
    expired.now = T0 + timedelta(hours=2)
    revoked = _Env()
    assert revoked.store.revoke(revoked.permit_id, "t1", OWNER).revoked
    codes = {
        expired.runner.run(expired.request()).code,
        revoked.runner.run(revoked.request()).code,
        env.runner.run(env.request(permit_id="nope")).code,
        env.runner.run(env.request(params_digest="c" * 64)).code,
        other.runner.run(other.request()).code,
    }
    assert codes == {"PERMIT_DENIED"}


# ---- TC086: registered runner ------------------------------------------------------------------

def test_unregistered_runner_is_denied_and_nothing_computed_or_burned() -> None:
    spy = _Spy()
    env = _Env(max_uses=1, compare=spy)
    _assert_denied(env.runner.run(env.request(runner_id="intruder")), "RUNNER_NOT_REGISTERED")
    assert spy.calls == 0
    assert env.admits() == 0
    assert not any(e.kind == "ADMIT" for e in env.store.audit())  # permit store not even consulted
    # the single permit use is still available to the registered runner
    assert env.runner.run(env.request()).status is EvaluationStatus.COMPUTED


def test_default_registry_is_empty_so_everything_is_denied() -> None:
    env = _Env()
    spy = _Spy()
    runner = EvaluationRunner(env.store, compare=spy)
    _assert_denied(runner.run(env.request()), "RUNNER_NOT_REGISTERED")
    assert spy.calls == 0


def test_runner_registered_for_another_scope_is_denied() -> None:
    env = _Env()
    runner = EvaluationRunner(env.store, {("t2", "s2"): frozenset({"runner-1"})})
    _assert_denied(runner.run(env.request()), "RUNNER_NOT_REGISTERED")


def test_runner_id_is_normalised_like_identities() -> None:
    env = _Env()
    assert env.runner.run(env.request(runner_id="  RUNNER-1 ")).status is EvaluationStatus.COMPUTED


def test_runner_id_with_invisible_char_is_not_registered() -> None:
    env = _Env()
    res = env.runner.run(env.request(runner_id="runner" + chr(0x200B) + "-1"))
    assert res.status is EvaluationStatus.DENIED and res.code == "INVALID_INPUT"


# ---- scope check before permit burn ------------------------------------------------------------

@pytest.mark.parametrize("which", ["native", "gateway"])
@pytest.mark.parametrize("scope", [("t2", "s1"), ("t1", "s2")])
def test_statement_scope_mismatch_denied_before_permit_is_burned(which: str,
                                                                 scope: tuple[str, str]) -> None:
    spy = _Spy()
    env = _Env(max_uses=1, compare=spy)
    bad = _statement(tenant=scope[0], source=scope[1])
    _assert_denied(env.runner.run(env.request(**{which: bad})), "SCOPE_MISMATCH")
    assert spy.calls == 0
    assert not any(e.kind == "ADMIT" for e in env.store.audit())
    # permit use survived: a correct request still succeeds with max_uses=1
    assert env.runner.run(env.request()).status is EvaluationStatus.COMPUTED
    assert env.admits() == 1


def test_scope_match_is_normalised() -> None:
    env = _Env()
    res = env.runner.run(env.request(native=_statement(tenant="T1"), gateway=_statement(tenant="T1")))
    # same normalised (tenant, source); the comparator itself may still judge the scopes
    assert res.status is EvaluationStatus.COMPUTED


# ---- TC087: canonical replay -------------------------------------------------------------------

def test_replay_gives_identical_digest_across_permits_and_runners() -> None:
    env = _Env()
    first = env.runner.run(env.request())
    second = env.runner.run(env.request())
    other_permit = env.issue("t1", "s1", key="another-key")
    third = env.runner.run(env.request(permit_id=other_permit))
    fresh = _Env()
    fourth = fresh.runner.run(fresh.request())
    digests = {first.result_digest, second.result_digest, third.result_digest, fourth.result_digest}
    assert len(digests) == 1 and None not in digests


def test_digest_is_canonical_for_row_order_and_decimal_scale() -> None:
    env = _Env()
    rows = (("cpA", "k1", "10"), ("cpB", "k2", "5"))
    ordered = _statement(rows=rows)
    reversed_ = _statement(rows=tuple(reversed(rows)))
    scaled = _statement(rows=(("cpA", "k1", "10.00"), ("cpB", "k2", "5.0")))
    base = env.runner.run(env.request(native=ordered, gateway=ordered)).result_digest
    assert base is not None
    assert env.runner.run(env.request(native=reversed_, gateway=reversed_)).result_digest == base
    assert env.runner.run(env.request(native=scaled, gateway=scaled)).result_digest == base


def test_changed_input_changes_digest() -> None:
    env = _Env()
    base = env.runner.run(env.request()).result_digest
    changed = {
        "gateway amount": env.request(gateway=_statement(amount="11")),
        "native amount": env.request(native=_statement(amount="12")),
        "both snapshot": env.request(native=_statement(snapshot="s2"), gateway=_statement(snapshot="s2")),
        "extra row": env.request(native=_statement(rows=(("cpA", "k1", "10"), ("cpB", "k2", "1"))),
                                 gateway=_statement(rows=(("cpA", "k1", "10"), ("cpB", "k2", "1")))),
    }
    seen = {base}
    for name, req in changed.items():
        digest = env.runner.run(req).result_digest
        assert digest is not None and digest not in seen, name
        seen.add(digest)


def test_changed_params_digest_changes_result_digest() -> None:
    env = _Env()
    base = env.runner.run(env.request()).result_digest
    other_digest = "d" * 64
    pid = env.issue("t1", "s1", digest=other_digest)
    changed = env.runner.run(env.request(permit_id=pid, params_digest=other_digest)).result_digest
    assert changed is not None and changed != base


def test_changed_policy_changes_digest_for_tolerated_difference() -> None:
    env = _Env()
    loose = EvaluationRunner(env.store, {("t1", "s1"): frozenset({"runner-1"})},
                             policy=er.TolerancePolicy("TOL", Decimal(5)))
    req = env.request(gateway=_statement(amount="12"))
    strict_res = env.runner.run(req)
    loose_res = loose.run(req)
    assert strict_res.comparison is not None and strict_res.comparison.state is ComparisonState.MISMATCH
    assert loose_res.comparison is not None and loose_res.comparison.state is ComparisonState.MATCH
    assert strict_res.result_digest != loose_res.result_digest


# ---- compute-stage hardening -------------------------------------------------------------------

def test_compare_raising_is_masked() -> None:
    def boom(n: LedgerStatement, g: LedgerStatement) -> Comparison:
        raise RuntimeError("SECRET-TEXT-123")

    env = _Env(compare=boom)
    res = env.runner.run(env.request())
    _assert_denied(res, "COMPUTE_FAILED")
    assert "SECRET" not in repr(res)


def test_compare_returning_wrong_type_or_foreign_authority_is_rejected() -> None:
    env = _Env(compare=lambda n, g: "MATCH")
    _assert_denied(env.runner.run(env.request()), "COMPUTE_FAILED")
    promoted = Comparison(ComparisonState.MATCH, "X", "p", (), authority="PROMOTED")
    env2 = _Env(compare=lambda n, g: promoted)
    _assert_denied(env2.runner.run(env2.request()), "COMPUTE_FAILED")


def test_constructor_comparator_runs_only_after_all_checks() -> None:
    spy = _Spy()
    env = _Env(compare=spy)
    res = env.runner.run(env.request())
    assert spy.calls == 1 and res.status is EvaluationStatus.COMPUTED


def test_forged_comparison_cannot_be_injected_through_run() -> None:
    env = _Env()
    assert list(inspect.signature(EvaluationRunner.run).parameters) == ["self", "request"]
    forged = Comparison(ComparisonState.MATCH, "FORGED", "p", ())
    with pytest.raises(TypeError):
        env.runner.run(env.request(), lambda n, g: forged)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        env.runner.run(env.request(), compare=lambda n, g: forged)  # type: ignore[call-arg]
    # the default comparator decides: a real mismatch stays a mismatch
    res = env.runner.run(env.request(gateway=_statement(amount="11")))
    assert res.comparison is not None and res.comparison.state is ComparisonState.MISMATCH
    assert res.comparison.reason_code != "FORGED"


# ---- no public bypass (__all__ audit) ----------------------------------------------------------

def test_all_audit_and_no_public_unchecked_compare() -> None:
    assert sorted(er.__all__) == ["EvaluationRequest", "EvaluationResult", "EvaluationRunner",
                                  "EvaluationStatus"]
    for name in er.__all__:
        assert hasattr(er, name)
    public_funcs = [n for n, o in vars(er).items()
                    if not n.startswith("_") and inspect.isfunction(o) and o.__module__ == er.__name__]
    assert public_funcs == []
    public_methods = {n for n, o in vars(EvaluationRunner).items()
                      if not n.startswith("_") and callable(o)}
    assert public_methods == {"run"}
    assert "compare_statements" not in er.__all__


def test_unchecked_compare_is_not_reachable_via_public_attributes() -> None:
    env = _Env()
    assert not [n for n in dir(env.runner) if not n.startswith("_") and n != "run"]
    assert [n for n in dir(EvaluationResult) if not n.startswith("_")
            and n not in {"status", "code", "comparison", "mode", "result_digest", "promotable"}] == []


# ---- wrong types never raise; no echo ----------------------------------------------------------

@pytest.mark.parametrize("junk", [None, 1, "x", b"x", [], {}, object(), 1.5, ("a",)])
def test_non_request_values_never_raise(junk: object) -> None:
    env = _Env()
    res = env.runner.run(junk)  # type: ignore[arg-type]
    _assert_denied(res, "INVALID_INPUT")


@pytest.mark.parametrize("field", ["permit_id", "tenant_id", "source_id", "runner_id",
                                   "params_digest", "requester", "native", "gateway"])
@pytest.mark.parametrize("junk", [None, 7, b"b", object(), ["x"]])
def test_wrong_field_types_never_raise(field: str, junk: object) -> None:
    spy = _Spy()
    env = _Env(compare=spy)
    res = env.runner.run(env.request(**{field: junk}))
    _assert_denied(res, "INVALID_INPUT")
    assert spy.calls == 0


def test_blank_identity_fields_are_invalid_input() -> None:
    env = _Env()
    for field in ("tenant_id", "source_id", "runner_id"):
        _assert_denied(env.runner.run(env.request(**{field: "   "})), "INVALID_INPUT")


def test_request_subclass_and_uninitialised_instance_never_raise() -> None:
    env = _Env()

    class Sub(EvaluationRequest):  # slots dataclass subclass: not the exact type
        pass

    sub = Sub(**{f: getattr(env.request(), f) for f in EvaluationRequest.__dataclass_fields__})
    _assert_denied(env.runner.run(sub), "INVALID_INPUT")
    empty = object.__new__(EvaluationRequest)
    _assert_denied(env.runner.run(empty), "INVALID_INPUT")


def test_non_callable_constructor_comparator_is_rejected() -> None:
    store = PermitStore(lambda: T0)
    with pytest.raises(TypeError):
        EvaluationRunner(store, compare="nope")  # type: ignore[arg-type]


def test_hostile_statement_scope_fails_closed_without_permit_use() -> None:
    env = _Env(max_uses=1)
    bad = _statement()
    object.__setattr__(bad, "scope", None)  # frozen+slots dataclass bypass
    _assert_denied(env.runner.run(env.request(native=bad)), "SCOPE_MISMATCH")
    assert env.admits() == 0


def test_no_caller_input_is_echoed_in_any_code_or_result() -> None:
    env = _Env()
    marker = "ZZ-MARKER-9"
    cases = [
        env.request(runner_id=marker),
        env.request(permit_id=marker),
        env.request(tenant_id=marker),
        env.request(params_digest=marker),
        env.request(requester=marker),
        env.request(native=_statement(tenant=marker)),
        env.request(gateway=_statement(source=marker)),
        env.request(source_id=marker),
    ]
    for req in cases:
        res = env.runner.run(req)
        assert res.code in FIXED_CODES
        assert marker.lower() not in repr(res).lower()
    # audit of the permit store carries only fixed codes/normalised ids, never raw statement data
    assert all(e.value in {"ADMITTED", "PERMIT_NOT_ADMITTABLE", "PARAMS_MISMATCH",
                           "REQUESTER_MISMATCH", "ISSUED"} for e in env.store.audit())


def test_denied_result_dataclass_cannot_carry_a_digest_or_comparison_by_default() -> None:
    res = replace(EvaluationResult(EvaluationStatus.DENIED, "X"))
    assert res.comparison is None and res.result_digest is None and res.promotable is False


# ---- constructor -------------------------------------------------------------------------------

def test_constructor_validation() -> None:
    store = PermitStore(lambda: T0)
    with pytest.raises(TypeError):
        EvaluationRunner(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        EvaluationRunner(store, policy="x")  # type: ignore[arg-type]
    for bad in ({("t", "s"): "runner-1"}, {("t",): frozenset({"r"})}, {("", "s"): frozenset({"r"})},
                {"ts": frozenset({"r"})}, {("t", "s"): [1]}):
        with pytest.raises(ValueError):
            EvaluationRunner(store, bad)  # type: ignore[arg-type]


def test_registry_is_copied_at_construction() -> None:
    env = _Env()
    reg: dict[tuple[str, str], frozenset[str]] = {("t1", "s1"): frozenset({"runner-1"})}
    runner = EvaluationRunner(env.store, reg)
    reg[("t1", "s1")] = frozenset({"intruder"})
    _assert_denied(runner.run(env.request(runner_id="intruder")), "RUNNER_NOT_REGISTERED")
    assert runner.run(env.request()).status is EvaluationStatus.COMPUTED
