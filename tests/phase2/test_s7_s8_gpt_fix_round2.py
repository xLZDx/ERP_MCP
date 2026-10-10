"""GPT-PM round-2 remediation: S7 M03 (removed root), S7 M05 (tracker generation), S8 M05 (audit recovery),
S8 M06 (legacy dispatcher), S8 M08 (forged foreign job record). Offline; fakes only."""
from __future__ import annotations

from uuid import UUID

from s7_receipts import checker, committer, receipt
from test_s7_fix_scope_membership import (
    DriveChange,
    DriveChangeKind,
    V,
    _page,
    _up,
    _world,
)
from test_s7_gpt_fix_cursor import CORPUS, IDENT, KEY, O, make_env
from test_s8_gpt_fix_jobs_api import Env as JobsEnv
from test_s8_gpt_fix_jobs_api import _shape
from test_s8_gpt_fix_session import KEY as RUN_KEY
from test_s8_gpt_fix_session import _setup
from test_workbench_session import FAIL_G, FAIL_N

from business_ai_gateway.phase2.drive_baseline import DriveBaseline, DriveRunMode
from business_ai_gateway.phase2.drive_cursor import DriveCursorStore, DriveLease
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_membership import PageStatus
from business_ai_gateway.phase2.fakes import DEFAULT_SCOPE as SCOPE
from business_ai_gateway.phase2.fakes import WORKER
from business_ai_gateway.phase2.jobs_api import (
    FakeJobDispatcher,
    JobRecord,
    read_job,
)
from business_ai_gateway.phase2.resnapshot import ResnapshotReason, ResnapshotTracker
from business_ai_gateway.phase2.safe_errors import SafeError
from business_ai_gateway.phase2.workbench_review import (
    AnnotationKind,
    RerunOutcome,
    check_rerun,
    commit_rerun,
)
from business_ai_gateway.phase2.workbench_types import FakeOwnership
from business_ai_gateway.phase2.workbench_types import ReasonCode as R

# ----------------------------------------------------------------------------------------- S7 M03

REMOVE = DriveChange("c1", "R", None, DriveChangeKind.REMOVED)


async def _removed_world():
    fake = _world()
    env = await committer()
    ck = checker(fake, env)
    await ck.prepare_page(_page([REMOVE]), "T1")
    return fake, env, ck


async def _requalified(ck):
    return await ck.prepare_page(_page([_up("c2", "R")], token="T2", nxt="T3"), "T2")


async def test_s7_m03_a_removed_root_no_longer_authorizes_its_own_id():
    fake = _world()
    env = await committer()
    ck = checker(fake, env)
    assert await ck.authorize_disclosure("R") is True
    await ck.prepare_page(_page([REMOVE]), "T1")
    res = await ck.check("R")  # the fake still serves stale readable metadata for R
    assert res.verdict is not V.IN_SCOPE
    assert await ck.authorize_disclosure("R") is False
    assert await ck.authorize_disclosure("A") is False


async def test_s7_m03_control_explicit_upsert_plus_the_matching_store_receipt_reinstates_the_root():
    _fake, env, ck = await _removed_world()
    prep = await _requalified(ck)
    assert await ck.authorize_disclosure("R") is False  # provisional until the cursor commit is proven
    proof = await receipt(env, "T2", prep.batch.committable_cursor())
    assert ck.accept_page(prep, proof) is True
    assert await ck.authorize_disclosure("R") is True
    assert await ck.authorize_disclosure("A") is True
    assert ck.accept_page(prep, proof) is False  # one-shot


async def test_s7_m03_refused_page_never_reinstates_the_root():
    _fake, env, ck = await _removed_world()
    bad = await ck.prepare_page(_page([_up("c2", "R")], token="T2", nxt="T3"), "WRONG-CURSOR")
    assert bad.status is not PageStatus.PREPARED
    assert ck.accept_page(bad, await receipt(env, "WRONG-CURSOR", "T3")) is False
    assert await ck.authorize_disclosure("R") is False
    assert await ck.authorize_disclosure("A") is False


async def test_s7_m03_an_unaccepted_or_replaced_preparation_never_reinstates():
    _fake, env, ck = await _removed_world()
    first = await _requalified(ck)
    await ck.prepare_page(_page([_up("c3", "A")], token="T3", nxt="T4"), "T3")  # replaces the first
    assert ck.accept_page(first, await receipt(env, "T2", first.batch.committable_cursor())) is False
    assert await ck.authorize_disclosure("R") is False


