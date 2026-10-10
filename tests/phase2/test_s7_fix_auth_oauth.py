"""S7 fix batch F2: Drive OAuth capacity/ordering fixes and auth-state adapters, poll hardening, alert
retry/dedup. Pure in-memory; the real ConsentManager and the real cursor store are used where the
finding was about seams that real components could not satisfy."""
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from business_ai_gateway.phase2 import drive_oauth
from business_ai_gateway.phase2.drive_auth_state import (
    AuthCause,
    AuthGuardedDrivePort,
    AuthState,
    ConsentManagerSeam,
    DriveAuthHealth,
    FakeAlertSink,
    FakeAuthSeam,
    FakeCursorView,
    HintIntake,
    HintResult,
    PollReason,
    PollStatus,
    ReconsentResult,
    StoreCursorReader,
    TokenStatus,
    run_poll,
)
from business_ai_gateway.phase2.drive_auth_state import ConsentState as AuthConsentState
from business_ai_gateway.phase2.drive_changes import DriveChange, DriveChangeKind
from business_ai_gateway.phase2.drive_cursor import (
    CursorReason,
    CursorState,
    DriveCorpus,
    DriveCursorStore,
    DriveLease,
    StoreCommit,
    cursor_key,
)
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_oauth import (
    ConsentCode,
    ConsentManager,
    ConsentState,
    FakeTokenStore,
)
from business_ai_gateway.phase2.drive_port import (
    DriveErrorCode,
    DrivePortError,
    DrivePortIdentity,
)
from business_ai_gateway.phase2.fakes import DEFAULT_SCOPE, WORKER, InMemoryLiving
from business_ai_gateway.phase2.resnapshot import ResnapshotTracker
from business_ai_gateway.phase2.scheduler import SourceState, SourceStateMachine

IDENT = DrivePortIdentity("account:acc-1", "A", "conn-1")
IDENT_B = DrivePortIdentity("account:acc-1", "tenant-2", "conn-1")
VERIFIER = "v" * 43
CODE = "FAKE-CODE-1"
NARROW = ("drive.file",)
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
CORPUS = DriveCorpus(None, ("ROOT-1",))


def _states():
    counter = itertools.count(1)
    return lambda: f"STATE-{next(counter):016d}"


def _mgr(**kw) -> ConsentManager:
    return ConsentManager(lambda: T0, state_source=_states(), **kw)


def _grant(mgr: ConsentManager, ident=IDENT) -> None:
    res = mgr.begin_consent(ident, NARROW, VERIFIER)
    assert res.ok, res
    assert mgr.complete_consent(ident, res.state_value, VERIFIER, CODE).ok


def _chg(cid: str, fid: str) -> DriveChange:
    return DriveChange(cid, fid, "r1", DriveChangeKind.UPSERT)


def _build(epoch: int = 0, seam=None):
    fake = FakeDrivePort(scope_epoch=epoch)
    seam = seam or FakeAuthSeam(scope_epoch=epoch)
    sink = FakeAlertSink()
    machine = SourceStateMachine()
    health = DriveAuthHealth(IDENT, epoch, seam, machine, sink)
    return fake, seam, sink, machine, health, AuthGuardedDrivePort(health, fake)


# ===================================================================================================
# drive_oauth
# ===================================================================================================


def test_tenant_a_begin_cycles_never_make_tenant_b_hit_capacity() -> None:
    mgr = _mgr(max_states=64)
    for _ in range(10_000):
        assert mgr.begin_consent(IDENT, NARROW, VERIFIER).code is ConsentCode.OK
    other = mgr.begin_consent(IDENT_B, NARROW, VERIFIER)
    assert other.ok and other.code is ConsentCode.OK


def test_grant_revoke_cycles_do_not_exhaust_state_capacity_for_other_tenants() -> None:
    mgr = _mgr(max_states=32)
    for _ in range(200):
        _grant(mgr)
        assert mgr.revoke(IDENT).ok
    assert mgr.begin_consent(IDENT_B, NARROW, VERIFIER).ok


