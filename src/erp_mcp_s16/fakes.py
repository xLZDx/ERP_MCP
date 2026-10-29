"""Small, thread-safe fakes for the isolated S16 slice. No persistent or live adapters."""
from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Callable
from uuid import UUID

from business_ai_gateway.phase2.change.errors import ErrorCode, Refusal
from business_ai_gateway.phase2.change.killswitch import SWITCH_OFF
from business_ai_gateway.phase2.change.proposal import ProposalContext, parse_proposal
from business_ai_gateway.phase2.change.types import Scope
from erp_mcp_s15.verifier import VerificationResult, VerificationStatus

from .contracts import (
    ApprovalDecision, ApplyReceipt, ChangeStore, ClaimRefused, Claimed, ClaimToken,
    DecisionBinding, DomainReceipt, KillSwitchPort, TargetScope, VerifyPort,
)


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime.now(timezone.utc)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, delta: timedelta) -> datetime:
        with self._lock:
            self._now += delta
            return self._now


class FakeNonceSource:
    def __init__(self, seed: str = "s16-fake", factory: Callable[[], str] | None = None) -> None:
        self._seed = seed
        self._counter = 0
        self._factory = factory
        self._lock = threading.Lock()

    def issue(self) -> str:
        import hashlib
        with self._lock:
            self._counter += 1
            raw = self._factory() if self._factory else hashlib.sha256(
                f"{self._seed}:{self._counter}".encode()).hexdigest()
            if type(raw) is not str or len(raw) < 32:
                raise ValueError("NONCE_SOURCE_INVALID")
            return raw


class InMemoryChangeStore(ChangeStore):
    """Storage fake. Claim is an atomic CAS; decision policy remains in S16Core."""
    def __init__(self, *, permissive_decisions: bool = False) -> None:
        self._lock = threading.RLock()
        self._receipts: dict[UUID, DomainReceipt] = {}
        self._bindings: dict[str, DecisionBinding] = {}
        self._used_refs: set[str] = set()
        self._used_nonces: set[str] = set()
        self._claims: dict[UUID, ClaimToken] = {}
        self.permissive_decisions = permissive_decisions

    def get(self, change_id: UUID) -> DomainReceipt | None:
        with self._lock:
            return self._receipts.get(change_id)

    def insert_proposal(self, receipt: DomainReceipt) -> None:
        with self._lock:
            if receipt.change_id in self._receipts:
                raise ValueError("CHANGE_ALREADY_EXISTS")
            self._receipts[receipt.change_id] = receipt

    def save_approval(self, decision: ApprovalDecision, *, s12_record=None) -> None:
        with self._lock:
            receipt = self._receipts.get(decision.change_id)
            if receipt is None or receipt.version != decision.version:
                raise ValueError("CHANGE_VERSION_MISMATCH")
            self._receipts[decision.change_id] = replace(
                receipt, status=(f"{s12_record.lifecycle.value}:{s12_record.authorization.value}"
                                 if s12_record else decision.decision),
                approval=decision, s12_record=s12_record or receipt.s12_record)

    def save_s12_record(self, change_id: UUID, s12_record) -> None:
        with self._lock:
            receipt = self._receipts.get(change_id)
            if receipt is None:
                raise ValueError("CHANGE_NOT_FOUND")
            self._receipts[change_id] = replace(
                receipt, status=f"{s12_record.lifecycle.value}:{s12_record.authorization.value}",
                s12_record=s12_record)

    def claim_once(self, change_id: UUID, *, expected_version: int,
                   expected_approval_digest: str, claimant_id: str, s12_record=None):
        with self._lock:
            receipt = self._receipts.get(change_id)
            if (receipt is None or receipt.version != expected_version or receipt.approval is None
                    or receipt.approval.approval_digest != expected_approval_digest
                    or change_id in self._claims):
                return ClaimRefused(ErrorCode.TICKET_SUPERSEDED)
            token = ClaimToken(f"claim-{len(self._claims) + 1}", change_id,
                               expected_version, expected_approval_digest)
            self._claims[change_id] = token
            self._receipts[change_id] = replace(
                receipt, status=(f"{s12_record.lifecycle.value}:{s12_record.authorization.value}"
                                 if s12_record else "CLAIMED"), s12_record=s12_record)
            return Claimed(token)

    def save_apply_receipt(self, change_id: UUID, receipt: ApplyReceipt) -> None:
        with self._lock:
            current = self._receipts.get(change_id)
            if current is None or receipt.change_id != change_id:
                raise ValueError("CHANGE_NOT_FOUND")
            self._receipts[change_id] = replace(current, status=receipt.status,
                                                document_ref=receipt.document_ref)

    def issue_decision_ref(self, decision_ref: str, binding: DecisionBinding) -> None:
        with self._lock:
            if decision_ref in self._bindings:
                raise ValueError("DECISION_REF_COLLISION")
            self._bindings[decision_ref] = binding

    def get_decision_binding(self, decision_ref: str) -> DecisionBinding | None:
        with self._lock:
            return self._bindings.get(decision_ref)

    def consume_decision_ref_and_nonce(self, decision_ref: str, *, expected: DecisionBinding,
                                       decision: ApprovalDecision, s12_record) -> bool:
        with self._lock:
            actual = self._bindings.get(decision_ref)
            if not self.permissive_decisions and (
                    actual != expected or decision_ref in self._used_refs
                    or expected.nonce_digest in self._used_nonces):
                return False
            receipt = self._receipts.get(expected.change_id)
            if receipt is None or receipt.version != expected.version:
                return False
            # Even permissive mode models state mutation, while core independently guards replay.
            self._used_refs.add(decision_ref)
            self._used_nonces.add(expected.nonce_digest)
            self._receipts[expected.change_id] = replace(
                receipt, status=f"{s12_record.lifecycle.value}:{s12_record.authorization.value}",
                approval=decision, s12_record=s12_record)
            return True

    @property
    def claim_count(self) -> int:
        with self._lock:
            return len(self._claims)


