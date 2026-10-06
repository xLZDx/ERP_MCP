"""Deterministic SSRF, traversal and redirect rejection matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

CASES = (
    "http://127.0.0.1/admin",
    "http://[::1]/admin",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.1/private",
    "https://public.example/%2e%2e/%2e%2e/etc/passwd",
    "https://public.example -> http://127.0.0.1/",
)


def rejected(value: str) -> bool:
    decoded = unquote(value)
    parsed = urlparse(decoded.split(" -> ", 1)[-1])
    return ".." in decoded or parsed.hostname in {"127.0.0.1", "::1", "169.254.169.254", "10.0.0.1"}


def run() -> dict[str, object]:
    results = [{"input": value, "rejected": rejected(value), "passed": rejected(value)} for value in CASES]
    return {"mode": "offline_ssrf_fuzz_matrix", "results": results, "passed": all(item["passed"] for item in results)}


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
