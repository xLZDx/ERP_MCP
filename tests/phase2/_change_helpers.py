"""Builders for the S12 offline change-package tests: records in every state, fully-passing evidence, proposals."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from business_ai_gateway.phase2.change import (
    SWITCH_OFF, ApprovalType, ApproveEvidence, Attribution, Authorization, BeginApplyEvidence, BudgetCheck,
    CallerClass, CallOwnership, CancelPermitEvidence, ChangeKind, ChangeRecord, ClaimEvidence, CompletionEvidence,
    Dispatch, DispatchEvidence, EffectKnown, Event, EvidenceKind, ExpireEvidence, ErrorCode, Execution,
    FailureStage, Hold, HoldCause, KillMode, Lifecycle, LogicalKeyState, NonceState, OperatorResolveEvidence,
    PermitEvidence, PermitNotIssuedEvidence, ProofClass, ProposalContext, ProposeEvidence, RejectEvidence,
    ReleaseClaimEvidence, ReleaseReason, RepairAuth, RepairContext, Reservation, ResolveEvidence, ResolveOutcome,
    RevokeCause, RevokeEvidence, Scope, SwitchReading, TokenState, ValidateEvidence, BusinessKeyState,
    Verification, VerifyEvidence, parse_proposal,
)

T0 = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)
APPROVAL_EXPIRES = T0 + timedelta(hours=1)
SCOPE = Scope("tenant-1", "company-1", "org-1", "base-1")
REQUESTER = "p-req"
APPROVER = "p-app"
OPERATOR = "p-op"
WITNESS = "p-wit"
PARENT_REQUESTER = "p-preq"
REPAIR_APPROVER = "p-app2"
HALT = Hold("h1", HoldCause.FAILED_VERIFY_HALT, "parent1", "doc1", "v7")
REPAIR_ID = "r1"
REPAIR_AUTH = RepairAuth(REPAIR_ID, "parent1", "doc1", "v7", "h1", "ap2", 1)
VERIFY_KINDS = frozenset({EvidenceKind.FIELD, EvidenceKind.MOVEMENT, EvidenceKind.VERSION})
ALL_EVENTS = tuple(Event)


def kill(mode: KillMode | None) -> SwitchReading:
    return SwitchReading(available=True, mode=mode)


UNREADABLE = SwitchReading()


def raw_create(**over) -> dict:
    payload = {
        "organization_ref": "org-1", "counterparty_ref": "cp-1", "contract_ref": "ct-1",
        "supplier_document_number": "N-1", "supplier_document_date": "2026-10-01", "currency": "RUB",
        "lines": [{"item_ref": "it-1", "quantity": "2", "price": "10.50", "vat_rate_code": "VAT20",
                   "amount": "21.00", "vat_amount": "3.50"}],
        "comment": "note",
    }
    payload.update(over.pop("payload_over", {}))
    raw = {"kind": "CREATE_DRAFT", "request_id": "req-1", "payload": payload, "reason": "why"}
    raw.update(over)
    return raw


def ctx(**over) -> ProposalContext:
    base = dict(change_id="c1", requester_principal="sub-req", requester_person_id=REQUESTER, scope=SCOPE,
                created_at=T0, expires_at=APPROVAL_EXPIRES, auth_epoch_at_proposal=3,
                epoch_dependencies=(("approver", 2), ("requester", 1)), preview_digest="a" * 64,
                business_state_digest="b" * 64, qualified_currencies=frozenset({"RUB"}))
    base.update(over)
    return ProposalContext(**base)


def raw_post(kind: str = "POST", **over) -> dict:
    raw = {"kind": kind, "request_id": "req-2", "parent_change_id": "parent1", "target_ref": "doc1",
           "target_version": "v7"}
    raw.update(over)
    return raw


def proposal(raw: dict | None = None, **ctx_over):
    result = parse_proposal(raw if raw is not None else raw_create(), ctx(**ctx_over))
    assert not hasattr(result, "code"), result
    return result


def rec(**over) -> ChangeRecord:
    base = dict(change_id="c1", kind=ChangeKind.CREATE_DRAFT, scope=SCOPE, requester_person_id=REQUESTER,
                expires_at=APPROVAL_EXPIRES)
    base.update(over)
    return ChangeRecord(**base)


def proposed(**o) -> ChangeRecord:
    return rec(**o)


def validated(**o) -> ChangeRecord:
    return rec(**{"lifecycle": Lifecycle.VALIDATED, **o})


def approved(**o) -> ChangeRecord:
    base = dict(authorization=Authorization.APPROVED, approver_person_id=APPROVER, approval_id="ap1")
    base.update(o)
    return validated(**base)


def claimed(**o) -> ChangeRecord:
    base = dict(authorization=Authorization.CLAIMED, token=TokenState.ISSUED, claim_generation=1,
                claim_expires_at=T0 + timedelta(seconds=120), reservation=Reservation.RESERVED, target_lock=True,
                key_lock=True, lease=True)
    base.update(o)
    return approved(**base)


def applying(dispatch: Dispatch = Dispatch.NOT_PERMITTED, **o) -> ChangeRecord:
    base = dict(execution=Execution.APPLYING, token=TokenState.CONSUMED, dispatch=dispatch,
                permit_expires_at=T0 + timedelta(seconds=60))
    base.update(o)
    return claimed(**base)


def dispatched(**o) -> ChangeRecord:
    return applying(Dispatch.DISPATCHED, **o)


def unknown(**o) -> ChangeRecord:
    base = dict(execution=Execution.APPLY_UNKNOWN, call_ownership=CallOwnership.POSSIBLY_EXECUTING)
    base.update(o)
    return dispatched(**base)


def triage(**o) -> ChangeRecord:
    return unknown(execution=Execution.TRIAGE_REQUIRED, **o)


def applied(**o) -> ChangeRecord:
    base = dict(execution=Execution.APPLIED, call_ownership=CallOwnership.PROVEN_FINISHED,
                attribution=Attribution.PROVEN, reservation=Reservation.CONSUMED, key_lock=False, lease=False)
    base.update(o)
    return dispatched(**base)


def failed_verify(**o) -> ChangeRecord:
    base = dict(verification=Verification.FAILED_VERIFY, effect_known=EffectKnown.YES)
    base.update(o)
    return applied(**base)


# ---- repair (section 4.2) -----------------------------------------------------------------------------------

def repair_rec(builder=approved, **o) -> ChangeRecord:
    """An UNPOST repair for parent1; ``builder`` picks the state (approved, claimed, applying, ...)."""
    base = dict(change_id=REPAIR_ID, kind=ChangeKind.UNPOST, parent_change_id="parent1", target_ref="doc1",
                approver_person_id=REPAIR_APPROVER, approval_id="ap2")
    base.update(o)
    return builder(**base)


def repair_live(builder=claimed, **o) -> ChangeRecord:
    """A repair that already passed T5 (carries R and ``repair_for``)."""
    base = dict(repair_for="parent1", repair=REPAIR_AUTH)
    base.update(o)
    return repair_rec(builder, **base)


def repair_ctx(owner: str | None = "parent1", **over) -> RepairContext:
    base = dict(parent_change_id="parent1", parent_verification=Verification.FAILED_VERIFY,
                parent_effect_known=EffectKnown.YES, parent_requester_person_id=PARENT_REQUESTER, halt=HALT,
                current_target_ref="doc1", current_version="v7", approval_fresh=True, approval_revoked=False,
                other_repair_exists=False, target_lock_owner=owner)
    base.update(over)
    return RepairContext(**base)


# ---- fully passing evidence ---------------------------------------------------------------------------------

def good(event: Event, record: ChangeRecord | None = None, now: datetime = T0, **over):
    """Evidence that passes every guard of ``event`` for ``record`` (state-dependent fields come from it)."""
    gen = record.claim_generation if record is not None else 0
    is_repair = record is not None and record.parent_change_id == "parent1" and record.kind is ChangeKind.UNPOST
    common = dict(now=now, kill=SWITCH_OFF)
    holds = (HALT,) if is_repair else ()
    builders = {
        Event.PROPOSE: lambda: ProposeEvidence(
            proposal=proposal(), schema_valid=True, scope_resolved=True, requester_entitled=True, epoch_read=True,
            logical_key=LogicalKeyState.UNUSED, **common),
        Event.VALIDATE: lambda: ValidateEvidence(
            preview_built=True, shape_qualified=True, allowed_effects_derived=True, budget=BudgetCheck.OK,
            key_state=BusinessKeyState.FREE, **common),
        Event.REJECT: lambda: RejectEvidence(actor_is_approver=True, **common),
        Event.EXPIRE: lambda: ExpireEvidence(**{**common, "now": APPROVAL_EXPIRES + timedelta(seconds=1) if now == T0 else now}),
        Event.APPROVE: lambda: ApproveEvidence(
            approver_person_id=APPROVER, approver_entitled=True, approver_mfa=True, approval_id="ap1",
            approval_type=ApprovalType.HUMAN, epoch_dependencies_current=True, nonce=NonceState.ISSUED,
            digest_bound=True, override_bound=True, unproven_flag_bound=True, checkpoint_ok=True, **common),
        Event.CLAIM: lambda: ClaimEvidence(
            caller_is_requester=True, epoch_deps_unchanged=True, holds=holds, parent_verified=True,
            repair_ctx=repair_ctx("parent1") if is_repair else None, scope_equal=True, target_class_equal=True,
            locks_read=True, target_lock_owner=None, key_lock_free=True, lease_free=True, budget=BudgetCheck.OK,
            **common),
        Event.RELEASE_CLAIM: lambda: ReleaseClaimEvidence(
            reason=ReleaseReason.TTL_EXPIRED, **{**common, "now": T0 + timedelta(seconds=500) if now == T0 else now}),
        Event.BEGIN_APPLY: lambda: BeginApplyEvidence(
            generation=gen, caller=CallerClass.REQUESTER, own_change=True, epoch_deps_equal_claim_epoch=True,
            holds=holds, version_equals_approved=True, fingerprint_authenticated=True, state_digest_equal=True,
            writer_lock_held=True, ownership_row_committed=True,
            repair_ctx=repair_ctx(REPAIR_ID) if is_repair else None, **common),
        Event.ISSUE_PERMIT: lambda: PermitEvidence(
            generation=gen, checkpoint_covers_head=True, holds=holds,
            repair_ctx=repair_ctx(REPAIR_ID) if is_repair else None, **common),
        Event.MARK_DISPATCHED: lambda: DispatchEvidence(
            caller=CallerClass.WRITER, generation=gen, permit_signature_valid=True,
            checkpoint_sequence_verified=True, holds=holds,
            repair_ctx=repair_ctx(REPAIR_ID) if is_repair else None, **common),
        Event.PERMIT_NOT_ISSUED: lambda: PermitNotIssuedEvidence(
            permitted_event_exists=False, checkpoint_unavailable=True, **common),
        Event.CANCEL_PERMIT: lambda: CancelPermitEvidence(
            generation=gen, cancel_cas_won=True, permit_invalidated=True, **{**common, "kill": kill(KillMode.STOP_ADMIT)}),
        Event.CALL_SUCCESS: lambda: CompletionEvidence(
            caller=CallerClass.WRITER, generation=gen, signed=True, call_id_matches=True, result_returned=True,
            checkpoint_ok=True, **common),
        Event.REFUSED_BEFORE_WRITE: lambda: CompletionEvidence(
            caller=CallerClass.WRITER, generation=gen, signed=True, call_id_matches=True, result_returned=False,
            stage=FailureStage.PRE_WRITE, no_effect_proof=True, refusal_code=ErrorCode.STALE_VERSION,
            checkpoint_ok=True, **common),
        Event.CALL_UNKNOWN: lambda: CompletionEvidence(
            caller=CallerClass.WRITER, generation=gen, signed=False, **common),
        Event.RESOLVE_FOUND: lambda: ResolveEvidence(
            caller=CallerClass.RECOVERY_WORKER, signed=True, proof_class=ProofClass.WRITER_COMPLETION,
            reader_healthy=True, settle_elapsed=True, observation_complete=True, effect_present=True,
            effect_identity_match=True, exclusivity_proven=True, checkpoint_ok=True, **common),
        Event.RESOLVE_ABSENT: lambda: ResolveEvidence(
            caller=CallerClass.RECOVERY_WORKER, signed=True, proof_class=ProofClass.SESSION_END_OBSERVED,
            reader_healthy=True, settle_elapsed=True, observation_complete=True, effect_present=False,
            checkpoint_ok=True, **common),
        Event.AGE_LIMIT: lambda: ResolveEvidence(
            caller=CallerClass.RECOVERY_WORKER, attempts=5, first_attempt_at=now - timedelta(minutes=16), **common),
        Event.VERIFY_OK: lambda: VerifyEvidence(
            caller=CallerClass.RECOVERY_WORKER, signed_kinds=VERIFY_KINDS, bound=True, matches=True, **common),
        Event.VERIFY_FAILED: lambda: VerifyEvidence(
            caller=CallerClass.RECOVERY_WORKER, signed_kinds=VERIFY_KINDS, bound=True, matches=False,
            effect_known=EffectKnown.YES, **common),
        Event.REVOKE: lambda: RevokeEvidence(cause=RevokeCause.SESSION_REVOKED, **common),
        Event.OPERATOR_RESOLVE: lambda: OperatorResolveEvidence(
            operator_person_id=OPERATOR, operator_class=CallerClass.OPERATOR, witness_person_id=WITNESS,
            witness_class=CallerClass.RECOVERY_WITNESS, signed=True, proof_class=ProofClass.WRITER_COMPLETION,
            reader_healthy=True, settle_elapsed=True, observation_complete=True, outcome=ResolveOutcome.ABSENT,
            checkpoint_ok=True, **common),
        Event.RETRY_VERIFY: lambda: VerifyEvidence(
            caller=CallerClass.RECOVERY_WORKER, signed_kinds=VERIFY_KINDS, bound=True, matches=True, **common),
        Event.CLOSE_FAILED_VERIFY: lambda: OperatorResolveEvidence(
            operator_person_id=OPERATOR, operator_class=CallerClass.OPERATOR, witness_person_id=WITNESS,
            witness_class=CallerClass.RECOVERY_WITNESS, signed=True, reader_healthy=True, settle_elapsed=True,
            observation_complete=True, **common),
    }
    return replace(builders[event](), **over)
