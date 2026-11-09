"""Synthetic S10 end-to-end coverage for the scoped capture runtime kill switch."""
import asyncio
import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from business_ai_gateway.phase2.backend_budget import BackendId, PhysicalBackendBudget
from business_ai_gateway.phase2.capture_loop import CaptureLoop
from business_ai_gateway.phase2.connector_sdk import (
    CaptureMode,
    CaptureRequest,
    CaptureResponse,
    Completeness,
    Provenance,
)
from business_ai_gateway.phase2.drift import CaptureOutcomeKind
from business_ai_gateway.phase2.fakes import InMemoryLiving, WORKER
from business_ai_gateway.phase2.jobs_api import JobKind, JobTicket
from business_ai_gateway.phase2.ports import Scope
from business_ai_gateway.phase2.resnapshot import ResnapshotTracker
from business_ai_gateway.phase2.scheduler import RunStatus, SourceScheduler
from business_ai_gateway.phase2.workbench_types import ViewerScope
from business_ai_gateway.runtime import Runtime
from business_ai_gateway.settings import Settings


NOW = datetime(2026, 11, 8, tzinfo=UTC)
TENANT = "tenant-s10"
SOURCE_ONE = "source-one"
SOURCE_TWO = "source-two"
COMPANY_ONE = "company-one"
COMPANY_TWO = "company-two"
REQUEST_DIGEST = "a" * 64


class BlockingConnector:
    connector_id = "synthetic-blocking"
    connector_version = "1"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def health(self, *, source_id, tenant_id):
        raise NotImplementedError

    def capture_page(self, request):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("synthetic connector release deadline expired")
        return CaptureResponse(
            request.source_id,
            request.tenant_id,
            request.scope_epoch,
            CaptureMode.SNAPSHOT_ONLY,
            Completeness.COMPLETE,
            Provenance(self.connector_id, self.connector_version, NOW, REQUEST_DIGEST),
        )


def _runtime(source_id: str, company_id: str, connector: BlockingConnector,
             *, connector_timeout: float = 30.0, max_threads: int = 4,
             backend_limit: int = 1):
    source_scope = Scope(TENANT, source_id)
    living = InMemoryLiving()
    living.seed_basic(source_scope)
    scheduler = SourceScheduler(
        living,
        actor=WORKER,
        scope=source_scope,
        worker=f"worker-{source_id}",
        backend_id=BackendId.normalize(f"backend-{source_id}"),
        budget=PhysicalBackendBudget(per_backend_limit=backend_limit, total_limit=2),
        clock=living.clock.now,
        jitter_source=lambda: 0.0,
    )
    # The test fixture models a source whose startup revalidation has completed.
    scheduler.machine.resume_validation_required = False
    viewer_scope = ViewerScope(TENANT, company_id, 0)
    loop = CaptureLoop(
        scheduler,
        ResnapshotTracker(),
        connector,
        living,
        source_scope,
        connector_timeout=connector_timeout,
        max_threads=max_threads,
        viewer_scope=viewer_scope,
    )
    runtime = Runtime(Settings(_env_file=None, environment="test"))
    service = runtime.bind_dev_test_capture(
        scope=viewer_scope,
        source_id=source_id,
        capture_loop=loop,
    )
    return runtime, service, living, source_scope


def _ticket(job_id: UUID, company_id: str) -> JobTicket:
    return JobTicket(
        job_id=str(job_id),
        tenant_id=TENANT,
        company_id=company_id,
        kind=JobKind.CAPTURE,
        request_digest=REQUEST_DIGEST,
    )


async def _wait_for_connector(connector: BlockingConnector) -> None:
    assert await asyncio.to_thread(connector.entered.wait, 2), "connector never entered capture"


