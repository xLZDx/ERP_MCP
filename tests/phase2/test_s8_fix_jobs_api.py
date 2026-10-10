"""S8 review-fix batch (stream G2) for the safe job/result API decisions.

Covers: two-step rerun atomicity (no lock across dispatch, EFFECT_DONE completion), per-tenant quotas
and bounded memory, ownership/entitlement/capture-policy/operation binding, outcome validation and
events, hostile types, exact boundaries. Offline; fakes only.
"""
from __future__ import annotations

import dataclasses
import threading
from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2 import jobs_api
from business_ai_gateway.phase2.jobs_api import (
    OPERATION_FOR,
    ApiContext,
    ApiDecision,
    CsrfGuard,
    Endpoint,
    EventKind,
    FakeCapturePolicy,
    FakeEventSink,
    FakeJobDispatcher,
    FakeScopeEpochs,
    IdempotencyStore,
    JobKind,
    JobRequest,
    JobState,
    JobTicket,
    RefusalLog,
    RerunCommit,
    RerunRequest,
    RunState,
    SessionRecord,
    decide_enqueue,
    decide_rerun,
    fake_csrf_token,
    keyed_csrf_derive,
    read_job,
    read_result,
)
from business_ai_gateway.phase2.safe_errors import FakeCorrelationSource
from business_ai_gateway.phase2.side_effect_boundary import default_registry
from business_ai_gateway.phase2.workbench_types import (
    FakeEntitlements,
    FakeOwnership,
    NextAction,
    ReasonCode,
    ViewerScope,
)

R = ReasonCode
START = datetime(2026, 1, 1, tzinfo=UTC)
DIGEST = "a" * 64
POISON = "Traceback secret://vault/key-7 SELECT * FROM tenants ForeignSourceName"
JOIN = 10.0


class ManualClock:
    """Exact clock: moves only when told (the shared FakeClock ticks 1 microsecond per read)."""

    def __init__(self) -> None:
        self.t = START

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class Gate:
    def __init__(self) -> None:
        self.verdict: ReasonCode | None = None
        self.commit_result: object = None
        self.checks = 0
        self.commits = 0
        self.on_commit = None
        self._lock = threading.Lock()

    def check(self, request):
        with self._lock:
            self.checks += 1
        return self.verdict

    def commit(self, request):
        with self._lock:
            self.commits += 1
            n = self.commits
        if self.on_commit is not None:
            self.on_commit(request)
        if self.commit_result is not None:
            return self.commit_result
        return RerunCommit(f"run-new-{n}", RunState.CREATED)


class Env:
    def __init__(self, store: IdempotencyStore | None = None, dispatcher=None) -> None:
        self.clock = ManualClock()
        self.dispatcher = dispatcher or FakeJobDispatcher()
        self.scopes = FakeScopeEpochs({("T1", "C1"): 1, ("T2", "C1"): 1})
        self.idem = store or IdempotencyStore(64, 3600, per_tenant=32, per_actor=32)
        self.ownership, self.entitlements = FakeOwnership(), FakeEntitlements()
        self.capture, self.events = FakeCapturePolicy(), FakeEventSink()
        for tenant, actor in (("T1", "alice"), ("T2", "bob")):
            self.entitlements.grant(tenant, actor, "C1")
            for kind, ref in (("source_id", "SRC-1"), ("comparison_key", "CK-1"), ("run_id", "run-1"),
                              ("snapshot_id", "SN-2"), ("snapshot_id", "SN-3"), ("report_id", "R-1"),
                              ("snapshot_id", "SN-4")):
                self.ownership.add(tenant, "C1", kind, ref)
        self.ctx = ApiContext(
            csrf=CsrfGuard(fake_csrf_token), scopes=self.scopes, registry=default_registry(),
            refusals=RefusalLog(), idempotency=self.idem, dispatcher=self.dispatcher,
            clock=self.clock, correlation=FakeCorrelationSource(), ownership=self.ownership,
            entitlements=self.entitlements, capture_policy=self.capture, events=self.events)

    def session(self, tenant="T1", actor="alice", seconds=7200) -> SessionRecord:
        return SessionRecord("S-" + actor, tenant, actor, START + timedelta(seconds=seconds), DIGEST)

    def rerun(self, key="idem-rerun-01", snapshot="SN-2", tenant="T1", actor="alice",
              comparison="CK-1", prev="run-1", company="C1", epoch=1) -> ApiDecision:
        s = self.session(tenant, actor)
        req = RerunRequest(ViewerScope(tenant, company, epoch), actor, comparison, prev, snapshot, key)
        return decide_rerun(self.ctx, req, s, fake_csrf_token(s), self.gate)

    def enqueue(self, kind=JobKind.RESCAN, params=(("source_id", "SRC-1"),), key="idem-key-0001",
                tenant="T1", actor="alice", operation=None, company="C1", epoch=1) -> ApiDecision:
        s = self.session(tenant, actor)
        req = JobRequest(ViewerScope(tenant, company, epoch), actor, kind,
                         OPERATION_FOR[kind] if operation is None else operation, params, key)
        return decide_enqueue(self.ctx, req, s, fake_csrf_token(s))

    gate = Gate()


