"""Evidence-basis contract: machine two-source evidence is labelled, bound and never native."""

from __future__ import annotations

import copy
import uuid

import pytest

from business_ai_gateway.evidence_basis import (
    BASIS_MACHINE,
    BASIS_MIXED,
    BASIS_NATIVE,
    EvidenceBasisError,
    authorization_scope_sha256,
    check_machine_evidence_structure,
    require_native_basis,
    stored_evidence_basis,
)
from business_ai_gateway.fixture_profiles import MACHINE_PROFILE_KIND, profile_provenance
from business_ai_gateway.registry import Registry
from business_ai_gateway.semantic import (
    SemanticProfileUnavailable,
    canonical_fingerprint,
    require_usable_semantic_profile,
    validate_native_reconciliation_evidence,
)
from business_ai_gateway.settings import Settings

SOURCE = "onec-test-reference"
COMPANY = "11111111-1111-1111-1111-111111111111"
CONCEPT = "account.balance_by_analytics"
MAPPING = {"accounts": [{"code": "521.1"}], "analytics": ["counterparty", "contract"]}
META_FP = "a" * 64
CAP_FP = "b" * 64
PLAN_HASH = "c" * 64
AUTHORITY = f"ROSETTA_PLAN:plan-198889:{PLAN_HASH}"


def _record(side: str, method: str, as_of: str) -> dict:
    return {
        "run_id": str(uuid.uuid4()),
        "side": side,
        "source_identity": f"source-{side}",
        "method": method,
        "parameters": {"as_of": as_of, "account": "521.1"},
        "snapshot": {"kind": "database_copy", "identity": f"snap-{side}"},
        "started_at": "2026-10-08T10:00:00+00:00",
        "finished_at": "2026-10-08T10:00:05+00:00",
        "artifact_sha256": "d" * 64,
        "code_identity": {"git_head": "abc1234", "script_sha256": "e" * 64},
    }


def _case(index: int) -> dict:
    as_of = f"2025-{index + 1:02d}-28T23:59:59+00:00" if index < 12 else "2026-01-31T23:59:59+00:00"
    return {
        "case_id": f"case-{index}",
        "status": "PASS",
        "result": "MATCH",
        "as_of": as_of,
        "evidence_class": "MACHINE_TWO_SOURCE_RECONCILIATION",
        "comparison_kind": "cross_copy_comparison",
        "native_report_ref": f"machine-artifact:private/case-{index}.json",
        "authorized_by": AUTHORITY,
        "run_record_a": _record("A", "onec_query_com_v8", as_of),
        "run_record_b": _record("B", "mcp_tool_accounting_balance_by_analytics", as_of),
    }


def _machine_evidence() -> dict:
    return {
        "native_reconciliation_cases": [_case(i) for i in range(10)],
        "evidence_basis": BASIS_MACHINE,
        "machine_scope": {
            "source_id": SOURCE,
            "company_id": COMPANY,
            "concept": CONCEPT,
            "mapping_fingerprint": canonical_fingerprint(MAPPING),
            "metadata_fingerprint": META_FP,
            "capability_fingerprint": CAP_FP,
            "authorization_scope_sha256": authorization_scope_sha256(
                source_id=SOURCE, company_id=COMPANY, concept=CONCEPT, mapping=MAPPING
            ),
        },
    }


def _native_evidence() -> dict:
    return {
        "native_reconciliation_cases": [
            {
                "case_id": f"n{i}",
                "status": "PASS",
                "native_report_ref": f"report-{i}",
                "evidence_class": "NATIVE_UI_REPORT",
            }
            for i in range(10)
        ]
    }


def _check(evidence: dict, **overrides) -> str:
    kwargs = {
        "source_id": SOURCE,
        "company_id": COMPANY,
        "concept": CONCEPT,
        "mapping": MAPPING,
        "metadata_fingerprint": META_FP,
        "capability_fingerprint": CAP_FP,
    }
    kwargs.update(overrides)
    return check_machine_evidence_structure(evidence, **kwargs)


def test_machine_evidence_passes_and_is_not_native():
    evidence = _machine_evidence()
    assert _check(evidence) == BASIS_MACHINE
    with pytest.raises(EvidenceBasisError):
        require_native_basis(evidence)


def test_legacy_cases_without_class_are_native():
    legacy = {"native_reconciliation_cases": [{"case_id": "x", "status": "PASS"}]}
    assert stored_evidence_basis(legacy) == BASIS_NATIVE
    require_native_basis(legacy)


def test_mixed_cases_are_refused_at_runtime():
    evidence = _machine_evidence()
    evidence["native_reconciliation_cases"][0] = _native_evidence()["native_reconciliation_cases"][0]
    evidence.pop("evidence_basis")
    assert stored_evidence_basis(evidence) == BASIS_MIXED
    with pytest.raises(EvidenceBasisError):
        _check(evidence)


