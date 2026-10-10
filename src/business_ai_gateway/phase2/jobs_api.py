"""Phase 2 sprint S8 (R2-US-041, TC121-TC123): safe job/result API DECISIONS. Not a server.

Offline, unwired, in-memory, synchronous reference logic: pure decision functions over typed requests.
There is no web framework, no cookie parsing, no HTTP library, no DB and no 1C client here.

Public decisions (each maps to one row of the ``ENDPOINTS`` annotation table):

* ``decide_enqueue`` / ``decide_rerun`` - mutations. Fixed check order, tested:
  structure -> session -> CSRF -> entitlement -> scope epoch -> operation boundary -> parameter schema
  -> capture policy -> ownership of every id -> idempotency key -> idempotency store -> dispatch.
  A refusal at any step never touches a later step, so a CSRF/epoch/boundary/ownership refusal creates
  no idempotency record and makes no dispatcher call. The entitlement check runs BEFORE the epoch check
  and refuses non-members and unknown companies with the same ``NOT_IN_SCOPE`` shape, so a non-member
  cannot probe epochs. ``decide_rerun`` has no caller operation name; its two-step state fence
  (``RerunGate.check`` pure, then ``RerunGate.commit``) runs INSIDE the idempotency step.
* ``read_job`` / ``read_result`` - reads. No CSRF. The scope epoch is re-checked before the fetch and
  again before disclosure; a foreign or missing job is the same ``NOT_FOUND`` shape. ``read_result`` of
  an own job that is QUEUED/RUNNING/FAILED answers with its fixed state and no digest.

Idempotency (``IdempotencyStore``): a slot is RESERVED (pending) under a short global lock and the
action runs OUTSIDE it, so a slow dispatch on key K1 never blocks key K2. Outcome states per slot:
DONE (ticket stored; replays) and EFFECT_DONE (the run was committed but the dispatch failed; a retry
with the same key completes the dispatch for the SAME run, never creating a second run and never
answering ``RERUN_TARGET_STALE``).

Every outcome is an ``ApiDecision``: ``(allowed, http_class, reason_code, next_action, correlation_id,
ticket, job)`` built only from fixed enums, fixed integers and ids produced by injected sources.
Caller text (operation names, keys, tokens, parameters, exception text) is never echoed. Hostile
input and failing collaborators give a fixed refusal and never raise; every converted component
exception is reported to an injected ``EventSink`` as ``(kind, component, exception CLASS NAME,
correlation id)`` - never the message.

Channel is not an input: no function takes a channel/transport label. The operation name is fixed by
``OPERATION_FOR[kind]``; a caller-supplied name must canonicalise to exactly that name. It is
classified by ``side_effect_boundary.evaluate`` before anything else. A refused (tenant, company,
operation) pair is written to an append-only ``RefusalLog`` and stays refused for every later spelling.

KNOWN GAPS: sessions, the CSRF derivation, the scope-epoch source, entitlement, ownership, capture
policy, the rerun gate and the actor role model are injected fakes; ``fake_csrf_token`` is a TEST-ONLY
unkeyed hash (production wires ``keyed_csrf_derive``); ``JobQueuePort`` / the real ``jobs`` table are
not used; no cookie flags, CORS or real HTTP. Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

import hashlib
import heapq
import hmac
import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

from ._identity import exact_text, stable_key
from .comparison_snapshot import canonical_digest
from .safe_errors import CorrelationSource
from .side_effect_boundary import (
    BoundaryCode,
    CapturePlan,
    Environment,
    OperationRegistry,
    canonical_operation,
    evaluate,
)
from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    NEXT_ACTION_FOR,
    NextAction,
    ReasonCode,
    SafeError,
    ViewerScope,
    correlation_ok,
    is_valid_scope,
)

if TYPE_CHECKING:
    from .workbench_types import EntitlementPort, OwnershipPort

__all__ = [
    "DECISION_ENDPOINTS", "ENDPOINTS", "HTTP_CLASSES", "OPERATION_FOR", "ApiContext", "ApiDecision",
    "ApiEvent", "CapturePolicyPort", "ComponentName", "CsrfGuard", "Endpoint", "EndpointAnnotation",
    "EventKind", "EventSink", "FakeCapturePolicy", "FakeEventSink", "FakeJobDispatcher",
    "FakeScopeEpochs", "IdempotencyStore", "JobDispatcher", "JobKind", "JobRecord", "JobRequest",
    "JobState", "JobSummary", "JobTicket", "NextAction", "RefusalLog", "RerunCommit", "RerunGate",
    "RerunRequest", "RunState", "ScopeEpochSource", "SessionRecord", "StoredOutcome", "decide_enqueue",
    "decide_rerun", "fake_csrf_token", "keyed_csrf_derive", "read_job", "read_result",
    "request_digest",
]

_R = ReasonCode
HTTP_CLASSES: Final = frozenset({200, 202, 400, 401, 403, 404, 409, 429})
_REFUSAL_HTTP: Final = frozenset({400, 401, 403, 404, 409, 429})
_KEY: Final = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_CLASS_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_MAX_TOKEN: Final = 512
_MAX_ENTRIES: Final = 1_000_000
_MAX_RETENTION: Final = 30 * 86400
_EFFECT_RING: Final = 1024


class Endpoint(StrEnum):
    ENQUEUE_JOB = "ENQUEUE_JOB"
    RERUN = "RERUN"
    PAUSE_SOURCE = "PAUSE_SOURCE"
    REVOKE_ATTESTATION = "REVOKE_ATTESTATION"
    READ_JOB = "READ_JOB"
    READ_RESULT = "READ_RESULT"


class JobKind(StrEnum):
    RESCAN = "RESCAN"
    REPORT = "REPORT"
    RECONCILIATION = "RECONCILIATION"
    CAPTURE = "CAPTURE"
    RERUN = "RERUN"


class JobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RunState(StrEnum):
    """Fixed state of the run a rerun created (never caller text)."""

    CREATED = "CREATED"
    COMPLETED = "COMPLETED"


class EventKind(StrEnum):
    COMPONENT_EXCEPTION = "COMPONENT_EXCEPTION"
    COMPONENT_OUTPUT_INVALID = "COMPONENT_OUTPUT_INVALID"
    QUOTA_OVERFLOW = "QUOTA_OVERFLOW"
    IN_FLIGHT_TIMEOUT = "IN_FLIGHT_TIMEOUT"
    DISPATCH_RETRY_PENDING = "DISPATCH_RETRY_PENDING"
    ORPHAN_JOB_CANCELLED = "ORPHAN_JOB_CANCELLED"
    ORPHAN_JOB_UNREACHABLE = "ORPHAN_JOB_UNREACHABLE"
    UNEXPECTED_EXCEPTION = "UNEXPECTED_EXCEPTION"


class ComponentName(StrEnum):
    CONTEXT = "CONTEXT"
    CLOCK = "CLOCK"
    CORRELATION = "CORRELATION"
    SCOPES = "SCOPES"
    ENTITLEMENTS = "ENTITLEMENTS"
    OWNERSHIP = "OWNERSHIP"
    CAPTURE_POLICY = "CAPTURE_POLICY"
    GATE = "GATE"
    DISPATCHER = "DISPATCHER"
    IDEMPOTENCY = "IDEMPOTENCY"
    DIGEST = "DIGEST"
    UNEXPECTED = "UNEXPECTED"


@dataclass(frozen=True, slots=True)
class EndpointAnnotation:
    """Fixed per-endpoint annotation (MCP-style hints). A control mutation is never read-only."""

    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool


_MUTATION = EndpointAnnotation(read_only=False, destructive=False, idempotent=True, open_world=False)
_READ = EndpointAnnotation(read_only=True, destructive=False, idempotent=True, open_world=False)
ENDPOINTS: Final[Mapping[Endpoint, EndpointAnnotation]] = MappingProxyType({
    Endpoint.ENQUEUE_JOB: _MUTATION, Endpoint.RERUN: _MUTATION,
    Endpoint.PAUSE_SOURCE: _MUTATION, Endpoint.REVOKE_ATTESTATION: _MUTATION,
    Endpoint.READ_JOB: _READ, Endpoint.READ_RESULT: _READ,
})
DECISION_ENDPOINTS: Final[Mapping[str, Endpoint]] = MappingProxyType({
    "decide_enqueue": Endpoint.ENQUEUE_JOB, "decide_rerun": Endpoint.RERUN,
    "read_job": Endpoint.READ_JOB, "read_result": Endpoint.READ_RESULT,
})

_PARAM_SCHEMA: Final[Mapping[JobKind, tuple[str, ...]]] = MappingProxyType({
    JobKind.RESCAN: ("source_id",), JobKind.REPORT: ("report_id",),
    JobKind.RECONCILIATION: ("comparison_key", "snapshot_id"), JobKind.CAPTURE: ("source_id",),
})
# The ONLY operation name a job kind may run under (design: the caller never chooses it).
OPERATION_FOR: Final[Mapping[JobKind, str]] = MappingProxyType({
    JobKind.RESCAN: "read_document", JobKind.REPORT: "export_report",
    JobKind.RECONCILIATION: "read_document", JobKind.CAPTURE: "list_catalogs",
    JobKind.RERUN: "read_document",
})
_OWNERSHIP_KIND: Final[Mapping[str, str]] = MappingProxyType({
    "source_id": "source_id", "report_id": "report_id", "comparison_key": "comparison_key",
    "snapshot_id": "snapshot_id",
})
_HTTP_FOR: Final[Mapping[ReasonCode, int]] = MappingProxyType({
    _R.SESSION_INVALID: 401, _R.CSRF_REJECTED: 403, _R.SCOPE_EPOCH_STALE: 403,
    _R.OPERATION_DENIED: 403, _R.OPERATION_UNCLASSIFIED: 403, _R.NOT_IN_SCOPE: 403,
    _R.PARAMETER_SCHEMA_INVALID: 400, _R.IDEMPOTENCY_KEY_REQUIRED: 400, _R.INTERNAL_REFUSED: 400,
    _R.DEPENDENCY_FAILED: 429,
    _R.NOT_FOUND: 404, _R.RERUN_TARGET_UNKNOWN: 404, _R.IDEMPOTENCY_CONFLICT: 409,
    _R.RERUN_TARGET_STALE: 409, _R.NO_NEW_EVIDENCE: 409, _R.SOURCE_PAUSED: 409, _R.RATE_LIMITED: 429,
})
_GATE_VERDICTS: Final = frozenset({
    _R.NO_NEW_EVIDENCE, _R.RERUN_TARGET_STALE, _R.RERUN_TARGET_UNKNOWN, _R.NOT_IN_SCOPE,
    _R.SOURCE_PAUSED, _R.OPERATION_DENIED, _R.NOT_FOUND, _R.RATE_LIMITED, _R.SCOPE_EPOCH_STALE,
    _R.DEPENDENCY_FAILED, _R.INTERNAL_REFUSED,  # also what check_rerun / commit_rerun may refuse with
})
_BOUNDARY_DENIED: Final[Mapping[BoundaryCode, ReasonCode]] = MappingProxyType({
    BoundaryCode.WRITE_OPERATION: _R.OPERATION_DENIED, BoundaryCode.POST_OPERATION: _R.OPERATION_DENIED,
    BoundaryCode.DELETE_OPERATION: _R.OPERATION_DENIED, BoundaryCode.RESET_OPERATION: _R.OPERATION_DENIED,
    BoundaryCode.ADMIN_OPERATION: _R.OPERATION_DENIED, BoundaryCode.RIGHTS_DISQUALIFY: _R.OPERATION_DENIED,
    BoundaryCode.PROBE_DENIED: _R.OPERATION_DENIED, BoundaryCode.PROBE_DENIED_IN_PROD: _R.OPERATION_DENIED,
})


def _id_ok(value: object) -> bool:
    return type(value) is str and value != "" and exact_text(value) == value


def _aware(value: object) -> bool:
    return (type(value) is datetime and value.tzinfo is not None
            and value.tzinfo.utcoffset(value) is not None)


def _key_ok(key: object) -> bool:
    return type(key) is str and len(key) <= 128 and _KEY.fullmatch(key) is not None


def _corr_ok(value: object) -> bool:
    """A usable correlation id: exact ``str`` accepted by ``SafeError`` (the unassigned default counts)."""
    return correlation_ok(value)


# ------------------------------------------------------------------ request / session types

@dataclass(frozen=True, slots=True)
class SessionRecord:
    """An already-authenticated session as the decision layer sees it (no cookie handling here).

    The record is bound to ``(tenant_id, actor_id)``: decisions compare both with the request, and the
    CSRF derivation covers the actor, so a token never moves between actors or tenants."""

    session_id: str = field(repr=False)
    tenant_id: str
    actor_id: str
    expires_at: datetime
    csrf_secret_digest: str = field(repr=False)

    def __post_init__(self) -> None:
        if not _session_ok(self):
            raise ValueError("SESSION_INVALID")


def _session_ok(value: object) -> bool:
    if type(value) is not SessionRecord:
        return False
    try:
        return (_id_ok(value.session_id) and _id_ok(value.tenant_id) and _id_ok(value.actor_id)
                and _aware(value.expires_at) and type(value.csrf_secret_digest) is str
                and _HEX64.fullmatch(value.csrf_secret_digest) is not None)
    except AttributeError:
        return False


@dataclass(frozen=True, slots=True)
class JobRequest:
    """Typed enqueue request: typed ids, a registered operation name and schema-checked parameters."""

    scope: ViewerScope
    actor_id: str
    kind: JobKind
    operation: str = field(repr=False)
    params: tuple[tuple[str, str], ...] = field(repr=False)
    idempotency_key: object = field(repr=False, default=None)

    def __post_init__(self) -> None:
        if not _request_ok(self):
            raise ValueError("JOB_REQUEST_INVALID")


def _request_ok(value: object) -> bool:
    if type(value) is not JobRequest:
        return False
    try:
        return (is_valid_scope(value.scope) and _id_ok(value.actor_id) and type(value.kind) is JobKind
                and type(value.operation) is str and type(value.params) is tuple)
    except AttributeError:
        return False


@dataclass(frozen=True, slots=True)
class RerunRequest:
    """Typed rerun request: only ids. No numbers, verdicts or states can be supplied."""

    scope: ViewerScope
    actor_id: str
    comparison_key: str
    previous_run_id: str
    new_snapshot_id: str
    idempotency_key: object = field(repr=False, default=None)

    def __post_init__(self) -> None:
        if not _rerun_ok(self):
            raise ValueError("RERUN_REQUEST_INVALID")


def _rerun_ok(value: object) -> bool:
    if type(value) is not RerunRequest:
        return False
    try:
        return (is_valid_scope(value.scope) and _id_ok(value.actor_id)
                and _id_ok(value.comparison_key) and _id_ok(value.previous_run_id)
                and _id_ok(value.new_snapshot_id))
    except AttributeError:
        return False


def _params(kind: JobKind, params: object) -> tuple[tuple[str, str], ...] | None:
    names = _PARAM_SCHEMA.get(kind)
    if names is None or type(params) is not tuple or len(params) != len(names):
        return None
    out: list[tuple[str, str]] = []
    for item in params:
        if type(item) is not tuple or len(item) != 2:
            return None
        name, value = item
        if (type(name) is not str or name not in names or type(value) is not str
                or len(value) > 128 or _KEY.fullmatch(value) is None):
            return None
        out.append((name, value))
    out.sort()
    if [n for n, _ in out] != sorted(names):
        return None  # duplicate or missing field
    return tuple(out)


def request_digest(request: object, endpoint: Endpoint) -> str:
    """Canonical sha256 over the typed parameters of a valid request; '' for anything unusable."""
    try:
        if type(request) is JobRequest and _request_ok(request):
            params = _params(request.kind, request.params)
            if params is None:
                return ""
            body = {"endpoint": endpoint.value, "company": request.scope.company_id,
                    "kind": request.kind.value, "operation": canonical_operation(request.operation),
                    "params": [list(p) for p in params]}
        elif type(request) is RerunRequest and _rerun_ok(request):
            body = {"endpoint": endpoint.value, "company": request.scope.company_id,
                    "comparison_key": request.comparison_key,
                    "previous_run_id": request.previous_run_id,
                    "new_snapshot_id": request.new_snapshot_id}
        else:
            return ""
        return canonical_digest(body)
    except Exception:  # noqa: BLE001 - public helper never raises
        return ""


# ------------------------------------------------------------------ outcome types

@dataclass(frozen=True, slots=True)
class RerunCommit:
    """What ``RerunGate.commit`` returns: the id and fixed state of the run it created."""

    run_id: str
    state: RunState

    def __post_init__(self) -> None:
        if not _key_ok(self.run_id) or type(self.state) is not RunState:
            raise ValueError("RERUN_COMMIT_INVALID")


@dataclass(frozen=True, slots=True)
class JobTicket:
    """Proof an enqueue/rerun was accepted. A rerun ticket also carries the new run id and state."""

    job_id: str
    tenant_id: str
    company_id: str
    kind: JobKind
    request_digest: str
    authority: str = AUTHORITY
    run_id: str | None = None
    run_state: RunState | None = None

    def __post_init__(self) -> None:
        ok = (_key_ok(self.job_id) and _id_ok(self.tenant_id) and _id_ok(self.company_id)
              and type(self.kind) is JobKind and type(self.request_digest) is str
              and _HEX64.fullmatch(self.request_digest) is not None and self.authority == AUTHORITY
              and ((self.run_id is None and self.run_state is None)
                   or (_key_ok(self.run_id) and type(self.run_state) is RunState)))
        if not ok:
            raise ValueError("JOB_TICKET_INVALID")


@dataclass(frozen=True, slots=True)
class JobSummary:
    job_id: str
    kind: JobKind
    state: JobState
    result_digest: str | None = None


@dataclass(frozen=True, slots=True)
class JobRecord:
    """What a dispatcher stores per job. Tenant/company stay inside; they are never disclosed."""

    job_id: str
    tenant_id: str
    company_id: str
    kind: JobKind
    state: JobState
    result_digest: str | None = None


def _record_ok(record: object) -> bool:
    """A dispatcher answer is validated before anything of it goes outward."""
    return (type(record) is JobRecord and _key_ok(record.job_id) and _id_ok(record.tenant_id)
            and _id_ok(record.company_id) and type(record.kind) is JobKind
            and type(record.state) is JobState
            and (record.result_digest is None
                 or (type(record.result_digest) is str
                     and _HEX64.fullmatch(record.result_digest) is not None)))


@dataclass(frozen=True, slots=True)
class ApiDecision:
    """The only outward shape: fixed enums, a fixed HTTP-like class, injected ids. No free text."""

    allowed: bool
    http_class: int
    reason_code: ReasonCode | None
    next_action: NextAction
    correlation_id: str
    ticket: JobTicket | None = None
    job: JobSummary | None = None
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        shape_ok = (
            type(self.allowed) is bool and type(self.http_class) is int
            and self.http_class in HTTP_CLASSES and type(self.next_action) is NextAction
            and _corr_ok(self.correlation_id)
            and type(self.authority) is str and self.authority == AUTHORITY
            and (self.ticket is None or type(self.ticket) is JobTicket)
            and (self.job is None or type(self.job) is JobSummary))
        if shape_ok and self.allowed:
            shape_ok = (self.http_class in (200, 202)
                        and (self.reason_code is None or self.reason_code is _R.REPLAYED)
                        and (self.ticket is not None or self.job is not None))
        elif shape_ok:
            shape_ok = (type(self.reason_code) is ReasonCode and self.http_class in _REFUSAL_HTTP
                        and self.ticket is None and self.job is None)
        if not shape_ok:
            raise ValueError("API_DECISION_INVALID")

    def safe_error(self) -> SafeError | None:
        """The refusal as a ``SafeError`` (``None`` for an allowed decision)."""
        if self.allowed or self.reason_code is None:
            return None
        return SafeError(self.reason_code, self.next_action, self.correlation_id)


def _refuse(reason: ReasonCode, corr: str | None) -> ApiDecision:
    reason = reason if type(reason) is ReasonCode and reason in _HTTP_FOR else _R.INTERNAL_REFUSED
    return ApiDecision(False, _HTTP_FOR[reason], reason, NEXT_ACTION_FOR[reason],
                       corr or DEFAULT_CORRELATION_ID)


def _accept(http: int, reason: ReasonCode | None, corr: str, ticket: JobTicket | None = None,
            job: JobSummary | None = None) -> ApiDecision:
    return ApiDecision(True, http, reason, NEXT_ACTION_FOR.get(reason, NextAction.NO_ACTION), corr,
                       ticket, job)


# ------------------------------------------------------------------ events (observability)

@dataclass(frozen=True, slots=True)
class ApiEvent:
    """A structured operational event: fixed enums, an exception CLASS NAME only, a correlation id."""

    kind: EventKind
    component: ComponentName
    error_class: str
    correlation_id: str


class EventSink(Protocol):
    def emit(self, event: ApiEvent) -> None: ...


class FakeEventSink:
    """Bounded, thread-safe in-memory sink for tests."""

    def __init__(self, max_events: int = 4096) -> None:
        self._lock = threading.Lock()
        self._events: deque[ApiEvent] = deque(maxlen=max_events)

    def emit(self, event: ApiEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[ApiEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def __repr__(self) -> str:
        return "FakeEventSink()"


def _emit(ctx: object, kind: EventKind, component: ComponentName, corr: object,
          error: BaseException | None = None) -> None:
    """Report to the injected sink; never raises and never carries an exception message."""
    try:
        sink = ctx.events  # type: ignore[attr-defined]
        if sink is None:
            return
        name = type(error).__name__ if error is not None else ""
        if name and _CLASS_NAME.fullmatch(name) is None:
            name = "Exception"
        sink.emit(ApiEvent(kind, component, name, corr if _corr_ok(corr) else DEFAULT_CORRELATION_ID))
    except Exception:  # noqa: BLE001, S110 - observability must never break a decision
        pass


class _Internal(Exception):
    """A collaborator failed or answered garbage; the event was already emitted.

    Always means ``DEPENDENCY_FAILED`` (retry later); an unusable context/digest stays ``INTERNAL_REFUSED``."""


def _guard(ctx: object, component: ComponentName, corr: object, fn: Callable[..., object],
           *args: object) -> object:
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - converted to a fixed refusal plus an event
        _emit(ctx, EventKind.COMPONENT_EXCEPTION, component, corr, exc)
        raise _Internal from None


def _bad_output(ctx: object, component: ComponentName, corr: object) -> _Internal:
    _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, component, corr)
    return _Internal()


# ------------------------------------------------------------------ injected collaborators

class ScopeEpochSource(Protocol):
    def current_epoch(self, tenant_id: str, company_id: str) -> int | None: ...


class CapturePolicyPort(Protocol):
    """Policy grant for CAPTURE jobs. The caller never asserts it; the wired policy answers."""

    def allowed(self, tenant_id: str, company_id: str, actor_id: str) -> bool: ...


class JobDispatcher(Protocol):
    def dispatch(self, tenant_id: str, company_id: str, kind: JobKind, request_digest: str) -> str: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def cancel(self, job_id: str) -> None:
        """Compensation: forget/stop a job that was created but could not be handed out."""


class RerunGate(Protocol):
    """Two-step state fence for a rerun (chain head, new evidence, paused source, actor allowed).

    ``check`` is PURE: it reads and returns a verdict (``None`` = may proceed, else one of the gate
    ``ReasonCode`` verdicts) and writes nothing. ``commit`` creates the run and runs exactly once per
    accepted idempotency slot, after the slot is reserved; it returns a ``RerunCommit`` or a verdict
    (the head moved between check and commit). Exceptions mean "dependency failure"."""

    def check(self, request: RerunRequest) -> ReasonCode | None: ...

    def commit(self, request: RerunRequest) -> RerunCommit | ReasonCode: ...


class FakeCapturePolicy:
    """In-memory capture policy: nothing is allowed until ``allow`` grants ``(tenant, company, actor)``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._grants: set[tuple[str, str, str]] = set()

    def allow(self, tenant_id: str, company_id: str, actor_id: str) -> None:
        with self._lock:
            self._grants.add((tenant_id, company_id, actor_id))

    def allowed(self, tenant_id: str, company_id: str, actor_id: str) -> bool:
        with self._lock:
            return (tenant_id, company_id, actor_id) in self._grants

    def __repr__(self) -> str:
        return "FakeCapturePolicy()"


