"""Run pinned promtool against real gateway metric output and alert fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path

import httpx

from business_ai_gateway.observability import HTTPMetrics

IMAGE = "prom/prometheus:v3.5.0@sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996"


async def sample_metrics() -> str:
    async def handler(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    metrics = HTTPMetrics().bind(handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=metrics), base_url="http://fixture") as client:
        await client.post("/mcp")
    metrics.record_operation("audit", "error")
    metrics.record_dependency("database", "error")
    return metrics.render()


def run(root: Path) -> dict[str, object]:
    base = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--entrypoint", "/bin/promtool",
            "--mount", f"type=bind,source={root / 'deploy/alerts'},target=/rules,readonly", IMAGE]
    results = []
    for name, args, stdin in (
        ("rule_lint", ["check", "rules", "/rules/prometheus.rules.yml"], None),
        ("pending_firing_resolution", ["test", "rules", "/rules/prometheus.test.yml"], None),
        ("gateway_text_format", ["check", "metrics"], asyncio.run(sample_metrics())),
    ):
        completed = subprocess.run([*base, *args], input=stdin.encode("utf-8") if stdin else None,
                                   capture_output=True, timeout=60, check=False)
        results.append({"check": name, "returncode": completed.returncode,
                        "passed": completed.returncode == 0})
        if completed.returncode:
            detail = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
            raise RuntimeError(f"promtool check failed: {name}: {detail}")
    return {"image": IMAGE, "results": results, "passed": all(item["passed"] for item in results),
            "alert_delivery": "NOT_TESTED", "real_1c_called": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(Path(__file__).resolve().parents[1])
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("promtool rule lint, firing/resolution and gateway metrics: PASS")


if __name__ == "__main__":
    main()
