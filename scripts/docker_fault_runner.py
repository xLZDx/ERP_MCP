"""Run or validate the isolated Docker dependency fault matrix."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path

try:
    from .fault_injection_runner import DEPENDENCIES
except ImportError:
    from fault_injection_runner import DEPENDENCIES


def compose_config(root: Path) -> None:
    subprocess.run(["docker", "compose", "-f", str(root / "deploy/fault-injection.compose.yml"), "config"], check=True)


def run(root: Path, execute: bool) -> dict[str, object]:
    if execute:
        try:
            from .local_dependency_drill import execute as drill
        except ImportError:
            from local_dependency_drill import execute as drill
        return asyncio.run(drill())
    return {
        "mode": "docker_compose_fault_runner" if execute else "docker_compose_plan",
        "execute": execute,
        "dependencies": list(DEPENDENCIES),
        "scenarios": [
            {"dependency": dependency, "disable": f"docker compose stop {dependency}", "expect_status": 503, "expect_recovery": 200}
            for dependency in DEPENDENCIES
        ],
        "real_1c_called": False,
        "passed": None,
        "status": "NOT_RUN",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = run(args.root, args.execute)
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
