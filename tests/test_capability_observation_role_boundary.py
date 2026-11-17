"""Focused PostgreSQL check for the capability writer/acceptor role boundary."""
import os
import uuid

import asyncpg
import pytest

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL")


@pytest.mark.asyncio
async def test_business_ai_app_cannot_forge_stable_observation():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"m2-synthetic-{uuid.uuid4()}"
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'M2 synthetic source', 'http://fake.invalid/odata')
            """,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.source_capabilities(
                source_id, metadata_fingerprint, compatibility_status, adapter_profile,
                metadata_supported, json_supported, atom_supported, entity_set_count,
                evidence_json, register_capabilities_json, drift_status
            )
            VALUES($1, $2, 'SUPPORTED', 'ODATA_JSON_V3', true, true, false, 1,
                   '{}'::jsonb, '{}'::jsonb, 'NEEDS_VALIDATION')
            """,
            source_id,
            "a" * 64,
        )

        writer_signature = (
            "bag.record_capability_observation(text,uuid,bigint,text,text,text,text,boolean,"
            "boolean,boolean,boolean,integer,jsonb,jsonb)"
        )
        acceptor_signature = "bag.accept_capability_observation(text,uuid,bigint)"
        reader_signature = "bag.read_accepted_capability_observation(text,uuid,bigint)"
        assert await conn.fetchval(
            "SELECT has_function_privilege('business_ai_app', $1::regprocedure, 'EXECUTE')",
            writer_signature,
        ) is False
        assert await conn.fetchval(
            "SELECT has_function_privilege('business_ai_app', $1::regprocedure, 'EXECUTE')",
            acceptor_signature,
        ) is False
        assert await conn.fetchval(
            "SELECT has_function_privilege('business_ai_app', $1::regprocedure, 'EXECUTE')",
            reader_signature,
        ) is True
        for role in ("business_ai_admin", "business_ai_control_api"):
            assert await conn.fetchval(
                "SELECT has_function_privilege($1, $2::regprocedure, 'EXECUTE')",
                role,
                reader_signature,
            ) is False

        await conn.execute("SET LOCAL ROLE business_ai_app")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE bag.source_capabilities SET drift_status='STABLE' WHERE source_id=$1",
                    source_id,
                )

        assert await conn.fetchval("SELECT current_user") == "business_ai_app"
        assert await conn.fetchval(
            "SELECT count(*) FROM bag.read_accepted_capability_observation($1, $2::uuid, 1)",
            source_id,
            str(uuid.uuid4()),
        ) == 0

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.fetchval(
                    """
                    SELECT bag.record_capability_observation(
                        $1, $2::uuid, $3::bigint, $4, $5, 'SUPPORTED', 'ODATA_JSON_V3',
                        true, true, false, false, 1, '{}'::jsonb, '{}'::jsonb
                    )
                    """,
                    source_id,
                    str(uuid.uuid4()),
                    1,
                    "a" * 64,
                    "8.3.synthetic",
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.fetchval(
                    "SELECT * FROM bag.accept_capability_observation($1, $2::uuid, 1)",
                    source_id,
                    str(uuid.uuid4()),
                )
    finally:
        await tx.rollback()
        await conn.close()
