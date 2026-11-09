"""Phase 2 per-source scheduler: pure logic over the job-queue port (lease + fence).

No wall clock and no global randomness: time comes from an injected ``clock`` and jitter from an
injected ``jitter_source`` (a callable returning a float in ``[0, 1)``), so every decision is
deterministic under test.

Responsibilities
- ``backoff_delay``: exponential backoff with bounded jitter, never above the cap.
- ``SourceStateMachine``: ACTIVE -> PAUSED -> QUARANTINED with validated transitions; only an
  explicit ``resume`` leaves QUARANTINED.
- ``SourceScheduler.run_job``: one job of one source at a time. Order of guards: poisoned, source
  state, scheduler-side not-before gate, physical-backend budget, separate ``reap``, lease acquire
  (the port denies a second lease for the source), fence verification, work with lease renewal,
  finish. A stale fence is a lost lease: work stops and ``finish_job`` is never attempted. A denied
  budget defers the job (small bounded backoff) without consuming an attempt. After
  ``min(poison_after, max_attempts)`` failed attempts the job is finished FAILED with a
  ``POISONED:`` error and is never run automatically again.

Failure accounting: every outcome of ``work`` is accounted. A value that is not a
``CaptureOutcomeKind`` is the failure ``WORK_RETURNED_INVALID``; a raised exception is recorded only
as ``WORK_EXCEPTION:<ClassName>`` (raw exception text can carry URLs, DSNs or credentials and is
never persisted or returned). An own-lease expiry is counted as a TIMEOUT failure, gated and
poison-eligible; a stale fence caused by someone else is a lost lease that is not counted.

Port notes: the job port has no "release for retry" call, so a retryable failure abandons the lease
and lets ``reap_expired_jobs`` requeue it at ``lease_until + 2^attempt`` (the port owns that
transition); the scheduler-side ``not_before`` gate is therefore never earlier than that instant.
``acquire_job`` also reaps but rolls the reap back on ``JOB_UNAVAILABLE``, which is why the separate
``reap()`` call is kept. POISONED is a scheduler-level terminal marker over port state FAILED.

Restart: the scheduler state (source state machine, pause count, failure counter, poisoned set and
retry gates) lives in memory. ``export_state()`` returns a ``SchedulerState`` snapshot and the
constructor / ``import_state()`` restores it. PERSISTING THE SNAPSHOT IS THE CALLER'S DUTY; a
scheduler built without a snapshot starts ACTIVE with zero counters but remains fenced until the
caller completes the scope/cursor revalidation handshake. Poison is additionally derived from the
port: a FAILED job whose ``last_error`` starts with ``POISONED:`` is poisoned even if the local set
was lost.
"""
from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from .backend_budget import BackendCapacityError, BackendId, PhysicalBackendBudget, WorkClass
from .drift import CaptureOutcomeKind, FailureCounter
from .ports import CursorOutboxPort, JobQueuePort, LedgerPort, PortError, Scope
from .resnapshot import ResnapshotTracker

__all__ = [
    "IllegalTransition", "LeaseHandle", "LeaseLost", "RunResult", "RunStatus", "SchedulerConfig",
    "SchedulerState", "SourceScheduler", "SourceState", "SourceStateMachine", "backoff_delay",
]

_MAX_EXPONENT: Final = 62
_MAX_SECONDS: Final = 10_000_000.0
_COMPLETE_KINDS: Final = frozenset({
    CaptureOutcomeKind.OK_COMPLETE, CaptureOutcomeKind.SCHEMA_CHANGED,
})
_SUCCESS_KINDS: Final = _COMPLETE_KINDS | {CaptureOutcomeKind.OK_PARTIAL}
_SCOPE_CODES: Final = frozenset({"SCOPE_REVOKED", "PERMISSION_DENIED", "SCOPE_NOT_GRANTED"})
_LEASE_LOST_CODES: Final = frozenset({"LEASE_EXPIRED", "STALE_JOB_FENCE"}) | _SCOPE_CODES
POISON_PREFIX: Final = "POISONED:"


