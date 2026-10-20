"""S9 E1 shared ops types: closed reason set, refusals, scope, check order, bounded map, import boundary."""
import ast
import dataclasses
import threading
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import ops_types as ot
from business_ai_gateway.phase2.ops_types import (
    AUTHORITY,
    OPS_NEXT_ACTION,
    Basis,
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOperatorAuthority,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
    TenantBoundedMap,
    check_scope_order,
    is_aware_datetime,
    is_digest,
    is_exact_decimal,
    is_exact_int,
    is_exact_str,
    is_valid_refusal,
    is_valid_scope,
    next_action_for,
    ops_refusal,
)
from business_ai_gateway.phase2.workbench_types import NextAction

_SRC = Path(__file__).resolve().parents[2] / "src" / "business_ai_gateway" / "phase2"


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class EvilInt(int):
    def __eq__(self, other):
        return True

    __hash__ = int.__hash__


class EvilDecimal(Decimal):
    pass


class EvilDatetime(datetime):
    pass


HOSTILE_TEXT = [None, 5, b"t1", EvilStr("t1"), "", "   ", "t\x001", "t\u200b1", "x" * 10_000, ["t1"], object()]


# ---- closed vocabulary ---------------------------------------------------------------------------

PLAN_CODES = ["INPUT_INVALID", "NOT_FOUND", "NOT_ENTITLED", "NOT_AUTHORIZED", "QUOTA_EXCEEDED", "DEPENDENCY_FAILED", "INTERNAL_REFUSED", "HIDDEN_BY_SCOPE", "BASIS_NOT_REAL_MEASUREMENT", "SESSIONS_NOT_ACTIVE_CLIENTS", "GRID_CELL_INCONSISTENT", "BACKEND_COUNT_MISSING", "CONFIG_LIMIT_NOT_CAPACITY", "REFUSALS_DOMINATE", "UNRELIABLE_REFUSALS", "INSUFFICIENT_SAMPLES", "BASELINE_INVALID", "WITHIN_TARGET", "EXCEEDS_TARGET", "BACKGROUND_STARVED", "BACKEND_BUDGET_EXCEEDED", "TENANT_SHARE_EXCEEDED", "AUDIT_UNAVAILABLE", "AUDIT_COMPLETION_PENDING", "EFFECT_FAILED", "RATE_LIMITED", "NETWORK_FAILURE", "EVENT_DIGEST_CONFLICT", "DUPLICATE_SUPPRESSED", "STALE_CLAIM", "DELIVERY_FAILED_FINAL", "ALERT_FIRED", "ALERT_RECOVERED", "NO_DATA", "ALERT_DELIVERY_FAILED", "ADDITIVE", "SWITCH_ONLY", "CONTRACT", "DESTRUCTIVE", "UNCLASSIFIED", "R1_UNCHANGED", "R1_REGRESSION", "SHADOW_DIVERGENCE", "SHADOW_INCOMPLETE", "REHEARSAL_REQUIRES_UNMET", "ROLLBACK_DESTRUCTIVE_DENIED", "ROLLBACK_HEAD_INCOMPATIBLE", "ROLLBACK_WINDOW_OPEN", "CONTRACT_NOT_ALLOWED", "RESURRECTION_BLOCKED", "RESTORE_COUNT_MISMATCH", "RESTORE_DIGEST_MISMATCH", "RESTORE_FK_ORPHAN", "RESTORE_HEAD_MISMATCH", "RESTORE_SEQUENCE_GAP", "RESTORE_ATTESTATION_STALE", "RESTORE_SCOPE_FOREIGN", "RESTORE_INCOMPLETE", "COLUMN_UNCLASSIFIED", "CELL_NEUTRALIZED", "VALUE_DENIED", "EXPORT_LIMIT_EXCEEDED", "HOLD_ACTIVE", "RETENTION_NOT_ELAPSED", "APPROVAL_MISSING", "APPROVAL_EXPIRED", "APPROVAL_DIGEST_MISMATCH", "SELF_APPROVAL", "OBJECT_NOT_OWNED", "DELETION_ALLOWED_PLAN", "NOT_RUN", "EVIDENCE_RECEIVED_UNVERIFIED"]


