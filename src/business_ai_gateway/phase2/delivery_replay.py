"""Phase 2 sprint S9 E2 (R2-US-044, TC131): at-least-once delivery with digest de-duplication.

Offline, unwired, in-memory, EVALUATION_ONLY. Outbox-shaped events per ``(tenant, source, connection)``.

* ``ReplayPlanner.register`` snapshots events once. Dedup key ``(tenant, source, connection, event_id)`` with the
  stored ``event_digest``: same id + same digest is a replay (nothing new); same id + other digest is
  ``EVENT_DIGEST_CONFLICT``: the conflicting copy is quarantined in its own per-tenant store and the original is
  never overwritten. The store is bounded PER TENANT: a full tenant gets an explicit ``QUOTA_EXCEEDED`` count and
  nothing is ever evicted (delivered records stay as dedup keys; slots are freed only by an operator-owned
  archive step outside S9, which has no delete).
* ``claim`` gives a worker a per-connection lease with a monotonically increasing ``generation`` (the fence). A
  claim whose generation is no longer current (another worker claimed after the lease expired) is stale: it cannot
  publish and cannot mark delivered (``STALE_CLAIM``). The fence is verified before each publish and again before
  each mark, in one critical section with the claim row.
* ``deliver_pending`` publishes a connection's events strictly in ``seq`` order and stops at the first event that
  is not delivered. ``DELIVERED`` and ``DUPLICATE_ACK`` mark it delivered; ``RATE_LIMITED`` (429) and
  ``NETWORK_FAILURE`` (a raising or malformed sink included) count an attempt and set ``not_before`` to now plus
  ``max(min(retry_after, max_delay), scheduler.backoff_delay(...))`` (bounded); after ``max_attempts`` failures the
  event is ``FAILED`` (explicit ``DELIVERY_FAILED_FINAL``, no infinite retry) and the connection is parked behind
  it until an operator acts (order is never skipped). A failure never advances the cursor.
* the cursor is DERIVED, never stored: the highest ``seq`` such that every registered event up to it is delivered.

Limits (stated): single process; compound steps run under a per-connection non-blocking try-lock built from
``TenantSlotCounter`` (a contended call is refused ``INTERNAL_REFUSED`` and nothing is half-applied); the fence
check and the sink call are not one atomic step, so a worker that goes stale between them may still publish once
- the sink MUST de-duplicate on ``(tenant, source, connection, event_id, digest)`` and answer ``DUPLICATE_ACK``;
if marking a published event fails (stale fence) the event stays pending and is re-published later, which the sink
answers with ``DUPLICATE_ACK``. Sink text, exceptions and payloads never reach any output. Real HTTP is NOT_RUN.
"""
from __future__ import annotations

import hashlib
import itertools
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol

from .ops_types import (
    AUTHORITY,
    MAX_TENANT_CAP,
    OpsReason,
    OpsRefusal,
    TenantBoundedMap,
    TenantSlotCounter,
    check_scope_order,
    is_aware_datetime,
    is_digest,
    is_exact_int,
    is_identity_text,
    ops_refusal,
)
from .scheduler import backoff_delay

__all__ = [
    "Claim", "DeliveryEvent", "DeliveryOutcome", "DeliveryRecord", "DeliverySinkPort", "DeliveryStatus",
    "FakeDeliverySink", "RecordStatus", "RegisterOutcome", "ReplayPlanner", "SinkKind", "SinkResponse",
    "deliver_pending",
]

_MAX_ID: Final = 128
_MAX_BATCH: Final = 1000
_MAX_RETRY_AFTER: Final = 3600
_SPIN: Final = 20_000
_BUSY: Final = object()


def _ident(value: object) -> bool:
    return is_identity_text(value) and len(value) <= _MAX_ID  # type: ignore[arg-type]


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class SinkKind(StrEnum):
    DELIVERED = "DELIVERED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    DUPLICATE_ACK = "DUPLICATE_ACK"


