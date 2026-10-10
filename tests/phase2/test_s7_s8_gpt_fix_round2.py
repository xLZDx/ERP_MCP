"""GPT-PM round-2 remediation: S7 M03 (removed root), S7 M05 (tracker generation), S8 M05 (audit recovery),
S8 M06 (legacy dispatcher), S8 M08 (forged foreign job record). Offline; fakes only."""
from __future__ import annotations

from uuid import UUID

from test_s7_fix_scope_membership import (
    DriveChange,
    DriveChangeKind,
    V,
    _ck,
    _page,
    _up,
    _world,
)
from test_s7_gpt_fix_cursor import CORPUS, IDENT, KEY, O, make_env
from test_s8_gpt_fix_jobs_api import Env as JobsEnv
from test_s8_gpt_fix_jobs_api import _shape
from test_s8_gpt_fix_session import KEY as RUN_KEY
from test_s8_gpt_fix_session import _setup

from business_ai_gateway.phase2.drive_baseline import DriveBaseline, DriveRunMode
from business_ai_gateway.phase2.drive_cursor import DriveCursorStore, DriveLease
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
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
from business_ai_gateway.phase2.workbench_types import ReasonCode as R

# ----------------------------------------------------------------------------------------- S7 M03


async def test_s7_m03_a_removed_root_no_longer_authorizes_its_own_id():
    ck = _ck(_world())
    assert await ck.authorize_disclosure("R") is True
    await ck.prepare_page(_page([DriveChange("c1", "R", None, DriveChangeKind.REMOVED)]), "T1")
    res = await ck.check("R")  # the fake still serves stale readable metadata for R
    assert res.verdict is not V.IN_SCOPE
    assert await ck.authorize_disclosure("R") is False
    assert await ck.authorize_disclosure("A") is False


async def test_s7_m03_control_explicit_upsert_reinstates_the_root():
    ck = _ck(_world())
    await ck.prepare_page(_page([DriveChange("c1", "R", None, DriveChangeKind.REMOVED)]), "T1")
    assert await ck.authorize_disclosure("R") is False
    await ck.prepare_page(_page([_up("c2", "R")], token="T2", nxt="T3"), "T2")
    assert await ck.authorize_disclosure("R") is True
    assert await ck.authorize_disclosure("A") is True


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
    assert b.token_from_marker(marker) is None or b._generation == a._generation
    assert a.token_from_marker(None) is None and a.token_from_marker(True) is None


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
