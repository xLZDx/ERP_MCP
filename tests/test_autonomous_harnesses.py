from pathlib import Path

from scripts.capability_report import diff_reports, evidence_manifest
from scripts.docker_fault_runner import run as run_docker_plan
from scripts.fault_injection_runner import run as run_faults
from scripts.mutation_negative_pack import run as run_mutations
from scripts.performance_benchmark import run as run_benchmark
from scripts.rsv_lifecycle_harness import run as run_rsv
from scripts.scan_sensitive_artifacts import scan
from scripts.security_regression_pack import run as run_security
from scripts.ssrf_fuzz_matrix import run as run_ssrf
from scripts.validate_metrics import validate_rules, validate_text_format

ROOT = Path(__file__).parents[1]


def test_fault_and_rsv_harnesses_cover_recovery_without_1c():
    assert run_faults()["passed"] is True
    assert run_rsv()["passed"] is True
    assert run_faults()["real_1c_called"] is False
    assert run_docker_plan(ROOT, execute=False)["status"] == "NOT_RUN"


def test_performance_evidence_covers_all_required_sizes():
    evidence = run_benchmark()
    assert [row["registered_sources"] for row in evidence["results"]] == [30, 50, 100, 150]
    assert all(row["fanout_isolated"] for row in evidence["results"])
    assert evidence["capacity_decision"] == "EVIDENCE_ONLY_NOT_SIGNOFF"


def test_metrics_rules_and_text_privacy_contract():
    result = validate_rules(ROOT / "deploy/alerts/prometheus.rules.yml")
    assert result["lint"] == "PASS"
    validate_text_format("erp_mcp_http_requests_total{status=\"200\"} 1")


def test_security_pack_is_fail_closed():
    evidence = run_security()
    assert evidence["passed"] is True
    assert all(item["passed"] for item in evidence["cases"])
    assert run_ssrf()["passed"] is True
    assert run_mutations()["passed"] is True


def test_sensitive_artifact_scanner_rejects_secret_and_accepts_safe_file(tmp_path: Path):
    safe = tmp_path / "safe.json"
    safe.write_text('{"status":"sanitized_failure"}', encoding="utf-8")
    assert scan([safe]) == []
    secret = tmp_path / "secret.log"
    secret.write_text("Authorization: Bearer abcdefghijklmnop", encoding="utf-8")
    assert scan([secret]) == [str(secret)]


def test_capability_cli_helpers(tmp_path: Path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('[{"source_id":"s1","operation":"DrCrTurnovers","status":"UNSUPPORTED"}]')
    right.write_text('[{"source_id":"s1","operation":"DrCrTurnovers","status":"STALE"}]')
    assert diff_reports(left, right)[0]["after"]["status"] == "STALE"
    assert evidence_manifest(right)["stale"] == 1
