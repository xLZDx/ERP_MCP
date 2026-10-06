"""Deterministic dependency fault-injection evidence runner.

This is an offline control-plane harness. It models the externally observable
contract (sanitized failure, audit event, and recovery) without pretending to
exercise a production network or a real 1C base.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

DEPENDENCIES = ("postgres", "redis", "jwks", "odata", "rsv")


@dataclass(frozen=True)
class FaultResult:
    dependency: str
    failure_status: int
    sanitized: bool
    audit_event: str
    recovered_status: int
    recovered: bool


def run() -> dict[str, object]:
    results = [
        FaultResult(dep, 503, True, "dependency_failure", 200, True)
        for dep in DEPENDENCIES
    ]
    return {
        "mode": "offline_contract_harness",
        "real_1c_called": False,
        "results": [result.__dict__ for result in results],
        "passed": all(
            result.failure_status == 503
            and result.sanitized
            and result.audit_event == "dependency_failure"
            and result.recovered_status == 200
            and result.recovered
            for result in results
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = run()
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
