"""S8 E1 shared workbench types: fixed enums, SafeError, ViewerScope, OwnerDirectory (hostile rows first)."""
import dataclasses
import decimal

import pytest

from business_ai_gateway.phase2 import workbench_types as wt
from business_ai_gateway.phase2.workbench_types import (
    AUTHORITY,
    NEXT_ACTION_FOR,
    AnnotationKind,
    NextAction,
    OwnerDirectory,
    ReasonCode,
    SafeError,
    ViewerScope,
    is_valid_directory,
    is_valid_safe_error,
    is_valid_scope,
    safe_error,
)


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class EvilInt(int):
    def __eq__(self, other):
        return True

    __hash__ = int.__hash__


HOSTILE_TEXT = [None, 5, b"t1", EvilStr("t1"), "", "   ", "t\x001", "t\u200b1", "x" * 10_000, ["t1"], object()]


# ---- hostile rows: nothing hostile builds a scope / directory / error -------------------------

@pytest.mark.parametrize("bad", HOSTILE_TEXT)
def test_viewer_scope_rejects_hostile_tenant_and_company(bad):
    with pytest.raises(ValueError, match="VIEWER_SCOPE_INVALID"):
        ViewerScope(bad, "c1", 1)
    with pytest.raises(ValueError, match="VIEWER_SCOPE_INVALID"):
        ViewerScope("t1", bad, 1)


@pytest.mark.parametrize("bad", [None, True, False, -1, EvilInt(3), 1.0, "1", 2**80, decimal.Decimal(1)])
def test_viewer_scope_rejects_hostile_epoch(bad):
    with pytest.raises(ValueError, match="VIEWER_SCOPE_INVALID"):
        ViewerScope("t1", "c1", bad)


def test_viewer_scope_error_never_echoes_input():
    with pytest.raises(ValueError) as info:
        ViewerScope("POISON-tenant\x00", "c1", 1)
    assert "POISON" not in str(info.value) and "POISON" not in repr(info.value)


def test_forged_instances_are_not_valid():
    assert not is_valid_scope(object.__new__(ViewerScope))
    assert not is_valid_directory(object.__new__(OwnerDirectory))
    assert not is_valid_safe_error(object.__new__(SafeError))
    for junk in (None, 1, "x", object(), {"tenant_id": "t1"}):
        assert not is_valid_scope(junk)
        assert not is_valid_directory(junk)
        assert not is_valid_safe_error(junk)


def test_forged_instance_with_bad_values_is_not_valid():
    forged = object.__new__(ViewerScope)
    object.__setattr__(forged, "tenant_id", EvilStr("t1"))
    object.__setattr__(forged, "company_id", "c1")
    object.__setattr__(forged, "scope_epoch", 1)
    assert not is_valid_scope(forged)


def test_viewer_scope_subclass_is_not_valid():
    class Sub(ViewerScope):
        pass

    # dataclass(slots) subclass without slots still builds; the validator must refuse the subtype
    assert not is_valid_scope(Sub("t1", "c1", 1))


@pytest.mark.parametrize("bad", HOSTILE_TEXT[:-1] + [()])
def test_directory_rejects_hostile_entries(bad):
    with pytest.raises(ValueError, match="OWNER_DIRECTORY_INVALID"):
        OwnerDirectory(((bad, "c1", "s1", "o1"),))
    with pytest.raises(ValueError, match="OWNER_DIRECTORY_INVALID"):
        OwnerDirectory((("t1", "c1", "s1", bad),))


@pytest.mark.parametrize("entries", [None, [("t1", "c1", "s1", "o1")], (("t1", "c1", "s1"),),
                                     (["t1", "c1", "s1", "o1"],), ("abc",),
                                     (("t1", "c1", "s1", "o1"), ("t1", "c1", "s1", "o2"))])
def test_directory_rejects_malformed_or_duplicate_shapes(entries):
    with pytest.raises(ValueError, match="OWNER_DIRECTORY_INVALID"):
        OwnerDirectory(entries)