def test_contradictions_are_refused():
    native_with_scope = _native_evidence()
    native_with_scope["machine_scope"] = _machine_evidence()["machine_scope"]
    with pytest.raises(EvidenceBasisError):
        stored_evidence_basis(native_with_scope)

    machine_without_scope = _machine_evidence()
    machine_without_scope.pop("machine_scope")
    with pytest.raises(EvidenceBasisError):
        stored_evidence_basis(machine_without_scope)

    wrong_label = _machine_evidence()
    wrong_label["evidence_basis"] = BASIS_NATIVE
    with pytest.raises(EvidenceBasisError):
        stored_evidence_basis(wrong_label)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["native_reconciliation_cases"].pop(),  # fewer than ten
        lambda e: e["native_reconciliation_cases"][1].update(case_id="case-0"),  # duplicate case id
        lambda e: e["native_reconciliation_cases"][1].update(
            as_of=e["native_reconciliation_cases"][0]["as_of"]
        ),  # duplicate as_of
        lambda e: e["native_reconciliation_cases"][0].update(comparison_kind="parity"),
        lambda e: e["native_reconciliation_cases"][0].update(native_report_ref="report-1"),
        lambda e: e["native_reconciliation_cases"][0].update(result="DIFF"),
        lambda e: e["native_reconciliation_cases"][0].update(authorized_by="GO"),
        lambda e: e["native_reconciliation_cases"][0].update(
            authorized_by=f"ROSETTA_PLAN:plan-other-1:{'f' * 64}"
        ),  # two authorizations
        lambda e: e["native_reconciliation_cases"][0]["run_record_b"].update(
            run_id=e["native_reconciliation_cases"][0]["run_record_a"]["run_id"]
        ),  # same run id on both sides
        lambda e: e["native_reconciliation_cases"][0]["run_record_b"].update(
            method="onec_query_com_v8"
        ),
        lambda e: e["native_reconciliation_cases"][0]["run_record_b"]["parameters"].update(account="521.2"),
        lambda e: e["native_reconciliation_cases"][0]["run_record_a"].pop("code_identity"),
        lambda e: e["native_reconciliation_cases"][0]["run_record_a"].update(artifact_sha256="zz"),
        lambda e: e["machine_scope"].update(company_id="22222222-2222-2222-2222-222222222222"),
        lambda e: e["machine_scope"].update(mapping_fingerprint="0" * 64),
    ],
)
def test_structure_refusals(mutate):
    evidence = copy.deepcopy(_machine_evidence())
    mutate(evidence)
    with pytest.raises(EvidenceBasisError):
        _check(evidence)


def test_scope_is_bound_to_profile_fingerprints():
    evidence = _machine_evidence()
    with pytest.raises(EvidenceBasisError):
        _check(evidence, metadata_fingerprint="9" * 64)
    with pytest.raises(EvidenceBasisError):
        _check(evidence, capability_fingerprint="9" * 64)
    with pytest.raises(EvidenceBasisError):
        _check(evidence, mapping={"accounts": [{"code": "521.2"}]})


def test_native_validators_refuse_machine_evidence():
    evidence = _machine_evidence()
    with pytest.raises(ValueError):
        validate_native_reconciliation_evidence(evidence)
    assert len(validate_native_reconciliation_evidence(evidence, allow_machine=True)) == 10

    profile = {
        "source_id": SOURCE,
        "company_id": COMPANY,
        "status": "VALIDATED",
        "metadata_fingerprint": META_FP,
        "validation_evidence": evidence,
    }
    kwargs = {
        "source_id": SOURCE,
        "company_id": COMPANY,
        "metadata_fingerprint": META_FP,
        "drift_status": "STABLE",
    }
    with pytest.raises(SemanticProfileUnavailable):
        require_usable_semantic_profile(profile, **kwargs)


def test_machine_provenance_is_labelled():
    provenance = profile_provenance({"profile_kind": MACHINE_PROFILE_KIND})
    assert provenance["evidence_level"] == "PROFILE_VALIDATED_MACHINE"
    assert provenance["native_reconciliation"] == "MACHINE_TWO_SOURCE"
    assert "MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT" in provenance["warnings"]


def test_settings_allow_list_is_test_only():
    items = Settings(environment="test", machine_reconciled_sources="a-1, b.2").machine_reconciled_source_items
    assert items == ("a-1", "b.2")
    with pytest.raises(ValueError):
        Settings(environment="production", machine_reconciled_sources="a-1")
    with pytest.raises(ValueError):
        Settings(environment="test", machine_reconciled_sources="Bad Id")


def test_registry_refuses_machine_sources_in_production():
    with pytest.raises(ValueError):
        Registry(None, production=True, machine_reconciled_sources=("a-1",))
    assert Registry(None, production=False, machine_reconciled_sources=("a-1",)).machine_reconciled_sources == {"a-1"}


def test_capability_fingerprint_ignores_probe_timestamp_only():
    from business_ai_gateway.semantic import capability_evidence_fingerprint

    base = {"source_id": SOURCE, "registers": [{"entity_set": "R", "methods": {"balance": {"available": True}}}]}
    first = {**base, "discovered_at": "2026-10-07T23:42:44.788Z"}
    later = {**base, "discovered_at": "2026-10-08T05:00:00.000Z"}
    assert capability_evidence_fingerprint(first) == capability_evidence_fingerprint(later)
    assert capability_evidence_fingerprint(base) == canonical_fingerprint(base)  # fixtures without the stamp unchanged
    changed = {**later, "registers": [{"entity_set": "R", "methods": {"balance": {"available": False}}}]}
    assert capability_evidence_fingerprint(changed) != capability_evidence_fingerprint(later)


def test_uniqueness_compares_instants_and_uuids_not_spellings():
    evidence = _machine_evidence()
    first, second = evidence["native_reconciliation_cases"][0], evidence["native_reconciliation_cases"][1]
    second["as_of"] = first["as_of"].replace("+00:00", "+0000") if "+00:00" in first["as_of"] else first["as_of"]
    for side in ("run_record_a", "run_record_b"):
        second[side]["parameters"]["as_of"] = second["as_of"]
    with pytest.raises(EvidenceBasisError):
        _check(evidence)

    evidence = _machine_evidence()
    reused = evidence["native_reconciliation_cases"][0]["run_record_a"]["run_id"]
    evidence["native_reconciliation_cases"][1]["run_record_a"]["run_id"] = "{" + reused + "}"
    with pytest.raises(EvidenceBasisError):
        _check(evidence)
