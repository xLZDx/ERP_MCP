"""E38-parallel: multi-process budget / grant reservation races on the CHANGE ledger (db/phase2 008 claim).

Contract under test: change_ledger.claim reserves capacity against ONE grant (amount_limit / count_limit) under a
row lock on the grant (budget_precheck ... FOR UPDATE) and refuses with the stable error BUDGET_EXCEEDED when the
reservation would pass the limit. The existing test_g1_concurrency_mp.py covers only the living registry; the
change-ledger budget paths were covered single-connection. Here N REAL OS processes (multiprocessing "spawn", one
PostgreSQL backend each) call the real change_ledger.claim as the real requester role (SET LOCAL ROLE
requester_role member, scope set) at the same instant:

  * start barrier: the parent holds an exclusive advisory lock, every child blocks on a shared one inside its open
    transaction, and one unlock releases them together (the parent first waits until all N are really blocked);
  * boundary matrix: limit minus one unit / exactly the limit / limit plus one, for the amount limit and for the
    reservation-count limit; exactly K of N succeed, the rest are refused with BUDGET_EXCEEDED;
  * invariants read back as superuser: committed reserved total <= limit, one RESERVED row per winner and none for a
    loser, no lost / duplicated reservation, one CLAIMED event per winner, the hash chain still verifies;
  * an abandoned reserver (explicit ROLLBACK, and abrupt process death) gives its capacity back to the waiters;
  * duplicate: several processes claiming the SAME change reserve once (replay returns the same token).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test builds its own throwaway database. No sleeps as synchronisation: bounded polling
of pg_locks / pg_stat_activity and blocking queue reads with timeouts.
"""
import asyncio
import multiprocessing
import queue
import time
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from _pg_harness import require_dsn, throwaway_db
from _s13_budget_worker import worker
from test_change_ledger_sql import BASES, C, DEFAULT_GRANT, L, ORG, T, _setup, exp, sha  # noqa: F401

from _approval_envelope import fixture_digest_for

pytestmark = pytest.mark.integration

CTX = multiprocessing.get_context("spawn")
GATE = 7_313_038
N = 10                      # racing processes (>= 8)
UNIT = 10                   # amount of every change in the amount-limit matrix
# The SQL ledger intentionally keeps BUDGET_EXCEEDED for an exhausted grant until a new migration (S12 amendment 2026-10-28).
STABLE_ERROR = "BUDGET_EXCEEDED"
WAIT = 120                  # generous bounded wait for spawn + connect on a slow Windows host


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


# ---------------------------------------------------------------- arrangement through the real API
async def make_grant(led, amount_limit, count_limit=1000, post_count_limit=1000):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", amount_limit, count_limit, post_count_limit,
                   datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC) + timedelta(hours=1))
    return gid


async def approved_change(led, i, gid, amount, counts_cu):
    """One APPROVED CREATE_DRAFT of alice on its own base / target / business key, budget declared against gid."""
    cid = uuid.uuid4()
    await led.call("clt_alice", "propose", cid, "CREATE_DRAFT", BASES[i], ORG, "clt_alice", f"e38-{i}-{cid.hex}",
                   fixture_digest_for("CREATE_DRAFT"), f"doc-e38-{i}", "v1", None, exp(), None)
    await led.call("clt_alice", "declare_business_key", cid, sha(str(cid)), None, None)
    await led.call("clt_alice", "declare_target_class", cid, "CLONE")
    await led.call("clt_alice", "declare_budget", cid, gid, "EUR", amount, counts_cu, False)
    assert await led.call("clt_alice", "validate", cid) == "VALIDATED"
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    await led.call("clt_bob", "approve", cid, nonce, await led.approval_digest(cid))
    return cid


async def make_changes(led, n, gid, amount, counts_cu):
    return [await approved_change(led, i, gid, amount, counts_cu) for i in range(n)]


