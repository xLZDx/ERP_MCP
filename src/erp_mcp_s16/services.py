"""Use-case services. They issue preview/approval material; transport handlers never mint claims."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from business_ai_gateway.phase2.change.errors import ErrorCode, Refusal
from business_ai_gateway.phase2.change.policy import LedgerOperation, authorize_operation
from business_ai_gateway.phase2.change.proposal import (
    ProposalContext,
    approval_canonical_text,
    digest_of_canonical_text,
    parse_proposal,
)
from business_ai_gateway.phase2.change.transitions import (
    BusinessKeyState,
    Event,
    LogicalKeyState,
    ProposeEvidence,
    ValidateEvidence,
    apply_transition,
)
from business_ai_gateway.phase2.change.types import (
    BudgetCheck,
    CallerClass,
    ChangeKind,
    Scope,
    Verification,
)

from .contracts import (
    ApprovalDecision,
    ApproverSession,
    AuthenticatedPrincipal,
    DecisionBinding,
    DecisionPage,
    DomainReceipt,
    NonceSource,
    PreviewSnapshot,
    ProposalPort,
    Result,
    TargetRecord,
    canonical_preview_bytes,
)
from .core import S16Core

APPROVAL_NONCE_LIFETIME = timedelta(minutes=5)
PROPOSAL_LIFETIME = timedelta(minutes=5)
APPROVER_SESSION_LIFETIME = timedelta(minutes=15)


def _digest(raw: bytes | str) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


def _now(clock, now: datetime | None) -> datetime:
    value = now if now is not None else clock.now()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("CLOCK_NOT_UTC_AWARE")
    return value.astimezone(UTC)


def _proposal_context(requester, principal_record, target, *, now, expires_at, change_id, preview_digest):
    return ProposalContext(
        change_id, requester.principal_id, requester.person_id,
        Scope(target.scope.tenant, target.scope.company, target.scope.organization,
              target.scope.base_fingerprint), now, expires_at, principal_record.epoch,
        principal_record.epoch_dependencies, preview_digest,
        business_state_digest=target.business_state_digest,
        qualified_currencies=target.qualified_currencies,
        in_scope_refs=target.in_scope_refs,
    )


class ChangeService:
    def __init__(self, core: S16Core, store, proposal_port: ProposalPort,
                 nonce_source: NonceSource, clock) -> None:
        self.core = core
        self.store = store
        self.proposal_port = proposal_port
        self.nonce_source = nonce_source
        self.clock = clock

    def propose(self, requester: AuthenticatedPrincipal, raw_request: Mapping[str, object], *,
                now: datetime | None = None) -> Result[PreviewSnapshot]:
        timestamp = _now(self.clock, now)
        try:
            auth_error = self.core.validate_current_requester(requester, timestamp)
            if auth_error is not None:
                return Result.refused(auth_error)
            if not isinstance(raw_request, Mapping):
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            request_id = raw_request.get("request_id")
            kind_text = raw_request.get("kind")
            if (type(request_id) is not str or type(kind_text) is not str
                    or kind_text not in ChangeKind.__members__):
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            target = self.core.targets.current(requester.scope)
            principal_record = self.core.principals.current(requester.principal_id)
            if target is None or principal_record is None:
                return Result.refused(ErrorCode.TARGET_REJECTED)
            expiry = timestamp + PROPOSAL_LIFETIME
            nonce = self.nonce_source.issue()
            if type(nonce) is not str or len(nonce) < 32:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            change_id = str(uuid4())
            provisional_context = _proposal_context(
                requester, principal_record, target, now=timestamp, expires_at=expiry,
                change_id=change_id, preview_digest="0" * 64)
            expected_provisional = parse_proposal(raw_request, provisional_context)
            if type(expected_provisional) is Refusal:
                return Result.refused(expected_provisional.code)
            built = self.proposal_port.build(requester, raw_request, now=timestamp,
                                             expires_at=expiry, preview_digest="0" * 64,
                                             change_id=change_id)
            if type(built) is ErrorCode:
                return Result.refused(built)
            proposal, returned_target = built
            if (type(proposal) is not type(expected_provisional) or proposal != expected_provisional
                    or type(returned_target) is not TargetRecord
                    or returned_target != target):
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
            preview_bytes = canonical_preview_bytes(
                proposal, target_version=target.version.value, target_class=target.scope.target_class)
            preview_digest = _digest(preview_bytes)
            expected_context = _proposal_context(
                requester, principal_record, target, now=timestamp, expires_at=expiry,
                change_id=change_id, preview_digest=preview_digest)
            expected_proposal = parse_proposal(raw_request, expected_context)
            if type(expected_proposal) is Refusal:
                return Result.refused(expected_proposal.code)
            rebuilt = self.proposal_port.build(requester, raw_request, now=timestamp,
                                               expires_at=expiry, preview_digest=preview_digest,
                                               change_id=change_id)
            if type(rebuilt) is ErrorCode:
                return Result.refused(rebuilt)
            proposal, returned_target = rebuilt
            if (type(proposal) is not type(expected_proposal) or proposal != expected_proposal
                    or type(returned_target) is not TargetRecord
                    or returned_target != target
                    or proposal.change_id != change_id or proposal.request_id != request_id
                    or proposal.requester_principal != requester.principal_id
                    or proposal.requester_person_id != requester.person_id
                    or proposal.scope.as_tuple() != target.scope.as_tuple()[:4]
                    or proposal.auth_epoch_at_proposal != principal_record.epoch
                    or proposal.created_at != timestamp or proposal.expires_at != expiry
                    or proposal.preview_digest != preview_digest
                    or proposal.kind is not ChangeKind(kind_text)):
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
            return self._store_proposal(requester, proposal, target, preview_bytes, preview_digest,
                                        nonce, timestamp, expiry)
        except Exception:
            return Result.refused(ErrorCode.SCHEMA_INVALID)

    def _store_proposal(self, requester, proposal, target: TargetRecord, preview_bytes: bytes,
                        preview_digest: str, nonce: str, now: datetime,
                        expires_at: datetime) -> Result[PreviewSnapshot]:
        auth_error = self.core.validate_current_requester(requester, now)
        if auth_error is not None:
            return Result.refused(auth_error)
        current_target = self.core.targets.current(requester.scope)
        if current_target != target:
            return Result.refused(ErrorCode.STALE_VERSION)
        expected_preview = canonical_preview_bytes(
            proposal, target_version=target.version.value, target_class=target.scope.target_class)
        if expected_preview != preview_bytes or proposal.expires_at != expires_at:
            return Result.refused(ErrorCode.DIGEST_MISMATCH)
        approval_text = approval_canonical_text(proposal, approval_nonce=nonce,
                                                declared_target_class=target.scope.target_class)
        approval_digest = digest_of_canonical_text(approval_text)
        snapshot = PreviewSnapshot(UUID(proposal.change_id), 1,
                                  _scope_from_proposal(proposal.scope, target), target.version,
                                  preview_bytes, preview_digest, proposal, approval_text, approval_digest,
                                  _digest(nonce), min(proposal.expires_at, now + APPROVAL_NONCE_LIFETIME))
        if snapshot.expires_at <= now:
            return Result.refused(ErrorCode.APPROVAL_EXPIRED)
        # Run the real S12 PROPOSE -> VALIDATE guards. A fake target must explicitly qualify the shape/key.
        try:
            for operation in (LedgerOperation.PROPOSE, LedgerOperation.VALIDATE):
                refusal = authorize_operation(CallerClass.REQUESTER, operation)
                if refusal is not None:
                    return Result.refused(refusal.code)
            current_auth = self.core.validate_current_requester(requester, now) is None
            reading = self.core.kill_switch.reading(snapshot.scope)
            proposed = apply_transition(None, Event.PROPOSE, ProposeEvidence(
                now=now, kill=reading, proposal=proposal, schema_valid=True, scope_resolved=True,
                requester_entitled=current_auth, epoch_read=current_auth,
                logical_key=LogicalKeyState.UNUSED,
                parent_attribution_unproven=False))
            if type(proposed).__name__ == "Refusal":
                return Result.refused(proposed.code)
            if proposed.record is None:
                return Result.refused(ErrorCode.IDEMPOTENCY_CONFLICT)
            validated = apply_transition(proposed.record, Event.VALIDATE, ValidateEvidence(
                now=now, kill=reading, preview_built=True,
                shape_qualified=proposal.kind.value in target.qualified_operations,
                allowed_effects_derived=True, budget=BudgetCheck.OK,
                key_state=BusinessKeyState.FREE if target.business_key_free is True
                else BusinessKeyState.NOT_CHECKED))
            if type(validated).__name__ == "Refusal":
                return Result.refused(validated.code)
            if validated.record is None:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            if proposal.kind in (ChangeKind.POST, ChangeKind.UNPOST) and not target.parent_verified:
                return Result.refused(ErrorCode.PARENT_NOT_VERIFIED)
            s12_record = validated.record
        except Exception:
            return Result.refused(ErrorCode.SCHEMA_INVALID)
        receipt = DomainReceipt(snapshot.change_id,
                                f"{s12_record.lifecycle.value}:{s12_record.authorization.value}",
                                snapshot.version, snapshot.scope,
                                proposal, proposal.requester_person_id, None, target.version, snapshot, s12_record)
        try:
            self.store.insert_proposal(receipt)
        except Exception:
            return Result.refused(ErrorCode.IDEMPOTENCY_CONFLICT)
        anchor_error = self.core.anchor_issuance(receipt)
        if anchor_error is not None:
            return Result.refused(anchor_error)
        return Result.success(snapshot)

    def status(self, requester: AuthenticatedPrincipal, change_id: UUID):
        return self.core.status(requester, change_id, now=_now(self.clock, None))

    def apply(self, requester: AuthenticatedPrincipal, change_id: UUID, *, now: datetime | None = None):
        return self.core.apply(requester, change_id, now=_now(self.clock, now))

    def verify(self, requester: AuthenticatedPrincipal, request):
        return self.core.verify(requester, request, now=_now(self.clock, None))

    def rollback_propose(self, requester: AuthenticatedPrincipal, change_id: UUID, *,
                         now: datetime | None = None) -> Result[PreviewSnapshot]:
        timestamp = _now(self.clock, now)
        auth_error = self.core.validate_current_requester(requester, timestamp)
        if auth_error is not None:
            return Result.refused(auth_error)
        original = self.store.get(change_id)
        if original is None or original.scope != requester.scope:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        anchor_error = self.core.validate_issued_receipt(original)
        if anchor_error is not None:
            return Result.refused(anchor_error)
        if (original.s12_record is None or original.s12_record.verification is not Verification.VERIFIED
                or original.proposal.kind is not ChangeKind.POST):
            return Result.refused(ErrorCode.ROLLBACK_REFUSED)
        try:
            nonce = self.nonce_source.issue()
            rollback_id = str(uuid4())
            expiry = timestamp + PROPOSAL_LIFETIME
            target = self.core.targets.current(requester.scope)
            principal_record = self.core.principals.current(requester.principal_id)
            if target is None or principal_record is None:
                return Result.refused(ErrorCode.TARGET_REJECTED)
            request_id = "rollback-" + rollback_id
            raw_rollback = {"kind": "UNPOST", "request_id": request_id,
                            "parent_change_id": original.proposal.change_id,
                            "target_ref": original.proposal.target_ref,
                            "target_version": target.version.value,
                            "reason": "S16 rollback proposal"}
            provisional_context = _proposal_context(
                requester, principal_record, target, now=timestamp, expires_at=expiry,
                change_id=rollback_id, preview_digest="0" * 64)
            expected_provisional = parse_proposal(raw_rollback, provisional_context)
            if type(expected_provisional) is Refusal:
                return Result.refused(expected_provisional.code)
            provisional = self.proposal_port.rollback(requester, original, now=timestamp,
                                                      expires_at=expiry, preview_digest="0" * 64,
                                                      change_id=rollback_id)
            if type(provisional) is ErrorCode:
                return Result.refused(provisional)
            proposal, returned_target = provisional
            if (type(proposal) is not type(expected_provisional)
                    or type(returned_target) is not TargetRecord
                    or proposal != expected_provisional or returned_target != target
                    or proposal.kind is not ChangeKind.UNPOST
                    or proposal.parent_change_id != original.proposal.change_id):
                return Result.refused(ErrorCode.ROLLBACK_REFUSED)
            visible = canonical_preview_bytes(
                proposal, target_version=target.version.value, target_class=target.scope.target_class)
            digest = _digest(visible)
            expected_context = _proposal_context(
                requester, principal_record, target, now=timestamp, expires_at=expiry,
                change_id=rollback_id, preview_digest=digest)
            expected_proposal = parse_proposal(raw_rollback, expected_context)
            if type(expected_proposal) is Refusal:
                return Result.refused(expected_proposal.code)
            rebuilt = self.proposal_port.rollback(requester, original, now=timestamp,
                                                  expires_at=expiry, preview_digest=digest,
                                                  change_id=rollback_id)
            if type(rebuilt) is ErrorCode:
                return Result.refused(rebuilt)
            proposal, returned_target = rebuilt
            if (type(proposal) is not type(expected_proposal)
                    or type(returned_target) is not TargetRecord
                    or proposal != expected_proposal or returned_target != target
                    or proposal.kind is not ChangeKind.UNPOST
                    or proposal.parent_change_id != original.proposal.change_id):
                return Result.refused(ErrorCode.ROLLBACK_REFUSED)
            return self._store_proposal(requester, proposal, target, visible, digest,
                                        nonce, timestamp, expiry)
        except Exception:
            return Result.refused(ErrorCode.ROLLBACK_REFUSED)


class ApprovalService:
    def __init__(self, core: S16Core, store, nonce_source: NonceSource, clock,
                 *, origin: str) -> None:
        self.core = core
        self.store = store
        self.nonce_source = nonce_source
        self.clock = clock
        self.origin = origin.rstrip("/")

    def open_preview(self, approver: AuthenticatedPrincipal, session: ApproverSession, ticket: UUID,
                     *, now: datetime | None = None) -> Result[DecisionPage]:
        from .contracts import PrincipalRole, TokenClass
        timestamp = _now(self.clock, now)
        if (approver.token_class is not TokenClass.APPROVER_SESSION
                or PrincipalRole.APPROVER not in approver.roles
                or session.principal != approver or session.session_id != approver.session_id
                or timestamp - session.last_seen_at > timedelta(minutes=15)
                or timestamp >= session.idle_expires_at or timestamp >= session.expires_at
                or session.expires_at - session.created_at > APPROVER_SESSION_LIFETIME):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        current_principal = self.core.principals.current(approver.principal_id)
        if not self.core._live_approver(current_principal, approver, timestamp):
            return Result.refused(ErrorCode.APPROVAL_VOIDED)
        receipt = self.store.get(ticket)
        if receipt is None:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        issued_error = self.core.validate_issued_receipt(receipt)
        if issued_error is not None:
            return Result.refused(issued_error)
        target_error = self.core.validate_current_target(receipt)
        if target_error is not None:
            return Result.refused(target_error)
        if receipt.scope != approver.scope:
            return Result.refused(ErrorCode.SCOPE_MISMATCH)
        if receipt.requester_person_id == approver.person_id:
            return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
        if not self.core.principals.are_independent(receipt.requester_person_id, approver.person_id):
            return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
        from business_ai_gateway.phase2.change.types import Authorization, Lifecycle
        if (receipt.s12_record is None or receipt.s12_record.lifecycle is not Lifecycle.VALIDATED
                or receipt.s12_record.authorization is not Authorization.NONE
                or receipt.approval is not None):
            return Result.refused(ErrorCode.TICKET_SUPERSEDED)
        if not current_principal.display_label or not current_principal.display_label.strip():
            return Result.refused(ErrorCode.NOT_ENTITLED)
        snap = receipt.snapshot
        if snap.expires_at <= timestamp:
            if receipt.proposal.expires_at <= timestamp:
                self.core.expire(ticket, now=timestamp)
            return Result.refused(ErrorCode.APPROVAL_EXPIRED)
        if _digest(snap.canonical_preview_bytes) != snap.preview_digest:
            return Result.refused(ErrorCode.APPROVAL_EXPIRED)
        try:
            ref = self.nonce_source.issue()
            ref_digest = _digest(ref)
            target = self.core.targets.current(receipt.scope)
            if target is None:
                return Result.refused(ErrorCode.TARGET_REJECTED)
            requires = receipt.proposal.kind is ChangeKind.POST
            if receipt.proposal.payload is not None:
                if target.amount_confirmation_threshold is None:
                    return Result.refused(ErrorCode.TARGET_REJECTED)
                from decimal import Decimal
                amount = sum((Decimal(line.amount) + Decimal(line.vat_amount)
                              for line in receipt.proposal.payload.lines), Decimal(0))
                requires = requires or amount > Decimal(target.amount_confirmation_threshold)
            phrase = "CONFIRM CHANGE" if requires else None
            decision_expires = min(snap.expires_at, session.expires_at, session.idle_expires_at)
            binding = DecisionBinding(snap.change_id, snap.version, snap.scope, approver.principal_id,
                                      approver.person_id, session.session_id, receipt.requester_person_id,
                                      snap.nonce_digest, ref_digest,
                                      _digest(ref + "\0" + session.csrf_secret), snap.preview_digest,
                                      snap.approval_digest, decision_expires, requires, phrase)
            self.store.issue_decision_ref(ref, binding)
            return Result.success(DecisionPage(
                decision_ref=ref,
                canonical_preview_bytes=snap.canonical_preview_bytes,
                preview_digest=snap.preview_digest,
                expires_at=decision_expires,
                confirmation_required=requires,
                confirmation_phrase=phrase,
                lifecycle_status=receipt.s12_record.lifecycle.value,
                authorization_status=receipt.s12_record.authorization.value,
                snapshot_version=receipt.version,
                created_at=receipt.proposal.created_at,
                approver_person_label=current_principal.display_label,
                decision_allowed=True,
            ))
        except Exception:
            return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)

    def submit_decision(self, approver: AuthenticatedPrincipal, session: ApproverSession,
                        decision_ref: str, decision: Literal["APPROVE", "REJECT"], *,
                        confirmation_text: str, origin: str, referer: str,
                        now: datetime | None = None) -> Result[ApprovalDecision]:
        timestamp = _now(self.clock, now)
        if origin != self.origin or not referer.startswith(self.origin + "/"):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        return self.core.decide(approver, session, decision_ref, decision,
                                confirmation_text=confirmation_text, origin=origin,
                                referer=referer, now=timestamp)


def _scope_from_proposal(scope, target: TargetRecord):
    from .contracts import TargetScope
    return TargetScope(scope.tenant, scope.company, scope.organization,
                       scope.base_fingerprint, target.scope.target_class)
