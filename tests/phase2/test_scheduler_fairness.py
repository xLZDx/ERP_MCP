"""TC059 (source isolation) and TC057 (fairness under backend-budget saturation) of the scheduler.

Behavioural tests over the real ``SourceScheduler`` + ``InMemoryLiving`` + ``PhysicalBackendBudget``.
Time is the fake store clock and jitter a fixed value: no sleeps, no wall clock, no randomness.

What the implementation guarantees about fairness (and what this file pins):
- a budget denial defers the job (``DEFERRED_BUDGET``) without consuming an attempt, failing or
  poisoning it; the deferral delay is ``backoff(deferrals)`` clamped by ``deferral_cap_seconds``;
  ``starved`` turns True at ``deferral_alert_threshold`` consecutive deferrals of that job.
- NOT guaranteed: any ordering between a long-deferred source and a fresh one. The budget is a plain
  counter with no queue, reservation or aging, and a release does not wake a deferred source (it
  has to wait out its own gate). A fresh source (no gate) can take the slot first, again and again.
  ``test_no_fairness_*`` document that real behaviour; they are not guarantees.

Each ``test_sensitivity_*`` flips one guard (config value, capacity, shared state) and asserts the
OPPOSITE outcome, proving the corresponding assertion elsewhere in this file can fail.
"""
from contextlib import contextmanager
from uuid import UUID

import pytest

from business_ai_gateway.phase2.backend_budget import (
    BackendCapacityError,
    BackendId,
    PhysicalBackendBudget,
)
from business_ai_gateway.phase2.drift import CaptureOutcomeKind, FailureCounter
from business_ai_gateway.phase2.fakes import WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import Scope
from business_ai_gateway.phase2.scheduler import (
    RunStatus,
    SchedulerConfig,
    SchedulerState,
    SourceScheduler,
    SourceState,
)

SCOPE_A = Scope("A", "s1")
SCOPE_B = Scope("A", "s2")
SCOPE_C = Scope("A", "s3")
DIGEST = "a" * 64
OK = CaptureOutcomeKind.OK_COMPLETE
TIMEOUT = CaptureOutcomeKind.TIMEOUT

# Aliases that all normalise to the one physical backend "db-1".
ALIAS_A, ALIAS_B, ALIAS_C = "DB-1", "  Db-1. ", "db-1."

CAP = 4.0
THRESHOLD = 3
FAIR_CFG = SchedulerConfig(backoff_base=1.0, backoff_cap=300.0, deferral_cap_seconds=CAP,
                           deferral_alert_threshold=THRESHOLD, poison_after=1)


def job_uuid(n: int) -> UUID:
    return UUID(int=n)


async def enqueue(living, n, scope):
    return await living.enqueue_job(WORKER, scope, job_uuid(n), "sync", DIGEST, f"key-{n}")


def world(per_backend=1, total=4):
    living = InMemoryLiving()
    for scope in (SCOPE_B, SCOPE_C):
        living.seed_basic(scope)
    return living, PhysicalBackendBudget(per_backend_limit=per_backend, total_limit=total)


def source(living, budget, scope, alias, *, config=None, jitter=0.0, **kw):
    return SourceScheduler(
        living, actor=WORKER, scope=scope, worker=f"w-{scope.source_id}",
        backend_id=BackendId.normalize(alias), budget=budget, clock=living.clock.now,
        jitter_source=lambda: jitter, config=config or SchedulerConfig(), **kw)


@contextmanager
def hold(budget, alias=ALIAS_A):
    """Someone else occupies the physical backend (the one slot of capacity 1)."""
    with budget.reserve(trusted_backend_id=BackendId.normalize(alias)):
        yield


async def succeed(handle):
    return OK


async def timeout(handle):
    return TIMEOUT


async def forbidden(handle):
    raise AssertionError("work must not run")


