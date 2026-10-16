"""In-memory synthetic coordinator for the frozen S12 governed-write contract.

This module is a local contract simulator only. It has no database, COM, network,
production identity registry, or authority to operate a real 1C base.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Callable, Mapping, Protocol

from ..change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidence,
    verify_record_signature,
)

__all__ = [
    "GovernedWriteCoordinator", "InMemoryGovernedLedger", "SyntheticWriterPort",
    "SyntheticWriterResult", "SyntheticNoInvocationGuard", "SyntheticAuthorizationCheck",
    "SyntheticAuthorizationDecision", "GovernedWriteState", "GovernedWriteSnapshot",
]


class GovernedWriteState(str, Enum):
    PRE_DISPATCH = "PRE_DISPATCH"
    DISPATCHED = "DISPATCHED"
    APPLY_UNKNOWN = "APPLY_UNKNOWN"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True, slots=True)
class SyntheticNoInvocationGuard:
    """Synthetic durable fact that the mutating method was never entered."""

    dispatch_cas_id: str
    call_id: str
    writer_process_instance_id: str
    evidence_digest: str
    durable: bool

    def calculated_digest(self) -> str:
        body = {
            "dispatch_cas_id": self.dispatch_cas_id,
            "call_id": self.call_id,
            "writer_process_instance_id": self.writer_process_instance_id,
            "durable": self.durable,
        }
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(b"ERP_MCP_R2:S12:SYNTHETIC-NO-INVOCATION-GUARD:v1\n" + encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SyntheticWriterResult:
    """Return from a fake writer, retaining signed records for local validation."""

    receipt: DispatchReceipt | None
    completion: CompletionProof | None
    call_may_have_started: bool
    no_invocation_guard: SyntheticNoInvocationGuard | None = None


class SyntheticWriterPort(Protocol):
    """A deliberately synthetic boundary; implementations must not connect to COM."""

    def invoke(self, attempt: DispatchAttempt) -> SyntheticWriterResult: ...


class SyntheticAuthorizationCheck(Protocol):
    """Fresh local authorization check, called on both sides of synthetic CAS."""

    def check(self, attempt: DispatchAttempt, phase: str) -> SyntheticAuthorizationDecision: ...


@dataclass(frozen=True, slots=True)
class SyntheticAuthorizationDecision:
    """Synthetic authorization result bound to this attempt's current permit tuple."""

    authorized: bool
    auth_epoch: int
    permit_id: str
    permit_digest: str

    def matches(self, attempt: DispatchAttempt) -> bool:
        return (
            self.authorized is True
            and self.auth_epoch == attempt.auth_epoch
            and self.permit_id == attempt.permit_id
            and self.permit_digest == attempt.permit_digest
        )


@dataclass(frozen=True, slots=True)
class GovernedWriteSnapshot:
    attempt: DispatchAttempt
    state: GovernedWriteState
    receipt: DispatchReceipt | None
    completion: CompletionProof | None
    outcome: OutcomeEvidence | None
    hold_retained: bool
    invocation_count: int


