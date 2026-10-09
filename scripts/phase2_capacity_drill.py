"""Phase 2 capacity drill (S4b E5): N sources x M worker OS processes against the disposable PostgreSQL.

Creates a throwaway database (tests/phase2/_pg_harness.throwaway_db, migrations 001-003), N sources
each with one cursor and one job, then starts M worker processes. After a start barrier every worker
loops over its sources: acquire_job -> commit_cursor_page (P pages, K small deterministic events) ->
finish_job, timing each call. Finally the parent recounts in the database and writes a JSON report.

The DSN is read from ERP_PHASE2_TEST_DSN (superuser DSN of erp-phase2-test-pg). It is passed to the
worker processes only through the environment, never argv, and is never written to the report: the DSN,
its password and its user name are redacted from every stored error text and from the final output.
Only local hosts (localhost, 127.0.0.1, ::1) are accepted unless ERP_PHASE2_DRILL_ALLOW_REMOTE=1.

    ERP_PHASE2_TEST_DSN=... python scripts/phase2_capacity_drill.py --sources 30 --workers 8 \
        --pages 3 --out drill_30.json

--keep-db [--db-name g1x_<name>] keeps the database (name reported as ``kept_database``) so a caller
can recount independently; the caller then owns the DROP.

Exit code 0 only when every recount invariant holds and there were zero errors; a worker phase that
exceeds its deadline kills the workers and exits non-zero.
This is a MEASUREMENT on a disposable local container, not a production capacity guarantee.
"""
import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import platform
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "phase2"))

TENANT = "A"
CONN_ID = "conn"
LEASE_SECONDS = 120
EVENTS_PER_PAGE = 2
COMMAND_TIMEOUT = 60
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MIN_COUNT_FOR_P99 = 100


def source_id(i: int) -> str:
    return f"d{i:04d}"


def job_id(sid: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_OID, "capacity-drill-job-" + sid)


def event_id(sid: str, p: int, e: int) -> str:
    return f"{sid}-p{p}-e{e}"


def page_json(sid: str, p: int, k: int = EVENTS_PER_PAGE) -> str:
    """Events whose digest equals the one living.commit_cursor_page recomputes from the jsonb text."""
    events = []
    for e in range(k):
        eid = event_id(sid, p, e)
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
            # p99 of fewer than 100 samples is just the max: do not publish it as a percentile
            "p99_ms": round(pct(ms, 99), 3) if len(ms) >= MIN_COUNT_FOR_P99 else None,
            "max_ms": round(ms[-1], 3), "mean_ms": round(sum(ms) / len(ms), 3)}


def parse_range(spec: str) -> range:
    """'start:stop:step' (the worker's source indices)."""
    start, stop, step = (int(x) for x in spec.split(":"))
    if step < 1:
        raise ValueError("step must be >= 1")
    return range(start, stop, step)


# ------------------------------------------------------------------------------------ safety
def _kv_host(dsn: str):
    m = re.search(r"(?:^|\s)host\s*=\s*('([^']*)'|(\S+))", dsn)
    return (m.group(2) if m and m.group(2) is not None else m.group(3)) if m else None


def dsn_host(dsn: str):
    if "://" in dsn:
        return urlsplit(dsn).hostname
    return _kv_host(dsn)


def host_allowed(dsn: str) -> bool:
    if os.environ.get("ERP_PHASE2_DRILL_ALLOW_REMOTE") == "1":
        return True
    host = dsn_host(dsn)
    return host is None or host.lower() in LOCAL_HOSTS  # no host = libpq default (local)


def secrets_of(dsn: str) -> list:
    out = {dsn}
    if "://" in dsn:
        u = urlsplit(dsn)
        for s in (u.password, unquote(u.password or ""), u.username, unquote(u.username or "")):
            if s and len(s) >= 3:
                out.add(s)
    else:
        for m in re.finditer(r"(?:^|\s)(?:password|user)\s*=\s*('([^']*)'|(\S+))", dsn):
            s = m.group(2) if m.group(2) is not None else m.group(3)
            if s and len(s) >= 3:
                out.add(s)
    return sorted(out, key=len, reverse=True)


def redact(text, dsn: str) -> str:
    text = str(text)
    for s in secrets_of(dsn):
        text = text.replace(s, "***")
    return text