async def spec_for(led, idx, cid, **extra):
    cb = await led.conn.fetchrow("SELECT * FROM change_ledger.change_budget WHERE change_id=$1", cid)
    dsn = require_dsn()
    return {"idx": idx, "dsn": dsn, "db": led.db.name, "role": "clt_alice", "t": T, "c": C, "change_id": str(cid),
            "grant_id": str(cb["grant_id"]), "amount": cb["amount"], "counts_cu": cb["counts_create_update"],
            "counts_post": cb["counts_post"], **extra}


# ---------------------------------------------------------------- process orchestration
class Swarm:
    def __init__(self):
        self.q = CTX.Queue()
        self.procs = {}
        self.cmds = {}
        self.ready = set()
        self.results = {}
        self.claimed_open = {}

    def start(self, spec):
        parent_end, child_end = CTX.Pipe()
        p = CTX.Process(target=worker, args=(spec, self.q, child_end), daemon=True)
        p.start()
        self.procs[spec["idx"]], self.cmds[spec["idx"]] = p, parent_end

    async def _get(self, timeout):
        return await asyncio.to_thread(self.q.get, True, timeout)

    async def pump_until(self, pred, timeout=WAIT, what="condition"):
        end = time.monotonic() + timeout
        while not pred():
            left = end - time.monotonic()
            if left <= 0:
                raise AssertionError(f"timeout waiting for {what}; ready={sorted(self.ready)} "
                                     f"results={self.results}")
            try:
                msg = await self._get(min(left, 5))
            except queue.Empty:
                continue
            self.absorb(msg)

    def absorb(self, msg):
        if msg[0] == "ready":
            self.ready.add(msg[1])
        elif msg[0] == "claimed_open":
            self.claimed_open[msg[1]] = msg[2]
        else:
            self.results[msg[1]] = msg[2]

    async def drain_nowait(self):
        while True:
            try:
                self.absorb(self.q.get_nowait())
            except queue.Empty:
                return

    async def finish(self, expected):
        await self.pump_until(lambda: set(self.results) >= set(expected), what="all results")
        for i in expected:
            await asyncio.to_thread(self.procs[i].join, 30)

    def reap(self):
        for p in self.procs.values():
            if p.is_alive():
                p.kill()
            p.join(5)


async def wait_for(conn, sql, expected, what, timeout=WAIT, *args):
    end = time.monotonic() + timeout
    got = None
    while time.monotonic() < end:
        got = await conn.fetchval(sql, *args)
        if got == expected:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timeout waiting for {what}: expected {expected}, last {got}")


async def race(led, cids, *, gate=GATE):
    """Run len(cids) processes at once (one claim each); return {idx: outcome} after every one has finished."""
    sw = Swarm()
    gate_conn = await asyncpg.connect(led.db.dsn, database=led.db.name)
    try:
        await gate_conn.execute("SELECT pg_advisory_lock($1)", gate)   # session lock: the barrier is closed
        for i, cid in enumerate(cids):
            sw.start(await spec_for(led, i, cid, gate=gate))
        await sw.pump_until(lambda: len(sw.ready) == len(cids), what="all children ready")
        await wait_for(gate_conn, "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted "
                       "AND objid=$1", len(cids), "all children blocked on the start barrier", WAIT, gate)
        await gate_conn.execute("SELECT pg_advisory_unlock($1)", gate)   # GO for everyone at once
        await sw.finish(range(len(cids)))
        return sw.results
    finally:
        sw.reap()
        await gate_conn.close()


# ---------------------------------------------------------------- read-back invariants (superuser)
async def reserved_rows(led, cids):
    rows = await led.conn.fetch("SELECT change_id, state, amount, counts_create_update FROM "
                                "change_ledger.reservations WHERE change_id = ANY($1::uuid[])", cids)
    return {r["change_id"]: r for r in rows}