class InMemoryGovernedLedger:
    """Thread-safe, process-local ledger enforcing one call per generation/base hold."""

    def __init__(self, signer_keys: Mapping[str, tuple[str, bytes]]) -> None:
        # key_id -> (one permitted role, public key); this is fixture data, not a trust registry.
        self._signer_keys = dict(signer_keys)
        role_keys: dict[str, set[bytes]] = {}
        for key_id, binding in self._signer_keys.items():
            if not isinstance(key_id, str) or not key_id or not isinstance(binding, tuple) or len(binding) != 2:
                raise ValueError("SYNTHETIC_SIGNER_CONFIGURATION_INVALID")
            role, public_key = binding
            if role not in {"writer_receipt", "verification_worker", "completion_supervisor"}:
                raise ValueError("SYNTHETIC_SIGNER_ROLE_INVALID")
            if type(public_key) is not bytes:
                raise ValueError("SYNTHETIC_PUBLIC_KEY_INVALID")
            role_keys.setdefault(role, set()).add(public_key)
        all_roles = tuple(role_keys)
        for index, first in enumerate(all_roles):
            for second in all_roles[index + 1:]:
                if role_keys[first] & role_keys[second]:
                    raise ValueError("SYNTHETIC_SIGNER_KEY_REUSED_ACROSS_ROLES")
        self._records: dict[tuple[str, int], GovernedWriteSnapshot] = {}
        self._base_holds: dict[tuple[str, str, str, str], tuple[str, int]] = {}
        self._lock = RLock()

    @staticmethod
    def _base(attempt: DispatchAttempt) -> tuple[str, str, str, str]:
        return (attempt.tenant_id, attempt.company_id, attempt.organization_ref, attempt.base_fingerprint)

    @staticmethod
    def _key(attempt: DispatchAttempt) -> tuple[str, int]:
        return (attempt.change_id, attempt.claim_generation)

    def begin(self, attempt: DispatchAttempt) -> GovernedWriteSnapshot:
        """Persist synthetic dispatch CAS before the fake writer can be entered."""
        with self._lock:
            key = self._key(attempt)
            existing = self._records.get(key)
            if existing is not None:
                if existing.attempt != attempt:
                    raise ValueError("GENERATION_ATTEMPT_CONFLICT")
                return existing
            base = self._base(attempt)
            held = self._base_holds.get(base)
            if held is not None:
                raise ValueError("BASE_CALL_OWNERSHIP_HOLD")
            snapshot = GovernedWriteSnapshot(
                attempt, GovernedWriteState.DISPATCHED, None, None, None, True, 0
            )
            self._records[key] = snapshot
            self._base_holds[base] = key
            return snapshot

    def consume_dispatch(self, attempt: DispatchAttempt) -> GovernedWriteSnapshot:
        """Atomically mark the single permitted writer invocation consumed."""
        with self._lock:
            current = self._required(attempt)
            if current.state is not GovernedWriteState.DISPATCHED or current.invocation_count:
                raise ValueError("DISPATCH_ALREADY_CONSUMED")
            consumed = GovernedWriteSnapshot(
                attempt, current.state, current.receipt, current.completion, current.outcome,
                True, 1,
            )
            self._records[self._key(attempt)] = consumed
            return consumed

    def mark_unknown(self, attempt: DispatchAttempt, *, invocation_count: int = 1) -> GovernedWriteSnapshot:
        with self._lock:
            current = self._required(attempt)
            if current.state is GovernedWriteState.VERIFIED:
                return current
            updated = GovernedWriteSnapshot(
                attempt, GovernedWriteState.APPLY_UNKNOWN, current.receipt, current.completion,
                current.outcome, True, max(current.invocation_count, invocation_count),
            )
            self._records[self._key(attempt)] = updated
            self._base_holds[self._base(attempt)] = self._key(attempt)
            return updated

    def accept_writer_result(
        self, attempt: DispatchAttempt, result: SyntheticWriterResult, *, reconcile: bool = False
    ) -> GovernedWriteSnapshot:
        with self._lock:
            current = self._required(attempt)
            allowed_states = {GovernedWriteState.DISPATCHED}
            if reconcile:
                allowed_states.add(GovernedWriteState.APPLY_UNKNOWN)
            if current.invocation_count != 1 or current.state not in allowed_states:
                raise ValueError("DISPATCH_ALREADY_CONSUMED")
            receipt, proof = result.receipt, result.completion
            # Preserve partial records before any parser, binding, or signature check.
            if receipt is not None or proof is not None:
                current = GovernedWriteSnapshot(
                    attempt, current.state, receipt or current.receipt, proof or current.completion,
                    current.outcome, True, current.invocation_count,
                )
                self._records[self._key(attempt)] = current
            receipt, proof = current.receipt, current.completion
            if receipt is None:
                return self.mark_unknown(attempt)
            receipt.validate_attempt_binding(attempt)
            if self._valid(receipt, "writer_receipt") is not True:
                return self.mark_unknown(attempt)
            # Only a proven pre-invocation refusal may clear the synthetic base hold.
            guard = result.no_invocation_guard
            guard_matches = (
                guard is not None and guard.durable is True
                and guard.dispatch_cas_id == attempt.dispatch_cas_id
                and guard.call_id == attempt.call_id
                and guard.writer_process_instance_id == attempt.writer_process_instance_id
                and guard.evidence_digest == guard.calculated_digest()
                and guard.evidence_digest == receipt.no_effect_evidence_digest
            )
            if (receipt.result_class == "PRE_WRITE_NO_EFFECT"
                    and receipt.write_invocation_stage == "NOT_INVOKED"
                    and result.call_may_have_started is False and guard_matches
                    and proof is None):
                updated = GovernedWriteSnapshot(
                    attempt, GovernedWriteState.PRE_DISPATCH, receipt, proof, None, False, 1
                )
                self._records[self._key(attempt)] = updated
                self._base_holds.pop(self._base(attempt), None)
                return updated
            if proof is None:
                return self.mark_unknown(attempt)
            proof.validate_attempt_binding(attempt, receipt)
            if self._valid(proof, proof.signer_role) is not True:
                return self.mark_unknown(attempt)
            if (result.call_may_have_started is not True or receipt.result_class != "CALL_RETURNED_SUCCESS"
                    or receipt.call_returned is not True
                    or proof.proof_class not in ("WRITER_CALL_RETURNED", "INDEPENDENT_SESSION_AND_PROCESS_CLOSED")):
                return self.mark_unknown(attempt)
            updated = GovernedWriteSnapshot(
                attempt, GovernedWriteState.APPLIED, receipt, proof, None, True, 1
            )
            self._records[self._key(attempt)] = updated
            return updated

    def accept_outcome(self, attempt: DispatchAttempt, evidence: OutcomeEvidence) -> GovernedWriteSnapshot:
        with self._lock:
            current = self._required(attempt)
            if current.state is not GovernedWriteState.APPLIED or current.receipt is None:
                raise ValueError("OUTCOME_REQUIRES_APPLIED")
            evidence.validate_attempt_binding(attempt, current.receipt)
            if self._valid(evidence, "verification_worker") is not True:
                raise ValueError("OUTCOME_SIGNATURE_INVALID")
            if evidence.observation_complete is not True or evidence.reader_health != "HEALTHY":
                raise ValueError("OUTCOME_INCOMPLETE")
            if evidence.fields_match is not True or evidence.movements_match is not True:
                raise ValueError("OUTCOME_EFFECT_MISMATCH")
            if evidence.effect_presence != "PRESENT" or evidence.effect_identity != "MATCH":
                raise ValueError("OUTCOME_ATTRIBUTION_UNPROVEN")
            if evidence.attribution_result != "PROVEN" or evidence.uncertainties:
                raise ValueError("OUTCOME_ATTRIBUTION_UNPROVEN")
            if evidence.expected_effect_digest != evidence.observed_effect_digest:
                raise ValueError("OUTCOME_EFFECT_DIGEST_MISMATCH")
            if current.completion is None or evidence.completion_proof_class != current.completion.proof_class:
                raise ValueError("OUTCOME_COMPLETION_CLASS_MISMATCH")
            self._validate_observed_operation(attempt, current.receipt, evidence)
            updated = GovernedWriteSnapshot(
                attempt, GovernedWriteState.VERIFIED, current.receipt, current.completion,
                evidence, False, current.invocation_count,
            )
            self._records[self._key(attempt)] = updated
            self._base_holds.pop(self._base(attempt), None)
            return updated

    @staticmethod
    def _validate_observed_operation(
        attempt: DispatchAttempt, receipt: DispatchReceipt, evidence: OutcomeEvidence
    ) -> None:
        """Reject signed observations that contradict the operation's frozen result."""
        expected_posting_state = "POSTED" if attempt.operation_kind == "POST" else "UNPOSTED"
        if evidence.document_posting_state != expected_posting_state:
            raise ValueError("OUTCOME_POSTING_STATE_MISMATCH")

        if attempt.operation_kind == "CREATE_DRAFT":
            if evidence.pre_version is not None or evidence.version_relation != "CREATED":
                raise ValueError("OUTCOME_CREATED_VERSION_INVALID")
            if (not receipt.returned_target_ref or not receipt.returned_version
                    or evidence.target_ref != receipt.returned_target_ref
                    or evidence.observed_version != receipt.returned_version):
                raise ValueError("OUTCOME_CREATED_TARGET_INVALID")
            return

        if (evidence.target_ref != attempt.expected_target_ref
                or evidence.pre_version != attempt.expected_pre_version):
            raise ValueError("OUTCOME_TARGET_PREIMAGE_MISMATCH")
        if (not evidence.observed_version
                or evidence.observed_version == evidence.pre_version
                or evidence.version_relation != "ADVANCED"
                or not receipt.returned_version
                or evidence.observed_version != receipt.returned_version):
            raise ValueError("OUTCOME_VERSION_NOT_ADVANCED")

    def get(self, attempt: DispatchAttempt) -> GovernedWriteSnapshot:
        with self._lock:
            return self._required(attempt)

    def recover_unresolved(self, attempt: DispatchAttempt) -> GovernedWriteSnapshot:
        """Mark any interrupted dispatch unknown without inferring a writer call."""
        with self._lock:
            current = self._required(attempt)
            if current.state is not GovernedWriteState.DISPATCHED:
                return current
            return self.mark_unknown(attempt, invocation_count=current.invocation_count)

    def reconcile_writer_evidence(
        self, attempt: DispatchAttempt, result: SyntheticWriterResult
    ) -> GovernedWriteSnapshot:
        """Attach evidence to APPLY_UNKNOWN without crossing the writer boundary again."""
        return self.accept_writer_result(attempt, result, reconcile=True)

    def _required(self, attempt: DispatchAttempt) -> GovernedWriteSnapshot:
        current = self._records.get(self._key(attempt))
        if current is None or current.attempt != attempt:
            raise ValueError("DISPATCH_ATTEMPT_NOT_FOUND")
        return current

    def _valid(self, record: object, expected_role: str) -> bool:
        key_id = getattr(record, "signer_key_id", None)
        configured = self._signer_keys.get(key_id)
        if configured is None or configured[0] != expected_role:
            return False
        return verify_record_signature(record, configured[1])  # type: ignore[arg-type]


