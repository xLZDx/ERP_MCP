"""S7 GPT-PM gate remediation (stream H1): M01 forged identity, M04 state reissue after eviction, M08
poll COMPLETE without a durable commit acknowledgment, M10 concurrent hint consumers.

Every test here fails against the pre-fix code for the stated reason (see the finding id in the name).
"""
from __future__ import annotations

import itertools
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from business_ai_gateway.phase2.drive_auth_state import (
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
    StoreCursorReader,
    run_poll,
)
from business_ai_gateway.phase2.drive_auth_state import ConsentState as AuthConsentState
from business_ai_gateway.phase2.drive_changes import DriveChange, DriveChangeKind
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_oauth import ConsentCode, ConsentManager, ConsentState
from business_ai_gateway.phase2.drive_port import DriveErrorCode, DrivePortError, DrivePortIdentity
from business_ai_gateway.phase2.scheduler import SourceStateMachine

VICTIM = DrivePortIdentity("account:acc-1", "tenant-victim", "conn-1")
IDENT = DrivePortIdentity("account:acc-1", "A", "conn-1")
VERIFIER = "v" * 43
CODE = "FAKE-CODE-1"
NARROW = ("drive.file",)
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class Liar(str):
    """A str subclass that equals everything and hashes like a chosen target (a forged key part)."""

    _target_hash = 0

    def __new__(cls, value: str, hash_like: str):
        obj = str.__new__(cls, value)
        obj._target_hash = hash(hash_like)
        return obj

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    def __hash__(self) -> int:
        return self._target_hash


def _forged_like(target: DrivePortIdentity, *, shell: bool = True) -> DrivePortIdentity:
    """An identity whose three fields lie: they hash and compare like ``target`` but are str subclasses."""
    obj = object.__new__(DrivePortIdentity)
    object.__setattr__(obj, "namespace", Liar("account:attacker", target.namespace))
    object.__setattr__(obj, "tenant", Liar("tenant-attacker", target.tenant))
    object.__setattr__(obj, "connection_id", Liar("conn-attacker", target.connection_id))
    return obj


def _forged_variants(target: DrivePortIdentity) -> list[DrivePortIdentity]:
    out = [_forged_like(target)]
    for lying in ("namespace", "tenant", "connection_id"):  # only one lying field, the rest honest
        obj = object.__new__(DrivePortIdentity)
        for name in ("namespace", "tenant", "connection_id"):
            value = getattr(target, name)
            object.__setattr__(obj, name, Liar(value, value) if name == lying else value)
        out.append(obj)
    out.append(object.__new__(DrivePortIdentity))  # unset slots
    return out


def _states():
    counter = itertools.count(1)
    return lambda: f"STATE-{next(counter):016d}"


def _mgr(**kw) -> ConsentManager:
    kw.setdefault("state_source", _states())
    return ConsentManager(lambda: T0, **kw)


def _grant(mgr: ConsentManager, ident: DrivePortIdentity) -> int:
    res = mgr.begin_consent(ident, NARROW, VERIFIER)
    assert res.ok, res
    done = mgr.complete_consent(ident, res.state_value, VERIFIER, CODE)
    assert done.ok
    return done.scope_epoch


# ===================================================================================================
# M01 forged identity
# ===================================================================================================


def test_m01_forged_identity_cannot_read_or_revoke_another_grant() -> None:
    mgr = _mgr()
    epoch = _grant(mgr, VICTIM)
    for forged in _forged_variants(VICTIM):
        assert mgr.revoke(forged).code is ConsentCode.IDENTITY_INVALID
        assert mgr.mark_auth_required(forged).code is ConsentCode.IDENTITY_INVALID
        assert mgr.snapshot(forged) is None
        assert mgr.state_of(forged) is ConsentState.NEW
        assert mgr.scope_epoch(forged) is None
        assert mgr.is_authorized(forged, epoch) is False
        assert mgr.consent_digest(forged) is None
        assert mgr.store.has_tokens(forged) is False
        assert mgr.begin_consent(forged, NARROW, VERIFIER).code is ConsentCode.IDENTITY_INVALID
        assert (
            mgr.complete_consent(forged, "STATE-0000000000000099", VERIFIER, CODE).code
            is ConsentCode.IDENTITY_INVALID
        )
    # the victim's grant is untouched
    assert mgr.state_of(VICTIM) is ConsentState.GRANTED
    assert mgr.is_authorized(VICTIM, epoch) is True
    assert mgr.store.has_tokens(VICTIM)


