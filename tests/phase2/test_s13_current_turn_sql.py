"""Focused SQL acceptance for current-turn S13 refusal/no-op and ACL contracts.

The suite provisions only an invocation-owned loopback PostgreSQL cluster and a throwaway
database inside it. It never connects to the lane database or writes business data.
Run with: uv run pytest -q tests/phase2/test_s13_current_turn_sql.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import MIGRATIONS, apply_files, disposable_cluster, throwaway_db
from test_change_ledger_sql import C, L, T, _setup

pytestmark = pytest.mark.integration
_S13_EVIDENCE_ORG = "org-s13-functional-test"

MIGRATIONS_019_027 = (
    "019_ed25519_action_only.sql",
    "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql",
    "022_lifecycle_epoch_fence.sql",
    "023_lifecycle_activation_cap.sql",
    "024_restore_caller_lock_timeout.sql",
    "025_lifecycle_checkpoint_suffix.sql",
    "026_lifecycle_checkpoint_payload_minimization.sql",
    "027_private_writer_admission_schema.sql",
)
MIGRATIONS_019_026 = MIGRATIONS_019_027[:-1]


@dataclass(frozen=True, slots=True, repr=False)
class _OwnedClusterDsn:
    value: str

    def __repr__(self) -> str:
        return "<invocation-owned disposable PostgreSQL DSN>"

_DIAGNOSTIC_DSN = re.compile(r"(?i)\bpostgres(?:ql)?://[^\s'\"<>]+")
_DIAGNOSTIC_DSN_FIELD = re.compile(
    r"(?i)\b(dsn|connection[_ -]?string)(\s*[=:]\s*)('[^']*'|\"[^\"]*\"|[^\s,;]+)"
)
_DIAGNOSTIC_PASSWORD = re.compile(
    r"(?i)\b(password|passwd|pwd)(\s*[=:]\s*|\s+)('[^']*'|\"[^\"]*\"|[^\s,;]+)"
)


def _redact_diagnostic_text(value: str) -> str:
    safe = _DIAGNOSTIC_DSN.sub("<REDACTED_DSN>", value)
    safe = _DIAGNOSTIC_DSN_FIELD.sub(r"\1\2<REDACTED>", safe)
    return _DIAGNOSTIC_PASSWORD.sub(r"\1\2<REDACTED>", safe)


def _safe_postgres_diagnostics(error: asyncpg.PostgresError) -> str:
    # asyncpg's context can embed the entire migration as `SQL statement "..."`; emitting it
    # made a setup failure print the full candidate source. Keep structured, bounded diagnostics
    # and rely on the separately hashed/trimmed internal_query excerpt below.
    fields = ("sqlstate", "severity", "message_primary", "position", "internal_position")
    diagnostics: dict[str, str | int] = {}
    for field in fields:
        value = getattr(error, field, None)
        if field == "message_primary" and value is None:
            value = str(error)
        if value is not None:
            diagnostics[field] = _redact_diagnostic_text(str(value))

    internal_query = getattr(error, "internal_query", None)
    if internal_query is not None:
        query = str(internal_query)
        diagnostics["internal_query_length"] = len(query)
        diagnostics["internal_query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
        position = getattr(error, "internal_position", None)
        try:
            center = int(position) - 1
        except (TypeError, ValueError):
            center = 0
        start = max(0, center - 180)
        stop = min(len(query), center + 180)
        diagnostics["internal_query_snippet"] = _redact_diagnostic_text(query[start:stop])
    return json.dumps(diagnostics, sort_keys=True)


async def _apply_migration(conn: asyncpg.Connection, name: str) -> None:
    raw = (MIGRATIONS / name).read_bytes()
    await conn.execute(
        "SELECT set_config('living.migration_checksum',$1,false)",
        hashlib.sha256(raw).hexdigest(),
    )
    await conn.execute(raw.decode("utf-8"))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def owned_cluster_dsn() -> AsyncIterator[_OwnedClusterDsn]:
    """Create an invocation-owned Docker cluster; restore the opt-in environment afterwards."""
    old_opt_in = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, _name, _token):
            yield _OwnedClusterDsn(dsn)
    finally:
        if old_opt_in is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old_opt_in


@pytest_asyncio.fixture
async def isolated_acl_cluster_dsn() -> AsyncIterator[_OwnedClusterDsn]:
    """Give cluster-global candidate roles an independently owned fixture lifecycle."""
    old_opt_in = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, _name, _token):
            yield _OwnedClusterDsn(dsn)
    finally:
        if old_opt_in is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old_opt_in


@pytest_asyncio.fixture
async def ledger(owned_cluster_dsn: _OwnedClusterDsn) -> AsyncIterator[L]:
    """Build a per-test disposable database from migrations 001–027 and synthetic actors."""
    # The harness only creates db.conn when migrate=True. It applies 001–018 here, without
    # business seed rows; the candidate chain and S13 actors are added below.
    async with throwaway_db(owned_cluster_dsn.value, seed=False) as db:
        step = "base migrations 001–018"
        try:
            await apply_files(db.conn)
            for migration in MIGRATIONS_019_027:
                step = migration
                await _apply_migration(db.conn, migration)
            step = "synthetic S13 fixture setup"
            await _setup(db.conn)
            # _setup adds the synthetic scope after migration 022 has run, so seed its legacy
            # lifecycle fence explicitly, as the source accepts legacy scopes for these gates.
            await db.conn.execute(
                "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
                "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE') ON CONFLICT(tenant_id,company_id) DO NOTHING",
                T,
                C,
            )
        except asyncpg.PostgresError as error:
            pytest.fail(
                f"PostgreSQL setup error in {step}: {_safe_postgres_diagnostics(error)}",
                pytrace=False,
            )
        yield L(db)


async def _ledger_snapshot(conn: asyncpg.Connection) -> tuple:
    """Stable contents of every change-ledger table, including the append-only event rows."""
    names = await conn.fetch(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='change_ledger' ORDER BY tablename"
    )
    snapshot = []
    for item in names:
        table = item["tablename"].replace('"', '""')
        rows = await conn.fetch(f'SELECT to_jsonb(row_data) FROM change_ledger."{table}" AS row_data')
        encoded = []
        for row in rows:
            value = row[0]
            if isinstance(value, str):
                value = json.loads(value)
            encoded.append(json.dumps(value, sort_keys=True, separators=(",", ":")))
        snapshot.append((item["tablename"], tuple(sorted(encoded))))
    return tuple(snapshot)


async def _expect_code(code: str, awaitable) -> asyncpg.PostgresError:
    try:
        await awaitable
    except asyncpg.PostgresError as error:
        assert error.sqlstate == "P0001", (error.sqlstate, str(error))
        assert str(error).splitlines()[0] == code, str(error)
        return error
    raise AssertionError(f"expected SQL refusal {code}; call succeeded")


async def test_s13_kill_switch_legacy_off_is_no_write_and_no_event(ledger: L) -> None:
    """S13-KILL-SWITCH-LEGACY-BRIDGE-01: the granted legacy OFF call is a true no-op."""
    conn = ledger.conn
    legacy_signature = "change_ledger.kill_switch(text,text,text)"
    versioned_signature = "change_ledger.kill_switch_v1(text,text,text)"
    assert await conn.fetchval(
        "SELECT pg_get_userbyid(p.proowner) FROM pg_catalog.pg_proc p "
        "WHERE p.oid=$1::regprocedure",
        legacy_signature,
    ) == "ledger_owner"
    assert await conn.fetchval(
        "SELECT has_function_privilege('clt_dave',$1,'EXECUTE')", legacy_signature
    )
    assert not await conn.fetchval(
        "SELECT has_function_privilege('clt_dave',$1,'EXECUTE')", versioned_signature
    )

    await conn.execute(
        "INSERT INTO change_ledger.kill_switch_state(tenant_id,company_id,mode,updated_at,updated_by) "
        "VALUES($1,$2,'OFF','2026-01-01T00:00:00Z','test-already-off') "
        "ON CONFLICT(tenant_id,company_id) DO UPDATE SET mode='OFF', "
        "updated_at=EXCLUDED.updated_at,updated_by=EXCLUDED.updated_by",
        T,
        C,
    )
    before = await _ledger_snapshot(conn)

    assert await ledger.call("clt_dave", "kill_switch", "OFF") == "OFF"

    after = await _ledger_snapshot(conn)
    assert after == before, "already-OFF legacy bridge changed state, sweep rows, or events"


async def test_s13_renew_null_generation_precedes_later_refusals_without_delta(ledger: L) -> None:
    """S13-LEASE-RENEW-RANK-01: NULL generation wins over execution/permit/lease refusals."""
    change_id = await ledger.approved(request_id="s13-null-generation", base="base-1")
    base_fingerprint = await ledger.conn.fetchval(
        "SELECT base_fingerprint FROM change_ledger.records WHERE change_id=$1", change_id
    )
    record = await ledger.conn.fetchrow(
        "SELECT claim_generation,execution_state FROM change_ledger.records WHERE change_id=$1",
        change_id,
    )
    assert record["claim_generation"] == 0
    assert record["execution_state"] == "NOT_STARTED"
    assert not await ledger.conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM change_ledger.dispatch_permits WHERE change_id=$1)", change_id
    )
    assert not await ledger.conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM change_ledger.writer_leases WHERE tenant_id=$1 "
        "AND company_id=$2 AND base_fingerprint=$3)",
        T,
        C,
        base_fingerprint,
    )
    before = await _ledger_snapshot(ledger.conn)

    await _expect_code(
        "TICKET_SUPERSEDED",
        ledger.call("clt_wri", "renew_writer_lease", change_id, None),
    )

    after = await _ledger_snapshot(ledger.conn)
    assert after == before, "NULL-generation refusal changed records, permits, leases, tokens, or events"


async def test_s13_renew_mismatched_generation_precedes_locked_existing_permit(ledger: L) -> None:
    """S13-LEASE-RENEW-RANK-01: stale generation refuses before a locked permit child."""
    change_id = await ledger.approved(request_id="s13-existing-stale-permit", base="base-1")
    record_generation = await ledger.conn.fetchval(
        "SELECT claim_generation FROM change_ledger.records WHERE change_id=$1", change_id
    )
    mismatched_generation = record_generation + 1
    # Arrange a stale child row for the requested generation. Holding it FOR UPDATE makes the
    # old lock order observably fail with lock_timeout; the accepted order refuses at the locked
    # parent generation check without waiting for this child row.
    await ledger.conn.execute(
        "INSERT INTO change_ledger.dispatch_permits(change_id,generation,state) "
        "VALUES($1,$2,'NOT_PERMITTED')",
        change_id,
        mismatched_generation,
    )
    before = await _ledger_snapshot(ledger.conn)

    blocker = await ledger.db.connect()
    lock_tx = blocker.transaction()
    await lock_tx.start()
    try:
        await blocker.fetchrow(
            "SELECT 1 FROM change_ledger.dispatch_permits WHERE change_id=$1 AND generation=$2 FOR UPDATE",
            change_id,
            mismatched_generation,
        )

        async def renew_with_short_child_lock_timeout() -> None:
            async with ledger.conn.transaction():
                await ledger.conn.execute('SET LOCAL ROLE "clt_wri"')
                await ledger.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
                await ledger.conn.fetchval("SELECT set_config('lock_timeout','250ms',true)")
                await ledger.conn.fetchval(
                    "SELECT change_ledger.renew_writer_lease($1,$2,$3,$4)",
                    T,
                    C,
                    change_id,
                    mismatched_generation,
                )

        await _expect_code("TICKET_SUPERSEDED", renew_with_short_child_lock_timeout())
    finally:
        await lock_tx.rollback()
        await blocker.close()

    after = await _ledger_snapshot(ledger.conn)
    assert after == before, "stale-generation refusal changed ledger rows or events"


async def test_s13_acl_normalizes_element_types_without_array_acl_mutation(
        isolated_acl_cluster_dsn: _OwnedClusterDsn) -> None:
    """S13-ACL-GENERATED-ARRAY-TYPES-01: normalize elements, never generated arrays."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)

        # These valid, unprivileged logins predate candidate migration 027. Direct USAGE on
        # their element types is a stale grant that the migration must remove.
        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute("CREATE TYPE living.s13_acl_array_probe AS (value text)")
        await conn.execute("CREATE TYPE change_ledger.s13_acl_array_probe AS (value text)")
        await conn.execute(
            "REVOKE USAGE ON TYPE living.s13_acl_array_probe FROM PUBLIC"
        )
        await conn.execute(
            "REVOKE USAGE ON TYPE change_ledger.s13_acl_array_probe FROM PUBLIC"
        )
        await conn.execute(
            "GRANT USAGE ON TYPE living.s13_acl_array_probe TO "
            "business_ai_private_writer,private_writer_evidence_ingest"
        )
        await conn.execute(
            "GRANT USAGE ON TYPE change_ledger.s13_acl_array_probe TO "
            "business_ai_private_writer,private_writer_evidence_ingest"
        )

        for schema in ("living", "change_ledger"):
            assert await conn.fetchval(
                "SELECT has_type_privilege('business_ai_private_writer', $1, 'USAGE')",
                f"{schema}.s13_acl_array_probe",
            )
            assert await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_type t "
                "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
                "WHERE n.nspname=$1 AND t.typname='_s13_acl_array_probe' "
                "AND t.typelem<>0 AND t.typacl IS NULL)",
                schema,
            )

        await _apply_migration(conn, "027_private_writer_admission_schema.sql")

        for schema in ("living", "change_ledger"):
            for role in ("business_ai_private_writer", "private_writer_evidence_ingest"):
                assert not await conn.fetchval(
                    "SELECT has_type_privilege($1, $2, 'USAGE')", role,
                    f"{schema}.s13_acl_array_probe",
                ), (
                    "direct element-type USAGE remained after ACL normalization",
                    schema,
                    role,
                    await conn.fetchval(
                        "SELECT t.typacl::text FROM pg_catalog.pg_type t "
                        "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
                        "WHERE n.nspname=$1 AND t.typname='s13_acl_array_probe'",
                        schema,
                    ),
                )
                assert not await conn.fetchval(
                    "SELECT has_type_privilege($1, $2, 'USAGE')", role,
                    f"{schema}.s13_acl_array_probe[]",
                )
            assert await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_type t "
                "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
                "WHERE n.nspname=$1 AND t.typname='_s13_acl_array_probe' "
                "AND t.typelem<>0 AND t.typacl IS NULL)",
                schema,
            ), "generated array type ACL must remain untouched"