async def test_s7_m03_a_child_task_spawned_during_preparation_cannot_disclose_the_root():
    import asyncio

    fake, _env, ck = await _removed_world()
    spawned: list[asyncio.Future] = []
    fake.run_after_calls(1, lambda f: spawned.append(
        asyncio.get_running_loop().create_task(ck.authorize_disclosure("R"))))
    prep = await _requalified(ck)
    assert prep.status is PageStatus.PREPARED
    assert [await t for t in spawned] == [False]
    assert await ck.authorize_disclosure("R") is False


async def test_s7_m03_an_epoch_change_before_acceptance_invalidates_the_preparation():
    _fake, env, ck = await _removed_world()
    prep = await _requalified(ck)
    proof = await receipt(env, "T2", prep.batch.committable_cursor())
    assert ck.advance_epoch(1) is True
    assert ck.accept_page(prep, proof) is False
    assert await ck.authorize_disclosure("R") is False


async def test_s7_m03_a_receipt_of_another_store_or_connection_or_transaction_is_not_proof():
    _fake, env, ck = await _removed_world()
    prep = await _requalified(ck)
    token = prep.batch.committable_cursor()
    other_store = await committer()  # a different store that really committed the same token
    assert ck.accept_page(prep, await receipt(other_store, "T2", token)) is False
    assert ck.accept_page(prep, await receipt(env, "T9", token)) is False  # wrong prior cursor
    assert ck.accept_page(prep, await receipt(env, "T2", "T7")) is False  # wrong committed cursor
    assert await ck.authorize_disclosure("R") is False
    assert ck.accept_page(prep, await receipt(env, "T2", token)) is True


