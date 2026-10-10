"""Phase 2 sprint S8 (R2-US-041, TC121-TC123): safe job/result API DECISIONS. Not a server.

Offline, unwired, in-memory, synchronous reference logic: pure decision functions over typed requests.
There is no web framework, no cookie parsing, no HTTP library, no DB and no 1C client here.

Public decisions (each maps to one row of the ``ENDPOINTS`` annotation table):

* ``decide_enqueue`` / ``decide_rerun`` - mutations. Fixed check order, tested:
  structure -> session -> CSRF -> scope epoch -> operation boundary -> parameter schema ->
  idempotency key -> idempotency store -> dispatch. A refusal at any step never touches a later step,
  so a CSRF/epoch/boundary refusal creates no idempotency record and makes no dispatcher call.
  ``decide_rerun`` has no caller operation name; its state fence (``RerunGate``) runs INSIDE the
  idempotency step so a retried request replays its stored outcome even after the head has moved.
* ``read_job`` / ``read_result`` - reads. No CSRF. The scope epoch is re-checked before the fetch and
  again before disclosure; a foreign or missing job is the same ``NOT_FOUND`` shape.

Every outcome is an ``ApiDecision``: ``(allowed, http_class, reason_code, next_action, correlation_id,
ticket, job)`` built only from fixed enums, fixed integers and ids produced by injected sources.
Caller text (operation names, keys, tokens, parameters, exception text) is never echoed. Hostile
input and failing collaborators give a fixed ``INTERNAL_REFUSED``/schema refusal and never raise.

Channel is not an input: no function takes a channel/transport label, and the operation name is
canonicalised by ``side_effect_boundary.canonical_operation`` and classified by ``evaluate`` before
anything else. A refused (tenant, company, operation) pair is written to an append-only ``RefusalLog``
and stays refused for every later spelling.

KNOWN GAPS: sessions, CSRF derivation, the scope-epoch source, the rerun gate and the actor role model
are injected fakes; ``JobQueuePort`` / the real ``jobs`` table are not used; no cookie flags, CORS or
real HTTP. Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol

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
    is_valid_scope,
    safe_error,
)

__all__ = [
    "DECISION_ENDPOINTS", "ENDPOINTS", "HTTP_CLASSES", "ApiContext", "ApiDecision", "CsrfGuard",
    "Endpoint", "EndpointAnnotation", "FakeJobDispatcher", "FakeScopeEpochs", "IdempotencyStore",
    "JobDispatcher", "JobKind", "JobRecord", "JobRequest", "JobState", "JobSummary", "JobTicket",
    "NextAction", "RefusalLog", "RerunGate", "RerunRequest", "ScopeEpochSource", "SessionRecord",
    "StoredOutcome", "decide_enqueue", "decide_rerun", "fake_csrf_token", "read_job", "read_result",
    "request_digest",
]

_R = ReasonCode
HTTP_CLASSES: Final = frozenset({200, 202, 400, 401, 403, 404, 409, 429})
_REFUSAL_HTTP: Final = frozenset({400, 401, 403, 404, 409, 429})
_KEY: Final = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_MAX_TOKEN: Final = 512
_MAX_ENTRIES: Final = 1_000_000
_MAX_RETENTION: Final = 30 * 86400


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
_HTTP_FOR: Final[Mapping[ReasonCode, int]] = MappingProxyType({
    _R.SESSION_INVALID: 401, _R.CSRF_REJECTED: 403, _R.SCOPE_EPOCH_STALE: 403,
    _R.OPERATION_DENIED: 403, _R.OPERATION_UNCLASSIFIED: 403, _R.NOT_IN_SCOPE: 403,
    _R.PARAMETER_SCHEMA_INVALID: 400, _R.IDEMPOTENCY_KEY_REQUIRED: 400, _R.INTERNAL_REFUSED: 400,
    _R.NOT_FOUND: 404, _R.RERUN_TARGET_UNKNOWN: 404, _R.IDEMPOTENCY_CONFLICT: 409,
    _R.RERUN_TARGET_STALE: 409, _R.NO_NEW_EVIDENCE: 409, _R.SOURCE_PAUSED: 409, _R.RATE_LIMITED: 429,
})
_GATE_VERDICTS: Final = frozenset({
    _R.NO_NEW_EVIDENCE, _R.RERUN_TARGET_STALE, _R.RERUN_TARGET_UNKNOWN, _R.NOT_IN_SCOPE,
    _R.SOURCE_PAUSED, _R.OPERATION_DENIED,
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


# ------------------------------------------------------------------ request / session types

@dataclass(frozen=True, slots=True)
class SessionRecord:
    """An already-authenticated session as the decision layer sees it (no cookie handling here)."""

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
class JobTicket:
    job_id: str
    tenant_id: str
    company_id: str
    kind: JobKind
    request_digest: str
    authority: str = AUTHORITY


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


def _corr_ok(value: object) -> bool:
    return safe_error(_R.NOT_FOUND, value).correlation_id == value and value != DEFAULT_CORRELATION_ID


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
            and safe_error(_R.NOT_FOUND, self.correlation_id).correlation_id == self.correlation_id
            and self.authority == AUTHORITY and type(self.authority) is str
            and (self.ticket is None or type(self.ticket) is JobTicket)
            and (self.job is None or type(self.job) is JobSummary))
        if shape_ok and self.allowed:
            shape_ok = (self.http_class in (200, 202) and self.reason_code in (None, _R.REPLAYED)
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


# ------------------------------------------------------------------ injected collaborators

class ScopeEpochSource(Protocol):
    def current_epoch(self, tenant_id: str, company_id: str) -> int | None: ...


class JobDispatcher(Protocol):
    def dispatch(self, tenant_id: str, company_id: str, kind: JobKind, request_digest: str) -> str: ...

    def get(self, job_id: str) -> JobRecord | None: ...


class RerunGate(Protocol):
    """State fence for a rerun (chain head, new evidence, paused source, actor allowed)."""

    def check(self, request: RerunRequest) -> ReasonCode | None: ...


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
    """Records every dispatch so 'zero calls on refusal' is observable. Job ids are JOB-000001..."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[tuple[str, str, JobKind, str]] = []
        self._gets: list[str] = []
        self._jobs: dict[str, JobRecord] = {}
        self.on_get: Callable[[], object] | None = None  # test hook: runs during a fetch

    @property
    def calls(self) -> tuple[tuple[str, str, JobKind, str], ...]:
        with self._lock:
            return tuple(self._calls)

    @property
    def get_log(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._gets)

    def dispatch(self, tenant_id: str, company_id: str, kind: JobKind, request_digest: str) -> str:
        with self._lock:
            self._calls.append((tenant_id, company_id, kind, request_digest))
            job_id = f"JOB-{len(self._calls):06d}"
            self._jobs[job_id] = JobRecord(job_id, tenant_id, company_id, kind, JobState.QUEUED)
            return job_id

    def complete(self, job_id: str, result_digest: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = JobRecord(job.job_id, job.tenant_id, job.company_id, job.kind,
                                           JobState.SUCCEEDED, result_digest)

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
    """Constant-time CSRF check against a token derived from the session by an injected pure function."""

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


def fake_csrf_token(session: object) -> str:
    """Deterministic test derivation (prefix FAKE-); bound to session id, tenant, actor and secret digest."""
    if not _session_ok(session):
        return "FAKE-INVALID"
    material = stable_key(session.session_id, session.tenant_id, session.actor_id,  # type: ignore[attr-defined]
                          session.csrf_secret_digest)  # type: ignore[attr-defined]
    return "FAKE-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class RefusalLog:
    """Append-only log of refused ``(tenant, company, canonical operation)`` pairs.

    The first recorded reason for a pair is final. When full, new pairs are simply not recorded (the
    boundary still refuses them); an existing entry is never evicted or rewritten.
    """

    def __init__(self, max_entries: int = 4096) -> None:
        if type(max_entries) is not int or not 1 <= max_entries <= _MAX_ENTRIES:
            raise ValueError("REFUSAL_LOG_INVALID")
        self._max = max_entries
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str], ReasonCode] = {}

    def record(self, tenant_id: object, company_id: object, operation: object, reason: object) -> None:
        if (not _id_ok(tenant_id) or not _id_ok(company_id) or type(operation) is not str
                or not operation or reason not in (_R.OPERATION_DENIED, _R.OPERATION_UNCLASSIFIED)
                or type(reason) is not ReasonCode):
            return
        with self._lock:
            key = (tenant_id, company_id, operation)  # type: ignore[assignment]
            if key not in self._rows and len(self._rows) < self._max:
                self._rows[key] = reason

    def lookup(self, tenant_id: object, company_id: object, operation: object) -> ReasonCode | None:
        with self._lock:
            return self._rows.get((tenant_id, company_id, operation))  # type: ignore[arg-type]

    def entries(self) -> tuple[tuple[str, str, str, ReasonCode], ...]:
        with self._lock:
            return tuple((t, c, o, r) for (t, c, o), r in self._rows.items())

    def __repr__(self) -> str:
        return "RefusalLog()"


