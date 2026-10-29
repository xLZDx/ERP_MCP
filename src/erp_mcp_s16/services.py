"""Use-case services. They issue preview/approval material; transport handlers never mint claims."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Mapping
from uuid import UUID, uuid4

from business_ai_gateway.phase2.change.errors import ErrorCode, Refusal
from business_ai_gateway.phase2.change.policy import LedgerOperation, authorize_operation
from business_ai_gateway.phase2.change.proposal import (
    approval_canonical_text, canonical_json, digest_of_canonical_text, payload_to_dict,
)
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.change.transitions import (
    BusinessKeyState, Event, LogicalKeyState, ProposeEvidence, ValidateEvidence, apply_transition,
)
from business_ai_gateway.phase2.change.types import BudgetCheck, CallerClass, Verification

from .contracts import (
    ApprovalDecision, ApproverSession, AuthenticatedPrincipal, DecisionBinding, DecisionPage,
    DomainReceipt, NonceSource, PreviewSnapshot, ProposalPort, Result, TargetRecord,
)
from .core import S16Core

APPROVAL_NONCE_LIFETIME = timedelta(minutes=5)
APPROVER_SESSION_LIFETIME = timedelta(minutes=15)


def _digest(raw: bytes | str) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


def _now(clock, now: datetime | None) -> datetime:
    value = now if now is not None else clock.now()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("CLOCK_NOT_UTC_AWARE")
    return value.astimezone(timezone.utc)


def _preview_object(proposal, target: TargetRecord) -> dict[str, object]:
    """One allowlisted display model; no caller claim fields or digest are serialized into it."""
    payload = payload_to_dict(proposal.payload)
    return {
        "change_id": proposal.change_id,
        "kind": proposal.kind.value,
        "scope": {
            "tenant": proposal.scope.tenant, "company": proposal.scope.company,
            "organization": proposal.scope.organization,
            "base_fingerprint": proposal.scope.base_fingerprint,
            "target_class": target.scope.target_class,
        },
        "target_version": target.version.value,
        "requester_person_id": proposal.requester_person_id,
        "reason": proposal.reason,
        "payload": payload,
        "expires_at": proposal.expires_at.isoformat(),
    }


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
            nonce = self.nonce_source.issue()
            if type(nonce) is not str or len(nonce) < 32:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            change_id = str(uuid4())
            built = self.proposal_port.build(requester, raw_request, now=timestamp,
                                             preview_digest="0" * 64, nonce=nonce, change_id=change_id)
            if type(built) is ErrorCode:
                return Result.refused(built)
            proposal, target = built
            preview_bytes = canonical_json(_preview_object(proposal, target)).encode("utf-8")
            preview_digest = _digest(preview_bytes)
            rebuilt = self.proposal_port.build(requester, raw_request, now=timestamp,
                                               preview_digest=preview_digest, nonce=nonce, change_id=change_id)
            if type(rebuilt) is ErrorCode:
                return Result.refused(rebuilt)
            proposal, target = rebuilt
            # The second build must preserve the exact user-visible bytes used to derive the digest.
            if not hmac.compare_digest(canonical_json(_preview_object(proposal, target)).encode("utf-8"),
                                       preview_bytes):
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
            return self._store_proposal(proposal, target, preview_bytes, preview_digest, nonce, timestamp)
        except Exception:
            return Result.refused(ErrorCode.SCHEMA_INVALID)

    def _store_proposal(self, proposal, target: TargetRecord, preview_bytes: bytes,
                        preview_digest: str, nonce: str, now: datetime) -> Result[PreviewSnapshot]:
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
            reading = self.core.kill_switch.reading(snapshot.scope)
            proposed = apply_transition(None, Event.PROPOSE, ProposeEvidence(
                now=now, kill=reading, proposal=proposal, schema_valid=True, scope_resolved=True,
                requester_entitled=True, epoch_read=True, logical_key=LogicalKeyState.UNUSED,
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
        original = self.store.get(change_id)
        if original is None or original.scope != requester.scope:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        if (original.s12_record is None or original.s12_record.verification is not Verification.VERIFIED
                or original.proposal.kind is not ChangeKind.POST):
            return Result.refused(ErrorCode.ROLLBACK_REFUSED)
        try:
            nonce = self.nonce_source.issue()
            rollback_id = str(uuid4())
            provisional = self.proposal_port.rollback(requester, original, now=timestamp,
                                                      preview_digest="0" * 64, nonce=nonce, change_id=rollback_id)
            if type(provisional) is ErrorCode:
                return Result.refused(provisional)
            proposal, target = provisional
            if proposal.kind is not ChangeKind.UNPOST or proposal.parent_change_id != original.proposal.change_id:
                return Result.refused(ErrorCode.ROLLBACK_REFUSED)
            visible = canonical_json(_preview_object(proposal, target)).encode("utf-8")
            digest = _digest(visible)
            rebuilt = self.proposal_port.rollback(requester, original, now=timestamp,
                                                  preview_digest=digest, nonce=nonce, change_id=rollback_id)
            if type(rebuilt) is ErrorCode:
                return Result.refused(rebuilt)
            proposal, target = rebuilt
            if proposal.kind is not ChangeKind.UNPOST or proposal.parent_change_id != original.proposal.change_id:
                return Result.refused(ErrorCode.ROLLBACK_REFUSED)
            if canonical_json(_preview_object(proposal, target)).encode("utf-8") != visible:
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
            return self._store_proposal(proposal, target, visible, digest, nonce, timestamp)
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
        if receipt.scope != approver.scope:
            return Result.refused(ErrorCode.SCOPE_MISMATCH)
        if receipt.requester_person_id == approver.person_id:
            return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
        if not self.core.principals.are_independent(receipt.requester_person_id, approver.person_id):
            return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
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
            return Result.success(DecisionPage(ref, snap.canonical_preview_bytes, snap.preview_digest,
                                               decision_expires, requires, phrase))
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