class FakeScopeEpochs:
    """Thread-safe in-memory ``(tenant, company) -> epoch`` table with a test-only ``bump``."""

    def __init__(self, epochs: Mapping[tuple[str, str], int]) -> None:
        self._lock = threading.Lock()
        self._epochs = dict(epochs)

    def current_epoch(self, tenant_id: str, company_id: str) -> int | None:
        with self._lock:
            return self._epochs.get((tenant_id, company_id))

    def bump(self, tenant_id: str, company_id: str) -> int:
        with self._lock:
            self._epochs[(tenant_id, company_id)] = self._epochs.get((tenant_id, company_id), 0) + 1
            return self._epochs[(tenant_id, company_id)]

    def __repr__(self) -> str:
        return "FakeScopeEpochs()"


class FakeJobDispatcher:
    """Records dispatches (bounded) so 'zero calls on refusal' is observable. Ids are JOB-000001...

    Call/get logs and the job table are bounded (oldest dropped); ``call_count`` is the true total."""

    def __init__(self, max_log: int = 4096, max_jobs: int = 4096) -> None:
        self._lock = threading.Lock()
        self._calls: deque[tuple[str, str, JobKind, str]] = deque(maxlen=max_log)
        self._gets: deque[str] = deque(maxlen=max_log)
        self._cancelled: deque[str] = deque(maxlen=max_log)
        self._jobs: OrderedDict[str, JobRecord] = OrderedDict()
        self._max_jobs = max_jobs
        self._n = 0
        self.on_get: Callable[[], object] | None = None  # test hook: runs during a fetch

    @property
    def calls(self) -> tuple[tuple[str, str, JobKind, str], ...]:
        with self._lock:
            return tuple(self._calls)

    @property
    def call_count(self) -> int:
        with self._lock:
            return self._n

    @property
    def get_log(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._gets)

    @property
    def cancel_log(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._cancelled)

    def dispatch(self, tenant_id: str, company_id: str, kind: JobKind, request_digest: str) -> str:
        with self._lock:
            self._n += 1
            self._calls.append((tenant_id, company_id, kind, request_digest))
            job_id = f"JOB-{self._n:06d}"
            self._jobs[job_id] = JobRecord(job_id, tenant_id, company_id, kind, JobState.QUEUED)
            while len(self._jobs) > self._max_jobs:
                self._jobs.popitem(last=False)
            return job_id

    def set_state(self, job_id: str, state: JobState, result_digest: str | None = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = JobRecord(job.job_id, job.tenant_id, job.company_id, job.kind,
                                           state, result_digest)

    def complete(self, job_id: str, result_digest: str) -> None:
        self.set_state(job_id, JobState.SUCCEEDED, result_digest)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancelled.append(job_id)
            self._jobs.pop(job_id, None)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            self._gets.append(job_id)
            found = self._jobs.get(job_id)
            hook = self.on_get
        if hook is not None:
            hook()
        return found

    def __repr__(self) -> str:
        return "FakeJobDispatcher()"


class CsrfGuard:
    """Constant-time CSRF check against a token derived from the session by an injected pure function.

    Production wires ``keyed_csrf_derive(secret)``; ``fake_csrf_token`` is a TEST-ONLY unkeyed hash."""

    def __init__(self, derive: Callable[[SessionRecord], str]) -> None:
        if not callable(derive):
            raise ValueError("CSRF_GUARD_INVALID")  # noqa: TRY004
        self._derive = derive

    def check(self, session: object, token: object) -> bool:
        if not _session_ok(session) or type(token) is not str or not 0 < len(token) <= _MAX_TOKEN:
            return False
        try:
            expected = self._derive(session)  # type: ignore[arg-type]
            if type(expected) is not str or not 0 < len(expected) <= _MAX_TOKEN:
                return False
            return hmac.compare_digest(expected.encode("ascii"), token.encode("ascii"))
        except Exception:  # noqa: BLE001 - any failure to derive or encode is a rejection
            return False

    def __repr__(self) -> str:
        return "CsrfGuard()"


def _csrf_material(session: SessionRecord) -> str:
    return stable_key(session.session_id, session.tenant_id, session.actor_id,
                      session.csrf_secret_digest)


def keyed_csrf_derive(secret: bytes) -> Callable[[SessionRecord], str]:
    """A production-shaped derivation: HMAC-SHA256 under a server-side ``secret`` (>= 16 bytes) over
    the session id, tenant, actor and secret digest. Knowing a session is not enough to forge a token."""
    if type(secret) is not bytes or len(secret) < 16:
        raise ValueError("CSRF_SECRET_INVALID")
    key = bytes(secret)

    def derive(session: SessionRecord) -> str:
        if not _session_ok(session):
            return ""
        return "CSRF-" + hmac.new(key, _csrf_material(session).encode("utf-8"),
                                  hashlib.sha256).hexdigest()

    return derive


def fake_csrf_token(session: object) -> str:
    """TEST-ONLY deterministic derivation (prefix FAKE-): an UNKEYED hash anyone can recompute.

    Never wire it outside tests; production uses ``keyed_csrf_derive``. Bound to session id, tenant,
    actor and secret digest."""
    if not _session_ok(session):
        return "FAKE-INVALID"
    return "FAKE-" + hashlib.sha256(_csrf_material(session).encode("utf-8")).hexdigest()[:32]  # type: ignore[arg-type]


class RefusalLog:
    """Append-only log of refused ``(tenant, company, canonical operation)`` pairs.

    The first recorded reason for a pair is final. Per-tenant quota (``per_tenant``) inside a global
    ceiling (``max_entries``): when a quota is full new pairs are not recorded (the boundary still
    refuses them) and ``overflow_count`` rises; an existing entry is never evicted or rewritten.
    """

    def __init__(self, max_entries: int = 4096, per_tenant: int | None = None) -> None:
        if type(max_entries) is not int or not 1 <= max_entries <= _MAX_ENTRIES:
            raise ValueError("REFUSAL_LOG_INVALID")
        quota = max(1, max_entries // 4) if per_tenant is None else per_tenant
        if type(quota) is not int or not 1 <= quota <= max_entries:
            raise ValueError("REFUSAL_LOG_INVALID")
        self._max = max_entries
        self._per_tenant = quota
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str], ReasonCode] = {}
        self._tenant_n: dict[str, int] = {}
        self._overflow = 0

    @staticmethod
    def _key(tenant_id: object, company_id: object, operation: object) -> tuple[str, str, str] | None:
        if type(tenant_id) is str and type(company_id) is str and type(operation) is str and operation:
            return (tenant_id, company_id, operation)
        return None

    def record(self, tenant_id: object, company_id: object, operation: object, reason: object) -> None:
        key = self._key(tenant_id, company_id, operation)
        if (key is None or not _id_ok(tenant_id) or not _id_ok(company_id)
                or type(reason) is not ReasonCode
                or reason not in (_R.OPERATION_DENIED, _R.OPERATION_UNCLASSIFIED)):
            return
        with self._lock:
            if key in self._rows:
                return
            if len(self._rows) >= self._max or self._tenant_n.get(key[0], 0) >= self._per_tenant:
                self._overflow += 1
                return
            self._rows[key] = reason
            self._tenant_n[key[0]] = self._tenant_n.get(key[0], 0) + 1

    def lookup(self, tenant_id: object, company_id: object, operation: object) -> ReasonCode | None:
        key = self._key(tenant_id, company_id, operation)
        if key is None:
            return None
        with self._lock:
            return self._rows.get(key)

    def peek(self, tenant_id: object, company_id: object, operation: object) -> ReasonCode | None:
        return self.lookup(tenant_id, company_id, operation)

    @property
    def overflow_count(self) -> int:
        with self._lock:
            return self._overflow

    def entries(self) -> tuple[tuple[str, str, str, ReasonCode], ...]:
        with self._lock:
            return tuple((t, c, o, r) for (t, c, o), r in self._rows.items())

    def __repr__(self) -> str:
        return "RefusalLog()"