def contender(seen, sched, job):
    """Work that, while it holds the slot, makes ``sched`` retry ``job`` and records the result."""
    async def work(handle):
        seen["b"] = await sched.run_job(job, forbidden)
        return OK
    return work


def seconds_until(living, at):
    return (at - living.clock.now()).total_seconds()


# =========================================================================== TC059 isolation
async def test_poisoning_a_leaves_b_runnable_and_state_independent():
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A, config=SchedulerConfig(poison_after=1),
               counter=FailureCounter(0, 100))
    b = source(living, budget, SCOPE_B, ALIAS_B)
    job_a, job_b = await enqueue(living, 1, SCOPE_A), await enqueue(living, 2, SCOPE_B)
    b_before = b.export_state()

    assert (await a.run_job(job_a, timeout)).status is RunStatus.POISONED
    assert a.is_poisoned(job_a) and a.machine.state is SourceState.PAUSED
    assert a.counter.consecutive_failures == 1

    assert b.export_state() == b_before                       # nothing of B moved
    assert b.machine.state is SourceState.ACTIVE and b.counter.consecutive_failures == 0
    assert not b.is_poisoned(job_a) and not b.is_poisoned(job_b)
    assert (await b.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED
    assert (await living.get_job(WORKER, SCOPE_B, job_b)).state == "SUCCEEDED"
    assert budget.active_total == 0


async def test_same_job_id_in_two_scopes_is_poisoned_only_in_its_own_source():
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A, config=SchedulerConfig(poison_after=1),
               counter=FailureCounter(0, 100))
    b = source(living, budget, SCOPE_B, ALIAS_B)
    same = job_uuid(7)
    for scope in (SCOPE_A, SCOPE_B):
        await living.enqueue_job(WORKER, scope, same, "sync", DIGEST, "key-7")
    assert (await a.run_job(same, timeout)).status is RunStatus.POISONED
    assert a.is_poisoned(same) and not b.is_poisoned(same)
    assert (await a.run_job(same, forbidden)).status is RunStatus.POISONED
    assert (await b.run_job(same, succeed)).status is RunStatus.SUCCEEDED
    assert (await living.get_job(WORKER, SCOPE_B, same)).state == "SUCCEEDED"
    assert (await living.get_job(WORKER, SCOPE_A, same)).state == "FAILED"


