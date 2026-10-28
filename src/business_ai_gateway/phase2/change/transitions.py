"""Phase 2 sprint S12: the transition table T1..T17 of sections 4, 4.1 and 4.2 as data plus a pure engine.

Offline and pure (stdlib only, no clock, no I/O). ``TRANSITION_TABLE`` lists every transition (id, event, required
source dimensions, target, ordered guard names); ``LOCK_MATRIX`` is the lock/lease/hold/reservation matrix of 4.1;
``FORBIDDEN_TRANSITIONS`` is the literal list of section 4. ``apply_transition(record, event, evidence)`` evaluates
every guard from the explicit ``evidence`` (typed per event, every field defaults to the failing value) and returns
``Applied(record, effects)`` or a code-only ``Refusal``; it never raises and never mutates its inputs. ``effects`` are
the ledger-level consequences a pure function cannot perform itself (open/release a hold, hand a lock to or back from
a repair, mint a token, alert). The repair authorization of 4.2 is one function, ``repair_authorization_error``,
evaluated identically at T5, T6, the dispatch permit and the writer boundary. Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .errors import ErrorCode, Refusal
from .killswitch import SwitchReading, effective_mode
from .proposal import ChangeProposal
from .types import (
    ApprovalType,
    Attribution,
    Authorization,
    BudgetCheck,
    CallerClass,
    CallOwnership,
    ChangeKind,
    ChangeRecord,
    Dispatch,
    EffectKnown,
    EvidenceKind,
    Execution,
    FailureStage,
    Hold,
    HoldCause,
    KillMode,
    Lifecycle,
    NonceState,
    ProofClass,
    RepairAuth,
    Reservation,
    TokenState,
    Verification,
    is_aware_datetime,
    is_identity_text,
)

__all__ = [
    "EVENT_EVIDENCE",
    "FORBIDDEN_TRANSITIONS",
    "LOCK_MATRIX",
    "TRANSITION_TABLE",
    "Applied",
    "ApproveEvidence",
    "BeginApplyEvidence",
    "BusinessKeyState",
    "CallUnknownEvidence",
    "CancelPermitEvidence",
    "ClaimEvidence",
    "CompletionEvidence",
    "DispatchEvidence",
    "EffectKind",
    "Event",
    "Evidence",
    "ExpireEvidence",
    "ForbiddenTransition",
    "HoldAction",
    "LockAction",
    "LockRow",
    "LogicalKeyState",
    "OperatorResolveEvidence",
    "PermitEvidence",
    "PermitNotIssuedEvidence",
    "ProposeEvidence",
    "RejectEvidence",
    "ReleaseClaimEvidence",
    "ReleaseReason",
    "RepairContext",
    "RepairPhase",
    "ResolveEvidence",
    "ResolveOutcome",
    "RetryVerifyEvidence",
    "RevokeCause",
    "RevokeEvidence",
    "TransitionRow",
    "ValidateEvidence",
    "VerifyEvidence",
    "apply_transition",
    "classify_completion",
    "forbidden_transition",
    "repair_authorization_error",
]

CLAIM_TTL: Final = timedelta(seconds=120)
PERMIT_TTL: Final = timedelta(seconds=60)
LOCK_BUSY_MAX_ATTEMPTS: Final = 5
LOCK_BUSY_WINDOW: Final = timedelta(minutes=15)
RESOLVE_MAX_ATTEMPTS: Final = 5
RESOLVE_WINDOW: Final = timedelta(minutes=15)
VERIFY_RETRY_BOUND: Final = 3
_DRAFT_KINDS: Final = (ChangeKind.CREATE_DRAFT, ChangeKind.UPDATE_DRAFT)
_INDEPENDENT_PROOFS: Final = (ProofClass.WRITER_COMPLETION, ProofClass.SESSION_END_OBSERVED)
_REQUIRED_VERIFY_KINDS: Final = frozenset({EvidenceKind.FIELD, EvidenceKind.MOVEMENT, EvidenceKind.VERSION})
_WRITER_REFUSAL_CODES: Final = frozenset({ErrorCode.STALE_VERSION, ErrorCode.LOCK_BUSY, ErrorCode.DUPLICATE_SUSPECTED,
                                          ErrorCode.ROLLBACK_REFUSED, ErrorCode.WRITE_REFUSED})


# ---- vocabularies of this module ----------------------------------------------------------------------------

class Event(StrEnum):
    PROPOSE = "PROPOSE"
    VALIDATE = "VALIDATE"
    REJECT = "REJECT"
    EXPIRE = "EXPIRE"
    APPROVE = "APPROVE"
    CLAIM = "CLAIM"
    RELEASE_CLAIM = "RELEASE_CLAIM"
    BEGIN_APPLY = "BEGIN_APPLY"
    ISSUE_PERMIT = "ISSUE_PERMIT"
    MARK_DISPATCHED = "MARK_DISPATCHED"
    PERMIT_NOT_ISSUED = "PERMIT_NOT_ISSUED"
    CANCEL_PERMIT = "CANCEL_PERMIT"
    CALL_SUCCESS = "CALL_SUCCESS"
    REFUSED_BEFORE_WRITE = "REFUSED_BEFORE_WRITE"
    CALL_UNKNOWN = "CALL_UNKNOWN"
    RESOLVE_FOUND = "RESOLVE_FOUND"
    RESOLVE_ABSENT = "RESOLVE_ABSENT"
    AGE_LIMIT = "AGE_LIMIT"
    VERIFY_OK = "VERIFY_OK"
    VERIFY_FAILED = "VERIFY_FAILED"
    REVOKE = "REVOKE"
    OPERATOR_RESOLVE = "OPERATOR_RESOLVE"
    RETRY_VERIFY = "RETRY_VERIFY"
    CLOSE_FAILED_VERIFY = "CLOSE_FAILED_VERIFY"


class EffectKind(StrEnum):
    """Ledger-level consequences returned with a new record (a pure function cannot perform them)."""

    REPLAY_EARLIER_RECEIPT = "REPLAY_EARLIER_RECEIPT"
    REPLAY_EXISTING_TICKET = "REPLAY_EXISTING_TICKET"
    CONSUME_NONCE = "CONSUME_NONCE"
    RESERVE_BUDGET = "RESERVE_BUDGET"
    MINT_CLAIM_TOKEN = "MINT_CLAIM_TOKEN"
    ACQUIRE_LOCKS = "ACQUIRE_LOCKS"
    HAND_LOCK_TO_REPAIR = "HAND_LOCK_TO_REPAIR"
    HAND_LOCK_BACK_TO_PARENT = "HAND_LOCK_BACK_TO_PARENT"
    INVALIDATE_REPAIR_AUTH = "INVALIDATE_REPAIR_AUTH"
    COMMIT_APPLYING_AND_OWNERSHIP_ROW = "COMMIT_APPLYING_AND_OWNERSHIP_ROW"
    SIGN_PERMIT = "SIGN_PERMIT"
    INVALIDATE_PERMIT = "INVALIDATE_PERMIT"
    RECORD_DISPATCHED = "RECORD_DISPATCHED"
    OPEN_HOLD_CALL_OWNERSHIP = "OPEN_HOLD_CALL_OWNERSHIP"
    RELEASE_HOLD_CALL_OWNERSHIP = "RELEASE_HOLD_CALL_OWNERSHIP"
    OPEN_HOLD_FAILED_VERIFY_HALT = "OPEN_HOLD_FAILED_VERIFY_HALT"
    RELEASE_HOLD_FAILED_VERIFY_HALT = "RELEASE_HOLD_FAILED_VERIFY_HALT"
    ALERT_HUMAN = "ALERT_HUMAN"
    MARK_PARENT_SUPERSEDED = "MARK_PARENT_SUPERSEDED"
    RECONCILE_AMOUNT_CONSUMED = "RECONCILE_AMOUNT_CONSUMED"


class LogicalKeyState(StrEnum):
    UNUSED = "UNUSED"
    SAME_DIGEST = "SAME_DIGEST"
    OTHER_DIGEST = "OTHER_DIGEST"


class BusinessKeyState(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    FREE = "FREE"
    COLLISION = "COLLISION"


class ReleaseReason(StrEnum):
    TTL_EXPIRED = "TTL_EXPIRED"
    KILL_SWITCH = "KILL_SWITCH"
    T6_GUARD_FAILED = "T6_GUARD_FAILED"


class RevokeCause(StrEnum):
    SESSION_REVOKED = "SESSION_REVOKED"
    ROLE_REVOKED = "ROLE_REVOKED"
    APPROVER_REVOKED = "APPROVER_REVOKED"
    EPOCH_DEPENDENCY_CHANGED = "EPOCH_DEPENDENCY_CHANGED"
    KILL_SWITCH_REVOKE = "KILL_SWITCH_REVOKE"


class ResolveOutcome(StrEnum):
    PRESENT_ATTRIBUTED = "PRESENT_ATTRIBUTED"
    PRESENT_UNATTRIBUTED = "PRESENT_UNATTRIBUTED"
    ABSENT = "ABSENT"


class RepairPhase(StrEnum):
    CLAIM = "CLAIM"
    BEGIN_APPLY = "BEGIN_APPLY"
    PERMIT = "PERMIT"
    WRITER = "WRITER"


class LockAction(StrEnum):
    ACQUIRE = "ACQUIRE"
    KEEP = "KEEP"
    RELEASE = "RELEASE"
    HANDOFF = "HANDOFF"
    NA = "NA"


class HoldAction(StrEnum):
    NONE = "NONE"
    OPEN_CALL_OWNERSHIP = "OPEN_CALL_OWNERSHIP"
    KEEP_CALL_OWNERSHIP = "KEEP_CALL_OWNERSHIP"
    RELEASE_CALL_OWNERSHIP = "RELEASE_CALL_OWNERSHIP"
    OPEN_FAILED_VERIFY_HALT = "OPEN_FAILED_VERIFY_HALT"
    RELEASE_FAILED_VERIFY_HALT = "RELEASE_FAILED_VERIFY_HALT"


_EXPECTED_ENUMS: Final = (
    (Event, ("PROPOSE", "VALIDATE", "REJECT", "EXPIRE", "APPROVE", "CLAIM", "RELEASE_CLAIM", "BEGIN_APPLY",
             "ISSUE_PERMIT", "MARK_DISPATCHED", "PERMIT_NOT_ISSUED", "CANCEL_PERMIT", "CALL_SUCCESS",
             "REFUSED_BEFORE_WRITE", "CALL_UNKNOWN", "RESOLVE_FOUND", "RESOLVE_ABSENT", "AGE_LIMIT", "VERIFY_OK",
             "VERIFY_FAILED", "REVOKE", "OPERATOR_RESOLVE", "RETRY_VERIFY", "CLOSE_FAILED_VERIFY")),
    (EffectKind, ("REPLAY_EARLIER_RECEIPT", "REPLAY_EXISTING_TICKET", "CONSUME_NONCE", "RESERVE_BUDGET",
                  "MINT_CLAIM_TOKEN", "ACQUIRE_LOCKS", "HAND_LOCK_TO_REPAIR", "HAND_LOCK_BACK_TO_PARENT",
                  "INVALIDATE_REPAIR_AUTH", "COMMIT_APPLYING_AND_OWNERSHIP_ROW", "SIGN_PERMIT", "INVALIDATE_PERMIT",
                  "RECORD_DISPATCHED", "OPEN_HOLD_CALL_OWNERSHIP", "RELEASE_HOLD_CALL_OWNERSHIP",
                  "OPEN_HOLD_FAILED_VERIFY_HALT", "RELEASE_HOLD_FAILED_VERIFY_HALT", "ALERT_HUMAN",
                  "MARK_PARENT_SUPERSEDED", "RECONCILE_AMOUNT_CONSUMED")),
    (LogicalKeyState, ("UNUSED", "SAME_DIGEST", "OTHER_DIGEST")),
    (BusinessKeyState, ("NOT_CHECKED", "FREE", "COLLISION")),
    (ReleaseReason, ("TTL_EXPIRED", "KILL_SWITCH", "T6_GUARD_FAILED")),
    (RevokeCause, ("SESSION_REVOKED", "ROLE_REVOKED", "APPROVER_REVOKED", "EPOCH_DEPENDENCY_CHANGED",
                   "KILL_SWITCH_REVOKE")),
    (ResolveOutcome, ("PRESENT_ATTRIBUTED", "PRESENT_UNATTRIBUTED", "ABSENT")),
    (RepairPhase, ("CLAIM", "BEGIN_APPLY", "PERMIT", "WRITER")),
    (LockAction, ("ACQUIRE", "KEEP", "RELEASE", "HANDOFF", "NA")),
    (HoldAction, ("NONE", "OPEN_CALL_OWNERSHIP", "KEEP_CALL_OWNERSHIP", "RELEASE_CALL_OWNERSHIP",
                  "OPEN_FAILED_VERIFY_HALT", "RELEASE_FAILED_VERIFY_HALT")),
)
for _cls, _names in _EXPECTED_ENUMS:
    # import-time guard: the closed vocabulary must equal the literal list
    if {m.name: m.value for m in _cls} != {n: n for n in _names}:
        raise RuntimeError("CHANGE_ENUM_INCOMPLETE")


# ---- results -------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Applied:
    """A successful transition: the new record (``None`` only for the idempotent propose replay) and its effects."""

    record: ChangeRecord | None
    effects: tuple[EffectKind, ...] = ()
    transition: str = ""


# ---- evidence (explicit inputs of every guard; every field defaults to the failing value) -----------------------

@dataclass(frozen=True, slots=True)
class Evidence:
    now: datetime | None = None
    kill: SwitchReading = field(default_factory=SwitchReading)  # unreadable by default: STOP_EFFECTS


@dataclass(frozen=True, slots=True)
class RepairContext:
    """Live facts the ledger reads for the repair authorization of section 4.2 (fail-closed defaults)."""

    parent_change_id: str = ""
    parent_verification: Verification = Verification.NOT_VERIFIED
    parent_effect_known: EffectKnown | None = None
    parent_requester_person_id: str = ""
    halt: Hold | None = None
    current_target_ref: str = ""
    current_version: str = ""
    approval_fresh: bool = False
    approval_revoked: bool = True
    other_repair_exists: bool = True
    target_lock_owner: str | None = None


@dataclass(frozen=True, slots=True)
class ProposeEvidence(Evidence):
    proposal: ChangeProposal | None = None
    schema_valid: bool = False
    scope_resolved: bool = False
    requester_entitled: bool = False
    epoch_read: bool = False
    logical_key: LogicalKeyState = LogicalKeyState.UNUSED
    parent_attribution_unproven: bool = False


@dataclass(frozen=True, slots=True)
class ValidateEvidence(Evidence):
    preview_built: bool = False
    shape_qualified: bool = False
    allowed_effects_derived: bool = False
    budget: BudgetCheck = BudgetCheck.NOT_CHECKED
    key_state: BusinessKeyState = BusinessKeyState.NOT_CHECKED


@dataclass(frozen=True, slots=True)
class RejectEvidence(Evidence):
    actor_is_approver: bool = False


@dataclass(frozen=True, slots=True)
class ExpireEvidence(Evidence):
    pass


@dataclass(frozen=True, slots=True)
class ApproveEvidence(Evidence):
    approver_person_id: str = ""
    approver_entitled: bool = False
    approver_mfa: bool = False
    approval_id: str = ""
    approval_type: ApprovalType = ApprovalType.HUMAN
    epoch_dependencies_current: bool = False
    nonce: NonceState = NonceState.INVALID
    digest_bound: bool = False
    override_bound: bool = False
    unproven_flag_bound: bool = False
    checkpoint_ok: bool = False


@dataclass(frozen=True, slots=True)
class ClaimEvidence(Evidence):
    caller_is_requester: bool = False
    epoch_deps_unchanged: bool = False
    holds: tuple[Hold, ...] | None = None  # None: holds unreadable (fail closed)
    parent_verified: bool = False
    repair_ctx: RepairContext | None = None
    scope_equal: bool = False
    target_class_equal: bool = False
    locks_read: bool = False
    target_lock_owner: str | None = None
    key_lock_free: bool = False
    lease_free: bool = False
    budget: BudgetCheck = BudgetCheck.NOT_CHECKED


@dataclass(frozen=True, slots=True)
class ReleaseClaimEvidence(Evidence):
    reason: ReleaseReason | None = None


@dataclass(frozen=True, slots=True)
class BeginApplyEvidence(Evidence):
    generation: int = -1
    caller: CallerClass | None = None
    own_change: bool = False
    epoch_deps_equal_claim_epoch: bool = False
    holds: tuple[Hold, ...] | None = None
    version_equals_approved: bool = False
    fingerprint_authenticated: bool = False
    period_closed: bool = False  # True only when the authenticated target read observed a closed period
    state_digest_equal: bool = False
    writer_lock_held: bool = False
    ownership_row_committed: bool = False
    repair_ctx: RepairContext | None = None


@dataclass(frozen=True, slots=True)
class PermitEvidence(Evidence):
    generation: int = -1
    checkpoint_covers_head: bool = False
    holds: tuple[Hold, ...] | None = None
    repair_ctx: RepairContext | None = None


@dataclass(frozen=True, slots=True)
class DispatchEvidence(Evidence):
    caller: CallerClass | None = None
    generation: int = -1
    permit_signature_valid: bool = False
    checkpoint_sequence_verified: bool = False
    holds: tuple[Hold, ...] | None = None
    repair_ctx: RepairContext | None = None


@dataclass(frozen=True, slots=True)
class PermitNotIssuedEvidence(Evidence):
    permitted_event_exists: bool = True
    checkpoint_unavailable: bool = False
    hold_open: bool = False


@dataclass(frozen=True, slots=True)
class CancelPermitEvidence(Evidence):
    generation: int = -1
    hold_open: bool = False
    cancel_cas_won: bool = False
    permit_invalidated: bool = False


@dataclass(frozen=True, slots=True)
class CompletionEvidence(Evidence):
    """The writer's (or, for a hard-deadline expiry, the worker's) record; the transition is chosen by its class."""

    caller: CallerClass | None = None
    generation: int = -1
    signed: bool = False
    call_id_matches: bool = False
    result_returned: bool = False
    stage: FailureStage | None = None
    no_effect_proof: bool = False
    refusal_code: ErrorCode | None = None
    checkpoint_ok: bool = False
    attempts: int = 0


CallUnknownEvidence = CompletionEvidence


@dataclass(frozen=True, slots=True)
class ResolveEvidence(Evidence):
    caller: CallerClass | None = None
    signed: bool = False
    proof_class: ProofClass = ProofClass.NONE
    reader_healthy: bool = False
    settle_elapsed: bool = False
    observation_complete: bool = False
    effect_present: bool = False
    effect_identity_match: bool = False
    exclusivity_proven: bool = False
    checkpoint_ok: bool = False
    attempts: int = 0
    first_attempt_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class VerifyEvidence(Evidence):
    caller: CallerClass | None = None
    signed_kinds: frozenset[EvidenceKind] = frozenset()
    bound: bool = False
    matches: bool = False
    effect_known: EffectKnown | None = None


RetryVerifyEvidence = VerifyEvidence


@dataclass(frozen=True, slots=True)
class RevokeEvidence(Evidence):
    cause: RevokeCause | None = None


@dataclass(frozen=True, slots=True)
class OperatorResolveEvidence(Evidence):
    operator_person_id: str = ""
    operator_class: CallerClass | None = None
    witness_person_id: str = ""
    witness_class: CallerClass | None = None
    signed: bool = False
    proof_class: ProofClass = ProofClass.NONE
    reader_healthy: bool = False
    settle_elapsed: bool = False
    observation_complete: bool = False
    outcome: ResolveOutcome | None = None
    effect_identity_match: bool = False
    exclusivity_proven: bool = False
    checkpoint_ok: bool = False


def classify_completion(evidence: object) -> Event:
    """T7, T8 or T9 chosen by the evidence class, never by a caller flag; anything unsigned or unclear is T9."""
    if type(evidence) is not CompletionEvidence or evidence.signed is not True or evidence.call_id_matches is not True:
        return Event.CALL_UNKNOWN
    if evidence.result_returned is True and evidence.stage is None:
        return Event.CALL_SUCCESS
    if (evidence.result_returned is not True and evidence.stage is FailureStage.PRE_WRITE
            and evidence.no_effect_proof is True and evidence.refusal_code in _WRITER_REFUSAL_CODES):
        return Event.REFUSED_BEFORE_WRITE
    return Event.CALL_UNKNOWN  # an error after the write call started is T9, never T8


# ---- repair authorization (section 4.2), one definition -----------------------------------------------------

def _holds_known(holds: object) -> bool:
    return type(holds) is tuple and all(type(h) is Hold for h in holds)


def repair_authorization_error(record: object, ctx: object, holds: object, kill: object,
                               phase: object) -> ErrorCode | None:
    """``None`` when the repair authorization is valid for ``phase``; otherwise one fixed code. It exempts only the
    parent-VERIFIED guard and the one matching FAILED_VERIFY_HALT row; everything else must hold."""
    if type(record) is not ChangeRecord or type(ctx) is not RepairContext or type(phase) is not RepairPhase:
        return ErrorCode.PARENT_NOT_VERIFIED
    halt = ctx.halt
    if record.kind is not ChangeKind.UNPOST or record.parent_change_id != ctx.parent_change_id or not ctx.parent_change_id:
        return ErrorCode.PARENT_NOT_VERIFIED
    if ctx.parent_verification is not Verification.FAILED_VERIFY or ctx.parent_effect_known is not EffectKnown.YES:
        return ErrorCode.PARENT_NOT_VERIFIED
    if (type(halt) is not Hold or halt.cause is not HoldCause.FAILED_VERIFY_HALT or halt.released
            or halt.change_id != ctx.parent_change_id):
        return ErrorCode.PARENT_NOT_VERIFIED
    if not (record.target_ref is not None and halt.target_ref == record.target_ref == ctx.current_target_ref):
        return ErrorCode.TARGET_REJECTED
    if halt.observed_version is None or halt.observed_version != ctx.current_version:
        return ErrorCode.STALE_VERSION
    approver = record.approver_person_id
    if (not approver or approver == record.requester_person_id or approver == ctx.parent_requester_person_id):
        return ErrorCode.APPROVER_NOT_INDEPENDENT
    if (ctx.approval_fresh is not True or ctx.approval_revoked is not False or record.authorization
            not in (Authorization.APPROVED, Authorization.CLAIMED)):
        return ErrorCode.APPROVAL_VOIDED
    if effective_mode(kill) is not None:
        return ErrorCode.KILL_SWITCH_ACTIVE
    if not _holds_known(holds) or any(not h.released and h.hold_id != halt.hold_id for h in holds):  # type: ignore[union-attr]
        return ErrorCode.BASE_HOLD
    if ctx.other_repair_exists is not False:
        return ErrorCode.LOCK_BUSY
    expected_owner = ctx.parent_change_id if phase is RepairPhase.CLAIM else record.change_id
    if ctx.target_lock_owner != expected_owner:
        return ErrorCode.LOCK_BUSY
    if phase is not RepairPhase.CLAIM:
        auth = record.repair
        if (type(auth) is not RepairAuth or auth.repair_change_id != record.change_id
                or record.repair_for != ctx.parent_change_id or auth.repair_for != ctx.parent_change_id
                or auth.target_ref != record.target_ref or auth.observed_version != ctx.current_version
                or auth.halt_id != halt.hold_id or auth.claim_generation != record.claim_generation
                or auth.approval_id != record.approval_id):
            return ErrorCode.TICKET_SUPERSEDED
    return None


# ---- guards: (record, evidence) -> None or the one refusal code -------------------------------------------------

_Guard = Callable[[ChangeRecord | None, Evidence], ErrorCode | None]
_GUARDS: dict[str, _Guard] = {}


def _guard(fn: _Guard) -> _Guard:
    _GUARDS[fn.__name__.removeprefix("g_")] = fn
    return fn


def _ok(condition: object, code: ErrorCode) -> ErrorCode | None:
    return None if condition is True else code


def _not_expired(deadline: datetime | None, now: object) -> bool:
    return is_aware_datetime(deadline) and is_aware_datetime(now) and now < deadline  # type: ignore[operator]


def _elapsed(deadline: datetime | None, now: object) -> bool:
    return is_aware_datetime(deadline) and is_aware_datetime(now) and now >= deadline  # type: ignore[operator]


def _budget_error(budget: object) -> ErrorCode | None:
    if budget is BudgetCheck.OK:
        return None
    if budget is BudgetCheck.CURRENCY_NOT_BUDGETED:
        return ErrorCode.CURRENCY_NOT_BUDGETED
    return ErrorCode.GRANT_EXHAUSTED if budget is BudgetCheck.EXHAUSTED else ErrorCode.BUDGET_EXCEEDED


def _holds_error(holds: object) -> ErrorCode | None:
    return None if _holds_known(holds) and all(h.released for h in holds) else ErrorCode.BASE_HOLD  # type: ignore[union-attr]


@_guard
def g_kill_off(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(effective_mode(ev.kill) is None, ErrorCode.KILL_SWITCH_ACTIVE)


@_guard
def g_schema_valid(record: ChangeRecord | None, ev: ProposeEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.schema_valid is True and type(ev.proposal) is ChangeProposal, ErrorCode.SCHEMA_INVALID)


@_guard
def g_scope_resolved(record: ChangeRecord | None, ev: ProposeEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.scope_resolved, ErrorCode.SCOPE_MISMATCH)


@_guard
def g_requester_entitled(record: ChangeRecord | None, ev: ProposeEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.requester_entitled, ErrorCode.NOT_ENTITLED)


@_guard
def g_epoch_read(record: ChangeRecord | None, ev: ProposeEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.epoch_read, ErrorCode.EPOCH_CHANGED)


@_guard
def g_logical_key_compatible(record: ChangeRecord | None, ev: ProposeEvidence) -> ErrorCode | None:  # type: ignore[override]
    return ErrorCode.IDEMPOTENCY_CONFLICT if ev.logical_key is LogicalKeyState.OTHER_DIGEST else _ok(
        type(ev.logical_key) is LogicalKeyState, ErrorCode.SCHEMA_INVALID)


@_guard
def g_preview_built(record: ChangeRecord | None, ev: ValidateEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.preview_built, ErrorCode.SCHEMA_INVALID)


@_guard
def g_shape_qualified(record: ChangeRecord | None, ev: ValidateEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.shape_qualified, ErrorCode.SHAPE_NOT_QUALIFIED)


@_guard
def g_effects_derived(record: ChangeRecord | None, ev: ValidateEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.allowed_effects_derived, ErrorCode.SCHEMA_INVALID)


@_guard
def g_budget_precheck(record: ChangeRecord | None, ev: ValidateEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _budget_error(ev.budget)


@_guard
def g_business_key_checked(record: ChangeRecord | None, ev: ValidateEvidence) -> ErrorCode | None:  # type: ignore[override]
    if record.kind in _DRAFT_KINDS:  # type: ignore[union-attr]
        return _ok(ev.key_state in (BusinessKeyState.FREE, BusinessKeyState.COLLISION), ErrorCode.DUPLICATE_SUSPECTED)
    return None


@_guard
def g_actor_is_approver(record: ChangeRecord | None, ev: RejectEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.actor_is_approver, ErrorCode.NOT_ENTITLED)


@_guard
def g_expiry_reached(record: ChangeRecord | None, ev: ExpireEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(_elapsed(record.expires_at, ev.now), ErrorCode.SCHEMA_INVALID)  # type: ignore[union-attr]


@_guard
def g_approval_window_open(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(_not_expired(record.expires_at, ev.now), ErrorCode.APPROVAL_EXPIRED)  # type: ignore[union-attr]


@_guard
def g_approver_independent(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    person = ev.approver_person_id
    return _ok(is_identity_text(person) and person != record.requester_person_id,  # type: ignore[union-attr]
               ErrorCode.APPROVER_NOT_INDEPENDENT)


@_guard
def g_approver_entitled(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    if type(ev.approval_type) is not ApprovalType:
        return ErrorCode.SCHEMA_INVALID
    mfa_ok = ev.approval_type is ApprovalType.TEST_LANE_AUTO or ev.approver_mfa is True
    return _ok(ev.approver_entitled is True and mfa_ok, ErrorCode.NOT_ENTITLED)


@_guard
def g_approval_id_valid(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(is_identity_text(ev.approval_id), ErrorCode.SCHEMA_INVALID)


@_guard
def g_epoch_current(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.epoch_dependencies_current, ErrorCode.EPOCH_CHANGED)


@_guard
def g_nonce_issued(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.nonce is NonceState.ISSUED, ErrorCode.APPROVAL_NONCE_INVALID)


@_guard
def g_digest_bound(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.digest_bound, ErrorCode.DIGEST_MISMATCH)


@_guard
def g_override_bound(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    if record.has_duplicate_override:  # type: ignore[union-attr]
        return _ok(ev.override_bound, ErrorCode.DIGEST_MISMATCH)
    return None


@_guard
def g_unproven_flag_bound(record: ChangeRecord | None, ev: ApproveEvidence) -> ErrorCode | None:  # type: ignore[override]
    if record.parent_attribution_unproven:  # type: ignore[union-attr]
        return _ok(ev.unproven_flag_bound, ErrorCode.ATTRIBUTION_UNPROVEN)
    return None


@_guard
def g_checkpoint_ok(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(getattr(ev, "checkpoint_ok", False), ErrorCode.CHECKPOINT_UNAVAILABLE)


@_guard
def g_caller_is_requester(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.caller_is_requester, ErrorCode.NOT_ENTITLED)


@_guard
def g_epoch_unchanged(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.epoch_deps_unchanged, ErrorCode.EPOCH_CHANGED)


def _claim_repair_path(record: ChangeRecord, ev: ClaimEvidence) -> bool:
    return record.kind is ChangeKind.UNPOST and ev.repair_ctx is not None


@_guard
def g_claim_holds_clear(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    if _claim_repair_path(record, ev):  # type: ignore[arg-type]
        return None  # the matching halt exception and every other hold are evaluated by the repair authorization
    return _holds_error(ev.holds)


@_guard
def g_claim_parent_ok(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    if _claim_repair_path(record, ev):  # type: ignore[arg-type]
        return repair_authorization_error(record, ev.repair_ctx, ev.holds, ev.kill, RepairPhase.CLAIM)
    if ev.repair_ctx is not None:
        return ErrorCode.PARENT_NOT_VERIFIED  # no other change may use the repair exception
    if record.kind in (ChangeKind.POST, ChangeKind.UNPOST):  # type: ignore[union-attr]
        return _ok(ev.parent_verified, ErrorCode.PARENT_NOT_VERIFIED)
    return None


@_guard
def g_scope_equal(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.scope_equal, ErrorCode.SCOPE_MISMATCH)


@_guard
def g_target_class_equal(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.target_class_equal, ErrorCode.TARGET_REJECTED)


@_guard
def g_locks_free(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    if ev.locks_read is not True or ev.key_lock_free is not True or ev.lease_free is not True:
        return ErrorCode.LOCK_BUSY
    if _claim_repair_path(record, ev):  # type: ignore[arg-type]
        return None  # the target lock owner is checked (must be the failed parent) by the repair authorization
    return _ok(ev.target_lock_owner is None, ErrorCode.LOCK_BUSY)


@_guard
def g_budget_reserved(record: ChangeRecord | None, ev: ClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _budget_error(ev.budget)


@_guard
def g_release_cause(record: ChangeRecord | None, ev: ReleaseClaimEvidence) -> ErrorCode | None:  # type: ignore[override]
    if ev.reason is ReleaseReason.TTL_EXPIRED:
        return _ok(_elapsed(record.claim_expires_at, ev.now), ErrorCode.SCHEMA_INVALID)  # type: ignore[union-attr]
    if ev.reason is ReleaseReason.KILL_SWITCH:
        return _ok(effective_mode(ev.kill) is not None, ErrorCode.SCHEMA_INVALID)
    return None if ev.reason is ReleaseReason.T6_GUARD_FAILED else ErrorCode.SCHEMA_INVALID


@_guard
def g_generation_current(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    gen = getattr(ev, "generation", -1)
    return _ok(type(gen) is int and gen == record.claim_generation, ErrorCode.TICKET_SUPERSEDED)  # type: ignore[union-attr]


@_guard
def g_caller_may_begin(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    if ev.caller is CallerClass.WRITER:
        return None  # a writer acts on behalf of a token
    return _ok(ev.caller is CallerClass.REQUESTER and ev.own_change is True, ErrorCode.NOT_ENTITLED)


@_guard
def g_claim_alive(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(_not_expired(record.claim_expires_at, ev.now), ErrorCode.CLAIM_EXPIRED)  # type: ignore[union-attr]


@_guard
def g_epoch_equals_claim(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.epoch_deps_equal_claim_epoch, ErrorCode.EPOCH_CHANGED)


def _repair_error(record: ChangeRecord, ev: Evidence, phase: RepairPhase) -> ErrorCode | None:
    """Re-validation at T6, the permit and the writer: only a repair record (``repair_for`` set) is affected."""
    if record.repair_for is None and record.repair is None:
        return _holds_error(getattr(ev, "holds", None))
    return repair_authorization_error(record, getattr(ev, "repair_ctx", None), getattr(ev, "holds", None), ev.kill, phase)


@_guard
def g_holds_and_repair_t6(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _repair_error(record, ev, RepairPhase.BEGIN_APPLY)  # type: ignore[arg-type]


@_guard
def g_version_equals_approved(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.version_equals_approved, ErrorCode.STALE_VERSION)


@_guard
def g_fingerprint_authenticated(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.fingerprint_authenticated, ErrorCode.TARGET_REJECTED)


@_guard
def g_period_open(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    # Runs before the state-digest guard: a positively observed closed period is reported as PERIOD_CLOSED; any other
    # change of the business state (including a period status that was not observed) stays DIGEST_MISMATCH.
    return None if ev.period_closed is not True else ErrorCode.PERIOD_CLOSED


@_guard
def g_state_digest_equal(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.state_digest_equal, ErrorCode.DIGEST_MISMATCH)


@_guard
def g_writer_lock_held(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.writer_lock_held, ErrorCode.LOCK_BUSY)


@_guard
def g_ownership_row_committed(record: ChangeRecord | None, ev: BeginApplyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.ownership_row_committed, ErrorCode.AUDIT_UNAVAILABLE)


@_guard
def g_checkpoint_covers_head(record: ChangeRecord | None, ev: PermitEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.checkpoint_covers_head, ErrorCode.CHECKPOINT_UNAVAILABLE)


@_guard
def g_permit_window_open(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(_not_expired(record.permit_expires_at, ev.now), ErrorCode.PERMIT_MISSING)  # type: ignore[union-attr]


@_guard
def g_holds_and_repair_permit(record: ChangeRecord | None, ev: PermitEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _repair_error(record, ev, RepairPhase.PERMIT)  # type: ignore[arg-type]


@_guard
def g_caller_is_writer(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(getattr(ev, "caller", None) is CallerClass.WRITER, ErrorCode.NOT_ENTITLED)


@_guard
def g_permit_signature_valid(record: ChangeRecord | None, ev: DispatchEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.permit_signature_valid, ErrorCode.PERMIT_MISSING)


@_guard
def g_checkpoint_sequence_verified(record: ChangeRecord | None, ev: DispatchEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.checkpoint_sequence_verified, ErrorCode.CHECKPOINT_UNAVAILABLE)


@_guard
def g_holds_and_repair_writer(record: ChangeRecord | None, ev: DispatchEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _repair_error(record, ev, RepairPhase.WRITER)  # type: ignore[arg-type]


@_guard
def g_no_permitted_event(record: ChangeRecord | None, ev: PermitNotIssuedEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.permitted_event_exists is False, ErrorCode.TICKET_SUPERSEDED)


@_guard
def g_permit_not_issued_cause(record: ChangeRecord | None, ev: PermitNotIssuedEvidence) -> ErrorCode | None:  # type: ignore[override]
    cause = (ev.checkpoint_unavailable is True or ev.hold_open is True or effective_mode(ev.kill) is not None
             or _elapsed(record.permit_expires_at, ev.now))  # type: ignore[union-attr]
    return _ok(cause, ErrorCode.SCHEMA_INVALID)


@_guard
def g_cancel_cause(record: ChangeRecord | None, ev: CancelPermitEvidence) -> ErrorCode | None:  # type: ignore[override]
    superseded = type(ev.generation) is int and ev.generation != record.claim_generation  # type: ignore[union-attr]
    cause = (effective_mode(ev.kill) is not None or ev.hold_open is True or superseded
             or _elapsed(record.permit_expires_at, ev.now))  # type: ignore[union-attr]
    return _ok(cause, ErrorCode.SCHEMA_INVALID)


@_guard
def g_cancel_cas_won(record: ChangeRecord | None, ev: CancelPermitEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.cancel_cas_won, ErrorCode.LOCK_BUSY)


@_guard
def g_permit_invalidated(record: ChangeRecord | None, ev: CancelPermitEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.permit_invalidated, ErrorCode.PERMIT_MISSING)


@_guard
def g_completion_signed(record: ChangeRecord | None, ev: CompletionEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.signed is True and ev.call_id_matches is True, ErrorCode.EVIDENCE_UNSIGNED)


def _class_guard(expected: Event) -> _Guard:
    def guard(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
        return _ok(classify_completion(ev) is expected, ErrorCode.SCHEMA_INVALID)
    return guard


_GUARDS["completion_is_success"] = _class_guard(Event.CALL_SUCCESS)
_GUARDS["completion_is_refusal"] = _class_guard(Event.REFUSED_BEFORE_WRITE)
_GUARDS["completion_is_unknown"] = _class_guard(Event.CALL_UNKNOWN)


@_guard
def g_caller_is_writer_or_worker(record: ChangeRecord | None, ev: CompletionEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.caller in (CallerClass.WRITER, CallerClass.RECOVERY_WORKER), ErrorCode.NOT_ENTITLED)


@_guard
def g_caller_is_worker(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(getattr(ev, "caller", None) is CallerClass.RECOVERY_WORKER, ErrorCode.NOT_ENTITLED)


@_guard
def g_resolve_signed(record: ChangeRecord | None, ev: ResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.signed, ErrorCode.EVIDENCE_UNSIGNED)


@_guard
def g_independent_proof(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    return _ok(getattr(ev, "proof_class", None) in _INDEPENDENT_PROOFS, ErrorCode.COMPLETION_PROOF_MISSING)


@_guard
def g_observation_complete(record: ChangeRecord | None, ev: Evidence) -> ErrorCode | None:
    healthy = (getattr(ev, "reader_healthy", False) is True and getattr(ev, "settle_elapsed", False) is True
               and getattr(ev, "observation_complete", False) is True)
    return _ok(healthy, ErrorCode.COMPLETION_PROOF_MISSING)


@_guard
def g_effect_present(record: ChangeRecord | None, ev: ResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.effect_present is True, ErrorCode.SCHEMA_INVALID)


@_guard
def g_effect_absent(record: ChangeRecord | None, ev: ResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.effect_present is False, ErrorCode.SCHEMA_INVALID)


@_guard
def g_attribution_proven(record: ChangeRecord | None, ev: ResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    # exclusivity is UNPROVEN for every unknown-outcome resolution in this contract version (section 5)
    return _ok(ev.effect_identity_match is True and ev.exclusivity_proven is True, ErrorCode.ATTRIBUTION_UNPROVEN)


@_guard
def g_triage_cause(record: ChangeRecord | None, ev: ResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    aged = (type(ev.attempts) is int and ev.attempts >= RESOLVE_MAX_ATTEMPTS and is_aware_datetime(ev.first_attempt_at)
            and is_aware_datetime(ev.now) and ev.now - ev.first_attempt_at >= RESOLVE_WINDOW)  # type: ignore[operator]
    if aged:
        return None
    if ev.effect_present is True and ev.observation_complete is True:
        if ev.signed is not True:
            return ErrorCode.EVIDENCE_UNSIGNED
        if not (ev.effect_identity_match is True and ev.exclusivity_proven is True):
            return None
    return ErrorCode.SCHEMA_INVALID


@_guard
def g_evidence_bound(record: ChangeRecord | None, ev: VerifyEvidence) -> ErrorCode | None:  # type: ignore[override]
    kinds = ev.signed_kinds
    return _ok(ev.bound is True and type(kinds) is frozenset and _REQUIRED_VERIFY_KINDS <= kinds,
               ErrorCode.EVIDENCE_UNSIGNED)


@_guard
def g_verify_matches(record: ChangeRecord | None, ev: VerifyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.matches, ErrorCode.VERIFY_FAILED)


@_guard
def g_verify_mismatch(record: ChangeRecord | None, ev: VerifyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.matches is False and type(ev.effect_known) is EffectKnown, ErrorCode.SCHEMA_INVALID)


@_guard
def g_retry_bound(record: ChangeRecord | None, ev: VerifyEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(record.verify_attempts < VERIFY_RETRY_BOUND, ErrorCode.VERIFY_FAILED)  # type: ignore[union-attr]


@_guard
def g_revoke_cause(record: ChangeRecord | None, ev: RevokeEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(type(ev.cause) is RevokeCause, ErrorCode.SCHEMA_INVALID)


@_guard
def g_two_person(record: ChangeRecord | None, ev: OperatorResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    op, wit = ev.operator_person_id, ev.witness_person_id
    if (ev.operator_class is not CallerClass.OPERATOR or ev.witness_class is not CallerClass.RECOVERY_WITNESS
            or not is_identity_text(op) or not is_identity_text(wit)):
        return ErrorCode.NOT_ENTITLED  # without a registered witness T16 stays unavailable (D10b)
    approver = record.approver_person_id  # type: ignore[union-attr]
    if (op == wit or record.requester_person_id in (op, wit)  # type: ignore[union-attr]
            or (approver is not None and op == approver and wit == approver)):
        return ErrorCode.APPROVER_NOT_INDEPENDENT
    return None


@_guard
def g_outcome_consistent(record: ChangeRecord | None, ev: OperatorResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(type(ev.outcome) is ResolveOutcome, ErrorCode.SCHEMA_INVALID)


@_guard
def g_operator_attribution(record: ChangeRecord | None, ev: OperatorResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    if ev.outcome is ResolveOutcome.PRESENT_ATTRIBUTED:
        return _ok(ev.effect_identity_match is True and ev.exclusivity_proven is True, ErrorCode.ATTRIBUTION_UNPROVEN)
    return None


@_guard
def g_operator_signed(record: ChangeRecord | None, ev: OperatorResolveEvidence) -> ErrorCode | None:  # type: ignore[override]
    return _ok(ev.signed, ErrorCode.EVIDENCE_UNSIGNED)


# ---- lock / lease / hold / reservation matrix (section 4.1) ----------------------------------------------------

@dataclass(frozen=True, slots=True)
class LockRow:
    tl: LockAction
    kl: LockAction
    wl: LockAction
    hold: HoldAction
    reservation: Reservation | None  # None: KEPT
    repair_handback: bool  # a repair's release of the target lock is a handback to the failed parent (4.2)
    proof: str


_L, _H, _R = LockAction, HoldAction, Reservation
_ACQ, _KEEP, _REL, _NA = _L.ACQUIRE, _L.KEEP, _L.RELEASE, _L.NA
LOCK_MATRIX: Final = MappingProxyType({
    "T5": LockRow(_ACQ, _ACQ, _ACQ, _H.NONE, _R.RESERVED, False, "claim transaction"),
    "T5_REPAIR": LockRow(_L.HANDOFF, _ACQ, _ACQ, _H.NONE, _R.RESERVED, False, "section 4.2"),
    "T5x": LockRow(_REL, _REL, _REL, _H.NONE, _R.RELEASED, True, "no PERMITTED event, or TTL expiry before any permit"),
    "T6": LockRow(_KEEP, _KEEP, _KEEP, _H.NONE, None, False, ""),
    "T6p": LockRow(_KEEP, _KEEP, _KEEP, _H.NONE, None, False, ""),
    "T6r": LockRow(_REL, _REL, _REL, _H.NONE, _R.RELEASED, True, "no PERMITTED event, or TTL expiry before any permit"),
    "T6c": LockRow(_REL, _REL, _REL, _H.NONE, _R.RELEASED, True,
                   "successful CAS PERMITTED to CANCELLED_UNDISPATCHED with the permit invalidated"),
    "T7": LockRow(_KEEP, _REL, _REL, _H.NONE, _R.CONSUMED, False, "writer completion record (proof class a)"),
    "T8": LockRow(_REL, _REL, _REL, _H.NONE, _R.RELEASED, True, "signed PRE_WRITE stage evidence"),
    "T9": LockRow(_KEEP, _KEEP, _KEEP, _H.OPEN_CALL_OWNERSHIP, None, False, ""),
    "T10": LockRow(_KEEP, _REL, _REL, _H.RELEASE_CALL_OWNERSHIP, _R.CONSUMED, False,
                   "proof class a or b, attribution proof"),
    # T11: contract 4.1 releases all three; for a repair the lock goes back to the parent (documented extension)
    "T11": LockRow(_REL, _REL, _REL, _H.RELEASE_CALL_OWNERSHIP, _R.RELEASED, True,
                   "proof class a or b, healthy complete absence observation"),
    "T12": LockRow(_KEEP, _KEEP, _KEEP, _H.KEEP_CALL_OWNERSHIP, None, False, ""),
    "T13": LockRow(_REL, _REL, _NA, _H.NONE, _R.CONSUMED, False, "verification evidence"),
    "T14": LockRow(_KEEP, _REL, _NA, _H.OPEN_FAILED_VERIFY_HALT, _R.CONSUMED, False, ""),
    "T15": LockRow(_REL, _REL, _REL, _H.NONE, _R.RELEASED, True, "pre-dispatch only"),
    "T16_ABSENT": LockRow(_REL, _REL, _REL, _H.RELEASE_CALL_OWNERSHIP, _R.RELEASED, True,
                          "completion proof (proof class a or b)"),
    "T16_PRESENT": LockRow(_KEEP, _REL, _REL, _H.RELEASE_CALL_OWNERSHIP, _R.CONSUMED, False,
                           "completion proof (proof class a or b)"),
    "T17_RETRY_OK": LockRow(_REL, _NA, _NA, _H.RELEASE_FAILED_VERIFY_HALT, None, False, "verification evidence"),
})


def _next_reservation(current: Reservation, new: Reservation | None) -> Reservation:
    """CONSUMED and RELEASED are final (a second resolution cannot change them); only a new claim re-reserves."""
    if new is None:
        return current
    if new is Reservation.RESERVED:
        return new if current in (Reservation.NONE, Reservation.RELEASED) else current
    return new if current is Reservation.RESERVED else current


_HOLD_EFFECT: Final = MappingProxyType({
    HoldAction.OPEN_CALL_OWNERSHIP: EffectKind.OPEN_HOLD_CALL_OWNERSHIP,
    HoldAction.RELEASE_CALL_OWNERSHIP: EffectKind.RELEASE_HOLD_CALL_OWNERSHIP,
    HoldAction.OPEN_FAILED_VERIFY_HALT: EffectKind.OPEN_HOLD_FAILED_VERIFY_HALT,
    HoldAction.RELEASE_FAILED_VERIFY_HALT: EffectKind.RELEASE_HOLD_FAILED_VERIFY_HALT,
})


def _lock_value(current: bool, action: LockAction) -> bool:
    if action in (LockAction.ACQUIRE, LockAction.HANDOFF):
        return True
    return False if action is LockAction.RELEASE else current


def _commit(record: ChangeRecord, tid: str, key: str, changes: dict[str, object],
            effects: tuple[EffectKind, ...] = ()) -> Applied:
    """Apply the dimension changes plus the 4.1 matrix row ``key`` (locks, lease, holds, reservation, handback)."""
    row = LOCK_MATRIX[key]
    out = list(effects)
    updates = dict(changes)
    if any(a is LockAction.ACQUIRE for a in (row.tl, row.kl, row.wl)):
        out.append(EffectKind.ACQUIRE_LOCKS)
    if row.tl is LockAction.HANDOFF:
        out.append(EffectKind.HAND_LOCK_TO_REPAIR)
    if row.repair_handback and record.repair is not None:  # common zero-effect handback rule of 4.2
        out += [EffectKind.INVALIDATE_REPAIR_AUTH, EffectKind.HAND_LOCK_BACK_TO_PARENT]
        updates["repair"] = None
    if row.hold in _HOLD_EFFECT:
        out.append(_HOLD_EFFECT[row.hold])
    updates.update(
        target_lock=_lock_value(record.target_lock, row.tl), key_lock=_lock_value(record.key_lock, row.kl),
        lease=_lock_value(record.lease, row.wl), reservation=_next_reservation(record.reservation, row.reservation))
    return Applied(replace(record, **updates), tuple(dict.fromkeys(out)), tid)


# ---- the table ------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TransitionRow:
    key: str
    tid: str
    event: Event
    requires: Mapping[str, frozenset[object]]  # dimension attribute -> allowed values (empty: no source record)
    target: str
    guards: tuple[str, ...]
    state_refusal: ErrorCode = ErrorCode.SCHEMA_INVALID


def _req(**dims: tuple[object, ...]) -> Mapping[str, frozenset[object]]:
    return MappingProxyType({k: frozenset(v) for k, v in dims.items()})


_LC, _AU, _EX, _VE, _DI, _TK = Lifecycle, Authorization, Execution, Verification, Dispatch, TokenState
_VALIDATED_APPROVED = {"lifecycle": (_LC.VALIDATED,), "authorization": (_AU.APPROVED,), "execution": (_EX.NOT_STARTED,)}
TRANSITION_TABLE: Final = (
    TransitionRow("T1", "T1", Event.PROPOSE, _req(), "lifecycle=PROPOSED",
                  ("kill_off", "schema_valid", "scope_resolved", "requester_entitled", "epoch_read",
                   "logical_key_compatible")),
    TransitionRow("T2", "T2", Event.VALIDATE, _req(lifecycle=(_LC.PROPOSED,)),
                  "lifecycle=VALIDATED or DUPLICATE_PARKED",
                  ("kill_off", "preview_built", "shape_qualified", "effects_derived", "budget_precheck",
                   "business_key_checked")),
    TransitionRow("T3_REJECT", "T3", Event.REJECT,
                  _req(lifecycle=(_LC.PROPOSED, _LC.VALIDATED), authorization=(_AU.NONE, _AU.APPROVED),
                       execution=(_EX.NOT_STARTED,)),
                  "lifecycle=REJECTED", ("actor_is_approver",)),
    TransitionRow("T3_EXPIRE", "T3", Event.EXPIRE,
                  _req(lifecycle=(_LC.PROPOSED, _LC.VALIDATED), authorization=(_AU.NONE, _AU.APPROVED),
                       execution=(_EX.NOT_STARTED,)),
                  "lifecycle=EXPIRED_QUEUED, authorization=EXPIRED", ("expiry_reached",)),
    TransitionRow("T4", "T4", Event.APPROVE, _req(lifecycle=(_LC.VALIDATED,), authorization=(_AU.NONE,)),
                  "authorization=APPROVED",
                  ("kill_off", "approval_window_open", "approver_independent", "approver_entitled", "approval_id_valid",
                   "epoch_current", "nonce_issued", "digest_bound", "override_bound", "unproven_flag_bound",
                   "checkpoint_ok")),
    TransitionRow("T5", "T5", Event.CLAIM, _req(**_VALIDATED_APPROVED),
                  "authorization=CLAIMED, execution=NOT_STARTED, claim_generation+1",
                  ("caller_is_requester", "approval_window_open", "epoch_unchanged", "kill_off", "claim_holds_clear",
                   "claim_parent_ok", "scope_equal", "target_class_equal", "locks_free", "budget_reserved")),
    TransitionRow("T5x", "T5x", Event.RELEASE_CLAIM,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.NOT_STARTED,)),
                  "authorization=APPROVED (EXPIRED or VOIDED when applicable), token SUPERSEDED",
                  ("release_cause",)),
    TransitionRow("T6", "T6", Event.BEGIN_APPLY,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.NOT_STARTED,), token=(_TK.ISSUED,)),
                  "execution=APPLYING, dispatch=NOT_PERMITTED",
                  ("generation_current", "caller_may_begin", "claim_alive", "epoch_equals_claim", "kill_off",
                   "holds_and_repair_t6", "approval_window_open", "version_equals_approved",
                   "fingerprint_authenticated", "period_open", "state_digest_equal", "writer_lock_held",
                   "ownership_row_committed"),
                  ErrorCode.TICKET_SUPERSEDED),
    TransitionRow("T6_REPLAY", "T6", Event.BEGIN_APPLY,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.APPLYING,), token=(_TK.CONSUMED,),
                       dispatch=(_DI.NOT_PERMITTED, _DI.PERMITTED)),
                  "unchanged (the existing ticket is returned)", ("generation_current", "caller_may_begin"),
                  ErrorCode.TICKET_SUPERSEDED),
    TransitionRow("T6p", "T6p", Event.ISSUE_PERMIT,
                  _req(execution=(_EX.APPLYING,), dispatch=(_DI.NOT_PERMITTED,)), "dispatch=PERMITTED",
                  ("generation_current", "kill_off", "checkpoint_covers_head", "permit_window_open",
                   "holds_and_repair_permit"), ErrorCode.PERMIT_MISSING),
    TransitionRow("T6p_DISPATCH", "T6p", Event.MARK_DISPATCHED,
                  _req(execution=(_EX.APPLYING,), dispatch=(_DI.PERMITTED,)), "dispatch=DISPATCHED",
                  ("caller_is_writer", "generation_current", "kill_off", "permit_signature_valid",
                   "checkpoint_sequence_verified", "holds_and_repair_writer"), ErrorCode.PERMIT_MISSING),
    TransitionRow("T6r", "T6r", Event.PERMIT_NOT_ISSUED,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.APPLYING,), dispatch=(_DI.NOT_PERMITTED,)),
                  "authorization=APPROVED, execution=NOT_STARTED, token SUPERSEDED",
                  ("no_permitted_event", "permit_not_issued_cause")),
    TransitionRow("T6c", "T6c", Event.CANCEL_PERMIT,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.APPLYING,), dispatch=(_DI.PERMITTED,)),
                  "dispatch=CANCELLED_UNDISPATCHED, authorization=APPROVED, execution=NOT_STARTED",
                  ("cancel_cause", "cancel_cas_won", "permit_invalidated"), ErrorCode.LOCK_BUSY),
    TransitionRow("T7", "T7", Event.CALL_SUCCESS,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.APPLYING,), dispatch=(_DI.DISPATCHED,)),
                  "execution=APPLIED, call_ownership=PROVEN_FINISHED, attribution=PROVEN",
                  ("caller_is_writer", "generation_current", "completion_signed", "completion_is_success",
                   "checkpoint_ok"), ErrorCode.PERMIT_MISSING),
    TransitionRow("T8", "T8", Event.REFUSED_BEFORE_WRITE,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.APPLYING,), dispatch=(_DI.DISPATCHED,)),
                  "execution=FAILED_APPLY or ROLLBACK_REFUSED, or APPROVED again for a transient LOCK_BUSY",
                  ("caller_is_writer", "generation_current", "completion_signed", "completion_is_refusal",
                   "checkpoint_ok"), ErrorCode.PERMIT_MISSING),
    TransitionRow("T9", "T9", Event.CALL_UNKNOWN,
                  _req(authorization=(_AU.CLAIMED,), execution=(_EX.APPLYING,), dispatch=(_DI.DISPATCHED,)),
                  "execution=APPLY_UNKNOWN, call_ownership=POSSIBLY_EXECUTING",
                  ("caller_is_writer_or_worker", "generation_current", "completion_is_unknown"),
                  ErrorCode.PERMIT_MISSING),
    TransitionRow("T10", "T10", Event.RESOLVE_FOUND, _req(execution=(_EX.APPLY_UNKNOWN,)),
                  "execution=APPLIED, call_ownership=PROVEN_FINISHED, attribution=PROVEN",
                  ("caller_is_worker", "resolve_signed", "independent_proof", "observation_complete",
                   "effect_present", "attribution_proven")),
    TransitionRow("T11", "T11", Event.RESOLVE_ABSENT, _req(execution=(_EX.APPLY_UNKNOWN,)),
                  "execution=FAILED_APPLY, call_ownership=PROVEN_FINISHED",
                  ("caller_is_worker", "resolve_signed", "independent_proof", "observation_complete",
                   "effect_absent", "checkpoint_ok")),
    TransitionRow("T12", "T12", Event.AGE_LIMIT, _req(execution=(_EX.APPLY_UNKNOWN,)), "execution=TRIAGE_REQUIRED",
                  ("caller_is_worker", "triage_cause")),
    TransitionRow("T13", "T13", Event.VERIFY_OK, _req(execution=(_EX.APPLIED,), verification=(_VE.NOT_VERIFIED,)),
                  "verification=VERIFIED", ("caller_is_worker", "evidence_bound", "verify_matches")),
    TransitionRow("T14", "T14", Event.VERIFY_FAILED, _req(execution=(_EX.APPLIED,), verification=(_VE.NOT_VERIFIED,)),
                  "verification=FAILED_VERIFY", ("caller_is_worker", "evidence_bound", "verify_mismatch")),
    TransitionRow("T15", "T15", Event.REVOKE,
                  _req(lifecycle=(_LC.VALIDATED,), authorization=(_AU.APPROVED, _AU.CLAIMED),
                       execution=(_EX.NOT_STARTED,)),
                  "authorization=VOIDED or REVOKED", ("revoke_cause",)),
    TransitionRow("T16", "T16", Event.OPERATOR_RESOLVE, _req(execution=(_EX.TRIAGE_REQUIRED,)),
                  "APPLIED (attributed or UNPROVEN_OPERATOR_ATTESTED) or FAILED_APPLY",
                  ("two_person", "outcome_consistent", "independent_proof", "operator_signed", "observation_complete",
                   "operator_attribution", "checkpoint_ok")),
    TransitionRow("T17_RETRY", "T17", Event.RETRY_VERIFY,
                  _req(verification=(_VE.FAILED_VERIFY,), closed=(False,)),
                  "verification=VERIFIED, or still FAILED_VERIFY with verify_attempts+1",
                  ("caller_is_worker", "evidence_bound", "retry_bound")),
    TransitionRow("T17_CLOSE", "T17", Event.CLOSE_FAILED_VERIFY,
                  _req(verification=(_VE.FAILED_VERIFY,), closed=(False,)),
                  "FAILED_VERIFY change closed, halt released",
                  ("two_person", "operator_signed", "observation_complete")),
)

_EVIDENCE: Final = {
    Event.PROPOSE: ProposeEvidence, Event.VALIDATE: ValidateEvidence, Event.REJECT: RejectEvidence,
    Event.EXPIRE: ExpireEvidence, Event.APPROVE: ApproveEvidence, Event.CLAIM: ClaimEvidence,
    Event.RELEASE_CLAIM: ReleaseClaimEvidence, Event.BEGIN_APPLY: BeginApplyEvidence,
    Event.ISSUE_PERMIT: PermitEvidence, Event.MARK_DISPATCHED: DispatchEvidence,
    Event.PERMIT_NOT_ISSUED: PermitNotIssuedEvidence, Event.CANCEL_PERMIT: CancelPermitEvidence,
    Event.CALL_SUCCESS: CompletionEvidence, Event.REFUSED_BEFORE_WRITE: CompletionEvidence,
    Event.CALL_UNKNOWN: CompletionEvidence, Event.RESOLVE_FOUND: ResolveEvidence,
    Event.RESOLVE_ABSENT: ResolveEvidence, Event.AGE_LIMIT: ResolveEvidence, Event.VERIFY_OK: VerifyEvidence,
    Event.VERIFY_FAILED: VerifyEvidence, Event.REVOKE: RevokeEvidence, Event.OPERATOR_RESOLVE: OperatorResolveEvidence,
    Event.RETRY_VERIFY: VerifyEvidence, Event.CLOSE_FAILED_VERIFY: OperatorResolveEvidence,
}
EVENT_EVIDENCE: Final = MappingProxyType(_EVIDENCE)


# ---- handlers: new dimensions per row -------------------------------------------------------------------------

def _unwound_authorization(record: ChangeRecord, ev: Evidence) -> Authorization:
    """Where an unwound claim lands: VOIDED under REVOKE, EXPIRED when the approval lapsed, else APPROVED."""
    if effective_mode(ev.kill) is KillMode.REVOKE:
        return Authorization.VOIDED
    return Authorization.EXPIRED if _elapsed(record.expires_at, ev.now) else Authorization.APPROVED


def _unwind(record: ChangeRecord, ev: Evidence, tid: str, key: str, extra: dict[str, object] | None = None,
            effects: tuple[EffectKind, ...] = ()) -> Applied:
    changes: dict[str, object] = {
        "authorization": _unwound_authorization(record, ev), "execution": Execution.NOT_STARTED, "token": TokenState.SUPERSEDED,
        "claim_expires_at": None, "permit_expires_at": None}
    changes.update(extra or {})
    return _commit(record, tid, key, changes, effects)


def _h_propose(record: ChangeRecord | None, ev: ProposeEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    if ev.logical_key is LogicalKeyState.SAME_DIGEST:
        return Applied(None, (EffectKind.REPLAY_EARLIER_RECEIPT,), row.tid)
    p = ev.proposal
    assert p is not None
    new = ChangeRecord(
        change_id=p.change_id, kind=p.kind, scope=p.scope, requester_person_id=p.requester_person_id,
        parent_change_id=p.parent_change_id, target_ref=p.target_ref,
        has_duplicate_override=p.duplicate_override is not None,
        parent_attribution_unproven=ev.parent_attribution_unproven is True, expires_at=p.expires_at)
    return Applied(new, (), row.tid)


def _h_validate(record: ChangeRecord, ev: ValidateEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    parked = (record.kind in _DRAFT_KINDS and ev.key_state is BusinessKeyState.COLLISION
              and not record.has_duplicate_override)
    return Applied(replace(record, lifecycle=Lifecycle.DUPLICATE_PARKED if parked else Lifecycle.VALIDATED), (), row.tid)


def _h_reject(record: ChangeRecord, ev: RejectEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    auth = Authorization.REVOKED if record.authorization is Authorization.APPROVED else record.authorization
    return Applied(replace(record, lifecycle=Lifecycle.REJECTED, authorization=auth), (), row.tid)


def _h_expire(record: ChangeRecord, ev: ExpireEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return Applied(replace(record, lifecycle=Lifecycle.EXPIRED_QUEUED, authorization=Authorization.EXPIRED), (), row.tid)


def _h_approve(record: ChangeRecord, ev: ApproveEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return Applied(replace(record, authorization=Authorization.APPROVED, approver_person_id=ev.approver_person_id,
                           approval_id=ev.approval_id, approval_type=ev.approval_type),
                   (EffectKind.CONSUME_NONCE,), row.tid)


def _h_claim(record: ChangeRecord, ev: ClaimEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    ctx = ev.repair_ctx if _claim_repair_path(record, ev) else None
    generation = record.claim_generation + 1
    changes: dict[str, object] = {
        "authorization": Authorization.CLAIMED, "execution": Execution.NOT_STARTED, "dispatch": Dispatch.NOT_PERMITTED,
        "token": TokenState.ISSUED, "claim_generation": generation, "claim_expires_at": ev.now + CLAIM_TTL,  # type: ignore[operator]
        "permit_expires_at": None}
    if ctx is not None:
        assert ctx.halt is not None and record.target_ref is not None and record.approval_id is not None
        changes.update(repair_for=ctx.parent_change_id, repair=RepairAuth(
            record.change_id, ctx.parent_change_id, record.target_ref, ctx.current_version, ctx.halt.hold_id,
            record.approval_id, generation))
    return _commit(record, row.tid, "T5_REPAIR" if ctx is not None else "T5", changes,
                   (EffectKind.RESERVE_BUDGET, EffectKind.MINT_CLAIM_TOKEN))


def _h_release_claim(record: ChangeRecord, ev: ReleaseClaimEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _unwind(record, ev, row.tid, "T5x")


def _h_begin_apply(record: ChangeRecord, ev: BeginApplyEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T6", {
        "execution": Execution.APPLYING, "token": TokenState.CONSUMED, "dispatch": Dispatch.NOT_PERMITTED,
        "permit_expires_at": ev.now + PERMIT_TTL},  # type: ignore[operator]
        (EffectKind.COMMIT_APPLYING_AND_OWNERSHIP_ROW,))


def _h_begin_replay(record: ChangeRecord, ev: BeginApplyEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return Applied(record, (EffectKind.REPLAY_EXISTING_TICKET,), row.tid)  # never a second permit


def _h_issue_permit(record: ChangeRecord, ev: PermitEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T6p", {"dispatch": Dispatch.PERMITTED, "permit_expires_at": ev.now + PERMIT_TTL},  # type: ignore[operator]
                   (EffectKind.SIGN_PERMIT,))


def _h_mark_dispatched(record: ChangeRecord, ev: DispatchEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T6p", {"dispatch": Dispatch.DISPATCHED}, (EffectKind.RECORD_DISPATCHED,))


def _h_permit_not_issued(record: ChangeRecord, ev: PermitNotIssuedEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _unwind(record, ev, row.tid, "T6r")


def _h_cancel_permit(record: ChangeRecord, ev: CancelPermitEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _unwind(record, ev, row.tid, "T6c", {"dispatch": Dispatch.CANCELLED_UNDISPATCHED},
                   (EffectKind.INVALIDATE_PERMIT,))


def _h_call_success(record: ChangeRecord, ev: CompletionEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T7", {
        "execution": Execution.APPLIED, "call_ownership": CallOwnership.PROVEN_FINISHED, "attribution": Attribution.PROVEN})


def _h_refused_before_write(record: ChangeRecord, ev: CompletionEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    if ev.refusal_code is ErrorCode.LOCK_BUSY:  # transient: back to APPROVED with a durable attempt counter
        attempts = record.lock_busy_attempts + 1
        first = record.first_attempt_at or ev.now
        in_window = is_aware_datetime(first) and is_aware_datetime(ev.now) and ev.now - first <= LOCK_BUSY_WINDOW  # type: ignore[operator]
        if attempts < LOCK_BUSY_MAX_ATTEMPTS and in_window:
            return _unwind(record, ev, row.tid, "T8", {"lock_busy_attempts": attempts, "first_attempt_at": first})
    refused = ev.refusal_code is ErrorCode.ROLLBACK_REFUSED and record.kind is ChangeKind.UNPOST
    return _commit(record, row.tid, "T8", {
        "execution": Execution.ROLLBACK_REFUSED if refused else Execution.FAILED_APPLY})


def _h_call_unknown(record: ChangeRecord, ev: CompletionEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T9", {
        "execution": Execution.APPLY_UNKNOWN, "call_ownership": CallOwnership.POSSIBLY_EXECUTING})


def _h_resolve_found(record: ChangeRecord, ev: ResolveEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T10", {
        "execution": Execution.APPLIED, "call_ownership": CallOwnership.PROVEN_FINISHED, "attribution": Attribution.PROVEN})


def _h_resolve_absent(record: ChangeRecord, ev: ResolveEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T11", {
        "execution": Execution.FAILED_APPLY, "call_ownership": CallOwnership.PROVEN_FINISHED})


def _h_age_limit(record: ChangeRecord, ev: ResolveEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T12", {"execution": Execution.TRIAGE_REQUIRED}, (EffectKind.ALERT_HUMAN,))


def _h_verify_ok(record: ChangeRecord, ev: VerifyEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    effects: tuple[EffectKind, ...] = ()
    if record.repair is not None:  # a verified repair reconciles the failed parent (4.2)
        effects = (EffectKind.MARK_PARENT_SUPERSEDED, EffectKind.RELEASE_HOLD_FAILED_VERIFY_HALT,
                   EffectKind.RECONCILE_AMOUNT_CONSUMED)
    return _commit(record, row.tid, "T13", {"verification": Verification.VERIFIED}, effects)


def _h_verify_failed(record: ChangeRecord, ev: VerifyEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T14", {"verification": Verification.FAILED_VERIFY, "effect_known": ev.effect_known},
                   (EffectKind.ALERT_HUMAN,))


def _h_revoke(record: ChangeRecord, ev: RevokeEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    voided = ev.cause in (RevokeCause.EPOCH_DEPENDENCY_CHANGED, RevokeCause.KILL_SWITCH_REVOKE)
    changes: dict[str, object] = {"authorization": Authorization.VOIDED if voided else Authorization.REVOKED,
                                      "claim_expires_at": None, "permit_expires_at": None}
    if record.token is TokenState.ISSUED:
        changes["token"] = TokenState.REVOKED
    return _commit(record, row.tid, "T15", changes)


def _h_operator_resolve(record: ChangeRecord, ev: OperatorResolveEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    if ev.outcome is ResolveOutcome.ABSENT:
        return _commit(record, row.tid, "T16_ABSENT", {
            "execution": Execution.FAILED_APPLY, "call_ownership": CallOwnership.PROVEN_FINISHED})
    attribution = (Attribution.PROVEN if ev.outcome is ResolveOutcome.PRESENT_ATTRIBUTED
                   else Attribution.UNPROVEN_OPERATOR_ATTESTED)
    return _commit(record, row.tid, "T16_PRESENT", {
        "execution": Execution.APPLIED, "call_ownership": CallOwnership.PROVEN_FINISHED, "attribution": attribution})


def _h_retry_verify(record: ChangeRecord, ev: VerifyEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    if ev.matches is True:
        return _commit(record, row.tid, "T17_RETRY_OK", {"verification": Verification.VERIFIED})
    return Applied(replace(record, verify_attempts=record.verify_attempts + 1), (), row.tid)


def _h_close_failed_verify(record: ChangeRecord, ev: OperatorResolveEvidence, row: TransitionRow) -> Applied:  # type: ignore[override]
    return _commit(record, row.tid, "T17_RETRY_OK", {"closed": True})


_HANDLERS: Final = {
    "T1": _h_propose, "T2": _h_validate, "T3_REJECT": _h_reject, "T3_EXPIRE": _h_expire, "T4": _h_approve,
    "T5": _h_claim, "T5x": _h_release_claim, "T6": _h_begin_apply, "T6_REPLAY": _h_begin_replay,
    "T6p": _h_issue_permit, "T6p_DISPATCH": _h_mark_dispatched, "T6r": _h_permit_not_issued, "T6c": _h_cancel_permit,
    "T7": _h_call_success, "T8": _h_refused_before_write, "T9": _h_call_unknown, "T10": _h_resolve_found,
    "T11": _h_resolve_absent, "T12": _h_age_limit, "T13": _h_verify_ok, "T14": _h_verify_failed, "T15": _h_revoke,
    "T16": _h_operator_resolve, "T17_RETRY": _h_retry_verify, "T17_CLOSE": _h_close_failed_verify,
}

_used_guards = {g for row in TRANSITION_TABLE for g in row.guards}
if (set(_HANDLERS) != {r.key for r in TRANSITION_TABLE} or len({r.key for r in TRANSITION_TABLE}) != len(TRANSITION_TABLE)
        or _used_guards != set(_GUARDS) or set(_EVIDENCE) != set(Event)
        or {r.event for r in TRANSITION_TABLE} != set(Event)):
    # import-time guard: every row has a handler, every guard name resolves and is used, every event has evidence
    raise RuntimeError("TRANSITION_TABLE_INCOMPLETE")


# ---- forbidden transitions (section 4, tested against this literal list) ----------------------------------------

@dataclass(frozen=True, slots=True)
class ForbiddenTransition:
    fid: str
    description: str
    code: ErrorCode


FORBIDDEN_TRANSITIONS: Final = (
    ForbiddenTransition("F1", "FAILED_APPLY from a timeout", ErrorCode.APPLY_UNKNOWN),
    ForbiddenTransition("F2", "APPLY_UNKNOWN to APPLIED or FAILED_APPLY without independent PROVEN_FINISHED",
                        ErrorCode.COMPLETION_PROOF_MISSING),
    ForbiddenTransition("F3", "APPLIED to VERIFIED without T13", ErrorCode.EVIDENCE_UNSIGNED),
    ForbiddenTransition("F4", "any transition out of REJECTED, EXPIRED_QUEUED, DUPLICATE_PARKED, ROLLBACK_REFUSED or "
                              "FAILED_APPLY except a new proposal", ErrorCode.SCHEMA_INVALID),
    ForbiddenTransition("F5", "VERIFIED to anything", ErrorCode.SCHEMA_INVALID),
)
_FORBIDDEN_BY_ID: Final = {f.fid: f for f in FORBIDDEN_TRANSITIONS}


def forbidden_transition(before: object, after: object, trigger: object,
                         independent_proof: bool) -> ForbiddenTransition | None:
    """The forbidden-list entry that ``before`` -> ``after`` under ``trigger`` violates, or ``None``."""
    if type(before) is not ChangeRecord or type(after) is not ChangeRecord:
        return None
    if trigger is Event.CALL_UNKNOWN and after.execution is Execution.FAILED_APPLY:
        return _FORBIDDEN_BY_ID["F1"]
    if (before.execution is Execution.APPLY_UNKNOWN and after.execution in (Execution.APPLIED, Execution.FAILED_APPLY)
            and independent_proof is not True):
        return _FORBIDDEN_BY_ID["F2"]
    if (before.verification is not Verification.VERIFIED and after.verification is Verification.VERIFIED
            and trigger not in (Event.VERIFY_OK, Event.RETRY_VERIFY)):
        return _FORBIDDEN_BY_ID["F3"]
    terminal = (before.lifecycle in (Lifecycle.REJECTED, Lifecycle.EXPIRED_QUEUED, Lifecycle.DUPLICATE_PARKED)
                or before.execution in (Execution.ROLLBACK_REFUSED, Execution.FAILED_APPLY))
    if terminal and after != before:
        return _FORBIDDEN_BY_ID["F4"]
    if before.verification is Verification.VERIFIED and after != before:
        return _FORBIDDEN_BY_ID["F5"]
    return None


# ---- the engine -----------------------------------------------------------------------------------------------

def _select_row(record: ChangeRecord | None, event: Event) -> TransitionRow | Refusal:
    rows = [r for r in TRANSITION_TABLE if r.event is event]
    for row in rows:
        if record is None:
            if not row.requires:
                return row
        elif all(getattr(record, dim) in allowed for dim, allowed in row.requires.items()):
            return row
    return Refusal(rows[0].state_refusal, rows[0].tid)


def apply_transition(record: object, event: object, evidence: object) -> Applied | Refusal:
    """Evaluate one event against ``record`` from explicit ``evidence``; never raises, never mutates its inputs.

    ``record`` is ``None`` only for ``Event.PROPOSE``. A wrong event, record type or evidence type, an illegal source
    state, or any failed guard returns a ``Refusal`` carrying one fixed code and the transition id.
    """
    try:
        if type(event) is not Event:
            return Refusal(ErrorCode.SCHEMA_INVALID)
        if type(evidence) is not _EVIDENCE[event]:
            return Refusal(ErrorCode.SCHEMA_INVALID)
        if (record is None) is not (event is Event.PROPOSE) or (record is not None and type(record) is not ChangeRecord):
            return Refusal(ErrorCode.SCHEMA_INVALID)
        row = _select_row(record, event)  # type: ignore[arg-type]
        if type(row) is Refusal:
            return row
        for name in row.guards:  # type: ignore[union-attr]
            code = _GUARDS[name](record, evidence)  # type: ignore[arg-type]
            if code is not None:
                return Refusal(code, row.tid)  # type: ignore[union-attr]
        applied = _HANDLERS[row.key](record, evidence, row)  # type: ignore[union-attr,arg-type]
        if record is not None and applied.record is not None:
            proof = getattr(evidence, "proof_class", ProofClass.NONE) in _INDEPENDENT_PROOFS
            violated = forbidden_transition(record, applied.record, event, proof)
            if violated is not None:
                return Refusal(violated.code, row.tid)  # type: ignore[union-attr]
        return applied
    except Exception:  # noqa: BLE001 - a public transition never raises; an unexpected error is one fixed refusal
        return Refusal(ErrorCode.SCHEMA_INVALID)
