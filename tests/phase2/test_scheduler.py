"""Behavioral tests of the Phase 2 per-source scheduler over the in-memory job-queue port.

Time comes from the fake store clock and jitter from a fixed/seeded source, so every test is
deterministic. Each ``test_guard_*`` pins one guard so that removing the guard turns it red.
"""
import asyncio
import random
from datetime import timedelta
from uuid import UUID

import pytest

from business_ai_gateway.phase2.backend_budget import BackendId, PhysicalBackendBudget
from business_ai_gateway.phase2.drift import CaptureOutcomeKind, FailureCounter
from business_ai_gateway.phase2.fakes import WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import Scope
from business_ai_gateway.phase2.scheduler import (
    IllegalTransition,
    RunStatus,
    SchedulerConfig,
    SourceScheduler,
    SourceState,
    SourceStateMachine,
    backoff_delay,
)

SCOPE = Scope("A", "s1")
DIGEST = "a" * 64
OK = CaptureOutcomeKind.OK_COMPLETE
TIMEOUT = CaptureOutcomeKind.TIMEOUT


def job_uuid(n: int) -> UUID:
    return UUID(int=n)


async def enqueue(living: InMemoryLiving, n: int) -> UUID:
    return await living.enqueue_job(WORKER, SCOPE, job_uuid(n), "sync", DIGEST, f"key-{n}")


def make(living=None, *, per_backend=1, backend="db-1", jitter=0.0, **kw):
    living = living or InMemoryLiving()
    budget = kw.pop("budget", None) or PhysicalBackendBudget(
        per_backend_limit=per_backend, total_limit=max(per_backend, 4))
    sched = SourceScheduler(
        living, actor=WORKER, scope=SCOPE, worker="w1", backend_id=BackendId.normalize(backend),
        budget=budget, clock=living.clock.now, jitter_source=lambda: jitter, **kw)
    return living, budget, sched


async def settle(living, sched):
    """Let an abandoned lease expire, reap it, then pass the port's requeue backoff."""
    living.clock.advance(100)
    await sched.reap()
    living.clock.advance(1000)


async def succeed(handle):
    return OK


async def timeout(handle):
    return TIMEOUT


def forbidden(handle):
    raise AssertionError("work must not run")


# --------------------------------------------------------------------------- backoff
@pytest.mark.parametrize("attempt, base, cap, jitter, expected", [
    (0, 1, 100, 0.0, 0.5),
    (0, 1, 100, 0.5, 0.75),
    (3, 1, 100, 0.0, 4.0),
    (3, 2, 100, 0.0, 8.0),
    (10, 1, 100, 0.0, 50.0),
])
def test_backoff_table(attempt, base, cap, jitter, expected):
    assert backoff_delay(attempt, base, cap, lambda: jitter) == pytest.approx(expected)


def test_guard_backoff_never_exceeds_cap():
    for attempt in (0, 5, 8, 50, 10**6):
        assert backoff_delay(attempt, 1, 100, lambda: 0.999999) <= 100
    assert backoff_delay(10**6, 1.5, 7, lambda: 0.999999) <= 7


def test_backoff_deterministic_under_seed():
    a, b = random.Random(7), random.Random(7)
    one = [backoff_delay(n, 1, 60, a.random) for n in range(12)]
    two = [backoff_delay(n, 1, 60, b.random) for n in range(12)]
    assert one == two and max(one) <= 60 and min(one) > 0


@pytest.mark.parametrize("attempt, base, cap, jitter", [
    (-1, 1, 10, 0.0), (0, 0, 10, 0.0), (0, -1, 10, 0.0), (0, 1, 0, 0.0),
    (0, 1, 10, 1.0), (0, 1, 10, -0.1), (True, 1, 10, 0.0), (0, 1, 10, None),
])
def test_guard_backoff_rejects_invalid_input(attempt, base, cap, jitter):
    with pytest.raises(ValueError):
        backoff_delay(attempt, base, cap, lambda: jitter)


