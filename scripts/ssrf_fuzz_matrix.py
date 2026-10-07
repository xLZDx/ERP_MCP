"""Executed adversarial evidence against production transport/egress boundaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .execute_evidence_tests import execute
except ImportError:
    from execute_evidence_tests import execute


def run() -> dict[str, object]:
    result = execute(["tests/test_transport_security_matrix.py", "tests/test_network_policy.py",
                      "tests/test_connect_time_egress.py"])
    result["not_covered"] = ["deployment_firewall", "exhaustive_envelope_fuzzing"]
    return result


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
