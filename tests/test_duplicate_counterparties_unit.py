"""Pure unit tests for the SC08 duplicate-counterparty collector (no DB, no network)."""

from __future__ import annotations

import copy
import hashlib
import random

import pytest

from business_ai_gateway.duplicate_counterparties import (
    DUPLICATE_CONCEPT,
    DUPLICATE_FAILURE_REASONS,
    MATCH_RULE,
    build_activity_query,
    build_catalog_query,
    evaluate_duplicate_candidates,
    group_id,
    is_conclusive,
    normalize_name,
    rows_truncated,
    validate_duplicate_mapping,
)
from business_ai_gateway.semantic import SemanticMappingUnconfirmed

ORG1 = "10000000-0000-0000-0000-000000000001"
ORG2 = "10000000-0000-0000-0000-000000000002"
SCOPE = "Организация_Key"
A = "20000000-0000-0000-0000-000000000001"
B = "20000000-0000-0000-0000-000000000003"
C = "20000000-0000-0000-0000-000000000004"
D = "20000000-0000-0000-0000-000000000005"
ZERO = "00000000-0000-0000-0000-000000000000"
MAPPING = {
    "entity_set": "Catalog_Counterparties",
    "output_fields": {"counterparty_ref": "Ref_Key", "code": "Code", "name": "Description"},
    "company_activity": {
        "entity_set": "AccumulationRegister_SettlementItems",
        "counterparty_field": "Counterparty_Key",
        "company_scope": {"field": SCOPE, "value_type": "guid"},
    },
    "match_rule": "normalized_name_v1",
    "required_register_capabilities": [],
}


def cat(ref, name, code="X"):
    return {"Ref_Key": ref, "Code": code, "Description": name}


def act(*refs, company=ORG1):
    return [{"Counterparty_Key": r, SCOPE: company} for r in refs]


def run(catalog, activity=None, *, limit=2000, act_trunc=False, cat_trunc=False, company=ORG1):
    if activity is None:
        activity = act(*[r["Ref_Key"] for r in catalog])
    return evaluate_duplicate_candidates(
        MAPPING, company_id=company, row_limit=limit, activity_rows=activity,
        activity_truncated=act_trunc, catalog_rows=catalog, catalog_truncated=cat_trunc,
    )


def ids(result):
    return [[m["counterparty_id"] for m in g["members"]] for g in result["groups"]]


# ---- normalisation / grouping -------------------------------------------------------------

@pytest.mark.parametrize("variant", [
    "synthetic customer", "SYNTHETIC CUSTOMER", "  Synthetic   Customer  ",
    "Synthetic\tCustomer\n", "Synthetic-Customer", "Synthetic_Customer", "Synthetic, Customer.",
    "ＳＹＮＴＨＥＴＩＣ　ＣＵＳＴＯＭＥＲ", "Synthetic Customer",
])
def test_name_variants_group_together(variant):
    result = run([cat(A, "Synthetic customer"), cat(B, variant)])
    assert result["status"] == "FINDING"
    assert ids(result) == [[A, B]]
    assert result["groups"][0]["match_key"] == "synthetic customer"


def test_nfkc_ligature_groups_with_plain_letters():
    result = run([cat(A, "Oﬃce supply"), cat(B, "Office supply")])
    assert ids(result) == [[A, B]]


def test_cyrillic_case_groups():
    result = run([cat(A, "Ромашка"), cat(B, "РОМАШКА")])
    assert ids(result) == [[A, B]]


def test_underscore_is_separator_not_word_character():
    assert normalize_name("a_b") == "a b"
    assert normalize_name("a__--b") == "a b"


def test_different_names_do_not_group():
    result = run([cat(A, "Alpha"), cat(B, "Beta"), cat(C, "Alphabet")])
    assert result["status"] == "PASS"
    assert result["groups"] == []


def test_blank_and_punctuation_only_names_are_excluded():
    result = run([cat(A, ""), cat(B, "   "), cat(C, "-- ..."), cat(D, "_")])
    assert result["status"] == "PASS"
    assert result["candidate_count"] == 0


def test_two_and_three_member_groups():
    two = run([cat(A, "Same"), cat(B, "same")])
    assert (two["candidate_count"], two["group_count"]) == (2, 1)
    three = run([cat(A, "Same"), cat(B, "same"), cat(C, "SAME!")])
    assert (three["candidate_count"], three["group_count"]) == (3, 1)
    assert ids(three) == [[A, B, C]]