@pytest.mark.asyncio
async def test_tc126_kill_switch_cancels_only_its_running_job_and_reports_thread_drain():
    first_connector = BlockingConnector()
    second_connector = BlockingConnector()
    runtime_one, service_one, living_one, source_scope_one = _runtime(
        SOURCE_ONE, COMPANY_ONE, first_connector)
    runtime_two, service_two, living_two, source_scope_two = _runtime(
        SOURCE_TWO, COMPANY_TWO, second_connector)
    scope_one = service_one.scope
    scope_two = service_two.scope
    job_one, job_two = uuid4(), uuid4()
    ticket_one, ticket_two = _ticket(job_one, COMPANY_ONE), _ticket(job_two, COMPANY_TWO)
    request_one = CaptureRequest(SOURCE_ONE, TENANT, 0)
    request_two = CaptureRequest(SOURCE_TWO, TENANT, 0)
    capture_one = asyncio.create_task(
        service_one.capture(ticket_one, "connection-one", request_one, snapshot=True))
    capture_two = asyncio.create_task(
        service_two.capture(ticket_two, "connection-two", request_two, snapshot=True))

    try:
        await asyncio.gather(_wait_for_connector(first_connector),
                             _wait_for_connector(second_connector))
        row_one = await living_one.get_job(WORKER, source_scope_one, job_one)
        row_two = await living_two.get_job(WORKER, source_scope_two, job_two)
        assert row_one.state == row_two.state == "RUNNING"

        stopped_one = await service_one.stop(scope_one, drain_timeout_seconds=0.05)
        assert stopped_one.admission_closed
        assert stopped_one.terminated_job_ids == (str(job_one),)
        assert stopped_one.queue_pending_job_ids == ()
        assert stopped_one.connector_pending_job_ids == (str(job_one),)
        assert service_two.state.value == "ACCEPTING"
        assert second_connector.entered.is_set() and not second_connector.release.is_set()
        assert (await living_one.get_job(WORKER, source_scope_one, job_one)).state == "CANCELLED"
        assert (await living_two.get_job(WORKER, source_scope_two, job_two)).state == "RUNNING"
        assert (await capture_one).status == "CANCELLED"

        denied = await service_one.capture(
            _ticket(uuid4(), COMPANY_ONE), "connection-one", request_one, snapshot=True)
        assert denied.status == "NOT_ADMITTED"
        assert first_connector.calls == 1

        first_connector.release.set()
        drained_one = await service_one.stop(scope_one, drain_timeout_seconds=2)
        assert drained_one.queue_pending_job_ids == ()
        assert drained_one.connector_pending_job_ids == ()

        stopped_two = await service_two.stop(scope_two, drain_timeout_seconds=0.05)
        assert stopped_two.admission_closed
        assert stopped_two.terminated_job_ids == (str(job_two),)
        assert stopped_two.connector_pending_job_ids == (str(job_two),)
        assert (await living_two.get_job(WORKER, source_scope_two, job_two)).state == "CANCELLED"
        assert (await capture_two).status == "CANCELLED"
        second_connector.release.set()
        drained_two = await service_two.stop(scope_two, drain_timeout_seconds=2)
        assert drained_two.queue_pending_job_ids == ()
        assert drained_two.connector_pending_job_ids == ()
    finally:
        first_connector.release.set()
        second_connector.release.set()
        if not capture_one.done():
            capture_one.cancel()
        if not capture_two.done():
            capture_two.cancel()
        await asyncio.gather(capture_one, capture_two, return_exceptions=True)
        if runtime_one._phase2_capture_runtime is not None:
            await runtime_one.close()
        if runtime_two._phase2_capture_runtime is not None:
            await runtime_two.close()