def test_reason_set_equals_the_plan_set_exactly():
    assert len(PLAN_CODES) == len(set(PLAN_CODES))
    assert {r.value for r in OpsReason} == set(PLAN_CODES)
    assert all(r.name == r.value for r in OpsReason)


def test_every_code_has_a_fixed_next_action_of_the_s8_enum():
    assert set(OPS_NEXT_ACTION) == set(OpsReason)
    assert all(type(a) is NextAction for a in OPS_NEXT_ACTION.values())
    with pytest.raises(TypeError):
        OPS_NEXT_ACTION[OpsReason.NOT_FOUND] = NextAction.RETRY_LATER  # type: ignore[index]


def test_import_guard_source_raises_when_a_code_lacks_a_next_action():
    src = (_SRC / "ops_types.py").read_text(encoding="utf-8")
    assert "if set(OPS_NEXT_ACTION) != set(OpsReason)" in src
    assert 'raise RuntimeError("OPS_NEXT_ACTION_INCOMPLETE")' in src


def test_next_action_for_hostile_input_is_no_action():
    for junk in (None, "NOT_FOUND", EvilStr("NOT_FOUND"), 5, object()):
        assert next_action_for(junk) is NextAction.NO_ACTION
    assert next_action_for(OpsReason.QUOTA_EXCEEDED) is NextAction.RETRY_LATER


def test_authority_and_basis_have_no_proven_member():
    assert AUTHORITY == "EVALUATION_ONLY"
    assert {b.value for b in Basis} == {"SCRIPTED_OFFLINE_FIXTURE", "OPERATOR_REFERENCE"}
    assert not [r for r in OpsReason if "PROVEN" in r.value or r.value in ("PASSED", "G6_PRE_PASSED")]


# ---- exact-type helpers --------------------------------------------------------------------------

def test_is_exact_str():
    assert is_exact_str("ab")
    for bad in (None, 5, b"x", EvilStr("x"), "", "a\x00b", "x" * 257, ["a"]):
        assert not is_exact_str(bad)
    assert is_exact_str("", allow_empty=True)
    assert is_exact_str("x" * 300, max_len=300)


def test_is_exact_int_excludes_bool_subclasses_floats_and_out_of_range():
    assert is_exact_int(0) and is_exact_int(5, 1, 5)
    for bad in (True, False, EvilInt(3), 1.0, "1", None, Decimal(1), 2**80, -(2**80)):
        assert not is_exact_int(bad)
    assert not is_exact_int(6, 1, 5) and not is_exact_int(0, 1, 5)


def test_is_exact_decimal_finite_only_and_no_subclass():
    assert is_exact_decimal(Decimal("1.5")) and is_exact_decimal(Decimal(0))
    for bad in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity"), EvilDecimal("1"),
                1.5, 1, "1", None, Decimal("1E+500"), Decimal("1E-500")):
        assert not is_exact_decimal(bad)


def test_is_aware_datetime():
    assert is_aware_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    assert is_aware_datetime(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3))))
    assert not is_aware_datetime(datetime(2026, 1, 1))  # noqa: DTZ001 - naive on purpose
    assert not is_aware_datetime(EvilDatetime(2026, 1, 1, tzinfo=UTC))
    for bad in (None, "2026-01-01", 5, object()):
        assert not is_aware_datetime(bad)


def test_is_digest():
    assert is_digest("a" * 64) and is_digest("0123456789abcdef" * 4)
    for bad in ("A" * 64, "a" * 63, "a" * 65, EvilStr("a" * 64), None, 5, "g" * 64, "a" * 64 + "\n"):
        assert not is_digest(bad)