async def test_s13_acl_rejects_reachable_public_type_usage_transactionally(
        isolated_acl_cluster_dsn: _OwnedClusterDsn) -> None:
    """S13-ACL-SOURCE-ROLE-MAP-01: PUBLIC type access reachable through an app schema fails closed."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)

        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute("CREATE TYPE living.s13_acl_public_probe AS (value text)")
        await conn.execute("GRANT USAGE ON SCHEMA living TO business_ai_private_writer")
        assert await conn.fetchval(
            "SELECT has_schema_privilege('business_ai_private_writer','living','USAGE')"
        )
        assert await conn.fetchval(
            "SELECT has_type_privilege('business_ai_private_writer', "
            "'living.s13_acl_public_probe','USAGE')"
        )
        before_acl = await conn.fetchval(
            "SELECT t.typacl::text FROM pg_catalog.pg_type t "
            "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
            "WHERE n.nspname='living' AND t.typname='s13_acl_public_probe'"
        )

        try:
            await _apply_migration(conn, "027_private_writer_admission_schema.sql")
        except asyncpg.PostgresError as error:
            assert error.sqlstate == "P0001"
            assert str(error).splitlines()[0] == "PRIVATE_WRITER_OUT_OF_SCOPE_PRIVILEGE"
            # Candidate 027 owns its explicit BEGIN/COMMIT, so the failed cutover leaves this
            # asyncpg session in an aborted transaction until the fixture rolls it back.
            await conn.execute("ROLLBACK")
        else:
            raise AssertionError("reachable PUBLIC type USAGE must refuse candidate cutover")

        # The single multi-statement candidate application must roll back all of its cutover
        # objects and ACL changes when the fail-closed reachability assertion rejects the seed.
        assert await conn.fetchval(
            "SELECT t.typacl::text FROM pg_catalog.pg_type t "
            "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
            "WHERE n.nspname='living' AND t.typname='s13_acl_public_probe'"
        ) == before_acl
        assert await conn.fetchval(
            "SELECT has_type_privilege('business_ai_private_writer', "
            "'living.s13_acl_public_probe','USAGE')"
        )
        assert await conn.fetchval(
            "SELECT to_regclass('change_ledger.private_writer_service_bindings') IS NULL"
        )


async def test_s13_acl_normalizes_preexisting_role_grants_and_owner_defaults(
        isolated_acl_cluster_dsn: _OwnedClusterDsn) -> None:
    """S13-ACL-SOURCE-ROLE-MAP-01: normalize legacy direct grants and future owner defaults."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)

        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        database_name = await conn.fetchval("SELECT current_database()")
        await conn.execute(
            f'GRANT CREATE ON DATABASE "{database_name}" '
            "TO business_ai_private_writer,private_writer_evidence_ingest"
        )
        await conn.execute("CREATE SCHEMA s13_acl_app")
        await conn.execute(
            "GRANT USAGE,CREATE ON SCHEMA s13_acl_app "
            "TO business_ai_private_writer,private_writer_evidence_ingest"
        )
        await conn.execute("CREATE TABLE s13_acl_app.probe (id integer, secret text)")
        await conn.execute("CREATE SEQUENCE s13_acl_app.probe_seq")
        await conn.execute(
            "CREATE FUNCTION s13_acl_app.probe_fn() RETURNS integer "
            "LANGUAGE SQL IMMUTABLE AS 'SELECT 1'"
        )
        await conn.execute("CREATE DOMAIN s13_acl_app.probe_type AS text")
        await conn.execute("REVOKE EXECUTE ON FUNCTION s13_acl_app.probe_fn() FROM PUBLIC")
        await conn.execute("REVOKE USAGE ON TYPE s13_acl_app.probe_type FROM PUBLIC")
        # Table creation also creates a composite row type with default PUBLIC USAGE. This
        # positive normalization case must not accidentally seed the separate fail-closed
        # reachable-PUBLIC criterion through that implicit type.
        await conn.execute("REVOKE USAGE ON TYPE s13_acl_app.probe FROM PUBLIC")
        await conn.execute("GRANT SELECT ON TABLE s13_acl_app.probe TO business_ai_private_writer")
        await conn.execute(
            "GRANT UPDATE(secret) ON TABLE s13_acl_app.probe TO private_writer_evidence_ingest"
        )
        await conn.execute(
            "GRANT USAGE,SELECT,UPDATE ON SEQUENCE s13_acl_app.probe_seq "
            "TO business_ai_private_writer,private_writer_evidence_ingest"
        )
        await conn.execute(
            "GRANT EXECUTE ON FUNCTION s13_acl_app.probe_fn() "
            "TO business_ai_private_writer,private_writer_evidence_ingest"
        )
        await conn.execute(
            "GRANT USAGE ON TYPE s13_acl_app.probe_type "
            "TO business_ai_private_writer,private_writer_evidence_ingest"
        )
        large_object_id = await conn.fetchval("SELECT pg_catalog.lo_create(0)")
        await conn.execute(
            f"GRANT SELECT,UPDATE ON LARGE OBJECT {int(large_object_id)} "
            "TO business_ai_private_writer,private_writer_evidence_ingest"
        )

        # Seed additive global and change_ledger-local defaults for every supported object kind.
        # 027 must normalize both layers, then future ledger_owner-created objects must inherit
        # neither PUBLIC nor private service-role privileges.
        for scope in (
            "ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner",
            "ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner IN SCHEMA change_ledger",
        ):
            for grant in (
                "GRANT ALL ON TABLES",
                "GRANT ALL ON SEQUENCES",
                "GRANT EXECUTE ON ROUTINES",
                "GRANT USAGE ON TYPES",
            ):
                await conn.execute(
                    f"{scope} {grant} TO "
                    "PUBLIC,business_ai_private_writer,private_writer_evidence_ingest"
                )

        assert await conn.fetchval(
            "SELECT has_database_privilege('business_ai_private_writer',current_database(),'CREATE')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege('business_ai_private_writer',"
            "'s13_acl_app.probe','SELECT')"
        )
        assert await conn.fetchval(
            "SELECT has_any_column_privilege('private_writer_evidence_ingest',"
            "'s13_acl_app.probe','UPDATE')"
        )
        assert await conn.fetchval(
            "SELECT has_sequence_privilege('business_ai_private_writer',"
            "'s13_acl_app.probe_seq','USAGE')"
        )
        assert await conn.fetchval(
            "SELECT has_function_privilege('business_ai_private_writer',"
            "'s13_acl_app.probe_fn()','EXECUTE')"
        )
        assert await conn.fetchval(
            "SELECT has_type_privilege('business_ai_private_writer',"
            "'s13_acl_app.probe_type','USAGE')"
        )
        assert await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_largeobject_metadata l "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(l.lomacl) acl "
            "WHERE l.oid=$1 AND acl.grantee=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$2) "
            "AND acl.privilege_type='UPDATE')",
            large_object_id,
            "business_ai_private_writer",
        )

        await _apply_migration(conn, "027_private_writer_admission_schema.sql")

        for role in ("business_ai_private_writer", "private_writer_evidence_ingest"):
            assert not await conn.fetchval(
                "SELECT has_database_privilege($1,current_database(),'CREATE')", role
            )
            assert not await conn.fetchval(
                "SELECT has_schema_privilege($1,'s13_acl_app','CREATE')", role
            )
            assert not await conn.fetchval(
                "SELECT has_table_privilege($1,'s13_acl_app.probe','SELECT,INSERT,UPDATE,DELETE')",
                role,
            )
            assert not await conn.fetchval(
                "SELECT has_any_column_privilege($1,'s13_acl_app.probe','SELECT,INSERT,UPDATE')",
                role,
            )
            assert not await conn.fetchval(
                "SELECT has_sequence_privilege($1,'s13_acl_app.probe_seq','USAGE,SELECT,UPDATE')",
                role,
            )
            assert not await conn.fetchval(
                "SELECT has_function_privilege($1,'s13_acl_app.probe_fn()','EXECUTE')", role
            )
            assert not await conn.fetchval(
                "SELECT has_type_privilege($1,'s13_acl_app.probe_type','USAGE')", role
            )
            assert not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_largeobject_metadata l "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(l.lomacl) acl "
                "WHERE l.oid=$1 AND acl.grantee=(SELECT oid FROM pg_catalog.pg_roles "
                "WHERE rolname=$2) AND acl.privilege_type IN ('SELECT','UPDATE'))",
                large_object_id,
                role,
            )

        # The source candidate grants only the writer's mapped admission API, not its internal
        # transaction assertion helper or evidence-ingest entry points.
        assert await conn.fetchval(
            "SELECT has_function_privilege('business_ai_private_writer', "
            "'change_ledger.private_writer_admit_v1(" 
            "change_ledger.private_writer_identity_v1,text,bigint)','EXECUTE')"
        )
        assert not await conn.fetchval(
            "SELECT has_function_privilege('business_ai_private_writer', "
            "'change_ledger.private_writer_assert_transaction_v1()','EXECUTE')"
        )
        assert not await conn.fetchval(
            "SELECT has_function_privilege('private_writer_evidence_ingest', "
            "'change_ledger.private_writer_admit_v1(" 
            "change_ledger.private_writer_identity_v1,text,bigint)','EXECUTE')"
        )

        await conn.execute("CREATE SCHEMA s13_acl_future AUTHORIZATION ledger_owner")
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE ledger_owner")
            for schema in ("change_ledger", "s13_acl_future"):
                await conn.execute(
                    f"CREATE TABLE {schema}.s13_acl_default_table (id integer)"
                )
                await conn.execute(
                    f"CREATE SEQUENCE {schema}.s13_acl_default_sequence"
                )
                await conn.execute(
                    f"CREATE FUNCTION {schema}.s13_acl_default_function() RETURNS integer "
                    "LANGUAGE SQL IMMUTABLE AS 'SELECT 1'"
                )
                await conn.execute(
                    f"CREATE TYPE {schema}.s13_acl_default_type AS ENUM ('ONE')"
                )

        roles = ("business_ai_private_writer", "private_writer_evidence_ingest")
        for schema in ("change_ledger", "s13_acl_future"):
            assert not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(c.relacl, "
                "pg_catalog.acldefault((CASE WHEN c.relkind='S' THEN 'S' ELSE 'r' END)::\"char\", "
                "c.relowner))) acl WHERE n.nspname=$1 "
                "AND c.relname IN ('s13_acl_default_table','s13_acl_default_sequence') "
                "AND acl.grantee IN (0,(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$2),"
                "(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$3)))",
                schema,
                *roles,
            ), f"future table/sequence default grants leaked in schema {schema}"
            assert not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_proc p "
                "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(p.proacl, "
                "pg_catalog.acldefault('f'::\"char\",p.proowner))) acl WHERE n.nspname=$1 "
                "AND p.proname='s13_acl_default_function' "
                "AND acl.grantee IN (0,(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$2),"
                "(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$3)))",
                schema,
                *roles,
            ), f"future routine default grants leaked in schema {schema}"
            assert not await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_type t "
                "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(t.typacl, "
                "pg_catalog.acldefault('T'::\"char\",t.typowner))) acl WHERE n.nspname=$1 "
                "AND t.typname='s13_acl_default_type' AND t.typelem=0 "
                "AND acl.grantee IN (0,(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$2),"
                "(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=$3)))",
                schema,
                *roles,
            ), f"future type default grants leaked in schema {schema}"


