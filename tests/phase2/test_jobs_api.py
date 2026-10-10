"""S8/E3 TC121 + TC122: safe job/result API decisions, CSRF, idempotency, fixed check order.

Offline decision layer only: no server, no cookies, no HTTP. Refusal/poison rows come first.
"""
from __future__ import annotations

import dataclasses
import re
import threading
from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2 import jobs_api
from business_ai_gateway.phase2.fakes import FakeClock
from business_ai_gateway.phase2.jobs_api import (
    DECISION_ENDPOINTS,
    ENDPOINTS,
    OPERATION_FOR,
    ApiContext,
    ApiDecision,
    CsrfGuard,
    Endpoint,
    EndpointAnnotation,
    FakeCapturePolicy,
    FakeEventSink,
    FakeJobDispatcher,
    FakeScopeEpochs,
    IdempotencyStore,
    JobKind,
    JobRequest,
    JobTicket,
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
    NEXT_ACTION_FOR,
    FakeEntitlements,
    FakeOwnership,
    NextAction,
    ReasonCode,
    SafeError,
    ViewerScope,
    is_valid_safe_error,
)

POISON = "Traceback secret://vault/key-7 SELECT * FROM tenants provider-said-no ForeignSourceName"
GATE_HTTP = {ReasonCode.NO_NEW_EVIDENCE: 409, ReasonCode.RERUN_TARGET_STALE: 409,
             ReasonCode.SOURCE_PAUSED: 409, ReasonCode.NOT_IN_SCOPE: 403,
             ReasonCode.OPERATION_DENIED: 403}
CORR = re.compile(r"[A-Za-z0-9._:-]{1,64}")
DIGEST = "a" * 64
START = datetime(2026, 1, 1, tzinfo=UTC)
R = ReasonCode


class Env:
    """One wired offline environment plus the helpers every test needs."""

    def __init__(self, max_entries: int = 64, retention: int = 3600) -> None:
        self.clock = FakeClock(START)
        self.dispatcher = FakeJobDispatcher()
        self.scopes = FakeScopeEpochs({("T1", "C1"): 1, ("T2", "C1"): 1, ("T1", "C2"): 1})
        self.idem = IdempotencyStore(max_entries, retention, per_tenant=max_entries,
                                     per_actor=max_entries)
        self.refusals = RefusalLog()
        self.corr = FakeCorrelationSource()
        self.ownership, self.entitlements = FakeOwnership(), FakeEntitlements()
        self.capture = FakeCapturePolicy()
        self.events = FakeEventSink()
        for tenant, company, actor in (("T1", "C1", "alice"), ("T1", "C1", "bob"),
                                       ("T2", "C1", "bob"), ("T2", "C1", "alice"),
                                       ("T1", "C2", "alice")):
            self.entitlements.grant(tenant, actor, company)
            for kind, refs in (("source_id", ("SRC-1", "SRC-2", "X")), ("report_id", ("R-1",)),
                               ("comparison_key", ("CK-1",)), ("snapshot_id", ("SN-1", "SN-2", "SN-3")),
                               ("run_id", ("run-1",))):
                for ref in refs:
                    self.ownership.add(tenant, company, kind, ref)
        self.ctx = ApiContext(
            csrf=CsrfGuard(fake_csrf_token), scopes=self.scopes, registry=default_registry(),
            refusals=self.refusals, idempotency=self.idem, dispatcher=self.dispatcher,
            clock=self.clock, correlation=self.corr, ownership=self.ownership,
            entitlements=self.entitlements, capture_policy=self.capture, events=self.events)

    def session(self, sid: str = "S1", tenant: str = "T1", actor: str = "alice",
                hours: int = 1) -> SessionRecord:
        return SessionRecord(sid, tenant, actor, START + timedelta(hours=hours), DIGEST)

    def token(self, session: SessionRecord | None = None) -> str:
        return fake_csrf_token(session or self.session())

    def request(self, key: object = "idem-key-0001", tenant: str = "T1", company: str = "C1",
                epoch: int = 1, actor: str = "alice", kind: JobKind = JobKind.RESCAN,
                operation: str | None = None, params=(("source_id", "SRC-1"),)) -> JobRequest:
        operation = OPERATION_FOR[kind] if operation is None else operation
        return JobRequest(ViewerScope(tenant, company, epoch), actor, kind, operation, params, key)

    def enqueue(self, request: JobRequest | None = None, session=None, token=None) -> ApiDecision:
        session = session or self.session()
        return decide_enqueue(self.ctx, request or self.request(), session,
                              self.token(session) if token is None else token)