@dataclass(frozen=True, slots=True)
class StoredOutcome:
    request_digest: str
    ticket: JobTicket


_PENDING, _FINISHING, _EFFECT_DONE, _DONE = 0, 1, 2, 3


class _Entry:
    __slots__ = ("created", "digest", "effect", "event", "owner", "phase", "seq", "ticket")

    def __init__(self, digest: str, created: datetime, owner: int, seq: int) -> None:
        self.digest = digest
        self.created = created
        self.phase = _PENDING
        self.owner = owner
        self.event = threading.Event()
        self.seq = seq
        self.ticket: JobTicket | None = None
        self.effect: RerunCommit | None = None


class IdempotencyStore:
    """Bounded idempotency registry keyed by ``(tenant, actor, endpoint, key)``.

    Same key + same digest replays the stored ticket; same key + different digest is a conflict and the
    stored outcome is untouched. Entries expire only by age on the injected clock (a min-heap sweep,
    amortised O(log n) per entry); when a quota is full of live entries a NEW key is refused (``FULL``)
    - a live entry is never evicted early, so one key can never map to two digests inside its window.

    Quotas: ``per_actor`` <= ``per_tenant`` <= ``max_entries`` (global ceiling), so one tenant or actor
    cannot exhaust the store for the others. ``stats`` counts every overflow by scope.

    Concurrency: the global lock only guards bookkeeping. A slot is RESERVED (pending) under the lock
    and ``action`` runs OUTSIDE it, so a slow action on one key never blocks another key and an action
    may re-enter the store on a different key. Concurrent same-key callers wait (bounded by
    ``wait_seconds``) and then replay; a same-key re-entrant call from the owning thread answers
    ``IN_FLIGHT`` immediately. A staged action returns a ``RerunCommit``: the slot becomes EFFECT_DONE
    and ``complete(commit)`` finishes the dispatch; if that fails the slot stays EFFECT_DONE and the
    next same-key call completes the dispatch for the same run (``complete`` only; no second commit).
    """

    def __init__(self, max_entries: int = 1024, retention_seconds: int = 86400,
                 per_tenant: int | None = None, per_actor: int | None = None,
                 wait_seconds: float = 5.0) -> None:
        if (type(max_entries) is not int or not 1 <= max_entries <= _MAX_ENTRIES
                or type(retention_seconds) is not int or not 1 <= retention_seconds <= _MAX_RETENTION):
            raise ValueError("IDEMPOTENCY_STORE_INVALID")
        tenant_quota = max(1, max_entries // 4) if per_tenant is None else per_tenant
        actor_quota = max(1, tenant_quota // 2) if per_actor is None else per_actor
        if (type(tenant_quota) is not int or type(actor_quota) is not int
                or not 1 <= actor_quota <= tenant_quota <= max_entries
                or type(wait_seconds) not in (int, float) or not 0 <= wait_seconds <= 60):
            raise ValueError("IDEMPOTENCY_STORE_INVALID")
        self._max, self._per_tenant, self._per_actor = max_entries, tenant_quota, actor_quota
        self._wait = float(wait_seconds)
        self._retention = timedelta(seconds=retention_seconds)
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str, str], _Entry] = {}
        self._tenant_n: dict[str, int] = {}
        self._actor_n: dict[tuple[str, str], int] = {}
        self._heap: list[tuple[datetime, int, tuple[str, str, str, str]]] = []
        self._seq = 0
        self._hint: datetime | None = None
        self._effects: deque[tuple[str, str]] = deque(maxlen=_EFFECT_RING)
        self._effect_total = 0
        self._stats = {"full_global": 0, "full_tenant": 0, "full_actor": 0, "in_flight": 0,
                       "expired": 0}

    # ---- bookkeeping (call with the lock held)
    def _sweep(self, now: datetime) -> None:
        if self._hint is None or now > self._hint:
            self._hint = now
        heap = self._heap
        while heap and now - heap[0][0] >= self._retention:
            created, seq, slot = heapq.heappop(heap)
            entry = self._rows.get(slot)
            if (entry is not None and entry.seq == seq and entry.created == created
                    and entry.phase in (_DONE, _EFFECT_DONE)):
                self._remove(slot, entry)
                self._stats["expired"] += 1
        if len(heap) > 2 * len(self._rows) + 256:
            live = [(e.created, e.seq, s) for s, e in self._rows.items()
                    if e.phase in (_DONE, _EFFECT_DONE)]
            heapq.heapify(live)
            self._heap = live

    def _remove(self, slot: tuple[str, str, str, str], entry: _Entry) -> None:
        if self._rows.get(slot) is not entry:
            return
        del self._rows[slot]
        tenant, actor = slot[0], slot[1]
        if self._tenant_n.get(tenant, 0) <= 1:
            self._tenant_n.pop(tenant, None)
        else:
            self._tenant_n[tenant] -= 1
        if self._actor_n.get((tenant, actor), 0) <= 1:
            self._actor_n.pop((tenant, actor), None)
        else:
            self._actor_n[(tenant, actor)] -= 1
        entry.event.set()

    def _quota_full(self, tenant: str, actor: str) -> str | None:
        if self._tenant_n.get(tenant, 0) >= self._per_tenant:
            return "full_tenant"
        if self._actor_n.get((tenant, actor), 0) >= self._per_actor:
            return "full_actor"
        if len(self._rows) >= self._max:
            return "full_global"
        return None

    def _settle(self, slot: tuple[str, str, str, str], entry: _Entry, phase: int) -> None:
        entry.phase = phase
        entry.owner = 0
        heapq.heappush(self._heap, (entry.created, entry.seq, slot))
        entry.event.set()

    def _record_effect(self, endpoint: Endpoint, ref: str) -> None:
        self._effects.append((endpoint.value, ref))
        self._effect_total += 1

    def execute(self, tenant_id: str, actor_id: str, endpoint: Endpoint, key: str, digest: str,
                now: datetime, action: Callable[[], JobTicket | RerunCommit | ReasonCode],
                complete: Callable[[RerunCommit], JobTicket] | None = None) -> tuple[str, object]:
        """Returns ``(status, value)``: NEW/REPLAY -> ticket, CONFLICT/FULL/IN_FLIGHT -> None,
        REFUSED -> reason, PARTIAL -> None (the run exists, the dispatch failed; retry completes it),
        FAILED -> None (the action raised or returned garbage; nothing is recorded)."""
        slot = (tenant_id, actor_id, endpoint.value, key)
        me = threading.get_ident()
        deadline = time.monotonic() + self._wait
        while True:
            with self._lock:
                self._sweep(now)
                entry = self._rows.get(slot)
                if entry is None:
                    full = self._quota_full(tenant_id, actor_id)
                    if full is not None:
                        self._stats[full] += 1
                        return "FULL", None
                    self._seq += 1
                    entry = _Entry(digest, now, me, self._seq)
                    self._rows[slot] = entry
                    self._tenant_n[tenant_id] = self._tenant_n.get(tenant_id, 0) + 1
                    self._actor_n[(tenant_id, actor_id)] = self._actor_n.get((tenant_id, actor_id), 0) + 1
                    break
                if entry.digest != digest:
                    return "CONFLICT", None
                if entry.phase == _DONE:
                    return "REPLAY", entry.ticket
                if entry.phase == _EFFECT_DONE:
                    if complete is None:
                        return "FAILED", None
                    entry.phase, entry.owner, entry.event = _FINISHING, me, threading.Event()
                    break
                if entry.owner == me:
                    self._stats["in_flight"] += 1
                    return "IN_FLIGHT", None
                waiting_on = entry.event
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not waiting_on.wait(remaining):
                with self._lock:
                    self._stats["in_flight"] += 1
                return "IN_FLIGHT", None
        return self._run(slot, entry, endpoint, action, complete)

    def _run(self, slot: tuple[str, str, str, str], entry: _Entry, endpoint: Endpoint,
             action: Callable[[], JobTicket | RerunCommit | ReasonCode],
             complete: Callable[[RerunCommit], JobTicket] | None) -> tuple[str, object]:
        settled = False
        try:
            if entry.phase == _PENDING:
                result = action()
                if type(result) is ReasonCode:
                    return "REFUSED", result
                if type(result) is JobTicket:
                    with self._lock:
                        entry.ticket = result
                        self._record_effect(endpoint, result.job_id)
                        self._settle(slot, entry, _DONE)
                    settled = True
                    return "NEW", result
                if type(result) is not RerunCommit or complete is None:
                    return "FAILED", None
                with self._lock:
                    entry.effect = result
                    entry.phase = _FINISHING
                    self._record_effect(endpoint, result.run_id)
            ticket = complete(entry.effect) if complete is not None and entry.effect is not None else None
            if type(ticket) is not JobTicket:
                raise ValueError("COMPLETE_INVALID")
            with self._lock:
                entry.ticket = ticket
                self._settle(slot, entry, _DONE)
            settled = True
            return "NEW", ticket
        except Exception:  # noqa: BLE001 - a failed step never escapes
            with self._lock:
                if entry.effect is not None:
                    self._settle(slot, entry, _EFFECT_DONE)
                    settled = True
                    return "PARTIAL", None
            return "FAILED", None
        finally:
            if not settled:
                with self._lock:
                    if entry.effect is not None and entry.phase == _FINISHING:
                        self._settle(slot, entry, _EFFECT_DONE)
                    else:
                        self._remove(slot, entry)

    def peek(self, tenant_id: object, actor_id: object, endpoint: Endpoint, key: object,
             now: datetime | None = None) -> StoredOutcome | None:
        """The stored outcome of a finished slot. Expiry is applied exactly as ``execute`` applies it
        (at ``now``, else at the latest ``now`` any ``execute`` saw)."""
        if type(tenant_id) is not str or type(actor_id) is not str or type(key) is not str:
            return None
        with self._lock:
            self._sweep_at(now)
            entry = self._rows.get((tenant_id, actor_id, endpoint.value, key))
            if entry is None or entry.phase != _DONE or entry.ticket is None:
                return None
            return StoredOutcome(entry.digest, entry.ticket)

    def record_count(self, now: datetime | None = None) -> int:
        with self._lock:
            self._sweep_at(now)
            return len(self._rows)

    def _sweep_at(self, now: datetime | None) -> None:
        at = now if _aware(now) else self._hint
        if at is not None:
            self._sweep(at)  # type: ignore[arg-type]

    @property
    def stats(self) -> Mapping[str, int]:
        """Overflow/in-flight/expiry counters (observable quota pressure)."""
        with self._lock:
            return MappingProxyType(dict(self._stats))

    @property
    def effects(self) -> tuple[tuple[str, str], ...]:
        """The most recent audit entries (ring buffer): one per executed (not replayed) mutation."""
        with self._lock:
            return tuple(self._effects)

    @property
    def effect_total(self) -> int:
        with self._lock:
            return self._effect_total

    def __repr__(self) -> str:
        return "IdempotencyStore()"