class FakeApplyPort:
    def __init__(self, result: ApplyReceipt | None = None, *, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.calls = 0
        self._lock = threading.Lock()

    def apply(self, receipt: DomainReceipt, claim: ClaimToken) -> ApplyReceipt:
        with self._lock:
            self.calls += 1
            if self.fail:
                raise RuntimeError("FAKE_APPLY_UNKNOWN")
            return self.result or ApplyReceipt(receipt.change_id, "APPLIED", "fake-correlation", "fake-document")


class FakeVerifyPort(VerifyPort):
    def __init__(self, result: VerificationResult | None = None) -> None:
        self.result = result or VerificationResult(VerificationStatus.INCONCLUSIVE, "fake", "MACHINE_VERIFIED")

    def verify(self, document_ref, expected, shape) -> VerificationResult:
        return self.result


class FakeKillSwitch(KillSwitchPort):
    def __init__(self, reading=SWITCH_OFF) -> None:
        self.value = reading

    def reading(self, scope: TargetScope):
        return self.value


class FakeRouteAssessment:
    def __init__(self, resolved_addresses=("127.0.0.1",), *, redirects=False,
                 proxy_used=False, unresolved=False) -> None:
        self.resolved_addresses = tuple(resolved_addresses)
        self.redirects = redirects
        self.proxy_used = proxy_used
        self.unresolved = unresolved


class FakeRouteProbe:
    def __init__(self, assessment: FakeRouteAssessment | None = None) -> None:
        self.assessment = assessment or FakeRouteAssessment()
        self.calls: list[tuple[str, int]] = []

    def assess(self, host_ip: str, port: int = 443) -> FakeRouteAssessment:
        self.calls.append((host_ip, port))
        return self.assessment


class FakeToolCallRecorder:
    """Sanitized metadata only; caller controls the allowlist passed to record."""
    def __init__(self) -> None:
        self.entries: list[tuple[str, tuple[str, ...], str]] = []
        self._lock = threading.Lock()

    def record(self, tool_name: str, argument_names: tuple[str, ...], safe_result: str) -> None:
        with self._lock:
            self.entries.append((tool_name[:64], tuple(sorted(argument_names))[:32], safe_result[:64]))


class FakeSecretStore:
    """Placeholder boundary: tracks identifiers only and never stores values."""
    def __init__(self) -> None:
        self.reads: dict[str, int] = {}

    def get(self, key: str):
        self.reads[key] = self.reads.get(key, 0) + 1
        raise LookupError("SECRET_STORE_NOT_CONFIGURED")


class FakeProposalPort:
    """S12 parser adapter with fixture-only scope, version, and currency admission."""
    def __init__(self, targets, principals, *, qualified_currencies: frozenset[str] = frozenset({"USD", "EUR"}),
                 lifetime: timedelta = timedelta(minutes=5)) -> None:
        self.targets = targets
        self.principals = principals
        self.qualified_currencies = qualified_currencies
        self.lifetime = lifetime

    def build(self, requester, raw_request, *, now, preview_digest, nonce, change_id):
        from .contracts import PrincipalRole, TokenClass
        if (requester.token_class is not TokenClass.CHAT_WRITE or PrincipalRole.REQUESTER not in requester.roles
                or requester.scope is None):
            return ErrorCode.NOT_ENTITLED
        target = self.targets.current(requester.scope)
        principal = self.principals.current(requester.principal_id)
        if target is None or not target.allowed or principal is None or principal.revoked:
            return ErrorCode.TARGET_REJECTED
        if target.scope != requester.scope or principal.person_id != requester.person_id:
            return ErrorCode.SCOPE_MISMATCH
        business_digest = __import__("hashlib").sha256(
            (target.scope.base_fingerprint + "\0" + target.version.value).encode()).hexdigest()
        context = ProposalContext(change_id, requester.principal_id, requester.person_id,
                                  Scope(requester.scope.tenant, requester.scope.company,
                                        requester.scope.organization, requester.scope.base_fingerprint),
                                  now, now + self.lifetime, requester.epoch,
                                  principal.epoch_dependencies, preview_digest,
                                  business_state_digest=business_digest,
                                  qualified_currencies=self.qualified_currencies)
        parsed = parse_proposal(raw_request, context)
        if type(parsed) is Refusal:
            return parsed.code
        return parsed, target

    def rollback(self, requester, receipt, *, now, preview_digest, nonce, change_id):
        from .contracts import PrincipalRole, TokenClass
        if (requester.token_class is not TokenClass.CHAT_WRITE or PrincipalRole.REQUESTER not in requester.roles
                or requester.scope != receipt.scope):
            return ErrorCode.NOT_ENTITLED
        target = self.targets.current(receipt.scope)
        principal = self.principals.current(requester.principal_id)
        if target is None or principal is None:
            return ErrorCode.TARGET_REJECTED
        business_digest = __import__("hashlib").sha256(
            (target.scope.base_fingerprint + "\0" + target.version.value).encode()).hexdigest()
        context = ProposalContext(change_id, requester.principal_id, requester.person_id,
                                  Scope(receipt.scope.tenant, receipt.scope.company,
                                        receipt.scope.organization, receipt.scope.base_fingerprint),
                                  now, now + self.lifetime, requester.epoch,
                                  principal.epoch_dependencies, preview_digest,
                                  business_state_digest=business_digest)
        raw = {"kind": "UNPOST", "request_id": "rollback-" + change_id,
               "parent_change_id": receipt.proposal.change_id,
               "target_ref": receipt.proposal.target_ref,
               "target_version": target.version.value, "reason": "S16 rollback proposal"}
        parsed = parse_proposal(raw, context)
        if type(parsed) is Refusal:
            return parsed.code
        return parsed, target
