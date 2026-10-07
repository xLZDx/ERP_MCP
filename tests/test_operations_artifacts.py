from __future__ import annotations

from pathlib import Path

from scripts.check_report_references import check
from scripts.validate_performance_evidence import validate


def test_fault_injection_and_runbook_artifacts_are_present():
    root = Path(__file__).parents[1]
    check(root)
    assert (root / "deploy/fault-injection.compose.yml").is_file()
    assert (root / "deploy/runbooks/ALERT_RESPONSE.md").is_file()
    assert (root / "deploy/runbooks/DEPENDENCY_FAILURE_MATRIX.md").is_file()


def test_performance_evidence_is_not_capacity_signoff():
    result = validate(
        {
            "real_1c_called": False,
            "results": [
                {"registered_sources": 30, "elapsed_ms": 10, "batch_p95_ms": 4, "throughput_sources_per_second": 3},
                {"registered_sources": 150, "elapsed_ms": 30, "batch_p95_ms": 6, "throughput_sources_per_second": 5},
            ],
        }
    )
    assert result["capacity_decision"] == "EVIDENCE_ONLY_NOT_SIGNOFF"
