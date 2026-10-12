"""Phase 2 sprint S12: the closed error-code registry of section 10 of the interface contract.

Offline and pure. One fixed message and one fixed next action per ``ErrorCode``; the render functions take a
code and nothing else, so no payload content, credential, foreign tenant id or path can be echoed. A value that
is not an ``ErrorCode`` renders as ``SCHEMA_INVALID``. Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = ["ERROR_INFO", "ErrorCode", "ErrorInfo", "NextAction", "Refusal", "render"]


class ErrorCode(StrEnum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    SHAPE_NOT_QUALIFIED = "SHAPE_NOT_QUALIFIED"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    REF_OUT_OF_SCOPE = "REF_OUT_OF_SCOPE"
    NOT_ENTITLED = "NOT_ENTITLED"
    APPROVER_NOT_INDEPENDENT = "APPROVER_NOT_INDEPENDENT"
    APPROVAL_MISSING = "APPROVAL_MISSING"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_VOIDED = "APPROVAL_VOIDED"
    APPROVAL_NONCE_INVALID = "APPROVAL_NONCE_INVALID"
    COMPLETION_PROOF_MISSING = "COMPLETION_PROOF_MISSING"
    ATTRIBUTION_UNPROVEN = "ATTRIBUTION_UNPROVEN"
    PERMIT_MISSING = "PERMIT_MISSING"
    TICKET_SUPERSEDED = "TICKET_SUPERSEDED"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    STALE_VERSION = "STALE_VERSION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    EPOCH_CHANGED = "EPOCH_CHANGED"
    TARGET_REJECTED = "TARGET_REJECTED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    BASE_HOLD = "BASE_HOLD"
    PARENT_NOT_VERIFIED = "PARENT_NOT_VERIFIED"
    CLAIM_EXPIRED = "CLAIM_EXPIRED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CURRENCY_NOT_BUDGETED = "CURRENCY_NOT_BUDGETED"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    CHECKPOINT_UNAVAILABLE = "CHECKPOINT_UNAVAILABLE"
    LOCK_BUSY = "LOCK_BUSY"
    WRITE_REFUSED = "WRITE_REFUSED"
    APPLY_UNKNOWN = "APPLY_UNKNOWN"
    TRIAGE_REQUIRED = "TRIAGE_REQUIRED"
    ROLLBACK_REFUSED = "ROLLBACK_REFUSED"
    VERIFY_FAILED = "VERIFY_FAILED"
    MARKER_UNTRUSTED = "MARKER_UNTRUSTED"
    EVIDENCE_UNSIGNED = "EVIDENCE_UNSIGNED"


class NextAction(StrEnum):
    FIX_REQUEST = "FIX_REQUEST"
    REFRESH_AND_RETRY = "REFRESH_AND_RETRY"
    REQUEST_NEW_APPROVAL = "REQUEST_NEW_APPROVAL"
    RETRY_LATER = "RETRY_LATER"
    CONTACT_APPROVER = "CONTACT_APPROVER"
    CONTACT_OPERATOR = "CONTACT_OPERATOR"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    message: str
    next_action: NextAction


_E, _A = ErrorCode, NextAction
ERROR_INFO: Final = MappingProxyType({
    _E.SCHEMA_INVALID: ErrorInfo("The request is not valid.", _A.FIX_REQUEST),
    _E.SHAPE_NOT_QUALIFIED: ErrorInfo("This document shape is not qualified for governed writes.", _A.FIX_REQUEST),
    _E.SCOPE_MISMATCH: ErrorInfo("The request does not match the authorized scope.", _A.FIX_REQUEST),
    _E.REF_OUT_OF_SCOPE: ErrorInfo("A referenced item is outside the authorized scope.", _A.FIX_REQUEST),
    _E.NOT_ENTITLED: ErrorInfo("The caller is not entitled to perform this operation.", _A.CONTACT_OPERATOR),
    _E.APPROVER_NOT_INDEPENDENT: ErrorInfo("The approval requires an independent person.", _A.CONTACT_APPROVER),
    _E.APPROVAL_MISSING: ErrorInfo("A valid approval is required.", _A.REQUEST_NEW_APPROVAL),
    _E.APPROVAL_EXPIRED: ErrorInfo("The approval has expired.", _A.REQUEST_NEW_APPROVAL),
    _E.APPROVAL_VOIDED: ErrorInfo("The approval is no longer valid.", _A.REQUEST_NEW_APPROVAL),
    _E.APPROVAL_NONCE_INVALID: ErrorInfo("The approval confirmation is not valid.", _A.REQUEST_NEW_APPROVAL),
    _E.COMPLETION_PROOF_MISSING: ErrorInfo("Independent proof that the call finished is missing.",
                                           _A.CONTACT_OPERATOR),
    _E.ATTRIBUTION_UNPROVEN: ErrorInfo("The effect cannot be attributed to this change.", _A.CONTACT_OPERATOR),
    _E.PERMIT_MISSING: ErrorInfo("A valid dispatch permit is required.", _A.REFRESH_AND_RETRY),
    _E.TICKET_SUPERSEDED: ErrorInfo("The ticket was superseded by a newer one.", _A.REFRESH_AND_RETRY),
    _E.DIGEST_MISMATCH: ErrorInfo("The approved content no longer matches.", _A.REQUEST_NEW_APPROVAL),
    _E.STALE_VERSION: ErrorInfo("The target changed since it was approved.", _A.REFRESH_AND_RETRY),
    _E.IDEMPOTENCY_CONFLICT: ErrorInfo("This request id was already used for a different request.", _A.FIX_REQUEST),
    _E.DUPLICATE_SUSPECTED: ErrorInfo("A matching document may already exist.", _A.CONTACT_APPROVER),
    _E.EPOCH_CHANGED: ErrorInfo("Authorization changed since the approval.", _A.REQUEST_NEW_APPROVAL),
    _E.TARGET_REJECTED: ErrorInfo("The target is not accepted for this operation.", _A.FIX_REQUEST),
    _E.KILL_SWITCH_ACTIVE: ErrorInfo("Writes are currently stopped.", _A.RETRY_LATER),
    _E.BASE_HOLD: ErrorInfo("The base is on hold.", _A.CONTACT_OPERATOR),
    _E.PARENT_NOT_VERIFIED: ErrorInfo("The parent change is not verified.", _A.REFRESH_AND_RETRY),
    _E.CLAIM_EXPIRED: ErrorInfo("The claim has expired.", _A.REFRESH_AND_RETRY),
    _E.BUDGET_EXCEEDED: ErrorInfo("The budget does not allow this operation.", _A.CONTACT_OPERATOR),
    _E.CURRENCY_NOT_BUDGETED: ErrorInfo("This currency has no budget grant.", _A.CONTACT_OPERATOR),
    _E.AUDIT_UNAVAILABLE: ErrorInfo("The audit record could not be written.", _A.RETRY_LATER),
    _E.CHECKPOINT_UNAVAILABLE: ErrorInfo("The external checkpoint is unavailable.", _A.RETRY_LATER),
    _E.LOCK_BUSY: ErrorInfo("The target is busy.", _A.RETRY_LATER),
    _E.WRITE_REFUSED: ErrorInfo("The write was refused.", _A.CONTACT_OPERATOR),
    _E.APPLY_UNKNOWN: ErrorInfo("The outcome of the write is unknown.", _A.CONTACT_OPERATOR),
    _E.TRIAGE_REQUIRED: ErrorInfo("A person must resolve this change.", _A.CONTACT_OPERATOR),
    _E.ROLLBACK_REFUSED: ErrorInfo("The rollback was refused.", _A.CONTACT_OPERATOR),
    _E.VERIFY_FAILED: ErrorInfo("Verification of the effect failed.", _A.CONTACT_OPERATOR),
    _E.MARKER_UNTRUSTED: ErrorInfo("The marker is not accepted as evidence.", _A.NO_ACTION),
    _E.EVIDENCE_UNSIGNED: ErrorInfo("The evidence record is not signed or not bound to this change.",
                                    _A.CONTACT_OPERATOR),
})
if (set(ERROR_INFO) != set(ErrorCode) or any(type(i.message) is not str or not i.message or "{" in i.message
                                             or type(i.next_action) is not NextAction
                                             for i in ERROR_INFO.values())):
    # import-time guard: a code added to the closed registry needs one fixed message and next action here
    raise RuntimeError("CHANGE_ERROR_TABLE_INCOMPLETE")


@dataclass(frozen=True, slots=True)
class Refusal:
    """A refusal is a code (and the transition that refused); text comes from the constant table only."""

    code: ErrorCode
    transition: str = ""

    def __post_init__(self) -> None:
        if type(self.code) is not ErrorCode or type(self.transition) is not str or len(self.transition) > 16:
            raise ValueError("REFUSAL_INVALID")

    @property
    def message(self) -> str:
        return ERROR_INFO[self.code].message

    @property
    def next_action(self) -> NextAction:
        return ERROR_INFO[self.code].next_action

    def __repr__(self) -> str:
        return f"Refusal({self.code.value})"


def render(code: object) -> ErrorInfo:
    """Constant text for a code; any other object renders as ``SCHEMA_INVALID``."""
    return ERROR_INFO[code] if type(code) is ErrorCode else ERROR_INFO[ErrorCode.SCHEMA_INVALID]
