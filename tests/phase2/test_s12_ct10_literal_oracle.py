"""Literal CT10 oracle for V2-S12-02.

The expected data below is transcribed from the revision-6 CT10 source and Appendix C of the
contract freeze, with the October 28 amendment applied. It intentionally does not import expected
values from TRANSITION_TABLE, handlers, or implementation guard registries. Guard names are the
offline model's explicit predicate projection of the contract clauses; the prose oracle records
the source semantics and ledger consequences independently.

This test pins the offline model's table projection. It is not runtime evidence, and a passing
projection does not approve the still-open T16 route reconciliation or certify the real adapter.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from business_ai_gateway.phase2.change import (
    Attribution,
    Applied,
    CallOwnership,
    Dispatch,
    ErrorCode,
    Event,
    Execution,
    FailureStage,
    ProofClass,
    Refusal,
    ResolveOutcome,
    Verification,
    apply_transition,
)
from business_ai_gateway.phase2.change import transitions as tr
from tests.phase2._change_helpers import (
    applied,
    applying,
    approved,
    claimed,
    dispatched,
    failed_verify,
    good,
    proposed,
    triage,
    unknown,
    validated,
)


@dataclass(frozen=True)
class LiteralRow:
    key: str
    source: str
    lineage: str
    from_state: tuple[tuple[str, tuple[str, ...]], ...]
    event: str
    guard_summary: str
    destination: str
    ledger_effect_codes: tuple[str, ...]
    ledger_effects: str


@dataclass(frozen=True)
class ModelRow:
    key: str
    tid: str
    event: str
    requires: tuple[tuple[str, tuple[str, ...]], ...]
    target: str
    guards: tuple[str, ...]
    refusal: str


@dataclass(frozen=True)
class SourceModelMapping:
    source_key: str
    model_key: str
    disposition: str
    model_guards: tuple[str, ...]
    handler: str
    lock_keys: tuple[str, ...]
    handler_effects: tuple[str, ...]
    scenario: str
    open_delta: str | None = None


# Source-derived typed ledger effects for one valid offline path per row/variant.
SOURCE_EFFECTS_BY_ROW = {
    "T1": (), "T2": (), "T3_REJECT": (), "T3_EXPIRE": (), "T4": ("CONSUME_NONCE",),
    "T5": ("RESERVE_BUDGET", "MINT_CLAIM_TOKEN", "ACQUIRE_LOCKS"), "T5x": (),
    "T6": ("COMMIT_APPLYING_AND_OWNERSHIP_ROW",), "T6_REPLAY": ("REPLAY_EXISTING_TICKET",),
    "T6p": ("SIGN_PERMIT",), "T6p_DISPATCH": ("RECORD_DISPATCHED",), "T6r": (),
    "T6c": ("INVALIDATE_PERMIT",), "T7": (), "T8": (),
    "T9": ("OPEN_HOLD_CALL_OWNERSHIP",), "T10": ("RELEASE_HOLD_CALL_OWNERSHIP",),
    "T11": ("RELEASE_HOLD_CALL_OWNERSHIP",), "T12": ("ALERT_HUMAN",), "T13": (),
    "T14": ("ALERT_HUMAN", "OPEN_HOLD_FAILED_VERIFY_HALT"), "T15": (),
    "T16": ("RELEASE_HOLD_CALL_OWNERSHIP",),
    "T17_RETRY": ("RELEASE_HOLD_FAILED_VERIFY_HALT",),
    "T17_CLOSE": ("RELEASE_HOLD_FAILED_VERIFY_HALT",),
}


def _row(key, source, lineage, from_state, event, guards, destination, effects):
    normalized_state = tuple(sorted(
        (dimension, tuple(sorted(values))) for dimension, values in from_state))
    return LiteralRow(key, source, lineage, normalized_state, event, guards, destination,
                      SOURCE_EFFECTS_BY_ROW[key], effects)


def _model(key, tid, event, requires, target, guards, refusal="SCHEMA_INVALID"):
    return ModelRow(key, tid, event, requires, target, guards, refusal)


# 25 literal row/variant entries. Source labels refer to the package's approved precedence:
# draft §4 for inherited CT10; freeze §§2–3, 5–6 for overlays; amendment item 4 for T6 period.
CT10_ORACLE = (
    _row("T1", "draft §4/T1", "inherited", (), "PROPOSE",
         "valid schema/scope; entitled requester; epoch read; compatible logical key",
         "lifecycle=PROPOSED", "append intent; replay same digest receipt; no reservation"),
    _row("T2", "draft §4/T2", "inherited", (("lifecycle", ("PROPOSED",)),), "VALIDATE",
         "server preview; checked business key, budget, qualified shape; derive allowed effects",
         "lifecycle=VALIDATED or DUPLICATE_PARKED", "collision parks this change; no reservation"),
    _row("T3_REJECT", "draft §4/T3", "inherited variant",
         (("lifecycle", ("PROPOSED", "VALIDATED")), ("authorization", ("NONE", "APPROVED")),
           ("execution", ("NOT_STARTED",))), "REJECT",
         "entitled approver rejects", "lifecycle=REJECTED", "terminal; no effect or reservation"),
    _row("T3_EXPIRE", "draft §4/T3", "inherited variant",
         (("lifecycle", ("PROPOSED", "VALIDATED")), ("authorization", ("NONE", "APPROVED")),
          ("execution", ("NOT_STARTED",))), "EXPIRE",
         "expiry reached; sweep driven", "lifecycle=EXPIRED_QUEUED, authorization=EXPIRED",
         "terminal; no effect or reservation"),
    _row("T4", "draft §4/T4", "inherited",
         (("lifecycle", ("VALIDATED",)), ("authorization", ("NONE",))), "APPROVE",
          "requester differs from approver; one-time nonce; digest set bound; approver entitled at epoch",
          "authorization=APPROVED", "consume nonce; immutable signed approval record"),
    _row("T5", "draft §4/T5, §§4.1–4.2", "inherited including repair variant",
         (("lifecycle", ("VALIDATED",)), ("authorization", ("APPROVED",)),
          ("execution", ("NOT_STARTED",))), "CLAIM",
         "current approval/epochs; switch below STOP_ADMIT; allowed hold state; parent verified except matching repair; scope/target match; locks/lease free; budget reserved atomically",
          "authorization=CLAIMED, execution=NOT_STARTED, claim_generation+1",
         "mint claim token; acquire target/key locks and writer lease; reserve budget (repair hands off target lock)"),
    _row("T5x", "draft §§4, 4.1–4.2", "inherited",
         (("authorization", ("CLAIMED",)), ("execution", ("NOT_STARTED",))), "RELEASE_CLAIM",
         "claim TTL, blocking switch, or failed pre-dispatch T6 guard",
          "authorization=APPROVED (EXPIRED or VOIDED when applicable), token SUPERSEDED",
         "release locks/lease/reservation; repair returns target lock to parent and preserves parent halt"),
    _row("T6", "draft §4/T6; amendment item 4", "inherited + period observation overlay",
         (("authorization", ("CLAIMED",)), ("execution", ("NOT_STARTED",)), ("token", ("ISSUED",))),
         "BEGIN_APPLY",
         "current epoch/generation; live approval; switch off; no disallowed hold; version/fingerprint/dependents match; positively observe period open before remaining digest comparison",
          "execution=APPLYING, dispatch=NOT_PERMITTED",
         "commit APPLYING and call-ownership/pre-image row atomically; closed period => PERIOD_CLOSED; missing observation or other mismatch => DIGEST_MISMATCH"),
    _row("T6_REPLAY", "draft §4 generation fencing; freeze §§2.1, 3", "derived replay variant",
         (("authorization", ("CLAIMED",)), ("execution", ("APPLYING",)), ("token", ("CONSUMED",)),
          ("dispatch", ("NOT_PERMITTED", "PERMITTED"))), "BEGIN_APPLY",
         "same current generation; ticket not dispatched; no superseding claim",
          "unchanged (the existing ticket is returned)", "read-only replay; never mint a second permit/call"),
    _row("T6p", "draft §4/T6p; freeze §§2.1, 3", "inherited + checkpoint overlay",
         (("execution", ("APPLYING",)), ("dispatch", ("NOT_PERMITTED",))), "ISSUE_PERMIT",
         "checkpoint covers committed T6 head and is read back; switch off; current generation",
          "dispatch=PERMITTED", "sign generation-bound permit; no physical call yet; failure uses T6r"),
    _row("T6p_DISPATCH", "draft §4/T6p; freeze §§2.1, 3", "derived CAS variant",
         (("execution", ("APPLYING",)), ("dispatch", ("PERMITTED",))), "MARK_DISPATCHED",
         "permit/checkpoint/generation/switch/hold valid; PERMITTED to DISPATCHED CAS wins",
          "dispatch=DISPATCHED", "record dispatch before one physical call; cancel winner forbids call"),
    _row("T6r", "draft §4/T6r", "inherited",
         (("authorization", ("CLAIMED",)), ("execution", ("APPLYING",)),
          ("dispatch", ("NOT_PERMITTED",))), "PERMIT_NOT_ISSUED",
         "checkpoint unavailable, switch/hold, or permit TTL; no permit exists",
          "authorization=APPROVED, execution=NOT_STARTED, token SUPERSEDED", "no call possible; release locks/lease/reservation or repair handback"),
    _row("T6c", "draft §4/T6c", "inherited",
         (("authorization", ("CLAIMED",)), ("execution", ("APPLYING",)),
          ("dispatch", ("PERMITTED",))), "CANCEL_PERMIT",
         "switch/hold/superseded generation/TTL; atomic cancel CAS and permit invalidation win",
          "dispatch=CANCELLED_UNDISPATCHED, authorization=APPROVED, execution=NOT_STARTED",
         "only winning cancel CAS proves nondispatch and releases resources; DISPATCHED follows T7/T9"),
    _row("T7", "draft §4/T7; freeze §§2.1–2.3, 3", "inherited + evidence overlay",
         (("authorization", ("CLAIMED",)), ("execution", ("APPLYING",)),
          ("dispatch", ("DISPATCHED",))), "CALL_SUCCESS",
         "authenticated receipt and signed result/completion bind call, CAS, generation, identity, operation and immutable evidence; return value alone insufficient",
          "execution=APPLIED, call_ownership=PROVEN_FINISHED, attribution=PROVEN",
         "consume reservation; checkpoint/persist result; verification due; persistence failure stays held"),
    _row("T8", "draft §4/T8; freeze §§2.1, 3", "inherited + invocation-stage overlay",
         (("authorization", ("CLAIMED",)), ("execution", ("APPLYING",)),
          ("dispatch", ("DISPATCHED",))), "REFUSED_BEFORE_WRITE",
         "durable CAS/process-bound NOT_INVOKED receipt and operation no-effect proof; entered conditional conflict excluded; refusal code alone insufficient",
          "execution=FAILED_APPLY or ROLLBACK_REFUSED, or APPROVED again for a transient LOCK_BUSY",
         "release only with exact durable proof; entered conflict remains APPLY_UNKNOWN/held for completion, no-effect evidence and governed T16"),
    _row("T9", "draft §4/T9; freeze §§2.1–2.3, 3", "inherited + fail-closed reinforcement",
         (("authorization", ("CLAIMED",)), ("execution", ("APPLYING",)),
          ("dispatch", ("DISPATCHED",))), "CALL_UNKNOWN",
         "neither valid T7 result nor complete T8 proof established",
          "execution=APPLY_UNKNOWN, call_ownership=POSSIBLY_EXECUTING",
         "retain target lock, lease, reservation and CALL_OWNERSHIP hold; no automatic retry/release"),
    _row("T10", "draft §4/T10; freeze §§2.2–3, 5", "inherited + evidence/attribution overlay",
         (("execution", ("APPLY_UNKNOWN",)),), "RESOLVE_FOUND",
         "independent completion proof; healthy reader; settle period; complete observation; exact effect identity and attribution with bound evidence",
          "execution=APPLIED, call_ownership=PROVEN_FINISHED, attribution=PROVEN",
         "consume reservation/release hold only after accepted proof; unattributed present effect routes to T12"),
    _row("T11", "draft §4/T11; freeze §§2.1–3, 5", "inherited + healthy-absence overlay",
         (("execution", ("APPLY_UNKNOWN",)),), "RESOLVE_ABSENT",
         "independent completion proof; healthy reader; settle period; complete healthy absence observation",
          "execution=FAILED_APPLY, call_ownership=PROVEN_FINISHED", "release reservation, locks, lease and hold only with proof; timeout/marker absence insufficient"),
    _row("T12", "draft §4/T12", "inherited",
         (("execution", ("APPLY_UNKNOWN",)),), "AGE_LIMIT",
         "durable bounded attempts/window exhausted or effect lacks attribution",
          "execution=TRIAGE_REQUIRED", "retain hold/lease/target lock/reservation; alert; only governed T16 resolution"),
    _row("T13", "draft §4/T13; freeze §§2.2–3, 5", "inherited + exact-evidence overlay",
         (("execution", ("APPLIED",)), ("verification", ("NOT_VERIFIED",))), "VERIFY_OK",
         "independently signed/bound fields, movement multiset and version evidence exactly match oracle and operation rule table",
          "verification=VERIFIED", "release target/key locks; bounded retries; acknowledgement/partial match insufficient"),
    _row("T14", "draft §4/T14; freeze evidence model", "inherited + typed evidence overlay",
         (("execution", ("APPLIED",)), ("verification", ("NOT_VERIFIED",))), "VERIFY_FAILED",
         "bound independent observation proves an unexpected/missing field, movement or version",
          "verification=FAILED_VERIFY", "record effect_known; retain target lock and consumed reservation; open halt and alert"),
    _row("T15", "draft §4/T15", "inherited",
         (("lifecycle", ("VALIDATED",)), ("authorization", ("APPROVED", "CLAIMED")),
          ("execution", ("NOT_STARTED",))), "REVOKE",
         "session/role/approver revoked or listed epoch dependency changed",
          "authorization=VOIDED or REVOKED", "release only pre-effect resources; unrelated epoch change does not revoke"),
    _row("T16", "draft §4/T16; freeze §§2.1–3, 5", "inherited + completion/evidence overlay",
         (("execution", ("TRIAGE_REQUIRED",)),), "OPERATOR_RESOLVE",
         "T10/T11-grade completion and observation; explicit attribution disposition; operator and witness are distinct and neither is requester; witness differs from approver, while an otherwise eligible approver may be operator signer; open ownership hold; entered conflict requires exact receipt, completion proof, independent no-effect observation, and V3 causal chain; route only after T12 exhausted bounded attempts/window or genuinely unattributable observed effect",
          "APPLIED (attributed or UNPROVEN_OPERATOR_ATTESTED) or FAILED_APPLY",
         "atomic hold/reservation resolution; present consumes; absent releases; upstream authenticated evidence-chain/runtime provision remains NOT_VERIFIED"),
    _row("T17_RETRY", "draft §4/T17; freeze §3", "inherited retry variant",
         (("verification", ("FAILED_VERIFY",)), ("closed", ("False",))), "RETRY_VERIFY",
         "worker supplies bound evidence; retries remain below 3",
          "verification=VERIFIED, or still FAILED_VERIFY with verify_attempts+1",
         "success releases halt/target lock; reservation remains consumed"),
    _row("T17_CLOSE", "draft §4/T17 and hold rules", "inherited closure variant",
         (("verification", ("FAILED_VERIFY",)), ("closed", ("False",))), "CLOSE_FAILED_VERIFY",
         "governed evidence-bound closure, required operator/two-person authority and complete observation",
          "FAILED_VERIFY change closed, halt released", "release halt only under recorded closure; never refund or claim VERIFIED"),
)


# Exact model projection, manually transcribed from the source crosswalk above. These are plain
# strings; the implementation enum objects are read only on the actual side of the comparison.
MODEL_PROJECTION = (
    _model("T1", "T1", "PROPOSE", (), "lifecycle=PROPOSED",
           ("kill_off", "schema_valid", "scope_resolved", "requester_entitled", "epoch_read", "logical_key_compatible")),
    _model("T2", "T2", "VALIDATE", (("lifecycle", ("PROPOSED",)),), "lifecycle=VALIDATED or DUPLICATE_PARKED",
           ("kill_off", "preview_built", "shape_qualified", "effects_derived", "budget_precheck", "business_key_checked")),
    _model("T3_REJECT", "T3", "REJECT", (("authorization", ("APPROVED", "NONE")), ("execution", ("NOT_STARTED",)), ("lifecycle", ("PROPOSED", "VALIDATED"))), "lifecycle=REJECTED", ("actor_is_approver",)),
    _model("T3_EXPIRE", "T3", "EXPIRE", (("authorization", ("APPROVED", "NONE")), ("execution", ("NOT_STARTED",)), ("lifecycle", ("PROPOSED", "VALIDATED"))), "lifecycle=EXPIRED_QUEUED, authorization=EXPIRED", ("expiry_reached",)),
    _model("T4", "T4", "APPROVE", (("authorization", ("NONE",)), ("lifecycle", ("VALIDATED",))), "authorization=APPROVED", ("kill_off", "approval_window_open", "approver_independent", "approver_entitled", "approval_id_valid", "epoch_current", "nonce_issued", "digest_bound", "override_bound", "unproven_flag_bound", "checkpoint_ok")),
    _model("T5", "T5", "CLAIM", (("authorization", ("APPROVED",)), ("execution", ("NOT_STARTED",)), ("lifecycle", ("VALIDATED",))), "authorization=CLAIMED, execution=NOT_STARTED, claim_generation+1", ("caller_is_requester", "approval_window_open", "epoch_unchanged", "kill_off", "claim_holds_clear", "claim_parent_ok", "scope_equal", "target_class_equal", "locks_free", "budget_reserved")),
    _model("T5x", "T5x", "RELEASE_CLAIM", (("authorization", ("CLAIMED",)), ("execution", ("NOT_STARTED",))), "authorization=APPROVED (EXPIRED or VOIDED when applicable), token SUPERSEDED", ("release_cause",)),
    _model("T6", "T6", "BEGIN_APPLY", (("authorization", ("CLAIMED",)), ("execution", ("NOT_STARTED",)), ("token", ("ISSUED",))), "execution=APPLYING, dispatch=NOT_PERMITTED", ("generation_current", "caller_may_begin", "claim_alive", "epoch_equals_claim", "kill_off", "holds_and_repair_t6", "approval_window_open", "version_equals_approved", "fingerprint_authenticated", "period_open", "state_digest_equal", "writer_lock_held", "ownership_row_committed"), "TICKET_SUPERSEDED"),
    _model("T6_REPLAY", "T6", "BEGIN_APPLY", (("authorization", ("CLAIMED",)), ("dispatch", ("NOT_PERMITTED", "PERMITTED")), ("execution", ("APPLYING",)), ("token", ("CONSUMED",))), "unchanged (the existing ticket is returned)", ("generation_current", "caller_may_begin"), "TICKET_SUPERSEDED"),
    _model("T6p", "T6p", "ISSUE_PERMIT", (("dispatch", ("NOT_PERMITTED",)), ("execution", ("APPLYING",))), "dispatch=PERMITTED", ("generation_current", "kill_off", "checkpoint_covers_head", "permit_window_open", "holds_and_repair_permit"), "PERMIT_MISSING"),
    _model("T6p_DISPATCH", "T6p", "MARK_DISPATCHED", (("dispatch", ("PERMITTED",)), ("execution", ("APPLYING",))), "dispatch=DISPATCHED", ("caller_is_writer", "generation_current", "kill_off", "permit_signature_valid", "checkpoint_sequence_verified", "holds_and_repair_writer"), "PERMIT_MISSING"),
    _model("T6r", "T6r", "PERMIT_NOT_ISSUED", (("authorization", ("CLAIMED",)), ("dispatch", ("NOT_PERMITTED",)), ("execution", ("APPLYING",))), "authorization=APPROVED, execution=NOT_STARTED, token SUPERSEDED", ("no_permitted_event", "permit_not_issued_cause")),
    _model("T6c", "T6c", "CANCEL_PERMIT", (("authorization", ("CLAIMED",)), ("dispatch", ("PERMITTED",)), ("execution", ("APPLYING",))), "dispatch=CANCELLED_UNDISPATCHED, authorization=APPROVED, execution=NOT_STARTED", ("cancel_cause", "cancel_cas_won", "permit_invalidated"), "LOCK_BUSY"),
    _model("T7", "T7", "CALL_SUCCESS", (("authorization", ("CLAIMED",)), ("dispatch", ("DISPATCHED",)), ("execution", ("APPLYING",))), "execution=APPLIED, call_ownership=PROVEN_FINISHED, attribution=PROVEN", ("caller_is_writer", "generation_current", "completion_signed", "completion_is_success", "completion_artifacts_bound", "checkpoint_ok"), "PERMIT_MISSING"),
    _model("T8", "T8", "REFUSED_BEFORE_WRITE", (("authorization", ("CLAIMED",)), ("dispatch", ("DISPATCHED",)), ("execution", ("APPLYING",))), "execution=FAILED_APPLY or ROLLBACK_REFUSED, or APPROVED again for a transient LOCK_BUSY", ("caller_is_writer", "generation_current", "completion_signed", "completion_is_refusal", "refusal_artifacts_bound", "checkpoint_ok"), "PERMIT_MISSING"),
    _model("T9", "T9", "CALL_UNKNOWN", (("authorization", ("CLAIMED",)), ("dispatch", ("DISPATCHED",)), ("execution", ("APPLYING",))), "execution=APPLY_UNKNOWN, call_ownership=POSSIBLY_EXECUTING", ("caller_is_writer_or_worker", "generation_current", "completion_is_unknown"), "PERMIT_MISSING"),
    _model("T10", "T10", "RESOLVE_FOUND", (("execution", ("APPLY_UNKNOWN",)),), "execution=APPLIED, call_ownership=PROVEN_FINISHED, attribution=PROVEN", ("caller_is_worker", "resolve_signed", "independent_proof", "observation_complete", "resolve_evidence_bound", "not_entered_conditional_conflict", "effect_present", "attribution_proven")),
    _model("T11", "T11", "RESOLVE_ABSENT", (("execution", ("APPLY_UNKNOWN",)),), "execution=FAILED_APPLY, call_ownership=PROVEN_FINISHED", ("caller_is_worker", "resolve_signed", "independent_proof", "observation_complete", "resolve_evidence_bound", "not_entered_conditional_conflict", "effect_absent", "checkpoint_ok")),
    _model("T12", "T12", "AGE_LIMIT", (("execution", ("APPLY_UNKNOWN",)),), "execution=TRIAGE_REQUIRED", ("caller_is_worker", "triage_cause")),
    _model("T13", "T13", "VERIFY_OK", (("execution", ("APPLIED",)), ("verification", ("NOT_VERIFIED",))), "verification=VERIFIED", ("caller_is_worker", "evidence_bound", "verify_matches")),
    _model("T14", "T14", "VERIFY_FAILED", (("execution", ("APPLIED",)), ("verification", ("NOT_VERIFIED",))), "verification=FAILED_VERIFY", ("caller_is_worker", "evidence_bound", "verify_mismatch")),
    _model("T15", "T15", "REVOKE", (("authorization", ("APPROVED", "CLAIMED")), ("execution", ("NOT_STARTED",)), ("lifecycle", ("VALIDATED",))), "authorization=VOIDED or REVOKED", ("revoke_cause",)),
    _model("T16", "T16", "OPERATOR_RESOLVE", (("execution", ("TRIAGE_REQUIRED",)),), "APPLIED (attributed or UNPROVEN_OPERATOR_ATTESTED) or FAILED_APPLY", ("two_person", "outcome_consistent", "independent_proof", "operator_signed", "observation_complete", "call_ownership_hold_open", "operator_resolution_evidence_bound", "operator_conditional_conflict_chain_bound", "operator_attribution", "checkpoint_ok")),
    _model("T17_RETRY", "T17", "RETRY_VERIFY", (("closed", ("False",)), ("verification", ("FAILED_VERIFY",))), "verification=VERIFIED, or still FAILED_VERIFY with verify_attempts+1", ("caller_is_worker", "evidence_bound", "retry_bound")),
    _model("T17_CLOSE", "T17", "CLOSE_FAILED_VERIFY", (("closed", ("False",)), ("verification", ("FAILED_VERIFY",))), "FAILED_VERIFY change closed, halt released", ("two_person", "operator_signed", "observation_complete")),
)


# One explicit source→model disposition per CT10 row. The model guard names, handler identity,
# lock-matrix keys and positive synthetic outcome effects are literal expectations, never read
# back from the implementation when constructing the oracle.
SOURCE_MODEL_MAPPING = (
    SourceModelMapping("T1", "T1", "INHERITED", ("kill_off", "schema_valid", "scope_resolved", "requester_entitled", "epoch_read", "logical_key_compatible"), "_h_propose", (), (), "none"),
    SourceModelMapping("T2", "T2", "INHERITED", ("kill_off", "preview_built", "shape_qualified", "effects_derived", "budget_precheck", "business_key_checked"), "_h_validate", (), (), "proposed"),
    SourceModelMapping("T3_REJECT", "T3_REJECT", "INHERITED_VARIANT", ("actor_is_approver",), "_h_reject", (), (), "proposed"),
    SourceModelMapping("T3_EXPIRE", "T3_EXPIRE", "INHERITED_VARIANT", ("expiry_reached",), "_h_expire", (), (), "proposed"),
    SourceModelMapping("T4", "T4", "INHERITED", ("kill_off", "approval_window_open", "approver_independent", "approver_entitled", "approval_id_valid", "epoch_current", "nonce_issued", "digest_bound", "override_bound", "unproven_flag_bound", "checkpoint_ok"), "_h_approve", (), ("CONSUME_NONCE",), "validated"),
    SourceModelMapping("T5", "T5", "INHERITED_WITH_REPAIR_VARIANT", ("caller_is_requester", "approval_window_open", "epoch_unchanged", "kill_off", "claim_holds_clear", "claim_parent_ok", "scope_equal", "target_class_equal", "locks_free", "budget_reserved"), "_h_claim", ("T5", "T5_REPAIR"), ("RESERVE_BUDGET", "MINT_CLAIM_TOKEN", "ACQUIRE_LOCKS"), "approved"),
    SourceModelMapping("T5x", "T5x", "INHERITED", ("release_cause",), "_h_release_claim", ("T5x",), (), "claimed"),
    SourceModelMapping("T6", "T6", "AMENDMENT_OVERLAY", ("generation_current", "caller_may_begin", "claim_alive", "epoch_equals_claim", "kill_off", "holds_and_repair_t6", "approval_window_open", "version_equals_approved", "fingerprint_authenticated", "period_open", "state_digest_equal", "writer_lock_held", "ownership_row_committed"), "_h_begin_apply", ("T6",), ("COMMIT_APPLYING_AND_OWNERSHIP_ROW",), "claimed", "`period_open` is a synthetic summary; no live period source observation is covered."),
    SourceModelMapping("T6_REPLAY", "T6_REPLAY", "DERIVED_REPLAY_VARIANT", ("generation_current", "caller_may_begin"), "_h_begin_replay", (), ("REPLAY_EXISTING_TICKET",), "applying"),
    SourceModelMapping("T6p", "T6p", "FREEZE_OVERLAY", ("generation_current", "kill_off", "checkpoint_covers_head", "permit_window_open", "holds_and_repair_permit"), "_h_issue_permit", ("T6p",), ("SIGN_PERMIT",), "applying", "Checkpoint summary is synthetic; external checkpoint storage/read-back is not exercised."),
    SourceModelMapping("T6p_DISPATCH", "T6p_DISPATCH", "DERIVED_CAS_VARIANT", ("caller_is_writer", "generation_current", "kill_off", "permit_signature_valid", "checkpoint_sequence_verified", "holds_and_repair_writer"), "_h_mark_dispatched", ("T6p",), ("RECORD_DISPATCHED",), "permitted", "The dispatch CAS is modeled; ledger atomicity and physical invocation are not exercised."),
    SourceModelMapping("T6r", "T6r", "INHERITED", ("no_permitted_event", "permit_not_issued_cause"), "_h_permit_not_issued", ("T6r",), (), "applying"),
    SourceModelMapping("T6c", "T6c", "INHERITED", ("cancel_cause", "cancel_cas_won", "permit_invalidated"), "_h_cancel_permit", ("T6c",), ("INVALIDATE_PERMIT",), "permitted"),
    SourceModelMapping("T7", "T7", "FREEZE_OVERLAY", ("caller_is_writer", "generation_current", "completion_signed", "completion_is_success", "completion_artifacts_bound", "checkpoint_ok"), "_h_call_success", ("T7",), (), "dispatched", "Receipt/result/persistence booleans are synthetic summaries, not authenticated envelope proof."),
    SourceModelMapping("T8", "T8", "FREEZE_OVERLAY", ("caller_is_writer", "generation_current", "completion_signed", "completion_is_refusal", "refusal_artifacts_bound", "checkpoint_ok"), "_h_refused_before_write", ("T8",), (), "dispatched", "NOT_INVOKED and durable receipt flags are synthetic summaries, not process/CAS-bound proof."),
    SourceModelMapping("T9", "T9", "FREEZE_REINFORCEMENT", ("caller_is_writer_or_worker", "generation_current", "completion_is_unknown"), "_h_call_unknown", ("T9",), ("OPEN_HOLD_CALL_OWNERSHIP",), "dispatched", "Fail-closed model behavior is offline; no writer crash/timeout boundary is exercised."),
    SourceModelMapping("T10", "T10", "FREEZE_OVERLAY", ("caller_is_worker", "resolve_signed", "independent_proof", "observation_complete", "resolve_evidence_bound", "not_entered_conditional_conflict", "effect_present", "attribution_proven"), "_h_resolve_found", ("T10",), ("RELEASE_HOLD_CALL_OWNERSHIP",), "unknown", "Healthy absence/completion binding and conflict-history flags are synthetic, not source-reader evidence."),
    SourceModelMapping("T11", "T11", "FREEZE_OVERLAY", ("caller_is_worker", "resolve_signed", "independent_proof", "observation_complete", "resolve_evidence_bound", "not_entered_conditional_conflict", "effect_absent", "checkpoint_ok"), "_h_resolve_absent", ("T11",), ("RELEASE_HOLD_CALL_OWNERSHIP",), "unknown", "Healthy absence/completion and conflict-history flags are synthetic, not source-reader evidence."),
    SourceModelMapping("T12", "T12", "INHERITED", ("caller_is_worker", "triage_cause"), "_h_age_limit", ("T12",), ("ALERT_HUMAN",), "unknown"),
    SourceModelMapping("T13", "T13", "FREEZE_OVERLAY", ("caller_is_worker", "evidence_bound", "verify_matches"), "_h_verify_ok", ("T13",), (), "applied", "Field/movement/version and oracle-match flags are synthetic, not independent 1C read evidence."),
    SourceModelMapping("T14", "T14", "FREEZE_EVIDENCE_OVERLAY", ("caller_is_worker", "evidence_bound", "verify_mismatch"), "_h_verify_failed", ("T14",), ("ALERT_HUMAN", "OPEN_HOLD_FAILED_VERIFY_HALT"), "applied"),
    SourceModelMapping("T15", "T15", "INHERITED", ("revoke_cause",), "_h_revoke", ("T15",), (), "approved"),
    SourceModelMapping("T16", "T16", "FREEZE_OVERLAY", ("two_person", "outcome_consistent", "independent_proof", "operator_signed", "observation_complete", "call_ownership_hold_open", "operator_resolution_evidence_bound", "operator_conditional_conflict_chain_bound", "operator_attribution", "checkpoint_ok"), "_h_operator_resolve", ("T16_ABSENT", "T16_PRESENT"), ("RELEASE_HOLD_CALL_OWNERSHIP",), "triage", "Source route is T9→T12→T16 only after T12 exhausted bounded attempts/window or genuinely unattributable observed-effect trigger; upstream authenticated evidence-chain/runtime provision remains NOT_VERIFIED."),
    SourceModelMapping("T17_RETRY", "T17_RETRY", "INHERITED_RETRY_VARIANT", ("caller_is_worker", "evidence_bound", "retry_bound"), "_h_retry_verify", ("T17_RETRY_OK",), ("RELEASE_HOLD_FAILED_VERIFY_HALT",), "failed_verify"),
    SourceModelMapping("T17_CLOSE", "T17_CLOSE", "INHERITED_CLOSE_VARIANT", ("two_person", "operator_signed", "observation_complete"), "_h_close_failed_verify", ("T17_RETRY_OK",), ("RELEASE_HOLD_FAILED_VERIFY_HALT",), "failed_verify"),
)


# Contract §4.1 lock/effect rows are literal source expectations. The code's LOCK_MATRIX is
# compared field-by-field below, including proof text and reservation/hold outcomes.
LOCK_MATRIX_ORACLE = (
    ("T5", "ACQUIRE", "ACQUIRE", "ACQUIRE", "NONE", "RESERVED", False, "claim transaction"),
    ("T5_REPAIR", "HANDOFF", "ACQUIRE", "ACQUIRE", "NONE", "RESERVED", False, "section 4.2"),
    ("T5x", "RELEASE", "RELEASE", "RELEASE", "NONE", "RELEASED", True, "no PERMITTED event, or TTL expiry before any permit"),
    ("T6", "KEEP", "KEEP", "KEEP", "NONE", None, False, ""),
    ("T6p", "KEEP", "KEEP", "KEEP", "NONE", None, False, ""),
    ("T6r", "RELEASE", "RELEASE", "RELEASE", "NONE", "RELEASED", True, "no PERMITTED event, or TTL expiry before any permit"),
    ("T6c", "RELEASE", "RELEASE", "RELEASE", "NONE", "RELEASED", True, "successful CAS PERMITTED to CANCELLED_UNDISPATCHED with the permit invalidated"),
    ("T7", "KEEP", "RELEASE", "RELEASE", "NONE", "CONSUMED", False, "writer completion record (proof class a)"),
    ("T8", "RELEASE", "RELEASE", "RELEASE", "NONE", "RELEASED", True, "signed PRE_WRITE stage evidence"),
    ("T9", "KEEP", "KEEP", "KEEP", "OPEN_CALL_OWNERSHIP", None, False, ""),
    ("T10", "KEEP", "RELEASE", "RELEASE", "RELEASE_CALL_OWNERSHIP", "CONSUMED", False, "proof class a or b, attribution proof"),
    ("T11", "RELEASE", "RELEASE", "RELEASE", "RELEASE_CALL_OWNERSHIP", "RELEASED", True, "proof class a or b, healthy complete absence observation"),
    ("T12", "KEEP", "KEEP", "KEEP", "KEEP_CALL_OWNERSHIP", None, False, ""),
    ("T13", "RELEASE", "RELEASE", "NA", "NONE", "CONSUMED", False, "verification evidence"),
    ("T14", "KEEP", "RELEASE", "NA", "OPEN_FAILED_VERIFY_HALT", "CONSUMED", False, ""),
    ("T15", "RELEASE", "RELEASE", "RELEASE", "NONE", "RELEASED", True, "pre-dispatch only"),
    ("T16_ABSENT", "RELEASE", "RELEASE", "RELEASE", "RELEASE_CALL_OWNERSHIP", "RELEASED", True, "completion proof (proof class a or b)"),
    ("T16_PRESENT", "KEEP", "RELEASE", "RELEASE", "RELEASE_CALL_OWNERSHIP", "CONSUMED", False, "completion proof (proof class a or b)"),
    ("T17_RETRY_OK", "RELEASE", "NA", "NA", "RELEASE_FAILED_VERIFY_HALT", None, False, "verification evidence"),
)


KNOWN_RECONCILIATION_OPEN = (
    "T16 upstream authenticated evidence-chain/runtime provision is NOT_VERIFIED; offline summary flags "
    "do not prove the source adapter or ledger evidence chain",
    "synthetic receipt/completion/observation flags are not signed envelope or runtime evidence",
    "G3 operator-facing status projection is separately PARTIAL",
)


# Ordered clause-to-predicate groups. Each clause is sourced from the CT10 row/crosswalk; its
# literal model guard names are then compared to the mapping, projection and actual table sequence.
SOURCE_GUARD_BINDINGS = {
    "T1": (("switch off", ("kill_off",)), ("schema and scope resolved", ("schema_valid", "scope_resolved")),
           ("requester entitlement and epoch", ("requester_entitled", "epoch_read")),
           ("logical key compatible", ("logical_key_compatible",))),
    "T2": (("switch off and server preview", ("kill_off", "preview_built")),
           ("qualified shape and derived effects", ("shape_qualified", "effects_derived")),
           ("budget precheck and business key", ("budget_precheck", "business_key_checked"))),
    "T3_REJECT": (("approver rejects", ("actor_is_approver",)),),
    "T3_EXPIRE": (("expiry reached", ("expiry_reached",)),),
    "T4": (("switch and approval window", ("kill_off", "approval_window_open")),
           ("independent entitled approver with valid id", ("approver_independent", "approver_entitled", "approval_id_valid")),
           ("current epoch and one-time nonce", ("epoch_current", "nonce_issued")),
           ("approval binds digest, override and attribution flag", ("digest_bound", "override_bound", "unproven_flag_bound")),
           ("checkpoint accepted", ("checkpoint_ok",))),
    "T5": (("requester and approval window", ("caller_is_requester", "approval_window_open")),
           ("claim epoch and kill switch", ("epoch_unchanged", "kill_off")),
           ("no disallowed hold and verified parent or exact repair", ("claim_holds_clear", "claim_parent_ok")),
           ("scope and target class match", ("scope_equal", "target_class_equal")),
           ("locks free and budget reserved atomically", ("locks_free", "budget_reserved"))),
    "T5x": (("claim release has a contract cause", ("release_cause",)),),
    "T6": (("current generation, permitted caller and live claim", ("generation_current", "caller_may_begin", "claim_alive")),
           ("claim epoch and switch", ("epoch_equals_claim", "kill_off")),
           ("hold/repair and approval still valid", ("holds_and_repair_t6", "approval_window_open")),
           ("approved version and authenticated base", ("version_equals_approved", "fingerprint_authenticated")),
           ("positive open-period observation before state digest", ("period_open", "state_digest_equal")),
           ("writer lock and ownership row committed", ("writer_lock_held", "ownership_row_committed"))),
    "T6_REPLAY": (("same current generation and authorized replay caller", ("generation_current", "caller_may_begin")),),
    "T6p": (("current generation and switch off", ("generation_current", "kill_off")),
            ("checkpoint covers head and permit is current", ("checkpoint_covers_head", "permit_window_open")),
            ("hold/repair permits issuance", ("holds_and_repair_permit",))),
    "T6p_DISPATCH": (("writer and current generation", ("caller_is_writer", "generation_current")),
                      ("switch off and permit valid", ("kill_off", "permit_signature_valid")),
                      ("checkpoint sequence and hold/repair valid", ("checkpoint_sequence_verified", "holds_and_repair_writer"))),
    "T6r": (("no permit event and a permitted not-issued cause", ("no_permitted_event", "permit_not_issued_cause")),),
    "T6c": (("cancellation cause and winning cancel CAS", ("cancel_cause", "cancel_cas_won")),
            ("permit invalidated", ("permit_invalidated",))),
    "T7": (("writer and current generation", ("caller_is_writer", "generation_current")),
           ("signed successful completion", ("completion_signed", "completion_is_success")),
           ("bound receipt/result/persistence and checkpoint", ("completion_artifacts_bound", "checkpoint_ok"))),
    "T8": (("writer and current generation", ("caller_is_writer", "generation_current")),
           ("signed refusal class", ("completion_signed", "completion_is_refusal")),
           ("bound NOT_INVOKED receipt/no-effect/persistence and checkpoint", ("refusal_artifacts_bound", "checkpoint_ok"))),
    "T9": (("writer or worker at current generation", ("caller_is_writer_or_worker", "generation_current")),
           ("completion remains unknown", ("completion_is_unknown",))),
    "T10": (("recovery worker and signed resolution", ("caller_is_worker", "resolve_signed")),
            ("independent completion proof and complete observation", ("independent_proof", "observation_complete")),
            ("bound resolution evidence", ("resolve_evidence_bound",)),
            ("bound history proves conditional conflict was not entered", ("not_entered_conditional_conflict",)),
            ("effect present and attribution proven", ("effect_present", "attribution_proven"))),
    "T11": (("recovery worker and signed resolution", ("caller_is_worker", "resolve_signed")),
            ("independent completion proof and complete observation", ("independent_proof", "observation_complete")),
            ("bound resolution evidence", ("resolve_evidence_bound",)),
            ("bound history proves conditional conflict was not entered", ("not_entered_conditional_conflict",)),
            ("effect absent and terminal checkpoint", ("effect_absent", "checkpoint_ok"))),
    "T12": (("recovery worker and bounded triage cause", ("caller_is_worker", "triage_cause")),),
    "T13": (("recovery worker and bound independent evidence", ("caller_is_worker", "evidence_bound")),
            ("fields, movements, version and operation oracle match", ("verify_matches",))),
    "T14": (("recovery worker and bound independent evidence", ("caller_is_worker", "evidence_bound")),
            ("typed mismatch observation", ("verify_mismatch",))),
    "T15": (("typed revocation cause", ("revoke_cause",)),),
    "T16": (("distinct operator and recovery witness, neither requester; witness differs from approver, operator may be approver", ("two_person",)),
            ("consistent outcome and machine completion proof", ("outcome_consistent", "independent_proof")),
            ("operator signature and complete observation", ("operator_signed", "observation_complete")),
            ("possible-execution hold remains open", ("call_ownership_hold_open",)),
            ("bound operator resolution evidence", ("operator_resolution_evidence_bound",)),
            ("entered conditional conflict requires bound receipt, completion, no-effect and V3 causal chain", ("operator_conditional_conflict_chain_bound",)),
            ("attribution disposition and checkpoint", ("operator_attribution", "checkpoint_ok"))),
    "T17_RETRY": (("recovery worker and bound evidence", ("caller_is_worker", "evidence_bound")),
                  ("retry bound", ("retry_bound",))),
    "T17_CLOSE": (("two-person operator sign-off and complete observation", ("two_person", "operator_signed", "observation_complete")),),
}


def _actual_projection():
    rows = []
    for row in tr.TRANSITION_TABLE:
        requires = tuple(sorted(
            (dimension, tuple(sorted(getattr(value, "value", str(value)) for value in values)))
            for dimension, values in row.requires.items()))
        rows.append(ModelRow(row.key, row.tid, row.event.value, requires, row.target, row.guards,
                             row.state_refusal.value))
    return tuple(rows)


def _actual_lock_projection():
    return tuple(
        (key, row.tl.value, row.kl.value, row.wl.value, row.hold.value,
         None if row.reservation is None else row.reservation.value,
         row.repair_handback, row.proof)
        for key, row in tr.LOCK_MATRIX.items())


def _state_for_scenario(scenario):
    builders = {
        "none": lambda: None,
        "proposed": proposed,
        "validated": validated,
        "approved": approved,
        "claimed": claimed,
        "applying": applying,
        "permitted": lambda: applying(Dispatch.PERMITTED),
        "dispatched": dispatched,
        "unknown": unknown,
        "applied": applied,
        "triage": triage,
        "failed_verify": failed_verify,
    }
    return builders[scenario]()


def test_literal_oracle_enumerates_all_25_source_rows_and_variants():
    assert len(CT10_ORACLE) == 25
    assert len(MODEL_PROJECTION) == 25
    assert len(SOURCE_MODEL_MAPPING) == 25
    assert tuple(row.key for row in CT10_ORACLE) == tuple(row.key for row in MODEL_PROJECTION)
    assert tuple(row.source_key for row in SOURCE_MODEL_MAPPING) == tuple(row.key for row in CT10_ORACLE)
    assert tuple(row.model_key for row in SOURCE_MODEL_MAPPING) == tuple(row.key for row in MODEL_PROJECTION)
    assert set(SOURCE_GUARD_BINDINGS) == {row.key for row in CT10_ORACLE}
    assert set(SOURCE_EFFECTS_BY_ROW) == {row.key for row in CT10_ORACLE}
    assert all(row.source and row.lineage and row.from_state is not None and row.event
               and row.guard_summary and row.destination and row.ledger_effects
               and row.ledger_effect_codes == SOURCE_EFFECTS_BY_ROW[row.key] for row in CT10_ORACLE)
    assert {row.key for row in CT10_ORACLE} == {row.key for row in _actual_projection()}


def test_literal_source_projection_matches_the_complete_transition_table():
    actual = _actual_projection()
    assert actual == MODEL_PROJECTION
    model_by_key = {row.key: row for row in MODEL_PROJECTION}
    mapping_by_source = {row.source_key: row for row in SOURCE_MODEL_MAPPING}
    for source in CT10_ORACLE:
        model = model_by_key[mapping_by_source[source.key].model_key]
        mapping = mapping_by_source[source.key]
        # Every comparable source field is bound to the hand-authored model row, not just its ID.
        assert (source.key, source.event, source.from_state, source.destination) == (
            model.key, model.event, model.requires, model.target)
        assert source.destination == model.target
        assert mapping.model_guards == model.guards
        guard_groups = SOURCE_GUARD_BINDINGS[source.key]
        assert all(clause and guards for clause, guards in guard_groups)
        guard_projection = tuple(guard for _, guards in guard_groups for guard in guards)
        assert guard_projection == mapping.model_guards
        assert mapping.disposition in {"INHERITED", "INHERITED_VARIANT", "INHERITED_WITH_REPAIR_VARIANT",
                                       "AMENDMENT_OVERLAY", "DERIVED_REPLAY_VARIANT", "FREEZE_OVERLAY",
                                       "DERIVED_CAS_VARIANT", "FREEZE_REINFORCEMENT", "FREEZE_EVIDENCE_OVERLAY",
                                       "OPEN_T16_ROUTE", "INHERITED_RETRY_VARIANT", "INHERITED_CLOSE_VARIANT"}
        assert tr._HANDLERS[model.key].__name__ == mapping.handler
        assert all(key in tr.LOCK_MATRIX for key in mapping.lock_keys)


def test_literal_lock_matrix_matches_each_source_transition_effect_row():
    assert _actual_lock_projection() == LOCK_MATRIX_ORACLE
    mapping_by_source = {row.source_key: row for row in SOURCE_MODEL_MAPPING}
    actual_lock_keys = set(tr.LOCK_MATRIX)
    assert all(set(mapping.lock_keys) <= actual_lock_keys for mapping in mapping_by_source.values())
    assert {key for mapping in mapping_by_source.values() for key in mapping.lock_keys} == actual_lock_keys


def test_literal_source_effects_match_the_handler_effects_for_all_25_rows():
    source_by_key = {row.key: row for row in CT10_ORACLE}
    mapping_by_key = {row.source_key: row for row in SOURCE_MODEL_MAPPING}
    model_by_key = {row.key: row for row in MODEL_PROJECTION}
    for key, source in source_by_key.items():
        mapping = mapping_by_key[key]
        assert source.ledger_effect_codes == mapping.handler_effects
        model = model_by_key[mapping.model_key]
        state = _state_for_scenario(mapping.scenario)
        event = Event(model.event)
        result = tr.apply_transition(state, event, good(event, state))
        assert type(result) is Applied, (key, result)
        actual_effects = tuple(sorted(effect.name for effect in result.effects))
        assert actual_effects == tuple(sorted(source.ledger_effect_codes)), (key, actual_effects)


def test_known_semantic_and_runtime_limits_keep_full_parity_unaccepted():
    # This test deliberately preserves the open adjudication boundary instead of presenting a
    # passing structural comparison as complete E45 acceptance.
    open_rows = {row.source_key: row.open_delta for row in SOURCE_MODEL_MAPPING if row.open_delta}
    assert set(open_rows) == {"T6", "T6p", "T6p_DISPATCH", "T7", "T8", "T9", "T10", "T11", "T13", "T16"}
    assert "period source observation" in open_rows["T6"]
    assert "CAS" in open_rows["T6p_DISPATCH"]
    assert "synthetic" in open_rows["T7"] and "synthetic" in open_rows["T8"]
    assert "source-reader evidence" in open_rows["T10"] and "source-reader evidence" in open_rows["T11"]
    assert "independent 1C read evidence" in open_rows["T13"]
    assert "upstream authenticated evidence-chain/runtime provision remains NOT_VERIFIED" in open_rows["T16"]
    assert "T9→T12→T16" in open_rows["T16"] and "T12 exhausted bounded attempts/window" in open_rows["T16"]
    assert "G3 operator-facing status projection is separately PARTIAL" in KNOWN_RECONCILIATION_OPEN


@pytest.mark.parametrize("field", ["receipt_bound", "result_evidence_bound", "evidence_persisted"])
def test_t7_requires_all_synthetic_success_artifact_summaries(field):
    evidence = good(Event.CALL_SUCCESS, dispatched(), **{field: False})
    result = apply_transition(dispatched(), Event.CALL_SUCCESS, evidence)
    assert tr.classify_completion(evidence) is Event.CALL_UNKNOWN
    assert type(result) is Refusal and result.code is ErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize("field", ["receipt_bound", "post_cas_not_invoked_proof", "evidence_persisted"])
def test_t8_requires_cas_bound_not_invoked_refusal_artifact_summaries(field):
    evidence = good(Event.REFUSED_BEFORE_WRITE, dispatched(), **{field: False})
    result = apply_transition(dispatched(), Event.REFUSED_BEFORE_WRITE, evidence)
    assert tr.classify_completion(evidence) is Event.CALL_UNKNOWN
    assert type(result) is Refusal and result.code is ErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize("field", ["dispatch_attempt_bound", "completion_proof_bound", "observation_evidence_bound"])
@pytest.mark.parametrize("event, state", [(Event.RESOLVE_FOUND, unknown()), (Event.RESOLVE_ABSENT, unknown())])
def test_t10_t11_require_bound_resolution_artifacts(field, event, state):
    evidence = good(event, state, **{field: False})
    result = apply_transition(state, event, evidence)
    assert type(result) is Refusal and result.code is ErrorCode.EVIDENCE_UNSIGNED


@pytest.mark.parametrize("entered_conflict", [True, None])
def test_t11_requires_bound_history_that_conditional_conflict_was_not_entered(entered_conflict):
    state = unknown()
    result = apply_transition(
        state, Event.RESOLVE_ABSENT,
        good(Event.RESOLVE_ABSENT, state, entered_conditional_conflict=entered_conflict),
    )
    assert type(result) is Refusal and result.code is ErrorCode.COMPLETION_PROOF_MISSING
    assert state.execution is Execution.APPLY_UNKNOWN
    assert state.call_ownership is CallOwnership.POSSIBLY_EXECUTING
    assert state.reservation.value == "RESERVED" and state.target_lock and state.key_lock and state.lease


@pytest.mark.parametrize("field", [
    "conditional_conflict_receipt_bound",
    "conditional_conflict_completion_bound",
    "conditional_conflict_no_effect_bound",
    "conditional_conflict_v3_causal_chain_bound",
])
@pytest.mark.parametrize("missing_value", [False, None])
def test_t16_entered_conflict_requires_every_bound_chain_flag(field, missing_value):
    state = triage()
    result = apply_transition(
        state, Event.OPERATOR_RESOLVE,
        good(Event.OPERATOR_RESOLVE, state, entered_conditional_conflict=True, **{field: missing_value}),
    )
    assert type(result) is Refusal and result.code is ErrorCode.COMPLETION_PROOF_MISSING
    assert state.execution is Execution.TRIAGE_REQUIRED
    assert state.call_ownership is CallOwnership.POSSIBLY_EXECUTING
    assert state.reservation.value == "RESERVED" and state.target_lock and state.key_lock and state.lease


def test_t16_entered_conflict_with_all_four_chain_flags_can_resolve_and_release():
    state = triage()
    result = apply_transition(
        state, Event.OPERATOR_RESOLVE,
        good(Event.OPERATOR_RESOLVE, state, entered_conditional_conflict=True,
             conditional_conflict_receipt_bound=True, conditional_conflict_completion_bound=True,
             conditional_conflict_no_effect_bound=True, conditional_conflict_v3_causal_chain_bound=True),
    )
    assert type(result) is Applied
    assert result.record.execution is Execution.FAILED_APPLY
    assert result.record.call_ownership is CallOwnership.PROVEN_FINISHED
    assert result.record.reservation.value == "RELEASED"
    assert (result.record.target_lock, result.record.key_lock, result.record.lease) == (False, False, False)
    assert tuple(effect.name for effect in result.effects) == ("RELEASE_HOLD_CALL_OWNERSHIP",)


@pytest.mark.parametrize("witness_person_id", ["p-app", "p-req"])
def test_t16_witness_must_differ_from_approver_and_requester(witness_person_id):
    state = triage()
    result = apply_transition(
        state, Event.OPERATOR_RESOLVE,
        good(Event.OPERATOR_RESOLVE, state, witness_person_id=witness_person_id),
    )
    assert type(result) is Refusal and result.code is ErrorCode.APPROVER_NOT_INDEPENDENT
    assert state.execution is Execution.TRIAGE_REQUIRED
    assert state.reservation.value == "RESERVED" and state.target_lock and state.key_lock and state.lease


def test_t16_approver_may_be_operator_when_witness_is_independent():
    state = triage()
    result = apply_transition(
        state, Event.OPERATOR_RESOLVE,
        good(Event.OPERATOR_RESOLVE, state, operator_person_id="p-app", witness_person_id="p-wit"),
    )
    assert type(result) is Applied
    assert result.record.execution is Execution.FAILED_APPLY
    assert result.record.reservation.value == "RELEASED"


def test_t13_requires_explicit_oracle_and_operation_match():
    state = applied()
    evidence = good(Event.VERIFY_OK, state, oracle_and_operation_match=False)
    result = apply_transition(state, Event.VERIFY_OK, evidence)
    assert type(result) is Refusal and result.code is ErrorCode.VERIFY_FAILED


@pytest.mark.parametrize("field", ["dispatch_attempt_bound", "completion_proof_bound", "observation_evidence_bound"])
def test_t16_requires_bound_resolution_artifacts(field):
    state = triage()
    evidence = good(Event.OPERATOR_RESOLVE, state, **{field: False})
    result = apply_transition(state, Event.OPERATOR_RESOLVE, evidence)
    assert type(result) is Refusal and result.code is ErrorCode.COMPLETION_PROOF_MISSING


def test_t16_requires_the_call_ownership_hold_to_remain_open():
    state = triage()
    evidence = good(Event.OPERATOR_RESOLVE, state, call_ownership_hold_open=False)
    result = apply_transition(state, Event.OPERATOR_RESOLVE, evidence)
    assert type(result) is Refusal and result.code is ErrorCode.BASE_HOLD