def test_two_groups_sorted_by_match_key_and_counted():
    result = run([cat(A, "Zeta"), cat(B, "zeta"), cat(C, "Alpha"), cat(D, "ALPHA")])
    assert [g["match_key"] for g in result["groups"]] == ["alpha", "zeta"]
    assert (result["candidate_count"], result["group_count"]) == (4, 2)


def test_members_sorted_by_lowercased_ref_key():
    upper = "AAAAAAAA-0000-0000-0000-000000000009"
    lower = "bbbbbbbb-0000-0000-0000-000000000001"
    result = run([cat(lower, "Same"), cat(upper, "same")])
    assert ids(result) == [[upper, lower]]


def test_same_ref_key_twice_is_fact_invalid_not_a_pair():
    result = run([cat(A, "Same"), cat(A, "Same")])
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_FACT_INVALID")
    assert result["groups"] == [] and result["candidate_count"] == 0


def test_same_ref_key_differing_only_by_case_is_fact_invalid():
    result = run([cat(A.upper(), "Same"), cat(A.lower(), "same")], activity=act(A))
    assert result["reason"] == "COUNTERPARTY_FACT_INVALID"


def test_duplicate_ref_key_outside_activity_is_still_fact_invalid():
    result = run([cat(A, "x"), cat(D, "y"), cat(D, "z")], activity=act(A))
    assert result["reason"] == "COUNTERPARTY_FACT_INVALID"


def test_single_counterparty_never_pairs_with_itself():
    result = run([cat(A, "Only")])
    assert result["status"] == "PASS"


# ---- company scoping through activity ---------------------------------------------------

def test_catalog_counterparty_without_activity_is_not_returned_or_counted():
    catalog = [cat(A, "Same"), cat(B, "same"), cat(C, "SAME")]
    result = run(catalog, activity=act(A, B))
    assert ids(result) == [[A, B]]
    assert result["candidate_count"] == 2


def test_no_activity_for_pair_gives_pass():
    result = run([cat(A, "Same"), cat(B, "same")], activity=act(A))
    assert result["status"] == "PASS" and result["groups"] == []


@pytest.mark.parametrize("empty", [None, "", ZERO])
def test_null_empty_zero_activity_counterparty_ignored(empty):
    catalog = [cat(A, "Same"), cat(B, "same")]
    result = run(catalog, activity=act(A, B) + act(empty))
    assert result["status"] == "FINDING"
    only_empty = run(catalog, activity=act(empty))
    assert only_empty["status"] == "PASS"


@pytest.mark.parametrize("bad", [5, True, ["x"], "not-a-guid"])
def test_malformed_activity_counterparty_is_fact_invalid(bad):
    result = run([cat(A, "Same")], activity=act(A, bad))
    assert result["reason"] == "COUNTERPARTY_FACT_INVALID"


def test_activity_row_missing_keys_is_fact_invalid():
    result = run([cat(A, "Same")], activity=[{"Counterparty_Key": A}])
    assert result["reason"] == "COUNTERPARTY_FACT_INVALID"


def test_company_mismatch_in_activity_row():
    activity = act(A) + act(B, company=ORG2)
    result = run([cat(A, "Same"), cat(B, "same")], activity=activity)
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COMPANY_SCOPE_MISMATCH")
    assert result["groups"] == []


def test_company_match_is_case_insensitive():
    result = run([cat(A, "Same"), cat(B, "same")], company=ORG1.upper())
    assert result["status"] == "FINDING"


def test_company_two_does_not_see_company_one_pair():
    catalog = [cat(A, "Same"), cat(B, "same")]
    result = run(catalog, activity=act(C, company=ORG2), company=ORG2)
    assert result["status"] == "PASS" and result["groups"] == []


def test_activity_guid_compare_is_case_insensitive():
    result = run([cat(A, "Same"), cat(B.upper(), "same")], activity=act(A.upper(), B))
    assert result["status"] == "FINDING"


# ---- truncation ---------------------------------------------------------------------------

