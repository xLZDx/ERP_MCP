"""S7/E4: notification hints (TC113) and polling without hints / without watch (TC114). Pure, no I/O."""
from __future__ import annotations

import pytest

from business_ai_gateway.phase2.drive_auth_state import (
    AuthGuardedDrivePort,
    AuthState,
    DriveAuthHealth,
    FakeAlertSink,
    FakeAuthSeam,
    FakeCursorView,
    HintIntake,
    HintResult,
    PollJob,
    PollStatus,
    run_poll,
)
from business_ai_gateway.phase2.drive_changes import DriveChange, DriveChangeKind
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_port import DrivePortIdentity
from business_ai_gateway.phase2.scheduler import SourceStateMachine

IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
SECRET_TOKEN = "chan-token-SECRET-123"


class StrSub(str):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__

    def encode(self, *a, **k):  # hostile override
        return b"CH1"


def _build():
    fake = FakeDrivePort()
    seam = FakeAuthSeam()
    health = DriveAuthHealth(IDENT, 0, seam, SourceStateMachine(), FakeAlertSink())
    guard = AuthGuardedDrivePort(health, fake)
    intake = HintIntake(health)
    assert intake.register_channel("CH1", "RES1", SECRET_TOKEN)
    return fake, seam, health, guard, intake


def _chg(cid: str, fid: str) -> DriveChange:
    return DriveChange(cid, fid, "r1", DriveChangeKind.UPSERT)


def _script(fake: FakeDrivePort) -> None:
    fake.script_page("T1", (_chg("c1", "F1"), _chg("c2", "F2")), next_page_token="T2")
    fake.script_page("T2", (_chg("c3", "F3"),), new_start_page_token="N1")


# --- TC113 -------------------------------------------------------------------------------------


def test_valid_hint_schedules_exactly_one_poll_job_with_no_data() -> None:
    _f, _s, _h, _g, intake = _build()
    assert intake.accept_hint("CH1", "RES1", SECRET_TOKEN) is HintResult.ACCEPTED_NEW_JOB
    assert intake.pending_jobs == 1
    job = intake.take_poll_job()
    assert job == PollJob("tenant-1", "conn-1", 0)
    assert set(PollJob.__slots__) == {"tenant", "connection_id", "scope_epoch"}
    assert intake.take_poll_job() is None and intake.pending_jobs == 0


def test_duplicate_and_out_of_order_hints_collapse_to_one_job() -> None:
    _f, _s, _h, _g, intake = _build()
    results = [intake.accept_hint("CH1", "RES1", SECRET_TOKEN, n) for n in (5, 5, 3, 9, 1, None)]
    assert results[0] is HintResult.ACCEPTED_NEW_JOB
    assert all(r is HintResult.ACCEPTED_COLLAPSED for r in results[1:])
    assert intake.pending_jobs == 1 and intake.accepted_count == 1 and intake.collapsed_count == 5
    assert intake.take_poll_job() is not None and intake.take_poll_job() is None
    # a hint after the job was taken schedules a fresh one
    assert intake.accept_hint("CH1", "RES1", SECRET_TOKEN, 2) is HintResult.ACCEPTED_NEW_JOB


@pytest.mark.parametrize("cid,rid,tok", [
    ("CH2", "RES1", SECRET_TOKEN),        # unknown channel
    ("CH1", "RES2", SECRET_TOKEN),        # resource of another channel
    ("CH1", "RES1", "wrong-token"),       # forged token
    ("CH1", "RES1", SECRET_TOKEN + "x"),  # token prefix match is not a match
    ("ch1", "RES1", SECRET_TOKEN),        # ids are case-sensitive, not folded
])
def test_forged_or_foreign_hint_is_ignored(cid, rid, tok) -> None:
    fake, _s, _h, _g, intake = _build()
    assert intake.accept_hint(cid, rid, tok) is HintResult.REJECTED_FOREIGN
    assert intake.pending_jobs == 0 and intake.take_poll_job() is None
    assert fake.call_count == 0


def test_hostile_hint_input_never_raises_and_is_refused_with_fixed_code() -> None:
    _f, _s, _h, _g, intake = _build()
    recursive: list = []
    recursive.append(recursive)
    bad_values = (None, 0, b"CH1", StrSub("CH1"), "", "CH 1", "CH1\x00", "CH1\n", "C\u200bH1", "x" * 100_000,
                  recursive, object())
    for bad in bad_values:
        assert intake.accept_hint(bad, "RES1", SECRET_TOKEN) is HintResult.REJECTED_INVALID
        assert intake.accept_hint("CH1", bad, SECRET_TOKEN) is HintResult.REJECTED_INVALID
        assert intake.accept_hint("CH1", "RES1", bad) is HintResult.REJECTED_INVALID
    assert intake.pending_jobs == 0


def test_register_channel_validates_and_is_bounded() -> None:
    _f, _s, _h, _g, intake = _build()
    for bad in (None, "", StrSub("x"), "a b", "x" * 2000):
        assert intake.register_channel(bad, "R", "T") is False
        assert intake.register_channel("C", bad, "T") is False
        assert intake.register_channel("C", "R", bad) is False
    for i in range(70):
        intake.register_channel(f"C{i}", "R", "T")
    assert intake.register_channel("OVERFLOW", "R", "T") is False
    assert intake.register_channel("C0", "R2", "T2") is True  # re-registering a known channel is fine