@pytest.fixture
def env() -> Env:
    return Env()


def _check_refusal(d: ApiDecision, code: ReasonCode, http: int) -> None:
    assert type(d) is ApiDecision
    assert d.allowed is False and d.reason_code is code and d.http_class == http
    assert d.next_action is NEXT_ACTION_FOR[code]
    assert CORR.fullmatch(d.correlation_id)
    assert d.ticket is None and d.job is None
    err = d.safe_error()
    assert type(err) is SafeError and is_valid_safe_error(err)
    assert (err.reason_code, err.next_action, err.correlation_id) == (
        code, NEXT_ACTION_FOR[code], d.correlation_id)


# ================================ TC121: safe refusals =======================================

def test_decision_fields_are_exactly_the_fixed_set():
    assert [f.name for f in dataclasses.fields(ApiDecision)] == [
        "allowed", "http_class", "reason_code", "next_action", "correlation_id", "ticket", "job",
        "authority"]


def test_endpoint_annotation_table_is_complete_and_correct():
    assert set(ENDPOINTS) == set(Endpoint)
    mutating = {Endpoint.ENQUEUE_JOB, Endpoint.RERUN, Endpoint.PAUSE_SOURCE,
                Endpoint.REVOKE_ATTESTATION}
    for endpoint, note in ENDPOINTS.items():
        assert type(note) is EndpointAnnotation
        assert note.idempotent is True and note.destructive is False and note.open_world is False
        assert note.read_only is (endpoint not in mutating)
    assert {Endpoint.READ_JOB, Endpoint.READ_RESULT} == set(Endpoint) - mutating
    with pytest.raises(TypeError):
        ENDPOINTS[Endpoint.RERUN] = EndpointAnnotation(True, False, True, False)  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ENDPOINTS[Endpoint.RERUN].read_only = True  # type: ignore[misc]


def test_every_public_decision_function_has_an_annotated_endpoint():
    public = {n for n in jobs_api.__all__ if n.startswith(("decide_", "read_"))}
    assert public == set(DECISION_ENDPOINTS) == {
        "decide_enqueue", "decide_rerun", "read_job", "read_result"}
    for name, endpoint in DECISION_ENDPOINTS.items():
        assert endpoint in ENDPOINTS
        assert callable(getattr(jobs_api, name))
    assert not ENDPOINTS[DECISION_ENDPOINTS["decide_enqueue"]].read_only
    assert not ENDPOINTS[DECISION_ENDPOINTS["decide_rerun"]].read_only
    assert ENDPOINTS[DECISION_ENDPOINTS["read_job"]].read_only


def test_every_refusal_path_is_a_safe_error_shape(env):
    scenarios = {
        (R.SESSION_INVALID, 401): lambda: decide_enqueue(env.ctx, env.request(), None, env.token()),
        (R.CSRF_REJECTED, 403): lambda: env.enqueue(token="FAKE-wrong"),
        (R.SCOPE_EPOCH_STALE, 403): lambda: env.enqueue(env.request(epoch=99)),
        (R.OPERATION_DENIED, 403): lambda: env.enqueue(env.request(operation="post_document")),
        (R.OPERATION_UNCLASSIFIED, 403): lambda: env.enqueue(env.request(operation="no_such_op")),
        (R.PARAMETER_SCHEMA_INVALID, 400): lambda: env.enqueue(
            env.request(params=(("unknown_field", "x"),))),
        (R.IDEMPOTENCY_KEY_REQUIRED, 400): lambda: env.enqueue(env.request(key=None)),
    }
    for (code, http), run in scenarios.items():
        _check_refusal(run(), code, http)
    assert env.dispatcher.calls == ()
    assert env.idem.record_count() == 0


def test_conflict_and_capacity_refusals_have_safe_shape(env):
    first = env.enqueue()
    assert first.http_class == 202
    other = env.request(params=(("source_id", "SRC-2"),))
    _check_refusal(env.enqueue(other), R.IDEMPOTENCY_CONFLICT, 409)
    small = Env(max_entries=1)
    assert small.enqueue().http_class == 202
    _check_refusal(small.enqueue(small.request(key="idem-key-0002")), R.RATE_LIMITED, 429)


POISON_FIELDS = [
    {"operation": POISON}, {"key": POISON}, {"params": ((POISON, POISON),)},
    {"params": (("source_id", POISON),)}, {"actor": POISON}, {"tenant": POISON},
]