def test_activity_truncation_is_inconclusive_and_ignores_catalog():
    result = evaluate_duplicate_candidates(
        MAPPING, company_id=ORG1, row_limit=2000, activity_rows=act(A, B),
        activity_truncated=True, catalog_rows=None, catalog_truncated=False,
    )
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_ROWS_TRUNCATED")
    assert result["groups"] == [] and result["candidate_count"] == 0
    assert result["truncated"] is True


def test_activity_truncation_ignores_a_supplied_duplicate_catalog():
    result = evaluate_duplicate_candidates(
        MAPPING, company_id=ORG1, row_limit=2000, activity_rows=act(A, B),
        activity_truncated=True, catalog_rows=[cat(A, "x"), cat(B, "x")],
        catalog_truncated=False,
    )
    assert result["status"] == "INCONCLUSIVE" and result["groups"] == []


def test_activity_exactly_at_limit_is_truncated():
    result = run([cat(A, "Same"), cat(B, "same")], activity=act(A, B), limit=2)
    assert result["reason"] == "COUNTERPARTY_ROWS_TRUNCATED"
    below = run([cat(A, "Same"), cat(B, "same")], activity=act(A, B), limit=3)
    assert below["status"] == "FINDING"


def test_catalog_truncation_has_no_partial_finding():
    catalog = [cat(A, "Same"), cat(B, "same")]
    result = run(catalog, activity=act(A, B), cat_trunc=True)
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_ROWS_TRUNCATED")
    assert result["groups"] == [] and result["candidate_count"] == 0
    assert result["group_count"] == 0 and result["truncated"] is True


def test_catalog_exactly_at_limit_is_truncated():
    catalog = [cat(A, "Same"), cat(B, "same")]
    result = run(catalog, activity=act(A), limit=2)
    assert result["reason"] == "COUNTERPARTY_ROWS_TRUNCATED"
    assert run(catalog, activity=act(A, B), limit=3)["status"] == "FINDING"


def test_rows_truncated_helper():
    assert rows_truncated([1, 2], 2, False) is True
    assert rows_truncated([1], 2, False) is False
    assert rows_truncated([], 2, True) is True


# ---- determinism --------------------------------------------------------------------------

def test_shuffled_and_duplicated_inputs_give_identical_result():
    catalog = [
        cat(A, "Synthetic customer", "C001"), cat(B, "synthetic  CUSTOMER", "C001D"),
        cat(C, "Other"), cat(D, "Another"),
    ]
    activity = act(A, B, C, D)
    baseline = run(catalog, activity)
    rng = random.Random(8)
    for _ in range(8):
        shuffled_cat = copy.deepcopy(catalog)
        rng.shuffle(shuffled_cat)
        shuffled_act = activity + act(A, B, A)
        rng.shuffle(shuffled_act)
        assert run(shuffled_cat, shuffled_act) == baseline


def test_group_id_stable_and_matches_documented_formula():
    result = run([cat(A, "Synthetic customer"), cat(B, "SYNTHETIC CUSTOMER")])
    expected = "dup-" + hashlib.sha256(b"normalized_name_v1\0synthetic customer").hexdigest()[:16]
    assert result["groups"][0]["group_id"] == expected == group_id("synthetic customer")
    assert result["groups"][0]["group_id"] == run(
        [cat(B, "SYNTHETIC CUSTOMER"), cat(A, "Synthetic customer")]
    )["groups"][0]["group_id"]
    assert group_id("a") != group_id("b")


def test_group_id_hashes_utf8_of_match_key():
    key = "ромашка"
    expected = "dup-" + hashlib.sha256(b"normalized_name_v1\0" + key.encode("utf-8")).hexdigest()[:16]
    assert group_id(key) == expected


# ---- shape / status -----------------------------------------------------------------------

def test_merge_count_is_int_zero_in_every_branch():
    results = [
        run([cat(A, "Same"), cat(B, "same")]),
        run([cat(A, "x")]),
        run([cat(A, "x")], act_trunc=True),
        run([cat(A, "x")], cat_trunc=True),
        run([cat(A, "x")], activity="nope"),
        run("nope", activity=act(A)),
        run([cat(A, "x"), cat(A, "x")]),
        run([cat(A, "x")], activity=act(A, company=ORG2)),
    ]
    assert [r["status"] for r in results] == [
        "FINDING", "PASS", "INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE", "INCONCLUSIVE",
        "INCONCLUSIVE", "INCONCLUSIVE",
    ]
    for r in results:
        assert r["merge_count"] == 0 and type(r["merge_count"]) is int


