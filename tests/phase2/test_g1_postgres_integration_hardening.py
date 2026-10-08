"""G1 PostgreSQL hardening integration tests (N-1..N-11) for db/phase2/001-003.

NOT run by the static suite. Needs ERP_PHASE2_TEST_DSN (a role able to CREATE DATABASE and
CREATE ROLE). Each test creates a throwaway database, applies 001-003, and drops it afterwards.
Without the DSN: FAIL when ERP_PHASE2_REQUIRE_PG=1, otherwise skip with reason NOT_RUN.
Fixtures are local on purpose (this module is independent of test_g1_postgres_integration.py).
"""
import asyncio
import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

pytestmark = pytest.mark.integration

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "phase2"
FILES = ("001_living_registry.sql", "002_job_cursor_functions.sql", "003_security_hardening.sql")
D1, D2 = "1" * 64, "2" * 64
OBS_AT = datetime(2024, 1, 2, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


class Env:
    def __init__(self, dsn, dbname):
        self.dsn, self.dbname = dsn, dbname

    async def connect(self):
        return await asyncpg.connect(self.dsn, database=self.dbname)


async def apply_file(conn, name):
    raw = (MIGRATIONS / name).read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


@pytest.fixture
async def env():
    dsn = os.environ.get("ERP_PHASE2_TEST_DSN")
    if not dsn:
        if os.environ.get("ERP_PHASE2_REQUIRE_PG") == "1":
            pytest.fail("ERP_PHASE2_REQUIRE_PG=1 but ERP_PHASE2_TEST_DSN is not set")
        pytest.skip("NOT_RUN: ERP_PHASE2_TEST_DSN not set")
    name = "living_hd_" + uuid.uuid4().hex[:12]
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE DATABASE "{name}"')
    e = Env(dsn, name)
    conn = await e.connect()
    try:
        for f in FILES:
            await apply_file(conn, f)
        await conn.execute("""
          INSERT INTO living.tenants VALUES ('A');
          INSERT INTO living.sources(tenant_id,source_id) VALUES ('A','s1');
          INSERT INTO living.role_scope(role_name,tenant_id,source_id) VALUES
            ('living_worker','A','s1'),('living_promoter','A','s1');
        """)
        # M1: evidence is accepted only from an owner-managed trusted reviewer role.
        await conn.execute(
            "SELECT living.set_trusted_reviewer('living_worker','A','s1',true,$1)", FUTURE)
        e.conn = conn
        yield e
    finally:
        await conn.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@asynccontextmanager
async def scope(conn, role, t="A", s="s1"):
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {role}")
        await conn.fetchval("SELECT living.set_scope($1,$2,NULL)", t, s)
        yield


async def call(conn, role, sql, *args, t="A", s="s1"):
    async with scope(conn, role, t, s):
        return await conn.fetchval(sql, *args)


async def fails(needle, coro, exc=asyncpg.PostgresError):
    with pytest.raises(exc) as ei:
        await coro
    assert needle in str(ei.value), (needle, str(ei.value))
    return ei.value


def ev_digest(revision_digest, evidence):
    """Evidence digest bound to the exact revision content (see 003 record_attestation)."""
    return hashlib.sha256(f"{revision_digest}:{evidence}".encode()).hexdigest()


REC = "SELECT living.record_attestation('A','s1',$1,$2,$3,$4,$5,$6,$7)"


async def attest(conn, rev, proposer="prop", evidence="ev1", digest=D1, att=None, decision="APPROVE",
                 expires=FUTURE, role="living_worker", bound_to=None):
    return await call(conn, role, REC, att or uuid.uuid4(), rev, proposer, evidence,
                      ev_digest(bound_to or digest, evidence), decision, expires)


INGEST = ("SELECT living.ingest_observation('A','s1',$1::uuid,$2,$3::uuid,'OBSERVED',$4,"
          "$5::timestamptz,$6::timestamptz,$7::uuid,$8::jsonb)")


async def ingest(conn, obj, rev, digest=D1, eff=None, observed=OBS_AT, sup=None, prov="{}",
                 obs_id=None):
    obs_id = obs_id or uuid.uuid4()
    return await call(conn, "living_worker", INGEST, obs_id, obj, rev, digest, eff, observed,
                      sup, prov)


async def snapshot(conn):
    fn = await conn.fetch(
        "SELECT p.oid::regprocedure::text AS f, p.prosecdef, p.proconfig::text AS cfg,"
        " p.proowner::regrole::text AS o, p.proacl::text AS acl FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='living' ORDER BY 1")
    pol = await conn.fetch(
        "SELECT tablename,policyname,cmd,roles::text AS r,qual,with_check FROM pg_policies"
        " WHERE schemaname='living' ORDER BY 1,2")
    rel = await conn.fetch(
        "SELECT c.oid::regclass::text AS t, c.relowner::regrole::text AS o, c.relacl::text AS acl,"
        " c.relrowsecurity, c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n"
        " ON n.oid=c.relnamespace WHERE n.nspname='living' AND c.relkind='r' ORDER BY 1")
    mig = await conn.fetch("SELECT version,checksum FROM living.schema_migrations ORDER BY 1")
    trg = await conn.fetch(
        "SELECT tgrelid::regclass::text AS t, tgname, tgenabled, pg_get_triggerdef(oid) AS d"
        " FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text LIKE 'living.%'"
        " ORDER BY 1,2")
    col = await conn.fetch(
        "SELECT table_name,column_name,data_type,is_nullable,column_default FROM"
        " information_schema.columns WHERE table_schema='living' ORDER BY 1,ordinal_position")
    return [[tuple(r) for r in x] for x in (fn, pol, rel, mig, trg, col)]


# ---- N-1 / N-11 ----
async def test_n1_reapply_001_002_after_003_equals_single_pass(env):
    c = env.conn
    before = await snapshot(c)
    assert all(r[1] for r in before[0] if "set_scope" in r[0] or "promote_head" in r[0])
    for f in ("001_living_registry.sql", "002_job_cursor_functions.sql",
              "003_security_hardening.sql", "001_living_registry.sql",
              "002_job_cursor_functions.sql", "003_security_hardening.sql"):
        await apply_file(c, f)
    assert await snapshot(c) == before
    policies = {r[1] for r in before[1]}
    assert "tenant_scope" not in policies


async def test_n11_checksum_is_consumed_and_verified(env):
    c = env.conn
    assert (await c.fetchval("SELECT current_setting('living.migration_checksum', true)")) in ("", None)
    await fails("MIGRATION_CHECKSUM_REQUIRED",
                c.execute("SELECT living.record_migration('001', ARRAY[]::text[])"))
    await c.execute("SELECT set_config('living.migration_checksum',$1,false)", "f" * 64)
    await fails("MIGRATION_CHECKSUM_MISMATCH",
                c.execute("SELECT living.record_migration('001', ARRAY[]::text[])"))
    await c.execute("SELECT set_config('living.migration_checksum',$1,false)",
                    hashlib.sha256((MIGRATIONS / FILES[0]).read_bytes()).hexdigest())
    assert await c.fetchval("SELECT living.record_migration('001', ARRAY[]::text[])") is False
    assert (await c.fetchval("SELECT current_setting('living.migration_checksum', true)")) == ""


# ---- N-2 ----
async def test_n2_dual_duty_login_cannot_promote(env):
    c = env.conn
    dual = "dual_" + uuid.uuid4().hex[:8]
    await c.execute(f"CREATE ROLE {dual} LOGIN")
    try:
        await c.execute(f"GRANT living_worker, living_promoter TO {dual}")
        rev = uuid.uuid4()
        await ingest(c, "o1", rev)
        await attest(c, rev)
        await call(c, "living_promoter", "SELECT living.create_head('A','s1','m1')")
        promote = "SELECT living.promote_head('A','s1','m1',0,$1,$2,'ev1')"
        async with c.transaction():
            await c.execute(f"SET LOCAL SESSION AUTHORIZATION {dual}")
            await c.execute("SET LOCAL ROLE living_promoter")
            await c.fetchval("SELECT living.set_scope('A','s1',NULL)")
            await fails("APPROVER_NOT_INDEPENDENT", c.fetchval(promote, rev, uuid.uuid4()))
        # positive control: a pure promoter identity still succeeds
        assert await call(c, "living_promoter", promote, rev, uuid.uuid4()) == 1
    finally:
        await c.execute(f"DROP ROLE IF EXISTS {dual}")


# ---- N-3 ----
async def test_n3_ingest_seq_recorded_at_and_commit_order_agree(env):
    a, b = env.conn, await env.connect()
    try:
        r1, r2 = uuid.uuid4(), uuid.uuid4()
        tx = a.transaction()
        await tx.start()
        await a.execute("SET LOCAL ROLE living_worker")
        await a.fetchval("SELECT living.set_scope('A','s1',NULL)")
        await a.fetchval(INGEST, uuid.uuid4(), "o1", r1, D1, None, OBS_AT, None, "{}")
        task = asyncio.create_task(ingest(b, "o2", r2))
        await asyncio.sleep(0.5)
        assert not task.done(), "second ingest must wait for the per-source ingest lock"
        await tx.commit()
        await asyncio.wait_for(task, 15)
        rows = await a.fetch("SELECT revision_id,recorded_at FROM living.observations"
                             " ORDER BY ingest_seq")
        assert [r["revision_id"] for r in rows] == [r1, r2]
        assert rows[0]["recorded_at"] <= rows[1]["recorded_at"]
    finally:
        await b.close()


# ---- N-4 ----
async def test_n4_rebase_scope_and_no_replay_from_older_epoch(env):
    c = env.conn
    enq = "SELECT living.enqueue_job('A','s1',$1,'k',$2,'idem-1','{}'::jsonb)"
    jid = uuid.uuid4()
    assert await call(c, "living_worker", enq, jid, D1) == jid
    await call(c, "living_worker", "SELECT living.create_cursor('A','s1','conn','c0')")
    await c.execute("UPDATE living.sources SET status='SUSPENDED' WHERE source_id='s1'")
    await c.execute("UPDATE living.sources SET status='ACTIVE' WHERE source_id='s1'")
    await fails("SCOPE_REVOKED", call(c, "living_worker", enq, uuid.uuid4(), D1))
    await fails("permission denied", call(c, "living_worker", "SELECT living.rebase_scope('A','s1')"))
    assert await c.fetchval("SELECT living.rebase_scope('A','s1')") >= 2
    assert await call(c, "living_worker", enq, uuid.uuid4(), D1) == jid
    assert await c.fetchval("SELECT scope_epoch FROM living.cursors") == \
        await c.fetchval("SELECT scope_epoch FROM living.sources")


# ---- N-5 ----
async def test_n5_second_acquire_is_job_unavailable_not_unique_violation(env):
    c = env.conn
    j1, j2 = uuid.uuid4(), uuid.uuid4()
    for j, k in ((j1, "k1"), (j2, "k2")):
        await call(c, "living_worker", "SELECT living.enqueue_job('A','s1',$1,'k',$2,$3,'{}'::jsonb)",
                   j, D1, k)
    acq = "SELECT living.acquire_job('A','s1',$1,'w1',60)"
    assert await call(c, "living_worker", acq, j1) == 1
    err = await fails("JOB_UNAVAILABLE", call(c, "living_worker", acq, j2))
    assert not isinstance(err, asyncpg.UniqueViolationError)


# ---- N-6 ----
async def test_n6_add_role_scope_validates_role_and_blocks_direct_dml(env):
    c = env.conn
    await fails("ROLE_NOT_FOUND", c.fetchval("SELECT living.add_role_scope('no_such_role_x','A','s1')"))
    await fails("permission denied", call(c, "living_worker",
                                          "SELECT living.add_role_scope('living_reader','A','s1')"))
    await fails("permission denied", call(c, "living_worker",
                "INSERT INTO living.role_scope(role_name,tenant_id,source_id)"
                " VALUES('living_worker','A','s1')"))
    await c.fetchval("SELECT living.add_role_scope('living_reader','A','s1')")
    assert await c.fetchval("SELECT count(*) FROM living.role_scope WHERE role_name='living_reader'") == 1


# ---- N-7 ----
async def test_n7_retry_and_replay_compare_all_columns(env):
    c = env.conn
    rev, oid = uuid.uuid4(), uuid.uuid4()
    assert await ingest(c, "o1", rev, obs_id=oid) == oid
    assert await ingest(c, "o1", rev) == oid  # identical retry
    eff = datetime(2024, 1, 1, tzinfo=UTC)
    await fails("CONFLICTING_OBSERVATION", ingest(c, "o1", rev, eff=eff))
    await fails("CONFLICTING_OBSERVATION", ingest(c, "o1", rev, prov='{"x":1}'))
    att = uuid.uuid4()
    await attest(c, rev, "prop", att=att)
    await attest(c, rev, "prop", att=att)  # identical replay
    await fails("CONFLICTING_ATTESTATION", attest(c, rev, "other", att=att))
    await fails("CONFLICTING_ATTESTATION", attest(c, rev, "prop"))  # new id, same revision+evidence
    await call(c, "living_promoter", "SELECT living.create_head('A','s1','m1')")
    promote = "SELECT living.promote_head('A','s1','m1',0,$1,$2,'ev1')"
    acc = uuid.uuid4()
    assert await call(c, "living_promoter", promote, rev, acc) == 1
    assert await call(c, "living_promoter", promote, rev, acc) == 1  # replay, no new version
    assert await c.fetchval("SELECT count(*) FROM living.acceptance_events") == 1
    await fails("ACCEPTANCE_ID_REUSED", call(
        c, "living_promoter", "SELECT living.promote_head('A','s1','m1',5,$1,$2,'ev1')", rev, acc))


# ---- N-8 ----
async def _seed_outbox(c, n):
    await call(c, "living_worker", "SELECT living.create_cursor('A','s1','conn','c0')")
    for i in range(n):
        await c.execute(
            "INSERT INTO living.outbox(tenant_id,source_id,connection_id,event_id,event_digest,content)"
            " VALUES('A','s1','conn',$1,$2,'{}'::jsonb)", f"e{i}", D2)


async def test_n8_outbox_claim_finish_lease_attempts_and_skip_locked(env):
    c = env.conn
    await c.fetchval("SELECT living.add_role_scope('living_publisher','A','s1')")
    await _seed_outbox(c, 3)
    claim = "SELECT event_id,attempts,claim_generation FROM living.claim_outbox('A','s1',$1,60,$2)"
    fin = "SELECT living.finish_outbox('A','s1','conn',$1,$2,$3,$4)"

    async def claim_rows(conn, limit, mx=5):
        async with scope(conn, "living_publisher"):
            return await conn.fetch(claim, limit, mx)

    first = await claim_rows(c, 2)
    assert [r["event_id"] for r in first] == ["e0", "e1"] and all(r["attempts"] == 1 for r in first)
    assert all(r["claim_generation"] == 1 for r in first)
    assert [r["event_id"] for r in await claim_rows(c, 5)] == ["e2"]  # leased rows skipped
    await call(c, "living_publisher", fin, "e0", 1, True, 5)
    assert await c.fetchval("SELECT status FROM living.outbox WHERE event_id='e0'") == "DELIVERED"
    await fails("OUTBOX_INVALID_TRANSITION", call(c, "living_publisher", fin, "e0", 1, True, 5))
    await fails("STALE_OUTBOX_LEASE", call(c, "living_publisher", fin, "e1", 7, True, 5))  # wrong fence
    await call(c, "living_publisher", fin, "e1", 1, False, 1)  # attempts(1) >= cap(1)
    assert await c.fetchval("SELECT status FROM living.outbox WHERE event_id='e1'") == "FAILED"
    await fails("permission denied", call(c, "living_worker", "SELECT * FROM living.claim_outbox("
                                          "'A','s1',1,60,5)"))
    await fails("OUTBOX_INVALID_TRANSITION", c.execute(
        "UPDATE living.outbox SET status='PENDING' WHERE event_id='e0'"))


async def test_n8_concurrent_claims_do_not_overlap(env):
    c = env.conn
    await c.fetchval("SELECT living.add_role_scope('living_publisher','A','s1')")
    await _seed_outbox(c, 2)
    b = await env.connect()
    claim = "SELECT event_id FROM living.claim_outbox('A','s1',1,60,5)"
    try:
        ta, tb = c.transaction(), b.transaction()
        await ta.start()
        await tb.start()
        got = []
        for conn, tx in ((c, ta), (b, tb)):
            await conn.execute("SET LOCAL ROLE living_publisher")
            await conn.fetchval("SELECT living.set_scope('A','s1',NULL)")
            got.append([r["event_id"] for r in await asyncio.wait_for(conn.fetch(claim), 10)])
        await ta.commit()
        await tb.commit()
        assert sorted(got[0] + got[1]) == ["e0", "e1"], got
    finally:
        await b.close()
