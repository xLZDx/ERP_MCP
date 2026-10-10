"""S8 GPT-PM gate remediation, stream K2: M01 (forged session in every facade path) and M05 (rerun audit).

M01: a ``SessionRecord`` built with ``object.__new__`` (correct tenant/actor/expiry, no session id and no
CSRF digest) must be ``SESSION_INVALID`` on every facade path, read-only ones included, with zero ledger,
view, entitlement and dispatcher calls.

M05: the audit annotation capacity is RESERVED before the run is created, so the run + annotation pair
cannot half-commit; a lost quota race leaves no run and a consistent refusal.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from test_workbench_session import FAIL_N, KEY, T0, Env

from business_ai_gateway.phase2.jobs_api import RerunRequest, SessionRecord, fake_csrf_token
from business_ai_gateway.phase2.workbench_review import (
    RerunOutcome,
    ReviewLog,
    check_rerun,
    commit_rerun,
)
from business_ai_gateway.phase2.workbench_types import (
    AnnotationKind,
    ReasonCode,
    SafeError,
)

R = ReasonCode


# ------------------------------------------------------------------ M01
def forged(*, set_id=False, set_digest=False, tenant="t1", actor="alice"):
    s = object.__new__(SessionRecord)
    object.__setattr__(s, "tenant_id", tenant)
    object.__setattr__(s, "actor_id", actor)
    object.__setattr__(s, "expires_at", T0 + timedelta(days=12))
    if set_id:
        object.__setattr__(s, "session_id", "S1")
    if set_digest:
        object.__setattr__(s, "csrf_secret_digest", "a" * 64)
    return s


class Spy:
    """Counts calls on the ports/stores a forged session must never reach."""

    def __init__(self, env):
        self.calls = []
        ent, led = env.entitlements, env.ledger
        orig_ent = ent.entitled
        ent.entitled = lambda *a, **k: (self.calls.append("entitled"), orig_ent(*a, **k))[1]
        for name in ("get", "list_runs", "current", "run"):
            orig = getattr(led, name)
            setattr(led, name, lambda *a, _o=orig, _n=name, **k: (self.calls.append(_n), _o(*a, **k))[1])
        env.dispatcher.dispatch = lambda *a, **k: self.calls.append("dispatch")


FORGERIES = (
    {},                       # neither session id nor digest
    {"set_id": True},          # no digest
    {"set_digest": True},      # no session id
)


@pytest.mark.parametrize("kw", FORGERIES)
def test_forged_session_is_session_invalid_on_every_facade_read_and_write_path(kw):
    env = Env()
    _, run1 = env.first_run()
    viewer = env.viewer
    spy = Spy(env)
    bad = forged(**kw)
    ws = env.ws
    outs = {
        "cards": ws.cards(bad, viewer, KEY, source_id="src1"),
        "verify": ws.verify_original(bad, viewer, object()),
        "annotate": ws.annotate(bad, viewer, "tok", run1.run_id, AnnotationKind.NOTE, "x"),
        "annotations": ws.annotations(bad, viewer, run1.run_id),
        "timeline": ws.timeline(bad, viewer),
        "coverage": ws.coverage(bad, viewer),
        "diff": ws.diff(bad, viewer),
        "evidence": ws.evidence(bad, viewer),
    }
    assert outs["verify"] is R.SESSION_INVALID
    for name, out in outs.items():
        if name == "verify":
            continue
        assert type(out) is SafeError and out.reason_code is R.SESSION_INVALID, name
    assert spy.calls == []


def test_genuine_session_is_still_admitted():
    env = Env()
    env.first_run()
    assert not isinstance(env.ws.coverage(env.session, env.viewer), SafeError)


def test_forged_session_never_reaches_jobs_api_paths_either():
    env = Env()
    _, run1 = env.first_run()
    spy = Spy(env)
    bad = forged(set_id=True)
    tok = fake_csrf_token(env.session)
    req = RerunRequest(env.viewer, "alice", KEY, run1.run_id, "SN-1", "idem-forge-0001")
    out = env.ws.rerun(req, bad, tok)
    assert getattr(out, "allowed", None) is False
    assert "dispatch" not in spy.calls and "run" not in spy.calls
    assert len(env.ledger.list_runs("t1", KEY)) == 1


# ------------------------------------------------------------------ M05
def _racy(log):
    """Instance hook: after ``_has_room`` said yes, another operation fills the last slot (check -> commit)."""
    state = {"armed": False, "filled": False}
    orig = log._has_room

    def has_room(tenant, run_id):
        ok = orig(tenant, run_id)
        if ok and state["armed"] and not state["filled"]:
            state["filled"] = True
            assert log._append(tenant, run_id, "racer", AnnotationKind.NOTE, "race", None, None, T0) is not None
        return ok
    log._has_room = has_room
    return state


def _setup(max_per_run=1):
    env = Env()
    log = ReviewLog(env.clk.now, max_per_run=max_per_run)
    log.race = _racy(log)
    env.review_log = log
    from test_s8_fix_session import rebuild
    rebuild(env, review_log=log)
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    return env, log, run1, s2


def test_quota_race_between_check_and_commit_leaves_no_run_and_a_refusal():
    env, log, run1, s2 = _setup()
    log.race['armed'] = True
    out = env.rerun(run1.run_id, s2.snapshot_id)
    assert log.race['filled']
    assert getattr(out, "allowed", None) is False and out.reason_code is R.RATE_LIMITED
    assert len(env.ledger.list_runs("t1", KEY)) == 1  # no unannotated run exists
    entries = log.entries(env.viewer, "t1", run1.run_id, ownership=env.ownership,
                          current_epoch=lambda: 5)
    assert [e.kind for e in entries] == [AnnotationKind.NOTE]


def test_commit_rerun_direct_race_creates_no_run_and_does_not_call_the_reader():
    env, log, run1, s2 = _setup()
    kw = {"ownership": env.ownership, "current_epoch": lambda: 5}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", KEY, run1.run_id, s2.snapshot_id, **kw)
    log.race['armed'] = True
    reads = env.reader_calls
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(out) is SafeError and out.reason_code is R.RATE_LIMITED
    assert env.reader_calls == reads and len(env.ledger.list_runs("t1", KEY)) == 1


def test_slot_taken_while_the_reader_runs_cannot_steal_the_reserved_audit_slot():
    env, log, run1, s2 = _setup()
    kw = {"ownership": env.ownership, "current_epoch": lambda: 5}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", KEY, run1.run_id, s2.snapshot_id, **kw)
    stolen = []

    def reader(tenant, snapshot_id):
        stolen.append(log._append(tenant, run1.run_id, "racer", AnnotationKind.NOTE, "x", None, None, T0))
        return env.reader(tenant, snapshot_id)

    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, reader, actor_id="alice", **kw)
    assert stolen == [None]  # the reservation holds the only slot
    assert type(out) is RerunOutcome and out.annotated is True
    entries = log._entries[("t1", run1.run_id)]
    assert [e.kind for e in entries] == [AnnotationKind.RERUN_REQUESTED]
    assert entries[0].related_run_id == out.new_run_id


def test_reservation_is_released_when_the_commit_fails_after_reserving():
    env, log, run1, s2 = _setup()
    kw = {"ownership": env.ownership, "current_epoch": lambda: 5}
    plan = check_rerun(env.ledger, env.store, log, env.viewer, "t1", KEY, run1.run_id, s2.snapshot_id, **kw)
    env.reader_error = RuntimeError("down")
    out = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(out) is SafeError and out.reason_code is R.DEPENDENCY_FAILED
    assert len(env.ledger.list_runs("t1", KEY)) == 1
    assert log._has_room("t1", run1.run_id)  # the slot is free again, nothing leaked
    env.reader_error = None
    ok = commit_rerun(env.ledger, env.store, log, env.viewer, plan, env.reader, actor_id="alice", **kw)
    assert type(ok) is RerunOutcome and ok.annotated is True


def test_normal_rerun_is_annotated_and_reservations_do_not_leak():
    env, log, run1, s2 = _setup(max_per_run=2)
    out = env.rerun(run1.run_id, s2.snapshot_id)
    assert out.allowed and len(env.ledger.list_runs("t1", KEY)) == 2
    assert len(log._entries[("t1", run1.run_id)]) == 1
    assert log._has_room("t1", run1.run_id)  # one slot of two used, none reserved any more