@dataclass(frozen=True, slots=True)
class ApiContext:
    """The injected collaborators of one wired offline environment (no validation here; the decisions
    check component types and refuse with ``INTERNAL_REFUSED`` when a part is unusable).

    ``ownership`` (``OwnershipPort``), ``entitlements`` (``EntitlementPort``) and ``capture_policy``
    (``CapturePolicyPort``) are REQUIRED: a missing or unusable one fails closed. ``events`` is an
    optional ``EventSink``."""

    csrf: CsrfGuard
    scopes: ScopeEpochSource
    registry: OperationRegistry
    refusals: RefusalLog
    idempotency: IdempotencyStore
    dispatcher: JobDispatcher
    clock: object
    correlation: CorrelationSource
    ownership: OwnershipPort
    entitlements: EntitlementPort
    capture_policy: CapturePolicyPort
    events: EventSink | None = None


def _callable_attrs(obj: object, *names: str) -> bool:
    return all(callable(getattr(obj, name, None)) for name in names)


def _ctx_ok(ctx: object) -> bool:
    try:
        return (type(ctx) is ApiContext and type(ctx.csrf) is CsrfGuard
                and type(ctx.registry) is OperationRegistry and type(ctx.refusals) is RefusalLog
                and type(ctx.idempotency) is IdempotencyStore
                and _callable_attrs(ctx.scopes, "current_epoch")
                and _callable_attrs(ctx.dispatcher, "dispatch", "get", "cancel")
                and _callable_attrs(ctx.clock, "now") and _callable_attrs(ctx.correlation, "next_id")
                and _callable_attrs(ctx.ownership, "owns")
                and _callable_attrs(ctx.entitlements, "entitled")
                and _callable_attrs(ctx.capture_policy, "allowed"))
    except Exception:  # noqa: BLE001
        return False