def test_payload_and_message_number_change_nothing_and_are_not_exposed() -> None:
    fake, _s, health, _g, intake = _build()
    payload = {"changes": [{"fileId": "F1"}], "token": "NEW-CURSOR", "self": None}
    payload["self"] = payload  # recursive
    r = intake.accept_hint("CH1", "RES1", SECRET_TOKEN, 10**30, payload)
    assert r is HintResult.ACCEPTED_NEW_JOB
    job = intake.take_poll_job()
    assert "NEW-CURSOR" not in repr(job) and "F1" not in repr(job)
    assert fake.call_count == 0  # and does not itself read Drive
    assert health.state is AuthState.HEALTHY


def test_nothing_in_the_intake_echoes_the_token() -> None:
    _f, _s, _h, _g, intake = _build()
    outcomes = [
        intake.accept_hint("CH1", "RES1", SECRET_TOKEN),
        intake.accept_hint("CH1", "RES1", "bad"),
        intake.accept_hint(None, None, None),
    ]
    blob = repr(outcomes) + repr(intake) + repr(intake.take_poll_job()) + str(HintResult.REJECTED_FOREIGN)
    assert SECRET_TOKEN not in blob and "RES1" not in blob


def test_hint_for_a_paused_connection_is_refused() -> None:
    fake, _s, health, _g, intake = _build()
    health.notify_revoked()
    assert intake.accept_hint("CH1", "RES1", SECRET_TOKEN) is HintResult.REJECTED_PAUSED
    assert intake.pending_jobs == 0 and fake.call_count == 0


def test_channel_from_the_old_epoch_is_stale_after_reconsent() -> None:
    _f, seam, health, _g, intake = _build()
    health.notify_revoked()
    seam.regrant(1)
    assert health.reconsent(1).value == "RECOVERED"
    assert intake.accept_hint("CH1", "RES1", SECRET_TOKEN) is HintResult.REJECTED_STALE
    assert intake.register_channel("CH1", "RES1", SECRET_TOKEN)  # re-registered at the new epoch
    assert intake.accept_hint("CH1", "RES1", SECRET_TOKEN) is HintResult.ACCEPTED_NEW_JOB
    assert intake.take_poll_job() == PollJob("tenant-1", "conn-1", 1)


def test_intake_requires_a_real_health_object() -> None:
    with pytest.raises(ValueError, match="HINT_INTAKE_CONFIG_INVALID"):
        HintIntake(object())  # type: ignore[arg-type]


# --- TC114: polling alone is complete -------------------------------------------------------------------


async def _poll_once() -> tuple[tuple, str | None, PollStatus]:
    fake = FakeDrivePort()
    _script(fake)
    health = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    guard = AuthGuardedDrivePort(health, fake)
    cursor = FakeCursorView("T1")
    seen: list = []

    def commit(token, page, epoch):
        seen.extend((c.change_id, c.file_id) for c in page.changes)
        cursor.commit_for_test(page.next_page_token or page.new_start_page_token)

    res = await run_poll(health, guard, cursor, commit)
    return tuple(seen), cursor.token, res.status


async def test_same_candidates_and_cursor_with_zero_hints_with_hints_and_without_watch() -> None:
    # (a) zero hints: scheduled poll only
    plain = await _poll_once()
    # (b) with a burst of hints: they only decide WHEN to poll; the chain is identical
    fake, _s, health, guard, intake = _build()
    _script(fake)
    for n in (4, 4, 2, 7):
        intake.accept_hint("CH1", "RES1", SECRET_TOKEN, n, {"changes": ["bogus"]})
    assert intake.take_poll_job() is not None and fake.call_count == 0
    cursor, seen = FakeCursorView("T1"), []

    def commit(token, page, epoch):
        seen.extend((c.change_id, c.file_id) for c in page.changes)
        cursor.commit_for_test(page.next_page_token or page.new_start_page_token)

    res = await run_poll(health, guard, cursor, commit)
    hinted = (tuple(seen), cursor.token, res.status)
    # (c) watch unsupported: no channel ever registered, hints (if any arrive) are foreign
    fake2 = FakeDrivePort()
    _script(fake2)
    health2 = DriveAuthHealth(IDENT, 0, FakeAuthSeam(), SourceStateMachine(), FakeAlertSink())
    no_watch = HintIntake(health2)
    assert no_watch.accept_hint("CH1", "RES1", SECRET_TOKEN) is HintResult.REJECTED_FOREIGN
    assert no_watch.take_poll_job() is None
    guard2 = AuthGuardedDrivePort(health2, fake2)
    cursor2, seen2 = FakeCursorView("T1"), []

    def commit2(token, page, epoch):
        seen2.extend((c.change_id, c.file_id) for c in page.changes)
        cursor2.commit_for_test(page.next_page_token or page.new_start_page_token)

    res2 = await run_poll(health2, guard2, cursor2, commit2)
    unsupported = (tuple(seen2), cursor2.token, res2.status)

    assert plain == hinted == unsupported
    assert plain == ((("c1", "F1"), ("c2", "F2"), ("c3", "F3")), "N1", PollStatus.COMPLETE)
    assert fake.call_log == fake2.call_log == ("list_changes", "list_changes")


async def test_hint_never_creates_evidence_or_reads_drive_but_poll_after_hint_is_guarded() -> None:
    fake, seam, health, guard, intake = _build()
    _script(fake)
    intake.accept_hint("CH1", "RES1", SECRET_TOKEN)
    seam.revoke()  # revoke between the hint and the poll job running
    cursor, seen = FakeCursorView("T1"), []
    res = await run_poll(health, guard, cursor, lambda *a: seen.append(a))
    assert res.status is PollStatus.AUTH_REQUIRED and seen == [] and fake.call_count == 0
    assert cursor.commits == 0
