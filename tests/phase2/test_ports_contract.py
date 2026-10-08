# ruff: noqa: C408 - dict(...) kwargs are the deliberate case-override style here
"""Shared port contract: ONE test body, run against the in-memory fake AND the real living.* SQL API.

Every test takes the ``h`` fixture parametrised over ``fake`` and ``sql``. The ``sql`` variant is
marked ``integration`` and needs ERP_PHASE2_TEST_DSN (skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1, see _pg_harness.require_dsn); each test gets its own throwaway database.
SQL is the source of truth: a failing ``fake`` variant means the fake is wrong.

Mutation-style rule: each guard has at least one test whose only failure cause is that guard, with
the specific error code asserted, so removing the guard from the fake (or from the SQL) turns that
test red. Time: the fake uses an injected clock; for SQL, ``h.warp`` moves job/outbox leases into
the past and ``h.sleep_until`` waits until the STORE clock passes a timestamp (only for attestation /
reviewer expiry, which cannot be warped in SQL), so slow setup can never make a test flaky.

Scope epochs: ``bump_scope_epoch`` / ``grant_scope`` / ``revoke_scope`` / ``rebase_scope`` exist on
both implementations (SQL: the real role_scope trigger and the owner-only living.* functions).
The two-connection race tests at the bottom are SQL-only; they hold the source row lock from a
third connection until both racers are provably blocked on it, so the overlap is real, not timing.
"""
import asyncio
import pickle
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from _pg_harness import require_dsn, throwaway_db
from _sql_ports import SqlLiving

from business_ai_gateway.phase2.fakes import FakeClock, InMemoryLiving
from business_ai_gateway.phase2.ports import (
    OMITTED,
    CursorOutboxPort,
    HeadAttestationPort,
    JobQueuePort,
    LedgerPort,
    OutboxRow,
    PortError,
    Scope,
    event_digest,
    evidence_digest,
    page_digest,
)

S = Scope("A", "s1")
S3, B = Scope("A", "s3"), Scope("B", "s1")  # sources that exist in the seed but nobody is granted
W, P, PUB, R = "living_worker", "living_promoter", "living_publisher", "living_reader"
PAST = datetime(2020, 1, 1, tzinfo=UTC)
D1, D2 = "1" * 64, "2" * 64
OBS_AT = datetime(2024, 1, 2, tzinfo=UTC)
E1, E2 = datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


class Harness:
    def __init__(self, kind, ports, db=None):
        self.kind, self.p, self.db = kind, ports, db

    async def warp(self, seconds):
        if self.kind == "fake":
            self.p.clock.advance(seconds)
        else:
            await self.p.warp(seconds)

    async def sleep_until(self, ts):
        """Return once the store clock is strictly after ``ts`` (fake: jump; SQL: wait the remainder)."""
        while (remaining := (ts - await self.p.now()).total_seconds()) >= 0:
            if self.kind == "fake":
                self.p.clock.advance(remaining + 0.01)
            else:
                await asyncio.sleep(remaining + 0.02)


@pytest.fixture(params=["fake", pytest.param("sql", marks=pytest.mark.integration)])
async def h(request):
    if request.param == "fake":
        yield Harness("fake", InMemoryLiving(FakeClock()))
        return
    dsn = require_dsn()
    async with throwaway_db(dsn) as db:
        yield Harness("sql", SqlLiving(db.conn), db)


async def rejected(code, awaitable):
    with pytest.raises(PortError) as ei:
        await awaitable
    assert ei.value.code == code, ei.value
    return ei.value


async def ing(h, obj, rev=None, kind="OBSERVED", digest=D1, eff=None, supersedes=None, obs_id=None,
              observed_at=OBS_AT, prov=OMITTED):
    obs_id, rev = obs_id or uuid.uuid4(), rev or uuid.uuid4()
    got = await h.p.ingest_observation(W, S, obs_id, obj, rev, kind, digest, eff, observed_at,
                                       supersedes, prov)
    return got, rev


def ev(eid, n=1):
    e = {"event_id": eid, "n": n}
    e["digest"] = event_digest(e)
    return e


def test_fake_implements_every_port():
    fake = InMemoryLiving()
    for port in (LedgerPort, JobQueuePort, CursorOutboxPort, HeadAttestationPort):
        assert isinstance(fake, port)
    # the canonical digest helpers are checked against SQL by the INVALID_OUTBOX_EVENT / replay tests
    assert event_digest({"event_id": "e", "n": 1}) == event_digest({"n": 1, "digest": "x",
                                                                    "event_id": "e"})


# =============================================================================== ledger
@pytest.mark.parametrize("code,kw", [
    ("CONFLICTING_DIGEST", dict(digest=D2)),
    ("REVISION_REUSED", dict(obj="other")),
    ("REVISION_REUSED", dict(kind="GAP")),
    ("CONFLICTING_OBSERVATION", dict(eff=E1)),
    ("CONFLICTING_OBSERVATION", dict(observed_at=OBS_AT - timedelta(days=1))),
    ("CONFLICTING_OBSERVATION", dict(prov={"a": 1})),
], ids=lambda v: v if isinstance(v, str) else "")
async def test_ingest_replay_must_match_the_stored_revision(h, code, kw):
    first, rev = await ing(h, "o1")
    again, _ = await ing(h, "o1", rev=rev)  # identical content, new observation id: idempotent
    assert again == first
    args = dict(obj="o1", rev=rev) | kw
    await rejected(code, ing(h, **args))


@pytest.mark.parametrize("code,kw", [
    ("INVALID_OBSERVATION", dict(obj="")),
    ("SUPERSEDES_OBJECT_MISMATCH", dict(supersedes=uuid.uuid4())),
    ("CHECK_VIOLATION", dict(kind="BOGUS", digest=None)),
    ("CHECK_VIOLATION", dict(digest=None)),
    ("CHECK_VIOLATION", dict(digest="xyz")),
    ("CHECK_VIOLATION", dict(observed_at=FUTURE)),
])
async def test_ingest_rejects_invalid_observations(h, code, kw):
    await rejected(code, ing(h, **(dict(obj="o1") | kw)))
    assert await h.p.as_known_at(W, S, await h.p.now()) == ()


async def test_ingest_supersedes_must_reference_same_object(h):
    first, _ = await ing(h, "o1")
    await rejected("SUPERSEDES_OBJECT_MISMATCH", ing(h, "o2", supersedes=first))
    await ing(h, "o1", digest=D2, supersedes=first)


async def test_ingest_rejects_duplicate_observation_id(h):
    first, _ = await ing(h, "o1")
    await rejected("UNIQUE_VIOLATION", ing(h, "o2", obs_id=first))


async def test_as_known_at_is_bitemporal_and_flags_availability_and_revocation(h):
    p = h.p
    k0 = await p.now()
    o1, _ = await ing(h, "o1", digest=D1, eff=E1)
    k1 = await p.now()
    await ing(h, "o1", digest=D2, eff=E1, supersedes=o1)
    k2 = await p.now()
    await ing(h, "o1", kind="GAP", digest=None)
    k3 = await p.now()
    await ing(h, "o1", kind="ATTESTATION_REVOKED", digest=None)
    k4 = await p.now()

    async def head(k):
        (row,) = await p.as_known_at(W, S, k)
        return row.observation.digest, row.available, row.latest_kind, row.revoked

    assert await p.as_known_at(W, S, k0) == ()
    assert await head(k1) == (D1, True, "OBSERVED", False)        # correction not yet known
    assert await head(k2) == (D2, True, "OBSERVED", False)
    assert await head(k3) == (D2, False, "GAP", False)            # GAP never hides the OBSERVED row
    assert await head(k4) == (D2, False, "ATTESTATION_REVOKED", True)
    assert await head(k1) == (D1, True, "OBSERVED", False)        # an old slice never changes


async def test_as_known_at_object_without_observed_row_is_unavailable(h):
    await ing(h, "gap", kind="GAP", digest=None)
    (row,) = await h.p.as_known_at(W, S, await h.p.now())
    assert (row.observation.kind, row.available, row.latest_kind) == ("GAP", False, "GAP")


async def test_as_effective_at_flags_undated_rows_and_picks_by_effective_time(h):
    p = h.p
    await ing(h, "o1", digest=D1, eff=E1)
    await ing(h, "o1", digest=D2, eff=E2)
    await ing(h, "o2", digest=D1, eff=None)
    await ing(h, "o3", digest=D1, eff=datetime(2024, 3, 1, tzinfo=UTC))
    k = await p.now()

    async def view(valid):
        rows = await p.as_effective_at(W, S, valid, k)
        return [(r.observation.object_id, r.effective_unknown, r.observation.digest, r.revoked)
                for r in rows]

    assert await view(datetime(2024, 1, 15, tzinfo=UTC)) == [
        ("o1", False, D1, False), ("o2", True, D1, False)]
    assert await view(datetime(2024, 2, 15, tzinfo=UTC)) == [
        ("o1", False, D2, False), ("o2", True, D1, False)]
    await ing(h, "o1", kind="ATTESTATION_REVOKED", digest=None)
    k = await p.now()
    assert (await view(datetime(2024, 2, 15, tzinfo=UTC)))[0] == ("o1", False, D2, True)