@pytest.fixture
def env() -> Env:
    e = Env()
    e.gate = Gate()
    return e


def _shape(d: ApiDecision) -> tuple:
    return dataclasses.astuple(dataclasses.replace(d, correlation_id="X"))


# ---------------------------------------------------------------- 1. rerun atomicity / locking

class FlakyDispatcher(FakeJobDispatcher):
    def __init__(self, fail_times: int = 1) -> None:
        super().__init__()
        self.fail_times = fail_times

    def dispatch(self, tenant_id, company_id, kind, request_digest):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError(POISON)
        return super().dispatch(tenant_id, company_id, kind, request_digest)


def test_dispatch_failure_then_retry_completes_the_same_run_never_stale():
    env = Env(dispatcher=FlakyDispatcher(1))
    env.gate = Gate()
    first = env.rerun()
    assert first.allowed is False and first.reason_code is R.DEPENDENCY_FAILED
    assert first.next_action is NextAction.RETRY_LATER and POISON not in repr(first)
    assert env.gate.commits == 1 and len(env.idem.effects) == 1
    env.gate.verdict = R.RERUN_TARGET_STALE  # the head moved because of the committed run
    retry = env.rerun()
    assert retry.allowed and retry.http_class == 202 and retry.reason_code is None
    assert retry.ticket.run_id == "run-new-1" and retry.ticket.run_state is RunState.CREATED
    assert env.gate.commits == 1 and env.gate.checks == 1  # no second run, no second check
    again = env.rerun()
    assert again.reason_code is R.REPLAYED and again.ticket == retry.ticket
    assert len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1
    assert [e.kind for e in env.events.events if e.kind is EventKind.DISPATCH_RETRY_PENDING]
    assert all(POISON not in repr(e) for e in env.events.events)


def test_dispatch_failing_twice_still_keeps_one_run():
    env = Env(dispatcher=FlakyDispatcher(2))
    env.gate = Gate()
    for _ in range(2):
        assert env.rerun().reason_code is R.DEPENDENCY_FAILED
    assert env.rerun().http_class == 202
    assert env.gate.commits == 1


def test_gate_commit_losing_the_race_is_a_verdict_and_records_nothing(env):
    env.gate.commit_result = R.RERUN_TARGET_STALE
    d = env.rerun()
    assert d.reason_code is R.RERUN_TARGET_STALE and d.http_class == 409
    assert env.idem.record_count() == 0 and env.dispatcher.calls == ()


def test_gate_commit_garbage_is_dependency_failed_without_a_record(env):
    for garbage in (POISON, 5, R.REPLAYED, object()):
        env.gate.commit_result = garbage
        d = env.rerun()
        assert d.reason_code is R.DEPENDENCY_FAILED and POISON not in repr(d)
    assert env.idem.record_count() == 0 and env.dispatcher.calls == ()


def test_blocked_action_on_one_key_does_not_block_another_key(env):
    started, release = threading.Event(), threading.Event()

    def on_commit(request):
        if request.new_snapshot_id == "SN-2":
            started.set()
            assert release.wait(JOIN)

    env.gate.on_commit = on_commit
    out: list[ApiDecision] = []
    t = threading.Thread(target=lambda: out.append(env.rerun(key="idem-rerun-K1", snapshot="SN-2")))
    t.start()
    assert started.wait(JOIN)
    other = env.rerun(key="idem-rerun-K2", snapshot="SN-3")  # must not wait for K1
    assert other.http_class == 202
    assert env.enqueue().http_class == 202
    release.set()
    t.join(JOIN)
    assert not t.is_alive() and out[0].http_class == 202