@pytest.mark.asyncio
async def test_tc126_timeout_keeps_sync_thread_owned_until_close_can_drain_it():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(
        SOURCE_ONE, COMPANY_ONE, connector, connector_timeout=0.02)
    job_id = uuid4()
    request = CaptureRequest(SOURCE_ONE, TENANT, 0)

    try:
        result = await service.capture(
            _ticket(job_id, COMPANY_ONE), "connection-timeout", request, snapshot=True)
        assert result.status == "FAILED"
        assert result.capture.outcome_kind is CaptureOutcomeKind.TIMEOUT
        assert connector.entered.is_set() and not connector.release.is_set()
        assert (await living.get_job(WORKER, source_scope, job_id)).state == "RUNNING"

        stopped = await service.stop(service.scope, drain_timeout_seconds=0.05)
        assert stopped.admission_closed
        assert stopped.connector_pending_job_ids == (str(job_id),)
        assert (await living.get_job(WORKER, source_scope, job_id)).state == "CANCELLED"
        with pytest.raises(RuntimeError, match="CAPTURE_RUNTIME_DRAIN_INCOMPLETE"):
            await service.close(drain_timeout_seconds=0.05)

        connector.release.set()
        drained = await service.stop(service.scope, drain_timeout_seconds=2)
        assert drained.connector_pending_job_ids == ()
        await runtime.close()
    finally:
        connector.release.set()
        if runtime._phase2_capture_runtime is not None:
            # Cleanup must not mask the assertion above if the product fails to
            # finalize a timed-out queue row after its connector thread drains.
            try:
                await runtime.close()
            except RuntimeError:
                pass


@pytest.mark.asyncio
async def test_tc126_stop_cancels_queued_job_before_any_lease_can_be_acquired():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(SOURCE_ONE, COMPANY_ONE, connector)
    scheduler = service._loop._sched
    original_run_job = scheduler.run_job
    run_entered = asyncio.Event()

    async def wait_before_lease(*args, **kwargs):
        run_entered.set()
        await asyncio.Future()  # stop cancels this job before the scheduler is entered

    scheduler.run_job = wait_before_lease
    job_id = uuid4()
    request = CaptureRequest(SOURCE_ONE, TENANT, 0)
    capture = asyncio.create_task(
        service.capture(_ticket(job_id, COMPANY_ONE), "connection-queued", request, snapshot=True))

    try:
        await asyncio.wait_for(run_entered.wait(), timeout=2)
        queued = await living.get_job(WORKER, source_scope, job_id)
        assert queued.state == "PENDING"
        stopped = await service.stop(service.scope, drain_timeout_seconds=2)
        assert stopped.admission_closed
        assert stopped.terminated_job_ids == (str(job_id),)
        assert stopped.queue_pending_job_ids == ()
        assert connector.calls == 0
        assert (await capture).status == "CANCELLED"
        assert (await living.get_job(WORKER, source_scope, job_id)).state == "CANCELLED"

        scheduler.run_job = original_run_job
        retried = await original_run_job(job_id, lambda _handle: asyncio.sleep(0))
        assert retried.status is RunStatus.CANCELLED
        assert connector.calls == 0
    finally:
        scheduler.run_job = original_run_job
        if not capture.done():
            capture.cancel()
        await asyncio.gather(capture, return_exceptions=True)
        if runtime._phase2_capture_runtime is not None:
            await runtime.close()


@pytest.mark.asyncio
async def test_tc126_stop_finalizes_lease_when_acquire_response_is_delayed():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(SOURCE_ONE, COMPANY_ONE, connector)
    scheduler = service._loop._sched
    original_acquire = living.acquire_job
    original_run_job = scheduler.run_job
    acquire_committed = asyncio.Event()
    release_acquire_response = asyncio.Event()
    acquired_fences: list[int] = []
    job_id = uuid4()
    request = CaptureRequest(SOURCE_ONE, TENANT, 0)

    async def delayed_acquire(actor, scope, acquired_job_id, worker, lease_seconds):
        fence = await original_acquire(
            actor, scope, acquired_job_id, worker, lease_seconds)
        if acquired_job_id == job_id:
            acquired_fences.append(fence)
            acquire_committed.set()
            await release_acquire_response.wait()
        return fence

    living.acquire_job = delayed_acquire
    capture = asyncio.create_task(service.capture(
        _ticket(job_id, COMPANY_ONE), "connection-delayed-acquire", request, snapshot=True))
    stop_task = None

    try:
        await asyncio.wait_for(acquire_committed.wait(), timeout=2)
        committed = await living.get_job(WORKER, source_scope, job_id)
        assert committed.state == "RUNNING"
        assert committed.lease_owner == scheduler._worker
        assert acquired_fences == [committed.fence]

        worker_task = service._jobs[job_id]
        stop_task = asyncio.create_task(service.stop(service.scope, drain_timeout_seconds=2))
        async with asyncio.timeout(2):
            while worker_task.cancelling() == 0:
                await asyncio.sleep(0)
        assert service.state.value == "STOPPED"

        release_acquire_response.set()
        stopped = await asyncio.wait_for(stop_task, timeout=2)
        assert stopped.admission_closed
        assert stopped.terminated_job_ids == (str(job_id),)
        assert stopped.queue_pending_job_ids == ()
        assert stopped.connector_pending_job_ids == ()
        assert (await capture).status == "CANCELLED"

        cancelled = await living.get_job(WORKER, source_scope, job_id)
        assert cancelled.state == "CANCELLED"
        assert cancelled.fence == acquired_fences[0]
        assert cancelled.lease_owner is None and cancelled.lease_until is None
        assert connector.calls == 0

        living.acquire_job = original_acquire
        retried = await original_run_job(job_id, lambda _handle: asyncio.sleep(0))
        assert retried.status is RunStatus.CANCELLED
        assert connector.calls == 0
    finally:
        release_acquire_response.set()
        connector.release.set()
        if stop_task is not None and not stop_task.done():
            await asyncio.gather(stop_task, return_exceptions=True)
        if not capture.done():
            capture.cancel()
        await asyncio.gather(capture, return_exceptions=True)
        living.acquire_job = original_acquire
        if runtime._phase2_capture_runtime is not None:
            await runtime.close()


