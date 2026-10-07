import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.capability_registry_cli import (
    CapabilityReportUnavailable,
    load_registry,
    parser,
    report_rows,
    run,
    unsupported_reason,
)
from scripts.capability_report import diff_reports, evidence_manifest

NOW = datetime(2026, 10, 6, tzinfo=UTC)
REGISTER = "AccountingRegister_Fixture"


def row():
    return {"source_id": "fixture", "enabled": True, "discovered_at": NOW,
            "compatibility_status": "SUPPORTED", "metadata_supported": True, "json_supported": True,
            "metadata_fingerprint": "a" * 64, "adapter_profile": "ODATA_JSON_V3", "drift_status": "STABLE",
            "register_capabilities_json": {"schema_version": 1, "source_id": "fixture",
                "evidence_source": "live-metadata", "metadata_fingerprint": "a" * 64,
                "registers": [{"entity_set": REGISTER, "methods": {"drCrTurnovers": {"available": True}}}]}}


def test_exact_source_live_profile_has_diagnostic_support_not_authority():
    report = report_rows([row()], now=NOW, ttl_seconds=60)
    assert report[0]["status"] == "SUPPORTED"
    result = unsupported_reason(report, source_id="fixture", entity_set=REGISTER, method="balance")
    assert result["error_code"] == "CAPABILITY_UNSUPPORTED"
    assert result["reason"] == "OPERATION_UNCONFIRMED"


@pytest.mark.parametrize("field,value,reason", [
    ("enabled", False, "SOURCE_DISABLED"), ("drift_status", "DRIFTED", "METADATA_DRIFT"),
    ("adapter_profile", "HTTP_QUERY_FALLBACK", "ADAPTER_UNSUPPORTED"),
    ("metadata_supported", False, "ADAPTER_UNSUPPORTED"),
    ("json_supported", False, "ADAPTER_UNSUPPORTED"),
    ("profile_bytes", 131073, "PROFILE_TOO_LARGE"),
    ("discovered_at", NOW - timedelta(seconds=61), "PROFILE_STALE"),
    ("discovered_at", NOW + timedelta(seconds=1), "PROFILE_STALE"),
    ("metadata_fingerprint", "b" * 64, "FINGERPRINT_MISMATCH"),
])
def test_diagnostic_fails_closed_for_disabled_drifted_stale_or_other_adapter(field, value, reason):
    candidate = row()
    candidate[field] = value
    report = report_rows([candidate], now=NOW, ttl_seconds=60)
    assert report[0]["status"] != "SUPPORTED" and report[0]["reason"] == reason


@pytest.mark.parametrize("change", ["wrong_source", "no_evidence", "false", "string_true", "missing"])
def test_upstream_method_presence_is_not_confirmation(change):
    candidate = row()
    profile = candidate["register_capabilities_json"]
    if change == "wrong_source":
        profile["source_id"] = "other"
    elif change == "no_evidence":
        profile["evidence_source"] = "upstream-api"
    else:
        evidence = profile["registers"][0]["methods"]["drCrTurnovers"]
        evidence.clear()
        if change != "missing":
            evidence["available"] = False if change == "false" else "true"
    report = report_rows([candidate], now=NOW, ttl_seconds=60)
    assert report[0]["status"] != "SUPPORTED"


def test_duplicate_profile_method_is_not_silently_collapsed():
    candidate = row()
    registers = candidate["register_capabilities_json"]["registers"]
    registers.append(registers[0])
    with pytest.raises(CapabilityReportUnavailable):
        report_rows([candidate], now=NOW, ttl_seconds=60)


@pytest.mark.asyncio
async def test_db_snapshot_is_readonly_repeatable_and_does_not_read_secret_columns():
    captured = {}

    class Connection:
        @asynccontextmanager
        async def transaction(self, **kwargs):
            captured["transaction"] = kwargs
            yield

        async def fetch(self, query, source, **kwargs):
            captured.update(query=query, source=source, kwargs=kwargs)
            return []

    assert await load_registry(Connection(), source_id="fixture") == []
    assert captured["transaction"] == {"isolation": "repeatable_read", "readonly": True}
    assert captured["source"] == "fixture" and captured["kwargs"]["timeout"] == 10
    for forbidden in ("base_url", "password", "username", "display_name", "INSERT", "UPDATE", "DELETE"):
        assert forbidden not in captured["query"]