# --------------------------------------------------------------------------- state machine
LEGAL = [
    (SourceState.ACTIVE, "pause", SourceState.PAUSED),
    (SourceState.PAUSED, "quarantine", SourceState.QUARANTINED),
    (SourceState.PAUSED, "resume", SourceState.ACTIVE),
    (SourceState.QUARANTINED, "resume", SourceState.ACTIVE),
]
ILLEGAL = [
    (SourceState.ACTIVE, "quarantine"), (SourceState.ACTIVE, "resume"),
    (SourceState.PAUSED, "pause"), (SourceState.QUARANTINED, "pause"),
    (SourceState.QUARANTINED, "quarantine"),
]


def apply(machine: SourceStateMachine, action: str) -> None:
    if action == "resume":
        machine.resume("operator")
    else:
        getattr(machine, action)("why")


@pytest.mark.parametrize("start, action, end", LEGAL)
def test_state_legal_transitions(start, action, end):
    machine = SourceStateMachine(start)
    apply(machine, action)
    assert machine.state is end


@pytest.mark.parametrize("start, action", ILLEGAL)
def test_guard_illegal_transition_raises_and_keeps_state(start, action):
    machine = SourceStateMachine(start)
    with pytest.raises(IllegalTransition):
        apply(machine, action)
    assert machine.state is start


def test_guard_quarantine_only_leaves_by_explicit_resume():
    machine = SourceStateMachine(SourceState.QUARANTINED)
    for blank in ("", "   "):
        with pytest.raises(IllegalTransition):
            machine.resume(blank)
    assert machine.state is SourceState.QUARANTINED
    machine.resume("alice")
    assert machine.state is SourceState.ACTIVE


# --------------------------------------------------------------------------- happy path + lease
async def test_run_success_finishes_job_and_resets_counter():
    living, _, sched = make(counter=FailureCounter(2, 3))
    job = await enqueue(living, 1)
    result = await sched.run_job(job, succeed)
    assert result.status is RunStatus.SUCCEEDED
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "SUCCEEDED" and view.lease_owner is None
    assert sched.counter.consecutive_failures == 0


async def test_guard_second_job_denied_while_lease_valid():
    living, _, sched = make(per_backend=2)
    j1, j2 = await enqueue(living, 1), await enqueue(living, 2)
    started, release = asyncio.Event(), asyncio.Event()

    async def hold(handle):
        started.set()
        await release.wait()
        return OK

    first = asyncio.create_task(sched.run_job(j1, hold))
    await started.wait()
    second = await sched.run_job(j2, forbidden)
    assert second.status is RunStatus.LEASE_DENIED
    assert (await living.get_job(WORKER, SCOPE, j2)).state == "PENDING"
    release.set()
    assert (await first).status is RunStatus.SUCCEEDED
    assert (await sched.run_job(j2, succeed)).status is RunStatus.SUCCEEDED


async def test_guard_renew_before_expiry_only_inside_margin():
    living, _, sched = make(config=SchedulerConfig(lease_seconds=60, renew_margin_seconds=20))
    job = await enqueue(living, 1)
    seen = {}

    async def work(handle):
        seen["start"] = handle.lease_until
        living.clock.advance(5)
        await handle.ensure_fresh()
        seen["early"] = handle.lease_until
        living.clock.advance(45)  # 50s into a 60s lease: inside the 20s margin
        await handle.ensure_fresh()
        seen["renewed"] = handle.lease_until
        return OK

    assert (await sched.run_job(job, work)).status is RunStatus.SUCCEEDED
    assert seen["early"] == seen["start"]
    assert seen["renewed"] > seen["start"] + timedelta(seconds=40)


async def test_guard_stale_fence_on_renew_is_lost_lease_and_no_finish():
    living, _, sched = make(config=SchedulerConfig(lease_seconds=60, renew_margin_seconds=20))
    job = await enqueue(living, 1)

    async def work(handle):
        # Another actor ends the job under this fence; our fence is now stale.
        await living.finish_job(WORKER, SCOPE, job, "w1", handle.fence, "CANCELLED", "ops")
        living.clock.advance(45)
        await handle.ensure_fresh()
        raise AssertionError("work must stop after the lease is lost")

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.LEASE_LOST
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "CANCELLED" and view.last_error == "ops"
    assert sched.counter.consecutive_failures == 0