def test_non_list_responses_are_source_response_invalid():
    assert run([cat(A, "x")], activity={"value": []})["reason"] == "SOURCE_RESPONSE_INVALID"
    assert run({"value": []}, activity=act(A))["reason"] == "SOURCE_RESPONSE_INVALID"
    assert run(None, activity=act(A))["reason"] == "SOURCE_RESPONSE_INVALID"


@pytest.mark.parametrize("row", [
    {"Ref_Key": A, "Code": "c"},
    {"Ref_Key": A, "Description": "d"},
    {"Code": "c", "Description": "d"},
    {"Ref_Key": A, "Code": "c", "Description": None},
    {"Ref_Key": A, "Code": "c", "Description": 5},
    {"Ref_Key": A, "Code": None, "Description": "d"},
    {"Ref_Key": None, "Code": "c", "Description": "d"},
    "not-a-row",
])
def test_bad_catalog_rows_are_fact_invalid(row):
    result = run([row], activity=act(A))
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_FACT_INVALID")


def test_empty_description_and_code_are_valid_values():
    result = run([cat(A, "", ""), cat(B, "x", "")])
    assert result["status"] == "PASS"


def test_seed_shape_one_group_of_two():
    catalog = [
        cat(A, "Synthetic customer", "C001"), cat(B, "Synthetic customer", "C001D"),
        cat(C, "Synthetic supplier", "S001"), cat(D, "Customer four", "C004"),
        cat("20000000-0000-0000-0000-000000000006", "Customer five", "C005"),
    ]
    result = run(catalog)
    assert result["status"] == "FINDING" and result["reason"] == "DUPLICATE_CANDIDATES_FOUND"
    assert (result["candidate_count"], result["group_count"], result["merge_count"]) == (2, 1, 0)
    group = result["groups"][0]
    assert group["match_basis"] == "NORMALIZED_NAME"
    assert group["members"] == [
        {"counterparty_id": A, "code": "C001", "name": "Synthetic customer"},
        {"counterparty_id": B, "code": "C001D", "name": "Synthetic customer"},
    ]


def test_pass_shape():
    result = run([cat(A, "a"), cat(B, "b")])
    assert result["reason"] == "NO_DUPLICATE_CANDIDATES"
    assert (result["candidate_count"], result["group_count"], result["groups"]) == (0, 0, [])
    assert result["truncated"] is False


def test_result_has_no_provenance_or_evidence_keys_and_fixed_flags():
    for result in (run([cat(A, "Same"), cat(B, "same")]), run([cat(A, "x")], act_trunc=True)):
        assert set(result) == {
            "concept", "match_rule", "status", "reason", "candidate_count", "group_count",
            "merge_count", "groups", "truncated", "native_approval_inferred",
            "human_review_required",
        }
        assert result["concept"] == DUPLICATE_CONCEPT == "counterparty.duplicate_candidates"
        assert result["match_rule"] == MATCH_RULE
        assert result["native_approval_inferred"] is False
        assert result["human_review_required"] is True


def test_is_conclusive_and_failure_reasons():
    assert DUPLICATE_FAILURE_REASONS == {
        "COUNTERPARTY_ROWS_TRUNCATED", "SOURCE_RESPONSE_INVALID", "COUNTERPARTY_FACT_INVALID",
        "COMPANY_SCOPE_MISMATCH",
    }
    assert is_conclusive(run([cat(A, "x")])) is True
    assert is_conclusive(run([cat(A, "Same"), cat(B, "same")])) is True
    for result in (
        run([cat(A, "x")], act_trunc=True), run([cat(A, "x")], activity="x"),
        run([{"Ref_Key": A}], activity=act(A)), run([cat(A, "x")], activity=act(A, company=ORG2)),
    ):
        assert result["reason"] in DUPLICATE_FAILURE_REASONS
        assert is_conclusive(result) is False


# ---- mapping validator --------------------------------------------------------------------

def mutated(**changes):
    mapping = copy.deepcopy(MAPPING)
    mapping.update(changes)
    return mapping


def test_validator_accepts_contract_mapping_and_returns_copy():
    valid = validate_duplicate_mapping(MAPPING)
    assert valid == MAPPING and valid is not MAPPING
    valid["output_fields"]["name"] = "changed"
    assert MAPPING["output_fields"]["name"] == "Description"