async def test_s13_acl_rejects_preexisting_replication_role_transactionally(
        isolated_acl_cluster_dsn: _OwnedClusterDsn) -> None:
    """S13-ACL-SOURCE-ROLE-MAP-01: a pre-existing REPLICATION writer role refuses cutover."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)
        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE REPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )

        try:
            await _apply_migration(conn, "027_private_writer_admission_schema.sql")
        except asyncpg.PostgresError as error:
            assert error.sqlstate == "P0001"
            assert str(error).splitlines()[0] == "PRIVATE_WRITER_ROLE_UNSAFE"
            await conn.execute("ROLLBACK")
        else:
            raise AssertionError("replication-capable pre-existing writer role must refuse cutover")

        assert await conn.fetchval(
            "SELECT rolreplication FROM pg_catalog.pg_roles WHERE rolname='business_ai_private_writer'"
        )
        assert await conn.fetchval(
            "SELECT to_regclass('change_ledger.private_writer_service_bindings') IS NULL"
        )


async def test_s13_acl_rejects_preexisting_private_role_schema_ownership_transactionally(
        isolated_acl_cluster_dsn: _OwnedClusterDsn) -> None:
    """S13-ACL-SOURCE-ROLE-MAP-01: service-role schema ownership is not silently reassigned."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)
        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute("CREATE SCHEMA s13_acl_owned AUTHORIZATION business_ai_private_writer")

        try:
            await _apply_migration(conn, "027_private_writer_admission_schema.sql")
        except asyncpg.PostgresError as error:
            assert error.sqlstate == "P0001"
            assert str(error).splitlines()[0] == "PRIVATE_WRITER_ROLE_OWNS_OBJECT"
            await conn.execute("ROLLBACK")
        else:
            raise AssertionError("pre-existing service-role schema ownership must refuse cutover")

        assert await conn.fetchval(
            "SELECT pg_catalog.pg_get_userbyid(nspowner)='business_ai_private_writer' "
            "FROM pg_catalog.pg_namespace WHERE nspname='s13_acl_owned'"
        )
        assert await conn.fetchval(
            "SELECT to_regclass('change_ledger.private_writer_service_bindings') IS NULL"
        )


