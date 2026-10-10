"""S8 GPT-PM gate remediation (stream K1) for the safe job/result API decisions.

M04 rerun side-effect refusal, M06 durable dispatch idempotency, M07 forged RerunCommit, M08 foreign
malformed record oracle, M09 entitlement revoked during a read, plus the event-sink class-name allow-list.
Offline; fakes only.
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from business_ai_gateway.phase2.jobs_api import (
    OPERATION_FOR,
    ApiContext,
    ApiDecision,
    ApiEvent,
    CsrfGuard,
    EventKind,
    FakeCapturePolicy,
    FakeEventSink,
    FakeJobDispatcher,
    FakeScopeEpochs,
    IdempotencyStore,
    JobKind,
    JobRecord,
    JobRequest,
    JobState,
    RefusalLog,
    RerunCommit,
    RerunRequest,
    RunState,
    SessionRecord,
    decide_enqueue,
    decide_rerun,
    fake_csrf_token,
    read_job,
    read_result,
)
from business_ai_gateway.phase2.safe_errors import FakeCorrelationSource
from business_ai_gateway.phase2.side_effect_boundary import default_registry
from business_ai_gateway.phase2.workbench_types import (
    FakeEntitlements,
    FakeOwnership,
    ReasonCode,
    ViewerScope,
)

R = ReasonCode
START = datetime(2026, 1, 1, tzinfo=UTC)
DIGEST = "a" * 64
POISON = "Traceback secret://vault/key-7 SELECT * FROM tenants ForeignSourceName"


class Clock:
    def now(self) -> datetime:
        return START


class Gate:
    def __init__(self) -> None:
        self.commits = 0
        self.checks = 0
        self.commit_result: object = None

    def check(self, request):
        self.checks += 1

    def commit(self, request):
        self.commits += 1
        if self.commit_result is not None:
            return self.commit_result
        return RerunCommit(f"run-new-{self.commits}", RunState.CREATED)


class Entitlements(FakeEntitlements):
    """Entitlements with a test-only revoke."""

    def __init__(self) -> None:
        super().__init__()
        self.revoked = False

    def entitled(self, tenant_id, actor_id, company_id) -> bool:
        return (not self.revoked) and super().entitled(tenant_id, actor_id, company_id)


class Env:
    def __init__(self, dispatcher=None) -> None:
        self.dispatcher = dispatcher or FakeJobDispatcher()
        self.scopes = FakeScopeEpochs({("T1", "C1"): 1})
        self.idem = IdempotencyStore(64, 3600, per_tenant=32, per_actor=32)
        self.ownership, self.entitlements = FakeOwnership(), Entitlements()
        self.events = FakeEventSink()
        self.refusals = RefusalLog()
        self.gate = Gate()
        self.entitlements.grant("T1", "alice", "C1")
        for kind, ref in (("source_id", "SRC-1"), ("comparison_key", "CK-1"), ("run_id", "run-1"),
                          ("snapshot_id", "SN-2")):
            self.ownership.add("T1", "C1", kind, ref)
        self.ctx = ApiContext(
            csrf=CsrfGuard(fake_csrf_token), scopes=self.scopes, registry=default_registry(),
            refusals=self.refusals, idempotency=self.idem, dispatcher=self.dispatcher,
            clock=Clock(), correlation=FakeCorrelationSource(), ownership=self.ownership,
            entitlements=self.entitlements, capture_policy=FakeCapturePolicy(), events=self.events)

    def session(self) -> SessionRecord:
        return SessionRecord("S-alice", "T1", "alice", START + timedelta(hours=2), DIGEST)

    def rerun(self, key="idem-rerun-01") -> ApiDecision:
        s = self.session()
        req = RerunRequest(ViewerScope("T1", "C1", 1), "alice", "CK-1", "run-1", "SN-2", key)
        return decide_rerun(self.ctx, req, s, fake_csrf_token(s), self.gate)

    def enqueue(self, key="idem-key-0001") -> ApiDecision:
        s = self.session()
        req = JobRequest(ViewerScope("T1", "C1", 1), "alice", JobKind.RESCAN,
                         OPERATION_FOR[JobKind.RESCAN], (("source_id", "SRC-1"),), key)
        return decide_enqueue(self.ctx, req, s, fake_csrf_token(s))

    def read(self, job_id, fn=read_job) -> ApiDecision:
        return fn(self.ctx, ViewerScope("T1", "C1", 1), self.session(), job_id)


def _shape(d: ApiDecision) -> tuple:
    return dataclasses.astuple(dataclasses.replace(d, correlation_id="X"))


# ---------------------------------------------------------------- M04

def test_m04_recorded_denial_blocks_rerun_before_commit():
    env = Env()
    env.refusals.record("T1", "C1", OPERATION_FOR[JobKind.RERUN], R.OPERATION_DENIED)
    d = env.rerun()
    assert d.allowed is False and d.reason_code is R.OPERATION_DENIED
    assert env.gate.commits == 0 and env.gate.checks == 0
    assert env.dispatcher.call_count == 0 and env.idem.effect_total == 0
    assert env.idem.record_count() == 0


# ---------------------------------------------------------------- M06

class LossyDispatcher(FakeJobDispatcher):
    """Creates the job, then loses the reply (raises) for the first ``lose`` calls."""

    def __init__(self, lose: int = 1) -> None:
        super().__init__()
        self.lose = lose

    def dispatch(self, tenant_id, company_id, kind, request_digest, dispatch_key=None):
        job_id = super().dispatch(tenant_id, company_id, kind, request_digest, dispatch_key)
        if self.lose > 0:
            self.lose -= 1
            raise RuntimeError(POISON)
        return job_id


def test_m06_enqueue_lost_reply_then_retry_creates_one_job():
    env = Env(LossyDispatcher())
    first = env.enqueue()
    assert first.allowed is False and first.reason_code is R.DEPENDENCY_FAILED
    second = env.enqueue()
    assert second.allowed is True and second.ticket is not None
    assert len(env.dispatcher._jobs) == 1
    assert second.ticket.job_id == "JOB-000001"
    third = env.enqueue()
    assert third.ticket == second.ticket and len(env.dispatcher._jobs) == 1


def test_m06_rerun_lost_reply_then_retry_creates_one_run_and_one_job():
    env = Env(LossyDispatcher())
    first = env.rerun()
    assert first.allowed is False and first.reason_code is R.DEPENDENCY_FAILED
    second = env.rerun()
    assert second.allowed is True and second.ticket is not None
    assert env.gate.commits == 1
    assert len(env.dispatcher._jobs) == 1
    assert second.ticket.run_id == "run-new-1"


def test_m06_dispatch_key_is_deterministic_and_not_the_raw_key():
    env = Env()
    env.enqueue(key="idem-key-0001")
    env.enqueue(key="idem-key-0002")
    keys = list(env.dispatcher._by_key)
    assert len(keys) == 2 and len(set(keys)) == 2
    assert all(len(k) == 64 and "idem-key" not in k for k in keys)
    assert env.dispatcher.find(keys[0]) == "JOB-000001"
    assert env.dispatcher.find("0" * 64) is None


# ---------------------------------------------------------------- M07

def _forged(run_id: object, state: object = RunState.CREATED) -> RerunCommit:
    forged = object.__new__(RerunCommit)
    object.__setattr__(forged, "run_id", run_id)
    object.__setattr__(forged, "state", state)
    return forged


def test_m07_forged_commit_never_reaches_dispatcher_nor_records_an_effect():
    for bad in (_forged("bad id with spaces"), _forged(POISON), _forged("run-x", "CREATED"),
                _forged(42), object.__new__(RerunCommit)):
        env = Env()
        env.gate.commit_result = bad
        d = env.rerun()
        assert d.allowed is False and d.reason_code is R.DEPENDENCY_FAILED
        assert env.dispatcher.call_count == 0
        assert env.idem.effect_total == 0 and env.idem.record_count() == 0
        assert POISON not in repr(d)


def test_m07_post_dispatch_ticket_failure_cancels_the_job():
    class Bad(FakeJobDispatcher):
        def dispatch(self, tenant_id, company_id, kind, request_digest, dispatch_key=None):
            super().dispatch(tenant_id, company_id, kind, request_digest, dispatch_key)
            return "bad id with spaces"

    env = Env(Bad())
    d = env.enqueue()
    assert d.allowed is False and d.reason_code is R.DEPENDENCY_FAILED
    assert env.dispatcher.cancel_log == ("bad id with spaces",)


# ---------------------------------------------------------------- M08

class Foreign(FakeJobDispatcher):
    def __init__(self, record) -> None:
        super().__init__()
        self.record = record

    def get(self, job_id):
        return self.record


def test_m08_missing_foreign_valid_foreign_malformed_are_identical():
    foreign_ok = JobRecord("JOB-X", "T9", "C9", JobKind.RESCAN, JobState.QUEUED)
    foreign_bad = JobRecord("JOB-X", "T9", "C9", JobKind.RESCAN, "not-a-state")  # type: ignore[arg-type]
    foreign_bad2 = JobRecord("JOB-X", "T9", POISON * 3, "x", JobState.QUEUED)  # type: ignore[arg-type]
    foreign_bad3 = JobRecord("JOB-X", 7, None, JobKind.RESCAN, JobState.QUEUED)  # type: ignore[arg-type]
    shapes = set()
    for rec in (None, foreign_ok, foreign_bad, foreign_bad2, foreign_bad3):
        env = Env(Foreign(rec))
        for fn in (read_job, read_result):
            d = env.read("JOB-X", fn)
            assert d.allowed is False and d.reason_code is R.NOT_FOUND, rec
            shapes.add(_shape(d))
            assert "T9" not in repr(d) and POISON not in repr(d)
    assert len(shapes) == 1


# ---------------------------------------------------------------- M09

def test_m09_entitlement_revoked_during_fetch_with_same_epoch_does_not_disclose():
    for fn in (read_job, read_result):
        env = Env()
        job_id = env.dispatcher.dispatch("T1", "C1", JobKind.RESCAN, DIGEST)
        env.dispatcher.on_get = lambda e=env: setattr(e.entitlements, "revoked", True)
        d = env.read(job_id, fn)
        assert d.allowed is False and d.reason_code is R.NOT_IN_SCOPE
        assert d.job is None and d.ticket is None


def test_m09_unrevoked_read_still_discloses():
    env = Env()
    job_id = env.dispatcher.dispatch("T1", "C1", JobKind.RESCAN, DIGEST)
    assert env.read(job_id).allowed is True


# ---------------------------------------------------------------- event class-name allow-list

def test_event_error_class_is_allow_listed():
    class SecretLeakingNameXyz123(Exception):
        pass

    class Raising(FakeJobDispatcher):
        def dispatch(self, *args, **kwargs):
            raise SecretLeakingNameXyz123(POISON)

    env = Env(Raising())
    env.enqueue()
    names = {e.error_class for e in env.events.events if e.kind is EventKind.COMPONENT_EXCEPTION}
    assert names == {"OTHER"}

    class Builtin(FakeJobDispatcher):
        def dispatch(self, *args, **kwargs):
            raise RuntimeError(POISON)

    env = Env(Builtin())
    env.enqueue()
    assert {e.error_class for e in env.events.events if e.kind is EventKind.COMPONENT_EXCEPTION} == {
        "RuntimeError"}
    assert isinstance(env.events.events[0], ApiEvent)