@dataclass(frozen=True, slots=True)
class StoredOutcome:
    request_digest: str
    ticket: JobTicket


@dataclass(slots=True)
class _Entry:
    outcome: StoredOutcome
    created: datetime


class IdempotencyStore:
    """Bounded idempotency registry keyed by ``(tenant, actor, endpoint, key)``.

    Same key + same digest replays the stored ticket; same key + different digest is a conflict and the
    stored outcome is untouched. Entries expire only by age on the injected clock; when the store is
    full of live entries a NEW key is refused (``FULL``) - a live entry is never evicted early, so one
    key can never map to two digests inside its retention window. The whole check-run-record sequence
    holds one lock, so concurrent identical requests dispatch exactly once.
    """

    def __init__(self, max_entries: int = 1024, retention_seconds: int = 86400) -> None:
        if (type(max_entries) is not int or not 1 <= max_entries <= _MAX_ENTRIES
                or type(retention_seconds) is not int or not 1 <= retention_seconds <= _MAX_RETENTION):
            raise ValueError("IDEMPOTENCY_STORE_INVALID")
        self._max = max_entries
        self._retention = timedelta(seconds=retention_seconds)
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str, str], _Entry] = {}
        self._effects: list[tuple[str, str]] = []

    def execute(self, tenant_id: str, actor_id: str, endpoint: Endpoint, key: str, digest: str,
                now: datetime, action: Callable[[], JobTicket | ReasonCode]) -> tuple[str, object]:
        """Returns ``(status, value)``: NEW/REPLAY -> ticket, CONFLICT/FULL -> None, REFUSED -> reason,
        FAILED -> None (the action raised or returned garbage; nothing is recorded)."""
        slot = (tenant_id, actor_id, endpoint.value, key)
        with self._lock:
            for old_slot in [s for s, e in self._rows.items() if now - e.created >= self._retention]:
                del self._rows[old_slot]
            entry = self._rows.get(slot)
            if entry is not None:
                if entry.outcome.request_digest == digest:
                    return "REPLAY", entry.outcome.ticket
                return "CONFLICT", None
            if len(self._rows) >= self._max:
                return "FULL", None
            try:
                result = action()
            except Exception:  # noqa: BLE001 - a failed dispatch records nothing
                return "FAILED", None
            if type(result) is ReasonCode:
                return "REFUSED", result
            if type(result) is not JobTicket:
                return "FAILED", None
            self._rows[slot] = _Entry(StoredOutcome(digest, result), now)
            self._effects.append((endpoint.value, result.job_id))
            return "NEW", result

    def peek(self, tenant_id: object, actor_id: object, endpoint: Endpoint, key: object) -> StoredOutcome | None:
        with self._lock:
            entry = self._rows.get((tenant_id, actor_id, endpoint.value, key))  # type: ignore[arg-type]
            return None if entry is None else entry.outcome

    def record_count(self) -> int:
        with self._lock:
            return len(self._rows)

    @property
    def effects(self) -> tuple[tuple[str, str], ...]:
        """One audit entry per executed (not replayed) mutation."""
        with self._lock:
            return tuple(self._effects)

    def __repr__(self) -> str:
        return "IdempotencyStore()"


