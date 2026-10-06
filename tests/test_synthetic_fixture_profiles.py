from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.fixture_profiles import SyntheticFixtureProfiles
from business_ai_gateway.registry import Registry
from business_ai_gateway.runtime import Runtime
from business_ai_gateway.semantic import SemanticProfileUnavailable, canonical_fingerprint
from business_ai_gateway.settings import Settings
from scripts import synthetic_fixture_profiles as fixture_gen
from tests.sc_stack import (
    ORG_ONE,
    ORG_TWO,
    build_stack,
    fixture_document,
    write_fixture_file,
)

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
needs_pg = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL")
START = "2026-04-01T00:00:00+00:00"
END = "2026-04-30T00:00:00+00:00"


async def _stack(fake1c, fake_sidecar, tmp_path, monkeypatch, *, tags=("synthetic-fixture",), listed=True):
    companies = {ORG_ONE: uuid.uuid4(), ORG_TWO: uuid.uuid4()}
    source_id = f"psc-{uuid.uuid4().hex[:12]}"
    document = fixture_document(source_id if listed else "some-other-source", companies)
    path = tmp_path / "profiles.json"
    sha = write_fixture_file(path, document)
    return await build_stack(
        DATABASE_URL, fake1c, fake_sidecar, fixture_file=path, fixture_sha=sha, tags=tags,
        source_id=source_id, companies=companies, env_setter=monkeypatch.setenv,
    )


# ---------------------------------------------------------------- committed fixture file


def test_committed_fixture_file_is_pinned_to_live_fake1c_metadata():
    committed = fixture_gen.FIXTURE_PATH.read_bytes()
    assert committed == fixture_gen.render(), "re-pin: python scripts/synthetic_fixture_profiles.py --write"
    document = json.loads(committed)
    pinned = document["sources"][fixture_gen.SOURCE_ID]["metadata_fingerprint"]
    from starlette.testclient import TestClient

    from testbed.fake1c.app import create_app

    served = TestClient(create_app("json")).get("/odata/standard.odata/$metadata").content
    import hashlib

    assert pinned == hashlib.sha256(served).hexdigest()
    assert document["review"]["kind"] == "SYNTHETIC_FIXTURE"


# ---------------------------------------------------------------- deny layers (no DB needed)


def test_layer1_settings_deny_production_incomplete_and_non_test(tmp_path):
    path = str(tmp_path / "p.json")
    sha = "a" * 64
    with pytest.raises(ValueError, match="FORBIDDEN_IN_PRODUCTION"):
        Settings(_env_file=None, environment="production", synthetic_fixture_profiles_file=path,
                 synthetic_fixture_profiles_sha256=sha)
    with pytest.raises(ValueError, match="FORBIDDEN_IN_PRODUCTION"):
        Settings(_env_file=None, environment="production", synthetic_fixture_profiles_sha256=sha)
    with pytest.raises(ValueError, match="INCOMPLETE"):
        Settings(_env_file=None, environment="test", synthetic_fixture_profiles_file=path)
    with pytest.raises(ValueError, match="REQUIRE_TEST_ENVIRONMENT"):
        Settings(_env_file=None, environment="development", synthetic_fixture_profiles_file=path,
                 synthetic_fixture_profiles_sha256=sha)
    ok = Settings(_env_file=None, environment="test", synthetic_fixture_profiles_file=path,
                  synthetic_fixture_profiles_sha256=sha)
    assert ok.synthetic_fixture_profiles_file == path


def test_layer2_provider_and_registry_refuse_production(tmp_path):
    path = tmp_path / "p.json"
    sha = write_fixture_file(path, fixture_document("s"))
    for env in ("production", "development"):
        with pytest.raises(RuntimeError, match="FORBIDDEN_ENVIRONMENT"):
            SyntheticFixtureProfiles(path, sha, environment=env)
    provider = SyntheticFixtureProfiles(path, sha, environment="test")
    with pytest.raises(ValueError, match="FORBIDDEN_IN_PRODUCTION"):
        Registry(MagicMock(), production=True, synthetic_profiles=provider)
    provider.environment = "production"  # tampering: every lookup re-checks
    for call in (
        lambda: provider.lookup("s", uuid.uuid4(), "cash.movements"),
        lambda: provider.listed_sources(),
        lambda: provider.pinned_metadata_fingerprint("s"),
    ):
        with pytest.raises(SemanticProfileUnavailable):
            call()


@pytest.mark.asyncio
async def test_layer2_production_registry_never_consults_provider(tmp_path):
    path = tmp_path / "p.json"
    sha = write_fixture_file(path, fixture_document("s"))
    provider = SyntheticFixtureProfiles(path, sha, environment="test")
    spy = MagicMock(wraps=provider)
    registry = Registry(MagicMock(), production=False, synthetic_profiles=spy)
    registry.production = True  # simulate a production registry holding a stray provider
    with pytest.raises(SemanticProfileUnavailable):
        await registry._synthetic_mapping("s", uuid.uuid4(), "cash.movements")
    assert spy.method_calls == []


