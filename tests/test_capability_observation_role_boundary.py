"""Focused PostgreSQL check for the capability writer/acceptor role boundary."""
import asyncio
import uuid

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import disposable_cluster
from scripts.migrate import load_migrations, migrate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
WRITER = "business_ai_capability_writer"
ACCEPTOR = "business_ai_capability_acceptor"


@pytest_asyncio.fixture
async def database_url(monkeypatch):
    """Own a fresh cluster; never attach this role-boundary test to a shared DSN."""
    monkeypatch.setenv("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", "1")
    async with disposable_cluster() as (dsn, _name, _owner_token):
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(
                "CREATE ROLE business_ai_app NOLOGIN; "
                "CREATE ROLE business_ai_admin NOLOGIN; "
                "CREATE ROLE business_ai_control_api NOLOGIN; "
                "CREATE ROLE business_ai_capability_writer NOLOGIN; "
                "CREATE ROLE business_ai_capability_acceptor NOLOGIN"
            )
            await migrate(conn, load_migrations())
        finally:
            await conn.close()
        yield dsn


async def test_business_ai_app_cannot_forge_stable_observation(database_url):
    conn = await asyncpg.connect(database_url)
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
            "bag.record_capability_observation(text,uuid,bigint,bigint,text,text,text,text,boolean,"
            "boolean,boolean,boolean,integer,jsonb,jsonb)"
        )
        reserve_signature = "bag.reserve_capability_probe(text,uuid,bigint)"
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
        assert await conn.fetchval(
            "SELECT has_function_privilege($1, $2::regprocedure, 'EXECUTE')", WRITER, reserve_signature
        ) is True
        assert await conn.fetchval(
            "SELECT has_function_privilege($1, $2::regprocedure, 'EXECUTE')", WRITER, acceptor_signature
        ) is False
        assert await conn.fetchval(
            "SELECT has_function_privilege($1, $2::regprocedure, 'EXECUTE')", ACCEPTOR, reserve_signature
        ) is False
        assert await conn.fetchval(
            "SELECT has_function_privilege($1, $2::regprocedure, 'EXECUTE')", ACCEPTOR, acceptor_signature
        ) is True

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
                        $1, $2::uuid, $3::bigint, $4::bigint, $5, $6, 'SUPPORTED', 'ODATA_JSON_V3',
                        true, true, false, false, 1, '{}'::jsonb, '{}'::jsonb
                    )
                    """,
                    source_id,
                    str(uuid.uuid4()),
                    1,
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


async def _source(conn, source_id):
    await conn.execute(
        "INSERT INTO bag.sources(source_id, project, kind, display_name, base_url) "
        "VALUES($1, 'onec', 'onec_auto', 'M2 synthetic source', 'http://fake.invalid/odata')",
        source_id,
    )
    await conn.execute(
        """INSERT INTO bag.source_capabilities(
             source_id, metadata_fingerprint, compatibility_status, adapter_profile,
             metadata_supported, json_supported, atom_supported, entity_set_count,
             evidence_json, register_capabilities_json, drift_status
           ) VALUES($1, $2, 'SUPPORTED', 'ODATA_JSON_V3', true, true, false, 1,
                    '{}'::jsonb, '{}'::jsonb, 'NEEDS_VALIDATION')""",
        source_id,
        "b" * 64,
    )
    return await conn.fetchval("SELECT row_version FROM bag.sources WHERE source_id=$1", source_id)


async def _as_session(conn, identity, sql, *args):
    assert identity in (WRITER, ACCEPTOR)
    await conn.execute(f"SET SESSION AUTHORIZATION {identity}")
    try:
        if sql.lstrip().upper().startswith("SELECT *"):
            return await conn.fetch(sql, *args)
        return await conn.fetchval(sql, *args)
    finally:
        await conn.execute("RESET SESSION AUTHORIZATION")


async def _reserve(conn, source_id, request_id, row_version):
    return await _as_session(
        conn, WRITER,
        "SELECT bag.reserve_capability_probe($1,$2::uuid,$3::bigint)",
        source_id, request_id, row_version,
    )


async def _record(conn, source_id, request_id, reservation_id, row_version):
    return await _as_session(
        conn, WRITER,
        """SELECT bag.record_capability_observation(
             $1,$2::uuid,$3::bigint,$4::bigint,$5,$6,'SUPPORTED','ODATA_JSON_V3',
             true,true,false,false,1,'{}'::jsonb,'{}'::jsonb)""",
        source_id, request_id, reservation_id, row_version, "a" * 64, "8.3.synthetic",
    )


async def _accept(conn, source_id, request_id, observation_id):
    return await _as_session(
        conn, ACCEPTOR,
        "SELECT * FROM bag.accept_capability_observation($1,$2::uuid,$3::bigint)",
        source_id, request_id, observation_id,
    )


async def test_probe_reservations_make_later_accepted_request_authoritative(database_url):
    owner = await asyncpg.connect(database_url)
    writer = await asyncpg.connect(database_url)
    acceptor = await asyncpg.connect(database_url)
    source_id = f"m2-order-{uuid.uuid4()}"
    request_a, request_b = uuid.uuid4(), uuid.uuid4()
    try:
        row_version = await _source(owner, source_id)
        reservation_a = await _reserve(writer, source_id, request_a, row_version)
        reservation_b = await _reserve(writer, source_id, request_b, row_version)
        assert reservation_b > reservation_a

        observation_b = await _record(writer, source_id, request_b, reservation_b, row_version)
        accepted_b = await _accept(acceptor, source_id, request_b, observation_b)
        assert len(accepted_b) == 1

        # An older request that records after the newer acceptance cannot replace it.
        observation_a = await _record(writer, source_id, request_a, reservation_a, row_version)
        assert observation_a is None
        with pytest.raises(asyncpg.PostgresError, match="provenance is missing or stale"):
            await _accept(acceptor, source_id, request_a, observation_a)

        accepted_id = await owner.fetchval(
            "SELECT accepted_observation_id FROM bag.source_capabilities WHERE source_id=$1", source_id
        )
        assert accepted_id == observation_b
        assert await _record(writer, source_id, request_b, reservation_b, row_version) == observation_b
        assert len(await _accept(acceptor, source_id, request_b, observation_b)) == 1
        assert await owner.fetchval(
            "SELECT accepted_observation_id FROM bag.source_capabilities WHERE source_id=$1", source_id
        ) == observation_b
    finally:
        await owner.close()
        await writer.close()
        await acceptor.close()


async def test_reservation_retry_keeps_identity_and_database_timestamp_across_connections(database_url):
    owner = await asyncpg.connect(database_url)
    writer_a = await asyncpg.connect(database_url)
    source_id, request_id = f"m2-retry-{uuid.uuid4()}", uuid.uuid4()
    try:
        row_version = await _source(owner, source_id)
        first_id = await _reserve(writer_a, source_id, request_id, row_version)
        first_at = await owner.fetchval(
            "SELECT reserved_at FROM bag.capability_probe_reservations WHERE reservation_id=$1", first_id
        )
        await writer_a.close()
        writer_b = await asyncpg.connect(database_url)
        try:
            retry_id = await _reserve(writer_b, source_id, request_id, row_version)
        finally:
            await writer_b.close()
        retry_at = await owner.fetchval(
            "SELECT reserved_at FROM bag.capability_probe_reservations WHERE reservation_id=$1", retry_id
        )
        assert retry_id == first_id
        assert retry_at == first_at
    finally:
        if not writer_a.is_closed():
            await writer_a.close()
        await owner.close()


async def test_concurrent_requests_coexist_but_stale_version_and_expired_reservation_fail_closed(database_url):
    owner = await asyncpg.connect(database_url)
    writer_a = await asyncpg.connect(database_url)
    writer_b = await asyncpg.connect(database_url)
    acceptor = await asyncpg.connect(database_url)
    source_id = f"m2-concurrent-{uuid.uuid4()}"
    request_a, request_b = uuid.uuid4(), uuid.uuid4()
    try:
        row_version = await _source(owner, source_id)
        reservation_a = await _reserve(writer_a, source_id, request_a, row_version)
        reservation_b = await _reserve(writer_b, source_id, request_b, row_version)
        observations = await asyncio.gather(
            _record(writer_a, source_id, request_a, reservation_a, row_version),
            _record(writer_b, source_id, request_b, reservation_b, row_version),
        )
        assert observations[0] != observations[1]
        assert await owner.fetchval(
            "SELECT count(*) FROM bag.capability_observations WHERE source_id=$1", source_id
        ) == 2

        stale_request = uuid.uuid4()
        stale_reservation = await _reserve(writer_a, source_id, stale_request, row_version)
        await owner.execute(
            "UPDATE bag.sources SET display_name=display_name || ' version bump' WHERE source_id=$1", source_id
        )
        current_version = await owner.fetchval("SELECT row_version FROM bag.sources WHERE source_id=$1", source_id)
        assert current_version > row_version
        with pytest.raises(asyncpg.PostgresError, match="configuration changed during observation"):
            await _record(writer_a, source_id, stale_request, stale_reservation, row_version)
        with pytest.raises(asyncpg.PostgresError, match="configuration changed before capability probe"):
            await _reserve(writer_a, source_id, uuid.uuid4(), row_version)

        expired_request = uuid.uuid4()
        expired_id = await _reserve(writer_a, source_id, expired_request, current_version)
        await owner.execute(
            "UPDATE bag.capability_probe_reservations "
            "SET reserved_at=clock_timestamp()-interval '6 minutes' WHERE reservation_id=$1", expired_id,
        )
        with pytest.raises(asyncpg.PostgresError, match="reservation is stale"):
            await _record(writer_a, source_id, expired_request, expired_id, current_version)
        renewed_id = await _reserve(writer_a, source_id, expired_request, current_version)
        assert renewed_id != expired_id

        # A process that disappears after reservation has no observation for the acceptor.
        orphan_request = uuid.uuid4()
        await _reserve(writer_a, source_id, orphan_request, current_version)
        with pytest.raises(asyncpg.PostgresError, match="provenance is missing or stale"):
            await _accept(acceptor, source_id, orphan_request, 987654321)

        await owner.execute("UPDATE bag.sources SET enabled=false WHERE source_id=$1", source_id)
        with pytest.raises(asyncpg.PostgresError, match="configuration changed before capability probe"):
            await _reserve(writer_a, source_id, uuid.uuid4(), current_version)
    finally:
        await owner.close()
        await writer_a.close()
        await writer_b.close()
        await acceptor.close()