@pytest.mark.asyncio
async def test_tc126_stop_owns_queue_row_after_capture_task_returns_without_a_lease():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(SOURCE_ONE, COMPANY_ONE, connector)
    job_id = uuid4()
    request = CaptureRequest(SOURCE_ONE, TENANT, 0)

    try:
        result = await service.capture(
            _ticket(job_id, COMPANY_ONE), "connection-needs-snapshot", request)
        assert result.status == "RESNAPSHOT_REQUIRED"
        assert result.capture.run is None
        assert (await living.get_job(WORKER, source_scope, job_id)).state == "PENDING"

        stopped = await service.stop(service.scope, drain_timeout_seconds=0.2)
        assert stopped.terminated_job_ids == (str(job_id),)
        assert stopped.queue_pending_job_ids == ()
        assert stopped.runtime_pending_job_ids == ()
        assert (await living.get_job(WORKER, source_scope, job_id)).state == "CANCELLED"
        assert connector.calls == 0
    finally:
        if runtime._phase2_capture_runtime is not None:
            await runtime.close()


@pytest.mark.asyncio
async def test_tc126_stop_deadline_surfaces_a_stalled_acquire_without_waiting_for_it():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(SOURCE_ONE, COMPANY_ONE, connector)
    original_acquire = living.acquire_job
    acquire_committed = asyncio.Event()
    release_acquire_response = asyncio.Event()
    job_id = uuid4()
    request = CaptureRequest(SOURCE_ONE, TENANT, 0)

    async def stalled_acquire(actor, scope, acquired_job_id, worker, lease_seconds):
        fence = await original_acquire(actor, scope, acquired_job_id, worker, lease_seconds)
        if acquired_job_id == job_id:
            acquire_committed.set()
            await release_acquire_response.wait()
        return fence

    living.acquire_job = stalled_acquire
    capture = asyncio.create_task(service.capture(
        _ticket(job_id, COMPANY_ONE), "connection-stalled-acquire", request, snapshot=True))

    try:
        await asyncio.wait_for(acquire_committed.wait(), timeout=2)
        started = asyncio.get_running_loop().time()
        stopped = await service.stop(service.scope, drain_timeout_seconds=0.05)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 0.3
        assert stopped.admission_closed
        assert str(job_id) in stopped.runtime_pending_job_ids
        assert str(job_id) in stopped.queue_pending_job_ids
        assert connector.calls == 0

        release_acquire_response.set()
        result = await asyncio.wait_for(capture, timeout=2)
        assert result.status == "CANCELLED"
        cancelled = await living.get_job(WORKER, source_scope, job_id)
        assert cancelled.state == "CANCELLED"
        drained = await service.stop(service.scope, drain_timeout_seconds=0.2)
        assert drained.queue_pending_job_ids == ()
        assert drained.runtime_pending_job_ids == ()
    finally:
        release_acquire_response.set()
        living.acquire_job = original_acquire
        if not capture.done():
            capture.cancel()
        await asyncio.gather(capture, return_exceptions=True)
        if runtime._phase2_capture_runtime is not None:
            await runtime.close()


