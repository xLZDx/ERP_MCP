"""Phase 2 sprint S9 E2 (R2-US-044, TC130): audit-before-effect gate that fails closed.

Offline, unwired, in-memory, EVALUATION_ONLY. No real sink, clock, I/O or threads of its own.

Flow of ``AuditGate.guarded_effect(scope, request_id, operation, effect, refs)``:

1. own input structure (no port is asked yet), then ``check_scope_order`` (structure -> entitlement ->
   ownership of every ref -> nothing else). Foreign and unknown refs give the identical refusal.
2. the operation name is classified by the EXISTING ``side_effect_boundary`` registry (no new list):
   ``READ`` passes WITHOUT the gate (``READ_PASSED``); an unregistered name is refused ``UNCLASSIFIED``;
   every other class is gated.
3. the tenant's sink binding must exist (missing = ``AUDIT_UNAVAILABLE``), and the tenant's unaudited list
   must have room (else ``QUOTA_EXCEEDED``) - both BEFORE the effect.
4. an INTENT record is written. Sink down, raising, slower than the fake deadline, returning a malformed
   ack, a non-durable ack, an ack bound to another record, or a bad clock => ``AUDIT_UNAVAILABLE`` and the
   effect is invoked ZERO times.
5. the effect runs. A raising effect is recorded (``EFFECT_FAILED``), never reported as success.
6. a COMPLETION record is written. If THAT write fails the effect already happened and cannot be undone:
   the outcome is ``AUDIT_COMPLETION_PENDING`` and a visible obligation is kept in the tenant's
   ``UnauditedEffects`` list (``AuditGate.unaudited``); the effect is NEVER retried. ``retry_completion``
   re-writes only the bookkeeping record.

Limits (stated, not hidden): the deadline is checked on the injected clock after the sink call returns
(a synchronous call cannot be pre-empted here); the sink must de-duplicate on ``(request_id, phase)``,
because a timed-out write may still have been stored.

Request ids: once an INTENT record is durable the gate remembers ``request_id`` PER TENANT (a bounded map,
nothing is evicted). A request id that is already known (in flight, completed, effect failed, completion
pending, reconciled) is refused BEFORE any record or effect with ``DUPLICATE_SUPPRESSED``; a request that was
refused because the sink was unavailable is NOT remembered (no effect ran), so it can be retried. The request
id space is the tenant's, because the sink de-duplicates on the tenant as well; a duplicate answer therefore
does not distinguish companies of one tenant. Slots (request ids and obligations) are freed only by the
operator-owned archive step outside S9 (S9 has no delete); a reconciled obligation keeps its slot. If the
per-tenant obligation list refuses an entry in a race after the pre-check (full or duplicate), the obligation
is counted in a visible overflow counter instead of being lost. Quotas are per tenant; nothing is evicted.

Interruptions: ``KeyboardInterrupt`` / ``SystemExit`` (any ``BaseException``) raised by the effect are
recorded exactly like a failing effect (completion record, or a visible obligation when that write fails)
and then re-raised unchanged.

Ownership: an obligation belongs to the company that ran the request; ``unaudited`` lists and
``retry_completion`` acts only on the caller's company. A foreign request id and an unknown request id give
the identical ``NOT_FOUND`` refusal with the identical port-call pattern.
"""
from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
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
from .side_effect_boundary import OperationClass, OperationRegistry, canonical_operation

__all__ = [
    "AuditAck", "AuditGate", "AuditPhase", "AuditRecord", "AuditSinkPort", "FakeAuditSink", "GateOutcome",
    "GateStatus", "SinkMode", "UnauditedEffect", "UnauditedReport", "guarded_effect", "is_valid_gate_outcome",
]

_MAX_ID: Final = 128
_MAX_BINDINGS: Final = 10_000
_REFUSAL_REASONS: Final = frozenset({
    OpsReason.INPUT_INVALID, OpsReason.NOT_FOUND, OpsReason.NOT_ENTITLED, OpsReason.NOT_AUTHORIZED,
    OpsReason.QUOTA_EXCEEDED, OpsReason.DEPENDENCY_FAILED, OpsReason.INTERNAL_REFUSED,
    OpsReason.AUDIT_UNAVAILABLE, OpsReason.UNCLASSIFIED, OpsReason.DUPLICATE_SUPPRESSED,
})


def _ident(value: object) -> bool:
    return is_identity_text(value) and len(value) <= _MAX_ID  # type: ignore[arg-type]


