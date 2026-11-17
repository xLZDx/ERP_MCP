"""Offline synthetic TEST-lane standing-grant policy and CT13 budget ledger.

This model evaluates operation authorization and budget reservations only. It has no persistence,
1C adapter, deployment hook, or runtime authority. Operations outside the frozen S12 write API are
represented only so their CT13 budget effects can be tested; this module does not make them
executable write kinds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from typing import Final

LANE: Final = "TEST"
_IDENT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_CURRENCY: Final = re.compile(r"[A-Z]{3}")


class GrantPolicyError(ValueError):
    """Stable fail-closed error from the offline grant model."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GrantOperation(StrEnum):
    CREATE_DRAFT = "CREATE_DRAFT"
    CONTRACT_UPDATE = "CONTRACT_UPDATE"
    POST = "POST"
    UNPOST = "UNPOST"
    REPOST = "REPOST"
    CORRECTION = "CORRECTION"


class ReservationState(StrEnum):
    RESERVED = "RESERVED"
    UNKNOWN = "UNKNOWN"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class EffectOutcome(StrEnum):
    UNKNOWN = "UNKNOWN"
    EXISTS = "EXISTS"
    PROVEN_ABSENT = "PROVEN_ABSENT"


@dataclass(frozen=True, slots=True)
class StandingGrant:
    grant_id: str
    company_id: str
    currency: str
    amount_limit: Decimal
    create_update_limit: int
    post_unpost_limit: int
    valid_from: datetime
    valid_to: datetime
    allowed_operations: frozenset[GrantOperation]
    revoked: bool = False
    lane: str = LANE
    synthetic: bool = True

    def __post_init__(self) -> None:
        if (not _valid_ident(self.grant_id) or not _valid_ident(self.company_id)
                or type(self.currency) is not str or not _CURRENCY.fullmatch(self.currency)
                or not _valid_amount(self.amount_limit)
                or not _valid_count(self.create_update_limit)
                or not _valid_count(self.post_unpost_limit)
                or not _aware(self.valid_from) or not _aware(self.valid_to)
                or self.valid_to <= self.valid_from
                or type(self.allowed_operations) is not frozenset or not self.allowed_operations
                or any(type(op) is not GrantOperation for op in self.allowed_operations)
                or type(self.revoked) is not bool or self.lane != LANE or self.synthetic is not True):
            raise ValueError("GRANT_INVALID")

    def __repr__(self) -> str:
        return "StandingGrant(<redacted>)"


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    request_id: str
    grant_id: str
    company_id: str
    currency: str
    operation: GrantOperation
    document_id: str
    gross_amount: Decimal
    lane: str = LANE
    synthetic: bool = True

    def __post_init__(self) -> None:
        if (not _valid_ident(self.request_id) or not _valid_ident(self.grant_id)
                or not _valid_ident(self.company_id) or not _valid_ident(self.document_id)
                or type(self.currency) is not str or not _CURRENCY.fullmatch(self.currency)
                or type(self.operation) is not GrantOperation or not _valid_amount(self.gross_amount)
                or self.lane != LANE or self.synthetic is not True):
            raise ValueError("REQUEST_INVALID")


@dataclass(frozen=True, slots=True)
class GrantReservation:
    request: PolicyRequest
    amount: Decimal
    state: ReservationState = ReservationState.RESERVED
    lane: str = LANE
    synthetic: bool = True

    @property
    def grant_id(self) -> str:
        return self.request.grant_id

    @property
    def document_id(self) -> str:
        return self.request.document_id

    @property
    def operation(self) -> GrantOperation:
        return self.request.operation

    def __repr__(self) -> str:
        return f"GrantReservation(request_id={self.request.request_id!r}, state={self.state.value!r})"


@dataclass(frozen=True, slots=True)
class GrantUsage:
    amount_consumed: Decimal
    amount_reserved: Decimal
    create_update_consumed: int
    create_update_reserved: int
    post_unpost_consumed: int
    post_unpost_reserved: int
    remaining_amount: Decimal
    remaining_create_update: int
    remaining_post_unpost: int


_CREATE_UPDATE: Final = frozenset({
    GrantOperation.CREATE_DRAFT, GrantOperation.CONTRACT_UPDATE, GrantOperation.CORRECTION,
})
_POST_UNPOST: Final = frozenset({
    GrantOperation.POST, GrantOperation.UNPOST, GrantOperation.REPOST,
})


