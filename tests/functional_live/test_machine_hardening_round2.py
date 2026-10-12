"""PostgreSQL tests for the second machine-profile hardening round (F-1, F-5, F-6, F-7, F-8).

Synthetic data only.  Every test runs inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

import asyncpg
import pytest

from business_ai_gateway.analytics_balance import ANALYTICS_BALANCE_CONCEPT
from business_ai_gateway.semantic import SemanticProfileUnavailable
from scripts.semantic_profiles import reverify_profile
from tests.functional_live.test_machine_profile_functional import (
    _insert_scope_mapping,
    _native_validated,
)
from tests.test_machine_profile_postgres import (
    PLAN_ID,
    ConnectionDatabase,
    _machine_registry,
    _validated,
)

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires the disposable PostgreSQL database")


@pytest.fixture
def machine_env(monkeypatch):
    monkeypatch.setenv("BAG_ENVIRONMENT", "test")


class _Tx:
    async def __aenter__(self):
        self.conn = await asyncpg.connect(DATABASE_URL)
        self.tx = self.conn.transaction()
        await self.tx.start()
        return self.conn

    async def __aexit__(self, *exc):
        await self.tx.rollback()
        await self.conn.close()


def _reverify_args(profile_id, tmp_path):
    return SimpleNamespace(
        profile_id=str(profile_id), actor="op", artifacts_root=str(tmp_path / "artifacts"),
        plans_dir=str(tmp_path / "plans"),
    )


async def _status(conn, profile_id):
    return await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id)


# ---------------------------------------------------------------- F-1


@pytest.mark.asyncio
async def test_reverify_keeps_a_profile_whose_proof_still_holds(tmp_path, machine_env, monkeypatch):
    async with _Tx() as conn:
        _, _, profile_id = await _validated(conn, tmp_path, monkeypatch)
        assert await reverify_profile(_reverify_args(profile_id, tmp_path), conn) is True
        assert await _status(conn, profile_id) == "VALIDATED"


@pytest.mark.asyncio
async def test_reverify_marks_the_profile_stale_when_an_artifact_byte_changes(tmp_path, machine_env, monkeypatch):
    async with _Tx() as conn:
        source_id, company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        victim = tmp_path / "artifacts" / "case-3" / "side_a.json"
        victim.write_bytes(victim.read_bytes() + b" ")
        assert await reverify_profile(_reverify_args(profile_id, tmp_path), conn) is False
        assert await _status(conn, profile_id) == "STALE"
        event = await conn.fetchrow(
            "SELECT action, details_json FROM bag.semantic_profile_events WHERE profile_id=$1 "
            "AND details_json->>'reason'='MACHINE_REVERIFY_FAILED'",
            profile_id,
        )
        assert event is not None and event["action"] == "MAPPING_CHANGED_INVALIDATED"
        details = json.loads(event["details_json"]) if isinstance(event["details_json"], str) else event["details_json"]
        assert details["reason"] == "MACHINE_REVERIFY_FAILED"
        assert details["evidence_basis"] == "MACHINE"
        assert "digest mismatch" in details["detail"]
        # the serving path no longer resolves the profile
        with pytest.raises(SemanticProfileUnavailable):
            await _machine_registry(conn, source_id).require_semantic_mapping(
                source_id, company_id, ANALYTICS_BALANCE_CONCEPT
            )


@pytest.mark.asyncio
async def test_reverify_marks_the_profile_stale_when_the_plan_is_no_longer_approved(
    tmp_path, machine_env, monkeypatch
):
    async with _Tx() as conn:
        _, _, profile_id = await _validated(conn, tmp_path, monkeypatch)
        plan_file = tmp_path / "plans" / f"{PLAN_ID}.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["status"] = "cancelled"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        assert await reverify_profile(_reverify_args(profile_id, tmp_path), conn) is False
        assert await _status(conn, profile_id) == "STALE"


@pytest.mark.asyncio
async def test_reverify_refuses_a_native_profile_and_leaves_it_validated(tmp_path, machine_env):
    async with _Tx() as conn:
        _, _, profile_id = await _native_validated(conn, tmp_path)
        with pytest.raises(ValueError, match="machine-reconciled"):
            await reverify_profile(_reverify_args(profile_id, tmp_path), conn)
        assert await _status(conn, profile_id) == "VALIDATED"


# ---------------------------------------------------------------- F-6


@pytest.mark.asyncio
async def test_validation_event_tells_machine_from_native(tmp_path, machine_env, monkeypatch):
    async with _Tx() as conn:
        (tmp_path / "m").mkdir()
        (tmp_path / "n").mkdir()
        _, _, machine_id = await _validated(conn, tmp_path / "m", monkeypatch)
        _, _, native_id = await _native_validated(conn, tmp_path / "n")
        rows = {}
        for key, pid in (("machine", machine_id), ("native", native_id)):
            raw = await conn.fetchval(
                "SELECT details_json FROM bag.semantic_profile_events WHERE profile_id=$1 AND action='VALIDATED'", pid
            )
            rows[key] = json.loads(raw) if isinstance(raw, str) else raw
        assert rows["machine"]["evidence_basis"] == "MACHINE"
        assert rows["machine"]["authorized_by"] and rows["machine"]["evidence_manifest_fingerprint"]
        assert rows["native"]["evidence_basis"] == "NATIVE"
        assert "authorized_by" not in rows["native"]


# ---------------------------------------------------------------- F-5


@pytest.mark.asyncio
async def test_machine_company_scope_exclusion_names_its_real_cause(tmp_path, machine_env, monkeypatch):
    from business_ai_gateway.admin_access import explain_access
    from business_ai_gateway.company_scope import CompanyScopeResolver, CompanyScopeUnavailable

    async with _Tx() as conn:
        source_id, company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        await _insert_scope_mapping(conn, profile_id)
        meta = await conn.fetchval(
            "SELECT metadata_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        )
        with pytest.raises(CompanyScopeUnavailable, match="machine-reconciled"):
            await CompanyScopeResolver(ConnectionDatabase(conn)).mapping(
                source=SimpleNamespace(id=source_id), company=SimpleNamespace(id=company_id),
                entity_set="Document_X", metadata_fingerprint=meta, drift_status="STABLE",
            )
        # an unrelated entity set still reports the generic cause
        with pytest.raises(CompanyScopeUnavailable, match="no validated company-scope mapping"):
            await CompanyScopeResolver(ConnectionDatabase(conn)).mapping(
                source=SimpleNamespace(id=source_id), company=SimpleNamespace(id=company_id),
                entity_set="Other_Set", metadata_fingerprint=meta, drift_status="STABLE",
            )
        ctx = SimpleNamespace(token=SimpleNamespace(subject="s"), groups=[])
        explained = await explain_access(
            conn, ctx=ctx, kind="subject", principal_id="s", source_id=source_id,
            entity_set="Document_X", limit=50, offset=0,
        )
        operations = {item["company_operation"] for item in explained["items"]}
        assert operations == {"profile_not_native_validated"}


# ---------------------------------------------------------------- F-7


@pytest.mark.asyncio
async def test_profile_lookup_prefers_native_over_machine_on_equal_scope(tmp_path, machine_env, monkeypatch):
    """Two VALIDATED profiles for one source/company/concept: the native one must win, deterministically."""
    async with _Tx() as conn:
        source_id, company_id, machine_id = await _validated(conn, tmp_path, monkeypatch)
        native_id = uuid.uuid4()
        # Clone the machine profile row as a native one with a LOWER version, so version order alone would pick machine.
        columns = [
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='bag' "
                "AND table_name='semantic_profiles'"
            )
        ]
        await conn.execute("ALTER TABLE bag.semantic_profiles DISABLE TRIGGER USER")
        await conn.execute(
            "UPDATE bag.semantic_profiles SET profile_version=2 WHERE profile_id=$1", machine_id
        )
        select_list = ", ".join(
            "$1::uuid" if c == "profile_id" else ("1" if c == "profile_version" else f"p.{c}") for c in columns
        )
        await conn.execute(
            f"INSERT INTO bag.semantic_profiles({', '.join(columns)}) "
            f"SELECT {select_list} FROM bag.semantic_profiles p WHERE p.profile_id=$2",
            native_id, machine_id,
        )
        native_evidence = {
            "native_reconciliation_cases": [
                {"case_id": f"n-{i}", "status": "PASS", "native_report_ref": f"r-{i}"} for i in range(10)
            ]
        }
        await conn.execute(
            "UPDATE bag.semantic_profiles SET validation_evidence_json=$2::jsonb WHERE profile_id=$1",
            native_id, json.dumps(native_evidence),
        )
        mapping = await conn.fetchrow(
            "SELECT * FROM bag.semantic_mappings WHERE profile_id=$1", machine_id
        )
        mapping_columns = list(mapping.keys())
        values = ", ".join(
            "$1::uuid" if c == "profile_id" else ("gen_random_uuid()" if c == "mapping_id" else f"m.{c}")
            for c in mapping_columns
        )
        await conn.execute(
            f"INSERT INTO bag.semantic_mappings({', '.join(mapping_columns)}) "
            f"SELECT {values} FROM bag.semantic_mappings m WHERE m.profile_id=$2",
            native_id, machine_id,
        )
        # the mapping trigger demotes a validated profile; restore the cloned profile to VALIDATED
        await conn.execute("UPDATE bag.semantic_profiles SET status='VALIDATED' WHERE profile_id=$1", native_id)
        served = await _machine_registry(conn, source_id).require_semantic_mapping(
            source_id, company_id, ANALYTICS_BALANCE_CONCEPT
        )
        assert served["profile_kind"] == "VALIDATED_NATIVE"


# ---------------------------------------------------------------- F-8


@pytest.mark.asyncio
async def test_portfolio_probe_raises_when_source_upsert_fails(monkeypatch):
    import subprocess

    from scripts.real1c import probes

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3, stdout="", stderr="boom")
    )
    lane = SimpleNamespace(env=SimpleNamespace(dsn=lambda role: f"postgresql://{role}@localhost/x"))
    with pytest.raises(RuntimeError, match="source-upsert failed"):
        await probes.probe_portfolio(lane, companies=2)


# ---------------------------------------------------------------- F-6 (list)


@pytest.mark.asyncio
async def test_profile_list_exposes_the_evidence_basis(tmp_path, machine_env, monkeypatch):
    from business_ai_gateway.admin_api import AdminRepository

    async with _Tx() as conn:
        (tmp_path / "m").mkdir()
        (tmp_path / "n").mkdir()
        _, _, machine_id = await _validated(conn, tmp_path / "m", monkeypatch)
        _, _, native_id = await _native_validated(conn, tmp_path / "n")
        ctx = SimpleNamespace(source_scope=lambda *roles: None, selected_source=None, page_limit=None, page_offset=0)
        items = await AdminRepository(ConnectionDatabase(conn)).list_profiles(ctx)
        basis = {item["profile_id"]: item["evidence_basis"] for item in items}
        assert basis[str(machine_id)] == "MACHINE"
        assert basis[str(native_id)] == "NATIVE"
