"""G1 PostgreSQL integration tests for db/phase2/001-003 (NOT run by the static suite).

Reads ERP_PHASE2_TEST_DSN (a role able to CREATE DATABASE and CREATE ROLE). Each test creates
a throwaway database, applies 001-003 in order, and drops the database afterwards. The four
cluster-global living_* roles are created by 003 and intentionally left in place.

Without the DSN: FAIL when ERP_PHASE2_REQUIRE_PG=1, otherwise skip with reason NOT_RUN.
Runtime roles are exercised with SET LOCAL ROLE; set_scope() is the only way to enter a scope.
"""
import asyncio
import hashlib
import json
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
D1, D2, DA, DB = "1" * 64, "2" * 64, "a" * 64, "b" * 64


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


class Env:
    def __init__(self, dsn, dbname):
        self.dsn, self.dbname = dsn, dbname

    async def connect(self):
        return await asyncpg.connect(self.dsn, database=self.dbname)


async def _apply_all(conn):
    for name in FILES:
        raw = (MIGRATIONS / name).read_bytes()
        await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                           hashlib.sha256(raw).hexdigest())
        await conn.execute(raw.decode("utf-8"))


@pytest.fixture
async def env():
    dsn = os.environ.get("ERP_PHASE2_TEST_DSN")
    if not dsn:
        if os.environ.get("ERP_PHASE2_REQUIRE_PG") == "1":
            pytest.fail("ERP_PHASE2_REQUIRE_PG=1 but ERP_PHASE2_TEST_DSN is not set: "
                        "G1 PostgreSQL integration cannot be skipped in this run")
        pytest.skip("NOT_RUN: ERP_PHASE2_TEST_DSN not set")
    name = "living_it_" + uuid.uuid4().hex[:12]
    admin = None
    conn = None
    created = False
    try:
        admin = await asyncpg.connect(dsn)
        await admin.execute(f'CREATE DATABASE "{name}"')
        created = True
        e = Env(dsn, name)
        conn = await e.connect()
        await _apply_all(conn)
        await conn.execute("""
          INSERT INTO living.tenants VALUES ('A'),('B');
          INSERT INTO living.sources(tenant_id,source_id,company_id) VALUES
            ('A','s1',NULL),('A','s3',NULL),('B','s1',NULL),('A','s4','c1'),('A','s5','c2');
          INSERT INTO living.role_scope(role_name,tenant_id,source_id,company_id) VALUES
            ('living_worker','A','s1',NULL),('living_reader','A','s1',NULL),
            ('living_promoter','A','s1',NULL),('living_reader','A','s4','c1');
        """)
        e.conn = conn
        yield e
    finally:
        if conn is not None:
            await conn.close()
        if admin is not None:
            try:
                if created:
                    await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            finally:
                await admin.close()


@asynccontextmanager
async def scope(conn, role, t="A", s="s1", company=None):
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {role}")
        await conn.fetchval("SELECT living.set_scope($1,$2,$3)", t, s, company)
        yield


async def ingest(conn, obj, rev, kind="OBSERVED", digest=None, eff=None, supersedes=None,
                 t="A", s="s1", obs_id=None):
    obs_id = obs_id or uuid.uuid4()
    async with scope(conn, "living_worker", t, s):
        # the function returns the stored observation id (the existing one on an idempotent retry)
        return await conn.fetchval(
            "SELECT living.ingest_observation($1,$2,$3::uuid,$4,$5::uuid,$6,$7,$8::timestamptz,"
            "$9::timestamptz,$10::uuid,'{}'::jsonb)",
            t, s, obs_id, obj, rev, kind, digest, eff, _dt(2024, 1, 2), supersedes)


async def seed_direct(conn, t, s, obj):
    await conn.execute(
        "INSERT INTO living.observations(tenant_id,source_id,observation_id,object_id,"
        "revision_id,kind,digest,observed_at) VALUES($1,$2,$3,$4,$5,'OBSERVED',$6,"
        "'2024-01-01Z')", t, s, uuid.uuid4(), obj, uuid.uuid4(), D1)


