"""Validate metric privacy invariants and Prometheus alert rule contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

FORBIDDEN_LABELS = ("source", "source_id", "company", "company_id", "query", "url", "path")
REQUIRED_ALERTS = (
    "ErpMcpHighServerErrorRate",
    "ErpMcpDependencyErrors",
    "ErpMcpAuditAppendErrors",
    "ErpMcpHighLatency",
)


def validate_rules(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    names = re.findall(r"alert:\s*(\w+)", text)
    forbidden = [label for label in FORBIDDEN_LABELS if re.search(rf"[{{,]\s*{label}\s*=", text)]
    if tuple(names) != REQUIRED_ALERTS or forbidden:
        raise ValueError(f"invalid alert contract: names={names}, forbidden={forbidden}")
    return {"rules": names, "forbidden_labels": forbidden, "lint": "PASS"}


def validate_text_format(text: str) -> None:
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if "{" in line and "}" in line:
            labels = line.split("{", 1)[1].split("}", 1)[0]
            if any(re.search(rf"\b{label}\s*=", labels) for label in FORBIDDEN_LABELS):
                raise ValueError("metric contains a sensitive label")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rules", type=Path)
    args = parser.parse_args()
    print(validate_rules(args.rules))


if __name__ == "__main__":
    main()