@pytest.mark.parametrize(
    "ownership_kind",
    ("relation", "sequence", "routine", "type", "large_object"),
)
async def test_s13_acl_rejects_preexisting_private_role_object_ownership_transactionally(
        isolated_acl_cluster_dsn: _OwnedClusterDsn, ownership_kind: str) -> None:
    """S13-ACL-SOURCE-ROLE-MAP-01: reject each portable service-role object ownership class."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)
        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute("CREATE SCHEMA s13_acl_owned")
        await conn.execute("GRANT USAGE,CREATE ON SCHEMA s13_acl_owned TO business_ai_private_writer")

        large_object_id: int | None = None
        if ownership_kind == "relation":
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE business_ai_private_writer")
                await conn.execute("CREATE TABLE s13_acl_owned.role_owned (id integer)")
        elif ownership_kind == "sequence":
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE business_ai_private_writer")
                await conn.execute("CREATE SEQUENCE s13_acl_owned.role_owned")
        elif ownership_kind == "routine":
            await conn.execute(
                "CREATE FUNCTION s13_acl_owned.role_owned() RETURNS integer "
                "LANGUAGE SQL IMMUTABLE AS 'SELECT 1'"
            )
            await conn.execute(
                "ALTER FUNCTION s13_acl_owned.role_owned() OWNER TO business_ai_private_writer"
            )
        elif ownership_kind == "type":
            await conn.execute("CREATE TYPE s13_acl_owned.role_owned AS ENUM ('ONE')")
            await conn.execute(
                "ALTER TYPE s13_acl_owned.role_owned OWNER TO business_ai_private_writer"
            )
        elif ownership_kind == "large_object":
            large_object_id = await conn.fetchval("SELECT pg_catalog.lo_create(0)")
            await conn.execute(
                f"ALTER LARGE OBJECT {int(large_object_id)} OWNER TO business_ai_private_writer"
            )
        else:
            raise AssertionError(f"unsupported test ownership kind: {ownership_kind}")

        try:
            await _apply_migration(conn, "027_private_writer_admission_schema.sql")
        except asyncpg.PostgresError as error:
            assert error.sqlstate == "P0001"
            assert str(error).splitlines()[0] == "PRIVATE_WRITER_ROLE_OWNS_OBJECT"
            await conn.execute("ROLLBACK")
        else:
            raise AssertionError(f"pre-existing {ownership_kind} ownership must refuse cutover")

        if ownership_kind in {"relation", "sequence"}:
            assert await conn.fetchval(
                "SELECT pg_catalog.pg_get_userbyid(c.relowner)='business_ai_private_writer' "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.relnamespace WHERE n.nspname='s13_acl_owned' AND c.relname='role_owned'"
            )
        elif ownership_kind == "routine":
            assert await conn.fetchval(
                "SELECT pg_catalog.pg_get_userbyid(p.proowner)='business_ai_private_writer' "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='s13_acl_owned' "
                "AND p.proname='role_owned'"
            )
        elif ownership_kind == "type":
            assert await conn.fetchval(
                "SELECT pg_catalog.pg_get_userbyid(t.typowner)='business_ai_private_writer' "
                "FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n "
                "ON n.oid=t.typnamespace WHERE n.nspname='s13_acl_owned' "
                "AND t.typname='role_owned' AND t.typelem=0"
            )
        else:
            assert await conn.fetchval(
                "SELECT pg_catalog.pg_get_userbyid(l.lomowner)='business_ai_private_writer' "
                "FROM pg_catalog.pg_largeobject_metadata l WHERE l.oid=$1",
                large_object_id,
            )
        assert await conn.fetchval(
            "SELECT to_regclass('change_ledger.private_writer_service_bindings') IS NULL"
        )


async def test_s13_acl_rejects_current_database_owned_by_private_role_transactionally(
        isolated_acl_cluster_dsn: _OwnedClusterDsn) -> None:
    """S13-ACL-SOURCE-ROLE-MAP-01: current database ownership refuses private-service admission."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)
        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        database_name = await conn.fetchval("SELECT current_database()")
        await conn.execute(
            f'ALTER DATABASE "{database_name}" OWNER TO business_ai_private_writer'
        )

        try:
            await _apply_migration(conn, "027_private_writer_admission_schema.sql")
        except asyncpg.PostgresError as error:
            assert error.sqlstate == "P0001"
            assert str(error).splitlines()[0] == "PRIVATE_WRITER_ROLE_OWNS_OBJECT"
            await conn.execute("ROLLBACK")
        else:
            raise AssertionError("current database ownership by a writer role must refuse cutover")

        assert await conn.fetchval(
            "SELECT pg_catalog.pg_get_userbyid(d.datdba)='business_ai_private_writer' "
            "FROM pg_catalog.pg_database d WHERE d.datname=current_database()"
        )
        assert await conn.fetchval(
            "SELECT to_regclass('change_ledger.private_writer_service_bindings') IS NULL"
        )


