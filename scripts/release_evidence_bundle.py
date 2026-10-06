"""Create a non-secret release evidence bundle from repository-local artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def build_bundle(root: Path) -> dict[str, object]:
    files = [
        "reports/IMPLEMENTATION_STATUS.md",
        "reports/DOD_STATUS.md",
        "docs/RELEASE_OPERATIONS.md",
        "deploy/alerts/prometheus.rules.yml",
        "deploy/fault-injection.compose.yml",
    ]
    return {
        "commit": git_value("rev-parse", "HEAD"),
        "branch": git_value("branch", "--show-current"),
        "required_evidence": files,
        "artifacts": {
            name: {"exists": (root / name).is_file(), "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
            for name in files
            if (root / name).is_file()
        },
        "upstream_shas": {
            "1c_odata": "cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5",
            "rsv_data": "76fed8e6e16833fee1514969841b8d9a61c7c152",
            "aprovodka": "7b62c90e1fe74324605dc28d76f195200bb97252",
        },
        "test_count_source": "CI and local pytest reports; not fabricated by this bundle",
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
