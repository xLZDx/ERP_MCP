# ruff: noqa: C408
"""G1 multi-process concurrency tests (S4b E4): REAL OS processes against the disposable PostgreSQL.

Needs ERP_PHASE2_TEST_DSN. Without it: skip NOT_RUN, or fail when ERP_PHASE2_REQUIRE_PG=1.

Each scenario prepares a throwaway database in the parent, then starts child Python processes that
connect to it (the DSN reaches them only through the environment). Children connect, print READY and
block on stdin; the parent releases all of them with one write each (a start barrier, no sleeps).
Only lease expiry uses a short real lease with a bounded polling wait.
"""
import asyncio
import json
import os
import sys
import uuid

import pytest
from _pg_harness import call, cursor_and_job, page, require_dsn, source_epoch, throwaway_db

pytestmark = pytest.mark.integration

CHILD = r'''
import asyncio, json, os, sys, time
import asyncpg

async def main():
    a = json.loads(sys.argv[1])
    c = await asyncpg.connect(os.environ["ERP_PHASE2_TEST_DSN"], database=a["db"], timeout=30)

    async def scoped(sql, *args):
        async with c.transaction():
            await c.execute("SET LOCAL ROLE living_worker")
            await c.fetchval("SELECT living.set_scope('A','s1',NULL)")
            return await c.fetchval(sql, *args)

    async def attempt(sql, *args):
        try:
            return {"ok": await scoped(sql, *args)}
        except asyncpg.PostgresError as e:
            return {"err": str(e).splitlines()[0]}

    print("READY", flush=True)
    sys.stdin.readline()
    op = a["op"]
    if op in ("acquire", "acquire_hold"):
        out = await attempt("SELECT living.acquire_job('A','s1',$1::uuid,$2,$3)",
                            a["job"], a["worker"], a["lease"])
    elif op == "reap_acquire":
        deadline = time.monotonic() + a["deadline"]
        reaped = 0
        out = {"err": "TIMEOUT"}
        while time.monotonic() < deadline:
            r = await attempt("SELECT living.reap_expired_jobs('A','s1')")
            reaped += r.get("ok") or 0
            out = await attempt("SELECT living.acquire_job('A','s1',$1::uuid,$2,$3)",
                                a["job"], a["worker"], a["lease"])
            if "ok" in out:
                break
            await asyncio.sleep(0.25)
        out["reaped"] = reaped
    elif op == "commit":
        out = await attempt(
            "SELECT living.commit_cursor_page('A','s1','conn',$1::uuid,$2,$3,$4,$5,$6,$7,$8::jsonb)",
            a["job"], a["worker"], a["fence"], a["prior"], a["version"], a["epoch"], a["new"],
            a["events"])
    else:
        out = {"err": "BAD_OP"}
    print("RESULT " + json.dumps(out), flush=True)
    if op == "acquire_hold":
        sys.stdin.readline()  # hold the lease (and the process) until the parent kills us

asyncio.run(main())
'''


class Child:
    def __init__(self, proc):
        self.proc = proc

    @classmethod
    async def start(cls, dsn, **args):
        env = dict(os.environ, ERP_PHASE2_TEST_DSN=dsn)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", CHILD, json.dumps(args, default=str), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        child = cls(proc)
        line = await asyncio.wait_for(proc.stdout.readline(), 90)
        assert line.strip() == b"READY", (line, await _stderr(proc))
        return child

    async def go(self):
        self.proc.stdin.write(b"GO\n")
        await self.proc.stdin.drain()

    async def result(self, timeout=90):
        line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        assert line.startswith(b"RESULT "), (line, await _stderr(self.proc))
        return json.loads(line[7:])


async def _stderr(proc):
    if proc.returncode is None:
        return b"<running>"
    return (await proc.stderr.read())[-800:]


async def _start_all(dsn, specs):
    return list(await asyncio.gather(*(Child.start(dsn, **s) for s in specs)))


async def _release_all(children):
    for ch in children:  # all released back to back; every child is already connected and waiting
        await ch.go()
    return await asyncio.gather(*(ch.result() for ch in children))


async def _reap_children(children):
    for ch in children:
        if ch.proc.returncode is None:
            ch.proc.kill()
    await asyncio.gather(*(ch.proc.wait() for ch in children))


async def _enqueue(c, key="k1"):
    await call(c, "living_worker", "SELECT living.create_cursor('A','s1','conn','p0')")
    j = uuid.uuid4()
    await call(c, "living_worker",
               "SELECT living.enqueue_job('A','s1',$1,'sync',$2,$3,'{}'::jsonb)", j, "c" * 64, key)
    return j


async def test_six_processes_acquire_same_job_exactly_one_wins():
    dsn = require_dsn()
    async with throwaway_db(dsn) as db:
        j = await _enqueue(db.conn)
        children = await _start_all(dsn, [dict(db=db.name, op="acquire", job=str(j), worker=f"w{i}",
                                               lease=60) for i in range(6)])
        try:
            results = await _release_all(children)
        finally:
            await _reap_children(children)
        winners = [r for r in results if "ok" in r]
        losers = [r for r in results if "err" in r]
        assert len(winners) == 1 and winners[0]["ok"] == 1, results
        assert len(losers) == 5 and all(r["err"] == "JOB_UNAVAILABLE" for r in losers), results
        row = await db.conn.fetchrow("SELECT state,fence,attempt,lease_owner FROM living.jobs "
                                     "WHERE job_id=$1", j)
        assert (row["state"], row["fence"], row["attempt"]) == ("RUNNING", 1, 1)
        assert row["lease_owner"] in {f"w{i}" for i in range(6)}


