"""Phase 2 capacity drill (S4b E5): N sources x M worker OS processes against the disposable PostgreSQL.

Creates a throwaway database (tests/phase2/_pg_harness.throwaway_db, migrations 001-003), N sources
each with one cursor and one job, then starts M worker processes. After a start barrier every worker
loops over its sources: acquire_job -> commit_cursor_page (P pages, K small deterministic events) ->
finish_job, timing each call. Finally the parent recounts in the database and writes a JSON report.

The DSN is read from ERP_PHASE2_TEST_DSN (superuser DSN of erp-phase2-test-pg). It is passed to the
worker processes only through the environment, never argv, and is never written to the report.

    ERP_PHASE2_TEST_DSN=... python scripts/phase2_capacity_drill.py --sources 30 --workers 8 \
        --pages 3 --out drill_30.json

Exit code 0 only when every recount invariant holds and there were zero errors.
This is a MEASUREMENT on a disposable local container, not a production capacity guarantee.
"""
import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
import time
import uuid
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "phase2"))

TENANT = "A"
CONN_ID = "conn"
LEASE_SECONDS = 120
EVENTS_PER_PAGE = 2


def source_id(i: int) -> str:
    return f"d{i:04d}"


def job_id(sid: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_OID, "capacity-drill-job-" + sid)


def page_json(sid: str, p: int, k: int = EVENTS_PER_PAGE) -> str:
    """Events whose digest equals the one living.commit_cursor_page recomputes from the jsonb text."""
    events = []
    for e in range(k):
        eid = f"{sid}-p{p}-e{e}"
        # jsonb text form: keys ordered by length then bytes, ': ' and ', ' separators.
        text = f'{{"n": {p}, "event_id": "{eid}"}}'
        events.append({"event_id": eid, "n": p, "digest": hashlib.sha256(text.encode()).hexdigest()})
    return json.dumps(events)


