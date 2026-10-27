"""S13 acknowledgement SQL contract on an invocation-owned PostgreSQL 16 container only."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _pg_harness import admin_connect, apply_files, disposable_cluster, throwaway_db
from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from test_change_ledger_sql import _setup
from test_s13_current_turn_sql import MIGRATIONS_019_027, _apply_migration
from test_private_writer_barrier_ack import _acknowledgement
from test_s13_barrier_ack_verifier import _PROCESS_ATTESTATION_PREFIX
from erp_mcp_private_writer.barrier_ack_protocol import (
    barrier_acknowledgement_ref,
    barrier_acknowledgement_signed_bytes,
)

pytestmark = pytest.mark.integration


class CandidateDb:
    def __init__(self, conn: asyncpg.Connection, dsn: str, database: str) -> None:
        self.conn = conn
        self.dsn = dsn
        self.database = database

    async def connect(self) -> asyncpg.Connection:
        return await admin_connect(self.dsn, database=self.database)


@pytest_asyncio.fixture
async def candidate_db() -> AsyncIterator[CandidateDb]:
    """Apply candidate schema only in this invocation's unique, owned PostgreSQL 16 cluster."""
    old_opt_in = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    old_image = os.environ.get("ERP_PHASE2_TEST_IMAGE")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    os.environ["ERP_PHASE2_TEST_IMAGE"] = "postgres:16"
    try:
        async with disposable_cluster() as (dsn, _name, _token):
            async with throwaway_db(dsn, seed=False) as db:
                try:
                    await apply_files(db.conn)
                    for migration in MIGRATIONS_019_027:
                        await _apply_migration(db.conn, migration)
                    await _setup(db.conn)
                except asyncpg.PostgresError as error:
                    pytest.fail(
                        "candidate migration/setup failed on owned PostgreSQL 16: "
                        f"{error.sqlstate} {str(error).splitlines()[0]}", pytrace=False,
                    )
                yield CandidateDb(db.conn, dsn, db.name)
    finally:
        if old_opt_in is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old_opt_in
        if old_image is None:
            os.environ.pop("ERP_PHASE2_TEST_IMAGE", None)
        else:
            os.environ["ERP_PHASE2_TEST_IMAGE"] = old_image


async def test_registration_locks_trust_revision_before_other_locks_and_checks_exact_replay_first(
        candidate_db: CandidateDb,
) -> None:
    conn = candidate_db.conn
    register = "change_ledger.private_writer_register_barrier_ack_v1(" \
        "change_ledger.private_writer_barrier_ack_v1,text,bytea,bigint)"
    exists = await conn.fetchval("SELECT to_regprocedure($1) IS NOT NULL", register)
    assert exists, "migration did not create the versioned acknowledgement registration routine"
    definition = (await conn.fetchval(
        "SELECT pg_get_functiondef($1::regprocedure)", register,
    )).lower()
    compact = re.sub(r"\s+", " ", definition)

    binding_lock = compact.index(
        "from change_ledger.private_writer_service_bindings x where "
        "x.base_fingerprint=p_ack.base_fingerprint",
    )
    binding_for_share = compact.index("for share", binding_lock)
    revision_lock = compact.index("from change_ledger.private_writer_trust_registry_revision")
    revision_for_share = compact.index("for share", revision_lock)
    first_advisory_lock = compact.index("pg_advisory_xact_lock")
    base_fence = compact.index("private_writer_take_base_fence_v1")
    key_lookup = compact.index(
        "select * into k from change_ledger.private_writer_signer_key_versions x "
        "where x.key_id=p_ack.key_id and x.key_version=p_ack.key_version for share",
    )
    exact_lookup = compact.index(
        "from change_ledger.writer_barrier_acknowledgements x where x.barrier_id",
    )
    exact_return = compact.index("if exact_tuple then return prior.acknowledgement_ref")
    stale_refusal = compact.index("current_trust_revision is distinct from p_trust_revision")

    assert (binding_lock < binding_for_share < revision_lock < revision_for_share
            < first_advisory_lock < base_fence < key_lookup), (
        "active writer binding must be held before trust-revision and advisory/fence locks",
    )
    assert exact_lookup < exact_return < stale_refusal, (
        "an exact durable tuple must remain replayable before stale snapshot refusal",
    )


