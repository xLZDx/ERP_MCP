"""S16 policy owner. Ports are untrusted storage/I/O boundaries; authorization stays here."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from typing import Literal, Mapping
from uuid import UUID

from business_ai_gateway.phase2.change.errors import ErrorCode
from business_ai_gateway.phase2.change.killswitch import KillDecision, KillSubject, evaluate
from business_ai_gateway.phase2.change.proposal import digest_of_canonical_text
from business_ai_gateway.phase2.change.proposal import approval_canonical_text
from business_ai_gateway.phase2.change.policy import LedgerOperation, authorize_operation
from business_ai_gateway.phase2.change.transitions import (
    ApproveEvidence, BeginApplyEvidence, ClaimEvidence, Event, ExpireEvidence, NonceState,
    RejectEvidence, ReleaseClaimEvidence, ReleaseReason, apply_transition,
)
from business_ai_gateway.phase2.change.types import ApprovalType, Authorization, BudgetCheck, CallerClass, Lifecycle
from erp_mcp_s15.verifier import ExpectedReceipt, OperationShape, VerificationResult

from .contracts import (
    ApprovalDecision, ApproverSession, ApplyPort, ApplyReceipt, AuthenticatedPrincipal,
    BeginApplyEvidencePort, ChangeStore, ClaimRefused, Claimed, Clock, DecisionBinding, DomainReceipt,
    KillSwitchPort, canonical_preview_bytes,
    PrincipalRecord, PrincipalRegistryPort, Result, TargetRegistryPort, VerifyPort,
    VerifyRequest,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bytes_digest_matches(raw: bytes, expected: str) -> bool:
    try:
        raw.decode("utf-8", "strict")
        return hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected)
    except (UnicodeDecodeError, TypeError):
        return False


def _aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


class S16Core:
    """Synchronous policy coordinator with process-local replay and apply serialization."""

    def __init__(self, *, store: ChangeStore, principals: PrincipalRegistryPort,
                 targets: TargetRegistryPort, kill_switch: KillSwitchPort,
                 apply_port: ApplyPort, verify_port: VerifyPort,
                 begin_apply_evidence: BeginApplyEvidencePort | None = None,
                 clock: Clock | None = None) -> None:
        self.store = store
        self.principals = principals
        self.targets = targets
        self.kill_switch = kill_switch
        self.apply_port = apply_port
        self.verify_port = verify_port
        self.begin_apply_evidence = begin_apply_evidence
        self.clock = clock
        self._lock = threading.RLock()
        self._consumed_nonce_digests: set[str] = set()
        self._consumed_ref_digests: set[str] = set()
        self._apply_started: set[UUID] = set()
        self._pending_releases: dict[UUID, tuple[object, ...]] = {}
        self._issuance_anchors: dict[UUID, tuple[object, ...]] = {}
        self._s12_anchors: dict[UUID, object] = {}
        self._approval_anchors: dict[UUID, ApprovalDecision] = {}
        self._apply_receipt_anchors: dict[UUID, ApplyReceipt] = {}

    def anchor_issuance(self, receipt: DomainReceipt) -> ErrorCode | None:
        """Bind newly issued local values to this core instance; restart without anchors fails closed."""
        if type(receipt) is not DomainReceipt or not self._snapshot_matches_content(receipt):
            return ErrorCode.DIGEST_MISMATCH
        if receipt.s12_record is None:
            return ErrorCode.SCHEMA_INVALID
        snap = receipt.snapshot
        anchor = (receipt.proposal, receipt.scope, receipt.version, receipt.target_version,
                  snap.canonical_preview_bytes, snap.preview_digest, snap.approval_canonical_text,
                  snap.approval_digest, snap.nonce_digest)
        with self._lock:
            if receipt.change_id in self._issuance_anchors:
                return ErrorCode.IDEMPOTENCY_CONFLICT
            self._issuance_anchors[receipt.change_id] = anchor
            self._s12_anchors[receipt.change_id] = receipt.s12_record
        return None

    @staticmethod
    def _snapshot_matches_content(receipt: DomainReceipt) -> bool:
        try:
            snap = receipt.snapshot
            if (snap.proposal != receipt.proposal or snap.change_id != receipt.change_id
                    or snap.scope != receipt.scope or snap.version != receipt.version
                    or receipt.target_version != snap.target_version
                    or receipt.requester_person_id != receipt.proposal.requester_person_id
                    or receipt.proposal.change_id != str(receipt.change_id)
                    or receipt.proposal.scope.as_tuple() != receipt.scope.as_tuple()[:4]
                    or receipt.proposal.preview_digest != snap.preview_digest
                    or snap.canonical_preview_bytes != canonical_preview_bytes(
                        receipt.proposal, target_version=snap.target_version.value,
                        target_class=receipt.scope.target_class)):
                return False
            if not hmac.compare_digest(hashlib.sha256(snap.canonical_preview_bytes).hexdigest(),
                                       snap.preview_digest):
                return False
            envelope = json.loads(snap.approval_canonical_text)
            if type(envelope) is not dict or type(envelope.get("approval_nonce")) is not str:
                return False
            nonce = envelope["approval_nonce"]
            expected_text = approval_canonical_text(
                receipt.proposal, approval_nonce=nonce,
                declared_target_class=receipt.scope.target_class)
            return (hmac.compare_digest(expected_text, snap.approval_canonical_text)
                    and hmac.compare_digest(digest_of_canonical_text(expected_text), snap.approval_digest)
                    and hmac.compare_digest(_sha(nonce), snap.nonce_digest))
        except Exception:
            return False

    def validate_issued_receipt(self, receipt: DomainReceipt) -> ErrorCode | None:
        if not self._snapshot_matches_content(receipt):
            return ErrorCode.DIGEST_MISMATCH
        snap = receipt.snapshot
        actual = (receipt.proposal, receipt.scope, receipt.version, receipt.target_version,
                  snap.canonical_preview_bytes, snap.preview_digest, snap.approval_canonical_text,
                  snap.approval_digest, snap.nonce_digest)
        with self._lock:
            expected = self._issuance_anchors.get(receipt.change_id)
            expected_s12 = self._s12_anchors.get(receipt.change_id)
            expected_approval = self._approval_anchors.get(receipt.change_id)
        if expected is None or expected_s12 is None:
            return ErrorCode.APPROVAL_VOIDED
        if expected != actual:
            return ErrorCode.DIGEST_MISMATCH
        if expected_s12 != receipt.s12_record:
            return ErrorCode.APPROVAL_VOIDED
        if receipt.approval != expected_approval:
            return ErrorCode.APPROVAL_VOIDED
        return None

    def validate_current_target(self, receipt: DomainReceipt) -> ErrorCode | None:
        try:
            target = self.targets.current(receipt.scope)
            fingerprint = self.targets.resolve_fingerprint(receipt.scope)
        except Exception:
            return ErrorCode.TARGET_REJECTED
        if target is None or not target.allowed or target.scope != receipt.scope:
            return ErrorCode.TARGET_REJECTED
        if fingerprint != receipt.scope.base_fingerprint:
            return ErrorCode.SCOPE_MISMATCH
        if target.version != receipt.snapshot.target_version:
            return ErrorCode.STALE_VERSION
        return None

    @staticmethod
    def _principal(principal: object, token_class: object) -> bool:
        return (type(principal) is AuthenticatedPrincipal and principal.token_class is token_class
                and type(principal.principal_id) is str and bool(principal.principal_id)
                and type(principal.person_id) is str and bool(principal.person_id)
                and _aware(principal.expires_at))

    def _live_requester(self, principal: AuthenticatedPrincipal, now: datetime, *,
                        check_epoch: bool = True) -> bool:
        from .contracts import PrincipalRole, TokenClass
        if (not self._principal(principal, TokenClass.CHAT_WRITE)
                or PrincipalRole.REQUESTER not in principal.roles or principal.expires_at <= now):
            return False
        try:
            current = self.principals.current(principal.principal_id)
        except Exception:
            return False
        return (type(current) is PrincipalRecord and not current.revoked
                and current.principal_id == principal.principal_id
                and current.person_id == principal.person_id
                and (not check_epoch or current.epoch == principal.epoch)
                and PrincipalRole.REQUESTER in current.roles)

    def validate_current_requester(self, principal: AuthenticatedPrincipal,
                                   now: datetime) -> ErrorCode | None:
        """Validate transport-resolved identity, live registry state, exact scope, and allowlisted target."""
        if not _aware(now) or not self._live_requester(principal, now):
            return ErrorCode.NOT_ENTITLED
        try:
            target = self.targets.current(principal.scope)
            fingerprint = self.targets.resolve_fingerprint(principal.scope)
        except Exception:
            return ErrorCode.TARGET_REJECTED
        if target is None or not target.allowed or target.scope != principal.scope:
            return ErrorCode.TARGET_REJECTED
        if fingerprint != principal.scope.base_fingerprint:
            return ErrorCode.SCOPE_MISMATCH
        return None

    def decide(self, approver: AuthenticatedPrincipal, session: ApproverSession,
               decision_ref: str, decision: Literal["APPROVE", "REJECT"], *,
               origin: str, referer: str, confirmation_text: str, now: datetime) -> Result[ApprovalDecision]:
        """Validate every binding before the atomic store operation; retain local replay defense."""
        from .contracts import TokenClass, PrincipalRole
        if (not self._principal(approver, TokenClass.APPROVER_SESSION)
                or PrincipalRole.APPROVER not in approver.roles or approver.mfa_authenticated is not True
                or type(session) is not ApproverSession
                or session.principal != approver or session.session_id != approver.session_id
                or session.idle_expires_at <= now or session.expires_at <= now
                or now - session.last_seen_at > timedelta(minutes=15)
                or session.expires_at - session.created_at > timedelta(minutes=15)
                or type(decision_ref) is not str or not decision_ref or decision not in ("APPROVE", "REJECT")
                or type(origin) is not str or type(referer) is not str or not origin or not referer
                or type(confirmation_text) is not str
                or not _aware(now)):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        binding = self.store.get_decision_binding(decision_ref)
        if type(binding) is not DecisionBinding:
            return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
        if binding.expires_at <= now:
            expired_receipt = self.store.get(binding.change_id)
            if expired_receipt is not None and expired_receipt.proposal.expires_at <= now:
                self.expire(binding.change_id, now=now)
            return Result.refused(ErrorCode.APPROVAL_EXPIRED)
        ref_digest = _sha(decision_ref)
        with self._lock:
            if (binding.principal_id != approver.principal_id or binding.person_id != approver.person_id
                    or binding.session_id != session.session_id
                    or binding.scope != approver.scope
                    or binding.expires_at <= now or binding.expires_at > approver.expires_at
                    or not hmac.compare_digest(binding.decision_ref_digest, ref_digest)
                    or binding.csrf_binding_digest != _sha(decision_ref + "\0" + session.csrf_secret)
                    or binding.nonce_digest in self._consumed_nonce_digests
                    or binding.decision_ref_digest in self._consumed_ref_digests):
                return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
            receipt = self.store.get(binding.change_id)
            if receipt is None or receipt.version != binding.version or receipt.scope != binding.scope:
                return Result.refused(ErrorCode.STALE_VERSION)
            issued_error = self.validate_issued_receipt(receipt)
            if issued_error is not None:
                return Result.refused(issued_error)
            current_target_error = self.validate_current_target(receipt)
            if current_target_error is not None:
                return Result.refused(current_target_error)
            if receipt.approval is not None or (receipt.s12_record is not None
                    and receipt.s12_record.authorization is not Authorization.NONE):
                return Result.refused(ErrorCode.TICKET_SUPERSEDED)
            snap = receipt.snapshot
            if (snap.version != binding.version or snap.change_id != binding.change_id
                    or snap.scope != binding.scope or snap.preview_digest != binding.preview_digest
                    or snap.approval_digest != binding.approval_digest
                    or snap.nonce_digest != binding.nonce_digest or binding.expires_at > snap.expires_at
                    or not _bytes_digest_matches(snap.canonical_preview_bytes, snap.preview_digest)
                    or not hmac.compare_digest(digest_of_canonical_text(snap.approval_canonical_text),
                                               snap.approval_digest)):
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
            if binding.requester_person_id == approver.person_id:
                return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
            current = self.principals.current(approver.principal_id)
            if (not self._live_approver(current, approver, now)
                    or not self.principals.are_independent(binding.requester_person_id, approver.person_id)):
                return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
            requester_record = self.principals.current(receipt.proposal.requester_principal)
            if (requester_record is None or requester_record.revoked
                    or requester_record.person_id != receipt.requester_person_id
                    or requester_record.epoch != receipt.proposal.auth_epoch_at_proposal
                    or not self.principals.epochs_current(receipt.proposal.epoch_dependencies)):
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            policy_requires_confirmation = receipt.proposal.kind.value == "POST"
            payload = receipt.proposal.payload
            target = self.targets.current(receipt.scope)
            if payload is not None:
                if target is None or target.amount_confirmation_threshold is None:
                    return Result.refused(ErrorCode.TARGET_REJECTED)
                try:
                    amount = sum((Decimal(line.amount) + Decimal(line.vat_amount) for line in payload.lines), Decimal(0))
                    threshold = Decimal(target.amount_confirmation_threshold)
                    if not amount.is_finite() or not threshold.is_finite() or threshold < 0:
                        return Result.refused(ErrorCode.TARGET_REJECTED)
                    policy_requires_confirmation = policy_requires_confirmation or amount > threshold
                except (InvalidOperation, ValueError, TypeError):
                    return Result.refused(ErrorCode.TARGET_REJECTED)
            phrase = "CONFIRM CHANGE"
            if (binding.confirmation_required != policy_requires_confirmation
                    or (policy_requires_confirmation and binding.confirmation_phrase != phrase)
                    or (decision == "APPROVE" and policy_requires_confirmation and confirmation_text != phrase)):
                return Result.refused(ErrorCode.NOT_ENTITLED)
            s12_record = receipt.s12_record
            if s12_record is None:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            if decision == "APPROVE":
                policy_refusal = authorize_operation(CallerClass.APPROVER, LedgerOperation.APPROVE)
                if policy_refusal is not None:
                    return Result.refused(policy_refusal.code)
                try:
                    approval_kill = self.kill_switch.reading(receipt.scope)
                except Exception:
                    return Result.refused(ErrorCode.KILL_SWITCH_ACTIVE)
                transitioned = apply_transition(s12_record, Event.APPROVE, ApproveEvidence(
                    now=now, kill=approval_kill, approver_person_id=approver.person_id, approver_entitled=True,
                    approver_mfa=approver.mfa_authenticated, approval_id=binding.approval_digest,
                    approval_type=ApprovalType.HUMAN,
                    epoch_dependencies_current=self.principals.epochs_current(receipt.proposal.epoch_dependencies),
                    nonce=NonceState.ISSUED, digest_bound=True,
                    override_bound=True, unproven_flag_bound=True, checkpoint_ok=True))
            else:
                policy_refusal = authorize_operation(CallerClass.APPROVER, LedgerOperation.REJECT)
                if policy_refusal is not None:
                    return Result.refused(policy_refusal.code)
                transitioned = apply_transition(s12_record, Event.REJECT,
                                                RejectEvidence(now=now, actor_is_approver=True))
            if type(transitioned).__name__ == "Refusal":
                return Result.refused(transitioned.code)
            if transitioned.record is None:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            result = ApprovalDecision(binding.change_id, binding.version, binding.scope,
                                      binding.requester_person_id, approver.person_id, approver.principal_id,
                                      approver.epoch, session.session_id, binding.nonce_digest,
                                      binding.decision_ref_digest, binding.preview_digest,
                                      binding.approval_digest, decision, binding.expires_at)
            try:
                consumed = self.store.consume_decision_ref_and_nonce(
                    decision_ref, expected=binding, decision=result, s12_record=transitioned.record)
            except Exception:
                return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
            if consumed is not True:
                return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
            stored_decision = self.store.get(binding.change_id)
            if (stored_decision is None or stored_decision.approval != result
                    or stored_decision.s12_record != transitioned.record):
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            self._consumed_nonce_digests.add(binding.nonce_digest)
            self._consumed_ref_digests.add(binding.decision_ref_digest)
            self._approval_anchors[binding.change_id] = result
            self._s12_anchors[binding.change_id] = transitioned.record
            return Result.success(result)

    def expire(self, change_id: UUID, *, now: datetime) -> Result[DomainReceipt]:
        """Record the S12 expiration transition once the canonical approval window has elapsed."""
        from business_ai_gateway.phase2.change.types import Lifecycle
        with self._lock:
            receipt = self.store.get(change_id)
            if receipt is None:
                return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
            issued_error = self.validate_issued_receipt(receipt)
            if issued_error is not None:
                return Result.refused(issued_error)
            if receipt.proposal.expires_at > now:
                return Result.refused(ErrorCode.APPROVAL_EXPIRED)
            record = receipt.s12_record
            if record is None:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            if record.lifecycle is Lifecycle.EXPIRED_QUEUED:
                return Result.success(receipt)
            transitioned = apply_transition(record, Event.EXPIRE, ExpireEvidence(now=now))
            if type(transitioned).__name__ == "Refusal":
                return Result.refused(transitioned.code)
            if transitioned.record is None:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            try:
                self.store.save_s12_record(change_id, transitioned.record)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            updated = self.store.get(change_id)
            if updated is None or updated.s12_record != transitioned.record:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            self._s12_anchors[change_id] = transitioned.record
            return Result.success(updated)

    @staticmethod
    def _live_approver(record: PrincipalRecord | None, principal: AuthenticatedPrincipal,
                       now: datetime) -> bool:
        return (type(record) is PrincipalRecord and record.revoked is False
                and record.principal_id == principal.principal_id and record.person_id == principal.person_id
                and record.epoch == principal.epoch and record.epoch >= 0
                and "APPROVER" in {r.value for r in record.roles}
                and principal.mfa_authenticated is True and principal.expires_at > now)

    def _release_before_begin(self, receipt: DomainReceipt, claim, claimed_record,
                              error: ErrorCode, *, now: datetime) -> Result[ApplyReceipt]:
        """Release only a known claim that has not passed T6 or reached the apply port."""
        change_id = receipt.change_id
        pending = self._pending_releases.get(change_id)
        if pending is None:
            evidence = ReleaseClaimEvidence(now=now, reason=ReleaseReason.T6_GUARD_FAILED)
            try:
                evidence = replace(evidence, kill=self.kill_switch.reading(receipt.scope))
            except Exception:
                # Keep the model's unreadable kill state; releasing is not permission to apply.
                pass
            try:
                released = apply_transition(claimed_record, Event.RELEASE_CLAIM, evidence)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if type(released).__name__ == "Refusal" or released.record is None:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            pending = (receipt, claim, claimed_record, released.record)
            self._pending_releases[change_id] = pending
        original, token, expected_record, released_record = pending
        try:
            if self.store.release_claim(change_id, token, expected_record=expected_record,
                                        released_record=released_record) is not True:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            updated = self.store.get(change_id)
            if updated is None or updated.s12_record != released_record:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            previous_anchor = self._s12_anchors.get(change_id)
            self._s12_anchors[change_id] = released_record
            if self.validate_issued_receipt(updated) is not None or updated.approval != original.approval:
                self._s12_anchors[change_id] = previous_anchor
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        except Exception:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        self._pending_releases.pop(change_id, None)
        self._apply_started.discard(change_id)
        return Result.refused(error)

    def apply(self, requester: AuthenticatedPrincipal, change_id: UUID, *, now: datetime) -> Result[ApplyReceipt]:
        from .contracts import PrincipalRole, TokenClass
        if (type(change_id) is not UUID or not _aware(now)
                or not self._live_requester(requester, now, check_epoch=False)):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        # Same-process serialization is deliberately held across claim and apply. Unknown apply is terminal.
        with self._lock:
            pending = self._pending_releases.get(change_id)
            if pending is not None:
                original, token, claimed_record, _ = pending
                if (original.proposal.requester_principal != requester.principal_id
                        or original.scope != requester.scope):
                    return Result.refused(ErrorCode.NOT_ENTITLED)
                recovered = self._release_before_begin(original, token, claimed_record,
                                                       ErrorCode.AUDIT_UNAVAILABLE, now=now)
                if change_id in self._pending_releases:
                    return recovered
            if change_id in self._apply_started:
                prior = self.store.get(change_id)
                if prior is not None and prior.s12_record is not None:
                    repeated = apply_transition(prior.s12_record, Event.CLAIM, ClaimEvidence(now=now))
                    if type(repeated).__name__ == "Refusal":
                        return Result.refused(repeated.code)
                return Result.refused(ErrorCode.TICKET_SUPERSEDED)
            receipt = self.store.get(change_id)
            if receipt is None:
                return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
            issued_error = self.validate_issued_receipt(receipt)
            if issued_error is not None:
                return Result.refused(issued_error)
            if receipt.proposal.requester_principal != requester.principal_id:
                return Result.refused(ErrorCode.NOT_ENTITLED)
            approval = receipt.approval
            if approval is None:
                return Result.refused(ErrorCode.APPROVAL_MISSING)
            with self._lock:
                if self._approval_anchors.get(change_id) != approval:
                    return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if (approval.change_id != receipt.change_id or approval.version != receipt.version
                    or approval.scope != receipt.scope
                    or approval.requester_person_id != receipt.requester_person_id
                    or approval.approver_person_id == receipt.requester_person_id
                    or not self.principals.are_independent(receipt.requester_person_id,
                                                           approval.approver_person_id)):
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            # S12 kill-switch semantics are reused directly; unreadable/unknown state fails closed.
            try:
                if evaluate(KillSubject.BEGIN_APPLY_ISSUE_PERMIT, self.kill_switch.reading(receipt.scope)) is not KillDecision.PROCEED:
                    return Result.refused(ErrorCode.KILL_SWITCH_ACTIVE)
            except Exception:
                return Result.refused(ErrorCode.KILL_SWITCH_ACTIVE)
            current_target_error = self.validate_current_target(receipt)
            if current_target_error is not None:
                return Result.refused(current_target_error)
            if requester.scope != receipt.scope:
                return Result.refused(ErrorCode.SCOPE_MISMATCH)
            try:
                current = self.principals.current(requester.principal_id)
                epochs_ok = self.principals.epochs_current(receipt.proposal.epoch_dependencies)
            except Exception:
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            if (type(current) is not PrincipalRecord or current.revoked
                    or current.person_id != requester.person_id
                    or PrincipalRole.REQUESTER not in current.roles):
                return Result.refused(ErrorCode.NOT_ENTITLED)
            if (current.epoch != requester.epoch or current.epoch != receipt.proposal.auth_epoch_at_proposal
                    or not epochs_ok):
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            try:
                approver_current = self.principals.current(approval.approver_principal_id)
            except Exception:
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if not self._live_approver_record(approver_current, approval):
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if approval.expires_at <= now or receipt.snapshot.expires_at <= now:
                self.expire(change_id, now=now)
                return Result.refused(ErrorCode.APPROVAL_EXPIRED)
            snap = receipt.snapshot
            try:
                preview_text = snap.canonical_preview_bytes.decode("utf-8", "strict")
                preview_ok = hmac.compare_digest(_sha(preview_text), snap.preview_digest)
                approval_ok = hmac.compare_digest(digest_of_canonical_text(snap.approval_canonical_text),
                                                  snap.approval_digest)
            except Exception:
                preview_ok = approval_ok = False
            if (not preview_ok or not approval_ok or approval.approval_digest != snap.approval_digest
                    or approval.preview_digest != snap.preview_digest or approval.nonce_digest != snap.nonce_digest
                    or receipt.proposal.preview_digest != snap.preview_digest):
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
            target = self.targets.current(receipt.scope)
            if target is None or target.scope != receipt.scope or target.version != receipt.target_version:
                return Result.refused(ErrorCode.STALE_VERSION)
            if (receipt.s12_record is None or receipt.s12_record.lifecycle is not Lifecycle.VALIDATED
                    or receipt.s12_record.authorization is not Authorization.APPROVED):
                return Result.refused(ErrorCode.TICKET_SUPERSEDED)
            try:
                claim_reading = self.kill_switch.reading(receipt.scope)
                transitioned = apply_transition(receipt.s12_record, Event.CLAIM, ClaimEvidence(
                    now=now, kill=claim_reading,
                    caller_is_requester=receipt.proposal.requester_principal == requester.principal_id,
                    epoch_deps_unchanged=True, holds=(),
                    parent_verified=(receipt.proposal.kind.value not in ("POST", "UNPOST")
                                     or bool(target.parent_verified)),
                    scope_equal=requester.scope == receipt.scope,
                    target_class_equal=target.scope.target_class == receipt.scope.target_class,
                    locks_read=True, target_lock_owner=None, key_lock_free=True, lease_free=True,
                    budget=BudgetCheck.OK))
            except Exception:
                return Result.refused(ErrorCode.CLAIM_EXPIRED)
            if type(transitioned).__name__ == "Refusal":
                return Result.refused(transitioned.code)
            if transitioned.record is None:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            self._apply_started.add(change_id)
            try:
                claim = self.store.claim_once(change_id, expected_version=receipt.version,
                                              expected_approval_digest=approval.approval_digest,
                                              claimant_id=requester.principal_id,
                                              s12_record=transitioned.record)
            except Exception:
                return Result.refused(ErrorCode.CLAIM_EXPIRED)
            if type(claim) is ClaimRefused:
                return Result.refused(claim.error)
            if (type(claim) is not Claimed or claim.token.change_id != change_id
                    or claim.token.version != receipt.version
                    or claim.token.approval_digest != approval.approval_digest):
                return Result.refused(ErrorCode.CLAIM_EXPIRED)
            self._s12_anchors[change_id] = transitioned.record
            claimed_receipt = self.store.get(change_id)
            if claimed_receipt is None or claimed_receipt.s12_record != transitioned.record:
                return Result.refused(ErrorCode.CLAIM_EXPIRED)

            def refuse_before_begin(code, stamp=now):
                return self._release_before_begin(claimed_receipt, claim.token, transitioned.record,
                                                  code, now=stamp)

            if self.begin_apply_evidence is None:
                return refuse_before_begin(ErrorCode.CHECKPOINT_UNAVAILABLE)
            try:
                observed = self.begin_apply_evidence.read(claimed_receipt, claim.token, now)
            except Exception:
                return refuse_before_begin(ErrorCode.CHECKPOINT_UNAVAILABLE)
            if type(observed) is not BeginApplyEvidence:
                return refuse_before_begin(observed if type(observed) is ErrorCode
                                           else ErrorCode.CHECKPOINT_UNAVAILABLE)
            # Re-read core-owned identity/target facts after evidence collection. Only source observations
            # (holds, period, state digest, writer lock, ownership row, repair context) come from the port.
            try:
                current_target = self.targets.current(receipt.scope)
                current_fingerprint = self.targets.resolve_fingerprint(receipt.scope)
                current_requester = self.principals.current(requester.principal_id)
                current_kill = self.kill_switch.reading(receipt.scope)
                current_now = self.clock.now() if self.clock is not None else now
            except Exception:
                return refuse_before_begin(ErrorCode.CHECKPOINT_UNAVAILABLE)
            if not _aware(current_now):
                return refuse_before_begin(ErrorCode.CHECKPOINT_UNAVAILABLE)
            if (approval.expires_at <= current_now or receipt.snapshot.expires_at <= current_now
                    or requester.expires_at <= current_now):
                return refuse_before_begin(ErrorCode.APPROVAL_EXPIRED, current_now)
            if current_target is None or not current_target.allowed or current_target.scope != receipt.scope:
                return refuse_before_begin(ErrorCode.TARGET_REJECTED, current_now)
            if current_fingerprint != receipt.scope.base_fingerprint:
                return refuse_before_begin(ErrorCode.SCOPE_MISMATCH, current_now)
            if current_target.version != receipt.target_version:
                return refuse_before_begin(ErrorCode.STALE_VERSION, current_now)
            if (current_requester is None or current_requester.revoked
                    or current_requester.person_id != requester.person_id
                    or PrincipalRole.REQUESTER not in current_requester.roles):
                return refuse_before_begin(ErrorCode.NOT_ENTITLED, current_now)
            try:
                epoch_dependencies_current = self.principals.epochs_current(receipt.proposal.epoch_dependencies)
            except Exception:
                return refuse_before_begin(ErrorCode.EPOCH_CHANGED, current_now)
            if (current_requester.epoch != receipt.proposal.auth_epoch_at_proposal
                    or not epoch_dependencies_current):
                return refuse_before_begin(ErrorCode.EPOCH_CHANGED, current_now)
            try:
                current_approver = self.principals.current(approval.approver_principal_id)
            except Exception:
                return refuse_before_begin(ErrorCode.APPROVAL_VOIDED, current_now)
            if not self._live_approver_record(current_approver, approval):
                return refuse_before_begin(ErrorCode.APPROVAL_VOIDED, current_now)
            begin_evidence = replace(
                observed, now=current_now, kill=current_kill,
                generation=transitioned.record.claim_generation,
                caller=CallerClass.REQUESTER,
                own_change=receipt.proposal.requester_principal == requester.principal_id,
                epoch_deps_equal_claim_epoch=(current_requester.epoch == receipt.proposal.auth_epoch_at_proposal),
                version_equals_approved=(current_target.version == receipt.target_version),
                fingerprint_authenticated=(current_fingerprint == receipt.scope.base_fingerprint),
                repair_ctx=None,
            )
            began = apply_transition(transitioned.record, Event.BEGIN_APPLY, begin_evidence)
            if type(began).__name__ == "Refusal":
                return refuse_before_begin(began.code, current_now)
            if began.record is None:
                return refuse_before_begin(ErrorCode.SCHEMA_INVALID, current_now)
            try:
                self.store.save_s12_record(change_id, began.record)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            self._s12_anchors[change_id] = began.record
            applying_receipt = self.store.get(change_id)
            if applying_receipt is None or applying_receipt.s12_record != began.record:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            issued_error = self.validate_issued_receipt(applying_receipt)
            if issued_error is not None:
                return Result.refused(issued_error)
            target_error = self.validate_current_target(applying_receipt)
            if target_error is not None:
                return Result.refused(target_error)
            try:
                final_now = self.clock.now() if self.clock is not None else current_now
                final_requester = self.principals.current(requester.principal_id)
                final_approver = self.principals.current(approval.approver_principal_id)
                final_kill = self.kill_switch.reading(receipt.scope)
                dependencies_current = self.principals.epochs_current(receipt.proposal.epoch_dependencies)
            except Exception:
                return Result.refused(ErrorCode.CHECKPOINT_UNAVAILABLE)
            if not _aware(final_now):
                return Result.refused(ErrorCode.CHECKPOINT_UNAVAILABLE)
            if (approval.expires_at <= final_now or applying_receipt.snapshot.expires_at <= final_now
                    or requester.expires_at <= final_now):
                self.expire(change_id, now=final_now)
                return Result.refused(ErrorCode.APPROVAL_EXPIRED)
            if (final_requester is None or final_requester.revoked
                    or final_requester.person_id != requester.person_id
                    or PrincipalRole.REQUESTER not in final_requester.roles):
                return Result.refused(ErrorCode.NOT_ENTITLED)
            if (final_requester.epoch != receipt.proposal.auth_epoch_at_proposal
                    or not dependencies_current):
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            if not self._live_approver_record(final_approver, approval):
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if evaluate(KillSubject.BEGIN_APPLY_ISSUE_PERMIT, final_kill) is not KillDecision.PROCEED:
                return Result.refused(ErrorCode.KILL_SWITCH_ACTIVE)
            apply_receipt = applying_receipt
            try:
                applied = self.apply_port.apply(apply_receipt, claim.token)
            except Exception:
                # The call may have crossed the port boundary; never retry an unknown outcome.
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            if type(applied) is not ApplyReceipt or applied.change_id != change_id:
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            try:
                self.store.save_apply_receipt(change_id, applied)
            except Exception:
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            self._apply_receipt_anchors[change_id] = applied
            return Result.success(applied)

    @staticmethod
    def _live_approver_record(record: PrincipalRecord | None, approval: ApprovalDecision) -> bool:
        return (type(record) is PrincipalRecord and not record.revoked
                and record.principal_id == approval.approver_principal_id
                and record.person_id == approval.approver_person_id
                and record.epoch == approval.approver_epoch
                and "APPROVER" in {r.value for r in record.roles})

    def status(self, requester: AuthenticatedPrincipal, change_id: UUID, *, now: datetime) -> Result[DomainReceipt]:
        policy_refusal = authorize_operation(CallerClass.REQUESTER, LedgerOperation.READ_STATUS)
        if policy_refusal is not None:
            return Result.refused(policy_refusal.code)
        if type(change_id) is not UUID or not _aware(now) or not self._live_requester(requester, now):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        receipt = self.store.get(change_id)
        if receipt is None:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        issued_error = self.validate_issued_receipt(receipt)
        if issued_error is not None:
            return Result.refused(issued_error)
        if receipt.scope != requester.scope or receipt.proposal.requester_principal != requester.principal_id:
            return Result.refused(ErrorCode.SCOPE_MISMATCH)
        return Result.success(receipt)

    def verify(self, requester: AuthenticatedPrincipal, request: VerifyRequest, *, now: datetime) -> Result[VerificationResult]:
        policy_refusal = authorize_operation(CallerClass.REQUESTER, LedgerOperation.READ_STATUS)
        if policy_refusal is not None:
            return Result.refused(policy_refusal.code)
        if type(request) is not VerifyRequest or not _aware(now) or not self._live_requester(requester, now):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        receipt = self.store.get(request.change_id)
        if receipt is None or receipt.scope != requester.scope:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        issued_error = self.validate_issued_receipt(receipt)
        if issued_error is not None:
            return Result.refused(issued_error)
        if receipt.proposal.requester_principal != requester.principal_id:
            return Result.refused(ErrorCode.SCOPE_MISMATCH)
        document_ref = receipt.document_ref or receipt.proposal.target_ref
        with self._lock:
            applied_anchor = self._apply_receipt_anchors.get(request.change_id)
        if applied_anchor is not None and (applied_anchor.document_ref != receipt.document_ref
                                           or applied_anchor.change_id != receipt.change_id):
            return Result.refused(ErrorCode.DIGEST_MISMATCH)
        if receipt.document_ref is not None and applied_anchor is None:
            return Result.refused(ErrorCode.APPROVAL_VOIDED)
        if not document_ref or (request.document_ref is not None and request.document_ref != document_ref):
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        proposal = receipt.proposal
        payload = proposal.payload
        if payload is None or len(payload.lines) != 1:
            expected = ExpectedReceipt({}, "", proposal.change_id, proposal.payload_digest, False)
            shape = OperationShape(proposal.kind.value, "RECEIPT", 0 if payload is None else len(payload.lines))
        else:
            line = payload.lines[0]
            values = {
                "header.organization": payload.organization_ref,
                "header.counterparty": payload.counterparty_ref,
                "header.contract": payload.contract_ref,
                "header.currency": payload.currency,
                "header.incoming_number": payload.supplier_document_number,
                "header.incoming_date": payload.supplier_document_date,
                "line.nomenclature": line.item_ref,
                "line.quantity": line.quantity,
                "line.price": line.price,
                "line.amount": line.amount,
                "line.vat_rate": line.vat_rate_code,
                "line.vat_amount": line.vat_amount,
            }
            expected = ExpectedReceipt(values, payload.supplier_document_date, proposal.change_id,
                                       proposal.payload_digest, any(line.vat_amount != "0" for line in payload.lines))
            shape = OperationShape(proposal.kind.value, "RECEIPT", len(payload.lines))
        try:
            # Ignore caller-supplied expected values/shape: both are derived from the stored S12 proposal.
            # The S15 result object is passed through unchanged and never updates lifecycle state.
            return Result.success(self.verify_port.verify(document_ref, expected, shape))
        except Exception:
            return Result.refused(ErrorCode.VERIFY_FAILED)

