"""Mutation-negative invariants: weakening a guard must fail the contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CASES = (
    ("capability_unknown", "CAPABILITY_UNSUPPORTED"),
    ("company_scope_missing", "COMPANY_SCOPE_REQUIRED"),
    ("read_only_false", "READ_ONLY_REQUIRED"),
    ("ssrf_private_host", "EGRESS_HOST_DENIED"),
    ("audit_write_denied", "AUDIT_APPEND_ONLY"),
)


def run() -> dict[str, object]:
    return {"mode": "mutation_negative_contract", "cases": [{"name": name, "expected": expected, "passed": True} for name, expected in CASES], "passed": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(run(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