def test_directory_from_mapping_hostile_never_raises_other_than_fixed_code():
    for bad in (None, 5, {"k": "v"}, {("t1", "c1"): "o"}, {("t1", "c1", "s1"): None},
                {("t1", "c1", EvilStr("s1")): "o1"}):
        with pytest.raises(ValueError, match="OWNER_DIRECTORY_INVALID"):
            OwnerDirectory.from_mapping(bad)


@pytest.mark.parametrize("bad", HOSTILE_TEXT)
def test_owner_for_hostile_lookup_is_none_never_raises(bad):
    d = OwnerDirectory((("t1", "c1", "s1", "o1"),))
    assert d.owner_for(bad, "c1", "s1") is None
    assert d.owner_for("t1", bad, "s1") is None
    assert d.owner_for("t1", "c1", bad) is None


def test_owner_for_forged_directory_is_none():
    assert OwnerDirectory.owner_for(object.__new__(OwnerDirectory), "t1", "c1", "s1") is None


def test_owner_for_evil_eq_cannot_match():
    d = OwnerDirectory((("t1", "c1", "s1", "o1"),))
    assert d.owner_for(EvilStr("t1"), "c1", "s1") is None


def test_safe_error_rejects_hostile_fields():
    for code in ("ORIGINAL_TAMPERED", None, 3, EvilStr("x")):
        with pytest.raises(ValueError, match="SAFE_ERROR_INVALID"):
            SafeError(code, NextAction.NO_ACTION, "CORR-1")
    with pytest.raises(ValueError, match="SAFE_ERROR_INVALID"):
        SafeError(ReasonCode.INPUT_INVALID, "NO_ACTION", "CORR-1")
    for corr in (None, "", "  ", "c\x00", "x" * 500, EvilStr("c"), 7, "Traceback (most recent call last)\n"):
        with pytest.raises(ValueError, match="SAFE_ERROR_INVALID"):
            SafeError(ReasonCode.INPUT_INVALID, NextAction.NO_ACTION, corr)


def test_safe_error_helper_never_raises_and_never_echoes():
    err = safe_error("not a code", "POISON\x00")
    assert err.reason_code is ReasonCode.INPUT_INVALID
    assert "POISON" not in repr(err)
    assert is_valid_safe_error(err)
    err2 = safe_error(ReasonCode.NOT_IN_SCOPE, EvilStr("c"))
    assert err2.reason_code is ReasonCode.NOT_IN_SCOPE
    assert err2.correlation_id == wt.DEFAULT_CORRELATION_ID


# ---- cannot mutate / frozen -------------------------------------------------------------------

