"""Phase 2 per-source scheduler: pure logic over the job-queue port (lease + fence).

No wall clock and no global randomness: time comes from an injected ``clock`` and jitter from an
injected ``jitter_source`` (a callable returning a float in ``[0, 1)``), so every decision is
deterministic under test.

Responsibilities
- ``backoff_delay``: exponential backoff with bounded jitter, never above the cap.
- ``SourceStateMachine``: ACTIVE -> PAUSED -> QUARANTINED with validated transitions; only an
  explicit ``resume`` leaves QUARANTINED.
- ``SourceScheduler.run_job``: one job of one source at a time. Order of guards: source state,
  scheduler-side not-before gate, physical-backend budget, lease acquire (the port denies a second
  lease for the source), work with lease renewal, finish. A stale fence is a lost lease: work stops
  and ``finish_job`` is never attempted. A denied budget defers the job (backoff) without consuming
  an attempt. After ``poison_after`` failed attempts the job is finished FAILED with a ``POISONED:``
  error and is never run automatically again.

Port notes: the job port has no "release for retry" call, so a retryable failure abandons the lease
and lets ``reap_expired_jobs`` requeue it (the port owns that transition); ``not_before`` is the
scheduler-side backoff gate. POISONED is a scheduler-level terminal marker over port state FAILED.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from .backend_budget import BackendCapacityError, BackendId, PhysicalBackendBudget
from .drift import CaptureOutcomeKind, FailureCounter
from .ports import JobQueuePort, PortError, Scope

__all__ = [
    "IllegalTransition", "LeaseHandle", "LeaseLost", "RunResult", "RunStatus", "SchedulerConfig",
    "SourceScheduler", "SourceState", "SourceStateMachine", "backoff_delay",
]

_MAX_EXPONENT: Final = 62
_SUCCESS_KINDS: Final = frozenset({
    CaptureOutcomeKind.OK_COMPLETE, CaptureOutcomeKind.OK_PARTIAL,
    CaptureOutcomeKind.SCHEMA_CHANGED,
})
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


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    not_before: datetime | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    lease_seconds: int = 60
    renew_margin_seconds: float = 20.0
    poison_after: int = 5
    backoff_base: float = 1.0
    backoff_cap: float = 300.0
    quarantine_after_pauses: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("LEASE_SECONDS_INVALID")
        if not 0 <= self.renew_margin_seconds < self.lease_seconds:
            raise ValueError("RENEW_MARGIN_INVALID")
        if self.poison_after < 1 or self.quarantine_after_pauses < 1:
            raise ValueError("SCHEDULER_LIMIT_INVALID")
        if not self.backoff_base > 0 or not self.backoff_cap > 0:
            raise ValueError("BACKOFF_CONFIG_INVALID")


class LeaseHandle:
    """What the work callable sees: renew-before-expiry and the fence it must keep using."""

    def __init__(self, scheduler: SourceScheduler, job_id: UUID, fence: int,
                 lease_until: datetime) -> None:
        self._s = scheduler
        self.job_id = job_id
        self.fence = fence
        self.lease_until = lease_until

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
            if exc.code == "STALE_JOB_FENCE":
                raise LeaseLost(exc.code) from exc
            raise


Work = Callable[[LeaseHandle], Awaitable[CaptureOutcomeKind]]


class SourceScheduler:
    """Runs jobs of ONE source (scope) one at a time through the job-queue port."""

    def __init__(self, port: JobQueuePort, *, actor: str, scope: Scope, worker: str,
                 backend_id: BackendId, budget: PhysicalBackendBudget,
                 clock: Callable[[], datetime], jitter_source: Callable[[], float],
                 config: SchedulerConfig | None = None,
                 machine: SourceStateMachine | None = None,
                 counter: FailureCounter | None = None) -> None:
        self._port, self._actor, self._scope, self._worker = port, actor, scope, worker
        self._backend, self._budget = backend_id, budget
        self._clock, self._jitter = clock, jitter_source
        self.config = config or SchedulerConfig()
        self.machine = machine or SourceStateMachine()
        self.counter = counter or FailureCounter()
        self._not_before: dict[UUID, datetime] = {}
        self._deferrals: dict[UUID, int] = {}
        self._poisoned: set[UUID] = set()

    def is_poisoned(self, job_id: UUID) -> bool:
        return job_id in self._poisoned

    def not_before(self, job_id: UUID) -> datetime | None:
        return self._not_before.get(job_id)

    async def reap(self) -> int:
        """Requeue (or fail) jobs whose lease expired, through the port."""
        return await self._port.reap_expired_jobs(self._actor, self._scope)

    def resume(self, by: str) -> None:
        """Explicit operator resume; also clears the consecutive-failure counter."""
        self.machine.resume(by)
        self.counter = FailureCounter(0, self.counter.threshold)

    def _delay(self, n: int) -> timedelta:
        return timedelta(seconds=backoff_delay(
            n, self.config.backoff_base, self.config.backoff_cap, self._jitter))

    async def run_job(self, job_id: UUID, work: Work) -> RunResult:
        if job_id in self._poisoned:
            return RunResult(RunStatus.POISONED, detail="already poisoned")
        if self.machine.state is not SourceState.ACTIVE:
            return RunResult(RunStatus.SOURCE_NOT_ACTIVE, detail=self.machine.state.value)
        gate = self._not_before.get(job_id)
        if gate is not None and self._clock() < gate:
            return RunResult(RunStatus.NOT_YET, gate)
        with ExitStack() as stack:
            try:
                stack.enter_context(self._budget.reserve(trusted_backend_id=self._backend))
            except BackendCapacityError as exc:
                if str(exc) != "BACKEND_CAPACITY_EXCEEDED":
                    raise
                return self._defer(job_id)
            # Reap separately: a JOB_UNAVAILABLE acquire aborts its own transaction, which would
            # roll back a reap done inside it and leave an abandoned lease RUNNING forever.
            await self.reap()
            try:
                fence = await self._port.acquire_job(
                    self._actor, self._scope, job_id, self._worker, self.config.lease_seconds)
            except PortError as exc:
                if exc.code == "JOB_UNAVAILABLE":
                    return RunResult(RunStatus.LEASE_DENIED, detail=exc.code)
                raise
            self._deferrals.pop(job_id, None)
            view = await self._port.get_job(self._actor, self._scope, job_id)
            if view is None or view.lease_until is None:
                return RunResult(RunStatus.LEASE_LOST, detail="JOB_VANISHED")
            handle = LeaseHandle(self, job_id, fence, view.lease_until)
            try:
                outcome = await work(handle)
            except LeaseLost as exc:
                return RunResult(RunStatus.LEASE_LOST, detail=str(exc))
            except Exception as exc:  # noqa: BLE001 - work failure is data for the failure policy
                return await self._failed(job_id, handle, CaptureOutcomeKind.OUTAGE,
                                          f"{type(exc).__name__}: {exc}")
            if outcome in _SUCCESS_KINDS:
                return await self._succeeded(job_id, handle, outcome)
            return await self._failed(job_id, handle, outcome, outcome.value)

    def _defer(self, job_id: UUID) -> RunResult:
        n = self._deferrals.get(job_id, 0)
        self._deferrals[job_id] = n + 1
        at = self._clock() + self._delay(n)
        self._not_before[job_id] = at
        return RunResult(RunStatus.DEFERRED_BUDGET, at, "BACKEND_CAPACITY_EXCEEDED")

    async def _finish(self, job_id: UUID, handle: LeaseHandle, state: str,
                      error: str | None = None) -> bool:
        """True when finished; False when the fence was stale (lease lost, nothing written)."""
        try:
            await self._port.finish_job(self._actor, self._scope, job_id, self._worker,
                                        handle.fence, state, error)
        except PortError as exc:
            if exc.code == "STALE_JOB_FENCE":
                return False
            raise
        return True

    async def _succeeded(self, job_id: UUID, handle: LeaseHandle,
                         outcome: CaptureOutcomeKind) -> RunResult:
        if not await self._finish(job_id, handle, "SUCCEEDED"):
            return RunResult(RunStatus.LEASE_LOST, detail="STALE_JOB_FENCE")
        self.counter = self.counter.advance(outcome)
        self.machine.pause_count = 0  # a success ends the run of pauses without progress
        self._not_before.pop(job_id, None)
        return RunResult(RunStatus.SUCCEEDED)

    async def _failed(self, job_id: UUID, handle: LeaseHandle, kind: CaptureOutcomeKind,
                      error: str) -> RunResult:
        view = await self._port.get_job(self._actor, self._scope, job_id)
        if view is None or view.fence != handle.fence or view.state != "RUNNING":
            return RunResult(RunStatus.LEASE_LOST, detail="STALE_JOB_FENCE")
        self.counter = self.counter.advance(kind)
        if view.attempt >= self.config.poison_after:
            if not await self._finish(job_id, handle, "FAILED", f"{POISON_PREFIX} {error}"):
                return RunResult(RunStatus.LEASE_LOST, detail="STALE_JOB_FENCE")
            self._poisoned.add(job_id)
            self._not_before.pop(job_id, None)
            self._escalate("poisoned job", force=True)
            return RunResult(RunStatus.POISONED, detail=error)
        at = self._clock() + self._delay(max(view.attempt - 1, 0))
        self._not_before[job_id] = at
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