def test_same_key_waiter_replays_after_the_owner_finishes(env):
    started, release = threading.Event(), threading.Event()

    def on_commit(request):
        started.set()
        assert release.wait(JOIN)

    env.gate.on_commit = on_commit
    out: list[ApiDecision] = []
    ts = [threading.Thread(target=lambda: out.append(env.rerun())) for _ in range(2)]
    ts[0].start()
    assert started.wait(JOIN)
    ts[1].start()
    release.set()
    for t in ts:
        t.join(JOIN)
    assert sorted(d.http_class for d in out) == [200, 202] and env.gate.commits == 1


def test_reentrant_callback_does_not_deadlock(env):
    inner: list[ApiDecision] = []

    def on_commit(request):
        if request.new_snapshot_id == "SN-2":
            inner.append(env.rerun(key="idem-rerun-K2", snapshot="SN-3"))  # other key: fine
            inner.append(env.rerun(key="idem-rerun-K1", snapshot="SN-2"))  # same key: in flight

    env.gate.on_commit = on_commit
    out: list[ApiDecision] = []
    t = threading.Thread(target=lambda: out.append(env.rerun(key="idem-rerun-K1", snapshot="SN-2")))
    t.start()
    t.join(JOIN)
    assert not t.is_alive(), "re-entrant call deadlocked"
    assert out[0].http_class == 202 and inner[0].http_class == 202
    assert inner[1].reason_code is R.RATE_LIMITED  # never waits on itself


# ---------------------------------------------------------------- 2. quotas / bounded memory

def test_tenant_quota_isolates_other_tenants_and_is_observable():
    store = IdempotencyStore(8, 3600, per_tenant=2, per_actor=2)
    env = Env(store)
    env.gate = Gate()
    assert env.enqueue(key="idem-key-0001").http_class == 202
    assert env.enqueue(key="idem-key-0002").http_class == 202
    full = env.enqueue(key="idem-key-0003")
    assert full.reason_code is R.RATE_LIMITED and full.http_class == 429
    assert env.enqueue(key="idem-key-0001").reason_code is R.REPLAYED  # replays still work
    other = env.enqueue(key="idem-key-0001", tenant="T2", actor="bob")
    assert other.http_class == 202  # tenant B's first enqueue still succeeds
    assert env.rerun(key="idem-rerun-b1", tenant="T2", actor="bob").http_class == 202
    assert store.stats["full_actor"] + store.stats["full_tenant"] >= 1
    assert any(e.kind is EventKind.QUOTA_OVERFLOW for e in env.events.events)


def test_store_quota_parameters_are_validated():
    for kwargs in ({"per_tenant": 9}, {"per_actor": 5, "per_tenant": 4}, {"per_tenant": 0},
                   {"wait_seconds": -1}, {"per_tenant": True}):
        with pytest.raises(ValueError, match="^IDEMPOTENCY_STORE_INVALID$"):
            IdempotencyStore(8, 60, **kwargs)  # type: ignore[arg-type]


def test_a_hundred_thousand_executions_keep_memory_bounded():
    store = IdempotencyStore(200, 10, per_tenant=100, per_actor=50)
    ticket = JobTicket("JOB-1", "T1", "C1", JobKind.RESCAN, DIGEST)
    now = START
    new = 0
    for i in range(100_000):
        now += timedelta(milliseconds=5)
        status, _ = store.execute(f"T{i % 4}", f"A{i % 8}", Endpoint.ENQUEUE_JOB, f"k{i}", DIGEST,
                                  now, lambda: ticket)
        new += status == "NEW"
        if i % 20_000 == 0:
            assert store.record_count(now) <= 200
    assert store.record_count(now) <= 200
    assert len(store.effects) <= 1024 and store.effect_total == new
    assert len(store._heap) <= 2 * 200 + 256 + 1
    assert store.stats["expired"] > 0


def test_dispatcher_logs_and_jobs_are_bounded():
    d = FakeJobDispatcher(max_log=50, max_jobs=50)
    for _ in range(100_000):
        d.dispatch("T1", "C1", JobKind.RESCAN, DIGEST)
    assert d.call_count == 100_000 and len(d.calls) == 50 and d._n == 100_000
    assert len(d._jobs) == 50
    for _ in range(100):
        d.get("JOB-000001")
    assert len(d.get_log) == 50


def test_refusal_log_per_tenant_quota_and_overflow_counter():
    log = RefusalLog(max_entries=8, per_tenant=2)
    for i in range(5):
        log.record("T1", "C1", f"op_{i}", R.OPERATION_DENIED)
    log.record("T2", "C1", "op_0", R.OPERATION_DENIED)
    assert len([e for e in log.entries() if e[0] == "T1"]) == 2
    assert log.lookup("T2", "C1", "op_0") is R.OPERATION_DENIED
    assert log.overflow_count == 3
    with pytest.raises(ValueError, match="^REFUSAL_LOG_INVALID$"):
        RefusalLog(max_entries=4, per_tenant=5)


