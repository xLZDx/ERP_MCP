"""Render a safe source capability evidence report from a JSON export."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def build_report(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > 8_000_000:
        raise ValueError("capability export exceeds input limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("schema_version") == 1 and payload.get("diagnostic_only") is True:
        payload = payload.get("report")
    if not isinstance(payload, list) or len(payload) > 20_000:
        raise TypeError("capability export must be a list")
    report = []
    for item in payload:
        if (not isinstance(item, dict) or not isinstance(item.get("source_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", item["source_id"])):
            raise TypeError("capability item requires source_id")
        status = item.get("status")
        if status not in {"SUPPORTED", "UNSUPPORTED", "STALE", "UNVALIDATED"}:
            raise ValueError("capability status is invalid")
        entity_set = item.get("entity_set", "")
        if (not isinstance(entity_set, str) or len(entity_set) > 256
                or (entity_set and not re.fullmatch(r"(?:Accounting|Accumulation|Information)Register_[\w]+", entity_set))):
            raise ValueError("capability entity set is invalid")
        fingerprint = item.get("fingerprint")
        if fingerprint is not None and (not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)):
            raise ValueError("capability fingerprint is invalid")
        operation = item.get("operation", "unknown")
        if not isinstance(operation, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", operation):
            raise ValueError("capability operation is invalid")
        evidence_kind = item.get("evidence_kind", "none")
        if evidence_kind not in {"none", "live-metadata", "metadata-get-function-import",
                                 "safe-capability-probe", "validated-semantic-profile"}:
            raise ValueError("capability evidence kind is invalid")
        reason = item.get("reason", "UNSPECIFIED")
        if reason not in {"UNSPECIFIED", "SOURCE_DISABLED", "PROFILE_MISSING", "PROFILE_UNCONFIRMED", "PROFILE_TOO_LARGE",
                          "ADAPTER_UNSUPPORTED", "METADATA_DRIFT", "FINGERPRINT_MISMATCH",
                          "PROFILE_STALE", "OPERATION_UNCONFIRMED", "NO_REGISTER_EVIDENCE", "CONFIRMED"}:
            raise ValueError("capability reason is invalid")
        report.append(
            {
                "source_id": item["source_id"],
                "operation": operation,
                "entity_set": entity_set,
                "status": status,
                "evidence_kind": evidence_kind,
                "reason": reason,
                "fingerprint": item.get("fingerprint"),
            }
        )
    keys = {(item["source_id"], item["entity_set"], item["operation"]) for item in report}
    if len(keys) != len(report):
        raise ValueError("duplicate capability entry")
    return sorted(report, key=lambda item: (item["source_id"], item["entity_set"], item["operation"]))


def diff_reports(left: Path, right: Path) -> list[dict[str, Any]]:
    before = {(item["source_id"], item["entity_set"], item["operation"]): item for item in build_report(left)}
    after = {(item["source_id"], item["entity_set"], item["operation"]): item for item in build_report(right)}
    changes = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changes.append({"source_id": key[0], "entity_set": key[1], "operation": key[2], "before": before.get(key), "after": after.get(key)})
    return changes


def evidence_manifest(path: Path) -> dict[str, Any]:
    report = build_report(path)
    return {
        "diagnostic_only": True,
        "authorization_checked": False,
        "artifact": "private_capability_export",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entries": len(report),
        "supported": sum(item["status"] == "SUPPORTED" for item in report),
        "stale": sum(item["status"] == "STALE" for item in report),
        "unsupported": sum(item["status"] == "UNSUPPORTED" for item in report),
        "report": report,
    }


def _main() -> None:
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


def main() -> None:
    try:
        _main()
    except (OSError, TypeError, ValueError, RecursionError):
        raise SystemExit("CAPABILITY_REPORT_FAILED") from None


if __name__ == "__main__":
    main()
