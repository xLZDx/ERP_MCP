"""Phase 2 sprint S12 (governed purchase-receipt write): closed vocabularies and the change record.

Offline and pure (stdlib only). Implements section 1 and section 4 of the S12 interface contract
(revision 6): the closed enums of every stored dimension, the scope tuple, holds, the repair authorization
record and the ``ChangeRecord`` that ``transitions.apply_transition`` evolves. Every enum is closed by an
import-time completeness guard: adding or removing a member without updating the literal list below raises
at import. Authority is ``EVALUATION_ONLY``; nothing here performs I/O or calls 1C.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

__all__ = [
    "ApprovalType", "Attribution", "BudgetCheck", "CallOwnership", "CallerClass", "ChangeKind",
    "ChangeRecord", "Dispatch", "EffectKnown", "EvidenceKind", "Execution", "FailureStage", "Hold", "HoldCause",
    "KillMode", "Lifecycle", "NonceState", "ProofClass", "RepairAuth", "Reservation", "Scope", "TokenState",
    "Verification", "Authorization", "is_aware_datetime", "is_identity_text",
]

MAX_IDENTITY_CHARS: Final = 200


class Lifecycle(StrEnum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    EXPIRED_QUEUED = "EXPIRED_QUEUED"
    DUPLICATE_PARKED = "DUPLICATE_PARKED"


class Authorization(StrEnum):
    NONE = "NONE"
    APPROVED = "APPROVED"
    CLAIMED = "CLAIMED"
    VOIDED = "VOIDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Execution(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    APPLYING = "APPLYING"
    APPLY_UNKNOWN = "APPLY_UNKNOWN"
    APPLIED = "APPLIED"
    FAILED_APPLY = "FAILED_APPLY"
    TRIAGE_REQUIRED = "TRIAGE_REQUIRED"
    ROLLBACK_REFUSED = "ROLLBACK_REFUSED"


class Verification(StrEnum):
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    FAILED_VERIFY = "FAILED_VERIFY"


class CallOwnership(StrEnum):
    NONE = "NONE"
    PROVEN_FINISHED = "PROVEN_FINISHED"
    POSSIBLY_EXECUTING = "POSSIBLY_EXECUTING"


class Attribution(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PROVEN = "PROVEN"
    UNPROVEN_OPERATOR_ATTESTED = "UNPROVEN_OPERATOR_ATTESTED"


class EffectKnown(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class Reservation(StrEnum):
    NONE = "NONE"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class Dispatch(StrEnum):
    NOT_PERMITTED = "NOT_PERMITTED"
    PERMITTED = "PERMITTED"
    CANCELLED_UNDISPATCHED = "CANCELLED_UNDISPATCHED"
    DISPATCHED = "DISPATCHED"


class HoldCause(StrEnum):
    CALL_OWNERSHIP = "CALL_OWNERSHIP"
    ANCHOR_GAP = "ANCHOR_GAP"
    FAILED_VERIFY_HALT = "FAILED_VERIFY_HALT"
    RLC_UNCLEAN = "RLC_UNCLEAN"


class CallerClass(StrEnum):
    REQUESTER = "REQUESTER"
    APPROVER = "APPROVER"
    OPERATOR = "OPERATOR"
    RECOVERY_WITNESS = "RECOVERY_WITNESS"
    WRITER = "WRITER"
    RECOVERY_WORKER = "RECOVERY_WORKER"
    AUDITOR = "AUDITOR"


class ChangeKind(StrEnum):
    CREATE_DRAFT = "CREATE_DRAFT"
    UPDATE_DRAFT = "UPDATE_DRAFT"
    POST = "POST"
    UNPOST = "UNPOST"


class KillMode(StrEnum):
    """Ordered STOP_ADMIT < STOP_EFFECTS < REVOKE (see ``killswitch.mode_rank``)."""

    STOP_ADMIT = "STOP_ADMIT"
    STOP_EFFECTS = "STOP_EFFECTS"
    REVOKE = "REVOKE"


class TokenState(StrEnum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class ApprovalType(StrEnum):
    HUMAN = "HUMAN"
    TEST_LANE_AUTO = "TEST_LANE_AUTO"


class NonceState(StrEnum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"


class ProofClass(StrEnum):
    """Proof classes for PROVEN_FINISHED (section 4): only the first two are independent proofs."""

    NONE = "NONE"
    WRITER_COMPLETION = "WRITER_COMPLETION"
    SESSION_END_OBSERVED = "SESSION_END_OBSERVED"
    FORCED_TERMINATION = "FORCED_TERMINATION"


class FailureStage(StrEnum):
    PRE_WRITE = "PRE_WRITE"
    WRITE_STARTED = "WRITE_STARTED"
    UNCLASSIFIED = "UNCLASSIFIED"


class EvidenceKind(StrEnum):
    FIELD = "FIELD"
    MOVEMENT = "MOVEMENT"
    VERSION = "VERSION"
    AUTHORIZATION_RECEIPT = "AUTHORIZATION_RECEIPT"


class BudgetCheck(StrEnum):
    OK = "OK"
    EXCEEDED = "EXCEEDED"
    CURRENCY_NOT_BUDGETED = "CURRENCY_NOT_BUDGETED"
    NOT_CHECKED = "NOT_CHECKED"


_EXPECTED: Final = (
    (Lifecycle, ("PROPOSED", "VALIDATED", "REJECTED", "EXPIRED_QUEUED", "DUPLICATE_PARKED")),
    (Authorization, ("NONE", "APPROVED", "CLAIMED", "VOIDED", "REVOKED", "EXPIRED")),
    (Execution, ("NOT_STARTED", "APPLYING", "APPLY_UNKNOWN", "APPLIED", "FAILED_APPLY", "TRIAGE_REQUIRED",
                 "ROLLBACK_REFUSED")),
    (Verification, ("NOT_VERIFIED", "VERIFIED", "FAILED_VERIFY")),
    (CallOwnership, ("NONE", "PROVEN_FINISHED", "POSSIBLY_EXECUTING")),
    (Attribution, ("NOT_APPLICABLE", "PROVEN", "UNPROVEN_OPERATOR_ATTESTED")),
    (EffectKnown, ("YES", "NO", "UNKNOWN")),
    (Reservation, ("NONE", "RESERVED", "CONSUMED", "RELEASED")),
    (Dispatch, ("NOT_PERMITTED", "PERMITTED", "CANCELLED_UNDISPATCHED", "DISPATCHED")),
    (HoldCause, ("CALL_OWNERSHIP", "ANCHOR_GAP", "FAILED_VERIFY_HALT", "RLC_UNCLEAN")),
    (CallerClass, ("REQUESTER", "APPROVER", "OPERATOR", "RECOVERY_WITNESS", "WRITER", "RECOVERY_WORKER",
                   "AUDITOR")),
    (ChangeKind, ("CREATE_DRAFT", "UPDATE_DRAFT", "POST", "UNPOST")),
    (KillMode, ("STOP_ADMIT", "STOP_EFFECTS", "REVOKE")),
    (TokenState, ("NONE", "ISSUED", "CONSUMED", "SUPERSEDED", "REVOKED")),
    (ApprovalType, ("HUMAN", "TEST_LANE_AUTO")),
    (NonceState, ("ISSUED", "CONSUMED", "EXPIRED", "INVALID")),
    (ProofClass, ("NONE", "WRITER_COMPLETION", "SESSION_END_OBSERVED", "FORCED_TERMINATION")),
    (FailureStage, ("PRE_WRITE", "WRITE_STARTED", "UNCLASSIFIED")),
    (EvidenceKind, ("FIELD", "MOVEMENT", "VERSION", "AUTHORIZATION_RECEIPT")),
    (BudgetCheck, ("OK", "EXCEEDED", "CURRENCY_NOT_BUDGETED", "NOT_CHECKED")),
)
for _cls, _names in _EXPECTED:
    # import-time guard: the closed vocabulary must equal the contract list exactly
    if {m.name: m.value for m in _cls} != {n: n for n in _names}:
        raise RuntimeError("CHANGE_ENUM_INCOMPLETE")


def is_identity_text(value: object, max_chars: int = MAX_IDENTITY_CHARS) -> bool:
    """Exact ``str``, non-empty, printable, without whitespace or control characters, bounded length."""
    return (type(value) is str and 0 < len(value) <= max_chars and value.isprintable()
            and not any(c.isspace() for c in value))


def is_aware_datetime(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class Scope:
    """The scope tuple (tenant, company, organization, base_fingerprint); immutable for the life of a change (I15)."""

    tenant: str
    company: str
    organization: str
    base_fingerprint: str

    def __post_init__(self) -> None:
        if not all(is_identity_text(v) for v in (self.tenant, self.company, self.organization,
                                                self.base_fingerprint)):
            raise ValueError("SCOPE_INVALID")

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.tenant, self.company, self.organization, self.base_fingerprint)

    def __repr__(self) -> str:
        return "Scope(<redacted>)"


@dataclass(frozen=True, slots=True)
class Hold:
    """A durable hold row; ``released`` is the only mutable-looking attribute (a release makes a new value)."""

    hold_id: str
    cause: HoldCause
    change_id: str
    target_ref: str | None = None
    observed_version: str | None = None
    released: bool = False

    def __post_init__(self) -> None:
        if (not is_identity_text(self.hold_id) or type(self.cause) is not HoldCause
                or not is_identity_text(self.change_id) or type(self.released) is not bool
                or (self.target_ref is not None and not is_identity_text(self.target_ref))
                or (self.observed_version is not None and not is_identity_text(self.observed_version))):
            raise ValueError("HOLD_INVALID")


@dataclass(frozen=True, slots=True)
class RepairAuth:
    """The typed repair authorization record R of section 4.2."""

    repair_change_id: str
    repair_for: str
    target_ref: str
    observed_version: str
    halt_id: str
    approval_id: str
    claim_generation: int

    def __post_init__(self) -> None:
        if (not all(is_identity_text(v) for v in (self.repair_change_id, self.repair_for, self.target_ref,
                                                  self.observed_version, self.halt_id, self.approval_id))
                or type(self.claim_generation) is not int or self.claim_generation < 1):
            raise ValueError("REPAIR_AUTH_INVALID")


_ENUM_FIELDS: Final = (
    ("kind", ChangeKind), ("lifecycle", Lifecycle), ("authorization", Authorization), ("execution", Execution),
    ("verification", Verification), ("call_ownership", CallOwnership), ("attribution", Attribution),
    ("reservation", Reservation), ("dispatch", Dispatch), ("token", TokenState),
)
_BOOL_FIELDS: Final = ("has_duplicate_override", "parent_attribution_unproven", "target_lock", "key_lock", "lease",
                       "closed")
_OPT_TEXT_FIELDS: Final = ("parent_change_id", "target_ref", "approver_person_id", "approval_id", "repair_for",
                           "superseded_by")
_OPT_TIME_FIELDS: Final = ("expires_at", "claim_expires_at", "permit_expires_at", "first_attempt_at")


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    """One change with every stored dimension of section 4 (the lifecycle is not the whole state).

    ``target_lock`` / ``key_lock`` / ``lease`` say whether THIS change currently owns the (base, target) lock,
    the (base, business-key-hash) lock and the base writer lease (section 4.1). Holds are NOT stored here.
    """

    change_id: str
    kind: ChangeKind
    scope: Scope
    requester_person_id: str
    lifecycle: Lifecycle = Lifecycle.PROPOSED
    authorization: Authorization = Authorization.NONE
    execution: Execution = Execution.NOT_STARTED
    verification: Verification = Verification.NOT_VERIFIED
    call_ownership: CallOwnership = CallOwnership.NONE
    attribution: Attribution = Attribution.NOT_APPLICABLE
    effect_known: EffectKnown | None = None
    reservation: Reservation = Reservation.NONE
    dispatch: Dispatch = Dispatch.NOT_PERMITTED
    token: TokenState = TokenState.NONE
    claim_generation: int = 0
    parent_change_id: str | None = None
    target_ref: str | None = None
    has_duplicate_override: bool = False
    parent_attribution_unproven: bool = False
    approver_person_id: str | None = None
    approval_id: str | None = None
    approval_type: ApprovalType | None = None
    expires_at: datetime | None = None
    claim_expires_at: datetime | None = None
    permit_expires_at: datetime | None = None
    target_lock: bool = False
    key_lock: bool = False
    lease: bool = False
    lock_busy_attempts: int = 0
    first_attempt_at: datetime | None = None
    verify_attempts: int = 0
    repair_for: str | None = None
    repair: RepairAuth | None = None
    superseded_by: str | None = None
    closed: bool = False

    def __post_init__(self) -> None:
        ok = (is_identity_text(self.change_id) and is_identity_text(self.requester_person_id)
              and type(self.scope) is Scope
              and all(type(getattr(self, n)) is c for n, c in _ENUM_FIELDS)
              and (self.effect_known is None or type(self.effect_known) is EffectKnown)
              and (self.approval_type is None or type(self.approval_type) is ApprovalType)
              and all(type(getattr(self, n)) is bool for n in _BOOL_FIELDS)
              and all(getattr(self, n) is None or is_identity_text(getattr(self, n)) for n in _OPT_TEXT_FIELDS)
              and all(getattr(self, n) is None or is_aware_datetime(getattr(self, n)) for n in _OPT_TIME_FIELDS)
              and all(type(getattr(self, n)) is int and getattr(self, n) >= 0
                      for n in ("claim_generation", "lock_busy_attempts", "verify_attempts"))
              and (self.repair is None or type(self.repair) is RepairAuth))
        if not ok:
            raise ValueError("CHANGE_RECORD_INVALID")

    def __repr__(self) -> str:
        return "ChangeRecord(<redacted>)"