def test_diff_keeps_same_method_on_different_registers_and_accepts_private_manifest(tmp_path):
    before = report_rows([row()], now=NOW, ttl_seconds=60)
    after = [*before, {**before[0], "entity_set": "AccountingRegister_Other", "status": "UNSUPPORTED"}]
    left, right = tmp_path / "left.json", tmp_path / "right.json"
    left.write_text(json.dumps({"schema_version": 1, "diagnostic_only": True, "report": before}))
    right.write_text(json.dumps({"schema_version": 1, "diagnostic_only": True, "report": after}))
    changes = diff_reports(left, right)
    assert len(changes) == 1 and changes[0]["entity_set"] == "AccountingRegister_Other"
    assert str(tmp_path) not in str(evidence_manifest(right))


def test_cli_has_all_mandatory_commands_without_dsn_argument():
    for command in ("capability-list", "stale-profile"):
        assert parser().parse_args([command]).command == command
    args = parser().parse_args(["unsupported-reason", "--source-id", "fixture",
                               "--register", REGISTER, "--method", "drCrTurnovers"])
    assert args.method == "drCrTurnovers"
    assert "dsn" not in vars(args)


def test_capability_diff_detects_reason_changes_and_rejects_duplicate_rows(tmp_path):
    before = report_rows([row()], now=NOW, ttl_seconds=60)
    before[0].update(status="UNSUPPORTED", reason="SOURCE_DISABLED")
    after = [{**before[0], "reason": "METADATA_DRIFT"}]
    left, right = tmp_path / "left.json", tmp_path / "right.json"
    left.write_text(json.dumps(before))
    right.write_text(json.dumps(after))
    assert diff_reports(left, right)[0]["after"]["reason"] == "METADATA_DRIFT"
    right.write_text(json.dumps(after * 2))
    with pytest.raises(ValueError, match="duplicate"):
        diff_reports(left, right)


@pytest.mark.asyncio
async def test_cli_default_output_is_aggregate_and_private_export_does_not_overwrite(monkeypatch, tmp_path):
    import scripts.capability_registry_cli as cli

    candidate = row()
    candidate["discovered_at"] = datetime.now(UTC)

    class Connection:
        @asynccontextmanager
        async def transaction(self, **_kwargs):
            yield

        async def fetch(self, *_args, **_kwargs):
            return [candidate]

        async def close(self, **_kwargs):
            return None

    async def connect(*_args, **_kwargs):
        return Connection()

    monkeypatch.setattr(cli.asyncpg, "connect", connect)
    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(database_url="synthetic", metadata_cache_ttl_seconds=60))
    result = await run(parser().parse_args(["capability-list"]))
    assert result["entries"] == 1 and result["protocol_calls"] == 0
    assert "fixture" not in str(result) and REGISTER not in str(result)
    target = tmp_path / "private-capability-export.json"
    args = parser().parse_args(["export-evidence-manifest", "--output", str(target)])
    result = await run(args)
    assert result["private_output_created"] is True and str(target) not in str(result)
    original = target.read_bytes()
    assert result["sha256"] == hashlib.sha256(original).hexdigest()
    with pytest.raises(FileExistsError):
        await run(args)
    assert target.read_bytes() == original
    args.output = Path(__file__).resolve().parents[1] / "private-test-never-written.json"
    with pytest.raises(CapabilityReportUnavailable, match="OUTSIDE_REPOSITORY"):
        await run(args)


@pytest.mark.asyncio
async def test_cli_connection_error_does_not_leak_driver_details(monkeypatch):
    import scripts.capability_registry_cli as cli

    async def failed(*_args, **_kwargs):
        raise RuntimeError("PRIVATE-CONNECTION-DETAIL")

    monkeypatch.setattr(cli.asyncpg, "connect", failed)
    with pytest.raises(CapabilityReportUnavailable) as failure:
        await run(parser().parse_args(["capability-list"]))
    assert "PRIVATE-CONNECTION-DETAIL" not in str(failure.value)
    assert failure.value.__cause__ is None
