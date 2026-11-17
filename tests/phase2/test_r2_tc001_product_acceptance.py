"""Focused differential tests for executable, synthetic R2-TC-001 acceptance."""
from __future__ import annotations

import copy
import asyncio
import json

import pytest

from run_r2_tc001 import DEFAULT_BASELINE, DEFAULT_CANDIDATE, _shutdown_process, run_scenario
from r2_tc001_oracle import DifferentialMismatch, assert_r1_equivalent


def _equal_snapshot():
    return {
        "tools": [{
            "name": "source_health",
            "inputSchema": {"type": "object", "properties": {"source_id": {"type": "string"}}},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        }],
        "calls": [{"case": "ok", "response": {"result": {"structuredContent": {"value": "ok"}}}}],
        "audit": [{"kind": "audit", "tool": "source_health", "outcome": "success"}],
        "side_effects": [{"kind": "adapter", "operation": "health_read"}],
    }


def test_r2_tc001_differential_oracle_accepts_matching_behavior():
    baseline = _equal_snapshot()
    assert_r1_equivalent(baseline, copy.deepcopy(baseline))


@pytest.mark.parametrize("mutation", ["schema", "output", "audit"])
def test_r2_tc001_differential_oracle_rejects_regressions(mutation):
    baseline = _equal_snapshot()
    altered = copy.deepcopy(baseline)
    if mutation == "schema":
        altered["tools"][0]["inputSchema"]["properties"]["source_id"]["type"] = "integer"
    elif mutation == "output":
        altered["calls"][0]["response"]["result"]["structuredContent"]["value"] = "altered"
    else:
        altered["audit"].append({"kind": "audit", "tool": "source_health", "outcome": "denied"})
    with pytest.raises(DifferentialMismatch):
        assert_r1_equivalent(baseline, altered)


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


def test_r2_tc001_runs_exact_commits_and_captures_current_candidate_gap(tmp_path):
    evidence_path = tmp_path / "r2-tc001-evidence.json"
    with pytest.raises(DifferentialMismatch, match="changed baseline R1 schema.*changed R1 calls.*changed R1 audit"):
        run_scenario(DEFAULT_BASELINE, DEFAULT_CANDIDATE, evidence_path)

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    baseline = evidence["baseline_run"]
    candidate = evidence["candidate_run"]
    assert evidence["outcome"] == "FAIL"
    assert evidence["baseline"]["commit"] == DEFAULT_BASELINE
    assert evidence["candidate"]["commit"] == DEFAULT_CANDIDATE
    assert baseline["process"]["pid"] != candidate["process"]["pid"]
    assert baseline["process"]["transport"] == candidate["process"]["transport"] == "stdio"
    assert baseline["process"]["shutdown"]["exit_code"] == 0
    assert candidate["process"]["shutdown"]["exit_code"] == 0
    for snapshot in (baseline, candidate):
        settings = snapshot["process"]["effective_settings"]
        assert settings["environment"] == "test"
        assert settings["oauth_enabled"] is False
    assert baseline["process"]["effective_settings"][
        "business_capability_enforcement_enabled"
    ] is None  # This setting does not exist at the approved baseline.
    assert candidate["process"]["effective_settings"][
        "business_capability_enforcement_enabled"
    ] is False
    assert evidence["tool_inventory"]["candidate_missing"] == []
    assert len(baseline["wire_trace"]) == len(candidate["wire_trace"]) == 4
    assert [call["case"] for call in baseline["calls"]] == ["source-health-ok", "source-health-error"]
    assert baseline["calls"][0] == candidate["calls"][0]
    assert baseline["calls"][1] != candidate["calls"][1]
    assert baseline["audit"] != candidate["audit"]
    assert baseline["side_effects"] == candidate["side_effects"]
    assert evidence["fixture"]["sha256"]
    assert evidence["exit_code"] == 1