@pytest.mark.parametrize("fields", POISON_FIELDS)
def test_poison_in_any_request_field_never_reaches_output(env, fields):
    try:
        request = env.request(**fields)
    except ValueError:
        return  # constructor refused it with a fixed code; nothing to echo
    d = env.enqueue(request)
    text = repr(d) + str(d) + " ".join(repr(getattr(d, f.name)) for f in dataclasses.fields(d))
    for fragment in ("Traceback", "secret://", "SELECT", "provider", "ForeignSourceName"):
        assert fragment not in text
    assert d.allowed is False


def test_poison_in_token_and_session_never_reaches_output(env):
    d = env.enqueue(token=POISON)
    _check_refusal(d, R.CSRF_REJECTED, 403)
    assert "Traceback" not in repr(d)
    bad_session = env.session(sid=POISON)
    d2 = env.enqueue(session=bad_session, token="FAKE-x")
    assert d2.allowed is False and POISON not in repr(d2) and "secret://" not in repr(d2)
    assert "secret://" not in repr(bad_session) and DIGEST not in repr(bad_session)


class RaisingDispatcher(FakeJobDispatcher):
    def dispatch(self, tenant_id, company_id, kind, request_digest, dispatch_key=None):
        raise RuntimeError(POISON)


class RaisingScopes(FakeScopeEpochs):
    def current_epoch(self, tenant_id, company_id):
        raise RuntimeError(POISON)


class PoisonClock:
    def now(self):
        raise RuntimeError(POISON)


class PoisonCorrelation:
    def next_id(self) -> str:
        return POISON


@pytest.mark.parametrize("which", ["dispatcher", "scopes", "clock", "correlation"])
def test_failing_collaborator_is_internal_refused_without_echo(which):
    env = Env()
    ctx = env.ctx
    swap = {
        "dispatcher": dataclasses.replace(ctx, dispatcher=RaisingDispatcher()),
        "scopes": dataclasses.replace(ctx, scopes=RaisingScopes({("T1", "C1"): 1})),
        "clock": dataclasses.replace(ctx, clock=PoisonClock()),
        "correlation": dataclasses.replace(ctx, correlation=PoisonCorrelation()),
    }[which]
    d = decide_enqueue(swap, env.request(), env.session(), env.token())
    assert d.allowed is False and d.ticket is None
    text = repr(d) + str(d.safe_error())
    assert POISON not in text and "Traceback" not in text and "secret://" not in text
    if which == "correlation":
        assert d.correlation_id == "CORR-UNASSIGNED"
    if which == "dispatcher":
        assert d.reason_code is R.DEPENDENCY_FAILED
        assert swap.idempotency.record_count() == 0  # a failed dispatch records nothing
        assert decide_enqueue(env.ctx, env.request(), env.session(), env.token()).http_class == 202


def test_collaborator_reprs_do_not_expose_contents(env):
    env.enqueue()
    env.enqueue(env.request(operation="post_document", key="idem-key-0002"))
    for obj in (env.idem, env.refusals, env.dispatcher, env.scopes, env.ctx.csrf, env.corr):
        text = repr(obj)
        assert "idem-key-0001" not in text and "post_document" not in text and "SRC-1" not in text


def test_job_ticket_and_session_repr_hide_secrets(env):
    d = env.enqueue()
    assert type(d.ticket) is JobTicket
    assert DIGEST not in repr(env.session())
    assert "idem-key-0001" not in repr(env.request())


def test_foreign_tenant_job_read_is_not_found_same_shape_as_missing(env):
    ticket = env.enqueue().ticket
    s2 = env.session("S2", "T2", "bob")
    foreign = read_job(env.ctx, ViewerScope("T2", "C1", 1), s2, ticket.job_id)
    missing = read_job(env.ctx, ViewerScope("T2", "C1", 1), s2, "JOB-999999")
    _check_refusal(foreign, R.NOT_FOUND, 404)
    _check_refusal(missing, R.NOT_FOUND, 404)
    assert dataclasses.replace(foreign, correlation_id="X") == dataclasses.replace(
        missing, correlation_id="X")
    other_company = read_job(env.ctx, ViewerScope("T1", "C2", 1), env.session(), ticket.job_id)
    _check_refusal(other_company, R.NOT_FOUND, 404)
    assert ticket.job_id not in repr(foreign) + repr(other_company)
    own = read_job(env.ctx, ViewerScope("T1", "C1", 1), env.session(), ticket.job_id)
    assert own.allowed and own.http_class == 200 and own.job.job_id == ticket.job_id