def test_m01_forged_identity_cannot_complete_a_victim_pending_state() -> None:
    mgr = _mgr()
    begin = mgr.begin_consent(VICTIM, NARROW, VERIFIER)
    assert begin.ok
    forged = _forged_like(VICTIM)
    assert mgr.complete_consent(forged, begin.state_value, VERIFIER, CODE).code is ConsentCode.IDENTITY_INVALID
    assert mgr.state_of(VICTIM) is ConsentState.CONSENT_PENDING
    assert mgr.complete_consent(VICTIM, begin.state_value, VERIFIER, CODE).ok


def test_m01_seam_refuses_forged_identity() -> None:
    mgr = _mgr()
    _grant(mgr, VICTIM)
    seam = ConsentManagerSeam(mgr)
    for forged in _forged_variants(VICTIM):
        assert seam.consent_state(forged) is AuthConsentState.NONE
        assert seam.token_status(forged).value == "MISSING"
        assert seam.scope_check_ok(forged, 0) is False
        with pytest.raises(LookupError):
            seam.scope_epoch(forged)
    assert seam.consent_state(VICTIM) is AuthConsentState.GRANTED


def test_m01_health_constructor_rejects_forged_identity() -> None:
    for forged in _forged_variants(IDENT):
        with pytest.raises(ValueError, match="AUTH_HEALTH_IDENTITY_INVALID"):
            DriveAuthHealth(forged, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())


def test_m01_health_identity_is_a_plain_validated_copy() -> None:
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    got = health.identity
    assert type(got) is DrivePortIdentity
    assert type(got.namespace) is str and type(got.tenant) is str and type(got.connection_id) is str
    assert got == IDENT


async def test_m01_guarded_port_refuses_forged_identity_with_zero_inner_calls() -> None:
    fake = FakeDrivePort(scope_epoch=0)
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    guard = AuthGuardedDrivePort(health, fake)
    for forged in _forged_variants(IDENT):
        with pytest.raises(DrivePortError) as err:
            await guard.get_start_page_token(forged, 0)
        assert err.value.code is DriveErrorCode.AUTH_REQUIRED
        with pytest.raises(DrivePortError):
            await guard.list_changes(forged, 0, "START-1")
        with pytest.raises(DrivePortError):
            await guard.get_file_meta(forged, 0, "F1")
        with pytest.raises(DrivePortError):
            await guard.list_revisions(forged, 0, "F1")
    assert fake.call_count == 0
    assert health.state is AuthState.HEALTHY  # a forged caller cannot push the real connection into AUTH_REQUIRED


async def test_m01_cursor_reader_refuses_forged_identity() -> None:
    loads: list[object] = []

    class Store:
        async def load(self, identity, corpus, epoch, lease):
            loads.append(identity)

    reader = StoreCursorReader(Store(), object(), object(), lambda: 0)
    for forged in _forged_variants(IDENT):
        assert await reader.committed_token(forged) is None
    assert loads == []


def test_m01_hint_registry_refuses_lying_str_fields() -> None:
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    intake = HintIntake(health)
    assert intake.register_channel("chan-1", "res-1", "tok-1")
    assert intake.register_channel(Liar("chan-2", "chan-1"), "res-2", "tok-2") is False
    assert intake.accept_hint(Liar("chan-1", "chan-1"), "res-1", "tok-1") is HintResult.REJECTED_INVALID
    assert intake.accept_hint("chan-1", Liar("other", "res-1"), "tok-1") is HintResult.REJECTED_INVALID
    assert intake.accept_hint("chan-1", "res-1", Liar("other", "tok-1")) is HintResult.REJECTED_INVALID
    assert intake.pending_jobs == 0
    assert intake.accept_hint("chan-1", "res-1", "tok-1") is HintResult.ACCEPTED_NEW_JOB


# ===================================================================================================
# M04 evicted state reissue
# ===================================================================================================


def _repeating(values: list[str]):
    it = iter(values)
    last = values[-1]

    def source() -> str:
        return next(it, last)

    return source


S1 = "STATE-0000000000000001"
S2 = "STATE-0000000000000002"


