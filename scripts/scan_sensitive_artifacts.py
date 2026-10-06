"""Scan logs/evidence artifacts for credentials and sensitive transport fields."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~-]{12,}"),
    re.compile(r'''(?i)["']?\b(password|client_secret|secret|token)["']?\s*[:=]\s*["']?[^,\s}"']{8,}'''),
    re.compile(r'''(?i)\b(authorization|cookie|set-cookie)["']?\s*[:=](?!\s*["']?\[REDACTED\])'''),
    re.compile(r'''(?i)\b(connection_string|dsn)["']?\s*[:=]\s*["']?[^\s]{12,}'''),
)


def scan(paths: list[Path]) -> list[str]:
    findings = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in PATTERNS):
            findings.append(str(path))
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    findings = scan(args.paths)
    if findings:
        raise SystemExit("sensitive artifact findings: " + ", ".join(findings))
    print(f"sensitive artifact scan: PASS ({len(args.paths)} files)")


if __name__ == "__main__":
    main()
