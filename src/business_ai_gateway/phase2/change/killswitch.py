"""Phase 2 sprint S12: the kill-switch precedence matrix of section 6 as data plus an evaluator.

Offline and pure. Modes are ordered STOP_ADMIT < STOP_EFFECTS < REVOKE and each includes the previous one.
``KILL_MATRIX`` maps every (subject, mode) pair to one decision; ``evaluate`` adds the switch-OFF case and the
fail-closed rule: an unreadable switch means STOP_EFFECTS. Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .types import KillMode

__all__ = [
    "KILL_MATRIX", "SWITCH_OFF", "KillDecision", "KillSubject", "SwitchReading", "effective_mode", "evaluate",
    "mode_rank",
]


class KillSubject(StrEnum):
    """Every operation or in-flight state that has a row in the section 6 matrix."""

    PROPOSE_VALIDATE_APPROVE = "PROPOSE_VALIDATE_APPROVE"
    CLAIM = "CLAIM"
    CLAIMED_CHANGE = "CLAIMED_CHANGE"
    BEGIN_APPLY_ISSUE_PERMIT = "BEGIN_APPLY_ISSUE_PERMIT"
    APPLYING_NOT_PERMITTED = "APPLYING_NOT_PERMITTED"
    APPLYING_PERMITTED_UNDISPATCHED = "APPLYING_PERMITTED_UNDISPATCHED"
    APPLYING_DISPATCHED = "APPLYING_DISPATCHED"
    APPROVED_UNCLAIMED = "APPROVED_UNCLAIMED"
    OBSERVATION = "OBSERVATION"
    OPERATOR_OPERATIONS = "OPERATOR_OPERATIONS"


class KillDecision(StrEnum):
    PROCEED = "PROCEED"
    REFUSED = "REFUSED"
    RELEASE_T5X = "RELEASE_T5X"
    RELEASE_T5X_VOID_APPROVAL = "RELEASE_T5X_VOID_APPROVAL"
    T6R = "T6R"
    T6C_CANCEL_CAS = "T6C_CANCEL_CAS"
    FOLLOW_CALL_NO_NEW_CALL = "FOLLOW_CALL_NO_NEW_CALL"
    KEPT = "KEPT"
    VOIDED = "VOIDED"
    ALLOWED = "ALLOWED"
    OBSERVATION_OPERATOR_GATED = "OBSERVATION_OPERATOR_GATED"


@dataclass(frozen=True, slots=True)
class SwitchReading:
    """What the authenticated, checkpointed switch read returned. ``available=False`` is the unreadable case."""

    available: bool = False
    mode: KillMode | None = None


SWITCH_OFF: Final = SwitchReading(available=True, mode=None)
_RANK: Final = MappingProxyType({KillMode.STOP_ADMIT: 1, KillMode.STOP_EFFECTS: 2, KillMode.REVOKE: 3})
_S, _D, _M = KillSubject, KillDecision, KillMode


def _row(subject: KillSubject, admit: KillDecision, effects: KillDecision | None = None,
         revoke: KillDecision | None = None) -> dict[tuple[KillSubject, KillMode], KillDecision]:
    return {(subject, _M.STOP_ADMIT): admit, (subject, _M.STOP_EFFECTS): effects or admit,
            (subject, _M.REVOKE): revoke or effects or admit}


KILL_MATRIX: Final = MappingProxyType({
    **_row(_S.PROPOSE_VALIDATE_APPROVE, _D.REFUSED),
    **_row(_S.CLAIM, _D.REFUSED),
    **_row(_S.CLAIMED_CHANGE, _D.RELEASE_T5X, revoke=_D.RELEASE_T5X_VOID_APPROVAL),
    **_row(_S.BEGIN_APPLY_ISSUE_PERMIT, _D.REFUSED),
    **_row(_S.APPLYING_NOT_PERMITTED, _D.T6R),
    **_row(_S.APPLYING_PERMITTED_UNDISPATCHED, _D.T6C_CANCEL_CAS),
    **_row(_S.APPLYING_DISPATCHED, _D.FOLLOW_CALL_NO_NEW_CALL),
    **_row(_S.APPROVED_UNCLAIMED, _D.KEPT, revoke=_D.VOIDED),
    **_row(_S.OBSERVATION, _D.ALLOWED, revoke=_D.OBSERVATION_OPERATOR_GATED),
    **_row(_S.OPERATOR_OPERATIONS, _D.ALLOWED),
})
if set(KILL_MATRIX) != {(s, m) for s in KillSubject for m in KillMode}:
    # import-time guard: every subject has a decision for every mode
    raise RuntimeError("KILL_MATRIX_INCOMPLETE")


def mode_rank(mode: object) -> int:
    """0 for no mode (switch off); 1..3 for STOP_ADMIT..REVOKE; an unknown value ranks as STOP_EFFECTS."""
    if mode is None:
        return 0
    return _RANK.get(mode, _RANK[KillMode.STOP_EFFECTS])  # type: ignore[call-overload]


def effective_mode(reading: object) -> KillMode | None:
    """The mode that applies: an unreadable (or malformed) reading is STOP_EFFECTS, never OFF."""
    if type(reading) is not SwitchReading or reading.available is not True:
        return KillMode.STOP_EFFECTS
    if reading.mode is None:
        return None
    return reading.mode if type(reading.mode) is KillMode else KillMode.STOP_EFFECTS


def evaluate(subject: object, reading: object) -> KillDecision:
    """Decision for ``subject`` under ``reading``; an unknown subject is REFUSED (fail closed)."""
    if type(subject) is not KillSubject:
        return KillDecision.REFUSED
    mode = effective_mode(reading)
    if mode is None:
        return KillDecision.PROCEED
    return KILL_MATRIX[(subject, mode)]