@pytest.mark.asyncio
async def test_tc126_stop_cancels_executor_work_that_has_not_started():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(
        SOURCE_ONE, COMPANY_ONE, connector, max_threads=1, backend_limit=2)
    scheduler = service._loop._sched
    original_run_job = scheduler.run_job

    class FreshLease:
        async def ensure_fresh(self):
            return None

    async def concurrently_run(job_id, work, *args, **kwargs):
        # The production scheduler intentionally serializes one source. This deterministic test
        # seam drives two already-admitted work callbacks concurrently so the single-thread
        # connector executor has one running call and one not-yet-started future to cancel.
        await work(FreshLease())
        return RunResult(RunStatus.SUCCEEDED)

    scheduler.run_job = concurrently_run
    first_id, queued_id = uuid4(), uuid4()
    request = CaptureRequest(SOURCE_ONE, TENANT, 0)
    first_capture = asyncio.create_task(service.capture(
        _ticket(first_id, COMPANY_ONE), "connection-first", request, snapshot=True))
    queued_capture = None

    async def wait_for_queued_future():
        deadline = asyncio.get_running_loop().time() + 2
        while asyncio.get_running_loop().time() < deadline:
            with service._loop._inflight_lock:
                futures = dict(service._loop._inflight)
            if len(futures) == 2 and any(not future.running() for future in futures):
                return futures
            await asyncio.sleep(0)
        first_row = await living.get_job(WORKER, source_scope, first_id)
        queued_row = await living.get_job(WORKER, source_scope, queued_id)
        raise AssertionError(
            "second connector future was not queued behind the running call; "
            f"futures={len(futures)}, first_row={first_row}, queued_row={queued_row}, "
            f"first_done={first_capture.done()}, queued_done={queued_capture.done()}, "
            f"connector_calls={connector.calls}, active_budget={service._loop._sched._budget.active_total}"
        )

    try:
        await _wait_for_connector(connector)
        queued_capture = asyncio.create_task(service.capture(
            _ticket(queued_id, COMPANY_ONE), "connection-queued-executor", request,
            snapshot=True))
        futures = await wait_for_queued_future()
        queued_futures = [future for future in futures if not future.running()]
        assert len(queued_futures) == 1

        stopped = await service.stop(service.scope, drain_timeout_seconds=0.05)
        assert stopped.admission_closed
        assert connector.calls == 1
        assert (await living.get_job(WORKER, source_scope, queued_id)).state == "CANCELLED"
        assert (await queued_capture).status == "CANCELLED"

        connector.release.set()
        await asyncio.wait_for(first_capture, timeout=2)
        drained = await service.stop(service.scope, drain_timeout_seconds=2)
        assert drained.queue_pending_job_ids == ()
        assert drained.connector_pending_job_ids == ()
        assert connector.calls == 1
    finally:
        connector.release.set()
        scheduler.run_job = original_run_job
        if queued_capture is not None and not queued_capture.done():
            queued_capture.cancel()
        if not first_capture.done():
            first_capture.cancel()
        await asyncio.gather(first_capture, *( [queued_capture] if queued_capture else [] ),
                             return_exceptions=True)
        if runtime._phase2_capture_runtime is not None:
            await runtime.close()


