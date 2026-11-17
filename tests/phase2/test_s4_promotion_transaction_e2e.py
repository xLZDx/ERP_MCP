"""Disposable PostgreSQL contract scenarios for S4 promotion (R2-US-016).

This module never reads ERP_PHASE2_TEST_DSN. It provisions an invocation-owned loopback
cluster through _pg_harness and a uniquely named s4_disposable_* database. The two S4 SQL
files remain testbed fixtures, not application migrations or production setup.
"""
import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

import _pg_harness as pg

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
S4_SQL = ROOT / "testbed" / "phase2" / "sql"
TENANT, SOURCE, COMPANY, MODEL = "A", "s4", "c1", "s4-contract-model"
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)
DIGEST = "a" * 64


@pytest.fixture
async def s4db():
    """A fresh owned cluster and explicitly guarded database for each scenario."""
    async with pg.disposable_cluster() as (admin_dsn, _container_name, _owner_token):
        db_name = "s4_disposable_" + uuid.uuid4().hex[:12]
        admin = await pg.admin_connect(admin_dsn)
        conn = None
        created = False
        try:
            await admin.execute(f'CREATE DATABASE "{db_name}"')
            created = True
            conn = await pg.admin_connect(admin_dsn, database=db_name)
            await pg.apply_files(conn)
            await pg.seed_basic(conn)
            await conn.execute("""
              INSERT INTO living.role_scope(role_name,tenant_id,source_id,company_id) VALUES
                ('living_worker','A','s4','c1'),
                ('living_promoter','A','s4','c1');
              INSERT INTO living.accepted_heads(tenant_id,source_id,model_key)
                VALUES ('A','s4','s4-contract-model');
            """)

            # Both scripts self-check the database name and this explicit session opt-in.
            await conn.execute("SELECT set_config('s4.disposable_fixture','on',false)")
            await conn.execute((S4_SQL / "s4_promotion_eligibility.sql").read_text(encoding="utf-8"))
            await conn.execute("""
              CREATE ROLE living_s4_verifier NOLOGIN NOSUPERUSER NOBYPASSRLS
                NOCREATEDB NOCREATEROLE;
            """)
            await conn.execute((S4_SQL / "s4_promotion_transaction.sql").read_text(encoding="utf-8"))

            # Every identity and scope below is synthetic and local to this disposable DB.
            await conn.execute(
                "INSERT INTO living.role_scope(role_name,tenant_id,source_id,company_id) "
                "VALUES ('living_s4_fixture_verifier','A','s4','c1'),"
                "('living_s4_fixture_promoter','A','s4','c1')")
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE living_owner")
                await conn.fetchval("SELECT living.set_trusted_reviewer($1,$2,$3,true,$4)",
                                    "living_worker", TENANT, SOURCE, FUTURE)
                await conn.fetchval("SELECT living.s4_set_model_mode($1,$2,$3,'ENROLLED')",
                                    TENANT, SOURCE, MODEL)
                await conn.fetchval(
                    "SELECT living.s4_bind_actor($1,$2,$3,$4,'REQUESTER')",
                    TENANT, SOURCE, "living_reader", "synthetic-requester")
                await conn.fetchval(
                    "SELECT living.s4_bind_actor($1,$2,$3,$4,'APPROVER')",
                    TENANT, SOURCE, "living_s4_fixture_promoter", "synthetic-approver")
            yield S4Database(admin_dsn, db_name, conn)
        finally:
            if conn is not None:
                await conn.close()
            if created:
                await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            await admin.close()


