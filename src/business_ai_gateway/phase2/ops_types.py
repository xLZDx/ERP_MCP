"""Phase 2 sprint S9 (R2-US-043..046): shared ops vocabulary and small generic helpers.

Offline, unwired, in-memory. Written first and imported READ-ONLY by every other S9 module. Public names:

Vocabulary
* ``OpsReason`` - the closed ``StrEnum`` of every S9 outward code (shared, capacity, faults/alerts,
  release, retention/restore/export, readiness). No caller text ever becomes a code.
* ``OPS_NEXT_ACTION`` / ``next_action_for`` - fixed ``NextAction`` (S8 enum) per code. An import-time
  guard raises ``RuntimeError("OPS_NEXT_ACTION_INCOMPLETE")`` if any code has none.
* ``AUTHORITY`` (= ``EVALUATION_ONLY``), ``Basis`` (``SCRIPTED_OFFLINE_FIXTURE`` / ``OPERATOR_REFERENCE``).

Refusals and scope
* ``OpsRefusal(reason, next_action, correlation_id)`` - frozen; ``ops_refusal(reason, ids)`` builds one
  with an id drawn from the injected source (never from input; never raises); ``is_valid_refusal``.
* ``OpsScope(tenant_id, company_id, actor_id)`` - exact-type validated, ``repr`` redacted;
  ``is_valid_scope`` (forged ``object.__new__`` instances are simply invalid).
* ``check_scope_order(scope, refs, ownership, entitlement, ids, quota=None)`` - the fixed order
  structure -> entitlement -> ownership of EVERY referenced object -> quota. Returns ``None`` or an
  ``OpsRefusal``. Foreign and unknown references give the identical refusal (``NOT_FOUND``) and the
  identical port-call pattern (every reference is asked, none short-circuits).
* ``OperatorAuthorityPort`` / ``FakeOperatorAuthority`` - platform-level ``authorized(actor_id, action)``.

Per-tenant storage
* ``TenantBoundedMap(per_tenant_cap, ids)`` - thread-safe, one counter and cap per tenant; ``insert``,
  ``replace``, ``get``, ``remove``, ``count``, ``has_room``, ``items``. Overflow is an explicit
  ``QUOTA_EXCEEDED`` refusal for THAT tenant only; the map never evicts anything on its own, so an
  undelivered/unfinished record disappears only through an explicit ``remove`` by its owner. Check and
  insert happen inside one lock critical section. Callers must run ``check_scope_order`` first: tenant
  ids that reach the map are then entitled ones. Single-process only (no cross-process atomicity).

* ``TenantSlotCounter(per_tenant_limit)`` - atomic per-``(tenant, key)`` concurrency counter
  (``try_acquire`` / ``release`` / ``active``); the sub-share building block over a shared budget.

Exact-type helpers (never raise): ``is_exact_str``, ``is_identity_text``, ``is_exact_int`` (bool is
not an int), ``is_exact_decimal`` (finite, bounded exponent), ``is_aware_datetime``, ``is_digest``.
Re-exported for convenience: ``CorrelationSource``, ``FakeCorrelationSource``, ``OwnershipPort``,
``EntitlementPort``, ``FakeOwnership``, ``FakeEntitlements``.

Authority is ``EVALUATION_ONLY``; nothing here can express a verdict such as "capacity proven".
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol

from ._identity import exact_text
from .safe_errors import CorrelationSource, FakeCorrelationSource
from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    OWNERSHIP_KINDS,
    EntitlementPort,
    FakeEntitlements,
    FakeOwnership,
    NextAction,
    OwnershipPort,
    correlation_ok,
)

__all__ = [
    "AUTHORITY", "MAX_TENANT_CAP", "OPS_NEXT_ACTION", "Basis", "CorrelationSource", "EntitlementPort",
    "FakeCorrelationSource", "FakeEntitlements", "FakeOperatorAuthority", "FakeOwnership",
    "OperatorAuthorityPort", "OpsReason", "OpsRefusal", "OpsScope", "OwnershipPort", "TenantBoundedMap",
    "TenantSlotCounter", "check_scope_order", "is_aware_datetime", "is_digest", "is_exact_decimal", "is_exact_int",
    "is_exact_str", "is_identity_text", "is_valid_refusal", "is_valid_scope", "next_action_for",
    "ops_refusal",
]

MAX_TENANT_CAP: Final = 1_000_000
_MAX_REFS: Final = 64
_MAX_AUTH_ROWS: Final = 100_000
_DIGEST: Final = re.compile(r"[a-f0-9]{64}")
_MAX_DECIMAL_EXPONENT: Final = 100


class OpsReason(StrEnum):
    # shared
    INPUT_INVALID = "INPUT_INVALID"
    NOT_FOUND = "NOT_FOUND"
    NOT_ENTITLED = "NOT_ENTITLED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    INTERNAL_REFUSED = "INTERNAL_REFUSED"
    HIDDEN_BY_SCOPE = "HIDDEN_BY_SCOPE"
    BASIS_NOT_REAL_MEASUREMENT = "BASIS_NOT_REAL_MEASUREMENT"
    # capacity
    SESSIONS_NOT_ACTIVE_CLIENTS = "SESSIONS_NOT_ACTIVE_CLIENTS"
    GRID_CELL_INCONSISTENT = "GRID_CELL_INCONSISTENT"
    BACKEND_COUNT_MISSING = "BACKEND_COUNT_MISSING"
    CONFIG_LIMIT_NOT_CAPACITY = "CONFIG_LIMIT_NOT_CAPACITY"
    REFUSALS_DOMINATE = "REFUSALS_DOMINATE"
    UNRELIABLE_REFUSALS = "UNRELIABLE_REFUSALS"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    BASELINE_INVALID = "BASELINE_INVALID"
    WITHIN_TARGET = "WITHIN_TARGET"
    EXCEEDS_TARGET = "EXCEEDS_TARGET"
    BACKGROUND_STARVED = "BACKGROUND_STARVED"
    BACKEND_BUDGET_EXCEEDED = "BACKEND_BUDGET_EXCEEDED"
    TENANT_SHARE_EXCEEDED = "TENANT_SHARE_EXCEEDED"
    # faults / alerts
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    AUDIT_COMPLETION_PENDING = "AUDIT_COMPLETION_PENDING"
    EFFECT_FAILED = "EFFECT_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    EVENT_DIGEST_CONFLICT = "EVENT_DIGEST_CONFLICT"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    STALE_CLAIM = "STALE_CLAIM"
    DELIVERY_FAILED_FINAL = "DELIVERY_FAILED_FINAL"
    ALERT_FIRED = "ALERT_FIRED"
    ALERT_RECOVERED = "ALERT_RECOVERED"
    NO_DATA = "NO_DATA"
    ALERT_DELIVERY_FAILED = "ALERT_DELIVERY_FAILED"
    # release
    ADDITIVE = "ADDITIVE"
    SWITCH_ONLY = "SWITCH_ONLY"
    CONTRACT = "CONTRACT"
    DESTRUCTIVE = "DESTRUCTIVE"
    UNCLASSIFIED = "UNCLASSIFIED"
    R1_UNCHANGED = "R1_UNCHANGED"
    R1_REGRESSION = "R1_REGRESSION"
    SHADOW_DIVERGENCE = "SHADOW_DIVERGENCE"
    SHADOW_INCOMPLETE = "SHADOW_INCOMPLETE"
    REHEARSAL_REQUIRES_UNMET = "REHEARSAL_REQUIRES_UNMET"
    ROLLBACK_DESTRUCTIVE_DENIED = "ROLLBACK_DESTRUCTIVE_DENIED"
    ROLLBACK_HEAD_INCOMPATIBLE = "ROLLBACK_HEAD_INCOMPATIBLE"
    ROLLBACK_WINDOW_OPEN = "ROLLBACK_WINDOW_OPEN"
    CONTRACT_NOT_ALLOWED = "CONTRACT_NOT_ALLOWED"
    RESURRECTION_BLOCKED = "RESURRECTION_BLOCKED"
    # retention / restore / export
    RESTORE_COUNT_MISMATCH = "RESTORE_COUNT_MISMATCH"
    RESTORE_DIGEST_MISMATCH = "RESTORE_DIGEST_MISMATCH"
    RESTORE_FK_ORPHAN = "RESTORE_FK_ORPHAN"
    RESTORE_HEAD_MISMATCH = "RESTORE_HEAD_MISMATCH"
    RESTORE_SEQUENCE_GAP = "RESTORE_SEQUENCE_GAP"
    RESTORE_ATTESTATION_STALE = "RESTORE_ATTESTATION_STALE"
    RESTORE_SCOPE_FOREIGN = "RESTORE_SCOPE_FOREIGN"
    RESTORE_INCOMPLETE = "RESTORE_INCOMPLETE"
    COLUMN_UNCLASSIFIED = "COLUMN_UNCLASSIFIED"
    CELL_NEUTRALIZED = "CELL_NEUTRALIZED"
    VALUE_DENIED = "VALUE_DENIED"
    EXPORT_LIMIT_EXCEEDED = "EXPORT_LIMIT_EXCEEDED"
    HOLD_ACTIVE = "HOLD_ACTIVE"
    RETENTION_NOT_ELAPSED = "RETENTION_NOT_ELAPSED"
    APPROVAL_MISSING = "APPROVAL_MISSING"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_DIGEST_MISMATCH = "APPROVAL_DIGEST_MISMATCH"
    SELF_APPROVAL = "SELF_APPROVAL"
    OBJECT_NOT_OWNED = "OBJECT_NOT_OWNED"
    DELETION_ALLOWED_PLAN = "DELETION_ALLOWED_PLAN"
    # readiness
    NOT_RUN = "NOT_RUN"
    EVIDENCE_RECEIVED_UNVERIFIED = "EVIDENCE_RECEIVED_UNVERIFIED"


class Basis(StrEnum):
    """Where a number came from. There is deliberately no ``PROVEN`` member."""

    SCRIPTED_OFFLINE_FIXTURE = "SCRIPTED_OFFLINE_FIXTURE"
    OPERATOR_REFERENCE = "OPERATOR_REFERENCE"


_R, _N = OpsReason, NextAction
_NO, _OWNER, _LATER = _N.NO_ACTION, _N.CONTACT_OWNER, _N.RETRY_LATER
OPS_NEXT_ACTION: Final[Mapping[OpsReason, NextAction]] = MappingProxyType({
    # shared
    _R.INPUT_INVALID: _NO, _R.NOT_FOUND: _NO, _R.NOT_ENTITLED: _OWNER, _R.NOT_AUTHORIZED: _OWNER,
    _R.QUOTA_EXCEEDED: _LATER, _R.DEPENDENCY_FAILED: _LATER, _R.INTERNAL_REFUSED: _LATER,
    _R.HIDDEN_BY_SCOPE: _NO, _R.BASIS_NOT_REAL_MEASUREMENT: _NO,
    # capacity
    _R.SESSIONS_NOT_ACTIVE_CLIENTS: _NO, _R.GRID_CELL_INCONSISTENT: _NO, _R.BACKEND_COUNT_MISSING: _NO,
    _R.CONFIG_LIMIT_NOT_CAPACITY: _NO, _R.REFUSALS_DOMINATE: _OWNER, _R.UNRELIABLE_REFUSALS: _OWNER,
    _R.INSUFFICIENT_SAMPLES: _LATER, _R.BASELINE_INVALID: _NO, _R.WITHIN_TARGET: _NO,
    _R.EXCEEDS_TARGET: _OWNER, _R.BACKGROUND_STARVED: _NO, _R.BACKEND_BUDGET_EXCEEDED: _LATER,
    _R.TENANT_SHARE_EXCEEDED: _LATER,
    # faults / alerts
    _R.AUDIT_UNAVAILABLE: _LATER, _R.AUDIT_COMPLETION_PENDING: _OWNER, _R.EFFECT_FAILED: _OWNER,
    _R.RATE_LIMITED: _LATER, _R.NETWORK_FAILURE: _LATER, _R.EVENT_DIGEST_CONFLICT: _OWNER,
    _R.DUPLICATE_SUPPRESSED: _NO, _R.STALE_CLAIM: _LATER, _R.DELIVERY_FAILED_FINAL: _OWNER,
    _R.ALERT_FIRED: _OWNER, _R.ALERT_RECOVERED: _NO, _R.NO_DATA: _OWNER, _R.ALERT_DELIVERY_FAILED: _LATER,
    # release
    _R.ADDITIVE: _NO, _R.SWITCH_ONLY: _NO, _R.CONTRACT: _OWNER, _R.DESTRUCTIVE: _OWNER,
    _R.UNCLASSIFIED: _OWNER, _R.R1_UNCHANGED: _NO, _R.R1_REGRESSION: _OWNER, _R.SHADOW_DIVERGENCE: _OWNER,
    _R.SHADOW_INCOMPLETE: _OWNER, _R.REHEARSAL_REQUIRES_UNMET: _OWNER,
    _R.ROLLBACK_DESTRUCTIVE_DENIED: _OWNER, _R.ROLLBACK_HEAD_INCOMPATIBLE: _OWNER,
    _R.ROLLBACK_WINDOW_OPEN: _LATER, _R.CONTRACT_NOT_ALLOWED: _OWNER, _R.RESURRECTION_BLOCKED: _NO,
    # retention / restore / export
    _R.RESTORE_COUNT_MISMATCH: _OWNER, _R.RESTORE_DIGEST_MISMATCH: _OWNER, _R.RESTORE_FK_ORPHAN: _OWNER,
    _R.RESTORE_HEAD_MISMATCH: _OWNER, _R.RESTORE_SEQUENCE_GAP: _OWNER, _R.RESTORE_ATTESTATION_STALE: _OWNER,
    _R.RESTORE_SCOPE_FOREIGN: _OWNER, _R.RESTORE_INCOMPLETE: _OWNER, _R.COLUMN_UNCLASSIFIED: _OWNER,
    _R.CELL_NEUTRALIZED: _NO, _R.VALUE_DENIED: _NO, _R.EXPORT_LIMIT_EXCEEDED: _NO, _R.HOLD_ACTIVE: _OWNER,
    _R.RETENTION_NOT_ELAPSED: _NO, _R.APPROVAL_MISSING: _OWNER, _R.APPROVAL_EXPIRED: _OWNER,
    _R.APPROVAL_DIGEST_MISMATCH: _OWNER, _R.SELF_APPROVAL: _OWNER, _R.OBJECT_NOT_OWNED: _NO,
    _R.DELETION_ALLOWED_PLAN: _NO,
    # readiness
    _R.NOT_RUN: _NO, _R.EVIDENCE_RECEIVED_UNVERIFIED: _NO,
})
if set(OPS_NEXT_ACTION) != set(OpsReason):  # import-time guard: every code needs a fixed next action
    raise RuntimeError("OPS_NEXT_ACTION_INCOMPLETE")


def next_action_for(reason: object) -> NextAction:
    """The fixed next action for a code; anything that is not an exact ``OpsReason`` maps to ``NO_ACTION``."""
    if type(reason) is not OpsReason:
        return NextAction.NO_ACTION
    return OPS_NEXT_ACTION[reason]


# --------------------------------------------------------------------------------------------------
# exact-type helpers (never raise)

def is_exact_str(value: object, *, max_len: int = 256, allow_empty: bool = False) -> bool:
    """Exactly ``str`` (no subclass), within the length bound, no NUL character."""
    return (type(value) is str and (allow_empty or value != "") and len(value) <= max_len
            and "\x00" not in value)


def is_identity_text(value: object) -> bool:
    """Exact ``str`` that survives ``exact_text`` unchanged (no control/zero-width/format characters)."""
    return type(value) is str and value != "" and exact_text(value) == value


def is_exact_int(value: object, lo: int = -(2**63), hi: int = 2**63 - 1) -> bool:
    """Exactly ``int`` (``bool`` and subclasses refused) within ``[lo, hi]``."""
    return type(value) is int and lo <= value <= hi


def is_exact_decimal(value: object) -> bool:
    """Exactly ``Decimal``, finite (no NaN/Infinity) and with a bounded exponent; subclasses refused."""
    if type(value) is not Decimal:
        return False
    try:
        return value.is_finite() and abs(value.adjusted()) <= _MAX_DECIMAL_EXPONENT
    except Exception:  # noqa: BLE001 - hostile state: simply invalid
        return False


def is_aware_datetime(value: object) -> bool:
    """Exactly ``datetime`` with a usable UTC offset (naive values and subclasses refused)."""
    if type(value) is not datetime:
        return False
    try:
        return value.tzinfo is not None and value.utcoffset() is not None
    except Exception:  # noqa: BLE001
        return False


def is_digest(value: object) -> bool:
    """Exact ``str`` holding a lower-case sha256 hex digest."""
    return type(value) is str and _DIGEST.fullmatch(value) is not None


# --------------------------------------------------------------------------------------------------
# refusals

@dataclass(frozen=True, slots=True)
class OpsRefusal:
    """A refusal as the outside world may see it: two fixed enums and an injected opaque id."""

    reason: OpsReason
    next_action: NextAction
    correlation_id: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        if (type(self.reason) is not OpsReason or type(self.next_action) is not NextAction
                or self.next_action is not OPS_NEXT_ACTION[self.reason]
                or not correlation_ok(self.correlation_id) or type(self.authority) is not str
                or self.authority != AUTHORITY):
            raise ValueError("OPS_REFUSAL_INVALID")


def is_valid_refusal(value: object) -> bool:
    if type(value) is not OpsRefusal:
        return False
    try:
        return (type(value.reason) is OpsReason and type(value.next_action) is NextAction
                and value.next_action is OPS_NEXT_ACTION[value.reason]
                and correlation_ok(value.correlation_id) and type(value.authority) is str
                and value.authority == AUTHORITY)
    except AttributeError:  # forged object.__new__ instance: slots never set
        return False


def ops_refusal(reason: object, correlation_source: object) -> OpsRefusal:
    """An ``OpsRefusal`` for ``reason`` with an id from the injected source; never raises, never echoes.

    A non-``OpsReason`` degrades to ``INPUT_INVALID``; a failing/hostile source degrades to the fixed
    default id. The carrier accepts any code (verdict-style codes included); callers decide which are errors.
    """
    code = reason if type(reason) is OpsReason else OpsReason.INPUT_INVALID
    try:
        corr = correlation_source.next_id()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a broken source must not turn a refusal into a crash
        corr = DEFAULT_CORRELATION_ID
    if not correlation_ok(corr):
        corr = DEFAULT_CORRELATION_ID
    return OpsRefusal(code, OPS_NEXT_ACTION[code], corr)


# --------------------------------------------------------------------------------------------------
# scope and the fixed check order

@dataclass(frozen=True, slots=True)
class OpsScope:
    """Who is acting: ``(tenant_id, company_id, actor_id)``, all exact identity text. ``repr`` is redacted."""

    tenant_id: str
    company_id: str
    actor_id: str

    def __post_init__(self) -> None:
        if not (is_identity_text(self.tenant_id) and is_identity_text(self.company_id)
                and is_identity_text(self.actor_id)):
            raise ValueError("OPS_SCOPE_INVALID")

    def __repr__(self) -> str:
        return "OpsScope(<redacted>)"


def is_valid_scope(value: object) -> bool:
    if type(value) is not OpsScope:
        return False
    try:
        return (is_identity_text(value.tenant_id) and is_identity_text(value.company_id)
                and is_identity_text(value.actor_id))
    except AttributeError:
        return False


def _snapshot_refs(refs: object) -> tuple[tuple[str, str], ...] | None:
    """One-time copy of ``refs``: a list/tuple of ``(kind, ref)`` exact-text pairs, or ``None``."""
    if type(refs) not in (tuple, list):
        return None
    try:
        if len(refs) > _MAX_REFS:  # type: ignore[arg-type]
            return None
        snap = tuple(refs)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None
    out: list[tuple[str, str]] = []
    for item in snap:
        if type(item) is not tuple or len(item) != 2:
            return None
        kind, ref = item
        if type(kind) is not str or kind not in OWNERSHIP_KINDS or not is_identity_text(ref):
            return None
        out.append((kind, ref))
    return tuple(out)


def check_scope_order(scope: object, refs: object, ownership: object, entitlement: object, ids: object,
                      quota: Callable[[], bool] | None = None) -> OpsRefusal | None:
    """Fixed order: structure -> entitlement -> ownership of EVERY reference -> quota. ``None`` = all passed.

    * structure: valid ``OpsScope``; ``refs`` is a list/tuple of ``(kind, ref)`` with ``kind`` in the S8
      ``OWNERSHIP_KINDS``; ``refs`` is copied once. Failure: ``INPUT_INVALID``.
    * entitlement: ``entitlement.entitled(tenant, actor, company)`` must be exactly ``True``
      (``NOT_ENTITLED`` otherwise) - asked BEFORE ownership, so an unentitled actor learns nothing.
    * ownership: ``ownership.owns(tenant, company, kind, ref)`` is asked for EVERY reference, in order,
      without short-circuit; any answer other than exactly ``True`` gives ``NOT_FOUND``. Foreign and
      unknown references are therefore indistinguishable (same reason, same fields, same port calls).
    * quota: optional zero-argument callable that must return exactly ``True`` (``QUOTA_EXCEEDED``).
    A port that raises gives ``DEPENDENCY_FAILED``; no exception escapes and no input is echoed.
    """
    if not is_valid_scope(scope):
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    snap = _snapshot_refs(refs)
    if snap is None:
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    tenant, company, actor = scope.tenant_id, scope.company_id, scope.actor_id  # type: ignore[attr-defined]
    try:
        entitled = entitlement.entitled(tenant, actor, company)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
    if entitled is not True:
        return ops_refusal(OpsReason.NOT_ENTITLED, ids)
    found = True
    for kind, ref in snap:
        try:
            owned = ownership.owns(tenant, company, kind, ref)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
        if owned is not True:
            found = False
    if not found:
        return ops_refusal(OpsReason.NOT_FOUND, ids)
    if quota is not None:
        try:
            room = quota()
        except Exception:  # noqa: BLE001
            return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
        if room is not True:
            return ops_refusal(OpsReason.QUOTA_EXCEEDED, ids)
    return None


# --------------------------------------------------------------------------------------------------
# platform-level operator authority

class OperatorAuthorityPort(Protocol):
    """Is ``actor_id`` allowed to perform the platform-level ``action``? Not tenant data."""

    def authorized(self, actor_id: str, action: str) -> bool: ...


class FakeOperatorAuthority:
    """In-memory ``OperatorAuthorityPort``: allow/deny table, deny wins, anything invalid is False."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._allow: set[tuple[str, str]] = set()
        self._deny: set[tuple[str, str]] = set()

    def allow(self, actor_id: object, action: object) -> None:
        if is_identity_text(actor_id) and is_identity_text(action):
            with self._lock:
                if len(self._allow) < _MAX_AUTH_ROWS:
                    self._allow.add((actor_id, action))  # type: ignore[arg-type]

    def deny(self, actor_id: object, action: object) -> None:
        if is_identity_text(actor_id) and is_identity_text(action):
            with self._lock:
                if len(self._deny) < _MAX_AUTH_ROWS:
                    self._deny.add((actor_id, action))  # type: ignore[arg-type]

    def authorized(self, actor_id: object, action: object) -> bool:
        try:
            if not (is_identity_text(actor_id) and is_identity_text(action)):
                return False
            key = (actor_id, action)
            with self._lock:
                return key in self._allow and key not in self._deny
        except Exception:  # noqa: BLE001 - a port answer is a bool, never an exception
            return False