def test_validator_accepts_information_register_activity():
    mapping = copy.deepcopy(MAPPING)
    mapping["company_activity"]["entity_set"] = "InformationRegister_Anything"
    assert validate_duplicate_mapping(mapping)


def _with_activity(**changes):
    mapping = copy.deepcopy(MAPPING)
    mapping["company_activity"].update(changes)
    return mapping


def _with_scope(**changes):
    mapping = copy.deepcopy(MAPPING)
    mapping["company_activity"]["company_scope"].update(changes)
    return mapping


def _bad_mappings():
    yield "unknown top key", mutated(extra=1)
    yield "unknown activity key", _with_activity(extra=1)
    yield "document entity", mutated(entity_set="Document_Sales")
    yield "no entity", {k: v for k, v in MAPPING.items() if k != "entity_set"}
    yield "non-string entity", mutated(entity_set=5)
    yield "register in catalog slot", mutated(entity_set="AccumulationRegister_X")
    yield "catalog activity", _with_activity(entity_set="Catalog_Counterparties")
    yield "document activity", _with_activity(entity_set="Document_Sales")
    yield "duplicate output names", mutated(
        output_fields={"counterparty_ref": "Ref_Key", "code": "Code", "name": "Code"})
    yield "extra output field", mutated(
        output_fields={**MAPPING["output_fields"], "tax_id": "INN"})
    yield "missing output field", mutated(
        output_fields={"counterparty_ref": "Ref_Key", "code": "Code"})
    yield "non-string output field", mutated(
        output_fields={"counterparty_ref": "Ref_Key", "code": "Code", "name": 1})
    yield "string value_type", _with_scope(value_type="string")
    yield "missing value_type", _with_scope(value_type=None)
    yield "scope field equals counterparty field", _with_scope(field="Counterparty_Key")
    yield "wrong match rule", mutated(match_rule="normalized_name_v2")
    yield "missing match rule", {k: v for k, v in MAPPING.items() if k != "match_rule"}
    yield "capabilities non-empty", mutated(required_register_capabilities=["x"])
    yield "capabilities missing", {
        k: v for k, v in MAPPING.items() if k != "required_register_capabilities"}
    yield "not a dict", ["x"]


@pytest.mark.parametrize("label,mapping", list(_bad_mappings()))
def test_validator_rejects(label, mapping):
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_duplicate_mapping(mapping)


def test_evaluate_rejects_an_invalid_mapping():
    with pytest.raises(SemanticMappingUnconfirmed):
        evaluate_duplicate_candidates(
            mutated(match_rule="x"), company_id=ORG1, row_limit=10, activity_rows=[],
            activity_truncated=False, catalog_rows=[], catalog_truncated=False,
        )


# ---- query builders -----------------------------------------------------------------------

def test_activity_query_has_company_filter_and_select():
    query = build_activity_query(MAPPING, ORG1, 123)
    assert query["entity_set"] == "AccumulationRegister_SettlementItems"
    assert query["select"] == ["Counterparty_Key", SCOPE]
    assert query["filter_expr"] == f"{SCOPE} eq guid'{ORG1}'"
    assert query["orderby"] == "Counterparty_Key asc"
    assert query["top"] == 123


def test_activity_query_rejects_non_guid_company():
    with pytest.raises(SemanticMappingUnconfirmed):
        build_activity_query(MAPPING, "not-a-guid", 10)


def test_catalog_query_has_no_filter_and_orders_by_ref_key():
    query = build_catalog_query(MAPPING, 77)
    assert query["entity_set"] == "Catalog_Counterparties"
    assert query["select"] == ["Ref_Key", "Code", "Description"]
    assert query["filter_expr"] is None
    assert query["orderby"] == "Ref_Key asc"
    assert query["top"] == 77


# ---- canonical GUID handling (hex-letter GUIDs: digit-only GUIDs cannot expose case bugs) -----

HEX_ORG = "ABCDEF01-0000-0000-0000-000000000001"
HEX_OTHER_ORG = "ABCDEF01-0000-0000-0000-000000000002"
HEX_A = "ABCDEF00-0000-0000-0000-000000000001"
HEX_B = "ABCDEF00-0000-0000-0000-000000000002"


def _hexless(value):
    return value.replace("-", "")


