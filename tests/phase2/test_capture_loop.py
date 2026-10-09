# ruff: noqa: RUF059 - tests unpack the whole build() tuple
"""Behavioral tests of the S4B-E3 capture loop (scheduler + SDK + drift + resnapshot tracker).

Deterministic: fake store clock, fake connector, no sleeps. Each ``test_guard_*`` pins one guard so
that removing the guard turns it red.
"""
from datetime import UTC, datetime
from uuid import UUID

import pytest

from business_ai_gateway.phase2.backend_budget import BackendId, PhysicalBackendBudget
from business_ai_gateway.phase2.capture_loop import (
    CaptureLoop,
    CaptureStatus,
    ConnectorFailure,
)
from business_ai_gateway.phase2.connector_sdk import (
    CaptureMode,
    CaptureRequest,
    CaptureResponse,
    Completeness,
    Provenance,
)
from business_ai_gateway.phase2.drift import CaptureOutcomeKind, DriftEventKind
from business_ai_gateway.phase2.fakes import WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import Scope
from business_ai_gateway.phase2.resnapshot import ResnapshotReason, ResnapshotTracker
from business_ai_gateway.phase2.scheduler import RunStatus, SourceScheduler

SCOPE = Scope("A", "s1")
CONN = "c1"
H1, H2 = "a" * 64, "b" * 64
SECRET = "https://user:hunter2@secret.example/db?token=abc"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeConnector:
    """Plays back scripted steps: a Completeness, a digest, an Exception, or a callable."""
    connector_id, connector_version = "fake", "1"

    def __init__(self, *steps, epoch=0, tamper=None, on_call=None):
        self.steps, self.calls, self.epoch = list(steps), 0, epoch
        self.tamper, self.on_call = tamper, on_call

    def health(self, *, source_id, tenant_id):
        raise NotImplementedError

    def capture_page(self, request):
        self.calls += 1
        if self.on_call:
            self.on_call()
        step = self.steps.pop(0) if self.steps else (Completeness.COMPLETE, H1)
        if isinstance(step, BaseException):
            raise step
        if self.tamper == "not_a_response":
            return {"completeness": "COMPLETE"}
        completeness, digest = step
        return CaptureResponse(
            "src-2" if self.tamper == "source" else request.source_id, request.tenant_id,
            request.scope_epoch, CaptureMode.SNAPSHOT_ONLY, completeness,
            Provenance("fake", "1", NOW, digest, request.page_cursor))


def req(epoch=0):
    return CaptureRequest("src-1", "ten-1", epoch)


async def build(connector, *, epoch=0, jobs=1):
    living = InMemoryLiving()
    for _ in range(epoch):  # bump first: jobs are bound to the epoch they were enqueued under
        await living.bump_scope_epoch(SCOPE)
    for n in range(1, jobs + 1):
        await living.enqueue_job(WORKER, SCOPE, UUID(int=n), "sync", H1, f"key-{n}")
    sched = SourceScheduler(
        living, actor=WORKER, scope=SCOPE, worker="w1", backend_id=BackendId.normalize("db-1"),
        budget=PhysicalBackendBudget(per_backend_limit=1, total_limit=4),
        clock=living.clock.now, jitter_source=lambda: 0.0)
    tracker = ResnapshotTracker()
    return living, sched, tracker, CaptureLoop(sched, tracker, connector, living, SCOPE)


def job(n=1):
    return UUID(int=n)


async def test_guard_incremental_refused_while_required_without_touching_job():
    conn = FakeConnector()
    living, sched, tracker, loop = await build(conn)
    tracker.require(CONN, ResnapshotReason.OPERATOR, 0)
    before = sched.counter
    res = await loop.capture_step(job(), CONN, req())
    assert res.status is CaptureStatus.RESNAPSHOT_REQUIRED
    assert res.resnapshot_required and res.run is None
    assert conn.calls == 0
    view = await living.get_job(WORKER, SCOPE, job())
    assert (view.state, view.attempt) == ("PENDING", 0)
    assert sched.counter == before and not sched.is_poisoned(job())
    assert sched.not_before(job()) is None