def _corr(ctx: object) -> str | None:
    try:
        value = ctx.correlation.next_id()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        _emit(ctx, EventKind.COMPONENT_EXCEPTION, ComponentName.CORRELATION, None, exc)
        return None
    if _corr_ok(value) and value != DEFAULT_CORRELATION_ID:
        return value
    _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.CORRELATION, None)
    return None


def _now(ctx: ApiContext, corr: str) -> datetime:
    value = _guard(ctx, ComponentName.CLOCK, corr, ctx.clock.now)  # type: ignore[attr-defined]
    if not _aware(value):
        raise _bad_output(ctx, ComponentName.CLOCK, corr)
    return value  # type: ignore[return-value]


def _entitled(ctx: ApiContext, corr: str, session: SessionRecord, scope: ViewerScope) -> bool:
    value = _guard(ctx, ComponentName.ENTITLEMENTS, corr, ctx.entitlements.entitled,
                   session.tenant_id, session.actor_id, scope.company_id)
    if type(value) is not bool:
        _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.ENTITLEMENTS, corr)
        return False  # fail closed: a non-boolean answer is not an entitlement
    return value


def _pre_checks(ctx: ApiContext, corr: str, session: object, token: object, scope: ViewerScope,
                actor_id: str | None, need_csrf: bool, now: datetime) -> ReasonCode | None:
    """session -> CSRF (mutations only) -> entitlement -> scope epoch. The fixed refusal or None."""
    if not _session_ok(session) or session.tenant_id != scope.tenant_id:  # type: ignore[attr-defined]
        return _R.SESSION_INVALID
    if now >= session.expires_at:  # type: ignore[attr-defined]
        return _R.SESSION_INVALID
    if actor_id is not None and session.actor_id != actor_id:  # type: ignore[attr-defined]
        return _R.SESSION_INVALID
    if need_csrf and not ctx.csrf.check(session, token):
        return _R.CSRF_REJECTED
    if not _entitled(ctx, corr, session, scope):  # type: ignore[arg-type]
        return _R.NOT_IN_SCOPE  # non-member and unknown company look the same; epoch not probeable
    return _epoch_check(ctx, corr, scope)


