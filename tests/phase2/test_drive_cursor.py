"""S7/E2: durable fail-closed Drive cursor record over the in-memory cursor CAS port (TC107, TC108)."""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest

from business_ai_gateway.phase2 import drive_cursor
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
    dedup_key,
    fail_closed_state,
    is_allowed_transition,
)
from business_ai_gateway.phase2.drive_port import DrivePortIdentity
from business_ai_gateway.phase2.fakes import DEFAULT_SCOPE, WORKER, InMemoryLiving
from business_ai_gateway.phase2.resnapshot import ResnapshotReason, ResnapshotTracker

SCOPE = DEFAULT_SCOPE
H = "a" * 64
IDENT_A = DrivePortIdentity("account:A", "A", "conn-1")
IDENT_B = DrivePortIdentity("drive:B", "A", "conn-1")
CORPUS = DriveCorpus(None, ("ROOT-1",))
OTHER_CORPUS = DriveCorpus(None, ("ROOT-2",))


class StrSub(str):
    pass


@dataclass
class Env:
    living: InMemoryLiving
    lease: DriveLease
    tracker: ResnapshotTracker
    store: DriveCursorStore


async def _lease(living: InMemoryLiving, *, epoch: int = 0, fence_delta: int = 0) -> DriveLease:
    await living.enqueue_job(WORKER, SCOPE, UUID(int=1), "drive", H, "key-1")
    fence = await living.acquire_job(WORKER, SCOPE, UUID(int=1), "w1", 300)
    return DriveLease(WORKER, SCOPE, UUID(int=1), "w1", fence + fence_delta, epoch)


@pytest.fixture
async def env() -> Env:
    living = InMemoryLiving()
    lease = await _lease(living)
    tracker = ResnapshotTracker()
    return Env(living, lease, tracker, DriveCursorStore(living, tracker))


def _event(file_id: str = "F1", ident: DrivePortIdentity = IDENT_A) -> dict:
    return build_event(ident, "DRIVE_CANDIDATE", "c1", file_id=file_id, revision_id=None,
                       status="UNATTESTED")


# --- record codec ---------------------------------------------------------------------------------


def _fresh(ident: DrivePortIdentity = IDENT_A) -> CursorRecord:
    return DriveCursorStore.fresh_record(ident, CORPUS, 0)


def test_record_round_trip_is_canonical_and_byte_exact():
    rec = _fresh().evolve(state=CursorState.BASELINING, token="Tok-ÄÖ/1+=", pos="Pos A".replace(" ", "_"),
                          seen=("s1", "S1"))
    text = rec.encode()
    assert CursorRecord.decode(text) == rec
    assert CursorRecord.decode(text).token == "Tok-ÄÖ/1+="  # no case-fold / normalisation
    assert CursorRecord.decode(text + " ") is None  # non-canonical bytes are refused