_REGISTER_NAME = "change_ledger.private_writer_register_barrier_ack_v1"
_REGISTER = _REGISTER_NAME + "(change_ledger.private_writer_barrier_ack_v1,text,bytea,bigint)"
_REGISTER_CALL = "SELECT " + _REGISTER_NAME + "(ROW($1::text,"
_REGISTER_CALL += "ROW($2::text,$3::text)::change_ledger.private_writer_scope_v1,"
_REGISTER_CALL += "$4::bigint,$5::uuid,$6::text,$7::bigint,$8::uuid[],$9::text,$10::text,"
_REGISTER_CALL += "$11::text,$12::text,$13::text,$14::text,$15::text,$16::bigint,$17::boolean,"
_REGISTER_CALL += "$18::text,$19::bytea)::change_ledger.private_writer_barrier_ack_v1,"
_REGISTER_CALL += "$20::text,$21::bytea,$22::bigint)"


def _raw_public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )


async def _valid_ack_fixture(conn: asyncpg.Connection):
    """Seed only the rows that the real registration routine and its table guard consume."""
    unsigned = _acknowledgement()
    writer_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    supervisor_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    ack = replace(unsigned, signature=writer_key.sign(unsigned.signature_preimage()))
    signed_at = datetime.strptime(ack.signed_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    process_created = signed_at - timedelta(minutes=1)
    process_doc = {
        "attestation_version": "1",
        "process_instance_id": ack.writer_process_instance_id,
        "host_boot_id": ack.host_boot_id,
        "service_id": ack.writer_service_id,
        "host_id": ack.writer_host_id,
        "os_pid": 321,
        "process_created_at": process_created.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "supervisor_key_id": "supervisor-key",
        "supervisor_key_version": "1",
    }
    process_signature = supervisor_key.sign(
        _PROCESS_ATTESTATION_PREFIX + canonical_json_bytes(process_doc),
    )
    valid_from = datetime(2026, 10, 1, tzinfo=UTC)
    valid_until = datetime(2026, 11, 1, tzinfo=UTC)
    await conn.execute("""
        INSERT INTO change_ledger.private_writer_service_bindings
            ("session_user",base_fingerprint,writer_service_id,writer_host_id)
        VALUES ('private_writer_evidence_ingest',$1,$2,$3)
    """, ack.base_fingerprint, ack.writer_service_id, ack.writer_host_id)
    await conn.execute("""
        INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason)
        VALUES($1,$2,'RECOVERING',$3,'S13_ACK_FIXTURE')
        ON CONFLICT(tenant_id,company_id) DO UPDATE
        SET state='RECOVERING',epoch=excluded.epoch,reason=excluded.reason
    """, ack.tenant_id, ack.company_id, ack.lifecycle_epoch)
    await conn.execute("""
        INSERT INTO change_ledger.writer_barriers(
            barrier_id,base_fingerprint,tenant_id,company_id,expected_current_epoch,epoch,
            barrier_origin_instance_id,barrier_origin_service_epoch,progress
        ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'CLOSED_WITH_HOLD')
    """, ack.barrier_id, ack.base_fingerprint, ack.tenant_id, ack.company_id,
        ack.lifecycle_epoch - 1, ack.lifecycle_epoch, ack.barrier_origin_instance_id,
        ack.barrier_origin_service_epoch)
    for key_id, service, role, key in (
        (ack.key_id, ack.writer_service_id, "writer_receipt", writer_key),
        ("supervisor-key", "supervisor-test", "completion_supervisor", supervisor_key),
    ):
        await conn.execute("""
            INSERT INTO change_ledger.private_writer_signer_key_versions(
                key_id,key_version,public_key,signer_role,service_id,host_id,valid_from,valid_until
            ) VALUES($1,'1',$2,$3,$4,$5,$6,$7)
        """, key_id, _raw_public_key(key), role, service, ack.writer_host_id,
            valid_from, valid_until)
        await conn.execute("""
            INSERT INTO change_ledger.private_writer_signer_key_scopes(
                key_id,key_version,tenant_id,company_id,organization_ref,base_fingerprint
            ) VALUES($1,'1',$2,$3,'org-1',$4)
        """, key_id, ack.tenant_id, ack.company_id, ack.base_fingerprint)
    await conn.execute("""
        INSERT INTO change_ledger.private_writer_process_attestations(
            process_instance_id,host_boot_id,service_id,host_id,os_pid,process_created_at,
            supervisor_key_id,supervisor_key_version,signature
        ) VALUES($1,$2,$3,$4,321,$5,'supervisor-key','1',$6)
    """, UUID(str(ack.writer_process_instance_id)), UUID(str(ack.host_boot_id)), ack.writer_service_id,
        ack.writer_host_id, process_created, process_signature)
    revision = await conn.fetchval(
        "SELECT revision FROM change_ledger.private_writer_trust_registry_revision WHERE revision_id=1",
    )
    await conn.execute(f"GRANT EXECUTE ON FUNCTION {_REGISTER} TO private_writer_evidence_ingest")
    return ack, revision


async def _enter_evidence_ingest(conn: asyncpg.Connection, application_name: str) -> None:
    await conn.execute("SET SESSION AUTHORIZATION private_writer_evidence_ingest")
    await conn.execute("SELECT set_config('application_name',$1,false)", application_name)


async def _wait_for_backend_event(
        observer: asyncpg.Connection, application_name: str, *, wait_event_type: str,
        wait_event: str | None = None, monitor: asyncio.Task | None = None,
) -> None:
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        if monitor is not None and monitor.done():
            result, error = monitor.result()
            assert error is None, f"backend failed before expected lock window: {error}"
            raise AssertionError("backend completed before entering the expected lock window")
        row = await observer.fetchrow("""
            SELECT state,wait_event_type,wait_event FROM pg_catalog.pg_stat_activity
            WHERE datname=current_database() AND application_name=$1
        """, application_name)
        if (row is not None and row["wait_event_type"] == wait_event_type
                and (wait_event is None or row["wait_event"] == wait_event)):
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"backend {application_name!r} did not reach {wait_event_type}/{wait_event}")