def test_read_result_only_after_completion_and_never_foreign(env):
    ticket = env.enqueue().ticket
    viewer, session = ViewerScope("T1", "C1", 1), env.session()
    queued = read_result(env.ctx, viewer, session, ticket.job_id)
    assert queued.allowed and queued.http_class == 202 and queued.job.state.value == "QUEUED"
    assert queued.job.result_digest is None
    env.dispatcher.complete(ticket.job_id, "b" * 64)
    done = read_result(env.ctx, viewer, session, ticket.job_id)
    assert done.allowed and done.job.result_digest == "b" * 64
    foreign = read_result(env.ctx, ViewerScope("T2", "C1", 1), env.session("S2", "T2", "bob"),
                          ticket.job_id)
    _check_refusal(foreign, R.NOT_FOUND, 404)


def test_read_rechecks_epoch_before_fetch_and_before_disclosure(env):
    ticket = env.enqueue().ticket
    viewer, session = ViewerScope("T1", "C1", 1), env.session()
    env.dispatcher.complete(ticket.job_id, "b" * 64)
    env.scopes.bump("T1", "C1")
    before = len(env.dispatcher.get_log)
    _check_refusal(read_job(env.ctx, viewer, session, ticket.job_id), R.SCOPE_EPOCH_STALE, 403)
    assert len(env.dispatcher.get_log) == before  # refused before any fetch
    for fn in (read_job, read_result):
        epoch = env.scopes.current_epoch("T1", "C1")
        env.dispatcher.on_get = lambda: env.scopes.bump("T1", "C1")  # revoke lands during the fetch
        d = fn(env.ctx, ViewerScope("T1", "C1", epoch), session, ticket.job_id)
        env.dispatcher.on_get = None
        _check_refusal(d, R.SCOPE_EPOCH_STALE, 403)


def test_read_requires_valid_session_and_matching_tenant(env):
    ticket = env.enqueue().ticket
    viewer = ViewerScope("T1", "C1", 1)
    _check_refusal(read_job(env.ctx, viewer, None, ticket.job_id), R.SESSION_INVALID, 401)
    other = env.session("S2", "T2", "bob")
    _check_refusal(read_job(env.ctx, viewer, other, ticket.job_id), R.SESSION_INVALID, 401)
    expired = env.session(hours=-1)
    _check_refusal(read_job(env.ctx, viewer, expired, ticket.job_id), R.SESSION_INVALID, 401)
    _check_refusal(read_job(env.ctx, viewer, env.session(), POISON), R.PARAMETER_SCHEMA_INVALID, 400)
    _check_refusal(read_job(env.ctx, viewer, env.session(), None), R.PARAMETER_SCHEMA_INVALID, 400)


def test_read_needs_no_csrf_token(env):
    ticket = env.enqueue().ticket
    d = read_job(env.ctx, ViewerScope("T1", "C1", 1), env.session(), ticket.job_id)
    assert d.allowed and d.job.state == "QUEUED"


# ================================ TC122: CSRF ===============================================

def _assert_no_side_effects(env: Env) -> None:
    assert env.dispatcher.calls == ()
    assert env.idem.record_count() == 0
    assert env.idem.effects == ()


def test_csrf_rejections_dispatch_nothing_and_record_nothing(env):
    s1 = env.session()
    s_other = env.session("S2", "T1", "alice")
    s_tenant2 = env.session("S9", "T2", "alice")
    rotated = SessionRecord("S1", "T1", "alice", START + timedelta(hours=1), "c" * 64)
    tokens = {
        "missing": None, "empty": "", "wrong": "FAKE-0000", "not-str": 12345,
        "other-session": fake_csrf_token(s_other), "cross-tenant": fake_csrf_token(s_tenant2),
        "rotated-secret": fake_csrf_token(rotated), "poison": POISON,
        "huge": "FAKE-" + "A" * 100_000,
    }
    for tok in tokens.values():
        d = decide_enqueue(env.ctx, env.request(), s1, tok)
        _check_refusal(d, R.CSRF_REJECTED, 403)
    _assert_no_side_effects(env)


def test_expired_session_is_401_and_does_not_touch_state(env):
    s = env.session(hours=-1)
    _check_refusal(decide_enqueue(env.ctx, env.request(), s, fake_csrf_token(s)),
                   R.SESSION_INVALID, 401)
    _assert_no_side_effects(env)


