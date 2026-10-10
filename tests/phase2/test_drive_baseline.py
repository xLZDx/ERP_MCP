"""S7/E2: start-token-first baseline + catch-up orchestrator (TC106, TC107, TC108, S6b lessons)."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest

from business_ai_gateway.phase2 import drive_baseline
from business_ai_gateway.phase2.drive_baseline import (
    BaselineItem,
    BaselineLimits,
    BaselineOutcome,
    BaselinePage,
    BaselineRequest,
    DriveBaseline,
    DriveRunMode,
    check_baseline_order,
)
from business_ai_gateway.phase2.drive_changes import DriveChange, DriveChangeKind
from business_ai_gateway.phase2.drive_cursor import (
    CursorReason,
    CursorRecord,
    CursorState,
    DriveCorpus,
    DriveCursorStore,
    DriveLease,
    cursor_key,
)
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_port import (
    ChangesPage,
    DriveErrorCode,
    DrivePortError,
    DrivePortIdentity,
    StartToken,
)
from business_ai_gateway.phase2.fakes import DEFAULT_SCOPE, WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import CommitResult, PortError
from business_ai_gateway.phase2.resnapshot import ResnapshotReason, ResnapshotTracker

SCOPE = DEFAULT_SCOPE
H = "a" * 64
IDENT_A = DrivePortIdentity("account:A", "A", "conn-1")
IDENT_B = DrivePortIdentity("drive:B", "A", "conn-1")
CORPUS = DriveCorpus(None, ("ROOT-1",))
O = BaselineOutcome
R = CursorReason


class StrSub(str):
    pass


def chg(cid: str, fid: str, rev: str | None = "r1", kind=DriveChangeKind.UPSERT,
        drive_id: str | None = None, mime: str | None = "application/pdf") -> DriveChange:
    return DriveChange(cid, fid, rev, kind, drive_id=drive_id, mime_type=mime)


class Lister:
    """Scripted baseline lister; appends ``baseline_list`` to the shared call log."""

    def __init__(self, log: list[str], pages: dict | None = None) -> None:
        self.log = log
        self.pages = pages if pages is not None else {None: BaselinePage(())}
        self.positions: list[str | None] = []
        self.on_call = None

    async def list_page(self, identity, scope_epoch, position):
        self.log.append("baseline_list")
        self.positions.append(position)
        if self.on_call:
            self.on_call(len(self.positions))
        item = self.pages[position]
        if isinstance(item, BaseException):
            raise item
        return item


class LoggedPort:
    def __init__(self, fake: FakeDrivePort, log: list[str]) -> None:
        self.fake, self.log = fake, log

    async def get_start_page_token(self, identity, scope_epoch):
        self.log.append("get_start_page_token")
        return await self.fake.get_start_page_token(identity, scope_epoch)

    async def list_changes(self, identity, scope_epoch, page_token):
        self.log.append("list_changes")
        return await self.fake.list_changes(identity, scope_epoch, page_token)


class FaultyCursors:
    """Delegates to the in-memory port; fails the n-th commit_cursor_page before or after it ran."""

    def __init__(self, inner: InMemoryLiving) -> None:
        self.inner, self.fail_on, self.mode, self.commits = inner, None, "before", 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def commit_cursor_page(self, *args):
        self.commits += 1
        armed = self.fail_on == self.commits
        if armed and self.mode == "before":
            raise PortError("BOOM")
        result = await self.inner.commit_cursor_page(*args)
        if armed:
            raise PortError("BOOM")
        return result


@dataclass
class Env:
    living: InMemoryLiving
    lease: DriveLease
    tracker: ResnapshotTracker
    store: DriveCursorStore
    ident: DrivePortIdentity
    fake: FakeDrivePort
    log: list[str]
    lister: Lister
    runner: DriveBaseline
    allowed: dict = field(default_factory=dict)

    def request(self, **over) -> BaselineRequest:
        args = {
            "identity": self.ident, "corpus": CORPUS, "drive_epoch": 0, "lease": self.lease,
            "scope_allowed": lambda fid: self.allowed.get(fid, True), "lister": self.lister,
        }
        args.update(over)
        return BaselineRequest(**args)

    async def run(self, mode=DriveRunMode.INCREMENTAL, **over):
        return await self.runner.run(self.request(**over), mode)

    async def record(self, ident=None) -> CursorRecord:
        view = await self.living.get_cursor(WORKER, SCOPE, cursor_key(ident or self.ident))
        return CursorRecord.decode(view.cursor_value)

    async def events(self) -> list[dict]:
        return [r.content for r in await self.living.list_outbox(WORKER, SCOPE)]

    async def init(self) -> None:
        await self.store.initialize(self.ident, CORPUS, 0, self.lease)


async def make_env(ident=IDENT_A, *, shared: Env | None = None, start="START-1",
                   cursors=None) -> Env:
    if shared is None:
        living = InMemoryLiving()
        await living.enqueue_job(WORKER, SCOPE, UUID(int=1), "drive", H, "key-1")
        fence = await living.acquire_job(WORKER, SCOPE, UUID(int=1), "w1", 300)
        lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", fence, 0)
        tracker = ResnapshotTracker()
        store = DriveCursorStore(cursors(living) if cursors else living, tracker)
    else:
        living, lease, tracker, store = shared.living, shared.lease, shared.tracker, shared.store
    fake = FakeDrivePort(start_page_token=start)
    log: list[str] = []
    env = Env(living, lease, tracker, store, ident, fake, log, Lister(log),
              DriveBaseline(LoggedPort(fake, log), store))
    return env


async def ready(**kw) -> Env:
    env = await make_env(**kw)
    await env.init()
    return env


# --- TC106 -------------------------------------------------------------------------------------


async def test_tc106_start_token_first_and_change_during_baseline_appears_in_catchup_once():
    env = await ready()
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"), BaselineItem("F2", "r1")))}
    env.lister.on_call = lambda n: env.fake.script_page(
        "START-1", (chg("c1", "F1", "r2"),), new_start_page_token="TOK-2")
    result = await env.run()
    assert result.outcome is O.LIVE and result.complete and result.reason is None
    assert env.log == ["get_start_page_token", "baseline_list", "list_changes"]
    assert check_baseline_order(env.log)
    assert result.trace == ("START_TOKEN", "TOKEN_PERSISTED", "BASELINE_PAGE", "BASELINE_DONE",
                            "CATCHUP_PAGE", "LIVE")
    rec = await env.record()
    assert (rec.state, rec.token, rec.pos) == (CursorState.LIVE, "TOK-2", None)
    events = await env.events()
    catchup = [e for e in events if e["change_id"] == "c1"]
    assert len(catchup) == 1 and catchup[0]["file_id"] == "F1" and catchup[0]["revision_id"] == "r2"
    assert len([e for e in events if e["change_id"].startswith("baseline|")]) == 2
    assert {c.file_id for c in result.candidates} == {"F1", "F2"}
    assert all(c.status == "UNATTESTED" for c in result.candidates)


async def test_tc106_start_token_is_persisted_before_the_listing_and_not_requested_again():
    env = await ready()
    env.lister.pages = {None: DrivePortError(DriveErrorCode.TRANSIENT)}
    first = await env.run()
    assert first.outcome is O.RETRYABLE and first.reason is R.TRANSIENT
    rec = await env.record()  # the token survived the failed listing
    assert (rec.state, rec.token) == (CursorState.BASELINING, "START-1")
    env.fake.script_start_token("START-OTHER")  # a second token request would be visible
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    second = await env.run()
    assert second.outcome is O.LIVE
    assert env.fake.count("get_start_page_token") == 1
    assert (await env.record()).token == "TOK-2"


def test_tc106_order_checker_detects_a_token_taken_after_the_listing():
    assert check_baseline_order(["get_start_page_token", "baseline_list", "list_changes"])
    assert not check_baseline_order(["baseline_list", "get_start_page_token", "list_changes"])
    assert not check_baseline_order(["list_changes", "get_start_page_token"])
    assert not check_baseline_order(["baseline_list", "list_changes"])  # no start token at all
    assert not check_baseline_order(None)
    assert not check_baseline_order([StrSub("get_start_page_token"), 1])
    assert not check_baseline_order(5)


async def test_tc106_a_run_refuses_when_the_observed_call_order_is_wrong():
    env = await ready()
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    late = lambda: ["baseline_list", "get_start_page_token"]
    result = await env.run(call_log=late)
    assert result.outcome is O.REFUSED and result.reason is R.START_TOKEN_ORDER
    assert not result.complete and result.state is not CursorState.LIVE


# --- bounded paging ------------------------------------------------------------------------------


async def test_page_limit_is_a_non_complete_resumable_result_never_live():
    env = await ready()
    env.lister.pages = {
        None: BaselinePage((BaselineItem("F1", "r1"),), "p2"),
        "p2": BaselinePage((BaselineItem("F2", "r1"),), "p3"),
        "p3": BaselinePage((BaselineItem("F3", "r1"),)),
    }
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    limited = await env.run(limits=BaselineLimits(max_pages=2, max_rows=100))
    assert (limited.outcome, limited.reason) == (O.LIMIT_REACHED, R.PAGE_LIMIT)
    assert not limited.complete and limited.pages == 2 and limited.state is CursorState.BASELINING
    rec = await env.record()
    assert rec.state is CursorState.BASELINING and rec.pos == "p3"
    done = await env.run()
    assert done.outcome is O.LIVE and env.lister.positions == [None, "p2", "p3"]
    assert env.fake.count("get_start_page_token") == 1
    assert len([e for e in await env.events() if e["event_kind"] == "DRIVE_CANDIDATE"]) == 3


async def test_row_limit_stops_before_the_second_oversized_page_and_commits_nothing_of_it():
    env = await ready()
    env.lister.pages = {
        None: BaselinePage((BaselineItem("F1", "r1"),), "p2"),
        "p2": BaselinePage((BaselineItem("F2", "r1"), BaselineItem("F3", "r1"))),
    }
    result = await env.run(limits=BaselineLimits(max_pages=10, max_rows=2))
    assert (result.outcome, result.reason) == (O.LIMIT_REACHED, R.ROW_LIMIT)
    assert not result.complete and result.rows == 1
    assert [e["file_id"] for e in await env.events()] == ["F1"]
    rec = await env.record()
    assert (rec.state, rec.pos) == (CursorState.BASELINING, "p2")


async def test_page_limit_in_catchup_stays_catching_up():
    env = await ready()
    env.lister.pages = {None: BaselinePage(())}
    env.fake.script_page("START-1", (chg("c1", "F1"),), next_page_token="N2")
    env.fake.script_page("N2", (chg("c2", "F2"),), new_start_page_token="TOK-3")
    result = await env.run(limits=BaselineLimits(max_pages=2, max_rows=100))
    assert (result.outcome, result.state) == (O.LIMIT_REACHED, CursorState.CATCHING_UP)
    assert (await env.record()).token == "N2"
    assert (await env.run()).outcome is O.LIVE
    assert (await env.record()).token == "TOK-3"


def test_limits_and_request_validate_exact_types():
    for bad in (0, -1, True, 2.0, StrSub("1"), 1_000_001):
        with pytest.raises(ValueError, match="BASELINE_LIMITS_INVALID"):
            BaselineLimits(max_pages=bad)
        with pytest.raises(ValueError, match="BASELINE_LIMITS_INVALID"):
            BaselineLimits(max_rows=bad)


# --- TC107 ---------------------------------------------------------------------------------------


async def test_tc107_same_file_id_in_two_namespaces_stays_two_candidates_and_two_cursors():
    a = await ready(ident=IDENT_A, start="SA")
    b = await ready(ident=IDENT_B, shared=a, start="SB")
    await b.init()
    a.lister.pages = {None: BaselinePage((BaselineItem("SAME", "r1"),))}
    b.lister.pages = {None: BaselinePage((BaselineItem("SAME", "r1", drive_id="B"),))}
    a.fake.script_page("SA", (chg("c1", "SAME"),), new_start_page_token="SA2")
    b.fake.script_page("SB", (chg("c1", "SAME", drive_id="B"),), new_start_page_token="SB2")
    ra, rb = await a.run(), await b.run()
    assert ra.outcome is O.LIVE and rb.outcome is O.LIVE
    assert {c.connection_id for c in ra.candidates} == {IDENT_A.connection_id}
    assert {c.connection_id for c in rb.candidates} == {IDENT_B.connection_id}
    assert {c.file_id for c in ra.candidates + rb.candidates} == {"SAME"}
    events = await a.events()
    assert len(events) == 4 and len({e["event_id"] for e in events}) == 4  # same change id c1, 2 ns
    assert {e["namespace"] for e in events} == {"account:A", "drive:B"}
    assert (await a.record()).token == "SA2" and (await b.record(IDENT_B)).token == "SB2"


async def test_tc107_a_change_page_of_one_namespace_cannot_move_the_other_cursor():
    a = await ready(ident=IDENT_A, start="SA")
    b = await ready(ident=IDENT_B, shared=a, start="SB")
    await b.init()
    for env in (a, b):
        env.fake.script_page(env.fake.__dict__["_start"].token, new_start_page_token="T2")
    assert (await a.run()).outcome is O.LIVE and (await b.run()).outcome is O.LIVE
    view_a = await a.living.get_cursor(WORKER, SCOPE, cursor_key(IDENT_A))
    b.fake.script_page("T2", (chg("c9", "F9", drive_id="B"),), new_start_page_token="T3")
    assert (await b.run()).outcome is O.LIVE
    assert await a.living.get_cursor(WORKER, SCOPE, cursor_key(IDENT_A)) == view_a
    assert (await b.record(IDENT_B)).token == "T3"


async def test_tc107_a_change_of_another_drive_is_counted_denied_and_never_a_candidate():
    env = await ready(ident=IDENT_B, start="SB")
    env.fake.script_page("SB", (chg("c1", "F1", drive_id="B"), chg("c2", "F2", drive_id="OTHER"),
                                chg("c3", "F3", drive_id=None)), new_start_page_token="SB2")
    result = await env.run()
    assert result.outcome is O.LIVE and result.denied_changes == 2
    assert [c.file_id for c in result.candidates] == ["F1"]
    assert {e["file_id"] for e in await env.events()} == {"F1"}


async def test_removed_change_gives_a_tombstone_and_requalification_never_a_replacement():
    env = await ready()
    env.fake.script_page(
        "START-1", (chg("c1", "FOLDER", None, DriveChangeKind.REMOVED, mime=None),
                    chg("c2", "NEW", "r9")), new_start_page_token="TOK-2")
    result = await env.run()
    assert result.outcome is O.LIVE
    assert [t.reason for t in result.tombstones] == ["REMOVED"]
    assert result.requalify_folder_ids == ("FOLDER",)
    kinds = sorted(e["event_kind"] for e in await env.events())
    assert kinds == ["DRIVE_CANDIDATE", "DRIVE_REQUALIFY", "DRIVE_TOMBSTONE"]


# --- TC108: lost / corrupt / foreign cursor ------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "reason"),
    [("empty", R.CURSOR_EMPTY), ("corrupt", R.CURSOR_CORRUPT),
     ("foreign", R.IDENTITY_CHANGED)],
)
async def test_tc108_lost_cursor_blocks_incremental_until_a_fresh_complete_snapshot(case, reason):
    env = await make_env()
    key = cursor_key(IDENT_A)
    if case == "empty":
        await env.living.create_cursor(WORKER, SCOPE, key, "")
    elif case == "corrupt":
        await env.living.create_cursor(WORKER, SCOPE, key, "{broken")
    elif case == "foreign":
        await env.living.create_cursor(
            WORKER, SCOPE, key, DriveCursorStore.fresh_record(IDENT_B, CORPUS, 0).encode())
    first = await env.run()
    assert (first.outcome, first.reason) == (O.RESNAPSHOT_REQUIRED, reason)
    assert not first.complete and env.fake.call_count == 0
    assert env.tracker.is_required(key)
    blocked = await env.run()  # still blocked, and still without touching Drive
    assert (blocked.outcome, blocked.reason) == (O.BLOCKED, R.INCREMENTAL_BLOCKED)
    assert env.fake.call_count == 0 and env.tracker.is_required(key)
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    fresh = await env.run(DriveRunMode.RESNAPSHOT_START)
    assert fresh.outcome is O.LIVE and fresh.snapshot_cleared
    assert not env.tracker.is_required(key)
    env.fake.script_page("TOK-2", new_start_page_token="TOK-2")
    assert (await env.run()).outcome is O.LIVE


async def test_tc108_an_incomplete_fresh_snapshot_does_not_clear_the_requirement():
    env = await make_env()
    env.lister.pages = {
        None: BaselinePage((BaselineItem("F1", "r1"),), "p2"),
        "p2": BaselinePage((BaselineItem("F2", "r1"),)),
    }
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    env.tracker.require(cursor_key(IDENT_A), ResnapshotReason.CURSOR_MISSING, 0)
    blocked_first = await env.run()
    assert (blocked_first.outcome, blocked_first.reason) == (O.BLOCKED, R.INCREMENTAL_BLOCKED)
    limited = await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    assert limited.outcome is O.LIMIT_REACHED and not limited.snapshot_cleared
    assert env.tracker.is_required(cursor_key(IDENT_A))
    assert (await env.run()).outcome is O.BLOCKED  # an interrupted snapshot is not LIVE
    done = await env.run(DriveRunMode.RESNAPSHOT_CONTINUE)
    assert done.outcome is O.LIVE and done.snapshot_cleared
    assert not env.tracker.is_required(cursor_key(IDENT_A))
    assert env.fake.count("get_start_page_token") == 1


async def test_tc108_identity_corpus_and_epoch_changes_versus_the_record_are_resnapshot():
    env = await ready()
    other_corpus = await env.run(corpus=DriveCorpus(None, ("ROOT-2",)))
    assert (other_corpus.outcome, other_corpus.reason) == (O.RESNAPSHOT_REQUIRED, R.CORPUS_CHANGED)
    env2 = await ready()
    epoch = await env2.run(drive_epoch=1)
    assert (epoch.outcome, epoch.reason) == (O.RESNAPSHOT_REQUIRED, R.SCOPE_EPOCH_CHANGED)
    assert env2.tracker.reason(cursor_key(IDENT_A)) is ResnapshotReason.SCOPE_EPOCH_CHANGED
    assert env.fake.call_count == 0 and env2.fake.call_count == 0


async def test_tc108_a_persisted_gap_survives_a_restart_and_is_not_cleared_by_a_plain_run():
    env = await ready()
    env.fake.script_page("START-1", (chg("c1", "F1"),), next_page_token="START-1")
    gap = await env.run()
    assert (gap.outcome, gap.reason, gap.cursor_marked) == (O.GAP, R.TOKEN_REPEATED, True)
    restarted = DriveBaseline(LoggedPort(env.fake, env.log),
                              DriveCursorStore(env.living, ResnapshotTracker()))
    again = await restarted.run(env.request())
    assert (again.outcome, again.reason) == (O.GAP, R.TOKEN_REPEATED)


# --- TC108: token chain problems -----------------------------------------------------------------


async def test_repeated_continuation_token_is_a_gap_and_the_page_is_not_committed():
    env = await ready()
    env.fake.script_page("START-1", (chg("c1", "F1"),), next_page_token="START-1")
    result = await env.run()
    assert (result.outcome, result.reason, result.state) == (O.GAP, R.TOKEN_REPEATED, CursorState.GAP)
    assert await env.events() == []
    rec = await env.record()
    assert rec.state is CursorState.GAP and rec.token == "START-1"
    assert env.tracker.is_required(cursor_key(IDENT_A))
    assert (await env.run()).outcome is O.BLOCKED


async def test_regressing_token_inside_a_chain_stops_after_the_last_good_page():
    env = await ready()
    env.fake.script_page("START-1", (chg("c1", "F1"),), next_page_token="B")
    env.fake.script_page("B", (chg("c2", "F2"),), next_page_token="START-1")
    result = await env.run()
    assert (result.outcome, result.reason) == (O.GAP, R.TOKEN_REGRESSED)
    assert [e["change_id"] for e in await env.events()] == ["c1"]
    rec = await env.record()
    assert rec.state is CursorState.GAP and rec.token == "B"


async def test_regressing_new_start_token_across_runs_uses_the_recorded_history():
    env = await ready()
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    assert (await env.run()).outcome is O.LIVE
    env.fake.script_page("TOK-2", (chg("c1", "F1"),), new_start_page_token="START-1")
    result = await env.run()
    assert (result.outcome, result.reason) == (O.GAP, R.TOKEN_REGRESSED)
    assert (await env.record()).token == "TOK-2"


async def test_live_poll_without_changes_commits_nothing_and_same_token_with_changes_is_a_gap():
    env = await ready()
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    await env.run()
    version = (await env.living.get_cursor(WORKER, SCOPE, cursor_key(IDENT_A))).version
    env.fake.script_page("TOK-2", new_start_page_token="TOK-2")
    quiet = await env.run()
    assert quiet.outcome is O.LIVE and quiet.pages == 1
    assert (await env.living.get_cursor(WORKER, SCOPE, cursor_key(IDENT_A))).version == version
    env.fake.script_page("TOK-2", (chg("c1", "F1"),), new_start_page_token="TOK-2")
    assert (await env.run()).reason is R.TOKEN_REPEATED


async def test_unknown_change_kind_never_advances_the_cursor_or_commits_the_page():
    env = await ready()
    env.fake.script_page(
        "START-1", (chg("c1", "F1"), chg("c2", "F2", None, DriveChangeKind.UNKNOWN)),
        new_start_page_token="TOK-2")
    result = await env.run()
    assert (result.outcome, result.reason) == (O.GAP, R.UNKNOWN_CHANGE_KIND)
    assert result.candidates == () and await env.events() == []
    rec = await env.record()
    assert rec.state is CursorState.GAP and rec.token == "START-1"


async def test_missing_continuation_or_non_page_object_is_a_gap():
    @dataclass
    class Both:
        changes: tuple = ()
        next_page_token: str | None = None
        new_start_page_token: str | None = None

    class Stub:
        def __init__(self, page):
            self.page = page

        async def get_start_page_token(self, identity, epoch):
            return StartToken("S1")

        async def list_changes(self, identity, epoch, token):
            return self.page

    for page, reason in ((Both(), R.TOKEN_MISSING), (Both(next_page_token="x"), R.PAGE_INVALID),
                         (None, R.PAGE_INVALID)):
        env = await ready()
        runner = DriveBaseline(Stub(page), env.store)
        result = await runner.run(env.request())
        assert (result.outcome, result.reason) == (O.GAP, reason)
        assert await env.events() == []


async def test_unverified_membership_is_a_gap_in_catchup_and_in_baseline():
    env = await ready()
    env.fake.script_page("START-1", (chg("c1", "F1"),), new_start_page_token="TOK-2")
    gap = await env.run(scope_allowed=lambda fid: None)
    assert (gap.outcome, gap.reason) == (O.GAP, R.MEMBERSHIP_UNVERIFIED)
    assert await env.events() == []
    for hostile in (lambda fid: (_ for _ in ()).throw(RuntimeError("SECRET")), lambda fid: "yes",
                    lambda fid: 1):
        env2 = await ready()
        env2.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
        result = await env2.run(scope_allowed=hostile)
        assert (result.outcome, result.reason) == (O.GAP, R.MEMBERSHIP_UNVERIFIED)
        assert "SECRET" not in repr(result)


async def test_out_of_scope_baseline_item_is_counted_and_not_a_tombstone():
    env = await ready()
    env.allowed["F2"] = False
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"), BaselineItem("F2", "r1")))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    result = await env.run()
    assert result.outcome is O.LIVE and result.denied_changes == 1 and result.tombstones == ()
    assert [c.file_id for c in result.candidates] == ["F1"]


async def test_lost_token_on_the_provider_side_is_resnapshot_required():
    env = await ready()  # no page is scripted for START-1 -> the fake answers NOT_FOUND
    result = await env.run()
    assert (result.outcome, result.reason) == (O.RESNAPSHOT_REQUIRED, R.TOKEN_NOT_FOUND)
    assert env.tracker.is_required(cursor_key(IDENT_A))


# --- crash / fence: page + cursor are all-or-nothing ---------------------------------------------


async def test_crash_before_the_commit_leaves_neither_page_nor_cursor_and_rerun_applies_it_once():
    holder: list[FaultyCursors] = []
    env = await make_env(cursors=lambda living: holder.append(FaultyCursors(living)) or holder[0])
    faulty = holder[0]
    await env.init()
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", (chg("c1", "F1", "r2"),), new_start_page_token="TOK-2")
    faulty.fail_on, faulty.mode = 3, "before"  # commits: start token, baseline page, catch-up page
    crashed = await env.run()
    assert (crashed.outcome, crashed.reason) == (O.RETRYABLE, R.PORT_FAILURE)
    assert [e["change_id"] for e in await env.events()] == [
        "baseline|7:START-1|F1"]
    rec = await env.record()
    assert (rec.state, rec.token) == (CursorState.CATCHING_UP, "START-1")
    faulty.fail_on = None
    assert (await env.run()).outcome is O.LIVE
    assert [e["change_id"] for e in await env.events()].count("c1") == 1
    assert (await env.record()).token == "TOK-2"


async def test_crash_after_the_commit_is_recovered_without_duplicating_the_page():
    holder: list[FaultyCursors] = []
    env = await make_env(cursors=lambda living: holder.append(FaultyCursors(living)) or holder[0])
    faulty = holder[0]
    await env.init()
    env.lister.pages = {None: BaselinePage(())}
    env.fake.script_page("START-1", (chg("c1", "F1", "r2"),), new_start_page_token="TOK-2")
    faulty.fail_on, faulty.mode = 3, "after"
    assert (await env.run()).outcome is O.RETRYABLE
    rec = await env.record()  # the commit really happened: page and cursor are both there
    assert (rec.state, rec.token) == (CursorState.LIVE, "TOK-2")
    assert [e["change_id"] for e in await env.events()] == ["c1"]
    faulty.fail_on = None
    env.fake.script_page("TOK-2", new_start_page_token="TOK-2")
    assert (await env.run()).outcome is O.LIVE
    assert [e["change_id"] for e in await env.events()] == ["c1"]


async def test_stale_fence_commits_nothing_at_all():
    env = await ready()
    stale = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", env.lease.fence + 1, 0)
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    result = await env.run(lease=stale)
    assert (result.outcome, result.reason) == (O.LEASE_LOST, R.LEASE_LOST) and not result.complete
    assert await env.events() == []
    assert (await env.record()).state is CursorState.UNINITIALIZED
    assert env.lister.positions == []  # the listing never started


async def test_lease_lost_mid_run_commits_nothing_for_the_current_page():
    env = await ready()
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.lister.on_call = lambda n: env.living.clock.advance(1000)  # the lease expires while listing
    result = await env.run()
    assert (result.outcome, result.reason) == (O.LEASE_LOST, R.LEASE_LOST)
    assert await env.events() == []
    rec = await env.record()
    assert (rec.state, rec.token, rec.pos) == (CursorState.BASELINING, "START-1", None)
    assert result.candidates == ()


async def test_ledger_scope_revoked_between_pages_is_resnapshot_and_commits_nothing_more():
    env = await ready()
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.lister.on_call = lambda n: env.living._st.sources[SCOPE].__setattr__("epoch", 1)
    result = await env.run()
    assert (result.outcome, result.reason) == (O.RESNAPSHOT_REQUIRED, R.SCOPE_REVOKED)
    assert await env.events() == []
    assert env.tracker.is_required(cursor_key(IDENT_A))


# --- port errors ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "outcome", "reason"),
    [
        (DriveErrorCode.INVALID_GRANT, O.AUTH_REQUIRED, R.AUTH_INVALID_GRANT),
        (DriveErrorCode.AUTH_REQUIRED, O.AUTH_REQUIRED, R.AUTH_REQUIRED),
        (DriveErrorCode.RATE_LIMITED, O.RETRYABLE, R.RATE_LIMITED),
        (DriveErrorCode.TRANSIENT, O.RETRYABLE, R.TRANSIENT),
        (DriveErrorCode.FORBIDDEN_HISTORY, O.REFUSED, R.PORT_UNEXPECTED),
        (DriveErrorCode.NOT_FOUND, O.REFUSED, R.PORT_UNEXPECTED),
        (DriveErrorCode.SCOPE_EPOCH_STALE, O.RESNAPSHOT_REQUIRED, R.SCOPE_EPOCH_CHANGED),
    ],
)
async def test_port_errors_map_to_fixed_outcomes_without_moving_the_cursor(code, outcome, reason):
    env = await ready()
    env.fake.force_error("get_start_page_token", code)
    result = await env.run()
    assert (result.outcome, result.reason) == (outcome, reason) and not result.complete
    rec = await env.record()
    if outcome is O.RESNAPSHOT_REQUIRED:
        assert rec.state is CursorState.RESNAPSHOT_REQUIRED
    else:
        assert rec.state is CursorState.UNINITIALIZED and rec.token is None  # untouched
        assert not env.tracker.is_required(cursor_key(IDENT_A))


# --- S6b lessons: exact types, byte-exact ids, hostile input never raises ------------------------


async def test_tokens_and_ids_are_preserved_byte_exact_and_never_case_folded():
    env = await ready(start="AbC-ü/1+=")
    env.lister.pages = {None: BaselinePage((BaselineItem("FiLe-Ä"),))}
    env.fake.script_page("AbC-ü/1+=", (chg("c-1", "FiLe-Ä"),), new_start_page_token="TOK-Ö")
    result = await env.run()
    assert result.outcome is O.LIVE
    assert (await env.record()).token == "TOK-Ö"
    assert {e["file_id"] for e in await env.events()} == {"FiLe-Ä"}
    env2 = await ready(start="AbC")
    env2.fake.script_page("abc", new_start_page_token="TOK-2")  # case variant is a different token
    assert (await env2.run()).reason is R.TOKEN_NOT_FOUND


async def test_hostile_run_arguments_never_raise():
    env = await ready()
    req = env.request()

    class SubRequest(BaselineRequest):
        pass

    sub = SubRequest(**{f: getattr(req, f) for f in (
        "identity", "corpus", "drive_epoch", "lease", "scope_allowed", "lister", "limits")})
    for args in ((None,), (req, "INCREMENTAL"), (req, None), (object(),), (StrSub("x"),), (sub,)):
        result = await env.runner.run(*args)
        assert result.outcome is O.REFUSED and result.reason is R.INVALID_REQUEST
    with pytest.raises(ValueError, match="BASELINE_REQUEST_INVALID"):
        env.request(identity="account:A")
    with pytest.raises(ValueError, match="BASELINE_REQUEST_INVALID"):
        env.request(drive_epoch=True)
    with pytest.raises(ValueError, match="BASELINE_REQUEST_INVALID"):
        env.request(scope_allowed=None)
    with pytest.raises(ValueError, match="DRIVE_STORE_REQUIRED"):
        DriveBaseline(env.fake, object())
    assert env.fake.call_count == 0


@pytest.mark.parametrize(
    "bad",
    [None, "page", {"items": ()}, 5, [], BaselinePage],
)
async def test_hostile_lister_results_are_a_gap_and_nothing_leaks(bad):
    env = await ready()
    env.lister.pages = {None: bad}
    result = await env.run()
    assert (result.outcome, result.reason) == (O.GAP, R.PAGE_INVALID)
    assert await env.events() == []


async def test_lister_exception_and_repeated_position_are_fixed_refusals():
    env = await ready()
    env.lister.pages = {None: RuntimeError("SECRET-xyz")}
    result = await env.run()
    assert (result.outcome, result.reason) == (O.REFUSED, R.INTERNAL)
    assert "SECRET" not in repr(result)
    env2 = await ready()
    env2.lister.pages = {None: BaselinePage((), "p2"), "p2": BaselinePage((), "p2")}
    assert (await env2.run()).reason is R.TOKEN_REPEATED


async def test_start_token_that_is_not_an_exact_start_token_is_refused():
    class SubToken(StartToken):
        pass

    class Stub:
        def __init__(self, value):
            self.value = value

        async def get_start_page_token(self, identity, epoch):
            return self.value

    for value in (None, "S1", StrSub("S1"), SubToken("S1")):
        env = await ready()
        result = await DriveBaseline(Stub(value), env.store).run(env.request())
        assert (result.outcome, result.reason) == (O.REFUSED, R.START_TOKEN_INVALID)
        assert (await env.record()).state is CursorState.UNINITIALIZED


def test_item_and_page_validation_is_exact_and_echoes_nothing():
    for kw in ({"file_id": StrSub("F")}, {"file_id": ""}, {"file_id": "F 1"}, {"file_id": "F\x00"},
               {"file_id": "F", "parents": ["P"]}, {"file_id": "F", "revision_id": 1}):
        with pytest.raises(ValueError, match="BASELINE_ITEM_INVALID"):
            BaselineItem(**kw)
    for kw in ({"items": [BaselineItem("F")]}, {"items": (None,)},
               {"items": (), "next_position": StrSub("p")}, {"items": (), "next_position": ""}):
        with pytest.raises(ValueError, match="BASELINE_PAGE_INVALID"):
            BaselinePage(**kw)


async def test_unused_changes_page_import_is_the_real_port_type():
    assert ChangesPage((), None, "x").new_start_page_token == "x"
    assert CommitResult(1, False).version == 1


def test_module_imports_no_release1_http_or_socket_code_and_reuses_the_projector():
    path = Path(drive_baseline.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
    forbidden = ("httpx", "requests", "socket", "subprocess", "drive_http", "business_ai_gateway.",
                 "sqlite3", "psycopg")
    assert not [n for n in names if any(n == f or n.startswith(f) for f in forbidden)], names
    assert "os" not in names
    assert ".drive_changes" in names  # the projector is reused, not copied
    assert "class DriveChangeProjector" not in path.read_text(encoding="utf-8")