def backoff_delay(attempt: int, base: float, cap: float,
                  jitter_source: Callable[[], float]) -> float:
    """Exponential backoff in ``[ceiling/2, ceiling)`` with ``ceiling = min(cap, base * 2**attempt)``.

    ``attempt`` is zero based. The result never exceeds ``cap``. ``jitter_source`` must return a
    float in ``[0, 1)``; anything else is rejected rather than clamped.
    """
    if type(attempt) is not int or attempt < 0:
        raise ValueError("BACKOFF_ATTEMPT_INVALID")
    if not isinstance(base, (int, float)) or isinstance(base, bool) or not base > 0:
        raise ValueError("BACKOFF_BASE_INVALID")
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not cap > 0:
        raise ValueError("BACKOFF_CAP_INVALID")
    ceiling = min(float(cap), float(base) * float(2 ** min(attempt, _MAX_EXPONENT)))
    jitter = jitter_source()
    if not isinstance(jitter, (int, float)) or not 0.0 <= jitter < 1.0:
        raise ValueError("BACKOFF_JITTER_INVALID")
    return min(float(cap), ceiling * (0.5 + 0.5 * float(jitter)))


# --------------------------------------------------------------------------- source state machine
class SourceState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    QUARANTINED = "QUARANTINED"


class IllegalTransition(Exception):
    """A source state transition that the machine does not allow."""


_ALLOWED: Final = frozenset({
    (SourceState.ACTIVE, SourceState.PAUSED),
    (SourceState.PAUSED, SourceState.ACTIVE),
    (SourceState.PAUSED, SourceState.QUARANTINED),
    (SourceState.QUARANTINED, SourceState.ACTIVE),
})


class SourceStateMachine:
    """ACTIVE -> PAUSED -> QUARANTINED. Leaving QUARANTINED needs an explicit ``resume``."""

    def __init__(self, state: SourceState = SourceState.ACTIVE) -> None:
        if not isinstance(state, SourceState):
            raise TypeError("SOURCE_STATE_INVALID")
        self.state = state
        self.reason = ""
        self.pause_count = 0
        self.resume_validation_required = False

    def _go(self, target: SourceState, reason: str) -> None:
        if (self.state, target) not in _ALLOWED:
            raise IllegalTransition(f"{self.state.value}->{target.value}")
        self.state, self.reason = target, reason

    def pause(self, reason: str) -> None:
        self._go(SourceState.PAUSED, reason)
        self.pause_count += 1

    def quarantine(self, reason: str) -> None:
        self._go(SourceState.QUARANTINED, reason)

    def resume(self, by: str) -> None:
        """Explicit operator resume from PAUSED or QUARANTINED."""
        if not by or not by.strip():
            raise IllegalTransition("RESUME_REQUIRES_EXPLICIT_ACTOR")
        self._go(SourceState.ACTIVE, f"resumed by {by}")
        self.resume_validation_required = True


# --------------------------------------------------------------------------- scheduler
class LeaseLost(Exception):
    """The fence is stale or the lease expired: the holder must stop and not finish the job."""


class RunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    POISONED = "POISONED"
    DEFERRED_BUDGET = "DEFERRED_BUDGET"
    NOT_YET = "NOT_YET"
    SOURCE_NOT_ACTIVE = "SOURCE_NOT_ACTIVE"
    LEASE_DENIED = "LEASE_DENIED"
    LEASE_LOST = "LEASE_LOST"
    EXHAUSTED = "EXHAUSTED"  # FAILED in the port without the POISONED: marker (attempts used up)
    ALREADY_SUCCEEDED = "ALREADY_SUCCEEDED"
    CANCELLED = "CANCELLED"
    JOB_MISSING = "JOB_MISSING"


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    not_before: datetime | None = None
    detail: str = ""
    deferrals: int = 0   # consecutive budget deferrals of this job (budget path only)
    starved: bool = False  # deferrals reached ``SchedulerConfig.deferral_alert_threshold``