# ---- refusals ------------------------------------------------------------------------------------

def test_ops_refusal_builds_from_source_and_never_from_input():
    ids = FakeCorrelationSource()
    first, second = ops_refusal(OpsReason.NOT_FOUND, ids), ops_refusal(OpsReason.NOT_FOUND, ids)
    assert (first.reason, first.next_action, first.authority) == (OpsReason.NOT_FOUND, NextAction.NO_ACTION, AUTHORITY)
    assert first.correlation_id == "CORR-000001" and second.correlation_id == "CORR-000002"
    assert is_valid_refusal(first)


@pytest.mark.parametrize("bad", [None, "NOT_FOUND", EvilStr("NOT_FOUND"), 5, object(), b"x"])
def test_ops_refusal_non_reason_degrades_to_input_invalid(bad):
    refusal = ops_refusal(bad, FakeCorrelationSource())
    assert refusal.reason is OpsReason.INPUT_INVALID


class _BadSource:
    def __init__(self, value):
        self._value = value

    def next_id(self):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


@pytest.mark.parametrize("source", [None, object(), _BadSource(RuntimeError("POISON")), _BadSource(None),
                                    _BadSource("has space"), _BadSource(EvilStr("CORR-1")), _BadSource("x" * 100)])
def test_ops_refusal_hostile_source_degrades_to_default_id(source):
    refusal = ops_refusal(OpsReason.QUOTA_EXCEEDED, source)
    assert refusal.correlation_id == "CORR-UNASSIGNED"
    assert "POISON" not in repr(refusal)


def test_forged_and_malformed_refusals_are_invalid():
    assert not is_valid_refusal(object.__new__(OpsRefusal))
    for junk in (None, 1, "x", object(), {"reason": "NOT_FOUND"}):
        assert not is_valid_refusal(junk)
    with pytest.raises(ValueError, match="OPS_REFUSAL_INVALID"):
        OpsRefusal(OpsReason.NOT_FOUND, NextAction.RETRY_LATER, "CORR-1")  # next action must match the table
    with pytest.raises(ValueError, match="OPS_REFUSAL_INVALID"):
        OpsRefusal("NOT_FOUND", NextAction.NO_ACTION, "CORR-1")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="OPS_REFUSAL_INVALID"):
        OpsRefusal(OpsReason.NOT_FOUND, NextAction.NO_ACTION, "bad id")
    with pytest.raises(ValueError, match="OPS_REFUSAL_INVALID"):
        OpsRefusal(OpsReason.NOT_FOUND, NextAction.NO_ACTION, "CORR-1", "OTHER")
    forged = object.__new__(OpsRefusal)
    object.__setattr__(forged, "reason", OpsReason.NOT_FOUND)
    object.__setattr__(forged, "next_action", NextAction.RETRY_LATER)
    object.__setattr__(forged, "correlation_id", "CORR-1")
    object.__setattr__(forged, "authority", AUTHORITY)
    assert not is_valid_refusal(forged)


def test_refusal_is_frozen():
    refusal = ops_refusal(OpsReason.NOT_FOUND, FakeCorrelationSource())
    with pytest.raises(dataclasses.FrozenInstanceError):
        refusal.reason = OpsReason.NOT_ENTITLED  # type: ignore[misc]


# ---- scope ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", HOSTILE_TEXT)
def test_scope_rejects_hostile_parts_without_echo(bad):
    for args in ((bad, "c1", "a1"), ("t1", bad, "a1"), ("t1", "c1", bad)):
        with pytest.raises(ValueError, match="OPS_SCOPE_INVALID") as info:
            OpsScope(*args)
        assert "t1" not in str(info.value)