def _mutated(**over) -> str:
    raw = json.loads(_fresh().evolve(state=CursorState.LIVE, token="T").encode())
    raw.update(over)
    return json.dumps(raw, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize(
    "value",
    [
        None, 5, b"x", "", "{", "[]", "null", "x" * 20_000, "\x00", "[" * 100_000,
        '{"v":NaN}', _mutated(extra=1), _mutated(epoch=True), _mutated(epoch=-1), _mutated(v=2),
        _mutated(state="NOPE"), _mutated(token=" T"), _mutated(token="T\x00"), _mutated(ns="x:1"),
        _mutated(corpus="ABC"), _mutated(seen="T"), _mutated(reason="BOGUS"), _mutated(token=None),
        StrSub(_fresh().encode()),
    ],
    ids=lambda v: f"{type(v).__name__}-{len(v) if hasattr(v, '__len__') else v}-{str(v)[:12]!r}",
)
def test_decode_hostile_input_is_none_and_never_raises(value):
    assert CursorRecord.decode(value) is None


def test_decode_refuses_non_canonical_key_order():
    raw = json.loads(_fresh().encode())
    assert CursorRecord.decode(json.dumps(raw)) is None  # insertion order != canonical sorted form


@pytest.mark.parametrize(
    "kwargs",
    [
        {"state": "LIVE"},  # not a CursorState
        {"state": CursorState.LIVE},  # live without a token
        {"state": CursorState.UNINITIALIZED, "token": "T"},
        {"state": CursorState.GAP},  # fail-closed state needs a reason
        {"state": CursorState.LIVE, "token": "T", "pos": "P"},
        {"state": CursorState.LIVE, "token": "T", "reason": CursorReason.TOKEN_REPEATED},
        {"epoch": True},
        {"seen": ("a",) * 17},
        {"seen": ["a"]},
        {"token": "bad token"},
    ],
)
def test_record_invariants_refuse_with_fixed_code_and_echo_nothing(kwargs):
    base = {"state": CursorState.UNINITIALIZED, "namespace": "account:A", "tenant": "t",
            "connection_id": "c", "corpus": "0" * 64, "epoch": 0}
    base.update(kwargs)
    with pytest.raises(ValueError) as err:
        CursorRecord(**base)
    assert str(err.value) == "DRIVE_CURSOR_RECORD_INVALID"


def test_value_types_validate_exactly():
    for bad in ((), ("a", "a"), ["a"], (StrSub("a"),), ("a b",)):
        with pytest.raises(ValueError, match="DRIVE_CORPUS_INVALID"):
            DriveCorpus(None, bad)
    with pytest.raises(ValueError, match="DRIVE_CORPUS_INVALID"):
        DriveCorpus(StrSub("d"), ("r",))
    assert DriveCorpus(None, ("a", "b")).fingerprint == DriveCorpus(None, ("b", "a")).fingerprint
    assert DriveCorpus("d", ("a",)).fingerprint != DriveCorpus(None, ("a",)).fingerprint
    for kw in ({"fence": True}, {"fence": -1}, {"expected_epoch": True}, {"worker": ""},
               {"job_id": "x"}, {"actor": StrSub("w")}):
        args = {"actor": WORKER, "scope": SCOPE, "job_id": UUID(int=1), "worker": "w",
                "fence": 1, "expected_epoch": 0}
        args.update(kw)
        with pytest.raises(ValueError, match="DRIVE_LEASE_INVALID"):
            DriveLease(**args)


# --- keys, namespaces, transitions ---------------------------------------------------------------


def test_keys_carry_the_namespace_and_never_collide():
    same_id_a = DrivePortIdentity("account:X", "t", "c")
    same_id_b = DrivePortIdentity("drive:X", "t", "c")
    assert cursor_key(same_id_a) != cursor_key(same_id_b)
    # length prefixes: a separator inside an id cannot forge another identity's key
    assert cursor_key(DrivePortIdentity("account:a", "t", "b|1:c")) != cursor_key(
        DrivePortIdentity("account:a", "t|1:b", "c"))
    assert dedup_key("account:X", "K", "c1") != dedup_key("drive:X", "K", "c1")
    assert _event(ident=same_id_a)["event_id"] != _event(ident=same_id_b)["event_id"]
    assert _event()["namespace"] == "account:A"


def test_transition_table_never_leaves_a_fail_closed_state():
    s = CursorState
    ok = [(s.UNINITIALIZED, s.BASELINING), (s.BASELINING, s.CATCHING_UP), (s.CATCHING_UP, s.LIVE),
          (s.LIVE, s.CATCHING_UP), (s.LIVE, s.GAP), (s.BASELINING, s.RESNAPSHOT_REQUIRED),
          (s.CATCHING_UP, s.AUTH_REQUIRED), (s.GAP, s.GAP)]
    bad = [(s.UNINITIALIZED, s.LIVE), (s.UNINITIALIZED, s.CATCHING_UP), (s.BASELINING, s.LIVE),
           (s.LIVE, s.BASELINING), (s.GAP, s.LIVE), (s.GAP, s.UNINITIALIZED),
           (s.RESNAPSHOT_REQUIRED, s.BASELINING), (s.AUTH_REQUIRED, s.LIVE), ("LIVE", s.GAP)]
    assert all(is_allowed_transition(a, b) for a, b in ok)
    assert not any(is_allowed_transition(a, b) for a, b in bad)
    assert fail_closed_state(CursorReason.TOKEN_REPEATED) is s.GAP
    assert fail_closed_state(CursorReason.CURSOR_MISSING) is s.RESNAPSHOT_REQUIRED


# --- load: fail-closed recovery triggers (TC108) -------------------------------------------------


async def _load(env: Env, ident=IDENT_A, corpus=CORPUS, epoch=0, lease=None, **kw) -> CursorLoad:
    return await env.store.load(ident, corpus, epoch, lease or env.lease, **kw)


async def test_initialize_creates_uninitialized_and_never_resets_existing(env):
    load = await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    assert load.usable and load.state is CursorState.UNINITIALIZED and load.version == 0
    first = await env.store.commit(
        IDENT_A, env.lease, load, load.record.evolve(state=CursorState.BASELINING, token="T1"), [])
    assert first.ok and first.version == 1
    again = await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    assert again.state is CursorState.BASELINING and again.record.token == "T1"


@pytest.mark.parametrize(
    ("case", "reason", "tracker_reason"),
    [
        ("missing", CursorReason.CURSOR_MISSING, ResnapshotReason.CURSOR_MISSING),
        ("empty", CursorReason.CURSOR_EMPTY, ResnapshotReason.CURSOR_LOST),
        ("corrupt", CursorReason.CURSOR_CORRUPT, ResnapshotReason.CURSOR_LOST),
        ("foreign_identity", CursorReason.IDENTITY_CHANGED, ResnapshotReason.CURSOR_LOST),
        ("corpus", CursorReason.CORPUS_CHANGED, ResnapshotReason.CURSOR_LOST),
        ("drive_epoch", CursorReason.SCOPE_EPOCH_CHANGED, ResnapshotReason.SCOPE_EPOCH_CHANGED),
        ("ledger_epoch", CursorReason.SCOPE_EPOCH_CHANGED, ResnapshotReason.SCOPE_EPOCH_CHANGED),
    ],
)
async def test_lost_empty_corrupt_foreign_or_changed_cursor_is_resnapshot_required(
        env, case, reason, tracker_reason):
    key = cursor_key(IDENT_A)
    kw: dict = {}
    if case == "empty":
        await env.living.create_cursor(WORKER, SCOPE, key, "")
    elif case == "corrupt":
        await env.living.create_cursor(WORKER, SCOPE, key, '{"v":1,"state":"LIVE"')
    elif case == "foreign_identity":
        await env.living.create_cursor(WORKER, SCOPE, key, _fresh(IDENT_B).encode())
    elif case != "missing":
        await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    if case == "corpus":
        kw["corpus"] = OTHER_CORPUS
    if case == "drive_epoch":
        kw["epoch"] = 1
    if case == "ledger_epoch":
        kw["lease"] = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", env.lease.fence, 1)
    load = await _load(env, **kw)
    assert not load.usable
    assert load.state is CursorState.RESNAPSHOT_REQUIRED and load.reason is reason
    assert env.tracker.is_required(key) and env.tracker.reason(key) is tracker_reason


async def test_one_namespace_never_reads_another_namespaces_cursor(env):
    await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    other = await _load(env, IDENT_B)
    assert other.reason is CursorReason.CURSOR_MISSING  # B has its own key; A's cursor is invisible
    assert env.tracker.is_required(cursor_key(IDENT_B))
    assert not env.tracker.is_required(cursor_key(IDENT_A))
    assert (await _load(env, IDENT_A)).usable


async def test_record_requirement_false_does_not_touch_the_tracker(env):
    load = await _load(env, record_requirement=False)
    assert load.reason is CursorReason.CURSOR_MISSING
    assert env.tracker.required_connections() == ()


# --- commit: all-or-nothing, replay, fence (TC054-style, TC108) ----------------------------------


async def test_commit_replay_is_idempotent_and_same_page_different_digest_is_a_conflict(env):
    load = await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    first = await env.store.commit(IDENT_A, env.lease, load, new, [_event("F1")])
    replay = await env.store.commit(IDENT_A, env.lease, load, new, [_event("F1")])
    conflict = await env.store.commit(IDENT_A, env.lease, load, new, [_event("F2")])
    assert (first.ok, first.replayed, first.version) == (True, False, 1)
    assert (replay.ok, replay.replayed, replay.version) == (True, True, 1)
    assert (conflict.ok, conflict.reason) == (False, CursorReason.COMMIT_CONFLICT)
    rows = await env.living.list_outbox(WORKER, SCOPE)
    assert len(rows) == 1 and rows[0].content["file_id"] == "F1"
    assert (await _load(env)).version == 1


async def test_stale_fence_and_expired_lease_commit_nothing(env):
    load = await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    new = load.record.evolve(state=CursorState.BASELINING, token="T1")
    stale = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", env.lease.fence + 1, 0)
    result = await env.store.commit(IDENT_A, stale, load, new, [_event()])
    assert (result.ok, result.reason) == (False, CursorReason.LEASE_LOST)
    env.living.clock.advance(400)  # the real lease runs out
    expired = await env.store.commit(IDENT_A, env.lease, load, new, [_event()])
    assert (expired.ok, expired.reason) == (False, CursorReason.LEASE_LOST)
    assert await env.living.list_outbox(WORKER, SCOPE) == ()
    assert (await _load(env, lease=env.lease)).state is CursorState.UNINITIALIZED


async def test_invalid_transition_and_invalid_batch_commit_nothing(env):
    load = await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    jump = load.record.evolve(state=CursorState.LIVE, token="T1")
    assert (await env.store.commit(IDENT_A, env.lease, load, jump, [])).reason is (
        CursorReason.INVALID_TRANSITION)
    bad_event = dict(_event(), digest="0" * 64)
    ok_state = load.record.evolve(state=CursorState.BASELINING, token="T1")
    refused = await env.store.commit(IDENT_A, env.lease, load, ok_state, [bad_event])
    assert (refused.ok, refused.reason) == (False, CursorReason.INVALID_BATCH)
    assert (await _load(env)).version == 0


async def test_fail_closed_marker_is_durable_and_never_auto_cleared(env):
    load = await env.store.initialize(IDENT_A, CORPUS, 0, env.lease)
    assert await env.store.fail_closed(IDENT_A, env.lease, load, CursorReason.TOKEN_REPEATED)  # UNINITIALIZED -> GAP
    # a restart (new tracker + store over the same durable cursor) still sees the block
    tracker2 = ResnapshotTracker()
    store2 = DriveCursorStore(env.living, tracker2)
    blocked = await store2.load(IDENT_A, CORPUS, 0, env.lease)
    assert not blocked.usable and blocked.state is CursorState.GAP
    assert blocked.reason is CursorReason.TOKEN_REPEATED
    assert tracker2.is_required(cursor_key(IDENT_A))
    # neither initialize nor commit can move it back
    assert (await store2.initialize(IDENT_A, CORPUS, 0, env.lease)).state is CursorState.GAP
    live = blocked.record.evolve(state=CursorState.BASELINING, token="T1", reason=None)
    assert (await store2.commit(IDENT_A, env.lease, blocked, live, [])).reason is (
        CursorReason.INVALID_REQUEST)
    # only an explicit reset restarts from a fresh snapshot
    fresh = await store2.reset(IDENT_A, CORPUS, 0, env.lease, blocked)
    assert fresh.usable and fresh.state is CursorState.UNINITIALIZED and fresh.version == 2


async def test_reset_overwrites_a_corrupt_cursor_and_initializes_a_missing_one(env):
    key = cursor_key(IDENT_A)
    missing = await _load(env, record_requirement=False)
    created = await env.store.reset(IDENT_A, CORPUS, 0, env.lease, missing)
    assert created.usable and created.version == 0
    await env.living.create_cursor(WORKER, SCOPE, cursor_key(IDENT_B), "garbage")
    corrupt = await _load(env, IDENT_B, record_requirement=False)
    assert corrupt.reason is CursorReason.CURSOR_CORRUPT
    fresh = await env.store.reset(IDENT_B, CORPUS, 0, env.lease, corrupt)
    assert fresh.usable and fresh.version == 1
    assert key != cursor_key(IDENT_B)


async def test_hostile_store_inputs_return_fixed_refusals_and_never_raise(env):
    for args in ((None, CORPUS, 0, env.lease), (IDENT_A, None, 0, env.lease),
                 (IDENT_A, CORPUS, True, env.lease), (IDENT_A, CORPUS, 0, None),
                 (IDENT_A, CORPUS, StrSub("x"), env.lease), ("account:A", CORPUS, 0, env.lease)):
        assert (await env.store.load(*args)).reason is CursorReason.INVALID_REQUEST
        assert (await env.store.initialize(*args)).reason is CursorReason.INVALID_REQUEST
    bad = CursorLoad(False, None, None)
    assert (await env.store.commit(IDENT_A, env.lease, bad, _fresh(), [])).reason is (
        CursorReason.INVALID_REQUEST)
    assert (await env.store.commit(None, None, None, None, None)).reason is (
        CursorReason.INVALID_REQUEST)
    assert (await env.store.reset(None, None, 0, None, None)).reason is CursorReason.INVALID_REQUEST
    with pytest.raises(ValueError, match="TRACKER_REQUIRED"):
        DriveCursorStore(env.living, object())


def test_module_imports_no_release1_http_or_socket_code():
    tree = ast.parse(Path(drive_cursor.__file__).read_text(encoding="utf-8"))
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
