"""S8 review-fix batch (stream G4): the workbench session facade over the new interfaces.

Covers: acting identity (entitlement FIRST, identical NOT_IN_SCOPE for non-member / unknown company /
forged viewer, epoch not probeable), annotate actor + CSRF + expiry, company B versus company A's
references, the two-step rerun gate (dispatcher failing once, stale epoch bumped by the reader, bounded
plan table), per-tenant quota isolation, component failure mapping plus events, cards run states and
determinism of refusals. Offline; the real E1-E3 functions run over fakes.
"""
from __future__ import annotations

import dataclasses
import inspect
from datetime import timedelta

import pytest
from test_workbench_session import CORR, DIGEST, FAIL_G, FAIL_N, KEY, POISON, T0, Env

from business_ai_gateway.phase2.comparison_snapshot import RunLedger
from business_ai_gateway.phase2.jobs_api import (
    ApiDecision,
    ComponentName,
    EventKind,
    FakeJobDispatcher,
    FakeScopeEpochs,
    IdempotencyStore,
    JobKind,
    JobRequest,
    RerunCommit,
    RerunRequest,
    RunState,
    SessionRecord,
    fake_csrf_token,
)
from business_ai_gateway.phase2.workbench_review import CardsResult, ReviewLog
from business_ai_gateway.phase2.workbench_session import WorkbenchSession
from business_ai_gateway.phase2.workbench_types import (
    AnnotationKind,
    ReasonCode,
    SafeError,
    ViewerScope,
)

R = ReasonCode
NOTE = AnnotationKind.NOTE


# ------------------------------------------------------------------ helpers
class CountingEpochs(FakeScopeEpochs):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.reads = 0

    def current_epoch(self, tenant_id, company_id):
        self.reads += 1
        return super().current_epoch(tenant_id, company_id)


class RaisingEpochs(FakeScopeEpochs):
    def current_epoch(self, tenant_id, company_id):
        raise RuntimeError(POISON)


class FlakyDispatcher(FakeJobDispatcher):
    """Raises on the first ``fail_next`` dispatches, then behaves."""

    def __init__(self):
        super().__init__()
        self.fail_next = 1

    def dispatch(self, tenant_id, company_id, kind, request_digest, dispatch_key=None):
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError(POISON)
        return super().dispatch(tenant_id, company_id, kind, request_digest, dispatch_key)


def rebuild(env, *, review_log=None, reader=None, **ctx_changes):
    """Re-wire the facade over a changed ApiContext / review log / reader."""
    env.ctx = dataclasses.replace(env.ctx, **ctx_changes)
    if review_log is not None:
        env.review_log = review_log
    env.ws = WorkbenchSession(
        ledger=env.ledger, store=env.store, review_log=env.review_log, owners=env.owners,
        attestations=env.att, ctx=env.ctx, reader=reader or env.reader, subjects=env._subjects,
        feeds=lambda: (), matrix=lambda: env._maybe_raise("matrix") or env.matrix,
        policy=lambda: env.policy, evidence=lambda: env.evidence_rows)


def make_session(actor, tenant="t1", sid="S9", days=12):
    return SessionRecord(sid, tenant, actor, T0 + timedelta(days=days), DIGEST)


def shape(value):
    """The outward shape of a refusal or decision without its correlation id."""
    if type(value) is ApiDecision:
        return ("D", value.allowed, value.http_class, value.reason_code, value.next_action)
    if type(value) is SafeError:
        return ("E", value.reason_code, value.next_action)
    return ("V", type(value).__name__)


def add_bob(env):
    env.entitlements.grant("t1", "bob", "B")
    session = make_session("bob")
    return session, ViewerScope("t1", "B", 5), fake_csrf_token(session)


def add_tenant_t2(env):
    """A second tenant with one company C, one actor carol, one FAIL run and an owned source."""
    env.scopes.bump("t2", "C")  # epoch 1
    env.entitlements.grant("t2", "carol", "C")
    env.ownership.add("t2", "C", "source_id", "SRC-1")
    env.ownership.add("t2", "C", "comparison_key", "tb:t2")
    snap = env.store.create("t2", {"values": {"native": FAIL_N, "gateway": FAIL_G}}, known_at=T0)
    env.values[snap.snapshot_id] = (FAIL_N, FAIL_G)
    run = env.ledger.run("t2", "tb:t2", *env.reader("t2", snap.snapshot_id), snapshot_id=snap.snapshot_id)
    env.ownership.add("t2", "C", "run_id", run.run_id)
    session = make_session("carol", "t2", "S7")
    return session, ViewerScope("t2", "C", 1), fake_csrf_token(session), run