def test_layer4_hash_mismatch_fails_runtime_startup(tmp_path):
    path = tmp_path / "p.json"
    write_fixture_file(path, fixture_document("s"))
    with pytest.raises(RuntimeError, match="HASH_MISMATCH"):
        SyntheticFixtureProfiles(path, "0" * 64, environment="test")
    settings = Settings(_env_file=None, environment="test", synthetic_fixture_profiles_file=str(path),
                        synthetic_fixture_profiles_sha256="0" * 64)
    with pytest.raises(RuntimeError, match="HASH_MISMATCH"):
        Runtime(settings)


# ---------------------------------------------------------------- SC11 / SC12 chains


@needs_pg
@pytest.mark.asyncio
async def test_sc11_inventory_signed_deltas_through_mcp_fixture_profile_and_audit(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        result = await stack.call(
            "inventory_movements", source_id=stack.source_id,
            company_id=str(stack.companies[ORG_ONE]), start_period=START, end_period=END,
        )
        assert not result.is_error
        body = stack.payload(result)
        deltas = [Decimal(row["quantity_delta"]) for row in body["value"]]
        item1 = [r for r in body["value"] if r["item_ref"].endswith("0001")]
        deltas = [Decimal(r["quantity_delta"]) for r in item1]
        assert deltas == [Decimal(7), Decimal(-2)] and sum(deltas) == 5
        assert [row["direction"] for row in item1] == ["receipt", "expense"]
        assert body["profile_kind"] == "SYNTHETIC_FIXTURE"
        assert body["evidence_level"] == "L1"
        assert body["native_reconciliation"] == "NOT_RUN"
        assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" in body["warnings"]
        assert body["profile_fingerprint"].startswith("synthetic-fixture:")
        rows = await stack.audit_rows("inventory_movements")
        success = [r for r in rows if r["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE"]
        assert len(success) == 1 and success[0]["outcome"] == "success"
        assert success[0]["profile_fingerprint"] == body["profile_fingerprint"]
        # company two shares the profile but the company dimension filter yields no company-one rows
        other = stack.payload(await stack.call(
            "inventory_movements", source_id=stack.source_id,
            company_id=str(stack.companies[ORG_TWO]), start_period=START, end_period=END,
        ))
        assert other["value"] == []
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_sc12_cash_signed_deltas_through_mcp(fake1c, fake_sidecar, tmp_path, monkeypatch):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        body = stack.payload(await stack.call(
            "cash_movements", source_id=stack.source_id,
            company_id=str(stack.companies[ORG_ONE]), start_period=START, end_period=END,
        ))
        deltas = [Decimal(row["amount_delta"]) for row in body["value"]]
        assert deltas == [Decimal(10), Decimal(-3)] and sum(deltas) == 7
        assert body["profile_kind"] == "SYNTHETIC_FIXTURE" and body["native_reconciliation"] == "NOT_RUN"
        rows = await stack.audit_rows("cash_movements")
        assert any(r["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE" for r in rows)
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_ungranted_company_is_denied_before_any_upstream_business_read(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        stack.runtime.onec.read = AsyncMock()
        stack.runtime.onec.capabilities = AsyncMock()
        with pytest.raises(UnexpectedToolError):
            await stack.call(
                "inventory_movements", source_id=stack.source_id,
                company_id=str(uuid.uuid4()), start_period=START, end_period=END,
            )
        stack.runtime.onec.read.assert_not_awaited()
        stack.runtime.onec.capabilities.assert_not_awaited()
        rows = await stack.audit_rows("inventory_movements")
        assert [r["outcome"] for r in rows] == ["denied"]
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["untagged", "unlisted"])
async def test_layer3_untagged_or_unlisted_source_gets_no_fixture_profile(
    fake1c, fake_sidecar, tmp_path, monkeypatch, variant
):
    stack = await _stack(
        fake1c, fake_sidecar, tmp_path, monkeypatch,
        tags=() if variant == "untagged" else ("synthetic-fixture",),
        listed=variant != "unlisted",
    )
    try:
        stack.runtime.onec.read = AsyncMock()
        with pytest.raises(UnexpectedToolError):
            await stack.call(
                "inventory_movements", source_id=stack.source_id,
                company_id=str(stack.companies[ORG_ONE]), start_period=START, end_period=END,
            )
        stack.runtime.onec.read.assert_not_awaited()
        rows = await stack.audit_rows("inventory_movements")
        assert rows[-1]["outcome"] == "denied"
        assert rows[-1]["detail_code"] == "SEMANTIC_PROFILE_UNVALIDATED"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_stale_fixture_fingerprint_is_denied_as_schema_drift(fake1c, fake_sidecar, tmp_path, monkeypatch):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        provider = stack.runtime.registry.synthetic_profiles
        provider._sources[stack.source_id]["metadata_fingerprint"] = "f" * 64
        with pytest.raises(UnexpectedToolError):
            await stack.call(
                "cash_movements", source_id=stack.source_id,
                company_id=str(stack.companies[ORG_ONE]), start_period=START, end_period=END,
            )
        rows = await stack.audit_rows("cash_movements")
        assert rows[-1]["detail_code"] == "SCHEMA_DRIFT"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_validated_db_profile_always_wins_over_fixture_and_fixture_never_a_db_row(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    pool = stack.db.require_pool()
    args = {
        "source_id": stack.source_id,
        "company_id": str(stack.companies[ORG_ONE]),
        "start_period": START,
        "end_period": END,
    }
    try:
        await stack.call("inventory_movements", **args)  # fixture path records capabilities
        assert await pool.fetchval(
            "SELECT count(*) FROM bag.semantic_profiles WHERE source_id=$1", stack.source_id
        ) == 0
        cap = await pool.fetchrow(
            "SELECT metadata_fingerprint, register_capabilities_json FROM bag.source_capabilities "
            "WHERE source_id=$1", stack.source_id)
        caps = cap["register_capabilities_json"]
        caps = json.loads(caps) if isinstance(caps, str) else caps
        mapping = fixture_gen.concept_mappings()["inventory.movements"]
        mapping["record_type_values"] = {"receipt": ["Expense"], "expense": ["Receipt"]}
        profile_id = uuid.uuid4()
        await pool.execute(
            """INSERT INTO bag.semantic_profiles(profile_id, source_id, company_id, preset_id,
                 profile_name, profile_version, status, metadata_fingerprint,
                 capability_fingerprint, profile_fingerprint, preset_repository,
                 preset_upstream_sha, created_by)
               VALUES($1,$2,$3,'bp30','db-native',1,'DRAFT',$4,$5,'profile-db','r','s','test')""",
            profile_id, stack.source_id, stack.companies[ORG_ONE], cap["metadata_fingerprint"],
            canonical_fingerprint(caps))
        await pool.execute(
            "INSERT INTO bag.semantic_mappings(mapping_id, profile_id, canonical_concept, "
            "mapping_json, mapping_status, confidence) VALUES($1,$2,'inventory.movements',"
            "$3::jsonb,'CONFIRMED','HIGH')", uuid.uuid4(), profile_id, json.dumps(mapping))
        evidence = {"native_reconciliation_cases": [
            {"case_id": f"c{i}", "status": "PASS", "native_report_ref": f"ref/{i}"}
            for i in range(10)]}
        await pool.execute(
            "UPDATE bag.semantic_profiles SET status='VALIDATED', validated_by='t', "
            "validated_at=now(), validation_evidence_json=$2::jsonb WHERE profile_id=$1",
            profile_id, json.dumps(evidence))
        body = stack.payload(await stack.call("inventory_movements", **args))
        assert body["profile_kind"] == "VALIDATED_NATIVE"
        assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" not in body["warnings"]
        assert not body["profile_fingerprint"].startswith("synthetic-fixture:")
        item1 = [r for r in body["value"] if r["item_ref"].endswith("0001")]
        assert [Decimal(r["quantity_delta"]) for r in item1] == [Decimal(-7), Decimal(2)]
        # a VALIDATED row that is invalid never falls through to the fixture
        await pool.execute(
            "UPDATE bag.semantic_mappings SET mapping_json=$2::jsonb WHERE profile_id=$1",
            profile_id, json.dumps({"entity_set": "bad"}))
        with pytest.raises(UnexpectedToolError):
            await stack.call("inventory_movements", **args)
        rows = await stack.audit_rows("inventory_movements")
        assert rows[-1]["detail_code"] == "SEMANTIC_PROFILE_UNVALIDATED"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_admin_validation_with_fewer_than_ten_cases_is_still_rejected(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    import asyncpg

    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    pool = stack.db.require_pool()
    try:
        profile_id = uuid.uuid4()
        await pool.execute(
            """INSERT INTO bag.semantic_profiles(profile_id, source_id, company_id, preset_id,
                 profile_name, profile_version, status, metadata_fingerprint,
                 capability_fingerprint, profile_fingerprint, preset_repository,
                 preset_upstream_sha, created_by)
               VALUES($1,$2,$3,'bp30','x',1,'DRAFT','m','c','p','r','s','test')""",
            profile_id, stack.source_id, stack.companies[ORG_ONE])
        nine = {"native_reconciliation_cases": [
            {"case_id": f"c{i}", "status": "PASS", "native_report_ref": f"r{i}"} for i in range(9)]}
        with pytest.raises(asyncpg.CheckViolationError):
            await pool.execute(
                "UPDATE bag.semantic_profiles SET status='VALIDATED', validated_by='t', "
                "validated_at=now(), validation_evidence_json=$2::jsonb WHERE profile_id=$1",
                profile_id, json.dumps(nine))
        assert Path(fixture_gen.FIXTURE_PATH).exists()
    finally:
        await stack.db.close()
