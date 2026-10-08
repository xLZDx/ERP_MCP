"""G1 guard-mutation proof: every critical guard must be load-bearing.

For each guard a NEW throwaway database is built from db/phase2/001-003 with the guard removed in
memory (text replacement of the SQL source, or DROP TRIGGER after apply; no db/phase2 file is ever
edited). The behaviour probe for that guard must report RED (guard missing -> the forbidden action
succeeds) on the mutant and GREEN (action refused with the guard's error) on an unmutated baseline
database. The (guard, mutant, baseline) table is printed and written as JSON (pytest base temp dir,
plus the path in ERP_PHASE2_MUTATION_TABLE when set).

Needs ERP_PHASE2_TEST_DSN; otherwise skip NOT_RUN (fail with ERP_PHASE2_REQUIRE_PG=1).
"""
import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field

import asyncpg
import pytest
from _pg_harness import (
    COMMIT,
    FUTURE,
    PROMOTE,
    attest,
    call,
    cursor_and_job,
    ingest,
    page,
    replace_once,
    require_dsn,
    scope,
    seed_direct,
    source_epoch,
    throwaway_db,
)

pytestmark = pytest.mark.integration

F001, F002, F003 = "001_living_registry.sql", "002_job_cursor_functions.sql", \
    "003_security_hardening.sql"
RESULTS: dict = {}
DROP_ALL_TRUNCATE_GUARDS = """
DO $m$ DECLARE r record; BEGIN
 FOR r IN SELECT tgname, tgrelid::regclass AS t FROM pg_trigger
          WHERE NOT tgisinternal AND tgname LIKE '%no_truncate' LOOP
  EXECUTE format('DROP TRIGGER %I ON %s', r.tgname, r.t);
 END LOOP; END $m$"""


async def refused(coro, needle):
    """(True, msg) when the call is refused with `needle`; (False, why) otherwise."""
    try:
        res = await coro
    except asyncpg.PostgresError as e:
        return (needle in str(e)), str(e).splitlines()[0]
    return False, f"EXECUTED (returned {res!r})"


async def probe_observation_immutable(db):
    c = db.conn
    await seed_direct(c, "A", "s1", "o1")
    out = [await refused(c.execute(s), "IMMUTABLE_LEDGER") for s in (
        "UPDATE living.observations SET object_id='x'", "DELETE FROM living.observations")]
    return all(o[0] for o in out), "; ".join(o[1] for o in out)


async def probe_outbox_truncate(db):
    return await refused(db.conn.execute("TRUNCATE living.outbox"), "IMMUTABLE_LEDGER")


async def probe_observations_truncate(db):
    c = db.conn
    await seed_direct(c, "A", "s1", "o1")
    return await refused(c.execute("TRUNCATE living.observations CASCADE"), "IMMUTABLE_LEDGER")


async def _two_fences(c):
    """Same worker w1 holds fence 1, loses the lease, re-acquires as fence 2 (owner check alone
    cannot tell the generations apart, only the fence can)."""
    j, f1 = await cursor_and_job(c)
    await c.execute("UPDATE living.jobs SET lease_until=clock_timestamp()-interval '1 second'")
    assert await call(c, "living_worker", "SELECT living.reap_expired_jobs('A','s1')") == 1
    await c.execute("UPDATE living.jobs SET next_run_at=clock_timestamp()-interval '1 second'")
    f2 = await call(c, "living_worker", "SELECT living.acquire_job('A','s1',$1,'w1',300)", j)
    assert (f1, f2) == (1, 2)
    return j, f1, await source_epoch(c)


async def probe_fence_commit(db):
    c = db.conn
    j, f1, ep = await _two_fences(c)
    return await refused(call(c, "living_worker", COMMIT, j, "w1", f1, "p0", 0, ep, "p1", "[]"),
                         "STALE_JOB_FENCE")