# ------------------------------------------------------------------------------------ worker mode
async def worker_main(db: str, indices: range, pages: int, wname: str, k: int) -> int:
    lat = {"acquire_job": [], "commit_cursor_page": [], "finish_job": []}
    errors = []
    c = await asyncpg.connect(os.environ["ERP_PHASE2_TEST_DSN"], database=db, timeout=30,
                              command_timeout=COMMAND_TIMEOUT)

    async def timed(op, sid, sql, *args):
        t0 = time.perf_counter()
        try:
            async with c.transaction():
                await c.execute('SET LOCAL ROLE "living_worker"')
                await c.fetchval("SELECT living.set_scope($1,$2,NULL)", TENANT, sid)
                res = await c.fetchval(sql, *args)
            lat[op].append(time.perf_counter() - t0)
            return res
        except (asyncpg.PostgresError, TimeoutError) as e:
            errors.append({"op": op, "source": sid, "error": str(e).splitlines()[0][:200]})
            return None

    print("READY", flush=True)
    go = sys.stdin.readline()  # start barrier: the parent writes one line to every worker at once
    if not go.strip():  # EOF / empty line = the parent is gone or aborted: never count it as GO
        print("worker aborted: stdin closed before GO", file=sys.stderr, flush=True)
        await c.close()
        return 3
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
                            p - 1, epoch, f"p{p}", page_json(sid, p, k))
            if v is not None and v != p:
                errors.append({"op": "commit_cursor_page", "source": sid,
                               "error": f"committed version {v} differs from expected page {p}"})
            if v != p:
                ok = False
                break
        if ok:
            await timed("finish_job", sid, "SELECT living.finish_job($1,$2,$3::uuid,$4,$5,$6,$7)",
                        TENANT, sid, jid, wname, fence, "SUCCEEDED", None)
    await c.close()
    print("RESULT " + json.dumps({"latencies": lat, "errors": errors}), flush=True)
    return 0


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