def test_per_identity_state_bookkeeping_is_bounded() -> None:
    mgr = _mgr()
    for _ in range(500):
        assert mgr.begin_consent(IDENT, NARROW, VERIFIER).ok
    assert len(mgr._states) <= 16


def test_capacity_refusal_does_not_allocate_a_record() -> None:
    mgr = _mgr(max_states=1)
    assert mgr.begin_consent(IDENT, NARROW, VERIFIER).ok
    assert mgr.begin_consent(IDENT_B, NARROW, VERIFIER).code is ConsentCode.CAPACITY
    assert mgr.snapshot(IDENT_B) is None


def test_failing_state_source_does_not_allocate_a_record() -> None:
    mgr = ConsentManager(lambda: T0, state_source=lambda: "short")
    assert mgr.begin_consent(IDENT, NARROW, VERIFIER).code is ConsentCode.STATE_SOURCE_INVALID
    assert mgr.snapshot(IDENT) is None


def test_clock_overflow_is_a_fixed_refusal_and_does_not_burn_the_pending_state() -> None:
    now = {"t": T0}
    mgr = ConsentManager(lambda: now["t"], state_source=_states())
    first = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert first.ok
    now["t"] = datetime.max.replace(tzinfo=UTC)
    got = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert (got.ok, got.code) == (False, ConsentCode.CLOCK_INVALID)
    now["t"] = T0
    assert mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING
    assert mgr.complete_consent(IDENT, first.state_value, VERIFIER, CODE).ok


def test_wrong_verifier_with_bad_scopes_is_verifier_mismatch_and_burns_the_state() -> None:
    mgr = _mgr()
    res = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    got = mgr.complete_consent(IDENT, res.state_value, "w" * 43, CODE, ("drive",))
    assert got.code is ConsentCode.VERIFIER_MISMATCH
    again = mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE)
    assert again.code is ConsentCode.STATE_REPLAYED


def test_expired_state_with_bad_scopes_is_expired_not_a_scope_probe() -> None:
    now = {"t": T0}
    mgr = ConsentManager(lambda: now["t"], state_source=_states(), pending_ttl=timedelta(minutes=1))
    res = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    now["t"] = T0 + timedelta(minutes=2)
    got = mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE, ("drive",))
    assert got.code is ConsentCode.STATE_EXPIRED


def test_correct_verifier_with_bad_scopes_still_does_not_burn_the_state() -> None:
    mgr = _mgr()
    res = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE, ("drive",)).code is ConsentCode.SCOPE_REFUSED
    assert mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).ok


def test_token_source_is_called_outside_the_manager_lock() -> None:
    holder: dict[str, ConsentManager] = {}
    seen: list[bool] = []
    counter = itertools.count(1)

    def source() -> str:
        seen.append(holder["m"]._lock.locked())
        return f"FAKE-token-{next(counter):04d}"

    holder["m"] = ConsentManager(lambda: T0, store=FakeTokenStore(source), state_source=_states())
    _grant(holder["m"])
    assert seen == [False, False]


def test_two_threads_completing_the_same_state_yield_exactly_one_grant() -> None:
    mgr = _mgr()
    res = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    barrier = threading.Barrier(2)
    results: list[object] = []

    def worker() -> None:
        barrier.wait()
        results.append(mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.ok for r in results) == [False, True]
    assert {r.code for r in results} == {ConsentCode.OK, ConsentCode.STATE_REPLAYED}
    assert mgr.store.count() == 1


def test_read_methods_never_raise_even_when_internals_fail(monkeypatch) -> None:
    mgr = _mgr()
    _grant(mgr)

    def boom(*_a, **_k):
        raise RuntimeError("INTERNAL")

    monkeypatch.setattr(ConsentManager, "_expire_locked", boom)
    assert mgr.snapshot(IDENT) is None
    assert mgr.state_of(IDENT) is ConsentState.NEW
    assert mgr.scope_epoch(IDENT) is None
    assert mgr.is_authorized(IDENT, 0) is False
    assert mgr.consent_digest(IDENT) is None


