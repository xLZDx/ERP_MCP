"""Phase 2 living-registry ports: runtime-neutral contracts for the ``living.*`` SQL API.

Four async ``typing.Protocol`` ports mirror db/phase2/001-003 one-to-one (names, arguments, error
codes). Two implementations exist: the in-memory fake in ``fakes.py`` and the real SQL functions
(driven by the thin adapter in tests/phase2/_sql_ports.py). One shared contract test body runs
against both; SQL is the source of truth, the fake is corrected to match it.

Conventions
- Every call names the ``actor`` (the authenticated DB role in SQL; ``living.caller_role()``) and
  the ``Scope`` (tenant, source). Identity is never a free-form argument of the SQL function.
- A rejected call raises ``PortError(code)``; ``code`` is the SQL exception text (for example
  ``STALE_JOB_FENCE``). Constraint violations that carry no text map to ``CHECK_VIOLATION``,
  ``UNIQUE_VIOLATION``, ``FK_VIOLATION`` and missing EXECUTE rights to ``PERMISSION_DENIED``.
- A rejected call changes nothing (the SQL call runs in one transaction that aborts).
- Results are frozen dataclasses. Pure helpers at the bottom (digests, canonical jsonb text) are
  shared by both implementations and by tests.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from .temporal import EventKind

__all__ = [
    "OMITTED",
    "AcceptanceView",
    "CommitResult",
    "CursorOutboxPort",
    "CursorView",
    "EffectiveRow",
    "EventKind",
    "HeadAttestationPort",
    "HeadView",
    "JobQueuePort",
    "JobView",
    "KnownRow",
    "LedgerPort",
    "Observation",
    "OutboxRow",
    "PortError",
    "Scope",
    "check_aware",
    "check_scope_type",
    "event_digest",
    "evidence_digest",
    "jsonb_text",
    "normalize_json",
    "page_digest",
]


class PortError(Exception):
    """A rejected port call. ``code`` is the stable machine-readable SQL error text."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def __reduce__(self):
        # Default Exception pickling replays ``args`` (the joined message) into ``__init__`` and
        # would turn "CODE: detail" into the code. Keep code and detail apart across processes.
        return (type(self), (self.code, self.detail))