def test_peek_and_record_count_agree_with_execute_on_expiry():
    store = IdempotencyStore(8, 100, per_tenant=8, per_actor=8)
    ticket = JobTicket("JOB-1", "T1", "C1", JobKind.RESCAN, DIGEST)
    assert store.execute("T1", "a", Endpoint.RERUN, "k1", DIGEST, START, lambda: ticket)[0] == "NEW"
    just_before = START + timedelta(seconds=99)
    assert store.peek("T1", "a", Endpoint.RERUN, "k1", just_before) is not None
    assert store.execute("T1", "a", Endpoint.RERUN, "k1", DIGEST, just_before, lambda: ticket)[0] == "REPLAY"
    exactly = START + timedelta(seconds=100)  # retention window is [0, 100): expired AT 100
    assert store.peek("T1", "a", Endpoint.RERUN, "k1", exactly) is None
    assert store.record_count(exactly) == 0
    assert store.execute("T1", "a", Endpoint.RERUN, "k1", DIGEST, exactly, lambda: ticket)[0] == "NEW"
    store.execute("T1", "a", Endpoint.RERUN, "k2", DIGEST, exactly, lambda: ticket)
    later = exactly + timedelta(seconds=100)
    store.execute("T1", "a", Endpoint.RERUN, "k3", DIGEST, later, lambda: ticket)
    assert store.peek("T1", "a", Endpoint.RERUN, "k1") is None  # hint = latest execute time
    assert store.record_count() == 1


def test_peek_with_hostile_keys_never_raises():
    store = IdempotencyStore(4, 60, per_tenant=4, per_actor=4)
    for bad in ([], {}, object(), None, 5, b"x"):
        assert store.peek(bad, bad, Endpoint.RERUN, bad) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------- 3. ownership

def test_foreign_and_unknown_ids_refuse_identically_before_idempotency(env):
    env.ownership.add("T2", "C1", "source_id", "FOREIGN-SRC")  # exists, but for another tenant
    foreign = env.enqueue(params=(("source_id", "FOREIGN-SRC"),))
    unknown = env.enqueue(params=(("source_id", "NO-SUCH-SRC"),))
    assert foreign.reason_code is R.NOT_IN_SCOPE and foreign.http_class == 403
    assert _shape(foreign) == _shape(unknown)
    assert env.idem.record_count() == 0 and env.dispatcher.calls == ()
    for kind, params in ((JobKind.REPORT, (("report_id", "R-X"),)),
                         (JobKind.RECONCILIATION, (("comparison_key", "CK-1"), ("snapshot_id", "SN-X"))),
                         (JobKind.CAPTURE, (("source_id", "SRC-X"),))):
        env.capture.allow("T1", "C1", "alice")
        assert env.enqueue(kind=kind, params=params).reason_code is R.NOT_IN_SCOPE
    assert env.dispatcher.calls == ()


def test_rerun_checks_every_id_with_the_right_kind(env):
    base = env.rerun(key="idem-rerun-ok")
    assert base.http_class == 202
    for override in ({"comparison": "CK-X"}, {"prev": "run-X"}, {"snapshot": "SN-X"}):
        d = env.rerun(key="idem-rerun-new", **override)
        assert d.reason_code is R.NOT_IN_SCOPE and d.http_class == 403
    # kind binding: a run id is not a snapshot id
    assert env.rerun(key="idem-rerun-new", snapshot="run-1").reason_code is R.NOT_IN_SCOPE
    assert env.gate.commits == 1 and env.idem.record_count() == 1


def test_ownership_port_failures_fail_closed():
    class Boom:
        def owns(self, *args):
            raise RuntimeError(POISON)

    class Truthy:
        def owns(self, *args):
            return 1

    for port, reason in ((Boom(), R.DEPENDENCY_FAILED), (Truthy(), R.NOT_IN_SCOPE)):
        env = Env()
        env.gate = Gate()
        ctx = dataclasses.replace(env.ctx, ownership=port)
        s = env.session()
        req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                         (("source_id", "SRC-1"),), "idem-key-0001")
        d = decide_enqueue(ctx, req, s, fake_csrf_token(s))
        assert d.reason_code is reason and POISON not in repr(d) + repr(env.events.events)
        assert env.dispatcher.calls == ()