async def test_s7_m03_computed_forged_malformed_and_hostile_receipts_are_never_proof():
    from business_ai_gateway.phase2.drive_cursor import CursorCommitReceipt

    _fake, env, ck = await _removed_world()
    prep = await _requalified(ck)
    token = prep.batch.committable_cursor()

    class HostileStr(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    half = object.__new__(CursorCommitReceipt)  # unset slot: must refuse, never raise
    cases = (None, "", token, 3, half, CursorCommitReceipt(object()), CursorCommitReceipt(HostileStr("x")))
    for proof in cases:
        assert ck.accept_page(prep, proof) is False
    genuine = await receipt(env, "T2", token)
    assert env.store.receipt_matches(genuine, HostileIdentity(), "T2", token, 0) is False
    assert env.store.receipt_matches(genuine, IDENT, HostileStr("T2"), token, 0) is False
    assert env.store.receipt_matches(genuine, IDENT, "T2", HostileStr(token), 0) is False
    assert env.store.receipt_matches(genuine, IDENT, "T2", token, True) is False  # bool is not an int epoch
    assert await ck.authorize_disclosure("R") is False
    assert ck.accept_page(prep, genuine) is True


class HostileIdentity:
    namespace = tenant = connection_id = "x"


async def test_s7_m03_a_checker_without_a_bound_store_never_reinstates():
    fake = _world()
    env = await committer()
    from business_ai_gateway.phase2.drive_membership import Corpus, MembershipChecker

    ck = MembershipChecker(fake, IDENT, Corpus(IDENT.namespace, ("R",)), 0)
    await ck.prepare_page(_page([REMOVE]), "T1")
    prep = await _requalified(ck)
    assert ck.accept_page(prep, await receipt(env, "T2", prep.batch.committable_cursor())) is False
    assert await ck.authorize_disclosure("R") is False


async def test_s7_m03_a_concurrent_disclosure_never_sees_the_provisional_root():
    import asyncio

    _fake, _env, ck = await _removed_world()
    task = asyncio.ensure_future(_requalified(ck))
    others = await asyncio.gather(ck.authorize_disclosure("R"), ck.authorize_disclosure("A"))
    await task
    assert others == [False, False]


# ----------------------------------------------------------------------------------------- S7 M05


async def test_s7_m05_a_marker_from_another_tracker_generation_is_never_continued():
    from business_ai_gateway.phase2.drive_baseline import BaselineLimits

    env = await make_env()
    env.tracker.require(KEY, ResnapshotReason.CURSOR_MISSING, 0)
    limited = await env.run(DriveRunMode.RESNAPSHOT_START, limits=BaselineLimits(1, 100))
    assert limited.outcome is O.LIMIT_REACHED
    # process restart: a fresh tracker whose order numbers can collide with the persisted marker
    tracker2 = ResnapshotTracker()
    tracker2.require(KEY, ResnapshotReason.SCOPE_EPOCH_CHANGED, 0)
    assert tracker2.token_from_marker((await env.record()).snap) is None
    fake2 = FakeDrivePort(start_page_token="START-1")
    fake2.script_page("START-1", new_start_page_token="TOK-2")
    store2 = DriveCursorStore(env.living, tracker2)
    lease = DriveLease(WORKER, SCOPE, UUID(int=1), "w1", 1, 0)
    env2 = type(env)(env.living, lease, tracker2, store2, fake2, env.lister, DriveBaseline(fake2, store2))
    done = await env2.run(DriveRunMode.RESNAPSHOT_CONTINUE)
    assert fake2.count("get_start_page_token") == 1  # restarted from a genuinely new snapshot
    assert done.outcome in (O.LIVE, O.LIMIT_REACHED)
    assert IDENT is not None and CORPUS is not None


def test_s7_m05_marker_roundtrip_is_bound_to_the_generation():
    a, b = ResnapshotTracker(), ResnapshotTracker()
    marker = a.persistent_marker(3)
    assert a.token_from_marker(marker) == 3
    assert b.token_from_marker(marker) is None
    assert a.token_from_marker(None) is None and a.token_from_marker(True) is None


def test_s7_m05_two_trackers_never_share_a_generation_even_if_the_random_source_repeats(monkeypatch):
    import business_ai_gateway.phase2.resnapshot as rs

    values = iter([7, 7, 7, 8])
    monkeypatch.setattr(rs.secrets, "randbits", lambda bits: next(values))
    rs._GENERATIONS_ISSUED.discard(7)
    rs._GENERATIONS_ISSUED.discard(8)
    a, b = ResnapshotTracker(), ResnapshotTracker()
    assert a._generation != b._generation
    assert b.token_from_marker(a.persistent_marker(2)) is None  # an old snapshot cannot clear b's requirement


# ----------------------------------------------------------------------------------------- S8 M05


def test_s8_m05_failed_audit_append_is_recovered_without_a_second_run():
    env, log, run1, s2 = _setup(max_per_run=3)
    kw = {"ownership": env.ownership, "current_epoch": lambda: 5}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", RUN_KEY, run1.run_id, s2.snapshot_id, **kw)
    real, state = log._append, {"fail": 2}

    def flaky(*args, **kwargs):
        if state["fail"] > 0:
            state["fail"] -= 1
            raise RuntimeError("audit store down")
        return real(*args, **kwargs)

    log._append = flaky
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(out) is SafeError and out.reason_code is R.INTERNAL_REFUSED
    runs_after_failure = len(env.ledger.list_runs("t1", RUN_KEY))
    assert runs_after_failure == 2 and not log._entries.get(("t1", run1.run_id))
    retry = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(retry) is RerunOutcome and retry.annotated is True
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == runs_after_failure  # recovery created no new run
    entries = log._entries[("t1", run1.run_id)]
    assert [e.kind for e in entries] == [AnnotationKind.RERUN_REQUESTED]
    assert entries[0].related_run_id == retry.new_run_id
    again = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(again) is not RerunOutcome or len(env.ledger.list_runs("t1", RUN_KEY)) == runs_after_failure


def test_s8_m05_one_transient_failure_is_absorbed_by_the_bounded_retry():
    env, log, run1, s2 = _setup(max_per_run=3)
    kw = {"ownership": env.ownership, "current_epoch": lambda: 5}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", RUN_KEY, run1.run_id, s2.snapshot_id, **kw)
    real, state = log._append, {"fail": 1}

    def flaky(*args, **kwargs):
        if state["fail"] > 0:
            state["fail"] -= 1
            return None
        return real(*args, **kwargs)

    log._append = flaky
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(out) is RerunOutcome and out.annotated is True
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == 2


def _failed_once(env, log, run1, s2):
    kw = {"ownership": env.ownership, "current_epoch": lambda: 5}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", RUN_KEY, run1.run_id, s2.snapshot_id, **kw)
    real, state = log._append, {"fail": 2}

    def flaky(*args, **kwargs):
        if state["fail"] > 0:
            state["fail"] -= 1
            raise RuntimeError("audit store down")
        return real(*args, **kwargs)

    log._append = flaky
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(out) is SafeError
    log._append = real
    return plan, kw


def test_s8_m05_recovery_is_refused_after_the_ownership_or_epoch_is_revoked():
    env, log, run1, s2 = _setup(max_per_run=3)
    plan, _kw = _failed_once(env, log, run1, s2)
    revoked = {"ownership": FakeOwnership(), "current_epoch": lambda: 5}
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **revoked)
    assert type(out) is SafeError and out.reason_code is R.NOT_IN_SCOPE
    moved = {"ownership": env.ownership, "current_epoch": lambda: 6}
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **moved)
    assert type(out) is SafeError and not log._entries.get(("t1", run1.run_id))