def test_digest_never_raises_when_the_key_derivation_fails(monkeypatch) -> None:
    mgr = _mgr()
    _grant(mgr)

    def boom(*_a, **_k):
        raise RuntimeError("INTERNAL")

    monkeypatch.setattr(drive_oauth, "stable_key", boom)
    assert mgr.consent_digest(IDENT) is None


# ===================================================================================================
# drive_auth_state: adapters over the real components
# ===================================================================================================


def test_consent_manager_seam_maps_every_real_state() -> None:
    mgr = _mgr()
    seam = ConsentManagerSeam(mgr)
    assert seam.consent_state(IDENT) is AuthConsentState.NONE
    with pytest.raises(LookupError):
        seam.scope_epoch(IDENT)
    pending = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert seam.consent_state(IDENT) is AuthConsentState.NONE
    assert seam.token_status(IDENT) is TokenStatus.MISSING
    assert mgr.complete_consent(IDENT, pending.state_value, VERIFIER, CODE).ok
    assert seam.consent_state(IDENT) is AuthConsentState.GRANTED
    assert seam.token_status(IDENT) is TokenStatus.VALID
    assert seam.scope_epoch(IDENT) == 0 and seam.scope_check_ok(IDENT, 0) is True
    assert seam.scope_check_ok(IDENT, 1) is False
    assert seam.refresh_access_token(IDENT) is False  # the fake store has no refresh path
    mgr.mark_auth_required(IDENT)
    assert seam.consent_state(IDENT) is AuthConsentState.REVOKED
    assert seam.token_status(IDENT) is TokenStatus.MISSING
    mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert seam.consent_state(IDENT) is AuthConsentState.NONE


def test_consent_manager_seam_is_fail_closed_and_validates_its_input() -> None:
    with pytest.raises(ValueError, match="CONSENT_ADAPTER_CONFIG_INVALID"):
        ConsentManagerSeam(object())  # type: ignore[arg-type]
    seam = ConsentManagerSeam(_mgr())
    for bad in (None, "x", object(), 5):
        assert seam.consent_state(bad) is AuthConsentState.NONE
        assert seam.token_status(bad) is TokenStatus.MISSING
        assert seam.scope_check_ok(bad, 0) is False
        assert seam.refresh_access_token(bad) is False
        with pytest.raises(LookupError):
            seam.scope_epoch(bad)


def test_seam_methods_are_validated_when_the_health_object_is_built() -> None:
    class Partial:
        def consent_state(self, identity):
            return AuthConsentState.GRANTED

    for bad in (object(), Partial(), 5):
        with pytest.raises(ValueError, match="AUTH_HEALTH_SEAM_INVALID"):
            DriveAuthHealth(IDENT, 0, bad, SourceStateMachine(), FakeAlertSink())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="AUTH_HEALTH_SEAM_INVALID"):
        DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), object())  # type: ignore[arg-type]


async def _lease(living: InMemoryLiving) -> DriveLease:
    await living.enqueue_job(WORKER, DEFAULT_SCOPE, UUID(int=1), "drive", "a" * 64, "key-1")
    fence = await living.acquire_job(WORKER, DEFAULT_SCOPE, UUID(int=1), "w1", 300)
    return DriveLease(WORKER, DEFAULT_SCOPE, UUID(int=1), "w1", fence, 0)


async def _to_live(store: DriveCursorStore, lease: DriveLease, token: str) -> None:
    load = await store.initialize(IDENT, CORPUS, 0, lease)
    for state in (CursorState.BASELINING, CursorState.CATCHING_UP, CursorState.LIVE):
        res = await store.commit(IDENT, lease, load, load.record.evolve(state=state, token=token), [])
        assert res.ok, res
        load = await store.load(IDENT, CORPUS, 0, lease)
        assert load.usable and load.state is state