def test_session_expires_exactly_at_the_boundary(env):
    s = SessionRecord("S1", "T1", "alice", START + timedelta(seconds=5), DIGEST)
    assert decide_enqueue(env.ctx, env.request(), s, fake_csrf_token(s)).http_class == 202
    env.clock.advance(10)
    d = decide_enqueue(env.ctx, env.request(key="idem-key-0002"), s, fake_csrf_token(s))
    _check_refusal(d, R.SESSION_INVALID, 401)


def test_session_must_match_request_tenant_and_actor(env):
    s = env.session()
    _check_refusal(decide_enqueue(env.ctx, env.request(tenant="T2"), s, fake_csrf_token(s)),
                   R.SESSION_INVALID, 401)
    _check_refusal(decide_enqueue(env.ctx, env.request(actor="mallory"), s, fake_csrf_token(s)),
                   R.SESSION_INVALID, 401)
    _assert_no_side_effects(env)


def test_correct_token_new_key_enqueues_once_202(env):
    d = env.enqueue()
    assert d.allowed and d.http_class == 202 and d.reason_code is None
    assert d.next_action is NextAction.NO_ACTION and d.safe_error() is None
    assert type(d.ticket) is JobTicket and d.ticket.job_id == "JOB-000001"
    assert len(env.dispatcher.calls) == 1 and env.idem.record_count() == 1
    assert len(env.idem.effects) == 1
    assert d.authority == "EVALUATION_ONLY"


def test_same_key_same_digest_replays_with_zero_extra_dispatch(env):
    first = env.enqueue()
    again = env.enqueue(env.request(params=(("source_id", "SRC-1"),)))
    assert again.allowed and again.http_class == 200 and again.reason_code is R.REPLAYED
    assert again.ticket == first.ticket
    assert len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1
    assert again.correlation_id != first.correlation_id


def test_param_order_does_not_change_the_digest(env):
    req = env.request(kind=JobKind.RECONCILIATION,
                      params=(("comparison_key", "CK-1"), ("snapshot_id", "SN-1")))
    swapped = env.request(kind=JobKind.RECONCILIATION,
                          params=(("snapshot_id", "SN-1"), ("comparison_key", "CK-1")))
    first = env.enqueue(req)
    assert first.http_class == 202
    assert env.enqueue(swapped).reason_code is R.REPLAYED
    assert len(env.dispatcher.calls) == 1


def test_same_key_different_digest_is_409_and_stored_outcome_unchanged(env):
    first = env.enqueue()
    stored = env.idem.peek("T1", "alice", Endpoint.ENQUEUE_JOB, "idem-key-0001")
    for changed in (env.request(params=(("source_id", "SRC-2"),)),
                    env.request(kind=JobKind.REPORT, params=(("report_id", "R-1"),)),
                    env.request(company="C2")):
        d = env.enqueue(changed)
        _check_refusal(d, R.IDEMPOTENCY_CONFLICT, 409)
    assert env.idem.peek("T1", "alice", Endpoint.ENQUEUE_JOB, "idem-key-0001") == stored
    assert stored.ticket == first.ticket
    assert len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1
    assert env.enqueue().reason_code is R.REPLAYED  # the original still replays


@pytest.mark.parametrize("key", [None, "", "short key", "k" * 129, "ключ-идемпотентности",
                                 "key\x00nul", b"idem-key-0001", 12345, ["x"], "a b"])
def test_missing_oversized_or_illformed_key_is_refused(env, key):
    d = env.enqueue(env.request(key=key))
    _check_refusal(d, R.IDEMPOTENCY_KEY_REQUIRED, 400)
    _assert_no_side_effects(env)


def test_key_boundary_lengths(env):
    assert env.enqueue(env.request(key="k" * 128)).http_class == 202
    _check_refusal(env.enqueue(env.request(key="k" * 129)), R.IDEMPOTENCY_KEY_REQUIRED, 400)


def test_same_key_is_independent_per_tenant_and_actor(env):
    assert env.enqueue().http_class == 202
    s2 = env.session("S2", "T2", "alice")
    d2 = decide_enqueue(env.ctx, env.request(tenant="T2"), s2, fake_csrf_token(s2))
    assert d2.http_class == 202 and d2.ticket.job_id == "JOB-000002"
    s3 = env.session("S3", "T1", "bob")
    d3 = decide_enqueue(env.ctx, env.request(actor="bob"), s3, fake_csrf_token(s3))
    assert d3.http_class == 202 and d3.ticket.job_id == "JOB-000003"
    assert len(env.dispatcher.calls) == 3