def test_hex_case_duplicate_catalog_ref_key_is_fact_invalid_not_a_pair():
    assert HEX_A.upper() != HEX_A.lower()  # the fixture really differs by case
    result = run(
        [cat(HEX_A.upper(), "Same"), cat(HEX_A.lower(), "same")], activity=act(HEX_A.lower()))
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_FACT_INVALID")
    assert result["groups"] == [] and result["candidate_count"] == 0


@pytest.mark.parametrize("form", ["braced", "hyphenless", "urn"])
def test_catalog_duplicate_in_different_textual_form_is_fact_invalid(form):
    variant = {
        "braced": "{" + HEX_A.lower() + "}", "hyphenless": _hexless(HEX_A).lower(),
        "urn": "urn:uuid:" + HEX_A.upper(),
    }[form]
    result = run([cat(HEX_A.lower(), "Same"), cat(variant, "same")], activity=act(HEX_A))
    assert result["reason"] == "COUNTERPARTY_FACT_INVALID"


@pytest.mark.parametrize("company", [
    HEX_ORG.upper(), HEX_ORG.lower(), "{" + HEX_ORG + "}", _hexless(HEX_ORG),
    _hexless(HEX_ORG).lower(), "urn:uuid:" + HEX_ORG,
])
def test_company_id_in_any_textual_form_matches_lower_case_row_scope(company):
    activity = act(HEX_A, HEX_B, company=HEX_ORG.lower())
    result = run([cat(HEX_A, "Same"), cat(HEX_B, "same")], activity=activity, company=company)
    assert (result["status"], result["reason"]) == ("FINDING", "DUPLICATE_CANDIDATES_FOUND")


@pytest.mark.parametrize("row_value", [
    HEX_ORG.upper(), "{" + HEX_ORG.lower() + "}", _hexless(HEX_ORG).upper(),
])
def test_row_company_value_in_any_textual_form_matches_company(row_value):
    activity = act(HEX_A, HEX_B, company=row_value)
    result = run([cat(HEX_A, "Same"), cat(HEX_B, "same")], activity=activity,
                 company=HEX_ORG.lower())
    assert result["status"] == "FINDING"


@pytest.mark.parametrize("company", [HEX_ORG.upper(), "{" + HEX_ORG + "}", _hexless(HEX_ORG)])
def test_row_for_another_company_guid_is_scope_mismatch_in_every_company_form(company):
    activity = act(HEX_A, company=HEX_ORG.lower()) + act(HEX_B, company=HEX_OTHER_ORG.lower())
    result = run([cat(HEX_A, "Same"), cat(HEX_B, "same")], activity=activity, company=company)
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COMPANY_SCOPE_MISMATCH")
    assert result["groups"] == []


@pytest.mark.parametrize("bad", [None, 5, True, ["x"], "", "not-a-guid"])
def test_row_company_value_not_a_guid_string_is_scope_mismatch(bad):
    activity = [{"Counterparty_Key": HEX_A, SCOPE: bad}]
    result = run([cat(HEX_A, "Same")], activity=activity, company=HEX_ORG)
    assert result["reason"] == "COMPANY_SCOPE_MISMATCH"


def test_non_guid_company_id_is_rejected_as_unconfirmed_mapping():
    with pytest.raises(SemanticMappingUnconfirmed):
        run([cat(HEX_A, "Same")], activity=act(HEX_A), company="not-a-guid")


def test_activity_guid_case_differs_from_catalog_case_still_matches():
    catalog = [cat(HEX_A.upper(), "Same"), cat(HEX_B.lower(), "same")]
    result = run(catalog, activity=act(HEX_A.lower(), HEX_B.upper(), company=HEX_ORG.lower()),
                 company=HEX_ORG.upper())
    assert result["status"] == "FINDING"
    assert ids(result) == [[HEX_A.upper(), HEX_B.lower()]]  # raw catalog text is echoed as-is


def test_members_sorted_case_insensitively_by_canonical_guid():
    upper_first = "BBBBBBBB-0000-0000-0000-000000000001"
    lower_second = "aaaaaaaa-0000-0000-0000-000000000001"
    assert sorted([upper_first, lower_second]) == [upper_first, lower_second]  # raw sort differs
    for catalog in ([cat(upper_first, "Same"), cat(lower_second, "same")],
                    [cat(lower_second, "same"), cat(upper_first, "Same")]):
        assert ids(run(catalog)) == [[lower_second, upper_first]]


