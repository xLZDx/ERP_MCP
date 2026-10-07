"""Read-only per-base registry diagnostics; never grants capability or makes protocol probes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from business_ai_gateway.settings import Settings

try:
    from .capability_report import diff_reports
except ImportError:
    from capability_report import diff_reports

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
QUERY = """
SELECT s.source_id, s.enabled, c.discovered_at, c.metadata_fingerprint,
       c.adapter_profile, c.compatibility_status, c.metadata_supported, c.json_supported,
       c.drift_status, octet_length(c.register_capabilities_json::text) AS profile_bytes,
       CASE WHEN octet_length(c.register_capabilities_json::text) > 131072 THEN '{}'::jsonb
            ELSE c.register_capabilities_json END AS register_capabilities_json
FROM bag.sources s LEFT JOIN bag.source_capabilities c USING(source_id)
WHERE s.project='onec' AND ($1::text IS NULL OR s.source_id=$1)
ORDER BY s.source_id LIMIT 251
"""


class CapabilityReportUnavailable(RuntimeError):
    pass


def report_rows(rows, *, now: datetime, ttl_seconds: float) -> list[dict]:
    if len(rows) > 250 or now.tzinfo is None or not 0 < ttl_seconds <= 3600:
        raise CapabilityReportUnavailable("CAPABILITY_REPORT_LIMIT")
    output = []
    for row in rows:
        source_id = row["source_id"]
        if not isinstance(source_id, str) or not _ID.fullmatch(source_id):
            raise CapabilityReportUnavailable("CAPABILITY_PROFILE_INVALID")
        profile = row["register_capabilities_json"]
        if isinstance(profile, str):
            if len(profile.encode()) > 4_000_000:
                raise CapabilityReportUnavailable("CAPABILITY_REPORT_LIMIT")
            try:
                profile = json.loads(profile)
            except (TypeError, ValueError):
                raise CapabilityReportUnavailable("CAPABILITY_PROFILE_INVALID") from None
        discovered = row["discovered_at"]
        reason = ""
        if not row["enabled"]:
            reason = "SOURCE_DISABLED"
        elif isinstance(row.get("profile_bytes"), int) and row["profile_bytes"] > 131072:
            reason = "PROFILE_TOO_LARGE"
        elif not isinstance(profile, dict) or not profile:
            reason = "PROFILE_MISSING"
        elif (type(profile.get("schema_version")) is not int or profile.get("schema_version") != 1
              or profile.get("source_id") != source_id or profile.get("evidence_source") != "live-metadata"
              or not isinstance(profile.get("registers"), list)):
            reason = "PROFILE_UNCONFIRMED"
        elif (row["adapter_profile"] != "ODATA_JSON_V3" or row["compatibility_status"] != "SUPPORTED"
              or row["metadata_supported"] is not True or row["json_supported"] is not True):
            reason = "ADAPTER_UNSUPPORTED"
        elif row["drift_status"] != "STABLE":
            reason = "METADATA_DRIFT"
        elif (not isinstance(row["metadata_fingerprint"], str) or not _HASH.fullmatch(row["metadata_fingerprint"])
              or profile.get("metadata_fingerprint") != row["metadata_fingerprint"]):
            reason = "FINGERPRINT_MISMATCH"
        elif (not isinstance(discovered, datetime) or discovered.tzinfo is None
              or not 0 <= (now - discovered).total_seconds() <= ttl_seconds):
            reason = "PROFILE_STALE"
        registers = profile.get("registers", []) if isinstance(profile, dict) else []
        safe_fingerprint = row["metadata_fingerprint"]
        if not isinstance(safe_fingerprint, str) or not _HASH.fullmatch(safe_fingerprint):
            safe_fingerprint = None
        if not isinstance(registers, list) or len(registers) > 250:
            raise CapabilityReportUnavailable("CAPABILITY_PROFILE_INVALID")
        methods_found = False
        for register in registers:
            if (not isinstance(register, dict) or not isinstance(register.get("entity_set"), str)
                    or not re.fullmatch(r"(?:Accounting|Accumulation|Information)Register_[\w]+", register["entity_set"])
                    or len(register["entity_set"]) > 256 or not isinstance(register.get("methods"), dict)
                    or len(register["methods"]) > 32):
                raise CapabilityReportUnavailable("CAPABILITY_PROFILE_INVALID")
            for method, evidence in register["methods"].items():
                if len(output) >= 20_000:
                    raise CapabilityReportUnavailable("CAPABILITY_REPORT_LIMIT")
                if not isinstance(method, str) or not _ID.fullmatch(method) or not isinstance(evidence, dict):
                    raise CapabilityReportUnavailable("CAPABILITY_PROFILE_INVALID")
                methods_found = True
                failure = reason or ("" if evidence.get("available") is True else "OPERATION_UNCONFIRMED")
                output.append({"source_id": source_id, "entity_set": register["entity_set"],
                               "operation": method, "status": "STALE" if failure == "PROFILE_STALE" else
                               "UNSUPPORTED" if failure else "SUPPORTED", "reason": failure or "CONFIRMED",
                               "evidence_kind": "live-metadata", "fingerprint": safe_fingerprint})
        if not methods_found:
            output.append({"source_id": source_id, "entity_set": "", "operation": "profile",
                           "status": "STALE" if reason == "PROFILE_STALE" else "UNVALIDATED",
                           "reason": reason or "NO_REGISTER_EVIDENCE", "evidence_kind": "none",
                           "fingerprint": safe_fingerprint})
    keys = {(item["source_id"], item["entity_set"], item["operation"]) for item in output}
    if len(keys) != len(output) or len(output) > 20_000:
        raise CapabilityReportUnavailable("CAPABILITY_PROFILE_INVALID")
    return sorted(output, key=lambda item: (item["source_id"], item["entity_set"], item["operation"]))


async def load_registry(connection, *, source_id: str | None = None, ttl_seconds=60) -> list[dict]:
    if source_id is not None and not _ID.fullmatch(source_id):
        raise CapabilityReportUnavailable("CAPABILITY_SOURCE_INVALID")
    # One repeatable read-only snapshot. No refresh, acknowledgement or mutation is authorized.
    async with connection.transaction(isolation="repeatable_read", readonly=True):
        rows = await connection.fetch(QUERY, source_id, timeout=10)
    return report_rows(rows, now=datetime.now(UTC), ttl_seconds=ttl_seconds)


def unsupported_reason(report: list[dict], *, source_id: str, entity_set: str, method: str) -> dict:
    if (not isinstance(source_id, str) or not _ID.fullmatch(source_id)
            or not isinstance(method, str) or not _ID.fullmatch(method)
            or not isinstance(entity_set, str) or len(entity_set) > 256
            or not re.fullmatch(r"(?:Accounting|Accumulation|Information)Register_[\w]+", entity_set)):
        raise CapabilityReportUnavailable("CAPABILITY_SELECTOR_INVALID")
    match = next((item for item in report if item["source_id"] == source_id
                  and item["entity_set"] == entity_set and item["operation"] == method), None)
    if match is not None:
        return {**match, "error_code": None if match["status"] == "SUPPORTED" else "CAPABILITY_UNSUPPORTED"}
    return {"source_id": source_id, "entity_set": entity_set, "operation": method,
                     "status": "UNSUPPORTED", "reason": "OPERATION_UNCONFIRMED",
                     "error_code": "CAPABILITY_UNSUPPORTED"}


async def run(args) -> dict:
    if args.command == "capability-diff":
        return {"diagnostic_only": True, "changes": diff_reports(args.before, args.after)}
    settings = Settings()
    connection = None
    try:
        connection = await asyncpg.connect(settings.database_url, timeout=10)
        report = await load_registry(connection, source_id=args.source_id,
                                     ttl_seconds=settings.metadata_cache_ttl_seconds)
    except Exception:  # noqa: BLE001 - never print DSNs, hostnames or driver exception details
        raise CapabilityReportUnavailable("CAPABILITY_REPORT_UNAVAILABLE") from None
    finally:
        if connection is not None:
            try:
                await connection.close(timeout=5)
            except Exception:  # noqa: BLE001 - do not expose connection cleanup diagnostics
                raise CapabilityReportUnavailable("CAPABILITY_REPORT_UNAVAILABLE") from None
    if args.command == "stale-profile":
        report = [item for item in report if item["status"] == "STALE" or item["reason"] == "METADATA_DRIFT"]
    if args.command == "unsupported-reason":
        report = [unsupported_reason(report, source_id=args.source_id, entity_set=args.register, method=args.method)]
    manifest = {"schema_version": 1, "diagnostic_only": True, "authorization_checked": False,
                "protocol_calls": 0, "entries": len(report), "report": report}
    if args.command == "export-evidence-manifest":
        target = args.output.resolve()
        repo = Path(__file__).resolve().parents[1]
        if target == repo or repo in target.parents:
            raise CapabilityReportUnavailable("PRIVATE_EVIDENCE_MUST_STAY_OUTSIDE_REPOSITORY")
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        with target.open("x", encoding="utf-8", newline="\n") as file:
            file.write(encoded)
        return {"entries": len(report), "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                "diagnostic_only": True, "private_output_created": True}
    if not args.details:
        return {"diagnostic_only": True, "authorization_checked": False, "entries": len(report),
                "protocol_calls": 0,
                "error_codes": sorted({item["error_code"] for item in report if item.get("error_code")}),
                "reasons": {reason: sum(item["reason"] == reason for item in report)
                            for reason in sorted({item["reason"] for item in report})},
                "statuses": {status: sum(item["status"] == status for item in report)
                             for status in ("SUPPORTED", "UNSUPPORTED", "STALE", "UNVALIDATED")}}
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("capability-list", "stale-profile", "unsupported-reason", "export-evidence-manifest"):
        command = commands.add_parser(name)
        command.add_argument("--source-id", required=name == "unsupported-reason")
        command.add_argument("--details", action="store_true", help="private operator output; never publish")
        if name == "unsupported-reason":
            command.add_argument("--register", required=True)
            command.add_argument("--method", required=True)
        if name == "export-evidence-manifest":
            command.add_argument("--output", type=Path, required=True)
    diff = commands.add_parser("capability-diff")
    diff.add_argument("--before", type=Path, required=True)
    diff.add_argument("--after", type=Path, required=True)
    return result


def main() -> None:
    try:
        manifest = asyncio.run(run(parser().parse_args()))
    except (CapabilityReportUnavailable, OSError, TypeError, ValueError, RecursionError):
        raise SystemExit("CAPABILITY_REPORT_FAILED") from None
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
