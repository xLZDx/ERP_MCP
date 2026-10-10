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
sink BOUND to the tenant at construction (``sinks``; a caller can never pass one); a failure (raise, ``False``,
anything but exactly ``True``) keeps the event undelivered, counts an attempt and returns
``ALERT_DELIVERY_FAILED``; after ``max_delivery_attempts`` failures the event is PARKED: it stays visible in
``records``/``undelivered`` (``parked=True``) and in ``AlertDeliveryOutcome.parked_count``, is not sent again, and
later events continue (the head of the line never blocks forever). A delivered event is never sent again.
The sink must de-duplicate on ``event_id``: a crash between send and mark could resend.

Ownership: every rule belongs to the company that registered it. ``set_rule``, ``observe``, ``tick``,
``status`` and the event reads run ``check_scope_order`` (structure -> entitlement -> ownership of the subject);
foreign and unknown subjects give the identical ``NOT_FOUND`` and port-call pattern. ``records`` / ``events`` /
``undelivered`` (optionally narrowed to one subject) and ``deliver_events`` only expose and act on the events
of the caller's company; rule keys, event ids and locks include the company.

Nothing is silent: a refused or dropped step (lock contention or an internal defect) increments a per-rule
``AlertStatus.dropped_count``; exhausted rule/event slots increment ``AlertStatus.exhausted_count`` (per rule,
event store) and ``AlertEngine.exhausted_count(scope)`` (per company, rules and events), and the call still
returns ``QUOTA_EXCEEDED``. Counters saturate at ``MAX_TENANT_CAP``. Rule/state/event slots are never evicted;
slots are freed only by an operator-owned archive step outside S9 (no delete in S9).
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
_MAX_BINDINGS: Final = 10_000


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
              and type(self.kind) is RuleKind and type(self.event_type) is EventType
              and type(self.reason) is OpsReason and pair in _EVENT_REASONS and is_exact_int(self.episode, 1)
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
    dropped_count: int = 0
    exhausted_count: int = 0


@dataclass(frozen=True, slots=True)
class AlertEventRecord:
    event: AlertEvent
    delivered: bool
    attempts: int
    parked: bool = False