def _epoch_check(ctx: ApiContext, corr: str, scope: ViewerScope) -> ReasonCode | None:
    current = _guard(ctx, ComponentName.SCOPES, corr, ctx.scopes.current_epoch,
                     scope.tenant_id, scope.company_id)
    if type(current) is not int or current != scope.scope_epoch:
        return _R.SCOPE_EPOCH_STALE
    return None


def _boundary(ctx: ApiContext, scope: ViewerScope, kind: JobKind, operation: str) -> ReasonCode | None:
    name = canonical_operation(operation)
    if not name:
        return _R.OPERATION_UNCLASSIFIED  # invalid spelling: never repaired, never evaluated
    prior = ctx.refusals.lookup(scope.tenant_id, scope.company_id, name)
    if prior is not None:
        return prior
    plan = CapturePlan((name,), frozenset({"read"}), Environment.PROD)
    decision = evaluate(plan, ctx.registry)
    if not decision.allowed:
        reason = _BOUNDARY_DENIED.get(decision.code, _R.OPERATION_UNCLASSIFIED)
        ctx.refusals.record(scope.tenant_id, scope.company_id, name, reason)
        return reason
    if name != OPERATION_FOR.get(kind):
        return _R.OPERATION_DENIED  # an allowed name that does not belong to this kind (not sticky)
    return None


