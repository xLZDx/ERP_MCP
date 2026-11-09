"""R2-US-042 TC124–125 dev/test capture runtime contract."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from business_ai_gateway.phase2.backend_budget import BackendId, PhysicalBackendBudget
from business_ai_gateway.phase2.capture_loop import CaptureLoop
from business_ai_gateway.phase2.capture_runtime import CaptureRuntime
from business_ai_gateway.phase2.connector_sdk import (
    CaptureMode,
    CaptureRequest,
    CaptureResponse,
    Completeness,
    Provenance,
)
from business_ai_gateway.phase2.fakes import WORKER, InMemoryLiving
from business_ai_gateway.phase2.jobs_api import JobKind, JobTicket
from business_ai_gateway.phase2.ports import Scope
from business_ai_gateway.phase2.resnapshot import ResnapshotReason, ResnapshotTracker
from business_ai_gateway.phase2.scheduler import SourceScheduler
from business_ai_gateway.phase2.workbench_types import ViewerScope
from business_ai_gateway.runtime import Runtime

TENANT = "A"
COMPANY = "company-a"
SOURCE = "s1"
CONNECTION = "connection-1"
JOB_ID = str(UUID(int=91))
DIGEST = "a" * 64
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Connector:
    connector_id = "synthetic-test"
    connector_version = "1"

    def __init__(self) -> None:
        self.calls = 0

    def health(self, *, source_id: str, tenant_id: str):
        raise NotImplementedError

    def capture_page(self, request: CaptureRequest) -> CaptureResponse:
        self.calls += 1
        return CaptureResponse(
            request.source_id,
            request.tenant_id,
            request.scope_epoch,
            CaptureMode.SNAPSHOT_ONLY,
            Completeness.COMPLETE,
            Provenance("synthetic-test", "1", NOW, DIGEST, request.page_cursor),
        )


async def build_parts(*, loop_viewer_scope: ViewerScope | None = None):
    source_scope = Scope(TENANT, SOURCE)
    viewer_scope = ViewerScope(TENANT, COMPANY, 0)
    living = InMemoryLiving()
    scheduler = SourceScheduler(
        living,
        actor=WORKER,
        scope=source_scope,
        worker="s10-test-worker",
        backend_id=BackendId.normalize("synthetic-test-backend"),
        budget=PhysicalBackendBudget(per_backend_limit=1, total_limit=1),
        clock=living.clock.now,
        jitter_source=lambda: 0.0,
    )
    scheduler.machine.resume_validation_required = False
    connector = Connector()
    capture_loop = CaptureLoop(
        scheduler, ResnapshotTracker(), connector, living, source_scope,
        viewer_scope=loop_viewer_scope or viewer_scope,
    )
    capture_loop._accepted[CONNECTION] = DIGEST
    return viewer_scope, living, capture_loop, connector


async def build_runtime(environment: str = "test", *,
                        loop_viewer_scope: ViewerScope | None = None):
    viewer_scope, living, capture_loop, connector = await build_parts(
        loop_viewer_scope=loop_viewer_scope,
    )
    runtime = CaptureRuntime(
        environment=environment,
        scope=viewer_scope,
        source_id=SOURCE,
        capture_loop=capture_loop,
    )
    return runtime, capture_loop, connector


def ticket(*, tenant: str = TENANT, company: str = COMPANY) -> JobTicket:
    return JobTicket(JOB_ID, tenant, company, JobKind.CAPTURE, DIGEST)


def request(*, tenant: str = TENANT, source: str = SOURCE, epoch: int = 0) -> CaptureRequest:
    return CaptureRequest(source, tenant, epoch, CaptureMode.SNAPSHOT_ONLY)


@pytest.mark.asyncio
async def test_tc124_exact_scope_capture_runs_and_labels_environment():
    runtime, capture_loop, connector = await build_runtime("development")
    try:
        result = await runtime.capture(ticket(), CONNECTION, request())
        assert result.status == "CAPTURED"
        assert result.environment == "development"
        assert result.production_approved is False
        assert result.capture is not None
        assert connector.calls == 1
        assert await capture_loop.job_state(UUID(JOB_ID)) == "SUCCEEDED"
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_ticket", "capture_request", "expected"),
    [
        (ticket(tenant="foreign-tenant"), request(), "CAPTURE_TICKET_SCOPE_MISMATCH"),
        (ticket(company="foreign-company"), request(), "CAPTURE_TICKET_SCOPE_MISMATCH"),
        (ticket(), request(tenant="foreign-tenant"), "CAPTURE_REQUEST_SCOPE_MISMATCH"),
        (ticket(), request(source="other-source"), "CAPTURE_REQUEST_SCOPE_MISMATCH"),
        (ticket(), request(epoch=1), "CAPTURE_REQUEST_SCOPE_MISMATCH"),
    ],
)
async def test_tc124_scope_mismatch_is_refused_before_enqueue_or_connector(
    job_ticket: JobTicket, capture_request: CaptureRequest, expected: str,
):
    runtime, capture_loop, connector = await build_runtime()
    try:
        with pytest.raises(ValueError, match=expected):
            await runtime.capture(job_ticket, CONNECTION, capture_request)
        assert connector.calls == 0
        assert await capture_loop.job_state(UUID(JOB_ID)) is None
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "loop_scope",
    [ViewerScope(TENANT, "other-company", 0), ViewerScope(TENANT, COMPANY, 1)],
)
async def test_tc124_capture_loop_binding_mismatch_is_refused_at_composition(
    loop_scope: ViewerScope,
):
    viewer_scope, _living, capture_loop, connector = await build_parts(
        loop_viewer_scope=loop_scope,
    )
    with pytest.raises(ValueError, match="CAPTURE_LOOP_VIEWER_SCOPE_MISMATCH"):
        CaptureRuntime(
            environment="test",
            scope=viewer_scope,
            source_id=SOURCE,
            capture_loop=capture_loop,
        )
    assert connector.calls == 0
    assert await capture_loop.job_state(UUID(JOB_ID)) is None
    await capture_loop.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "test"])
async def test_tc125_dev_test_pass_is_never_production_approval(environment: str):
    runtime, _capture_loop, connector = await build_runtime(environment)
    try:
        result = await runtime.capture(ticket(), CONNECTION, request())
        assert result.environment == environment
        assert result.production_approved is False
        assert connector.calls == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_tc125_runtime_refuses_production_binding_before_capture():
    runtime, capture_loop, connector = await build_runtime()
    await runtime.close()

    serving_runtime = Runtime.__new__(Runtime)
    serving_runtime.settings = SimpleNamespace(environment="production")
    serving_runtime._phase2_capture_runtime = None
    with pytest.raises(ValueError, match="CAPTURE_RUNTIME_ENVIRONMENT_REFUSED"):
        serving_runtime.bind_dev_test_capture(
            scope=ViewerScope(TENANT, COMPANY, 0),
            source_id=SOURCE,
            capture_loop=capture_loop,
        )
    assert connector.calls == 0


@pytest.mark.asyncio
async def test_tc126_stop_cancels_queue_row_after_capture_returns_without_running_it():
    runtime, capture_loop, connector = await build_runtime()
    capture_loop._tracker.require(CONNECTION, ResnapshotReason.OPERATOR, 0)
    try:
        result = await runtime.capture(ticket(), CONNECTION, request())

        assert result.status == "RESNAPSHOT_REQUIRED"
        assert connector.calls == 0
        assert await capture_loop.job_state(UUID(JOB_ID)) == "PENDING"

        stopped = await runtime.stop(runtime.scope, drain_timeout_seconds=0.5)

        assert stopped.terminated_job_ids == (JOB_ID,)
        assert stopped.queue_pending_job_ids == ()
        assert stopped.connector_pending_job_ids == ()
        assert stopped.runtime_pending_job_ids == ()
        assert await capture_loop.job_state(UUID(JOB_ID)) == "CANCELLED"
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_tc126_confirmed_missing_enqueue_failure_allows_same_job_retry():
    runtime, capture_loop, connector = await build_runtime()
    original_enqueue = capture_loop.enqueue_job
    calls = 0

    async def fail_before_enqueue(job_id, request_digest, *, company_id, connection_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("enqueue did not create a row")
        return await original_enqueue(
            job_id, request_digest, company_id=company_id, connection_id=connection_id)

    capture_loop.enqueue_job = fail_before_enqueue
    try:
        with pytest.raises(TimeoutError, match="enqueue did not create a row"):
            await runtime.capture(ticket(), CONNECTION, request())
        assert await capture_loop.job_state(UUID(JOB_ID)) is None
        assert connector.calls == 0

        result = await runtime.capture(ticket(), CONNECTION, request())

        assert result.status == "CAPTURED"
        assert connector.calls == 1
        assert await capture_loop.job_state(UUID(JOB_ID)) == "SUCCEEDED"
    finally:
        capture_loop.enqueue_job = original_enqueue
        await runtime.close()


@pytest.mark.asyncio
async def test_tc126_ambiguous_enqueue_failure_keeps_job_for_stop_reconciliation():
    runtime, capture_loop, connector = await build_runtime()
    original_enqueue = capture_loop.enqueue_job

    async def commit_then_lose_response(job_id, request_digest, *, company_id, connection_id):
        await original_enqueue(
            job_id, request_digest, company_id=company_id, connection_id=connection_id)
        raise TimeoutError("enqueue response was lost after commit")

    capture_loop.enqueue_job = commit_then_lose_response
    try:
        with pytest.raises(TimeoutError, match="response was lost after commit"):
            await runtime.capture(ticket(), CONNECTION, request())
        assert await capture_loop.job_state(UUID(JOB_ID)) == "PENDING"
        assert connector.calls == 0

        with pytest.raises(ValueError, match="CAPTURE_JOB_ALREADY_OWNED"):
            await runtime.capture(ticket(), CONNECTION, request())

        stopped = await runtime.stop(runtime.scope, drain_timeout_seconds=0.5)

        assert stopped.terminated_job_ids == (JOB_ID,)
        assert stopped.queue_pending_job_ids == ()
        assert await capture_loop.job_state(UUID(JOB_ID)) == "CANCELLED"
        assert connector.calls == 0
    finally:
        capture_loop.enqueue_job = original_enqueue
        await runtime.close()


@pytest.mark.asyncio
async def test_tc126_stop_bounds_wait_for_capture_task_that_is_stuck_acquiring():
    runtime, capture_loop, connector = await build_runtime()
    scheduler = capture_loop._sched
    original_acquire = scheduler._port.acquire_job
    acquire_started = asyncio.Event()
    release_acquire = asyncio.Event()

    async def blocked_acquire(*args, **kwargs):
        acquire_started.set()
        await release_acquire.wait()
        return await original_acquire(*args, **kwargs)

    scheduler._port.acquire_job = blocked_acquire
    capture = asyncio.create_task(runtime.capture(ticket(), CONNECTION, request()))
    try:
        await asyncio.wait_for(acquire_started.wait(), timeout=1)
        started = asyncio.get_running_loop().time()
        stopped = await runtime.stop(runtime.scope, drain_timeout_seconds=0.05)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 1
        assert stopped.admission_closed
        assert stopped.runtime_pending_job_ids == (JOB_ID,)
        assert stopped.queue_pending_job_ids == (JOB_ID,)
        assert await capture_loop.job_state(UUID(JOB_ID)) == "PENDING"
        assert connector.calls == 0
        release_acquire.set()
        await asyncio.wait_for(capture, timeout=2)
        retried = await runtime.stop(runtime.scope, drain_timeout_seconds=1)
        assert retried.queue_pending_job_ids == ()
        assert retried.connector_pending_job_ids == ()
        assert await capture_loop.job_state(UUID(JOB_ID)) == "CANCELLED"
    finally:
        release_acquire.set()
        await asyncio.wait_for(asyncio.gather(capture, return_exceptions=True), timeout=2)
        scheduler._port.acquire_job = original_acquire
        await runtime.close(drain_timeout_seconds=1)


@pytest.mark.asyncio
async def test_tc126_stop_bounds_queue_cancel_and_keeps_job_for_retry():
    runtime, capture_loop, connector = await build_runtime()
    capture_loop._tracker.require(CONNECTION, ResnapshotReason.OPERATOR, 0)
    assert (await runtime.capture(ticket(), CONNECTION, request())).status == "RESNAPSHOT_REQUIRED"
    original_cancel = capture_loop.cancel_job
    cancel_started = asyncio.Event()
    release_cancel = asyncio.Event()

    async def blocked_cancel(job_id):
        cancel_started.set()
        await release_cancel.wait()
        return await original_cancel(job_id)

    capture_loop.cancel_job = blocked_cancel
    try:
        started = asyncio.get_running_loop().time()
        stopped = await runtime.stop(runtime.scope, drain_timeout_seconds=0.05)
        elapsed = asyncio.get_running_loop().time() - started

        assert cancel_started.is_set()
        assert elapsed < 1
        assert stopped.queue_pending_job_ids == (JOB_ID,)
        assert connector.calls == 0
        assert await capture_loop.job_state(UUID(JOB_ID)) == "PENDING"

        release_cancel.set()
        retried = await runtime.stop(runtime.scope, drain_timeout_seconds=1)

        assert retried.queue_pending_job_ids == ()
        assert retried.terminated_job_ids == (JOB_ID,)
        assert await capture_loop.job_state(UUID(JOB_ID)) == "CANCELLED"
    finally:
        release_cancel.set()
        capture_loop.cancel_job = original_cancel
        await runtime.close(drain_timeout_seconds=1)