@asynccontextmanager
async def drill_db(dsn: str, keep: bool, name):
    """Throwaway database; with keep=True it is NOT dropped (the caller owns the DROP)."""
    from _pg_harness import DB_PREFIX, Db, admin_connect, apply_files, new_name, throwaway_db

    if not keep:
        async with throwaway_db(dsn, seed=False) as db:
            yield db
        return
    name = name or new_name()
    if not name.startswith(DB_PREFIX) or not re.fullmatch(r"[a-z0-9_]{5,40}", name):
        raise ValueError(f"--db-name must match {DB_PREFIX}[a-z0-9_]+")
    admin = await admin_connect(dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    db = Db(dsn, name)
    db.conn = await db.connect()
    try:
        await apply_files(db.conn)
        yield db
    finally:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(db.conn.close(), 5)


async def sample_lock_waits(dsn, dbname, stop: asyncio.Event, out: dict) -> None:
    c = await asyncpg.connect(dsn, database=dbname, timeout=30, command_timeout=COMMAND_TIMEOUT)
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
    expected = {source_id(i): sorted(event_id(source_id(i), p, e)
                                     for p in range(1, pages + 1) for e in range(k))
                for i in range(n)}
    got = {r["source_id"]: sorted(r["ids"]) for r in await c.fetch(
        "SELECT source_id, array_agg(event_id) AS ids FROM living.outbox GROUP BY source_id")}
    mismatched = sorted(s for s in set(expected) | set(got) if expected.get(s) != got.get(s))
    r = {
        "expected_pages": exp_pages, "expected_outbox_rows": exp_events,
        "cursor_version_sum": await c.fetchval("SELECT coalesce(sum(version),0)::bigint FROM living.cursors"),
        "cursors_at_final_page": await c.fetchval(
            "SELECT count(*) FROM living.cursors WHERE version=$1 AND cursor_value=$2",
            pages, f"p{pages}"),
        "outbox_rows": await c.fetchval("SELECT count(*) FROM living.outbox"),
        "outbox_distinct_event_ids": await c.fetchval(
            "SELECT count(DISTINCT event_id) FROM living.outbox"),
        "sources_with_unexpected_event_set": len(mismatched),
        "unexpected_event_set_sample": mismatched[:10],
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
        "expected_event_ids_per_source": rc["sources_with_unexpected_event_set"] == 0,
        "all_jobs_succeeded": rc["jobs_succeeded"] == n and rc["jobs_total"] == n,
        "no_fence_violation": rc["jobs_with_fence_not_1"] == 0 and rc["jobs_still_leased"] == 0,
        "zero_errors": len(errors) == 0,
    }
    inv["all_ok"] = all(inv.values())
    return inv


async def _kill_and_wait(procs) -> None:
    for p in procs:
        if p.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                p.kill()
    for p in procs:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(p.wait(), 15)


async def run_drill(dsn: str, n: int, workers: int, pages: int, keep: bool = False,
                    db_name=None, k: int = EVENTS_PER_PAGE) -> dict:
    workers = max(1, min(workers, n))
    deadline = 120 + n * pages * 0.5  # seconds for the whole worker phase
    async with drill_db(dsn, keep, db_name) as db:
        await setup(db, n)
        env = dict(os.environ, ERP_PHASE2_TEST_DSN=dsn)  # DSN only via environment
        procs = []
        stop = asyncio.Event()
        sampler = None
        lock = {"samples": 0, "max_concurrent_lock_waiters": 0, "samples_with_waiters": 0,
                "sample_interval_s": 0.1}
        try:
            for w in range(workers):
                procs.append(await asyncio.create_subprocess_exec(
                    sys.executable, os.path.abspath(__file__), "--worker", "--db", db.name,
                    "--indices", f"{w}:{n}:{workers}", "--pages", str(pages),
                    "--wname", f"drill-w{w}", "--events", str(k), env=env,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE))
            for p in procs:
                line = await asyncio.wait_for(p.stdout.readline(), 120)
                if line.strip() != b"READY":
                    raise RuntimeError("worker did not become ready: " + repr(line))
            sampler = asyncio.create_task(sample_lock_waits(dsn, db.name, stop, lock))
            ends = []

            async def finish(p):
                out, err = await p.communicate()
                ends.append(time.perf_counter())
                return p.returncode, out.decode(errors="replace"), err.decode(errors="replace")

            t0 = time.perf_counter()
            for p in procs:  # a BrokenPipe here still reaches the cleanup in `finally`
                p.stdin.write(b"GO\n")
                await p.stdin.drain()
            try:
                results = await asyncio.wait_for(asyncio.gather(*(finish(p) for p in procs)),
                                                 deadline)
            except TimeoutError:
                raise RuntimeError(f"worker phase exceeded its {deadline:.0f}s deadline; "
                                   "workers killed") from None
            wall = max(ends) - t0
            stop.set()
            await sampler
        finally:
            stop.set()
            if sampler is not None:
                sampler.cancel()
                with contextlib.suppress(BaseException):
                    await sampler
            await _kill_and_wait(procs)  # kill AND reap every worker before the database goes away
        lat = {"acquire_job": [], "commit_cursor_page": [], "finish_job": []}
        errors = []
        for rc_, out, err in results:
            res = [ln for ln in out.splitlines() if ln.startswith("RESULT ")]
            if rc_ != 0 or not res:
                errors.append({"op": "worker_process",
                               "error": f"exit={rc_} stderr={redact(err[-300:], dsn)}"})
                continue
            body = json.loads(res[0][7:])
            errors.extend({**e, "error": redact(e.get("error", ""), dsn)} for e in body["errors"])
            for op, vals in body["latencies"].items():
                lat[op].extend(vals)
        rc = await recount(db.conn, n, pages, k)
        kept = db.name if keep else None
    inv = invariants(rc, n, errors)
    total_ops = sum(len(v) for v in lat.values())
    return {
        "params": {"sources": n, "workers": workers, "pages": pages,
                   "events_per_page": k, "lease_seconds": LEASE_SECONDS,
                   "worker_phase_deadline_s": deadline},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "database": "disposable PostgreSQL container (not production)"},
        "kept_database": kept,
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


def _emit(report: dict, out, dsn: str) -> None:
    text = redact(json.dumps(report, indent=2), dsn)  # final defence against a leaked secret
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    print(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--events", type=int, default=EVENTS_PER_PAGE, help="events per page")
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--keep-db", action="store_true",
                    help="do not drop the throwaway database (caller recounts and drops it)")
    ap.add_argument("--db-name", type=str, default=None, help="name for --keep-db (g1x_...)")
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
        return asyncio.run(worker_main(a.db, parse_range(a.indices), a.pages, a.wname, a.events))
    if a.sources < 1 or a.workers < 1 or a.pages < 1 or a.events < 1:
        print("--sources, --workers, --pages and --events must be >= 1", file=sys.stderr)
        return 2
    if a.db_name and not a.keep_db:
        print("--db-name requires --keep-db", file=sys.stderr)
        return 2
    if not host_allowed(dsn):
        print("refusing a non-local database host (set ERP_PHASE2_DRILL_ALLOW_REMOTE=1 to override)",
              file=sys.stderr)
        return 2

    async def go() -> dict:
        pre = await asyncpg.connect(dsn, timeout=10)  # fail fast on a bad DSN/password, no retries
        await pre.close()
        return await run_drill(dsn, a.sources, a.workers, a.pages, a.keep_db, a.db_name, a.events)

    try:
        report = asyncio.run(go())
    except Exception as e:  # noqa: BLE001 - report a redacted message, never the raw DSN/password
        msg = redact(f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}", dsn)
        _emit({"error": msg, "invariants": {"all_ok": False}}, a.out, dsn)
        return 1
    _emit(report, a.out, dsn)
    return 0 if report["invariants"]["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
