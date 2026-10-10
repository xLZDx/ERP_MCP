"""Phase 2 sprint S9 E2 (R2-US-044, TC132): alert state machine with hysteresis and visible delivery failure.

Offline, unwired, in-memory, EVALUATION_ONLY. Time comes only from the injected clock; the engine reads it
once per step. No threads of its own: compound steps run under a per-``(tenant, key)`` non-blocking try-lock
built from ``TenantSlotCounter`` (a contended call is refused ``INTERNAL_REFUSED``, never half-applied).

Rule: ``AlertRule(kind, threshold, for_duration, recover_threshold, recover_duration, no_data_after)``.
A sample BREACHES at ``value >= threshold`` and is CLEAR at ``value <= recover_threshold``; between the two is
the hysteresis band. Durations are whole seconds. Construction refuses (``ValueError``) anything that is not an
exact int/``Decimal``, NaN/Infinity, negative, bool, ``recover_threshold >= threshold`` or a ratio above 1.

States: ``OK -> PENDING -> FIRING -> RECOVERING -> OK`` (a transient RESOLVED is the instant ``RECOVERED``
event, so it has no state of its own).
* OK -> PENDING on a breach (straight to FIRING when ``for_duration == 0``); PENDING -> OK on a non-breach;
  PENDING -> FIRING once breaching samples span ``for_duration`` seconds.
* FIRING -> RECOVERING on a clear sample; RECOVERING -> OK once clear samples span ``recover_duration``;
  RECOVERING -> FIRING again on any non-clear sample WITHOUT a new event (flapping inside the band or back above
  the threshold creates no second ``FIRED``).
* exactly one ``FIRED`` (``ALERT_FIRED``) when an episode starts and exactly one ``RECOVERED``
  (``ALERT_RECOVERED``) when it ends.
* ``NO_DATA``: a stream with no sample for ``no_data_after`` seconds (checked by every ``tick``; the caller
  must tick on a schedule, a stream nobody ticks cannot detect its own silence) fires with ``reason NO_DATA`` immediately; silence is never "OK". Fresh samples then recover it normally.
* clock regression: the step time is ``max(now, last step time)``, so a clock moving backwards neither
  un-fires nor double-fires.

Events are stored per tenant (bounded; a full store refuses the observation ``QUOTA_EXCEEDED`` WITHOUT changing
state, so no transition is ever lost silently). ``deliver_events`` sends undelivered events in order to the
injected ``AlertSinkPort``; a failure (raise, ``False``, anything but exactly ``True``) keeps the event
undelivered, counts an attempt and returns ``ALERT_DELIVERY_FAILED``; a delivered event is never sent again.
The sink must de-duplicate on ``event_id``: a crash between send and mark could resend. Rule/state/event slots
are never evicted; slots are freed only by an operator-owned archive step outside S9 (no delete in S9).
Real delivery to a human is NOT_RUN.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
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
    is_exact_decimal,
    is_exact_int,
    is_identity_text,
    ops_refusal,
)

__all__ = [
    "AlertDeliveryOutcome", "AlertEngine", "AlertEvent", "AlertEventRecord", "AlertRule", "AlertSinkPort",
    "AlertState", "AlertStatus", "EventType", "FakeAlertSink", "RuleKind",
]

_MAX_ID: Final = 128
_MAX_SECONDS: Final = 30 * 86_400
_SPIN: Final = 20_000


class RuleKind(StrEnum):
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    CURSOR_LAG = "CURSOR_LAG"
    OUTBOX_LAG = "OUTBOX_LAG"
    FAILURE_RATIO = "FAILURE_RATIO"
    UNAUDITED_EFFECTS = "UNAUDITED_EFFECTS"
    RESTORE_VERIFICATION_FAILED = "RESTORE_VERIFICATION_FAILED"


class AlertState(StrEnum):
    OK = "OK"
    PENDING = "PENDING"
    FIRING = "FIRING"
    RECOVERING = "RECOVERING"


class EventType(StrEnum):
    FIRED = "FIRED"
    RECOVERED = "RECOVERED"


def _number(value: object) -> Decimal | None:
    """A non-negative exact int or finite exact ``Decimal`` as ``Decimal``; anything else ``None``."""
    if type(value) is int and value >= 0 and is_exact_int(value, 0):
        return Decimal(value)
    if type(value) is Decimal and is_exact_decimal(value) and value >= 0:
        return value
    return None


def _ident(value: object) -> bool:
    return is_identity_text(value) and len(value) <= _MAX_ID  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class AlertRule:
    kind: RuleKind
    threshold: Decimal
    for_duration: int
    recover_threshold: Decimal
    recover_duration: int
    no_data_after: int = 300

    def __post_init__(self) -> None:
        threshold, recover = _number(self.threshold), _number(self.recover_threshold)
        ok = (type(self.kind) is RuleKind and threshold is not None and recover is not None and threshold > 0
              and recover < threshold and is_exact_int(self.for_duration, 0, _MAX_SECONDS)
              and is_exact_int(self.recover_duration, 0, _MAX_SECONDS)
              and is_exact_int(self.no_data_after, 1, _MAX_SECONDS)
              and (self.kind is not RuleKind.FAILURE_RATIO or threshold <= 1))
        if not ok:
            raise ValueError("ALERT_RULE_INVALID")
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "recover_threshold", recover)


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """One edge of an episode. ``repr`` is redacted; ``event_id`` is a stable digest for sink de-duplication."""

    event_id: str
    tenant_id: str
    subject_id: str
    kind: RuleKind
    event_type: EventType
    reason: OpsReason
    episode: int
    at: datetime
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        pair = (self.event_type, self.reason)
        ok = (_ident(self.event_id) and _ident(self.tenant_id) and _ident(self.subject_id)
              and type(self.kind) is RuleKind and pair in _EVENT_REASONS and is_exact_int(self.episode, 1)
              and is_aware_datetime(self.at) and self.authority == AUTHORITY)
        if not ok:
            raise ValueError("ALERT_EVENT_INVALID")

    def __repr__(self) -> str:
        return "AlertEvent(<redacted>)"


_EVENT_REASONS: Final = frozenset({
    (EventType.FIRED, OpsReason.ALERT_FIRED), (EventType.FIRED, OpsReason.NO_DATA),
    (EventType.RECOVERED, OpsReason.ALERT_RECOVERED),
})


class AlertSinkPort(Protocol):
    def send(self, event: AlertEvent) -> bool: ...


class FakeAlertSink:
    """TEST-ONLY sink. ``fail_next(n)`` makes the next ``n`` sends fail; modes cover raising/falsy/malformed.
    De-duplicates on ``event_id`` (a repeat returns ``True`` and stores nothing). Lock-free: atomic builtins."""

    POISON: Final = "POISON-ALERT-SINK-token=FAKE-secret"

    def __init__(self, log: list | None = None) -> None:
        self._log = log
        self._fail = 0
        self._mode = "raise"
        self._seen: dict[str, AlertEvent] = {}
        self.sent: list[AlertEvent] = []
        self.attempts = 0

    def fail_next(self, count: int, mode: str = "raise") -> None:
        self._fail, self._mode = count, mode

    def send(self, event: AlertEvent) -> bool:
        self.attempts += 1
        if self._fail > 0:
            self._fail -= 1
            if self._mode == "raise":
                raise ConnectionError(self.POISON)
            if self._mode == "false":
                return False
            return "yes"  # type: ignore[return-value]  # malformed: truthy but not exactly True
        if self._seen.setdefault(event.event_id, event) is event:
            self.sent.append(event)
            if self._log is not None:
                self._log.append(("alert", event.event_type.value))
        return True


@dataclass(frozen=True, slots=True)
class AlertStatus:
    state: AlertState
    episode: int
    no_data_active: bool
    authority: str = AUTHORITY


@dataclass(frozen=True, slots=True)
class AlertEventRecord:
    event: AlertEvent
    delivered: bool
    attempts: int


@dataclass(frozen=True, slots=True)
class AlertDeliveryOutcome:
    delivered_count: int
    remaining_count: int
    reason: OpsReason | None
    correlation_id: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        if not (is_exact_int(self.delivered_count, 0) and is_exact_int(self.remaining_count, 0)
                and self.reason in (None, OpsReason.ALERT_DELIVERY_FAILED)
                and (self.reason is None) is (self.remaining_count == 0) and _ident(self.correlation_id)
                and self.authority == AUTHORITY):
            raise ValueError("ALERT_DELIVERY_OUTCOME_INVALID")


@dataclass(frozen=True, slots=True)
class _State:
    rule: AlertRule
    phase: AlertState
    since: datetime | None
    last_sample: datetime
    last_time: datetime
    episode: int
    no_data: bool


@dataclass(frozen=True, slots=True)
class _Rec:
    event: AlertEvent
    delivered: bool
    attempts: int


_BUSY: Final = object()


def _locked(counter: TenantSlotCounter, tenant: str, key: str, fn: Callable[[], object]) -> object:
    """Run ``fn`` under the non-blocking per-key lock, or return ``_BUSY`` when it stays contended."""
    for _ in range(_SPIN):
        if counter.try_acquire(tenant, key):
            break
    else:
        return _BUSY
    try:
        return fn()
    finally:
        counter.release(tenant, key)


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class AlertEngine:
    def __init__(self, ownership: object, entitlement: object, ids: object, clock: object, *,
                 rules_per_tenant: object = 1000, events_per_tenant: object = 10_000) -> None:
        if (not callable(getattr(clock, "now", None)) or not is_exact_int(rules_per_tenant, 1, MAX_TENANT_CAP)
                or not is_exact_int(events_per_tenant, 1, MAX_TENANT_CAP)):
            raise ValueError("ALERT_ENGINE_CONFIG_INVALID")
        self._ownership = ownership
        self._entitlement = entitlement
        self._ids = ids
        self._clock = clock
        self._states = TenantBoundedMap(rules_per_tenant, ids)
        self._events = TenantBoundedMap(events_per_tenant, ids)
        self._locks = TenantSlotCounter(1)

    def __repr__(self) -> str:
        return "AlertEngine(<redacted>)"

    # ---- helpers -------------------------------------------------------------------------------
    def _refuse(self, reason: OpsReason) -> OpsRefusal:
        return ops_refusal(reason, self._ids)

    def _now(self) -> datetime | None:
        try:
            value = self._clock.now()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None
        return value if is_aware_datetime(value) else None

    def _check(self, scope: object, subject: object) -> OpsRefusal | None:
        refs = () if subject is None else (("source_id", subject),)
        return check_scope_order(scope, refs, self._ownership, self._entitlement, self._ids)

    @staticmethod
    def _key(subject: str, kind: RuleKind) -> str:
        return _digest(subject, kind.value)

    # ---- configuration -------------------------------------------------------------------------
    def set_rule(self, scope: object, subject_id: object, rule: object) -> OpsRefusal | None:
        """Register the one rule of ``(subject, kind)``. Re-registering is ``DUPLICATE_SUPPRESSED`` (a rule
        never changes mid-episode)."""
        try:
            if type(rule) is not AlertRule or not _ident(subject_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            try:  # one validated copy: a forged instance (unset slots) is simply invalid
                rule = AlertRule(rule.kind, rule.threshold, rule.for_duration, rule.recover_threshold,
                                 rule.recover_duration, rule.no_data_after)
            except (AttributeError, ValueError):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, subject_id)
            if refusal is not None:
                return refusal
            now = self._now()
            if now is None:
                return self._refuse(OpsReason.DEPENDENCY_FAILED)
            state = _State(rule, AlertState.OK, None, now, now, 0, False)
            return self._states.insert(scope.tenant_id, self._key(subject_id, rule.kind), state)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    # ---- state machine -------------------------------------------------------------------------
    def observe(self, scope: object, subject_id: object, kind: object, value: object) -> OpsRefusal | None:
        """Feed one sample. ``None`` = accepted; anything else is a refusal and changed nothing."""
        try:
            number = _number(value)
            if type(kind) is not RuleKind or number is None or not _ident(subject_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            return self._step(scope, subject_id, kind, number)
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def tick(self, scope: object, subject_id: object, kind: object) -> OpsRefusal | None:
        """A time step with no sample: the only way silence can become ``NO_DATA``."""
        try:
            if type(kind) is not RuleKind or not _ident(subject_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            return self._step(scope, subject_id, kind, None)
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def _step(self, scope: object, subject: str, kind: RuleKind, value: Decimal | None) -> OpsRefusal | None:
        refusal = self._check(scope, subject)
        if refusal is not None:
            return refusal
        tenant = scope.tenant_id  # type: ignore[attr-defined]
        key = self._key(subject, kind)
        now = self._now()
        if now is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)

        def under_lock() -> OpsRefusal | None:
            state = self._states.get(tenant, key)
            if type(state) is not _State:
                return self._refuse(OpsReason.NOT_FOUND)
            new, edge = _advance(state, value, max(now, state.last_time))
            if edge is not None:
                event_type, reason = edge
                eid = _digest(tenant, subject, kind.value, str(new.episode), event_type.value)[:32]
                event = AlertEvent(eid, tenant, subject, kind, event_type, reason, new.episode, new.last_time)
                stored = self._events.insert(tenant, eid, _Rec(event, False, 0))
                if stored is not None and stored.reason is not OpsReason.DUPLICATE_SUPPRESSED:
                    return stored  # QUOTA_EXCEEDED: state unchanged, nothing lost silently
            self._states.replace(tenant, key, new)
            return None

        result = _locked(self._locks, tenant, key, under_lock)
        if result is _BUSY:
            return self._refuse(OpsReason.INTERNAL_REFUSED)
        return result  # type: ignore[return-value]

    def status(self, scope: object, subject_id: object, kind: object) -> AlertStatus | OpsRefusal:
        try:
            if type(kind) is not RuleKind or not _ident(subject_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, subject_id)
            if refusal is not None:
                return refusal
            state = self._states.get(scope.tenant_id, self._key(subject_id, kind))  # type: ignore[attr-defined]
            if type(state) is not _State:
                return self._refuse(OpsReason.NOT_FOUND)
            return AlertStatus(state.phase, state.episode, state.no_data)
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    # ---- events and delivery -------------------------------------------------------------------
    def _records(self, tenant: str) -> list[_Rec]:
        recs = [v for _, v in self._events.items(tenant) if type(v) is _Rec]
        recs.sort(key=lambda r: (r.event.at, r.event.episode, r.event.event_type is EventType.RECOVERED,
                                 r.event.event_id))
        return recs

    def records(self, scope: object) -> tuple[AlertEventRecord, ...] | OpsRefusal:
        try:
            refusal = self._check(scope, None)
            if refusal is not None:
                return refusal
            return tuple(AlertEventRecord(r.event, r.delivered, r.attempts)
                         for r in self._records(scope.tenant_id))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def events(self, scope: object) -> tuple[AlertEvent, ...] | OpsRefusal:
        recs = self.records(scope)
        return recs if type(recs) is OpsRefusal else tuple(r.event for r in recs)

    def undelivered(self, scope: object) -> tuple[AlertEvent, ...] | OpsRefusal:
        recs = self.records(scope)
        return recs if type(recs) is OpsRefusal else tuple(r.event for r in recs if not r.delivered)

    def deliver_events(self, scope: object, sink: object) -> AlertDeliveryOutcome | OpsRefusal:
        """Send undelivered events in order, stopping at the first failure (order is preserved)."""
        try:
            if not callable(getattr(sink, "send", None)):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, None)
            if refusal is not None:
                return refusal
            tenant = scope.tenant_id  # type: ignore[attr-defined]

            def under_lock() -> AlertDeliveryOutcome:
                delivered = 0
                recs = [r for r in self._records(tenant) if not r.delivered]
                for index, rec in enumerate(recs):
                    try:
                        ok = sink.send(rec.event)  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001 - sink text never surfaces
                        ok = False
                    if ok is not True:
                        self._events.replace(tenant, rec.event.event_id, _Rec(rec.event, False, rec.attempts + 1))
                        return self._outcome(delivered, len(recs) - index, OpsReason.ALERT_DELIVERY_FAILED)
                    self._events.replace(tenant, rec.event.event_id, _Rec(rec.event, True, rec.attempts + 1))
                    delivered += 1
                return self._outcome(delivered, 0, None)

            result = _locked(self._locks, tenant, "deliver-events", under_lock)
            if result is _BUSY:
                return self._refuse(OpsReason.DUPLICATE_SUPPRESSED)
            return result  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def _outcome(self, delivered: int, remaining: int, reason: OpsReason | None) -> AlertDeliveryOutcome:
        return AlertDeliveryOutcome(delivered, remaining, reason, self._refuse(OpsReason.INTERNAL_REFUSED).correlation_id)


def _advance(state: _State, value: Decimal | None,
             t: datetime) -> tuple[_State, tuple[EventType, OpsReason] | None]:
    """Pure transition. Returns the new state and at most one edge ``(event_type, reason)``."""
    rule, phase = state.rule, state.phase
    last_sample = state.last_sample
    since, episode, no_data = state.since, state.episode, state.no_data
    edge: tuple[EventType, OpsReason] | None = None

    def fire(reason: OpsReason, nd: bool) -> None:
        nonlocal phase, since, episode, no_data, edge
        phase, since, episode, no_data = AlertState.FIRING, None, episode + 1, nd
        edge = (EventType.FIRED, reason)

    def recover() -> None:
        nonlocal phase, since, no_data, edge
        phase, since, no_data = AlertState.OK, None, False
        edge = (EventType.RECOVERED, OpsReason.ALERT_RECOVERED)

    if value is None:
        if t - last_sample >= timedelta(seconds=rule.no_data_after):
            if phase in (AlertState.OK, AlertState.PENDING):
                fire(OpsReason.NO_DATA, True)
            elif phase is AlertState.RECOVERING:
                phase, since, no_data = AlertState.FIRING, None, True
    else:
        last_sample = t
        breach, clear = value >= rule.threshold, value <= rule.recover_threshold
        span_for, span_rec = timedelta(seconds=rule.for_duration), timedelta(seconds=rule.recover_duration)
        if phase is AlertState.OK:
            if breach:
                if span_for == timedelta(0):
                    fire(OpsReason.ALERT_FIRED, False)
                else:
                    phase, since = AlertState.PENDING, t
        elif phase is AlertState.PENDING:
            if not breach:
                phase, since = AlertState.OK, None
            elif since is not None and t - since >= span_for:
                fire(OpsReason.ALERT_FIRED, False)
        elif phase is AlertState.FIRING:
            if clear:
                if span_rec == timedelta(0):
                    recover()
                else:
                    phase, since = AlertState.RECOVERING, t
        elif phase is AlertState.RECOVERING:
            if not clear:
                phase, since = AlertState.FIRING, None
            elif since is not None and t - since >= span_rec:
                recover()
    return _State(rule, phase, since, last_sample, t, episode, no_data), edge