def unchanged(env, runs=1, dispatched=0, records=0):
    assert len(env.statuses()) == runs
    assert len(env.dispatcher.calls) == dispatched and env.idem.record_count() == records


# ------------------------------------------------------------------ company B versus company A
def test_company_b_gets_identical_refusals_for_a_keys_and_unknown_keys():
    env = Env()
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    assert env.ws.annotate(env.session, env.viewer, env.token(), run1.run_id, NOTE, "a note").seq == 1
    job_a = env.ws.enqueue(env.job_request(), env.session, env.token()).ticket.job_id
    bob, vb, btok = add_bob(env)
    card = env.ws.cards(env.session, env.viewer, KEY, source_id="src1").cards[0]

    def rerun(key, prev, snap, idem):
        return env.ws.rerun(RerunRequest(vb, "bob", key, prev, snap, idem), bob, btok)

    def enqueue(source, idem):
        return env.ws.enqueue(JobRequest(vb, "bob", JobKind.RESCAN, "read_document",
                                         (("source_id", source),), idem), bob, btok)

    pairs = {
        "cards": (env.ws.cards(bob, vb, KEY, source_id="src1"),
                  env.ws.cards(bob, vb, "tb:unknown", source_id="src1")),
        "cards_by_run": (env.ws.cards(bob, vb, KEY, source_id="src1", run_id=run1.run_id),
                         env.ws.cards(bob, vb, KEY, source_id="src1", run_id="run-unknown")),
        "annotate": (env.ws.annotate(bob, vb, btok, run1.run_id, NOTE, "x"),
                     env.ws.annotate(bob, vb, btok, "run-unknown", NOTE, "x")),
        "annotations": (env.ws.annotations(bob, vb, run1.run_id), env.ws.annotations(bob, vb, "run-unknown")),
        "rerun": (rerun(KEY, run1.run_id, s2.snapshot_id, "idem-bob-0001"),
                  rerun("tb:unknown", "run-unknown", "snap-unknown", "idem-bob-0002")),
        "enqueue": (enqueue("SRC-1", "idem-bob-1001"), enqueue("SRC-UNKNOWN", "idem-bob-1002")),
        "read_job": (env.ws.read_job(vb, bob, job_a), env.ws.read_job(vb, bob, "JOB-999999")),
        "read_result": (env.ws.read_result(vb, bob, job_a), env.ws.read_result(vb, bob, "JOB-999999")),
    }
    for name, (on_a, unknown) in pairs.items():
        assert shape(on_a) == shape(unknown), name
        assert shape(on_a)[0] in ("E", "D") and not _is_data(on_a), name
        assert POISON not in repr(on_a)
    assert {shape(p[0])[-2] for k, p in pairs.items() if k not in ("read_job", "read_result")} == {R.NOT_IN_SCOPE}
    assert pairs["read_job"][0].reason_code is R.NOT_FOUND and pairs["read_result"][0].reason_code is R.NOT_FOUND
    assert env.ws.verify_original(bob, vb, card) is R.NOT_IN_SCOPE
    # nothing of company A moved: ledger, review log, dispatcher and idempotency are as before
    unchanged(env, runs=1, dispatched=1, records=1)
    assert len(env.ws.annotations(env.session, env.viewer, run1.run_id)) == 1
    assert env.reader_calls == 1


def _is_data(value):
    return type(value) not in (SafeError, ApiDecision) or (type(value) is ApiDecision and value.allowed)


# ------------------------------------------------------------------ a forged ViewerScope is not an identity
FORGED = (("t1", "A", 5), ("t1", "A", 99), ("t1", "ZZ", 5), ("t2", "A", 5))