class S4Database:
    def __init__(self, dsn, name, conn):
        self.dsn, self.name, self.conn = dsn, name, conn

    async def connect(self):
        return await pg.admin_connect(self.dsn, database=self.name)

    @asynccontextmanager
    async def scoped(self, conn, role="living_s4_fixture_promoter", company=COMPANY):
        async with conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {role}")
            await conn.fetchval("SELECT living.set_scope($1,$2,$3)", TENANT, SOURCE, company)
            yield

    async def seed_eligible(self, *, model=MODEL, object_id=None):
        revision, observation, attestation, eligibility = (uuid.uuid4() for _ in range(4))
        object_id = object_id or "s4-object-" + uuid.uuid4().hex
        async with self.scoped(self.conn, "living_worker"):
            await self.conn.fetchval(
                "SELECT living.ingest_observation($1,$2,$3::uuid,$4,$5::uuid,'OBSERVED',$6,"
                "NULL,$7::timestamptz,NULL,NULL,'{}'::jsonb)",
                TENANT, SOURCE, observation, object_id, revision, DIGEST,
                datetime(2024, 1, 2, tzinfo=UTC))
        evidence = "synthetic-evidence-" + uuid.uuid4().hex
        evidence_digest = hashlib.sha256(f"{DIGEST}:{evidence}".encode()).hexdigest()
        async with self.scoped(self.conn, "living_worker"):
            await self.conn.fetchval(
                "SELECT living.record_attestation($1,$2,$3,$4,$5,$6,$7,'APPROVE',$8)",
                TENANT, SOURCE, attestation, revision, "synthetic-requester", evidence,
                evidence_digest, FUTURE)
        async with self.scoped(self.conn, "living_s4_fixture_verifier"):
            await self.conn.fetchval(
                "SELECT living.s4_register_eligibility($1,$2,$3,$4,$5,$6,$7,$8)",
                TENANT, SOURCE, eligibility, COMPANY, attestation, revision,
                "fixture-v1", DIGEST)
        return Eligible(revision, attestation, eligibility, evidence)

    async def request(self, eligible, *, acceptance=None, expected=0, model=MODEL,
                      operation="promote", rollback_version=None):
        acceptance = acceptance or uuid.uuid4()
        async with self.conn.transaction():
            await self.conn.execute("SET LOCAL ROLE living_owner")
            result = await self.conn.fetchval(
                "SELECT living.s4_register_request($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                TENANT, SOURCE, str(acceptance), COMPANY, model, operation, rollback_version,
                expected, str(eligible.revision), eligible.eligibility, "living_reader")
        assert result == acceptance
        return acceptance

    async def promote(self, conn, acceptance, *, role="living_s4_fixture_promoter", company=COMPANY):
        async with self.scoped(conn, role, company):
            return await conn.fetchrow(
                "SELECT * FROM living.s4_promote_v1($1,$2,$3)", TENANT, SOURCE, acceptance)

    async def readback(self, conn, acceptance, *, role="living_s4_fixture_promoter", company=COMPANY):
        async with self.scoped(conn, role, company):
            return await conn.fetchrow(
                "SELECT * FROM living.s4_readback_v1($1,$2,$3)", TENANT, SOURCE, acceptance)


class Eligible:
    def __init__(self, revision, attestation, eligibility, evidence):
        self.revision, self.attestation = revision, attestation
        self.eligibility, self.evidence = eligibility, evidence


async def _counts(conn, acceptance):
    return await conn.fetchrow("""
      SELECT (SELECT count(*) FROM living.acceptance_events
               WHERE tenant_id=$1 AND source_id=$2 AND acceptance_id=$3) AS events,
             (SELECT count(*) FROM living.s4_acceptance_fingerprints
               WHERE tenant_id=$1 AND source_id=$2 AND acceptance_id=$3) AS fingerprints,
             (SELECT version FROM living.accepted_heads
               WHERE tenant_id=$1 AND source_id=$2 AND model_key=$4) AS version
    """, TENANT, SOURCE, acceptance, MODEL)


async def _capture_promotion(s4db, acceptance):
    conn = await s4db.connect()
    try:
        return await s4db.promote(conn, acceptance)
    finally:
        await conn.close()


async def _promotion_attempt(s4db, acceptance):
    try:
        return await _capture_promotion(s4db, acceptance)
    except asyncpg.PostgresError as exc:
        return exc


async def test_concurrent_requests_share_one_expected_head_version(s4db):
    eligible = await s4db.seed_eligible()
    first = await s4db.request(eligible, expected=0)
    second = await s4db.request(eligible, expected=0)
    outcomes = await asyncio.gather(_promotion_attempt(s4db, first),
                                    _promotion_attempt(s4db, second))

    successes = [o for o in outcomes if not isinstance(o, Exception)]
    failures = [o for o in outcomes if isinstance(o, asyncpg.PostgresError)]
    assert len(successes) == 1
    assert successes[0]["outcome"] == "COMMITTED"
    assert len(failures) == 1 and "STALE_ACCEPTED_HEAD" in str(failures[0])
    first_counts = tuple(await _counts(s4db.conn, first))
    second_counts = tuple(await _counts(s4db.conn, second))
    assert sorted((first_counts[0], second_counts[0])) == [0, 1]
    assert sorted((first_counts[1], second_counts[1])) == [0, 1]
    assert first_counts[2] == second_counts[2] == 1


async def test_legacy_path_rejects_enrolled_model_and_old_event_is_unverified(s4db):
    eligible = await s4db.seed_eligible()
    old_acceptance = uuid.uuid4()
    await s4db.conn.execute("""
      INSERT INTO living.acceptance_events(tenant_id,source_id,acceptance_id,model_key,
        from_version,to_version,accepted_revision,approver_subject,independent_evidence_ref)
      VALUES($1,$2,$3,$4,0,1,$5,'synthetic-approver','historical-evidence')
    """, TENANT, SOURCE, old_acceptance, MODEL, eligible.revision)
    async with s4db.scoped(s4db.conn, "living_promoter"):
        with pytest.raises(asyncpg.PostgresError, match="S4_MODEL_ENROLLED"):
            await s4db.conn.fetchval(
                "SELECT living.promote_head($1,$2,$3,0,$4,$5,'historical-evidence')",
                TENANT, SOURCE, MODEL, eligible.revision, old_acceptance)

    async with s4db.scoped(s4db.conn):
        old = await s4db.conn.fetchrow(
            "SELECT * FROM living.s4_readback_v1($1,$2,$3)", TENANT, SOURCE, old_acceptance)
    assert tuple(old) == ("HISTORICAL_EVENT", None, None)
    assert await s4db.conn.fetchval(
        "SELECT count(*) FROM living.s4_acceptance_fingerprints WHERE acceptance_id=$1",
        old_acceptance) == 0


