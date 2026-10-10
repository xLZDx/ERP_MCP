"""S7/E4: Drive auth-health state machine (TC112), revoke/expiry race, S6b lesson rows. Pure, no I/O."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import drive_auth_state
from business_ai_gateway.phase2.drive_auth_state import (
    AuthAlert,
    AuthCause,
    AuthGuardedDrivePort,
    AuthState,
    ConsentState,
    DriveAuthHealth,
    FakeAlertSink,
    FakeAuthSeam,
    FakeCursorView,
    PollStatus,
    ReconsentResult,
    TokenStatus,
    run_poll,
)
from business_ai_gateway.phase2.drive_changes import DriveChange, DriveChangeKind
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_port import (
    DriveErrorCode,
    DrivePortError,
    DrivePortIdentity,
)
from business_ai_gateway.phase2.scheduler import SourceState, SourceStateMachine

IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
SECRET = "ya29.SECRET-provider-text"


class IntSub(int):
    pass


class StrSub(str):
    def __eq__(self, other: object) -> bool:  # hostile
        return True

    __hash__ = str.__hash__


def _chg(cid: str, fid: str) -> DriveChange:
    return DriveChange(cid, fid, "r1", DriveChangeKind.UPSERT)


def _build(epoch: int = 0, machine: SourceStateMachine | None = None):
    fake = FakeDrivePort(scope_epoch=epoch)
    seam = FakeAuthSeam(scope_epoch=epoch)
    sink = FakeAlertSink()
    machine = machine or SourceStateMachine()
    health = DriveAuthHealth(IDENT, epoch, seam, machine, sink)
    guard = AuthGuardedDrivePort(health, fake)
    return fake, seam, sink, machine, health, guard


async def _all_methods_blocked(guard, health, fake) -> None:
    before = fake.call_count
    ep = health.scope_epoch
    for coro in (
        guard.get_start_page_token(IDENT, ep),
        guard.list_changes(IDENT, ep, "T1"),
        guard.get_file_meta(IDENT, ep, "F1"),
        guard.list_revisions(IDENT, ep, "F1"),
    ):
        with pytest.raises(DrivePortError) as ei:
            await coro
        assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
        assert str(ei.value) == "AUTH_REQUIRED"
    assert fake.call_count == before  # ZERO inner calls


# --- TC112: three distinct results ------------------------------------------------------------


async def test_healthy_call_passes_through() -> None:
    fake, _seam, sink, _m, health, guard = _build()
    token = await guard.get_start_page_token(IDENT, 0)
    assert token.token == "START-1" and fake.call_log == ("get_start_page_token",)
    assert health.state is AuthState.HEALTHY and sink.alerts == ()


async def test_expired_but_refreshable_refreshes_and_continues() -> None:
    _fake, seam, sink, machine, health, guard = _build()
    seam.expire_token(refreshable=True)
    token = await guard.get_start_page_token(IDENT, 0)
    assert token.token == "START-1"
    assert seam.refresh_calls == 1 and health.refresh_count == 1
    assert health.state is AuthState.HEALTHY and health.cause is None
    assert sink.alerts == () and machine.state is SourceState.ACTIVE


async def test_expired_not_refreshable_is_invalid_grant_auth_required() -> None:
    fake, seam, sink, machine, health, guard = _build()
    seam.expire_token(refreshable=False)
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    assert fake.call_count == 0
    assert health.state is AuthState.AUTH_REQUIRED and health.cause is AuthCause.INVALID_GRANT
    assert machine.state is SourceState.PAUSED and machine.pause_count == 1
    assert len(sink.alerts) == 1 and sink.alerts[0].cause is AuthCause.INVALID_GRANT


async def test_port_invalid_grant_moves_to_auth_required_and_blocks_everything() -> None:
    fake, _seam, sink, machine, health, guard = _build()
    fake.force_provider_response("list_changes", 400, f"invalid_grant {SECRET}")
    cursor = FakeCursorView("T1")
    with pytest.raises(DrivePortError) as ei:
        await guard.list_changes(IDENT, 0, "T1")
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    assert SECRET not in str(ei.value) and SECRET not in repr(ei.value)
    assert health.cause is AuthCause.INVALID_GRANT and machine.state is SourceState.PAUSED
    assert len(sink.alerts) == 1
    await _all_methods_blocked(guard, health, fake)
    assert cursor.commits == 0 and cursor.token == "T1"  # cursor untouched
    assert len(sink.alerts) == 1  # blocked calls do not re-alert


async def test_revoked_consent_is_a_distinct_cause() -> None:
    fake, seam, sink, machine, health, guard = _build()
    seam.revoke()
    with pytest.raises(DrivePortError) as ei:
        await guard.get_file_meta(IDENT, 0, "F1")
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED and fake.call_count == 0
    assert health.cause is AuthCause.CONSENT_REVOKED
    assert [a.cause for a in sink.alerts] == [AuthCause.CONSENT_REVOKED]
    assert machine.state is SourceState.PAUSED
    await _all_methods_blocked(guard, health, fake)


def test_three_results_are_three_different_values() -> None:
    assert AuthCause.INVALID_GRANT is not AuthCause.CONSENT_REVOKED
    assert {c.value for c in AuthCause} >= {"INVALID_GRANT", "CONSENT_REVOKED"}
    assert TokenStatus.EXPIRED_REFRESHABLE not in {c for c in AuthCause}  # expiry is not an auth cause


async def test_provider_401_with_refreshable_token_refreshes_and_retries() -> None:
    fake, seam, sink, _m, health, guard = _build()
    fake.force_provider_response("get_start_page_token", 401)
    seam.token = TokenStatus.VALID
    # token looks valid at preflight, expires before the provider answers 401
    fake.run_after_calls(1, lambda _f: seam.expire_token(refreshable=True))
    token = await guard.get_start_page_token(IDENT, 0)
    assert token.token == "START-1" and fake.count("get_start_page_token") == 2
    assert health.state is AuthState.HEALTHY and sink.alerts == ()


async def test_provider_401_without_refresh_is_access_rejected() -> None:
    fake, _seam, sink, _m, health, guard = _build()
    fake.force_provider_response("get_start_page_token", 401, SECRET)
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    assert health.cause is AuthCause.ACCESS_REJECTED and len(sink.alerts) == 1


@pytest.mark.parametrize("status,code", [(429, DriveErrorCode.RATE_LIMITED), (404, DriveErrorCode.NOT_FOUND)])
async def test_other_provider_errors_pass_through_without_transition(status, code) -> None:
    fake, _seam, sink, machine, health, guard = _build()
    fake.force_provider_response("get_file_meta", status, SECRET)
    with pytest.raises(DrivePortError) as ei:
        await guard.get_file_meta(IDENT, 0, "F1")
    assert ei.value.code is code and SECRET not in str(ei.value)
    assert health.state is AuthState.HEALTHY and sink.alerts == () and machine.state is SourceState.ACTIVE


class _ExplodingPort:
    async def get_start_page_token(self, identity, scope_epoch):
        raise RuntimeError(f"boom {SECRET}")


async def test_foreign_exception_from_inner_port_is_transient_and_not_echoed() -> None:
    seam, sink = FakeAuthSeam(), FakeAlertSink()
    health = DriveAuthHealth(IDENT, 0, seam, SourceStateMachine(), sink)
    guard = AuthGuardedDrivePort(health, _ExplodingPort())
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.TRANSIENT
    assert SECRET not in str(ei.value) and ei.value.__cause__ is None and ei.value.__suppress_context__
    assert health.state is AuthState.HEALTHY


# --- dedup, alert content ---------------------------------------------------------------------


async def test_exactly_one_alert_per_transition_even_with_repeated_failures() -> None:
    _fake, seam, sink, machine, health, guard = _build()
    seam.revoke()
    for _ in range(3):
        with pytest.raises(DrivePortError):
            await guard.get_start_page_token(IDENT, 0)
    health.notify_revoked()
    health.record_failure(AuthCause.INVALID_GRANT)
    assert len(sink.alerts) == 1 and len(health.alerts) == 1
    assert machine.pause_count == 1


async def test_alert_record_has_only_fixed_fields() -> None:
    _f, seam, sink, _m, _h, guard = _build()
    seam.revoke()
    with pytest.raises(DrivePortError):
        await guard.get_start_page_token(IDENT, 0)
    alert = sink.alerts[0]
    assert alert == AuthAlert("tenant-1", "conn-1", AuthCause.CONSENT_REVOKED, 0, 1)
    text = repr(alert)
    assert "ya29" not in text and "token" not in text.lower().replace("transition", "")
    assert set(AuthAlert.__slots__) == {"tenant", "connection_id", "cause", "scope_epoch", "transition_no"}


async def test_sink_failure_does_not_open_the_gate() -> None:
    fake, seam, sink, _m, health, guard = _build()
    sink.fail = True
    seam.revoke()
    with pytest.raises(DrivePortError):
        await guard.get_start_page_token(IDENT, 0)
    assert health.state is AuthState.AUTH_REQUIRED and health.alert_failures == 1
    assert len(health.alerts) == 1 and sink.alerts == ()
    await _all_methods_blocked(guard, health, fake)


# --- fail closed on hostile input / faulty seam -------------------------------------------------


async def test_hostile_identity_and_epoch_never_raise_anything_but_fixed_codes() -> None:
    fake, _seam, sink, _m, health, guard = _build()
    for ident in (None, "x", object(), StrSub("account:acc-1"), (IDENT,)):
        with pytest.raises(DrivePortError) as ei:
            await guard.get_start_page_token(ident, 0)
        assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    other = DrivePortIdentity("account:acc-1", "tenant-1", "conn-2")
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(other, 0)
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED
    for ep in (None, "0", True, IntSub(0), -1, 2**70, 1, 0.0, object()):
        with pytest.raises(DrivePortError) as ei:
            await guard.get_start_page_token(IDENT, ep)
        assert ei.value.code is DriveErrorCode.SCOPE_EPOCH_STALE
    assert fake.call_count == 0 and health.state is AuthState.HEALTHY and sink.alerts == ()


async def test_hostile_ids_to_inner_port_never_raise_raw() -> None:
    _f, _s, _k, _m, health, guard = _build()
    for bad in (None, "", "a\x00b", "x" * 5000, StrSub("F1"), 7):
        with pytest.raises(DrivePortError) as ei:
            await guard.get_file_meta(IDENT, 0, bad)
        assert ei.value.code is DriveErrorCode.NOT_FOUND
    assert health.state is AuthState.HEALTHY


async def test_seam_fault_blocks_with_transient_zero_calls_and_no_transition() -> None:
    fake, seam, sink, machine, health, guard = _build()
    seam.fault = True
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.TRANSIENT and "SECRET" not in str(ei.value)
    assert fake.call_count == 0 and health.state is AuthState.HEALTHY
    assert sink.alerts == () and machine.state is SourceState.ACTIVE


@pytest.mark.parametrize("field,value", [
    ("consent", "GRANTED"), ("consent", None), ("token", "VALID"), ("token", 1), ("epoch", True), ("epoch", "0"),
])
async def test_seam_answer_of_wrong_type_is_not_trusted(field, value) -> None:
    fake, seam, _sink, _m, health, guard = _build()
    setattr(seam, field, value)
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.TRANSIENT and fake.call_count == 0
    assert health.state is AuthState.HEALTHY


async def test_seam_epoch_moved_without_reconsent_closes_the_connection() -> None:
    fake, seam, _sink, _m, health, guard = _build()
    seam.epoch = 5
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.AUTH_REQUIRED and fake.call_count == 0
    assert health.cause is AuthCause.CONSENT_REVOKED


def test_constructor_validation_uses_fixed_codes() -> None:
    seam, sink, m = FakeAuthSeam(), FakeAlertSink(), SourceStateMachine()
    for args, code in (
        ((None, 0, seam, m, sink), "AUTH_HEALTH_IDENTITY_INVALID"),
        ((IDENT, True, seam, m, sink), "AUTH_HEALTH_EPOCH_INVALID"),
        ((IDENT, IntSub(0), seam, m, sink), "AUTH_HEALTH_EPOCH_INVALID"),
        ((IDENT, 0, seam, object(), sink), "AUTH_HEALTH_MACHINE_INVALID"),
        ((IDENT, 0, None, m, sink), "AUTH_HEALTH_SEAM_INVALID"),
    ):
        with pytest.raises(ValueError, match=code):
            DriveAuthHealth(*args)
    with pytest.raises(ValueError, match="AUTH_GUARD_CONFIG_INVALID"):
        AuthGuardedDrivePort(object(), FakeDrivePort())  # type: ignore[arg-type]


# --- recovery: new epoch + fresh scope check, no resurrection ------------------------------------


async def _closed(seam, guard):
    seam.revoke()
    with pytest.raises(DrivePortError):
        await guard.get_start_page_token(IDENT, 0)


async def test_recovery_requires_new_epoch_granted_consent_and_fresh_scope_check() -> None:
    fake, seam, sink, machine, health, guard = _build()
    await _closed(seam, guard)
    assert health.reconsent(0) is ReconsentResult.EPOCH_NOT_NEW  # same epoch: old grant not resurrected
    assert health.reconsent(1) is ReconsentResult.NO_CONSENT  # consent still revoked
    seam.regrant(2)
    assert health.reconsent(1) is ReconsentResult.EPOCH_MISMATCH
    seam.regrant(1, scope_ok=False)
    assert health.reconsent(1) is ReconsentResult.SCOPE_CHECK_FAILED and seam.scope_checks == 1
    assert health.state is AuthState.AUTH_REQUIRED and machine.state is SourceState.PAUSED
    seam.regrant(1)
    assert health.reconsent(1) is ReconsentResult.RECOVERED and seam.scope_checks == 2
    assert health.state is AuthState.HEALTHY and health.scope_epoch == 1
    assert machine.state is SourceState.ACTIVE
    # the old epoch is dead for both the guard and the fake; the new epoch works
    with pytest.raises(DrivePortError) as ei:
        await guard.get_start_page_token(IDENT, 0)
    assert ei.value.code is DriveErrorCode.SCOPE_EPOCH_STALE
    fake.set_scope_epoch(1)
    assert (await guard.get_start_page_token(IDENT, 1)).token == "START-1"
    assert len(sink.alerts) == 1


async def test_second_failure_after_recovery_is_a_new_transition_with_its_own_alert() -> None:
    fake, seam, sink, machine, health, guard = _build()
    await _closed(seam, guard)
    seam.regrant(1)
    assert health.reconsent(1) is ReconsentResult.RECOVERED
    fake.set_scope_epoch(1)
    seam.revoke()
    with pytest.raises(DrivePortError):
        await guard.get_start_page_token(IDENT, 1)
    assert [(a.transition_no, a.scope_epoch) for a in sink.alerts] == [(1, 0), (2, 1)]
    assert machine.pause_count == 2


def test_reconsent_when_healthy_and_hostile_epochs() -> None:
    _f, seam, _s, _m, health, _g = _build()
    assert health.reconsent(1) is ReconsentResult.NOT_REQUIRED
    health.notify_revoked()
    seam.regrant(1)
    for bad in (None, "1", True, IntSub(1), -1, 2**70, 1.0, object(), float("nan")):
        assert health.reconsent(bad) is ReconsentResult.EPOCH_NOT_NEW
    assert health.state is AuthState.AUTH_REQUIRED


def test_reconsent_seam_fault_and_scope_check_fault_fail_closed() -> None:
    _f, seam, _s, _m, health, _g = _build()
    health.notify_revoked()
    seam.regrant(1)
    seam.fault = True
    assert health.reconsent(1) is ReconsentResult.SEAM_FAULT
    seam.fault = False
    seam.scope_ok = "yes"  # not exactly True
    assert health.reconsent(1) is ReconsentResult.SCOPE_CHECK_FAILED
    assert health.state is AuthState.AUTH_REQUIRED


def test_quarantined_source_is_not_resumed_by_reconsent() -> None:
    _f, seam, _s, machine, health, _g = _build()
    health.notify_revoked()
    machine.quarantine("operator")
    seam.regrant(1)
    assert health.reconsent(1) is ReconsentResult.QUARANTINED
    assert health.state is AuthState.AUTH_REQUIRED and machine.state is SourceState.QUARANTINED


def test_source_paused_by_someone_else_stays_paused_after_recovery() -> None:
    machine = SourceStateMachine()
    machine.pause("failures")
    _f, seam, _s, _m, health, _g = _build(machine=machine)
    health.notify_revoked()
    assert machine.pause_count == 1  # we did not pause again
    seam.regrant(1)
    assert health.reconsent(1) is ReconsentResult.RECOVERED
    assert machine.state is SourceState.PAUSED


# --- revoke / expiry race between pages --------------------------------------------------------------


def _script_chain(fake: FakeDrivePort) -> None:
    fake.script_page("T1", (_chg("c1", "F1"),), next_page_token="T2")
    fake.script_page("T2", (_chg("c2", "F2"),), next_page_token="T3")
    fake.script_page("T3", (_chg("c3", "F3"),), new_start_page_token="N1")


def _committer(cursor: FakeCursorView, sink: list):
    def commit(token, page, epoch):
        sink.append((token, tuple(c.change_id for c in page.changes), epoch))
        cursor.commit_for_test(page.next_page_token or page.new_start_page_token)

    return commit


async def test_poll_chain_complete_without_hints() -> None:
    fake, _s, _k, _m, health, guard = _build()
    _script_chain(fake)
    cursor, got = FakeCursorView("T1"), []
    res = await run_poll(health, guard, cursor, _committer(cursor, got))
    assert res.status is PollStatus.COMPLETE and res.pages_committed == 3 and res.final_token == "N1"
    assert cursor.token == "N1" and [g[1] for g in got] == [("c1",), ("c2",), ("c3",)]


async def test_revoke_during_second_page_stops_chain_without_committing_it() -> None:
    fake, seam, sink, machine, health, guard = _build()
    _script_chain(fake)
    fake.run_after_calls(2, lambda _f: seam.revoke())  # revoke lands while page 2 is in flight
    cursor, got = FakeCursorView("T1"), []
    res = await run_poll(health, guard, cursor, _committer(cursor, got))
    assert res.status is PollStatus.AUTH_REQUIRED and res.pages_committed == 1
    assert [g[0] for g in got] == ["T1"]  # page after the revoke is not committed
    assert cursor.token == "T2" and cursor.commits == 1  # stays at the last committed value
    assert fake.call_count == 2  # page 3 never requested
    assert len(sink.alerts) == 1 and machine.state is SourceState.PAUSED


async def test_revoke_before_first_page_commits_nothing() -> None:
    fake, seam, _k, _m, health, guard = _build()
    _script_chain(fake)
    fake.run_after_calls(1, lambda _f: seam.revoke())
    cursor, got = FakeCursorView("T1"), []
    res = await run_poll(health, guard, cursor, _committer(cursor, got))
    assert res.status is PollStatus.AUTH_REQUIRED and res.pages_committed == 0
    assert got == [] and cursor.commits == 0 and cursor.token == "T1"


async def test_expiry_between_pages_refreshes_and_chain_completes() -> None:
    fake, seam, sink, _m, health, guard = _build()
    _script_chain(fake)
    fake.run_after_calls(1, lambda _f: seam.expire_token(refreshable=True))
    cursor, got = FakeCursorView("T1"), []
    res = await run_poll(health, guard, cursor, _committer(cursor, got))
    assert res.status is PollStatus.COMPLETE and res.pages_committed == 3
    assert seam.refresh_calls == 1 and sink.alerts == ()


async def test_expiry_not_refreshable_between_pages_stops_chain() -> None:
    fake, seam, sink, _m, health, guard = _build()
    _script_chain(fake)
    fake.run_after_calls(1, lambda _f: seam.expire_token(refreshable=False))
    cursor, got = FakeCursorView("T1"), []
    res = await run_poll(health, guard, cursor, _committer(cursor, got))
    assert res.status is PollStatus.AUTH_REQUIRED and res.pages_committed == 1 and cursor.token == "T2"
    assert [a.cause for a in sink.alerts] == [AuthCause.INVALID_GRANT]


async def test_poll_after_auth_required_makes_zero_fake_calls() -> None:
    fake, _seam, _s, _m, health, guard = _build()
    _script_chain(fake)
    health.notify_revoked()
    cursor, got = FakeCursorView("T1"), []
    res = await run_poll(health, guard, cursor, _committer(cursor, got))
    assert res.status is PollStatus.AUTH_REQUIRED and fake.call_count == 0 and got == []
    assert res.error_code is DriveErrorCode.AUTH_REQUIRED


async def test_poll_fixed_refusals_and_no_leak() -> None:
    fake, _s, _k, _m, health, guard = _build()
    _script_chain(fake)
    nothing = FakeCursorView(None)
    assert (await run_poll(health, guard, nothing, lambda *a: None)).status is PollStatus.NO_CURSOR
    for bad in ("", "a b", "x\x00", StrSub("T1")[:0]):
        assert (await run_poll(health, guard, FakeCursorView(bad), lambda *a: None)).status is PollStatus.NO_CURSOR
    for bad in (0, True, None, IntSub(3)):
        assert (await run_poll(health, guard, FakeCursorView("T1"), lambda *a: None, max_pages=bad)).status \
            is PollStatus.PORT_ERROR
    cur = FakeCursorView("T1")
    limited = await run_poll(health, guard, cur, _committer(cur, []), max_pages=2)
    assert limited.status is PollStatus.PAGE_LIMIT and limited.pages_committed == 2

    def boom(*_a):
        raise RuntimeError(SECRET)

    res = await run_poll(health, guard, FakeCursorView("T1"), boom)
    assert res.status is PollStatus.COMMIT_FAILED and SECRET not in repr(res)
    miss = await run_poll(health, guard, FakeCursorView("UNSCRIPTED"), lambda *a: None)
    assert miss.status is PollStatus.PORT_ERROR and miss.error_code is DriveErrorCode.NOT_FOUND


async def test_async_commit_callback_is_awaited() -> None:
    fake, _s, _k, _m, health, guard = _build()
    _script_chain(fake)
    seen: list[str] = []

    async def commit(token, page, epoch):
        seen.append(token)

    res = await run_poll(health, guard, FakeCursorView("T1"), commit)
    assert res.status is PollStatus.COMPLETE and seen == ["T1", "T2", "T3"]


# --- structure ---------------------------------------------------------------------------------------


def test_module_has_no_forbidden_imports_and_no_cursor_write_or_token_text() -> None:
    src = Path(drive_auth_state.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0] if node.level == 0 else "." + (node.module or ""))
    banned = {"httpx", "requests", "socket", "urllib", "aiohttp", "business_ai_gateway"}
    assert not (mods & banned)
    assert not any(m.startswith(".") and m.strip(".") in {"drive_oauth", "drive_cursor"} for m in mods)
    # the cursor seam is read-only: no write-shaped method on the protocol
    assert [n for n in dir(drive_auth_state.CursorView) if not n.startswith("_")] == ["committed_token"]


def test_consent_states_are_fixed_strings() -> None:
    assert {s.value for s in ConsentState} == {"GRANTED", "REVOKED", "NONE"}