async def probe_fence_finish(db):
    c = db.conn
    j, f1, _ = await _two_fences(c)
    return await refused(call(
        c, "living_worker", "SELECT living.finish_job('A','s1',$1,'w1',$2,'SUCCEEDED')", j, f1),
        "STALE_JOB_FENCE")


async def probe_page_replay(db):
    c = db.conn
    j, f = await cursor_and_job(c)
    ep = await source_epoch(c)
    assert await call(c, "living_worker", COMMIT, j, "w1", f, "p0", 0, ep, "p1",
                      await page(c, "e1")) == 1
    return await refused(call(c, "living_worker", COMMIT, j, "w1", f, "p0", 0, ep, "p1",
                              await page(c, "e2")), "CONFLICTING_PAGE_REPLAY")


async def probe_recheck_scope(db):
    """A grant revoked (and committed) while the API waits for the source lock must be honoured."""
    c, b = db.conn, await db.connect()
    try:
        rev_tx = b.transaction()
        await rev_tx.start()
        await b.execute("DELETE FROM living.role_scope WHERE role_name='living_worker'"
                        " AND tenant_id='A' AND source_id='s1'")  # takes the source row lock

        async def api():
            async with c.transaction():
                await c.execute("SET LOCAL ROLE living_worker")
                await c.fetchval("SELECT living.set_scope('A','s1',NULL)")
                return await c.fetchval("SELECT living.create_cursor('A','s1','late','x')")

        task = asyncio.create_task(refused(api(), "SCOPE_"))
        await asyncio.sleep(1.0)
        assert not task.done(), "API must be waiting on the source lock"
        await rev_tx.commit()
        return await asyncio.wait_for(task, 20)
    finally:
        await b.close()


async def probe_outbox_generation(db):
    c = db.conn
    j, f = await cursor_and_job(c)
    ep = await source_epoch(c)
    await call(c, "living_worker", COMMIT, j, "w1", f, "p0", 0, ep, "p1", await page(c, "e1"))
    claim = "SELECT claim_generation FROM living.claim_outbox('A','s1',1,60,5)"

    async def claim_gen():
        async with scope(c, "living_publisher"):
            return (await c.fetchrow(claim))[0]
    g1 = await claim_gen()
    await c.execute("UPDATE living.outbox SET lease_until=clock_timestamp()-interval '1 second'")
    g2 = await claim_gen()
    assert (g1, g2) == (1, 2)
    return await refused(call(c, "living_publisher",
                              "SELECT living.finish_outbox('A','s1','conn','e1',$1,true,5)", g1),
                         "STALE_OUTBOX_LEASE")


async def probe_trusted_reviewer(db):
    c = db.conn
    rev = uuid.uuid4()
    await ingest(c, "o1", rev)
    await attest(c, rev)  # trusted at attestation time
    await call(c, "living_promoter", "SELECT living.create_head('A','s1','m1')")
    await c.fetchval("SELECT living.set_trusted_reviewer('living_worker','A','s1',false,$1)",
                     FUTURE)  # trust withdrawn before promotion
    return await refused(call(c, "living_promoter", PROMOTE, rev, uuid.uuid4()),
                         "REVIEWER_NOT_TRUSTED")


@dataclass
class Guard:
    name: str
    probe: object
    mutate: dict = field(default_factory=dict)
    post_sql: str = ""
    what: str = ""


