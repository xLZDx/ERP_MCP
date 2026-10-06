"""Render a safe source capability evidence report from a JSON export."""

from __future__ import annotations

import argparse
import hashlib
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


def diff_reports(left: Path, right: Path) -> list[dict[str, Any]]:
    before = {(item["source_id"], item["operation"]): item for item in build_report(left)}
    after = {(item["source_id"], item["operation"]): item for item in build_report(right)}
    changes = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changes.append({"source_id": key[0], "operation": key[1], "before": before.get(key), "after": after.get(key)})
    return changes


def evidence_manifest(path: Path) -> dict[str, Any]:
    report = build_report(path)
    return {
        "artifact": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entries": len(report),
        "supported": sum(item["status"] == "SUPPORTED" for item in report),
        "stale": sum(item["status"] == "STALE" for item in report),
        "unsupported": sum(item["status"] == "UNSUPPORTED" for item in report),
        "report": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path)
    parser.add_argument("--diff", type=Path, metavar="OTHER")
    parser.add_argument("--stale", action="store_true")
    parser.add_argument("--unsupported-reason", action="store_true")
    parser.add_argument("--evidence-manifest", action="store_true")
    args = parser.parse_args()
    if args.diff:
        result: Any = diff_reports(args.export, args.diff)
    elif args.evidence_manifest:
        result = evidence_manifest(args.export)
    else:
        result = build_report(args.export)
        if args.stale:
            result = [item for item in result if item["status"] == "STALE"]
        if args.unsupported_reason:
            result = [
                {**item, "reason": "source capability was not confirmed"}
                for item in result
                if item["status"] == "UNSUPPORTED"
            ]
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
