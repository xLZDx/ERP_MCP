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
from .workbench_types import ViewerScope

__all__ = ["CaptureJobResult", "CaptureRuntime", "KillSwitchResult", "RuntimeState"]


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
        self._draining_jobs: set[UUID] = set()

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
            if job_id in self._jobs:
                raise ValueError("CAPTURE_JOB_ALREADY_RUNNING")
            enqueued_id = await self._loop.enqueue_job(
                job_id, ticket.request_digest,
                company_id=ticket.company_id,
                connection_id=connection_id,
            )
            if enqueued_id != job_id:
                raise RuntimeError("CAPTURE_QUEUE_ID_MISMATCH")
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

    async def stop(self, scope: ViewerScope, *, drain_timeout_seconds: float = 5.0
                   ) -> KillSwitchResult:
        """Close admission, cancel this scope's owned tasks, and report connector threads not drained."""
        if type(scope) is not ViewerScope or scope != self.scope:
            raise ValueError("KILL_SWITCH_SCOPE_MISMATCH")
        if (isinstance(drain_timeout_seconds, bool)
                or not isinstance(drain_timeout_seconds, (int, float))
                or not 0 < drain_timeout_seconds <= 300):
            raise ValueError("KILL_SWITCH_DRAIN_TIMEOUT_INVALID")
        async with self._lock:
            self._state = RuntimeState.STOPPED
            owned = dict(self._jobs)
            draining = set(self._draining_jobs) | set(owned) | set(self._loop.inflight_job_ids)
            for task in owned.values():
                task.cancel()
        if owned:
            await asyncio.gather(*owned.values(), return_exceptions=True)
        queue_pending: set[UUID] = set()
        terminal: set[UUID] = set()
        for job_id in draining:
            state = await self._loop.cancel_job(job_id)
            if state is None:
                state = await self._loop.job_state(job_id)
            if state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                terminal.add(job_id)
            else:
                queue_pending.add(job_id)
        connector_pending = await self._loop.wait_for_jobs(
            draining, float(drain_timeout_seconds))
        async with self._lock:
            self._draining_jobs = queue_pending | set(connector_pending)
        terminated = tuple(sorted(str(job_id) for job_id in terminal))
        return KillSwitchResult(
            state=self._state,
            admission_closed=True,
            terminated_job_ids=terminated,
            queue_pending_job_ids=tuple(sorted(str(job_id) for job_id in queue_pending)),
            connector_pending_job_ids=tuple(sorted(str(job_id) for job_id in connector_pending)),
        )

    async def close(self, *, drain_timeout_seconds: float = 5.0) -> None:
        stopped = await self.stop(self.scope, drain_timeout_seconds=drain_timeout_seconds)
        if stopped.queue_pending_job_ids or stopped.connector_pending_job_ids:
            raise RuntimeError("CAPTURE_RUNTIME_DRAIN_INCOMPLETE")
        await self._loop.close(drain_timeout_seconds)
