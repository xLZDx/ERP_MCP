from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.capability_report import build_report
from scripts.dependency_failure_matrix import validate_matrix
from scripts.release_evidence_bundle import build_bundle


def test_dependency_failure_matrix_is_fail_closed():
    cases = validate_matrix()
    assert len(cases) >= 6
    assert all(case.expected_status >= 400 for case in cases)


def test_capability_report_is_sorted_and_preserves_unsupported(tmp_path: Path):
    export = tmp_path / "capabilities.json"
    export.write_text(
        json.dumps(
            [
                {"source_id": "b", "operation": "DrCrTurnovers", "status": "UNSUPPORTED"},
                {"source_id": "a", "operation": "Balance", "status": "SUPPORTED"},
            ]
        ),
        encoding="utf-8",
    )
    report = build_report(export)
    assert [item["source_id"] for item in report] == ["a", "b"]
    assert report[1]["status"] == "UNSUPPORTED"


def test_release_bundle_is_non_secret_and_points_to_evidence():
    bundle = build_bundle(Path(__file__).parents[1])
    assert bundle["production_decision"] == "NO-GO_UNTIL_ALL_FROZEN_GATES_CLOSE"
    assert bundle["package_status"] == "INVENTORY_ONLY_NOT_ASSEMBLED"
    assert bundle["actual_image_digests"] is None
    assert bundle["secret_values_included"] is False
    assert "deploy/alerts/prometheus.rules.yml" in bundle["required_evidence"]


def test_capability_report_rejects_unknown_status(tmp_path: Path):
    export = tmp_path / "capabilities.json"
    export.write_text(json.dumps([{"source_id": "a", "status": "GUESS"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="status"):
        build_report(export)