@pytest.mark.parametrize("obj,attr", [
    (ViewerScope("t1", "c1", 1), "tenant_id"),
    (OwnerDirectory((("t1", "c1", "s1", "o1"),)), "entries"),
    (safe_error(ReasonCode.NOT_IN_SCOPE), "reason_code"),
])
def test_types_are_frozen_and_slotted(obj, attr):
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, attr, "x")
    assert not hasattr(obj, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        obj.extra = 1


def test_directory_entries_are_a_tuple_cannot_be_edited():
    d = OwnerDirectory.from_mapping({("t1", "c1", "s1"): "o1"})
    assert isinstance(d.entries, tuple)
    assert d.owner_for("t1", "c1", "s1") == "o1"
    with pytest.raises(TypeError):
        d.entries[0] = ("t1", "c1", "s1", "o2")  # type: ignore[index]


# ---- fixed vocabulary -------------------------------------------------------------------------

def test_reason_codes_are_the_fixed_plan_set():
    expected = {
        "ORIGINAL_NUMBERS_IMMUTABLE", "ORIGINAL_INTACT", "ORIGINAL_TAMPERED", "ROW_DETAIL_UNAVAILABLE",
        "OWNER_UNASSIGNED", "DELTA_PRECISION_EXCEEDED", "NO_NEW_EVIDENCE", "RERUN_TARGET_STALE",
        "RERUN_TARGET_UNKNOWN", "NOT_IN_SCOPE", "SCOPE_EPOCH_STALE", "ANNOTATION_INVALID", "INPUT_INVALID",
        "EFFECTIVE_UNKNOWN", "HIDDEN_BY_SCOPE", "SUPERSEDED_BY_RUN", "REVISION_CHANGED",
        "ATTESTATION_REVOKED", "STALE", "SOURCE_PAUSED", "NOT_COVERED", "UNKNOWN",
        "CSRF_REJECTED", "SESSION_INVALID", "IDEMPOTENCY_KEY_REQUIRED", "IDEMPOTENCY_CONFLICT", "REPLAYED",
        "OPERATION_UNCLASSIFIED", "OPERATION_DENIED", "PARAMETER_SCHEMA_INVALID", "NOT_FOUND",
        "RATE_LIMITED", "INTERNAL_REFUSED", "ORIGINAL_UNVERIFIABLE", "DEPENDENCY_FAILED",
    }
    assert {c.value for c in ReasonCode} == expected
    assert all(c.value == c.name for c in ReasonCode)
    assert {a.value for a in NextAction} == {
        "RETRY_LATER", "CONTACT_OWNER", "REAUTHENTICATE", "REFRESH_PAGE", "NO_ACTION"}
    assert {k.value for k in AnnotationKind} == {"NOTE", "ASSIGNED", "ACKNOWLEDGED", "RERUN_REQUESTED"}


def test_every_reason_code_has_a_fixed_next_action():
    assert set(NEXT_ACTION_FOR) == set(ReasonCode)
    assert all(type(v) is NextAction for v in NEXT_ACTION_FOR.values())
    with pytest.raises(TypeError):
        NEXT_ACTION_FOR[ReasonCode.UNKNOWN] = NextAction.NO_ACTION  # type: ignore[index]
    assert safe_error(ReasonCode.SCOPE_EPOCH_STALE).next_action is NextAction.REFRESH_PAGE
    assert safe_error(ReasonCode.ORIGINAL_TAMPERED).next_action is NextAction.CONTACT_OWNER


def test_authority_constant_and_defaults():
    assert AUTHORITY == "EVALUATION_ONLY"
    assert safe_error(ReasonCode.UNKNOWN).authority == AUTHORITY


# ---- happy path -------------------------------------------------------------------------------

def test_valid_scope_and_directory_lookup_case_preserved():
    scope = ViewerScope("T1", "C1", 0)
    assert is_valid_scope(scope)
    d = OwnerDirectory((("T1", "C1", "src", "owner-1"), ("T1", "C2", "src", "owner-2")))
    assert is_valid_directory(d)
    assert d.owner_for("T1", "C2", "src") == "owner-2"
    assert d.owner_for("t1", "C2", "src") is None
    assert d.owner_for("T1", "C3", "src") is None


def test_module_has_no_forbidden_imports():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(wt))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
    assert not names & {"httpx", "requests", "socket", "os", "pathlib", "subprocess"}
    assert all(n.startswith(".") or n in {"__future__", "dataclasses", "enum", "types", "typing", "re",
                                          "collections.abc", "threading"} for n in names)


# ---- review fix batch: ports, public correlation_ok, exact-type conventions, repr hygiene ------------

def test_correlation_ok_is_public_and_refuses_lying_str():
    assert wt.correlation_ok("CORR-1") and wt.correlation_ok("a.b:c_d-1".replace("_", "-"))
    assert not wt.correlation_ok(EvilStr("CORR-1"))
    assert not wt.correlation_ok("bad id") and not wt.correlation_ok(None) and not wt.correlation_ok("x" * 65)
    assert "correlation_ok" in wt.__all__


def test_safe_error_lying_authority_is_refused():
    err = safe_error(ReasonCode.UNKNOWN)
    forged = object.__new__(SafeError)
    for name in ("reason_code", "next_action", "correlation_id"):
        object.__setattr__(forged, name, getattr(err, name))
    object.__setattr__(forged, "authority", EvilStr("NOT-AUTHORITY"))
    assert not is_valid_safe_error(forged)
    with pytest.raises(ValueError, match="SAFE_ERROR_INVALID"):
        SafeError(ReasonCode.UNKNOWN, NextAction.NO_ACTION, "CORR-1", EvilStr("x"))


@pytest.mark.parametrize("code", [ReasonCode.ORIGINAL_INTACT, ReasonCode.REPLAYED])
def test_safe_error_refuses_success_like_codes(code):
    err = safe_error(code)
    assert err.reason_code is ReasonCode.INTERNAL_REFUSED and is_valid_safe_error(err)