def _owned(ctx: ApiContext, corr: str, scope: ViewerScope,
           refs: tuple[tuple[str, str], ...]) -> ReasonCode | None:
    """Every id must be owned by the request scope's company; foreign and unknown look the same."""
    for ownership_kind, ref in refs:
        value = _guard(ctx, ComponentName.OWNERSHIP, corr, ctx.ownership.owns,
                       scope.tenant_id, scope.company_id, ownership_kind, ref)
        if type(value) is not bool:
            _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.OWNERSHIP, corr)
            return _R.NOT_IN_SCOPE
        if not value:
            return _R.NOT_IN_SCOPE
    return None


def _outcome(ctx: ApiContext, status: str, value: object, corr: str) -> ApiDecision:
    if status == "NEW" and type(value) is JobTicket:
        return _accept(202, None, corr, ticket=value)
    if status == "REPLAY" and type(value) is JobTicket:
        return _accept(200, _R.REPLAYED, corr, ticket=value)
    if status == "CONFLICT":
        return _refuse(_R.IDEMPOTENCY_CONFLICT, corr)
    if status == "FULL":
        _emit(ctx, EventKind.QUOTA_OVERFLOW, ComponentName.IDEMPOTENCY, corr)
        return _refuse(_R.RATE_LIMITED, corr)
    if status == "IN_FLIGHT":
        _emit(ctx, EventKind.IN_FLIGHT_TIMEOUT, ComponentName.IDEMPOTENCY, corr)
        return _refuse(_R.RATE_LIMITED, corr)
    if status == "PARTIAL":
        _emit(ctx, EventKind.DISPATCH_RETRY_PENDING, ComponentName.DISPATCHER, corr)
        return _refuse(_R.DEPENDENCY_FAILED, corr)  # retry with the same key completes the dispatch
    if status == "REFUSED" and type(value) is ReasonCode:
        return _refuse(value, corr)
    if status == "FAILED":
        return _refuse(_R.DEPENDENCY_FAILED, corr)  # the action raised or answered garbage
    return _refuse(_R.INTERNAL_REFUSED, corr)


def _dispatch_ticket(ctx: ApiContext, corr: str, scope: ViewerScope, kind: JobKind, digest: str,
                     commit: RerunCommit | None = None) -> JobTicket:
    job_id = _guard(ctx, ComponentName.DISPATCHER, corr, ctx.dispatcher.dispatch,
                    scope.tenant_id, scope.company_id, kind, digest)
    if not _key_ok(job_id):
        if type(job_id) is str:
            try:
                ctx.dispatcher.cancel(job_id)
                _emit(ctx, EventKind.ORPHAN_JOB_CANCELLED, ComponentName.DISPATCHER, corr)
            except Exception as exc:  # noqa: BLE001
                _emit(ctx, EventKind.ORPHAN_JOB_UNREACHABLE, ComponentName.DISPATCHER, corr, exc)
        else:
            _emit(ctx, EventKind.ORPHAN_JOB_UNREACHABLE, ComponentName.DISPATCHER, corr)
        raise _bad_output(ctx, ComponentName.DISPATCHER, corr)
    return JobTicket(job_id, scope.tenant_id, scope.company_id, kind, digest,  # type: ignore[arg-type]
                     run_id=None if commit is None else commit.run_id,
                     run_state=None if commit is None else commit.state)


def _unexpected(ctx: object, corr: str | None, exc: Exception) -> ApiDecision:
    _emit(ctx, EventKind.UNEXPECTED_EXCEPTION, ComponentName.UNEXPECTED, corr, exc)
    return _refuse(_R.INTERNAL_REFUSED, corr)


# ------------------------------------------------------------------ public decisions