@dataclass(frozen=True, slots=True)
class ApiContext:
    """The injected collaborators of one wired offline environment (no validation here; the decisions
    check component types and refuse with ``INTERNAL_REFUSED`` when a part is unusable)."""

    csrf: CsrfGuard
    scopes: ScopeEpochSource
    registry: OperationRegistry
    refusals: RefusalLog
    idempotency: IdempotencyStore
    dispatcher: JobDispatcher
    clock: object
    correlation: CorrelationSource


def _ctx_ok(ctx: object) -> bool:
    try:
        return (type(ctx) is ApiContext and type(ctx.csrf) is CsrfGuard
                and type(ctx.registry) is OperationRegistry and type(ctx.refusals) is RefusalLog
                and type(ctx.idempotency) is IdempotencyStore)
    except AttributeError:
        return False


def _corr(ctx: object) -> str | None:
    try:
        value = ctx.correlation.next_id()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None
    return value if _corr_ok(value) else None


def _now(ctx: ApiContext) -> datetime | None:
    value = ctx.clock.now()  # type: ignore[attr-defined]
    return value if _aware(value) else None


def _pre_checks(ctx: ApiContext, session: object, token: object, scope: ViewerScope,
                actor_id: str | None, need_csrf: bool, now: datetime) -> ReasonCode | None:
    """session -> CSRF (mutations only) -> scope epoch. Returns the fixed refusal or None."""
    if not _session_ok(session) or session.tenant_id != scope.tenant_id:  # type: ignore[attr-defined]
        return _R.SESSION_INVALID
    if now >= session.expires_at:  # type: ignore[attr-defined]
        return _R.SESSION_INVALID
    if actor_id is not None and session.actor_id != actor_id:  # type: ignore[attr-defined]
        return _R.SESSION_INVALID
    if need_csrf and not ctx.csrf.check(session, token):
        return _R.CSRF_REJECTED
    return _epoch_check(ctx, scope)


