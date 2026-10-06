"""Create a non-secret release evidence bundle from repository-local artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def build_bundle(root: Path) -> dict[str, object]:
    return {
        "commit": git_value("rev-parse", "HEAD"),
        "branch": git_value("branch", "--show-current"),
        "required_evidence": [
            "reports/IMPLEMENTATION_STATUS.md",
            "reports/DOD_STATUS.md",
            "docs/RELEASE_OPERATIONS.md",
            "deploy/alerts/prometheus.rules.yml",
        ],
        "production_decision": "NO-GO_UNTIL_EXTERNAL_EVIDENCE",
        "secret_values_included": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = build_bundle(Path(__file__).resolve().parents[1])
    args.output.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(f"release evidence bundle: {args.output}")


if __name__ == "__main__":
    main()