class AuditPhase(StrEnum):
    INTENT = "INTENT"
    COMPLETION = "COMPLETION"


class _RecordOutcome(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    EFFECT_FAILED = "EFFECT_FAILED"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One audit record as the sink stores it (tenant data for the tenant's own sink). ``repr`` redacted."""

    tenant_id: str
    company_id: str
    actor_id: str
    request_id: str
    operation: str
    phase: AuditPhase
    outcome: _RecordOutcome

    def __post_init__(self) -> None:
        ok = (_ident(self.tenant_id) and _ident(self.company_id) and _ident(self.actor_id)
              and _ident(self.request_id) and type(self.operation) is str and self.operation != ""
              and canonical_operation(self.operation) == self.operation
              and type(self.phase) is AuditPhase and type(self.outcome) is _RecordOutcome
              and ((self.phase is AuditPhase.INTENT) is (self.outcome is _RecordOutcome.PENDING)))
        if not ok:
            raise ValueError("AUDIT_RECORD_INVALID")

    def __repr__(self) -> str:
        return "AuditRecord(<redacted>)"

    @property
    def digest(self) -> str:
        """sha256 over the fixed field order (identity text has no control characters, so ``\\x1f`` is safe)."""
        raw = "\x1f".join((self.tenant_id, self.company_id, self.actor_id, self.request_id, self.operation,  # noqa: FLY002
                           self.phase.value, self.outcome.value))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditAck:
    """What a sink answers. Deliberately NOT validated here: the gate validates what a sink returns."""

    sequence: int
    durable: bool
    record_digest: str


class AuditSinkPort(Protocol):
    def write(self, record: AuditRecord) -> AuditAck: ...


class SinkMode(StrEnum):
    HEALTHY = "HEALTHY"
    DOWN = "DOWN"            # raises (with poison text that must never surface)
    SLOW = "SLOW"            # stores, but advances the injected fake clock past the deadline
    MALFORMED = "MALFORMED"  # returns something that is not an AuditAck
    NON_DURABLE = "NON_DURABLE"  # ack without a usable sequence number / durable flag


class FakeAuditSink:
    """TEST-ONLY sink with scripted modes. De-duplicates on ``(tenant, request_id, phase)`` like a real
    sink must; a repeated write returns the stored ack and stores nothing new. Lock-free by design: every
    shared operation is a single atomic builtin call."""

    POISON: Final = "POISON-SINK-SECRET-dsn=postgres://user:pw@host"

    def __init__(self, clock: object = None, *, delay_seconds: int = 60, log: list | None = None,
                 name: str = "audit") -> None:
        self._clock = clock
        self._delay = delay_seconds
        self._log = log
        self._name = name
        self._mode = SinkMode.HEALTHY
        self._phase_mode: dict[AuditPhase, SinkMode] = {}
        self._seq = itertools.count(1)
        self._acks: dict[tuple[str, str, str], AuditAck] = {}
        self.records: list[AuditRecord] = []
        self.write_attempts: list[AuditPhase] = []

    def set_mode(self, mode: SinkMode) -> None:
        self._mode = mode

    def set_phase_mode(self, phase: AuditPhase, mode: SinkMode | None) -> None:
        if mode is None:
            self._phase_mode.pop(phase, None)
        else:
            self._phase_mode[phase] = mode

    def write(self, record: AuditRecord) -> AuditAck:
        self.write_attempts.append(record.phase)
        if self._log is not None:
            self._log.append((self._name, record.phase.value))
        mode = self._phase_mode.get(record.phase, self._mode)
        if mode is SinkMode.DOWN:
            raise ConnectionError(self.POISON)
        if mode is SinkMode.MALFORMED:
            return object()  # type: ignore[return-value]
        if mode is SinkMode.NON_DURABLE:
            return AuditAck(0, False, record.digest)
        key = (record.tenant_id, record.request_id, record.phase.value)
        fresh = AuditAck(next(self._seq), True, record.digest)
        ack = self._acks.setdefault(key, fresh)
        if ack is fresh:
            self.records.append(record)
        if mode is SinkMode.SLOW and self._clock is not None:
            self._clock.advance(self._delay)  # type: ignore[attr-defined]
        return ack


class GateStatus(StrEnum):
    READ_PASSED = "READ_PASSED"
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    EFFECT_FAILED = "EFFECT_FAILED"
    COMPLETION_PENDING = "COMPLETION_PENDING"


_STATUS_REASONS: Final = MappingProxyType({
    GateStatus.READ_PASSED: frozenset({None}),
    GateStatus.COMPLETED: frozenset({None}),
    GateStatus.REFUSED: frozenset(_REFUSAL_REASONS),
    GateStatus.EFFECT_FAILED: frozenset({OpsReason.EFFECT_FAILED}),
    GateStatus.COMPLETION_PENDING: frozenset({OpsReason.AUDIT_COMPLETION_PENDING}),
})


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """Derived result of one gated call. Carries no input text and no effect return value."""

    status: GateStatus
    reason: OpsReason | None
    intent_sequence: int
    completion_sequence: int
    effect_invoked: bool
    correlation_id: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        ok = (type(self.status) is GateStatus and (self.reason is None or type(self.reason) is OpsReason)
              and self.reason in _STATUS_REASONS[self.status]
              and is_exact_int(self.intent_sequence, 0) and is_exact_int(self.completion_sequence, 0)
              and type(self.effect_invoked) is bool
              and (self.status is not GateStatus.REFUSED or not self.effect_invoked)
              and _ident(self.correlation_id) and self.authority == AUTHORITY)
        if not ok:
            raise ValueError("GATE_OUTCOME_INVALID")


def is_valid_gate_outcome(value: object) -> bool:
    if type(value) is not GateOutcome:
        return False
    try:
        return (type(value.status) is GateStatus and (value.reason is None or type(value.reason) is OpsReason)
                and value.reason in _STATUS_REASONS[value.status]
                and _ident(value.correlation_id) and value.authority == AUTHORITY)
    except AttributeError:
        return False


@dataclass(frozen=True, slots=True)
class UnauditedEffect:
    """A visible reconciliation obligation: an effect happened but its completion record is not durable."""

    request_id: str
    operation: str
    intent_sequence: int
    effect_failed: bool
    reconciled: bool

    def __repr__(self) -> str:
        return "UnauditedEffect(<redacted>)"


@dataclass(frozen=True, slots=True)
class UnauditedReport:
    entries: tuple[UnauditedEffect, ...]
    overflow_count: int
    authority: str = AUTHORITY

    @property
    def pending_count(self) -> int:
        """Unreconciled obligations plus overflowed ones; feeds the ``UNAUDITED_EFFECTS`` alert rule."""
        return sum(1 for e in self.entries if not e.reconciled) + self.overflow_count


@dataclass(frozen=True, slots=True)
class _Obligation:
    company_id: str
    effect: UnauditedEffect
    completion: AuditRecord


class AuditGate:
    """Per-tenant audit gate. See the module docstring for the flow and the stated limits."""

    def __init__(self, registry: object, sinks: object, ownership: object, entitlement: object, ids: object,
                 clock: object, *, timeout_seconds: object = 5, unaudited_cap: object = 1000,
                 request_cap: object = 100_000) -> None:
        if (type(registry) is not OperationRegistry or type(sinks) is not dict or len(sinks) > _MAX_BINDINGS
                or not is_exact_int(timeout_seconds, 1, 3600) or not is_exact_int(unaudited_cap, 1, MAX_TENANT_CAP)
                or not is_exact_int(request_cap, 1, MAX_TENANT_CAP)
                or not callable(getattr(clock, "now", None))):
            raise ValueError("AUDIT_GATE_CONFIG_INVALID")
        bindings: dict[str, object] = {}
        for tenant, sink in sinks.items():  # type: ignore[union-attr]
            if not _ident(tenant) or not callable(getattr(sink, "write", None)):
                raise ValueError("AUDIT_GATE_CONFIG_INVALID")
            bindings[tenant] = sink
        self._registry = registry
        self._sinks = bindings  # private snapshot: later edits of the caller's dict change nothing
        self._ownership = ownership
        self._entitlement = entitlement
        self._ids = ids
        self._clock = clock
        self._timeout = timedelta(seconds=timeout_seconds)  # type: ignore[arg-type]
        self._obligations = TenantBoundedMap(unaudited_cap, ids)
        self._requests = TenantBoundedMap(request_cap, ids)  # request ids with a durable intent, per tenant
        self._overflow = TenantSlotCounter(MAX_TENANT_CAP)

    def __repr__(self) -> str:
        return "AuditGate(<redacted>)"

    # ---- helpers -------------------------------------------------------------------------------
    def _outcome(self, status: GateStatus, reason: OpsReason | None, *, intent: int = 0, completion: int = 0,
                 invoked: bool = False, corr: str | None = None) -> GateOutcome:
        if corr is None:
            corr = ops_refusal(OpsReason.INTERNAL_REFUSED, self._ids).correlation_id
        return GateOutcome(status, reason, intent, completion, invoked, corr)

    def _refused(self, reason: OpsReason) -> GateOutcome:
        refusal = ops_refusal(reason, self._ids)
        return self._outcome(GateStatus.REFUSED, refusal.reason, corr=refusal.correlation_id)

    def _scope(self, scope: object, refs: object) -> OpsRefusal | None:
        return check_scope_order(scope, refs, self._ownership, self._entitlement, self._ids)

    def _write(self, sink: object, record: AuditRecord) -> int | None:
        """Sequence number of a durable, matching ack within the deadline, else ``None`` (fail closed)."""
        try:
            t0 = self._clock.now()  # type: ignore[attr-defined]
            ack = sink.write(record)  # type: ignore[attr-defined]
            t1 = self._clock.now()  # type: ignore[attr-defined]
            if not (is_aware_datetime(t0) and is_aware_datetime(t1)) or t1 - t0 > self._timeout:
                return None
            if (type(ack) is not AuditAck or ack.durable is not True or not is_exact_int(ack.sequence, 1)
                    or not is_digest(ack.record_digest) or ack.record_digest != record.digest):
                return None
            return ack.sequence
        except Exception:  # noqa: BLE001 - sink exception text must never surface
            return None

    # ---- gated effect --------------------------------------------------------------------------
    def guarded_effect(self, scope: object, request_id: object, operation: object, effect: object,
                       refs: object = ()) -> GateOutcome:
        try:
            return self._guarded(scope, request_id, operation, effect, refs)
        except Exception:  # noqa: BLE001 - a public function never raises
            return self._refused(OpsReason.INTERNAL_REFUSED)

    def _guarded(self, scope: object, request_id: object, operation: object, effect: object,
                 refs: object) -> GateOutcome:
        if not (_ident(request_id) and callable(effect) and type(operation) is str):
            return self._refused(OpsReason.INPUT_INVALID)
        name = canonical_operation(operation)
        if not name:
            return self._refused(OpsReason.INPUT_INVALID)
        refusal = self._scope(scope, refs)
        if refusal is not None:
            return self._outcome(GateStatus.REFUSED, refusal.reason, corr=refusal.correlation_id)
        klass = self._registry.classify(name)
        if klass is OperationClass.UNCLASSIFIED:
            return self._refused(OpsReason.UNCLASSIFIED)
        if klass is OperationClass.READ:
            try:
                effect()  # type: ignore[operator]
            except Exception:  # noqa: BLE001
                return self._outcome(GateStatus.EFFECT_FAILED, OpsReason.EFFECT_FAILED, invoked=True)
            return self._outcome(GateStatus.READ_PASSED, None, invoked=True)
        scope_ = scope  # validated by check_scope_order
        tenant, company, actor = scope_.tenant_id, scope_.company_id, scope_.actor_id  # type: ignore[attr-defined]
        sink = self._sinks.get(tenant)
        if sink is None:
            return self._refused(OpsReason.AUDIT_UNAVAILABLE)
        if self._requests.get(tenant, request_id) is not None:
            return self._refused(OpsReason.DUPLICATE_SUPPRESSED)  # known request: no record, no effect
        if not self._obligations.has_room(tenant) or not self._requests.has_room(tenant):
            return self._refused(OpsReason.QUOTA_EXCEEDED)
        intent = AuditRecord(tenant, company, actor, request_id, name, AuditPhase.INTENT,  # type: ignore[arg-type]
                             _RecordOutcome.PENDING)
        intent_seq = self._write(sink, intent)
        if intent_seq is None:
            return self._refused(OpsReason.AUDIT_UNAVAILABLE)
        remembered = self._requests.insert(tenant, request_id, True)  # atomic: one of two racers wins
        if remembered is not None:
            return self._refused(OpsReason.DUPLICATE_SUPPRESSED if remembered.reason is OpsReason.DUPLICATE_SUPPRESSED
                                 else OpsReason.QUOTA_EXCEEDED)
        failed = False
        interrupt: BaseException | None = None
        try:
            effect()  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - effect text never surfaces
            failed = True
        except BaseException as exc:  # noqa: BLE001 - audited below, then re-raised unchanged
            failed, interrupt = True, exc
        completion = AuditRecord(tenant, company, actor, request_id, name, AuditPhase.COMPLETION,  # type: ignore[arg-type]
                                 _RecordOutcome.EFFECT_FAILED if failed else _RecordOutcome.SUCCEEDED)
        try:
            completion_seq = self._write(sink, completion)
            if completion_seq is None:
                self._keep_obligation(tenant, company, request_id, name, intent_seq, failed,  # type: ignore[arg-type]
                                      completion)
        finally:
            if interrupt is not None:
                raise interrupt
        if completion_seq is None:
            return self._outcome(GateStatus.COMPLETION_PENDING, OpsReason.AUDIT_COMPLETION_PENDING,
                                 intent=intent_seq, invoked=True)
        if failed:
            return self._outcome(GateStatus.EFFECT_FAILED, OpsReason.EFFECT_FAILED, intent=intent_seq,
                                 completion=completion_seq, invoked=True)
        return self._outcome(GateStatus.COMPLETED, None, intent=intent_seq, completion=completion_seq,
                             invoked=True)

    def _keep_obligation(self, tenant: str, company: str, request_id: str, name: str, intent_seq: int,
                         failed: bool, completion: AuditRecord) -> None:
        entry = _Obligation(company, UnauditedEffect(request_id, name, intent_seq, failed, False), completion)
        refusal = self._obligations.insert(tenant, request_id, entry)
        if refusal is not None:  # full, duplicate or unusable: visible counter, never a silent loss
            self._overflow.try_acquire(tenant, f"overflow:{company}")

    # ---- obligations ---------------------------------------------------------------------------
    def unaudited(self, scope: object) -> UnauditedReport | OpsRefusal:
        """The tenant's obligations (entitlement first; no ownership refs are involved)."""
        try:
            refusal = self._scope(scope, ())
            if refusal is not None:
                return refusal
            tenant, company = scope.tenant_id, scope.company_id  # type: ignore[attr-defined]
            entries = tuple(v.effect for _, v in self._obligations.items(tenant)
                            if type(v) is _Obligation and v.company_id == company)
            return UnauditedReport(entries, self._overflow.active(tenant, f"overflow:{company}"))
        except Exception:  # noqa: BLE001
            return ops_refusal(OpsReason.INTERNAL_REFUSED, self._ids)

    def retry_completion(self, scope: object, request_id: object) -> GateOutcome:
        """Re-write ONLY the bookkeeping record of one obligation; the effect is never invoked again."""
        try:
            if not _ident(request_id):
                return self._refused(OpsReason.INPUT_INVALID)
            refusal = self._scope(scope, ())
            if refusal is not None:
                return self._outcome(GateStatus.REFUSED, refusal.reason, corr=refusal.correlation_id)
            tenant, company = scope.tenant_id, scope.company_id  # type: ignore[attr-defined]
            entry = self._obligations.get(tenant, request_id)
            sink = self._sinks.get(tenant)
            if type(entry) is not _Obligation or entry.company_id != company:
                return self._refused(OpsReason.NOT_FOUND)  # foreign company == unknown request
            if entry.effect.reconciled:
                return self._outcome(GateStatus.COMPLETED, None, intent=entry.effect.intent_sequence)
            if sink is None:
                return self._refused(OpsReason.AUDIT_UNAVAILABLE)
            seq = self._write(sink, entry.completion)
            if seq is None:
                return self._outcome(GateStatus.COMPLETION_PENDING, OpsReason.AUDIT_COMPLETION_PENDING,
                                     intent=entry.effect.intent_sequence)
            done = _Obligation(entry.company_id, UnauditedEffect(entry.effect.request_id, entry.effect.operation,
                                               entry.effect.intent_sequence, entry.effect.effect_failed, True),
                               entry.completion)
            self._obligations.replace(tenant, request_id, done)
            return self._outcome(GateStatus.COMPLETED, None, intent=entry.effect.intent_sequence,
                                 completion=seq)
        except Exception:  # noqa: BLE001
            return self._refused(OpsReason.INTERNAL_REFUSED)


def guarded_effect(gate: object, scope: object, request_id: object, operation: object, effect: Callable[[], object],
                   refs: object = ()) -> GateOutcome | OpsRefusal:
    """Module-level entry point: ``gate`` must be an exact ``AuditGate``; anything else is ``INPUT_INVALID``."""
    if type(gate) is not AuditGate:
        return ops_refusal(OpsReason.INPUT_INVALID, None)
    return gate.guarded_effect(scope, request_id, operation, effect, refs)