def test_read_foreign_company_and_missing_share_one_shape(env):
    ticket = env.enqueue().ticket
    env.entitlements.grant("T1", "alice", "C2")
    env.scopes.bump("T1", "C2")
    other_company = read_job(env.ctx, ViewerScope("T1", "C2", 1), env.session(), ticket.job_id)
    missing = read_job(env.ctx, ViewerScope("T1", "C2", 1), env.session(), "JOB-999999")
    assert other_company.reason_code is R.NOT_FOUND and _shape(other_company) == _shape(missing)


# ---------------------------------------------------------------- 4. entitlement / csrf

def test_non_member_and_unknown_company_are_indistinguishable_and_epoch_not_probeable(env):
    s = env.session("T1", "alice")
    env.entitlements = FakeEntitlements()  # alice is a member of nothing now
    ctx = dataclasses.replace(env.ctx, entitlements=env.entitlements)
    outcomes = []
    for company, epoch in (("C1", 1), ("C1", 99), ("C9", 1), ("C9", 5)):
        req = JobRequest(ViewerScope("T1", company, epoch), "alice", JobKind.RESCAN, "read_document",
                         (("source_id", "SRC-1"),), "idem-key-0001")
        outcomes.append(_shape(decide_enqueue(ctx, req, s, fake_csrf_token(s))))
        outcomes.append(_shape(read_job(ctx, ViewerScope("T1", company, epoch), s, "JOB-000001")))
    assert len(set(outcomes[0::2])) == 1 and len(set(outcomes[1::2])) == 1
    assert outcomes[0][2] is R.NOT_IN_SCOPE and outcomes[1][2] is R.NOT_IN_SCOPE


def test_member_with_stale_epoch_is_still_told_stale(env):
    assert env.enqueue(epoch=99).reason_code is R.SCOPE_EPOCH_STALE


def test_entitlement_failures_fail_closed(env):
    class Boom:
        def entitled(self, *args):
            raise RuntimeError(POISON)

    class Truthy:
        def entitled(self, *args):
            return "yes"

    for port, reason in ((Boom(), R.DEPENDENCY_FAILED), (Truthy(), R.NOT_IN_SCOPE)):
        ctx = dataclasses.replace(env.ctx, entitlements=port)
        s = env.session()
        d = read_job(ctx, ViewerScope("T1", "C1", 1), s, "JOB-000001")
        assert d.reason_code is reason and POISON not in repr(d)


def test_csrf_check_precedes_entitlement(env):
    s = env.session()
    req = JobRequest(ViewerScope("T1", "C9", 1), "alice", JobKind.RESCAN, "read_document",
                     (("source_id", "SRC-1"),), "idem-key-0001")
    assert decide_enqueue(env.ctx, req, s, "FAKE-bad").reason_code is R.CSRF_REJECTED


def test_keyed_csrf_derivation_is_keyed_and_actor_bound(env):
    key_a, key_b = b"k" * 32, b"j" * 32
    derive_a = keyed_csrf_derive(key_a)
    s_alice, s_bob = env.session("T1", "alice"), env.session("T1", "bob")
    assert derive_a(s_alice) == derive_a(s_alice) and derive_a(s_alice) != derive_a(s_bob)
    assert derive_a(s_alice) != keyed_csrf_derive(key_b)(s_alice) != fake_csrf_token(s_alice)
    guard = CsrfGuard(derive_a)
    assert guard.check(s_alice, derive_a(s_alice)) is True
    assert guard.check(s_alice, derive_a(s_bob)) is False
    assert guard.check(s_alice, keyed_csrf_derive(key_b)(s_alice)) is False
    assert guard.check(s_alice, fake_csrf_token(s_alice)) is False  # the test-only hash is not accepted
    for bad in (b"short", "k" * 32, None, 5):
        with pytest.raises(ValueError, match="^CSRF_SECRET_INVALID$"):
            keyed_csrf_derive(bad)  # type: ignore[arg-type]
    ctx = dataclasses.replace(env.ctx, csrf=guard)
    req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                     (("source_id", "SRC-1"),), "idem-key-0001")
    assert decide_enqueue(ctx, req, s_alice, derive_a(s_alice)).http_class == 202
    assert decide_enqueue(ctx, req, s_alice, derive_a(s_bob)).reason_code is R.CSRF_REJECTED