async def _register_as_evidence_ingest(conn: asyncpg.Connection, ack, revision: int):
    await _enter_evidence_ingest(conn, "s13-ack-registration")
    async with conn.transaction():
        return await _register_call(conn, ack, revision)


async def _register_call_in_transaction(conn: asyncpg.Connection, ack, revision: int):
    async with conn.transaction():
        return await _register_call(conn, ack, revision)


async def _start_revocation(conn: asyncpg.Connection) -> None:
    await conn.execute("SELECT set_config('application_name','s13-ack-revocation',false)")
    async with conn.transaction():
        await conn.execute("""
            UPDATE change_ledger.private_writer_service_bindings
            SET revoked_at=clock_timestamp()
            WHERE "session_user"='private_writer_evidence_ingest'
        """)


async def _register_call(conn: asyncpg.Connection, ack, trust_revision: int = 1) -> tuple[str | None, str | None]:
    signed_bytes = barrier_acknowledgement_signed_bytes(ack)
    acknowledgement_ref = barrier_acknowledgement_ref(ack)
    try:
        result = await conn.fetchval(
            _REGISTER_CALL,
            ack.base_fingerprint, ack.tenant_id, ack.company_id, ack.lifecycle_epoch,
            ack.barrier_id, ack.barrier_origin_instance_id,
            ack.barrier_origin_service_epoch, list(ack.call_ids), ack.key_id, ack.key_version,
            ack.writer_service_id, ack.writer_host_id, ack.host_boot_id,
            ack.writer_process_instance_id, ack.process_attestation_ref,
            ack.writer_queue_epoch, ack.local_queue_closed, ack.signed_at, ack.signature,
            acknowledgement_ref, signed_bytes, trust_revision,
        )
        return result, None
    except asyncpg.PostgresError as error:
        return None, str(error)


