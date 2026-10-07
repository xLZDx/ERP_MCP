"""Offline tests of the per-story evaluator: observations in, one truthful disposition out (no live 1C needed)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.real1c.catalog import load_catalog
from scripts.real1c.disposition import PASS
from scripts.real1c.probes import GATED_TOOLS, TOOL_ABBR
from scripts.real1c.run_lane import sweep_outputs
from scripts.real1c.schema import validate_case_result
from scripts.real1c.stories import CUSTOM, evaluate_story

CATALOG = Path(__file__).resolve().parents[2] / "docs" / "REAL_1C_STORY_CATALOG_818HA.md"
BASE = {"schema_version": 1, "git_sha": "a" * 40, "manifest_sha256": "b" * 64, "finished_at": "2026-10-07T10:00:00+03:00"}
SRC = "onec-818ha-reference"


def _gate(refused: bool = True, data: bool = False) -> dict:
    return {a: {"tool": TOOL_ABBR[a], "is_error": refused, "detail_code": "SEMANTIC_PROFILE_UNVALIDATED" if refused else None,
                "outcome": "denied", "refused": refused, "data_returned": data} for a in GATED_TOOLS}


def _ev(*, refused: bool = True, data: bool = False, surface: str = "companies_list onec_read", paging: bool = False) -> dict:
    cases = [{"case": c, "is_error": True, "detail": "InvalidRequest", "rows": None}
             for c in ("action_post", "batch_endpoint", "absolute_url", "path_traversal")]
    return {
        "gate": _gate(refused, data),
        "disc": {"surface": surface, "count": 23, "names": [], "mutating_names": [], "tools": []},
        "evtool": {"status": "EVIDENCE_REQUIRED", "audit": {}, "business_acceptance": None,
                   "native_approval_inferred": None, "evidence_required": True, "data_returned": False},
        "write": {"cases": cases, "tool_names_mutating": [], "upstream_methods": ["GET"], "refused_methods": {},
                  "upstream_write_seen": False, "paths": {}},
        "zero_write": {"pre": "p" * 64, "post": "p" * 64, "fingerprint_equal": True, "table_count": 1, "total_rows": 1,
                       "upstream_write_seen": False, "methods": {"GET": 3}},
        "acl": {"cross_source_denied": {"detail": "AccessDenied"}, "revoke_mid_session": {
            "revoke_http": 200, "before_detail": "SEMANTIC_PROFILE_UNVALIDATED", "after_detail": "AccessDenied", "regrant_http": 201}},
        "portfolio": {"companies_created": 150, "visible_to_one": 75, "visible_to_two": 75, "overlap": 0,
                      "union_equals_all": True, "list_seconds": 1.0, "paging_parameters_supported": paging},
        "related": {}, "expiring": {"create_http": 201, "during": "SEMANTIC_PROFILE_UNVALIDATED", "after_expiry": "AccessDenied"},
        "audit": {"calls_made": 3, "calls_with_audit_row": 3, "tamper": {"app:UPDATE": "InsufficientPrivilegeError"}},
        "malformed": {"cases": [], "unaudited": []},
        "secret": {"sources_scanned": ["gateway.out.log"], "hits": []},
        "drift": {"before": {"metadata_fingerprint": "1" * 64, "drift_status": "CLEAN"},
                  "after": {"metadata_fingerprint": "2" * 64, "drift_status": "DRIFTED"},
                  "read_while_drifted": {"is_error": True, "detail": "METADATA_DRIFTED"},
                  "after_restore": {"metadata_fingerprint": "1" * 64, "drift_status": "DRIFTED"}, "ack_http": 200},
        "outage": {"fan_out": {SRC: {"is_error": False, "seconds": 0.5, "payload": {"ok": True}},
                               "onec-818ha-drift": {"is_error": False, "seconds": 6.5, "payload": {"ok": True}},
                               "onec-818ha-down": {"is_error": False, "seconds": 0.4, "payload": {"ok": False}}},
                   "read_during_outage": {"is_error": True, "detail": "OneCTransportError"},
                   "recovered_health": {"payload": {"ok": True}},
                   "read_after_recovery": {"is_error": False, "rows": 1}},
        "identity": {"product_reports_identity_privilege": False, "reader_com_write_probe": "PASS_WRITE_DENIED",
                     "reader_probe_rolled_back": True},
    }


@pytest.fixture(scope="module")
def cat():
    return load_catalog(CATALOG)


def _by_id(cat, ev):
    return {s.id: evaluate_story(s, ev, BASE) for s in cat.stories}


def test_every_story_gets_a_schema_valid_result(cat):
    results = _by_id(cat, _ev())
    assert len(results) == 130
    assert [e for r in results.values() for e in validate_case_result(r)] == []


def test_only_rr_stories_with_a_real_observation_can_pass(cat):
    results = _by_id(cat, _ev())
    classes = {s.id: s.catalogue_class for s in cat.stories}
    passed = {i for i, r in results.items() if r["disposition"] == PASS}
    assert passed and all(classes[i] == "RR" for i in passed)
    assert passed <= set(CUSTOM)


def test_gated_tool_refusal_is_reported_as_unvalidated_profile_not_pass(cat):
    results = _by_id(cat, _ev(refused=True))
    st016 = results["ST-016"]
    assert st016["disposition"] == "SEMANTIC_PROFILE_UNVALIDATED"
    assert st016["owner_action"]


def test_data_without_profile_is_a_finding_for_np_stories(cat):
    results = _by_id(cat, _ev(refused=False, data=True))
    np_with_gated_tool = [s.id for s in cat.stories if s.catalogue_class == "NP" and any(t in GATED_TOOLS for t in s.tools)]
    assert np_with_gated_tool
    assert all(results[i]["disposition"] == "FINDING" for i in np_with_gated_tool)


def test_write_deferred_stories_are_refused_writes(cat):
    results = _by_id(cat, _ev())
    assert {r["disposition"] for i, r in results.items() if i in {s.id for s in cat.stories if s.catalogue_class == "WD"}} == {
        "REFUSED-WRITE"}


def test_write_effect_turns_wd_into_finding(cat):
    ev = _ev()
    ev["zero_write"] = {**ev["zero_write"], "fingerprint_equal": False}
    results = _by_id(cat, ev)
    assert results["ST-068"]["disposition"] == "FINDING"
    assert results["ST-084"]["disposition"] == "FINDING"


def test_capability_found_in_surface_is_a_finding_for_unsupported_stories(cat):
    results = _by_id(cat, _ev(surface="consolidation intercompany dry-run"))
    assert results["AX-008"]["disposition"] == "FINDING"
    assert results["ST-073"]["disposition"] == "FINDING"


def test_portfolio_story_needs_paging_to_pass(cat):
    assert _by_id(cat, _ev(paging=False))["ST-075"]["disposition"] == "FINDING"
    assert _by_id(cat, _ev(paging=True))["ST-075"]["disposition"] == PASS


def test_secret_hit_fails_the_hygiene_story(cat):
    ev = _ev()
    ev["secret"]["hits"] = [{"where": "gateway.out.log", "kind": "credential_assignment"}]
    assert _by_id(cat, ev)["ST-083"]["disposition"] == "FINDING"


def test_sweep_flags_literal_secret_and_assignment_patterns():
    hits = sweep_outputs({"a": "ok text", "b": "has hunter2-literal inside", "c": "password=abc123"}, ["hunter2-literal"])
    assert {h["where"] for h in hits} == {"b", "c"}
    assert sweep_outputs({"a": "secret sweep clean; secret reference names only"}, ["x" * 8]) == []


# ----------------------------------------------------------------------------- one broken conjunct must break the PASS
def _mut(path, value):
    def apply(ev):
        node = ev
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return apply


BREAKERS = [
    ("ST-072", _mut(("acl", "revoke_mid_session", "after_detail"), "SEMANTIC_PROFILE_UNVALIDATED")),
    ("ST-072", _mut(("acl", "revoke_mid_session", "revoke_http"), 500)),
    ("ST-072", _mut(("acl", "revoke_mid_session", "regrant_http"), 500)),
    ("ST-072", _mut(("acl", "revoke_mid_session", "before_detail"), "AccessDenied")),
    ("ST-075", _mut(("portfolio", "overlap"), 1)),
    ("ST-075", _mut(("portfolio", "union_equals_all"), False)),
    ("ST-075", _mut(("portfolio", "companies_created"), 149)),
    ("ST-076", _mut(("audit", "calls_with_audit_row"), 2)),
    ("ST-076", _mut(("audit", "tamper"), {"app:TRUNCATE": "ALLOWED"})),
    ("ST-076", _mut(("malformed", "unaudited"), ["x"])),
    ("ST-079", _mut(("drift", "after_restore", "drift_status"), "CLEAN")),
    ("ST-079", _mut(("drift", "ack_http"), 500)),
    ("ST-079", _mut(("drift", "read_while_drifted", "detail"), "OneCError")),
    ("ST-079", _mut(("drift", "after", "metadata_fingerprint"), "1" * 64)),
    ("ST-081", _mut(("outage", "fan_out", "onec-818ha-drift", "seconds"), 0.2)),  # slow fault not effective
    ("ST-081", _mut(("outage", "fan_out", "onec-818ha-reference", "seconds"), 7.0)),
    ("ST-081", _mut(("outage", "fan_out", "onec-818ha-down", "payload"), {"ok": True})),
    ("ST-081", _mut(("outage", "fan_out", "onec-818ha-reference", "is_error"), True)),
    ("ST-083", _mut(("secret", "sources_scanned"), ["only-one"])),
    ("ST-084", _mut(("zero_write", "methods"), {})),
    ("ST-084", _mut(("zero_write", "upstream_write_seen"), True)),
    ("ST-086", _mut(("outage", "read_during_outage", "detail"), "SomethingElse")),
    ("ST-086", _mut(("outage", "recovered_health", "payload"), {"ok": False})),
    ("ST-086", _mut(("outage", "read_after_recovery", "rows"), 0)),
    ("ST-068", _mut(("write", "cases", 0, "is_error"), False)),
    ("ST-068", _mut(("write", "cases", 1, "transport_error"), True)),
    ("ST-068", _mut(("write", "cases", 2, "detail"), None)),
    ("ST-068", _mut(("write", "upstream_write_seen"), True)),
    ("ST-068", _mut(("zero_write", "methods"), {})),
]


def _with_secret_pass(ev):
    ev["portfolio"]["paging_parameters_supported"] = True
    ev["secret"]["sources_scanned"] = [f"s{i}" for i in range(12)]
    ev["outage"]["fan_out"]["onec-818ha-drift"]["seconds"] = 6.4
    ev["write"]["cases"] = [{"case": c, "is_error": True, "transport_error": False, "detail": "ValueError", "rows": None}
                            for c in ("action_post", "batch_endpoint", "absolute_url", "path_traversal")]
    return ev


@pytest.mark.parametrize(("story_id", "mutate"), BREAKERS)
def test_breaking_one_conjunct_breaks_the_pass(cat, story_id, mutate):
    ev = _with_secret_pass(_ev())
    story = next(s for s in cat.stories if s.id == story_id)
    baseline = evaluate_story(story, copy.deepcopy(ev), BASE)["disposition"]
    assert baseline in {PASS, "REFUSED-WRITE"}, f"baseline for {story_id} must be the success state, got {baseline}"
    broken = copy.deepcopy(ev)
    mutate(broken)
    assert evaluate_story(story, broken, BASE)["disposition"] not in {PASS, "REFUSED-WRITE"}


def test_st077_inconclusive_when_the_probe_itself_failed(cat):
    story = next(s for s in cat.stories if s.id == "ST-077")
    assert evaluate_story(story, _ev(), BASE)["disposition"] == "FINDING"  # capability works -> catalogue is wrong
    ev = _ev()
    ev["expiring"] = {"create_http": 500}
    assert evaluate_story(story, ev, BASE)["disposition"] == "INCONCLUSIVE"  # a failed probe is not "capability absent"


def test_mixed_gate_rows_are_not_a_blanket_refusal(cat):
    ev = _ev()
    ev["gate"]["ABT"] = {**ev["gate"]["ABT"], "refused": False, "data_returned": True, "is_error": False, "detail_code": None}
    story = next(s for s in cat.stories if s.id == "AX-040")  # tools ABT,APR
    assert evaluate_story(story, ev, BASE)["disposition"] != "SEMANTIC_PROFILE_UNVALIDATED"


def test_untyped_gate_answer_is_an_error_not_a_refusal(cat):
    ev = _ev()
    ev["gate"]["ARB"] = {**ev["gate"]["ARB"], "is_error": True, "detail_code": None, "refused": False, "transport_error": True}
    story = next(s for s in cat.stories if s.id == "ST-016")
    result = evaluate_story(story, ev, BASE)
    assert result["disposition"] == "ERROR" and not validate_case_result(result)


def test_evaluator_defect_becomes_error_on_that_story_only(cat):
    ev = _ev()
    del ev["drift"]
    results = _by_id(cat, ev)
    assert results["ST-079"]["disposition"] == "ERROR"
    assert results["ST-016"]["disposition"] == "SEMANTIC_PROFILE_UNVALIDATED"


def test_paging_observation_reflects_the_probe(cat):
    story = next(s for s in cat.stories if s.id == "ST-075")
    assert evaluate_story(story, _ev(paging=True), BASE)["observations"][1]["outcome"] == "supported"
    assert evaluate_story(story, _ev(paging=False), BASE)["observations"][1]["outcome"] == "none"