async def test_store_cursor_reader_reads_only_catching_up_or_live_tokens() -> None:
    living = InMemoryLiving()
    lease = await _lease(living)
    tracker = ResnapshotTracker()
    store = DriveCursorStore(living, tracker)
    reader = StoreCursorReader(store, CORPUS, lease, lambda: 0)
    assert await reader.committed_token(IDENT) is None  # missing cursor
    load = await store.initialize(IDENT, CORPUS, 0, lease)
    assert await reader.committed_token(IDENT) is None  # UNINITIALIZED
    await store.commit(IDENT, lease, load, load.record.evolve(state=CursorState.BASELINING, token="T1"), [])
    assert await reader.committed_token(IDENT) is None  # BASELINING token is a baseline token, not a cursor
    living2 = InMemoryLiving()
    lease2 = await _lease(living2)
    store2 = DriveCursorStore(living2, ResnapshotTracker())
    await _to_live(store2, lease2, "T1")
    assert await StoreCursorReader(store2, CORPUS, lease2, lambda: 0).committed_token(IDENT) == "T1"
    assert await StoreCursorReader(store2, CORPUS, lease2, lambda: 7).committed_token(IDENT) is None
    assert await StoreCursorReader(store2, CORPUS, lease2, lambda: 0).committed_token(None) is None


async def test_store_cursor_reader_never_raises_on_a_broken_store_or_epoch_source() -> None:
    class Broken:
        async def load(self, *a, **k):
            raise RuntimeError("DB https://x/?token=SECRET")

    def bad_epoch() -> int:
        raise RuntimeError("EPOCH")

    lease = await _lease(InMemoryLiving())
    assert await StoreCursorReader(Broken(), CORPUS, lease, lambda: 0).committed_token(IDENT) is None
    store = DriveCursorStore(InMemoryLiving(), ResnapshotTracker())
    assert await StoreCursorReader(store, CORPUS, lease, bad_epoch).committed_token(IDENT) is None
    with pytest.raises(ValueError, match="CURSOR_READER_CONFIG_INVALID"):
        StoreCursorReader(None, CORPUS, lease, lambda: 0)  # type: ignore[arg-type]


async def test_real_consent_manager_and_cursor_store_end_to_end_revoke_and_reconsent() -> None:
    mgr = _mgr()
    _grant(mgr)
    living = InMemoryLiving()
    lease = await _lease(living)
    tracker = ResnapshotTracker()
    store = DriveCursorStore(living, tracker)
    await _to_live(store, lease, "T1")
    fake = FakeDrivePort(scope_epoch=0)
    fake.script_page("T1", (_chg("c1", "F1"),), new_start_page_token="N1")
    sink = FakeAlertSink()
    machine = SourceStateMachine()
    health = DriveAuthHealth(IDENT, 0, ConsentManagerSeam(mgr), machine, sink)
    guard = AuthGuardedDrivePort(health, fake)
    reader = StoreCursorReader(store, CORPUS, lease, lambda: health.scope_epoch)
    key = cursor_key(IDENT)

    committed: list[str] = []
    res = await run_poll(health, guard, reader, lambda tok, page, ep: committed.append(tok))
    assert res.status is PollStatus.COMPLETE and committed == ["T1"] and fake.call_count == 1
    raw_before = (await living.get_cursor(WORKER, DEFAULT_SCOPE, key)).cursor_value

    assert mgr.revoke(IDENT).ok
    calls = fake.call_count
    res = await run_poll(health, guard, reader, lambda *a: committed.append("X"))
    assert res.status is PollStatus.AUTH_REQUIRED and res.error_code is DriveErrorCode.AUTH_REQUIRED
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    assert fake.call_count == calls and committed == ["T1"]
    assert (await living.get_cursor(WORKER, DEFAULT_SCOPE, key)).cursor_value == raw_before
    assert health.state is AuthState.AUTH_REQUIRED and machine.state is SourceState.PAUSED
    assert len(sink.alerts) == 1

    assert health.reconsent(1) is ReconsentResult.NO_CONSENT  # still revoked in the real manager
    pending = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert pending.scope_epoch == 1
    assert mgr.complete_consent(IDENT, pending.state_value, VERIFIER, CODE).ok
    assert health.reconsent(0) is ReconsentResult.EPOCH_NOT_NEW
    assert health.reconsent(1) is ReconsentResult.RECOVERED
    assert health.state is AuthState.HEALTHY and machine.state is SourceState.ACTIVE
    assert len(sink.alerts) == 1

    # the cursor was written under epoch 0: after the epoch moved it must be re-baselined, never polled
    fake.set_scope_epoch(1)
    res = await run_poll(health, guard, reader, lambda *a: committed.append("Y"))
    assert res.status is PollStatus.NO_CURSOR
    assert fake.call_count == calls and committed == ["T1"]
    assert tracker.is_required(key)
    assert (await living.get_cursor(WORKER, DEFAULT_SCOPE, key)).cursor_value == raw_before