async def test_failure_counter_pause_of_a_does_not_touch_b_counter_or_state():
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A, config=SchedulerConfig(poison_after=10),
               counter=FailureCounter(0, 1))
    b = source(living, budget, SCOPE_B, ALIAS_B, counter=FailureCounter(2, 3))
    job_a, job_b = await enqueue(living, 1, SCOPE_A), await enqueue(living, 2, SCOPE_B)

    assert (await a.run_job(job_a, timeout)).status is RunStatus.RETRY_SCHEDULED
    assert a.machine.state is SourceState.PAUSED and a.counter.consecutive_failures == 1
    assert (await a.run_job(job_a, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE

    # A's abandoned lease is still RUNNING in A's scope; B's scope is a separate queue.
    assert (await living.get_job(WORKER, SCOPE_A, job_a)).state == "RUNNING"
    assert b.machine.state is SourceState.ACTIVE and b.counter.consecutive_failures == 2
    assert (await b.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED
    assert b.counter.consecutive_failures == 0                 # B's own reset, A stays at 1
    assert a.counter.consecutive_failures == 1
    assert budget.active_total == 0


async def test_quarantine_of_a_leaves_b_gates_and_jobs_runnable():
    living, budget = world()
    cfg = SchedulerConfig(poison_after=10, quarantine_after_pauses=1)
    a = source(living, budget, SCOPE_A, ALIAS_A, config=cfg, counter=FailureCounter(0, 1))
    b = source(living, budget, SCOPE_B, ALIAS_B, config=cfg)
    job_a, job_b1, job_b2 = (await enqueue(living, 1, SCOPE_A), await enqueue(living, 2, SCOPE_B),
                             await enqueue(living, 3, SCOPE_B))
    await a.run_job(job_a, timeout)
    assert a.machine.state is SourceState.QUARANTINED
    assert (await a.run_job(job_a, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE

    # B has its own retry gate on job_b1 (budget deferral); A's quarantine neither adds nor removes it.
    with hold(budget):
        assert (await b.run_job(job_b1, forbidden)).status is RunStatus.DEFERRED_BUDGET
    assert b.machine.state is SourceState.ACTIVE and b.not_before(job_b1) is not None
    assert (await b.run_job(job_b1, forbidden)).status is RunStatus.NOT_YET
    assert (await b.run_job(job_b2, succeed)).status is RunStatus.SUCCEEDED     # other job: no gate
    living.clock.advance(CAP + 1)
    assert (await b.run_job(job_b1, succeed)).status is RunStatus.SUCCEEDED
    assert a.machine.state is SourceState.QUARANTINED          # still quarantined, untouched by B
    assert budget.active_total == 0


async def test_exported_state_of_a_never_contains_b_job_ids():
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A, config=SchedulerConfig(poison_after=1),
               counter=FailureCounter(0, 100))
    b = source(living, budget, SCOPE_B, ALIAS_B)
    job_a, job_b = await enqueue(living, 1, SCOPE_A), await enqueue(living, 2, SCOPE_B)
    await a.run_job(job_a, timeout)                            # A: poisoned set + gate cleared
    with hold(budget):
        assert (await b.run_job(job_b, forbidden)).status is RunStatus.DEFERRED_BUDGET
    snap_a, snap_b = a.export_state(), b.export_state()
    assert snap_a.poisoned == frozenset({job_a})
    assert job_b not in snap_a.poisoned and all(j != job_b for j, _ in snap_a.not_before)
    assert [j for j, _ in snap_b.not_before] == [job_b]        # B's gate is B's alone
    assert job_a not in snap_b.poisoned and all(j != job_a for j, _ in snap_b.not_before)
    assert snap_b.source_state is SourceState.ACTIVE


async def test_job_of_a_cannot_be_run_by_b_scheduler():
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A)
    b = source(living, budget, SCOPE_B, ALIAS_B)
    job_a = await enqueue(living, 1, SCOPE_A)

    # Observed: B's port scope has no such job, acquire is JOB_UNAVAILABLE, get_job returns None.
    result = await b.run_job(job_a, forbidden)
    assert result.status is RunStatus.JOB_MISSING and result.detail == "JOB_MISSING"
    view = await living.get_job(WORKER, SCOPE_A, job_a)
    assert view.state == "PENDING" and view.attempt == 0 and view.lease_owner is None
    assert b.not_before(job_a) is None and not b.is_poisoned(job_a)
    assert b.counter.consecutive_failures == 0 and b.machine.state is SourceState.ACTIVE
    assert budget.active_total == 0
    # The owner still runs it normally afterwards.
    assert (await a.run_job(job_a, succeed)).status is RunStatus.SUCCEEDED


async def test_snapshot_of_a_can_be_imported_into_b_documented_behaviour():
    """OBSERVED, not a guarantee: ``SchedulerState`` carries no scope/source identity, so the type
    does not stop importing A's snapshot into B's scheduler; B then becomes PAUSED and also treats
    A's poisoned ids as poisoned. Keeping snapshots per source is the caller's documented duty."""
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A, config=SchedulerConfig(poison_after=1),
               counter=FailureCounter(0, 100))
    b = source(living, budget, SCOPE_B, ALIAS_B)
    job_a, job_b = await enqueue(living, 1, SCOPE_A), await enqueue(living, 2, SCOPE_B)
    await a.run_job(job_a, timeout)
    snap_a = a.export_state()
    assert snap_a.source_state is SourceState.PAUSED
    assert not hasattr(snap_a, "scope") and not hasattr(snap_a, "source")
    b.import_state(snap_a)                                     # accepted without error
    assert b.machine.state is SourceState.PAUSED and b.is_poisoned(job_a)
    assert (await b.run_job(job_b, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE
    # A fresh B built from no snapshot is unaffected (cold start), so the leak needs the caller.
    cold = source(living, budget, SCOPE_B, ALIAS_B)
    assert (await cold.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED


async def test_sensitivity_shared_state_machine_would_couple_a_and_b():
    """Proves the independence assertions can fail: wiring B to A's machine makes A's pause stop B."""
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A)
    b = source(living, budget, SCOPE_B, ALIAS_B, machine=a.machine)     # deliberately coupled
    job_b = await enqueue(living, 2, SCOPE_B)
    a.machine.pause("operator")
    assert (await b.run_job(job_b, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE
    assert b.machine.state is SourceState.PAUSED

    b_ok = source(living, budget, SCOPE_B, ALIAS_B)                     # the real wiring
    assert (await b_ok.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED


# =========================================================================== TC057 saturation
async def test_saturated_backend_defers_without_attempt_failure_or_poison():
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)       # poison_after=1 on purpose
    job = await enqueue(living, 1, SCOPE_B)
    before = living.clock.now()
    with hold(budget, ALIAS_A):                                         # alias of the same backend
        result = await b.run_job(job, forbidden)
    assert result.status is RunStatus.DEFERRED_BUDGET and result.detail == "BACKEND_CAPACITY_EXCEEDED"
    assert result.deferrals == 1 and result.starved is False
    assert (result.not_before - before).total_seconds() == pytest.approx(0.5, abs=1e-3)
    view = await living.get_job(WORKER, SCOPE_B, job)
    assert view.state == "PENDING" and view.attempt == 0 and view.last_error is None
    assert not b.is_poisoned(job) and b.counter.consecutive_failures == 0
    assert b.machine.state is SourceState.ACTIVE and budget.active_total == 0


@pytest.mark.parametrize("jitter", [0.0, 0.5, 0.999999])
async def test_deferral_delay_never_exceeds_cap_and_starved_flips_at_threshold(jitter):
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG, jitter=jitter)
    job = await enqueue(living, 1, SCOPE_B)
    delays, flags = [], []
    with hold(budget):
        for _ in range(9):
            before = living.clock.now()
            result = await b.run_job(job, forbidden)
            assert result.status is RunStatus.DEFERRED_BUDGET
            delays.append(seconds_until(living, result.not_before) )
            flags.append((result.deferrals, result.starved))
            living.clock.advance(seconds_until(living, result.not_before))
            assert living.clock.now() > before
    assert all(0 < d <= CAP for d in delays)
    assert [n for n, _ in flags] == list(range(1, 10))
    assert [s for _, s in flags] == [n >= THRESHOLD for n in range(1, 10)]
    if jitter == 0.0:
        assert delays == pytest.approx([0.5, 1.0, 2.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0], abs=1e-3)
    else:
        assert max(delays) <= CAP and delays[-1] > 0.5 * CAP    # saturated at (just under) the cap
    assert (await living.get_job(WORKER, SCOPE_B, job)).attempt == 0


async def test_release_then_deferred_source_acquires_within_cap_window_and_succeeds():
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    job = await enqueue(living, 1, SCOPE_B)
    with hold(budget):
        for _ in range(THRESHOLD + 1):
            result = await b.run_job(job, forbidden)
            living.clock.advance(seconds_until(living, result.not_before))
        result = await b.run_job(job, forbidden)
        assert result.starved is True
    # Holder released, but nothing wakes B: it still waits out its own gate (documented).
    assert budget.active_total == 0
    assert (await b.run_job(job, forbidden)).status is RunStatus.NOT_YET
    assert seconds_until(living, b.not_before(job)) <= CAP
    living.clock.advance(CAP)                                  # the whole cap window, no sleeping
    assert (await b.run_job(job, succeed)).status is RunStatus.SUCCEEDED
    assert (await living.get_job(WORKER, SCOPE_B, job)).state == "SUCCEEDED"
    assert b.not_before(job) is None and budget.active_total == 0


async def test_several_deferred_sources_all_acquire_within_cap_window_after_release():
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    c = source(living, budget, SCOPE_C, ALIAS_C, config=FAIR_CFG)
    job_b, job_c = await enqueue(living, 1, SCOPE_B), await enqueue(living, 2, SCOPE_C)
    with hold(budget):
        assert (await b.run_job(job_b, forbidden)).status is RunStatus.DEFERRED_BUDGET
        assert (await c.run_job(job_c, forbidden)).status is RunStatus.DEFERRED_BUDGET
    living.clock.advance(CAP)
    assert (await b.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED
    assert (await c.run_job(job_c, succeed)).status is RunStatus.SUCCEEDED     # B released on finish
    assert budget.active_total == 0


async def test_real_scheduler_holder_blocks_another_source_until_its_work_ends():
    living, budget = world()
    a = source(living, budget, SCOPE_A, ALIAS_A)
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    job_a, job_b = await enqueue(living, 1, SCOPE_A), await enqueue(living, 2, SCOPE_B)
    seen = {}

    async def holder(handle):
        assert budget.active_total == 1
        seen["b"] = await b.run_job(job_b, forbidden)         # B contends while A's work runs
        return OK

    assert (await a.run_job(job_a, holder)).status is RunStatus.SUCCEEDED
    assert seen["b"].status is RunStatus.DEFERRED_BUDGET
    assert budget.active_total == 0
    living.clock.advance(CAP)
    assert (await b.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED


async def test_no_fairness_fresh_source_takes_slot_before_long_deferred_source():
    """OBSERVED, not a guarantee: after release a fresh source (no gate) runs immediately, while the
    long-deferred, starved source is still NOT_YET for up to the cap."""
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    c = source(living, budget, SCOPE_C, ALIAS_C, config=FAIR_CFG)
    job_b, job_c = await enqueue(living, 1, SCOPE_B), await enqueue(living, 2, SCOPE_C)
    with hold(budget):
        for _ in range(THRESHOLD + 2):
            result = await b.run_job(job_b, forbidden)
            living.clock.advance(seconds_until(living, result.not_before))
        result = await b.run_job(job_b, forbidden)
        assert result.starved is True and result.deferrals == THRESHOLD + 3
    seen = {}
    assert (await c.run_job(job_c, contender(seen, b, job_b))).status is RunStatus.SUCCEEDED
    assert seen["b"].status is RunStatus.NOT_YET              # C ran at once; B was still gated
    # Next C job takes the slot again exactly when B's gate opens: B loses a second time.
    job_c2 = await enqueue(living, 3, SCOPE_C)
    living.clock.advance(seconds_until(living, b.not_before(job_b)))
    seen2 = {}
    assert (await c.run_job(job_c2, contender(seen2, b, job_b))).status is RunStatus.SUCCEEDED
    assert seen2["b"].status is RunStatus.DEFERRED_BUDGET
    assert seen2["b"].deferrals == THRESHOLD + 4 and seen2["b"].starved is True    # no aging/reset
    assert (await living.get_job(WORKER, SCOPE_B, job_b)).attempt == 0


async def test_no_fairness_continuous_fresh_arrivals_can_defer_one_job_indefinitely():
    """OBSERVED, not a guarantee: no queue/aging, so every retry of B can lose to a different holder.
    B stays PENDING at attempt 0 with a growing deferral count; only ``starved`` reports it."""
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    c = source(living, budget, SCOPE_C, ALIAS_C, config=FAIR_CFG)
    job_b = await enqueue(living, 99, SCOPE_B)
    rounds = 8
    for n in range(rounds):
        job_c = await enqueue(living, n + 1, SCOPE_C)
        seen = {}
        contend = contender(seen, b, job_b)
        assert (await c.run_job(job_c, contend)).status is RunStatus.SUCCEEDED
        assert seen["b"].status is RunStatus.DEFERRED_BUDGET and seen["b"].deferrals == n + 1
        assert seen["b"].starved is (n + 1 >= THRESHOLD)
        living.clock.advance(seconds_until(living, seen["b"].not_before))   # B retries at its gate
    assert (await living.get_job(WORKER, SCOPE_B, job_b)).attempt == 0
    # Only once nobody holds the slot does B get through, within the cap window.
    assert (await b.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED


# =========================================================================== guard sensitivity
async def deferral_series(config, rounds=9):
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=config)
    job = await enqueue(living, 1, SCOPE_B)
    out = []
    with hold(budget):
        for _ in range(rounds):
            result = await b.run_job(job, forbidden)
            out.append((seconds_until(living, result.not_before), result.starved))
            living.clock.advance(seconds_until(living, result.not_before))
    return out


async def test_sensitivity_without_deferral_cap_delay_exceeds_it():
    capped = await deferral_series(FAIR_CFG)
    uncapped = await deferral_series(SchedulerConfig(
        backoff_base=1.0, backoff_cap=300.0, deferral_cap_seconds=10_000.0,
        deferral_alert_threshold=THRESHOLD))
    assert max(d for d, _ in capped) <= CAP
    assert max(d for d, _ in uncapped) > CAP                  # the cap assertion would fail here


async def test_sensitivity_threshold_controls_the_starved_flag():
    low = await deferral_series(FAIR_CFG)
    never = await deferral_series(SchedulerConfig(
        backoff_base=1.0, deferral_cap_seconds=CAP, deferral_alert_threshold=1_000_000))
    assert any(s for _, s in low) and not any(s for _, s in never)


async def test_sensitivity_capacity_two_removes_the_deferral():
    living, budget = world(per_backend=2)
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    job = await enqueue(living, 1, SCOPE_B)
    with hold(budget):                                        # one of two slots taken: not saturated
        assert (await b.run_job(job, succeed)).status is RunStatus.SUCCEEDED


async def test_sensitivity_only_capacity_errors_are_deferrals(monkeypatch):
    """A different budget error must NOT be turned into a deferral (it would hide a bad backend id)."""
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    job = await enqueue(living, 1, SCOPE_B)

    def broken(*, trusted_backend_id):
        raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")
    monkeypatch.setattr(budget, "reserve", broken)
    with pytest.raises(BackendCapacityError, match="UNVERIFIED_BACKEND_IDENTITY"):
        await b.run_job(job, forbidden)
    assert b.not_before(job) is None and b.counter.consecutive_failures == 0


async def test_sensitivity_gate_import_roundtrip_resets_deferral_count():
    """Deferral counts are in memory only: a restart (snapshot import) restarts the starvation count
    while the retry gate survives. Pins the real behaviour so a persistence change is noticed."""
    living, budget = world()
    b = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG)
    job = await enqueue(living, 1, SCOPE_B)
    with hold(budget):
        for _ in range(THRESHOLD):
            result = await b.run_job(job, forbidden)
            living.clock.advance(seconds_until(living, result.not_before))
        assert (await b.run_job(job, forbidden)).starved is True
        snap = b.export_state()
        restarted = source(living, budget, SCOPE_B, ALIAS_B, config=FAIR_CFG, state=snap)
        assert restarted.not_before(job) == b.not_before(job)
        assert isinstance(snap, SchedulerState)
        living.clock.advance(seconds_until(living, b.not_before(job)))
        again = await restarted.run_job(job, forbidden)
    assert again.status is RunStatus.DEFERRED_BUDGET
    assert again.deferrals == 1 and again.starved is False     # count lost on restart