async def test_failure_between_event_and_fingerprint_rolls_back_head_and_event(s4db):
    eligible = await s4db.seed_eligible()
    acceptance = await s4db.request(eligible)
    await s4db.conn.execute("""
      CREATE FUNCTION living.s4_test_fail_fingerprint_insert() RETURNS trigger
      LANGUAGE plpgsql AS $fn$ BEGIN RAISE EXCEPTION 'INJECTED_FINGERPRINT_FAILURE'; END $fn$;
      CREATE TRIGGER s4_test_fail_fingerprint_insert
      BEFORE INSERT ON living.s4_acceptance_fingerprints
      FOR EACH ROW EXECUTE FUNCTION living.s4_test_fail_fingerprint_insert();
    """)

    with pytest.raises(asyncpg.PostgresError, match="INJECTED_FINGERPRINT_FAILURE"):
        await s4db.promote(s4db.conn, acceptance)
    counts = await _counts(s4db.conn, acceptance)
    assert tuple(counts) == (0, 0, 0)


async def test_discarded_response_reads_back_exact_commit_without_duplicate(s4db):
    eligible = await s4db.seed_eligible()
    acceptance = await s4db.request(eligible)
    committed = await s4db.promote(s4db.conn, acceptance)
    assert committed["outcome"] == "COMMITTED"

    # Model a caller that lost/discarded the response after the DB call completed; this does not
    # emulate a network partition. Recovery uses a new connection and never dispatches again.
    recovered_conn = await s4db.connect()
    try:
        recovered = await s4db.readback(recovered_conn, acceptance)
    finally:
        await recovered_conn.close()
    assert recovered["outcome"] == "EXACT_COMMIT"
    assert recovered["to_version"] == committed["to_version"] == 1
    assert recovered["request_sha256"] == committed["request_sha256"]
    assert tuple(await _counts(s4db.conn, acceptance)) == (1, 1, 1)


async def test_revoked_eligibility_fails_before_head_write(s4db):
    eligible = await s4db.seed_eligible()
    acceptance = await s4db.request(eligible)
    async with s4db.scoped(s4db.conn, "living_s4_fixture_verifier"):
        await s4db.conn.fetchval(
            "SELECT living.s4_revoke_eligibility($1,$2,$3)",
            TENANT, SOURCE, eligible.eligibility)
    with pytest.raises(asyncpg.PostgresError, match="ELIGIBILITY_NOT_VALID"):
        await s4db.promote(s4db.conn, acceptance)
    assert tuple(await _counts(s4db.conn, acceptance)) == (0, 0, 0)


async def test_company_and_role_mismatch_fail_closed(s4db):
    eligible = await s4db.seed_eligible()
    acceptance = await s4db.request(eligible)
    with pytest.raises(asyncpg.PostgresError, match="COMPANY_SCOPE_MISMATCH"):
        async with s4db.scoped(s4db.conn):
            await s4db.conn.execute("SELECT set_config('living.company_id','c2',true)")
            await s4db.conn.fetchrow(
                "SELECT * FROM living.s4_promote_v1($1,$2,$3)", TENANT, SOURCE, acceptance)
    with pytest.raises(asyncpg.PostgresError, match="permission denied"):
        async with s4db.scoped(s4db.conn, "living_reader"):
            await s4db.conn.fetchrow(
                "SELECT * FROM living.s4_promote_v1($1,$2,$3)", TENANT, SOURCE, acceptance)
    assert tuple(await _counts(s4db.conn, acceptance)) == (0, 0, 0)


async def test_rollback_restores_previously_accepted_revision_at_new_version(s4db):
    first_revision = await s4db.seed_eligible()
    first_acceptance = await s4db.request(first_revision, expected=0)
    first = await s4db.promote(s4db.conn, first_acceptance)
    assert first["outcome"] == "COMMITTED" and first["to_version"] == 1

    next_revision = await s4db.seed_eligible()
    next_acceptance = await s4db.request(next_revision, expected=1)
    second = await s4db.promote(s4db.conn, next_acceptance)
    assert second["outcome"] == "COMMITTED" and second["to_version"] == 2

    rollback_acceptance = await s4db.request(
        first_revision, expected=2, operation="rollback", rollback_version=1)
    rollback = await s4db.promote(s4db.conn, rollback_acceptance)
    assert rollback["outcome"] == "COMMITTED" and rollback["to_version"] == 3
    head = await s4db.conn.fetchrow(
        "SELECT revision_id,version FROM living.accepted_heads WHERE tenant_id=$1"
        " AND source_id=$2 AND model_key=$3", TENANT, SOURCE, MODEL)
    assert tuple(head) == (first_revision.revision, 3)