def test_non_entitled_actor_with_a_forged_viewer_is_refused_identically_and_the_epoch_is_not_probeable():
    env = Env(CountingEpochs)
    _, run1 = env.first_run()
    eve = make_session("eve", sid="S66")
    etok = fake_csrf_token(eve)
    reads_before = env.scopes.reads
    outcomes = {}
    for company, epoch in ((c, e) for _, c, e in FORGED[:3]):
        v = ViewerScope("t1", company, epoch)
        for name, call in {
            "cards": lambda v=v: env.ws.cards(eve, v, KEY, source_id="src1"),
            "annotate": lambda v=v: env.ws.annotate(eve, v, etok, run1.run_id, NOTE, "x"),
            "annotate_bad_csrf": lambda v=v: env.ws.annotate(eve, v, "FAKE-bad", run1.run_id, NOTE, "x"),
            "annotations": lambda v=v: env.ws.annotations(eve, v, run1.run_id),
            "timeline": lambda v=v: env.ws.timeline(eve, v),
            "coverage": lambda v=v: env.ws.coverage(eve, v),
            "diff": lambda v=v: env.ws.diff(eve, v),
            "evidence": lambda v=v: env.ws.evidence(eve, v),
            "rerun": lambda v=v: env.ws.rerun(RerunRequest(v, "eve", KEY, run1.run_id, "SN-1", "idem-eve-0001"),
                                              eve, etok),
            "enqueue": lambda v=v: env.ws.enqueue(JobRequest(v, "eve", JobKind.RESCAN, "read_document",
                                                              (("source_id", "SRC-1"),), "idem-eve-1001"),
                                                  eve, etok),
            "read_job": lambda v=v: env.ws.read_job(v, eve, "JOB-000001"),
        }.items():
            outcomes.setdefault(name, set()).add(shape(call()))
    other_tenant = ViewerScope("t2", "A", 5)  # a viewer of another tenant than the session's
    for name, call in {"cards": lambda: env.ws.cards(eve, other_tenant, KEY, source_id="src1"),
                       "annotate": lambda: env.ws.annotate(eve, other_tenant, etok, run1.run_id, NOTE, "x"),
                       "timeline": lambda: env.ws.timeline(eve, other_tenant),
                       "diff": lambda: env.ws.diff(eve, other_tenant)}.items():
        outcomes[name].add(shape(call()))
    for name, shapes in outcomes.items():
        assert len(shapes) == 1, (name, shapes)  # identical for every forged variant: no oracle
        (only,) = shapes
        assert only[-2] is R.NOT_IN_SCOPE, (name, only)
    assert env.ws.verify_original(eve, ViewerScope("t1", "A", 5), object()) is R.NOT_IN_SCOPE
    assert env.scopes.reads == reads_before  # entitlement first: the epoch source was never consulted
    unchanged(env)
    assert env.review_log.entries(env.viewer, "t1", run1.run_id, ownership=env.ownership,
                                  current_epoch=lambda: 5) == ()


def test_entitled_actor_still_gets_the_epoch_refusal_and_unknown_company_matches_a_non_member():
    env = Env()
    env.first_run()
    env.scopes.bump("t1", "A")
    assert env.ws.timeline(env.session, env.viewer).reason_code is R.SCOPE_EPOCH_STALE  # member: epoch visible
    unknown_company = env.ws.timeline(env.session, ViewerScope("t1", "NOPE", 5))
    stranger = env.ws.timeline(make_session("eve"), env.viewer)
    assert shape(unknown_company) == shape(stranger) and shape(stranger)[1] is R.NOT_IN_SCOPE


def test_every_public_method_takes_the_acting_session():
    for name in ("cards", "verify_original", "annotate", "annotations", "rerun", "enqueue", "read_job",
                 "read_result", "timeline", "coverage", "diff", "evidence"):
        assert "session" in inspect.signature(getattr(WorkbenchSession, name)).parameters, name
    assert "capture_allowed" not in inspect.signature(WorkbenchSession.enqueue).parameters


@pytest.mark.parametrize("bad", [None, "alice", object()])
def test_a_non_session_is_refused_as_session_invalid(bad):
    env = Env()
    env.first_run()
    result = env.ws.timeline(bad, env.viewer)
    assert type(result) is SafeError and result.reason_code is R.SESSION_INVALID
    assert env.ws.verify_original(bad, env.viewer, object()) is R.SESSION_INVALID