async def test_guard_work_rechecks_requirement_after_lease_without_calling_connector():
    """Requirement appears between the pre-check and the lease: connector still not called."""
    conn = FakeConnector()
    living, sched, tracker, loop = await build(conn)
    orig = sched.reap

    async def reap_then_require():
        tracker.require(CONN, ResnapshotReason.CURSOR_LOST, 0)
        return await orig()
    sched.reap = reap_then_require
    res = await loop.capture_step(job(), CONN, req())
    assert res.status is CaptureStatus.RESNAPSHOT_REQUIRED
    assert conn.calls == 0
    assert res.run.status is RunStatus.RETRY_SCHEDULED  # port has no release: one accounted retry


async def test_guard_cursor_loss_requires_resnapshot_and_next_incremental_is_refused():
    conn = FakeConnector(ConnectorFailure(CaptureOutcomeKind.CURSOR_LOST))
    living, sched, tracker, loop = await build(conn, jobs=2)
    res = await loop.capture_step(job(1), CONN, req())
    assert res.status is CaptureStatus.FAILED
    assert res.outcome_kind is CaptureOutcomeKind.CURSOR_LOST
    assert DriftEventKind.RESNAPSHOT_REQUIRED in res.events
    assert tracker.reason(CONN) is ResnapshotReason.CURSOR_LOST and res.resnapshot_required
    res2 = await loop.capture_step(job(2), CONN, req())
    assert res2.status is CaptureStatus.RESNAPSHOT_REQUIRED and conn.calls == 1


async def test_guard_complete_snapshot_at_live_epoch_clears_requirement():
    conn = FakeConnector((Completeness.COMPLETE, H1))
    living, sched, tracker, loop = await build(conn, epoch=1)
    tracker.require(CONN, ResnapshotReason.CURSOR_LOST, 1)
    res = await loop.capture_step(job(), CONN, req(1), snapshot=True)
    assert res.status is CaptureStatus.CAPTURED and res.cleared
    assert not res.resnapshot_required and tracker.incremental_allowed(CONN)
    assert res.accepted_hash == H1 and loop.accepted_hash(CONN) == H1


@pytest.mark.parametrize("step", [
    (Completeness.PARTIAL, H1), (Completeness.UNKNOWN, H1),
    ConnectorFailure(CaptureOutcomeKind.TIMEOUT), ConnectorFailure(CaptureOutcomeKind.OUTAGE),
    ConnectorFailure(CaptureOutcomeKind.ACCESS_DENIED),
])
async def test_guard_partial_or_failed_snapshot_keeps_requirement(step):
    conn = FakeConnector(step)
    living, sched, tracker, loop = await build(conn)
    tracker.require(CONN, ResnapshotReason.CURSOR_LOST, 0)
    res = await loop.capture_step(job(), CONN, req(), snapshot=True)
    assert conn.calls == 1 and not res.cleared
    assert tracker.is_required(CONN) and res.resnapshot_required


async def test_guard_snapshot_at_older_epoch_keeps_requirement():
    conn = FakeConnector((Completeness.COMPLETE, H1))
    living, sched, tracker, loop = await build(conn, epoch=2)
    tracker.require(CONN, ResnapshotReason.SCOPE_EPOCH_CHANGED, 1)
    res = await loop.capture_step(job(), CONN, req(1), snapshot=True)  # ran under epoch 1, live 2
    assert res.status is CaptureStatus.CAPTURED and not res.cleared
    assert tracker.is_required(CONN)


async def test_guard_late_snapshot_started_before_requirement_does_not_clear():
    """Token is taken BEFORE the connector call: a requirement recorded mid-call survives."""
    tracker_box = {}
    conn = FakeConnector((Completeness.COMPLETE, H1), on_call=lambda: tracker_box["t"].require(
        CONN, ResnapshotReason.CURSOR_LOST, 0))
    living, sched, tracker, loop = await build(conn)
    tracker_box["t"] = tracker
    assert not tracker.is_required(CONN)
    res = await loop.capture_step(job(), CONN, req(), snapshot=True)
    assert res.status is CaptureStatus.CAPTURED and not res.cleared
    assert tracker.is_required(CONN)