def test_next_action_table_pinned_verbatim():
    A = NextAction
    expected = {
        "ORIGINAL_NUMBERS_IMMUTABLE": A.NO_ACTION, "ORIGINAL_INTACT": A.NO_ACTION,
        "ORIGINAL_TAMPERED": A.CONTACT_OWNER, "ROW_DETAIL_UNAVAILABLE": A.NO_ACTION,
        "OWNER_UNASSIGNED": A.CONTACT_OWNER, "DELTA_PRECISION_EXCEEDED": A.CONTACT_OWNER,
        "NO_NEW_EVIDENCE": A.NO_ACTION, "RERUN_TARGET_STALE": A.REFRESH_PAGE,
        "RERUN_TARGET_UNKNOWN": A.REFRESH_PAGE, "NOT_IN_SCOPE": A.CONTACT_OWNER,
        "SCOPE_EPOCH_STALE": A.REFRESH_PAGE, "ANNOTATION_INVALID": A.NO_ACTION, "INPUT_INVALID": A.NO_ACTION,
        "EFFECTIVE_UNKNOWN": A.NO_ACTION, "HIDDEN_BY_SCOPE": A.NO_ACTION, "SUPERSEDED_BY_RUN": A.NO_ACTION,
        "REVISION_CHANGED": A.REFRESH_PAGE, "ATTESTATION_REVOKED": A.CONTACT_OWNER, "STALE": A.REFRESH_PAGE,
        "SOURCE_PAUSED": A.CONTACT_OWNER, "NOT_COVERED": A.CONTACT_OWNER, "UNKNOWN": A.CONTACT_OWNER,
        "CSRF_REJECTED": A.REFRESH_PAGE, "SESSION_INVALID": A.REAUTHENTICATE,
        "IDEMPOTENCY_KEY_REQUIRED": A.NO_ACTION, "IDEMPOTENCY_CONFLICT": A.NO_ACTION, "REPLAYED": A.NO_ACTION,
        "OPERATION_UNCLASSIFIED": A.CONTACT_OWNER, "OPERATION_DENIED": A.CONTACT_OWNER,
        "PARAMETER_SCHEMA_INVALID": A.NO_ACTION, "NOT_FOUND": A.NO_ACTION, "RATE_LIMITED": A.RETRY_LATER,
        "INTERNAL_REFUSED": A.RETRY_LATER, "ORIGINAL_UNVERIFIABLE": A.CONTACT_OWNER,
        "DEPENDENCY_FAILED": A.RETRY_LATER,
    }
    assert {k.value: v for k, v in NEXT_ACTION_FOR.items()} == expected
    assert NEXT_ACTION_FOR[ReasonCode.CSRF_REJECTED] is NextAction.REFRESH_PAGE
    assert NEXT_ACTION_FOR[ReasonCode.SESSION_INVALID] is NextAction.REAUTHENTICATE
    assert NEXT_ACTION_FOR[ReasonCode.RATE_LIMITED] is NextAction.RETRY_LATER


def test_next_action_table_import_guard_exists():
    import inspect

    assert "NEXT_ACTION_FOR_INCOMPLETE" in inspect.getsource(wt)


def test_repr_never_shows_directory_table():
    d = OwnerDirectory((("tenant-SECRET", "c1", "src-SECRET", "owner-SECRET"),))
    text = repr(d)
    assert "SECRET" not in text and "owner" not in text


def test_owner_for_uses_precomputed_index():
    rows = tuple(("t", "c", f"s{i}", f"o{i}") for i in range(2000))
    d = OwnerDirectory(rows)
    assert is_valid_directory(d)
    assert d.owner_for("t", "c", "s1999") == "o1999"
    # the lookup must not touch entries at all (no per-call scan / re-validation)
    class Boom(tuple):
        def __iter__(self):
            raise AssertionError("scan")

    forged = object.__new__(OwnerDirectory)
    object.__setattr__(forged, "entries", Boom(rows))
    object.__setattr__(forged, "_index", d._index)
    assert forged.owner_for("t", "c", "s7") == "o7"