async def raises(coro, *needles, exc=asyncpg.PostgresError):
    with pytest.raises(exc) as ei:
        await coro
    for n in needles:
        assert n in str(ei.value), (n, str(ei.value))


async def test_runtime_roles_cannot_update_delete_truncate_or_insert(env):
    c = env.conn
    await seed_direct(c, "A", "s1", "o1")
    for role in ("living_worker", "living_reader", "living_promoter"):
        for stmt in ("UPDATE living.observations SET object_id='x'",
                     "DELETE FROM living.observations",
                     "TRUNCATE living.observations",
                     "UPDATE living.accepted_heads SET version=99",
                     "DELETE FROM living.outbox", "TRUNCATE living.outbox",
                     "INSERT INTO living.tenants VALUES ('Z')"):
            async with scope(c, role):
                await raises(c.execute(stmt), exc=asyncpg.InsufficientPrivilegeError)
    # even the privileged applier cannot rewrite or truncate the ledger
    await raises(c.execute("UPDATE living.observations SET object_id='x'"), "IMMUTABLE_LEDGER")
    # plain TRUNCATE is stopped earlier by the foreign key from accepted_heads; CASCADE reaches the guard
    await raises(c.execute("TRUNCATE living.observations CASCADE"), "IMMUTABLE_LEDGER")


async def test_cross_tenant_source_company_reads_empty_and_provenance_hidden(env):
    c = env.conn
    for t, s in (("A", "s1"), ("A", "s3"), ("B", "s1"), ("A", "s4")):
        await seed_direct(c, t, s, f"obj-{t}-{s}")
    async with scope(c, "living_reader"):
        rows = await c.fetch("SELECT tenant_id,source_id FROM living.observations")
        assert {(r[0], r[1]) for r in rows} == {("A", "s1")}
        assert await c.fetchval("SELECT count(*) FROM living.tenants") == 1
        await raises(c.fetch("SELECT provenance FROM living.observations"),
                     exc=asyncpg.InsufficientPrivilegeError)
    for t, s, co in (("B", "s1", None), ("A", "s3", None), ("A", "s5", "c2"),
                     ("A", "s4", "c2"), ("A", "s4", None)):
        async with c.transaction():
            await c.execute("SET LOCAL ROLE living_reader")
            await raises(c.fetchval("SELECT living.set_scope($1,$2,$3)", t, s, co),
                         "SCOPE_NOT_GRANTED")
    async with scope(c, "living_reader", "A", "s4", "c1"):
        assert await c.fetchval("SELECT count(*) FROM living.observations") == 1


async def test_guc_spoof_returns_nothing(env):
    c = env.conn
    for t, s, o in (("A", "s1", "o-ok"), ("A", "s3", "o-s3"), ("B", "s1", "o-b")):
        await seed_direct(c, t, s, o)
    for t, s in (("B", "s1"), ("A", "s3")):
        async with c.transaction():
            await c.execute("SET LOCAL ROLE living_reader")
            await c.execute("SELECT set_config('living.tenant_id',$1,true),"
                            "set_config('living.source_id',$2,true)", t, s)
            assert await c.fetchval("SELECT count(*) FROM living.observations") == 0
            assert await c.fetchval("SELECT count(*) FROM living.sources") == 0
            # the spoofed tenant is never visible; only the role's own granted tenant A may be
            seen = {r[0] for r in await c.fetch("SELECT tenant_id FROM living.tenants")}
            assert seen <= {"A"} and t not in (seen - {"A"})
    async with c.transaction():  # spoof without set_scope: mutating APIs refuse too
        await c.execute("SET LOCAL ROLE living_worker")
        await c.execute("SELECT set_config('living.tenant_id','B',true),"
                        "set_config('living.source_id','s1',true)")
        await raises(c.fetchval("SELECT living.create_cursor('B','s1','c','x')"),
                     "SCOPE_NOT_GRANTED")