# ------------------------------------------------------------------ annotate: actor, CSRF, expiry
def test_annotate_records_the_session_actor_and_requires_csrf_and_a_live_session():
    env = Env()
    _, run1 = env.first_run()
    env.entitlements.grant("t1", "dana", "A")
    dana = make_session("dana", sid="S8")
    entry = env.ws.annotate(dana, env.viewer, fake_csrf_token(dana), run1.run_id, NOTE, "by dana")
    assert entry.actor_id == "dana" and entry.run_id == run1.run_id
    assert env.ws.annotate(env.session, env.viewer, env.token(), run1.run_id, NOTE, "by alice").actor_id == "alice"
    assert [e.actor_id for e in env.ws.annotations(env.session, env.viewer, run1.run_id)] == ["dana", "alice"]

    assert env.ws.annotate(env.session, env.viewer, "FAKE-bad", run1.run_id, NOTE, "x").reason_code is R.CSRF_REJECTED
    assert env.ws.annotate(env.session, env.viewer, fake_csrf_token(dana), run1.run_id, NOTE, "x"
                           ).reason_code is R.CSRF_REJECTED  # another actor's token
    expired = make_session("alice", sid="S3", days=1)
    assert env.ws.annotate(expired, env.viewer, fake_csrf_token(expired), run1.run_id, NOTE, "x"
                           ).reason_code is R.SESSION_INVALID
    assert env.ws.timeline(expired, env.viewer).reason_code is R.SESSION_INVALID
    assert len(env.ws.annotations(env.session, env.viewer, run1.run_id)) == 2  # refusals wrote nothing


def test_annotate_has_no_actor_parameter_so_an_actor_cannot_be_asserted():
    params = inspect.signature(WorkbenchSession.annotate).parameters
    assert "actor_id" not in params and "actor" not in params and "session" in params


def test_annotate_on_a_stale_epoch_writes_nothing_and_the_epoch_is_read_from_the_live_source():
    env = Env()
    _, run1 = env.first_run()
    env.scopes.bump("t1", "A")
    stale = env.ws.annotate(env.session, env.viewer, env.token(), run1.run_id, NOTE, "x")
    assert stale.reason_code is R.SCOPE_EPOCH_STALE
    fresh = ViewerScope("t1", "A", 6)
    assert env.ws.annotations(env.session, fresh, run1.run_id) == ()


# ------------------------------------------------------------------ rerun: two-step gate
def test_rerun_with_a_dispatcher_that_fails_once_gives_exactly_one_run_and_a_ticket_with_run_id_and_state():
    env = Env()
    flaky = FlakyDispatcher()
    rebuild(env, dispatcher=flaky)
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    reads0 = env.reader_calls  # the first run's own read
    first = env.rerun(run1.run_id, s2.snapshot_id)
    assert (first.allowed, first.reason_code, first.http_class) == (False, R.DEPENDENCY_FAILED, 429)
    assert POISON not in repr(first)
    assert len(env.statuses()) == 2 and env.reader_calls == reads0 + 1  # the run exists; only the hand-off failed
    run2_id = env.statuses()[-1][0]
    retry = env.rerun(run1.run_id, s2.snapshot_id)  # same idempotency key
    assert retry.allowed and retry.http_class == 202 and retry.reason_code is None
    assert retry.ticket.run_id == run2_id and retry.ticket.run_state is RunState.CREATED
    assert retry.ticket.kind is JobKind.RERUN
    assert len(env.statuses()) == 2 and env.reader_calls == reads0 + 1 and flaky.call_count == 1
    assert env.idem.effect_total == 1
    again = env.rerun(run1.run_id, s2.snapshot_id)
    assert again.reason_code is R.REPLAYED and again.ticket == retry.ticket
    assert [st for _, st in env.statuses()] == ["SUPERSEDED", "CURRENT"] and env.reader_calls == reads0 + 1
    assert env.ws._gate.pending() == 0