@pytest.mark.asyncio
async def test_tc126_stalled_queue_cancel_does_not_starve_later_owned_rows():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(SOURCE_ONE, COMPANY_ONE, connector)
    original_cancel = service._loop.cancel_job
    job_ids = [uuid4() for _ in range(4)]
    stalled_id = job_ids[0]
    attempted: list[UUID] = []
    stalled_started = asyncio.Event()
    release_stalled = asyncio.Event()

    async def cancel_with_one_stalled_row(job_id):
        attempted.append(job_id)
        if job_id == stalled_id:
            stalled_started.set()
            await release_stalled.wait()
        return await original_cancel(job_id)

    service._loop.cancel_job = cancel_with_one_stalled_row

    try:
        for index, job_id in enumerate(job_ids):
            result = await service.capture(
                _ticket(job_id, COMPANY_ONE), f"connection-needs-snapshot-{index}",
                CaptureRequest(SOURCE_ONE, TENANT, 0), snapshot=False)
            assert result.status == "RESNAPSHOT_REQUIRED"
            assert (await living.get_job(WORKER, source_scope, job_id)).state == "PENDING"

        started = asyncio.get_running_loop().time()
        stopped = await service.stop(service.scope, drain_timeout_seconds=0.1)
        elapsed = asyncio.get_running_loop().time() - started

        assert await asyncio.wait_for(stalled_started.wait(), timeout=0.2)
        assert elapsed < 0.5
        assert set(attempted) == set(job_ids)
        assert len(service._queue_cleanup_tasks) <= 8
        assert stopped.queue_pending_job_ids == (str(stalled_id),)
        assert set(stopped.terminated_job_ids) == {str(job_id) for job_id in job_ids[1:]}
        for job_id in job_ids[1:]:
            assert (await living.get_job(WORKER, source_scope, job_id)).state == "CANCELLED"
        assert (await living.get_job(WORKER, source_scope, stalled_id)).state == "PENDING"
        assert connector.calls == 0

        release_stalled.set()
        drained = await service.stop(service.scope, drain_timeout_seconds=0.2)
        assert drained.queue_pending_job_ids == ()
        assert (await living.get_job(WORKER, source_scope, stalled_id)).state == "CANCELLED"
    finally:
        release_stalled.set()
        service._loop.cancel_job = original_cancel
        if runtime._phase2_capture_runtime is not None:
            await runtime.close()


@pytest.mark.asyncio
async def test_tc126_queue_cleanup_cap_surfaces_unscheduled_rows_for_later_stop():
    connector = BlockingConnector()
    runtime, service, living, source_scope = _runtime(SOURCE_ONE, COMPANY_ONE, connector)
    original_cancel = service._loop.cancel_job
    job_ids = [uuid4() for _ in range(10)]
    attempted: list[UUID] = []
    release_cancellations = asyncio.Event()

    async def hold_cancellation_until_released(job_id):
        attempted.append(job_id)
        await release_cancellations.wait()
        return await original_cancel(job_id)

    service._loop.cancel_job = hold_cancellation_until_released

    try:
        for index, job_id in enumerate(job_ids):
            result = await service.capture(
                _ticket(job_id, COMPANY_ONE), f"connection-pending-{index}",
                CaptureRequest(SOURCE_ONE, TENANT, 0), snapshot=False)
            assert result.status == "RESNAPSHOT_REQUIRED"
            assert (await living.get_job(WORKER, source_scope, job_id)).state == "PENDING"

        started = asyncio.get_running_loop().time()
        stopped = await service.stop(service.scope, drain_timeout_seconds=0.1)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 0.5
        assert len(attempted) == 8
        assert len(service._queue_cleanup_tasks) == 8
        assert set(stopped.queue_pending_job_ids) == {str(job_id) for job_id in job_ids}
        for job_id in job_ids:
            assert (await living.get_job(WORKER, source_scope, job_id)).state == "PENDING"
        assert connector.calls == 0

        release_cancellations.set()
        active_cleanup = tuple(service._queue_cleanup_tasks.values())
        _, still_active = await asyncio.wait(active_cleanup, timeout=1)
        assert not still_active
        drained = await service.stop(service.scope, drain_timeout_seconds=0.3)
        assert drained.queue_pending_job_ids == ()
        assert len(attempted) == 10
        for job_id in job_ids:
            assert (await living.get_job(WORKER, source_scope, job_id)).state == "CANCELLED"
    finally:
        release_cancellations.set()
        service._loop.cancel_job = original_cancel
        if runtime._phase2_capture_runtime is not None:
            await runtime.close()