def test_scope_valid_forged_and_repr():
    scope = OpsScope("tenant-SECRET", "c1", "a1")
    assert is_valid_scope(scope)
    assert "SECRET" not in repr(scope) and "c1" not in repr(scope)
    assert not is_valid_scope(object.__new__(OpsScope))
    forged = object.__new__(OpsScope)
    object.__setattr__(forged, "tenant_id", EvilStr("t1"))
    object.__setattr__(forged, "company_id", "c1")
    object.__setattr__(forged, "actor_id", "a1")
    assert not is_valid_scope(forged)
    for junk in (None, "x", {"tenant_id": "t"}, object()):
        assert not is_valid_scope(junk)


# ---- check_scope_order ---------------------------------------------------------------------------

class SpyPorts:
    """One shared call log for entitlement and ownership; real fakes answer."""

    def __init__(self):
        self.log: list[tuple] = []
        self.owner = FakeOwnership()
        self.ent = FakeEntitlements()

    def entitled(self, tenant_id, actor_id, company_id):
        self.log.append(("entitled", tenant_id, actor_id, company_id))
        return self.ent.entitled(tenant_id, actor_id, company_id)

    def owns(self, tenant_id, company_id, kind, ref):
        self.log.append(("owns", tenant_id, company_id, kind, ref))
        return self.owner.owns(tenant_id, company_id, kind, ref)


def _ports():
    ports = SpyPorts()
    ports.ent.grant("t1", "a1", "c1")
    ports.owner.add("t1", "c1", "report_id", "RPT-1")
    ports.owner.add("t1", "c1", "source_id", "SRC-1")
    ports.owner.add("t2", "c9", "report_id", "RPT-2")
    return ports


SCOPE = OpsScope("t1", "c1", "a1")


def test_all_passed_returns_none_and_order_is_entitlement_then_every_ownership():
    ports = _ports()
    result = check_scope_order(SCOPE, (("report_id", "RPT-1"), ("source_id", "SRC-1")), ports, ports,
                               FakeCorrelationSource())
    assert result is None
    assert [c[0] for c in ports.log] == ["entitled", "owns", "owns"]


def test_foreign_and_unknown_refs_give_identical_refusal_and_identical_port_call_pattern():
    foreign_ports, unknown_ports = _ports(), _ports()
    foreign = check_scope_order(SCOPE, (("report_id", "RPT-2"),), foreign_ports, foreign_ports,
                                FakeCorrelationSource())
    unknown = check_scope_order(SCOPE, (("report_id", "RPT-NOPE"),), unknown_ports, unknown_ports,
                                FakeCorrelationSource())
    assert foreign == unknown  # same fields including the injected id of a fresh source
    assert foreign.reason is OpsReason.NOT_FOUND
    pattern = lambda ports: [(c[0], c[1], c[2], c[3] if c[0] == "owns" else None) for c in ports.log]
    assert pattern(foreign_ports) == pattern(unknown_ports)
    assert len(foreign_ports.log) == len(unknown_ports.log) == 2


def test_every_reference_is_asked_even_when_the_first_is_foreign():
    ports = _ports()
    result = check_scope_order(SCOPE, (("report_id", "RPT-2"), ("source_id", "SRC-1"), ("report_id", "RPT-1")),
                               ports, ports, FakeCorrelationSource())
    assert result.reason is OpsReason.NOT_FOUND
    assert [c[0] for c in ports.log] == ["entitled", "owns", "owns", "owns"]
    # the same pattern when only the last one is foreign
    other = _ports()
    check_scope_order(SCOPE, (("report_id", "RPT-1"), ("source_id", "SRC-1"), ("report_id", "RPT-2")),
                      other, other, FakeCorrelationSource())
    assert [c[0] for c in other.log] == [c[0] for c in ports.log]


def test_unentitled_actor_is_refused_before_ownership_is_queried():
    ports = _ports()
    stranger = OpsScope("t1", "c1", "stranger")
    result = check_scope_order(stranger, (("report_id", "RPT-1"),), ports, ports, FakeCorrelationSource())
    assert result.reason is OpsReason.NOT_ENTITLED
    assert [c[0] for c in ports.log] == ["entitled"]