async def test_future_knowledge_cutoff_is_not_settled(h):
    await rejected("KNOWLEDGE_HORIZON_NOT_SETTLED", h.p.as_known_at(W, S, FUTURE))
    await rejected("KNOWLEDGE_HORIZON_NOT_SETTLED", h.p.as_effective_at(W, S, E1, FUTURE))


# =============================================================================== job queue
async def start_job(h, key="k1", lease=30, worker="w1"):
    j = uuid.uuid4()
    assert await h.p.enqueue_job(W, S, j, "sync", "c" * 64, key) == j
    return j, await h.p.acquire_job(W, S, j, worker, lease)


async def reacquired_after_lost_lease(h):
    """w1 holds fence 1, loses the lease, is reaped and re-acquires as fence 2."""
    p = h.p
    j, f1 = await start_job(h)
    await h.warp(31)
    assert await p.reap_expired_jobs(W, S) == 1
    await h.warp(3)  # past the 2 s backoff
    f2 = await p.acquire_job(W, S, j, "w1", 30)
    assert (f1, f2) == (1, 2)
    return j, f1, f2


async def test_enqueue_is_idempotent_per_key_and_digest(h):
    p = h.p
    j = uuid.uuid4()
    assert await p.enqueue_job(W, S, j, "sync", "c" * 64, "k1") == j
    assert await p.enqueue_job(W, S, uuid.uuid4(), "sync", "c" * 64, "k1") == j
    await rejected("IDEMPOTENCY_CONFLICT", p.enqueue_job(W, S, uuid.uuid4(), "sync", "d" * 64, "k1"))
    view = await p.get_job(W, S, j)
    assert (view.state, view.fence, view.attempt, view.lease_owner) == ("PENDING", 0, 0, None)


@pytest.mark.parametrize("kw", [dict(request_digest="short"), dict(job_kind=""),
                                dict(idempotency_key=""), dict(job_id=None)])
async def test_enqueue_rejects_invalid_jobs(h, kw):
    args = dict(job_id=uuid.uuid4(), job_kind="sync", request_digest="c" * 64,
                idempotency_key="k") | kw
    await rejected("INVALID_JOB", h.p.enqueue_job(W, S, **args))


async def test_acquire_gives_a_fence_and_only_one_job_runs_per_source(h):
    p = h.p
    j, fence = await start_job(h)
    assert fence == 1
    view = await p.get_job(W, S, j)
    assert (view.state, view.lease_owner, view.fence, view.attempt) == ("RUNNING", "w1", 1, 1)
    other = uuid.uuid4()
    await p.enqueue_job(W, S, other, "sync", "c" * 64, "k2")
    await rejected("JOB_UNAVAILABLE", p.acquire_job(W, S, other, "w2", 30))   # source is busy
    await rejected("JOB_UNAVAILABLE", p.acquire_job(W, S, j, "w2", 30))       # already running


async def test_acquire_unknown_job_is_unavailable(h):
    await rejected("JOB_UNAVAILABLE", h.p.acquire_job(W, S, uuid.uuid4(), "w1", 30))


@pytest.mark.parametrize("kw", [dict(lease_seconds=0), dict(lease_seconds=301),
                                dict(lease_seconds=None), dict(worker=""), dict(job_id=None)])
async def test_acquire_rejects_invalid_lease_arguments(h, kw):
    j = uuid.uuid4()
    await h.p.enqueue_job(W, S, j, "sync", "c" * 64, "k1")
    args = dict(job_id=j, worker="w1", lease_seconds=30) | kw
    await rejected("INVALID_LEASE", h.p.acquire_job(W, S, **args))


async def test_finish_job_rejects_a_stale_fence(h):
    p = h.p
    j, f1, f2 = await reacquired_after_lost_lease(h)
    await rejected("STALE_JOB_FENCE", p.finish_job(W, S, j, "w1", f1, "SUCCEEDED"))
    assert (await p.get_job(W, S, j)).state == "RUNNING"
    await p.finish_job(W, S, j, "w1", f2, "SUCCEEDED")                         # positive control
    assert (await p.get_job(W, S, j)).state == "SUCCEEDED"


async def test_renew_lease_rejects_a_stale_fence(h):
    p = h.p
    j, f1, f2 = await reacquired_after_lost_lease(h)
    await rejected("STALE_JOB_FENCE", p.renew_lease(W, S, j, "w1", f1, 30))
    assert await p.renew_lease(W, S, j, "w1", f2, 30) > await p.now()           # positive control


async def test_commit_page_rejects_a_stale_fence_and_leaves_the_cursor_alone(h):
    p = h.p
    await p.create_cursor(W, S, "conn", "p0")
    j, f1, f2 = await reacquired_after_lost_lease(h)
    ep = await p.scope_epoch(S)
    await rejected("STALE_JOB_FENCE",
                   p.commit_cursor_page(W, S, "conn", j, "w1", f1, "p0", 0, ep, "p1", [ev("e1")]))
    cur = await p.get_cursor(W, S, "conn")
    assert (cur.cursor_value, cur.version) == ("p0", 0) and await p.list_outbox(W, S) == ()
    res = await p.commit_cursor_page(W, S, "conn", j, "w1", f2, "p0", 0, ep, "p1", [ev("e1")])
    assert (res.version, res.replayed) == (1, False)                           # positive control


async def test_job_calls_reject_the_wrong_worker_even_with_the_right_fence(h):
    p = h.p
    j, fence = await start_job(h)
    await rejected("STALE_JOB_FENCE", p.finish_job(W, S, j, "intruder", fence, "SUCCEEDED"))
    await rejected("STALE_JOB_FENCE", p.renew_lease(W, S, j, "intruder", fence, 30))


async def test_an_expired_lease_cannot_finish_renew_or_commit_before_it_is_reaped(h):
    p = h.p
    await p.create_cursor(W, S, "conn", "p0")
    j, fence = await start_job(h, lease=5)
    ep = await p.scope_epoch(S)
    await h.warp(6)
    await rejected("STALE_JOB_FENCE", p.finish_job(W, S, j, "w1", fence, "SUCCEEDED"))
    await rejected("STALE_JOB_FENCE", p.renew_lease(W, S, j, "w1", fence, 30))
    await rejected("STALE_JOB_FENCE",
                   p.commit_cursor_page(W, S, "conn", j, "w1", fence, "p0", 0, ep, "p1", []))
    assert (await p.get_job(W, S, j)).state == "RUNNING"   # nobody reaped it yet


async def test_renew_extends_the_live_lease(h):
    p = h.p
    j, fence = await start_job(h, lease=5)
    before = (await p.get_job(W, S, j)).lease_until
    until = await p.renew_lease(W, S, j, "w1", fence, 200)
    assert until > before and (await p.get_job(W, S, j)).lease_until == until


@pytest.mark.parametrize("kw", [dict(lease_seconds=0), dict(lease_seconds=301), dict(worker="")])
async def test_renew_rejects_invalid_lease_arguments(h, kw):
    j, fence = await start_job(h)
    args = dict(job_id=j, worker="w1", fence=fence, lease_seconds=30) | kw
    await rejected("INVALID_LEASE", h.p.renew_lease(W, S, **args))


async def test_reap_moves_expired_jobs_to_pending_with_backoff(h):
    p = h.p
    j, _ = await start_job(h, lease=10)
    assert await p.reap_expired_jobs(W, S) == 0            # live lease untouched
    assert (await p.get_job(W, S, j)).state == "RUNNING"
    await h.warp(11)
    assert await p.reap_expired_jobs(W, S) == 1
    view = await p.get_job(W, S, j)
    assert (view.state, view.lease_owner, view.lease_until, view.last_error) == (
        "PENDING", None, None, "LEASE_EXPIRED")
    await rejected("JOB_UNAVAILABLE", p.acquire_job(W, S, j, "w1", 30))   # backoff not elapsed
    await h.warp(3)
    assert await p.acquire_job(W, S, j, "w1", 30) == 2


async def test_a_rejected_acquire_rolls_back_the_reap_it_did(h):
    p = h.p
    j, _ = await start_job(h, lease=5)
    await h.warp(6)
    await rejected("JOB_UNAVAILABLE", p.acquire_job(W, S, j, "w2", 30))   # reaped, then backoff blocks
    view = await p.get_job(W, S, j)
    assert (view.state, view.lease_owner, view.last_error) == ("RUNNING", "w1", None)


async def test_a_job_that_keeps_losing_its_lease_becomes_poison_after_max_attempts(h):
    p = h.p
    j = uuid.uuid4()
    await p.enqueue_job(W, S, j, "sync", "c" * 64, "poison")
    for attempt in range(1, 6):
        assert await p.acquire_job(W, S, j, "w1", 10) == attempt
        assert (await p.get_job(W, S, j)).attempt == attempt
        await h.warp(11)
        assert await p.reap_expired_jobs(W, S) == 1
        view = await p.get_job(W, S, j)
        assert view.state == ("FAILED" if attempt == 5 else "PENDING")
        assert view.last_error == "LEASE_EXPIRED" and view.max_attempts == 5
        await h.warp(301)
    await rejected("JOB_UNAVAILABLE", p.acquire_job(W, S, j, "w1", 10))
    view = await p.get_job(W, S, j)
    assert (view.state, view.attempt, view.fence) == ("FAILED", 5, 5)