async def test_killed_lease_holder_is_reaped_and_its_old_fence_is_dead():
    dsn = require_dsn()
    async with throwaway_db(dsn) as db:
        c = db.conn
        j = await _enqueue(c)
        ep = await source_epoch(c)
        (dead,) = await _start_all(dsn, [dict(db=db.name, op="acquire_hold", job=str(j),
                                              worker="w-dead", lease=1)])
        live = None
        try:
            await dead.go()
            first = await dead.result()
            assert first == {"ok": 1}, first
            assert await c.fetchval("SELECT lease_owner FROM living.jobs WHERE job_id=$1", j) \
                == "w-dead"
            dead.proc.kill()  # hard kill (TerminateProcess/SIGKILL) while the lease is held
            await dead.proc.wait()
            assert dead.proc.returncode != 0
            # a second process reaps once the 1s lease expires (bounded wait inside the child)
            (live,) = await _start_all(dsn, [dict(db=db.name, op="reap_acquire", job=str(j),
                                                  worker="w-live", lease=120, deadline=40)])
            await live.go()
            second = await live.result(timeout=60)
        finally:
            await _reap_children([x for x in (dead, live) if x is not None])
        assert second["ok"] == 2 and second["reaped"] >= 1, second
        # the dead holder's fence (1) is rejected by finish_job and commit_cursor_page
        for sql, args in (
            ("SELECT living.finish_job('A','s1',$1,'w-dead',1,'SUCCEEDED',NULL)", (j,)),
            ("SELECT living.commit_cursor_page('A','s1','conn',$1,'w-dead',1,'p0',0,$2,'p1',$3::jsonb)",
             (j, ep, await page(c, "e1"))),
        ):
            with pytest.raises(Exception, match="STALE_JOB_FENCE"):
                await call(c, "living_worker", sql, *args)
        assert await c.fetchval("SELECT count(*) FROM living.outbox") == 0
        assert tuple(await c.fetchrow("SELECT cursor_value,version FROM living.cursors")) == ("p0", 0)
        # positive control: the new holder's fence commits the page
        assert await call(c, "living_worker",
                          "SELECT living.commit_cursor_page('A','s1','conn',$1,'w-live',2,'p0',0,$2,"
                          "'p1',$3::jsonb)", j, ep, await page(c, "e1")) == 1
        assert await c.fetchval("SELECT count(*) FROM living.outbox") == 1


async def _race_commit(dsn, db, j, f, ep, specs):
    children = await _start_all(dsn, [dict(db=db.name, op="commit", job=str(j), worker="w1",
                                           fence=f, prior="p0", version=0, epoch=ep, **s)
                                      for s in specs])
    try:
        return await _release_all(children)
    finally:
        await _reap_children(children)


async def test_two_processes_commit_same_prior_cursor_different_pages_one_wins():
    dsn = require_dsn()
    async with throwaway_db(dsn) as db:
        c = db.conn
        j, f = await cursor_and_job(c)
        ep = await source_epoch(c)
        pa, pb = await page(c, "a1", "a2"), await page(c, "b1", "b2", "b3")
        results = await _race_commit(dsn, db, j, f, ep, [dict(new="pa", events=pa),
                                                         dict(new="pb", events=pb)])
        oks = [r for r in results if "ok" in r]
        errs = [r for r in results if "err" in r]
        assert len(oks) == 1 and oks[0]["ok"] == 1, results
        assert len(errs) == 1 and errs[0]["err"] == "STALE_CURSOR_OR_SCOPE", results
        winner = "pa" if results[0] == oks[0] else "pb"
        want = ["a1", "a2"] if winner == "pa" else ["b1", "b2", "b3"]
        got = [r[0] for r in await c.fetch("SELECT event_id FROM living.outbox ORDER BY seq")]
        assert got == want  # only the winner's events; nothing of the loser, no duplicates
        assert tuple(await c.fetchrow("SELECT cursor_value,version FROM living.cursors")) \
            == (winner, 1)


async def test_two_processes_commit_identical_page_is_applied_once():
    dsn = require_dsn()
    async with throwaway_db(dsn) as db:
        c = db.conn
        j, f = await cursor_and_job(c)
        ep = await source_epoch(c)
        pg = await page(c, "e1", "e2")
        results = await _race_commit(dsn, db, j, f, ep, [dict(new="p1", events=pg),
                                                         dict(new="p1", events=pg)])
        assert results == [{"ok": 1}, {"ok": 1}], results  # one applies, one idempotent replay
        got = [r[0] for r in await c.fetch("SELECT event_id FROM living.outbox ORDER BY seq")]
        assert got == ["e1", "e2"]
        assert await c.fetchval("SELECT count(DISTINCT event_id) FROM living.outbox") == 2
        assert tuple(await c.fetchrow("SELECT cursor_value,version FROM living.cursors")) \
            == ("p1", 1)