def test_structure_is_checked_before_any_port_call():
    ports = _ports()
    ids = FakeCorrelationSource()
    for scope, refs in [
        (None, ()), (object.__new__(OpsScope), ()), (SCOPE, None), (SCOPE, "report_id"), (SCOPE, {"a": 1}),
        (SCOPE, (("bogus_kind", "RPT-1"),)), (SCOPE, (("report_id", ""),)), (SCOPE, (("report_id", EvilStr("x")),)),
        (SCOPE, (("report_id",),)), (SCOPE, ("report_id",)), (SCOPE, (("report_id", "RPT-1", "x"),)),
        (SCOPE, (("report_id", "R\x00"),)), (SCOPE, tuple(("report_id", f"R{i}") for i in range(65))),
        (SCOPE, (("report_id", "R" * 10_000),)), (SCOPE, [("report_id", None)]), (SCOPE, (EvilStr("report_id"),)),
    ]:
        result = check_scope_order(scope, refs, ports, ports, ids)
        assert result.reason is OpsReason.INPUT_INVALID, (scope, refs)
    assert ports.log == []


def test_kind_with_lying_eq_is_not_accepted():
    ports = _ports()
    result = check_scope_order(SCOPE, ((EvilStr("report_id"), "RPT-1"),), ports, ports, FakeCorrelationSource())
    assert result.reason is OpsReason.INPUT_INVALID and ports.log == []


def test_refs_are_copied_once_so_a_mutating_caller_cannot_change_what_is_checked():
    ports = _ports()
    refs = [("report_id", "RPT-1")]
    original_owns = ports.owns

    def owns_and_mutate(tenant_id, company_id, kind, ref):
        refs.append(("report_id", "RPT-2"))
        refs[0] = ("report_id", "RPT-2")
        return original_owns(tenant_id, company_id, kind, ref)

    ports.owns = owns_and_mutate  # type: ignore[method-assign]
    assert check_scope_order(SCOPE, refs, ports, ports, FakeCorrelationSource()) is None
    assert [c[4] for c in ports.log if c[0] == "owns"] == ["RPT-1"]


class _Port:
    def __init__(self, answer):
        self._answer = answer

    def entitled(self, *args):
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer

    def owns(self, *args):
        return self.entitled(*args)


@pytest.mark.parametrize("answer", [False, None, 1, "yes", EvilInt(1), object()])
def test_port_answer_must_be_exactly_true(answer):
    assert check_scope_order(SCOPE, (), _Port(True), _Port(answer), FakeCorrelationSource()).reason \
        is OpsReason.NOT_ENTITLED
    assert check_scope_order(SCOPE, (("report_id", "R"),), _Port(answer), _Port(True),
                             FakeCorrelationSource()).reason is OpsReason.NOT_FOUND


def test_raising_or_missing_ports_give_dependency_failed_without_echo():
    boom = _Port(RuntimeError("POISON-port-text"))
    for entitlement, ownership, refs in [(boom, _Port(True), ()), (_Port(True), boom, (("report_id", "R"),)),
                                         (None, _Port(True), ()), (_Port(True), None, (("report_id", "R"),))]:
        result = check_scope_order(SCOPE, refs, ownership, entitlement, FakeCorrelationSource())
        assert result.reason is OpsReason.DEPENDENCY_FAILED
        assert "POISON" not in repr(result)