def decide_enqueue(ctx: object, request: object, session: object, csrf_token: object) -> ApiDecision:
    """Decide an enqueue (rescan/report/reconciliation/capture). Never raises."""
    corr = _corr(ctx)
    try:
        if not _ctx_ok(ctx) or corr is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        if not _request_ok(request):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        now = _now(ctx, corr)  # type: ignore[arg-type]
        scope, kind, actor = request.scope, request.kind, request.actor_id  # type: ignore[attr-defined]
        refusal = _pre_checks(ctx, corr, session, csrf_token, scope, actor, True, now)  # type: ignore[arg-type]
        if refusal is not None:
            return _refuse(refusal, corr)
        refusal = _boundary(ctx, scope, kind, request.operation)  # type: ignore[arg-type,attr-defined]
        if refusal is not None:
            return _refuse(refusal, corr)
        params = _params(kind, request.params)  # type: ignore[attr-defined]
        if params is None:
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        if kind is JobKind.CAPTURE:
            granted = _guard(ctx, ComponentName.CAPTURE_POLICY, corr,  # type: ignore[arg-type]
                             ctx.capture_policy.allowed, scope.tenant_id, scope.company_id, actor)  # type: ignore[attr-defined]
            if granted is not True:
                if type(granted) is not bool:
                    _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.CAPTURE_POLICY, corr)
                return _refuse(_R.OPERATION_DENIED, corr)  # no policy grant: idempotency untouched
        refusal = _owned(ctx, corr, scope, tuple((_OWNERSHIP_KIND[n], v) for n, v in params))  # type: ignore[arg-type]
        if refusal is not None:
            return _refuse(refusal, corr)
        if not _key_ok(request.idempotency_key):  # type: ignore[attr-defined]
            return _refuse(_R.IDEMPOTENCY_KEY_REQUIRED, corr)
        digest = request_digest(request, Endpoint.ENQUEUE_JOB)
        if not digest:
            _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.DIGEST, corr)
            return _refuse(_R.INTERNAL_REFUSED, corr)
        status, value = ctx.idempotency.execute(  # type: ignore[attr-defined]
            scope.tenant_id, actor, Endpoint.ENQUEUE_JOB, request.idempotency_key,  # type: ignore[attr-defined]
            digest, now, lambda: _dispatch_ticket(ctx, corr, scope, kind, digest))  # type: ignore[arg-type]
        return _outcome(ctx, status, value, corr)  # type: ignore[arg-type]
    except _Internal:
        return _refuse(_R.DEPENDENCY_FAILED, corr)
    except Exception as exc:  # noqa: BLE001 - a decision function never raises
        return _unexpected(ctx, corr, exc)


def decide_rerun(ctx: object, request: object, session: object, csrf_token: object,
                 gate: object) -> ApiDecision:
    """Decide a safe rerun: CSRF + entitlement + scope + ownership + idempotency + the two-step gate."""
    corr = _corr(ctx)
    try:
        if not _ctx_ok(ctx) or corr is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        if not _rerun_ok(request):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        now = _now(ctx, corr)  # type: ignore[arg-type]
        scope, actor = request.scope, request.actor_id  # type: ignore[attr-defined]
        refusal = _pre_checks(ctx, corr, session, csrf_token, scope, actor, True, now)  # type: ignore[arg-type]
        if refusal is not None:
            return _refuse(refusal, corr)
        refusal = _owned(ctx, corr, scope, (  # type: ignore[arg-type]
            ("comparison_key", request.comparison_key), ("run_id", request.previous_run_id),  # type: ignore[attr-defined]
            ("snapshot_id", request.new_snapshot_id)))  # type: ignore[attr-defined]
        if refusal is not None:
            return _refuse(refusal, corr)
        if not _key_ok(request.idempotency_key):  # type: ignore[attr-defined]
            return _refuse(_R.IDEMPOTENCY_KEY_REQUIRED, corr)
        if not _callable_attrs(gate, "check", "commit"):
            _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.GATE, corr)
            return _refuse(_R.INTERNAL_REFUSED, corr)
        digest = request_digest(request, Endpoint.RERUN)
        if not digest:
            _emit(ctx, EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.DIGEST, corr)
            return _refuse(_R.INTERNAL_REFUSED, corr)

        def verdict_of(value: object) -> ReasonCode:
            if type(value) is ReasonCode and value in _GATE_VERDICTS:
                return value
            raise _bad_output(ctx, ComponentName.GATE, corr)  # type: ignore[arg-type]

        def action() -> RerunCommit | ReasonCode:
            verdict = _guard(ctx, ComponentName.GATE, corr, gate.check, request)  # type: ignore[attr-defined,arg-type]
            if verdict is not None:
                return verdict_of(verdict)
            made = _guard(ctx, ComponentName.GATE, corr, gate.commit, request)  # type: ignore[attr-defined,arg-type]
            if type(made) is RerunCommit:
                return made
            return verdict_of(made)

        def complete(commit: RerunCommit) -> JobTicket:
            return _dispatch_ticket(ctx, corr, scope, JobKind.RERUN, digest, commit)  # type: ignore[arg-type]

        status, value = ctx.idempotency.execute(  # type: ignore[attr-defined]
            scope.tenant_id, actor, Endpoint.RERUN, request.idempotency_key,  # type: ignore[attr-defined]
            digest, now, action, complete)
        return _outcome(ctx, status, value, corr)  # type: ignore[arg-type]
    except _Internal:
        return _refuse(_R.DEPENDENCY_FAILED, corr)
    except Exception as exc:  # noqa: BLE001
        return _unexpected(ctx, corr, exc)


def _read(ctx: object, viewer: object, session: object, job_id: object, want_result: bool) -> ApiDecision:
    corr = _corr(ctx)
    try:
        if not _ctx_ok(ctx) or corr is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        if not is_valid_scope(viewer):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        now = _now(ctx, corr)  # type: ignore[arg-type]
        refusal = _pre_checks(ctx, corr, session, None, viewer, None, False, now)  # type: ignore[arg-type]
        if refusal is not None:
            return _refuse(refusal, corr)
        if not _key_ok(job_id):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        record = _guard(ctx, ComponentName.DISPATCHER, corr, ctx.dispatcher.get, job_id)  # type: ignore[attr-defined,arg-type]
        refusal = _epoch_check(ctx, corr, viewer)  # type: ignore[arg-type]  # re-check before disclosure
        if refusal is not None:
            return _refuse(refusal, corr)
        if record is None:
            return _refuse(_R.NOT_FOUND, corr)
        if not _record_ok(record):
            raise _bad_output(ctx, ComponentName.DISPATCHER, corr)  # type: ignore[arg-type]
        if (record.tenant_id != viewer.tenant_id or record.company_id != viewer.company_id  # type: ignore[attr-defined]
                or record.job_id != job_id):  # type: ignore[attr-defined]
            return _refuse(_R.NOT_FOUND, corr)  # foreign: indistinguishable from missing
        http = 200
        digest = None
        if want_result:
            if record.state is JobState.SUCCEEDED:  # type: ignore[attr-defined]
                if record.result_digest is None:  # type: ignore[attr-defined]
                    raise _bad_output(ctx, ComponentName.DISPATCHER, corr)  # type: ignore[arg-type]
                digest = record.result_digest  # type: ignore[attr-defined]
            elif record.state in (JobState.QUEUED, JobState.RUNNING):  # type: ignore[attr-defined]
                http = 202  # own job, not finished: its fixed state, no digest
        summary = JobSummary(record.job_id, record.kind, record.state, digest)  # type: ignore[attr-defined]
        return _accept(http, None, corr, job=summary)  # type: ignore[arg-type]
    except _Internal:
        return _refuse(_R.DEPENDENCY_FAILED, corr)
    except Exception as exc:  # noqa: BLE001
        return _unexpected(ctx, corr, exc)


def read_job(ctx: object, viewer: object, session: object, job_id: object) -> ApiDecision:
    """Read a job's status inside the viewer's scope. Never raises."""
    return _read(ctx, viewer, session, job_id, False)


def read_result(ctx: object, viewer: object, session: object, job_id: object) -> ApiDecision:
    """Read a job's result digest inside the viewer's scope; an unfinished own job shows its state."""
    return _read(ctx, viewer, session, job_id, True)