def _epoch_check(ctx: ApiContext, scope: ViewerScope) -> ReasonCode | None:
    current = ctx.scopes.current_epoch(scope.tenant_id, scope.company_id)
    if type(current) is not int or current != scope.scope_epoch:
        return _R.SCOPE_EPOCH_STALE
    return None


def _key_ok(key: object) -> bool:
    return type(key) is str and len(key) <= 128 and _KEY.fullmatch(key) is not None


def _boundary(ctx: ApiContext, scope: ViewerScope, operation: str) -> ReasonCode | None:
    name = canonical_operation(operation)
    if not name:
        return _R.OPERATION_UNCLASSIFIED  # invalid spelling: never repaired, never evaluated
    prior = ctx.refusals.lookup(scope.tenant_id, scope.company_id, name)
    if prior is not None:
        return prior
    plan = CapturePlan((name,), frozenset({"read"}), Environment.PROD)
    decision = evaluate(plan, ctx.registry)
    if decision.allowed:
        return None
    reason = _BOUNDARY_DENIED.get(decision.code, _R.OPERATION_UNCLASSIFIED)
    ctx.refusals.record(scope.tenant_id, scope.company_id, name, reason)
    return reason


def _outcome(status: str, value: object, corr: str) -> ApiDecision:
    if status == "NEW" and type(value) is JobTicket:
        return _accept(202, None, corr, ticket=value)
    if status == "REPLAY" and type(value) is JobTicket:
        return _accept(200, _R.REPLAYED, corr, ticket=value)
    if status == "CONFLICT":
        return _refuse(_R.IDEMPOTENCY_CONFLICT, corr)
    if status == "FULL":
        return _refuse(_R.RATE_LIMITED, corr)
    if status == "REFUSED" and type(value) is ReasonCode:
        return _refuse(value, corr)
    return _refuse(_R.INTERNAL_REFUSED, corr)


def _dispatch_ticket(ctx: ApiContext, scope: ViewerScope, kind: JobKind, digest: str) -> JobTicket:
    job_id = ctx.dispatcher.dispatch(scope.tenant_id, scope.company_id, kind, digest)
    if not _id_ok(job_id):
        raise ValueError("DISPATCH_INVALID")
    return JobTicket(job_id, scope.tenant_id, scope.company_id, kind, digest)


# ------------------------------------------------------------------ public decisions

def decide_enqueue(ctx: object, request: object, session: object, csrf_token: object,
                   capture_allowed: object = False) -> ApiDecision:
    """Decide an enqueue (rescan/report/reconciliation/capture). Never raises."""
    corr = _corr(ctx)
    try:
        if not _ctx_ok(ctx) or corr is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        if not _request_ok(request):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        now = _now(ctx)  # type: ignore[arg-type]
        if now is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        scope = request.scope  # type: ignore[attr-defined]
        refusal = _pre_checks(ctx, session, csrf_token, scope, request.actor_id, True, now)  # type: ignore[arg-type,attr-defined]
        if refusal is not None:
            return _refuse(refusal, corr)
        refusal = _boundary(ctx, scope, request.operation)  # type: ignore[arg-type,attr-defined]
        if refusal is not None:
            return _refuse(refusal, corr)
        if _params(request.kind, request.params) is None:  # type: ignore[attr-defined]
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        if request.kind is JobKind.CAPTURE and capture_allowed is not True:  # type: ignore[attr-defined]
            return _refuse(_R.OPERATION_DENIED, corr)
        if not _key_ok(request.idempotency_key):  # type: ignore[attr-defined]
            return _refuse(_R.IDEMPOTENCY_KEY_REQUIRED, corr)
        digest = request_digest(request, Endpoint.ENQUEUE_JOB)
        kind = request.kind  # type: ignore[attr-defined]
        status, value = ctx.idempotency.execute(  # type: ignore[attr-defined]
            scope.tenant_id, request.actor_id, Endpoint.ENQUEUE_JOB, request.idempotency_key,  # type: ignore[attr-defined]
            digest, now, lambda: _dispatch_ticket(ctx, scope, kind, digest))  # type: ignore[arg-type]
        return _outcome(status, value, corr)
    except Exception:  # noqa: BLE001 - a decision function never raises
        return _refuse(_R.INTERNAL_REFUSED, corr)


