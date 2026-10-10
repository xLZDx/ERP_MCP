"""S7 fix batch F1: regression tests for the cursor store and the baseline orchestrator.

Each test names the review finding it guards. Self-contained harness (no import of sibling tests).
"""
from __future__ import annotations

import asyncio
import gc
import time
import warnings
from dataclasses import dataclass, field
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
    CursorLoad,
    CursorReason,
    CursorRecord,
    CursorState,
    DriveCorpus,
    DriveCursorStore,
    DriveLease,
    build_event,
    cursor_key,
)
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_port import (
    DriveErrorCode,
    DrivePortError,
    DrivePortIdentity,
)
from business_ai_gateway.phase2.fakes import DEFAULT_SCOPE, WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import CommitResult, CursorView, PortError, Scope
from business_ai_gateway.phase2.resnapshot import ResnapshotReason, ResnapshotTracker

SCOPE = DEFAULT_SCOPE
H = "a" * 64
IDENT = DrivePortIdentity("account:A", "A", "conn-1")
CORPUS = DriveCorpus(None, ("ROOT-1",))
O = BaselineOutcome
R = CursorReason
BLOCK_CODES = ["SCOPE_REVOKED", "SCOPE_NOT_GRANTED", "PERMISSION_DENIED"]
KEY = cursor_key(IDENT)


class StrSub(str):
    pass


