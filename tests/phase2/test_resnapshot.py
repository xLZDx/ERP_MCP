"""Behavioral tests of the resnapshot tracker (R2-US-012 / R2-US-020; TC035, TC036, TC060).

Each ``test_guard_*`` fails if the named guard is removed.
"""
import asyncio
import dataclasses

import pytest

from business_ai_gateway.phase2.drift import (
    CaptureOutcome,
    CaptureOutcomeKind,
    DriftDecision,
    DriftEventKind,
    classify,
)
from business_ai_gateway.phase2.fakes import WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import PortError, Scope
from business_ai_gateway.phase2.resnapshot import (
    ResnapshotBlocked,
    ResnapshotReason,
    ResnapshotState,
    ResnapshotTracker,
)

SCOPE = Scope("A", "s1")
R = ResnapshotReason
K = CaptureOutcomeKind
LOST = DriftDecision((DriftEventKind.RESNAPSHOT_REQUIRED,), None)


def run(coro):
    return asyncio.run(coro)


async def living_with_cursor(*names):
    living = InMemoryLiving()
    await living.enqueue_job(WORKER, SCOPE, __import__("uuid").UUID(int=1), "sync", "a" * 64, "k")
    for n in names:
        await living.create_cursor(WORKER, SCOPE, n, "c0")
    await living.bump_scope_epoch(SCOPE)  # live epoch is 1 (a fresh source starts at 0)
    return living


def reval(tracker, living, ids, epoch):
    return tracker.revalidate(living, living, WORKER, SCOPE, ids, epoch)


# --------------------------------------------------------------------------- decision / complete
def test_guard_decision_requires_resnapshot():
    t = ResnapshotTracker()
    assert t.incremental_allowed("c1")
    assert t.observe_decision("c1", LOST, 1) is True
    assert t.is_required("c1") and not t.incremental_allowed("c1")
    assert t.reason("c1") is R.CURSOR_LOST


def test_decision_without_event_requires_nothing():
    t = ResnapshotTracker()
    assert t.observe_decision("c1", classify(CaptureOutcome(K.OK_PARTIAL), None), 1) is False
    assert not t.is_required("c1")


def test_classify_cursor_lost_feeds_tracker():
    t = ResnapshotTracker()
    t.observe_decision("c1", classify(CaptureOutcome(K.CURSOR_LOST), None), 1)
    assert t.is_required("c1")


@pytest.mark.parametrize("kind", [k for k in K if k is not K.OK_COMPLETE])
def test_guard_only_ok_complete_clears(kind):
    t = ResnapshotTracker()
    t.require("c1", R.CURSOR_LOST, 1)
    assert t.complete("c1", kind, 1, 1) is False
    assert t.is_required("c1")


def test_guard_stale_epoch_complete_does_not_clear():
    t = ResnapshotTracker()
    t.require("c1", R.SCOPE_EPOCH_CHANGED, 2)
    assert t.complete("c1", K.OK_COMPLETE, 1, 2) is False
    assert t.is_required("c1")


def test_ok_complete_at_current_epoch_clears():
    t = ResnapshotTracker()
    t.require("c1", R.CURSOR_LOST, 2)
    assert t.complete("c1", K.OK_COMPLETE, 2, 2) is True
    assert t.incremental_allowed("c1")
    assert t.complete("c1", K.OK_COMPLETE, 2, 2) is False  # nothing left to clear


def test_guard_reason_not_downgraded():
    t = ResnapshotTracker()
    t.require("c1", R.CURSOR_LOST, 1)
    t.require("c1", R.OPERATOR, 5)
    t.observe_decision("c1", LOST, 9)
    assert t.reason("c1") is R.CURSOR_LOST
    assert t.export_state().required == (("c1", R.CURSOR_LOST, 1),)


@pytest.mark.parametrize("args", [("", R.OPERATOR, 1), (" ", R.OPERATOR, 1),
                                  ("c", "OPERATOR", 1), ("c", R.OPERATOR, -1),
                                  ("c", R.OPERATOR, True)])
def test_require_rejects_bad_input(args):
    t = ResnapshotTracker()
    with pytest.raises((ValueError, TypeError)):
        t.require(*args)
    assert t.required_connections() == ()


# --------------------------------------------------------------------------- revalidate
def test_guard_revalidate_epoch_change():
    async def go():
        living = await living_with_cursor("c1", "c2")
        t = ResnapshotTracker()
        assert await reval(t, living, ["c1", "c2"], 1) == ()
        await living.bump_scope_epoch(SCOPE)
        assert await reval(t, living, ["c1", "c2"], 1) == ("c1", "c2")
        assert t.reason("c1") is R.SCOPE_EPOCH_CHANGED
    run(go())


def test_guard_revalidate_missing_cursor():
    async def go():
        living = await living_with_cursor("c1")
        t = ResnapshotTracker()
        assert await reval(t, living, ["c1", "gone"], 1) == ("gone",)
        assert t.reason("gone") is R.CURSOR_MISSING
        assert t.incremental_allowed("c1")
    run(go())