async def test_guard_expired_lease_work_result_is_not_committed():
    living, _, sched = make(config=SchedulerConfig(lease_seconds=60, renew_margin_seconds=20))
    job = await enqueue(living, 1)

    async def work(handle):
        living.clock.advance(61)
        await living.reap_expired_jobs(WORKER, SCOPE)
        return OK  # success reported under an expired fence

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.LEASE_LOST
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "PENDING"  # reaped, never finished by the stale holder
    assert sched.counter.consecutive_failures == 0


async def test_guard_expired_lease_detected_locally_before_renew():
    living, _, sched = make(config=SchedulerConfig(lease_seconds=60, renew_margin_seconds=20))
    job = await enqueue(living, 1)

    async def work(handle):
        living.clock.advance(61)
        await handle.ensure_fresh()
        raise AssertionError("unreachable")

    assert (await sched.run_job(job, work)).status is RunStatus.LEASE_LOST


async def test_reap_requeues_abandoned_lease():
    living, _, sched = make()
    job = await enqueue(living, 1)
    assert (await sched.run_job(job, timeout)).status is RunStatus.RETRY_SCHEDULED
    assert (await living.get_job(WORKER, SCOPE, job)).state == "RUNNING"
    living.clock.advance(61)
    assert await sched.reap() == 1
    assert (await living.get_job(WORKER, SCOPE, job)).state == "PENDING"


# --------------------------------------------------------------------------- retry + poison
async def test_failure_schedules_backoff_gate_then_retry_succeeds():
    living, _, sched = make(config=SchedulerConfig(backoff_base=10, backoff_cap=300))
    job = await enqueue(living, 1)
    first = await sched.run_job(job, timeout)
    assert first.status is RunStatus.RETRY_SCHEDULED and first.not_before is not None
    assert sched.not_before(job) == first.not_before
    assert (await sched.run_job(job, forbidden)).status is RunStatus.NOT_YET
    await settle(living, sched)
    assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED
    assert sched.not_before(job) is None


async def test_guard_poison_cap_is_terminal_and_not_retried():
    living, _, sched = make(config=SchedulerConfig(poison_after=2),
                            counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)
    assert (await sched.run_job(job, timeout)).status is RunStatus.RETRY_SCHEDULED
    await settle(living, sched)
    result = await sched.run_job(job, timeout)
    assert result.status is RunStatus.POISONED
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "FAILED" and view.last_error.startswith("POISONED:")
    assert sched.is_poisoned(job)
    attempts = view.attempt
    await settle(living, sched)
    sched.resume("op")  # even an active source never retries a poisoned job
    again = await sched.run_job(job, forbidden)
    assert again.status is RunStatus.POISONED
    assert (await living.get_job(WORKER, SCOPE, job)).attempt == attempts


async def test_guard_below_poison_cap_job_is_retryable_not_poisoned():
    living, _, sched = make(config=SchedulerConfig(poison_after=3), counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)
    for _ in range(2):
        assert (await sched.run_job(job, timeout)).status is RunStatus.RETRY_SCHEDULED
        await settle(living, sched)
    assert not sched.is_poisoned(job)
    assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED


async def test_poison_pauses_source():
    living, _, sched = make(config=SchedulerConfig(poison_after=1), counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)
    assert (await sched.run_job(job, timeout)).status is RunStatus.POISONED
    assert sched.machine.state is SourceState.PAUSED
    other = await enqueue(living, 2)
    assert (await sched.run_job(other, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE


# --------------------------------------------------------------------------- source policy
async def test_consecutive_failures_pause_source_via_failure_counter():
    living, _, sched = make(config=SchedulerConfig(poison_after=10))
    job = await enqueue(living, 1)
    for expected in (1, 2, 3):
        assert (await sched.run_job(job, timeout)).status is RunStatus.RETRY_SCHEDULED
        assert sched.counter.consecutive_failures == expected
        await settle(living, sched)
    assert sched.machine.state is SourceState.PAUSED
    assert (await sched.run_job(job, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE
    sched.resume("operator")
    assert sched.machine.state is SourceState.ACTIVE
    assert sched.counter.consecutive_failures == 0
    assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED


async def test_success_between_failures_resets_counter_no_pause():
    living, _, sched = make(config=SchedulerConfig(poison_after=10))
    j1, j2 = await enqueue(living, 1), await enqueue(living, 2)
    await sched.run_job(j1, timeout)
    await sched.run_job(j1, forbidden)  # gated: not a failure
    await settle(living, sched)
    await sched.run_job(j1, timeout)
    assert sched.counter.consecutive_failures == 2
    await settle(living, sched)
    assert (await sched.run_job(j2, succeed)).status is RunStatus.SUCCEEDED
    assert sched.counter.consecutive_failures == 0
    assert sched.machine.state is SourceState.ACTIVE


async def test_repeated_pauses_without_progress_quarantine_until_explicit_resume():
    living, _, sched = make(
        config=SchedulerConfig(poison_after=10, quarantine_after_pauses=2),
        counter=FailureCounter(0, 1))
    job = await enqueue(living, 1)
    await sched.run_job(job, timeout)
    assert sched.machine.state is SourceState.PAUSED
    sched.resume("operator")
    await settle(living, sched)
    await sched.run_job(job, timeout)
    assert sched.machine.state is SourceState.QUARANTINED
    assert (await sched.run_job(job, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE
    sched.resume("operator")
    await settle(living, sched)
    assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED


async def test_work_exception_is_a_failure_not_a_crash():
    living, _, sched = make()
    job = await enqueue(living, 1)

    async def boom(handle):
        raise RuntimeError("source exploded")

    result = await sched.run_job(job, boom)
    assert result.status is RunStatus.RETRY_SCHEDULED and "source exploded" in result.detail
    assert sched.counter.consecutive_failures == 1


# --------------------------------------------------------------------------- budget
async def test_guard_denied_budget_defers_with_backoff_not_fail_or_poison():
    living, budget, sched = make(config=SchedulerConfig(poison_after=1, backoff_base=1,
                                                         backoff_cap=300))
    job = await enqueue(living, 1)
    delays = []
    with budget.reserve(trusted_backend_id=BackendId.normalize("DB-1 ")):  # same physical backend
        for _ in range(3):
            before = living.clock.now()
            result = await sched.run_job(job, forbidden)
            assert result.status is RunStatus.DEFERRED_BUDGET
            delays.append((result.not_before - before).total_seconds())
            await settle(living, sched)
    assert delays == pytest.approx([0.5, 1.0, 2.0], abs=0.01)  # exponential, jitter fixed at 0
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "PENDING" and view.attempt == 0 and view.last_error is None
    assert not sched.is_poisoned(job)
    assert sched.counter.consecutive_failures == 0
    assert sched.machine.state is SourceState.ACTIVE
    assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED
    assert budget.active_total == 0


async def test_deferred_job_is_gated_until_not_before():
    living, budget, sched = make()
    job = await enqueue(living, 1)
    with budget.reserve(trusted_backend_id=BackendId.normalize("db-1")):
        deferred = await sched.run_job(job, forbidden)
    assert (await sched.run_job(job, forbidden)).status is RunStatus.NOT_YET
    living.clock.advance((deferred.not_before - living.clock.now()).total_seconds() + 1)
    assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED


async def test_other_physical_backend_is_not_blocked():
    living, budget, sched = make(backend="db-2")
    job = await enqueue(living, 1)
    with budget.reserve(trusted_backend_id=BackendId.normalize("db-1")):
        assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED


async def test_budget_released_after_work_failure():
    living, budget, sched = make()
    job = await enqueue(living, 1)
    await sched.run_job(job, timeout)
    assert budget.active_total == 0


def test_config_validation():
    with pytest.raises(ValueError):
        SchedulerConfig(lease_seconds=0)
    with pytest.raises(ValueError):
        SchedulerConfig(lease_seconds=30, renew_margin_seconds=30)
    with pytest.raises(ValueError):
        SchedulerConfig(poison_after=0)