@dataclass(frozen=True, slots=True)
class AlertDeliveryOutcome:
    delivered_count: int
    remaining_count: int
    reason: OpsReason | None
    correlation_id: str
    authority: str = AUTHORITY
    parked_count: int = 0

    def __post_init__(self) -> None:
        if not (is_exact_int(self.delivered_count, 0) and is_exact_int(self.remaining_count, 0)
                and is_exact_int(self.parked_count, 0)
                and (self.reason is None or type(self.reason) is OpsReason)
                and self.reason in (None, OpsReason.ALERT_DELIVERY_FAILED)
                and (self.reason is None) is (self.remaining_count == 0 and self.parked_count == 0)
                and _ident(self.correlation_id)
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
    company_id: str = ""
    parked: bool = False


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
                 rules_per_tenant: object = 1000, events_per_tenant: object = 10_000,
                 sinks: object = None, max_delivery_attempts: object = 5) -> None:
        if sinks is None:
            sinks = {}
        if (type(sinks) is not dict or len(sinks) > _MAX_BINDINGS
                or any(not _ident(t) or not callable(getattr(s, "send", None)) for t, s in sinks.items())
                or not callable(getattr(clock, "now", None)) or not is_exact_int(rules_per_tenant, 1, MAX_TENANT_CAP)
                or not is_exact_int(events_per_tenant, 1, MAX_TENANT_CAP)
                or not is_exact_int(max_delivery_attempts, 1, 100)):
            raise ValueError("ALERT_ENGINE_CONFIG_INVALID")
        self._sinks: dict[str, object] = dict(sinks)  # type: ignore[arg-type]  # private snapshot
        self._max_attempts: int = max_delivery_attempts  # type: ignore[assignment]
        self._dropped = TenantSlotCounter(MAX_TENANT_CAP)
        self._exhausted = TenantSlotCounter(MAX_TENANT_CAP)
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
    def _key(company: str, subject: str, kind: RuleKind) -> str:
        return _digest(company, subject, kind.value)

    @staticmethod
    def _company_key(company: str, what: str) -> str:
        return _digest(company, what)

    def _exhaust(self, tenant: str, company: str, rule_key: str | None) -> None:
        """Visible, never silent: quota exhaustion is counted (per company, and per rule when one exists)."""
        self._exhausted.try_acquire(tenant, self._company_key(company, "exhausted"))
        if rule_key is not None:
            self._exhausted.try_acquire(tenant, rule_key)

    def exhausted_count(self, scope: object) -> int | OpsRefusal:
        """How many times a rule or event slot was refused for the caller's company (frozen until archival)."""
        try:
            refusal = self._check(scope, None)
            if refusal is not None:
                return refusal
            return self._exhausted.active(scope.tenant_id,  # type: ignore[attr-defined]
                                          self._company_key(scope.company_id, "exhausted"))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

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
            tenant, company = scope.tenant_id, scope.company_id  # type: ignore[attr-defined]
            stored = self._states.insert(tenant, self._key(company, subject_id, rule.kind), state)
            if stored is not None and stored.reason is OpsReason.QUOTA_EXCEEDED:
                self._exhaust(tenant, company, None)
            return stored
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
        tenant, company = scope.tenant_id, scope.company_id  # type: ignore[attr-defined]
        key = self._key(company, subject, kind)
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
                eid = _digest(tenant, company, subject, kind.value, str(new.episode), event_type.value)[:32]
                event = AlertEvent(eid, tenant, subject, kind, event_type, reason, new.episode, new.last_time)
                stored = self._events.insert(tenant, eid, _Rec(event, False, 0, company))
                if stored is not None and stored.reason is not OpsReason.DUPLICATE_SUPPRESSED:
                    if stored.reason is OpsReason.QUOTA_EXCEEDED:
                        self._exhaust(tenant, company, key)  # loud: state unchanged AND the counter moves
                    return stored  # QUOTA_EXCEEDED: state unchanged, nothing lost silently
            self._states.replace(tenant, key, new)
            return None

        try:
            result = _locked(self._locks, tenant, key, under_lock)
        except Exception:  # noqa: BLE001 - an internal defect drops the sample visibly
            self._dropped.try_acquire(tenant, key)
            return self._refuse(OpsReason.INTERNAL_REFUSED)
        if result is _BUSY:
            self._dropped.try_acquire(tenant, key)
            return self._refuse(OpsReason.INTERNAL_REFUSED)
        return result  # type: ignore[return-value]

    def status(self, scope: object, subject_id: object, kind: object) -> AlertStatus | OpsRefusal:
        try:
            if type(kind) is not RuleKind or not _ident(subject_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, subject_id)
            if refusal is not None:
                return refusal
            tenant = scope.tenant_id  # type: ignore[attr-defined]
            key = self._key(scope.company_id, subject_id, kind)  # type: ignore[attr-defined]
            state = self._states.get(tenant, key)
            if type(state) is not _State:
                return self._refuse(OpsReason.NOT_FOUND)
            return AlertStatus(state.phase, state.episode, state.no_data,
                               dropped_count=self._dropped.active(tenant, key),
                               exhausted_count=self._exhausted.active(tenant, key))
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    # ---- events and delivery -------------------------------------------------------------------
    def _records(self, tenant: str, company: str, subject: str | None = None) -> list[_Rec]:
        recs = [v for _, v in self._events.items(tenant)
                if type(v) is _Rec and v.company_id == company and (subject is None or v.event.subject_id == subject)]
        recs.sort(key=lambda r: (r.event.at, r.event.episode, r.event.event_type is EventType.RECOVERED,
                                 r.event.event_id))
        return recs

    def records(self, scope: object, subject_id: object = None) -> tuple[AlertEventRecord, ...] | OpsRefusal:
        """The caller's company events; with ``subject_id`` only that subject's (ownership is checked)."""
        try:
            if subject_id is not None and not _ident(subject_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            refusal = self._check(scope, subject_id)
            if refusal is not None:
                return refusal
            return tuple(AlertEventRecord(r.event, r.delivered, r.attempts, r.parked)
                         for r in self._records(scope.tenant_id, scope.company_id, subject_id))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def events(self, scope: object, subject_id: object = None) -> tuple[AlertEvent, ...] | OpsRefusal:
        recs = self.records(scope, subject_id)
        return recs if type(recs) is OpsRefusal else tuple(r.event for r in recs)

    def undelivered(self, scope: object, subject_id: object = None) -> tuple[AlertEvent, ...] | OpsRefusal:
        """Not delivered yet, parked events included."""
        recs = self.records(scope, subject_id)
        return recs if type(recs) is OpsRefusal else tuple(r.event for r in recs if not r.delivered)

    def deliver_events(self, scope: object) -> AlertDeliveryOutcome | OpsRefusal:
        """Send the caller's company events in order through the BOUND sink, stopping at the first non-final
        failure (order is preserved); an event that used up its attempts is parked and the rest continue."""
        try:
            refusal = self._check(scope, None)
            if refusal is not None:
                return refusal
            tenant, company = scope.tenant_id, scope.company_id  # type: ignore[attr-defined]
            sink = self._sinks.get(tenant)
            if sink is None:
                return self._refuse(OpsReason.DEPENDENCY_FAILED)

            def under_lock() -> AlertDeliveryOutcome:
                delivered = 0
                recs = [r for r in self._records(tenant, company) if not r.delivered and not r.parked]
                for index, rec in enumerate(recs):
                    try:
                        ok = sink.send(rec.event)  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001 - sink text never surfaces
                        ok = False
                    attempts = rec.attempts + 1
                    if ok is not True:
                        parked = attempts >= self._max_attempts
                        self._events.replace(tenant, rec.event.event_id,
                                             _Rec(rec.event, False, attempts, company, parked))
                        if not parked:
                            return self._outcome(delivered, len(recs) - index, tenant, company)
                        continue  # parked: visible, and later events are not blocked behind it
                    self._events.replace(tenant, rec.event.event_id, _Rec(rec.event, True, attempts, company))
                    delivered += 1
                return self._outcome(delivered, 0, tenant, company)

            result = _locked(self._locks, tenant, self._company_key(company, "deliver-events"), under_lock)
            if result is _BUSY:
                return self._refuse(OpsReason.DUPLICATE_SUPPRESSED)
            return result  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            return self._refuse(OpsReason.INTERNAL_REFUSED)

    def _outcome(self, delivered: int, remaining: int, tenant: str, company: str) -> AlertDeliveryOutcome:
        parked = sum(1 for r in self._records(tenant, company) if r.parked and not r.delivered)
        reason = OpsReason.ALERT_DELIVERY_FAILED if (remaining or parked) else None
        return AlertDeliveryOutcome(delivered, remaining, reason,
                                    self._refuse(OpsReason.INTERNAL_REFUSED).correlation_id, parked_count=parked)


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