@dataclass(frozen=True, slots=True)
class SinkResponse:
    """What a sink answers. Not validated here: the planner validates what a sink returns."""

    kind: SinkKind
    retry_after_seconds: int = 0


class DeliverySinkPort(Protocol):
    def publish(self, tenant_id: str, source_id: str, connection_id: str, event_id: str,
                event_digest: str) -> SinkResponse: ...


class FakeDeliverySink:
    """TEST-ONLY sink with a per-tenant script of faults, consumed one per publish call.

    Script items: ``SinkKind.RATE_LIMITED`` / ``SinkKind.NETWORK_FAILURE`` (nothing stored), ``"RAISE"`` (raises with
    poison text), ``"LOST_ACK"`` (stores the event, then reports a network failure), ``"MALFORMED"``. An empty
    script means healthy. Dedups on ``(tenant, source, connection, event_id)``: a repeat answers ``DUPLICATE_ACK``
    and stores nothing. Lock-free: every shared operation is one atomic builtin call."""

    POISON: Final = "POISON-DELIVERY-SINK-token=FAKE-secret"

    def __init__(self, on_publish: Callable[[str, str, str, str], None] | None = None) -> None:
        self._scripts: dict[str, deque] = {}
        self._seen: dict[tuple[str, str, str, str], tuple[str]] = {}
        self._retry_after = 5
        self._hook = on_publish
        self._attempts = itertools.count(1)
        self.published: list[tuple[str, str, str, str, str]] = []
        self.calls: list[tuple[str, str, str, str]] = []

    def script(self, tenant_id: str, items: list, retry_after: int = 5) -> None:
        self._scripts.setdefault(tenant_id, deque()).extend(items)
        self._retry_after = retry_after

    def publish(self, tenant_id: str, source_id: str, connection_id: str, event_id: str,
                event_digest: str) -> SinkResponse:
        self.calls.append((tenant_id, source_id, connection_id, event_id))
        if self._hook is not None:
            self._hook(tenant_id, source_id, connection_id, event_id)
        try:
            item = self._scripts.get(tenant_id, deque()).popleft()
        except IndexError:
            item = None
        if item is SinkKind.RATE_LIMITED:
            return SinkResponse(SinkKind.RATE_LIMITED, self._retry_after)
        if item is SinkKind.NETWORK_FAILURE:
            return SinkResponse(SinkKind.NETWORK_FAILURE)
        if item == "RAISE":
            raise ConnectionError(self.POISON)
        if item == "MALFORMED":
            return object()  # type: ignore[return-value]
        key = (tenant_id, source_id, connection_id, event_id)
        entry = (event_digest,)
        first = self._seen.setdefault(key, entry) is entry
        if first:
            self.published.append((tenant_id, source_id, connection_id, event_id, event_digest))
        if item == "LOST_ACK":
            return SinkResponse(SinkKind.NETWORK_FAILURE)
        return SinkResponse(SinkKind.DELIVERED if first else SinkKind.DUPLICATE_ACK)


class RecordStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DeliveryEvent:
    """One registrable event (outbox shape without content: identity, order and digest only)."""

    connection_id: str
    seq: int
    event_id: str
    event_digest: str

    def __post_init__(self) -> None:
        if not (_ident(self.connection_id) and is_exact_int(self.seq, 1, 2**62) and _ident(self.event_id)
                and is_digest(self.event_digest)):
            raise ValueError("DELIVERY_EVENT_INVALID")

    def __repr__(self) -> str:
        return "DeliveryEvent(<redacted>)"


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """Read view of a stored event. ``repr`` redacted."""

    connection_id: str
    seq: int
    event_id: str
    status: RecordStatus
    attempts: int
    not_before: datetime | None

    def __repr__(self) -> str:
        return "DeliveryRecord(<redacted>)"


@dataclass(frozen=True, slots=True)
class Claim:
    """A worker's lease on one connection; ``generation`` is the fence."""

    worker_id: str
    generation: int

    def __repr__(self) -> str:
        return "Claim(<redacted>)"