async def test_s13_acl_rejects_preexisting_private_role_extension_ownership_transactionally(
        isolated_acl_cluster_dsn: _OwnedClusterDsn) -> None:
    """S13-ACL-SOURCE-ROLE-MAP-01: a trusted disposable extension owned by writer refuses cutover."""
    async with throwaway_db(isolated_acl_cluster_dsn.value, seed=False) as db:
        conn = db.conn
        await apply_files(conn)
        for migration in MIGRATIONS_019_026:
            await _apply_migration(conn, migration)
        await conn.execute(
            "CREATE ROLE business_ai_private_writer LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        await conn.execute(
            "CREATE ROLE private_writer_evidence_ingest LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT"
        )
        database_name = await conn.fetchval("SELECT current_database()")
        await conn.execute(
            f'GRANT CREATE ON DATABASE "{database_name}" TO business_ai_private_writer'
        )
        await conn.execute("CREATE SCHEMA s13_acl_extension")
        await conn.execute("GRANT USAGE,CREATE ON SCHEMA s13_acl_extension TO business_ai_private_writer")
        trusted_citext = await conn.fetchval(
            "SELECT trusted FROM pg_catalog.pg_available_extension_versions "
            "WHERE name='citext' ORDER BY version DESC LIMIT 1"
        )
        if trusted_citext is not True:
            pytest.skip("NOT_RUN: trusted citext extension is unavailable in disposable PostgreSQL image")

        try:
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE business_ai_private_writer")
                await conn.execute("CREATE EXTENSION citext WITH SCHEMA s13_acl_extension")
        except asyncpg.PostgresError as error:
            pytest.skip(
                "NOT_RUN: disposable PostgreSQL image does not permit trusted citext creation by "
                f"the seeded role ({error.sqlstate}: {str(error).splitlines()[0]})"
            )

        assert await conn.fetchval(
            "SELECT pg_catalog.pg_get_userbyid(extowner)='business_ai_private_writer' "
            "FROM pg_catalog.pg_extension WHERE extname='citext'"
        )
        try:
            await _apply_migration(conn, "027_private_writer_admission_schema.sql")
        except asyncpg.PostgresError as error:
            assert error.sqlstate == "P0001"
            assert str(error).splitlines()[0] == "PRIVATE_WRITER_ROLE_OWNS_OBJECT"
            await conn.execute("ROLLBACK")
        else:
            raise AssertionError("extension ownership by a private service role must refuse cutover")

        assert await conn.fetchval(
            "SELECT pg_catalog.pg_get_userbyid(extowner)='business_ai_private_writer' "
            "FROM pg_catalog.pg_extension WHERE extname='citext'"
        )
        assert await conn.fetchval(
            "SELECT to_regclass('change_ledger.private_writer_service_bindings') IS NULL"
        )