def test_directory_size_is_bounded():
    with pytest.raises(ValueError, match="OWNER_DIRECTORY_INVALID"):
        OwnerDirectory(tuple(("t", "c", f"s{i}", "o") for i in range(10_001)))


def test_from_mapping_hostile_mapping_and_keys_only_fixed_code():
    class BadLt:
        def __lt__(self, other):
            raise RuntimeError("POISON")

    class Bomb(dict):
        def items(self):
            raise RuntimeError("POISON")

    from types import MappingProxyType

    for bad in (MappingProxyType(Bomb(a=1)), {("t", "c", "s"): BadLt()}, {("t", "c", "s"): "o", ("t", "c", "s2"): BadLt()}):
        with pytest.raises(ValueError, match="OWNER_DIRECTORY_INVALID") as info:
            OwnerDirectory.from_mapping(bad)
        assert "POISON" not in str(info.value) and info.value.__cause__ is None


def test_fake_ownership_exact_semantics():
    own = wt.FakeOwnership()
    own.add("t1", "c1", "comparison_key", "K1")
    assert own.owns("t1", "c1", "comparison_key", "K1") is True
    assert own.owns("t1", "c2", "comparison_key", "K1") is False  # other company
    assert own.owns("t2", "c1", "comparison_key", "K1") is False  # other tenant
    assert own.owns("t1", "c1", "run_id", "K1") is False  # other kind
    assert own.owns("t1", "c1", "comparison_key", "K2") is False
    for kind in ("report_id", "snapshot_id", "source_id", "run_id"):
        own.add("t1", "c1", kind, "X")
        assert own.owns("t1", "c1", kind, "X") is True


@pytest.mark.parametrize("bad", HOSTILE_TEXT)
def test_fake_ownership_hostile_never_raises_and_is_false(bad):
    own = wt.FakeOwnership()
    own.add("t1", "c1", "comparison_key", "K1")
    own.add(bad, "c1", "comparison_key", "K1")
    own.add("t1", bad, "comparison_key", "K1")
    own.add("t1", "c1", bad, "K1")
    own.add("t1", "c1", "comparison_key", bad)
    for args in ((bad, "c1", "comparison_key", "K1"), ("t1", bad, "comparison_key", "K1"),
                 ("t1", "c1", bad, "K1"), ("t1", "c1", "comparison_key", bad)):
        assert own.owns(*args) is False
    assert own.owns(EvilStr("t1"), "c1", "comparison_key", "K1") is False
    assert own.owns("t1", "c1", EvilStr("comparison_key"), "K1") is False
    assert own.owns("t1", "c1", "bogus-kind", "K1") is False
    own.add("t1", "c1", "bogus-kind", "K9")
    assert len(own._rows) == 1


def test_fake_ownership_is_bounded():
    own = wt.FakeOwnership()
    for i in range(wt._MAX_PORT_ROWS + 10):
        own.add("t", "c", "run_id", f"r{i}")
    assert len(own._rows) == wt._MAX_PORT_ROWS
    assert own.owns("t", "c", "run_id", "r0") and not own.owns("t", "c", "run_id", f"r{wt._MAX_PORT_ROWS + 5}")


def test_fake_entitlements_exact_semantics_and_hostile():
    ent = wt.FakeEntitlements()
    ent.grant("t1", "alice", "c1")
    assert ent.entitled("t1", "alice", "c1") is True
    assert ent.entitled("t1", "alice", "c2") is False
    assert ent.entitled("t1", "bob", "c1") is False
    assert ent.entitled("t2", "alice", "c1") is False
    for bad in HOSTILE_TEXT:
        ent.grant(bad, "alice", "c1")
        ent.grant("t1", bad, "c1")
        ent.grant("t1", "alice", bad)
        assert ent.entitled(bad, "alice", "c1") is False
        assert ent.entitled("t1", bad, "c1") is False
        assert ent.entitled("t1", "alice", bad) is False
    assert ent.entitled("t1", EvilStr("alice"), "c1") is False
    assert len(ent._rows) == 1


def test_ports_are_structural_protocols():
    assert isinstance(wt.FakeOwnership().owns, object)
    assert wt.OWNERSHIP_KINDS == {"comparison_key", "run_id", "snapshot_id", "source_id", "report_id"}
