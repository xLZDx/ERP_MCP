"""Executed production-client subprocess evidence, not declared recovery flags."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .execute_evidence_tests import execute
except ImportError:
    from execute_evidence_tests import execute


def run() -> dict[str, object]:
    result = execute(["tests/test_rsv_process_lifecycle.py"], timeout_seconds=240)
    result.update(real_1c_called=False, transport="official_sdk_stdio",
                  operations=["ping", "config"],
                  not_covered=["native_COM_crash", "native_1C_restart", "Windows_secret_DACL"])
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