def _check_int(value: object, name: str, lo: int, hi: int) -> None:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(name)


def _check_float(value: object, name: str, lo: float, hi: float, *, lo_open: bool) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value > hi
            or (value <= lo if lo_open else value < lo)):
        raise ValueError(name)


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    lease_seconds: int = 60
    renew_margin_seconds: float = 20.0
    poison_after: int = 5
    backoff_base: float = 1.0
    backoff_cap: float = 300.0
    quarantine_after_pauses: int = 3
    deferral_cap_seconds: float = 30.0   # budget deferral never waits longer than this
    deferral_alert_threshold: int = 5    # deferrals after which RunResult.starved is True

    def __post_init__(self) -> None:
        _check_int(self.lease_seconds, "LEASE_SECONDS_INVALID", 1, 300)
        _check_float(self.renew_margin_seconds, "RENEW_MARGIN_INVALID", 0.0, _MAX_SECONDS,
                     lo_open=False)
        if self.renew_margin_seconds >= self.lease_seconds:
            raise ValueError("RENEW_MARGIN_INVALID")
        _check_int(self.poison_after, "SCHEDULER_LIMIT_INVALID", 1, 1000)
        _check_int(self.quarantine_after_pauses, "SCHEDULER_LIMIT_INVALID", 1, 1000)
        _check_float(self.backoff_base, "BACKOFF_CONFIG_INVALID", 0.0, _MAX_SECONDS, lo_open=True)
        _check_float(self.backoff_cap, "BACKOFF_CONFIG_INVALID", 0.0, _MAX_SECONDS, lo_open=True)
        _check_float(self.deferral_cap_seconds, "DEFERRAL_CONFIG_INVALID", 0.0, _MAX_SECONDS,
                     lo_open=True)
        _check_int(self.deferral_alert_threshold, "DEFERRAL_CONFIG_INVALID", 1, 1_000_000)


@dataclass(frozen=True, slots=True)
class SchedulerState:
    """Persistable, source-bound snapshot of in-memory scheduler state (caller stores it)."""
    source_state: SourceState = SourceState.ACTIVE
    reason: str = ""
    pause_count: int = 0
    consecutive_failures: int = 0
    failure_threshold: int = 3
    poisoned: frozenset[UUID] = frozenset()
    not_before: tuple[tuple[UUID, datetime], ...] = ()
    # None identifies snapshots produced before this field existed; import fails closed.
    resume_validation_required: bool | None = None
    # Snapshots are only valid for the exact tenant/source pair that produced them.
    scope: Scope | None = None


class LeaseHandle:
    """What the work callable sees: renew-before-expiry and the fence it must keep using."""

    def __init__(self, scheduler: SourceScheduler, job_id: UUID, fence: int,
                 lease_until: datetime, attempt: int = 1, max_attempts: int = 1) -> None:
        self._s = scheduler
        self.job_id = job_id
        self.fence = fence
        self.lease_until = lease_until
        self.attempt = attempt
        self.max_attempts = max_attempts

    async def ensure_fresh(self) -> None:
        """Renew when within the margin of expiry; raise ``LeaseLost`` on a stale fence/expiry."""
        s = self._s
        now = s._clock()
        if now >= self.lease_until:
            raise LeaseLost("LEASE_EXPIRED")
        if self.lease_until - now > timedelta(seconds=s.config.renew_margin_seconds):
            return
        try:
            self.lease_until = await s._port.renew_lease(
                s._actor, s._scope, self.job_id, s._worker, self.fence, s.config.lease_seconds)
        except PortError as exc:
            if exc.code == "STALE_JOB_FENCE" or exc.code in _SCOPE_CODES:
                raise LeaseLost(exc.code) from exc
            raise


Work = Callable[[LeaseHandle], Awaitable[CaptureOutcomeKind]]


def _code(value: object) -> str:
    """A port error code safe to persist/return (stable upper-case tokens only)."""
    text = str(value)
    return text if text.isascii() and text.replace("_", "").isalnum() and text.isupper() \
        and len(text) <= 48 else "PORT_ERROR"