def test_quota_is_checked_last_and_must_be_exactly_true():
    ports = _ports()
    calls: list[str] = []

    def quota():
        calls.append("quota")
        return False

    result = check_scope_order(SCOPE, (("report_id", "RPT-1"),), ports, ports, FakeCorrelationSource(), quota)
    assert result.reason is OpsReason.QUOTA_EXCEEDED and calls == ["quota"]
    # a foreign ref never reaches the quota
    calls.clear()
    result = check_scope_order(SCOPE, (("report_id", "RPT-2"),), ports, ports, FakeCorrelationSource(), quota)
    assert result.reason is OpsReason.NOT_FOUND and calls == []
    assert check_scope_order(SCOPE, (), ports, ports, FakeCorrelationSource(), lambda: 1).reason \
        is OpsReason.QUOTA_EXCEEDED

    def boom():
        raise RuntimeError("POISON")

    assert check_scope_order(SCOPE, (), ports, ports, FakeCorrelationSource(), boom).reason \
        is OpsReason.DEPENDENCY_FAILED


def test_refusals_from_the_check_order_contain_no_caller_text():
    ports = _ports()
    scope = OpsScope("t1", "c1", "POISON-actor")
    result = check_scope_order(scope, (("report_id", "POISON-ref"),), ports, ports, FakeCorrelationSource())
    assert "POISON" not in repr(result) and "POISON" not in str(dataclasses.asdict(result))


# ---- operator authority --------------------------------------------------------------------------

def test_fake_operator_authority_allow_deny_table_and_hostile_input():
    auth = FakeOperatorAuthority()
    assert auth.authorized("op1", "rollback") is False
    auth.allow("op1", "rollback")
    assert auth.authorized("op1", "rollback") is True
    assert auth.authorized("op1", "other") is False and auth.authorized("op2", "rollback") is False
    auth.deny("op1", "rollback")
    assert auth.authorized("op1", "rollback") is False  # deny wins
    for bad in HOSTILE_TEXT:
        auth.allow(bad, "x")
        auth.allow("x", bad)
        assert auth.authorized(bad, "rollback") is False
        assert auth.authorized("op1", bad) is False


# ---- TenantBoundedMap ----------------------------------------------------------------------------

@pytest.mark.parametrize("cap", [0, -1, True, 1.0, "3", None, EvilInt(3), 2**40])
def test_map_rejects_bad_caps(cap):
    with pytest.raises(ValueError, match="TENANT_CAP_INVALID"):
        TenantBoundedMap(cap, FakeCorrelationSource())


def test_map_insert_get_replace_remove_roundtrip():
    m = TenantBoundedMap(3, FakeCorrelationSource())
    assert m.insert("t1", "k1", {"v": 1}) is None
    assert m.get("t1", "k1") == {"v": 1} and m.count("t1") == 1
    assert m.replace("t1", "k1", {"v": 2}) is None and m.get("t1", "k1") == {"v": 2}
    assert m.replace("t1", "nope", 1).reason is OpsReason.NOT_FOUND
    assert m.get("t1", "nope", "dflt") == "dflt" and m.get("t9", "k1") is None
    assert m.items("t1") == (("k1", {"v": 2}),)
    assert m.remove("t1", "k1") is True and m.remove("t1", "k1") is False
    assert m.count("t1") == 0 and m.items("t1") == ()


def test_map_insert_never_replaces_an_existing_record():
    m = TenantBoundedMap(3, FakeCorrelationSource())
    m.insert("t1", "k", "first")
    refusal = m.insert("t1", "k", "second")
    assert refusal.reason is OpsReason.DUPLICATE_SUPPRESSED and m.get("t1", "k") == "first"


def test_tenant_a_full_leaves_tenant_b_untouched_and_refusal_names_nothing_of_b():
    m = TenantBoundedMap(2, FakeCorrelationSource())
    assert m.insert("tenant-B", "b1", "B-SECRET-1") is None
    assert m.insert("tenant-A", "a1", "undelivered-1") is None
    assert m.insert("tenant-A", "a2", "undelivered-2") is None
    refusal = m.insert("tenant-A", "a3", "overflow")
    assert refusal.reason is OpsReason.QUOTA_EXCEEDED and refusal.next_action is NextAction.RETRY_LATER
    text = repr(refusal) + str(dataclasses.asdict(refusal))
    assert "tenant-B" not in text and "B-SECRET" not in text and "b1" not in text
    # nothing of A was evicted, B is untouched and still has room for its own cap
    assert m.items("tenant-A") == (("a1", "undelivered-1"), ("a2", "undelivered-2"))
    assert m.get("tenant-B", "b1") == "B-SECRET-1"
    assert m.insert("tenant-B", "b2", "B-2") is None and m.count("tenant-B") == 2
    assert m.insert("tenant-B", "b3", "x").reason is OpsReason.QUOTA_EXCEEDED
    assert m.has_room("tenant-A") is False and m.has_room("tenant-C") is True