def test_s8_m05_recovery_is_bound_to_the_same_request_actor_and_snapshot():
    env, log, run1, s2 = _setup(max_per_run=3)
    plan, kw = _failed_once(env, log, run1, s2)
    other = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="mallory", **kw)
    assert type(other) is not RerunOutcome and not log._entries.get(("t1", run1.run_id))
    own = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(own) is RerunOutcome and own.annotated is True


def test_s8_m05_append_that_wrote_then_raised_does_not_duplicate_the_audit_entry():
    env, log, run1, s2 = _setup(max_per_run=3)
    kw = {"ownership": env.ownership, "current_epoch": lambda: 5}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", RUN_KEY, run1.run_id, s2.snapshot_id, **kw)
    real, state = log._append, {"first": True}

    def write_then_lose_ack(*args, **kwargs):
        entry = real(*args, **kwargs)
        if state["first"]:
            state["first"] = False
            raise RuntimeError("ack lost")
        return entry

    log._append = write_then_lose_ack
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(out) is RerunOutcome and out.annotated is True
    entries = log._entries[("t1", run1.run_id)]
    assert [e.kind for e in entries] == [AnnotationKind.RERUN_REQUESTED]  # exactly one
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == 2


def test_s8_m05_the_public_session_retry_reaches_recovery_and_creates_one_run_one_audit_one_job():
    env, log, run1, s2 = _setup(max_per_run=3)
    real, state = log._append, {"fail": 2}

    def flaky(*args, **kwargs):
        if state["fail"] > 0:
            state["fail"] -= 1
            raise RuntimeError("audit store down")
        return real(*args, **kwargs)

    log._append = flaky
    first = env.rerun(run1.run_id, s2.snapshot_id)
    assert getattr(first, "allowed", None) is False
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == 2 and not log._entries.get(("t1", run1.run_id))
    retry = env.rerun(run1.run_id, s2.snapshot_id)
    assert getattr(retry, "allowed", None) is True, retry
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == 2  # still exactly one new run
    assert [e.kind for e in log._entries[("t1", run1.run_id)]] == [AnnotationKind.RERUN_REQUESTED]
    replay = env.rerun(run1.run_id, s2.snapshot_id)
    assert getattr(replay, "allowed", None) is True
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == 2
    assert len(log._entries[("t1", run1.run_id)]) == 1


def test_s8_m05_the_public_retry_of_a_different_snapshot_stays_stale():
    env, log, run1, s2 = _setup(max_per_run=3)
    _failed_once(env, log, run1, s2)
    other = env.snapshot(dict(FAIL_G), dict(FAIL_N))
    out = env.rerun(run1.run_id, other.snapshot_id)
    assert getattr(out, "allowed", None) is False and out.reason_code is R.RERUN_TARGET_STALE
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == 2


