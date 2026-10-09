# ruff: noqa: C408
"""G1 multi-process concurrency tests (S4b E4): REAL OS processes against the disposable PostgreSQL.

Racing scenarios use a real gate: the parent holds an exclusive advisory lock, every child blocks on a
shared one inside its open transaction right after GO, and one unlock releases them together; each
child reports its execution window (database clock) and the test asserts the windows overlap.

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

    win = {}
    now = "SELECT extract(epoch FROM clock_timestamp())::float8"

    async def scoped(sql, *args):
        async with c.transaction():
            await c.execute("SET LOCAL ROLE living_worker")
            await c.fetchval("SELECT living.set_scope('A','s1',NULL)")
            if a.get("gate"):  # blocks until the parent releases its exclusive advisory lock
                await c.fetchval("SELECT pg_advisory_xact_lock_shared($1)", a["gate"])
                win["t0"] = await c.fetchval(now)  # database clock: comparable across processes
            return await c.fetchval(sql, *args)

    async def attempt(sql, *args):
        try:
            out = {"ok": await scoped(sql, *args)}
        except asyncpg.PostgresError as e:
            out = {"err": str(e).splitlines()[0]}
        if a.get("gate"):
            out["win"] = [win.get("t0"), await c.fetchval(now)]
        return out

    print("READY", flush=True)
    if not sys.stdin.readline().strip():  # EOF / empty line = parent gone: abort, never count as GO
        sys.exit(3)
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


GATE = 424242  # advisory-lock key the parent holds exclusively while the racing children queue up


class Child:
    def __init__(self, proc):
        self.proc = proc
        self._err = bytearray()
        # drain stderr continuously so a chatty child can never block on a full pipe
        self._drain = asyncio.create_task(self._pump())

    async def _pump(self):
        while chunk := await self.proc.stderr.read(4096):
            self._err += chunk
            del self._err[:-4000]

    def stderr_tail(self):
        return bytes(self._err[-800:])

    @classmethod
    async def start(cls, dsn, **args):
        env = dict(os.environ, ERP_PHASE2_TEST_DSN=dsn)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", CHILD, json.dumps(args, default=str), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        child = cls(proc)
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), 90)
            assert line.strip() == b"READY", (line, child.stderr_tail())
        except BaseException:
            await child.kill()  # never leak a started process on any start failure
            raise
        return child

    async def kill(self):
        if self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        await self.proc.wait()
        self._drain.cancel()
        await asyncio.gather(self._drain, return_exceptions=True)

    async def go(self):
        self.proc.stdin.write(b"GO\n")
        await self.proc.stdin.drain()

    async def result(self, timeout=90):
        line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
        assert line.startswith(b"RESULT "), (line, self.stderr_tail())
        return json.loads(line[7:])


async def _start_all(dsn, specs):
    res = await asyncio.gather(*(Child.start(dsn, **s) for s in specs), return_exceptions=True)
    started = [r for r in res if isinstance(r, Child)]
    failed = [r for r in res if isinstance(r, BaseException)]
    if failed:
        await _reap_children(started)
        raise failed[0]
    return started


def _clean(result):
    return {k: v for k, v in result.items() if k != "win"}


async def _release_all(children, db):
    """Real contention: the parent holds an exclusive advisory lock; every child blocks on it (inside
    its open transaction) right after GO. Once all are queued, one unlock releases them together.
    Returns the raw results (with execution windows); assertions must not depend on arrival order."""
    c = db.conn
    await c.execute("SELECT pg_advisory_lock($1)", GATE)
    held = True
    try:
        for ch in children:
            await ch.go()
        for _ in range(600):  # bounded: up to ~30 s for all children to queue on the gate
            waiting = await c.fetchval(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted AND "
                "database=(SELECT oid FROM pg_database WHERE datname=current_database())")
            if waiting == len(children):
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError(f"only {waiting} of {len(children)} children queued on the gate")
        await c.execute("SELECT pg_advisory_unlock($1)", GATE)
        held = False
        results = await asyncio.gather(*(ch.result() for ch in children))
    finally:
        if held:
            await c.execute("SELECT pg_advisory_unlock($1)", GATE)
    wins = [r["win"] for r in results]
    assert all(w[0] is not None for w in wins), results
    # the racing calls really overlapped: the latest start precedes the earliest end
    assert max(w[0] for w in wins) < min(w[1] for w in wins), wins
    return results


async def _reap_children(children):
    await asyncio.gather(*(ch.kill() for ch in children), return_exceptions=True)


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
                                               lease=60, gate=GATE) for i in range(6)])
        try:
            results = await _release_all(children, db)
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
        dead = live = None
        try:
            (dead,) = await _start_all(dsn, [dict(db=db.name, op="acquire_hold", job=str(j),
                                                  worker="w-dead", lease=1)])
            await dead.go()
            first = await dead.result()
            assert first == {"ok": 1}, first
            assert await c.fetchval("SELECT lease_owner FROM living.jobs WHERE job_id=$1", j) \
                == "w-dead"
            dead.proc.kill()  # hard kill (TerminateProcess/SIGKILL) while the lease is held
            await dead.proc.wait()
            assert dead.proc.returncode != 0
            # a second process takes over once the 1s lease expires (bounded wait inside the child);
            # acquire_job may reclaim the expired lease itself, so the reap count is not asserted
            (live,) = await _start_all(dsn, [dict(db=db.name, op="reap_acquire", job=str(j),
                                                  worker="w-live", lease=120, deadline=40)])
            await live.go()
            second = await live.result(timeout=60)
        finally:
            await _reap_children([x for x in (dead, live) if x is not None])
        assert second["ok"] == 2, second  # the new holder has fence 2; the dead one's fence 1 is dead
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
                                           fence=f, prior="p0", version=0, epoch=ep, gate=GATE, **s)
                                      for s in specs])
    try:
        return await _release_all(children, db)
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
        winner = "pa" if results[0] is oks[0] else "pb"
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
        # one applies, one is an idempotent replay (either order)
        assert [_clean(r) for r in results] == [{"ok": 1}, {"ok": 1}], results
        got = [r[0] for r in await c.fetch("SELECT event_id FROM living.outbox ORDER BY seq")]
        assert got == ["e1", "e2"]
        assert await c.fetchval("SELECT count(DISTINCT event_id) FROM living.outbox") == 2
        assert tuple(await c.fetchrow("SELECT cursor_value,version FROM living.cursors")) \
            == ("p1", 1)
