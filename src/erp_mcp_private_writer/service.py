"""Fail-closed orchestration boundary for the private S13 writer service.

This module deliberately contains no HTTP listener, database adapter, COM/OData client, or public
gateway registration. A durable admission adapter must atomically enforce the S13 epoch, unique
call identity, one unresolved physical call per authenticated base across all scopes, and the ordered
base/scope fences. Each adapter call must commit or roll back its own top-level transaction before
returning. In particular, no adapter transaction may span a writer port call.

Only the process that durably wins a new admission may invoke the injected writer, and it can do so
at most once. Replays and uncertain outcomes are looked up; they are never dispatched again.
"""
from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID, uuid4

from business_ai_gateway.phase2.change.errors import Refusal
from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
    validate_conditional_conflict_terminal_evidence,
)
from business_ai_gateway.phase2.change.proposal import (
    parse_writer_payload,
    payload_digest,
    payload_to_dict,
)
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.change.types import Scope as ProposalScope
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.uuid_contract import (
    is_canonical_nonzero_uuid,
    is_canonical_process_instance_uuid,
)
from business_ai_gateway.phase2.change_ledger.write_port import (
    ApplyTicket,
    BarrierAcknowledgement,
    DispatchPermit,
    InvocationContext,
    OneCWritePort,
    ReceiptLookupKey,
    ReceiptLookupResult,
    ReceiptLookupState,
    ServingAuthorityLease,
    ServingAuthorityMutex,
)

from .barrier_ack_protocol import (
    BarrierAcknowledgementProtocolError,
    validate_barrier_acknowledgement,
)
from .evidence_trust import EvidenceScope
from .production_evidence_verifier import VerifiedEvidenceRecord

_WRITER_PRECHECK_TIMEOUT_SECONDS = 5.0
_MAX_BARRIER_WAIT_SECONDS = 30.0
_MAX_SHUTDOWN_WAIT_SECONDS = 300.0

__all__ = [
    "AdmissionDecision",
    "AdmissionRefusal",
    "AdmissionState",
    "AdmissionStoreError",
    "BarrierAcknowledgement",
    "BarrierAcknowledgementRejected",
    "BarrierAcknowledgementVerifier",
    "BarrierProgress",
    "BarrierSnapshot",
    "CallIdentity",
    "CallSnapshot",
    "ConditionalConflictEvidenceRefs",
    "ConditionalConflictTerminalRecords",
    "PrivateWriterService",
    "ReceiptDisposition",
    "ResolvedReceiptEvidence",
    "ServiceError",
    "StartupRecoveryState",
    "SuccessfulOutcomeEvidence",
    "T16ResolutionPreparation",
    "WriterEvidenceResolver",
    "WriterReceiptVerifier",
]