async def test_backdated_recorded_at_is_overwritten(env):
    c = env.conn
    await c.execute(
        "INSERT INTO living.observations(tenant_id,source_id,observation_id,object_id,"
        "revision_id,kind,digest,observed_at,recorded_at) VALUES('A','s1',$1,'o',$2,"
        "'OBSERVED',$3,'1999-01-01Z','2000-01-01Z')", uuid.uuid4(), uuid.uuid4(), D1)
    age = await c.fetchval("SELECT clock_timestamp()-recorded_at FROM living.observations")
    assert age.total_seconds() < 60


async def _job(c, key="k1"):
    j = uuid.uuid4()
    async with scope(c, "living_worker"):
        await c.fetchval("SELECT living.enqueue_job('A','s1',$1,'sync',$2,$3,'{}'::jsonb)",
                         j, "c" * 64, key)
    return j


async def _acquire(c, j, worker, secs=1):
    async with scope(c, "living_worker"):
        return await c.fetchval("SELECT living.acquire_job('A','s1',$1,$2,$3)", j, worker, secs)


COMMIT = ("SELECT living.commit_cursor_page('A','s1','conn',$1,$2,$3,$4,$5,$6,$7,$8::jsonb)")


async def test_stale_fence_rejected(env):
    c = env.conn
    async with scope(c, "living_worker"):
        await c.fetchval("SELECT living.create_cursor('A','s1','conn','p0')")
    j = await _job(c)
    f1 = await _acquire(c, j, "w1")
    assert f1 == 1
    await c.execute("UPDATE living.jobs SET lease_until=clock_timestamp()-interval '1 second'")
    async with scope(c, "living_worker"):  # reap puts the job back to PENDING with backoff
        assert await c.fetchval("SELECT living.reap_expired_jobs('A','s1')") == 1
    # skip the 2**attempt seconds backoff deterministically instead of sleeping
    await c.execute("UPDATE living.jobs SET next_run_at=clock_timestamp()-interval '1 second'")
    f2 = await _acquire(c, j, "w2", 60)
    assert f2 == 2
    async with scope(c, "living_worker"):
        await raises(c.fetchval(COMMIT, j, "w1", f1, "p0", 0, 0, "p1", "[]"), "STALE_JOB_FENCE")
    async with scope(c, "living_worker"):
        await raises(c.fetchval("SELECT living.finish_job('A','s1',$1,'w1',$2,'SUCCEEDED')",
                                j, f1), "STALE_JOB_FENCE")
    async with scope(c, "living_worker"):
        assert await c.fetchval(COMMIT, j, "w2", f2, "p0", 0, 0, "p1", "[]") == 1


async def test_null_page_events_rejected_cursor_unchanged(env):
    c = env.conn
    async with scope(c, "living_worker"):
        await c.fetchval("SELECT living.create_cursor('A','s1','conn','p0')")
    j = await _job(c)
    f = await _acquire(c, j, "w1", 60)
    async with scope(c, "living_worker"):
        await raises(c.fetchval(COMMIT, j, "w1", f, "p0", 0, 0, "p1", None),
                     "INVALID_CURSOR_BATCH")
    assert await c.fetchrow("SELECT cursor_value,version FROM living.cursors") == ("p0", 0)
    base = {"event_id": "e1", "n": 1}
    digest = await c.fetchval("SELECT encode(sha256(convert_to($1::jsonb::text,'UTF8')),'hex')",
                              '{"event_id": "e1", "n": 1}')
    good = json.dumps({**base, "digest": digest})
    bad = json.dumps({**base, "digest": "f" * 64})
    async with scope(c, "living_worker"):
        await raises(c.fetchval(COMMIT, j, "w1", f, "p0", 0, 0, "p1", f"[{bad}]"),
                     "INVALID_OUTBOX_EVENT")
    assert await c.fetchval("SELECT version FROM living.cursors") == 0
    async with scope(c, "living_worker"):
        assert await c.fetchval(COMMIT, j, "w1", f, "p0", 0, 0, "p1", f"[{good}]") == 1
    async with scope(c, "living_worker"):  # replay is an idempotent no-op
        assert await c.fetchval(COMMIT, j, "w1", f, "p0", 0, 0, "p1", f"[{good}]") == 1
    assert await c.fetchval("SELECT count(*) FROM living.outbox") == 1
    await c.execute("UPDATE living.sources SET status='REVOKED' WHERE source_id='s1'"
                    " AND tenant_id='A'")
    async with c.transaction():  # set_scope itself refuses a revoked source; set GUCs by hand
        await c.execute("SET LOCAL ROLE living_worker")
        await c.execute("SELECT set_config('living.tenant_id','A',true),"
                        "set_config('living.source_id','s1',true)")
        await raises(c.fetchval(COMMIT, j, "w1", f, "p1", 1, 0, "p2", "[]"),
                     "SCOPE_REVOKED")


