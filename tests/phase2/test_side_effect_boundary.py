"""R2-US-025 side-effect boundary: TC073 (read-only plan), TC074 (rights), TC075 (probes, name tricks)."""
from __future__ import annotations

import dataclasses

import pytest

from business_ai_gateway.phase2.side_effect_boundary import (
    BoundaryCode,
    CapturePlan,
    Environment,
    OperationClass,
    OperationRegistry,
    RegistryError,
    default_registry,
    evaluate,
)

REG = default_registry()
READ_RIGHTS = frozenset({"read"})


def plan(ops, rights=READ_RIGHTS, env=Environment.NON_PROD, probes=()):
    return CapturePlan(tuple(ops), frozenset(rights), env, tuple(probes))


# ---- TC073 ----
def test_read_only_plan_allowed_with_ordered_complete_coverage():
    d = evaluate(plan(["export_report", "list_catalogs", "read_document"]), REG)
    assert d.allowed and d.code is BoundaryCode.ALLOWED
    assert d.coverage == (
        ("export_report", OperationClass.READ),
        ("list_catalogs", OperationClass.READ),
        ("read_document", OperationClass.READ),
    )
    assert d.denied_ops == ()


def test_duplicates_collapse_and_are_reported():
    d = evaluate(plan(["list_catalogs", " LIST_CATALOGS ", "read_document"]), REG)
    assert d.allowed
    assert [n for n, _ in d.coverage] == ["list_catalogs", "read_document"]
    assert d.duplicate_ops == ("list_catalogs",)


def test_unclassified_operation_denies_even_if_rest_is_read():
    d = evaluate(plan(["list_catalogs", "brand_new_op", "read_document"]), REG)
    assert not d.allowed and d.code is BoundaryCode.OPERATION_UNCLASSIFIED
    assert d.denied_ops == ("brand_new_op",)
    assert ("brand_new_op", OperationClass.UNCLASSIFIED) in d.coverage
    assert len(d.coverage) == 3


def test_empty_plan_denied():
    d = evaluate(plan([]), REG)
    assert not d.allowed and d.code is BoundaryCode.EMPTY_PLAN


@pytest.mark.parametrize("op,code", [
    ("create_document", BoundaryCode.WRITE_OPERATION),
    ("update_document", BoundaryCode.WRITE_OPERATION),
    ("post_document", BoundaryCode.POST_OPERATION),
    ("delete_document", BoundaryCode.DELETE_OPERATION),
    ("reset_database", BoundaryCode.RESET_OPERATION),
    ("grant_role", BoundaryCode.ADMIN_OPERATION),
])
def test_each_non_read_class_denies_with_its_code(op, code):
    d = evaluate(plan(["list_catalogs", op]), REG)
    assert not d.allowed and d.code is code and d.denied_ops == (op,)


# ---- TC074 ----
@pytest.mark.parametrize("right", [
    "admin", "Administrator", "posting", "post", "full_access", "WRITE", "supervisor",
    "mystery_right", "", "re\u200bad", "read\n",
])
def test_non_read_or_unknown_rights_disqualify(right):
    d = evaluate(plan(["list_catalogs"], rights={"read", right}), REG)
    assert not d.allowed and d.code is BoundaryCode.RIGHTS_DISQUALIFY
    assert len(d.disqualifying_rights) == 1


def test_read_only_rights_pass_including_normalised_spelling():
    d = evaluate(plan(["list_catalogs"], rights={"Read", " VIEW ", "list"}), REG)
    assert d.allowed and d.disqualifying_rights == ()


def test_custom_allow_list_is_honoured_and_default_not_widened():
    p = plan(["list_catalogs"], rights={"audit_read"})
    assert not evaluate(p, REG).allowed
    assert evaluate(p, REG, frozenset({"audit_read"})).allowed
    # a disqualifying right stays disqualifying even if someone lists it as allowed
    assert not evaluate(plan(["list_catalogs"], rights={"admin"}), REG, frozenset({"admin"})).allowed


# ---- TC075 ----
@pytest.mark.parametrize("probe", ["reset_database", "create_document", "never_heard_of_it"])
def test_non_read_probe_denied_in_prod(probe):
    d = evaluate(plan(["list_catalogs"], env=Environment.PROD, probes=[probe]), REG)
    assert not d.allowed and d.code is BoundaryCode.PROBE_DENIED_IN_PROD


def test_read_probe_allowed_in_prod_and_write_probe_denied_in_non_prod():
    assert evaluate(plan(["list_catalogs"], env=Environment.PROD, probes=["read_document"]), REG).allowed
    d = evaluate(plan(["list_catalogs"], probes=["update_document"]), REG)
    assert not d.allowed and d.code is BoundaryCode.PROBE_DENIED


