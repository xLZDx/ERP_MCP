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
from business_ai_gateway.phase2.ports import PortError, Scope
from business_ai_gateway.phase2.scheduler import (
    IllegalTransition,
    RunStatus,
    SchedulerConfig,
    SchedulerState,
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


async def enqueue(living: InMemoryLiving, n: int, scope: Scope = SCOPE) -> UUID:
    return await living.enqueue_job(WORKER, scope, job_uuid(n), "sync", DIGEST, f"key-{n}")


def make(living=None, *, per_backend=1, backend="db-1", jitter=0.0, scope=SCOPE, **kw):
    living = living or InMemoryLiving()
    budget = kw.pop("budget", None) or PhysicalBackendBudget(
        per_backend_limit=per_backend, total_limit=max(per_backend, 4))
    sched = SourceScheduler(
        living, actor=WORKER, scope=scope, worker="w1", backend_id=BackendId.normalize(backend),
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
    assert sched.counter.consecutive_failures == 1  # own lease expiry is an accounted failure
    assert result.not_before is not None and sched.not_before(job) == result.not_before


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
    assert result.status is RunStatus.RETRY_SCHEDULED
    assert result.detail == "WORK_EXCEPTION:RuntimeError"
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


@pytest.mark.parametrize("kw", [
    {"lease_seconds": True}, {"lease_seconds": None}, {"lease_seconds": 30.5},
    {"renew_margin_seconds": float("nan")}, {"renew_margin_seconds": True},
    {"renew_margin_seconds": None}, {"poison_after": True}, {"poison_after": None},
    {"poison_after": 10**9}, {"quarantine_after_pauses": True},
    {"backoff_base": float("inf")}, {"backoff_base": float("nan")}, {"backoff_base": True},
    {"backoff_base": None}, {"backoff_base": 1e30}, {"backoff_cap": float("inf")},
    {"backoff_cap": 1e300}, {"backoff_cap": None}, {"deferral_cap_seconds": float("nan")},
    {"deferral_cap_seconds": 0}, {"deferral_alert_threshold": True},
])
def test_guard_config_rejects_bad_types_and_overflowing_values(kw):
    with pytest.raises(ValueError):
        SchedulerConfig(**kw)


# --------------------------------------------------------------------------- outcome matrix
# kind -> (job state after run, RunStatus, consecutive failures after, last_error)
MATRIX = {
    CaptureOutcomeKind.OK_COMPLETE: ("SUCCEEDED", RunStatus.SUCCEEDED, 0, None),
    CaptureOutcomeKind.SCHEMA_CHANGED: ("SUCCEEDED", RunStatus.SUCCEEDED, 0, None),
    CaptureOutcomeKind.OK_PARTIAL: ("SUCCEEDED", RunStatus.SUCCEEDED, 2, None),  # neutral
    CaptureOutcomeKind.TIMEOUT: ("RUNNING", RunStatus.RETRY_SCHEDULED, 3, None),
    CaptureOutcomeKind.OUTAGE: ("RUNNING", RunStatus.RETRY_SCHEDULED, 3, None),
    CaptureOutcomeKind.ACCESS_DENIED: ("RUNNING", RunStatus.RETRY_SCHEDULED, 3, None),
    CaptureOutcomeKind.CURSOR_LOST: ("RUNNING", RunStatus.RETRY_SCHEDULED, 3, None),
}


def test_matrix_covers_every_outcome_kind():
    assert set(MATRIX) == set(CaptureOutcomeKind)


@pytest.mark.parametrize("kind", list(CaptureOutcomeKind))
async def test_run_job_outcome_matrix(kind):
    state, status, failures, last_error = MATRIX[kind]
    living, _, sched = make(counter=FailureCounter(2, 100))
    job = await enqueue(living, 1)

    async def work(handle):
        return kind

    result = await sched.run_job(job, work)
    view = await living.get_job(WORKER, SCOPE, job)
    assert (view.state, result.status, sched.counter.consecutive_failures,
            view.last_error) == (state, status, failures, last_error)
    assert (sched.not_before(job) is not None) is (status is RunStatus.RETRY_SCHEDULED)
    assert not sched.is_poisoned(job)


@pytest.mark.parametrize("kind, expected_pause_count", [
    (CaptureOutcomeKind.OK_PARTIAL, 2), (CaptureOutcomeKind.OK_COMPLETE, 0),
    (CaptureOutcomeKind.SCHEMA_CHANGED, 0)])
async def test_guard_pause_count_resets_only_on_complete_success(kind, expected_pause_count):
    machine = SourceStateMachine()
    machine.pause_count = 2
    living, _, sched = make(machine=machine)
    job = await enqueue(living, 1)

    async def work(handle):
        return kind

    assert (await sched.run_job(job, work)).status is RunStatus.SUCCEEDED
    assert sched.machine.pause_count == expected_pause_count


# --------------------------------------------------------------------------- work result + secrets
@pytest.mark.parametrize("bad", [None, "OK_COMPLETE", "TIMEOUT", 1, True])
async def test_guard_invalid_work_return_is_a_failure_never_running_unaccounted(bad):
    living, _, sched = make()
    job = await enqueue(living, 1)

    async def work(handle):
        return bad

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.RETRY_SCHEDULED
    assert result.detail == "WORK_RETURNED_INVALID"
    assert sched.counter.consecutive_failures == 1
    assert sched.not_before(job) is not None


async def test_guard_invalid_work_return_poisons_at_cap_with_fixed_code():
    living, _, sched = make(config=SchedulerConfig(poison_after=1), counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)

    async def work(handle):
        return None

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.POISONED
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "FAILED" and view.last_error == "POISONED: WORK_RETURNED_INVALID"


SECRET = "postgresql://svc:hunter2@db.internal:5432/erp?sslmode=require token=abc123"


@pytest.mark.parametrize("poison_after", [5, 1])
async def test_guard_secret_exception_text_is_never_persisted_or_returned(poison_after):
    living, _, sched = make(config=SchedulerConfig(poison_after=poison_after),
                            counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)

    async def work(handle):
        raise ConnectionError(SECRET)

    result = await sched.run_job(job, work)
    view = await living.get_job(WORKER, SCOPE, job)
    blob = f"{result!r} {view!r}"
    assert "hunter2" not in blob and "abc123" not in blob and "postgresql" not in blob
    assert result.detail == "WORK_EXCEPTION:ConnectionError"
    if poison_after == 1:
        assert view.last_error == "POISONED: WORK_EXCEPTION:ConnectionError"


# --------------------------------------------------------------------------- poison threshold
async def test_guard_poison_threshold_is_capped_by_job_max_attempts():
    living, _, sched = make(config=SchedulerConfig(poison_after=100),
                            counter=FailureCounter(0, 1000))
    job = await enqueue(living, 1)
    for _ in range(4):
        assert (await sched.run_job(job, timeout)).status is RunStatus.RETRY_SCHEDULED
        await settle(living, sched)
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.attempt == 4 and view.max_attempts == 5
    last = await sched.run_job(job, timeout)  # attempt 5 == max_attempts: no retry is possible
    assert last.status is RunStatus.POISONED and sched.is_poisoned(job)
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "FAILED" and view.last_error.startswith("POISONED:")


# --------------------------------------------------------------------------- stale fence accounting
async def steal(living, job, handle):
    await living.finish_job(WORKER, SCOPE, job, "w1", handle.fence, "CANCELLED", "ops")


@pytest.mark.parametrize("poison_after", [5, 1])
async def test_guard_stale_fence_on_failure_path_is_lost_lease_not_counted(poison_after):
    living, _, sched = make(config=SchedulerConfig(poison_after=poison_after),
                            counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)

    async def work(handle):
        await steal(living, job, handle)
        return TIMEOUT

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.LEASE_LOST and result.detail == "STALE_JOB_FENCE"
    assert sched.counter.consecutive_failures == 0
    assert not sched.is_poisoned(job) and sched.not_before(job) is None
    assert sched.machine.state is SourceState.ACTIVE
    assert (await living.get_job(WORKER, SCOPE, job)).last_error == "ops"


async def test_guard_stale_fence_on_success_path_is_lost_lease_not_counted():
    living, _, sched = make(counter=FailureCounter(1, 100))

    job = await enqueue(living, 1)

    async def work(handle):
        await steal(living, job, handle)
        return OK

    assert (await sched.run_job(job, work)).status is RunStatus.LEASE_LOST
    assert sched.counter.consecutive_failures == 1  # untouched: no reset either


# --------------------------------------------------------------------------- own lease expiry
async def test_guard_own_lease_expiry_is_counted_gated_and_retried():
    living, _, sched = make(config=SchedulerConfig(backoff_base=0.001, backoff_cap=0.01),
                            counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)
    seen = {}

    async def work(handle):
        seen["until"] = handle.lease_until
        living.clock.advance(61)
        await handle.ensure_fresh()
        return OK

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.LEASE_LOST and result.detail == "LEASE_EXPIRED"
    assert sched.counter.consecutive_failures == 1
    assert result.not_before >= seen["until"] + timedelta(seconds=2)  # port requeue backoff
    assert (await sched.run_job(job, forbidden)).status is RunStatus.NOT_YET
    await settle(living, sched)
    assert (await sched.run_job(job, succeed)).status is RunStatus.SUCCEEDED


async def test_guard_own_lease_expiry_is_poison_eligible():
    living, _, sched = make(config=SchedulerConfig(poison_after=1), counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)

    async def work(handle):
        living.clock.advance(61)
        await handle.ensure_fresh()
        return OK

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.POISONED and sched.is_poisoned(job)
    assert sched.machine.state is SourceState.PAUSED


async def test_guard_own_lease_expiry_counts_toward_source_pause():
    living, _, sched = make(config=SchedulerConfig(poison_after=10), counter=FailureCounter(0, 1))
    job = await enqueue(living, 1)

    async def work(handle):
        living.clock.advance(61)
        await handle.ensure_fresh()
        return OK

    await sched.run_job(job, work)
    assert sched.machine.state is SourceState.PAUSED


async def test_guard_abandoned_lease_gate_is_never_earlier_than_port_requeue():
    living, _, sched = make(config=SchedulerConfig(backoff_base=0.001, backoff_cap=0.01))
    job = await enqueue(living, 1)
    result = await sched.run_job(job, timeout)
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "RUNNING"
    assert result.not_before >= view.lease_until + timedelta(seconds=2)
    living.clock.advance(30)  # inside the lease: the source is still RUNNING in the port
    assert (await sched.run_job(job, forbidden)).status is RunStatus.NOT_YET


async def test_guard_separate_reap_is_needed_because_acquire_rolls_its_reap_back():
    living, _, sched = make(config=SchedulerConfig(backoff_base=0.001, backoff_cap=0.01))
    job = await enqueue(living, 1)
    assert (await sched.run_job(job, timeout)).status is RunStatus.RETRY_SCHEDULED
    living.clock.advance(61)  # lease over, nobody called reap(); a restarted scheduler has no gate
    _, _, fresh = make(living)
    held = await fresh.run_job(job, forbidden)
    assert held.status is RunStatus.NOT_YET and held.detail == "PORT_BACKOFF"
    assert (await living.get_job(WORKER, SCOPE, job)).state == "PENDING"  # reap() committed
    living.clock.advance(3)
    assert (await fresh.run_job(job, succeed)).status is RunStatus.SUCCEEDED


# --------------------------------------------------------------------------- terminal job statuses
async def drain_attempts(living, job):
    for _ in range(5):
        await living.acquire_job(WORKER, SCOPE, job, "w1", 1)
        living.clock.advance(2)
        await living.reap_expired_jobs(WORKER, SCOPE)
        living.clock.advance(1000)


async def test_guard_exhausted_job_has_its_own_status_and_cleans_state():
    living, _, sched = make()
    job = await enqueue(living, 1)
    await drain_attempts(living, job)
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "FAILED" and view.last_error == "LEASE_EXPIRED"
    past = living.clock.now() - timedelta(seconds=5)
    sched.import_state(SchedulerState(not_before=((job, past),)))
    result = await sched.run_job(job, forbidden)
    assert result.status is RunStatus.EXHAUSTED and result.detail == "LEASE_EXPIRED"
    assert not sched.is_poisoned(job) and sched.not_before(job) is None


async def test_guard_port_poison_marker_is_derived_after_state_loss():
    living, _, sched = make(config=SchedulerConfig(poison_after=1), counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)
    assert (await sched.run_job(job, timeout)).status is RunStatus.POISONED
    _, _, restarted = make(living)  # restart without a snapshot
    assert not restarted.is_poisoned(job)
    result = await restarted.run_job(job, forbidden)
    assert result.status is RunStatus.POISONED and restarted.is_poisoned(job)


async def test_guard_succeeded_cancelled_missing_and_held_jobs_have_distinct_statuses():
    living, _, sched = make()
    done, cancelled, held = [await enqueue(living, n) for n in (1, 2, 3)]
    assert (await sched.run_job(done, succeed)).status is RunStatus.SUCCEEDED
    assert (await sched.run_job(done, forbidden)).status is RunStatus.ALREADY_SUCCEEDED
    fence = await living.acquire_job(WORKER, SCOPE, cancelled, "w1", 60)
    await living.finish_job(WORKER, SCOPE, cancelled, "w1", fence, "CANCELLED", "ops")
    assert (await sched.run_job(cancelled, forbidden)).status is RunStatus.CANCELLED
    assert (await sched.run_job(job_uuid(99), forbidden)).status is RunStatus.JOB_MISSING
    await living.acquire_job(WORKER, SCOPE, held, "other", 60)
    result = await sched.run_job(held, forbidden)
    assert result.status is RunStatus.LEASE_DENIED and result.detail == "LEASE_HELD"
    assert result.not_before == (await living.get_job(WORKER, SCOPE, held)).lease_until


async def test_guard_budget_deferral_state_is_cleaned_when_job_is_terminal():
    living, budget, sched = make()
    job = await enqueue(living, 1)
    with budget.reserve(trusted_backend_id=BackendId.normalize("db-1")):
        assert (await sched.run_job(job, forbidden)).deferrals == 1
    fence = await living.acquire_job(WORKER, SCOPE, job, "w1", 60)
    await living.finish_job(WORKER, SCOPE, job, "w1", fence, "SUCCEEDED")
    living.clock.advance(1000)
    assert (await sched.run_job(job, forbidden)).status is RunStatus.ALREADY_SUCCEEDED
    assert sched.not_before(job) is None
    with budget.reserve(trusted_backend_id=BackendId.normalize("db-1")):
        assert (await sched.run_job(job, forbidden)).deferrals == 1  # counter restarted


# --------------------------------------------------------------------------- budget starvation
async def test_guard_budget_deferral_is_capped_and_starvation_is_observable():
    cfg = SchedulerConfig(backoff_base=100, backoff_cap=300, deferral_cap_seconds=5,
                          deferral_alert_threshold=3)
    living, budget, sched = make(config=cfg)
    job = await enqueue(living, 1)
    flags = []
    with budget.reserve(trusted_backend_id=BackendId.normalize("db-1")):
        for _ in range(3):
            before = living.clock.now()
            result = await sched.run_job(job, forbidden)
            assert result.status is RunStatus.DEFERRED_BUDGET
            assert (result.not_before - before).total_seconds() <= 5.01
            flags.append((result.deferrals, result.starved))
            living.clock.advance(10)
    assert flags == [(1, False), (2, False), (3, True)]


# --------------------------------------------------------------------------- restart state
async def test_guard_quarantine_survives_export_import():
    living, _, sched = make(
        config=SchedulerConfig(poison_after=10, quarantine_after_pauses=2),
        counter=FailureCounter(0, 1))
    job = await enqueue(living, 1)
    await sched.run_job(job, timeout)
    sched.resume("operator")
    await settle(living, sched)
    await sched.run_job(job, timeout)
    assert sched.machine.state is SourceState.QUARANTINED
    snapshot = sched.export_state()
    assert snapshot.source_state is SourceState.QUARANTINED and snapshot.pause_count == 2
    _, _, restarted = make(living, config=sched.config, state=snapshot)
    assert restarted.machine.state is SourceState.QUARANTINED
    assert restarted.machine.pause_count == 2
    assert restarted.counter.consecutive_failures == sched.counter.consecutive_failures
    assert restarted.counter.threshold == 1
    assert restarted.not_before(job) == sched.not_before(job)
    assert (await restarted.run_job(job, forbidden)).status is RunStatus.SOURCE_NOT_ACTIVE
    restarted.resume("operator")
    assert restarted.machine.state is SourceState.ACTIVE


async def test_guard_poisoned_set_survives_export_import():
    living, _, sched = make(config=SchedulerConfig(poison_after=1), counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)
    await sched.run_job(job, timeout)
    _, _, restarted = make(living, state=sched.export_state())
    assert restarted.is_poisoned(job)


def test_guard_state_arguments_are_exclusive_and_validated():
    living = InMemoryLiving()
    with pytest.raises(ValueError):
        make(living, machine=SourceStateMachine(), state=SchedulerState())
    with pytest.raises(TypeError):
        make(living, state="QUARANTINED")
    with pytest.raises(ValueError):
        make(living, state=SchedulerState(pause_count=-1))
    with pytest.raises(ValueError):
        make(living, state=SchedulerState(consecutive_failures=-1))


async def test_guard_poisoning_source_a_leaves_source_b_unchanged():
    living = InMemoryLiving()
    scope_b = Scope("A", "s2")
    living.seed_basic(scope_b)
    _, _, a = make(living, config=SchedulerConfig(poison_after=1), counter=FailureCounter(0, 100))
    _, _, b = make(living, scope=scope_b, counter=FailureCounter(1, 100))
    job_a, job_b = await enqueue(living, 1), await enqueue(living, 2, scope_b)
    before = b.export_state()
    assert (await a.run_job(job_a, timeout)).status is RunStatus.POISONED
    assert a.machine.state is SourceState.PAUSED
    assert b.export_state() == before and not b.is_poisoned(job_a)
    assert (await b.run_job(job_b, succeed)).status is RunStatus.SUCCEEDED


# --------------------------------------------------------------------------- port error mapping
class FlakyPort:
    """Delegates to the in-memory port; named calls raise the given PortError instead."""

    def __init__(self, inner, **raises):
        self._inner, self._raises = inner, raises

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        exc = self._raises.get(name)
        if exc is None:
            return target

        async def boom(*args, **kwargs):
            raise exc
        return boom


def flaky(living, **raises):
    _, _, sched = make(FlakyPort(living, **raises))
    sched._clock = living.clock.now
    return sched


@pytest.mark.parametrize("call", ["reap_expired_jobs", "acquire_job"])
@pytest.mark.parametrize("code", ["SCOPE_REVOKED", "PERMISSION_DENIED"])
async def test_guard_scope_errors_before_work_are_source_not_active_not_outage(call, code):
    living = InMemoryLiving()
    job = await enqueue(living, 1)
    sched = flaky(living, **{call: PortError(code)})
    result = await sched.run_job(job, forbidden)
    assert result.status is RunStatus.SOURCE_NOT_ACTIVE and result.detail == code
    assert sched.counter.consecutive_failures == 0


async def test_guard_scope_error_on_finish_is_lease_lost_not_outage():
    living = InMemoryLiving()
    job = await enqueue(living, 1)
    sched = flaky(living, finish_job=PortError("SCOPE_REVOKED"))
    result = await sched.run_job(job, succeed)
    assert result.status is RunStatus.LEASE_LOST and result.detail == "SCOPE_REVOKED"
    assert sched.counter.consecutive_failures == 0


async def test_guard_scope_error_on_renew_is_lease_lost_not_outage():
    living = InMemoryLiving()
    job = await enqueue(living, 1)
    sched = flaky(living, renew_lease=PortError("PERMISSION_DENIED"))

    async def work(handle):
        living.clock.advance(50)
        await handle.ensure_fresh()
        return OK

    result = await sched.run_job(job, work)
    assert result.status is RunStatus.LEASE_LOST and result.detail == "PERMISSION_DENIED"
    assert sched.counter.consecutive_failures == 0


async def test_guard_other_port_error_after_acquire_does_not_escape_and_is_gated():
    living = InMemoryLiving()
    job = await enqueue(living, 1)
    sched = flaky(living, finish_job=PortError("DB_DOWN", "postgresql://u:pw@h/db"))
    result = await sched.run_job(job, succeed)
    assert result.status is RunStatus.LEASE_LOST and result.detail == "DB_DOWN"
    assert "pw" not in repr(result) and sched.not_before(job) == result.not_before
    assert result.not_before is not None


async def test_guard_port_error_from_get_job_on_failure_path_does_not_escape():
    living = InMemoryLiving()
    job = await enqueue(living, 1)
    calls = {"n": 0}
    sched = flaky(living)
    real = sched._port._inner.get_job

    async def get_job(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return await real(*args, **kwargs)  # post-acquire verification
        raise PortError("DB_DOWN")
    sched._port._raises["get_job"] = None
    sched._port.get_job = get_job
    result = await sched.run_job(job, timeout)
    assert result.status is RunStatus.LEASE_LOST and result.not_before is not None


async def test_guard_acquire_is_verified_against_the_returned_fence():
    living = InMemoryLiving()
    job = await enqueue(living, 1)
    sched = flaky(living)
    real = sched._port._inner.get_job

    async def get_job(*args, **kwargs):
        view = await real(*args, **kwargs)
        return None if view is None else type(view)(
            view.job_id, view.state, view.lease_owner, view.lease_until, view.fence + 7,
            view.attempt, view.max_attempts, view.next_run_at, view.last_error, view.scope_epoch)
    sched._port.get_job = get_job
    result = await sched.run_job(job, forbidden)
    assert result.status is RunStatus.LEASE_LOST and result.detail == "ACQUIRE_NOT_VERIFIED"


async def test_guard_cancelled_work_abandons_lease_gates_and_reraises():
    living, budget, sched = make(counter=FailureCounter(0, 100))
    job = await enqueue(living, 1)
    started = asyncio.Event()

    async def hang(handle):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(sched.run_job(job, hang))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    view = await living.get_job(WORKER, SCOPE, job)
    assert view.state == "RUNNING"
    assert sched.not_before(job) >= view.lease_until
    assert sched.counter.consecutive_failures == 0
    assert budget.active_total == 0