@pytest_asyncio.fixture(scope="module")
async def evidence_lookup_db() -> AsyncIterator[object]:
    """One isolated PG16 fixture for behavioral checks of the bounded evidence reader."""
    old_opt_in = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, _name, _token):
            async with throwaway_db(dsn, seed=False) as db:
                await apply_files(db.conn)
                for migration in MIGRATIONS_019_027:
                    await _apply_migration(db.conn, migration)
                await _setup(db.conn)
                yield db
    finally:
        if old_opt_in is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old_opt_in


def _lookup_identity() -> dict[str, object]:
    return {
        "dispatch_cas_id": uuid.uuid4(),
        "dispatch_intent_id": uuid.uuid4(),
        "call_id": uuid.uuid4(),
        "change_id": uuid.uuid4(),
        "permit_id": uuid.uuid4(),
        "tenant_id": T,
        "company_id": C,
        "organization_ref": _S13_EVIDENCE_ORG,
        "base_fingerprint": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "claim_generation": 1,
        "dispatch_generation": 1,
        "operation_kind": "POST",
        "approval_digest": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "payload_digest": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "permit_digest": hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        "auth_epoch": 1,
        "expected_target_ref": "target-s13-evidence",
        "expected_pre_version": "v1",
        "writer_service_id": "s13-functional-test-service",
        "writer_host_id": "s13-functional-test-host",
        "writer_process_instance_id": str(uuid.uuid4()),
        "session_user": "s13_ingest_" + uuid.uuid4().hex,
        "signer_key_id": "s13-functional-test-key-" + uuid.uuid4().hex,
        "signer_key_version": "v1",
        "signer_public_key": hashlib.sha256(uuid.uuid4().bytes).digest(),
        "evidence_refs": [],
    }