def test_zero_guid_catalog_row_is_ignored_and_never_a_duplicate_partner():
    catalog = [cat(ZERO, "Same"), cat(A, "same")]
    result = run(catalog, activity=act(ZERO, A))
    assert (result["status"], result["reason"]) == ("PASS", "NO_DUPLICATE_CANDIDATES")
    assert result["groups"] == [] and result["candidate_count"] == 0
    # control: the same name on a real in-scope counterparty still groups
    assert run([cat(B, "Same"), cat(A, "same")], activity=act(B, A))["status"] == "FINDING"


@pytest.mark.parametrize("bad_ref", ["not-a-guid", "", " ", "{A}", "12345", "xyz" * 12])
def test_non_guid_catalog_ref_key_is_fact_invalid_even_outside_activity(bad_ref):
    result = run([cat(HEX_A, "x"), cat(bad_ref, "y")], activity=act(HEX_A))
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_FACT_INVALID")


def test_braced_pair_with_lower_case_twin_is_fact_invalid():
    result = run([cat("{" + HEX_A + "}", "Same"), cat(HEX_A.lower(), "same")],
                 activity=act(HEX_A))
    assert result["reason"] == "COUNTERPARTY_FACT_INVALID"


@pytest.mark.parametrize("form", ["braced", "hyphenless", "urn"])
def test_in_scope_duplicate_pair_with_non_canonical_ref_text_is_still_a_finding(form):
    wrap = {
        "braced": lambda v: "{" + v + "}", "hyphenless": _hexless,
        "urn": lambda v: "urn:uuid:" + v,
    }[form]
    first, second = wrap(HEX_A.lower()), wrap(HEX_B.upper())
    result = run([cat(first, "Same"), cat(second, "SAME")], activity=act(HEX_A, HEX_B))
    assert result["status"] == "FINDING"
    assert ids(result) == [[first, second]]


# ---- lone surrogates ----------------------------------------------------------------------

