"""Phase 2 sprint S12 offline reference code for the governed purchase-receipt write (EVALUATION_ONLY).

Pure stdlib, no database, no network, no 1C. Contract: ``docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md``
(revision 6). Modules: ``types`` (closed vocabularies, scope, change record), ``proposal`` (typed proposal, canonical
JSON, digests), ``errors`` (closed error-code registry), ``transitions`` (T1..T17 table and engine), ``killswitch``
(precedence matrix) and ``policy`` (grant arithmetic and the caller-class endpoint matrix).
"""
from __future__ import annotations

from .errors import ERROR_INFO, ErrorCode, ErrorInfo, NextAction, Refusal, render
from .killswitch import (
    KILL_MATRIX, SWITCH_OFF, KillDecision, KillSubject, SwitchReading, effective_mode, evaluate, mode_rank,
)
from .policy import (
    CALLER_MATRIX, INTERNAL_OPERATIONS, EffectState, Grant, LedgerOperation, amount_to_reserve, authorize_operation,
    check_operation, consume, ledger_invariant_holds, release, release_hold_error, reservation_for_effect, reserve,
    settle_reservation,
)
from .proposal import (
    MEASURED_SHAPE_MAX_LINES, OPERATION_RULES, RULE_TABLE_VERSION, ChangeProposal, DraftPayload, DuplicateOverride,
    Line, ProposalContext, approval_digest, canonical_json, derive_allowed_effects, parse_proposal, payload_digest,
    payload_to_dict, sha256_hex, APPROVAL_DIGEST_VERSION, approval_canonical_text, digest_of_canonical_text,
)
from .transitions import (
    EVENT_EVIDENCE, FORBIDDEN_TRANSITIONS, LOCK_MATRIX, TRANSITION_TABLE, Applied, ApproveEvidence, BeginApplyEvidence,
    BusinessKeyState, CallUnknownEvidence, CancelPermitEvidence, ClaimEvidence, CompletionEvidence, DispatchEvidence,
    EffectKind, Event, Evidence, ExpireEvidence, ForbiddenTransition, HoldAction, LockAction, LockRow, LogicalKeyState,
    OperatorResolveEvidence, PermitEvidence, PermitNotIssuedEvidence, ProposeEvidence, RejectEvidence,
    ReleaseClaimEvidence, ReleaseReason, RepairContext, RepairPhase, ResolveEvidence, ResolveOutcome,
    RetryVerifyEvidence, RevokeCause, RevokeEvidence, TransitionRow, ValidateEvidence, VerifyEvidence,
    apply_transition, classify_completion, forbidden_transition, repair_authorization_error,
)
from .trust_registry import (
    IdentityScope, KeyVersion, OracleArtifact, ProcessInstanceAttestation, SignerIdentity, TrustedIdentityRegistry,
    process_attestation_preimage, validate_conditional_conflict_terminal_record_set, verify_authorized_record,
)
from .types import (
    ApprovalType, Attribution, Authorization, BudgetCheck, CallOwnership, CallerClass, ChangeKind, ChangeRecord,
    Dispatch, EffectKnown, EvidenceKind, Execution, FailureStage, Hold, HoldCause, KillMode, Lifecycle, NonceState,
    ProofClass, RepairAuth, Reservation, Scope, TokenState, Verification, is_aware_datetime, is_identity_text,
)

__all__ = [
    "Applied", "ApprovalType", "ApproveEvidence", "Attribution", "Authorization", "BeginApplyEvidence", "BudgetCheck",
    "BusinessKeyState", "CALLER_MATRIX", "CallOwnership", "CallUnknownEvidence", "CallerClass", "CancelPermitEvidence",
    "ChangeKind", "ChangeProposal", "ChangeRecord", "ClaimEvidence", "CompletionEvidence", "Dispatch",
    "DispatchEvidence", "DraftPayload", "DuplicateOverride", "ERROR_INFO", "EVENT_EVIDENCE", "EffectKind",
    "EffectKnown", "EffectState", "ErrorCode", "ErrorInfo", "Event", "Evidence", "EvidenceKind", "Execution",
    "ExpireEvidence", "FORBIDDEN_TRANSITIONS", "FailureStage", "ForbiddenTransition", "Grant", "Hold", "HoldAction",
    "HoldCause", "INTERNAL_OPERATIONS", "KILL_MATRIX", "KillDecision", "KillMode", "KillSubject", "LOCK_MATRIX",
    "LedgerOperation", "Lifecycle", "Line", "LockAction", "LockRow", "LogicalKeyState", "MEASURED_SHAPE_MAX_LINES",
    "NextAction", "NonceState", "OPERATION_RULES", "OperatorResolveEvidence", "PermitEvidence",
    "PermitNotIssuedEvidence", "ProofClass", "ProposalContext", "ProposeEvidence", "RULE_TABLE_VERSION", "Refusal",
    "RejectEvidence", "ReleaseClaimEvidence", "ReleaseReason", "RepairAuth", "RepairContext", "RepairPhase",
    "Reservation", "ResolveEvidence", "ResolveOutcome", "RetryVerifyEvidence", "RevokeCause", "RevokeEvidence",
    "IdentityScope", "KeyVersion", "OracleArtifact", "ProcessInstanceAttestation", "SignerIdentity",
    "TrustedIdentityRegistry",
    "SWITCH_OFF", "Scope", "SwitchReading", "TRANSITION_TABLE", "TokenState", "TransitionRow", "ValidateEvidence",
    "APPROVAL_DIGEST_VERSION", "approval_canonical_text", "digest_of_canonical_text",
    "Verification", "VerifyEvidence", "amount_to_reserve", "apply_transition", "approval_digest",
    "authorize_operation", "canonical_json", "check_operation", "classify_completion", "consume",
    "derive_allowed_effects", "effective_mode", "evaluate", "forbidden_transition", "is_aware_datetime",
    "is_identity_text", "ledger_invariant_holds", "mode_rank", "parse_proposal", "payload_digest", "payload_to_dict",
    "process_attestation_preimage", "validate_conditional_conflict_terminal_record_set",
    "verify_authorized_record",
    "release", "release_hold_error", "render", "repair_authorization_error", "reservation_for_effect", "reserve",
    "settle_reservation", "sha256_hex",
]