# ===================================================================================================
# drive_auth_state: run_poll hardening
# ===================================================================================================


class _PagePort:
    def __init__(self, page: object) -> None:
        self.page = page
        self.calls = 0

    async def list_changes(self, identity, scope_epoch, page_token):
        self.calls += 1
        return self.page


@pytest.mark.parametrize("page", [None, object(), "page", {"changes": ()}, 5])
async def test_forged_page_never_raises_and_is_never_committed(page) -> None:
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    port = _PagePort(page)
    guard = AuthGuardedDrivePort(health, port)  # type: ignore[arg-type]
    got: list = []
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda *a: got.append(a))
    assert res.status is PollStatus.PAGE_INVALID and res.reason is PollReason.PAGE_TYPE_INVALID
    assert got == [] and port.calls == 1


async def test_forged_health_or_guard_never_raises() -> None:
    res = await run_poll(object(), object(), FakeCursorView("T1"), lambda *a: None)  # type: ignore[arg-type]
    assert res.status is PollStatus.PORT_ERROR and res.reason is PollReason.INTERNAL


async def test_repeated_page_token_stops_without_committing() -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (_chg("c1", "F1"),), next_page_token="T1")
    got: list = []
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda *a: got.append(a), max_pages=5)
    assert res.status is PollStatus.PAGE_INVALID and res.reason is PollReason.TOKEN_REPEATED
    assert len(got) <= 1 and fake.call_count <= 2 and res.pages_committed == len(got)


async def test_regressed_page_token_stops_without_committing_the_offending_page() -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (_chg("c1", "F1"),), next_page_token="T2")
    fake.script_page("T2", (_chg("c2", "F2"),), next_page_token="T1")
    got: list = []
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda tok, *a: got.append(tok), max_pages=5)
    assert res.status is PollStatus.PAGE_INVALID and res.reason is PollReason.TOKEN_REGRESSED
    assert got == ["T1"] and fake.call_count == 2 and res.pages_committed == 1


async def test_terminal_new_start_token_not_newer_than_committed_is_not_complete() -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (), new_start_page_token="T1")
    got: list = []
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda *a: got.append(a))
    assert res.status is PollStatus.PAGE_INVALID and res.reason is PollReason.START_TOKEN_ORDER
    assert got == [] and res.final_token is None
    fake2, _s2, _k2, _m2, health2, guard2 = _build()
    fake2.script_page("T1", (), next_page_token="T2")
    fake2.script_page("T2", (), new_start_page_token="T1")
    got2: list = []
    res2 = await run_poll(health2, guard2, FakeCursorView("T1"), lambda tok, *a: got2.append(tok))
    assert res2.status is PollStatus.PAGE_INVALID and res2.reason is PollReason.START_TOKEN_ORDER
    assert got2 == ["T1"] and res2.final_token is None


@dataclass
class _Result:
    ok: object
    reason: object = None


