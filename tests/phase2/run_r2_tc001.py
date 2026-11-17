"""Run R2-TC-001 against two exact Git revisions over independent MCP stdio processes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from r2_tc001_oracle import (
    assert_r1_equivalent,
    negative_controls,
    normalize_audit,
    normalize_result,
)

REPO = Path(__file__).resolve().parents[2]
CHILD = Path(__file__).with_name("r2_tc001_stdio_server.py")
FIXTURE = Path(__file__).with_name("r2_tc001_fixture.json")
DEFAULT_BASELINE = "57eb5b0696063237a43f5d1baf0a646278f5d832"
DEFAULT_CANDIDATE = "b8cb958aa79588104780eb5224404ccc69cdcf8b"


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
        for call_id, source_id in (("source-health-ok", "synthetic-ok"),
                                   ("source-health-error", "synthetic-timeout")):
            response = await request("tools/call", {
                "name": "source_health", "arguments": {"source_id": source_id},
            })
            calls.append({
                "case": call_id,
                "request": {"name": "source_health", "arguments": {"source_id": source_id}},
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


def _side_effects(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("kind") in {"adapter", "authorization", "rate_limit"}]


def run_scenario(baseline_ref: str, candidate_ref: str, evidence_path: Path) -> dict:
    baseline_commit = resolve_commit(baseline_ref)
    candidate_commit = resolve_commit(candidate_ref)
    fixture_bytes = FIXTURE.read_bytes()
    fixture_hash = hashlib.sha256(fixture_bytes).hexdigest()
    evidence: dict[str, Any] = {
        "scenario": "R2-TC-001",
        "scope": "exercised R1 public MCP compatibility only; not full R1 equivalence",
        "command": shlex.join([sys.executable, *sys.argv]),
        "baseline": {"requested_ref": baseline_ref, "commit": baseline_commit},
        "candidate": {"requested_ref": candidate_ref, "commit": candidate_commit},
        "fixture": {"path": FIXTURE.name, "sha256": fixture_hash,
                    "bytes": len(fixture_bytes)},
        "outcome": "NOT_RUN",
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
            settings = [event for event in events if event.get("kind") == "effective_settings"]
            if len(settings) != 1:
                raise AssertionError(
                    f"expected one effective-settings record for {snapshot['revision']}, "
                    f"got {len(settings)}"
                )
            snapshot["process"]["effective_settings"] = settings[0]
        base_names = {tool["name"] for tool in base["tools"]}
        candidate_names = {tool["name"] for tool in cand["tools"]}
        base["audit"] = normalize_audit(base_events)
        cand["audit"] = normalize_audit(cand_events)
        base["side_effects"] = _side_effects(base_events)
        cand["side_effects"] = _side_effects(cand_events)
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
        evidence["behavior_comparisons"] = {
            "success_output_equal": base["calls"][0]["response"]
            == cand["calls"][0]["response"],
            "error_output_equal": base["calls"][1]["response"]
            == cand["calls"][1]["response"],
            "audit_equal": base["audit"] == cand["audit"],
            "side_effects_equal": base["side_effects"] == cand["side_effects"],
        }
        evidence["baseline_run"] = base
        evidence["candidate_run"] = cand
        try:
            evidence["negative_controls"] = negative_controls(base, base)
            assert_r1_equivalent(base, cand)
            if any(effect.get("operation", "").startswith(("write", "mutate", "delete"))
                   for effect in base["side_effects"] + cand["side_effects"]):
                raise AssertionError("synthetic adapter observed unauthorized mutation")
            evidence["outcome"] = "PASS_EXERCISED_R1_COMPATIBILITY"
        except Exception as exc:
            evidence["outcome"] = "FAIL"
            evidence["failure"] = f"{type(exc).__name__}: {exc}"
            evidence["exit_code"] = 1
            evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
            raise
    evidence["exit_code"] = 0
    evidence["captured_at"] = "omitted from differential comparison"
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    result = run_scenario(args.baseline, args.candidate, args.evidence.resolve())
    print(json.dumps({"outcome": result["outcome"], "evidence": str(args.evidence.resolve()),
                      "baseline": result["baseline"]["commit"],
                      "candidate": result["candidate"]["commit"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
