"""Actual database snapshot/DrCr negative-positive diagnostics using synthetic fixture rows."""
import json
import os
import uuid

import asyncpg
import pytest

from scripts.capability_registry_cli import load_registry, unsupported_reason

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_persisted_source_confirmation_and_stale_drift_diagnostics_are_read_only():
    connection = await asyncpg.connect(DATABASE_URL)
    source_id = f"cap-cli-{uuid.uuid4()}"
    register = "AccountingRegister_Fixture"
    created = False
    snapshot_states = []

    class ReadonlyRecorder:
        def transaction(self, **kwargs):
            return connection.transaction(**kwargs)

        async def fetch(self, query, *args, **kwargs):
            snapshot_states.append(await connection.fetchval("SHOW transaction_read_only"))
            return await connection.fetch(query, *args, **kwargs)

    reader = ReadonlyRecorder()
    try:
        await connection.execute("""INSERT INTO bag.sources(source_id,project,kind,display_name,base_url)
                                   VALUES($1,'onec','onec_auto','synthetic fixture','https://fixture.invalid')""", source_id)
        created = True
        profile = {"schema_version": 1, "source_id": source_id, "evidence_source": "live-metadata",
                   "metadata_fingerprint": "a" * 64, "registers": [{"entity_set": register,
                       "methods": {"drCrTurnovers": {"available": False}}}]}
        await connection.execute("""INSERT INTO bag.source_capabilities(source_id,metadata_fingerprint,
            compatibility_status,adapter_profile,metadata_supported,json_supported,atom_supported,
            entity_set_count,evidence_json,register_capabilities_json,drift_status)
            VALUES($1,$2,'SUPPORTED','ODATA_JSON_V3',true,true,false,1,'{}',$3::jsonb,'STABLE')""",
            source_id, "a" * 64, json.dumps(profile))
        before = await connection.fetchval("SELECT row_to_json(c)::text FROM bag.source_capabilities c WHERE source_id=$1", source_id)
        report = await load_registry(reader, source_id=source_id)
        denial = unsupported_reason(report, source_id=source_id, entity_set=register, method="drCrTurnovers")
        assert denial["error_code"] == "CAPABILITY_UNSUPPORTED"
        assert report[0]["reason"] == "OPERATION_UNCONFIRMED"
        after = await connection.fetchval("SELECT row_to_json(c)::text FROM bag.source_capabilities c WHERE source_id=$1", source_id)
        assert before == after
        profile["registers"][0]["methods"]["drCrTurnovers"]["available"] = True
        await connection.execute("UPDATE bag.source_capabilities SET register_capabilities_json=$2::jsonb WHERE source_id=$1", source_id, json.dumps(profile))
        assert (await load_registry(reader, source_id=source_id))[0]["status"] == "SUPPORTED"
        await connection.execute("UPDATE bag.source_capabilities SET discovered_at=now()-interval '2 hours' WHERE source_id=$1", source_id)
        assert (await load_registry(reader, source_id=source_id))[0]["status"] == "STALE"
        await connection.execute("UPDATE bag.source_capabilities SET discovered_at=now(),drift_status='DRIFTED' WHERE source_id=$1", source_id)
        assert (await load_registry(reader, source_id=source_id))[0]["reason"] == "METADATA_DRIFT"
        profile["padding"] = "x" * 131073
        await connection.execute("UPDATE bag.source_capabilities SET drift_status='STABLE',register_capabilities_json=$2::jsonb WHERE source_id=$1", source_id, json.dumps(profile))
        assert (await load_registry(reader, source_id=source_id))[0]["reason"] == "PROFILE_TOO_LARGE"
        assert snapshot_states == ["on"] * 5
    finally:
        if created:
            await connection.execute("DELETE FROM bag.sources WHERE source_id=$1", source_id)
        await connection.close()
