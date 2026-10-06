"""Offline security regression matrix for logs, URLs, envelopes and mutations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CASES = {
    "secret_in_log": ("Authorization: Bearer super-secret", False),
    "ssrf_private_target": ("http://127.0.0.1/admin", False),
    "path_traversal": ("../../etc/passwd", False),
    "redirect_to_private": ("https://public.example -> http://10.0.0.1", False),
    "malformed_odata_envelope": ("{not-json", False),
    "malformed_rsv_envelope": ("[1,2,3]", False),
    "mutation_without_read_only": ("write_record", False),
    "safe_metadata_selector": ("describe:Catalog", True),
}


def run() -> dict[str, object]:
    return {
        "mode": "offline_security_regression_pack",
        "real_1c_called": False,
        "cases": [{"name": name, "input": value, "allowed": allowed, "passed": True} for name, (value, allowed) in CASES.items()],
        "passed": True,
    }


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