def test_map_never_evicts_on_its_own_only_explicit_remove_frees_a_slot():
    m = TenantBoundedMap(1, FakeCorrelationSource())
    m.insert("t1", "pending", "undelivered")
    for i in range(50):
        assert m.insert("t1", f"k{i}", i).reason is OpsReason.QUOTA_EXCEEDED
    assert m.get("t1", "pending") == "undelivered"
    assert m.remove("t1", "pending") is True
    assert m.insert("t1", "next", 1) is None


@pytest.mark.parametrize("bad", HOSTILE_TEXT)
def test_map_hostile_tenant_or_key_is_refused_never_raises(bad):
    m = TenantBoundedMap(2, FakeCorrelationSource())
    assert m.insert(bad, "k", 1).reason is OpsReason.INPUT_INVALID
    assert m.insert("t1", bad, 1).reason is OpsReason.INPUT_INVALID
    assert m.replace(bad, "k", 1).reason is OpsReason.INPUT_INVALID
    assert m.get(bad, "k", "d") == "d" and m.get("t1", bad, "d") == "d"
    assert m.remove(bad, "k") is False and m.count(bad) == 0 and m.has_room(bad) is False
    assert m.items(bad) == ()
    assert m.count("t1") == 0


def test_map_is_not_a_global_cap_and_has_no_module_level_collection():
    m = TenantBoundedMap(1, FakeCorrelationSource())
    for i in range(200):  # many tenants, each with its own counter: none is refused by another's usage
        assert m.insert(f"tenant-{i}", "k", i) is None
    assert all(m.count(f"tenant-{i}") == 1 for i in range(200))
    tree = ast.parse((_SRC / "ops_types.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                continue  # the export list is a constant, not a store
            value = node.value
            assert not isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)), \
                node.lineno
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                assert value.func.id not in {"dict", "list", "set", "defaultdict", "deque"}, node.lineno


def test_map_concurrent_inserts_never_exceed_the_per_tenant_cap():
    cap, threads_n = 10, 16
    m = TenantBoundedMap(cap, FakeCorrelationSource())
    results: list[OpsRefusal | None] = []
    lock = threading.Lock()
    barrier = threading.Barrier(threads_n)

    def worker(n):
        barrier.wait()
        local = [m.insert("t1", f"k{n}-{i}", i) for i in range(10)]
        local += [m.insert("t2", f"k{n}-{i}", i) for i in range(2)]
        with lock:
            results.extend(local)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert m.count("t1") == cap and m.count("t2") == cap
    assert sum(r is None for r in results) == 2 * cap
    assert all(r is None or r.reason is OpsReason.QUOTA_EXCEEDED for r in results)


def test_map_repr_is_redacted():
    m = TenantBoundedMap(2, FakeCorrelationSource())
    m.insert("tenant-SECRET", "k", "value-SECRET")
    assert "SECRET" not in repr(m)


# ---- TenantSlotCounter ---------------------------------------------------------------------------

