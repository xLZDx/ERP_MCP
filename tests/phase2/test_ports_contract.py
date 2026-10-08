# ruff: noqa: C408 - dict(...) kwargs are the deliberate case-override style here
"""Shared port contract: ONE test body, run against the in-memory fake AND the real living.* SQL API.

Every test takes the ``h`` fixture parametrised over ``fake`` and ``sql``. The ``sql`` variant is
marked ``integration`` and needs ERP_PHASE2_TEST_DSN (skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1, see _pg_harness.require_dsn); each test gets its own throwaway database.
SQL is the source of truth: a failing ``fake`` variant means the fake is wrong.

Mutation-style rule: each guard has at least one test whose only failure cause is that guard, with
the specific error code asserted, so removing the guard from the fake (or from the SQL) turns that
test red. Time: the fake uses an injected clock; for SQL, ``h.warp`` moves job/outbox leases into
the past and ``h.sleep_real`` waits (only for attestation expiry, which is immutable in SQL).
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from _pg_harness import require_dsn, throwaway_db
from _sql_ports import SqlLiving

from business_ai_gateway.phase2.fakes import FakeClock, InMemoryLiving
from business_ai_gateway.phase2.ports import (
    CursorOutboxPort,
    HeadAttestationPort,
    JobQueuePort,
    LedgerPort,
    PortError,
    Scope,
    event_digest,
    evidence_digest,
    page_digest,
)

S = Scope("A", "s1")
W, P, PUB = "living_worker", "living_promoter", "living_publisher"
D1, D2 = "1" * 64, "2" * 64
OBS_AT = datetime(2024, 1, 2, tzinfo=UTC)
E1, E2 = datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


class Harness:
    def __init__(self, kind, ports):
        self.kind, self.p = kind, ports

    async def warp(self, seconds):
        if self.kind == "fake":
            self.p.clock.advance(seconds)
        else:
            await self.p.warp(seconds)

    async def sleep_real(self, seconds):
        if self.kind == "fake":
            self.p.clock.advance(seconds)
        else:
            await asyncio.sleep(seconds)


@pytest.fixture(params=["fake", pytest.param("sql", marks=pytest.mark.integration)])
async def h(request):
    if request.param == "fake":
        yield Harness("fake", InMemoryLiving(FakeClock()))
        return
    dsn = require_dsn()
    async with throwaway_db(dsn) as db:
        yield Harness("sql", SqlLiving(db.conn))


async def rejected(code, awaitable):
    with pytest.raises(PortError) as ei:
        await awaitable
    assert ei.value.code == code, ei.value
    return ei.value


async def ing(h, obj, rev=None, kind="OBSERVED", digest=D1, eff=None, supersedes=None, obs_id=None,
              observed_at=OBS_AT, prov=None):
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


async def test_promote_rejects_expired_evidence(h):
    p = h.p
    expires = (await p.now()) + timedelta(milliseconds=1500)
    rev, _ = await attested(h, expires=expires)
    await h.sleep_real(1.8)
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