def test_a_scope_epoch_bumped_by_the_reader_creates_no_run_and_discloses_nothing():
    env = Env()
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))

    def bumping_reader(tenant, snapshot_id):
        out = env.reader(tenant, snapshot_id)
        env.scopes.bump("t1", "A")  # access revoked while the reader was running
        return out

    rebuild(env, reader=bumping_reader)
    d = env.rerun(run1.run_id, s2.snapshot_id)
    assert (d.allowed, d.reason_code, d.http_class) == (False, R.SCOPE_EPOCH_STALE, 403) and d.ticket is None
    assert len(env.statuses()) == 1 and len(env.dispatcher.calls) == 0
    assert env.review_log.entries(ViewerScope("t1", "A", 6), "t1", run1.run_id, ownership=env.ownership,
                                  current_epoch=lambda: 6) == ()
    assert env.ws.cards(env.session, env.viewer, KEY, source_id="src1").reason_code is R.SCOPE_EPOCH_STALE
    assert env.ws._gate.pending() == 0  # the plan was consumed by the commit attempt


def test_gate_check_is_pure_and_commit_creates_the_run_from_the_kept_plan():
    env = Env()
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    gate = env.ws._gate
    req = env.rerun_request(run1.run_id, s2.snapshot_id, "idem-gate-0001")
    assert gate.check(req) is None
    assert env.reader_calls == 1  # first_run read once; the pure check read nothing
    assert len(env.statuses()) == 1 and gate.pending() == 1
    committed = gate.commit(req)
    assert type(committed) is RerunCommit and committed.state is RunState.CREATED
    assert committed.run_id == env.statuses()[-1][0] and len(env.statuses()) == 2 and gate.pending() == 0
    # a refusal at check time keeps nothing
    assert gate.check(env.rerun_request(run1.run_id, s2.snapshot_id, "idem-gate-0002")) is R.RERUN_TARGET_STALE
    assert gate.pending() == 0


def test_gate_commit_without_a_kept_plan_derives_it_again_instead_of_acting_blind():
    env = Env()
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    committed = env.ws._gate.commit(env.rerun_request(run1.run_id, s2.snapshot_id, "idem-gate-0003"))
    assert type(committed) is RerunCommit and len(env.statuses()) == 2
    refused = env.ws._gate.commit(env.rerun_request("run-unknown", s2.snapshot_id, "idem-gate-0004"))
    assert refused is R.RERUN_TARGET_UNKNOWN or refused is R.NOT_IN_SCOPE  # never a commit


def test_the_plan_table_is_bounded():
    env = Env()
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    for n in range(1100):
        assert env.ws._gate.check(env.rerun_request(run1.run_id, s2.snapshot_id, f"idem-bound-{n:05d}")) is None
    assert env.ws._gate.pending() == 1024
    assert len(env.statuses()) == 1  # a thousand checks created nothing


def test_gate_codes_map_one_to_one_and_unexpected_codes_become_internal_refused():
    env = Env()
    s1, run1 = env.first_run()
    gate = env.ws._gate
    assert gate.check(env.rerun_request(run1.run_id, s1.snapshot_id, "idem-map-0001")) is R.NO_NEW_EVIDENCE
    env.ownership.add("t1", "A", "snapshot_id", "snap-missing")
    assert gate.check(env.rerun_request(run1.run_id, "snap-missing", "idem-map-0002")) is R.NOT_FOUND
    stale = ViewerScope("t1", "A", 4)
    req = RerunRequest(stale, "alice", KEY, run1.run_id, s1.snapshot_id, "idem-map-0003")
    assert gate.check(req) is R.SCOPE_EPOCH_STALE
    assert gate._code(env.ws.override()) is R.INTERNAL_REFUSED  # ORIGINAL_NUMBERS_IMMUTABLE is not a gate verdict
    assert gate._code(None) is R.INTERNAL_REFUSED