def test_same_key_is_independent_per_endpoint(env):
    assert env.enqueue().http_class == 202
    gate = AllowGate()
    rerun = RerunRequest(ViewerScope("T1", "C1", 1), "alice", "CK-1", "run-1", "SN-2", "idem-key-0001")
    d = decide_rerun(env.ctx, rerun, env.session(), env.token(), gate)
    assert d.http_class == 202 and d.reason_code is None


def test_retention_eviction_never_maps_a_key_to_two_digests_inside_the_window():
    env = Env(max_entries=2, retention=60)
    a, b = env.request(key="idem-key-aaaa"), env.request(key="idem-key-bbbb")
    assert env.enqueue(a).http_class == 202 and env.enqueue(b).http_class == 202
    full = env.enqueue(env.request(key="idem-key-cccc"))
    _check_refusal(full, R.RATE_LIMITED, 429)  # full of live keys: refuse, never evict early
    assert len(env.dispatcher.calls) == 2
    # a full store still replays and still conflicts: the live window is never given up
    assert env.enqueue(a).reason_code is R.REPLAYED
    _check_refusal(env.enqueue(env.request(key="idem-key-aaaa", params=(("source_id", "X"),))),
                   R.IDEMPOTENCY_CONFLICT, 409)
    env.clock.advance(61)
    assert env.enqueue(env.request(key="idem-key-cccc")).http_class == 202
    assert env.idem.record_count() <= 2
    # outside the window the old key is genuinely new and may carry a different digest
    again = env.enqueue(env.request(key="idem-key-aaaa", params=(("source_id", "X"),)))
    assert again.http_class == 202 and len(env.dispatcher.calls) == 4


def test_key_to_digest_mapping_is_stable_across_a_scripted_timeline():
    env = Env(max_entries=3, retention=100)
    seen: dict[str, tuple[str, datetime]] = {}
    script = [("k1", "A", 0), ("k2", "B", 10), ("k1", "C", 10), ("k3", "D", 10), ("k4", "E", 10),
              ("k2", "F", 50), ("k1", "A", 40), ("k5", "G", 5), ("k1", "H", 60), ("k3", "D", 1)]
    for key, src, dt in script:
        env.clock.advance(dt)
        now = env.clock.now()
        req = env.request(key=f"idem-key-{key}", params=(("source_id", src),))
        d = env.enqueue(req)
        digest = jobs_api.request_digest(req, Endpoint.ENQUEUE_JOB)
        prior = seen.get(key)
        if prior and (now - prior[1]).total_seconds() < 100:
            assert (d.http_class == 200) == (prior[0] == digest)
            if prior[0] != digest:
                assert d.reason_code is R.IDEMPOTENCY_CONFLICT
        if d.http_class == 202:
            seen[key] = (digest, now)
    assert env.idem.record_count() <= 3