async def assert_consistent(led, cids, results, gid, k, limit_check):
    winners = {i for i, r in results.items() if r["ok"]}
    losers = set(results) - winners
    assert len(winners) == k, results
    for i in losers:      # the refusal is the one stable budget error, not a lock/deadlock/other failure
        assert results[i]["err"] == STABLE_ERROR, (i, results[i])
    rows = await reserved_rows(led, cids)
    # no reservation lost, none duplicated, none for a loser
    assert {cids[i] for i in winners} == set(rows), (winners, sorted(map(str, rows)))
    assert all(r["state"] == "RESERVED" for r in rows.values())
    assert len({results[i]["token_id"] for i in winners}) == k          # distinct tokens
    assert all(results[i]["generation"] == 1 for i in winners)
    # the committed total of the grant never passes its limit
    total, count_cu = await led.conn.fetchrow(
        "SELECT coalesce(sum(amount),0), count(*) FILTER (WHERE counts_create_update) FROM change_ledger.reservations "
        "WHERE grant_id=$1 AND state IN ('RESERVED','CONSUMED')", gid)
    limit_check(total, count_cu)
    for i in winners:
        rec = await led.rec(cids[i])
        assert (rec["authorization_state"], rec["claim_generation"], rec["reservation_state"]) == ("CLAIMED", 1, "RESERVED")
        assert await led.locks(cids[i]) == (1, 1, 1)
    for i in losers:      # nothing of a refused claim may leak: locks, reservation, state, claimed event
        rec = await led.rec(cids[i])
        assert (rec["authorization_state"], rec["claim_generation"]) == ("APPROVED", 0), (i, dict(rec))
        assert await led.locks(cids[i]) == (0, 0, 0)
        assert await led.res_state(cids[i]) is None
    n_claimed = await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
                                        "AND event_type='CLAIMED' AND change_id = ANY($3::uuid[])", T, C, cids)
    assert n_claimed == k
    chain = await led.call("clt_aud", "verify_chain")
    assert chain["ok"] is True, chain


# ---------------------------------------------------------------- boundary matrix: amount limit
@pytest.mark.parametrize("limit,k", [(5 * UNIT - 1, 4), (5 * UNIT, 5), (5 * UNIT + 1, 5)],
                         ids=["limit-minus-one-unit", "exactly-limit", "limit-plus-one-unit"])
async def test_amount_limit_boundary_admits_exactly_k_of_n_processes(led, limit, k):
    gid = await make_grant(led, limit)
    cids = await make_changes(led, N, gid, UNIT, False)
    results = await race(led, cids)
    assert len(results) == N and sum(1 for r in results.values() if r["ok"]) == k, results

    def under_limit(total, _count_cu):
        assert total == k * UNIT and total <= limit, (total, limit)
    await assert_consistent(led, cids, results, gid, k, under_limit)
    # the grant is really full: one more claim of a refused change still fails with the stable error
    loser = next(i for i, r in results.items() if not r["ok"])
    assert (await led.conn.fetchval("SELECT count(*) FROM change_ledger.reservations WHERE grant_id=$1", gid)) == k
    with pytest.raises(asyncpg.PostgresError, match=STABLE_ERROR):
        await led.claimed(cids[loser], observe=False)


# ---------------------------------------------------------------- boundary matrix: reservation-count limit
@pytest.mark.parametrize("count_limit,k", [(4, 4), (5, 5), (6, 6)],
                         ids=["count-limit-minus-one", "count-exactly-limit", "count-limit-plus-one"])
async def test_count_limit_boundary_admits_exactly_k_of_n_processes(led, count_limit, k):
    gid = await make_grant(led, amount_limit=1_000_000, count_limit=count_limit)
    cids = await make_changes(led, N, gid, 1, True)
    results = await race(led, cids)

    def under_limit(total, count_cu):
        assert count_cu == k <= count_limit and total == k, (count_cu, total)
    await assert_consistent(led, cids, results, gid, k, under_limit)