# --------------------------------------------------------------------------------------------------
# per-tenant bounded store

class TenantBoundedMap:
    """Thread-safe store with an independent counter and cap per tenant.

    * ``insert(tenant, key, value)``: add a NEW record. ``QUOTA_EXCEEDED`` when that tenant is at its cap,
      ``DUPLICATE_SUPPRESSED`` when the key already exists (the stored value is never replaced),
      ``INPUT_INVALID`` for unusable tenant/key. Returns ``None`` on success.
    * ``replace(tenant, key, value)``: change an EXISTING record (``NOT_FOUND`` if absent); never grows.
    * ``get`` / ``items`` / ``count`` / ``has_room`` / ``remove`` as named; ``items`` is a copy.
    Nothing is ever evicted implicitly: only the owner's explicit ``remove`` frees a slot. One tenant being
    full has no effect on any other tenant and the refusal names no other tenant. Values are stored by
    reference and are opaque to the map. Tenants with no records hold no memory.
    """

    def __init__(self, per_tenant_cap: object, ids: object) -> None:
        if not is_exact_int(per_tenant_cap, 1, MAX_TENANT_CAP):
            raise ValueError("TENANT_CAP_INVALID")
        self._cap: int = per_tenant_cap  # type: ignore[assignment]
        self._ids = ids
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, object]] = {}

    def __repr__(self) -> str:
        return "TenantBoundedMap(<redacted>)"

    def _usable(self, tenant_id: object, key: object) -> bool:
        return is_identity_text(tenant_id) and is_identity_text(key)

    def insert(self, tenant_id: object, key: object, value: object) -> OpsRefusal | None:
        if not self._usable(tenant_id, key):
            return ops_refusal(OpsReason.INPUT_INVALID, self._ids)
        reason: OpsReason | None = None
        with self._lock:
            bucket = self._data.get(tenant_id)  # type: ignore[arg-type]
            if bucket is not None and key in bucket:
                reason = OpsReason.DUPLICATE_SUPPRESSED
            elif bucket is not None and len(bucket) >= self._cap:
                reason = OpsReason.QUOTA_EXCEEDED
            else:
                if bucket is None:
                    bucket = self._data[tenant_id] = {}  # type: ignore[index]
                bucket[key] = value  # type: ignore[index]
        return None if reason is None else ops_refusal(reason, self._ids)

    def replace(self, tenant_id: object, key: object, value: object) -> OpsRefusal | None:
        if not self._usable(tenant_id, key):
            return ops_refusal(OpsReason.INPUT_INVALID, self._ids)
        with self._lock:
            bucket = self._data.get(tenant_id)  # type: ignore[arg-type]
            if bucket is not None and key in bucket:
                bucket[key] = value  # type: ignore[index]
                return None
        return ops_refusal(OpsReason.NOT_FOUND, self._ids)

    def get(self, tenant_id: object, key: object, default: object = None) -> object:
        if not self._usable(tenant_id, key):
            return default
        with self._lock:
            bucket = self._data.get(tenant_id)  # type: ignore[arg-type]
            return default if bucket is None else bucket.get(key, default)  # type: ignore[arg-type]

    def remove(self, tenant_id: object, key: object) -> bool:
        if not self._usable(tenant_id, key):
            return False
        with self._lock:
            bucket = self._data.get(tenant_id)  # type: ignore[arg-type]
            if bucket is None or key not in bucket:
                return False
            del bucket[key]  # type: ignore[arg-type]
            if not bucket:
                del self._data[tenant_id]  # type: ignore[arg-type]
            return True

    def count(self, tenant_id: object) -> int:
        if not is_identity_text(tenant_id):
            return 0
        with self._lock:
            return len(self._data.get(tenant_id, ()))  # type: ignore[arg-type]

    def has_room(self, tenant_id: object) -> bool:
        """Advisory snapshot (``insert`` is the authoritative atomic check)."""
        if not is_identity_text(tenant_id):
            return False
        with self._lock:
            return len(self._data.get(tenant_id, ())) < self._cap  # type: ignore[arg-type]

    def items(self, tenant_id: object) -> tuple[tuple[str, object], ...]:
        if not is_identity_text(tenant_id):
            return ()
        with self._lock:
            return tuple(self._data.get(tenant_id, {}).items())  # type: ignore[arg-type]


