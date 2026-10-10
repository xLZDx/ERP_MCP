"""S7 GPT-PM remediation (stream H3): M05 original snapshot-generation fence, M09 no port text leak."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest

from business_ai_gateway.phase2.drive_baseline import (
    BaselineItem,
    BaselineLimits,
    BaselineOutcome,
    BaselinePage,
    BaselineRequest,
    DriveBaseline,
    DriveRunMode,
)
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
from business_ai_gateway.phase2.drive_port import DrivePortIdentity
from business_ai_gateway.phase2.fakes import DEFAULT_SCOPE, WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import PortError
from business_ai_gateway.phase2.resnapshot import ResnapshotReason, ResnapshotTracker

SCOPE = DEFAULT_SCOPE
H = "a" * 64
IDENT = DrivePortIdentity("account:A", "A", "conn-1")
CORPUS = DriveCorpus(None, ("ROOT-1",))
KEY = cursor_key(IDENT)
O = BaselineOutcome
SECRET = "SECRET-MARKER-7f3a"
TOKEN_SECRET = "OPAQUE-TOKEN-9c1d"


class StrSub(str):
    pass


class Lister:
    def __init__(self, pages: dict) -> None:
        self.pages, self.positions = pages, []

    async def list_page(self, identity, scope_epoch, position):
        self.positions.append(position)
        return self.pages[position]


class HostileCursors:
    """Delegates to the in-memory port; raises a hostile PortError from one named method."""

    def __init__(self, inner: InMemoryLiving, method: str | None = None, code=SECRET) -> None:
        self.inner, self.method, self.code = inner, method, code

    def __getattr__(self, name):
        target = getattr(self.inner, name)
        if name != self.method:
            return target

        async def boom(*args, **kwargs):
            raise PortError(self.code, f"detail {SECRET}")

        return boom


@dataclass
class Env:
    living: InMemoryLiving
    lease: DriveLease
    tracker: ResnapshotTracker
    store: DriveCursorStore
    fake: FakeDrivePort
    lister: Lister
    runner: DriveBaseline

    async def run(self, mode=DriveRunMode.INCREMENTAL, **over):
        args = {"identity": IDENT, "corpus": CORPUS, "drive_epoch": 0, "lease": self.lease,
                "scope_allowed": lambda fid: True, "lister": self.lister}
        args.update(over)
        return await self.runner.run(BaselineRequest(**args), mode)

    async def record(self) -> CursorRecord:
        view = await self.living.get_cursor(WORKER, SCOPE, KEY)
        return CursorRecord.decode(view.cursor_value)


async def make_env(*, tracker=None, living=None) -> Env:
    if living is None:
        living = InMemoryLiving()
        await living.enqueue_job(WORKER, SCOPE, UUID(int=1), "drive", H, "key-1")
        fence = await living.acquire_job(WORKER, SCOPE, UUID(int=1), "w1", 300)
        lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", fence, 0)
    else:
        lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", 1, 0)
    tracker = tracker or ResnapshotTracker()
    store = DriveCursorStore(living, tracker)
    fake = FakeDrivePort(start_page_token="START-1")
    fake.script_page("START-1", new_start_page_token="TOK-2")
    lister = Lister({
        None: BaselinePage((BaselineItem("F1", "r1"),), "p2"),
        "p2": BaselinePage((BaselineItem("F2", "r1"),)),
    })
    return Env(living, lease, tracker, store, fake, lister, DriveBaseline(fake, store))


# --- M05 --------------------------------------------------------------------------------------------


async def test_m05_a_later_requirement_survives_the_older_resumed_baseline():
    env = await make_env()
    limited = await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    assert limited.outcome is O.LIMIT_REACHED
    # a requirement recorded AFTER the original baseline began
    env.tracker.require(KEY, ResnapshotReason.SCOPE_EPOCH_CHANGED, 0)
    done = await env.run(DriveRunMode.RESNAPSHOT_CONTINUE)
    assert done.outcome is O.LIMIT_REACHED or done.outcome is O.LIVE
    assert not done.snapshot_cleared
    assert env.tracker.is_required(KEY)


async def test_m05_control_requirement_recorded_before_the_baseline_clears_normally():
    env = await make_env()
    env.tracker.require(KEY, ResnapshotReason.CURSOR_MISSING, 0)
    limited = await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    assert limited.outcome is O.LIMIT_REACHED
    done = await env.run(DriveRunMode.RESNAPSHOT_CONTINUE)
    assert done.outcome is O.LIVE and done.snapshot_cleared
    assert not env.tracker.is_required(KEY)
    assert env.fake.count("get_start_page_token") == 1  # genuinely continued, not restarted


async def test_m05_the_original_marker_is_persisted_in_the_cursor_record():
    env = await make_env()
    env.tracker.require(KEY, ResnapshotReason.CURSOR_MISSING, 0)
    await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    rec = await env.record()
    assert rec.state is CursorState.BASELINING and env.tracker.token_from_marker(rec.snap) == 1
    assert CursorRecord.decode(rec.encode()) == rec


async def test_m05_a_record_without_a_marker_restarts_from_a_genuinely_new_snapshot():
    env = await make_env()
    env.tracker.require(KEY, ResnapshotReason.CURSOR_MISSING, 0)
    await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    rec = await env.record()
    view = await env.living.get_cursor(WORKER, SCOPE, KEY)
    legacy = rec.evolve(snap=None)  # a v1 record: the marker is lost
    assert '"snap"' not in legacy.encode()
    await env.living.commit_cursor_page(
        WORKER, SCOPE, KEY, env.lease.job_id, "w1", env.lease.fence, view.cursor_value,
        view.version, 0, legacy.encode(), [])
    env.fake.script_page("START-1", new_start_page_token="TOK-2")
    done = await env.run(DriveRunMode.RESNAPSHOT_CONTINUE)
    assert done.outcome is O.LIVE and done.snapshot_cleared
    assert env.fake.count("get_start_page_token") == 2  # restarted, not continued
    assert (await env.record()).snap is not None


async def test_m05_a_foreign_marker_from_another_tracker_restarts():
    env = await make_env()
    env.tracker.require(KEY, ResnapshotReason.CURSOR_MISSING, 0)
    env.tracker.require("other-key", ResnapshotReason.CURSOR_MISSING, 0)
    await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    # a restarted process: its tracker's order counter is behind the persisted marker
    fresh = ResnapshotTracker()
    fresh.require(KEY, ResnapshotReason.CURSOR_MISSING, 0)
    env2 = await make_env(tracker=fresh, living=env.living)
    env2.lease = env.lease
    env2.fake.script_page("START-1", new_start_page_token="TOK-2")
    rec = await env.record()
    assert rec.snap is not None
    forged = rec.evolve(snap=rec.snap + 50)
    view = await env.living.get_cursor(WORKER, SCOPE, KEY)
    await env.living.commit_cursor_page(
        WORKER, SCOPE, KEY, env.lease.job_id, "w1", env.lease.fence, view.cursor_value,
        view.version, 0, forged.encode(), [])
    done = await env2.run(DriveRunMode.RESNAPSHOT_CONTINUE)
    assert done.outcome is O.LIVE
    assert env2.fake.count("get_start_page_token") == 1  # restarted from a new snapshot


@pytest.mark.parametrize("snap", [True, -1, 2**63, "1", 1.0])
def test_m05_marker_validation_is_exact(snap):
    base = {"state": CursorState.BASELINING, "namespace": "account:A", "tenant": "t",
            "connection_id": "c", "corpus": "0" * 64, "epoch": 0, "token": "T"}
    with pytest.raises(ValueError, match="DRIVE_CURSOR_RECORD_INVALID"):
        CursorRecord(**base, snap=snap)
    with pytest.raises(ValueError, match="DRIVE_CURSOR_RECORD_INVALID"):
        CursorRecord(**{**base, "state": CursorState.UNINITIALIZED, "token": None}, snap=1)


def test_m05_v2_record_is_canonical_and_v1_without_a_marker_is_unchanged():
    base = {"state": CursorState.BASELINING, "namespace": "account:A", "tenant": "t",
            "connection_id": "c", "corpus": "0" * 64, "epoch": 0, "token": "T"}
    v1 = CursorRecord(**base)
    v2 = CursorRecord(**base, snap=3)
    assert '"v":1' in v1.encode() and '"v":2' in v2.encode()
    assert CursorRecord.decode(v1.encode()) == v1 and CursorRecord.decode(v2.encode()) == v2
    assert CursorRecord.decode(v2.encode().replace('"v":2', '"v":1')) is None
    assert CursorRecord.decode(v2.encode().replace('"snap":3', '"snap":null')) is None


# --- M09 --------------------------------------------------------------------------------------------


def _assert_clean(*objs):
    for obj in objs:
        for text in (repr(obj), str(obj)):
            assert SECRET not in text and TOKEN_SECRET not in text


@pytest.mark.parametrize("method", ["get_cursor", "create_cursor", "commit_cursor_page"])
@pytest.mark.parametrize("code", [SECRET, StrSub(SECRET), SECRET + ": more"])
async def test_m09_hostile_port_error_text_never_reaches_a_public_result(method, code):
    inner = InMemoryLiving()
    await inner.enqueue_job(WORKER, SCOPE, UUID(int=1), "drive", H, "key-1")
    fence = await inner.acquire_job(WORKER, SCOPE, UUID(int=1), "w1", 300)
    lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", fence, 0)
    tracker = ResnapshotTracker()
    store = DriveCursorStore(HostileCursors(inner, method, code), tracker)
    fake = FakeDrivePort(start_page_token=TOKEN_SECRET)
    fake.script_page(TOKEN_SECRET, new_start_page_token="TOK-2")
    lister = Lister({None: BaselinePage((BaselineItem("F1", "r1"),))})
    runner = DriveBaseline(fake, store)
    req = BaselineRequest(IDENT, CORPUS, 0, lease, lambda f: True, lister)
    results = [
        await store.load(IDENT, CORPUS, 0, lease),
        await store.initialize(IDENT, CORPUS, 0, lease),
        await runner.run(req, DriveRunMode.INCREMENTAL),
        await runner.run(req, DriveRunMode.RESNAPSHOT_START),
    ]
    load = results[0]
    assert load.port_code is None or load.port_code != SECRET
    for res in results:
        _assert_clean(res)
        port_code = getattr(res, "port_code", None)
        assert port_code is None or port_code in {"STALE_JOB_FENCE", "CURSOR_NOT_FOUND"}


async def test_m09_store_commit_with_hostile_code_is_a_fixed_reason():
    inner = InMemoryLiving()
    await inner.enqueue_job(WORKER, SCOPE, UUID(int=1), "drive", H, "key-1")
    fence = await inner.acquire_job(WORKER, SCOPE, UUID(int=1), "w1", 300)
    lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", fence, 0)
    store = DriveCursorStore(HostileCursors(inner, "commit_cursor_page"), ResnapshotTracker())
    load = await store.initialize(IDENT, CORPUS, 0, lease)
    res = await store.commit(IDENT, lease, load, load.record.evolve(
        state=CursorState.BASELINING, token=TOKEN_SECRET), [])
    assert (res.ok, res.reason) == (False, CursorReason.PORT_FAILURE)
    _assert_clean(res)


async def test_m09_known_port_codes_are_still_reported_and_unknown_become_none():
    inner = InMemoryLiving()
    await inner.enqueue_job(WORKER, SCOPE, UUID(int=1), "drive", H, "key-1")
    fence = await inner.acquire_job(WORKER, SCOPE, UUID(int=1), "w1", 300)
    lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", fence, 0)
    known = await DriveCursorStore(
        HostileCursors(inner, "get_cursor", "INVALID_LEASE"), ResnapshotTracker()
    ).load(IDENT, CORPUS, 0, lease)
    unknown = await DriveCursorStore(
        HostileCursors(inner, "get_cursor", SECRET), ResnapshotTracker()
    ).load(IDENT, CORPUS, 0, lease)
    assert known.port_code == "INVALID_LEASE" and type(known.port_code) is str
    assert unknown.port_code is None and unknown.reason is CursorReason.PORT_FAILURE


async def test_m09_opaque_cursor_values_are_redacted_from_reprs():
    env = await make_env()
    env.fake = FakeDrivePort(start_page_token=TOKEN_SECRET)
    env.fake.script_page(TOKEN_SECRET, new_start_page_token="TOK-2")
    env.runner = DriveBaseline(env.fake, env.store)
    await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    rec = await env.record()
    assert rec.token == TOKEN_SECRET
    load = await env.store.load(IDENT, CORPUS, 0, env.lease)
    assert TOKEN_SECRET in load.raw_value  # the value itself is intact ...
    _assert_clean(rec, load)  # ... but never printed
    rec_pos = rec.evolve(pos=TOKEN_SECRET, seen=(TOKEN_SECRET,))
    _assert_clean(rec_pos)