@pytest.mark.parametrize("field", ["name", "code", "ref"])
def test_lone_surrogate_in_a_catalog_field_is_fact_invalid_without_exception(field):
    row = cat(A, "Acme", "C1")
    if field == "name":
        row["Description"] = "Acme\ud800"
    elif field == "code":
        row["Code"] = "C\udfff1"
    else:
        row["Ref_Key"] = A + "\ud800"
    result = run([row, cat(B, "Acme")], activity=act(A, B))
    assert (result["status"], result["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_FACT_INVALID")
    assert result["groups"] == []


def test_lone_surrogate_name_never_reaches_a_serialisable_group():
    ok = run([cat(A, "Acme"), cat(B, "Acme")])
    assert ok["status"] == "FINDING"
    bad = run([cat(A, "Acme\ud800"), cat(B, "Acme")])
    assert bad["status"] == "INCONCLUSIVE" and bad["groups"] == []


# ---- normalisation table ------------------------------------------------------------------

@pytest.mark.parametrize("left,right", [
    ("Acme LLC", "Acme"), ("Customer 1", "Customer 2"), ("Alpha Beta", "Beta Alpha"),
    ("Café", "Cafe"),
])
def test_names_that_must_not_group(left, right):
    assert normalize_name(left) != normalize_name(right)
    result = run([cat(A, left), cat(B, right)])
    assert (result["status"], result["groups"]) == ("PASS", [])


def test_casefold_and_nfkc_keys_are_pinned_to_the_real_implementation():
    assert normalize_name("Straße") == "strasse" == normalize_name("STRASSE")
    assert "Straße".lower() != normalize_name("Straße")  # lower() would keep the sharp s
    assert ids(run([cat(A, "Straße"), cat(B, "STRASSE")])) == [[A, B]]
    composed, combining = "Café", "Café"
    assert composed != combining
    assert normalize_name(composed) == normalize_name(combining) == "café"
    # without NFKC the combining accent is a non-word separator and would yield "cafe"
    assert normalize_name(combining) != "cafe"
    assert ids(run([cat(A, composed), cat(B, combining)])) == [[A, B]]


# ---- extra validator rejections -----------------------------------------------------------

def _without(key, mapping=MAPPING):
    return {k: v for k, v in mapping.items() if k != key}


def _activity_without(key):
    return mutated(company_activity={
        k: v for k, v in MAPPING["company_activity"].items() if k != key})


def _with_output(**changes):
    return mutated(output_fields={**MAPPING["output_fields"], **changes})


def _extra_bad_mappings():
    yield "scope extra key", _with_scope(extra=1)
    yield "scope not a dict", _with_activity(company_scope="Организация_Key")
    yield "scope None", _with_activity(company_scope=None)
    yield "scope missing field", _with_activity(company_scope={"value_type": "guid"})
    yield "company_activity missing", _without("company_activity")
    yield "company_activity None", mutated(company_activity=None)
    yield "company_activity list", mutated(company_activity=["x"])
    yield "activity missing counterparty_field", _activity_without("counterparty_field")
    yield "activity missing entity_set", _activity_without("entity_set")
    yield "activity entity_set non-string", _with_activity(entity_set=5)
    yield "empty counterparty_field", _with_activity(counterparty_field="")
    yield "counterparty_field non-string", _with_activity(counterparty_field=None)
    yield "counterparty_field with space", _with_activity(counterparty_field="Counterparty Key")
    yield "counterparty_field with quote", _with_activity(counterparty_field="Counterparty'Key")
    yield "counterparty_field with slash", _with_activity(counterparty_field="Counterparty/Key")
    yield "scope field empty", _with_scope(field="")
    yield "scope field with space", _with_scope(field="Org Key")
    yield "scope field with quote", _with_scope(field="Org'Key")
    yield "scope field with slash", _with_scope(field="Org/Key")
    yield "scope field non-string", _with_scope(field=7)
    yield "output name with space", _with_output(name="Desc ription")
    yield "output name with quote", _with_output(name="Desc'ription")
    yield "output name with slash", _with_output(name="Desc/ription")
    yield "output name with newline", _with_output(name="Description\n")
    yield "output name empty", _with_output(name="")
    yield "output_fields not a dict", mutated(output_fields=["Ref_Key", "Code", "Description"])
    yield "register entity with space", _with_activity(entity_set="AccumulationRegister_A B")
    yield "catalog entity with slash", mutated(entity_set="Catalog_Counterparties/x")
    yield "bare Catalog_ prefix", mutated(entity_set="Catalog_")
    yield "value_type uppercase", _with_scope(value_type="GUID")


@pytest.mark.parametrize("label,mapping", list(_extra_bad_mappings()))
def test_validator_rejects_more_bad_mappings_with_the_domain_error(label, mapping):
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_duplicate_mapping(mapping)  # never a TypeError/KeyError


# ---- scoping guard and the accepted empty-scan limitation ----------------------------------

def test_out_of_scope_counterparty_sharing_the_normalised_name_is_not_reported():
    catalog = [cat(HEX_A, "Acme Ltd."), cat(HEX_B, "ACME LTD"), cat(C, "acme ltd")]
    only_in_scope = run(catalog, activity=act(HEX_A, HEX_B))
    assert ids(only_in_scope) == [[HEX_A, HEX_B]] and only_in_scope["candidate_count"] == 2
    assert C not in str(only_in_scope)
    lone = run(catalog, activity=act(HEX_A))
    assert (lone["status"], lone["groups"], lone["candidate_count"]) == ("PASS", [], 0)
    # activity of another counterparty only: nothing of the namesake trio is in scope
    assert run(catalog, activity=act(D))["status"] == "PASS"


@pytest.mark.parametrize("activity", [
    [], act(None), act(""), act(ZERO), act(None, "", ZERO),
])
def test_documented_limitation_empty_activity_scan_is_pass_per_contract_section_8(activity):
    """Documents an ACCEPTED LIMITATION, not a desired feature.

    An activity scan that returns no usable counterparty (empty, or only null/empty/zero party
    values) is PASS NO_DUPLICATE_CANDIDATES with group_count 0 per contract section 8 (see
    DECISION_LOG). It cannot tell 'company has no activity' from 'activity not recorded'. If the
    contract is ever changed, this test must change with it.
    """
    result = run([cat(A, "Same"), cat(B, "same")], activity=activity)
    assert (result["status"], result["reason"]) == ("PASS", "NO_DUPLICATE_CANDIDATES")
    assert (result["group_count"], result["candidate_count"], result["groups"]) == (0, 0, [])