async def test_duplicate_digest_conflict(env):
    c = env.conn
    rev = uuid.uuid4()
    first = await ingest(c, "o1", rev, digest=DA, eff=_dt(2024, 1, 1))
    again = await ingest(c, "o1", rev, digest=DA, eff=_dt(2024, 1, 1))
    assert first == again
    with pytest.raises(asyncpg.PostgresError) as ei:
        await ingest(c, "o1", rev, digest=DB, eff=_dt(2024, 1, 1))
    assert "CONFLICTING_DIGEST" in str(ei.value)
    assert await c.fetchval("SELECT count(*) FROM living.observations") == 1


async def test_two_session_concurrent_promote_has_one_winner(env):
    c = env.conn
    rev = uuid.uuid4()
    await ingest(c, "o1", rev, digest=DA, eff=_dt(2024, 1, 1))
    async with scope(c, "living_promoter"):
        await c.fetchval("SELECT living.create_head('A','s1','m')")
    import hashlib
    far = _dt(2099, 1, 1)
    # M1: evidence counts only from an owner-managed trusted reviewer and is bound to the revision digest
    await c.execute("SELECT living.set_trusted_reviewer('living_worker','A','s1',true,$1)", far)
    async with scope(c, "living_worker"):
        await c.fetchval("SELECT living.record_attestation('A','s1',$1,$2,'proposer-x','ev1',$3,"
                         "'APPROVE',$4)", uuid.uuid4(), rev,
                         hashlib.sha256(f"{DA}:ev1".encode()).hexdigest(), far)
    # the worker cannot promote at all
    async with scope(c, "living_worker"):
        await raises(c.fetchval("SELECT living.promote_head('A','s1','m',0,$1,$2,'ev1')",
                                rev, uuid.uuid4()), exc=asyncpg.InsufficientPrivilegeError)
    started = asyncio.Event()

    async def session(first):
        conn = await env.connect()
        try:
            if not first:
                await started.wait()
            tx = conn.transaction()
            await tx.start()
            try:
                await conn.execute("SET LOCAL ROLE living_promoter")
                await conn.fetchval("SELECT living.set_scope('A','s1',NULL)")
                v = await conn.fetchval("SELECT living.promote_head('A','s1','m',0,$1,$2,'ev1')",
                                        rev, uuid.uuid4())
                if first:
                    started.set()
                    await asyncio.sleep(1.5)  # hold the row lock so the second session blocks
                await tx.commit()
                return v
            except BaseException:
                await tx.rollback()
                raise
        finally:
            await conn.close()

    results = await asyncio.gather(session(True), session(False), return_exceptions=True)
    wins = [r for r in results if r == 1]
    errs = [r for r in results if isinstance(r, Exception)]
    assert len(wins) == 1 and len(errs) == 1, results
    assert "STALE_ACCEPTED_HEAD" in str(errs[0])
    assert await c.fetchval("SELECT version FROM living.accepted_heads") == 1
    assert await c.fetchval("SELECT count(*) FROM living.acceptance_events") == 1


