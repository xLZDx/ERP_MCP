"""Dev/test-only composition of accepted capture jobs with the Phase 2 capture loop.

This module deliberately has no public MCP registration and refuses production construction.
Job tickets retain tenant/company identity; connector requests retain tenant/source/epoch identity.
The two boundaries are checked together before a CaptureLoop task is admitted.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .capture_loop import CaptureLoop, CaptureResult
from .connector_sdk import CaptureRequest
from .jobs_api import JobKind, JobTicket
from .ports import Scope
from .scheduler import RunStatus
from .workbench_types import ViewerScope

__all__ = ["CaptureJobResult", "CaptureRuntime", "KillSwitchResult", "RuntimeState"]

_TERMINAL_QUEUE_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
_TERMINAL_RUN_STATUSES = frozenset({
    RunStatus.SUCCEEDED, RunStatus.POISONED, RunStatus.EXHAUSTED,
    RunStatus.ALREADY_SUCCEEDED, RunStatus.CANCELLED, RunStatus.JOB_MISSING,
})
_MAX_CONCURRENT_QUEUE_CANCELLATIONS = 8
_QUEUE_CLEANUP_TIMEOUT_SECONDS = 5.0


class RuntimeState(StrEnum):
    ACCEPTING = "ACCEPTING"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class CaptureJobResult:
    job_id: str
    environment: str
    status: str
    capture: CaptureResult | None
    production_approved: bool = False


@dataclass(frozen=True, slots=True)
class KillSwitchResult:
    state: RuntimeState
    admission_closed: bool
    terminated_job_ids: tuple[str, ...]
    queue_pending_job_ids: tuple[str, ...]
    connector_pending_job_ids: tuple[str, ...]
    production_approved: bool = False
    runtime_pending_job_ids: tuple[str, ...] = ()


class CaptureRuntime:
    """One exact company/source scope in a non-production process.

    A switch is one-way for this instance. A stopped instance cannot be reopened; callers must
    rebuild it through the normal scope/epoch validation path. The synchronous connector cannot be
    force-killed, so ``stop`` reports still-running connector jobs and keeps admission closed until
    a later retry observes that they have drained.
    """

    def __init__(self, *, environment: str, scope: ViewerScope, source_id: str,
                 capture_loop: CaptureLoop) -> None:
        if environment not in {"development", "test"}:
            raise ValueError("CAPTURE_RUNTIME_ENVIRONMENT_REFUSED")
        if type(scope) is not ViewerScope:
            raise ValueError("CAPTURE_RUNTIME_SCOPE_INVALID")
        if type(source_id) is not str or not source_id.strip():
            raise ValueError("CAPTURE_RUNTIME_SOURCE_INVALID")
        if type(capture_loop) is not CaptureLoop:
            raise ValueError("CAPTURE_RUNTIME_LOOP_INVALID")
        if (type(capture_loop.scope) is not Scope
                or capture_loop.scope.tenant_id != scope.tenant_id
                or capture_loop.scope.source_id != source_id):
            raise ValueError("CAPTURE_LOOP_SCOPE_MISMATCH")
        if capture_loop.viewer_scope != scope:
            raise ValueError("CAPTURE_LOOP_VIEWER_SCOPE_MISMATCH")
        self.environment = environment
        self.scope = scope
        self.source_id = source_id
        self._loop = capture_loop
        self._state = RuntimeState.ACCEPTING
        self._lock = asyncio.Lock()
        self._jobs: dict[UUID, asyncio.Task[CaptureResult]] = {}
        # Queue rows outlive capture tasks when admission is deferred or validation returns early.
        self._owned_jobs: set[UUID] = set()
        self._draining_jobs: set[UUID] = set()
        self._queue_cleanup_tasks: dict[UUID, asyncio.Task[str | None]] = {}
        self._queue_cleanup_slots = asyncio.Semaphore(_MAX_CONCURRENT_QUEUE_CANCELLATIONS)

    @property
    def state(self) -> RuntimeState:
        return self._state

    async def capture(self, ticket: JobTicket, connection_id: str, request: CaptureRequest,
                      *, snapshot: bool = False) -> CaptureJobResult:
        """Run one API-approved CAPTURE ticket after exact ticket/request scope comparison."""
        if type(ticket) is not JobTicket or ticket.kind is not JobKind.CAPTURE:
            raise ValueError("CAPTURE_TICKET_REQUIRED")
        if (ticket.tenant_id != self.scope.tenant_id
                or ticket.company_id != self.scope.company_id):
            raise ValueError("CAPTURE_TICKET_SCOPE_MISMATCH")
        if (type(request) is not CaptureRequest or request.tenant_id != self.scope.tenant_id
                or request.source_id != self.source_id
                or request.scope_epoch != self.scope.scope_epoch):
            raise ValueError("CAPTURE_REQUEST_SCOPE_MISMATCH")
        if type(connection_id) is not str or not connection_id.strip():
            raise ValueError("CAPTURE_CONNECTION_INVALID")
        if type(snapshot) is not bool:
            raise ValueError("CAPTURE_SNAPSHOT_FLAG_INVALID")
        try:
            job_id = UUID(ticket.job_id)
        except (ValueError, AttributeError):
            raise ValueError("CAPTURE_JOB_ID_INVALID") from None
        if str(job_id) != ticket.job_id:
            raise ValueError("CAPTURE_JOB_ID_INVALID")

        async with self._lock:
            if self._state is not RuntimeState.ACCEPTING:
                return CaptureJobResult(ticket.job_id, self.environment, "NOT_ADMITTED", None)
            if job_id in self._owned_jobs:
                raise ValueError("CAPTURE_JOB_ALREADY_OWNED")
            # Record ownership before the await: stop() can then see this ID even if enqueue is
            # still resolving when the switch is thrown.
            self._owned_jobs.add(job_id)
            try:
                enqueued_id = await self._loop.enqueue_job(
                    job_id, ticket.request_digest,
                    company_id=ticket.company_id,
                    connection_id=connection_id,
                )
            except asyncio.CancelledError:
                # The enqueue may have committed before cancellation reached the port. Keep the
                # ID until stop() can confirm and cancel or observe its queue state.
                raise
            except Exception:
                try:
                    state = await asyncio.wait_for(
                        self._loop.job_state(job_id), _QUEUE_CLEANUP_TIMEOUT_SECONDS)
                except Exception:
                    state = "UNKNOWN"
                if state is None or state in _TERMINAL_QUEUE_STATES:
                    self._owned_jobs.discard(job_id)
                raise
            if enqueued_id != job_id:
                raise RuntimeError("CAPTURE_QUEUE_ID_MISMATCH")
            if self._state is not RuntimeState.ACCEPTING:
                try:
                    state = await self._cancel_or_read_state(job_id)
                except Exception:
                    state = None
                if state in _TERMINAL_QUEUE_STATES:
                    self._owned_jobs.discard(job_id)
                return CaptureJobResult(ticket.job_id, self.environment, "NOT_ADMITTED", None)
            task = asyncio.create_task(
                self._loop.capture_step(job_id, connection_id, request, snapshot=snapshot),
                name=f"phase2-capture-{job_id}",
            )
            self._jobs[job_id] = task

        try:
            result = await task
            return CaptureJobResult(ticket.job_id, self.environment, result.status.value, result)
        except asyncio.CancelledError:
            return CaptureJobResult(ticket.job_id, self.environment, "CANCELLED", None)
        finally:
            async with self._lock:
                if self._jobs.get(job_id) is task:
                    self._jobs.pop(job_id, None)
                if task.done() and not task.cancelled():
                    try:
                        completed = task.result()
                    except Exception:
                        completed = None
                    if (completed is not None and completed.run is not None
                            and completed.run.status in _TERMINAL_RUN_STATUSES
                            and job_id not in self._loop.inflight_job_ids):
                        self._owned_jobs.discard(job_id)
                        self._draining_jobs.discard(job_id)

    async def _cancel_or_read_state(self, job_id: UUID) -> str | None:
        async with self._queue_cleanup_slots:
            async with asyncio.timeout(_QUEUE_CLEANUP_TIMEOUT_SECONDS):
                state = await self._loop.cancel_job(job_id)
                return await self._loop.job_state(job_id) if state is None else state

    async def stop(self, scope: ViewerScope, *, drain_timeout_seconds: float = 5.0
                   ) -> KillSwitchResult:
        """Close admission, cancel this scope's owned tasks, and report connector threads not drained."""
        if type(scope) is not ViewerScope or scope != self.scope:
            raise ValueError("KILL_SWITCH_SCOPE_MISMATCH")
        if (isinstance(drain_timeout_seconds, bool)
                or not isinstance(drain_timeout_seconds, (int, float))
                or not 0 < drain_timeout_seconds <= 300):
            raise ValueError("KILL_SWITCH_DRAIN_TIMEOUT_INVALID")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(drain_timeout_seconds)
        # This state transition is synchronous and precedes every await, so admission closes even
        # while an enqueue or another task is holding _lock.
        self._state = RuntimeState.STOPPED
        owned = dict(self._jobs)
        draining = (set(self._draining_jobs) | self._owned_jobs | set(owned)
                    | set(self._queue_cleanup_tasks)
                    | set(self._loop.inflight_job_ids))
        for task in owned.values():
            task.cancel()
        runtime_pending: set[UUID] = set()
        if owned:
            remaining = max(0.0, deadline - loop.time())
            _, pending_tasks = await asyncio.wait(set(owned.values()), timeout=remaining)
            runtime_pending = {
                job_id for job_id, task in owned.items() if task in pending_tasks
            }
        queue_pending: set[UUID] = set()
        terminal: set[UUID] = set()
        cleanup_tasks: dict[UUID, asyncio.Task[str | None]] = {}
        active_cleanup_count = sum(not task.done() for task in self._queue_cleanup_tasks.values())
        available_cleanup_slots = max(0, _MAX_CONCURRENT_QUEUE_CANCELLATIONS - active_cleanup_count)
        for job_id in draining:
            task = self._queue_cleanup_tasks.get(job_id)
            if task is not None and task.done():
                try:
                    previous_state = task.result()
                except Exception:
                    previous_state = None
                if previous_state in _TERMINAL_QUEUE_STATES:
                    self._queue_cleanup_tasks.pop(job_id, None)
                    terminal.add(job_id)
                    continue
                self._queue_cleanup_tasks.pop(job_id, None)
                task = None
            if task is None and available_cleanup_slots and loop.time() < deadline:
                task = asyncio.create_task(self._cancel_or_read_state(job_id))
                self._queue_cleanup_tasks[job_id] = task
                available_cleanup_slots -= 1
            if task is not None:
                cleanup_tasks[job_id] = task
            else:
                queue_pending.add(job_id)
        remaining = max(0.0, deadline - loop.time())
        if cleanup_tasks and remaining:
            await asyncio.wait(set(cleanup_tasks.values()), timeout=remaining)
        for job_id, task in cleanup_tasks.items():
            if not task.done():
                queue_pending.add(job_id)
                continue
            if self._queue_cleanup_tasks.get(job_id) is task:
                self._queue_cleanup_tasks.pop(job_id, None)
            try:
                state = task.result()
            except Exception:
                state = None
            if state in _TERMINAL_QUEUE_STATES:
                terminal.add(job_id)
            else:
                queue_pending.add(job_id)
        remaining = max(0.0, deadline - loop.time())
        if remaining:
            connector_pending = set(await self._loop.wait_for_jobs(draining, remaining))
        else:
            connector_pending = set(self._loop.inflight_job_ids) & draining
        runtime_pending.update(
            job_id for job_id, task in self._jobs.items() if not task.done()
        )
        unresolved = queue_pending | connector_pending | runtime_pending
        self._owned_jobs.intersection_update(unresolved)
        self._draining_jobs = unresolved
        terminated = tuple(sorted(str(job_id) for job_id in terminal))
        return KillSwitchResult(
            state=self._state,
            admission_closed=True,
            terminated_job_ids=terminated,
            queue_pending_job_ids=tuple(sorted(str(job_id) for job_id in queue_pending)),
            connector_pending_job_ids=tuple(sorted(str(job_id) for job_id in connector_pending)),
            runtime_pending_job_ids=tuple(sorted(str(job_id) for job_id in runtime_pending)),
        )

    async def close(self, *, drain_timeout_seconds: float = 5.0) -> None:
        stopped = await self.stop(self.scope, drain_timeout_seconds=drain_timeout_seconds)
        if (stopped.queue_pending_job_ids or stopped.connector_pending_job_ids
                or stopped.runtime_pending_job_ids):
            raise RuntimeError("CAPTURE_RUNTIME_DRAIN_INCOMPLETE")
        await self._loop.close(drain_timeout_seconds)
