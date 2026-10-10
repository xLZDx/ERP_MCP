"""Phase 2 sprint S8 (R2-US-039..041): shared frozen types and fixed vocabularies for the workbench.

Offline, unwired, in-memory. Everything here is a small immutable type or a closed ``StrEnum``:

* ``ReasonCode`` / ``NextAction`` - the fixed outward vocabulary. No caller text ever becomes a code.
* ``SafeError`` - ``(reason_code, next_action, correlation_id)`` and nothing else: no free text, no
  exception object, no foreign source name, no stack text, no secret reference.
* ``ViewerScope`` - who is looking: ``(tenant_id, company_id, scope_epoch)``.
* ``OwnerDirectory`` - injected ``(tenant, company, source) -> owner_id`` table; an unmapped item is
  reported as ``OWNER_UNASSIGNED`` by the caller, never guessed.
* ``AnnotationKind`` - the closed set of reviewer annotation kinds.

Constructors raise ``ValueError`` with a fixed code only for malformed input (the fixed code is the
whole message; the input is never echoed). The ``is_valid_*`` predicates and ``owner_for`` /
``safe_error`` never raise: forged ``object.__new__`` instances, subclasses and lookalike strings
are simply refused. Authority is ``EVALUATION_ONLY``; nothing here can express a verdict.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol

from ._identity import exact_text

__all__ = [
    "AUTHORITY", "DEFAULT_CORRELATION_ID", "NEXT_ACTION_FOR", "OWNERSHIP_KINDS", "AnnotationKind",
    "EntitlementPort", "FakeEntitlements", "FakeOwnership", "NextAction", "OwnerDirectory", "OwnershipPort",
    "ReasonCode", "SafeError", "ViewerScope", "correlation_ok", "is_valid_directory", "is_valid_safe_error",
    "is_valid_scope", "safe_error",
]

AUTHORITY: Final = "EVALUATION_ONLY"
DEFAULT_CORRELATION_ID: Final = "CORR-UNASSIGNED"
_MAX_EPOCH: Final = 2**63 - 1
_CORRELATION: Final = re.compile(r"[A-Za-z0-9._:-]{1,64}")


class ReasonCode(StrEnum):
    # workbench / review
    ORIGINAL_NUMBERS_IMMUTABLE = "ORIGINAL_NUMBERS_IMMUTABLE"
    ORIGINAL_INTACT = "ORIGINAL_INTACT"
    ORIGINAL_TAMPERED = "ORIGINAL_TAMPERED"
    ROW_DETAIL_UNAVAILABLE = "ROW_DETAIL_UNAVAILABLE"
    OWNER_UNASSIGNED = "OWNER_UNASSIGNED"
    DELTA_PRECISION_EXCEEDED = "DELTA_PRECISION_EXCEEDED"
    NO_NEW_EVIDENCE = "NO_NEW_EVIDENCE"
    RERUN_TARGET_STALE = "RERUN_TARGET_STALE"
    RERUN_TARGET_UNKNOWN = "RERUN_TARGET_UNKNOWN"
    NOT_IN_SCOPE = "NOT_IN_SCOPE"
    SCOPE_EPOCH_STALE = "SCOPE_EPOCH_STALE"
    ANNOTATION_INVALID = "ANNOTATION_INVALID"
    INPUT_INVALID = "INPUT_INVALID"
    # timeline / coverage
    EFFECTIVE_UNKNOWN = "EFFECTIVE_UNKNOWN"
    HIDDEN_BY_SCOPE = "HIDDEN_BY_SCOPE"
    SUPERSEDED_BY_RUN = "SUPERSEDED_BY_RUN"
    REVISION_CHANGED = "REVISION_CHANGED"
    ATTESTATION_REVOKED = "ATTESTATION_REVOKED"
    STALE = "STALE"
    SOURCE_PAUSED = "SOURCE_PAUSED"
    NOT_COVERED = "NOT_COVERED"
    UNKNOWN = "UNKNOWN"
    # api
    CSRF_REJECTED = "CSRF_REJECTED"
    SESSION_INVALID = "SESSION_INVALID"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    REPLAYED = "REPLAYED"
    OPERATION_UNCLASSIFIED = "OPERATION_UNCLASSIFIED"
    OPERATION_DENIED = "OPERATION_DENIED"
    PARAMETER_SCHEMA_INVALID = "PARAMETER_SCHEMA_INVALID"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_REFUSED = "INTERNAL_REFUSED"
    # added by the S8 review fix batch
    ORIGINAL_UNVERIFIABLE = "ORIGINAL_UNVERIFIABLE"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"


class NextAction(StrEnum):
    RETRY_LATER = "RETRY_LATER"
    CONTACT_OWNER = "CONTACT_OWNER"
    REAUTHENTICATE = "REAUTHENTICATE"
    REFRESH_PAGE = "REFRESH_PAGE"
    NO_ACTION = "NO_ACTION"


class AnnotationKind(StrEnum):
    NOTE = "NOTE"
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RERUN_REQUESTED = "RERUN_REQUESTED"


_R, _N = ReasonCode, NextAction
NEXT_ACTION_FOR: Final[Mapping[ReasonCode, NextAction]] = MappingProxyType({
    _R.ORIGINAL_NUMBERS_IMMUTABLE: _N.NO_ACTION, _R.ORIGINAL_INTACT: _N.NO_ACTION,
    _R.ORIGINAL_TAMPERED: _N.CONTACT_OWNER, _R.ROW_DETAIL_UNAVAILABLE: _N.NO_ACTION,
    _R.OWNER_UNASSIGNED: _N.CONTACT_OWNER, _R.DELTA_PRECISION_EXCEEDED: _N.CONTACT_OWNER,
    _R.NO_NEW_EVIDENCE: _N.NO_ACTION, _R.RERUN_TARGET_STALE: _N.REFRESH_PAGE,
    _R.RERUN_TARGET_UNKNOWN: _N.REFRESH_PAGE, _R.NOT_IN_SCOPE: _N.CONTACT_OWNER,
    _R.SCOPE_EPOCH_STALE: _N.REFRESH_PAGE, _R.ANNOTATION_INVALID: _N.NO_ACTION,
    _R.INPUT_INVALID: _N.NO_ACTION, _R.EFFECTIVE_UNKNOWN: _N.NO_ACTION,
    _R.HIDDEN_BY_SCOPE: _N.NO_ACTION, _R.SUPERSEDED_BY_RUN: _N.NO_ACTION,
    _R.REVISION_CHANGED: _N.REFRESH_PAGE, _R.ATTESTATION_REVOKED: _N.CONTACT_OWNER,
    _R.STALE: _N.REFRESH_PAGE, _R.SOURCE_PAUSED: _N.CONTACT_OWNER, _R.NOT_COVERED: _N.CONTACT_OWNER,
    _R.UNKNOWN: _N.CONTACT_OWNER, _R.CSRF_REJECTED: _N.REFRESH_PAGE,
    _R.SESSION_INVALID: _N.REAUTHENTICATE, _R.IDEMPOTENCY_KEY_REQUIRED: _N.NO_ACTION,
    _R.IDEMPOTENCY_CONFLICT: _N.NO_ACTION, _R.REPLAYED: _N.NO_ACTION,
    _R.OPERATION_UNCLASSIFIED: _N.CONTACT_OWNER, _R.OPERATION_DENIED: _N.CONTACT_OWNER,
    _R.PARAMETER_SCHEMA_INVALID: _N.NO_ACTION, _R.NOT_FOUND: _N.NO_ACTION,
    _R.RATE_LIMITED: _N.RETRY_LATER, _R.INTERNAL_REFUSED: _N.RETRY_LATER,
    _R.ORIGINAL_UNVERIFIABLE: _N.CONTACT_OWNER, _R.DEPENDENCY_FAILED: _N.RETRY_LATER,
})
if set(NEXT_ACTION_FOR) != set(ReasonCode):  # import-time guard: every code needs a fixed next action
    raise RuntimeError("NEXT_ACTION_FOR_INCOMPLETE")
_SUCCESS_LIKE: Final = frozenset({ReasonCode.ORIGINAL_INTACT, ReasonCode.REPLAYED})


def correlation_ok(value: object) -> bool:
    """True only for an exact ``str`` correlation id of the fixed shape (a lying-``__eq__`` subclass is refused)."""
    return type(value) is str and _CORRELATION.fullmatch(value) is not None


_correlation_ok = correlation_ok


@dataclass(frozen=True, slots=True)
class SafeError:
    """A refusal as the outside world may see it: two fixed enums and an injected opaque id."""

    reason_code: ReasonCode
    next_action: NextAction
    correlation_id: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        if (type(self.reason_code) is not ReasonCode or type(self.next_action) is not NextAction
                or not correlation_ok(self.correlation_id) or type(self.authority) is not str
                or self.authority != AUTHORITY):
            raise ValueError("SAFE_ERROR_INVALID")


def safe_error(code: object, correlation_id: object = DEFAULT_CORRELATION_ID) -> SafeError:
    """Build a ``SafeError`` for a fixed code; unusable input degrades to fixed values, never raises.

    Success-like codes (``ORIGINAL_INTACT``, ``REPLAYED``) are not errors: they degrade to
    ``INTERNAL_REFUSED`` so a caller bug can never present a success as a refusal.
    """
    reason = code if type(code) is ReasonCode else ReasonCode.INPUT_INVALID
    if reason in _SUCCESS_LIKE:
        reason = ReasonCode.INTERNAL_REFUSED
    corr = correlation_id if correlation_ok(correlation_id) else DEFAULT_CORRELATION_ID
    return SafeError(reason, NEXT_ACTION_FOR[reason], corr)  # type: ignore[arg-type]


def is_valid_safe_error(value: object) -> bool:
    if type(value) is not SafeError:
        return False
    try:
        return (type(value.reason_code) is ReasonCode and type(value.next_action) is NextAction
                and correlation_ok(value.correlation_id) and type(value.authority) is str
                and value.authority == AUTHORITY)
    except AttributeError:  # forged object.__new__ instance: slots never set
        return False


def _text_ok(value: object) -> bool:
    return type(value) is str and value != "" and exact_text(value) == value


@dataclass(frozen=True, slots=True)
class ViewerScope:
    tenant_id: str
    company_id: str
    scope_epoch: int

    def __post_init__(self) -> None:
        if (not _text_ok(self.tenant_id) or not _text_ok(self.company_id)
                or type(self.scope_epoch) is not int or not 0 <= self.scope_epoch <= _MAX_EPOCH):
            raise ValueError("VIEWER_SCOPE_INVALID")


def is_valid_scope(value: object) -> bool:
    if type(value) is not ViewerScope:
        return False
    try:
        return (_text_ok(value.tenant_id) and _text_ok(value.company_id)
                and type(value.scope_epoch) is int and 0 <= value.scope_epoch <= _MAX_EPOCH)
    except AttributeError:
        return False


_MAX_DIRECTORY_ENTRIES: Final = 10_000


def _entries_ok(entries: object) -> bool:
    if type(entries) is not tuple or len(entries) > _MAX_DIRECTORY_ENTRIES:
        return False
    seen: set[tuple[str, str, str]] = set()
    for item in entries:
        if type(item) is not tuple or len(item) != 4 or not all(_text_ok(part) for part in item):
            return False
        key = item[:3]
        if key in seen:
            return False
        seen.add(key)
    return True


@dataclass(frozen=True, slots=True)
class OwnerDirectory:
    """Immutable ``(tenant, company, source) -> owner_id`` table; entries are 4-tuples of exact text.

    The lookup index is built once at construction; ``repr`` never shows the table.
    """

    entries: tuple[tuple[str, str, str, str], ...] = field(repr=False)
    _index: Mapping[tuple[str, str, str], str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _entries_ok(self.entries):
            raise ValueError("OWNER_DIRECTORY_INVALID")
        object.__setattr__(self, "_index", MappingProxyType({e[:3]: e[3] for e in self.entries}))

    def __repr__(self) -> str:
        return "OwnerDirectory(<redacted>)"

    @classmethod
    def from_mapping(cls, mapping: object) -> OwnerDirectory:
        if type(mapping) not in (dict, MappingProxyType):
            raise ValueError("OWNER_DIRECTORY_INVALID")
        try:
            rows = []
            for key, owner in mapping.items():  # type: ignore[attr-defined]
                if type(key) is not tuple or len(key) != 3:
                    raise ValueError("OWNER_DIRECTORY_INVALID")
                rows.append((*key, owner))
                if len(rows) > _MAX_DIRECTORY_ENTRIES:
                    raise ValueError("OWNER_DIRECTORY_INVALID")
            rows.sort()
            return cls(tuple(rows))
        except Exception:  # noqa: BLE001 - hostile Mapping / __lt__: only the fixed code escapes
            raise ValueError("OWNER_DIRECTORY_INVALID") from None

    def owner_for(self, tenant_id: object, company_id: object, source_id: object) -> str | None:
        """The mapped owner id, or None when unmapped or anything is unusable (never a guess)."""
        if type(self) is not OwnerDirectory:
            return None
        if not (_text_ok(tenant_id) and _text_ok(company_id) and _text_ok(source_id)):
            return None
        try:
            index = self._index
        except AttributeError:  # forged object.__new__ instance
            return None
        if type(index) is not MappingProxyType:
            return None
        return index.get((tenant_id, company_id, source_id))  # type: ignore[arg-type]


def is_valid_directory(value: object) -> bool:
    if type(value) is not OwnerDirectory:
        return False
    try:
        return _entries_ok(value.entries) and type(value._index) is MappingProxyType
    except AttributeError:
        return False


# --------------------------------------------------------------------------------------------------
# injected ports: company ownership of workbench references and actor entitlement

OWNERSHIP_KINDS: Final = frozenset({"comparison_key", "run_id", "snapshot_id", "source_id", "report_id"})
_MAX_PORT_ROWS: Final = 100_000


class OwnershipPort(Protocol):
    """Does ``company_id`` (of ``tenant_id``) own the referenced object? Unknown and foreign read the same."""

    def owns(self, tenant_id: str, company_id: str, kind: str, ref: str) -> bool: ...


class EntitlementPort(Protocol):
    """Is ``actor_id`` entitled to act for ``company_id`` of ``tenant_id``?"""

    def entitled(self, tenant_id: str, actor_id: str, company_id: str) -> bool: ...


class FakeOwnership:
    """In-memory ``OwnershipPort``: exact types only, never raises, bounded, anything invalid is False."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: set[tuple[str, str, str, str]] = set()

    def add(self, tenant_id: object, company_id: object, kind: object, ref: object) -> None:
        if not (_text_ok(tenant_id) and _text_ok(company_id) and _text_ok(ref)
                and type(kind) is str and kind in OWNERSHIP_KINDS):
            return
        with self._lock:
            if len(self._rows) < _MAX_PORT_ROWS:
                self._rows.add((tenant_id, company_id, kind, ref))  # type: ignore[arg-type]

    def owns(self, tenant_id: object, company_id: object, kind: object, ref: object) -> bool:
        try:
            if not (_text_ok(tenant_id) and _text_ok(company_id) and _text_ok(ref)
                    and type(kind) is str and kind in OWNERSHIP_KINDS):
                return False
            with self._lock:
                return (tenant_id, company_id, kind, ref) in self._rows
        except Exception:  # noqa: BLE001 - a port answer is a bool, never an exception
            return False


class FakeEntitlements:
    """In-memory ``EntitlementPort`` with the same properties as ``FakeOwnership``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: set[tuple[str, str, str]] = set()

    def grant(self, tenant_id: object, actor_id: object, company_id: object) -> None:
        if not (_text_ok(tenant_id) and _text_ok(actor_id) and _text_ok(company_id)):
            return
        with self._lock:
            if len(self._rows) < _MAX_PORT_ROWS:
                self._rows.add((tenant_id, actor_id, company_id))  # type: ignore[arg-type]

    def entitled(self, tenant_id: object, actor_id: object, company_id: object) -> bool:
        try:
            if not (_text_ok(tenant_id) and _text_ok(actor_id) and _text_ok(company_id)):
                return False
            with self._lock:
                return (tenant_id, actor_id, company_id) in self._rows
        except Exception:  # noqa: BLE001 - a port answer is a bool, never an exception
            return False