def test_m04_repeated_state_after_eviction_is_not_reissued_and_old_callback_is_dead() -> None:
    mgr = _mgr(max_states_per_identity=1, state_source=_repeating([S1, S1, S1, S1, S1]))
    first = mgr.begin_consent(VICTIM, NARROW, VERIFIER)
    assert first.ok and first.state_value == S1
    assert mgr.complete_consent(VICTIM, S1, VERIFIER, CODE).ok  # S1 consumed
    assert mgr.revoke(VICTIM).ok
    epoch = mgr.scope_epoch(VICTIM)
    # the bounded retention evicts S1; the generator now repeats it
    again = mgr.begin_consent(VICTIM, NARROW, VERIFIER)
    assert again.ok is False and again.code is ConsentCode.STATE_SOURCE_INVALID
    assert again.state_value is None
    # the old callback (same state, same verifier) must not grant anything
    replay = mgr.complete_consent(VICTIM, S1, VERIFIER, CODE)
    assert replay.ok is False
    assert mgr.state_of(VICTIM) is ConsentState.REVOKED
    assert mgr.store.has_tokens(VICTIM) is False
    assert mgr.scope_epoch(VICTIM) == epoch


def test_m04_repeated_value_is_skipped_and_the_next_fresh_value_is_used() -> None:
    mgr = _mgr(max_states_per_identity=1, state_source=_repeating([S1, S1, S2]))
    assert mgr.begin_consent(VICTIM, NARROW, VERIFIER).state_value == S1
    assert mgr.complete_consent(VICTIM, S1, VERIFIER, CODE).ok
    assert mgr.revoke(VICTIM).ok
    nxt = mgr.begin_consent(VICTIM, NARROW, VERIFIER)
    assert nxt.ok and nxt.state_value == S2
    assert mgr.complete_consent(VICTIM, S1, VERIFIER, CODE).ok is False
    assert mgr.state_of(VICTIM) is ConsentState.CONSENT_PENDING


def test_m04_repeat_across_identities_is_refused_after_global_eviction() -> None:
    mgr = _mgr(max_states=1, state_source=_repeating([S1, S1, S1, S1]))
    assert mgr.begin_consent(VICTIM, NARROW, VERIFIER).state_value == S1
    assert mgr.complete_consent(VICTIM, S1, VERIFIER, CODE).ok
    other = mgr.begin_consent(IDENT, NARROW, VERIFIER)  # S1 evicted by the global bound, generator repeats
    assert other.ok is False and other.code is ConsentCode.STATE_SOURCE_INVALID
    assert mgr.complete_consent(IDENT, S1, VERIFIER, CODE).ok is False


def test_m04_issued_digest_set_is_bounded_and_fails_closed() -> None:
    mgr = _mgr(max_issued_states=3)
    for _ in range(3):
        assert mgr.begin_consent(VICTIM, NARROW, VERIFIER).ok
    full = mgr.begin_consent(VICTIM, NARROW, VERIFIER)
    assert full.ok is False and full.code is ConsentCode.CAPACITY
    assert mgr.begin_consent(IDENT, NARROW, VERIFIER).code is ConsentCode.CAPACITY
    assert mgr.snapshot(IDENT) is None  # no record allocated by the refusal


def test_m04_invalid_issued_bound_is_a_config_error() -> None:
    for bad in (0, -1, True, "5", 1.5):
        with pytest.raises(ValueError):
            _mgr(max_issued_states=bad)


# ===================================================================================================
# M08 explicit commit acknowledgment
# ===================================================================================================


def _chg(cid: str, fid: str) -> DriveChange:
    return DriveChange(cid, fid, "r1", DriveChangeKind.UPSERT)


def _build():
    fake = FakeDrivePort(scope_epoch=0)
    fake.script_page("T1", (_chg("c1", "F1"),), new_start_page_token="N1")
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    return fake, health, AuthGuardedDrivePort(health, fake)


async def test_m08_noop_commit_returning_none_is_not_complete_and_cursor_unchanged() -> None:
    _fake, health, guard = _build()
    cursor = FakeCursorView("T1")
    res = await run_poll(health, guard, cursor, lambda *a: None)
    assert res.status is PollStatus.COMMIT_FAILED and res.reason is PollReason.COMMIT_REJECTED
    assert res.pages_committed == 0 and res.final_token is None
    assert cursor.token == "T1" and cursor.commits == 0


@dataclass(frozen=True)
class _Ack:
    ok: object


@pytest.mark.parametrize("value", [None, False, 0, 1, "ok", "True", b"", object(), _Ack(1), _Ack("yes"), _Ack(None)])
async def test_m08_anything_but_an_explicit_ack_is_commit_failed(value: object) -> None:
    _fake, health, guard = _build()
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda *a: value)
    assert res.status is PollStatus.COMMIT_FAILED and res.pages_committed == 0