# ------------------------------------------------------------------ per-tenant quota isolation
def test_one_tenant_filling_its_annotation_quota_does_not_block_another_tenant():
    env = Env()
    _, run1 = env.first_run()
    rebuild(env, review_log=ReviewLog(env.clk.now, max_per_run=10, max_per_tenant=2))
    carol, vc, ctok, run_c = add_tenant_t2(env)
    for n in range(2):
        assert env.ws.annotate(env.session, env.viewer, env.token(), run1.run_id, NOTE, f"n{n}").seq == n + 1
    full = env.ws.annotate(env.session, env.viewer, env.token(), run1.run_id, NOTE, "one too many")
    assert type(full) is SafeError and full.reason_code is R.RATE_LIMITED
    other = env.ws.annotate(carol, vc, ctok, run_c.run_id, NOTE, "tenant two is unaffected")
    assert other.seq == 1 and other.actor_id == "carol" and other.tenant_id == "t2"
    assert len(env.ws.annotations(env.session, env.viewer, run1.run_id)) == 2
    assert len(env.ws.annotations(carol, vc, run_c.run_id)) == 1


def test_one_tenant_filling_its_idempotency_quota_does_not_block_another_tenant():
    env = Env()
    rebuild(env, idempotency=IdempotencyStore(8, 3600, per_tenant=2, per_actor=2))
    carol, vc, ctok, _ = add_tenant_t2(env)

    def enqueue(session, viewer, token, actor, idem):
        return env.ws.enqueue(JobRequest(viewer, actor, JobKind.RESCAN, "read_document",
                                         (("source_id", "SRC-1"),), idem), session, token)

    results = [enqueue(env.session, env.viewer, env.token(), "alice", f"idem-q-{n:04d}") for n in range(3)]
    assert [d.http_class for d in results] == [202, 202, 429]
    assert results[2].reason_code is R.RATE_LIMITED and len(env.dispatcher.calls) == 2
    ok = enqueue(carol, vc, ctok, "carol", "idem-q-t2-01")
    assert ok.allowed and ok.http_class == 202 and ok.ticket.tenant_id == "t2"
    assert len(env.dispatcher.calls) == 3


# ------------------------------------------------------------------ failure mapping and events
def _events(env, kind=None):
    return [e for e in env.events.events if kind is None or e.kind is kind]


def test_a_provider_exception_is_internal_refused_with_an_event_of_class_name_and_correlation_only():
    env = Env()
    _, run1 = env.first_run(FAIL_N, FAIL_N)
    env.raise_in = "matrix"
    result = env.ws.coverage(env.session, env.viewer)
    assert type(result) is SafeError and result.reason_code is R.INTERNAL_REFUSED
    (event,) = _events(env)
    assert (event.kind, event.component, event.error_class) == (
        EventKind.UNEXPECTED_EXCEPTION, ComponentName.UNEXPECTED, "RuntimeError")
    assert event.correlation_id == result.correlation_id and CORR.fullmatch(event.correlation_id)
    assert POISON not in repr(event) and POISON not in repr(result)
    env.raise_in = "subjects"
    again = env.ws.diff(env.session, env.viewer)
    assert again.reason_code is R.INTERNAL_REFUSED and len(_events(env)) == 2
    assert run1.run_id not in repr(_events(env))


def test_an_internal_refusal_returned_by_a_component_is_reported_too(monkeypatch):
    env = Env()
    env.first_run()

    def boom(self, *a, **k):
        raise RuntimeError(POISON)

    monkeypatch.setattr(RunLedger, "current", boom)
    result = env.ws.cards(env.session, env.viewer, KEY, source_id="src1")  # E1 swallows it into a SafeError
    assert type(result) is SafeError and result.reason_code is R.INTERNAL_REFUSED
    assert result.correlation_id != "CORR-UNASSIGNED" and POISON not in repr(result)
    (event,) = _events(env, EventKind.UNEXPECTED_EXCEPTION)
    assert event.correlation_id == result.correlation_id and event.error_class == ""


def test_a_failing_epoch_source_is_dependency_failed_not_a_stale_epoch():
    env = Env()
    _, run1 = env.first_run()
    rebuild(env, scopes=RaisingEpochs({("t1", "A"): 5}))
    for result in (env.ws.cards(env.session, env.viewer, KEY, source_id="src1"),
                   env.ws.annotate(env.session, env.viewer, env.token(), run1.run_id, NOTE, "x"),
                   env.ws.annotations(env.session, env.viewer, run1.run_id)):
        assert type(result) is SafeError and result.reason_code is R.DEPENDENCY_FAILED
        assert POISON not in repr(result) and CORR.fullmatch(result.correlation_id)