@pytest.mark.parametrize("state,err,stored", [("SUCCEEDED", "ignored", None),
                                              ("FAILED", "boom", "boom"),
                                              ("CANCELLED", "stop", "stop")])
async def test_finish_job_records_terminal_state_and_frees_the_source(h, state, err, stored):
    p = h.p
    j, fence = await start_job(h)
    await p.finish_job(W, S, j, "w1", fence, state, err)
    view = await p.get_job(W, S, j)
    assert (view.state, view.lease_owner, view.lease_until, view.last_error) == (
        state, None, None, stored)
    await rejected("STALE_JOB_FENCE", p.finish_job(W, S, j, "w1", fence, state))   # terminal
    await rejected("JOB_UNAVAILABLE", p.acquire_job(W, S, j, "w1", 30))
    nxt = uuid.uuid4()
    await p.enqueue_job(W, S, nxt, "sync", "c" * 64, "k2")
    assert await p.acquire_job(W, S, nxt, "w1", 30) == 1                           # slot is free


async def test_finish_job_rejects_unknown_terminal_state(h):
    j, fence = await start_job(h)
    await rejected("INVALID_TERMINAL_STATE", h.p.finish_job(W, S, j, "w1", fence, "RUNNING"))
    await rejected("INVALID_TERMINAL_STATE", h.p.finish_job(W, S, j, "w1", fence, None))


async def test_job_calls_need_the_worker_role(h):
    await rejected("PERMISSION_DENIED", h.p.enqueue_job(PUB, S, uuid.uuid4(), "k", "c" * 64, "x"))


# =============================================================================== cursor + outbox
async def cursor_job(h, lease=60):
    await h.p.create_cursor(W, S, "conn", "p0")
    return await start_job(h, lease=lease)


async def commit(h, j, f, events, prior="p0", pv=0, new="p1", worker="w1", conn="conn", epoch=None):
    ep = await h.p.scope_epoch(S) if epoch is None else epoch
    return await h.p.commit_cursor_page(W, S, conn, j, worker, f, prior, pv, ep, new, events)


async def test_create_cursor_is_idempotent_and_never_moves_an_existing_cursor(h):
    p = h.p
    assert await p.create_cursor(W, S, "conn", "p0") == 0
    assert await p.create_cursor(W, S, "conn", "other") == 0
    assert (await p.get_cursor(W, S, "conn")).cursor_value == "p0"
    await rejected("INVALID_ARGUMENT", p.create_cursor(W, S, "", "p0"))
    await rejected("INVALID_ARGUMENT", p.create_cursor(W, S, "c", None))


async def test_commit_page_advances_the_cursor_and_fills_the_outbox(h):
    p = h.p
    j, f = await cursor_job(h)
    page1 = [ev("e1"), ev("e2")]
    res = await commit(h, j, f, page1)
    assert (res.version, res.replayed) == (1, False)
    cur = await p.get_cursor(W, S, "conn")
    assert (cur.cursor_value, cur.version) == ("p1", 1)
    assert cur.last_page_digest == page_digest("p0", "p1", page1)     # canonical form equals SQL's
    rows = await p.list_outbox(W, S)
    assert [(r.event_id, r.status, r.attempts, r.claim_generation) for r in rows] == [
        ("e1", "PENDING", 0, 0), ("e2", "PENDING", 0, 0)]
    assert rows[0].content == page1[0] and rows[0].event_digest == event_digest(page1[0])
    assert (await commit(h, j, f, [ev("e1"), ev("e3")], "p1", 1, "p2")).version == 2
    assert [r.event_id for r in await p.list_outbox(W, S)] == ["e1", "e2", "e3"]  # e1 deduped


async def test_identical_page_replay_is_an_idempotent_no_op(h):
    p = h.p
    j, f = await cursor_job(h)
    page = [ev("e1"), ev("e2")]
    await commit(h, j, f, page)
    before = await p.list_outbox(W, S)
    res = await commit(h, j, f, [dict(reversed(list(e.items()))) for e in page])  # key order irrelevant
    assert (res.version, res.replayed) == (1, True)
    assert await p.list_outbox(W, S) == before
    assert (await p.get_cursor(W, S, "conn")).version == 1


async def test_conflicting_page_replay_is_rejected(h):
    p = h.p
    j, f = await cursor_job(h)
    await commit(h, j, f, [ev("e1")])
    await rejected("CONFLICTING_PAGE_REPLAY", commit(h, j, f, [ev("e1"), ev("e2")]))
    await rejected("CONFLICTING_PAGE_REPLAY", commit(h, j, f, [ev("e1", n=2)]))
    await rejected("CONFLICTING_PAGE_REPLAY", commit(h, j, f, []))
    assert [r.event_id for r in await p.list_outbox(W, S)] == ["e1"]
    assert (await p.get_cursor(W, S, "conn")).version == 1


async def test_replay_still_needs_a_live_job_fence(h):
    j, f = await cursor_job(h)
    await commit(h, j, f, [ev("e1")])
    await rejected("STALE_JOB_FENCE", commit(h, j, f + 1, [ev("e1")]))


async def test_conflicting_event_content_rolls_back_the_whole_page(h):
    p = h.p
    j, f = await cursor_job(h)
    await commit(h, j, f, [ev("e1", n=1)])
    await rejected("CONFLICTING_EVENT_DIGEST",
                   commit(h, j, f, [ev("e0"), ev("e1", n=2)], "p1", 1, "p2"))
    cur = await p.get_cursor(W, S, "conn")
    assert (cur.cursor_value, cur.version) == ("p1", 1)
    rows = await p.list_outbox(W, S)
    assert [(r.event_id, r.content["n"]) for r in rows] == [("e1", 1)]


_BAD_NO_ID = {"n": 1}
_BAD_NO_ID["digest"] = event_digest(_BAD_NO_ID)


@pytest.mark.parametrize("code,kw", [
    ("CURSOR_NOT_FOUND", dict(conn="nope")),
    ("SCOPE_REVOKED", dict(epoch=7)),
    ("INVALID_ARGUMENT", dict(prior=None)),
    ("INVALID_ARGUMENT", dict(pv=None)),
    ("INVALID_CURSOR_BATCH", dict(new="")),
    ("INVALID_CURSOR_BATCH", dict(events=None)),
    ("INVALID_CURSOR_BATCH", dict(events="not-an-array")),
    ("INVALID_OUTBOX_EVENT", dict(events=[{"event_id": "e1", "digest": "0" * 64}])),
    ("INVALID_OUTBOX_EVENT", dict(events=[{"event_id": "e1"}])),
    ("INVALID_OUTBOX_EVENT", dict(events=[_BAD_NO_ID])),
    ("STALE_CURSOR_OR_SCOPE", dict(prior="elsewhere")),
    ("STALE_CURSOR_OR_SCOPE", dict(pv=5)),
    ("STALE_JOB_FENCE", dict(worker="other")),
    ("STALE_JOB_FENCE", dict(fence_delta=1)),
], ids=lambda v: v if isinstance(v, str) else "")
async def test_commit_page_rejections_leave_the_cursor_and_outbox_untouched(h, code, kw):
    p = h.p
    j, f = await cursor_job(h)
    kw = dict(kw)
    f += kw.pop("fence_delta", 0)
    events = kw.pop("events", [ev("e1")])
    await rejected(code, commit(h, j, f, events, **kw))
    cur = await p.get_cursor(W, S, "conn")
    assert (cur.cursor_value, cur.version, cur.last_page_digest) == ("p0", 0, None)
    assert await p.list_outbox(W, S) == ()


async def test_commit_page_with_a_missing_job_is_a_stale_fence(h):
    await h.p.create_cursor(W, S, "conn", "p0")
    await rejected("STALE_JOB_FENCE", commit(h, uuid.uuid4(), 1, [ev("e1")]))


async def outbox_with_events(h, *eids):
    j, f = await cursor_job(h)
    await commit(h, j, f, [ev(e) for e in eids])


async def test_claim_outbox_leases_in_seq_order_with_attempt_and_generation(h):
    p = h.p
    await outbox_with_events(h, "e1", "e2", "e3")
    first = await p.claim_outbox(PUB, S, 2, 30)
    assert [(r.event_id, r.attempts, r.claim_generation, r.lease_owner) for r in first] == [
        ("e1", 1, 1, PUB), ("e2", 1, 1, PUB)]
    rest = await p.claim_outbox(PUB, S, 5, 30)                     # leased rows are not claimable
    assert [r.event_id for r in rest] == ["e3"]
    assert await p.claim_outbox(PUB, S, 5, 30) == ()


@pytest.mark.parametrize("kw", [dict(limit=0), dict(limit=1001), dict(lease_seconds=0),
                                dict(lease_seconds=301), dict(max_attempts=0),
                                dict(max_attempts=21)])