GUARDS = [
    Guard("observations immutability trigger", probe_observation_immutable,
          post_sql="DROP TRIGGER observations_immutable ON living.observations",
          what="DROP TRIGGER observations_immutable"),
    Guard("outbox TRUNCATE guard", probe_outbox_truncate,
          post_sql="DROP TRIGGER outbox_no_truncate ON living.outbox",
          what="DROP TRIGGER outbox_no_truncate"),
    Guard("observations TRUNCATE guard (FK closure)", probe_observations_truncate,
          post_sql=DROP_ALL_TRUNCATE_GUARDS,
          what="drop every *no_truncate trigger (observations is protected by the whole FK closure)"),
    Guard("commit_cursor_page job fence", probe_fence_commit,
          mutate={F002: replace_once("OR j_fence IS DISTINCT FROM p_fence OR j_until IS NULL",
                                     "OR j_until IS NULL")},
          what="remove j_fence IS DISTINCT FROM p_fence"),
    Guard("finish_job fence", probe_fence_finish,
          mutate={F002: replace_once(
              " AND lease_owner=worker AND fence=token\n AND lease_until>clock_timestamp() "
              "AND scope_epoch=src_epoch;",
              " AND lease_owner=worker\n AND lease_until>clock_timestamp() "
              "AND scope_epoch=src_epoch;")},
          what="remove fence=token from the finish_job UPDATE"),
    Guard("living.recheck_scope_locked", probe_recheck_scope,
          mutate={F001: replace_once(
              "BEGIN\n PERFORM living.assert_scope(t,s);\nEND $fn$;\n\n-- Authenticated caller",
              "BEGIN\n NULL;\nEND $fn$;\n\n-- Authenticated caller")},
          what="recheck_scope_locked body replaced by NULL"),
    Guard("page-replay digest (CONFLICTING_PAGE_REPLAY)", probe_page_replay,
          mutate={F002: replace_once(
              "IF cur_digest IS DISTINCT FROM page_digest THEN RAISE EXCEPTION "
              "'CONFLICTING_PAGE_REPLAY'; END IF;", "NULL;")},
          what="digest comparison removed"),
    Guard("outbox claim_generation fence", probe_outbox_generation,
          mutate={F003: replace_once("OR ob.claim_generation IS DISTINCT FROM p_generation", "")},
          what="claim_generation comparison removed from finish_outbox"),
    Guard("trusted-reviewer check in promote_head", probe_trusted_reviewer,
          mutate={F003: replace_once(
              "IF NOT living.is_trusted_reviewer(t,s,obs) THEN RAISE EXCEPTION "
              "'REVIEWER_NOT_TRUSTED'; END IF;", "NULL;")},
          what="is_trusted_reviewer(t,s,obs) check removed"),
]


async def _run(dsn, guard, mutated):
    async with throwaway_db(dsn, mutate=guard.mutate if mutated else None) as db:
        if mutated and guard.post_sql:
            await db.conn.execute(guard.post_sql)
        held, detail = await guard.probe(db)
        return ("GREEN" if held else "RED"), detail


@pytest.mark.parametrize("guard", GUARDS, ids=[g.name for g in GUARDS])
async def test_guard_is_red_when_removed_and_green_on_baseline(guard):
    dsn = require_dsn()
    base, base_detail = await _run(dsn, guard, mutated=False)
    mut, mut_detail = await _run(dsn, guard, mutated=True)
    RESULTS[guard.name] = {"guard": guard.name, "mutation": guard.what, "mutant": mut,
                           "mutant_detail": mut_detail, "baseline": base,
                           "baseline_detail": base_detail}
    assert base == "GREEN", f"baseline must hold the guard: {base_detail}"
    assert mut == "RED", f"guard is not load-bearing, mutant still safe: {mut_detail}"


def test_zz_emit_mutation_table(tmp_path_factory, capsys):
    if set(RESULTS) != {g.name for g in GUARDS}:
        pytest.skip("not every guard test ran in this session")
    rows = [RESULTS[g.name] for g in GUARDS]
    lines = [f"{'guard':50} {'mutant':7} {'baseline':8}"] + [
        f"{r['guard']:50} {r['mutant']:7} {r['baseline']:8}" for r in rows]
    text = "\n".join(lines)
    with capsys.disabled():
        print("\nGUARD MUTATION TABLE\n" + text)
    out = tmp_path_factory.getbasetemp() / "guard_mutation_table.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    extra = os.environ.get("ERP_PHASE2_MUTATION_TABLE")
    if extra:
        with open(extra, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)
    assert all(r["mutant"] == "RED" and r["baseline"] == "GREEN" for r in rows)