def test_concurrent_identical_requests_dispatch_exactly_once(env):
    n = 24
    barrier = threading.Barrier(n)
    results: list[ApiDecision] = []
    lock = threading.Lock()
    session, token = env.session(), env.token()

    def work() -> None:
        barrier.wait()
        d = decide_enqueue(env.ctx, env.request(), session, token)
        with lock:
            results.append(d)

    threads = [threading.Thread(target=work) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(env.dispatcher.calls) == 1
    assert sorted(d.http_class for d in results) == [200] * (n - 1) + [202]
    assert len({d.ticket for d in results}) == 1
    assert len({d.correlation_id for d in results}) == n
    assert len(env.idem.effects) == 1


def test_concurrent_same_key_different_digests_one_winner(env):
    n = 16
    barrier = threading.Barrier(n)
    results: list[ApiDecision] = []
    lock = threading.Lock()
    session, token = env.session(), env.token()
    for i in range(n):
        env.ownership.add("T1", "C1", "source_id", f"SRC-{i}")

    def work(i: int) -> None:
        barrier.wait()
        d = decide_enqueue(env.ctx, env.request(params=(("source_id", f"SRC-{i}"),)), session, token)
        with lock:
            results.append(d)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(env.dispatcher.calls) == 1
    assert sorted(d.http_class for d in results) == [202] + [409] * (n - 1)


def test_stale_epoch_is_refused_before_idempotency_is_touched(env):
    env.scopes.bump("T1", "C1")
    d = env.enqueue()
    _check_refusal(d, R.SCOPE_EPOCH_STALE, 403)
    _assert_no_side_effects(env)
    d2 = env.enqueue(env.request(epoch=2))
    assert d2.http_class == 202  # the same key was never consumed by the refused request


def test_unknown_scope_is_refused_as_not_in_scope(env):
    d = env.enqueue(env.request(company="C9"))
    _check_refusal(d, R.NOT_IN_SCOPE, 403)
    _assert_no_side_effects(env)


def test_fixed_check_order_session_csrf_scope_boundary_idempotency_dispatch(env):
    bad_session, good = None, env.session()
    bad_req = env.request(key=None, epoch=99, operation="post_document")
    _check_refusal(decide_enqueue(env.ctx, bad_req, bad_session, "FAKE-bad"), R.SESSION_INVALID, 401)
    _check_refusal(decide_enqueue(env.ctx, bad_req, good, "FAKE-bad"), R.CSRF_REJECTED, 403)
    _check_refusal(decide_enqueue(env.ctx, bad_req, good, env.token(good)), R.SCOPE_EPOCH_STALE, 403)
    no_epoch = env.request(key=None, operation="post_document")
    _check_refusal(decide_enqueue(env.ctx, no_epoch, good, env.token(good)), R.OPERATION_DENIED, 403)
    no_key = env.request(key=None)
    _check_refusal(decide_enqueue(env.ctx, no_key, good, env.token(good)),
                   R.IDEMPOTENCY_KEY_REQUIRED, 400)
    ok = decide_enqueue(env.ctx, env.request(), good, env.token(good))
    assert ok.http_class == 202 and len(env.dispatcher.calls) == 1


def test_capture_job_needs_an_explicit_permit_fact_and_never_consumes_the_key(env):
    capture = env.request(kind=JobKind.CAPTURE)
    _check_refusal(env.enqueue(capture), R.OPERATION_DENIED, 403)
    _assert_no_side_effects(env)
    env.capture.allow("T1", "C1", "alice")
    assert env.enqueue(capture).http_class == 202


@pytest.mark.parametrize("kind,params", [
    (JobKind.RESCAN, ()), (JobKind.RESCAN, (("source_id", "a"), ("source_id", "b"))),
    (JobKind.RESCAN, (("source_id", ""),)), (JobKind.REPORT, (("source_id", "SRC-1"),)),
    (JobKind.RERUN, (("source_id", "SRC-1"),)), (JobKind.RESCAN, (("source_id", "a\u200bb"),)),
    (JobKind.RESCAN, (("source_id", 5),)), (JobKind.RESCAN, (("command", "post"),)),
])
def test_parameter_schema_is_enforced(env, kind, params):
    _check_refusal(env.enqueue(env.request(kind=kind, params=params)),
                   R.PARAMETER_SCHEMA_INVALID, 400)
    _assert_no_side_effects(env)


# ================================ rerun =====================================================

class AllowGate:
    def __init__(self, verdict: ReasonCode | None = None) -> None:
        self.verdict = verdict
        self.calls = 0

    def check(self, request) -> ReasonCode | None:
        self.calls += 1
        return self.verdict

    def commit(self, request):
        self.commits = getattr(self, "commits", 0) + 1
        return RerunCommit(f"run-new-{self.commits}", RunState.CREATED)


def _rerun(env: Env, key="idem-key-9001", snapshot="SN-2", prev="run-1") -> RerunRequest:
    return RerunRequest(ViewerScope("T1", "C1", 1), "alice", "CK-1", prev, snapshot, key)


def test_rerun_requires_csrf_and_idempotency_and_fresh_scope(env):
    gate, s = AllowGate(), env.session()
    _check_refusal(decide_rerun(env.ctx, _rerun(env), s, "FAKE-bad", gate), R.CSRF_REJECTED, 403)
    env.scopes.bump("T1", "C1")
    _check_refusal(decide_rerun(env.ctx, _rerun(env), s, env.token(s), gate),
                   R.SCOPE_EPOCH_STALE, 403)
    assert gate.calls == 0 and env.dispatcher.calls == () and env.idem.record_count() == 0
    env.scopes.bump("T1", "C1")
    fresh = RerunRequest(ViewerScope("T1", "C1", 3), "alice", "CK-1", "run-1", "SN-2", None)
    _check_refusal(decide_rerun(env.ctx, fresh, s, env.token(s), gate),
                   R.IDEMPOTENCY_KEY_REQUIRED, 400)
    assert gate.calls == 0


def test_rerun_state_fence_codes_refuse_without_dispatch_or_record(env):
    s = env.session()
    for verdict in (R.NO_NEW_EVIDENCE, R.RERUN_TARGET_STALE, R.NOT_IN_SCOPE, R.SOURCE_PAUSED,
                    R.OPERATION_DENIED):
        gate = AllowGate(verdict)
        d = decide_rerun(env.ctx, _rerun(env), s, env.token(s), gate)
        assert d.allowed is False and d.reason_code is verdict and d.ticket is None
        assert CORR.fullmatch(d.correlation_id) and d.http_class == GATE_HTTP[verdict]
    assert env.dispatcher.calls == () and env.idem.record_count() == 0


def test_rerun_gate_returning_garbage_is_internal_refused(env):
    s = env.session()
    for verdict in (POISON, 5, object(), ReasonCode.REPLAYED):
        d = decide_rerun(env.ctx, _rerun(env), s, env.token(s), AllowGate(verdict))
        assert d.reason_code is R.DEPENDENCY_FAILED and d.ticket is None
        assert POISON not in repr(d)
    assert env.dispatcher.calls == ()


def test_rerun_accepts_once_and_replays_after_the_head_moved(env):
    s, gate = env.session(), AllowGate()
    first = decide_rerun(env.ctx, _rerun(env), s, env.token(s), gate)
    assert first.http_class == 202 and first.ticket.kind is JobKind.RERUN
    gate.verdict = R.RERUN_TARGET_STALE  # the head moved because of the first rerun
    again = decide_rerun(env.ctx, _rerun(env), s, env.token(s), gate)
    assert again.reason_code is R.REPLAYED and again.ticket == first.ticket
    assert len(env.dispatcher.calls) == 1 and len(env.idem.effects) == 1
    other_key = decide_rerun(env.ctx, _rerun(env, key="idem-key-9002"), s, env.token(s), gate)
    _check_refusal(other_key, R.RERUN_TARGET_STALE, 409)
    changed = decide_rerun(env.ctx, _rerun(env, snapshot="SN-3"), s, env.token(s), gate)
    _check_refusal(changed, R.IDEMPOTENCY_CONFLICT, 409)


def test_rerun_never_takes_numbers_or_verdicts():
    names = {f.name for f in dataclasses.fields(RerunRequest)}
    assert names == {"scope", "actor_id", "comparison_key", "previous_run_id", "new_snapshot_id",
                     "idempotency_key"}
    with pytest.raises(TypeError):
        RerunRequest(ViewerScope("T1", "C1", 1), "alice", "CK-1", "run-1", "SN-2", "k",
                     state="PASS")  # type: ignore[call-arg]


def test_concurrent_reruns_of_one_head_dispatch_once(env):
    n = 12
    barrier = threading.Barrier(n)
    out: list[ApiDecision] = []
    lock = threading.Lock()
    s, gate = env.session(), AllowGate()

    def work() -> None:
        barrier.wait()
        d = decide_rerun(env.ctx, _rerun(env), s, env.token(s), gate)
        with lock:
            out.append(d)

    ts = [threading.Thread(target=work) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(env.dispatcher.calls) == 1
    assert sorted(d.http_class for d in out) == [200] * (n - 1) + [202]


def test_request_types_validate_in_constructor_with_fixed_codes():
    with pytest.raises(ValueError, match="^JOB_REQUEST_INVALID$"):
        JobRequest("not-a-scope", "alice", JobKind.RESCAN, "read_document", (), "k")
    with pytest.raises(ValueError, match="^SESSION_INVALID$"):
        SessionRecord("S1", "T1", "alice", datetime(2026, 1, 1), DIGEST)  # noqa: DTZ001 - naive on purpose
    with pytest.raises(ValueError, match="^RERUN_REQUEST_INVALID$"):
        RerunRequest(ViewerScope("T1", "C1", 1), "alice", "", "run-1", "SN-2", "k")
    with pytest.raises(ValueError, match="^IDEMPOTENCY_STORE_INVALID$"):
        IdempotencyStore(0, 10)
    with pytest.raises(ValueError, match="^IDEMPOTENCY_STORE_INVALID$"):
        IdempotencyStore(10, True)  # type: ignore[arg-type]