async def test_claim_outbox_rejects_invalid_arguments(h, kw):
    args = dict(limit=5, lease_seconds=30, max_attempts=5) | kw
    await rejected("INVALID_ARGUMENT", h.p.claim_outbox(PUB, S, **args))


async def test_outbox_api_is_for_publishers_only(h):
    await outbox_with_events(h, "e1")
    await rejected("PERMISSION_DENIED", h.p.claim_outbox(W, S, 5, 30))
    await rejected("PERMISSION_DENIED", h.p.finish_outbox(W, S, "conn", "e1", 1, True))


async def test_finish_outbox_needs_the_current_claim_generation(h):
    p = h.p
    await outbox_with_events(h, "e1")
    (c1,) = await p.claim_outbox(PUB, S, 1, 30)
    await h.warp(31)                                              # lease expires, same publisher
    (c2,) = await p.claim_outbox(PUB, S, 1, 30)                    # re-claims
    assert (c1.claim_generation, c2.claim_generation, c2.attempts) == (1, 2, 2)
    await rejected("STALE_OUTBOX_LEASE", p.finish_outbox(PUB, S, "conn", "e1", 1, True))
    assert (await p.list_outbox(W, S))[0].status == "PENDING"
    await p.finish_outbox(PUB, S, "conn", "e1", 2, True)           # positive control
    assert (await p.list_outbox(W, S))[0].status == "DELIVERED"


async def test_finish_outbox_needs_the_lease_owner(h):
    p = h.p
    await p.define_actor("p2c_publisher2", (PUB,))
    await outbox_with_events(h, "e1")
    (c,) = await p.claim_outbox(PUB, S, 1, 30)
    await rejected("STALE_OUTBOX_LEASE",
                   p.finish_outbox("p2c_publisher2", S, "conn", "e1", c.claim_generation, True))
    await p.finish_outbox(PUB, S, "conn", "e1", c.claim_generation, True)


async def test_finish_outbox_needs_a_live_lease(h):
    p = h.p
    await outbox_with_events(h, "e1")
    (c,) = await p.claim_outbox(PUB, S, 1, 5)
    await h.warp(6)
    await rejected("STALE_OUTBOX_LEASE", p.finish_outbox(PUB, S, "conn", "e1", c.claim_generation, True))


async def test_finish_outbox_transitions_are_one_way(h):
    p = h.p
    await outbox_with_events(h, "e1")
    await rejected("STALE_OUTBOX_LEASE", p.finish_outbox(PUB, S, "conn", "e1", 1, True))  # unclaimed
    (c,) = await p.claim_outbox(PUB, S, 1, 30)
    await p.finish_outbox(PUB, S, "conn", "e1", c.claim_generation, True)
    await rejected("OUTBOX_INVALID_TRANSITION",
                   p.finish_outbox(PUB, S, "conn", "e1", c.claim_generation, True))
    await rejected("OUTBOX_EVENT_NOT_FOUND", p.finish_outbox(PUB, S, "conn", "nope", 1, True))
    await rejected("INVALID_ARGUMENT", p.finish_outbox(PUB, S, "conn", "e1", None, True))
    await rejected("INVALID_ARGUMENT", p.finish_outbox(PUB, S, "conn", "e1", 1, None))
    assert await p.claim_outbox(PUB, S, 5, 30) == ()               # delivered is never claimed again


async def test_failed_delivery_retries_then_fails_after_max_attempts(h):
    p = h.p
    await outbox_with_events(h, "e1")
    (c1,) = await p.claim_outbox(PUB, S, 1, 30, 2)
    await p.finish_outbox(PUB, S, "conn", "e1", c1.claim_generation, False, 2)
    row = (await p.list_outbox(W, S))[0]
    assert (row.status, row.attempts, row.lease_owner, row.lease_until) == ("PENDING", 1, None, None)
    (c2,) = await p.claim_outbox(PUB, S, 1, 30, 2)
    assert (c2.attempts, c2.claim_generation) == (2, 2)
    await p.finish_outbox(PUB, S, "conn", "e1", c2.claim_generation, False, 2)
    assert (await p.list_outbox(W, S))[0].status == "FAILED"
    assert await p.claim_outbox(PUB, S, 5, 30, 2) == ()


async def test_claim_marks_attempt_exhausted_pending_rows_failed(h):
    p = h.p
    await outbox_with_events(h, "e1")
    (c,) = await p.claim_outbox(PUB, S, 1, 30)
    await p.finish_outbox(PUB, S, "conn", "e1", c.claim_generation, False)      # back to PENDING
    assert await p.claim_outbox(PUB, S, 5, 30, 1) == ()                          # attempts 1 >= max 1
    assert (await p.list_outbox(W, S))[0].status == "FAILED"


# =============================================================================== heads + attestations
async def attested(h, evidence="ev1", proposer="prop", decision="APPROVE", expires=FUTURE,
                   actor=W, model="m1", digest=D1):
    """Revision r (OBSERVED) + head `model` + one attestation; returns (revision, attestation id)."""
    p = h.p
    _, rev = await ing(h, "o1", digest=digest, eff=E1)
    await p.create_head(P, S, model)
    att = uuid.uuid4()
    await p.record_attestation(actor, S, att, rev, proposer, evidence,
                               evidence_digest(digest, evidence), decision, expires)
    return rev, att


async def test_promote_head_happy_path_and_acceptance_replay(h):
    p = h.p
    rev, _ = await attested(h)
    assert await p.create_head(P, S, "m1") == 0                    # idempotent
    acc = uuid.uuid4()
    assert await p.promote_head(P, S, "m1", 0, rev, acc, "ev1") == 1
    head = await p.get_head(P, S, "m1")
    assert (head.revision_id, head.version) == (rev, 1)
    (ev1,) = await p.list_acceptances(P, S)
    assert (ev1.approver_subject, ev1.from_version, ev1.to_version, ev1.independent_evidence_ref) == (
        P, 0, 1, "ev1")
    assert await p.promote_head(P, S, "m1", 0, rev, acc, "ev1") == 1          # exact replay
    assert len(await p.list_acceptances(P, S)) == 1
    await rejected("ACCEPTANCE_ID_REUSED", p.promote_head(P, S, "m1", 1, rev, acc, "ev1"))


async def test_create_head_rejects_empty_model_key(h):
    await rejected("INVALID_ARGUMENT", h.p.create_head(P, S, ""))