@pytest.mark.parametrize("name", [
    "LIST_CATALOGS", "  list_catalogs  ", "\uff4c\uff49\uff53\uff54_catalogs",
])
def test_harmless_spelling_variants_canonicalise_to_the_registered_read_name(name):
    d = evaluate(plan([name]), REG)
    assert d.allowed and d.coverage == (("list_catalogs", OperationClass.READ),)


@pytest.mark.parametrize("name", ["CREATE_DOCUMENT", " create_document ", "\uff43reate_document"])
def test_variants_of_write_names_stay_write(name):
    d = evaluate(plan([name]), REG)
    assert not d.allowed and d.code is BoundaryCode.WRITE_OPERATION
    assert d.coverage == (("create_document", OperationClass.WRITE),)


@pytest.mark.parametrize("name", [
    "list_cat\u200balogs",     # zero width space
    "list_catalogs\u200d",     # zero width joiner
    "list\u00a0catalogs",      # no-break space
    "list_catalogs\n",
    "list\tcatalogs",
    "l\u0456st_catalogs",      # Cyrillic i
    "read_d\u043ecument",      # Cyrillic o
    "list catalogs",
    "list_catalogs;drop",
    "",
    "   ",
])
def test_forbidden_or_mixed_script_names_are_invalid_never_read(name):
    d = evaluate(plan(["list_catalogs", name]), REG)
    assert not d.allowed and d.code is BoundaryCode.OPERATION_NAME_INVALID
    assert d.invalid_count == 1
    assert ("<invalid>", OperationClass.UNCLASSIFIED) in d.coverage


def test_conflicting_registry_rejected():
    with pytest.raises(RegistryError) as e:
        OperationRegistry.from_entries([("do_it", OperationClass.READ), (" DO_IT", OperationClass.WRITE)])
    assert str(e.value) == "REGISTRY_CONFLICT"


@pytest.mark.parametrize("entries", [
    [("bad\u200bname", OperationClass.READ)],
    [("x", "READ")],
    [("x", OperationClass.UNCLASSIFIED)],
    [("x",)],
    "list_catalogs",
    5,
])
def test_invalid_registry_entries_rejected(entries):
    with pytest.raises(RegistryError):
        OperationRegistry.from_entries(entries)


def test_same_class_duplicate_entry_is_fine():
    r = OperationRegistry.from_entries([("a", OperationClass.READ), ("A", OperationClass.READ)])
    assert r.classify("a") is OperationClass.READ


def test_registry_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        REG.entries = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        REG.entries["create_document"] = OperationClass.READ  # type: ignore[index]
    src = {"a": OperationClass.READ}
    r = OperationRegistry.from_entries(src.items())
    src["a"] = OperationClass.WRITE
    assert r.classify("a") is OperationClass.READ


# ---- codes / types ----
def test_codes_never_echo_caller_input():
    secret = "SeCrEt\u200bOp"
    d = evaluate(plan([secret], rights={"SeCrEtRight\n"}, probes=[secret]), REG)
    blob = repr((d.code, d.coverage, d.denied_ops, d.disqualifying_rights)).lower()
    assert "secret" not in blob


@pytest.mark.parametrize("bad", [
    None, "x", 1, [], object(),
    CapturePlan(["list_catalogs"], frozenset(), Environment.PROD),            # list not tuple
    CapturePlan(("list_catalogs",), {"read"}, Environment.PROD),               # set not frozenset
    CapturePlan(("list_catalogs",), frozenset(), "PROD"),                      # str env
    CapturePlan(("list_catalogs",), frozenset(), Environment.PROD, ["a"]),     # list probes
])
def test_wrong_types_give_fixed_code(bad):
    d = evaluate(bad, REG)
    assert not d.allowed and d.code is BoundaryCode.INVALID_INPUT


def test_wrong_registry_or_rights_type_give_fixed_code():
    p = plan(["list_catalogs"])
    assert evaluate(p, {"list_catalogs": "READ"}).code is BoundaryCode.INVALID_INPUT
    assert evaluate(p, None).code is BoundaryCode.INVALID_INPUT
    assert evaluate(p, REG, {"read"}).code is BoundaryCode.INVALID_INPUT


def test_non_string_items_are_invalid_names_not_errors():
    d = evaluate(plan(["list_catalogs", 5, None]), REG)  # type: ignore[list-item]
    assert not d.allowed and d.code is BoundaryCode.OPERATION_NAME_INVALID


def test_non_string_right_disqualifies_without_error():
    d = evaluate(plan(["list_catalogs"], rights={"read", 5}), REG)  # type: ignore[arg-type]
    assert not d.allowed and d.code is BoundaryCode.RIGHTS_DISQUALIFY