class DeliveryStatus(StrEnum):
    COMPLETE = "COMPLETE"
    WAITING = "WAITING"
    FAILED_FINAL = "FAILED_FINAL"
    STALE = "STALE"
    CLAIM_HELD = "CLAIM_HELD"
    REFUSED = "REFUSED"


_REFUSED_REASONS: Final = frozenset({
    OpsReason.INPUT_INVALID, OpsReason.NOT_FOUND, OpsReason.NOT_ENTITLED, OpsReason.QUOTA_EXCEEDED,
    OpsReason.DEPENDENCY_FAILED, OpsReason.INTERNAL_REFUSED,
})
_STATUS_REASONS: Final = {
    DeliveryStatus.COMPLETE: frozenset({None}),
    DeliveryStatus.WAITING: frozenset({None, OpsReason.RATE_LIMITED, OpsReason.NETWORK_FAILURE}),
    DeliveryStatus.FAILED_FINAL: frozenset({OpsReason.DELIVERY_FAILED_FINAL}),
    DeliveryStatus.STALE: frozenset({OpsReason.STALE_CLAIM}),
    DeliveryStatus.CLAIM_HELD: frozenset({OpsReason.DUPLICATE_SUPPRESSED}),
    DeliveryStatus.REFUSED: _REFUSED_REASONS,
}


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    status: DeliveryStatus
    reason: OpsReason | None
    delivered_count: int
    duplicate_ack_count: int
    cursor_seq: int
    next_retry_at: datetime | None
    correlation_id: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        ok = (type(self.status) is DeliveryStatus and self.reason in _STATUS_REASONS[self.status]
              and is_exact_int(self.delivered_count, 0) and is_exact_int(self.duplicate_ack_count, 0)
              and is_exact_int(self.cursor_seq, 0)
              and (self.next_retry_at is None or is_aware_datetime(self.next_retry_at))
              and _ident(self.correlation_id) and self.authority == AUTHORITY)
        if not ok:
            raise ValueError("DELIVERY_OUTCOME_INVALID")


@dataclass(frozen=True, slots=True)
class RegisterOutcome:
    accepted: int
    replayed: int
    conflicts: int
    quota_refused: int
    reason: OpsReason | None
    correlation_id: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        expected = (OpsReason.EVENT_DIGEST_CONFLICT if self.conflicts else
                    OpsReason.QUOTA_EXCEEDED if self.quota_refused else None)
        if not (all(is_exact_int(n, 0) for n in (self.accepted, self.replayed, self.conflicts, self.quota_refused))
                and self.reason is expected and _ident(self.correlation_id) and self.authority == AUTHORITY):
            raise ValueError("REGISTER_OUTCOME_INVALID")


@dataclass(frozen=True, slots=True)
class _Rec:
    connection_id: str
    seq: int
    event_id: str
    digest: str
    status: RecordStatus
    attempts: int
    not_before: datetime | None


@dataclass(frozen=True, slots=True)
class _ClaimRow:
    owner: str | None
    generation: int
    lease_until: datetime