async def test_promote_head_compare_and_swap_on_expected_version(h):
    p = h.p
    rev, _ = await attested(h)
    assert await p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1") == 1
    await rejected("STALE_ACCEPTED_HEAD", p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    await rejected("STALE_ACCEPTED_HEAD", p.promote_head(P, S, "m1", 7, rev, uuid.uuid4(), "ev1"))
    await rejected("STALE_ACCEPTED_HEAD", p.promote_head(P, S, "nope", 0, rev, uuid.uuid4(), "ev1"))
    assert (await p.get_head(P, S, "m1")).version == 1 and len(await p.list_acceptances(P, S)) == 1
    assert await p.promote_head(P, S, "m1", 1, rev, uuid.uuid4(), "ev1") == 2   # positive control


async def test_workers_cannot_promote(h):
    rev, _ = await attested(h)
    await rejected("PERMISSION_DENIED", h.p.promote_head(W, S, "m1", 0, rev, uuid.uuid4(), "ev1"))


@pytest.mark.parametrize("kw", [dict(evidence_ref=""), dict(evidence_ref=None),
                                dict(new_revision=None), dict(acceptance_id=None),
                                dict(expected_version=None), dict(model_key=None)])
async def test_promote_requires_complete_arguments(h, kw):
    rev, _ = await attested(h)
    args = dict(model_key="m1", expected_version=0, new_revision=rev,
                acceptance_id=uuid.uuid4(), evidence_ref="ev1") | kw
    await rejected("INDEPENDENT_APPROVAL_REQUIRED", h.p.promote_head(P, S, **args))


async def test_promote_needs_the_evidence_to_exist_for_that_exact_revision(h):
    p = h.p
    rev, _ = await attested(h)
    await rejected("EVIDENCE_NOT_FOUND", p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev-x"))
    _, other = await ing(h, "o2", digest=D2)
    await rejected("EVIDENCE_NOT_FOUND", p.promote_head(P, S, "m1", 0, other, uuid.uuid4(), "ev1"))
    _, gap = await ing(h, "o3", kind="GAP", digest=None)
    await rejected("REVISION_NOT_OBSERVED", p.promote_head(P, S, "m1", 0, gap, uuid.uuid4(), "ev1"))
    await rejected("REVISION_NOT_OBSERVED",
                   p.promote_head(P, S, "m1", 0, uuid.uuid4(), uuid.uuid4(), "ev1"))


@pytest.mark.parametrize("case", ["approver_is_proposer", "approver_is_a_worker",
                                  "approver_is_a_worker_unrelated_to_observer",
                                  "approver_contains_observer", "approver_is_member_of_proposer"])
async def test_approver_must_be_independent_of_observer_and_proposer(h, case):
    p = h.p
    observer, proposer = W, "prop"
    if case == "approver_is_proposer":
        await p.define_actor("p2c_prom_a", (P,))
        approver, proposer = "p2c_prom_a", "p2c_prom_a"
    elif case == "approver_is_a_worker":
        await p.define_actor("p2c_dual", (W, P))
        approver = "p2c_dual"
    elif case == "approver_is_a_worker_unrelated_to_observer":
        # only the living_worker duty-separation rule can catch this one
        await p.define_actor("p2c_trusted", ())
        await p.define_actor("p2c_rev", (W, "p2c_trusted"))
        await p.set_trusted_reviewer("p2c_trusted", S, True, FUTURE)
        await p.define_actor("p2c_dual2", (W, P))
        approver, observer = "p2c_dual2", "p2c_rev"
    elif case == "approver_contains_observer":
        await p.define_actor("p2c_boss", (P,))
        await p.define_actor("p2c_obs", (W, "p2c_boss"))
        approver, observer = "p2c_boss", "p2c_obs"
    else:
        await p.define_actor("p2c_prop_role", ())
        await p.define_actor("p2c_member", (P, "p2c_prop_role"))
        approver, proposer = "p2c_member", "p2c_prop_role"
    rev, _ = await attested(h, actor=observer, proposer=proposer)
    await rejected("APPROVER_NOT_INDEPENDENT",
                   p.promote_head(approver, S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    assert (await p.get_head(P, S, "m1")).version == 0 and await p.list_acceptances(P, S) == ()
    await p.define_actor("p2c_prom_ok", (P,))                       # an unrelated promoter succeeds
    assert await p.promote_head("p2c_prom_ok", S, "m1", 0, rev, uuid.uuid4(), "ev1") == 1


async def test_promote_rejects_a_reject_decision(h):
    rev, _ = await attested(h, decision="REJECT")
    await rejected("EVIDENCE_NOT_APPROVED", h.p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1"))


async def test_promote_rejects_revoked_evidence(h):
    p = h.p
    rev, att = await attested(h)
    revoked_at = await p.revoke_attestation(W, S, att)              # the recording observer
    assert await p.revoke_attestation(W, S, att) == revoked_at      # irreversible and idempotent
    await rejected("EVIDENCE_REVOKED", p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    assert (await p.get_head(P, S, "m1")).version == 0


async def attested_expiring(h, window=1.5, **kw):
    """`attested` with an attestation that expires ``window`` s from the STORE clock.

    Setup slower than the window would make record_attestation itself raise EVIDENCE_EXPIRED; retry
    with a 4x/16x window instead of flaking. Returns (revision, attestation id, expires_at).
    """
    for w in (window, window * 4, window * 16):
        expires = (await h.p.now()) + timedelta(seconds=w)
        try:
            rev, att = await attested(h, expires=expires, **kw)
            return rev, att, expires
        except PortError as e:
            if e.code != "EVIDENCE_EXPIRED":
                raise
    raise AssertionError("test setup is slower than a 24 s attestation window")


async def test_promote_rejects_expired_evidence(h):
    p = h.p
    rev, _, expires = await attested_expiring(h)
    await h.sleep_until(expires)
    await rejected("EVIDENCE_EXPIRED", p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    assert (await p.get_head(P, S, "m1")).version == 0


async def test_promote_rechecks_that_the_observer_is_still_a_trusted_reviewer(h):
    p = h.p
    rev, _ = await attested(h)
    await p.set_trusted_reviewer(W, S, False, FUTURE)
    await rejected("REVIEWER_NOT_TRUSTED", p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    await p.set_trusted_reviewer(W, S, True, FUTURE)
    assert await p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1") == 1


async def test_revoke_attestation_authorisation(h):
    p = h.p
    await p.define_actor("p2c_worker2", (W,))
    _, att = await attested(h)
    await rejected("NOT_AUTHORIZED", p.revoke_attestation("p2c_worker2", S, att))
    await rejected("EVIDENCE_NOT_FOUND", p.revoke_attestation(W, S, uuid.uuid4()))
    await rejected("INVALID_ARGUMENT", p.revoke_attestation(W, S, None))
    assert await p.revoke_attestation(P, S, att) is not None         # any promoter may revoke


@pytest.mark.parametrize("code,kw", [
    ("EVIDENCE_DIGEST_MISMATCH", dict(evidence_digest=evidence_digest(D2, "ev1"))),
    ("REVISION_NOT_OBSERVED", dict(revision_id=uuid.uuid4())),
    ("INVALID_ARGUMENT", dict(decision="MAYBE")),
    ("INVALID_ARGUMENT", dict(evidence_digest="nothex")),
    ("INVALID_ARGUMENT", dict(proposer="")),
    ("INVALID_ARGUMENT", dict(evidence_ref="")),
    ("INVALID_ARGUMENT", dict(expires_at=None)),
    ("EVIDENCE_EXPIRED", dict(expires_at=OBS_AT)),
])
async def test_record_attestation_rejections(h, code, kw):
    _, rev = await ing(h, "o1", digest=D1)
    args = dict(attestation_id=uuid.uuid4(), revision_id=rev, proposer="prop", evidence_ref="ev1",
                evidence_digest=evidence_digest(D1, "ev1"), decision="APPROVE",
                expires_at=FUTURE) | kw
    await rejected(code, h.p.record_attestation(W, S, **args))


async def test_record_attestation_rejects_a_non_observed_revision(h):
    _, gap = await ing(h, "o1", kind="GAP", digest=None)
    await rejected("REVISION_NOT_OBSERVED", h.p.record_attestation(
        W, S, uuid.uuid4(), gap, "prop", "ev1", evidence_digest(D1, "ev1"), "APPROVE", FUTURE))


async def test_record_attestation_needs_a_trusted_reviewer(h):
    p = h.p
    _, rev = await ing(h, "o1", digest=D1)
    await p.set_trusted_reviewer(W, S, False, FUTURE)
    await rejected("REVIEWER_NOT_TRUSTED", p.record_attestation(
        W, S, uuid.uuid4(), rev, "prop", "ev1", evidence_digest(D1, "ev1"), "APPROVE", FUTURE))
    await p.set_trusted_reviewer(W, S, True, FUTURE)
    await p.record_attestation(W, S, uuid.uuid4(), rev, "prop", "ev1", evidence_digest(D1, "ev1"),
                               "APPROVE", FUTURE)


async def test_record_attestation_is_idempotent_and_conflicts_are_rejected(h):
    p = h.p
    _, rev = await ing(h, "o1", digest=D1)
    att, dig = uuid.uuid4(), evidence_digest(D1, "ev1")
    assert await p.record_attestation(W, S, att, rev, "prop", "ev1", dig, "APPROVE", FUTURE) == att
    assert await p.record_attestation(W, S, att, rev, "prop", "ev1", dig, "APPROVE", FUTURE) == att
    await rejected("CONFLICTING_ATTESTATION",
                   p.record_attestation(W, S, att, rev, "someone-else", "ev1", dig, "APPROVE", FUTURE))
    await rejected("CONFLICTING_ATTESTATION",     # same (revision, evidence_ref) under a new id
                   p.record_attestation(W, S, uuid.uuid4(), rev, "prop", "ev1", dig, "APPROVE", FUTURE))


async def test_set_trusted_reviewer_validates_its_arguments(h):
    p = h.p
    await rejected("ROLE_NOT_FOUND", p.set_trusted_reviewer("p2c_no_such_role", S, True, FUTURE))
    await rejected("SOURCE_NOT_FOUND",
                   p.set_trusted_reviewer(W, Scope("A", "missing"), True, FUTURE))
    await rejected("INVALID_ARGUMENT", p.set_trusted_reviewer("", S, True, FUTURE))
    await rejected("INVALID_ARGUMENT", p.set_trusted_reviewer(W, S, None, FUTURE))


# =============================================================================== reviewer trust window
async def test_a_trust_window_that_is_already_over_trusts_nobody(h):
    p = h.p
    _, rev = await ing(h, "o1", digest=D1)
    await p.set_trusted_reviewer(W, S, True, PAST)
    await rejected("REVIEWER_NOT_TRUSTED", p.record_attestation(
        W, S, uuid.uuid4(), rev, "prop", "ev1", evidence_digest(D1, "ev1"), "APPROVE", FUTURE))
    await p.set_trusted_reviewer(W, S, True, FUTURE)
    await p.record_attestation(W, S, uuid.uuid4(), rev, "prop", "ev1", evidence_digest(D1, "ev1"),
                               "APPROVE", FUTURE)


async def test_trust_that_expires_after_recording_blocks_the_promotion(h):
    p = h.p
    rev, _ = await attested(h)                                    # trusted until FUTURE
    expires = (await p.now()) + timedelta(seconds=1.5)
    await p.set_trusted_reviewer(W, S, True, expires)
    await h.sleep_until(expires)                                  # store clock is past the window
    await rejected("REVIEWER_NOT_TRUSTED", p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    _, other = await ing(h, "o2", digest=D2)
    await rejected("REVIEWER_NOT_TRUSTED", p.record_attestation(
        W, S, uuid.uuid4(), other, "prop", "ev2", evidence_digest(D2, "ev2"), "APPROVE", FUTURE))
    await p.set_trusted_reviewer(W, S, True, FUTURE)
    assert await p.promote_head(P, S, "m1", 0, rev, uuid.uuid4(), "ev1") == 1


# =============================================================================== permission matrix
@pytest.mark.parametrize("actor", [R, P, PUB])
async def test_only_workers_may_ingest(h, actor):
    await rejected("PERMISSION_DENIED", h.p.ingest_observation(
        actor, S, uuid.uuid4(), "o1", uuid.uuid4(), "OBSERVED", D1, None, OBS_AT))
    assert await h.p.as_known_at(W, S, await h.p.now()) == ()


@pytest.mark.parametrize("actor", [R, P, PUB])
async def test_only_workers_may_record_attestations(h, actor):
    _, rev = await ing(h, "o1", digest=D1)
    await rejected("PERMISSION_DENIED", h.p.record_attestation(
        actor, S, uuid.uuid4(), rev, "prop", "ev1", evidence_digest(D1, "ev1"), "APPROVE", FUTURE))


async def test_readers_read_the_ledger_and_heads_but_nothing_else(h):
    p = h.p
    rev, _ = await attested(h)
    k = await p.now()
    assert [r.observation.object_id for r in await p.as_known_at(R, S, k)] == ["o1"]   # positive
    assert [r.observation.object_id for r in await p.as_effective_at(R, S, E2, k)] == ["o1"]
    assert (await p.get_head(R, S, "m1")).version == 0
    assert await p.list_acceptances(R, S) == ()
    j = uuid.uuid4()
    await rejected("PERMISSION_DENIED", p.enqueue_job(R, S, j, "sync", "c" * 64, "k"))
    await rejected("PERMISSION_DENIED", p.get_job(R, S, j))
    await rejected("PERMISSION_DENIED", p.create_cursor(R, S, "conn", "p0"))
    await rejected("PERMISSION_DENIED", p.create_head(R, S, "m2"))
    await rejected("PERMISSION_DENIED", p.promote_head(R, S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    await rejected("PERMISSION_DENIED", p.revoke_attestation(R, S, uuid.uuid4()))
    await rejected("PERMISSION_DENIED", p.claim_outbox(R, S, 1, 30))
    await rejected("PERMISSION_DENIED", p.list_outbox(R, S))


async def test_publishers_cannot_read_or_write_the_ledger(h):
    p = h.p
    await rejected("PERMISSION_DENIED", p.as_known_at(PUB, S, await p.now()))
    await rejected("PERMISSION_DENIED", p.get_head(PUB, S, "m1"))
    await rejected("PERMISSION_DENIED", p.get_job(PUB, S, uuid.uuid4()))


async def test_an_actor_outside_every_runtime_role_is_permission_denied(h):
    p = h.p
    await p.define_actor("p2c_nobody", ())
    await rejected("PERMISSION_DENIED", p.as_known_at("p2c_nobody", S, await p.now()))
    await rejected("PERMISSION_DENIED", p.enqueue_job("p2c_nobody", S, uuid.uuid4(), "k", "c" * 64, "x"))


# =============================================================================== tenant / scope isolation
@pytest.mark.parametrize("scope", [S3, B, Scope("A", "missing"), Scope("Z", "z")],
                         ids=["same-tenant-other-source", "other-tenant", "no-source", "no-tenant"])
async def test_an_ungranted_scope_is_scope_not_granted_for_every_runtime_role(h, scope):
    p = h.p
    k = await p.now()
    await rejected("SCOPE_NOT_GRANTED", p.as_known_at(W, scope, k))
    await rejected("SCOPE_NOT_GRANTED", p.as_known_at(R, scope, k))
    await rejected("SCOPE_NOT_GRANTED", p.get_head(P, scope, "m1"))
    await rejected("SCOPE_NOT_GRANTED", p.claim_outbox(PUB, scope, 1, 30))
    await rejected("SCOPE_NOT_GRANTED", p.ingest_observation(
        W, scope, uuid.uuid4(), "o1", uuid.uuid4(), "OBSERVED", D1, None, OBS_AT))
    await rejected("SCOPE_NOT_GRANTED", p.enqueue_job(W, scope, uuid.uuid4(), "k", "c" * 64, "x"))
    await rejected("SCOPE_NOT_GRANTED", p.create_cursor(W, scope, "conn", "p0"))


async def test_scope_must_be_a_complete_scope(h):
    for bad in (Scope("", "s1"), Scope("A", ""), None):
        await rejected("INVALID_ARGUMENT", h.p.as_known_at(W, bad, await h.p.now()))


async def test_revoking_a_grant_denies_the_role_and_bumps_the_epoch(h):
    p = h.p
    e0 = await p.scope_epoch(S)
    await p.revoke_scope(W, S)
    assert await p.scope_epoch(S) == e0 + 1
    await rejected("SCOPE_NOT_GRANTED", p.as_known_at(W, S, await p.now()))
    assert await p.as_known_at(R, S, await p.now()) == ()          # other roles keep their grants
    await p.grant_scope(W, S)
    assert await p.scope_epoch(S) == e0 + 1                        # granting does not bump
    assert await p.as_known_at(W, S, await p.now()) == ()


async def test_scope_epoch_of_an_unknown_source_is_none(h):
    assert await h.p.scope_epoch(Scope("A", "missing")) is None


async def test_scope_b_cannot_read_write_or_promote_scope_a_data(h):
    p = h.p
    await p.grant_scope(W, B)
    await p.grant_scope(P, B)
    await p.set_trusted_reviewer(W, B, True, FUTURE)
    rev_a, att_a = await attested(h)                                      # scope A, model m1
    job_a, _ = await start_job(h, key="shared-key")
    await p.create_cursor(W, S, "conn", "p0")
    got_b = await p.ingest_observation(W, B, uuid.uuid4(), "o1", uuid.uuid4(), "OBSERVED", D2,
                                       None, OBS_AT)                      # same object id in B
    k = await p.now()
    # reads: each scope sees only its own row
    (row_a,) = await p.as_known_at(W, S, k)
    assert (row_a.observation.revision_id, row_a.observation.digest) == (rev_a, D1)
    (row_b,) = await p.as_known_at(W, B, k)
    assert (row_b.observation.observation_id, row_b.observation.digest) == (got_b, D2)
    # jobs / cursors / idempotency keys are per scope
    assert await p.get_job(W, B, job_a) is None and await p.get_cursor(W, B, "conn") is None
    job_b = uuid.uuid4()
    assert await p.enqueue_job(W, B, job_b, "sync", "c" * 64, "shared-key") == job_b
    assert await p.get_job(W, S, job_b) is None
    await rejected("JOB_UNAVAILABLE", p.acquire_job(W, B, job_a, "w1", 30))
    await rejected("STALE_JOB_FENCE", p.finish_job(W, B, job_a, "w1", 1, "SUCCEEDED"))
    assert (await p.get_job(W, S, job_a)).state == "RUNNING"
    # writes that reference scope A data from scope B
    dig = evidence_digest(D1, "ev1")
    await rejected("REVISION_NOT_OBSERVED",
                   p.record_attestation(W, B, uuid.uuid4(), rev_a, "prop", "ev1", dig, "APPROVE", FUTURE))
    await rejected("EVIDENCE_NOT_FOUND", p.revoke_attestation(W, B, att_a))
    await p.create_head(P, B, "m1")
    await rejected("REVISION_NOT_OBSERVED", p.promote_head(P, B, "m1", 0, rev_a, uuid.uuid4(), "ev1"))
    assert (await p.get_head(P, B, "m1")).version == 0 and await p.list_acceptances(P, B) == ()
    # the publisher has no grant on B at all, and A's untouched state is intact
    await rejected("SCOPE_NOT_GRANTED", p.claim_outbox(PUB, B, 1, 30))
    assert (await p.get_head(P, S, "m1")).version == 0
    assert await p.promote_head(P, S, "m1", 0, rev_a, uuid.uuid4(), "ev1") == 1


async def test_a_scope_epoch_bump_is_per_source(h):
    p = h.p
    await p.grant_scope(W, B)
    eb = await p.scope_epoch(B)
    ea = await p.scope_epoch(S)
    assert await p.bump_scope_epoch(S) == ea + 1
    assert await p.scope_epoch(B) == eb
    await p.create_cursor(W, B, "conn", "p0")                       # B is unaffected
    j = uuid.uuid4()
    assert await p.enqueue_job(W, B, j, "sync", "c" * 64, "kb") == j
    assert await p.acquire_job(W, B, j, "w1", 30) == 1


# =============================================================================== scope-epoch revocation
async def test_a_stale_epoch_cannot_commit_renew_finish_or_replay(h):
    p = h.p
    await p.create_cursor(W, S, "conn", "p0")
    j, f = await start_job(h, key="k1", lease=60)                    # RUNNING under the old epoch
    e0 = await p.scope_epoch(S)
    assert await p.bump_scope_epoch(S) == e0 + 1
    # a replayed enqueue of work queued under the old epoch is never current work again
    await rejected("SCOPE_REVOKED", p.enqueue_job(W, S, uuid.uuid4(), "sync", "c" * 64, "k1"))
    fresh = uuid.uuid4()
    assert await p.enqueue_job(W, S, fresh, "sync", "c" * 64, "k-new") == fresh   # new work is fine
    # the holder of the old-epoch job loses renew / finish (no row matches the current epoch)
    await rejected("STALE_JOB_FENCE", p.renew_lease(W, S, j, "w1", f, 30))
    await rejected("STALE_JOB_FENCE", p.finish_job(W, S, j, "w1", f, "SUCCEEDED"))
    # commits: stale expected epoch, and the current epoch with an old-epoch job
    await rejected("SCOPE_REVOKED", commit(h, j, f, [ev("e1")], epoch=e0))
    await rejected("SCOPE_REVOKED", commit(h, j, f, [ev("e1")], epoch=e0 + 1))
    cur = await p.get_cursor(W, S, "conn")
    assert (cur.cursor_value, cur.version, cur.scope_epoch) == ("p0", 0, e0)
    assert await p.list_outbox(W, S) == ()
    assert await p.as_known_at(R, S, await p.now()) == ()            # reads re-enter at the new epoch


async def test_acquire_of_a_job_queued_under_an_old_epoch_is_scope_revoked(h):
    p = h.p
    j = uuid.uuid4()
    await p.enqueue_job(W, S, j, "sync", "c" * 64, "k1")
    await p.bump_scope_epoch(S)
    await rejected("SCOPE_REVOKED", p.acquire_job(W, S, j, "w1", 30))
    assert (await p.get_job(W, S, j)).state == "PENDING"


async def test_rebase_scope_repoints_cursors_and_pending_jobs_so_work_resumes(h):
    p = h.p
    await p.create_cursor(W, S, "conn", "p0")
    await start_job(h, key="k1", lease=10)
    pend = uuid.uuid4()
    await p.enqueue_job(W, S, pend, "sync", "c" * 64, "k2")
    e1 = await p.bump_scope_epoch(S)
    await h.warp(11)
    assert await p.reap_expired_jobs(W, S) == 1                        # old holder is gone
    await h.warp(3)
    await rejected("SCOPE_REVOKED", p.acquire_job(W, S, pend, "w1", 30))
    assert await p.rebase_scope(S) == 3                                # cursor + both PENDING jobs
    assert await p.rebase_scope(S) == 0
    f2 = await p.acquire_job(W, S, pend, "w1", 30)
    res = await commit(h, pend, f2, [ev("e1")], epoch=e1)
    assert (res.version, res.replayed) == (1, False)
    assert (await p.get_cursor(W, S, "conn")).scope_epoch == e1


# =============================================================================== fake == SQL divergences
async def test_an_explicit_null_provenance_or_payload_is_invalid_but_omitting_it_is_not(h):
    p = h.p
    await rejected("INVALID_OBSERVATION", ing(h, "o1", prov=None))
    await rejected("INVALID_JOB", p.enqueue_job(W, S, uuid.uuid4(), "sync", "c" * 64, "k", None))
    await ing(h, "o1")
    assert await p.enqueue_job(W, S, (j := uuid.uuid4()), "sync", "c" * 64, "k") == j


async def test_provenance_equality_is_jsonb_not_python(h):
    first, rev = await ing(h, "o1", prov={"a": 1, "b": [1, 2]})
    again, _ = await ing(h, "o1", rev=rev, prov={"b": [1, 2], "a": 1.0})        # key order, 1 == 1.0
    assert again == first
    await rejected("CONFLICTING_OBSERVATION", ing(h, "o1", rev=rev, prov={"a": True, "b": [1, 2]}))
    await rejected("CONFLICTING_OBSERVATION", ing(h, "o1", rev=rev, prov={"a": 1, "b": [2, 1]}))


async def test_provenance_and_payload_accept_floats_and_nested_json(h):
    await ing(h, "o1", prov={"x": 1.5, "y": [None, {"z": "é"}]})
    j = uuid.uuid4()
    assert await h.p.enqueue_job(W, S, j, "sync", "c" * 64, "k", {"w": 0.25}) == j


async def test_naive_datetimes_are_a_typed_rejection(h):
    p = h.p
    naive = datetime(2024, 1, 2)  # noqa: DTZ001 - naive on purpose
    await rejected("NAIVE_DATETIME", ing(h, "o1", observed_at=naive))
    await rejected("NAIVE_DATETIME", ing(h, "o1", eff=naive))
    await rejected("NAIVE_DATETIME", p.as_known_at(W, S, naive))
    await rejected("NAIVE_DATETIME", p.as_effective_at(W, S, naive, await p.now()))
    await rejected("NAIVE_DATETIME", p.set_trusted_reviewer(W, S, True, naive))
    _, rev = await ing(h, "o2", digest=D1)
    await rejected("NAIVE_DATETIME", p.record_attestation(
        W, S, uuid.uuid4(), rev, "prop", "ev1", evidence_digest(D1, "ev1"), "APPROVE", naive))


async def test_non_json_arguments_are_a_typed_rejection(h):
    p = h.p
    await rejected("INVALID_JSON", ing(h, "o1", prov={1: "a"}))
    await rejected("INVALID_JSON", ing(h, "o1", prov={"a": {1, 2}}))
    await rejected("INVALID_JSON", ing(h, "o1", prov={"a": float("nan")}))
    await rejected("INVALID_JSON", p.enqueue_job(W, S, uuid.uuid4(), "sync", "c" * 64, "k", {"a": object()}))
    await p.create_cursor(W, S, "conn", "p0")
    j, f = await start_job(h)
    bad = {"event_id": "e1", 1: "x", "digest": "0" * 64}
    await rejected("INVALID_JSON", commit(h, j, f, [bad]))
    await rejected("INVALID_JSON", commit(h, j, f, [{"event_id": "e1", "when": datetime(2024, 1, 1, tzinfo=UTC)}]))
    assert (await p.get_cursor(W, S, "conn")).version == 0


async def test_a_nul_character_is_rejected_in_text_and_in_json(h):
    p = h.p
    await rejected("INVALID_TEXT", ing(h, "o\x001"))
    await rejected("INVALID_TEXT", ing(h, "o1", prov={"k": "a\x00b"}))
    await rejected("INVALID_TEXT", ing(h, "o1", prov={"a\x00": 1}))
    await rejected("INVALID_TEXT", p.enqueue_job(W, S, uuid.uuid4(), "sync", "c" * 64, "k\x00"))
    assert await p.as_known_at(W, S, await p.now()) == ()


async def test_define_actor_and_trusted_reviewer_reject_bad_arguments_with_port_errors(h):
    p = h.p
    await rejected("ROLE_NOT_FOUND", p.define_actor("p2c_orphan", ("p2c_no_such_parent",)))
    await rejected("INVALID_ARGUMENT", p.set_trusted_reviewer(W, None, True, FUTURE))


async def test_outbox_rows_are_hashable_and_compare_by_digest(h):
    p = h.p
    await outbox_with_events(h, "e1", "e2")
    rows = await p.list_outbox(W, S)
    assert len({*rows, *await p.list_outbox(W, S)}) == 2
    assert {rows[0]: 1}[rows[0]] == 1


def test_port_error_survives_pickling_with_code_and_detail():
    err = pickle.loads(pickle.dumps(PortError("STALE_JOB_FENCE", "lease lost")))
    assert (err.code, err.detail, str(err)) == ("STALE_JOB_FENCE", "lease lost",
                                                "STALE_JOB_FENCE: lease lost")
    bare = pickle.loads(pickle.dumps(PortError("X")))
    assert (bare.code, bare.detail) == ("X", "")


def test_omitted_is_a_stable_singleton():
    assert pickle.loads(pickle.dumps(OMITTED)) is OMITTED and repr(OMITTED) == "OMITTED"


def test_outbox_row_without_comparing_content_is_hashable():
    row = OutboxRow(1, "c", "e", "d" * 64, {"a": 1}, "PENDING", 0, None, None, 0)
    assert hash(row) == hash(OutboxRow(1, "c", "e", "d" * 64, {"a": 2}, "PENDING", 0, None, None, 0))


# =============================================================================== REQUIRE_PG session guard
def _report(nodeid, outcome, *, when="call", marks=("integration",), wasxfail=False,
            where="tests/phase2/test_x.py"):
    rep = SimpleNamespace(nodeid=nodeid, when=when, skipped=outcome == "skipped",
                          passed=outcome == "passed", failed=outcome == "failed",
                          location=(where, 1, "t"), keywords={m: 1 for m in marks})
    if wasxfail:
        rep.wasxfail = "reason"
    return rep


def _item(nodeid, variant):
    return SimpleNamespace(nodeid=nodeid, callspec=SimpleNamespace(params={"h": variant}))


@pytest.fixture
def guard(request):
    return request.config._phase2_guard_cls()


C = "tests/phase2/test_ports_contract.py"


def test_guard_flags_a_skipped_integration_item_even_in_the_sql_contract(guard):
    guard.observe(_report(f"{C}::test_a[sql]", "skipped", when="setup", where=C))
    assert "test_a[sql] (skipped)" in guard.problems()[0]


def test_guard_flags_an_xfailed_integration_item(guard):
    guard.observe(_report("tests/phase2/test_x.py::t", "skipped", wasxfail=True))
    assert "(xfailed)" in guard.problems()[0]


def test_guard_ignores_skips_that_are_not_phase2_integration(guard):
    guard.observe(_report("tests/phase2/test_x.py::t", "skipped", marks=()))
    guard.observe(_report("tests/other/test_x.py::t", "skipped", where="tests/other/test_x.py"))
    assert guard.problems() == []


def test_guard_flags_deselected_integration_items(guard):
    class Item(SimpleNamespace):
        def get_closest_marker(self, name):
            return object() if name == "integration" else None
    from pathlib import Path
    guard.deselected([Item(nodeid="n::t", path=Path(__file__))])
    assert guard.problems() and "(deselected)" in guard.problems()[0]


def test_sentinel_requires_as_many_sql_contract_items_as_fake_items(guard):
    guard.plan([_item(f"{C}::t{i}[fake]", "fake") for i in range(3)]
               + [_item("tests/phase2/test_other.py::t[fake]", "fake")])
    for i in range(2):
        guard.observe(_report(f"{C}::t{i}[sql]", "passed", where=C))
    guard.observe(_report(f"{C}::t2[fake]", "passed", where=C, marks=()))          # fake never counts
    guard.observe(_report(f"{C}::t2[sql]", "passed", when="setup", where=C))       # setup is not a run
    assert "only 2 [sql] contract items executed but 3 [fake]" in guard.problems()[0]
    guard.observe(_report(f"{C}::t2[sql]", "failed", where=C))                     # a failure ran
    assert guard.problems() == []


def test_sentinel_counts_parametrised_sql_ids_in_any_position(guard):
    guard.plan([_item(f"{C}::t[x-fake]", "fake"), _item(f"{C}::t[fake-y]", "fake")])
    guard.observe(_report(f"{C}::t[x-sql]", "passed", where=C))
    assert guard.problems()
    guard.observe(_report(f"{C}::t[sql-y]", "passed", where=C))
    assert guard.problems() == []


# =============================================================================== SQL-only concurrency
@pytest.fixture
async def race_db():
    """(port on connection 1, port on connection 2, lock connection) over one throwaway database."""
    dsn = require_dsn()
    async with throwaway_db(dsn) as db:
        c2, c3 = await db.connect(), await db.connect()
        try:
            yield SqlLiving(db.conn), SqlLiving(c2), c3
        finally:
            await c2.close()
            await c3.close()


async def _blocked_on_a_lock(locker, conns, timeout=30.0):
    pids = [c.get_server_pid() for c in conns]
    end = asyncio.get_running_loop().time() + timeout
    while await locker.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE pid=ANY($1::int[]) "
            "AND wait_event_type='Lock'", pids) != len(pids):
        assert asyncio.get_running_loop().time() < end, "racers never blocked on the source lock"
        await asyncio.sleep(0.02)


async def race(race_db, make_a, make_b):
    """Run ``make_a(port1)`` and ``make_b(port2)`` truly concurrently on two connections.

    A third connection holds the source row lock (``FOR UPDATE``); both calls are started, and the
    lock is released only when pg_stat_activity shows BOTH waiting on a lock, so the two
    transactions are guaranteed to overlap and are serialised by PostgreSQL itself.
    """
    one, two, locker = race_db
    tasks = []
    try:
        async with locker.transaction():
            await locker.execute("SELECT 1 FROM living.sources WHERE tenant_id=$1 AND source_id=$2 "
                                 "FOR UPDATE", S.tenant_id, S.source_id)
            tasks = [asyncio.ensure_future(make_a(one)), asyncio.ensure_future(make_b(two))]
            await _blocked_on_a_lock(locker, [one.conn, two.conn])
    except BaseException:
        for t in tasks:
            t.cancel()
        raise
    return await asyncio.gather(*tasks, return_exceptions=True)


def one_winner(results, loser_code):
    wins = [r for r in results if not isinstance(r, BaseException)]
    losses = [r for r in results if isinstance(r, BaseException)]
    assert len(wins) == 1 and len(losses) == 1, results
    assert isinstance(losses[0], PortError) and losses[0].code == loser_code, losses[0]
    return wins[0], results.index(wins[0])


@pytest.mark.integration
@pytest.mark.parametrize("same_job", [True, False], ids=["same-job", "two-jobs"])
async def test_race_two_acquires_of_one_source_give_exactly_one_fence(race_db, same_job):
    one, _two, _ = race_db
    j1, j2 = uuid.uuid4(), uuid.uuid4()
    await one.enqueue_job(W, S, j1, "sync", "c" * 64, "k1")
    await one.enqueue_job(W, S, j2, "sync", "c" * 64, "k2")
    results = await race(race_db, lambda c: c.acquire_job(W, S, j1, "w1", 30),
                         lambda c: c.acquire_job(W, S, j1 if same_job else j2, "w2", 30))
    fence, _ = one_winner(results, "JOB_UNAVAILABLE")
    assert fence == 1
    states = sorted([(await one.get_job(W, S, j)).state for j in (j1, j2)])
    assert states == ["PENDING", "RUNNING"]


@pytest.mark.integration
async def test_race_two_promotions_at_the_same_expected_version_give_exactly_one_head(race_db):
    one, _two, _ = race_db
    await one.define_actor("p2c_pa", (P,))
    await one.define_actor("p2c_pb", (P,))
    rev = uuid.uuid4()
    await one.ingest_observation(W, S, uuid.uuid4(), "o1", rev, "OBSERVED", D1, E1, OBS_AT)
    await one.create_head(P, S, "m1")
    await one.record_attestation(W, S, uuid.uuid4(), rev, "prop", "ev1", evidence_digest(D1, "ev1"),
                                 "APPROVE", FUTURE)
    results = await race(race_db,
                         lambda c: c.promote_head("p2c_pa", S, "m1", 0, rev, uuid.uuid4(), "ev1"),
                         lambda c: c.promote_head("p2c_pb", S, "m1", 0, rev, uuid.uuid4(), "ev1"))
    version, idx = one_winner(results, "STALE_ACCEPTED_HEAD")
    assert version == 1 and (await one.get_head(P, S, "m1")).version == 1
    (acc,) = await one.list_acceptances(P, S)
    assert acc.approver_subject == ("p2c_pa", "p2c_pb")[idx]


async def _cursor_ready(one):
    await one.create_cursor(W, S, "conn", "p0")
    j = uuid.uuid4()
    await one.enqueue_job(W, S, j, "sync", "c" * 64, "k1")
    return j, await one.acquire_job(W, S, j, "w1", 120), await one.scope_epoch(S)


@pytest.mark.integration
async def test_race_two_commits_from_the_same_prior_cursor_give_exactly_one_advance(race_db):
    one, _two, _ = race_db
    j, f, ep = await _cursor_ready(one)

    def page(new, eid):
        return lambda c: c.commit_cursor_page(W, S, "conn", j, "w1", f, "p0", 0, ep, new, [ev(eid)])
    results = await race(race_db, page("pa", "ea"), page("pb", "eb"))
    res, idx = one_winner(results, "STALE_CURSOR_OR_SCOPE")
    won, eid = (("pa", "ea"), ("pb", "eb"))[idx]
    assert (res.version, res.replayed) == (1, False)
    cur = await one.get_cursor(W, S, "conn")
    assert (cur.cursor_value, cur.version) == (won, 1)
    assert [r.event_id for r in await one.list_outbox(W, S)] == [eid]       # loser wrote nothing


@pytest.mark.integration
async def test_race_two_identical_commits_apply_once_and_replay_once(race_db):
    one, _two, _ = race_db
    j, f, ep = await _cursor_ready(one)
    events = [ev("e1"), ev("e2")]

    def page(c):
        return c.commit_cursor_page(W, S, "conn", j, "w1", f, "p0", 0, ep, "p1", events)
    results = await race(race_db, page, page)
    assert all(isinstance(r, type(results[0])) and not isinstance(r, BaseException) for r in results)
    assert sorted((r.version, r.replayed) for r in results) == [(1, False), (1, True)]
    assert [r.event_id for r in await one.list_outbox(W, S)] == ["e1", "e2"]


@pytest.mark.integration
async def test_race_two_publishers_never_claim_the_same_event(race_db):
    one, _two, _ = race_db
    await one.define_actor("p2c_pub_a", (PUB,))
    await one.define_actor("p2c_pub_b", (PUB,))
    j, f, ep = await _cursor_ready(one)
    await one.commit_cursor_page(W, S, "conn", j, "w1", f, "p0", 0, ep, "p1", [ev("e1"), ev("e2")])
    results = await race(race_db, lambda c: c.claim_outbox("p2c_pub_a", S, 1, 60),
                         lambda c: c.claim_outbox("p2c_pub_b", S, 1, 60))
    assert all(not isinstance(r, BaseException) and len(r) == 1 for r in results), results
    assert sorted(r[0].event_id for r in results) == ["e1", "e2"]
    assert {r[0].claim_generation for r in results} == {1}
