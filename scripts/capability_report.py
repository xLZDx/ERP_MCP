"""Render a safe source capability evidence report from a JSON export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_report(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("capability export must be a list")
    report = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("source_id"), str):
            raise TypeError("capability item requires source_id")
        status = item.get("status")
        if status not in {"SUPPORTED", "UNSUPPORTED", "STALE", "UNVALIDATED"}:
            raise ValueError("capability status is invalid")
        report.append(
            {
                "source_id": item["source_id"],
                "operation": item.get("operation", "unknown"),
                "status": status,
                "evidence_kind": item.get("evidence_kind", "none"),
                "fingerprint": item.get("fingerprint"),
            }
        )
    return sorted(report, key=lambda item: (item["source_id"], item["operation"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path)
    args = parser.parse_args()
    report = build_report(args.export)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