async def _seed_evidence_lookup_attempt(
        conn: asyncpg.Connection, *, evidence_count: int = 1,
        oversized: bool = False) -> dict[str, object]:
    """Seed relationally valid synthetic immutable records for the S13 lookup boundary."""
    identity = _lookup_identity()
    cid = identity["change_id"]
    generation = identity["claim_generation"]
    base = identity["base_fingerprint"]
    refs = [f"s13-lookup-{uuid.uuid4()}" for _ in range(evidence_count)]
    identity["evidence_refs"] = refs
    oversized_ref = refs[0] if oversized else None

    await conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class) "
        "VALUES($1,$2,$3,$4,'DISPOSABLE_CLONE')",
        identity["tenant_id"], identity["company_id"], base, identity["organization_ref"],
    )
    await conn.execute(
        "INSERT INTO change_ledger.records(change_id,tenant_id,company_id,base_fingerprint,organization_ref,"
        "kind,requester,request_id,payload_digest,auth_epoch_at_proposal,expires_at) "
        "VALUES($1,$2,$3,$4,$5,'POST','s13-test', $6,$7,1,clock_timestamp()+interval '1 day')",
        cid, identity["tenant_id"], identity["company_id"], base, identity["organization_ref"],
        str(uuid.uuid4()), identity["payload_digest"],
    )
    await conn.execute(
        "INSERT INTO change_ledger.dispatch_permits(change_id,generation) VALUES($1,$2)",
        cid, generation,
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_service_bindings(\"session_user\",base_fingerprint,"
        "writer_service_id,writer_host_id) VALUES($1,$2,$3,$4)",
        identity["session_user"], base, identity["writer_service_id"], identity["writer_host_id"],
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_versions(key_id,key_version,public_key,signer_role,"
        "service_id,host_id,valid_from,valid_until) VALUES($1,$2,$3,'writer_receipt',$4,$5,"
        "clock_timestamp()-interval '1 day',clock_timestamp()+interval '1 day')",
        identity["signer_key_id"], identity["signer_key_version"], identity["signer_public_key"],
        identity["writer_service_id"], identity["writer_host_id"],
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_scopes(key_id,key_version,tenant_id,company_id,"
        "organization_ref,base_fingerprint) VALUES($1,$2,$3,$4,$5,$6)",
        identity["signer_key_id"], identity["signer_key_version"], identity["tenant_id"],
        identity["company_id"], identity["organization_ref"], base,
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_dispatch_intents(dispatch_intent_id,tenant_id,company_id,"
        "organization_ref,base_fingerprint,change_id,claim_generation,dispatch_generation,call_id,operation_kind,"
        "approval_digest,payload_digest,target_ref,expected_pre_version,auth_epoch) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
        identity["dispatch_intent_id"], identity["tenant_id"], identity["company_id"],
        identity["organization_ref"], base, cid, generation, identity["dispatch_generation"],
        identity["call_id"], identity["operation_kind"], identity["approval_digest"],
        identity["payload_digest"], identity["expected_target_ref"], identity["expected_pre_version"],
        identity["auth_epoch"],
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_permit_bindings(dispatch_intent_id,permit_id,permit_digest,"
        "checkpoint_seq,signer_key_id,signer_key_version,issued_at,expires_at) "
        "VALUES($1,$2,$3,1,$4,$5,clock_timestamp(),clock_timestamp()+interval '1 day')",
        identity["dispatch_intent_id"], identity["permit_id"], identity["permit_digest"],
        identity["signer_key_id"], identity["signer_key_version"],
    )
    await conn.execute(
        "INSERT INTO change_ledger.dispatch_attempts(dispatch_cas_id,dispatch_intent_id,tenant_id,company_id,"
        "organization_ref,base_fingerprint,change_id,claim_generation,dispatch_generation,call_id,operation_kind,"
        "approval_digest,payload_digest,permit_id,permit_digest,expected_target_ref,expected_pre_version,auth_epoch,"
        "\"session_user\",writer_service_id,writer_host_id,writer_process_instance_id,service_epoch,state) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,1,"
        "'ACCEPTED_NOT_INVOKED')",
        identity["dispatch_cas_id"], identity["dispatch_intent_id"], identity["tenant_id"],
        identity["company_id"], identity["organization_ref"], base, cid, generation,
        identity["dispatch_generation"], identity["call_id"], identity["operation_kind"],
        identity["approval_digest"], identity["payload_digest"], identity["permit_id"],
        identity["permit_digest"], identity["expected_target_ref"], identity["expected_pre_version"],
        identity["auth_epoch"], identity["session_user"], identity["writer_service_id"],
        identity["writer_host_id"], identity["writer_process_instance_id"],
    )

    for evidence_ref in refs:
        signed_bytes = (
            b"s13-functional-evidence:" + evidence_ref.encode("ascii")
            if evidence_ref != oversized_ref else b"x" * (2 * 1024 * 1024 + 1)
        )
        digest = hashlib.sha256(signed_bytes).hexdigest()
        await conn.execute(
            "INSERT INTO change_ledger.private_writer_evidence(evidence_ref,record_type,writer_receipt_id,"
            "writer_invocation_stage,writer_result_class,writer_call_returned,no_effect_evidence_digest,"
            "signed_bytes,signed_bytes_sha256,record_digest,tenant_id,company_id,organization_ref,base_fingerprint,"
            "change_id,claim_generation,dispatch_generation,call_id,dispatch_cas_id,dispatch_intent_id,"
            "operation_kind,approval_digest,payload_digest,permit_id,permit_digest,target_ref,pre_version,auth_epoch,"
            "repair_authorization_id,signer_key_id,signer_key_version,signer_role,signer_service_id,signer_host_id,"
            "signed_at,trust_registry_revision,verified_at,validator_build_id,process_instance_id,session_instance_id) "
            "VALUES($1,'DISPATCH_NO_ENTRY_RECEIPT_V1',$2,'NOT_INVOKED','PRE_WRITE_NO_EFFECT',false,$3,$4,"
            "pg_catalog.sha256($4),$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,"
            "$23,NULL,$24,$25,'writer_receipt',$26,$27,clock_timestamp(),1,clock_timestamp(),"
            "'s13-functional-test-fixture',$28,NULL)",
            evidence_ref, uuid.uuid4(), digest, signed_bytes, digest, identity["tenant_id"], identity["company_id"],
            identity["organization_ref"], base, cid, generation, identity["dispatch_generation"],
            identity["call_id"], identity["dispatch_cas_id"], identity["dispatch_intent_id"],
            identity["operation_kind"], identity["approval_digest"], identity["payload_digest"],
            identity["permit_id"], identity["permit_digest"], identity["expected_target_ref"],
            identity["expected_pre_version"], identity["auth_epoch"], identity["signer_key_id"],
            identity["signer_key_version"], identity["writer_service_id"], identity["writer_host_id"],
            identity["writer_process_instance_id"],
        )
    return identity


_EVIDENCE_LOAD_FUNCTION = (
    "change_ledger.private_writer_load_evidence_records_v1(uuid,uuid,text,text,text,text,uuid,bigint,text,text[])"
)
_EVIDENCE_LOAD_SQL = (
    "SELECT * FROM change_ledger.private_writer_load_evidence_records_v1("
    "$1::uuid,$2::uuid,$3::text,$4::text,$5::text,$6::text,$7::uuid,$8::bigint,$9::text,$10::text[])"
)


def _evidence_load_args(identity: dict[str, object], refs: list[str]) -> tuple[object, ...]:
    return (
        identity["dispatch_cas_id"], identity["call_id"], identity["tenant_id"], identity["company_id"],
        identity["organization_ref"], identity["base_fingerprint"], identity["change_id"],
        identity["claim_generation"], identity["operation_kind"], refs,
    )


async def _call_evidence_loader_as(
        conn: asyncpg.Connection, session_role: str, args: tuple[object, ...],
        sql: str = _EVIDENCE_LOAD_SQL) -> list[asyncpg.Record]:
    """Temporarily grant and SET SESSION AUTHORIZATION inside a transaction that always rolls back."""
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(f"GRANT EXECUTE ON FUNCTION {_EVIDENCE_LOAD_FUNCTION} TO {session_role}")
        await conn.execute(f"SET SESSION AUTHORIZATION {session_role}")
        return await conn.fetch(sql, *args)
    finally:
        await tx.rollback()


async def _expect_evidence_loader_refusal(
        conn: asyncpg.Connection, session_role: str, args: tuple[object, ...],
        code: str = "NOT_ENTITLED", sqlstate: str = "42501",
        sql: str = _EVIDENCE_LOAD_SQL) -> None:
    try:
        await _call_evidence_loader_as(conn, session_role, args, sql)
    except asyncpg.PostgresError as error:
        assert error.sqlstate == sqlstate, (error.sqlstate, str(error))
        assert str(error).splitlines()[0] == code, str(error)
    else:
        raise AssertionError(f"evidence loader must refuse with stable {code}")


@pytest.mark.asyncio(loop_scope="module")
async def test_s13_evidence_loader_returns_exact_one_and_five_refs_in_requested_order(
        evidence_lookup_db: object) -> None:
    """S13-EVIDENCE-READ-01: only the complete attempt selector returns exact ordered envelopes."""
    conn = evidence_lookup_db.conn
    one = await _seed_evidence_lookup_attempt(conn, evidence_count=1)
    five = await _seed_evidence_lookup_attempt(conn, evidence_count=5)
    single_rows = await _call_evidence_loader_as(
        conn, "private_writer_evidence_ingest", _evidence_load_args(one, [one["evidence_refs"][0]])
    )
    assert [(row["evidence_ref"], row["record_type"], row["signed_bytes"])
            for row in single_rows] == [(one["evidence_refs"][0], "DISPATCH_NO_ENTRY_RECEIPT_V1",
                                         b"s13-functional-evidence:" + one["evidence_refs"][0].encode("ascii"))]

    requested = [five["evidence_refs"][3], five["evidence_refs"][0], five["evidence_refs"][4],
                 five["evidence_refs"][1], five["evidence_refs"][2]]
    five_rows = await _call_evidence_loader_as(
        conn, "private_writer_evidence_ingest", _evidence_load_args(five, requested)
    )
    assert [(row["evidence_ref"], row["record_type"], row["signed_bytes"])
            for row in five_rows] == [
        (ref, "DISPATCH_NO_ENTRY_RECEIPT_V1", b"s13-functional-evidence:" + ref.encode("ascii"))
        for ref in requested
    ]


@pytest.mark.parametrize("mutation", [
    "dispatch_cas_id", "call_id", "tenant_id", "company_id", "organization_ref", "base_fingerprint",
    "change_id", "claim_generation", "operation_kind",
])
@pytest.mark.asyncio(loop_scope="module")
async def test_s13_evidence_loader_wrong_attempt_selector_returns_no_rows(
        evidence_lookup_db: object, mutation: str) -> None:
    """S13-EVIDENCE-READ-02: each S12 selector is bound to one exact attempt."""
    conn = evidence_lookup_db.conn
    attempt = await _seed_evidence_lookup_attempt(conn)
    bad = dict(attempt)
    if mutation in {"dispatch_cas_id", "call_id", "change_id"}:
        bad[mutation] = uuid.uuid4()
    elif mutation == "claim_generation":
        bad[mutation] = attempt[mutation] + 1
    elif mutation == "operation_kind":
        bad[mutation] = "UNPOST"
    elif mutation == "base_fingerprint":
        bad[mutation] = hashlib.sha256(b"different valid S13 base").hexdigest()
    else:
        bad[mutation] = str(attempt[mutation]) + "-wrong"
    await _expect_evidence_loader_refusal(
        conn, "private_writer_evidence_ingest", _evidence_load_args(bad, attempt["evidence_refs"])
    )


@pytest.mark.parametrize("selector_kind", [
    "null", "empty", "duplicate", "multidimensional", "empty_ref", "padded_ref", "oversized_ref",
    "control_ref", "non_one_lower_bound",
])
@pytest.mark.asyncio(loop_scope="module")
async def test_s13_evidence_loader_rejects_malformed_array_selectors(
        evidence_lookup_db: object, selector_kind: str) -> None:
    """S13-EVIDENCE-READ-03: malformed text-array selectors fail closed before any row is returned."""
    conn = evidence_lookup_db.conn
    attempt = await _seed_evidence_lookup_attempt(conn)
    ref = attempt["evidence_refs"][0]
    args = list(_evidence_load_args(attempt, [ref]))
    if selector_kind == "null":
        args[-1] = None
    elif selector_kind == "empty":
        args[-1] = []
    elif selector_kind == "duplicate":
        args[-1] = [ref, ref]
    elif selector_kind == "multidimensional":
        args[-1] = [[ref], [ref + "-other"]]
    elif selector_kind == "empty_ref":
        args[-1] = [""]
    elif selector_kind == "padded_ref":
        args[-1] = [" " + ref]
    elif selector_kind == "oversized_ref":
        args[-1] = ["x" * 257]
    elif selector_kind == "control_ref":
        args[-1] = [ref + "\n"]
    else:
        args[-1] = ref
        lower_bound_sql = _EVIDENCE_LOAD_SQL.replace(
            "$10::text[]", "pg_catalog.array_fill($10::text,ARRAY[1],ARRAY[0])"
        )
        await _expect_evidence_loader_refusal(
            conn, "private_writer_evidence_ingest", tuple(args),
            code="SCHEMA_INVALID", sqlstate="P0001", sql=lower_bound_sql,
        )
        return
    await _expect_evidence_loader_refusal(
        conn, "private_writer_evidence_ingest", tuple(args), code="SCHEMA_INVALID", sqlstate="P0001"
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_s13_evidence_loader_missing_and_cross_attempt_refs_refuse_without_partial_rows(
        evidence_lookup_db: object) -> None:
    """S13-EVIDENCE-READ-04: one missing ref invalidates the whole selector, never a partial result."""
    conn = evidence_lookup_db.conn
    first = await _seed_evidence_lookup_attempt(conn)
    second = await _seed_evidence_lookup_attempt(conn)
    await _expect_evidence_loader_refusal(
        conn, "private_writer_evidence_ingest",
        _evidence_load_args(first, [first["evidence_refs"][0], "missing-s13-evidence-ref"]),
    )
    await _expect_evidence_loader_refusal(
        conn, "private_writer_evidence_ingest",
        _evidence_load_args(first, [first["evidence_refs"][0], second["evidence_refs"][0]]),
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_s13_evidence_loader_wrong_session_identity_is_not_entitled(
        evidence_lookup_db: object) -> None:
    """S13-EVIDENCE-READ-05: callers other than the evidence-ingest session are refused."""
    conn = evidence_lookup_db.conn
    attempt = await _seed_evidence_lookup_attempt(conn)
    await _expect_evidence_loader_refusal(
        conn, "business_ai_private_writer", _evidence_load_args(attempt, attempt["evidence_refs"])
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_s13_evidence_loader_oversized_envelope_is_not_returned(
        evidence_lookup_db: object) -> None:
    """S13-EVIDENCE-READ-06: envelopes above two MiB fail closed, without partial rows."""
    conn = evidence_lookup_db.conn
    attempt = await _seed_evidence_lookup_attempt(conn, oversized=True)
    oversized = attempt["evidence_refs"][0]
    await _expect_evidence_loader_refusal(
        conn, "private_writer_evidence_ingest", _evidence_load_args(attempt, [oversized])
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_s13_evidence_loader_candidate_keeps_table_and_execute_acl_withheld(
        evidence_lookup_db: object) -> None:
    """S13-EVIDENCE-ACL-01: writer/reader roles have no direct table grant or lookup EXECUTE."""
    conn = evidence_lookup_db.conn
    for role in ("business_ai_private_writer", "private_writer_evidence_ingest"):
        assert not await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.unnest(ARRAY["
            "'SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) p(priv) "
            "WHERE pg_catalog.has_table_privilege($1,"
            "'change_ledger.private_writer_evidence',p.priv))",
            role,
        ), f"{role} unexpectedly has direct access to immutable evidence rows"
        assert not await conn.fetchval(
            "SELECT pg_catalog.has_function_privilege($1, $2, 'EXECUTE')",
            role, _EVIDENCE_LOAD_FUNCTION,
        ), f"{role} unexpectedly has EXECUTE on the bounded lookup function"
    assert not await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_proc p "
        "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,"
        "pg_catalog.acldefault('f'::\"char\",p.proowner))) a "
        "WHERE n.nspname='change_ledger' AND p.proname='private_writer_load_evidence_records_v1' "
        "AND a.grantee=0 AND a.privilege_type='EXECUTE')"
    )