def test_session_is_bound_to_the_request_actor(env):
    s = env.session("T1", "alice")
    req = JobRequest(ViewerScope("T1", "C1", 1), "bob", JobKind.RESCAN, "read_document",
                     (("source_id", "SRC-1"),), "idem-key-0001")
    assert decide_enqueue(env.ctx, req, s, fake_csrf_token(s)).reason_code is R.SESSION_INVALID


def test_session_expires_exactly_at_the_boundary(env):
    s = env.session(seconds=60)
    req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                     (("source_id", "SRC-1"),), "idem-key-0001")
    env.clock.advance(59.999999)
    assert decide_enqueue(env.ctx, req, s, fake_csrf_token(s)).http_class == 202
    env.clock.advance(0.000001)  # now == expires_at exactly
    d = decide_enqueue(env.ctx, req, s, fake_csrf_token(s))
    assert d.reason_code is R.SESSION_INVALID and d.http_class == 401


def test_idempotency_retention_exactly_at_the_window(env):
    assert env.enqueue().http_class == 202
    env.clock.advance(3599)
    assert env.enqueue().reason_code is R.REPLAYED
    env.clock.advance(1)  # exactly the retention window
    assert env.enqueue().http_class == 202  # the idempotency slot is new again
    assert len(env.dispatcher.calls) == 1  # S8 GPT M06: same dispatch key -> the existing job is reused


# ---------------------------------------------------------------- 5. boundary binding / capture policy

def test_operation_must_match_the_kind_table_and_mismatch_is_not_sticky(env):
    mismatch = env.enqueue(operation="export_report")  # a valid read op, wrong for RESCAN
    assert mismatch.reason_code is R.OPERATION_DENIED and mismatch.http_class == 403
    assert env.enqueue(operation="list_catalogs").reason_code is R.OPERATION_DENIED
    assert env.idem.record_count() == 0 and env.dispatcher.calls == ()
    assert env.ctx.refusals.entries() == ()  # a mismatch must not poison the legit operation
    assert env.enqueue().http_class == 202
    assert env.enqueue(kind=JobKind.REPORT, params=(("report_id", "R-1"),),
                       key="idem-key-0002").http_class == 202
    assert OPERATION_FOR[JobKind.REPORT] == "export_report"


def test_capture_needs_the_injected_policy_grant_before_idempotency(env):
    params = (("source_id", "SRC-1"),)
    d = env.enqueue(kind=JobKind.CAPTURE, params=params)
    assert d.reason_code is R.OPERATION_DENIED
    assert env.idem.record_count() == 0 and env.dispatcher.calls == ()
    env.capture.allow("T1", "C1", "bob")  # another actor's grant does not count
    assert env.enqueue(kind=JobKind.CAPTURE, params=params).reason_code is R.OPERATION_DENIED
    env.capture.allow("T1", "C1", "alice")
    assert env.enqueue(kind=JobKind.CAPTURE, params=params).http_class == 202


def test_capture_policy_failures_fail_closed(env):
    class Boom:
        def allowed(self, *args):
            raise RuntimeError(POISON)

    class Truthy:
        def allowed(self, *args):
            return 1

    for port, reason in ((Boom(), R.DEPENDENCY_FAILED), (Truthy(), R.OPERATION_DENIED)):
        ctx = dataclasses.replace(env.ctx, capture_policy=port)
        s = env.session()
        req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.CAPTURE, "list_catalogs",
                         (("source_id", "SRC-1"),), "idem-key-0001")
        assert decide_enqueue(ctx, req, s, fake_csrf_token(s)).reason_code is reason
    assert env.dispatcher.calls == ()


def test_decide_enqueue_has_no_caller_supplied_capture_flag():
    import inspect
    assert list(inspect.signature(decide_enqueue).parameters) == ["ctx", "request", "session", "csrf_token"]


# ---------------------------------------------------------------- 6. outcomes / events / validation

def test_rerun_ticket_carries_run_id_and_state(env):
    t = env.rerun().ticket
    assert t.run_id == "run-new-1" and t.run_state is RunState.CREATED and t.kind is JobKind.RERUN
    assert env.enqueue().ticket.run_id is None
    for bad in ({"run_id": "bad id"}, {"run_state": RunState.CREATED}, {"run_id": "r1", "run_state": "CREATED"}):
        with pytest.raises(ValueError, match="^JOB_TICKET_INVALID$"):
            JobTicket("JOB-1", "T1", "C1", JobKind.RERUN, DIGEST, **bad)
    with pytest.raises(ValueError, match="^RERUN_COMMIT_INVALID$"):
        RerunCommit("bad id", RunState.CREATED)