async def test_guard_sdk_invalid_response_is_failure_not_drift():
    for tamper in ("source", "not_a_response"):
        conn = FakeConnector((Completeness.COMPLETE, H2), tamper=tamper)
        living, sched, tracker, loop = await build(conn)
        loop._accepted[CONN] = H1
        res = await loop.capture_step(job(), CONN, req())
        assert res.status is CaptureStatus.INVALID_RESPONSE
        assert res.run.status is RunStatus.RETRY_SCHEDULED
        assert res.run.detail == "WORK_RETURNED_INVALID"
        assert res.events == () and res.candidate_hash is None
        assert res.accepted_hash == H1 and not tracker.is_required(CONN)
        assert sched.counter.consecutive_failures == 1


async def test_guard_exception_text_is_never_persisted_or_returned():
    conn = FakeConnector(RuntimeError(SECRET))
    living, sched, tracker, loop = await build(conn)
    res = await loop.capture_step(job(), CONN, req())
    assert res.status is CaptureStatus.FAILED
    assert res.run.detail == "WORK_EXCEPTION:RuntimeError"
    assert res.outcome_kind is CaptureOutcomeKind.OUTAGE
    view = await living.get_job(WORKER, SCOPE, job())
    for text in (repr(res), repr(view), repr(sched.export_state())):
        assert "hunter2" not in text and "secret.example" not in text


async def test_guard_drift_on_complete_does_not_advance_accepted_hash():
    conn = FakeConnector((Completeness.COMPLETE, H1), (Completeness.COMPLETE, H2))
    living, sched, tracker, loop = await build(conn, jobs=2)
    first = await loop.capture_step(job(1), CONN, req())
    assert first.events == () and first.accepted_hash == H1
    second = await loop.capture_step(job(2), CONN, req())
    assert second.status is CaptureStatus.CAPTURED
    assert second.events == (DriftEventKind.STRUCTURAL_DRIFT,)
    assert second.accepted_hash == H1 and second.candidate_hash == H2
    assert loop.accepted_hash(CONN) == H1


@pytest.mark.parametrize("step,kind", [
    (ConnectorFailure(CaptureOutcomeKind.OUTAGE), CaptureOutcomeKind.OUTAGE),
    (TimeoutError(SECRET), CaptureOutcomeKind.TIMEOUT),
    (ConnectorFailure(CaptureOutcomeKind.ACCESS_DENIED), CaptureOutcomeKind.ACCESS_DENIED),
    ((Completeness.PARTIAL, H2), CaptureOutcomeKind.OK_PARTIAL),
])
async def test_guard_failures_and_partial_never_yield_drift_or_move_baseline(step, kind):
    conn = FakeConnector(step)
    living, sched, tracker, loop = await build(conn)
    loop._accepted[CONN] = H1
    res = await loop.capture_step(job(), CONN, req())
    assert res.outcome_kind is kind
    assert DriftEventKind.STRUCTURAL_DRIFT not in res.events
    assert res.candidate_hash is None and res.accepted_hash == H1
    assert not tracker.is_required(CONN)
    assert "hunter2" not in repr(res)


async def test_guard_lost_lease_at_finish_applies_no_clear_and_no_hash():
    conn = FakeConnector((Completeness.COMPLETE, H1))
    living, sched, tracker, loop = await build(conn)
    tracker.require(CONN, ResnapshotReason.CURSOR_LOST, 0)

    async def expire():
        living.clock.advance(1000)  # own lease expires during the capture
    conn.on_call = None
    orig = sched._succeeded

    async def late(job_id, handle, outcome):
        await expire()
        return await orig(job_id, handle, outcome)
    sched._succeeded = late
    res = await loop.capture_step(job(), CONN, req(), snapshot=True)
    assert res.run.status is not RunStatus.SUCCEEDED
    assert not res.cleared and tracker.is_required(CONN)
    assert loop.accepted_hash(CONN) is None