async def test_registration_requires_an_exact_active_base_service_host_binding(
        candidate_db: CandidateDb,
) -> None:
    """Exercise the SQL boundary; no mocked query or configured lane is involved."""
    conn = candidate_db.conn
    await conn.execute(f"GRANT EXECUTE ON FUNCTION {_REGISTER} TO private_writer_evidence_ingest")
    await conn.execute("""
        INSERT INTO change_ledger.private_writer_service_bindings
            ("session_user",base_fingerprint,writer_service_id,writer_host_id)
        VALUES
            ('fixture_base_only',$1,$2,$3),
            ('fixture_service_only',$4,$5,$6),
            ('fixture_host_only',$7,$8,$9),
            ('fixture_revoked',$10,$11,$12),
            ('fixture_exact',$13,$14,$15)
    """, "b" * 64, "writer-base", "host-base",
        "d" * 64, "writer-existing", "host-service",
        "f" * 64, "writer-host", "host-existing",
        "c" * 64, "writer-revoked", "host-revoked",
        "a" * 64, "writer-test", "host-test")
    await conn.execute("""
        UPDATE change_ledger.private_writer_service_bindings
        SET revoked_at=pg_catalog.clock_timestamp()
        WHERE "session_user"='fixture_revoked'
    """)
    await conn.execute("SET SESSION AUTHORIZATION private_writer_evidence_ingest")
    try:
        base_ack = _acknowledgement()
        mismatch_cases = (
            (replace(base_ack, base_fingerprint="e" * 64,
                     writer_service_id="writer-missing", writer_host_id="host-missing"),
             "no binding exists"),
            (replace(base_ack, base_fingerprint="a" * 64, writer_service_id="writer-base",
                     writer_host_id="host-base"), "the existing binding has a different base"),
            (replace(base_ack, base_fingerprint="d" * 64, writer_service_id="writer-requested",
                     writer_host_id="host-service"), "the existing binding has a different service"),
            (replace(base_ack, base_fingerprint="f" * 64, writer_service_id="writer-host",
                     writer_host_id="host-requested"), "the existing binding has a different host"),
            (replace(base_ack, base_fingerprint="c" * 64, writer_service_id="writer-revoked",
                     writer_host_id="host-revoked"), "the exact binding is revoked"),
        )
        for ack, reason in mismatch_cases:
            _result, error = await _register_call(conn, ack)
            assert "NOT_ENTITLED" in error, reason

        # The exact live binding passes the new guard and reaches the later barrier lookup.
        # A missing barrier is the next independent refusal and must not write an ACK row.
        _result, later_error = await _register_call(conn, base_ack)
        assert "BARRIER_CONFLICT" in later_error
    finally:
        await conn.execute("RESET SESSION AUTHORIZATION")

    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.writer_barrier_acknowledgements",
    ) == 0


async def test_acknowledgement_verification_and_registration_routines_are_revoked_by_default(
        candidate_db: CandidateDb,
) -> None:
    conn = candidate_db.conn
    signatures = (
        "change_ledger.private_writer_register_barrier_ack_v1(change_ledger.private_writer_barrier_ack_v1,text,bytea,bigint)",
        "change_ledger.private_writer_lookup_barrier_ack_v1(uuid)",
        "change_ledger.private_writer_load_barrier_ack_trust_v1(change_ledger.private_writer_barrier_ack_v1)",
    )
    for signature in signatures:
        oid = await conn.fetchval("SELECT to_regprocedure($1)", signature)
        assert oid is not None, f"candidate function missing: {signature}"
        for role in ("private_writer_evidence_ingest", "business_ai_private_writer"):
            allowed = await conn.fetchval(
                "SELECT has_function_privilege($1,$2,'EXECUTE')", role, signature,
            )
            assert not allowed, f"{role} unexpectedly has EXECUTE for {signature}"
        public_execute = await conn.fetchval(
            """SELECT EXISTS(
                 SELECT 1 FROM pg_catalog.pg_proc p
                 CROSS JOIN LATERAL pg_catalog.aclexplode(
                   coalesce(p.proacl, pg_catalog.acldefault('f',p.proowner))
                 ) acl
                 WHERE p.oid=$1::regprocedure AND acl.grantee=0
                   AND acl.privilege_type='EXECUTE'
               )""",
            signature,
        )
        assert not public_execute, f"PUBLIC has EXECUTE for {signature}"