class SourceScheduler:
    """Runs jobs of ONE source (scope) one at a time through the job-queue port."""

    def __init__(self, port: JobQueuePort, *, actor: str, scope: Scope, worker: str,
                 backend_id: BackendId, budget: PhysicalBackendBudget,
                 clock: Callable[[], datetime], jitter_source: Callable[[], float],
                 config: SchedulerConfig | None = None,
                 machine: SourceStateMachine | None = None,
                 counter: FailureCounter | None = None,
                 state: SchedulerState | None = None) -> None:
        self._port, self._actor, self._scope, self._worker = port, actor, scope, worker
        self._backend, self._budget = backend_id, budget
        self._clock, self._jitter = clock, jitter_source
        self.config = config or SchedulerConfig()
        self.machine = machine or SourceStateMachine()
        # Missing state cannot prove that this is a first-ever start rather than a restart.
        # Require the same scope/cursor handshake used by resume before any job can execute.
        self.machine.resume_validation_required = True
        self.counter = counter or FailureCounter()
        self._not_before: dict[UUID, datetime] = {}
        self._deferrals: dict[UUID, int] = {}
        self._owned_fences: dict[UUID, int] = {}
        self._poisoned: set[UUID] = set()
        if state is not None:
            if machine is not None or counter is not None:
                raise ValueError("STATE_AND_MACHINE_EXCLUSIVE")
            self.import_state(state)

    # ------------------------------------------------------------------ persistence
    def export_state(self) -> SchedulerState:
        return SchedulerState(
            self.machine.state, self.machine.reason, self.machine.pause_count,
            self.counter.consecutive_failures, self.counter.threshold,
            frozenset(self._poisoned), tuple(sorted(self._not_before.items())),
            self.machine.resume_validation_required, self._scope)

    def import_state(self, state: SchedulerState) -> None:
        """Restore a persisted snapshot (QUARANTINED stays QUARANTINED).

        The input is validated completely before anything is changed. A snapshot without the exact
        source scope is rejected so pause, poison and retry state cannot bleed across sources.
        Every imported snapshot also requires fresh scope/cursor revalidation; persisted validation
        is not proof that permissions or cursors are still current after a restart. Poison is merged
        with the live local set, so a stale same-source snapshot never un-poisons a job.
        """
        if not isinstance(state, SchedulerState) or not isinstance(state.source_state, SourceState):
            raise TypeError("SCHEDULER_STATE_INVALID")
        if not isinstance(getattr(state, "scope", None), Scope) or state.scope != self._scope:
            raise ValueError("SCHEDULER_STATE_SCOPE_MISMATCH")
        resume_validation_required = getattr(state, "resume_validation_required", None)
        if resume_validation_required is not None and type(resume_validation_required) is not bool:
            raise ValueError("SCHEDULER_STATE_INVALID")
        for count in (state.pause_count, state.consecutive_failures, state.failure_threshold):
            if type(count) is not int or count < 0:
                raise ValueError("SCHEDULER_STATE_INVALID")
        try:
            poisoned = set(state.poisoned)
            gates = dict(state.not_before)
        except (TypeError, ValueError):
            raise ValueError("SCHEDULER_STATE_INVALID") from None
        if not all(type(j) is UUID for j in poisoned) or not all(
                type(j) is UUID and isinstance(at, datetime) and at.utcoffset() is not None
                for j, at in gates.items()):
            raise ValueError("SCHEDULER_STATE_INVALID")
        try:
            counter = FailureCounter(state.consecutive_failures, state.failure_threshold)
        except (TypeError, ValueError):
            raise ValueError("SCHEDULER_STATE_INVALID") from None
        machine = SourceStateMachine(state.source_state)
        machine.reason, machine.pause_count = str(state.reason), state.pause_count
        # A persisted `False` can go stale while the scheduler is stopped. Every restore must
        # revalidate scope and cursors before work, including snapshots previously marked current.
        machine.resume_validation_required = True
        self.machine, self.counter = machine, counter
        self._poisoned |= poisoned
        self._not_before = gates
        self._deferrals = {}

    def is_poisoned(self, job_id: UUID) -> bool:
        return job_id in self._poisoned

    def not_before(self, job_id: UUID) -> datetime | None:
        return self._not_before.get(job_id)

    async def reap(self) -> int:
        """Requeue (or fail) jobs whose lease expired, through the port."""
        return await self._port.reap_expired_jobs(self._actor, self._scope)

    async def job_state(self, job_id: UUID) -> str | None:
        """Read the exact source-scoped queue state for a job."""
        view = await self._port.get_job(self._actor, self._scope, job_id)
        return None if view is None else view.state

    async def cancel_owned_job(self, job_id: UUID) -> str | None:
        """Atomically cancel queued work or the exact lease previously acquired by this scheduler."""
        fence = self._owned_fences.get(job_id)
        state = await self._port.cancel_job(
            self._actor, self._scope, job_id,
            self._worker if fence is not None else None, fence,
        )
        if state in {"SUCCEEDED", "FAILED", "CANCELLED"} or state is None:
            self._forget(job_id)
        return state

    async def enqueue_capture_job(self, job_id: UUID, request_digest: str,
                                  payload: dict[str, Any]) -> UUID:
        """Enqueue one capture under this scheduler's server-owned actor and exact source scope."""
        if type(job_id) is not UUID:
            raise ValueError("JOB_ID_INVALID")
        if (type(request_digest) is not str or len(request_digest) != 64
                or any(char not in "0123456789abcdef" for char in request_digest)):
            raise ValueError("REQUEST_DIGEST_INVALID")
        if type(payload) is not dict:
            raise ValueError("JOB_PAYLOAD_INVALID")
        return await self._port.enqueue_job(
            self._actor, self._scope, job_id, "CAPTURE", request_digest,
            f"capture:{job_id.hex}", payload)

    async def _finish_cancelled(self, job_id: UUID, fence: int) -> None:
        try:
            await asyncio.shield(self._port.finish_job(
                self._actor, self._scope, job_id, self._worker, fence,
                "CANCELLED", "KILL_SWITCH_CANCELLED",
            ))
        except PortError as exc:
            raise RuntimeError("JOB_CANCELLATION_NOT_CONFIRMED") from exc

    def resume(self, by: str) -> None:
        """Request resume; jobs remain fenced until ``resume_revalidated`` succeeds."""
        self.machine.resume(by)
        self.counter = FailureCounter(0, self.counter.threshold)

    async def resume_revalidated(self, by: str, *, tracker: ResnapshotTracker, ledger: LedgerPort,
                                 cursors: CursorOutboxPort, connection_ids: Iterable[str],
                                 recorded_epoch: int) -> tuple[str, ...]:
        """Revalidate scope epoch and cursors FIRST, then resume; returns connections to resnapshot.

        ``ResnapshotBlocked`` propagates before anything changes: the source keeps its current
        non-ACTIVE state and the failure counter is not reset. ``resume`` itself is unchanged.
        """
        required = await tracker.revalidate(
            ledger, cursors, self._actor, self._scope, connection_ids, recorded_epoch)
        if self.machine.state is not SourceState.ACTIVE:
            self.machine.resume(by)
        elif not self.machine.resume_validation_required:
            raise IllegalTransition("RESUME_REVALIDATION_NOT_REQUIRED")
        elif not by or not by.strip():
            raise IllegalTransition("RESUME_REQUIRES_EXPLICIT_ACTOR")
        self.machine.resume_validation_required = False
        self.counter = FailureCounter(0, self.counter.threshold)
        return required

    def _delay(self, n: int) -> timedelta:
        return timedelta(seconds=backoff_delay(
            n, self.config.backoff_base, self.config.backoff_cap, self._jitter))

    def _forget(self, job_id: UUID) -> None:
        self._not_before.pop(job_id, None)
        self._deferrals.pop(job_id, None)
        self._owned_fences.pop(job_id, None)
        self._budget.cancel_waiter(trusted_backend_id=self._backend, waiter_id=job_id)

    def _gate_for_abandoned(self, job_id: UUID, handle: LeaseHandle, own_at: datetime) -> datetime:
        """Gate never earlier than the instant the port requeues the abandoned lease."""
        port_backoff = min(300, 2 ** min(handle.attempt, 8))
        at = max(own_at, handle.lease_until + timedelta(seconds=port_backoff))
        self._not_before[job_id] = at
        return at

    def _threshold(self, max_attempts: int) -> int:
        return min(self.config.poison_after, max_attempts)

    # ------------------------------------------------------------------ run
    async def run_job(self, job_id: UUID, work: Work,
                      work_class: WorkClass = WorkClass.CAPTURE) -> RunResult:
        if job_id in self._poisoned:
            return RunResult(RunStatus.POISONED, detail="already poisoned")
        if self.machine.state is not SourceState.ACTIVE:
            return RunResult(RunStatus.SOURCE_NOT_ACTIVE, detail=self.machine.state.value)
        if self.machine.resume_validation_required:
            return RunResult(RunStatus.SOURCE_NOT_ACTIVE, detail="RESUME_REVALIDATION_REQUIRED")
        gate = self._not_before.get(job_id)
        if gate is not None and self._clock() < gate:
            return RunResult(RunStatus.NOT_YET, gate)
        with ExitStack() as stack:
            try:
                stack.enter_context(self._budget.reserve(
                    trusted_backend_id=self._backend, work_class=work_class, waiter_id=job_id))
            except BackendCapacityError as exc:
                if str(exc) not in {"BACKEND_CAPACITY_EXCEEDED", "BACKEND_WAIT_QUEUE_FULL"}:
                    raise
                return self._defer(job_id, str(exc))
            # Reap separately: a JOB_UNAVAILABLE acquire aborts its own transaction, which would
            # roll back a reap done inside it and leave an abandoned lease RUNNING forever.
            try:
                await self.reap()
                acquire_task = asyncio.create_task(self._port.acquire_job(
                    self._actor, self._scope, job_id, self._worker, self.config.lease_seconds))
                try:
                    fence = await asyncio.shield(acquire_task)
                except asyncio.CancelledError:
                    # The queue transaction may commit just before cancellation reaches this task.
                    # Keep its result alive long enough to record and cancel this exact lease.
                    try:
                        fence = await acquire_task
                    except PortError:
                        raise asyncio.CancelledError from None
                    self._owned_fences[job_id] = fence
                    await self._finish_cancelled(job_id, fence)
                    self._forget(job_id)
                    raise
            except PortError as exc:
                if exc.code in _SCOPE_CODES:
                    return RunResult(RunStatus.SOURCE_NOT_ACTIVE, detail=exc.code)
                if exc.code == "JOB_UNAVAILABLE":
                    return await self._unavailable(job_id)
                raise
            self._owned_fences[job_id] = fence
            self._deferrals.pop(job_id, None)
            try:
                view = await self._port.get_job(self._actor, self._scope, job_id)
            except asyncio.CancelledError:
                await self._finish_cancelled(job_id, fence)
                self._forget(job_id)
                raise
            except PortError as exc:
                return RunResult(RunStatus.LEASE_LOST, detail=_code(exc.code))
            if (view is None or view.lease_until is None or view.fence != fence
                    or view.state != "RUNNING" or view.lease_owner != self._worker):
                return RunResult(RunStatus.LEASE_LOST, detail="ACQUIRE_NOT_VERIFIED")
            handle = LeaseHandle(self, job_id, fence, view.lease_until, view.attempt,
                                 view.max_attempts)
            try:
                outcome = await work(handle)
            except LeaseLost as exc:
                code = str(exc) if str(exc) in _LEASE_LOST_CODES else "LEASE_LOST"
                return self._lease_lost(job_id, handle, code)
            except asyncio.CancelledError:
                await self._finish_cancelled(job_id, fence)
                self._forget(job_id)
                raise
            except Exception as exc:  # noqa: BLE001 - work failure is data for the failure policy
                return await self._failed(job_id, handle, CaptureOutcomeKind.OUTAGE,
                                          f"WORK_EXCEPTION:{type(exc).__name__[:64]}")
            if not isinstance(outcome, CaptureOutcomeKind):
                return await self._failed(job_id, handle, CaptureOutcomeKind.OUTAGE,
                                          "WORK_RETURNED_INVALID")
            if outcome in _SUCCESS_KINDS:
                return await self._succeeded(job_id, handle, outcome)
            return await self._failed(job_id, handle, outcome, outcome.value)

    def _defer(self, job_id: UUID, reason: str = "BACKEND_CAPACITY_EXCEEDED") -> RunResult:
        n = self._deferrals.get(job_id, 0)
        self._deferrals[job_id] = n + 1
        delay = min(self._delay(n), timedelta(seconds=self.config.deferral_cap_seconds))
        at = self._clock() + delay
        self._not_before[job_id] = at
        return RunResult(RunStatus.DEFERRED_BUDGET, at, reason,
                         deferrals=n + 1, starved=n + 1 >= self.config.deferral_alert_threshold)

    async def _unavailable(self, job_id: UUID) -> RunResult:
        """JOB_UNAVAILABLE: re-read the job and report why, with a distinct status."""
        try:
            view = await self._port.get_job(self._actor, self._scope, job_id)
        except PortError as exc:
            if exc.code in _SCOPE_CODES:
                return RunResult(RunStatus.SOURCE_NOT_ACTIVE, detail=exc.code)
            return RunResult(RunStatus.LEASE_DENIED, detail="JOB_UNAVAILABLE")
        if view is None:
            self._forget(job_id)
            return RunResult(RunStatus.JOB_MISSING, detail="JOB_MISSING")
        if view.state == "SUCCEEDED":
            self._forget(job_id)
            return RunResult(RunStatus.ALREADY_SUCCEEDED)
        if view.state == "CANCELLED":
            self._forget(job_id)
            return RunResult(RunStatus.CANCELLED)
        if view.state == "FAILED":
            self._forget(job_id)
            if (view.last_error or "").startswith(POISON_PREFIX):
                self._poisoned.add(job_id)
                return RunResult(RunStatus.POISONED, detail="POISONED_IN_PORT")
            return RunResult(RunStatus.EXHAUSTED, detail=(
                "LEASE_EXPIRED" if view.last_error == "LEASE_EXPIRED" else "FAILED"))
        if view.state == "PENDING":
            if view.attempt >= view.max_attempts:
                self._forget(job_id)
                return RunResult(RunStatus.EXHAUSTED, detail="ATTEMPTS_EXHAUSTED")
            if view.next_run_at > self._clock():
                self._not_before[job_id] = max(
                    view.next_run_at, self._not_before.get(job_id, view.next_run_at))
                return RunResult(RunStatus.NOT_YET, view.next_run_at, "PORT_BACKOFF")
            return RunResult(RunStatus.LEASE_DENIED, detail="SOURCE_BUSY")
        return RunResult(RunStatus.LEASE_DENIED, view.lease_until, "LEASE_HELD")

    async def _finish(self, job_id: UUID, handle: LeaseHandle, state: str,
                      error: str | None = None) -> str | None:
        """None when finished; otherwise the stable code of why nothing was written."""
        try:
            await self._port.finish_job(self._actor, self._scope, job_id, self._worker,
                                        handle.fence, state, error)
        except PortError as exc:
            return _code(exc.code)
        self._owned_fences.pop(job_id, None)
        return None

    def _lease_lost(self, job_id: UUID, handle: LeaseHandle, code: str) -> RunResult:
        """Lease lost. Own expiry is accounted (failure + gate + poison-eligible); a stale fence
        caused by someone else is reported without touching the failure counter."""
        expired = code == "LEASE_EXPIRED" or (
            code == "STALE_JOB_FENCE" and self._clock() >= handle.lease_until)
        if not expired:
            return RunResult(RunStatus.LEASE_LOST, detail=code)
        self.counter = self.counter.advance(CaptureOutcomeKind.TIMEOUT)
        if handle.attempt >= self._threshold(handle.max_attempts):
            self._poisoned.add(job_id)
            self._forget(job_id)
            self._escalate("poisoned job", force=True)
            return RunResult(RunStatus.POISONED, detail="LEASE_EXPIRED")
        at = self._gate_for_abandoned(job_id, handle, self._clock())
        if self.counter.escalate:
            self._escalate("consecutive failures", force=False)
        return RunResult(RunStatus.LEASE_LOST, at, "LEASE_EXPIRED")

    def _port_trouble(self, job_id: UUID, handle: LeaseHandle, code: str) -> RunResult:
        """A non-stale port error after acquire: never escapes raw, never leaves the job ungated."""
        if code in _SCOPE_CODES:
            return RunResult(RunStatus.LEASE_LOST, detail=code)
        if code == "STALE_JOB_FENCE":
            return self._lease_lost(job_id, handle, code)
        at = self._gate_for_abandoned(job_id, handle, self._clock())
        return RunResult(RunStatus.LEASE_LOST, at, code)

    async def _succeeded(self, job_id: UUID, handle: LeaseHandle,
                         outcome: CaptureOutcomeKind) -> RunResult:
        err = await self._finish(job_id, handle, "SUCCEEDED")
        if err is not None:
            return self._port_trouble(job_id, handle, err)
        self.counter = self.counter.advance(outcome)
        if outcome in _COMPLETE_KINDS:
            self.machine.pause_count = 0  # only a complete success ends the run of pauses
        self._forget(job_id)
        return RunResult(RunStatus.SUCCEEDED)

    async def _failed(self, job_id: UUID, handle: LeaseHandle, kind: CaptureOutcomeKind,
                      error: str) -> RunResult:
        try:
            view = await self._port.get_job(self._actor, self._scope, job_id)
        except PortError as exc:
            return self._port_trouble(job_id, handle, _code(exc.code))
        if (view is None or view.fence != handle.fence or view.state != "RUNNING"
                or view.lease_owner != self._worker):
            if view is not None and view.state == "RUNNING":
                # Another fence/worker holds the job now: not our lease, nothing to account, and
                # its lease_until must never be adopted.
                return RunResult(RunStatus.LEASE_LOST, detail="STALE_JOB_FENCE")
            return self._lease_lost(job_id, handle, "STALE_JOB_FENCE")
        if view.lease_until is not None:
            handle.lease_until = view.lease_until
        if self._clock() >= handle.lease_until:
            return self._lease_lost(job_id, handle, "LEASE_EXPIRED")
        if view.attempt >= self._threshold(view.max_attempts):
            err = await self._finish(job_id, handle, "FAILED", f"{POISON_PREFIX} {error}")
            if err is not None:
                return self._port_trouble(job_id, handle, err)
            self.counter = self.counter.advance(kind)
            self._poisoned.add(job_id)
            self._forget(job_id)
            self._escalate("poisoned job", force=True)
            return RunResult(RunStatus.POISONED, detail=error)
        self.counter = self.counter.advance(kind)
        at = self._gate_for_abandoned(
            job_id, handle, self._clock() + self._delay(max(view.attempt - 1, 0)))
        if self.counter.escalate:
            self._escalate("consecutive failures", force=False)
        return RunResult(RunStatus.RETRY_SCHEDULED, at, error)

    def _escalate(self, reason: str, *, force: bool) -> None:
        if self.machine.state is not SourceState.ACTIVE:
            return
        if not (force or self.counter.escalate):
            return
        repeated = self.machine.pause_count + 1 >= self.config.quarantine_after_pauses
        self.machine.pause(reason)
        if repeated:
            self.machine.quarantine(f"repeated pauses: {reason}")