class GovernedWriteCoordinator:
    """Consume a dispatch generation once and fail closed after possible invocation."""

    def __init__(
        self, ledger: InMemoryGovernedLedger, authorization: SyntheticAuthorizationCheck
    ) -> None:
        self._ledger = ledger
        self._authorization = authorization

    def dispatch(self, attempt: DispatchAttempt, writer: SyntheticWriterPort) -> GovernedWriteSnapshot:
        pre_cas = self._authorization.check(attempt, "PRE_CAS")
        if not isinstance(pre_cas, SyntheticAuthorizationDecision) or not pre_cas.matches(attempt):
            raise ValueError("AUTHORIZATION_PRE_CAS_DENIED")
        current = self._ledger.begin(attempt)
        if current.invocation_count:
            # A duplicate returns durable state; it must never call the port again.
            return current
        # Count/consume before crossing the fake writer boundary. Any exception is ambiguous.
        try:
            self._ledger.consume_dispatch(attempt)
        except ValueError as exc:
            if str(exc) == "DISPATCH_ALREADY_CONSUMED":
                return self._ledger.get(attempt)
            raise
        try:
            post_cas = self._authorization.check(attempt, "POST_CAS_PRE_WRITER")
        except BaseException:
            self._ledger.mark_unknown(attempt)
            raise
        if not isinstance(post_cas, SyntheticAuthorizationDecision) or not post_cas.matches(attempt):
            self._ledger.mark_unknown(attempt)
            return self._ledger.get(attempt)
        try:
            result = writer.invoke(attempt)
        except BaseException:
            # The call may have crossed the physical boundary; never retry or release the hold.
            self._ledger.mark_unknown(attempt)
            raise
        try:
            return self._ledger.accept_writer_result(attempt, result)
        except BaseException:
            # Invalid or incomplete evidence after the boundary is unresolved, too.
            self._ledger.mark_unknown(attempt)
            raise

    def recover_unresolved(self, attempt: DispatchAttempt) -> GovernedWriteSnapshot:
        return self._ledger.recover_unresolved(attempt)

    def reconcile_writer_evidence(
        self, attempt: DispatchAttempt, result: SyntheticWriterResult
    ) -> GovernedWriteSnapshot:
        return self._ledger.reconcile_writer_evidence(attempt, result)

    def record_outcome(self, attempt: DispatchAttempt, evidence: OutcomeEvidence) -> GovernedWriteSnapshot:
        return self._ledger.accept_outcome(attempt, evidence)