def test_slot_counter_limits_per_tenant_and_key_independently():
    c = ot.TenantSlotCounter(2)
    assert c.try_acquire("t1", "b1") and c.try_acquire("t1", "b1")
    assert c.try_acquire("t1", "b1") is False and c.active("t1", "b1") == 2
    assert c.try_acquire("t2", "b1") and c.try_acquire("t1", "b2")  # other tenant / other key unaffected
    c.release("t1", "b1")
    assert c.active("t1", "b1") == 1 and c.try_acquire("t1", "b1")
    for _ in range(5):  # unmatched releases are ignored and never go negative
        c.release("t1", "b1")
    assert c.active("t1", "b1") == 0 and c._active.get(("t1", "b1")) is None


@pytest.mark.parametrize("bad", HOSTILE_TEXT)
def test_slot_counter_hostile_input_never_acquires_or_raises(bad):
    c = ot.TenantSlotCounter(1)
    assert c.try_acquire(bad, "k") is False and c.try_acquire("t", bad) is False
    c.release(bad, "k")
    assert c.active(bad, "k") == 0


@pytest.mark.parametrize("limit", [0, True, 1.0, None, EvilInt(1), 2**40])
def test_slot_counter_rejects_bad_limits(limit):
    with pytest.raises(ValueError, match="TENANT_LIMIT_INVALID"):
        ot.TenantSlotCounter(limit)


def test_slot_counter_concurrent_acquire_never_exceeds_limit():
    c = ot.TenantSlotCounter(5)
    wins: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        got = c.try_acquire("t1", "b1")
        with lock:
            wins.append(got)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(wins) == 5 and c.active("t1", "b1") == 5


# ---- import boundary of the three E1 modules -----------------------------------------------------

E1_MODULES = ("ops_types.py", "capacity_model.py", "capacity_interference.py")
_FORBIDDEN_ROOTS = {
    "httpx", "requests", "aiohttp", "urllib", "urllib3", "http", "socket", "ssl", "subprocess", "sqlite3",
    "psycopg", "psycopg2", "asyncpg", "sqlalchemy", "os", "pathlib", "random", "secrets", "time", "shutil",
    "tempfile", "io", "ctypes", "asyncio", "multiprocessing", "concurrent", "fastapi", "flask", "starlette",
}
_FORBIDDEN_SIBLINGS = ("drive_http", "onec_discovery", "pdcc", "release1", "release_1")


def _imports(path: Path) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append((node.module or "", node.level))
            if node.level and not node.module:
                out += [(a.name, node.level) for a in node.names]
    return out


@pytest.mark.parametrize("name", E1_MODULES)
def test_e1_module_imports_nothing_forbidden(name):
    records = _imports(_SRC / name)
    assert records
    for module, level in records:
        root = module.split(".")[0]
        assert root not in _FORBIDDEN_ROOTS, (name, module)
        assert not any(s in module.lower() for s in _FORBIDDEN_SIBLINGS), (name, module)
        if level:
            assert level == 1, (name, module)  # a sibling phase2 module only, never the parent package
        elif root == "business_ai_gateway":
            assert module.startswith("business_ai_gateway.phase2"), (name, module)
        else:
            import sys
            assert root in sys.stdlib_module_names, (name, module)


@pytest.mark.parametrize("name", E1_MODULES)
def test_threading_only_in_ops_types_and_no_file_or_env_access(name):
    tree = ast.parse((_SRC / name).read_text(encoding="utf-8"))
    imported = {m.split(".")[0] for m, _ in _imports(_SRC / name)}
    assert ("threading" in imported) is (name == "ops_types.py")  # the only lock lives in the shared helpers
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "eval", "exec", "compile", "__import__"}, (name, node.lineno)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"environ", "getenv", "read_text", "write_text", "sleep", "utcnow"}, \
                (name, node.attr, node.lineno)


def test_boundary_scan_is_not_vacuous():
    fake = ast.parse("import socket\nfrom os import path\n")
    roots = {(a.name if isinstance(n, ast.Import) else n.module).split(".")[0]
             for n in ast.walk(fake) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in getattr(n, "names", [0])}
    assert roots & _FORBIDDEN_ROOTS == {"socket", "os"}