class ServiceError(Exception):
    """Stable service refusal; dependency error text is not included."""

    def __init__(self, code: str, *, sqlstate: str | None = None,
                 outcome_unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.sqlstate = sqlstate
        self.outcome_unknown = outcome_unknown


class BarrierAcknowledgementRejected(Exception):
    """The verifier proved a barrier acknowledgement invalid before any durable insert."""


def _is_canonical_process_instance_id(value: object) -> bool:
    """Match the process-instance UUID domain enforced by the S13 store and trust schema."""
    return is_canonical_process_instance_uuid(value)


def _is_canonical_nonzero_uuid(value: object) -> bool:
    return is_canonical_nonzero_uuid(value)


class AdmissionStoreError(Exception):
    """Sanitized adapter failure preserving stable code and transaction certainty."""

    _CODES = frozenset({
        "STALE_EPOCH", "CALL_IDENTITY_CONFLICT", "WRITER_ADMISSION_CLOSED",
        "BASE_CALL_IN_PROGRESS", "NOT_ACCEPTED", "RECOVERY_EVIDENCE_REJECTED",
        "VERIFY_EVIDENCE_ID_CONFLICT", "EVIDENCE_IDENTITY_CONFLICT",
        "TARGET_OBSERVATION_CONFLICT", "RECEIPT_IDENTITY_CONFLICT",
        "T16_RESOLUTION_REQUIRED", "TERMINAL_EVIDENCE_REJECTED",
        "BARRIER_CONFLICT", "LOCK_PLAN_STALE", "LEDGER_LOCK_TIMEOUT",
        "MUTATION_TRANSACTION_INVALID", "NOT_ENTITLED",
        "STARTUP_RECOVERY_INVENTORY_LIMIT",
        "SQL_55P03", "SQL_57014", "SQL_40P01", "STORE_OUTCOME_UNKNOWN",
    })
    _SQLSTATE_BY_CODE = {
        "STALE_EPOCH": "P0001",
        "CALL_IDENTITY_CONFLICT": "P0001",
        "WRITER_ADMISSION_CLOSED": "P0001",
        "BASE_CALL_IN_PROGRESS": "P0001",
        "NOT_ACCEPTED": "P0001",
        "RECOVERY_EVIDENCE_REJECTED": "P0001",
        "VERIFY_EVIDENCE_ID_CONFLICT": "P0001",
        "EVIDENCE_IDENTITY_CONFLICT": "P0001",
        "TARGET_OBSERVATION_CONFLICT": "P0001",
        "RECEIPT_IDENTITY_CONFLICT": "P0001",
        "T16_RESOLUTION_REQUIRED": "P0001",
        "TERMINAL_EVIDENCE_REJECTED": "P0001",
        "BARRIER_CONFLICT": "P0001",
        "LOCK_PLAN_STALE": "P0001",
        "LEDGER_LOCK_TIMEOUT": "P0001",
        "MUTATION_TRANSACTION_INVALID": "P0001",
        "STARTUP_RECOVERY_INVENTORY_LIMIT": "P0001",
        "NOT_ENTITLED": "42501",
        "SQL_55P03": "55P03",
        "SQL_57014": "57014",
        "SQL_40P01": "40P01",
    }

    def __init__(self, code: str, *, sqlstate: str | None = None,
                 outcome_unknown: bool = False) -> None:
        safe_code = code if type(code) is str and code in self._CODES else "STORE_OUTCOME_UNKNOWN"
        expected_sqlstate = self._SQLSTATE_BY_CODE.get(safe_code)
        if (expected_sqlstate is not None and sqlstate != expected_sqlstate):
            # Preserve raw PostgreSQL 55P03 separately from the dedicated fence timeout.
            if safe_code == "LEDGER_LOCK_TIMEOUT" and sqlstate == "55P03":
                safe_code = "SQL_55P03"
                expected_sqlstate = "55P03"
            else:
                safe_code = "STORE_OUTCOME_UNKNOWN"
                expected_sqlstate = None
        elif expected_sqlstate is None and safe_code != "STORE_OUTCOME_UNKNOWN":
            safe_code = "STORE_OUTCOME_UNKNOWN"
        elif safe_code == "STORE_OUTCOME_UNKNOWN":
            expected_sqlstate = None
        super().__init__(safe_code)
        self.code = safe_code
        self.sqlstate = expected_sqlstate
        self.outcome_unknown = outcome_unknown or safe_code in {
            "SQL_55P03", "SQL_57014", "SQL_40P01", "STORE_OUTCOME_UNKNOWN",
        }


class AdmissionState(StrEnum):
    NOT_ACCEPTED = "NOT_ACCEPTED"
    ACCEPTED_NOT_INVOKED = "ACCEPTED_NOT_INVOKED"
    POSSIBLY_EXECUTING = "POSSIBLY_EXECUTING"
    TERMINAL_WITH_EVIDENCE = "TERMINAL_WITH_EVIDENCE"


class AdmissionRefusal(StrEnum):
    STALE_EPOCH = "STALE_EPOCH"
    CALL_IDENTITY_CONFLICT = "CALL_IDENTITY_CONFLICT"
    WRITER_ADMISSION_CLOSED = "WRITER_ADMISSION_CLOSED"
    BASE_CALL_IN_PROGRESS = "BASE_CALL_IN_PROGRESS"
    LOCK_PLAN_STALE = "LOCK_PLAN_STALE"


class BarrierProgress(StrEnum):
    CLOSED_WITH_HOLD = "CLOSED_WITH_HOLD"
    QUIESCED = "QUIESCED"


@dataclass(frozen=True)
class CallIdentity:
    """Immutable client/writer tuple used for durable call-ID conflict detection."""

    tenant_id: str
    company_id: str
    organization_ref: str
    change_id: str
    generation: int
    call_id: str
    operation: str
    target_ref: str | None
    target_version: str | None
    epoch: int
    payload_digest: str
    permit_id: str
    permit_digest: str
    base_fingerprint: str
    host_id: str
    repair_authorization_id: str | None

    def __post_init__(self) -> None:
        """Reject malformed identities from both API construction and durable lookups."""
        text_values = (
            self.tenant_id, self.company_id, self.organization_ref, self.change_id,
            self.call_id, self.operation, self.permit_id, self.permit_digest,
            self.base_fingerprint, self.host_id,
        )
        if any(type(value) is not str or not value or value != value.strip()
               or len(value) > 512
               or any(ord(character) < 32 or ord(character) == 127 for character in value)
               for value in text_values):
            raise ValueError("CALL_IDENTITY_INVALID")
        if (type(self.generation) is not int or self.generation <= 0
                or type(self.epoch) is not int or self.epoch <= 0):
            raise ValueError("CALL_IDENTITY_INVALID")
        if self.operation not in {"CREATE_DRAFT", "POST", "UNPOST"}:
            raise ValueError("CALL_IDENTITY_INVALID")
        if (self.operation == "CREATE_DRAFT"
                and (self.target_ref is not None or self.target_version is not None)):
            raise ValueError("CALL_IDENTITY_INVALID")
        if self.operation != "CREATE_DRAFT" and any(
                type(value) is not str or not value or value != value.strip()
                or len(value) > 512
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
                for value in (self.target_ref, self.target_version)):
            raise ValueError("CALL_IDENTITY_INVALID")
        for value in (self.change_id, self.call_id, self.permit_id):
            if not is_canonical_nonzero_uuid(value):
                raise ValueError("CALL_IDENTITY_INVALID") from None
        if self.repair_authorization_id is not None:
            if not is_canonical_nonzero_uuid(self.repair_authorization_id):
                raise ValueError("CALL_IDENTITY_INVALID") from None
        if any(type(value) is not str or len(value) != 64
               or any(character not in "0123456789abcdef" for character in value)
               for value in (self.payload_digest, self.permit_digest, self.base_fingerprint)):
            raise ValueError("CALL_IDENTITY_INVALID")

    @property
    def scope(self) -> Scope:
        return Scope(self.tenant_id, self.company_id)


@dataclass(frozen=True)
class AdmissionDecision:
    """Result of the atomic, durable admission operation."""

    identity: CallIdentity
    state: AdmissionState
    newly_admitted: bool
    dispatch_cas_id: UUID | None = None
    owner_instance_id: str | None = None
    evidence_ref: str | None = None
    refusal_code: AdmissionRefusal | None = None


@dataclass(frozen=True)
class CallSnapshot:
    """Authoritative durable lookup result for an exact immutable call tuple."""

    identity: CallIdentity
    state: AdmissionState
    dispatch_cas_id: UUID | None = None
    evidence_ref: str | None = None
    owner_instance_id: str | None = None


@dataclass(frozen=True)
class BarrierSnapshot:
    """Complete pre-barrier call set returned atomically by the durable admission store."""

    scope: Scope
    base_fingerprint: str
    barrier_id: UUID
    expected_current_epoch: int
    epoch: int
    barrier_origin_instance_id: str
    barrier_origin_service_epoch: int
    call_ids: tuple[str, ...]
    progress: BarrierProgress
    unresolved_call_ids: tuple[str, ...]
    acknowledgement_ref: str | None = None
    acknowledgement_digest: bytes | None = None
    quiesced_at: datetime | None = None


@dataclass(frozen=True)
class StartupRecoveryState:
    """Durable startup view and exclusive serving epoch for this process instance."""

    service_instance_id: str
    service_epoch: int
    pending_calls: tuple[CallSnapshot, ...]
    open_barriers: tuple[BarrierSnapshot, ...]
    readiness_ref: str | None


@dataclass(frozen=True)
class SuccessfulOutcomeEvidence:
    """Immutable registry references required to finalize a successful S12 operation."""

    outcome_evidence_ref: str
    completion_proof_ref: str


@dataclass(frozen=True)
class ResolvedReceiptEvidence:
    """Exact persisted receipt and its production-verifier result."""

    attempt: DispatchAttempt
    receipt: DispatchReceipt
    verified_receipt: VerifiedEvidenceRecord
    expected_scope: EvidenceScope


@dataclass(frozen=True)
class ConditionalConflictTerminalRecords:
    """Exact signed S12 records required to terminalize an entered conflict."""

    attempt: DispatchAttempt
    receipt: DispatchReceipt
    outcome: OutcomeEvidenceV3
    completion: CompletionProof
    post_completion_challenge: PostCompletionChallenge
    read_attestation: PostCompletionReadAttestation
    verified_records: tuple[VerifiedEvidenceRecord, ...]
    expected_scope: EvidenceScope


@dataclass(frozen=True)
class ConditionalConflictEvidenceRefs:
    """Immutable references ordered by the causal proof chain."""

    completion_proof_ref: str
    post_completion_challenge_ref: str
    outcome_evidence_ref: str
    read_attestation_ref: str

    def __post_init__(self) -> None:
        if any(type(value) is not str or not value for value in (
                self.completion_proof_ref, self.post_completion_challenge_ref,
                self.outcome_evidence_ref, self.read_attestation_ref)):
            raise ValueError("CONFLICT_EVIDENCE_REFERENCE_INVALID")


@dataclass(frozen=True)
class T16ResolutionPreparation:
    """Verified immutable inputs required to continue T16 through checkpoint and S13 recovery."""

    identity: CallIdentity
    dispatch_cas_id: UUID
    receipt_ref: str
    evidence_refs: ConditionalConflictEvidenceRefs

    def __post_init__(self) -> None:
        if (type(self.identity) is not CallIdentity or type(self.dispatch_cas_id) is not UUID
                or self.dispatch_cas_id.int == 0
                or type(self.receipt_ref) is not str or not self.receipt_ref
                or type(self.evidence_refs) is not ConditionalConflictEvidenceRefs):
            raise ValueError("T16_RESOLUTION_PREPARATION_INVALID")


class ReceiptDisposition(StrEnum):
    SUCCESS = "SUCCESS"
    PRE_WRITE_NO_EFFECT = "PRE_WRITE_NO_EFFECT"
    ENTERED_CONDITIONAL_VERSION_CONFLICT = "ENTERED_CONDITIONAL_VERSION_CONFLICT"
    UNKNOWN = "UNKNOWN"


class BarrierAcknowledgementVerifier(Protocol):
    """Independent registry verifier that durably records accepted physical barrier proofs.

    Implementations may raise :class:`BarrierAcknowledgementRejected` only when they can prove
    the acknowledgement was rejected before durable registration. Timeouts, cancellation, and
    every other exception are ambiguous because registration may have committed; the caller will
    return an unknown outcome and retry by the same barrier ID to obtain exact immutable replay.
    """

    async def verify_and_store(self, acknowledgement: BarrierAcknowledgement) -> str: ...


class OutcomeEvidenceProvider(Protocol):
    """Independent read-only verifier for writer receipt, observed effect and completion proof."""

    async def verify_success(self, identity: CallIdentity, dispatch_cas_id: UUID,
                             receipt_ref: str) -> SuccessfulOutcomeEvidence: ...

    async def verify_conditional_conflict(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str) -> ConditionalConflictEvidenceRefs:
        """Return refs for completion → challenge → challenged read-back.

        A completion supervisor issues the challenge only after authenticating
        completion. A distinct read-attestor signs the nonce-bound request, source
        response digest, exact outcome digest, and durable sequence. The coordinator
        reloads and verifies every immutable record.
        """
        ...


class WriterReceiptVerifier(Protocol):
    """Validate original signed receipt bytes before parsing/storage can lose JSON details."""

    async def verify_and_store(self, identity: CallIdentity, dispatch_cas_id: UUID,
                               process_instance_id: str, receipt_envelope: bytes) -> str: ...


class WriterEvidenceResolver(Protocol):
    """Resolve immutable stored records; implementations must fail closed on missing records."""

    async def load_receipt(self, identity: CallIdentity, dispatch_cas_id: UUID,
                           receipt_ref: str) -> ResolvedReceiptEvidence: ...

    async def load_conditional_conflict_terminal_records(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str, outcome_evidence_ref: str,
            completion_proof_ref: str,
            post_completion_challenge_ref: str,
            read_attestation_ref: str) -> ConditionalConflictTerminalRecords: ...


class AdmissionStore(Protocol):
    """Durable adapter contract; every method is a bounded top-level DB transaction.

    ``admit`` atomically compares lifecycle and serving epochs, checks the full call tuple, claims
    the one unresolved physical-base slot, and inserts/returns the unique call record. It reports
    ``newly_admitted=True`` only to the process instance that won
    the insert; an identical replay returns the original owner and is lookup-only. Barrier methods
    return the same deterministically ordered, complete, unpaginated pre-barrier call set for each
    poll and persist QUIESCED only after every call has terminal evidence. ``record_terminal``
    validates writer evidence before committing it. Recovery methods must validate the referenced
    signed S12 receipt/evidence/proof, exact scope and dispatch-CAS binding in the database; opaque
    caller-provided references are never sufficient authority. ``record_recovered_not_invoked``
    must atomically compare-and-transition the same attempt against ``mark_invoking``: if the old
    owner wins invocation, recovery refuses; if recovery wins with process-bound no-effect proof,
    the old owner can no longer mark or enter COM. ``startup_recovery_state`` must read a complete
    durable call/barrier inventory and issue ``readiness_ref`` only when database-side startup
    invariants are satisfied. Startup must atomically claim the exclusive serving epoch and return
    the full recovery inventory; it fences prior service instances from new admission and
    invocation-stage CAS without cancelling a COM invocation that already won its CAS. Admission
    and ``mark_invoking`` must take a shared database lock on the active serving-epoch row after
    the advisory fence order but before claim/record locks, then compare the supplied epoch. Startup
    updates that row exclusively and takes no advisory or scope lock, so epoch takeover serializes
    with both transitions without a lock-order cycle.
    """

    async def admit(self, identity: CallIdentity, process_instance_id: str,
                    service_epoch: int) -> AdmissionDecision: ...

    async def mark_invoking(self, identity: CallIdentity, dispatch_cas_id: UUID,
                            process_instance_id: str, service_epoch: int) -> bool:
        """Recheck serving/lifecycle epochs, barrier and kill-switch in the atomic transition."""
        ...

    async def begin_com_entry(self, identity: CallIdentity, dispatch_cas_id: UUID,
                              process_instance_id: str, service_epoch: int) -> bool:
        """Commit a one-way attempt/CAS fence immediately before the injected writer call."""
        ...

    async def record_terminal(self, identity: CallIdentity, dispatch_cas_id: UUID,
                              process_instance_id: str,
                              receipt_ref: str) -> str:
        """Persist an immutable receipt only; do not terminalize or release the base slot."""
        ...

    async def attach_recovered_receipt(self, identity: CallIdentity, dispatch_cas_id: UUID,
                                       active_service_instance_id: str, service_epoch: int,
                                       original_owner_instance_id: str,
                                       receipt_ref: str) -> str:
        """Attach original-owner evidence to the exact CAS under the current recovery epoch."""
        ...

    async def record_verified_success(self, identity: CallIdentity, dispatch_cas_id: UUID,
                                      active_service_instance_id: str, service_epoch: int,
                                      receipt_ref: str, outcome_evidence_ref: str,
                                      completion_proof_ref: str) -> str:
        """Fence terminal evidence and slot release to the active serving process."""
        ...

    async def record_recovered_not_invoked(self, identity: CallIdentity,
                                           dispatch_cas_id: UUID,
                                           active_service_instance_id: str,
                                           service_epoch: int,
                                           no_effect_receipt_ref: str) -> str:
        """Resolve a live or inventoried attempt only from a one-way non-entry proof.

        For POSSIBLY_EXECUTING, the database must atomically prove that the physical guard
        committed non-entry and permanently prevents that attempt from entering COM later. The
        routine validates the active serving instance/epoch and exact attempt owner. A live apply
        result may resolve its current owner's attempt; a recovery entry point additionally
        requires the exact identity/CAS in this process's complete startup inventory, even after
        readiness is reached. Either path refuses after its restart-required latch.
        A receipt reference or a failed local response alone is never sufficient.
        """
        ...

    async def record_recovered_terminal(self, identity: CallIdentity, dispatch_cas_id: UUID,
                                        active_service_instance_id: str, service_epoch: int,
                                        outcome_evidence_ref: str,
                                        completion_proof_ref: str,
                                        post_completion_challenge_ref: str,
                                        read_attestation_ref: str,
                                        resolution_event_id: UUID) -> str:
        """Resolve only after the store validates bound S12 evidence and proof.

        A conditional-conflict terminal path must load the exact immutable receipt,
            outcome, completion, and post-completion challenge records and apply
        ``validate_conditional_conflict_terminal_evidence`` before the database
        transition. The resolver first re-verifies all exact envelopes with the
        production verifier against one fresh trust snapshot; this helper then checks
        causal and structural evidence binding. The SQL
        transition also requires the exact committed S12 T16 ``OPERATOR_RESOLVE``
        event UUID. It verifies the consumed witness cosign, no-effect observation
        reference and completion-proof identity; T16 alone writes ``FAILED_APPLY``
        and releases the S12 hold/reservation. The SQL transition rechecks the
        immutable evidence and active serving epoch before clearing the S13
        physical-base slot. Caller-supplied evidence references alone never
        authorize that transition.
        """
        ...

    async def lookup(self, identity: CallIdentity) -> CallSnapshot: ...

    async def lookup_barrier(self, barrier_id: UUID) -> BarrierSnapshot | None:
        """Read authoritative progress for an immutable barrier ID after ambiguous outcomes."""
        ...

    async def close_and_advance(self, base_fingerprint: str, scope: Scope,
                                expected_current_epoch: int,
                                barrier_id: UUID, service_instance_id: str,
                                service_epoch: int) -> BarrierSnapshot:
        """Close admission only for the currently serving instance and epoch."""
        ...

    async def finish_barrier(self, snapshot: BarrierSnapshot,
                             acknowledgement_ref: str, service_instance_id: str,
                             service_epoch: int) -> BarrierSnapshot:
        """Require current serving ownership and verified physical evidence before QUIESCED."""
        ...

    async def startup_recovery_state(
            self, service_instance_id: str,
            authority_lease: ServingAuthorityLease) -> StartupRecoveryState:
        """Advance serving epoch under the host-wide serving-authority mutex.

        This mutex is shared with ``OneCWritePort.quiesce`` so takeover and
        physical queue closure have a single host-local linearization order. The
        database transaction remains bounded and never spans a COM call.
        """
        ...


class PrivateWriterService:
    """Coordinate durable admission and one injected writer call, without retrying COM."""

    __slots__ = (
        "_active_control_operations",
        "_active_dispatch",
        "_active_dispatch_done",
        "_active_quiesce",
        "_barrier_ack_verifier",
        "_barrier_wait_seconds",
        "_base_dispatch_lock",
        "_base_fingerprint",
        "_control_operations_done",
        "_host_id",
        "_outcome_evidence_provider",
        "_pending_t16_resolution_calls",
        "_restart_required",
        "_service_epoch",
        "_service_instance_id",
        "_serving_authority_mutex",
        "_shutdown_started",
        "_startup_complete",
        "_startup_recovery",
        "_store",
        "_terminal_mutation_lock",
        "_writer",
        "_writer_evidence_resolver",
        "_writer_receipt_verifier",
    )
    _CONFIGURATION_FIELDS = frozenset({
        "_store", "_writer", "_serving_authority_mutex", "_host_id", "_service_instance_id",
        "_base_fingerprint", "_barrier_wait_seconds", "_barrier_ack_verifier",
        "_writer_receipt_verifier", "_outcome_evidence_provider", "_writer_evidence_resolver",
        "_base_dispatch_lock", "_active_dispatch_done", "_control_operations_done",
        "_terminal_mutation_lock",
        "_pending_t16_resolution_calls",
    })
    _LIFECYCLE_FIELDS = frozenset({
        "_active_dispatch", "_active_quiesce", "_startup_complete", "_service_epoch",
        "_startup_recovery", "_shutdown_started", "_active_control_operations",
    })

    def __setattr__(self, name: str, value: object) -> None:
        if name in type(self)._CONFIGURATION_FIELDS and hasattr(self, name):
            code = (
                "BARRIER_TIMEOUT_CONFIGURATION_IMMUTABLE"
                if name == "_barrier_wait_seconds" else "WRITER_CONFIGURATION_IMMUTABLE"
            )
            raise AttributeError(code)
        if (name in type(self)._LIFECYCLE_FIELDS and hasattr(self, name)):
            raise AttributeError("WRITER_LIFECYCLE_MUTATION_FORBIDDEN")
        if name == "_restart_required" and hasattr(self, name):
            raise AttributeError("WRITER_RESTART_LATCH_INTERNAL")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in type(self)._CONFIGURATION_FIELDS:
            code = (
                "BARRIER_TIMEOUT_CONFIGURATION_IMMUTABLE"
                if name == "_barrier_wait_seconds" else "WRITER_CONFIGURATION_IMMUTABLE"
            )
            raise AttributeError(code)
        if name in type(self)._LIFECYCLE_FIELDS:
            raise AttributeError("WRITER_LIFECYCLE_MUTATION_FORBIDDEN")
        raise AttributeError("WRITER_STATE_DELETION_FORBIDDEN")

    def _set_lifecycle_field(self, name: str, value: object) -> None:
        """Apply validated internal lifecycle updates without exposing ordinary assignment."""
        if name not in type(self)._LIFECYCLE_FIELDS:
            raise AttributeError("WRITER_LIFECYCLE_MUTATION_FORBIDDEN")
        current = getattr(self, name)
        if name == "_active_dispatch":
            valid = value is None or isinstance(value, asyncio.Task)
            if valid and value is None and current is not None:
                valid = isinstance(current, asyncio.Task) and current.done()
        elif name == "_shutdown_started":
            valid = type(value) is bool and (value is current or (current is False and value is True))
        elif name == "_active_control_operations":
            valid = type(value) is int and value >= 0 and abs(value - current) == 1
        elif name == "_active_quiesce":
            valid = (value is None or (type(value) is tuple and len(value) == 2
                     and type(value[0]) is UUID and value[0].int != 0
                     and isinstance(value[1], asyncio.Task)))
            if valid and value is None and current is not None:
                valid = (type(current) is tuple and len(current) == 2
                         and isinstance(current[1], asyncio.Task) and current[1].done())
        elif name == "_startup_complete":
            valid = type(value) is bool
            if value is True:
                state = self._startup_recovery
                valid = (valid and type(self._service_epoch) is int
                         and type(state) is StartupRecoveryState
                         and state.service_epoch == self._service_epoch
                         and bool(state.readiness_ref)
                         and not state.pending_calls and not state.open_barriers
                         and not self._restart_required and not self._shutdown_started)
        elif name == "_service_epoch":
            valid = value is None or (type(value) is int and value >= 1)
            if value is not None:
                state = self._startup_recovery
                valid = (valid and type(state) is StartupRecoveryState
                         and state.service_epoch == value)
        else:
            valid = value is None or type(value) is StartupRecoveryState
        if not valid:
            raise RuntimeError("WRITER_LIFECYCLE_VALUE_INVALID")
        if current is value or (type(value) in (bool, int, type(None)) and current == value):
            return
        object.__setattr__(self, name, value)

    _WRITER_METHODS = MappingProxyType({
        "CREATE_DRAFT": "create_draft",
        "POST": "post",
        "UNPOST": "unpost",
    })

    @staticmethod
    def _store_failure(error: Exception, fallback_code: str) -> ServiceError:
        if isinstance(error, AdmissionStoreError):
            return ServiceError(error.code, sqlstate=error.sqlstate,
                                outcome_unknown=error.outcome_unknown)
        return ServiceError(fallback_code, outcome_unknown=True)

    def __init__(self, store: AdmissionStore, writer: OneCWritePort, *, host_id: str,
                 base_fingerprint: str,
                 serving_authority_mutex: ServingAuthorityMutex | None = None,
                 barrier_wait_seconds: float = 5.0,
                 barrier_ack_verifier: BarrierAcknowledgementVerifier | None = None,
                 writer_receipt_verifier: WriterReceiptVerifier | None = None,
                 outcome_evidence_provider: OutcomeEvidenceProvider | None = None,
                 writer_evidence_resolver: WriterEvidenceResolver | None = None,
                 ) -> None:
        if (type(host_id) is not str or not host_id or host_id != host_id.strip()
                or len(host_id) > 512
                or any(ord(character) < 32 or ord(character) == 127 for character in host_id)
                or type(base_fingerprint) is not str or len(base_fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in base_fingerprint)):
            raise ValueError("WRITER_BINDING_INVALID")
        if (isinstance(barrier_wait_seconds, bool)
                or not isinstance(barrier_wait_seconds, (int, float))):
            raise ValueError("BARRIER_TIMEOUT_INVALID")
        if barrier_wait_seconds <= 0 or barrier_wait_seconds > _MAX_BARRIER_WAIT_SECONDS:
            raise ValueError("BARRIER_TIMEOUT_INVALID")
        try:
            validated_barrier_wait = float(barrier_wait_seconds)
        except (OverflowError, ValueError):
            raise ValueError("BARRIER_TIMEOUT_INVALID") from None
        if not math.isfinite(validated_barrier_wait) or validated_barrier_wait <= 0:
            raise ValueError("BARRIER_TIMEOUT_INVALID")
        self._store = store
        self._writer = writer
        self._serving_authority_mutex = serving_authority_mutex
        self._host_id = host_id
        self._service_instance_id = str(uuid4())
        self._base_fingerprint = base_fingerprint
        self._barrier_wait_seconds = validated_barrier_wait
        self._barrier_ack_verifier = barrier_ack_verifier
        self._writer_receipt_verifier = writer_receipt_verifier
        self._outcome_evidence_provider = outcome_evidence_provider
        self._writer_evidence_resolver = writer_evidence_resolver
        self._base_dispatch_lock = asyncio.Lock()
        self._active_dispatch: asyncio.Task[Any] | None = None
        self._active_dispatch_done = asyncio.Event()
        self._active_dispatch_done.set()
        self._active_quiesce: tuple[UUID, asyncio.Task[Any]] | None = None
        self._active_control_operations = 0
        self._control_operations_done = asyncio.Event()
        self._control_operations_done.set()
        # Serialize fatal process-latch changes with terminal/recovery store calls.
        # The lock is intentionally held through each bounded database transaction: a
        # terminal commit that acquires it first linearizes before a later fatal latch;
        # if the latch wins first, the terminal mutation is refused.
        self._terminal_mutation_lock = asyncio.Lock()
        self._pending_t16_resolution_calls: dict[
            tuple[CallIdentity, UUID], ConditionalConflictEvidenceRefs
        ] = {}
        self._startup_complete = False
        self._restart_required = False
        self._service_epoch: int | None = None
        self._startup_recovery: StartupRecoveryState | None = None
        self._shutdown_started = False

    @property
    def ready(self) -> bool:
        """Whether this coordinator may admit/dispatch work in its current process."""
        return (self._startup_complete and not self._restart_required
                and not self._shutdown_started)

    async def shutdown(self, *, timeout_seconds: float = 30.0) -> None:
        """Stop new dispatch/control work and drain every operation that already entered.

        The HTTP/MCP listener must already have stopped accepting requests. This method does not
        close the writer or authority mutex; the runtime closes those only after this drain
        succeeds. A timeout leaves the service fail-stopped and preserves any held authority.
        """
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= _MAX_SHUTDOWN_WAIT_SECONDS):
            raise ValueError("WRITER_SHUTDOWN_TIMEOUT_INVALID")
        self._set_lifecycle_field("_shutdown_started", True)
        self._set_lifecycle_field("_startup_complete", False)
        deadline = asyncio.get_running_loop().time() + float(timeout_seconds)

        while True:
            if self._active_control_operations:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    await self._latch_restart_required()
                    raise ServiceError("WRITER_SHUTDOWN_DRAIN_TIMEOUT", outcome_unknown=True)
                try:
                    async with asyncio.timeout(remaining):
                        await self._control_operations_done.wait()
                except TimeoutError:
                    await self._latch_restart_required()
                    raise ServiceError("WRITER_SHUTDOWN_DRAIN_TIMEOUT",
                                       outcome_unknown=True) from None
                continue

            active_dispatch = self._active_dispatch
            if active_dispatch is not None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    await self._latch_restart_required()
                    raise ServiceError("WRITER_SHUTDOWN_DRAIN_TIMEOUT", outcome_unknown=True)
                try:
                    async with asyncio.timeout(remaining):
                        await asyncio.shield(active_dispatch)
                except asyncio.CancelledError:
                    if active_dispatch.cancelled():
                        await self._latch_restart_required()
                    else:
                        raise
                except Exception:
                    # The physical path completed with a refusal or unknown outcome. Its
                    # completion callback still owns lease release and lifecycle cleanup.
                    pass
                if self._active_dispatch is active_dispatch:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        await self._latch_restart_required()
                        raise ServiceError("WRITER_SHUTDOWN_DRAIN_TIMEOUT", outcome_unknown=True)
                    try:
                        async with asyncio.timeout(remaining):
                            await self._active_dispatch_done.wait()
                    except TimeoutError:
                        await self._latch_restart_required()
                        raise ServiceError("WRITER_SHUTDOWN_DRAIN_TIMEOUT",
                                           outcome_unknown=True) from None
                continue

            active_quiesce = self._active_quiesce
            if active_quiesce is not None:
                try:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError
                    async with asyncio.timeout(remaining):
                        await asyncio.shield(active_quiesce[1])
                except asyncio.CancelledError:
                    if active_quiesce[1].cancelled():
                        await self._latch_restart_required()
                    else:
                        raise
                except Exception:
                    pass
                if self._active_quiesce == active_quiesce:
                    self._authority_task_done(*active_quiesce)
                continue

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                await self._latch_restart_required()
                raise ServiceError("WRITER_SHUTDOWN_DRAIN_TIMEOUT", outcome_unknown=True)
            try:
                async with asyncio.timeout(remaining):
                    await self._base_dispatch_lock.acquire()
            except TimeoutError:
                await self._latch_restart_required()
                raise ServiceError("WRITER_SHUTDOWN_DRAIN_TIMEOUT",
                                   outcome_unknown=True) from None
            self._base_dispatch_lock.release()
            if self._active_dispatch is None and self._active_quiesce is None:
                if self._restart_required:
                    raise ServiceError("SERVICE_RESTART_REQUIRED", outcome_unknown=True)
                return

    @property
    def restart_required(self) -> bool:
        """Latch unsafe physical-close outcomes until a new process reconstructs state."""
        return self._restart_required

    async def inspect_startup_recovery(self) -> StartupRecoveryState:
        self._begin_control_operation()
        try:
            return await self._inspect_startup_recovery_started()
        finally:
            self._end_control_operation()

    async def _inspect_startup_recovery_started(self) -> StartupRecoveryState:
        """Return the complete durable restart inventory while keeping dispatch closed."""
        if self._restart_required:
            raise ServiceError("SERVICE_RESTART_REQUIRED")
        self._set_lifecycle_field("_startup_complete", False)
        self._set_lifecycle_field("_service_epoch", None)
        mutex = self._serving_authority_mutex
        if mutex is None:
            raise ServiceError("SERVING_AUTHORITY_MUTEX_UNAVAILABLE")
        try:
            lease = await mutex.try_acquire()
        except BaseException:
            await self._latch_restart_required()
            raise ServiceError("STARTUP_RECOVERY_UNAVAILABLE") from None
        if lease is None:
            raise ServiceError("SERVING_AUTHORITY_BUSY", outcome_unknown=True)
        try:
            try:
                async with asyncio.timeout(self._barrier_wait_seconds):
                    lease.assert_held()
                    state = await self._store.startup_recovery_state(
                        self._service_instance_id, lease,
                    )
            finally:
                try:
                    await lease.release()
                except BaseException:
                    await self._latch_restart_required()
                    raise
        except TimeoutError:
            raise ServiceError("STARTUP_RECOVERY_UNAVAILABLE") from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "STARTUP_RECOVERY_UNAVAILABLE") from None
        except Exception as exc:
            raise self._store_failure(exc, "STARTUP_RECOVERY_UNAVAILABLE") from None
        if (type(state) is not StartupRecoveryState
                or type(state.pending_calls) is not tuple
                or type(state.open_barriers) is not tuple
                or not _is_canonical_process_instance_id(state.service_instance_id)
                or state.service_instance_id != self._service_instance_id
                or type(state.service_epoch) is not int or state.service_epoch <= 0
                or type(state.readiness_ref) not in (str, type(None))):
            raise ServiceError("STARTUP_RECOVERY_STATE_INVALID")
        if (state.readiness_ref is not None
                and not _is_canonical_nonzero_uuid(state.readiness_ref)):
            raise ServiceError("STARTUP_RECOVERY_STATE_INVALID")
        for call in state.pending_calls:
            if (type(call) is not CallSnapshot or type(call.identity) is not CallIdentity
                    or call.identity.base_fingerprint != self._base_fingerprint
                    or call.identity.host_id != self._host_id
                    or type(call.state) is not AdmissionState
                    or call.state not in (AdmissionState.ACCEPTED_NOT_INVOKED,
                                          AdmissionState.POSSIBLY_EXECUTING)
                    or type(call.dispatch_cas_id) is not UUID
                    or call.dispatch_cas_id.int == 0
                    or (call.evidence_ref is not None
                        and (type(call.evidence_ref) is not str or not call.evidence_ref
                             or call.evidence_ref != call.evidence_ref.strip()))
                    or (call.state is AdmissionState.POSSIBLY_EXECUTING
                        and not _is_canonical_process_instance_id(call.owner_instance_id))
                    or (call.state is not AdmissionState.POSSIBLY_EXECUTING
                        and call.owner_instance_id is not None)):
                raise ServiceError("STARTUP_RECOVERY_STATE_INVALID")
        for barrier in state.open_barriers:
            if (type(barrier) is not BarrierSnapshot
                    or not self._barrier_snapshot_valid(
                        barrier, barrier.scope, self._base_fingerprint,
                        barrier.epoch, barrier.barrier_id)):
                raise ServiceError("STARTUP_RECOVERY_STATE_INVALID")
        if (len({call.identity.call_id for call in state.pending_calls})
                != len(state.pending_calls)
                or len({call.dispatch_cas_id for call in state.pending_calls})
                != len(state.pending_calls)
                or len({barrier.barrier_id for barrier in state.open_barriers})
                != len(state.open_barriers)):
            raise ServiceError("STARTUP_RECOVERY_STATE_INVALID")
        self._set_lifecycle_field("_startup_recovery", state)
        self._set_lifecycle_field("_service_epoch", state.service_epoch)
        return state

    async def prepare_to_serve(self) -> StartupRecoveryState:
        """Open dispatch only after a complete durable startup view proves there is no recovery work."""
        if self._shutdown_started:
            raise ServiceError("WRITER_SHUTTING_DOWN")
        if self._restart_required:
            raise ServiceError("SERVICE_RESTART_REQUIRED")
        state = await self.inspect_startup_recovery()
        # Recovery inspection awaits storage; shutdown or a failed physical close can
        # invalidate this startup attempt before the coroutine resumes.
        if self._shutdown_started:
            raise ServiceError("WRITER_SHUTTING_DOWN")
        if self._restart_required:
            raise ServiceError("SERVICE_RESTART_REQUIRED")
        if state.pending_calls or state.open_barriers or not state.readiness_ref:
            raise ServiceError("STARTUP_RECOVERY_REQUIRED")
        self._set_lifecycle_field("_startup_recovery", state)
        self._set_lifecycle_field("_service_epoch", state.service_epoch)
        self._set_lifecycle_field("_startup_complete", True)
        return state

    def _identity(self, ticket: ApplyTicket, permit: DispatchPermit) -> CallIdentity:
        if type(ticket) is not ApplyTicket or type(permit) is not DispatchPermit:
            raise ServiceError("CALL_IDENTITY_INVALID")
        if (type(ticket.kind) is not str
                or type(ticket.change_id) is not str or type(ticket.call_id) is not str
                or type(permit.change_id) is not str or type(permit.call_id) is not str
                or type(ticket.repair_authorization_id) not in (str, type(None))
                or type(permit.repair_authorization_id) not in (str, type(None))
                or type(ticket.target_ref) not in (str, type(None))
                or type(ticket.target_version) not in (str, type(None))
                or type(ticket.generation) is not int or ticket.generation <= 0
                or type(permit.generation) is not int or permit.generation <= 0
                or type(permit.lifecycle_epoch) is not int or permit.lifecycle_epoch <= 0
                or permit.generation != ticket.generation
                or permit.change_id != ticket.change_id or permit.call_id != ticket.call_id
                or permit.repair_authorization_id != ticket.repair_authorization_id
                or type(ticket.base_fingerprint) is not str
                or ticket.base_fingerprint != self._base_fingerprint):
            raise ServiceError("CALL_IDENTITY_INVALID")
        if ticket.kind not in self._WRITER_METHODS:
            raise ServiceError("OPERATION_UNSUPPORTED")
        uuid_inputs = (ticket.change_id, ticket.call_id, permit.permit_id)
        if any(type(value) is not str or len(value) != 36 for value in uuid_inputs):
            raise ServiceError("CALL_IDENTITY_INVALID")
        if (ticket.repair_authorization_id is not None
                and (type(ticket.repair_authorization_id) is not str
                     or len(ticket.repair_authorization_id) != 36)):
            raise ServiceError("CALL_IDENTITY_INVALID")
        try:
            parsed_change_id = UUID(ticket.change_id)
            parsed_call_id = UUID(ticket.call_id)
            parsed_permit_id = UUID(permit.permit_id)
            parsed_repair_authorization_id = (
                UUID(ticket.repair_authorization_id)
                if ticket.repair_authorization_id is not None else None
            )
            if (parsed_change_id.int == 0 or parsed_call_id.int == 0
                    or parsed_permit_id.int == 0
                    or (parsed_repair_authorization_id is not None
                        and parsed_repair_authorization_id.int == 0)):
                raise ValueError
            change_id = str(parsed_change_id)
            call_id = str(parsed_call_id)
            permit_id = str(parsed_permit_id)
            repair_authorization_id = (
                str(parsed_repair_authorization_id)
                if parsed_repair_authorization_id is not None else None
            )
        except (ValueError, TypeError, AttributeError):
            raise ServiceError("CALL_IDENTITY_INVALID") from None
        if (change_id != ticket.change_id or call_id != ticket.call_id
                or permit_id != permit.permit_id
                or (ticket.repair_authorization_id is not None
                    and repair_authorization_id != ticket.repair_authorization_id)):
            raise ServiceError("CALL_IDENTITY_INVALID")
        if any(type(value) is not str or not value or value != value.strip()
               or len(value) > 512
               or any(ord(character) < 32 or ord(character) == 127 for character in value)
               for value in (ticket.tenant_id, ticket.company_id, ticket.organization)):
            raise ServiceError("CALL_SCOPE_INVALID")
        if ticket.kind == "CREATE_DRAFT":
            if ticket.target_ref is not None or ticket.target_version is not None:
                raise ServiceError("CALL_IDENTITY_INVALID")
        elif any(type(value) is not str or not value or value != value.strip()
                 or len(value) > 512
                 or any(ord(character) < 32 or ord(character) == 127 for character in value)
                 for value in (ticket.target_ref, ticket.target_version)):
            raise ServiceError("CALL_IDENTITY_INVALID")
        if (type(ticket.digest_set_hash) is not str or len(ticket.digest_set_hash) != 64
                or any(ch not in "0123456789abcdef" for ch in ticket.digest_set_hash)
                or type(ticket.approved_payload_digest) is not str
                or len(ticket.approved_payload_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in ticket.approved_payload_digest)
                or type(permit.permit_digest) is not str or len(permit.permit_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in permit.permit_digest)):
            raise ServiceError("CALL_IDENTITY_INVALID")
        return CallIdentity(
            tenant_id=ticket.tenant_id,
            company_id=ticket.company_id,
            organization_ref=ticket.organization,
            change_id=change_id,
            generation=ticket.generation,
            call_id=call_id,
            operation=ticket.kind,
            target_ref=ticket.target_ref,
            target_version=ticket.target_version,
            epoch=permit.lifecycle_epoch,
            payload_digest=ticket.approved_payload_digest,
            permit_id=permit_id,
            permit_digest=permit.permit_digest,
            base_fingerprint=ticket.base_fingerprint,
            host_id=self._host_id,
            repair_authorization_id=repair_authorization_id,
        )

    async def lookup(self, ticket: ApplyTicket, permit: DispatchPermit) -> CallSnapshot:
        """Return the durable status for the exact ticket/permit identity; never invoke the writer."""
        identity = self._identity(ticket, permit)
        try:
            snapshot = await self._store.lookup(identity)
        except Exception as exc:
            raise self._store_failure(exc, "OUTCOME_LOOKUP_UNAVAILABLE") from None
        if (type(snapshot) is not CallSnapshot or snapshot.identity != identity
                or type(snapshot.state) is not AdmissionState
                or (snapshot.state is not AdmissionState.NOT_ACCEPTED
                    and (type(snapshot.dispatch_cas_id) is not UUID
                         or snapshot.dispatch_cas_id.int == 0))
                or (snapshot.state is AdmissionState.NOT_ACCEPTED
                    and (snapshot.dispatch_cas_id is not None
                         or snapshot.evidence_ref is not None
                         or snapshot.owner_instance_id is not None))
                or (snapshot.evidence_ref is not None
                    and (type(snapshot.evidence_ref) is not str or not snapshot.evidence_ref
                         or snapshot.evidence_ref != snapshot.evidence_ref.strip()))
                or (snapshot.state is AdmissionState.TERMINAL_WITH_EVIDENCE
                    and snapshot.evidence_ref is None)
                or (snapshot.state is AdmissionState.POSSIBLY_EXECUTING
                    and not _is_canonical_process_instance_id(snapshot.owner_instance_id))
                or (snapshot.state is not AdmissionState.POSSIBLY_EXECUTING
                    and snapshot.owner_instance_id is not None)):
            raise ServiceError("OUTCOME_LOOKUP_INVALID")
        return snapshot

    async def _lookup_admitted_call(self, ticket: ApplyTicket, permit: DispatchPermit,
                                    dispatch_cas_id: UUID) -> CallSnapshot:
        snapshot = await self.lookup(ticket, permit)
        if snapshot.dispatch_cas_id != dispatch_cas_id:
            raise ServiceError("DISPATCH_CAS_MISMATCH")
        return snapshot

    def _recovery_transition_authorized(self, identity: CallIdentity,
                                        dispatch_cas_id: UUID) -> bool:
        """Allow recovery only for this process's exact startup-inventoried orphan."""
        if (self._restart_required or type(self._service_epoch) is not int
                or self._service_epoch < 1):
            return False
        state = self._startup_recovery
        return bool(
            type(state) is StartupRecoveryState
            and state.service_instance_id == self._service_instance_id
            and state.service_epoch == self._service_epoch
            and any(
                call.state in (AdmissionState.ACCEPTED_NOT_INVOKED,
                               AdmissionState.POSSIBLY_EXECUTING)
                and call.identity == identity
                and call.dispatch_cas_id == dispatch_cas_id
                for call in state.pending_calls
            )
        )

    def _active_transition_authorized(self, identity: CallIdentity,
                                      dispatch_cas_id: UUID) -> bool:
        """Allow a live terminal result or an exact inventoried recovery transition."""
        if (self._restart_required or type(self._service_epoch) is not int
                or self._service_epoch < 1):
            return False
        if self._startup_complete:
            return True
        return self._recovery_transition_authorized(identity, dispatch_cas_id)

    def _active_serving_context(self) -> tuple[str, int]:
        """Return this process's current epoch, refusing writes after a fatal latch."""
        if (self._restart_required or type(self._service_epoch) is not int
                or self._service_epoch < 1):
            raise ServiceError("SERVING_EPOCH_UNAVAILABLE", outcome_unknown=True)
        return self._service_instance_id, self._service_epoch

    async def _latch_restart_required(self) -> None:
        """Linearize a fatal latch against any terminal database transaction in this process."""
        async def latch() -> None:
            async with self._terminal_mutation_lock:
                object.__setattr__(self, "_restart_required", True)
                self._set_lifecycle_field("_startup_complete", False)

        task = asyncio.create_task(latch())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # The caller may be handling cancellation from the physical operation. The
            # fail-stop latch must still finish before cancellation leaves this boundary.
            await task
            raise

    async def _run_active_terminal_mutation(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            transition: Callable[[str, int], Awaitable[Any]], *,
            require_startup_inventory: bool = False) -> Any:
        """Reauthorize and serialize one terminal store call with fatal local latching.

        Holding the process-local lock through the adapter's bounded call defines the
        authorization race: either the store call reaches its return/cleanup boundary
        before a fatal latch becomes visible, or the latch is visible and the call does
        not start. An indeterminate commit remains unknown and requires authoritative
        lookup. Active serving epoch and recovery-inventory checks remain independently
        enforced by the versioned SQL API.
        """
        async with self._terminal_mutation_lock:
            authorized = (
                self._recovery_transition_authorized(identity, dispatch_cas_id)
                if require_startup_inventory
                else self._active_transition_authorized(identity, dispatch_cas_id)
            )
            if not authorized:
                raise ServiceError("STARTUP_RECOVERY_REQUIRED")
            instance_id, service_epoch = self._active_serving_context()
            return await transition(instance_id, service_epoch)

    async def lookup_barrier(self, barrier_id: UUID) -> BarrierSnapshot | None:
        """Read the durable state after an unknown barrier-finalization outcome."""
        if type(barrier_id) is not UUID or barrier_id.int == 0:
            raise ServiceError("BARRIER_REQUEST_INVALID")
        try:
            snapshot = await self._store.lookup_barrier(barrier_id)
        except Exception as exc:
            raise self._store_failure(exc, "BARRIER_LOOKUP_UNAVAILABLE") from None
        if snapshot is None:
            return None
        if (not self._barrier_snapshot_valid(
                snapshot, snapshot.scope, self._base_fingerprint, snapshot.epoch, barrier_id)):
            raise ServiceError("BARRIER_SNAPSHOT_INVALID")
        return snapshot

    @staticmethod
    def _barrier_snapshot_valid(snapshot: Any, scope: Scope, base_fingerprint: str,
                                epoch: int, barrier_id: UUID) -> bool:
        if (type(snapshot) is not BarrierSnapshot or snapshot.scope != scope
                or type(snapshot.barrier_id) is not UUID or snapshot.barrier_id.int == 0
                or snapshot.base_fingerprint != base_fingerprint
                or snapshot.barrier_id != barrier_id or snapshot.epoch != epoch
                or type(snapshot.expected_current_epoch) is not int
                or snapshot.expected_current_epoch < 0
                or snapshot.epoch != snapshot.expected_current_epoch + 1
                or type(snapshot.epoch) is not int
                or type(snapshot.barrier_origin_instance_id) is not str
                or not snapshot.barrier_origin_instance_id
                or type(snapshot.barrier_origin_service_epoch) is not int
                or snapshot.barrier_origin_service_epoch < 1
                or type(snapshot.progress) is not BarrierProgress
                or (snapshot.acknowledgement_ref is not None
                    and (type(snapshot.acknowledgement_ref) is not str
                         or not snapshot.acknowledgement_ref
                         or snapshot.acknowledgement_ref != snapshot.acknowledgement_ref.strip()))
                or (snapshot.acknowledgement_digest is not None
                    and (type(snapshot.acknowledgement_digest) is not bytes
                         or len(snapshot.acknowledgement_digest) != 32))
                or (snapshot.quiesced_at is not None
                    and (type(snapshot.quiesced_at) is not datetime
                         or snapshot.quiesced_at.tzinfo is None
                         or snapshot.quiesced_at.utcoffset() is None))
                or type(snapshot.call_ids) is not tuple
                or type(snapshot.unresolved_call_ids) is not tuple
                or any(type(call_id) is not str or not call_id for call_id in snapshot.call_ids)
                or any(type(call_id) is not str or not call_id
                       for call_id in snapshot.unresolved_call_ids)
                or len(set(snapshot.call_ids)) != len(snapshot.call_ids)
                or len(set(snapshot.unresolved_call_ids)) != len(snapshot.unresolved_call_ids)
                or not set(snapshot.unresolved_call_ids).issubset(snapshot.call_ids)):
            return False
        try:
            if any((parsed := UUID(call_id)).int == 0 or str(parsed) != call_id
                   for call_id in snapshot.call_ids):
                return False
            if not _is_canonical_process_instance_id(snapshot.barrier_origin_instance_id):
                return False
        except (ValueError, TypeError, AttributeError):
            return False
        if snapshot.call_ids != tuple(sorted(snapshot.call_ids)):
            return False
        unresolved_set = set(snapshot.unresolved_call_ids)
        ordered_unresolved = tuple(
            call_id for call_id in snapshot.call_ids if call_id in unresolved_set
        )
        if ordered_unresolved != snapshot.unresolved_call_ids:
            return False
        if snapshot.progress is BarrierProgress.QUIESCED:
            return (not snapshot.unresolved_call_ids
                    and type(snapshot.acknowledgement_ref) is str
                    and type(snapshot.acknowledgement_digest) is bytes
                    and len(snapshot.acknowledgement_digest) == 32
                    and type(snapshot.quiesced_at) is datetime
                    and snapshot.quiesced_at.tzinfo is not None
                    and snapshot.quiesced_at.utcoffset() is not None)
        return (snapshot.progress is BarrierProgress.CLOSED_WITH_HOLD
                and snapshot.acknowledgement_ref is None
                and snapshot.acknowledgement_digest is None
                and snapshot.quiesced_at is None)

    async def _bounded_barrier_call(self, call: Callable[[], Awaitable[Any]],
                                    deadline: float) -> Any:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            return await call()

    async def _quiesce_under_authority(self, mutex: ServingAuthorityMutex,
                                       call: Callable[[ServingAuthorityLease],
                                                      Awaitable[BarrierAcknowledgement]
                                                      ]) -> BarrierAcknowledgement:
        """Own a non-queued host lease in the retained task until queue closure completes."""
        try:
            lease = await mutex.try_acquire()
        except BaseException:
            # A concrete mutex may acquire OS ownership and then fail while constructing
            # or unwinding its lease; the caller cannot prove the host is still available.
            await self._latch_restart_required()
            raise
        if lease is None:
            raise ServiceError("SERVING_AUTHORITY_BUSY", outcome_unknown=True)
        try:
            lease.assert_held()
            acknowledgement = await call(lease)
        except BaseException:
            # A raised/cancelled port awaitable does not prove that underlying COM
            # queue closure has stopped. Keep the OS mutex owned until process exit.
            await self._latch_restart_required()
            raise
        else:
            try:
                await lease.release()
            except BaseException:
                # A failed unlock leaves host authority uncertain even when the port
                # returned normally; require process replacement before serving again.
                await self._latch_restart_required()
                raise
            return acknowledgement

    async def _bounded_quiesce_wait(self, task: asyncio.Task[BarrierAcknowledgement],
                                    deadline: float) -> BarrierAcknowledgement:
        """Bound the request wait without cancelling queue closure or releasing its mutex."""
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            return await asyncio.shield(task)

    def _authority_task_done(self, barrier_id: UUID, task: asyncio.Task[Any]) -> None:
        """Release the single in-process quiesce slot only after its authority lease ends."""
        if self._active_quiesce == (barrier_id, task):
            self._set_lifecycle_field("_active_quiesce", None)
        # Retrieve an eventual exception if the initiating request already timed out/cancelled.
        if not task.cancelled():
            task.exception()

    def _dispatch_task_done(self, task: asyncio.Task[Any]) -> None:
        """Clear the retained dispatch only after its physical/evidence task is terminal."""
        if self._active_dispatch is task:
            self._set_lifecycle_field("_active_dispatch", None)
            self._active_dispatch_done.set()

    def _begin_control_operation(self) -> None:
        """Atomically admit lifecycle work before its first suspension point."""
        if self._shutdown_started:
            raise ServiceError("WRITER_SHUTTING_DOWN")
        self._set_lifecycle_field(
            "_active_control_operations", self._active_control_operations + 1,
        )
        self._control_operations_done.clear()

    def _end_control_operation(self) -> None:
        """Release the accepted startup-recovery or barrier operation count."""
        remaining = self._active_control_operations - 1
        self._set_lifecycle_field("_active_control_operations", remaining)
        if remaining == 0:
            self._control_operations_done.set()

    async def dispatch(self, ticket: ApplyTicket, permit: DispatchPermit,
                       payload: dict[str, Any]) -> CallSnapshot:
        """Serialize one physical call against local work, barriers, and process takeover.

        The host-wide serving-authority lease spans the complete admitted operation. Startup
        recovery and quiescence acquire the same mutex, so neither can advance process authority
        while this process may still be inside its COM writer. Cancellation of the requesting
        coroutine does not cancel the accepted operation or release that lease early.
        """
        if self._shutdown_started:
            raise ServiceError("WRITER_SHUTTING_DOWN")
        # A requester may have been cancelled while its shielded dispatch continues. In
        # that case the local lock is released but _active_dispatch still owns the physical
        # authority lease; refuse before trying the OS mutex or starting another admission.
        if self._active_dispatch is not None or self._base_dispatch_lock.locked():
            raise ServiceError("WRITER_BUSY")
        # There is no suspension between the unlocked check and acquire's fast path, so
        # same-loop callers cannot both pass the check. The OS mutex serializes this physical
        # base against other processes; the database CAS still owns stable call-ID admission.
        await self._base_dispatch_lock.acquire()
        lease: ServingAuthorityLease | None = None
        dispatch_task: asyncio.Task[CallSnapshot] | None = None
        retained_for_callback = False
        try:
            if self._shutdown_started:
                raise ServiceError("WRITER_SHUTTING_DOWN")
            mutex = self._serving_authority_mutex
            if mutex is None:
                raise ServiceError("SERVING_AUTHORITY_MUTEX_UNAVAILABLE")
            try:
                lease = await mutex.try_acquire()
            except asyncio.CancelledError:
                # The actor request may still acquire on its owner thread after this task is
                # cancelled; retain fail-stop state until process replacement.
                await self._latch_restart_required()
                raise
            except Exception:
                await self._latch_restart_required()
                raise ServiceError("SERVING_AUTHORITY_UNAVAILABLE") from None
            if lease is None:
                raise ServiceError("SERVING_AUTHORITY_BUSY")
            try:
                lease.assert_held()
            except Exception:
                await self._latch_restart_required()
                raise ServiceError("SERVING_AUTHORITY_UNAVAILABLE") from None

            task = asyncio.create_task(self._dispatch_once(ticket, permit, payload))
            dispatch_task = task
            self._set_lifecycle_field("_active_dispatch", task)
            self._active_dispatch_done.clear()
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # A cancelled request must not release physical authority while an accepted
                # COM call is still running. Keep the lease until the full admission/evidence
                # path completes; if the task itself is cancelled during loop shutdown, do not
                # call ReleaseMutex and fail-stop this service. The mutex's dedicated owner thread
                # keeps kernel ownership independent of the event-loop thread; runtime shutdown
                # must still close this authority object only after the COM STA has drained.
                retained_lease = lease
                lease = None
                retained_for_callback = True

                async def release_after_dispatch(
                        completed: asyncio.Task[CallSnapshot]) -> None:
                    if completed.cancelled():
                        object.__setattr__(self, "_restart_required", True)
                        object.__setattr__(self, "_startup_complete", False)
                        self._dispatch_task_done(completed)
                        return
                    # Consume any eventual exception because the caller already received an
                    # indeterminate outcome when it cancelled.
                    completed.exception()
                    try:
                        await retained_lease.release()
                    except BaseException:
                        # If release fails, the kernel mutex remains the final fence. The
                        # process-local latch prevents this instance from accepting new work.
                        object.__setattr__(self, "_restart_required", True)
                        object.__setattr__(self, "_startup_complete", False)
                    finally:
                        self._dispatch_task_done(completed)

                task.add_done_callback(
                    lambda completed: asyncio.create_task(release_after_dispatch(completed))
                )
                raise ServiceError("WRITER_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        finally:
            release_failed = False
            try:
                if lease is not None:
                    try:
                        await lease.release()
                    except asyncio.CancelledError:
                        await self._latch_restart_required()
                        raise
                    except Exception:
                        release_failed = True
                        await self._latch_restart_required()
            finally:
                if dispatch_task is not None and not retained_for_callback:
                    self._dispatch_task_done(dispatch_task)
                self._base_dispatch_lock.release()
            if release_failed:
                raise ServiceError("SERVING_AUTHORITY_RELEASE_FAILED",
                                   outcome_unknown=True) from None

    async def _dispatch_once(self, ticket: ApplyTicket, permit: DispatchPermit,
                             payload: dict[str, Any]) -> CallSnapshot:
        """Admit once, mark invocation before I/O, and leave uncertainty unresolved without retry."""
        if self._writer_receipt_verifier is None or self._outcome_evidence_provider is None:
            raise ServiceError("WRITER_EVIDENCE_VERIFIER_UNAVAILABLE")
        service_epoch = self._service_epoch
        if not self.ready or service_epoch is None:
            raise ServiceError("STARTUP_RECOVERY_REQUIRED")
        identity = self._identity(ticket, permit)
        if type(payload) is not dict:
            raise ServiceError("PAYLOAD_INVALID")
        try:
            writer_model = parse_writer_payload(
                payload,
                ChangeKind(identity.operation),
                ProposalScope(identity.tenant_id, identity.company_id,
                              identity.organization_ref, identity.base_fingerprint),
            )
            if type(writer_model) is Refusal:
                raise ServiceError("PAYLOAD_INVALID")
            if payload_digest(writer_model, identity.target_version) != identity.payload_digest:
                raise ServiceError("PAYLOAD_DIGEST_MISMATCH")
            writer_payload = payload_to_dict(writer_model)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("PAYLOAD_INVALID") from None
        try:
            async with asyncio.timeout(_WRITER_PRECHECK_TIMEOUT_SECONDS):
                await self._writer.verify_ticket(ticket)
                await self._writer.verify_permit(ticket, permit)
                actual_fingerprint = await self._writer.authenticate_base(ticket)
        except TimeoutError:
            raise ServiceError("WRITER_PRECHECK_TIMEOUT") from None
        except Exception:
            raise ServiceError("WRITER_PRECHECK_FAILED") from None
        if actual_fingerprint != identity.base_fingerprint:
            raise ServiceError("BASE_FINGERPRINT_MISMATCH")

        try:
            decision = await self._store.admit(
                identity, self._service_instance_id, service_epoch,
            )
        except Exception as exc:
            raise self._store_failure(exc, "ADMISSION_UNAVAILABLE") from None
        if (type(decision) is not AdmissionDecision or decision.identity != identity
                or type(decision.state) is not AdmissionState
                or type(decision.newly_admitted) is not bool):
            raise ServiceError("ADMISSION_RESPONSE_INVALID")
        if decision.state is AdmissionState.NOT_ACCEPTED:
            if (type(decision.refusal_code) is not AdmissionRefusal
                    or decision.newly_admitted is not False
                    or decision.dispatch_cas_id is not None
                    or decision.owner_instance_id is not None
                    or decision.evidence_ref is not None):
                raise ServiceError("ADMISSION_RESPONSE_INVALID")
            # The store contract exposes a decision code, not a PostgreSQL SQLSTATE.
            raise ServiceError(decision.refusal_code.value)
        if (decision.state not in {
                    AdmissionState.ACCEPTED_NOT_INVOKED,
                    AdmissionState.POSSIBLY_EXECUTING,
                    AdmissionState.TERMINAL_WITH_EVIDENCE,
                }
                or decision.refusal_code is not None
                or type(decision.dispatch_cas_id) is not UUID
                or decision.dispatch_cas_id.int == 0):
            raise ServiceError("ADMISSION_RESPONSE_INVALID")
        if (not _is_canonical_process_instance_id(decision.owner_instance_id)
                or (decision.evidence_ref is not None
                    and (type(decision.evidence_ref) is not str or not decision.evidence_ref
                         or decision.evidence_ref != decision.evidence_ref.strip()))
                or (decision.state is AdmissionState.TERMINAL_WITH_EVIDENCE
                    and decision.evidence_ref is None)
                or (decision.newly_admitted
                    and (decision.state is not AdmissionState.ACCEPTED_NOT_INVOKED
                         or decision.owner_instance_id != self._service_instance_id
                         or decision.evidence_ref is not None))):
            raise ServiceError("ADMISSION_RESPONSE_INVALID")
        if (decision.state is not AdmissionState.ACCEPTED_NOT_INVOKED
                or decision.newly_admitted is not True
                or decision.owner_instance_id != self._service_instance_id):
            return await self._lookup_admitted_call(ticket, permit, decision.dispatch_cas_id)

        # The store returns newly_admitted=True only to the transaction that inserted this call.
        # Existing identical admissions retain their original owner and are lookup-only.
        try:
            invocation_started = await self._store.mark_invoking(
                identity, decision.dispatch_cas_id, self._service_instance_id,
                service_epoch,
            )
        except asyncio.CancelledError:
            raise ServiceError("INVOCATION_STAGE_UNKNOWN", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "INVOCATION_STAGE_UNKNOWN") from None
        except Exception:
            raise ServiceError("INVOCATION_STAGE_UNKNOWN", outcome_unknown=True) from None
        if invocation_started is False:
            return await self._lookup_admitted_call(ticket, permit, decision.dispatch_cas_id)
        if invocation_started is not True:
            raise ServiceError("INVOCATION_STAGE_UNKNOWN", outcome_unknown=True)

        try:
            entry_callback_lock = asyncio.Lock()
            entry_callback_used = False

            async def authorize_com_entry() -> bool:
                nonlocal entry_callback_used
                async with entry_callback_lock:
                    if entry_callback_used:
                        return False
                    # Claim locally before I/O. An uncertain/lost DB response must not trigger a
                    # second guard attempt or accidentally authorize a second COM entry.
                    entry_callback_used = True
                try:
                    value = await self._store.begin_com_entry(
                        identity, decision.dispatch_cas_id, self._service_instance_id, service_epoch,
                    )
                except asyncio.CancelledError:
                    raise ServiceError("COM_ENTRY_GUARD_UNKNOWN", outcome_unknown=True) from None
                except AdmissionStoreError as exc:
                    raise self._store_failure(exc, "COM_ENTRY_GUARD_UNKNOWN") from None
                except Exception:
                    raise ServiceError("COM_ENTRY_GUARD_UNKNOWN", outcome_unknown=True) from None
                if type(value) is not bool:
                    raise ServiceError("COM_ENTRY_GUARD_UNKNOWN", outcome_unknown=True)
                return value

            context = InvocationContext(
                dispatch_cas_id=decision.dispatch_cas_id,
                service_instance_id=self._service_instance_id,
                service_epoch=service_epoch,
                host_id=self._host_id,
                base_fingerprint=identity.base_fingerprint,
                tenant_id=identity.tenant_id,
                company_id=identity.company_id,
                organization_ref=identity.organization_ref,
                change_id=identity.change_id,
                generation=identity.generation,
                call_id=identity.call_id,
                operation=identity.operation,
                target_ref=identity.target_ref,
                expected_pre_version=identity.target_version,
                authority_epoch=identity.epoch,
                permit_id=identity.permit_id,
                permit_digest=identity.permit_digest,
                digest_set_hash=ticket.digest_set_hash,
                approved_payload_digest=identity.payload_digest,
                repair_authorization_id=identity.repair_authorization_id,
                authorize_com_entry=authorize_com_entry,
            )
            context.require_matches(
                ticket, permit, service_instance_id=self._service_instance_id,
                host_id=self._host_id, base_fingerprint=self._base_fingerprint,
            )
            writer_method = getattr(self._writer, self._WRITER_METHODS[identity.operation])
        except Exception:
            raise ServiceError("WRITER_CONTEXT_INVALID") from None
        try:
            result = (await writer_method(ticket, permit, context, writer_payload)
                      if identity.operation == "CREATE_DRAFT"
                      else await writer_method(ticket, permit, context))
        except asyncio.CancelledError:
            raise ServiceError("WRITER_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        except ServiceError:
            # Admission and invocation-stage CAS have already committed. A port-level
            # ServiceError is not signed no-effect evidence and cannot downgrade uncertainty.
            raise ServiceError("WRITER_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        except Exception:
            raise ServiceError("WRITER_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        if type(result) is not bytes or not result:
            raise ServiceError("WRITER_OUTCOME_UNKNOWN", outcome_unknown=True)
        try:
            receipt_ref = await self._writer_receipt_verifier.verify_and_store(
                identity, decision.dispatch_cas_id, self._service_instance_id, result,
            )
        except asyncio.CancelledError:
            raise ServiceError("WRITER_RECEIPT_UNKNOWN", outcome_unknown=True) from None
        except Exception:
            raise ServiceError("WRITER_RECEIPT_UNKNOWN", outcome_unknown=True) from None
        if type(receipt_ref) is not str or not receipt_ref:
            raise ServiceError("WRITER_RECEIPT_UNKNOWN", outcome_unknown=True)
        try:
            receipt_ref = await self._store.record_terminal(
                identity, decision.dispatch_cas_id, self._service_instance_id, receipt_ref,
            )
        except asyncio.CancelledError:
            raise ServiceError("OUTCOME_PERSISTENCE_UNKNOWN", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "OUTCOME_PERSISTENCE_UNKNOWN") from None
        except Exception:
            raise ServiceError("OUTCOME_PERSISTENCE_UNKNOWN", outcome_unknown=True) from None
        if type(receipt_ref) is not str or not receipt_ref:
            raise ServiceError("OUTCOME_PERSISTENCE_UNKNOWN", outcome_unknown=True)
        disposition, receipt_records = await self._verified_receipt_disposition(
            identity, decision.dispatch_cas_id, receipt_ref,
        )
        if disposition is ReceiptDisposition.PRE_WRITE_NO_EFFECT:
            return await self._terminalize_recovered_no_effect(
                ticket, permit, identity, decision.dispatch_cas_id, receipt_ref,
                require_startup_inventory=False,
            )
        if disposition is ReceiptDisposition.ENTERED_CONDITIONAL_VERSION_CONFLICT:
            return await self._terminalize_entered_conflict(
                ticket, permit, identity, decision.dispatch_cas_id, receipt_ref,
                require_startup_inventory=False,
            )
        if disposition is not ReceiptDisposition.SUCCESS or receipt_records is None:
            raise ServiceError("WRITER_OUTCOME_UNKNOWN", outcome_unknown=True)
        try:
            verified = await self._outcome_evidence_provider.verify_success(
                identity, decision.dispatch_cas_id, receipt_ref,
            )
        except asyncio.CancelledError:
            raise ServiceError("OUTCOME_VERIFICATION_UNKNOWN", outcome_unknown=True) from None
        except Exception:
            raise ServiceError("OUTCOME_VERIFICATION_UNKNOWN", outcome_unknown=True) from None
        if (type(verified) is not SuccessfulOutcomeEvidence
                or type(verified.outcome_evidence_ref) is not str
                or not verified.outcome_evidence_ref
                or type(verified.completion_proof_ref) is not str
                or not verified.completion_proof_ref):
            raise ServiceError("OUTCOME_VERIFICATION_INVALID", outcome_unknown=True)
        try:
            await self._run_active_terminal_mutation(
                identity, decision.dispatch_cas_id,
                lambda active_instance_id, active_epoch:
                    self._store.record_verified_success(
                        identity, decision.dispatch_cas_id, active_instance_id, active_epoch,
                        receipt_ref, verified.outcome_evidence_ref,
                        verified.completion_proof_ref,
                    ),
            )
        except asyncio.CancelledError:
            raise ServiceError("OUTCOME_TERMINALIZATION_UNKNOWN", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "OUTCOME_TERMINALIZATION_UNKNOWN") from None
        except Exception:
            raise ServiceError("OUTCOME_TERMINALIZATION_UNKNOWN", outcome_unknown=True) from None
        try:
            return await self._lookup_admitted_call(ticket, permit, decision.dispatch_cas_id)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("OUTCOME_LOOKUP_UNAVAILABLE", outcome_unknown=True) from None

    @staticmethod
    def _receipt_identity_matches(identity: CallIdentity, dispatch_cas_id: UUID,
                                  records: ResolvedReceiptEvidence) -> bool:
        attempt = records.attempt
        receipt = records.receipt
        expected_scope = EvidenceScope(
            identity.tenant_id, identity.company_id, identity.organization_ref,
            identity.base_fingerprint,
        )
        return (
            type(records) is ResolvedReceiptEvidence
            and type(attempt) is DispatchAttempt
            and type(records.receipt) is DispatchReceipt
            and type(records.verified_receipt) is VerifiedEvidenceRecord
            and records.verified_receipt.record is records.receipt
            and type(records.expected_scope) is EvidenceScope
            and records.expected_scope == expected_scope
            and attempt.tenant_id == identity.tenant_id
            and attempt.company_id == identity.company_id
            and attempt.organization_ref == identity.organization_ref
            and attempt.base_fingerprint == identity.base_fingerprint
            and attempt.change_id == identity.change_id
            and attempt.claim_generation == identity.generation
            and attempt.dispatch_cas_id == str(dispatch_cas_id)
            and attempt.call_id == identity.call_id
            and attempt.operation_kind == identity.operation
            and attempt.auth_epoch == identity.epoch
            and attempt.permit_id == identity.permit_id
            and attempt.permit_digest == identity.permit_digest
            and attempt.expected_target_ref == identity.target_ref
            and attempt.expected_pre_version == identity.target_version
            and attempt.writer_host_id == identity.host_id
            and receipt.tenant_id == identity.tenant_id
            and receipt.company_id == identity.company_id
            and receipt.organization_ref == identity.organization_ref
            and receipt.base_fingerprint == identity.base_fingerprint
            and receipt.change_id == identity.change_id
            and receipt.claim_generation == identity.generation
            and receipt.dispatch_cas_id == str(dispatch_cas_id)
            and receipt.call_id == identity.call_id
            and receipt.operation_kind == identity.operation
            and receipt.approved_payload_digest == identity.payload_digest
            and receipt.auth_epoch == identity.epoch
            and receipt.permit_id == identity.permit_id
            and receipt.permit_digest == identity.permit_digest
            and receipt.expected_target_ref == identity.target_ref
            and receipt.expected_pre_version == identity.target_version
            and receipt.writer_host_id == identity.host_id
            and receipt.result_class in {
                "CALL_RETURNED_SUCCESS", "PRE_WRITE_NO_EFFECT",
                "CONDITIONAL_VERSION_CONFLICT",
            }
        )

    async def _verified_receipt_disposition(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str) -> tuple[ReceiptDisposition, ResolvedReceiptEvidence | None]:
        resolver = self._writer_evidence_resolver
        if resolver is None:
            return ReceiptDisposition.UNKNOWN, None
        try:
            records = await resolver.load_receipt(identity, dispatch_cas_id, receipt_ref)
            if not self._receipt_identity_matches(identity, dispatch_cas_id, records):
                return ReceiptDisposition.UNKNOWN, None
        except asyncio.CancelledError:
            raise ServiceError("WRITER_RECEIPT_UNKNOWN", outcome_unknown=True) from None
        except Exception:
            return ReceiptDisposition.UNKNOWN, None
        receipt = records.receipt
        if (receipt.result_class == "CALL_RETURNED_SUCCESS"
                and receipt.write_invocation_stage in ("ENTERED", "INVOKED")
                and receipt.call_returned):
            return ReceiptDisposition.SUCCESS, records
        if (receipt.result_class == "PRE_WRITE_NO_EFFECT"
                and receipt.write_invocation_stage == "NOT_INVOKED"
                and not receipt.call_returned):
            return ReceiptDisposition.PRE_WRITE_NO_EFFECT, records
        if (receipt.result_class == "CONDITIONAL_VERSION_CONFLICT"
                and receipt.write_invocation_stage == "ENTERED" and receipt.call_returned):
            return ReceiptDisposition.ENTERED_CONDITIONAL_VERSION_CONFLICT, records
        return ReceiptDisposition.UNKNOWN, None

    async def _terminalize_recovered_no_effect(
            self, ticket: ApplyTicket, permit: DispatchPermit, identity: CallIdentity,
            dispatch_cas_id: UUID, receipt_ref: str, *,
            require_startup_inventory: bool = True) -> CallSnapshot:
        authorized = (
            self._recovery_transition_authorized(identity, dispatch_cas_id)
            if require_startup_inventory
            else self._active_transition_authorized(identity, dispatch_cas_id)
        )
        if not authorized:
            raise ServiceError("STARTUP_RECOVERY_REQUIRED")
        try:
            await self._run_active_terminal_mutation(
                identity, dispatch_cas_id,
                lambda active_instance_id, active_epoch:
                    self._store.record_recovered_not_invoked(
                        identity, dispatch_cas_id, active_instance_id, active_epoch, receipt_ref,
                    ),
                require_startup_inventory=require_startup_inventory,
            )
            return await self._lookup_admitted_call(ticket, permit, dispatch_cas_id)
        except asyncio.CancelledError:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "RECOVERY_TERMINALIZATION_UNAVAILABLE") from None
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None

    async def _terminalize_entered_conflict(
            self, ticket: ApplyTicket, permit: DispatchPermit, identity: CallIdentity,
            dispatch_cas_id: UUID, receipt_ref: str, *,
            require_startup_inventory: bool = True) -> CallSnapshot:
        provider = self._outcome_evidence_provider
        resolver = self._writer_evidence_resolver
        authorized = (
            self._recovery_transition_authorized(identity, dispatch_cas_id)
            if require_startup_inventory
            else self._active_transition_authorized(identity, dispatch_cas_id)
        )
        if provider is None or resolver is None or not authorized:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True)
        try:
            refs = await provider.verify_conditional_conflict(
                identity, dispatch_cas_id, receipt_ref,
            )
            if type(refs) is not ConditionalConflictEvidenceRefs:
                raise ValueError("CONFLICT_EVIDENCE_INVALID")
            records = await resolver.load_conditional_conflict_terminal_records(
                identity, dispatch_cas_id, receipt_ref, refs.outcome_evidence_ref,
                refs.completion_proof_ref, refs.post_completion_challenge_ref,
                refs.read_attestation_ref,
            )
            resolved_receipt = ResolvedReceiptEvidence(
                records.attempt, records.receipt,
                records.verified_records[0] if type(records.verified_records) is tuple
                and len(records.verified_records) == 5 else None,
                records.expected_scope,
            )
            if (type(records) is not ConditionalConflictTerminalRecords
                    or type(records.outcome) is not OutcomeEvidenceV3
                    or type(records.completion) is not CompletionProof
                    or type(records.post_completion_challenge) is not PostCompletionChallenge
                    or type(records.read_attestation) is not PostCompletionReadAttestation
                    or type(records.verified_records) is not tuple
                    or len(records.verified_records) != 5
                    or any(type(value) is not VerifiedEvidenceRecord
                           for value in records.verified_records)
                    or any(value.record is not record for value, record in zip(
                        records.verified_records,
                        (records.receipt, records.outcome, records.completion,
                         records.post_completion_challenge, records.read_attestation),
                        strict=True,
                    ))
                    or not self._receipt_identity_matches(
                        identity, dispatch_cas_id, resolved_receipt,
                    )
                    or records.receipt.result_class != "CONDITIONAL_VERSION_CONFLICT"
                    or records.receipt.write_invocation_stage != "ENTERED"
                    or not records.receipt.call_returned):
                raise ValueError("CONFLICT_RECORD_SET_INVALID")
            validate_conditional_conflict_terminal_evidence(
                records.attempt, records.receipt, records.outcome, records.completion,
                records.post_completion_challenge, records.read_attestation,
            )
            self._pending_t16_resolution_calls[(identity, dispatch_cas_id)] = refs
            # T16 is an independently authenticated operator-plus-witness action. The
            # private-writer service cannot manufacture that authority or release its own
            # safety hold on a structural no-effect claim alone.
            raise ServiceError("T16_RESOLUTION_REQUIRED", outcome_unknown=True)
        except asyncio.CancelledError:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "RECOVERY_TERMINALIZATION_UNAVAILABLE") from None
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None

    async def prepare_t16_resolution(
            self, ticket: ApplyTicket, permit: DispatchPermit, *,
            require_startup_inventory: bool = True) -> T16ResolutionPreparation:
        """Return refs only after validating the exact entered-conflict proof set.

        This prepares evidence for the separately authorized operator/witness T16 action. It does
        not call T16, checkpoint anything, release a hold, or terminalize the physical call.
        """
        if type(require_startup_inventory) is not bool:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED")
        identity = self._identity(ticket, permit)
        try:
            current = await self.lookup(ticket, permit)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_LOOKUP_UNAVAILABLE", outcome_unknown=True) from None
        if (current.state is not AdmissionState.POSSIBLY_EXECUTING
                or type(current.dispatch_cas_id) is not UUID
                or current.dispatch_cas_id.int == 0
                or type(current.evidence_ref) is not str or not current.evidence_ref):
            raise ServiceError("RECOVERY_STATE_CONFLICT")

        key = (identity, current.dispatch_cas_id)
        refs = self._pending_t16_resolution_calls.get(key)
        if refs is None:
            try:
                await self._terminalize_entered_conflict(
                    ticket, permit, identity, current.dispatch_cas_id, current.evidence_ref,
                    require_startup_inventory=require_startup_inventory,
                )
            except ServiceError as exc:
                if exc.code != "T16_RESOLUTION_REQUIRED":
                    raise
            refs = self._pending_t16_resolution_calls.get(key)
        if type(refs) is not ConditionalConflictEvidenceRefs:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True)
        return T16ResolutionPreparation(
            identity, current.dispatch_cas_id, current.evidence_ref, refs,
        )

    async def reconcile_recovered_success(self, ticket: ApplyTicket,
                                          permit: DispatchPermit) -> CallSnapshot:
        """Finalize a stored successful orphan without dispatching COM a second time."""
        identity = self._identity(ticket, permit)
        try:
            current = await self.lookup(ticket, permit)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_LOOKUP_UNAVAILABLE", outcome_unknown=True) from None
        if (current.state is not AdmissionState.POSSIBLY_EXECUTING
                or type(current.dispatch_cas_id) is not UUID
                or current.dispatch_cas_id.int == 0):
            raise ServiceError("RECOVERY_STATE_CONFLICT")
        if (not _is_canonical_process_instance_id(current.owner_instance_id)
                or type(self._service_epoch) is not int or self._service_epoch < 1):
            raise ServiceError("RECOVERY_OWNER_IDENTITY_UNAVAILABLE", outcome_unknown=True)
        receipt_ref = current.evidence_ref
        if receipt_ref is None:
            verifier = self._writer_receipt_verifier
            if verifier is None:
                raise ServiceError("WRITER_RECEIPT_LOOKUP_UNAVAILABLE", outcome_unknown=True)
            lookup_key = ReceiptLookupKey(
                dispatch_cas_id=current.dispatch_cas_id,
                base_fingerprint=identity.base_fingerprint,
                tenant_id=identity.tenant_id,
                company_id=identity.company_id,
                organization_ref=identity.organization_ref,
                change_id=identity.change_id,
                generation=identity.generation,
                call_id=identity.call_id,
                operation=identity.operation,
                target_ref=identity.target_ref,
                expected_pre_version=identity.target_version,
                authority_epoch=identity.epoch,
                permit_id=identity.permit_id,
                permit_digest=identity.permit_digest,
                approved_payload_digest=identity.payload_digest,
                host_id=identity.host_id,
                repair_authorization_id=identity.repair_authorization_id,
            )
            try:
                recovered = await self._writer.lookup_receipt(lookup_key)
            except asyncio.CancelledError:
                raise ServiceError("WRITER_RECEIPT_LOOKUP_UNKNOWN", outcome_unknown=True) from None
            except Exception:
                raise ServiceError("WRITER_RECEIPT_LOOKUP_UNKNOWN", outcome_unknown=True) from None
            if (type(recovered) is not ReceiptLookupResult
                    or recovered.state is not ReceiptLookupState.RECEIPT_AVAILABLE
                    or type(recovered.receipt_envelope) is not bytes
                    or not recovered.receipt_envelope):
                raise ServiceError("WRITER_RECEIPT_LOOKUP_UNRESOLVED", outcome_unknown=True)
            try:
                receipt_ref = await verifier.verify_and_store(
                    identity, current.dispatch_cas_id, current.owner_instance_id,
                    recovered.receipt_envelope,
                )
                if type(receipt_ref) is not str or not receipt_ref:
                    raise ValueError("RECEIPT_REFERENCE_INVALID")
                receipt_ref = await self._run_active_terminal_mutation(
                    identity, current.dispatch_cas_id,
                    lambda active_instance_id, active_epoch:
                        self._store.attach_recovered_receipt(
                            identity, current.dispatch_cas_id, active_instance_id,
                            active_epoch, current.owner_instance_id, receipt_ref,
                        ),
                    require_startup_inventory=True,
                )
            except asyncio.CancelledError:
                raise ServiceError("RECOVERY_RECEIPT_PERSISTENCE_UNKNOWN", outcome_unknown=True) from None
            except AdmissionStoreError as exc:
                raise self._store_failure(exc, "RECOVERY_RECEIPT_PERSISTENCE_UNKNOWN") from None
            except ServiceError:
                raise
            except Exception:
                raise ServiceError("RECOVERY_RECEIPT_REJECTED", outcome_unknown=True) from None
            if type(receipt_ref) is not str or not receipt_ref:
                raise ServiceError("RECOVERY_RECEIPT_PERSISTENCE_UNKNOWN", outcome_unknown=True)
        if type(receipt_ref) is not str or not receipt_ref:
            raise ServiceError("RECOVERY_STATE_CONFLICT")
        disposition, _ = await self._verified_receipt_disposition(
            identity, current.dispatch_cas_id, receipt_ref,
        )
        if disposition is not ReceiptDisposition.SUCCESS:
            if disposition is ReceiptDisposition.PRE_WRITE_NO_EFFECT:
                return await self._terminalize_recovered_no_effect(
                    ticket, permit, identity, current.dispatch_cas_id, receipt_ref,
                    require_startup_inventory=True,
                )
            if disposition is ReceiptDisposition.ENTERED_CONDITIONAL_VERSION_CONFLICT:
                return await self._terminalize_entered_conflict(
                    ticket, permit, identity, current.dispatch_cas_id, receipt_ref,
                    require_startup_inventory=True,
                )
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True)
        provider = self._outcome_evidence_provider
        if provider is None:
            raise ServiceError("OUTCOME_VERIFICATION_UNAVAILABLE", outcome_unknown=True)
        try:
            verified = await provider.verify_success(
                identity, current.dispatch_cas_id, receipt_ref,
            )
            if (type(verified) is not SuccessfulOutcomeEvidence
                    or type(verified.outcome_evidence_ref) is not str
                    or not verified.outcome_evidence_ref
                    or type(verified.completion_proof_ref) is not str
                    or not verified.completion_proof_ref):
                raise ValueError("OUTCOME_VERIFICATION_INVALID")
            await self._run_active_terminal_mutation(
                identity, current.dispatch_cas_id,
                lambda active_instance_id, active_epoch:
                    self._store.record_verified_success(
                        identity, current.dispatch_cas_id, active_instance_id, active_epoch,
                        receipt_ref, verified.outcome_evidence_ref,
                        verified.completion_proof_ref,
                    ),
                require_startup_inventory=True,
            )
            return await self._lookup_admitted_call(
                ticket, permit, current.dispatch_cas_id,
            )
        except asyncio.CancelledError:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "OUTCOME_TERMINALIZATION_UNKNOWN") from None
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None

    async def record_recovered_not_invoked(self, ticket: ApplyTicket, permit: DispatchPermit,
                                           no_effect_receipt_ref: str) -> CallSnapshot:
        """Resolve a non-entry orphan only from a durable one-way S12 physical guard."""
        identity = self._identity(ticket, permit)
        if type(no_effect_receipt_ref) is not str or not no_effect_receipt_ref:
            raise ServiceError("RECOVERY_EVIDENCE_INVALID")
        try:
            current = await self.lookup(ticket, permit)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_LOOKUP_UNAVAILABLE", outcome_unknown=True) from None
        if (current.state not in (AdmissionState.ACCEPTED_NOT_INVOKED,
                                  AdmissionState.POSSIBLY_EXECUTING)
                or type(current.dispatch_cas_id) is not UUID
                or current.dispatch_cas_id.int == 0):
            raise ServiceError("RECOVERY_STATE_CONFLICT")
        if not self._recovery_transition_authorized(identity, current.dispatch_cas_id):
            raise ServiceError("STARTUP_RECOVERY_REQUIRED")
        try:
            evidence_ref = await self._run_active_terminal_mutation(
                identity, current.dispatch_cas_id,
                lambda active_instance_id, active_epoch:
                    self._store.record_recovered_not_invoked(
                        identity, current.dispatch_cas_id, active_instance_id, active_epoch,
                        no_effect_receipt_ref,
                    ),
                require_startup_inventory=True,
            )
        except asyncio.CancelledError:
            raise ServiceError("RECOVERY_TERMINALIZATION_UNKNOWN", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "RECOVERY_TERMINALIZATION_UNAVAILABLE") from None
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None
        if type(evidence_ref) is not str or not evidence_ref:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED")
        try:
            return await self._lookup_admitted_call(ticket, permit, current.dispatch_cas_id)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_LOOKUP_UNAVAILABLE", outcome_unknown=True) from None

    async def record_recovered_terminal(self, ticket: ApplyTicket, permit: DispatchPermit,
                                        outcome_evidence_ref: str,
                                        completion_proof_ref: str,
                                        post_completion_challenge_ref: str,
                                        read_attestation_ref: str,
                                        resolution_event_id: UUID) -> CallSnapshot:
        """Finalize an entered conflict only after exact signed S12 records and T16 event."""
        identity = self._identity(ticket, permit)
        if type(resolution_event_id) is not UUID or resolution_event_id.int == 0:
            raise ServiceError("T16_RESOLUTION_REQUIRED")
        if any(type(value) is not str or not value for value in
               (outcome_evidence_ref, completion_proof_ref,
                post_completion_challenge_ref, read_attestation_ref)):
            raise ServiceError("RECOVERY_EVIDENCE_INVALID")
        try:
            current = await self.lookup(ticket, permit)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_LOOKUP_UNAVAILABLE", outcome_unknown=True) from None
        if (current.state is not AdmissionState.POSSIBLY_EXECUTING
                or type(current.dispatch_cas_id) is not UUID
                or current.dispatch_cas_id.int == 0
                or type(current.evidence_ref) is not str or not current.evidence_ref):
            raise ServiceError("RECOVERY_STATE_CONFLICT")
        pending_authorized = (
            not self._restart_required
            and self._startup_complete
            and (identity, current.dispatch_cas_id) in self._pending_t16_resolution_calls
        )
        recovery_authorized = self._recovery_transition_authorized(identity, current.dispatch_cas_id)
        if not pending_authorized and not recovery_authorized:
            raise ServiceError("STARTUP_RECOVERY_REQUIRED")
        require_startup_inventory = not pending_authorized
        resolver = self._writer_evidence_resolver
        if resolver is None:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True)
        try:
            records = await resolver.load_conditional_conflict_terminal_records(
                identity, current.dispatch_cas_id, current.evidence_ref,
                outcome_evidence_ref, completion_proof_ref,
                post_completion_challenge_ref, read_attestation_ref,
            )
            resolved_receipt = ResolvedReceiptEvidence(
                records.attempt, records.receipt,
                records.verified_records[0] if type(records.verified_records) is tuple
                and len(records.verified_records) == 5 else None,
                records.expected_scope,
            )
            if (type(records) is not ConditionalConflictTerminalRecords
                    or type(records.outcome) is not OutcomeEvidenceV3
                    or type(records.completion) is not CompletionProof
                    or type(records.post_completion_challenge) is not PostCompletionChallenge
                    or type(records.read_attestation) is not PostCompletionReadAttestation
                    or type(records.verified_records) is not tuple
                    or len(records.verified_records) != 5
                    or any(type(value) is not VerifiedEvidenceRecord
                           for value in records.verified_records)
                    or any(value.record is not record for value, record in zip(
                        records.verified_records,
                        (records.receipt, records.outcome, records.completion,
                         records.post_completion_challenge, records.read_attestation),
                        strict=True,
                    ))
                    or not self._receipt_identity_matches(
                        identity, current.dispatch_cas_id, resolved_receipt,
                    )
                    or records.receipt.result_class != "CONDITIONAL_VERSION_CONFLICT"
                    or records.receipt.write_invocation_stage != "ENTERED"
                    or not records.receipt.call_returned):
                raise ValueError("CONFLICT_RECORD_SET_INVALID")
            validate_conditional_conflict_terminal_evidence(
                records.attempt, records.receipt, records.outcome, records.completion,
                records.post_completion_challenge, records.read_attestation,
            )
            evidence_ref = await self._run_active_terminal_mutation(
                identity, current.dispatch_cas_id,
                lambda active_instance_id, active_epoch:
                    self._store.record_recovered_terminal(
                        identity, current.dispatch_cas_id, active_instance_id, active_epoch,
                        outcome_evidence_ref, completion_proof_ref,
                        post_completion_challenge_ref, read_attestation_ref, resolution_event_id,
                    ),
                require_startup_inventory=require_startup_inventory,
            )
        except asyncio.CancelledError:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None
        except AdmissionStoreError as exc:
            raise self._store_failure(exc, "RECOVERY_TERMINALIZATION_UNAVAILABLE") from None
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True) from None
        if type(evidence_ref) is not str or not evidence_ref:
            raise ServiceError("RECOVERY_EVIDENCE_REJECTED", outcome_unknown=True)
        self._pending_t16_resolution_calls.pop((identity, current.dispatch_cas_id), None)
        try:
            return await self._lookup_admitted_call(ticket, permit, current.dispatch_cas_id)
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("RECOVERY_LOOKUP_UNAVAILABLE", outcome_unknown=True) from None

    async def fence_scope(self, scope: Scope, expected_current_epoch: int,
                          barrier_id: UUID) -> BarrierSnapshot:
        self._begin_control_operation()
        try:
            return await self._fence_scope_started(scope, expected_current_epoch, barrier_id)
        finally:
            self._end_control_operation()

    async def _fence_scope_started(self, scope: Scope, expected_current_epoch: int,
                                   barrier_id: UUID) -> BarrierSnapshot:
        """Commit DB admission closure before waiting for local COM quiescence."""
        if (type(scope) is not Scope or type(expected_current_epoch) is not int
                or expected_current_epoch < 0 or type(barrier_id) is not UUID
                or barrier_id.int == 0):
            raise ServiceError("BARRIER_REQUEST_INVALID")
        service_epoch = self._service_epoch
        if not self._startup_complete or service_epoch is None:
            raise ServiceError("STARTUP_RECOVERY_REQUIRED")
        deadline = asyncio.get_running_loop().time() + self._barrier_wait_seconds
        # A barrier ID is the idempotency key. Once present, its stored epochs are authoritative;
        # a replay carrying an older caller epoch must not be treated as a different barrier.
        try:
            existing = await self._store.lookup_barrier(barrier_id)
        except Exception as exc:
            raise self._store_failure(exc, "BARRIER_LOOKUP_UNAVAILABLE") from None
        if existing is not None:
            if (not self._barrier_snapshot_valid(
                    existing, scope, self._base_fingerprint, existing.epoch, barrier_id)):
                raise ServiceError("BARRIER_CONFLICT")
            if existing.progress is BarrierProgress.QUIESCED:
                return existing
            # Continue the same closed barrier. Never issue close_and_advance again for this ID.
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return existing
                await asyncio.wait_for(self._base_dispatch_lock.acquire(), timeout=remaining)
            except TimeoutError:
                return existing
            try:
                return await self._finish_closed_barrier(existing, deadline)
            finally:
                self._base_dispatch_lock.release()
        try:
            snapshot = await self._bounded_barrier_call(
                lambda: self._store.close_and_advance(
                    self._base_fingerprint, scope, expected_current_epoch, barrier_id,
                    self._service_instance_id, service_epoch,
                ), deadline,
            )
        except TimeoutError:
            raise ServiceError("BARRIER_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        except Exception as exc:
            raise self._store_failure(exc, "BARRIER_UNAVAILABLE") from None
        if not self._barrier_snapshot_valid(
                snapshot, scope, self._base_fingerprint, snapshot.epoch, barrier_id):
            raise ServiceError("BARRIER_SNAPSHOT_INVALID")
        # Another caller may have completed this same barrier after lookup_barrier returned None.
        if snapshot.progress is BarrierProgress.QUIESCED:
            return snapshot
        if snapshot.progress is not BarrierProgress.CLOSED_WITH_HOLD:
            raise ServiceError("BARRIER_SNAPSHOT_INVALID")

        # Any call that won durable admission before closure is already in this immutable set.
        # Calls queued behind the local mutex cannot enter COM because DB admission is now closed.
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return snapshot
            await asyncio.wait_for(self._base_dispatch_lock.acquire(), timeout=remaining)
        except TimeoutError:
            return snapshot
        try:
            return await self._finish_closed_barrier(snapshot, deadline)
        finally:
            self._base_dispatch_lock.release()

    async def _finish_closed_barrier(self, snapshot: BarrierSnapshot,
                                     deadline: float) -> BarrierSnapshot:
        """Acknowledge a DB-closed barrier while holding the local physical-call queue."""
        if self._restart_required:
            raise ServiceError("SERVICE_RESTART_REQUIRED", outcome_unknown=True)
        scope = snapshot.scope
        epoch = snapshot.epoch
        barrier_id = snapshot.barrier_id
        pre_barrier_call_ids = snapshot.call_ids
        service_epoch = self._service_epoch
        if service_epoch is None:
            raise ServiceError("STARTUP_RECOVERY_REQUIRED")
        mutex = self._serving_authority_mutex
        if mutex is None:
            raise ServiceError("SERVING_AUTHORITY_MUTEX_UNAVAILABLE")
        try:
            active = self._active_quiesce
            if (active is not None and active[0] != barrier_id
                    and active[1].done()):
                self._authority_task_done(*active)
                active = self._active_quiesce
            if active is not None and active[0] != barrier_id:
                raise ServiceError("SERVING_AUTHORITY_BUSY", outcome_unknown=True)
            if active is None:
                task = asyncio.create_task(
                    self._quiesce_under_authority(
                        mutex,
                        lambda authority_lease: self._writer.quiesce(
                            self._base_fingerprint, scope.tenant_id, scope.company_id,
                            epoch, barrier_id, snapshot.barrier_origin_instance_id,
                            snapshot.barrier_origin_service_epoch,
                            pre_barrier_call_ids, authority_lease,
                        ),
                    ),
                )
                self._set_lifecycle_field("_active_quiesce", (barrier_id, task))
                task.add_done_callback(
                    lambda completed, current_barrier=barrier_id:
                    self._authority_task_done(current_barrier, completed),
                )
            else:
                task = active[1]
            acknowledgement = await self._bounded_quiesce_wait(task, deadline)
        except TimeoutError:
            raise ServiceError("BARRIER_ACK_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("BARRIER_ACK_UNAVAILABLE", outcome_unknown=True) from None
        if (type(acknowledgement) is not BarrierAcknowledgement
                or acknowledgement.base_fingerprint != self._base_fingerprint
                or acknowledgement.tenant_id != scope.tenant_id
                or acknowledgement.company_id != scope.company_id
                or acknowledgement.lifecycle_epoch != epoch
                or type(acknowledgement.lifecycle_epoch) is not int
                or acknowledgement.barrier_id != barrier_id
                or acknowledgement.barrier_origin_instance_id
                != snapshot.barrier_origin_instance_id
                or acknowledgement.barrier_origin_service_epoch
                != snapshot.barrier_origin_service_epoch
                or type(acknowledgement.barrier_origin_service_epoch) is not int
                or acknowledgement.call_ids != pre_barrier_call_ids
                or type(acknowledgement.key_id) is not str or not acknowledgement.key_id
                or type(acknowledgement.key_version) is not str or not acknowledgement.key_version
                or type(acknowledgement.writer_service_id) is not str
                or not acknowledgement.writer_service_id
                or type(acknowledgement.writer_host_id) is not str
                or acknowledgement.writer_host_id != self._host_id
                or not _is_canonical_process_instance_id(acknowledgement.host_boot_id)
                or type(acknowledgement.writer_process_instance_id) is not str
                or not _is_canonical_process_instance_id(
                    acknowledgement.writer_process_instance_id,
                )
                or type(acknowledgement.process_attestation_ref) is not str
                or not acknowledgement.process_attestation_ref
                or type(acknowledgement.writer_queue_epoch) is not int
                or acknowledgement.writer_queue_epoch <= 0
                or type(acknowledgement.local_queue_closed) is not bool
                or not acknowledgement.local_queue_closed
                or type(acknowledgement.signed_at) is not str
                or not acknowledgement.signed_at
                or type(acknowledgement.signature) is not bytes
                or len(acknowledgement.signature) != 64):
            raise ServiceError("BARRIER_ACK_INVALID")
        try:
            validate_barrier_acknowledgement(acknowledgement)
        except BarrierAcknowledgementProtocolError:
            raise ServiceError("BARRIER_ACK_INVALID") from None
        if self._barrier_ack_verifier is None:
            raise ServiceError("BARRIER_ACK_VERIFIER_UNAVAILABLE")
        try:
            acknowledgement_ref = await self._bounded_barrier_call(
                lambda: self._barrier_ack_verifier.verify_and_store(acknowledgement), deadline,
            )
        except BarrierAcknowledgementRejected:
            raise ServiceError("BARRIER_ACK_REJECTED") from None
        except asyncio.CancelledError:
            raise ServiceError("BARRIER_ACK_VERIFY_UNKNOWN", outcome_unknown=True) from None
        except TimeoutError:
            raise ServiceError("BARRIER_ACK_VERIFY_UNKNOWN", outcome_unknown=True) from None
        except Exception:
            raise ServiceError("BARRIER_ACK_VERIFY_UNKNOWN", outcome_unknown=True) from None
        if (type(acknowledgement_ref) is not str or not acknowledgement_ref
                or acknowledgement_ref != acknowledgement_ref.strip()):
            # The verifier may have committed before returning a malformed reference. Require
            # lookup/replay by barrier ID rather than reporting a definitive rejection.
            raise ServiceError("BARRIER_ACK_VERIFY_UNKNOWN", outcome_unknown=True)

        while True:
            try:
                current = await self._bounded_barrier_call(
                    lambda: self._store.finish_barrier(
                        snapshot, acknowledgement_ref, self._service_instance_id, service_epoch,
                    ), deadline,
                )
            except TimeoutError:
                # Commit may have succeeded; the durable state is now unknown to this caller.
                raise ServiceError("BARRIER_OUTCOME_UNKNOWN", outcome_unknown=True) from None
            except Exception as exc:
                raise self._store_failure(exc, "BARRIER_UNAVAILABLE") from None
            if (not self._barrier_snapshot_valid(
                    current, scope, self._base_fingerprint, epoch, barrier_id)
                    or current.call_ids != pre_barrier_call_ids):
                raise ServiceError("BARRIER_SNAPSHOT_INVALID")
            if current.progress is BarrierProgress.QUIESCED:
                if current.unresolved_call_ids:
                    raise ServiceError("BARRIER_SNAPSHOT_INVALID")
                return current
            if asyncio.get_running_loop().time() >= deadline:
                return current
            await asyncio.sleep(min(0.05, max(0.0, deadline - asyncio.get_running_loop().time())))

    async def resume_barrier(self, barrier_id: UUID) -> BarrierSnapshot:
        self._begin_control_operation()
        try:
            return await self._resume_barrier_started(barrier_id)
        finally:
            self._end_control_operation()

    async def _resume_barrier_started(self, barrier_id: UUID) -> BarrierSnapshot:
        """Resume one inventoried open barrier with dispatch disabled after process restart."""
        if type(barrier_id) is not UUID or barrier_id.int == 0:
            raise ServiceError("BARRIER_REQUEST_INVALID")
        state = self._startup_recovery
        if (self._startup_complete or self._restart_required
                or state is None
                or self._service_epoch != state.service_epoch):
            raise ServiceError(
                "SERVICE_RESTART_REQUIRED" if self._restart_required
                else "BARRIER_RECOVERY_NOT_READY"
            )
        expected = next((item for item in state.open_barriers if item.barrier_id == barrier_id), None)
        if expected is None:
            raise ServiceError("BARRIER_NOT_IN_STARTUP_INVENTORY")
        current = await self.lookup_barrier(barrier_id)
        if current is None:
            raise ServiceError("BARRIER_SNAPSHOT_INVALID")
        if (not self._barrier_snapshot_valid(
                    current, expected.scope, expected.base_fingerprint, expected.epoch, barrier_id)
                or current.call_ids != expected.call_ids
                or current.barrier_origin_instance_id != expected.barrier_origin_instance_id
                or current.barrier_origin_service_epoch != expected.barrier_origin_service_epoch):
            raise ServiceError("BARRIER_SNAPSHOT_INVALID")
        if current.progress is BarrierProgress.QUIESCED:
            if current.unresolved_call_ids:
                raise ServiceError("BARRIER_SNAPSHOT_INVALID")
            return current
        if current.progress is not BarrierProgress.CLOSED_WITH_HOLD:
            raise ServiceError("BARRIER_SNAPSHOT_INVALID")

        deadline = asyncio.get_running_loop().time() + self._barrier_wait_seconds
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return current
            await asyncio.wait_for(self._base_dispatch_lock.acquire(), timeout=remaining)
        except TimeoutError:
            return current
        try:
            return await self._finish_closed_barrier(current, deadline)
        finally:
            self._base_dispatch_lock.release()
