"""Behavioral tests of ``SourceScheduler.resume_revalidated`` (TC060)."""
import asyncio
from uuid import UUID

import pytest

from business_ai_gateway.phase2.backend_budget import BackendId, PhysicalBackendBudget
from business_ai_gateway.phase2.drift import CaptureOutcomeKind
from business_ai_gateway.phase2.fakes import WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import PortError, Scope
from business_ai_gateway.phase2.resnapshot import (
    ResnapshotBlocked,
    ResnapshotReason,
    ResnapshotTracker,
)
from business_ai_gateway.phase2.scheduler import SourceScheduler, SourceState

SCOPE = Scope("A", "s1")


async def setup(*cursors):
    living = InMemoryLiving()
    await living.enqueue_job(WORKER, SCOPE, UUID(int=1), "sync", "a" * 64, "k")
    await living.bump_scope_epoch(SCOPE)  # live epoch is 1 (a fresh source starts at 0)
    for c in cursors:  # created AFTER the bump so they are bound to the live epoch
        await living.create_cursor(WORKER, SCOPE, c, "c0")
    sched = SourceScheduler(
        living, actor=WORKER, scope=SCOPE, worker="w1", backend_id=BackendId.normalize("db-1"),
        budget=PhysicalBackendBudget(per_backend_limit=1, total_limit=4),
        clock=living.clock.now, jitter_source=lambda: 0.0)
    return living, sched


def paused(sched):
    sched.machine.pause("test")
    sched.counter = sched.counter.advance(CaptureOutcomeKind.TIMEOUT)
    assert sched.counter.consecutive_failures == 1


def call(sched, living, tracker, ids, epoch):
    return sched.resume_revalidated(
        "op", tracker=tracker, ledger=living, cursors=living, connection_ids=ids,
        recorded_epoch=epoch)


def test_resume_clean_resumes_and_resets_counter():
    async def go():
        living, sched = await setup("c1")
        paused(sched)
        assert await call(sched, living, ResnapshotTracker(), ["c1"], 1) == ()
        assert sched.machine.state is SourceState.ACTIVE
        assert sched.counter.consecutive_failures == 0
    asyncio.run(go())


def test_guard_resume_reports_epoch_change_but_still_resumes():
    async def go():
        living, sched = await setup("c1")
        paused(sched)
        await living.bump_scope_epoch(SCOPE)
        t = ResnapshotTracker()
        assert await call(sched, living, t, ["c1"], 1) == ("c1",)
        assert t.reason("c1") is ResnapshotReason.SCOPE_EPOCH_CHANGED
        assert sched.machine.state is SourceState.ACTIVE
    asyncio.run(go())


def test_guard_resume_reports_a_cursor_bound_to_an_older_epoch():
    """live == recorded but the cursor was never rebased: the source resumes, the cursor must resnapshot."""
    async def go():
        living, sched = await setup("c1")
        await living.bump_scope_epoch(SCOPE)       # live 2; the cursor stays bound to epoch 1
        paused(sched)
        t = ResnapshotTracker()
        assert await call(sched, living, t, ["c1"], 2) == ("c1",)
        assert t.reason("c1") is ResnapshotReason.SCOPE_EPOCH_CHANGED
        assert t.incremental_allowed("c1") is False
    asyncio.run(go())


def test_guard_resume_reports_missing_cursor():
    async def go():
        living, sched = await setup()
        paused(sched)
        t = ResnapshotTracker()
        assert await call(sched, living, t, ["c1"], 1) == ("c1",)
        assert t.reason("c1") is ResnapshotReason.CURSOR_MISSING
    asyncio.run(go())


@pytest.mark.parametrize("final", ["PAUSED", "QUARANTINED"])
def test_guard_blocked_resume_keeps_state_and_counter(final):
    async def go():
        living, sched = await setup("c1")
        paused(sched)
        if final == "QUARANTINED":
            sched.machine.quarantine("q")
        await living.revoke_scope(WORKER, SCOPE)
        t = ResnapshotTracker()
        with pytest.raises(ResnapshotBlocked):
            await call(sched, living, t, ["c1"], 1)
        assert sched.machine.state is SourceState(final)
        assert sched.counter.consecutive_failures == 1
        assert t.required_connections() == ()
    asyncio.run(go())


@pytest.mark.parametrize("final", ["PAUSED", "QUARANTINED"])
def test_guard_empty_connection_list_never_resumes_a_revoked_source(final):
    """No connection to read means no probe of the scope: reject instead of resuming."""
    async def go():
        living, sched = await setup("c1")
        paused(sched)
        if final == "QUARANTINED":
            sched.machine.quarantine("q")
        await living.revoke_scope(WORKER, SCOPE)
        with pytest.raises(ValueError, match="CONNECTION_IDS_REQUIRED"):
            await call(sched, living, ResnapshotTracker(), [], 1)
        assert sched.machine.state is SourceState(final)
        assert sched.counter.consecutive_failures == 1
    asyncio.run(go())


def test_guard_other_port_error_propagates_without_resume():
    class Broken:
        async def scope_epoch(self, scope):
            raise PortError("CHECK_VIOLATION")

    async def go():
        living, sched = await setup("c1")
        paused(sched)
        with pytest.raises(PortError):
            await sched.resume_revalidated(
                "op", tracker=ResnapshotTracker(), ledger=Broken(), cursors=living,
                connection_ids=["c1"], recorded_epoch=1)
        assert sched.machine.state is SourceState.PAUSED
        assert sched.counter.consecutive_failures == 1
    asyncio.run(go())


def test_plain_resume_unchanged_without_revalidation():
    async def go():
        living, sched = await setup()
        paused(sched)
        await living.revoke_scope(WORKER, SCOPE)
        sched.resume("op")  # existing behaviour: no port call, no revalidation
        assert sched.machine.state is SourceState.ACTIVE
    asyncio.run(go())
