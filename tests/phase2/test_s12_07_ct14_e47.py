"""S12-07 E47 contract coverage for the real, pinned offline CT14 record."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from business_ai_gateway.phase2.change import ct14_qualification

ROOT = Path(__file__).resolve().parents[2]
RECORD_PATH = Path("docs/phase2/artifacts/CT14_QUALIFICATION_RECORD_V1.json")


def _canonical_sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _copy_ct14_inputs(destination: Path) -> dict:
    record = json.loads((ROOT / RECORD_PATH).read_text(encoding="utf-8"))
    for source in record["sources"]:
        source_path = Path(source["path"])
        target = destination / source_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source_path, target)
    target_record = destination / RECORD_PATH
    target_record.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / RECORD_PATH, target_record)
    return record


def _write_mutated_record(root: Path, record: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    record_path = root / RECORD_PATH
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(ct14_qualification, "EXPECTED_RECORD_SHA256", _canonical_sha256(record_path.read_bytes()))


def test_e47_uses_the_actual_record_and_blocks_governed_create_draft():
    result = ct14_qualification.evaluate_e47(ROOT)

    assert result["operation"] == "CREATE_DRAFT"
    assert result["decision"] == "BLOCKED"
    assert result["evidence_status"] == "VERIFIED_BOUNDED_RECORD"
    assert result["technical_feasibility"] == "SUPPORTED"
    assert result["reason_codes"] == [
        "CT14_CAPABILITY_QUALIFIED_NOT_SATISFIED",
        "CT14_SCOPE_QUALIFIED_NOT_SATISFIED",
        "CT14_OPERATION_AUTHORIZED_NOT_SATISFIED",
    ]


def test_exact_measured_scope_still_requires_qualification_and_authority():
    requested_scope = {
        "clone": "818HA_p2diff",
        "database_type": "file",
        "platform_version": "8.3.27.2342",
        "configuration": "БухгалтерияДляМолдовы 3.0.67.1",
        "document_shape": "ПоступлениеТоваровУслуг",
        "channel": "COM",
    }

    result = ct14_qualification.evaluate_e47(ROOT, requested_scope=requested_scope)

    assert result["decision"] == "BLOCKED"
    assert result["evidence_status"] == "VERIFIED_BOUNDED_RECORD"
    assert result["reason_codes"] == [
        "CT14_CAPABILITY_QUALIFIED_NOT_SATISFIED",
        "CT14_SCOPE_QUALIFIED_NOT_SATISFIED",
        "CT14_OPERATION_AUTHORIZED_NOT_SATISFIED",
    ]


@pytest.mark.parametrize(("key", "wrong_value"), [
    ("clone", "another-base"),
    ("database_type", "client-server"),
    ("platform_version", "9.0.0.0"),
    ("configuration", "AnotherConfiguration 1.0"),
    ("document_shape", "AnotherDocument"),
    ("channel", "OData"),
])
def test_mismatched_scope_is_not_qualified_by_historical_clone_evidence(key: str, wrong_value: str):
    requested_scope = {
        "clone": "818HA_p2diff",
        "database_type": "file",
        "platform_version": "8.3.27.2342",
        "configuration": "БухгалтерияДляМолдовы 3.0.67.1",
        "document_shape": "ПоступлениеТоваровУслуг",
        "channel": "COM",
    }
    requested_scope[key] = wrong_value

    result = ct14_qualification.evaluate_e47(ROOT, requested_scope=requested_scope)

    assert result["decision"] == "BLOCKED"
    assert result["evidence_status"] == "NOT_VERIFIED"
    assert result["reason_codes"] == ["CT14_REQUESTED_SCOPE_MISMATCH"]


def test_record_binds_reviewed_sources_and_keeps_rights_revisions_distinct():
    record = json.loads((ROOT / RECORD_PATH).read_text(encoding="utf-8"))
    expected_reviewed = {
        "docs/phase2/S11_TEST_DESIGN_PACKAGE_2026-10-12.md": "a13c332a58cf3cb89cd526ad5a8011f16fa272311d7596995c0fdba038f35b1b",
        "docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md": "628d527a78cb699e8dc8e88050b92f414bb8e7ce29862edc546fb22e8f8124a6",
        "docs/phase2/artifacts/CT14_METADATA_INVENTORY_IVAN_2026-10-27.json": "13c4f98f30b6387e8b07df0719e1d20616e4ec4c237b07faa84699101c2f9283",
        "docs/phase2/artifacts/CT14_DRAFT_DESTINATION_TYPES_2026-10-27.json": "214896b219d37e23c67a2417c299aa12d5955e09eb3608b3ed4c6c94711c2425",
        "docs/phase2/artifacts/CT14_VAT_ENUMERATION_SEMANTICS_2026-10-27.json": "a86d9dc9a01040263529f088c58e3423329067633c782ed59776b549f4e6b55b",
        "docs/phase2/artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json": "7d34ba423197851f0e2fd16d65a47eed2bfd6b43090d0367dd5566ee97fdf310",
        "docs/phase2/artifacts/CT14_EFFECTIVE_RIGHTS_2026-10-27.json": "2f44531a67360b7e7388ca819ab4f796dedc54f214bbd21554509bd9e399f2a4",
    }
    assert {source["path"] for source in record["sources"]} == set(expected_reviewed)
    for source in record["sources"]:
        assert source["reviewed_sha256"] == expected_reviewed[source["path"]]
        assert _canonical_sha256((ROOT / source["path"]).read_bytes()) == source["canonical_sha256"]
        assert source["artifact_date"] in {"2026-10-12", "2026-10-27"}

    rights = {item["revision_id"]: item for item in record["rights_revisions"]}
    assert rights["CT14_SPIKE_2026-10-12"]["reported_right_entries"] == 53
    assert rights["CT14_EFFECTIVE_RIGHTS_2026-10-27"]["reported_committed_objects"] == 53
    assert rights["CT14_EXECUTOR_CLONE_FACTS_2026-10-27"]["reported_effective_object_count"] == 57
    assert rights["CT14_EXECUTOR_CLONE_FACTS_2026-10-27"]["added_read_rights"] == [
        "Organizations", "Counterparties", "Currencies", "Nomenclature",
    ]
    assert "exact identity" in rights["CT14_EFFECTIVE_RIGHTS_2026-10-27"]["scope"]


def test_unmeasured_capabilities_and_marker_limitation_are_preserved():
    record = json.loads((ROOT / RECORD_PATH).read_text(encoding="utf-8"))
    items = {item["item_id"]: item for item in record["capability_observations"]}

    for item_id in ("9", "10b", "13"):
        assert items[item_id]["status"] == "INCONCLUSIVE"
        assert items[item_id]["measurement_state"] == "NOT_MEASURED"
    assert "DENIED" in items["9"]["disposition"]
    assert "base-wide hold" in items["10b"]["disposition"]
    assert items["12-standard"]["status"] == "UNSUPPORTED"
    assert items["12-custom"]["status"] == "SUPPORTED"
    assert "mutable" in items["14"]["limitation"]


def test_missing_source_fails_closed_with_not_verified_reason(tmp_path: Path):
    _copy_ct14_inputs(tmp_path)
    (tmp_path / "docs/phase2/artifacts/CT14_EFFECTIVE_RIGHTS_2026-10-27.json").unlink()

    result = ct14_qualification.evaluate_e47(tmp_path)

    assert result["decision"] == "BLOCKED"
    assert result["evidence_status"] == "NOT_VERIFIED"
    assert "CT14_SOURCE_EVIDENCE_MISSING" in result["reason_codes"]


def test_stale_source_bytes_fail_closed(tmp_path: Path):
    _copy_ct14_inputs(tmp_path)
    source = tmp_path / "docs/phase2/artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json"
    source.write_bytes(source.read_bytes() + b" ")

    result = ct14_qualification.evaluate_e47(tmp_path)

    assert result["decision"] == "BLOCKED"
    assert result["evidence_status"] == "NOT_VERIFIED"
    assert "CT14_SOURCE_EVIDENCE_STALE" in result["reason_codes"]


def test_contradictory_observations_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    record = _copy_ct14_inputs(tmp_path)
    record["capability_observations"].append({
        "item_id": "1",
        "observation_id": "synthetic-conflict-for-E47-negative-case",
        "scope_id": "clone-818HA_p2diff-COM",
        "status": "UNSUPPORTED",
    })
    _write_mutated_record(tmp_path, record, monkeypatch)

    result = ct14_qualification.evaluate_e47(tmp_path)

    assert result["decision"] == "BLOCKED"
    assert result["evidence_status"] == "NOT_VERIFIED"
    assert "CT14_EVIDENCE_CONTRADICTORY" in result["reason_codes"]


@pytest.mark.parametrize(("source_path", "reason_code"), [
    ("docs/phase2/UNKNOWN_CT14_SOURCE.json", "CT14_SOURCE_MANIFEST_INVALID"),
    ("../../outside.json", "CT14_SOURCE_PATH_INVALID"),
])
def test_unknown_or_path_traversal_source_reference_fails_closed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_path: str, reason_code: str):
    record = _copy_ct14_inputs(tmp_path)
    record["sources"][0]["path"] = source_path
    _write_mutated_record(tmp_path, record, monkeypatch)

    result = ct14_qualification.evaluate_e47(tmp_path)

    assert result["decision"] == "BLOCKED"
    assert result["evidence_status"] == "NOT_VERIFIED"
    assert reason_code in result["reason_codes"]