@pytest.mark.parametrize("returned", [False, True, 0, 1, "ok", [], {}, object(), _Result(False), _Result(1), _Result("yes")])
async def test_a_commit_callback_returning_anything_but_none_or_success_is_commit_failed(returned) -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (), new_start_page_token="N1")
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda *a: returned)
    assert res.status is PollStatus.COMMIT_FAILED and res.pages_committed == 0
    assert res.reason is PollReason.COMMIT_REJECTED


async def test_commit_rejection_surfaces_the_fixed_store_reason_code() -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (), new_start_page_token="N1")
    rejected = StoreCommit(False, False, None, CursorReason.LEASE_LOST)

    async def commit(*_a):
        return rejected

    res = await run_poll(health, guard, FakeCursorView("T1"), commit)
    assert res.status is PollStatus.COMMIT_FAILED and res.commit_reason == "LEASE_LOST"
    assert "SECRET" not in repr(res)


async def test_commit_callback_raising_has_a_fixed_reason_and_no_echo() -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (), new_start_page_token="N1")

    def boom(*_a):
        raise RuntimeError("ya29.SECRET")

    res = await run_poll(health, guard, FakeCursorView("T1"), boom)
    assert res.status is PollStatus.COMMIT_FAILED and res.reason is PollReason.COMMIT_RAISED
    assert "SECRET" not in repr(res)


async def test_explicit_commit_success_objects_complete_the_poll() -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (), next_page_token="T2")
    fake.script_page("T2", (), new_start_page_token="N1")
    ok = StoreCommit(True, False, 1, None)

    async def commit(*_a):
        return ok

    res = await run_poll(health, guard, FakeCursorView("T1"), commit)
    assert res.status is PollStatus.COMPLETE and res.pages_committed == 2 and res.final_token == "N1"
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda *a: ok)
    assert res.status is PollStatus.COMPLETE


async def test_async_cursor_view_is_supported() -> None:
    fake, _s, _k, _m, health, guard = _build()
    fake.script_page("T1", (), new_start_page_token="N1")

    class AsyncView:
        async def committed_token(self, identity):
            return "T1"

    res = await run_poll(health, guard, AsyncView(), lambda *a: None)  # type: ignore[arg-type]
    assert res.status is PollStatus.COMPLETE


# ===================================================================================================
# drive_auth_state: alerts, refresh, channels, construction
# ===================================================================================================


def test_two_health_instances_for_one_identity_each_emit_their_own_alert() -> None:
    sink = FakeAlertSink()
    for _ in range(2):
        health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), sink)
        health.notify_revoked()
    assert len(sink.alerts) == 2
    assert sink.alerts[0].dedup_key != sink.alerts[1].dedup_key


def test_dedup_key_covers_the_scope_epoch() -> None:
    seam = FakeAuthSeam()
    sink = FakeAlertSink()
    health = DriveAuthHealth(IDENT, 0, seam, SourceStateMachine(), sink)
    health.notify_revoked()
    seam.regrant(1)
    assert health.reconsent(1) is ReconsentResult.RECOVERED
    health.notify_revoked()
    keys = [a.dedup_key for a in sink.alerts]
    assert len(set(keys)) == 2 and all(1 in k or 0 in k for k in keys)


async def test_failed_alert_delivery_is_retried_by_flush_exactly_once() -> None:
    _f, seam, sink, _m, health, guard = _build()
    sink.fail = True
    seam.revoke()
    with pytest.raises(DrivePortError):
        await guard.get_start_page_token(IDENT, 0)
    assert sink.alerts == () and health.alert_failures == 1
    assert health.flush_alerts() == 0  # sink still down: nothing delivered, nothing lost
    sink.fail = False
    assert health.flush_alerts() == 1
    assert len(sink.alerts) == 1
    assert health.flush_alerts() == 0 and len(sink.alerts) == 1
    assert len(health.alerts) == 1