async def test_promote_requires_independent_approver_and_blocks_direct_head_change(env):
    c = env.conn
    rev = uuid.uuid4()
    await ingest(c, "o1", rev, digest=DA, eff=_dt(2024, 1, 1))
    async with scope(c, "living_promoter"):
        await c.fetchval("SELECT living.create_head('A','s1','m')")
    # a caught error aborts its transaction, so the failing call gets its own scope
    async with scope(c, "living_promoter"):
        await raises(c.fetchval("SELECT living.promote_head('A','s1','m',0,$1,$2,'nope')",
                                rev, uuid.uuid4()), "EVIDENCE_NOT_FOUND")
    # attestation whose observer is the approver itself
    await c.execute("INSERT INTO living.attestations(tenant_id,source_id,attestation_id,"
                    "revision_id,proposer_subject,observer_subject,evidence_ref) VALUES"
                    "('A','s1',$1,$2,'someone','living_promoter','ev-self')", uuid.uuid4(), rev)
    async with scope(c, "living_promoter"):
        await raises(c.fetchval("SELECT living.promote_head('A','s1','m',0,$1,$2,'ev-self')",
                                rev, uuid.uuid4()), "APPROVER_NOT_INDEPENDENT")
    await raises(c.execute("UPDATE living.accepted_heads SET version=5, revision_id=NULL"),
                 "HEAD_CHANGE_FORBIDDEN")


async def test_bitemporal_golden_dataset(env):
    c = env.conn
    E1 = _dt(2024, 1, 1)
    r1, r2, r3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    o1 = await ingest(c, "o1", r1, digest=D1, eff=E1)
    k1 = await c.fetchval("SELECT clock_timestamp()")
    await ingest(c, "o1", r2, digest=D2, eff=E1, supersedes=o1)  # late correction
    k2 = await c.fetchval("SELECT clock_timestamp()")
    await ingest(c, "o1", r3, kind="GAP")  # GAP after OBSERVED
    k3 = await c.fetchval("SELECT clock_timestamp()")
    await ingest(c, "o2", uuid.uuid4(), digest=D1, eff=None)  # NULL effective
    for obj, dig, eff in (("o3", DA, _dt(2024, 1, 1)), ("o3", DB, _dt(2024, 2, 1)),
                          ("o3", DA, _dt(2024, 3, 1))):  # A -> B -> A
        await ingest(c, obj, uuid.uuid4(), digest=dig, eff=eff)
    k4 = await c.fetchval("SELECT clock_timestamp()")

    async def known(k):
        async with scope(c, "living_reader"):
            return {r["object_id"]: r for r in await c.fetch(
                "SELECT * FROM living.as_known_at('A','s1',$1)", k)}

    async def eff(v, k):
        async with scope(c, "living_reader"):
            return await c.fetch("SELECT * FROM living.as_effective_at('A','s1',$1,$2)", v, k)

    assert (await known(k1))["o1"]["digest"] == D1
    assert (await known(k2))["o1"]["digest"] == D2  # correction visible only after its record time
    kg = (await known(k3))["o1"]
    assert kg["digest"] == D2 and kg["available"] is False and kg["latest_kind"] == "GAP"
    assert (await known(k2))["o1"]["available"] is True
    assert [r["digest"] for r in await eff(E1, k1) if r["object_id"] == "o1"] == [D1]
    assert [r["digest"] for r in await eff(E1, k2) if r["object_id"] == "o1"] == [D2]
    nulls = [r for r in await eff(_dt(2030, 1, 1), k4) if r["object_id"] == "o2"]
    assert len(nulls) == 1 and nulls[0]["effective_unknown"] is True
    for v, want in ((_dt(2024, 1, 15), DA), (_dt(2024, 2, 15), DB), (_dt(2024, 3, 15), DA)):
        got = [r for r in await eff(v, k4) if r["object_id"] == "o3"]
        assert [r["digest"] for r in got] == [want]
    # revocation applies in every effective slice, regardless of source_effective_at
    await ingest(c, "o1", uuid.uuid4(), kind="ATTESTATION_REVOKED")
    k5 = await c.fetchval("SELECT clock_timestamp()")
    assert (await known(k5))["o1"]["revoked"] is True
    assert all(r["revoked"] for r in await eff(E1, k5) if r["object_id"] == "o1")