def decide_rerun(ctx: object, request: object, session: object, csrf_token: object,
                 gate: object) -> ApiDecision:
    """Decide a safe rerun: CSRF + idempotency + scope + injected state fence. Never raises."""
    corr = _corr(ctx)
    try:
        if not _ctx_ok(ctx) or corr is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        if not _rerun_ok(request):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        now = _now(ctx)  # type: ignore[arg-type]
        if now is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        scope = request.scope  # type: ignore[attr-defined]
        refusal = _pre_checks(ctx, session, csrf_token, scope, request.actor_id, True, now)  # type: ignore[arg-type,attr-defined]
        if refusal is not None:
            return _refuse(refusal, corr)
        if not _key_ok(request.idempotency_key):  # type: ignore[attr-defined]
            return _refuse(_R.IDEMPOTENCY_KEY_REQUIRED, corr)
        digest = request_digest(request, Endpoint.RERUN)

        def action() -> JobTicket | ReasonCode:
            verdict = gate.check(request)  # type: ignore[attr-defined]
            if verdict is None:
                return _dispatch_ticket(ctx, scope, JobKind.RERUN, digest)  # type: ignore[arg-type]
            if type(verdict) is ReasonCode and verdict in _GATE_VERDICTS:
                return verdict
            raise ValueError("GATE_VERDICT_INVALID")

        status, value = ctx.idempotency.execute(  # type: ignore[attr-defined]
            scope.tenant_id, request.actor_id, Endpoint.RERUN, request.idempotency_key,  # type: ignore[attr-defined]
            digest, now, action)
        return _outcome(status, value, corr)
    except Exception:  # noqa: BLE001
        return _refuse(_R.INTERNAL_REFUSED, corr)


def _read(ctx: object, viewer: object, session: object, job_id: object, want_result: bool) -> ApiDecision:
    corr = _corr(ctx)
    try:
        if not _ctx_ok(ctx) or corr is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        if not is_valid_scope(viewer):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        now = _now(ctx)  # type: ignore[arg-type]
        if now is None:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        refusal = _pre_checks(ctx, session, None, viewer, None, False, now)  # type: ignore[arg-type]
        if refusal is not None:
            return _refuse(refusal, corr)
        if not _key_ok(job_id):
            return _refuse(_R.PARAMETER_SCHEMA_INVALID, corr)
        record = ctx.dispatcher.get(job_id)  # type: ignore[attr-defined]
        refusal = _epoch_check(ctx, viewer)  # type: ignore[arg-type]  # re-check before disclosure
        if refusal is not None:
            return _refuse(refusal, corr)
        if record is None:
            return _refuse(_R.NOT_FOUND, corr)
        if type(record) is not JobRecord:
            return _refuse(_R.INTERNAL_REFUSED, corr)
        if record.tenant_id != viewer.tenant_id or record.company_id != viewer.company_id:  # type: ignore[attr-defined]
            return _refuse(_R.NOT_FOUND, corr)  # foreign: indistinguishable from missing
        if want_result and (record.state is not JobState.SUCCEEDED or record.result_digest is None):
            return _refuse(_R.NOT_FOUND, corr)
        summary = JobSummary(record.job_id, record.kind, record.state,
                             record.result_digest if want_result else None)
        return _accept(200, None, corr, job=summary)
    except Exception:  # noqa: BLE001
        return _refuse(_R.INTERNAL_REFUSED, corr)


def read_job(ctx: object, viewer: object, session: object, job_id: object) -> ApiDecision:
    """Read a job's status inside the viewer's scope. Never raises."""
    return _read(ctx, viewer, session, job_id, False)


def read_result(ctx: object, viewer: object, session: object, job_id: object) -> ApiDecision:
    """Read a finished job's result digest inside the viewer's scope. Never raises."""
    return _read(ctx, viewer, session, job_id, True)