async def test_failed_alert_is_re_emitted_on_the_next_guarded_call() -> None:
    _f, seam, sink, _m, _health, guard = _build()
    sink.fail = True
    seam.revoke()
    with pytest.raises(DrivePortError):
        await guard.get_start_page_token(IDENT, 0)
    sink.fail = False
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    assert len(sink.alerts) == 1


async def test_transient_seam_fault_during_401_refresh_does_not_escalate() -> None:
    fake, seam, sink, machine, health, guard = _build()
    fake.force_provider_response("get_start_page_token", 401)
    fake.run_after_calls(1, lambda _f: setattr(seam, "fault", True))
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.TRANSIENT
    assert health.state is AuthState.HEALTHY and sink.alerts == () and machine.state is SourceState.ACTIVE


async def test_refresh_fault_after_expiry_during_401_does_not_escalate() -> None:
    class RefreshFault(FakeAuthSeam):
        def refresh_access_token(self, identity):
            raise RuntimeError("SEAM_DOWN")

    seam = RefreshFault()
    fake, _s, sink, machine, health, guard = _build(seam=seam)
    fake.force_provider_response("get_start_page_token", 401)
    fake.run_after_calls(1, lambda _f: seam.expire_token(refreshable=True))
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.TRANSIENT
    assert health.state is AuthState.HEALTHY and sink.alerts == () and machine.state is SourceState.ACTIVE


async def test_persistent_401_after_a_successful_refresh_is_one_access_rejected_alert() -> None:
    fake, seam, sink, _m, health, guard = _build()
    fake.force_provider_response("get_start_page_token", 401, times=2)
    fake.run_after_calls(1, lambda _f: seam.expire_token(refreshable=True))
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    assert health.refresh_count == 1 and seam.refresh_calls == 1
    assert fake.count("get_start_page_token") == 2
    assert health.cause is AuthCause.ACCESS_REJECTED and len(sink.alerts) == 1


async def test_repeated_reconsents_do_not_permanently_block_channel_registration() -> None:
    _f, seam, _s, _m, health, _g = _build()
    intake = HintIntake(health)
    for i in range(64):
        assert intake.register_channel(f"C{i}", "R", "T")
    assert intake.register_channel("OVER", "R", "T") is False  # same epoch: still bounded
    health.notify_revoked()
    seam.regrant(1)
    assert health.reconsent(1) is ReconsentResult.RECOVERED
    assert intake.register_channel("NEW", "RES", "TOK") is True  # older-epoch channels were evicted
    assert intake.accept_hint("NEW", "RES", "TOK") is HintResult.ACCEPTED_NEW_JOB
    assert intake.accept_hint("C0", "R", "T") is HintResult.REJECTED_FOREIGN


def test_construction_over_a_revoked_or_moved_seam_starts_auth_required() -> None:
    seam = FakeAuthSeam()
    seam.revoke()
    sink = FakeAlertSink()
    machine = SourceStateMachine()
    health = DriveAuthHealth(IDENT, 0, seam, machine, sink)
    assert health.state is AuthState.AUTH_REQUIRED and health.cause is AuthCause.CONSENT_REVOKED
    assert len(sink.alerts) == 1 and machine.state is SourceState.PAUSED
    moved = FakeAuthSeam(scope_epoch=3)
    assert DriveAuthHealth(IDENT, 0, moved, SourceStateMachine(), FakeAlertSink()).state is AuthState.AUTH_REQUIRED


def test_construction_over_a_faulty_seam_stays_healthy_and_quiet() -> None:
    seam = FakeAuthSeam()
    seam.fault = True
    sink = FakeAlertSink()
    health = DriveAuthHealth(IDENT, 0, seam, SourceStateMachine(), sink)
    assert health.state is AuthState.HEALTHY and sink.alerts == ()


def test_public_failure_paths_never_raise_when_the_machine_or_sink_misbehave() -> None:
    class BadMachine(SourceStateMachine):
        def pause(self, reason):
            raise RuntimeError("MACHINE")

    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), BadMachine(), FakeAlertSink())
    health.notify_revoked()
    assert health.state is AuthState.AUTH_REQUIRED
