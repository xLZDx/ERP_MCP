"""R2-US-042 TC124–125 dev/test capture runtime contract."""
from __future__ import annotations

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
from business_ai_gateway.phase2.resnapshot import ResnapshotTracker
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
