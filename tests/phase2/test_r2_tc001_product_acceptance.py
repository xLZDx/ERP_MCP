"""Focused contract-oracle and public stdio tests for R2-TC-001."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess

import pytest
from r2_tc001_oracle import DifferentialMismatch, _oracle_pair, negative_controls
from run_r2_tc001 import (
    DEFAULT_BASELINE,
    _shutdown_process,
    resolve_commit,
    run_scenario,
    serialize_differential_outcome,
)

EXPECTED_NEGATIVE_CONTROLS = {
    "removed_tool", "removed_property", "incompatible_field_type", "changed_required",
    "nested_schema_mutation", "additional_properties_true", "annotations_changed",
    "additional_properties_omitted",
    "unknown_argument_accepted", "misspelled_filter_reached_adapter", "valid_input_rejected",
    "success_mutation", "error_mutation", "missing_receipt", "misplaced_receipt",
    "completion_audit_outcome", "unauthorized_adapter_mutation",
}


def test_r2_tc001_oracle_rejects_every_required_contract_regression():
    checks = negative_controls()
    assert set(checks) == EXPECTED_NEGATIVE_CONTROLS
    assert all(checks.values())


def test_r2_tc001_nonzero_child_exit_cannot_be_accepted_as_evidence():
    class Stdin:
        def close(self):
            pass

        async def wait_closed(self):
            return None

    class Process:
        stdin = Stdin()
        returncode = 7

        async def wait(self):
            return self.returncode

        def kill(self):
            raise AssertionError("nonzero exit should be reported without a kill")

    async def check_exit():
        async def stderr():
            return b"deliberate child failure"

        task = asyncio.create_task(stderr())
        await _shutdown_process(Process(), task, "candidate")

    with pytest.raises(RuntimeError, match="candidate MCP process exited with 7.*deliberate child failure"):
        asyncio.run(check_exit())


def test_r2_tc001_real_differential_mismatch_is_serialized_as_fail_open(tmp_path):
    baseline, candidate = _oracle_pair()
    candidate["tools"][0]["inputSchema"]["properties"]["source_id"]["type"] = "integer"
    evidence_path = tmp_path / "differential-failure.json"
    evidence = {
        "test_harness": {"status": "PASS", "negative_controls": "PASS"},
        "product_acceptance_status": "OPEN",
    }

    with pytest.raises(DifferentialMismatch, match="incompatible input schema"):
        from r2_tc001_oracle import assert_r1_equivalent

        assert_r1_equivalent(baseline, candidate)

    result = serialize_differential_outcome(evidence, baseline, candidate, evidence_path)
    stored = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert result == stored
    assert stored["test_harness"]["status"] == "PASS"
    assert stored["differential_result"] == "FAIL"
    assert "incompatible input schema: source_health" in stored["differential_failure"]
    assert stored["product_acceptance_status"] == "OPEN"
    assert stored["overall_result"] == "HARNESS_PASS_PRODUCT_FAIL_OPEN"
    assert stored["runner_exit_code"] == 0


def test_r2_tc001_actual_exact_revision_scenario_records_harness_and_product_separately(tmp_path):
    evidence_path = tmp_path / "r2-tc001-evidence.json"
    candidate_commit = resolve_commit("HEAD")
    product_status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/business_ai_gateway/server.py",
         "src/business_ai_gateway/tool_errors.py"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert not product_status.strip(), "product changes must be committed before exact-HEAD acceptance"
    requested_candidate = os.environ.get("R2_TC001_CANDIDATE")
    if requested_candidate:
        assert resolve_commit(requested_candidate) == candidate_commit, (
            "R2_TC001_CANDIDATE differs from the current exact worktree HEAD"
        )
    evidence = run_scenario(DEFAULT_BASELINE, candidate_commit, evidence_path)
    assert resolve_commit("HEAD") == candidate_commit, "candidate HEAD changed during the scenario"
    stored = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert stored == evidence
    assert evidence["test_harness"] == {"status": "PASS", "negative_controls": "PASS"}
    assert evidence["contract_adjudication_request_id"] == "7fdc4c52-5de3-4d76-a3fa-f78e2b1073d4"
    assert {item["request_id"] for item in evidence["pm_contract_provenance"]} == {
        "11ad043a-0c66-473d-9bd6-5fe7e052a701",
        "5f38119f-3919-4a5d-a572-42a6b2bdf6d9",
        "bd092c6b-28d9-4a7f-9f47-2ce93e18908d",
        "7fdc4c52-5de3-4d76-a3fa-f78e2b1073d4",
    }
    assert evidence["runner_exit_code"] == 0
    assert evidence["product_acceptance_status"] in {"OPEN", "OPEN_PENDING_GPT_PM_ADJUDICATION"}
    assert evidence["differential_result"] in {"FAIL", "PASS"}
    assert evidence["baseline"]["commit"] == DEFAULT_BASELINE
    assert evidence["candidate"]["requested_ref"] == candidate_commit
    assert evidence["candidate"]["commit"] == candidate_commit
    assert evidence["fixture"]["sha256"]
    assert evidence["negative_controls"] == {name: True for name in sorted(EXPECTED_NEGATIVE_CONTROLS)}

    baseline = evidence["baseline_run"]
    candidate = evidence["candidate_run"]
    assert baseline["process"]["pid"] != candidate["process"]["pid"]
    assert baseline["process"]["transport"] == candidate["process"]["transport"] == "stdio"
    assert baseline["process"]["shutdown"]["exit_code"] == 0
    assert candidate["process"]["shutdown"]["exit_code"] == 0
    assert baseline["effective_settings"] == candidate["effective_settings"]
    assert "business_capability_enforcement_enabled" in baseline["settings_field_presence"]
    assert "business_capability_enforcement_enabled" in candidate["settings_field_presence"]
    assert isinstance(baseline["settings_inventory"], dict)
    assert isinstance(candidate["settings_inventory"], dict)
    assert isinstance(evidence["behavior_comparisons"]["complete_settings_field_names_equal"], bool)
    for snapshot in (baseline, candidate):
        for field in snapshot["settings_redacted_fields"]:
            assert snapshot["settings_inventory"][field] == "<REDACTED>"
    assert evidence["tool_inventory"]["candidate_missing"] == []
    assert all(evidence["baseline_r1_strictness_baseline"].values())
    strict_inventory = evidence["candidate_strict_schema_inventory"]
    assert set(strict_inventory) == set(evidence["tool_inventory"]["baseline_r1"]) | set(
        evidence["tool_inventory"]["candidate_additions"]
    )
    assert all(entry == {"additionalProperties": False, "strict": True}
               for entry in strict_inventory.values())
    assert len(baseline["wire_trace"]) == len(candidate["wire_trace"]) == 6
    assert [call["case"] for call in baseline["calls"]] == [
        "source-health-ok", "source-health-error", "onec-read-valid",
        "onec-read-misspelled-filter",
    ]
    assert evidence["behavior_comparisons"]["effective_settings_equal"]
    assert "acl_rate_decisions_equal_for_compatible_calls" in evidence["behavior_comparisons"]
    assert "completion_audit_equal_for_compatible_calls" in evidence["behavior_comparisons"]
    assert "access_receipts" in evidence["behavior_comparisons"]
    assert "adapter_side_effects_equal_for_compatible_calls" in evidence["behavior_comparisons"]
    assert "other_events_equal" in evidence["behavior_comparisons"]
    assert evidence["input_validation_probes"]["candidate"][0]["case"] == "onec-read-valid"
    assert evidence["input_validation_probes"]["candidate"][0]["response"]["result"]["isError"] is False
    assert evidence["input_validation_probes"]["candidate"][1]["case"] == "onec-read-misspelled-filter"
    assert evidence["input_validation_probes"]["candidate"][1]["response"]["result"]["isError"] is True