def test_s8_m05_recovery_after_a_lost_ack_needs_no_new_audit_slot():
    env, log, run1, s2 = _setup(max_per_run=1)
    real, state = log._append, {"first": True}

    def write_then_lose_ack(*args, **kwargs):
        entry = real(*args, **kwargs)
        if state["first"]:
            state["first"] = False
            raise RuntimeError("ack lost")
        return entry

    log._append = write_then_lose_ack
    # the facade's own retry of the append absorbs a single lost ack; force both attempts to lose it
    state["first"] = True
    calls = {"n": 0}

    def always_lose(*args, **kwargs):
        calls["n"] += 1
        entry = real(*args, **kwargs)
        if calls["n"] <= 2:
            raise RuntimeError("ack lost")
        return entry

    log._append = always_lose
    first = env.rerun(run1.run_id, s2.snapshot_id)
    assert getattr(first, "allowed", None) is False
    assert len(log._entries[("t1", run1.run_id)]) == 1  # written; the quota (1) is now full
    retry = env.rerun(run1.run_id, s2.snapshot_id)
    assert getattr(retry, "allowed", None) is True, retry
    assert len(env.ledger.list_runs("t1", RUN_KEY)) == 2
    assert len(log._entries[("t1", run1.run_id)]) == 1
    assert log._pending_get("t1", run1.run_id) is None


def test_s8_m05_an_epoch_move_during_recovery_blocks_the_audit_effect():
    env, log, run1, s2 = _setup(max_per_run=3)
    epoch = [5]
    kw = {"ownership": env.ownership, "current_epoch": lambda: epoch[0]}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", RUN_KEY, run1.run_id, s2.snapshot_id, **kw)
    real, state = log._append, {"fail": 2}

    def flaky(*args, **kwargs):
        if state["fail"] > 0:
            state["fail"] -= 1
            raise RuntimeError("audit store down")
        return real(*args, **kwargs)

    log._append = flaky
    assert type(commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader,
                             actor_id="alice", **kw)) is SafeError
    appended = []
    log._append = lambda *a, **k: appended.append(a) or real(*a, **k)
    real_now = log._now

    def now_and_revoke():
        epoch[0] = 6  # authorization moves after the gate, before the audit effect
        return real_now()

    log._now = now_and_revoke
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(out) is SafeError and out.reason_code is R.SCOPE_EPOCH_STALE
    assert appended == [] and not log._entries.get(("t1", run1.run_id))


# ----------------------------------------------------------------------------------------- S8 M06


class LegacyDispatcher(FakeJobDispatcher):
    """A 4-argument dispatcher without dispatch-key support that loses its reply after creating the job."""

    def dispatch(self, tenant_id, company_id, kind, request_digest):
        super().dispatch(tenant_id, company_id, kind, request_digest)
        raise RuntimeError("reply lost")


def test_s8_m06_a_legacy_dispatcher_is_refused_before_any_side_effect():
    env = JobsEnv(LegacyDispatcher())
    first = env.enqueue()
    assert first.allowed is False and first.reason_code is R.DEPENDENCY_FAILED
    retry = env.enqueue()
    assert retry.allowed is False
    assert env.dispatcher.call_count == 0  # never reached: no duplicate job is possible
    assert env.idem.record_count() == 0


def test_s8_m06_a_legacy_dispatcher_is_refused_for_a_rerun_before_the_gate_commits():
    env = JobsEnv(LegacyDispatcher())
    out = env.rerun()
    assert out.allowed is False and out.reason_code is R.DEPENDENCY_FAILED
    assert env.gate.commits == 0 and env.gate.checks == 0
    assert env.dispatcher.call_count == 0 and env.idem.record_count() == 0


def test_s8_m06_control_a_key_aware_dispatcher_still_works():
    env = JobsEnv()
    assert env.enqueue().allowed is True
    assert env.enqueue().allowed is True
    assert env.dispatcher.call_count == 1


# ----------------------------------------------------------------------------------------- S8 M08


class ForgedForeign(FakeJobDispatcher):
    def get(self, job_id):
        if job_id == "JOB-FORGED":
            forged = object.__new__(JobRecord)  # slots unset on purpose (no tenant_id)
            object.__setattr__(forged, "job_id", job_id)
            return forged
        return super().get(job_id)


def test_s8_m08_forged_incomplete_foreign_record_looks_like_a_missing_job():
    env = JobsEnv(ForgedForeign())
    missing = env.read("JOB-MISSING")
    forged = env.read("JOB-FORGED")
    assert missing.reason_code is R.NOT_FOUND
    assert _shape(forged) == _shape(missing)
    assert "JOB-FORGED" not in repr(forged)
    assert read_job is not None