class ReplayPlanner:
    def __init__(self, ownership: object, entitlement: object, ids: object, clock: object, *,
                 per_tenant_cap: object = 10_000, max_attempts: object = 5, base_delay: object = 1,
                 max_delay: object = 300, lease_seconds: object = 60,
                 jitter_source: Callable[[], float] | None = None) -> None:
        if (not callable(getattr(clock, "now", None)) or not is_exact_int(per_tenant_cap, 1, MAX_TENANT_CAP)
                or not is_exact_int(max_attempts, 1, 100) or not is_exact_int(base_delay, 1, 3600)
                or not is_exact_int(max_delay, 1, 86_400) or not is_exact_int(lease_seconds, 1, 86_400)
                or base_delay > max_delay  # type: ignore[operator]
                or (jitter_source is not None and not callable(jitter_source))):
            raise ValueError("REPLAY_PLANNER_CONFIG_INVALID")
        self._ownership, self._entitlement, self._ids, self._clock = ownership, entitlement, ids, clock
        self._max_attempts: int = max_attempts  # type: ignore[assignment]
        self._base: int = base_delay  # type: ignore[assignment]
        self._max_delay: int = max_delay  # type: ignore[assignment]
        self._lease = timedelta(seconds=lease_seconds)  # type: ignore[arg-type]
        self._jitter = jitter_source or (lambda: 0.0)
        self._records = TenantBoundedMap(per_tenant_cap, ids)
        self._quarantine = TenantBoundedMap(per_tenant_cap, ids)
        self._claims = TenantBoundedMap(per_tenant_cap, ids)
        self._locks = TenantSlotCounter(1)

    def __repr__(self) -> str:
        return "ReplayPlanner(<redacted>)"

    # ---- helpers -------------------------------------------------------------------------------
    def _refuse(self, reason: OpsReason) -> OpsRefusal:
        return ops_refusal(reason, self._ids)

    def _now(self) -> datetime | None:
        try:
            value = self._clock.now()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None
        return value if is_aware_datetime(value) else None

    def _check(self, scope: object, source: object) -> OpsRefusal | None:
        return check_scope_order(scope, (("source_id", source),), self._ownership, self._entitlement, self._ids)

    def _locked(self, tenant: str, key: str, fn: Callable[[], object]) -> object:
        for _ in range(_SPIN):
            if self._locks.try_acquire(tenant, key):
                break
        else:
            return _BUSY
        try:
            return fn()
        finally:
            self._locks.release(tenant, key)

    def _outcome(self, status: DeliveryStatus, reason: OpsReason | None, delivered: int = 0, dup: int = 0,
                 cursor: int = 0, retry_at: datetime | None = None) -> DeliveryOutcome:
        corr = self._refuse(OpsReason.INTERNAL_REFUSED).correlation_id
        return DeliveryOutcome(status, reason, delivered, dup, cursor, retry_at, corr)

    def _refused_outcome(self, reason: OpsReason, refusal: OpsRefusal | None = None) -> DeliveryOutcome:
        refusal = refusal or self._refuse(reason)
        return DeliveryOutcome(DeliveryStatus.REFUSED, refusal.reason, 0, 0, 0, None, refusal.correlation_id)

    def _conn_recs(self, tenant: str, connection: str) -> list[tuple[str, _Rec]]:
        found = [(k, v) for k, v in self._records.items(tenant) if type(v) is _Rec and v.connection_id == connection]
        found.sort(key=lambda kv: (kv[1].seq, kv[1].event_id))
        return found

    @staticmethod
    def _cursor_of(recs: list[tuple[str, _Rec]]) -> int:
        cursor = 0
        for _, rec in recs:
            if rec.status is not RecordStatus.DELIVERED:
                break
            cursor = rec.seq
        return cursor

    @staticmethod
    def _rec_key(source: str, connection: str, event_id: str) -> str:
        return _digest(source, connection, event_id)

    @staticmethod
    def _conn_key(source: str, connection: str) -> str:
        return _digest(source, connection)

    # ---- registration --------------------------------------------------------------------------
    def register(self, scope: object, source_id: object, events: object) -> RegisterOutcome | OpsRefusal:
        try:
            if not _ident(source_id) or type(events) not in (list, tuple) or len(events) > _MAX_BATCH:  # type: ignore[arg-type]
                return self._refuse(OpsReason.INPUT_INVALID)
            snap = tuple(events)  # type: ignore[arg-type]  # one copy; never re-read the caller's container
            if any(type(e) is not DeliveryEvent for e in snap):
                return self._refuse(OpsReason.INPUT_INVALID)
            try:
                batch = tuple(DeliveryEvent(e.connection_id, e.seq, e.event_id, e.event_digest) for e in snap)
            except (AttributeError, ValueError):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, source_id)
            if refusal is not None:
                return refusal
            tenant = scope.tenant_id  # type: ignore[attr-defined]
            accepted = replayed = conflicts = quota = 0
            for ev in batch:
                key = self._rec_key(source_id, ev.connection_id, ev.event_id)  # type: ignore[arg-type]
                result = self._records.insert(tenant, key, _Rec(ev.connection_id, ev.seq, ev.event_id,
                                                                ev.event_digest, RecordStatus.PENDING, 0, None))
                if result is None:
                    accepted += 1
                elif result.reason is OpsReason.QUOTA_EXCEEDED:
                    quota += 1
                elif result.reason is OpsReason.DUPLICATE_SUPPRESSED:
                    existing = self._records.get(tenant, key)
                    if type(existing) is _Rec and existing.digest == ev.event_digest:
                        replayed += 1
                    else:
                        conflicts += 1
                        held = self._quarantine.insert(tenant, _digest(key, ev.event_digest), ev.seq)
                        if held is not None and held.reason is OpsReason.QUOTA_EXCEEDED:
                            quota += 1
                else:
                    return self._refuse(OpsReason.INTERNAL_REFUSED)
            reason = (OpsReason.EVENT_DIGEST_CONFLICT if conflicts else OpsReason.QUOTA_EXCEEDED if quota else None)
            return RegisterOutcome(accepted, replayed, conflicts, quota, reason,
                                   self._refuse(OpsReason.INTERNAL_REFUSED).correlation_id)
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def quarantine_count(self, scope: object) -> int | OpsRefusal:
        try:
            refusal = check_scope_order(scope, (), self._ownership, self._entitlement, self._ids)
            return refusal if refusal is not None else self._quarantine.count(scope.tenant_id)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    # ---- reads ---------------------------------------------------------------------------------
    def records(self, scope: object, source_id: object,
                connection_id: object) -> tuple[DeliveryRecord, ...] | OpsRefusal:
        try:
            if not (_ident(source_id) and _ident(connection_id)):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, source_id)
            if refusal is not None:
                return refusal
            recs = self._conn_recs(scope.tenant_id, connection_id)  # type: ignore[attr-defined,arg-type]
            return tuple(DeliveryRecord(r.connection_id, r.seq, r.event_id, r.status, r.attempts, r.not_before)
                         for _, r in recs)
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def cursor(self, scope: object, source_id: object, connection_id: object) -> int | OpsRefusal:
        """Derived: highest seq with every registered event up to it delivered (0 = none)."""
        try:
            if not (_ident(source_id) and _ident(connection_id)):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, source_id)
            if refusal is not None:
                return refusal
            return self._cursor_of(self._conn_recs(scope.tenant_id, connection_id))  # type: ignore[attr-defined,arg-type]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    # ---- claims --------------------------------------------------------------------------------
    def claim(self, scope: object, worker_id: object, source_id: object,
              connection_id: object) -> Claim | OpsRefusal:
        """Lease the connection. A live lease of another worker gives ``DUPLICATE_SUPPRESSED``."""
        try:
            if not (_ident(worker_id) and _ident(source_id) and _ident(connection_id)):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, source_id)
            if refusal is not None:
                return refusal
            return self._claim(scope.tenant_id, worker_id, source_id, connection_id)  # type: ignore[attr-defined,arg-type]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def _claim(self, tenant: str, worker: str, source: str, connection: str) -> Claim | OpsRefusal:
        now = self._now()
        if now is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        ckey = self._conn_key(source, connection)

        def under_lock() -> Claim | OpsRefusal:
            row = self._claims.get(tenant, ckey)
            generation = 0
            if type(row) is _ClaimRow:
                if row.owner is not None and row.owner != worker and row.lease_until > now:
                    return self._refuse(OpsReason.DUPLICATE_SUPPRESSED)
                generation = row.generation
            new = _ClaimRow(worker, generation + 1, now + self._lease)
            stored = self._claims.replace(tenant, ckey, new) if type(row) is _ClaimRow \
                else self._claims.insert(tenant, ckey, new)
            if stored is not None:
                return stored
            return Claim(worker, new.generation)

        result = self._locked(tenant, ckey, under_lock)
        return self._refuse(OpsReason.INTERNAL_REFUSED) if result is _BUSY else result  # type: ignore[return-value]

    def _fenced(self, tenant: str, ckey: str, claim: Claim, action: Callable[[], object]) -> object:
        """Run ``action`` only while ``claim`` is the current fence; ``None`` = stale, ``_BUSY`` = contended."""
        def under_lock() -> object:
            row = self._claims.get(tenant, ckey)
            if type(row) is not _ClaimRow or row.generation != claim.generation or row.owner != claim.worker_id:
                return None
            return action()

        return self._locked(tenant, ckey, under_lock)

    def _mark(self, tenant: str, ckey: str, claim: Claim, key: str | None, new: _Rec | None) -> str:
        """Fence check plus (optionally) the record write in ONE critical section: ``ok``/``stale``/``busy``/``failed``."""
        def action() -> bool:
            return key is None or new is None or self._records.replace(tenant, key, new) is None

        result = self._fenced(tenant, ckey, claim, action)
        if result is None:
            return "stale"
        if result is _BUSY:
            return "busy"
        return "ok" if result is True else "failed"

    def _mark_outcome(self, state: str, delivered: int, dup: int) -> DeliveryOutcome:
        if state == "stale":
            return self._outcome(DeliveryStatus.STALE, OpsReason.STALE_CLAIM, delivered, dup)
        return self._refused_outcome(OpsReason.INTERNAL_REFUSED)

    def _release(self, tenant: str, ckey: str, claim: Claim, now: datetime) -> None:
        self._fenced(tenant, ckey, claim,
                     lambda: self._claims.replace(tenant, ckey, _ClaimRow(None, claim.generation, now)))

    def _delay(self, attempts_done: int, retry_after: int) -> timedelta:
        try:
            backoff = backoff_delay(attempts_done - 1, float(self._base), float(self._max_delay), self._jitter)
        except Exception:  # noqa: BLE001
            backoff = float(self._max_delay)
        seconds = min(float(self._max_delay), max(backoff, float(min(retry_after, self._max_delay))))
        return timedelta(seconds=seconds)

    # ---- delivery ------------------------------------------------------------------------------
    def deliver_pending(self, scope: object, worker_id: object, source_id: object, connection_id: object,
                        sink: object, claim: object = None) -> DeliveryOutcome:
        try:
            return self._deliver(scope, worker_id, source_id, connection_id, sink, claim)
        except Exception:  # noqa: BLE001 - a public function never raises
            return self._refused_outcome(OpsReason.INTERNAL_REFUSED)

    def _deliver(self, scope: object, worker_id: object, source_id: object, connection_id: object, sink: object,
                 claim: object) -> DeliveryOutcome:
        if not (_ident(worker_id) and _ident(source_id) and _ident(connection_id)
                and callable(getattr(sink, "publish", None)) and (claim is None or type(claim) is Claim)):
            return self._refused_outcome(OpsReason.INPUT_INVALID)
        refusal = self._check(scope, source_id)
        if refusal is not None:
            return self._refused_outcome(refusal.reason, refusal)
        tenant = scope.tenant_id  # type: ignore[attr-defined]
        ckey = self._conn_key(source_id, connection_id)  # type: ignore[arg-type]
        if claim is None:
            got = self._claim(tenant, worker_id, source_id, connection_id)  # type: ignore[arg-type]
            if type(got) is OpsRefusal:
                if got.reason is OpsReason.DUPLICATE_SUPPRESSED:
                    return self._outcome(DeliveryStatus.CLAIM_HELD, OpsReason.DUPLICATE_SUPPRESSED)
                return self._refused_outcome(got.reason, got)
            claim = got
        try:
            claim = Claim(claim.worker_id, claim.generation)  # type: ignore[attr-defined]  # one snapshot
        except AttributeError:
            return self._refused_outcome(OpsReason.INPUT_INVALID)
        delivered = dup = 0
        outcome: DeliveryOutcome | None = None
        recs = self._conn_recs(tenant, connection_id)  # type: ignore[arg-type]
        for key, rec in recs:
            if rec.status is RecordStatus.DELIVERED:
                continue
            now = self._now()
            if now is None:
                outcome = self._refused_outcome(OpsReason.DEPENDENCY_FAILED)
                break
            if rec.status is RecordStatus.FAILED:
                outcome = self._outcome(DeliveryStatus.FAILED_FINAL, OpsReason.DELIVERY_FAILED_FINAL, delivered, dup)
                break
            if rec.not_before is not None and rec.not_before > now:
                outcome = self._outcome(DeliveryStatus.WAITING, None, delivered, dup, retry_at=rec.not_before)
                break
            guard = self._mark(tenant, ckey, claim, None, None)
            if guard != "ok":
                outcome = self._mark_outcome(guard, delivered, dup)
                break
            kind, retry_after = self._publish(sink, tenant, source_id, rec)  # type: ignore[arg-type]
            if kind in (SinkKind.DELIVERED, SinkKind.DUPLICATE_ACK):
                done = _Rec(rec.connection_id, rec.seq, rec.event_id, rec.digest, RecordStatus.DELIVERED,
                            rec.attempts + 1, None)
                marked = self._mark(tenant, ckey, claim, key, done)
                if marked != "ok":
                    outcome = self._mark_outcome(marked, delivered, dup)
                    break
                delivered += kind is SinkKind.DELIVERED
                dup += kind is SinkKind.DUPLICATE_ACK
                continue
            attempts = rec.attempts + 1
            if attempts >= self._max_attempts:
                failed = _Rec(rec.connection_id, rec.seq, rec.event_id, rec.digest, RecordStatus.FAILED, attempts,
                              None)
                reason, status, retry_at = OpsReason.DELIVERY_FAILED_FINAL, DeliveryStatus.FAILED_FINAL, None
            else:
                retry_at = now + self._delay(attempts, retry_after)
                failed = _Rec(rec.connection_id, rec.seq, rec.event_id, rec.digest, RecordStatus.PENDING, attempts,
                              retry_at)
                reason = OpsReason.RATE_LIMITED if kind is SinkKind.RATE_LIMITED else OpsReason.NETWORK_FAILURE
                status = DeliveryStatus.WAITING
            marked = self._mark(tenant, ckey, claim, key, failed)
            if marked != "ok":
                outcome = self._mark_outcome(marked, delivered, dup)
            else:
                outcome = self._outcome(status, reason, delivered, dup, retry_at=retry_at)
            break
        now = self._now()
        if now is not None:
            self._release(tenant, ckey, claim, now)
        cursor = self._cursor_of(self._conn_recs(tenant, connection_id))  # type: ignore[arg-type]
        if outcome is None:
            return self._outcome(DeliveryStatus.COMPLETE, None, delivered, dup, cursor)
        return DeliveryOutcome(outcome.status, outcome.reason, outcome.delivered_count, outcome.duplicate_ack_count,
                               cursor, outcome.next_retry_at, outcome.correlation_id)

    @staticmethod
    def _publish(sink: object, tenant: str, source: str, rec: _Rec) -> tuple[SinkKind, int]:
        try:
            resp = sink.publish(tenant, source, rec.connection_id, rec.event_id, rec.digest)  # type: ignore[attr-defined]
            if type(resp) is not SinkResponse or type(resp.kind) is not SinkKind:
                return SinkKind.NETWORK_FAILURE, 0
            retry = resp.retry_after_seconds
            if not is_exact_int(retry, 0, _MAX_RETRY_AFTER):
                return SinkKind.NETWORK_FAILURE, 0
            return resp.kind, retry
        except Exception:  # noqa: BLE001 - sink text never surfaces
            return SinkKind.NETWORK_FAILURE, 0


def deliver_pending(planner: object, scope: object, worker_id: object, source_id: object, connection_id: object,
                    sink: object, claim: object = None) -> DeliveryOutcome | OpsRefusal:
    """Module-level entry point: ``planner`` must be an exact ``ReplayPlanner``."""
    if type(planner) is not ReplayPlanner:
        return ops_refusal(OpsReason.INPUT_INVALID, None)
    return planner.deliver_pending(scope, worker_id, source_id, connection_id, sink, claim)