async def test_m08_async_noop_commit_is_not_complete() -> None:
    _fake, health, guard = _build()

    async def commit(token, page, epoch):
        return None

    res = await run_poll(health, guard, FakeCursorView("T1"), commit)
    assert res.status is PollStatus.COMMIT_FAILED


@pytest.mark.parametrize("value", [True, _Ack(True)])
async def test_m08_explicit_ack_completes(value: object) -> None:
    _fake, health, guard = _build()
    res = await run_poll(health, guard, FakeCursorView("T1"), lambda *a: value)
    assert res.status is PollStatus.COMPLETE and res.pages_committed == 1 and res.final_token == "N1"


async def test_m08_explicit_async_ack_completes() -> None:
    _fake, health, guard = _build()

    async def commit(token, page, epoch):
        return _Ack(True)

    res = await run_poll(health, guard, FakeCursorView("T1"), commit)
    assert res.status is PollStatus.COMPLETE


# ===================================================================================================
# M10 atomic hint consumption
# ===================================================================================================


def _intake() -> HintIntake:
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    intake = HintIntake(health)
    assert intake.register_channel("chan-1", "res-1", "tok-1")
    return intake


class _SlowFlagIntake(HintIntake):
    """Widens the check-then-clear window: reading ``_pending`` yields the GIL (a lost-update window)."""

    @property
    def _pending(self) -> bool:  # type: ignore[override]
        value = self.__dict__.get("_p", False)
        time.sleep(0.02)
        return value

    @_pending.setter
    def _pending(self, value: bool) -> None:
        self.__dict__["_p"] = value


def _slow_intake() -> _SlowFlagIntake:
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    intake = _SlowFlagIntake(health)
    assert intake.register_channel("chan-1", "res-1", "tok-1")
    return intake


def _race(n: int, fn) -> list:
    barrier = threading.Barrier(n)
    out: list = [None] * n

    def worker(i: int) -> None:
        barrier.wait()
        out[i] = fn()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_m10_widened_window_n_consumers_get_exactly_one_job() -> None:
    intake = _slow_intake()
    assert intake.accept_hint("chan-1", "res-1", "tok-1") is HintResult.ACCEPTED_NEW_JOB
    jobs = [j for j in _race(8, intake.take_poll_job) if j is not None]
    assert len(jobs) == 1
    assert intake.pending_jobs == 0 and intake.accepted_count == 1


def test_m10_widened_window_concurrent_hints_create_one_job_and_consistent_counters() -> None:
    intake = _slow_intake()
    results = _race(8, lambda: intake.accept_hint("chan-1", "res-1", "tok-1"))
    assert results.count(HintResult.ACCEPTED_NEW_JOB) == 1
    assert results.count(HintResult.ACCEPTED_COLLAPSED) == 7
    assert intake.accepted_count == 1 and intake.collapsed_count == 7
    assert len(_race(8, intake.take_poll_job)) == 8


def test_m10_real_threads_consumers_one_job_per_hint() -> None:
    intake = _intake()
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for _ in range(200):
            assert intake.accept_hint("chan-1", "res-1", "tok-1") is HintResult.ACCEPTED_NEW_JOB
            jobs = [j for j in _race(8, intake.take_poll_job) if j is not None]
            assert len(jobs) == 1
    finally:
        sys.setswitchinterval(old)
    assert intake.accepted_count == 200 and intake.collapsed_count == 0 and intake.pending_jobs == 0


def test_m10_stress_producers_and_consumers_never_duplicate_a_job() -> None:
    intake = _intake()
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    stop = threading.Event()
    taken: list[int] = []
    lock = threading.Lock()
    per_producer = 300
    producers_n = 4

    def producer() -> None:
        for _ in range(per_producer):
            intake.accept_hint("chan-1", "res-1", "tok-1")

    def consumer() -> None:
        mine = 0
        while not stop.is_set():
            if intake.take_poll_job() is not None:
                mine += 1
        with lock:
            taken.append(mine)

    try:
        consumers = [threading.Thread(target=consumer) for _ in range(4)]
        producers = [threading.Thread(target=producer) for _ in range(producers_n)]
        for t in consumers + producers:
            t.start()
        for t in producers:
            t.join()
        stop.set()
        for t in consumers:
            t.join()
    finally:
        sys.setswitchinterval(old)
    leftover = intake.pending_jobs
    # every ACCEPTED_NEW_JOB is consumed exactly once (or is still pending); every other hint collapsed
    assert sum(taken) + leftover == intake.accepted_count
    assert intake.accepted_count + intake.collapsed_count == per_producer * producers_n