# ---------------------------------------------------------------- abandoned reserver releases capacity
@pytest.mark.parametrize("how", ["rollback", "kill"])
async def test_abandoned_reserver_releases_its_capacity_to_the_waiters(led, how):
    k, racers = 3, 7                                   # 8 processes: 1 holder + 7 racers, capacity for exactly 3
    gid = await make_grant(led, k * UNIT)
    cids = await make_changes(led, racers + 1, gid, UNIT, False)
    sw = Swarm()
    try:
        # the holder claims first and keeps its transaction (and the grant row lock) open
        sw.start(await spec_for(led, 0, cids[0], hold=True))
        await sw.pump_until(lambda: 0 in sw.claimed_open, what="holder claim inside an open transaction")
        assert sw.claimed_open[0]["ok"]
        for i in range(1, racers + 1):
            sw.start(await spec_for(led, i, cids[i]))
        await sw.pump_until(lambda: len(sw.ready) == racers + 1, what="all racers ready")
        # every racer is queued behind the holder's grant row lock inside change_ledger.claim
        await wait_for(led.conn, "SELECT count(*) FROM pg_stat_activity WHERE datname=$1 AND wait_event_type='Lock' "
                       "AND state='active' AND query LIKE '%change_ledger.claim(%'", racers,
                       "racers blocked behind the holder", WAIT, led.db.name)
        await sw.drain_nowait()
        assert not [i for i in sw.results if i != 0], "a racer finished while the holder still held the grant"
        # nothing of the holder is visible to others before it ends (uncommitted)
        assert await led.res_state(cids[0]) is None
        if how == "rollback":
            sw.cmds[0].send("rollback")
            await sw.pump_until(lambda: 0 in sw.results, what="holder rollback result")
        else:
            sw.procs[0].kill()                          # abrupt death: no rollback, no cleanup code runs
            await asyncio.to_thread(sw.procs[0].join, 30)
        await sw.pump_until(lambda: set(range(1, racers + 1)) <= set(sw.results), what="racers finished")
    finally:
        sw.reap()
    results = {i: sw.results[i] for i in range(1, racers + 1)}
    winners = [i for i, r in results.items() if r["ok"]]
    # the released slot is reusable: all K slots go to the racers (would be K-1 if the holder had leaked its slot)
    assert len(winners) == k, results
    for i, r in results.items():
        if not r["ok"]:
            assert r["err"] == STABLE_ERROR, (i, r)
    rows = await reserved_rows(led, cids)
    assert set(rows) == {cids[i] for i in winners} and cids[0] not in rows
    total = await led.conn.fetchval("SELECT coalesce(sum(amount),0) FROM change_ledger.reservations "
                                    "WHERE grant_id=$1 AND state IN ('RESERVED','CONSUMED')", gid)
    assert total == k * UNIT
    rec = await led.rec(cids[0])      # the holder's change is intact and unreserved, no lock leaked
    assert (rec["authorization_state"], rec["claim_generation"]) == ("APPROVED", 0)
    assert await led.locks(cids[0]) == (0, 0, 0)
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True
    # the grant is full now: the abandoned change cannot reserve either (no phantom capacity)
    with pytest.raises(asyncpg.PostgresError, match=STABLE_ERROR):
        await led.claimed(cids[0], observe=False)


# ---------------------------------------------------------------- duplicates: the same change claimed concurrently
async def test_same_change_claimed_by_several_processes_reserves_exactly_once(led):
    gid = await make_grant(led, UNIT)                  # room for exactly ONE reservation: a duplicate would refuse
    cid = (await make_changes(led, 1, gid, UNIT, True))[0]
    results = await race(led, [cid] * 5)
    assert all(r["ok"] for r in results.values()), results          # replay of a live claim, never BUDGET_EXCEEDED
    assert len({r["token_id"] for r in results.values()}) == 1
    assert {r["generation"] for r in results.values()} == {1}
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.reservations WHERE change_id=$1", cid) == 1
    assert await led.res_state(cid) == "RESERVED"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.claim_tokens WHERE change_id=$1", cid) == 1
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND "
                                   "event_type='CLAIMED'", cid) == 1
    assert (await led.rec(cid))["claim_generation"] == 1
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True