class LyingStr(str):
    """A str subclass whose equality always says 'equal'."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


class LyingInt(int):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = int.__hash__


class Wrap:
    """Cursor port wrapper: records calls; ``override[name]`` raises (exception) or returns (value)."""

    def __init__(self, inner: InMemoryLiving) -> None:
        self.inner, self.calls, self.override = inner, [], {}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def _go(self, name, args):
        self.calls.append(name)
        if name in self.override:
            value = self.override[name]
            if isinstance(value, BaseException):
                raise value
            return value
        return await getattr(self.inner, name)(*args)

    async def get_cursor(self, *a):
        return await self._go("get_cursor", a)

    async def create_cursor(self, *a):
        return await self._go("create_cursor", a)

    async def commit_cursor_page(self, *a):
        return await self._go("commit_cursor_page", a)


def chg(cid, fid, rev="r1", kind=DriveChangeKind.UPSERT, drive_id=None, mime="application/pdf"):
    return DriveChange(cid, fid, rev, kind, drive_id=drive_id, mime_type=mime)


class Lister:
    def __init__(self, log):
        self.log, self.pages, self.positions, self.on_call = log, {None: BaselinePage(())}, [], None

    async def list_page(self, identity, scope_epoch, position):
        self.log.append("baseline_list")
        self.positions.append(position)
        if self.on_call:
            await self.on_call()
        item = self.pages[position]
        if isinstance(item, BaseException):
            raise item
        return item


class LoggedPort:
    def __init__(self, fake, log):
        self.fake, self.log = fake, log

    async def get_start_page_token(self, identity, scope_epoch):
        self.log.append("get_start_page_token")
        return await self.fake.get_start_page_token(identity, scope_epoch)

    async def list_changes(self, identity, scope_epoch, page_token):
        self.log.append("list_changes")
        return await self.fake.list_changes(identity, scope_epoch, page_token)


@dataclass
class Env:
    living: InMemoryLiving
    cursors: Wrap
    lease: DriveLease
    tracker: ResnapshotTracker
    store: DriveCursorStore
    fake: FakeDrivePort
    log: list
    lister: Lister
    runner: DriveBaseline
    allowed: dict = field(default_factory=dict)

    def request(self, **over):
        args = {"identity": IDENT, "corpus": CORPUS, "drive_epoch": 0, "lease": self.lease,
                "scope_allowed": lambda fid: self.allowed.get(fid, True), "lister": self.lister}
        args.update(over)
        return BaselineRequest(**args)

    async def run(self, mode=DriveRunMode.INCREMENTAL, **over):
        return await self.runner.run(self.request(**over), mode)

    async def record(self) -> CursorRecord:
        view = await self.living.get_cursor(WORKER, SCOPE, KEY)
        return CursorRecord.decode(view.cursor_value)

    async def events(self) -> list[dict]:
        return [r.content for r in await self.living.list_outbox(WORKER, SCOPE)]

    async def init(self):
        await self.store.initialize(IDENT, CORPUS, 0, self.lease)


async def make_env(*, init: bool = False, start: str = "START-1") -> Env:
    living = InMemoryLiving()
    await living.enqueue_job(WORKER, SCOPE, UUID(int=1), "drive", H, "key-1")
    fence = await living.acquire_job(WORKER, SCOPE, UUID(int=1), "w1", 300)
    lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", fence, 0)
    tracker = ResnapshotTracker()
    cursors = Wrap(living)
    store = DriveCursorStore(cursors, tracker)
    fake = FakeDrivePort(start_page_token=start)
    log: list[str] = []
    env = Env(living, cursors, lease, tracker, store, fake, log, Lister(log),
              DriveBaseline(LoggedPort(fake, log), store))
    if init:
        await env.init()
    return env


# --- finding 1: revoked scope / lease loss must not become RETRYABLE --------------------------------


@pytest.mark.parametrize("code", BLOCK_CODES)
async def test_f1_get_cursor_blocking_code_is_resnapshot_and_marks_the_tracker(code):
    env = await make_env()
    env.cursors.override["get_cursor"] = PortError(code, "SECRET-detail")
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    assert (load.usable, load.state, load.reason) == (
        False, CursorState.RESNAPSHOT_REQUIRED, R.SCOPE_REVOKED)
    assert env.tracker.is_required(KEY)
    assert "SECRET" not in repr(load)


@pytest.mark.parametrize("code", BLOCK_CODES)
async def test_f1_create_cursor_blocking_code_is_resnapshot_and_marks_the_tracker(code):
    env = await make_env()
    env.cursors.override["create_cursor"] = PortError(code)
    load = await env.store.initialize(IDENT, CORPUS, 0, env.lease)
    assert (load.state, load.reason) == (CursorState.RESNAPSHOT_REQUIRED, R.SCOPE_REVOKED)
    assert env.tracker.is_required(KEY)


@pytest.mark.parametrize("code", BLOCK_CODES)
async def test_f1_commit_blocking_code_maps_to_scope_revoked(code):
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    env.cursors.override["commit_cursor_page"] = PortError(code)
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    result = await env.store.commit(IDENT, env.lease, load, new, [])
    assert (result.ok, result.reason) == (False, R.SCOPE_REVOKED)


async def test_f1_unknown_port_code_is_carried_but_stays_a_port_failure_without_marking():
    env = await make_env()
    env.cursors.override["get_cursor"] = PortError("BOOM")
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    assert (load.reason, load.port_code, load.state) == (R.PORT_FAILURE, "BOOM", None)
    assert not env.tracker.is_required(KEY)


@pytest.mark.parametrize("code", BLOCK_CODES)
async def test_f1_run_get_cursor_blocking_code_is_resnapshot_not_retryable(code):
    env = await make_env()
    env.cursors.override["get_cursor"] = PortError(code)
    result = await env.run()
    assert (result.outcome, result.reason) == (O.RESNAPSHOT_REQUIRED, R.SCOPE_REVOKED)
    assert env.tracker.is_required(KEY) and env.fake.call_count == 0


@pytest.mark.parametrize("code", BLOCK_CODES)
async def test_f1_run_commit_blocking_code_is_resnapshot_not_retryable(code):
    env = await make_env(init=True)
    env.cursors.override["commit_cursor_page"] = PortError(code)
    result = await env.run()
    assert (result.outcome, result.reason) == (O.RESNAPSHOT_REQUIRED, R.SCOPE_REVOKED)
    assert env.tracker.is_required(KEY)


@pytest.mark.parametrize(
    ("code", "outcome", "reason"),
    [
        ("STALE_JOB_FENCE", O.LEASE_LOST, R.LEASE_LOST),
        ("CONFLICTING_PAGE_REPLAY", O.CONFLICT, R.COMMIT_CONFLICT),
        ("PERMISSION_DENIED", O.RESNAPSHOT_REQUIRED, R.SCOPE_REVOKED),
        ("SCOPE_REVOKED", O.RESNAPSHOT_REQUIRED, R.SCOPE_REVOKED),
    ],
)
async def test_f1_reset_failures_keep_their_meaning_instead_of_retryable(code, outcome, reason):
    env = await make_env(init=True)
    env.cursors.override["commit_cursor_page"] = PortError(code)
    result = await env.run(DriveRunMode.RESNAPSHOT_START)
    assert (result.outcome, result.reason) == (outcome, reason)
    assert env.fake.call_count == 0


# --- finding 2: lease tenant must equal the identity tenant -------------------------------------------


async def test_f2_tenant_mismatch_is_invalid_request_with_zero_port_calls():
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    other = DriveLease(WORKER, Scope("OTHER-TENANT", "s1"), UUID(int=1), "w1", env.lease.fence, 0)
    env.cursors.calls.clear()
    assert (await env.store.load(IDENT, CORPUS, 0, other)).reason is R.INVALID_REQUEST
    assert (await env.store.initialize(IDENT, CORPUS, 0, other)).reason is R.INVALID_REQUEST
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    assert (await env.store.commit(IDENT, other, load, new, [])).reason is R.INVALID_REQUEST
    assert (await env.store.reset(IDENT, CORPUS, 0, other, load)).reason is R.INVALID_REQUEST
    assert await env.store.fail_closed(IDENT, other, load, R.TOKEN_REPEATED) is False
    assert env.cursors.calls == []


async def test_f2_equal_guid_tenants_in_different_spelling_are_accepted():
    env = await make_env()
    guid = "abcdef01-2345-6789-abcd-ef0123456789"
    ident = DrivePortIdentity("account:A", "{" + guid.upper() + "}", "conn-1")
    assert ident.tenant == guid
    lease = DriveLease(WORKER, Scope(guid.upper(), "s1"), UUID(int=1), "w1", 1, 0)
    env.cursors.override["get_cursor"] = None
    assert (await env.store.load(ident, CORPUS, 0, lease)).reason is R.CURSOR_MISSING


# --- finding 3: commit must be bound to the loaded record ----------------------------------------------


async def test_f3_forged_load_cannot_overwrite_a_stored_gap():
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    assert await env.store.fail_closed(IDENT, env.lease, load, R.TOKEN_REPEATED)
    gap_view = await env.living.get_cursor(WORKER, SCOPE, KEY)
    fresh = DriveCursorStore.fresh_record(IDENT, CORPUS, 0)
    forged = CursorLoad(True, fresh.state, None, fresh, gap_view.version, gap_view.cursor_value)
    env.cursors.calls.clear()
    new = fresh.evolve(state=CursorState.BASELINING, token="T1")
    result = await env.store.commit(IDENT, env.lease, forged, new, [])
    assert (result.ok, result.reason) == (False, R.INVALID_REQUEST)
    assert env.cursors.calls == []
    assert CursorRecord.decode((await env.living.get_cursor(WORKER, SCOPE, KEY)).cursor_value).state \
        is CursorState.GAP


async def test_f3_commit_refuses_inconsistent_loads_and_foreign_new_records():
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    rec = load.record
    good = rec.evolve(state=CursorState.BASELINING, token="T1")
    other_ident = DrivePortIdentity("drive:B", "A", "conn-1")
    cases = [
        CursorLoad(True, CursorState.LIVE, None, rec, load.version, load.raw_value),  # state lies
        CursorLoad(True, rec.state, None, rec, load.version, load.raw_value + " "),  # raw lies
        CursorLoad(True, rec.state, None, rec, load.version, "x"),
    ]
    for bad_load in cases:
        env.cursors.calls.clear()
        assert (await env.store.commit(IDENT, env.lease, bad_load, good, [])).reason \
            is R.INVALID_REQUEST
        assert env.cursors.calls == []
    for new in (good.evolve(corpus="b" * 64), good.evolve(epoch=1), good.evolve(tenant="Z"),
                good.evolve(connection_id="conn-2"), good.evolve(namespace="account:Z")):
        env.cursors.calls.clear()
        assert (await env.store.commit(IDENT, env.lease, load, new, [])).reason is R.INVALID_REQUEST
        assert env.cursors.calls == []
    env.cursors.calls.clear()  # the load belongs to another identity than the one passed
    assert (await env.store.commit(other_ident, env.lease, load, good, [])).reason \
        is R.INVALID_REQUEST
    assert env.cursors.calls == []
    assert (await env.store.commit(IDENT, env.lease, load, good, [])).ok


# --- finding 4: public store methods never raise -----------------------------------------------------------


async def test_f4_lying_equality_in_the_cursor_view_is_corrupt_not_trusted():
    env = await make_env(init=True)
    raw = (await env.living.get_cursor(WORKER, SCOPE, KEY)).cursor_value
    for view in (
        CursorView(LyingStr(KEY + "-other"), raw, 0, 0, None),
        CursorView(KEY, raw, 0, LyingInt(7), None),
        CursorView(KEY, raw, 0, False, None),
        CursorView(KEY, raw, True, 0, None),
        object.__new__(CursorView),
    ):
        env.cursors.override["get_cursor"] = view
        load = await env.store.load(IDENT, CORPUS, 0, env.lease)
        assert (load.usable, load.reason) == (False, R.CURSOR_CORRUPT)


async def test_f4_runtime_errors_from_the_port_are_fixed_refusals_and_leak_nothing():
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    boom = RuntimeError("SECRET-xyz")
    for name in ("get_cursor", "create_cursor", "commit_cursor_page"):
        env.cursors.override[name] = boom
    res_load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    res_init = await env.store.initialize(IDENT, CORPUS, 0, env.lease)
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    res_commit = await env.store.commit(IDENT, env.lease, load, new, [])
    res_reset = await env.store.reset(IDENT, CORPUS, 0, env.lease, load)
    marked = await env.store.fail_closed(IDENT, env.lease, load, R.TOKEN_REPEATED)
    assert res_load.reason is R.PORT_FAILURE and res_init.reason is R.PORT_FAILURE
    assert res_commit.reason is R.PORT_FAILURE and res_reset.reason is R.PORT_FAILURE
    assert marked is False and env.tracker.is_required(KEY)
    assert "SECRET" not in repr((res_load, res_init, res_commit, res_reset))


async def test_f4_forged_objects_are_fixed_refusals_and_touch_no_port():
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    lying_ident = object.__new__(DrivePortIdentity)
    for name, value in (("namespace", LyingStr("account:A")), ("tenant", "A"),
                        ("connection_id", "conn-1")):
        object.__setattr__(lying_ident, name, value)
    forged_ident = object.__new__(DrivePortIdentity)
    forged_lease = object.__new__(DriveLease)
    forged_corpus = object.__new__(DriveCorpus)
    forged_load = object.__new__(CursorLoad)
    forged_rec = object.__new__(CursorRecord)
    env.cursors.calls.clear()
    for ident, corpus, lease in ((forged_ident, CORPUS, env.lease), (lying_ident, CORPUS, env.lease),
                                 (IDENT, forged_corpus, env.lease), (IDENT, CORPUS, forged_lease)):
        assert (await env.store.load(ident, corpus, 0, lease)).reason is R.INVALID_REQUEST
        assert (await env.store.initialize(ident, corpus, 0, lease)).reason is R.INVALID_REQUEST
        assert (await env.store.reset(ident, corpus, 0, lease, load)).reason is R.INVALID_REQUEST
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    for ident, lease, ld, rec in ((forged_ident, env.lease, load, new), (IDENT, forged_lease, load, new),
                                  (IDENT, env.lease, forged_load, new), (IDENT, env.lease, load, forged_rec)):
        assert (await env.store.commit(ident, lease, ld, rec, [])).reason is R.INVALID_REQUEST
    assert (await env.store.reset(IDENT, CORPUS, 0, env.lease, forged_load)).reason is R.INVALID_REQUEST
    assert await env.store.fail_closed(forged_ident, env.lease, load, R.TOKEN_REPEATED) is False
    assert await env.store.fail_closed(IDENT, forged_lease, load, R.TOKEN_REPEATED) is False
    assert await env.store.fail_closed(IDENT, env.lease, forged_load, R.TOKEN_REPEATED) is False
    assert env.cursors.calls == []


async def test_f4_forged_port_results_are_port_failures():
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    for forged in (object.__new__(CommitResult), None, "x", CommitResult(True, False)):
        env.cursors.override["commit_cursor_page"] = forged
        assert (await env.store.commit(IDENT, env.lease, load, new, [])).reason is R.PORT_FAILURE


async def test_f4_cancellation_is_never_swallowed():
    env = await make_env(init=True)
    env.cursors.override["get_cursor"] = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await env.store.load(IDENT, CORPUS, 0, env.lease)


# --- finding 5: the baseline enforces the corpus ----------------------------------------------------------


async def test_f5_async_scope_callback_is_refused_at_construction():
    env = await make_env(init=True)

    async def aio(fid):
        return True

    class CallAsync:
        async def __call__(self, fid):
            return True

    for cb in (aio, CallAsync()):
        with pytest.raises(ValueError, match="BASELINE_SCOPE_CALLBACK_ASYNC"):
            env.request(scope_allowed=cb)

    def returns_coroutine(fid):
        return aio(fid)

    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await env.run(scope_allowed=returns_coroutine)
        gc.collect()
    assert (result.outcome, result.reason) == (O.GAP, R.MEMBERSHIP_UNVERIFIED)
    assert not [w for w in caught if "never awaited" in str(w.message)]


async def test_f5_account_namespace_with_a_drive_corpus_admits_only_that_drive():
    env = await make_env(init=False)
    corpus = DriveCorpus("D1", ("ROOT-1",))
    await env.store.initialize(IDENT, corpus, 0, env.lease)
    env.lister.pages = {None: BaselinePage((
        BaselineItem("IN", "r1", drive_id="D1"), BaselineItem("FOREIGN", "r1", drive_id="D2"),
        BaselineItem("NODRIVE", "r1"), BaselineItem("OUT", "r1", drive_id="D1")))}
    env.allowed["OUT"] = False  # in the drive but outside the corpus roots (membership proof says no)
    env.fake.script_page(
        "START-1", (chg("c1", "IN2", drive_id="D1"), chg("c2", "FOREIGN2", drive_id="D2"),
                    chg("c3", "NODRIVE2", drive_id=None)), new_start_page_token="TOK-2")
    result = await env.run(corpus=corpus)
    assert result.outcome is O.LIVE
    assert {c.file_id for c in result.candidates} == {"IN", "IN2"}
    assert {e["file_id"] for e in await env.events() if e["event_kind"] == "DRIVE_CANDIDATE"} \
        == {"IN", "IN2"}
    assert result.denied_changes >= 4  # FOREIGN, NODRIVE, OUT (membership) and the two catch-up ones


# --- finding 6: a first INCREMENTAL run on a fresh connection does not poison the tracker -------------


async def test_f6_incremental_first_run_on_a_fresh_connection_does_not_mark_the_tracker():
    env = await make_env(init=False)
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    result = await env.run()
    assert result.outcome is O.LIVE and result.complete
    assert not env.tracker.is_required(KEY)
    assert (await env.record()).token == "TOK-2"


async def test_f6_a_failed_first_run_leaves_the_tracker_clean_and_is_resumable():
    env = await make_env(init=False)
    env.lister.pages = {None: DrivePortError(DriveErrorCode.TRANSIENT)}
    first = await env.run()
    assert (first.outcome, first.reason) == (O.RETRYABLE, R.TRANSIENT)
    assert not env.tracker.is_required(KEY)
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    assert (await env.run()).outcome is O.LIVE


# --- finding 7: a snapshot tombstones what left the scope while the cursor was lost -------------------------


async def test_f7_resnapshot_emits_a_membership_tombstone_for_a_file_that_left_scope():
    env = await make_env(init=True)
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"), BaselineItem("F2", "r1")))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    first = await env.run()
    assert first.outcome is O.LIVE and {c.file_id for c in first.candidates} == {"F1", "F2"}
    env.tracker.require(KEY, ResnapshotReason.OPERATOR, 0)
    env.allowed["F1"] = False  # F1 left the scope while nobody was watching
    env.fake.script_start_token("START-2")
    env.fake.script_page("START-2", new_start_page_token="TOK-3")
    second = await env.run(DriveRunMode.RESNAPSHOT_START)
    assert second.outcome is O.LIVE and second.snapshot_cleared and not second.clear_failed
    assert {c.file_id for c in second.candidates} == {"F2"}
    assert [(t.file_id, t.reason) for t in second.tombstones] == [("F1", "MEMBERSHIP_CHANGED")]
    tombs = [e for e in await env.events() if e["event_kind"] == "DRIVE_TOMBSTONE"]
    assert [(e["file_id"], e["reason"]) for e in tombs] == [("F1", "MEMBERSHIP_CHANGED")]


async def test_f7_a_first_incremental_baseline_still_makes_no_tombstone_for_a_refused_item():
    env = await make_env(init=True)
    env.allowed["F2"] = False
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"), BaselineItem("F2", "r1")))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    result = await env.run()
    assert result.outcome is O.LIVE and result.tombstones == () and result.denied_changes == 1
    assert [e for e in await env.events() if e["event_kind"] == "DRIVE_TOMBSTONE"] == []


# --- finding 8: a page bigger than max_rows must not livelock ---------------------------------------------


async def test_f8_a_single_page_over_max_rows_still_progresses():
    env = await make_env(init=True)
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"), BaselineItem("F2", "r1")))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    result = await env.run(limits=BaselineLimits(max_pages=10, max_rows=1))
    assert result.outcome is O.LIVE and result.rows == 2


async def test_f8_second_page_hits_the_row_limit_and_the_rerun_resumes_and_finishes():
    env = await make_env(init=True)
    env.lister.pages = {
        None: BaselinePage((BaselineItem("F1", "r1"), BaselineItem("F2", "r1")), "p2"),
        "p2": BaselinePage((BaselineItem("F3", "r1"), BaselineItem("F4", "r1"))),
    }
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    limits = BaselineLimits(max_pages=10, max_rows=1)
    first = await env.run(limits=limits)
    assert (first.outcome, first.reason, first.rows) == (O.LIMIT_REACHED, R.ROW_LIMIT, 2)
    second = await env.run(limits=limits)
    assert second.outcome is O.LIVE and second.rows == 2
    assert len([e for e in await env.events() if e["event_kind"] == "DRIVE_CANDIDATE"]) == 4


# --- finding 9: tracker.complete failing after the cursor is LIVE -----------------------------------------


async def test_f9_complete_failure_after_live_is_reported_as_a_flag_not_a_refusal():
    env = await make_env(init=True)
    env.tracker.require(KEY, ResnapshotReason.OPERATOR, 0)

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET-complete")

    env.tracker.complete = boom
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    result = await env.run(DriveRunMode.RESNAPSHOT_START)
    assert result.outcome is O.LIVE and result.state is CursorState.LIVE and result.complete
    assert result.clear_failed and not result.snapshot_cleared
    assert env.tracker.is_required(KEY)
    assert (await env.record()).state is CursorState.LIVE
    assert "SECRET" not in repr(result)


# --- finding 10: requalify folders are de-duplicated in linear time and capped ------------------------------


async def test_f10_ten_thousand_removed_changes_are_collected_in_bounded_time_without_duplicates():
    env = await make_env(init=True)
    pages = 20
    for p in range(pages):
        token = "START-1" if p == 0 else f"N{p}"
        changes = tuple(
            chg(f"c{p}-{i}", "FOLD-0-0" if (p == 1 and i == 0) else f"FOLD-{p}-{i}", None,
                DriveChangeKind.REMOVED, mime=None)
            for i in range(500))
        if p == pages - 1:
            env.fake.script_page(token, changes, new_start_page_token="TOK-END")
        else:
            env.fake.script_page(token, changes, next_page_token=f"N{p + 1}")
    started = time.perf_counter()
    result = await env.run()
    elapsed = time.perf_counter() - started
    assert result.outcome is O.LIVE and result.rows == 10_000
    ids = result.requalify_folder_ids
    assert len(ids) == len(set(ids)) == 9_999 and ids[0] == "FOLD-0-0"
    assert not result.requalify_truncated
    assert elapsed < 60


async def test_f10_requalify_list_is_capped_and_says_so(monkeypatch):
    monkeypatch.setattr(drive_baseline, "_MAX_REQUALIFY", 5)
    env = await make_env(init=True)
    changes = tuple(chg(f"c{i}", f"FOLD-{i}", None, DriveChangeKind.REMOVED, mime=None)
                    for i in range(8))
    env.fake.script_page("START-1", changes, new_start_page_token="TOK-2")
    result = await env.run()
    assert result.outcome is O.LIVE
    assert result.requalify_folder_ids == tuple(f"FOLD-{i}" for i in range(5))
    assert result.requalify_truncated


# --- finding 11: build_event ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["event_id", "event_kind", "namespace", "tenant", "connection_id", "digest"])
def test_f11_build_event_rejects_reserved_keys(key):
    with pytest.raises(ValueError, match="DRIVE_EVENT_INVALID"):
        build_event(IDENT, "K", "c1", **{key: "x"})


@pytest.mark.parametrize(
    "bad", [1, True, 1.5, {"a": 1}, ["a", 1], ("a",), StrSub("x"), [StrSub("a")], b"x"])
def test_f11_build_event_rejects_bad_value_types(bad):
    with pytest.raises(ValueError, match="DRIVE_EVENT_INVALID"):
        build_event(IDENT, "K", "c1", file_id=bad)


def test_f11_build_event_still_accepts_str_none_and_list_of_str():
    event = build_event(IDENT, "K", "c1", a="x", b=None, c=["p", "q"])
    assert event["a"] == "x" and event["b"] is None and event["c"] == ["p", "q"]
    assert len(event["digest"]) == 64


# --- finding 12: candidate connection id ------------------------------------------------------------------------


async def test_f12_candidate_connection_id_is_the_identity_connection_id_like_the_events():
    env = await make_env(init=True)
    env.lister.pages = {None: BaselinePage((BaselineItem("F1", "r1"),))}
    env.fake.script_page("START-1", (chg("c1", "F2"),), new_start_page_token="TOK-2")
    result = await env.run()
    assert {c.connection_id for c in result.candidates} == {IDENT.connection_id}
    assert {e["connection_id"] for e in await env.events()} == {IDENT.connection_id}
    assert IDENT.connection_id != KEY


# --- finding 13: total helpers ----------------------------------------------------------------------------------


def test_f13_check_baseline_order_is_total():
    def boom():
        raise RuntimeError("SECRET")
        yield  # pragma: no cover

    class Hostile:
        def __iter__(self):
            raise RuntimeError("SECRET")

    assert check_baseline_order(boom()) is False
    assert check_baseline_order(Hostile()) is False


async def test_f13_request_with_a_hostile_lister_is_the_fixed_validation_error():
    env = await make_env()

    class HostileLister:
        def __getattr__(self, name):
            raise RuntimeError("SECRET")

    with pytest.raises(ValueError, match="BASELINE_REQUEST_INVALID") as err:
        env.request(lister=HostileLister())
    assert "SECRET" not in str(err.value)


# --- finding 14: concurrent runners and list_changes error mapping ---------------------------------------


class RacePort:
    """Port whose first ``list_changes`` result is returned only after another runner has run."""

    def __init__(self, fake, hook):
        self.fake, self.hook = fake, hook

    async def get_start_page_token(self, identity, scope_epoch):
        return await self.fake.get_start_page_token(identity, scope_epoch)

    async def list_changes(self, identity, scope_epoch, page_token):
        page = await self.fake.list_changes(identity, scope_epoch, page_token)
        hook, self.hook = self.hook, None
        if hook is not None:
            await hook()
        return page


@pytest.mark.parametrize(
    ("b_change", "b_token", "outcome", "reason"),
    [
        ("c-other", "TOK-2", O.CONFLICT, R.COMMIT_CONFLICT),   # same advance, different page digest
        ("c-other", "TOK-B", O.RETRYABLE, R.STALE_CURSOR),     # the cursor moved somewhere else
        ("c-mine", "TOK-2", O.LIVE, None),                     # identical page: idempotent replay
    ],
)
async def test_f14_second_runner_advancing_between_load_and_commit_never_duplicates_events(
        b_change, b_token, outcome, reason):
    env = await make_env(init=True)
    env.fake.script_page("START-1", (chg("c-mine", "F1"),), new_start_page_token="TOK-2")
    fake_b = FakeDrivePort(start_page_token="START-1")
    fake_b.script_page("START-1", (chg(b_change, "F1"),), new_start_page_token=b_token)
    runner_b = DriveBaseline(LoggedPort(fake_b, []), env.store)
    seen_b: list = []

    async def hook():
        seen_b.append(await runner_b.run(env.request()))

    runner_a = DriveBaseline(RacePort(env.fake, hook), env.store)
    result = await runner_a.run(env.request(), DriveRunMode.INCREMENTAL)
    assert seen_b and seen_b[0].outcome is O.LIVE
    assert (result.outcome, result.reason) == (outcome, reason)
    ids = [e["change_id"] for e in await env.events() if e["event_kind"] == "DRIVE_CANDIDATE"
           and not e["change_id"].startswith("baseline|")]
    assert ids == [b_change]  # committed exactly once, by the runner that won
    assert (await env.record()).token == b_token


@pytest.mark.parametrize(
    ("code", "outcome", "reason", "state"),
    [
        (DriveErrorCode.INVALID_GRANT, O.AUTH_REQUIRED, R.AUTH_INVALID_GRANT, CursorState.CATCHING_UP),
        (DriveErrorCode.AUTH_REQUIRED, O.AUTH_REQUIRED, R.AUTH_REQUIRED, CursorState.CATCHING_UP),
        (DriveErrorCode.RATE_LIMITED, O.RETRYABLE, R.RATE_LIMITED, CursorState.CATCHING_UP),
        (DriveErrorCode.TRANSIENT, O.RETRYABLE, R.TRANSIENT, CursorState.CATCHING_UP),
        (DriveErrorCode.FORBIDDEN_HISTORY, O.REFUSED, R.PORT_UNEXPECTED, CursorState.CATCHING_UP),
        (DriveErrorCode.NOT_FOUND, O.RESNAPSHOT_REQUIRED, R.TOKEN_NOT_FOUND,
         CursorState.RESNAPSHOT_REQUIRED),
        (DriveErrorCode.SCOPE_EPOCH_STALE, O.RESNAPSHOT_REQUIRED, R.SCOPE_EPOCH_CHANGED,
         CursorState.RESNAPSHOT_REQUIRED),
    ],
)
async def test_f14_list_changes_errors_after_page_one_keep_page_one_committed(
        code, outcome, reason, state):
    env = await make_env(init=True)
    env.fake.script_page("START-1", (chg("c1", "F1"),), next_page_token="N2")
    env.fake.force_error("list_changes", code, after=1)
    result = await env.run()
    assert (result.outcome, result.reason) == (outcome, reason) and not result.complete
    rec = await env.record()
    assert rec.token == "N2" and rec.state is state  # page 1's cursor advance survived
    assert [e["change_id"] for e in await env.events()] == ["c1"]
    assert env.tracker.is_required(KEY) is (outcome is O.RESNAPSHOT_REQUIRED)


# --- livelock: a page whose events exceed the port batch limit -------------------------------------------


async def test_big_baseline_page_over_the_event_limit_is_a_fixed_non_retryable_refusal():
    env = await make_env(init=True)
    env.lister.pages = {None: BaselinePage(tuple(BaselineItem(f"F{i}", "r1") for i in range(1001)))}
    result = await env.run()
    assert (result.outcome, result.reason) == (O.REFUSED, R.PAGE_TOO_LARGE)
    assert await env.events() == []
    assert (await env.record()).state is CursorState.BASELINING


async def test_baseline_page_at_exactly_the_event_limit_commits():
    env = await make_env(init=True)
    env.lister.pages = {None: BaselinePage(tuple(BaselineItem(f"F{i}", "r1") for i in range(1000)))}
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    result = await env.run()
    assert result.outcome is O.LIVE and len(await env.events()) == 1000


async def test_catchup_page_whose_extra_tombstone_and_requalify_events_pass_the_limit_is_refused():
    env = await make_env(init=True)
    changes = tuple(chg(f"c{i}", f"FOLD-{i}", None, DriveChangeKind.REMOVED, mime=None)
                    for i in range(1000))  # 1000 tombstones + 1 requalify event
    env.fake.script_page("START-1", changes, new_start_page_token="TOK-2")
    result = await env.run()
    assert (result.outcome, result.reason) == (O.REFUSED, R.PAGE_TOO_LARGE)
    assert await env.events() == []
    assert (await env.record()).token == "START-1"


async def test_store_commit_refuses_too_many_events_before_any_port_call():
    env = await make_env(init=True)
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    env.cursors.calls.clear()
    events = [build_event(IDENT, "K", f"c{i}") for i in range(1001)]
    result = await env.store.commit(IDENT, env.lease, load, new, events)
    assert (result.ok, result.reason) == (False, R.PAGE_TOO_LARGE)
    assert env.cursors.calls == []