def test_distinct_refusals_for_distinct_conditions(env):
    class Boom:
        def current_epoch(self, *args):
            raise RuntimeError(POISON)

    assert env.enqueue(params=(("source_id", POISON),)).reason_code is R.PARAMETER_SCHEMA_INVALID
    assert env.enqueue(epoch=9).reason_code is R.SCOPE_EPOCH_STALE
    ctx = dataclasses.replace(env.ctx, scopes=Boom())
    s = env.session()
    req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                     (("source_id", "SRC-1"),), "idem-key-0001")
    assert decide_enqueue(ctx, req, s, fake_csrf_token(s)).reason_code is R.DEPENDENCY_FAILED
    assert decide_enqueue(dataclasses.replace(ctx, csrf=object()), req, s, "x").reason_code \
        is R.INTERNAL_REFUSED  # an unusable context is a different condition
    events = env.events.events
    assert any(e.kind is EventKind.COMPONENT_EXCEPTION and e.error_class == "RuntimeError"
               and e.component.value == "SCOPES" and e.correlation_id.startswith("CORR-") for e in events)
    assert POISON not in repr(events)


def test_event_sink_failure_never_breaks_a_decision(env):
    class BadSink:
        def emit(self, event):
            raise RuntimeError(POISON)

    ctx = dataclasses.replace(env.ctx, events=BadSink(), dispatcher=FlakyDispatcher(1))
    s = env.session()
    req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                     (("source_id", "SRC-1"),), "idem-key-0001")
    assert decide_enqueue(ctx, req, s, fake_csrf_token(s)).reason_code is R.DEPENDENCY_FAILED
    assert decide_enqueue(dataclasses.replace(ctx, events=None), req, s,
                          fake_csrf_token(s)).http_class == 202


def test_empty_request_digest_refuses_internal_with_no_dispatch(env, monkeypatch):
    monkeypatch.setattr(jobs_api, "request_digest", lambda request, endpoint: "")
    assert env.enqueue().reason_code is R.INTERNAL_REFUSED
    assert env.rerun().reason_code is R.INTERNAL_REFUSED
    assert env.dispatcher.calls == () and env.idem.record_count() == 0 and env.gate.commits == 0


def test_invalid_job_id_from_dispatcher_cancels_the_orphan(env):
    class BadIds(FakeJobDispatcher):
        def dispatch(self, tenant_id, company_id, kind, request_digest):
            super().dispatch(tenant_id, company_id, kind, request_digest)
            return "bad id with spaces"

    env.dispatcher = BadIds()
    env.ctx = dataclasses.replace(env.ctx, dispatcher=env.dispatcher)
    d = env.enqueue()
    assert d.reason_code is R.DEPENDENCY_FAILED and env.idem.record_count() == 0
    assert env.dispatcher.cancel_log == ("bad id with spaces",)
    assert any(e.kind is EventKind.ORPHAN_JOB_CANCELLED for e in env.events.events)
    assert "bad id" not in repr(d)

    class NoIds(FakeJobDispatcher):
        def dispatch(self, *args):
            return 5

    env.ctx = dataclasses.replace(env.ctx, dispatcher=NoIds())
    assert env.enqueue().reason_code is R.DEPENDENCY_FAILED
    assert any(e.kind is EventKind.ORPHAN_JOB_UNREACHABLE for e in env.events.events)


def test_dispatcher_records_are_validated_before_disclosure(env):
    ticket = env.enqueue().ticket
    s, viewer = env.session(), ViewerScope("T1", "C1", 1)
    env.dispatcher.set_state(ticket.job_id, JobState.SUCCEEDED, "not-hex")
    assert read_result(env.ctx, viewer, s, ticket.job_id).reason_code is R.DEPENDENCY_FAILED
    env.dispatcher.set_state(ticket.job_id, JobState.SUCCEEDED, None)
    assert read_result(env.ctx, viewer, s, ticket.job_id).reason_code is R.DEPENDENCY_FAILED