class _Omitted:
    """Type of ``OMITTED``: an argument the caller did not pass (SQL ``DEFAULT``), as opposed to None (SQL NULL)."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "OMITTED"

    def __reduce__(self):
        return "OMITTED"


OMITTED = _Omitted()


@dataclass(frozen=True, slots=True)
class Scope:
    tenant_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: UUID
    object_id: str
    revision_id: UUID
    kind: str
    digest: str | None
    source_effective_at: datetime | None
    observed_at: datetime
    recorded_at: datetime
    ingest_seq: int
    supersedes: UUID | None


@dataclass(frozen=True, slots=True)
class KnownRow:
    """One row of ``living.as_known_at`` (head row plus availability/revocation flags)."""
    observation: Observation
    available: bool
    latest_kind: str
    revoked: bool


@dataclass(frozen=True, slots=True)
class EffectiveRow:
    """One row of ``living.as_effective_at``; ``effective_unknown`` flags undated rows."""
    observation: Observation
    effective_unknown: bool
    revoked: bool


@dataclass(frozen=True, slots=True)
class JobView:
    job_id: UUID
    state: str
    lease_owner: str | None
    lease_until: datetime | None
    fence: int
    attempt: int
    max_attempts: int
    next_run_at: datetime
    last_error: str | None
    scope_epoch: int


@dataclass(frozen=True, slots=True)
class CursorView:
    connection_id: str
    cursor_value: str
    version: int
    scope_epoch: int
    last_page_digest: str | None


@dataclass(frozen=True, slots=True)
class CommitResult:
    version: int
    replayed: bool  # True when SQL raised the CURSOR_ALREADY_APPLIED notice (identical replay)


@dataclass(frozen=True, slots=True)
class OutboxRow:
    seq: int
    connection_id: str
    event_id: str
    event_digest: str
    # Excluded from eq/hash so the frozen row is hashable (a dict is not); ``event_digest`` is a
    # SHA-256 over exactly this content, so two rows with equal digests carry equal content.
    content: dict[str, Any] = field(compare=False)
    status: str
    attempts: int
    lease_owner: str | None
    lease_until: datetime | None
    claim_generation: int


@dataclass(frozen=True, slots=True)
class HeadView:
    model_key: str
    revision_id: UUID | None
    version: int


@dataclass(frozen=True, slots=True)
class AcceptanceView:
    acceptance_id: UUID
    model_key: str
    from_version: int
    to_version: int
    accepted_revision: UUID
    approver_subject: str
    independent_evidence_ref: str


@runtime_checkable
class LedgerPort(Protocol):
    """Bitemporal observation ledger (``living.ingest_observation`` / ``as_known_at`` / ``as_effective_at``)."""

    async def now(self) -> datetime:
        """The authoritative store clock (SQL ``clock_timestamp()``); the only legal source of ``k``."""

    async def scope_epoch(self, scope: Scope) -> int: ...

    async def ingest_observation(
        self, actor: str, scope: Scope, observation_id: UUID | None, object_id: str | None,
        revision_id: UUID | None, kind: str | None, digest: str | None,
        source_effective_at: datetime | None, observed_at: datetime | None,
        supersedes: UUID | None = None,
        provenance: dict[str, Any] | None | _Omitted = OMITTED) -> UUID:
        """``provenance`` omitted = SQL default ``{}``; an explicit None is SQL NULL = INVALID_OBSERVATION."""

    async def as_known_at(self, actor: str, scope: Scope, k: datetime) -> tuple[KnownRow, ...]: ...

    async def as_effective_at(self, actor: str, scope: Scope, valid_at: datetime,
                              k: datetime) -> tuple[EffectiveRow, ...]: ...


@runtime_checkable
class JobQueuePort(Protocol):
    """Lease + fence job queue (``enqueue_job`` / ``acquire_job`` / ``renew_lease`` / ``finish_job`` / ``reap_expired_jobs``)."""

    async def enqueue_job(self, actor: str, scope: Scope, job_id: UUID | None, job_kind: str | None,
                          request_digest: str | None, idempotency_key: str | None,
                          payload: dict[str, Any] | None | _Omitted = OMITTED) -> UUID:
        """``payload`` omitted = SQL default ``{}``; an explicit None is SQL NULL = INVALID_JOB."""

    async def acquire_job(self, actor: str, scope: Scope, job_id: UUID | None, worker: str | None,
                          lease_seconds: int | None) -> int:
        """Returns the new fence token."""

    async def renew_lease(self, actor: str, scope: Scope, job_id: UUID | None, worker: str | None,
                          fence: int | None, lease_seconds: int | None) -> datetime: ...

    async def finish_job(self, actor: str, scope: Scope, job_id: UUID | None, worker: str | None,
                         fence: int | None, completed_state: str | None,
                         error: str | None = None) -> None: ...

    async def reap_expired_jobs(self, actor: str, scope: Scope) -> int: ...

    async def get_job(self, actor: str, scope: Scope, job_id: UUID) -> JobView | None: ...


@runtime_checkable
class CursorOutboxPort(Protocol):
    """Cursor CAS with page-replay digest + job fence, and the leased outbox with claim generations."""

    async def create_cursor(self, actor: str, scope: Scope, connection_id: str | None,
                            initial_cursor: str | None) -> int: ...

    async def commit_cursor_page(
        self, actor: str, scope: Scope, connection_id: str | None, job_id: UUID | None,
        worker: str | None, fence: int | None, prior_cursor: str | None,
        prior_version: int | None, expected_epoch: int | None, new_cursor: str | None,
        events: list[dict[str, Any]] | None) -> CommitResult: ...

    async def get_cursor(self, actor: str, scope: Scope, connection_id: str) -> CursorView | None: ...

    async def claim_outbox(self, actor: str, scope: Scope, limit: int | None,
                           lease_seconds: int | None,
                           max_attempts: int | None = 5) -> tuple[OutboxRow, ...]:
        """Claimed rows in ``seq`` order; ``claim_generation`` is the per-claim fence."""

    async def finish_outbox(self, actor: str, scope: Scope, connection_id: str | None,
                            event_id: str | None, generation: int | None, delivered: bool | None,
                            max_attempts: int | None = 5) -> None: ...

    async def list_outbox(self, actor: str, scope: Scope) -> tuple[OutboxRow, ...]: ...


@runtime_checkable
class HeadAttestationPort(Protocol):
    """Accepted heads with expected-version CAS and independent, revocable, expiring attestations."""

    async def create_head(self, actor: str, scope: Scope, model_key: str | None) -> int: ...

    async def promote_head(self, actor: str, scope: Scope, model_key: str | None,
                           expected_version: int | None, new_revision: UUID | None,
                           acceptance_id: UUID | None, evidence_ref: str | None) -> int: ...

    async def record_attestation(
        self, actor: str, scope: Scope, attestation_id: UUID | None, revision_id: UUID | None,
        proposer: str | None, evidence_ref: str | None, evidence_digest: str | None,
        decision: str | None, expires_at: datetime | None) -> UUID: ...

    async def revoke_attestation(self, actor: str, scope: Scope,
                                 attestation_id: UUID | None) -> datetime: ...

    async def set_trusted_reviewer(self, role: str | None, scope: Scope, active: bool | None,
                                   expires_at: datetime | None) -> None:
        """Owner-only administration (``living.set_trusted_reviewer``)."""

    async def define_actor(self, name: str, member_of: tuple[str, ...]) -> None:
        """Test-support directory: create an idempotent NOLOGIN role that is a member of ``member_of``."""

    async def get_head(self, actor: str, scope: Scope, model_key: str) -> HeadView | None: ...

    async def list_acceptances(self, actor: str, scope: Scope) -> tuple[AcceptanceView, ...]: ...


# --------------------------------------------------------------------------- pure helpers
def check_aware(**values: Any) -> None:
    """Port contract: every datetime argument is timezone-aware (naive -> ``NAIVE_DATETIME``).

    Shared by the fake and the SQL adapter so a naive value is a typed rejection on both sides and
    never a TypeError (fake) or a silent local-time reinterpretation (driver).
    """
    for name, value in values.items():
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise PortError("NAIVE_DATETIME", name)


def check_scope_type(scope: Any) -> None:
    """A non-Scope or empty tenant/source is ``INVALID_ARGUMENT`` (SQL ``set_scope`` rejects it first)."""
    if (not isinstance(scope, Scope) or not isinstance(scope.tenant_id, str)
            or not isinstance(scope.source_id, str) or not scope.tenant_id or not scope.source_id):
        raise PortError("INVALID_ARGUMENT", "scope")


def normalize_json(value: Any) -> Any:
    """Strict JSON model of a jsonb argument; returns a deep copy (tuples become lists).

    Allowed: None, bool, int, finite float, str, list/tuple, dict with str keys. Anything else
    (non-str keys, sets, bytes, datetimes, NaN/inf, ...) is ``INVALID_JSON``: ``json.dumps`` would
    either raise a TypeError or silently coerce (``{1: "a"}`` becomes ``{"1": "a"}``).
    """
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or value in (float("inf"), float("-inf")):
            raise PortError("INVALID_JSON", "non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        return [normalize_json(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise PortError("INVALID_JSON", f"non-string key {type(k).__name__}")
            out[k] = normalize_json(v)
        return out
    raise PortError("INVALID_JSON", type(value).__name__)


def _json_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def jsonb_text(value: Any) -> str:
    """PostgreSQL ``jsonb::text`` rendering (keys ordered by UTF-8 length then bytes; ``": "``/``", "``).

    Supports str, int, bool, None, list, dict. Floats are rejected: jsonb numeric normalisation is
    not reproduced here, so a float inside a hashed event would silently diverge from SQL.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _json_str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(jsonb_text(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda k: (len(k.encode("utf-8")), k.encode("utf-8")))
        return "{" + ", ".join(f"{_json_str(k)}: {jsonb_text(value[k])}" for k in keys) + "}"
    raise TypeError(f"UNSUPPORTED_JSONB_VALUE: {type(value).__name__}")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def event_digest(event: dict[str, Any]) -> str:
    """Digest SQL computes for an outbox event: sha256 of ``(event - 'digest')::text``."""
    return _sha256(jsonb_text({k: v for k, v in event.items() if k != "digest"}))


def page_digest(prior_cursor: str, new_cursor: str, events: list[dict[str, Any]]) -> str:
    """Canonical page digest used for replay detection in ``commit_cursor_page``."""
    return _sha256(jsonb_text({"prior": prior_cursor, "new": new_cursor, "events": events}))


def evidence_digest(revision_digest: str, evidence_ref: str) -> str:
    """Digest binding evidence to the exact revision: sha256(revision_digest || ':' || evidence_ref)."""
    return _sha256(f"{revision_digest}:{evidence_ref}")
