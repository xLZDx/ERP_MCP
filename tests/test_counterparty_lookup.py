"""Counterparty lookup / name resolution over the real-shaped Catalog_Контрагенты profile."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from business_ai_gateway.analytics_balance import compute_account_totals
from business_ai_gateway.counterparty_lookup import (
    COUNTERPARTY_LOOKUP_CONCEPT,
    build_lookup_query,
    build_refs_filter,
    evaluate_lookup,
    index_names,
    normalize_search_text,
    validate_counterparty_lookup_mapping,
)
from business_ai_gateway.fixture_profiles import ProvisionalProfiles
from business_ai_gateway.semantic import SemanticMappingUnconfirmed

PROFILE = Path(__file__).resolve().parents[1] / "testbed" / "real1c" / "provisional_profiles_818ha.json"
COMPANY = uuid.UUID("3e31afc5-351f-4f36-8074-99129fa3d911")
MOLD_REF = "0ef98609-57ad-11ee-aa2f-d85ed30dc416"
OTHER_REF = "6b48d7c7-8237-11ee-aa36-d85ed30dc416"


@pytest.fixture(scope="module")
def mapping():
    provider = ProvisionalProfiles(PROFILE, hashlib.sha256(PROFILE.read_bytes()).hexdigest(), environment="test")
    return provider.lookup("onec-818ha-reference", COMPANY, COUNTERPARTY_LOOKUP_CONCEPT)


def cat(ref, name, code="000000001", deleted=False, folder=False):
    return {"Ref_Key": ref, "Code": code, "Description": name, "DeletionMark": deleted, "IsFolder": folder}


def test_committed_profile_is_valid(mapping):
    assert validate_counterparty_lookup_mapping(mapping) == "Catalog_Контрагенты"


@pytest.mark.parametrize("patch", [
    {"entity_set": "InformationRegister_X"},
    {"entity_set": "Catalog_X/../Y"},
    {"max_results": 0}, {"max_results": 51}, {"max_results": True},
    {"required_register_capabilities": [{"entity_set": "A", "method": "balance"}]},
    {"extra": 1},
    {"output_fields": {"ref": "Ref_Key", "code": "Code", "name": "Code", "deleted": "D", "folder": "F"}},
    {"output_fields": {"ref": "Ref_Key", "code": "Code", "name": "x eq 1 or y", "deleted": "D", "folder": "F"}},
])
def test_bad_mapping_fails_closed(mapping, patch):
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_counterparty_lookup_mapping({**mapping, **patch})


@pytest.mark.parametrize("bad", [None, 5, "", "a", "x" * 65, "ab\x00cd", "ab\ncd\x07"])
def test_search_text_is_bounded(bad):
    with pytest.raises(ValueError):
        normalize_search_text(bad)


def test_query_escapes_quotes_and_never_takes_names_from_caller(mapping):
    entity, select, flt, limit = build_lookup_query(mapping, "O'Brien' or 1 eq 1")
    assert entity == "Catalog_Контрагенты"
    assert flt == "substringof('O''Brien'' or 1 eq 1', Description)"
    assert select == ["Ref_Key", "Code", "Description", "DeletionMark", "IsFolder"]
    assert limit == mapping["max_results"] + 1


def test_refs_filter_accepts_only_guids(mapping):
    assert build_refs_filter(mapping, [MOLD_REF.upper()]) == f"Ref_Key eq guid'{MOLD_REF}'"
    for bad in (["x"], ["' or 1 eq 1 or '"], [], [MOLD_REF] * 31, [7]):
        with pytest.raises(ValueError):
            build_refs_filter(mapping, bad)


def test_exact_match_is_case_insensitive(mapping):
    out = evaluate_lookup([cat(MOLD_REF, "MOLDRETAIL GROUP SRL")], mapping, "moldretail group srl")
    assert out["status"] == "EXACT"
    assert out["matches"] == [{"ref": MOLD_REF, "code": "000000001", "name": "MOLDRETAIL GROUP SRL",
                               "deleted": False, "folder": False}]


def test_partial_single_hit(mapping):
    out = evaluate_lookup([cat(MOLD_REF, "MOLDRETAIL GROUP SRL")], mapping, "moldretail")
    assert out["status"] == "PARTIAL" and out["match_count"] == 1


def test_ambiguous_partial_and_duplicate_exact(mapping):
    rows = [cat(MOLD_REF, "MOLDRETAIL GROUP SRL"), cat(OTHER_REF, "MOLDRETAIL TRADE SRL")]
    assert evaluate_lookup(rows, mapping, "moldretail")["status"] == "AMBIGUOUS"
    dup = [cat(MOLD_REF, "ACME"), cat(OTHER_REF, "acme")]
    assert evaluate_lookup(dup, mapping, "ACME")["status"] == "AMBIGUOUS"


def test_live_exact_beats_deleted_duplicate(mapping):
    rows = [cat(MOLD_REF, "ACME", deleted=True), cat(OTHER_REF, "ACME")]
    out = evaluate_lookup(rows, mapping, "acme")
    assert (out["status"], out["matches"][0]["ref"]) == ("EXACT", OTHER_REF)


def test_folders_are_never_matches_and_empty_is_not_found(mapping):
    assert evaluate_lookup([cat(MOLD_REF, "MOLDRETAIL", folder=True)], mapping, "moldretail")["status"] == "NOT_FOUND"
    assert evaluate_lookup([], mapping, "nobody")["status"] == "NOT_FOUND"


def test_source_hit_that_does_not_contain_text_is_dropped(mapping):
    assert evaluate_lookup([cat(MOLD_REF, "Other name")], mapping, "moldretail")["status"] == "NOT_FOUND"


def test_truncation_is_flagged(mapping):
    rows = [cat(str(uuid.uuid4()), f"ACME {i}") for i in range(mapping["max_results"] + 1)]
    out = evaluate_lookup(rows, mapping, "acme")
    assert out["truncated"] is True and out["match_count"] == mapping["max_results"]


@pytest.mark.parametrize("rows", ["x", [1], [{"Ref_Key": MOLD_REF}], [cat("nope", "A")]])
def test_malformed_catalog_response_fails_closed(mapping, rows):
    with pytest.raises(SemanticMappingUnconfirmed):
        evaluate_lookup(rows, mapping, "ab")


def test_index_names_by_lowercase_ref(mapping):
    index = index_names([cat(MOLD_REF.upper(), "MOLDRETAIL GROUP SRL", code="000000042", deleted=True)], mapping)
    assert index == {MOLD_REF: {"code": "000000042", "name": "MOLDRETAIL GROUP SRL", "deleted": True}}


def _row(account, debit, credit):
    return {"account": account, "balance_debit": debit, "balance_credit": credit}


def test_account_totals_are_exact_decimals():
    rows = [_row("521.1", "0", "452249.54"), _row("521.1", "264.6", "0"), _row("521.1", "0", "0.1"),
            _row("521.2", "1", "0")]
    totals = compute_account_totals(rows)
    assert totals[0] == {"account": "521.1", "balance_debit": "264.6", "balance_credit": "452249.64",
                         "net_credit": "451985.04", "row_count": 3}
    assert totals[1]["net_credit"] == "-1"


def test_account_totals_match_the_real_521_1_figure():
    credits = ["452249.54", "90230.56", "58200", "16600", "3600", "1509", "925.17"]
    rows = [_row("521.1", "0", value) for value in credits] + [_row("521.1", "264.6", "0")]
    assert compute_account_totals(rows)[0]["net_credit"] == "623049.67"