class OfflineGrantPolicyEngine:
    """Thread-safe in-memory grant accounting for synthetic CT13 tests only."""

    def __init__(self) -> None:
        self._grants: dict[str, StandingGrant] = {}
        self._reservations: dict[str, GrantReservation] = {}
        self._amount_consumed: dict[tuple[str, str], Decimal] = {}
        self._lock = RLock()

    @staticmethod
    def _require_lane(lane: object) -> None:
        if lane != LANE:
            raise GrantPolicyError("TEST_LANE_REQUIRED")

    def register_grant(self, grant: StandingGrant, *, lane: str) -> None:
        self._require_lane(lane)
        if type(grant) is not StandingGrant or grant.lane != LANE:
            raise GrantPolicyError("GRANT_INVALID")
        with self._lock:
            if grant.grant_id in self._grants:
                raise GrantPolicyError("GRANT_AMBIGUOUS")
            self._grants[grant.grant_id] = grant

    def update_grant(self, grant: StandingGrant, *, lane: str) -> None:
        """Replace current policy facts so later dequeue checks see revocation or changed limits."""
        self._require_lane(lane)
        if type(grant) is not StandingGrant or grant.lane != LANE:
            raise GrantPolicyError("GRANT_INVALID")
        with self._lock:
            if grant.grant_id not in self._grants:
                raise GrantPolicyError("GRANT_NOT_FOUND")
            self._grants[grant.grant_id] = grant

    def reserve(self, request: PolicyRequest, *, now: datetime, lane: str) -> GrantReservation:
        """Atomically check standing rights and reserve amount plus the applicable operation counter."""
        self._require_lane(lane)
        if type(request) is not PolicyRequest or request.lane != LANE or not _aware(now):
            raise GrantPolicyError("REQUEST_INVALID")
        with self._lock:
            prior = self._reservations.get(request.request_id)
            if prior is not None:
                if _request_identity(prior.request) != _request_identity(request):
                    raise GrantPolicyError("IDEMPOTENCY_CONFLICT")
                return prior

            grant = self._require_grant(request)
            self._check_grant(grant, request, now)
            if self._has_active_document_reservation(request.grant_id, request.document_id):
                raise GrantPolicyError("DOCUMENT_RESERVATION_PENDING")
            if (request.operation is GrantOperation.CREATE_DRAFT
                    and self._document_has_consumed_effect(request.grant_id, request.document_id)):
                raise GrantPolicyError("DOCUMENT_ALREADY_EXISTS")
            amount = self._amount_for(request)
            usage = self._usage(grant.grant_id)
            if usage.amount_consumed + usage.amount_reserved + amount > grant.amount_limit:
                code = "GRANT_EXHAUSTED" if usage.remaining_amount <= 0 and amount > 0 else "BUDGET_EXCEEDED"
                raise GrantPolicyError(code)
            create_reserved = usage.create_update_reserved + (1 if request.operation in _CREATE_UPDATE else 0)
            create_consumed = usage.create_update_consumed
            post_reserved = usage.post_unpost_reserved + (1 if request.operation in _POST_UNPOST else 0)
            post_consumed = usage.post_unpost_consumed
            if create_consumed + create_reserved > grant.create_update_limit:
                raise GrantPolicyError("BUDGET_EXCEEDED")
            if post_consumed + post_reserved > grant.post_unpost_limit:
                raise GrantPolicyError("BUDGET_EXCEEDED")
            reservation = GrantReservation(request=request, amount=amount)
            self._reservations[request.request_id] = reservation
            return reservation

    def revalidate_at_dequeue(self, request: PolicyRequest, *, now: datetime, lane: str) -> GrantReservation:
        """Recheck the exact queued request against current grant rights and aggregate budget.

        The caller must supply the request payload observed at dequeue. Comparing it with the
        reserved identity prevents a changed queue payload from borrowing an earlier reservation.
        This returns a policy result only; it does not make an operation executable.
        """
        self._require_lane(lane)
        if type(request) is not PolicyRequest or request.lane != LANE or not _aware(now):
            raise GrantPolicyError("REQUEST_INVALID")
        with self._lock:
            reservation = self._require_reservation(request.request_id)
            if reservation.state is not ReservationState.RESERVED:
                raise GrantPolicyError("RESERVATION_NOT_EXECUTABLE")
            if _request_identity(reservation.request) != _request_identity(request):
                raise GrantPolicyError("DEQUEUE_IDENTITY_MISMATCH")
            grant = self._require_grant(request)
            self._check_grant(grant, request, now)
            usage = self._usage(grant.grant_id)
            if (usage.amount_consumed + usage.amount_reserved > grant.amount_limit
                    or usage.create_update_consumed + usage.create_update_reserved > grant.create_update_limit
                    or usage.post_unpost_consumed + usage.post_unpost_reserved > grant.post_unpost_limit):
                raise GrantPolicyError("BUDGET_CHANGED")
            return reservation

    def mark_unknown(self, request_id: str, *, lane: str) -> GrantReservation:
        """Keep all reserved amount/counters protected until independent outcome evidence resolves them."""
        self._require_lane(lane)
        with self._lock:
            reservation = self._require_reservation(request_id)
            if reservation.state is ReservationState.UNKNOWN:
                return reservation
            if reservation.state is not ReservationState.RESERVED:
                raise GrantPolicyError("RESERVATION_FINAL")
            updated = replace(reservation, state=ReservationState.UNKNOWN)
            self._reservations[request_id] = updated
            return updated

    def resolve_unknown(
        self, request_id: str, *, outcome: EffectOutcome, independently_proven: bool, lane: str,
    ) -> GrantReservation:
        """Settle an unknown reservation only from an independently proven effect/no-effect result."""
        self._require_lane(lane)
        if type(outcome) is not EffectOutcome or outcome is EffectOutcome.UNKNOWN or independently_proven is not True:
            raise GrantPolicyError("OUTCOME_UNRESOLVED")
        with self._lock:
            reservation = self._require_reservation(request_id)
            target = ReservationState.CONSUMED if outcome is EffectOutcome.EXISTS else ReservationState.RELEASED
            if reservation.state in (ReservationState.CONSUMED, ReservationState.RELEASED):
                if reservation.state is target:
                    return reservation
                raise GrantPolicyError("IDEMPOTENCY_CONFLICT")
            if reservation.state is not ReservationState.UNKNOWN:
                raise GrantPolicyError("OUTCOME_NOT_UNKNOWN")
            updated = replace(reservation, state=target)
            self._reservations[request_id] = updated
            if target is ReservationState.CONSUMED and reservation.amount > 0:
                key = (reservation.grant_id, reservation.document_id)
                self._amount_consumed[key] = self._amount_consumed.get(key, Decimal(0)) + reservation.amount
            return updated

    def settle(self, request_id: str, *, outcome: EffectOutcome, lane: str) -> GrantReservation:
        """Settle a still-reserved request after a known outcome; UNKNOWN remains budget-protected."""
        self._require_lane(lane)
        if type(outcome) is not EffectOutcome:
            raise GrantPolicyError("OUTCOME_UNRESOLVED")
        if outcome is EffectOutcome.UNKNOWN:
            return self.mark_unknown(request_id, lane=lane)
        with self._lock:
            reservation = self._require_reservation(request_id)
            target = ReservationState.CONSUMED if outcome is EffectOutcome.EXISTS else ReservationState.RELEASED
            if reservation.state in (ReservationState.CONSUMED, ReservationState.RELEASED):
                if reservation.state is target:
                    return reservation
                raise GrantPolicyError("IDEMPOTENCY_CONFLICT")
            if reservation.state is not ReservationState.RESERVED:
                raise GrantPolicyError("OUTCOME_NOT_UNKNOWN")
            updated = replace(reservation, state=target)
            self._reservations[request_id] = updated
            if target is ReservationState.CONSUMED and reservation.amount > 0:
                key = (reservation.grant_id, reservation.document_id)
                self._amount_consumed[key] = self._amount_consumed.get(key, Decimal(0)) + reservation.amount
            return updated

    def amount_consumed(self, grant_id: str, document_id: str, *, lane: str) -> Decimal:
        self._require_lane(lane)
        if not _valid_ident(grant_id) or not _valid_ident(document_id):
            raise GrantPolicyError("REQUEST_INVALID")
        with self._lock:
            if grant_id not in self._grants:
                raise GrantPolicyError("GRANT_NOT_FOUND")
            return self._amount_consumed.get((grant_id, document_id), Decimal(0))

    def usage(self, grant_id: str, *, lane: str) -> GrantUsage:
        self._require_lane(lane)
        if not _valid_ident(grant_id):
            raise GrantPolicyError("GRANT_INVALID")
        with self._lock:
            grant = self._grants.get(grant_id)
            if grant is None:
                raise GrantPolicyError("GRANT_NOT_FOUND")
            return self._usage(grant_id)

    def reservation(self, request_id: str, *, lane: str) -> GrantReservation:
        self._require_lane(lane)
        with self._lock:
            return self._require_reservation(request_id)

    def _amount_for(self, request: PolicyRequest) -> Decimal:
        if request.operation in (GrantOperation.CONTRACT_UPDATE, GrantOperation.UNPOST, GrantOperation.REPOST):
            return Decimal(0)
        if request.operation is GrantOperation.CREATE_DRAFT:
            return request.gross_amount
        consumed = self._amount_consumed.get((request.grant_id, request.document_id), Decimal(0))
        return max(Decimal(0), request.gross_amount - consumed)

    def _usage(self, grant_id: str) -> GrantUsage:
        grant = self._grants[grant_id]
        rows = [r for r in self._reservations.values() if r.grant_id == grant_id]
        reserved_rows = [r for r in rows if r.state in (ReservationState.RESERVED, ReservationState.UNKNOWN)]
        consumed_rows = [r for r in rows if r.state is ReservationState.CONSUMED]
        amount_consumed = sum(self._amount_consumed.get((grant_id, d), Decimal(0)) for g, d in self._amount_consumed
                              if g == grant_id)
        amount_reserved = sum((r.amount for r in reserved_rows), Decimal(0))
        cu_reserved = sum(r.operation in _CREATE_UPDATE for r in reserved_rows)
        cu_consumed = sum(r.operation in _CREATE_UPDATE for r in consumed_rows)
        pu_reserved = sum(r.operation in _POST_UNPOST for r in reserved_rows)
        pu_consumed = sum(r.operation in _POST_UNPOST for r in consumed_rows)
        return GrantUsage(
            amount_consumed, amount_reserved, cu_consumed, cu_reserved, pu_consumed, pu_reserved,
            grant.amount_limit - amount_consumed - amount_reserved,
            grant.create_update_limit - cu_consumed - cu_reserved,
            grant.post_unpost_limit - pu_consumed - pu_reserved,
        )

    def _has_active_document_reservation(self, grant_id: str, document_id: str) -> bool:
        return any(
            reservation.grant_id == grant_id
            and reservation.document_id == document_id
            and reservation.state in (ReservationState.RESERVED, ReservationState.UNKNOWN)
            for reservation in self._reservations.values()
        )

    def _document_has_consumed_effect(self, grant_id: str, document_id: str) -> bool:
        return any(
            reservation.grant_id == grant_id
            and reservation.document_id == document_id
            and reservation.state is ReservationState.CONSUMED
            for reservation in self._reservations.values()
        )

    def _require_grant(self, request: PolicyRequest) -> StandingGrant:
        grant = self._grants.get(request.grant_id)
        if grant is None:
            raise GrantPolicyError("GRANT_NOT_FOUND")
        return grant

    @staticmethod
    def _check_grant(grant: StandingGrant, request: PolicyRequest, now: datetime) -> None:
        if grant.revoked:
            raise GrantPolicyError("GRANT_REVOKED")
        if (request.company_id != grant.company_id or request.currency != grant.currency):
            raise GrantPolicyError("SCOPE_MISMATCH")
        if request.operation not in grant.allowed_operations:
            raise GrantPolicyError("NOT_ENTITLED")
        if not grant.valid_from <= now < grant.valid_to:
            raise GrantPolicyError("GRANT_EXPIRED")

    def _require_reservation(self, request_id: str) -> GrantReservation:
        if not _valid_ident(request_id):
            raise GrantPolicyError("REQUEST_INVALID")
        reservation = self._reservations.get(request_id)
        if reservation is None:
            raise GrantPolicyError("RESERVATION_NOT_FOUND")
        return reservation


def _request_identity(request: PolicyRequest) -> tuple[object, ...]:
    return (request.grant_id, request.company_id, request.currency, request.operation,
            request.document_id, request.gross_amount)


def _valid_ident(value: object) -> bool:
    return type(value) is str and _IDENT.fullmatch(value) is not None


def _valid_amount(value: object) -> bool:
    return type(value) is Decimal and value.is_finite() and value >= 0


def _valid_count(value: object) -> bool:
    return type(value) is int and value >= 0


def _aware(value: object) -> bool:
    return (type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None)
