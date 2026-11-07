"""Run R2-TC-001 against two exact Git revisions over independent MCP stdio processes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from r2_tc001_oracle import (
    DifferentialMismatch,
    assert_r1_equivalent,
    input_schema_compatible,
    negative_controls,
    normalize_result,
)

REPO = Path(__file__).resolve().parents[2]
CHILD = Path(__file__).with_name("r2_tc001_stdio_server.py")
FIXTURE = Path(__file__).with_name("r2_tc001_fixture.json")
DEFAULT_BASELINE = "57eb5b0696063237a43f5d1baf0a646278f5d832"


def resolve_commit(ref: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def export_source(commit: str, target: Path) -> None:
    archive = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", commit, "src"],
        check=True, capture_output=True,
    ).stdout
    target.mkdir(parents=True, exist_ok=True)
    import io

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(target, filter="data")


async def _read_matching(proc: asyncio.subprocess.Process, request_id: int) -> dict:
    assert proc.stdout is not None
    while True:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=20)
        if not line:
            raise RuntimeError(f"MCP server exited before response to request {request_id}")
        message = json.loads(line)
        if message.get("id") == request_id:
            return message


async def run_process(*, ref: str, commit: str, source_root: Path, label: str,
                      work_dir: Path, fixture_path: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    event_path = work_dir / f"{label}-events.jsonl"
    # The product's BaseSettings reads BAG_* variables. Strip ambient overrides so both
    # exact revisions run with the same defaults; the child records resolved values below.
    env = {key: value for key, value in os.environ.items() if not key.startswith("BAG_")}
    env.update({
        "PYTHONPATH": str(source_root),
        "R2_TC001_SOURCE_ROOT": str(source_root),
        "R2_TC001_EVENT_LOG": str(event_path),
        "R2_TC001_FIXTURE": str(fixture_path),
    })
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(CHILD), cwd=str(work_dir), env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None
    assert proc.stderr is not None
    stderr_task = asyncio.create_task(proc.stderr.read())
    trace: list[dict] = []
    next_id = 1

    async def request(method: str, params: dict) -> dict:
        nonlocal next_id
        request_id = next_id
        next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        wire = json.dumps(payload, separators=(",", ":"))
        proc.stdin.write((wire + "\n").encode("utf-8"))
        await proc.stdin.drain()
        response = await _read_matching(proc, request_id)
        trace.append({"request": payload, "response": response})
        return response

    result: dict[str, Any] | None = None
    try:
        init = await request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "r2-tc001-product-test", "version": "1"},
        })
        if "error" in init:
            raise RuntimeError(f"MCP initialization failed: {init['error']}")
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        proc.stdin.write((json.dumps(notification, separators=(",", ":")) + "\n").encode())
        await proc.stdin.drain()
        tools_response = await request("tools/list", {})
        if "error" in tools_response:
            raise RuntimeError(f"tools/list failed: {tools_response['error']}")
        calls = []
        probes = [
            ("source-health-ok", "source_health", {"source_id": "synthetic-ok"}),
            ("source-health-error", "source_health", {"source_id": "synthetic-timeout"}),
            ("onec-read-valid", "onec_read", {
                "source_id": "synthetic-read", "entity_set": "SyntheticRows",
                "filter_expr": "id eq 'synthetic-1'", "top": 1,
            }),
            ("onec-read-misspelled-filter", "onec_read", {
                "source_id": "synthetic-typo", "entity_set": "SyntheticRows",
                "filter": "id eq 'synthetic-1'", "top": 1,
            }),
        ]
        for call_id, tool_name, arguments in probes:
            response = await request("tools/call", {"name": tool_name, "arguments": arguments})
            calls.append({
                "case": call_id,
                "request": {"name": tool_name, "arguments": arguments},
                "response": normalize_result(response),
            })
        result = {
            "revision": commit,
            "requested_ref": ref,
            "process": {"pid": proc.pid, "python": sys.executable,
                        "argv": [sys.executable, str(CHILD)], "cwd": str(work_dir),
                        "environment": "synthetic-test", "transport": "stdio",
                        "bag_environment_overrides": "stripped; child records resolved settings"},
            "initialize": init,
            "tools": tools_response["result"].get("tools", []),
            "calls": calls,
            "wire_trace": trace,
            "events": event_path,
        }
    finally:
        shutdown = await _shutdown_process(proc, stderr_task, label)
        if result is not None:
            result["process"]["shutdown"] = shutdown
    if result is None:
        raise RuntimeError(f"{label} MCP process produced no scenario result")
    return result


def _events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def serialize_differential_outcome(
    evidence: dict, baseline: dict, candidate: dict, evidence_path: Path,
) -> dict:
    """Persist an exact product diff without turning harness success into acceptance PASS."""
    try:
        assert_r1_equivalent(baseline, candidate)
    except DifferentialMismatch as exc:
        evidence["differential_result"] = "FAIL"
        evidence["differential_failure"] = str(exc)
        evidence["product_acceptance_status"] = "OPEN"
    else:
        evidence["differential_result"] = "PASS"
        evidence["product_acceptance_status"] = "OPEN_PENDING_GPT_PM_ADJUDICATION"
    evidence["baseline_run"] = baseline
    evidence["candidate_run"] = candidate
    evidence["runner_exit_code"] = 0
    evidence["overall_result"] = (
        "HARNESS_PASS_PRODUCT_FAIL_OPEN"
        if evidence["differential_result"] == "FAIL"
        else "HARNESS_PASS_PRODUCT_OPEN_PENDING_GPT_PM"
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return evidence


async def _shutdown_process(proc: asyncio.subprocess.Process, stderr_task: asyncio.Task[bytes],
                           label: str) -> dict[str, Any]:
    """Close stdio and require a clean child exit before treating a run as evidence."""
    assert proc.stdin is not None
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.stdin.wait_closed(), timeout=5)
    except (AttributeError, BrokenPipeError, TimeoutError):
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        stderr_bytes = await asyncio.wait_for(stderr_task, timeout=5)
        raise RuntimeError(
            f"{label} MCP process did not exit after stdin close; killed after timeout; "
            f"stderr={stderr_bytes.decode('utf-8', errors='replace')}"
        )
    stderr_bytes = await asyncio.wait_for(stderr_task, timeout=5)
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            f"{label} MCP process exited with {proc.returncode}; stderr={stderr_text}"
        )
    return {"exit_code": proc.returncode, "stderr": stderr_text}


def run_scenario(baseline_ref: str, candidate_ref: str, evidence_path: Path) -> dict:
    baseline_commit = resolve_commit(baseline_ref)
    candidate_commit = resolve_commit(candidate_ref)
    fixture_bytes = FIXTURE.read_bytes()
    fixture_hash = hashlib.sha256(fixture_bytes).hexdigest()
    evidence: dict[str, Any] = {
        "scenario": "R2-TC-001",
        "scope": "exercised R1 public MCP compatibility only; not full R1 equivalence",
        "contract_adjudication_request_id": "7fdc4c52-5de3-4d76-a3fa-f78e2b1073d4",
        "pm_contract_provenance": [
            {"request_id": "11ad043a-0c66-473d-9bd6-5fe7e052a701", "purpose": "approved test contract"},
            {"request_id": "5f38119f-3919-4a5d-a572-42a6b2bdf6d9", "purpose": "contract adjudication"},
            {"request_id": "bd092c6b-28d9-4a7f-9f47-2ce93e18908d", "purpose": "decision precedence"},
            {"request_id": "7fdc4c52-5de3-4d76-a3fa-f78e2b1073d4", "purpose": "schema and audit exceptions"},
        ],
        "approved_narrow_differences": [
            "candidate root inputSchema may add additionalProperties=false only",
            "candidate uses exact read-only annotations: readOnly=true, destructive=false, openWorld=true",
            "candidate adds one ACCESS_AUTHORIZED receipt before adapter dispatch; compare completion audits separately",
        ],
        "command": shlex.join([sys.executable, *sys.argv]),
        "baseline": {"requested_ref": baseline_ref, "commit": baseline_commit},
        "candidate": {"requested_ref": candidate_ref, "commit": candidate_commit},
        "fixture": {"path": FIXTURE.name, "sha256": fixture_hash,
                    "bytes": len(fixture_bytes)},
        "test_harness": {"status": "NOT_RUN"},
        "differential_result": "NOT_RUN",
        "product_acceptance_status": "OPEN",
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r2-tc001-") as temporary:
        root = Path(temporary)
        baseline_src = root / "baseline"
        candidate_src = root / "candidate"
        export_source(baseline_commit, baseline_src)
        export_source(candidate_commit, candidate_src)
        base = asyncio.run(run_process(
            ref=baseline_ref, commit=baseline_commit, source_root=baseline_src / "src",
            label="baseline", work_dir=root / "baseline-process", fixture_path=FIXTURE,
        ))
        cand = asyncio.run(run_process(
            ref=candidate_ref, commit=candidate_commit, source_root=candidate_src / "src",
            label="candidate", work_dir=root / "candidate-process", fixture_path=FIXTURE,
        ))
        base_events = _events(base.pop("events"))
        cand_events = _events(cand.pop("events"))
        for snapshot, events in ((base, base_events), (cand, cand_events)):
            settings = [event for event in events if event.get("kind") == "settings_snapshot"]
            process = [event for event in events if event.get("kind") == "process"]
            if len(settings) != 1 or len(process) != 1:
                raise AssertionError(
                    f"expected one settings and process record for {snapshot['revision']}, "
                    f"got settings={len(settings)}, process={len(process)}"
                )
            snapshot["effective_settings"] = settings[0]["effective"]
            snapshot["settings_inventory"] = settings[0]["inventory"]
            snapshot["settings_redacted_fields"] = settings[0]["redacted_fields"]
            snapshot["settings_field_presence"] = settings[0]["field_presence"]
            snapshot["runtime_process"] = process[0]
        base_names = {tool["name"] for tool in base["tools"]}
        candidate_names = {tool["name"] for tool in cand["tools"]}
        for snapshot, events in ((base, base_events), (cand, cand_events)):
            snapshot["event_log"] = events
            snapshot["acl_rate_decisions"] = [
                event for event in events if event.get("kind") in {"authorization", "rate_limit"}
            ]
            snapshot["access_receipts"] = [
                event for event in events if event.get("kind") == "audit"
                and event.get("detail_code") == "ACCESS_AUTHORIZED"
            ]
            snapshot["completion_audit"] = [
                event for event in events if event.get("kind") == "audit"
                and event.get("detail_code") != "ACCESS_AUTHORIZED"
            ]
            snapshot["adapter_side_effects"] = [
                event for event in events if event.get("kind") == "adapter"
            ]
            recognized = {"process", "settings_snapshot", "authorization", "rate_limit", "audit", "adapter"}
            snapshot["other_events"] = [event for event in events if event.get("kind") not in recognized]
            snapshot["input_probes"] = [
                call for call in snapshot["calls"]
                if call["case"] in {"onec-read-misspelled-filter", "onec-read-valid"}
            ]
        cand["all_candidate_tools"] = list(cand["tools"])
        base["tools"] = [t for t in base["tools"] if t["name"] in base_names]
        cand["tools"] = [t for t in cand["tools"] if t["name"] in base_names]
        evidence["tool_inventory"] = {
            "baseline_r1": sorted(base_names),
            "candidate_missing": sorted(base_names - candidate_names),
            "candidate_additions": sorted(candidate_names - base_names),
        }
        base_tool_map = {tool["name"]: tool for tool in base["tools"]}
        candidate_tool_map = {tool["name"]: tool for tool in cand["tools"]}
        evidence["schema_annotation_differences"] = {
            name: {"baseline": base_tool_map[name], "candidate": candidate_tool_map[name]}
            for name in sorted(base_names & candidate_names)
            if json.dumps(base_tool_map[name], sort_keys=True)
            != json.dumps(candidate_tool_map[name], sort_keys=True)
        }
        evidence["schema_contract_comparison"] = {
            name: {
                "baseline_root_additional_properties_absent": (
                    "additionalProperties" not in base_tool_map[name].get("inputSchema", {})
                ),
                "input_schema_compatible": input_schema_compatible(
                    base_tool_map[name].get("inputSchema"),
                    candidate_tool_map[name].get("inputSchema"),
                ),
                "root_additional_properties_false_allowance_applied": (
                    "additionalProperties" not in base_tool_map[name].get("inputSchema", {})
                    and candidate_tool_map[name].get("inputSchema", {}).get("additionalProperties") is False
                ),
                "baseline_annotations": base_tool_map[name].get("annotations"),
                "candidate_annotations": candidate_tool_map[name].get("annotations"),
                "candidate_read_only_annotations_exact": candidate_tool_map[name].get(
                    "annotations"
                ) == {
                    "destructiveHint": False,
                    "openWorldHint": True,
                    "readOnlyHint": True,
                },
            }
            for name in sorted(base_names & candidate_names)
        }
        evidence["baseline_r1_strictness_baseline"] = {
            name: "additionalProperties" not in base_tool_map[name].get("inputSchema", {})
            for name in sorted(base_names & candidate_names)
        }
        evidence["candidate_strict_schema_inventory"] = {
            tool["name"]: {
                "additionalProperties": tool.get("inputSchema", {}).get("additionalProperties")
                if isinstance(tool.get("inputSchema"), dict) else None,
                "strict": isinstance(tool.get("inputSchema"), dict)
                and tool["inputSchema"].get("additionalProperties") is False,
            }
            for tool in cand["all_candidate_tools"]
        }
        def compatible_events_equal(category: str) -> bool:
            def relevant(snapshot):
                return [event for event in snapshot[category]
                        if event.get("source_id") != "synthetic-typo"]
            return relevant(base) == relevant(cand)

        evidence["behavior_comparisons"] = {
            "success_output_equal": base["calls"][0]["response"] == cand["calls"][0]["response"],
            "error_output_equal": base["calls"][1]["response"] == cand["calls"][1]["response"],
            "valid_onec_read_output_equal": base["calls"][2]["response"] == cand["calls"][2]["response"],
            "effective_settings_equal": base["effective_settings"] == cand["effective_settings"],
            "complete_settings_field_names_equal": set(base["settings_inventory"])
            == set(cand["settings_inventory"]),
            "settings_inventory": {
                "baseline": base["settings_inventory"],
                "candidate": cand["settings_inventory"],
                "baseline_redacted_fields": base["settings_redacted_fields"],
                "candidate_redacted_fields": cand["settings_redacted_fields"],
                "baseline_presence": base["settings_field_presence"],
                "candidate_presence": cand["settings_field_presence"],
            },
            "acl_rate_decisions_equal_for_compatible_calls": compatible_events_equal("acl_rate_decisions"),
            "completion_audit_equal_for_compatible_calls": compatible_events_equal("completion_audit"),
            "access_receipts": {"baseline": base["access_receipts"], "candidate": cand["access_receipts"]},
            "adapter_side_effects_equal_for_compatible_calls": compatible_events_equal("adapter_side_effects"),
            "other_events_equal": base["other_events"] == cand["other_events"],
        }
        evidence["input_validation_probes"] = {
            "baseline": [call for call in base["calls"] if call["case"].startswith("onec-read-")],
            "candidate": [call for call in cand["calls"] if call["case"].startswith("onec-read-")],
        }
        try:
            evidence["negative_controls"] = negative_controls()
            evidence["test_harness"] = {"status": "PASS", "negative_controls": "PASS"}
        except Exception as exc:
            evidence["test_harness"] = {"status": "FAIL"}
            evidence["harness_failure"] = f"{type(exc).__name__}: {exc}"
            evidence["exit_code"] = 1
            evidence["baseline_run"] = base
            evidence["candidate_run"] = cand
            evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
            raise
    evidence["captured_at"] = "omitted from differential comparison"
    return serialize_differential_outcome(evidence, base, cand, evidence_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument(
        "--candidate",
        default=os.environ.get("R2_TC001_CANDIDATE"),
        help="explicit Git ref or commit SHA (or set R2_TC001_CANDIDATE)",
    )
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if not args.candidate:
        parser.error("--candidate or R2_TC001_CANDIDATE is required; no stale candidate default is used")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", resolve_commit(args.candidate)):
        parser.error("candidate ref did not resolve to an exact commit SHA")
    result = run_scenario(args.baseline, args.candidate, args.evidence.resolve())
    print(json.dumps({"harness": result["test_harness"]["status"],
                      "differential": result["differential_result"],
                      "product_acceptance": result["product_acceptance_status"],
                      "evidence": str(args.evidence.resolve()),
                      "baseline": result["baseline"]["commit"],
                      "candidate": result["candidate"]["commit"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