def test_guard_revalidate_blocked_requires_nothing():
    async def go():
        living = await living_with_cursor("c1", "c2")
        await living.revoke_scope(WORKER, SCOPE)
        t = ResnapshotTracker()
        with pytest.raises(ResnapshotBlocked) as ei:
            await reval(t, living, ["c1", "c2"], 1)
        assert ei.value.code == "RESNAPSHOT_BLOCKED" and "SCOPE" not in str(ei.value)
        assert t.required_connections() == ()
    run(go())


def test_guard_blocked_midway_is_all_or_nothing():
    class Flaky:
        async def scope_epoch(self, scope):
            return 1

        async def get_cursor(self, actor, scope, cid):
            if cid == "c2":
                raise PortError("PERMISSION_DENIED", "secret detail")

    async def go():
        t = ResnapshotTracker()
        with pytest.raises(ResnapshotBlocked) as ei:
            await t.revalidate(Flaky(), Flaky(), WORKER, SCOPE, ["c1", "c2"], 1)
        assert "secret" not in str(ei.value)
        assert t.required_connections() == ()  # c1 (missing) was not recorded
    run(go())


def test_guard_other_port_error_propagates():
    class Broken:
        async def scope_epoch(self, scope):
            raise PortError("CHECK_VIOLATION")

    async def go():
        t = ResnapshotTracker()
        with pytest.raises(PortError) as ei:
            await t.revalidate(Broken(), Broken(), WORKER, SCOPE, ["c1"], 1)
        assert ei.value.code == "CHECK_VIOLATION"
        assert t.required_connections() == ()
    run(go())


def test_guard_revalidate_keeps_existing_reason():
    async def go():
        living = await living_with_cursor()
        t = ResnapshotTracker()
        t.require("c1", R.OPERATOR, 1)
        await reval(t, living, ["c1"], 1)  # cursor missing, but OPERATOR was first
        assert t.reason("c1") is R.OPERATOR
    run(go())


def test_aba_epoch_returning_to_recorded_value_is_not_noticed():
    """Documented limitation: only recorded vs live is compared, so 1 -> 2 -> 1 is invisible."""
    async def go():
        living = await living_with_cursor("c1")
        await living.bump_scope_epoch(SCOPE)  # 2
        living._st.sources[SCOPE].epoch = 1   # test-only: return to the recorded number
        t = ResnapshotTracker()
        assert await reval(t, living, ["c1"], 1) == ()
        assert t.incremental_allowed("c1")
        # but against the epoch actually seen after the change the tracker does notice
        assert await reval(t, living, ["c1"], 2) == ("c1",)
    run(go())


# --------------------------------------------------------------------------- persistence
def test_export_import_roundtrip():
    t = ResnapshotTracker()
    t.require("b", R.CURSOR_MISSING, 3)
    t.require("a", R.OPERATOR, 1)
    snap = t.export_state()
    assert snap.required == (("a", R.OPERATOR, 1), ("b", R.CURSOR_MISSING, 3))
    assert ResnapshotTracker(snap).export_state() == snap


def test_guard_import_never_clears_pending():
    t = ResnapshotTracker()
    t.require("c1", R.CURSOR_LOST, 4)
    t.import_state(ResnapshotState())  # empty/stale snapshot
    assert t.is_required("c1")
    t.import_state(ResnapshotState((("c1", R.OPERATOR, 1), ("c2", R.OPERATOR, 1))))
    assert t.export_state().required == (("c1", R.CURSOR_LOST, 4), ("c2", R.OPERATOR, 1))


@pytest.mark.parametrize("bad", [
    ResnapshotState((("c", R.OPERATOR),)),
    ResnapshotState((("", R.OPERATOR, 1),)),
    ResnapshotState(((1, R.OPERATOR, 1),)),
    ResnapshotState((("c", "OPERATOR", 1),)),
    ResnapshotState((("c", R.OPERATOR, -1),)),
    ResnapshotState((("c", R.OPERATOR, True),)),
    ResnapshotState((("c", R.OPERATOR, 1), ("c", R.OPERATOR, 2))),
    ResnapshotState((["c", R.OPERATOR, 1],)),
    ResnapshotState(5),
    "not a state",
])
def test_guard_invalid_import_rejected_state_unchanged(bad):
    t = ResnapshotTracker()
    t.require("keep", R.OPERATOR, 1)
    before = t.export_state()
    with pytest.raises(ValueError, match="RESNAPSHOT_STATE_INVALID"):
        t.import_state(bad)
    assert t.export_state() == before


def test_invalid_entry_after_valid_one_applies_nothing():
    t = ResnapshotTracker()
    with pytest.raises(ValueError):
        t.import_state(ResnapshotState((("ok", R.OPERATOR, 1), ("bad", R.OPERATOR, -1))))
    assert t.required_connections() == ()


def test_state_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ResnapshotState().required = ()  # type: ignore[misc]
