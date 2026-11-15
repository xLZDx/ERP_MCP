"""S16 policy owner. Ports are untrusted storage/I/O boundaries; authorization stays here."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
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
    BeginApplyEvidencePort, ChangeStore, ClaimRefused, Claimed, ClaimToken, Clock, DecisionBinding, DomainReceipt,
    KillSwitchPort, canonical_preview_bytes,
    PrincipalRecord, PrincipalRegistryPort, PrincipalRole, Result, TargetRecord, TargetRegistryPort,
    TargetVersion, VerifyPort, TargetScope, VerifyRequest,
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
    try:
        return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None
    except Exception:
        return False


def _as_utc(value: object) -> datetime | None:
    if not _aware(value):
        return None
    try:
        return value.astimezone(timezone.utc)
    except Exception:
        return None


def _expires_after(value: object, now: object) -> bool:
    expires_at = _as_utc(value)
    current_time = _as_utc(now)
    return expires_at is not None and current_time is not None and expires_at > current_time


def _valid_sha256_hex(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _valid_wire_text(value: object, *, limit: int) -> bool:
    if type(value) is not str or not value or len(value) > limit:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def _valid_apply_receipt(receipt: object, change_id: UUID) -> bool:
    if type(receipt) is not ApplyReceipt or type(change_id) is not UUID:
        return False
    try:
        return (type(receipt.change_id) is UUID and receipt.change_id == change_id
                and _valid_wire_text(receipt.status, limit=64)
                and _valid_wire_text(receipt.correlation_id, limit=128)
                and (receipt.document_ref is None
                     or _valid_wire_text(receipt.document_ref, limit=512)))
    except Exception:
        return False


def _allowed_target_record(target: object, scope: object) -> bool:
    """Require a well-typed positive registry decision before trusting target metadata."""
    return (type(target) is TargetRecord and type(target.allowed) is bool and target.allowed is True
            and type(target.scope) is TargetScope and type(scope) is TargetScope
            and target.scope == scope and type(target.version) is TargetVersion)


def _valid_approver_session(session: object, principal: AuthenticatedPrincipal,
                            now: datetime) -> bool:
    if (type(principal) is not AuthenticatedPrincipal or type(session) is not ApproverSession
            or not _aware(now) or type(principal.session_id) is not str or not principal.session_id
            or type(session.session_id) is not str or not session.session_id
            or type(session.csrf_secret) is not str or not session.csrf_secret
            or session.principal != principal or session.session_id != principal.session_id):
        return False
    timestamps = (session.created_at, session.last_seen_at, session.idle_expires_at, session.expires_at)
    if not all(_aware(value) for value in timestamps):
        return False
    try:
        created_at, last_seen_at, idle_expires_at, expires_at = (
            value.astimezone(timezone.utc) for value in timestamps
        )
        current = now.astimezone(timezone.utc)
        return (created_at <= last_seen_at <= current < idle_expires_at <= expires_at
                and current - last_seen_at <= timedelta(minutes=15)
                and expires_at - created_at <= timedelta(minutes=15))
    except Exception:
        return False


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
        if not _allowed_target_record(target, receipt.scope):
            return ErrorCode.TARGET_REJECTED
        if fingerprint != receipt.scope.base_fingerprint:
            return ErrorCode.SCOPE_MISMATCH
        if target.version != receipt.snapshot.target_version:
            return ErrorCode.STALE_VERSION
        return None

    @staticmethod
    def _principal(principal: object, token_class: object) -> bool:
        return (type(principal) is AuthenticatedPrincipal and principal.token_class is token_class
                and type(principal.roles) is frozenset
                and all(type(role) is PrincipalRole for role in principal.roles)
                and type(principal.epoch) is int and principal.epoch >= 0
                and type(principal.mfa_authenticated) is bool
                and type(principal.lane) is str and principal.lane == "TEST"
                and type(principal.scope) is TargetScope and type(principal.scope.target_class) is str
                and principal.scope.target_class == "TEST"
                and type(principal.principal_id) is str and bool(principal.principal_id)
                and type(principal.person_id) is str and bool(principal.person_id)
                and _aware(principal.expires_at))

    def _live_requester(self, principal: AuthenticatedPrincipal, now: datetime, *,
                        check_epoch: bool = True) -> bool:
        from .contracts import PrincipalRole, TokenClass
        if (not self._principal(principal, TokenClass.CHAT_WRITE)
                or PrincipalRole.REQUESTER not in principal.roles
                or not _expires_after(principal.expires_at, now)):
            return False
        try:
            current = self.principals.current(principal.principal_id)
        except Exception:
            return False
        return self._live_requester_record(current, principal, check_epoch=check_epoch)

    @staticmethod
    def _live_requester_record(record: object, principal: AuthenticatedPrincipal, *,
                               check_epoch: bool = True) -> bool:
        from .contracts import PrincipalRole
        return (type(record) is PrincipalRecord and type(record.revoked) is bool and not record.revoked
                and type(record.lane) is str and record.lane == principal.lane == "TEST"
                and type(record.principal_id) is str and record.principal_id == principal.principal_id
                and type(record.person_id) is str and record.person_id == principal.person_id
                and type(record.epoch) is int and record.epoch >= 0
                and (not check_epoch or record.epoch == principal.epoch)
                and type(record.roles) is frozenset
                and all(type(role) is PrincipalRole for role in record.roles)
                and PrincipalRole.REQUESTER in record.roles)

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
        if not _allowed_target_record(target, principal.scope):
            return ErrorCode.TARGET_REJECTED
        if fingerprint != principal.scope.base_fingerprint:
            return ErrorCode.SCOPE_MISMATCH
        return None

    def decide(self, approver: AuthenticatedPrincipal, session: ApproverSession,
               decision_ref: str, decision: Literal["APPROVE", "REJECT"], *,
               origin: str, referer: str, confirmation_text: str, now: datetime,
               csrf_token: str = "") -> Result[ApprovalDecision]:
        """Validate every binding before the atomic store operation; retain local replay defense."""
        from .contracts import TokenClass, PrincipalRole
        if not _aware(now):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        if (not self._principal(approver, TokenClass.APPROVER_SESSION)
                or PrincipalRole.APPROVER not in approver.roles or approver.mfa_authenticated is not True
                or not _valid_approver_session(session, approver, now)
                or type(decision_ref) is not str or not decision_ref
                or type(decision) is not str or decision not in ("APPROVE", "REJECT")
                or type(csrf_token) is not str or not re.fullmatch(r"[0-9a-f]{64}", csrf_token)
                or type(origin) is not str or type(referer) is not str or not origin or not referer
                or type(confirmation_text) is not str):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        try:
            binding = self.store.get_decision_binding(decision_ref)
        except Exception:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        if (type(binding) is not DecisionBinding or type(binding.change_id) is not UUID
                or type(binding.version) is not int or binding.version < 1
                or type(binding.scope) is not TargetScope
                or any(type(value) is not str or not value for value in (
                    binding.principal_id, binding.person_id, binding.session_id,
                    binding.requester_person_id))
                or not all(_valid_sha256_hex(value) for value in (
                    binding.nonce_digest, binding.decision_ref_digest, binding.csrf_binding_digest,
                    binding.preview_digest, binding.approval_digest))
                or type(binding.confirmation_required) is not bool
                or (binding.confirmation_phrase is not None
                    and type(binding.confirmation_phrase) is not str)):
            return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
        binding_expires_at = _as_utc(binding.expires_at)
        now_utc = _as_utc(now)
        approver_expires_at = _as_utc(approver.expires_at)
        if binding_expires_at is None or now_utc is None or approver_expires_at is None:
            return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
        if binding_expires_at <= now_utc:
            try:
                expired_receipt = self.store.get(binding.change_id)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            proposal_expires_at = (_as_utc(expired_receipt.proposal.expires_at)
                                   if type(expired_receipt) is DomainReceipt else None)
            if proposal_expires_at is not None and proposal_expires_at <= now_utc:
                try:
                    self.expire(binding.change_id, now=now)
                except Exception:
                    return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            return Result.refused(ErrorCode.APPROVAL_EXPIRED)
        ref_digest = _sha(decision_ref)
        with self._lock:
            if (binding.principal_id != approver.principal_id or binding.person_id != approver.person_id
                    or binding.session_id != session.session_id
                    or binding.scope != approver.scope
                    or binding_expires_at <= now_utc or binding_expires_at > approver_expires_at
                    or not hmac.compare_digest(binding.decision_ref_digest, ref_digest)
                    or not hmac.compare_digest(binding.csrf_binding_digest, csrf_token)
                    or not hmac.compare_digest(
                        binding.csrf_binding_digest, _sha(decision_ref + "\0" + session.csrf_secret))
                    or binding.nonce_digest in self._consumed_nonce_digests
                    or binding.decision_ref_digest in self._consumed_ref_digests):
                return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
            try:
                receipt = self.store.get(binding.change_id)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if type(receipt) is not DomainReceipt:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if receipt.version != binding.version or receipt.scope != binding.scope:
                return Result.refused(ErrorCode.STALE_VERSION)
            if receipt.requester_person_id != binding.requester_person_id:
                return Result.refused(ErrorCode.APPROVAL_NONCE_INVALID)
            try:
                issued_error = self.validate_issued_receipt(receipt)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if issued_error is not None:
                if type(issued_error) is not ErrorCode:
                    return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
                return Result.refused(issued_error)
            snapshot_expires_at = _as_utc(receipt.snapshot.expires_at)
            proposal_expires_at = _as_utc(receipt.proposal.expires_at)
            if (snapshot_expires_at is None or proposal_expires_at is None
                    or snapshot_expires_at > proposal_expires_at):
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
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
                    or snap.nonce_digest != binding.nonce_digest or binding_expires_at > snapshot_expires_at
                    or not _bytes_digest_matches(snap.canonical_preview_bytes, snap.preview_digest)
                    or not hmac.compare_digest(digest_of_canonical_text(snap.approval_canonical_text),
                                               snap.approval_digest)):
                return Result.refused(ErrorCode.DIGEST_MISMATCH)
            if binding.requester_person_id == approver.person_id:
                return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
            try:
                current = self.principals.current(approver.principal_id)
                independent = self.principals.are_independent(binding.requester_person_id, approver.person_id)
            except Exception:
                return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
            if (not self._live_approver(current, approver, now)
                    or type(independent) is not bool or independent is not True):
                return Result.refused(ErrorCode.APPROVER_NOT_INDEPENDENT)
            try:
                requester_record = self.principals.current(receipt.proposal.requester_principal)
                dependencies_current = self.principals.epochs_current(receipt.proposal.epoch_dependencies)
            except Exception:
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            if (type(requester_record) is not PrincipalRecord
                    or type(requester_record.revoked) is not bool or requester_record.revoked
                    or type(requester_record.lane) is not str or requester_record.lane != receipt.scope.target_class
                    or type(requester_record.principal_id) is not str
                    or requester_record.principal_id != receipt.proposal.requester_principal
                    or type(requester_record.person_id) is not str or not requester_record.person_id
                    or requester_record.person_id != receipt.requester_person_id
                    or type(requester_record.epoch) is not int or requester_record.epoch < 0
                    or requester_record.epoch != receipt.proposal.auth_epoch_at_proposal
                    or type(requester_record.roles) is not frozenset
                    or any(type(role) is not PrincipalRole for role in requester_record.roles)
                    or PrincipalRole.REQUESTER not in requester_record.roles
                    or type(dependencies_current) is not bool or not dependencies_current):
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            policy_requires_confirmation = receipt.proposal.kind.value == "POST"
            payload = receipt.proposal.payload
            try:
                target = self.targets.current(receipt.scope)
            except Exception:
                return Result.refused(ErrorCode.TARGET_REJECTED)
            if not _allowed_target_record(target, receipt.scope):
                return Result.refused(ErrorCode.TARGET_REJECTED)
            if target.version != receipt.target_version:
                return Result.refused(ErrorCode.STALE_VERSION)
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
                    epoch_dependencies_current=dependencies_current,
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
            try:
                stored_decision = self.store.get(binding.change_id)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if (type(stored_decision) is not DomainReceipt
                    or stored_decision.change_id != receipt.change_id
                    or stored_decision.version != receipt.version
                    or stored_decision.scope != receipt.scope
                    or stored_decision.proposal != receipt.proposal
                    or stored_decision.snapshot != receipt.snapshot
                    or stored_decision.requester_person_id != receipt.requester_person_id
                    or stored_decision.target_version != receipt.target_version
                    or stored_decision.document_ref != receipt.document_ref
                    or stored_decision.approval != result
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
        now_utc = _as_utc(now)
        if type(change_id) is not UUID or now_utc is None:
            return Result.refused(ErrorCode.SCHEMA_INVALID)
        now = now_utc
        with self._lock:
            try:
                receipt = self.store.get(change_id)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if receipt is None:
                return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
            if type(receipt) is not DomainReceipt:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            try:
                issued_error = self.validate_issued_receipt(receipt)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if issued_error is not None:
                if type(issued_error) is not ErrorCode:
                    return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
                return Result.refused(issued_error)
            proposal_expires_at = _as_utc(receipt.proposal.expires_at)
            if proposal_expires_at is None:
                return Result.refused(ErrorCode.SCHEMA_INVALID)
            if proposal_expires_at > now:
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
            try:
                updated = self.store.get(change_id)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if (type(updated) is not DomainReceipt or updated.change_id != receipt.change_id
                    or updated.version != receipt.version or updated.scope != receipt.scope
                    or updated.proposal != receipt.proposal or updated.snapshot != receipt.snapshot
                    or updated.requester_person_id != receipt.requester_person_id
                    or updated.approval != receipt.approval
                    or updated.target_version != receipt.target_version
                    or updated.document_ref != receipt.document_ref
                    or updated.s12_record != transitioned.record):
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            self._s12_anchors[change_id] = transitioned.record
            return Result.success(updated)

    @staticmethod
    def _live_approver(record: PrincipalRecord | None, principal: AuthenticatedPrincipal,
                       now: datetime) -> bool:
        from .contracts import PrincipalRole, TokenClass
        if (type(record) is not PrincipalRecord or type(principal) is not AuthenticatedPrincipal
                or type(record.revoked) is not bool or record.revoked
                or type(record.lane) is not str or record.lane != "TEST"
                or type(principal.lane) is not str or principal.lane != "TEST"
                or principal.token_class is not TokenClass.APPROVER_SESSION
                or type(principal.scope) is not TargetScope
                or type(principal.scope.target_class) is not str or principal.scope.target_class != "TEST"
                or type(record.principal_id) is not str or type(record.person_id) is not str
                or type(principal.principal_id) is not str or type(principal.person_id) is not str
                or record.principal_id != principal.principal_id or record.person_id != principal.person_id
                or type(record.epoch) is not int or type(principal.epoch) is not int
                or record.epoch < 0 or record.epoch != principal.epoch
                or type(record.roles) is not frozenset
                or any(type(role) is not PrincipalRole for role in record.roles)
                or PrincipalRole.APPROVER not in record.roles
                or principal.mfa_authenticated is not True):
            return False
        expires_at = _as_utc(principal.expires_at)
        current = _as_utc(now)
        return expires_at is not None and current is not None and expires_at > current

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
            if (type(updated) is not DomainReceipt or updated.change_id != original.change_id
                    or updated.version != original.version or updated.scope != original.scope
                    or updated.proposal != original.proposal or updated.snapshot != original.snapshot
                    or updated.requester_person_id != original.requester_person_id
                    or updated.target_version != original.target_version
                    or updated.document_ref != original.document_ref
                    or updated.approval != original.approval or updated.s12_record != released_record):
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            previous_anchor = self._s12_anchors.get(change_id)
            self._s12_anchors[change_id] = released_record
            if self.validate_issued_receipt(updated) is not None:
                self._s12_anchors[change_id] = previous_anchor
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        except Exception:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        self._pending_releases.pop(change_id, None)
        self._apply_started.discard(change_id)
        return Result.refused(error)

    def apply(self, requester: AuthenticatedPrincipal, change_id: UUID, *, now: datetime) -> Result[ApplyReceipt]:
        from .contracts import PrincipalRole, TokenClass
        now_utc = _as_utc(now)
        if (type(change_id) is not UUID or now_utc is None
                or not self._live_requester(requester, now_utc, check_epoch=False)):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        now = now_utc
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
                try:
                    prior = self.store.get(change_id)
                except Exception:
                    return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
                if type(prior) is not DomainReceipt:
                    if prior is not None:
                        return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
                elif prior.s12_record is not None:
                    repeated = apply_transition(prior.s12_record, Event.CLAIM, ClaimEvidence(now=now))
                    if type(repeated).__name__ == "Refusal":
                        return Result.refused(repeated.code)
                return Result.refused(ErrorCode.TICKET_SUPERSEDED)
            try:
                receipt = self.store.get(change_id)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if receipt is None:
                return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
            if type(receipt) is not DomainReceipt:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            try:
                issued_error = self.validate_issued_receipt(receipt)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if issued_error is not None:
                if type(issued_error) is not ErrorCode:
                    return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
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
                    or approval.approver_person_id == receipt.requester_person_id):
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            try:
                independent = self.principals.are_independent(receipt.requester_person_id,
                                                              approval.approver_person_id)
            except Exception:
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if type(independent) is not bool or independent is not True:
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
            if not self._live_requester_record(current, requester, check_epoch=False):
                return Result.refused(ErrorCode.NOT_ENTITLED)
            if (current.epoch != requester.epoch or current.epoch != receipt.proposal.auth_epoch_at_proposal
                    or type(epochs_ok) is not bool or epochs_ok is not True):
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            try:
                approver_current = self.principals.current(approval.approver_principal_id)
            except Exception:
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if not self._live_approver_record(approver_current, approval):
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if (not _expires_after(approval.expires_at, now)
                    or not _expires_after(receipt.snapshot.expires_at, now)):
                try:
                    self.expire(change_id, now=now)
                except Exception:
                    pass
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
            try:
                target = self.targets.current(receipt.scope)
            except Exception:
                return Result.refused(ErrorCode.TARGET_REJECTED)
            if not _allowed_target_record(target, receipt.scope):
                return Result.refused(ErrorCode.TARGET_REJECTED)
            if target.version != receipt.target_version:
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
                return Result.refused(claim.error if type(claim.error) is ErrorCode else ErrorCode.CLAIM_EXPIRED)
            if (type(claim) is not Claimed or type(claim.token) is not ClaimToken
                    or type(claim.token.claim_id) is not str or not claim.token.claim_id
                    or type(claim.token.change_id) is not UUID
                    or type(claim.token.version) is not int or claim.token.version < 1
                    or not _valid_sha256_hex(claim.token.approval_digest)
                    or claim.token.change_id != change_id
                    or claim.token.version != receipt.version
                    or claim.token.approval_digest != approval.approval_digest):
                return Result.refused(ErrorCode.CLAIM_EXPIRED)
            self._s12_anchors[change_id] = transitioned.record
            try:
                claimed_receipt = self.store.get(change_id)
            except Exception:
                return self._release_before_begin(receipt, claim.token, transitioned.record,
                                                  ErrorCode.AUDIT_UNAVAILABLE, now=now)
            try:
                claimed_receipt_matches = (type(claimed_receipt) is DomainReceipt
                    and claimed_receipt.s12_record == transitioned.record
                    and claimed_receipt.approval == approval
                    and claimed_receipt.change_id == receipt.change_id
                    and claimed_receipt.version == receipt.version
                    and claimed_receipt.scope == receipt.scope
                    and claimed_receipt.proposal == receipt.proposal
                    and claimed_receipt.requester_person_id == receipt.requester_person_id
                    and claimed_receipt.target_version == receipt.target_version
                    and claimed_receipt.snapshot == receipt.snapshot
                    and claimed_receipt.document_ref == receipt.document_ref)
            except Exception:
                claimed_receipt_matches = False
            if not claimed_receipt_matches:
                return self._release_before_begin(receipt, claim.token, transitioned.record,
                                                  ErrorCode.CLAIM_EXPIRED, now=now)

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
            current_now = _as_utc(current_now)
            if current_now is None:
                return refuse_before_begin(ErrorCode.CHECKPOINT_UNAVAILABLE)
            if (not _expires_after(approval.expires_at, current_now)
                    or not _expires_after(receipt.snapshot.expires_at, current_now)
                    or not _expires_after(requester.expires_at, current_now)):
                return refuse_before_begin(ErrorCode.APPROVAL_EXPIRED, current_now)
            if not _allowed_target_record(current_target, receipt.scope):
                return refuse_before_begin(ErrorCode.TARGET_REJECTED, current_now)
            if current_target.version != receipt.target_version:
                return refuse_before_begin(ErrorCode.STALE_VERSION, current_now)
            if current_fingerprint != receipt.scope.base_fingerprint:
                return refuse_before_begin(ErrorCode.SCOPE_MISMATCH, current_now)
            if not self._live_requester_record(current_requester, requester, check_epoch=False):
                return refuse_before_begin(ErrorCode.NOT_ENTITLED, current_now)
            try:
                epoch_dependencies_current = self.principals.epochs_current(receipt.proposal.epoch_dependencies)
            except Exception:
                return refuse_before_begin(ErrorCode.EPOCH_CHANGED, current_now)
            if (current_requester.epoch != receipt.proposal.auth_epoch_at_proposal
                    or type(epoch_dependencies_current) is not bool or epoch_dependencies_current is not True):
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
            try:
                applying_receipt = self.store.get(change_id)
            except Exception:
                # BEGIN_APPLY is already persisted. Keep the claim terminal for this process,
                # return a fixed refusal, and leave recovery to reconcile the durable state.
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if (type(applying_receipt) is not DomainReceipt
                    or applying_receipt.change_id != receipt.change_id
                    or applying_receipt.version != receipt.version
                    or applying_receipt.scope != receipt.scope
                    or applying_receipt.proposal != receipt.proposal
                    or applying_receipt.snapshot != receipt.snapshot
                    or applying_receipt.approval != approval
                    or applying_receipt.target_version != receipt.target_version
                    or applying_receipt.s12_record != began.record):
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            try:
                issued_error = self.validate_issued_receipt(applying_receipt)
            except Exception:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
            if issued_error is not None:
                if type(issued_error) is not ErrorCode:
                    return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
                return Result.refused(issued_error)
            try:
                target_error = self.validate_current_target(applying_receipt)
            except Exception:
                return Result.refused(ErrorCode.TARGET_REJECTED)
            if target_error is not None:
                if type(target_error) is not ErrorCode:
                    return Result.refused(ErrorCode.TARGET_REJECTED)
                return Result.refused(target_error)
            try:
                final_now = self.clock.now() if self.clock is not None else current_now
                final_requester = self.principals.current(requester.principal_id)
                final_approver = self.principals.current(approval.approver_principal_id)
                final_kill = self.kill_switch.reading(receipt.scope)
                dependencies_current = self.principals.epochs_current(receipt.proposal.epoch_dependencies)
            except Exception:
                return Result.refused(ErrorCode.CHECKPOINT_UNAVAILABLE)
            final_now = _as_utc(final_now)
            if final_now is None:
                return Result.refused(ErrorCode.CHECKPOINT_UNAVAILABLE)
            if (not _expires_after(approval.expires_at, final_now)
                    or not _expires_after(applying_receipt.snapshot.expires_at, final_now)
                    or not _expires_after(requester.expires_at, final_now)):
                try:
                    self.expire(change_id, now=final_now)
                except Exception:
                    pass
                return Result.refused(ErrorCode.APPROVAL_EXPIRED)
            if not self._live_requester_record(final_requester, requester, check_epoch=False):
                return Result.refused(ErrorCode.NOT_ENTITLED)
            if (final_requester.epoch != receipt.proposal.auth_epoch_at_proposal
                    or type(dependencies_current) is not bool or dependencies_current is not True):
                return Result.refused(ErrorCode.EPOCH_CHANGED)
            if not self._live_approver_record(final_approver, approval):
                return Result.refused(ErrorCode.APPROVAL_VOIDED)
            if evaluate(KillSubject.BEGIN_APPLY_ISSUE_PERMIT, final_kill) is not KillDecision.PROCEED:
                return Result.refused(ErrorCode.KILL_SWITCH_ACTIVE)
            try:
                final_target = self.targets.current(receipt.scope)
                final_fingerprint = self.targets.resolve_fingerprint(receipt.scope)
            except Exception:
                return Result.refused(ErrorCode.TARGET_REJECTED)
            if not _allowed_target_record(final_target, applying_receipt.scope):
                return Result.refused(ErrorCode.TARGET_REJECTED)
            if final_fingerprint != applying_receipt.scope.base_fingerprint:
                return Result.refused(ErrorCode.SCOPE_MISMATCH)
            if final_target.version != applying_receipt.target_version:
                return Result.refused(ErrorCode.STALE_VERSION)
            apply_receipt = applying_receipt
            try:
                applied = self.apply_port.apply(apply_receipt, claim.token)
            except Exception:
                # The call may have crossed the port boundary; never retry an unknown outcome.
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            if not _valid_apply_receipt(applied, change_id):
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            try:
                self.store.save_apply_receipt(change_id, applied)
            except Exception:
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            try:
                persisted_apply = self.store.get(change_id)
            except Exception:
                # The apply boundary may already have been crossed. Never retry or claim persistence.
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            expected_persisted = replace(applying_receipt, status=applied.status,
                                         document_ref=applied.document_ref)
            if type(persisted_apply) is not DomainReceipt or persisted_apply != expected_persisted:
                return Result.refused(ErrorCode.APPLY_UNKNOWN)
            self._apply_receipt_anchors[change_id] = applied
            return Result.success(applied)

    @staticmethod
    def _live_approver_record(record: PrincipalRecord | None, approval: ApprovalDecision) -> bool:
        return (type(record) is PrincipalRecord and type(record.revoked) is bool and record.revoked is False
                and type(record.lane) is str and record.lane == "TEST"
                and type(record.principal_id) is str and bool(record.principal_id)
                and type(record.person_id) is str and bool(record.person_id)
                and type(record.epoch) is int and record.epoch >= 0
                and type(record.roles) is frozenset
                and all(type(role) is PrincipalRole for role in record.roles)
                and type(approval) is ApprovalDecision
                and type(approval.scope) is TargetScope and type(approval.scope.target_class) is str
                and approval.scope.target_class == "TEST"
                and record.principal_id == approval.approver_principal_id
                and record.person_id == approval.approver_person_id
                and type(approval.approver_epoch) is int and approval.approver_epoch >= 0
                and record.epoch == approval.approver_epoch
                and PrincipalRole.APPROVER in record.roles)

    def status(self, requester: AuthenticatedPrincipal, change_id: UUID, *, now: datetime) -> Result[DomainReceipt]:
        policy_refusal = authorize_operation(CallerClass.REQUESTER, LedgerOperation.READ_STATUS)
        if policy_refusal is not None:
            return Result.refused(policy_refusal.code)
        if type(change_id) is not UUID or not _aware(now) or not self._live_requester(requester, now):
            return Result.refused(ErrorCode.NOT_ENTITLED)
        try:
            receipt = self.store.get(change_id)
        except Exception:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        if receipt is None:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        if type(receipt) is not DomainReceipt:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        try:
            issued_error = self.validate_issued_receipt(receipt)
        except Exception:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        if issued_error is not None:
            if type(issued_error) is not ErrorCode:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
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
        if type(request.change_id) is not UUID or (request.document_ref is not None
                                                   and type(request.document_ref) is not str):
            return Result.refused(ErrorCode.SCHEMA_INVALID)
        try:
            receipt = self.store.get(request.change_id)
        except Exception:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        if receipt is None:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        if type(receipt) is not DomainReceipt:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        if receipt.scope != requester.scope:
            return Result.refused(ErrorCode.REF_OUT_OF_SCOPE)
        try:
            issued_error = self.validate_issued_receipt(receipt)
        except Exception:
            return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
        if issued_error is not None:
            if type(issued_error) is not ErrorCode:
                return Result.refused(ErrorCode.AUDIT_UNAVAILABLE)
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