async def test_registration_inserts_ack_with_exact_active_binding(candidate_db: CandidateDb) -> None:
    admin = candidate_db.conn
    ack, revision = await _valid_ack_fixture(admin)
    expected_ref = barrier_acknowledgement_ref(ack)
    conn = await candidate_db.connect()
    try:
        await _enter_evidence_ingest(conn, "s13-ack-success")
        result, error = await _register_call(conn, ack, revision)
    finally:
        await conn.close()
    assert error is None, f"valid acknowledgement was refused: {error}"
    assert result == expected_ref
    stored = await admin.fetchrow("""
        SELECT acknowledgement_ref,barrier_id,base_fingerprint,writer_service_id,writer_host_id,
               signed_bytes_sha256
        FROM change_ledger.writer_barrier_acknowledgements
    """)
    assert stored is not None
    assert stored["acknowledgement_ref"] == expected_ref
    assert stored["barrier_id"] == ack.barrier_id
    assert stored["base_fingerprint"] == ack.base_fingerprint
    assert stored["writer_service_id"] == ack.writer_service_id
    assert stored["writer_host_id"] == ack.writer_host_id
    assert bytes(stored["signed_bytes_sha256"]) == hashlib.sha256(
        barrier_acknowledgement_signed_bytes(ack),
    ).digest()


async def test_registration_binding_share_lock_serializes_concurrent_revocation(
        candidate_db: CandidateDb,
) -> None:
    admin = candidate_db.conn
    ack, revision = await _valid_ack_fixture(admin)
    await admin.execute("CREATE SCHEMA test_s13_ack")
    await admin.execute("""
        CREATE FUNCTION test_s13_ack.pause_ack_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.8); RETURN NEW; END $$
    """)
    await admin.execute("""
        CREATE TRIGGER test_s13_ack_pause BEFORE INSERT
        ON change_ledger.writer_barrier_acknowledgements
        FOR EACH ROW EXECUTE FUNCTION test_s13_ack.pause_ack_insert()
    """)
    registration = await candidate_db.connect()
    revocation = await candidate_db.connect()
    observer = await candidate_db.connect()
    register_task = revoke_task = None
    try:
        register_task = asyncio.create_task(_register_as_evidence_ingest(registration, ack, revision))
        await _wait_for_backend_event(
            observer, "s13-ack-registration", wait_event_type="Timeout", wait_event="PgSleep",
            monitor=register_task,
        )
        revoke_task = asyncio.create_task(_start_revocation(revocation))
        await _wait_for_backend_event(observer, "s13-ack-revocation", wait_event_type="Lock")
        result, error = await asyncio.wait_for(register_task, timeout=5)
        await asyncio.wait_for(revoke_task, timeout=5)
    finally:
        for task in (register_task, revoke_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await registration.close()
        await revocation.close()
        await observer.close()
    assert error is None, f"registration-first order was refused: {error}"
    assert result == barrier_acknowledgement_ref(ack)
    assert await admin.fetchval(
        "SELECT count(*) FROM change_ledger.writer_barrier_acknowledgements",
    ) == 1
    assert await admin.fetchval("""
        SELECT revoked_at IS NOT NULL FROM change_ledger.private_writer_service_bindings
        WHERE "session_user"='private_writer_evidence_ingest'
    """)


async def test_revocation_first_order_blocks_registration_and_writes_no_ack(
        candidate_db: CandidateDb,
) -> None:
    admin = candidate_db.conn
    ack, revision = await _valid_ack_fixture(admin)
    registration = await candidate_db.connect()
    revocation = await candidate_db.connect()
    observer = await candidate_db.connect()
    register_task = None
    try:
        await revocation.execute("SELECT set_config('application_name','s13-ack-revocation-first',false)")
        async with revocation.transaction():
            await revocation.execute("""
                UPDATE change_ledger.private_writer_service_bindings
                SET revoked_at=clock_timestamp()
                WHERE "session_user"='private_writer_evidence_ingest'
            """)
            await _enter_evidence_ingest(registration, "s13-ack-registration")
            register_task = asyncio.create_task(
                _register_call_in_transaction(registration, ack, revision),
            )
            await _wait_for_backend_event(
                observer, "s13-ack-registration", wait_event_type="Lock", monitor=register_task,
            )
        result, error = await asyncio.wait_for(register_task, timeout=5)
    finally:
        if register_task is not None and not register_task.done():
            register_task.cancel()
            try:
                await register_task
            except asyncio.CancelledError:
                pass
        await registration.close()
        await revocation.close()
        await observer.close()
    assert result is None
    assert error is not None and "NOT_ENTITLED" in error
    assert await admin.fetchval(
        "SELECT count(*) FROM change_ledger.writer_barrier_acknowledgements",
    ) == 0
