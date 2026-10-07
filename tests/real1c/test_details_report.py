"""Per-test documentation: call selection and the HTML builder (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.real1c import documentation
from scripts.real1c.catalog import load_catalog
from scripts.real1c.details_report import WHY, build_details
from scripts.real1c.stories import evaluate_story
from tests.real1c.test_stories import BASE, _ev

CATALOG = Path(__file__).resolve().parents[2] / "docs" / "REAL_1C_STORY_CATALOG_818HA.md"


@pytest.fixture(scope="module")
def cat():
    return load_catalog(CATALOG)


def _call(probe, tool, **args):
    return {"probe": probe, "principal": "user_company_one", "tool": tool, "arguments": args, "is_error": True,
            "transport_error": False, "ms": 5, "audit_outcome": "denied", "detail_code": "SEMANTIC_PROFILE_UNVALIDATED",
            "returned_items": 0, "response": {"text": "Error executing tool"}}


def _full_ev():
    ev = _ev()
    ev["call_log"] = [_call("gate", "accounting_balance_and_turnovers", source_id="s"), _call("evtool", "external_evidence_manifest"),
                      _call("write", "onec_read", entity_set="$batch"), _call("outage", "source_health", source_id="x")]
    ev["query_log"] = [("NR-02", 'ВЫБРАТЬ 1 ГДЕ Т.НомерВходящегоДокумента = "SECRET-NO-1"')]
    return ev


def test_catalog_exposes_expected_and_negative(cat):
    st010 = next(s for s in cat.stories if s.id == "ST-010")
    assert "no gap/duplicate" in st010.expected
    ax = next(s for s in cat.stories if s.id == "AX-004")
    assert ax.negative


def test_call_selection_by_class_and_probe():
    ev = _full_ev()
    assert documentation.select("ST-016", "ST", "RR", ("ABT",), ev)["calls"][0]["tool"] == "accounting_balance_and_turnovers"
    assert documentation.select("ST-029", "ST", "EV", ("EVM",), ev)["calls"][0]["tool"] == "external_evidence_manifest"
    assert documentation.select("ST-068", "ST", "WD", (), ev)["calls"][0]["tool"] == "onec_read"
    assert documentation.select("ST-081", "ST", "RR", (), ev)["calls"][0]["tool"] == "source_health"
    ug = documentation.select("ST-002", "ST", "UG", (), ev)
    assert ug["calls"] == [] and "No request is sent" in ug["channel_note"]
    assert "ST-083" in documentation.CHANNEL_NOTES and documentation.select("ST-083", "ST", "RR", (), ev)["calls"] == []


def test_query_documentation_masks_owner_identifiers():
    out = documentation.select("NR-02", "NR", None, (), _full_ev())
    assert "SECRET-NO-1" not in out["queries"][0]["text"] and "<sha8:" in out["queries"][0]["text"]


def test_call_cap_is_reported():
    ev = _full_ev()
    ev["call_log"] = [_call("gate", "accounting_balance_and_turnovers") for _ in range(9)]
    out = documentation.select("ST-016", "ST", "RR", ("ABT",), ev)
    assert len(out["calls"]) == documentation.MAX_CALLS and out["calls_total"] == 9


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_details_report_has_one_section_per_case_and_no_secret_shapes(cat, lang):
    ev = _full_ev()
    results = []
    for s in cat.stories:
        r = evaluate_story(s, ev, BASE)
        r.update(documentation.select(s.id, s.kind, s.catalogue_class, s.tools, ev))
        r.update({"question": s.title, "expected": s.expected, "negative": s.negative})
        results.append(r)
    page = build_details(results, cat, "a" * 40, "2026-10-07T10:00:00+03:00", lang=lang, summary_href="x.html")
    assert page.count('class="card"') == 130
    assert "<header>" in page and f'lang="{lang}"' in page
    assert all(r["case_id"] in page for r in results)


def test_every_reason_code_the_lane_can_emit_is_explained():
    emitted = {"profile_gate_refusal", "oracle_match", "oracle_mismatch", "capability_absent_confirmed", "evidence_required_observed",
               "write_refused", "capability_present_but_catalogued_unsupported", "com_agrees_native_ui_report_required",
               "com_disagrees_with_candidate_assertion", "head_metadata_rejected_by_1c", "malformed_calls_not_audited",
               "identity_privilege_not_reported", "no_paging_arguments", "literal_secret_refused_untyped", "validation_refused",
               "error", "profile_gate_not_observed", "capability_not_confirmed", "not_computable_by_com"}
    assert emitted <= set(WHY) and all({"en", "ru"} <= set(v) for v in WHY.values())