class TenantSlotCounter:
    """Thread-safe per-``(tenant, key)`` concurrency counter with one fixed limit per pair.

    ``try_acquire`` is an atomic check-and-increment (``False`` at the limit or for unusable input);
    ``release`` decrements (never below zero; an unmatched release is ignored); ``active`` reads. Pairs at
    zero hold no memory. The limit is per tenant and key: one tenant at its limit never affects another.
    It is the sub-share building block used on top of the shared ``PhysicalBackendBudget``.
    """

    def __init__(self, per_tenant_limit: object) -> None:
        if not is_exact_int(per_tenant_limit, 1, MAX_TENANT_CAP):
            raise ValueError("TENANT_LIMIT_INVALID")
        self._limit: int = per_tenant_limit  # type: ignore[assignment]
        self._lock = threading.Lock()
        self._active: dict[tuple[str, str], int] = {}

    def __repr__(self) -> str:
        return "TenantSlotCounter(<redacted>)"

    def try_acquire(self, tenant_id: object, key: object) -> bool:
        if not (is_identity_text(tenant_id) and is_identity_text(key)):
            return False
        pair = (tenant_id, key)
        with self._lock:
            used = self._active.get(pair, 0)  # type: ignore[arg-type]
            if used >= self._limit:
                return False
            self._active[pair] = used + 1  # type: ignore[index]
            return True

    def release(self, tenant_id: object, key: object) -> None:
        if not (is_identity_text(tenant_id) and is_identity_text(key)):
            return
        pair = (tenant_id, key)
        with self._lock:
            used = self._active.get(pair, 0)  # type: ignore[arg-type]
            if used <= 1:
                self._active.pop(pair, None)  # type: ignore[arg-type]
            else:
                self._active[pair] = used - 1  # type: ignore[index]

    def active(self, tenant_id: object, key: object) -> int:
        if not (is_identity_text(tenant_id) and is_identity_text(key)):
            return 0
        with self._lock:
            return self._active.get((tenant_id, key), 0)  # type: ignore[arg-type]