def test_a_failing_entitlement_port_is_dependency_failed_with_an_event_and_reads_nothing():
    env = Env()
    env.first_run()

    class Broken:
        def entitled(self, tenant_id, actor_id, company_id):
            raise RuntimeError(POISON)

    rebuild(env, entitlements=Broken())
    for result in (env.ws.timeline(env.session, env.viewer), env.ws.cards(env.session, env.viewer, KEY, source_id="s"),
                   env.ws.annotate(env.session, env.viewer, env.token(), "run-1", NOTE, "x")):
        assert type(result) is SafeError and result.reason_code is R.DEPENDENCY_FAILED
        assert POISON not in repr(result)
    events = _events(env, EventKind.COMPONENT_EXCEPTION)
    assert len(events) == 3 and {e.component for e in events} == {ComponentName.ENTITLEMENTS}
    assert {e.error_class for e in events} == {"RuntimeError"}


def test_a_non_boolean_entitlement_answer_fails_closed():
    env = Env()
    env.first_run()

    class Sloppy:
        def entitled(self, tenant_id, actor_id, company_id):
            return "yes"

    rebuild(env, entitlements=Sloppy())
    result = env.ws.timeline(env.session, env.viewer)
    assert type(result) is SafeError and result.reason_code is R.NOT_IN_SCOPE
    assert _events(env)[0].kind is EventKind.COMPONENT_OUTPUT_INVALID


def test_a_raising_or_missing_event_sink_never_breaks_a_refusal():
    class BadSink:
        def emit(self, event):
            raise RuntimeError(POISON)

    for sink in (BadSink(), None):
        env = Env()
        env.first_run()
        rebuild(env, events=sink)
        env.raise_in = "matrix"
        result = env.ws.coverage(env.session, env.viewer)
        assert type(result) is SafeError and result.reason_code is R.INTERNAL_REFUSED


def test_a_gate_exception_is_dependency_failed_and_leaves_no_run():
    env = Env()
    _, run1 = env.first_run()
    s2 = env.snapshot(dict(FAIL_N), dict(FAIL_N))
    env.reader_error = RuntimeError(POISON)
    d = env.rerun(run1.run_id, s2.snapshot_id)
    assert (d.reason_code, d.http_class) == (R.DEPENDENCY_FAILED, 429)
    assert len(env.statuses()) == 1 and env.ws._gate.pending() == 0 and len(env.dispatcher.calls) == 0


# ------------------------------------------------------------------ cards run state
def test_cards_result_keeps_no_run_pass_and_fail_apart():
    env = Env()
    env.ownership.add("t1", "A", "comparison_key", "tb:norun")
    env.first_run(FAIL_N, FAIL_N, key="tb:pass")
    _, run_fail = env.first_run()
    none = env.ws.cards(env.session, env.viewer, "tb:norun", source_id="src1")
    passed = env.ws.cards(env.session, env.viewer, "tb:pass", source_id="src1")
    failed = env.ws.cards(env.session, env.viewer, KEY, source_id="src1")
    assert all(type(r) is CardsResult for r in (none, passed, failed))
    assert (none.run_state, none.run_id, none.cards) == ("NO_RUN", None, ())
    assert (passed.run_state, passed.cards) == ("PASS", ()) and passed.run_id is not None
    assert (failed.run_state, failed.run_id, len(failed.cards)) == ("FAIL", run_fail.run_id, 2)
    assert none != passed != failed


# ------------------------------------------------------------------ determinism of refusals
def _refusal_script(env):
    env.first_run()
    eve = make_session("eve", sid="S66")
    out = []
    for company, epoch in (("A", 5), ("A", 99), ("ZZ", 5)):
        v = ViewerScope("t1", company, epoch)
        out += [repr(env.ws.cards(eve, v, KEY, source_id="src1")), repr(env.ws.timeline(eve, v)),
                repr(env.ws.annotate(eve, v, fake_csrf_token(eve), "run-1", NOTE, "x")),
                repr(env.ws.read_job(v, eve, "JOB-000001"))]
    return out


def test_refusals_are_byte_identical_across_two_identical_environments():
    first, second = _refusal_script(Env()), _refusal_script(Env())
    assert first == second and len(first) == 12
    assert all("CORR-" in line for line in first)
