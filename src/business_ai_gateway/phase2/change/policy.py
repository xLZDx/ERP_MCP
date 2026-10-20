"""Phase 2 sprint S12: grant/reservation arithmetic (section 8) and the caller-class endpoint matrix (section 2).

Offline and pure. Amounts are ``Decimal``; floats are refused. The reservation state is a deterministic function of
the independently proven effect state (``reservation_for_effect``), never of an operator-chosen label. The endpoint
matrix is closed: ``check_operation`` refuses (with ``NOT_ENTITLED``) every operation not listed for the caller class,
and the internal-only operations are refused for every external class. Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .errors import ErrorCode, Refusal
from .types import CallerClass, HoldCause, Reservation, is_aware_datetime, is_identity_text

__all__ = [
    "CALLER_MATRIX", "EffectState", "Grant", "INTERNAL_OPERATIONS", "LedgerOperation", "amount_to_reserve",
    "authorize_operation", "check_operation", "consume", "ledger_invariant_holds", "release", "release_hold_error",
    "reservation_for_effect", "reserve", "settle_reservation",
]


class LedgerOperation(StrEnum):
    PROPOSE = "PROPOSE"
    VALIDATE = "VALIDATE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CLAIM = "CLAIM"
    RELEASE_CLAIM = "RELEASE_CLAIM"
    BEGIN_APPLY = "BEGIN_APPLY"
    ISSUE_PERMIT = "ISSUE_PERMIT"
    RECORD_CALL = "RECORD_CALL"
    COMPLETE = "COMPLETE"
    RECOVER_SWEEP = "RECOVER_SWEEP"
    RESOLVE_UNKNOWN = "RESOLVE_UNKNOWN"
    OPERATOR_RESOLVE = "OPERATOR_RESOLVE"
    RELEASE_HOLD = "RELEASE_HOLD"
    VERIFY = "VERIFY"
    KILL_SWITCH = "KILL_SWITCH"
    BUDGET_RESERVE = "BUDGET_RESERVE"
    BUDGET_CONSUME = "BUDGET_CONSUME"
    BUDGET_RELEASE = "BUDGET_RELEASE"
    BUDGET_ADMIN = "BUDGET_ADMIN"
    READ_STATUS = "READ_STATUS"
    READ_EVIDENCE = "READ_EVIDENCE"
    READ_OBSERVATION = "READ_OBSERVATION"


_EXPECTED_OPERATIONS: Final = (
    "PROPOSE", "VALIDATE", "APPROVE", "REJECT", "CLAIM", "RELEASE_CLAIM", "BEGIN_APPLY", "ISSUE_PERMIT",
    "RECORD_CALL", "COMPLETE", "RECOVER_SWEEP", "RESOLVE_UNKNOWN", "OPERATOR_RESOLVE", "RELEASE_HOLD", "VERIFY",
    "KILL_SWITCH", "BUDGET_RESERVE", "BUDGET_CONSUME", "BUDGET_RELEASE", "BUDGET_ADMIN", "READ_STATUS",
    "READ_EVIDENCE", "READ_OBSERVATION",
)
if {m.name: m.value for m in LedgerOperation} != {n: n for n in _EXPECTED_OPERATIONS}:
    # import-time guard: the closed operation list equals the contract list
    raise RuntimeError("CHANGE_ENUM_INCOMPLETE")

_O, _C = LedgerOperation, CallerClass
INTERNAL_OPERATIONS: Final = frozenset({_O.ISSUE_PERMIT, _O.BUDGET_RESERVE, _O.BUDGET_CONSUME, _O.BUDGET_RELEASE})
CALLER_MATRIX: Final = MappingProxyType({
    _C.REQUESTER: frozenset({_O.PROPOSE, _O.VALIDATE, _O.CLAIM, _O.RELEASE_CLAIM, _O.BEGIN_APPLY, _O.READ_STATUS}),
    _C.APPROVER: frozenset({_O.APPROVE, _O.REJECT, _O.READ_STATUS}),
    _C.OPERATOR: frozenset({_O.KILL_SWITCH, _O.RELEASE_HOLD, _O.BUDGET_ADMIN, _O.OPERATOR_RESOLVE}),
    _C.RECOVERY_WITNESS: frozenset({_O.OPERATOR_RESOLVE}),
    _C.WRITER: frozenset({_O.COMPLETE, _O.READ_OBSERVATION, _O.RECORD_CALL, _O.BEGIN_APPLY}),
    _C.RECOVERY_WORKER: frozenset({_O.RECOVER_SWEEP, _O.RESOLVE_UNKNOWN, _O.VERIFY, _O.RELEASE_CLAIM, _O.COMPLETE,
                                   _O.READ_OBSERVATION}),
    _C.AUDITOR: frozenset({_O.READ_STATUS, _O.READ_EVIDENCE}),
})
if (set(CALLER_MATRIX) != set(CallerClass)
        or any(INTERNAL_OPERATIONS & ops for ops in CALLER_MATRIX.values())):
    # import-time guard: every class has a row and no external class reaches an internal-only operation
    raise RuntimeError("CALLER_MATRIX_INVALID")


def check_operation(caller: object, operation: object, own_change: bool = True) -> ErrorCode | None:
    """``NOT_ENTITLED`` unless ``operation`` is listed for ``caller``; a requester may begin_apply own changes only."""
    if type(caller) is not CallerClass or type(operation) is not LedgerOperation:
        return ErrorCode.NOT_ENTITLED
    if operation in INTERNAL_OPERATIONS or operation not in CALLER_MATRIX[caller]:
        return ErrorCode.NOT_ENTITLED
    if caller is CallerClass.REQUESTER and operation is LedgerOperation.BEGIN_APPLY and own_change is not True:
        return ErrorCode.NOT_ENTITLED
    return None


def authorize_operation(caller: object, operation: object, own_change: bool = True) -> Refusal | None:
    """The refusing form of ``check_operation``: ``None`` when allowed."""
    code = check_operation(caller, operation, own_change)
    return None if code is None else Refusal(code)


def release_hold_error(cause: object, machine_verified_evidence: bool, completion_proof: bool) -> ErrorCode | None:
    """Section 4/6 ``release_hold``: ANCHOR_GAP and RLC_UNCLEAN need machine-verified release evidence; CALL_OWNERSHIP
    is never released without completion proof; FAILED_VERIFY_HALT is released only by T17, never here."""
    if type(cause) is not HoldCause:
        return ErrorCode.SCHEMA_INVALID
    if cause is HoldCause.CALL_OWNERSHIP:
        return None if completion_proof is True and machine_verified_evidence is True else ErrorCode.COMPLETION_PROOF_MISSING
    if cause is HoldCause.FAILED_VERIFY_HALT:
        return ErrorCode.NOT_ENTITLED
    return None if machine_verified_evidence is True else ErrorCode.EVIDENCE_UNSIGNED


# ---- reservation state as a function of the proven effect state (section 8) -------------------------------

class EffectState(StrEnum):
    PROVEN_ABSENT = "PROVEN_ABSENT"
    EXISTS = "EXISTS"
    UNKNOWN = "UNKNOWN"


def reservation_for_effect(effect: object) -> Reservation | None:
    """RELEASED for a proven no-effect, CONSUMED for an existing effect, ``None`` (KEPT) while the effect is unknown."""
    if effect is EffectState.PROVEN_ABSENT:
        return Reservation.RELEASED
    if effect is EffectState.EXISTS:
        return Reservation.CONSUMED
    return None


def settle_reservation(current: object, target: object) -> Reservation:
    """CONSUMED and RELEASED are final: a repeated resolution cannot change them (section 8, repeated operator_resolve)."""
    if type(current) is not Reservation or type(target) is not Reservation:
        raise ValueError("RESERVATION_INVALID")
    if current in (Reservation.CONSUMED, Reservation.RELEASED):
        return current
    if current is Reservation.NONE and target is not Reservation.RESERVED:
        return current
    return target


# ---- grant arithmetic ----------------------------------------------------------------------------------------

def _amount_ok(value: object) -> bool:
    return type(value) is Decimal and value.is_finite() and value >= 0


@dataclass(frozen=True, slots=True)
class Grant:
    """A budget grant: ``reserved + consumed <= limit`` always; the window is checked at claim only (CT13)."""

    grant_id: str
    currency: str
    limit: Decimal
    valid_from: datetime
    valid_to: datetime
    reserved: Decimal = Decimal(0)
    consumed: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if (not is_identity_text(self.grant_id, 64) or not is_identity_text(self.currency, 8)
                or not all(_amount_ok(v) for v in (self.limit, self.reserved, self.consumed))
                or not is_aware_datetime(self.valid_from) or not is_aware_datetime(self.valid_to)
                or self.valid_to <= self.valid_from or self.reserved + self.consumed > self.limit):
            raise ValueError("GRANT_INVALID")

    def __repr__(self) -> str:
        return "Grant(<redacted>)"


def amount_to_reserve(document_amount: object, amount_consumed: object) -> Decimal:
    """POST: only the unconsumed part of the document amount is reserved (``amount_consumed`` read in the claim tx)."""
    if not _amount_ok(document_amount) or not _amount_ok(amount_consumed):
        raise ValueError("AMOUNT_INVALID")
    return max(Decimal(0), document_amount - amount_consumed)  # type: ignore[operator]


def reserve(grant: object, amount: object, currency: object, now: object) -> Grant | ErrorCode:
    """Reserve ``amount`` at claim time: currency must match, the window must contain ``now``, the limit must hold."""
    if type(grant) is not Grant or not _amount_ok(amount) or not is_aware_datetime(now):
        return ErrorCode.SCHEMA_INVALID
    if currency != grant.currency:
        return ErrorCode.CURRENCY_NOT_BUDGETED
    if not grant.valid_from <= now < grant.valid_to:  # type: ignore[operator]
        return ErrorCode.BUDGET_EXCEEDED
    if grant.reserved + grant.consumed + amount > grant.limit:  # type: ignore[operator]
        return ErrorCode.BUDGET_EXCEEDED
    return replace(grant, reserved=grant.reserved + amount)  # type: ignore[operator]


def consume(grant: object, amount: object) -> Grant | ErrorCode:
    """Move ``amount`` from reserved to consumed (an effect exists)."""
    if type(grant) is not Grant or not _amount_ok(amount) or amount > grant.reserved:  # type: ignore[operator]
        return ErrorCode.SCHEMA_INVALID
    return replace(grant, reserved=grant.reserved - amount, consumed=grant.consumed + amount)  # type: ignore[operator]


def release(grant: object, amount: object) -> Grant | ErrorCode:
    """Drop ``amount`` from reserved (proven no-effect)."""
    if type(grant) is not Grant or not _amount_ok(amount) or amount > grant.reserved:  # type: ignore[operator]
        return ErrorCode.SCHEMA_INVALID
    return replace(grant, reserved=grant.reserved - amount)  # type: ignore[operator]


def ledger_invariant_holds(grant: object, live_reserved: object, live_consumed: object) -> bool:
    """Ledger-wide invariant: the grant's reserved and consumed totals equal the sums over the live change states."""
    return (type(grant) is Grant and _amount_ok(live_reserved) and _amount_ok(live_consumed)
            and grant.reserved == live_reserved and grant.consumed == live_consumed)  # type: ignore[union-attr]