def pct(sorted_ms: list, q: float) -> float:
    if not sorted_ms:
        return 0.0
    rank = max(1, -(-len(sorted_ms) * q // 100))  # nearest-rank
    return sorted_ms[int(rank) - 1]


def stats(samples_s: list) -> dict:
    ms = sorted(x * 1000.0 for x in samples_s)
    if not ms:
        return {"count": 0}
    return {"count": len(ms), "p50_ms": round(pct(ms, 50), 3), "p95_ms": round(pct(ms, 95), 3),
            "p99_ms": round(pct(ms, 99), 3), "max_ms": round(ms[-1], 3),
            "mean_ms": round(sum(ms) / len(ms), 3)}


# ------------------------------------------------------------------------------------ worker mode
async def worker_main(db: str, indices: list, pages: int, wname: str) -> None:
    lat = {"acquire_job": [], "commit_cursor_page": [], "finish_job": []}
    errors = []
    c = await asyncpg.connect(os.environ["ERP_PHASE2_TEST_DSN"], database=db, timeout=30)

    async def timed(op, sid, sql, *args):
        t0 = time.perf_counter()
        try:
            async with c.transaction():
                await c.execute('SET LOCAL ROLE "living_worker"')
                await c.fetchval("SELECT living.set_scope($1,$2,NULL)", TENANT, sid)
                res = await c.fetchval(sql, *args)
            lat[op].append(time.perf_counter() - t0)
            return res
        except asyncpg.PostgresError as e:
            errors.append({"op": op, "source": sid, "error": str(e).splitlines()[0][:200]})
            return None

    print("READY", flush=True)
    sys.stdin.readline()  # start barrier: the parent writes one line to every worker at once
    for i in indices:
        sid = source_id(i)
        jid = job_id(sid)
        epoch = await c.fetchval("SELECT scope_epoch FROM living.sources WHERE tenant_id=$1 AND "
                                 "source_id=$2", TENANT, sid)
        fence = await timed("acquire_job", sid, "SELECT living.acquire_job($1,$2,$3::uuid,$4,$5)",
                            TENANT, sid, jid, wname, LEASE_SECONDS)
        if fence is None:
            continue
        ok = True
        for p in range(1, pages + 1):
            v = await timed("commit_cursor_page", sid,
                            "SELECT living.commit_cursor_page($1,$2,$3,$4::uuid,$5,$6,$7,$8,$9,$10,"
                            "$11::jsonb)", TENANT, sid, CONN_ID, jid, wname, fence, f"p{p - 1}",
                            p - 1, epoch, f"p{p}", page_json(sid, p))
            if v != p:
                ok = False
                break
        if ok:
            await timed("finish_job", sid, "SELECT living.finish_job($1,$2,$3::uuid,$4,$5,$6,$7)",
                        TENANT, sid, jid, wname, fence, "SUCCEEDED", None)
    await c.close()
    print("RESULT " + json.dumps({"latencies": lat, "errors": errors}), flush=True)


# ------------------------------------------------------------------------------------ parent mode
async def setup(db, n: int) -> None:
    c = db.conn
    await c.execute("INSERT INTO living.tenants VALUES ('A')")
    await c.execute("INSERT INTO living.sources(tenant_id,source_id,company_id) "
                    "SELECT 'A','d'||lpad(i::text,4,'0'),NULL FROM generate_series(0,$1::int-1) i", n)
    await c.execute("INSERT INTO living.role_scope(role_name,tenant_id,source_id,company_id) "
                    "SELECT 'living_worker','A',source_id,NULL FROM living.sources")
    for i in range(n):
        sid = source_id(i)
        async with c.transaction():
            await c.execute('SET LOCAL ROLE "living_worker"')
            await c.fetchval("SELECT living.set_scope('A',$1,NULL)", sid)
            await c.fetchval("SELECT living.create_cursor('A',$1,$2,'p0')", sid, CONN_ID)
            await c.fetchval("SELECT living.enqueue_job('A',$1,$2::uuid,'sync',$3,$4,'{}'::jsonb)",
                             sid, job_id(sid), "c" * 64, "k-" + sid)


async def sample_lock_waits(dsn, dbname, stop: asyncio.Event, out: dict) -> None:
    c = await asyncpg.connect(dsn, database=dbname, timeout=30)
    try:
        while not stop.is_set():
            n = await c.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datname=$1 AND "
                                 "wait_event_type='Lock'", dbname)
            out["samples"] += 1
            out["max_concurrent_lock_waiters"] = max(out["max_concurrent_lock_waiters"], n)
            out["samples_with_waiters"] += 1 if n else 0
            try:
                await asyncio.wait_for(stop.wait(), 0.1)
            except TimeoutError:
                pass
    finally:
        await c.close()


async def recount(c, n: int, pages: int, k: int) -> dict:
    exp_pages, exp_events = n * pages, n * pages * k
    r = {
        "expected_pages": exp_pages, "expected_outbox_rows": exp_events,
        "cursor_version_sum": await c.fetchval("SELECT coalesce(sum(version),0)::bigint FROM living.cursors"),
        "cursors_at_final_page": await c.fetchval(
            "SELECT count(*) FROM living.cursors WHERE version=$1 AND cursor_value=$2",
            pages, f"p{pages}"),
        "outbox_rows": await c.fetchval("SELECT count(*) FROM living.outbox"),
        "outbox_distinct_event_ids": await c.fetchval(
            "SELECT count(DISTINCT event_id) FROM living.outbox"),
        "jobs_succeeded": await c.fetchval("SELECT count(*) FROM living.jobs WHERE state='SUCCEEDED'"),
        "jobs_total": await c.fetchval("SELECT count(*) FROM living.jobs"),
        "jobs_with_fence_not_1": await c.fetchval(
            "SELECT count(*) FROM living.jobs WHERE fence<>1 OR attempt<>1"),
        "jobs_still_leased": await c.fetchval(
            "SELECT count(*) FROM living.jobs WHERE lease_owner IS NOT NULL"),
    }
    return r


def invariants(rc: dict, n: int, errors: list) -> dict:
    inv = {
        "pages_committed_equals_expected": rc["cursor_version_sum"] == rc["expected_pages"],
        "all_cursors_at_final_page": rc["cursors_at_final_page"] == n,
        "outbox_rows_equals_expected": rc["outbox_rows"] == rc["expected_outbox_rows"],
        "no_duplicate_event_ids": rc["outbox_distinct_event_ids"] == rc["outbox_rows"],
        "all_jobs_succeeded": rc["jobs_succeeded"] == n and rc["jobs_total"] == n,
        "no_fence_violation": rc["jobs_with_fence_not_1"] == 0 and rc["jobs_still_leased"] == 0,
        "zero_errors": len(errors) == 0,
    }
    inv["all_ok"] = all(inv.values())
    return inv


async def run_drill(dsn: str, n: int, workers: int, pages: int) -> dict:
    from _pg_harness import throwaway_db  # reuse the existing disposable-database helper

    workers = max(1, min(workers, n))
    async with throwaway_db(dsn, seed=False) as db:
        await setup(db, n)
        env = dict(os.environ, ERP_PHASE2_TEST_DSN=dsn)  # DSN only via environment
        procs = []
        for w in range(workers):
            idx = ",".join(str(i) for i in range(w, n, workers))
            procs.append(await asyncio.create_subprocess_exec(
                sys.executable, os.path.abspath(__file__), "--worker", "--db", db.name,
                "--indices", idx, "--pages", str(pages), "--wname", f"drill-w{w}", env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE))
        try:
            for p in procs:
                line = await asyncio.wait_for(p.stdout.readline(), 120)
                if line.strip() != b"READY":
                    raise RuntimeError("worker did not become ready: " + repr(line))
            lock = {"samples": 0, "max_concurrent_lock_waiters": 0, "samples_with_waiters": 0}
            stop = asyncio.Event()
            sampler = asyncio.create_task(sample_lock_waits(dsn, db.name, stop, lock))
            t0 = time.perf_counter()
            for p in procs:
                p.stdin.write(b"GO\n")
                await p.stdin.drain()
            ends = []

            async def finish(p):
                out, err = await p.communicate()
                ends.append(time.perf_counter())
                return p.returncode, out.decode(errors="replace"), err.decode(errors="replace")

            results = await asyncio.gather(*(finish(p) for p in procs))
            wall = max(ends) - t0
            stop.set()
            await sampler
        finally:
            for p in procs:
                if p.returncode is None:
                    p.kill()
        lat = {"acquire_job": [], "commit_cursor_page": [], "finish_job": []}
        errors = []
        for rc_, out, err in results:
            res = [ln for ln in out.splitlines() if ln.startswith("RESULT ")]
            if rc_ != 0 or not res:
                errors.append({"op": "worker_process", "error": f"exit={rc_} stderr={err[-300:]}"})
                continue
            body = json.loads(res[0][7:])
            errors.extend(body["errors"])
            for op, vals in body["latencies"].items():
                lat[op].extend(vals)
        rc = await recount(db.conn, n, pages, EVENTS_PER_PAGE)
    inv = invariants(rc, n, errors)
    total_ops = sum(len(v) for v in lat.values())
    return {
        "params": {"sources": n, "workers": workers, "pages": pages,
                   "events_per_page": EVENTS_PER_PAGE, "lease_seconds": LEASE_SECONDS},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "database": "disposable PostgreSQL container (not production)"},
        "wall_seconds": round(wall, 3),
        "total_timed_operations": total_ops,
        "throughput_ops_per_s": round(total_ops / wall, 2) if wall else None,
        "throughput_pages_per_s": round(rc["cursor_version_sum"] / wall, 2) if wall else None,
        "latency": {op: stats(v) for op, v in lat.items()},
        "lock_waits": lock,
        "error_count": len(errors),
        "errors_sample": errors[:10],
        "db_recount": rc,
        "invariants": inv,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--db", type=str, help=argparse.SUPPRESS)
    ap.add_argument("--indices", type=str, help=argparse.SUPPRESS)
    ap.add_argument("--wname", type=str, default="drill-w", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    dsn = os.environ.get("ERP_PHASE2_TEST_DSN")
    if not dsn:
        print("ERP_PHASE2_TEST_DSN is not set", file=sys.stderr)
        return 2
    if a.worker:
        asyncio.run(worker_main(a.db, [int(x) for x in a.indices.split(",") if x], a.pages, a.wname))
        return 0
    if a.sources < 1 or a.workers < 1 or a.pages < 1:
        print("--sources, --workers and --pages must be >= 1", file=sys.stderr)
        return 2
    report = asyncio.run(run_drill(dsn, a.sources, a.workers, a.pages))
    text = json.dumps(report, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["invariants"]["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