def test_read_result_states_are_distinguishable_from_not_found(env):
    ticket = env.enqueue().ticket
    s, viewer = env.session(), ViewerScope("T1", "C1", 1)
    seen = {}
    for state in (JobState.QUEUED, JobState.RUNNING, JobState.FAILED):
        env.dispatcher.set_state(ticket.job_id, state)
        d = read_result(env.ctx, viewer, s, ticket.job_id)
        assert d.allowed and d.job.state is state and d.job.result_digest is None
        seen[state] = d.http_class
    assert seen == {JobState.QUEUED: 202, JobState.RUNNING: 202, JobState.FAILED: 200}
    env.dispatcher.set_state(ticket.job_id, JobState.SUCCEEDED, "b" * 64)
    assert read_result(env.ctx, viewer, s, ticket.job_id).job.result_digest == "b" * 64
    # another tenant sees the same NOT_FOUND shape for a RUNNING job as for a missing one
    env.dispatcher.set_state(ticket.job_id, JobState.RUNNING)
    s2, v2 = env.session("T2", "bob"), ViewerScope("T2", "C1", 1)
    foreign = read_result(env.ctx, v2, s2, ticket.job_id)
    missing = read_result(env.ctx, v2, s2, "JOB-777777")
    assert foreign.reason_code is R.NOT_FOUND and _shape(foreign) == _shape(missing)


# ---------------------------------------------------------------- 7. hostile types

class StrSub(str):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


class LyingReason:
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 1


def test_refusal_log_never_raises_on_hostile_keys():
    log = RefusalLog()
    hostile = [[], {}, set(), object(), None, 5, StrSub("T1"), b"x", ("a",)]
    for bad in hostile:
        log.record(bad, "C1", "op", R.OPERATION_DENIED)
        log.record("T1", bad, "op", R.OPERATION_DENIED)
        log.record("T1", "C1", bad, R.OPERATION_DENIED)
        log.record("T1", "C1", "op", bad)
        assert log.lookup(bad, bad, bad) is None and log.peek(bad, "C1", "op") is None
    assert log.entries() == () and log.overflow_count == 0


def test_api_decision_rejects_lying_reason_and_subclass_correlation():
    ok = {"next_action": NextAction.NO_ACTION, "correlation_id": "CORR-000001"}
    ticket = JobTicket("JOB-1", "T1", "C1", JobKind.RESCAN, DIGEST)
    with pytest.raises(ValueError, match="^API_DECISION_INVALID$"):
        ApiDecision(True, 202, LyingReason(), ticket=ticket, **ok)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="^API_DECISION_INVALID$"):
        ApiDecision(True, 202, None, next_action=NextAction.NO_ACTION, correlation_id=StrSub("CORR-1"),
                    ticket=ticket)
    assert ApiDecision(True, 202, None, ticket=ticket, **ok).allowed is True


def test_decisions_survive_a_lying_correlation_source(env):
    class Lying:
        def next_id(self):
            return StrSub("CORR-1")

    ctx = dataclasses.replace(env.ctx, correlation=Lying())
    s = env.session()
    req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                     (("source_id", "SRC-1"),), "idem-key-0001")
    d = decide_enqueue(ctx, req, s, fake_csrf_token(s))
    assert d.correlation_id == "CORR-UNASSIGNED" and d.allowed is False
    assert env.dispatcher.calls == ()


def test_missing_new_context_parts_fail_closed(env):
    for name in ("ownership", "entitlements", "capture_policy"):
        ctx = dataclasses.replace(env.ctx, **{name: object()})
        s = env.session()
        req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN, "read_document",
                         (("source_id", "SRC-1"),), "idem-key-0001")
        assert decide_enqueue(ctx, req, s, fake_csrf_token(s)).reason_code is R.INTERNAL_REFUSED
    assert env.dispatcher.calls == ()


@pytest.mark.parametrize("verdict,http", [
    (R.NOT_FOUND, 404), (R.RATE_LIMITED, 429), (R.SCOPE_EPOCH_STALE, 403),
    (R.DEPENDENCY_FAILED, 429), (R.INTERNAL_REFUSED, 400), (R.RERUN_TARGET_UNKNOWN, 404)])
def test_every_rerun_refusal_code_of_the_review_layer_maps_to_a_fixed_http_class(env, verdict, http):
    env.gate.verdict = verdict
    d = env.rerun()
    assert d.reason_code is verdict and d.http_class == http and d.ticket is None
    assert env.idem.record_count() == 0 and env.dispatcher.calls == ()


def test_new_reason_codes_have_constant_text():
    from business_ai_gateway.phase2.safe_errors import MESSAGES, render_safe_error
    from business_ai_gateway.phase2.workbench_types import safe_error
    for code in (R.ORIGINAL_UNVERIFIABLE, R.DEPENDENCY_FAILED):
        assert render_safe_error(safe_error(code, "CORR-000001")).message == MESSAGES[code]
