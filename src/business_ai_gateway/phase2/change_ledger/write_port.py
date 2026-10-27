"""NON-OPERATIONAL 1C write port skeleton (S12 section 7). No COM, OData or network code.

Every method raises ``NotWired``. The data types fix the shapes the real writer must honour: an apply
ticket with separate ticket-set and approved-payload digests, a dispatch permit for the current
generation, and typed invocation context. ``FailureEvidence`` is descriptive only: a local dictionary,
refusal code, or non-empty proof field cannot establish a definite (T8) outcome.

The coordinator's ``verify_ticket``/``verify_permit`` calls are early rejection only. Each eventual
mutating operation must repeat the authoritative entitlement, permit signature/expiry/revocation,
authority-epoch, kill-switch, base-fingerprint, target/pre-version and generation checks immediately
before entering COM. ``create_draft`` must also canonicalize the supplied payload, match its approved
digest, and prove the exact COM field/line mapping derives from those approved bytes. A post-CAS refusal
is a definite no-entry result only when a trusted registry validates the original signed S12 receipt
against a durable process/CAS-bound physical guard that proves the method was never entered and makes
later entry impossible; otherwise the result is uncertain and must not be retried. A port returns the
original receipt bytes, not a parsed dictionary that could have discarded duplicate JSON keys.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Awaitable, Callable, ClassVar, Protocol
from uuid import UUID

from .uuid_contract import is_canonical_nonzero_uuid


class NotWired(Exception):
    """Fixed error: this port has no implementation."""

    def __init__(self) -> None:
        super().__init__("WRITE_PORT_NOT_WIRED")


class FailureStage(StrEnum):
    PRE_WRITE = "PRE_WRITE"
    WRITE_STARTED = "WRITE_STARTED"
    POST_WRITE = "POST_WRITE"


class WriterRefusal(StrEnum):
    STALE_VERSION = "STALE_VERSION"
    LOCK_BUSY = "LOCK_BUSY"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    ROLLBACK_REFUSED = "ROLLBACK_REFUSED"
    WRITE_REFUSED = "WRITE_REFUSED"


@dataclass(frozen=True)
class ApplyTicket:
    change_id: str
    generation: int
    call_id: str
    kind: str
    tenant_id: str
    company_id: str
    organization: str
    base_fingerprint: str
    target_ref: str | None
    target_version: str | None
    digest_set_hash: str
    repair_authorization_id: str | None = None
    approved_payload_digest: str | None = None


@dataclass(frozen=True)
class InvocationContext:
    """Typed one-shot context for the exact winning database invocation reservation.

    The coordinator supplies a one-shot asynchronous callback for the durable one-way COM-entry
    guard. The concrete adapter calls it only after its final entitlement, permit and physical
    context checks, immediately before the mutating COM call, and must refuse COM unless it returns
    ``True``. ``False`` or an exception never authorizes entry. These fields are comparison
    bindings, not caller-supplied authority by themselves.
    """

    dispatch_cas_id: UUID
    service_instance_id: str
    service_epoch: int
    host_id: str
    base_fingerprint: str
    tenant_id: str
    company_id: str
    organization_ref: str
    change_id: str
    generation: int
    call_id: str
    operation: str
    target_ref: str | None
    expected_pre_version: str | None
    authority_epoch: int
    permit_id: str
    permit_digest: str
    digest_set_hash: str
    approved_payload_digest: str
    repair_authorization_id: str | None
    authorize_com_entry: Callable[[], Awaitable[bool]] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (type(self.operation) is not str
                or self.operation not in ("CREATE_DRAFT", "POST", "UNPOST")):
            raise ValueError("INVOCATION_OPERATION_INVALID")
        if type(self.dispatch_cas_id) is not UUID or self.dispatch_cas_id.int == 0:
            raise ValueError("INVOCATION_CAS_INVALID")
        for value in (self.service_instance_id, self.change_id, self.call_id, self.permit_id):
            if not _canonical_uuid(value):
                raise ValueError("INVOCATION_ID_INVALID")
        for value in (self.host_id, self.tenant_id, self.company_id, self.organization_ref):
            if not _nonblank_text(value):
                raise ValueError("INVOCATION_SCOPE_INVALID")
        if (type(self.base_fingerprint) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.base_fingerprint) is None):
            raise ValueError("INVOCATION_BASE_FINGERPRINT_INVALID")
        for value in (self.service_epoch, self.generation, self.authority_epoch):
            if type(value) is not int or value < 1:
                raise ValueError("INVOCATION_EPOCH_INVALID")
        for value in (self.permit_digest, self.digest_set_hash, self.approved_payload_digest):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("INVOCATION_DIGEST_INVALID")
        if (self.repair_authorization_id is not None
                and not _canonical_uuid(self.repair_authorization_id)):
            raise ValueError("INVOCATION_REPAIR_AUTHORIZATION_INVALID")
        if self.operation == "CREATE_DRAFT":
            if self.target_ref is not None or self.expected_pre_version is not None:
                raise ValueError("INVOCATION_PREIMAGE_INVALID")
        elif (not _nonblank_text(self.target_ref)
              or not _nonblank_text(self.expected_pre_version)):
            raise ValueError("INVOCATION_PREIMAGE_REQUIRED")
        if not callable(self.authorize_com_entry):
            raise ValueError("INVOCATION_ENTRY_GUARD_INVALID")

    def require_matches(self, ticket: ApplyTicket, permit: DispatchPermit, *,
                        service_instance_id: str, host_id: str,
                        base_fingerprint: str) -> None:
        """Reject a validly shaped context that belongs to a different call or process."""
        ticket_change_id = _canonical_uuid_text(ticket.change_id) if type(ticket) is ApplyTicket else None
        ticket_call_id = _canonical_uuid_text(ticket.call_id) if type(ticket) is ApplyTicket else None
        permit_change_id = _canonical_uuid_text(permit.change_id) if type(permit) is DispatchPermit else None
        permit_call_id = _canonical_uuid_text(permit.call_id) if type(permit) is DispatchPermit else None
        if (type(ticket) is not ApplyTicket or type(permit) is not DispatchPermit
                or self.service_instance_id != service_instance_id
                or self.host_id != host_id or self.base_fingerprint != base_fingerprint
                or (self.change_id, self.generation, self.call_id, self.operation,
                    self.tenant_id, self.company_id, self.organization_ref,
                    self.target_ref, self.expected_pre_version, self.digest_set_hash,
                    self.approved_payload_digest, self.repair_authorization_id)
                != (ticket_change_id, ticket.generation, ticket_call_id, ticket.kind,
                    ticket.tenant_id, ticket.company_id, ticket.organization,
                    ticket.target_ref, ticket.target_version, ticket.digest_set_hash,
                    ticket.approved_payload_digest, ticket.repair_authorization_id)
                or (self.permit_id, self.permit_digest, self.authority_epoch)
                != (permit.permit_id, permit.permit_digest, permit.lifecycle_epoch)
                or (self.change_id, self.generation, self.call_id)
                != (permit_change_id, permit.generation, permit_call_id)):
            raise ValueError("INVOCATION_CONTEXT_MISMATCH")


def _canonical_uuid(value: object) -> bool:
    return is_canonical_nonzero_uuid(value)


def _canonical_uuid_text(value: object) -> str | None:
    return value if is_canonical_nonzero_uuid(value) else None


def _nonblank_text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


@dataclass(frozen=True)
class ReceiptLookupKey:
    """Immutable physical-call identity used only for read-only receipt recovery."""

    dispatch_cas_id: UUID
    base_fingerprint: str
    tenant_id: str
    company_id: str
    organization_ref: str
    change_id: str
    generation: int
    call_id: str
    operation: str
    target_ref: str | None
    expected_pre_version: str | None
    authority_epoch: int
    permit_id: str
    permit_digest: str
    approved_payload_digest: str
    host_id: str
    repair_authorization_id: str | None

    def __post_init__(self) -> None:
        if type(self.operation) is not str or self.operation not in (
                "CREATE_DRAFT", "POST", "UNPOST"):
            raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")
        if (type(self.dispatch_cas_id) is not UUID or self.dispatch_cas_id.int == 0
                or type(self.generation) is not int or self.generation < 1
                or type(self.authority_epoch) is not int or self.authority_epoch < 1):
            raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")
        if any(not _canonical_uuid(value) for value in (
                self.change_id, self.call_id, self.permit_id)):
            raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")
        if (self.repair_authorization_id is not None
                and not _canonical_uuid(self.repair_authorization_id)):
            raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")
        if any(not _nonblank_text(value) for value in (
                self.tenant_id, self.company_id, self.organization_ref, self.host_id)):
            raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")
        for value in (self.base_fingerprint, self.permit_digest, self.approved_payload_digest):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")
        if self.operation == "CREATE_DRAFT":
            if self.target_ref is not None or self.expected_pre_version is not None:
                raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")
        elif (not _nonblank_text(self.target_ref)
              or not _nonblank_text(self.expected_pre_version)):
            raise ValueError("RECEIPT_LOOKUP_KEY_INVALID")


class ReceiptLookupState(StrEnum):
    RECEIPT_AVAILABLE = "RECEIPT_AVAILABLE"
    OUTCOME_UNRESOLVED = "OUTCOME_UNRESOLVED"


@dataclass(frozen=True)
class ReceiptLookupResult:
    """The writer returns original signed bytes or explicitly leaves the call unresolved."""

    state: ReceiptLookupState
    receipt_envelope: bytes | None = None

    def __post_init__(self) -> None:
        if type(self.state) is not ReceiptLookupState:
            raise ValueError("RECEIPT_LOOKUP_STATE_INVALID")
        if self.state is ReceiptLookupState.RECEIPT_AVAILABLE:
            if type(self.receipt_envelope) is not bytes or not self.receipt_envelope:
                raise ValueError("RECEIPT_LOOKUP_BYTES_REQUIRED")
        elif self.receipt_envelope is not None:
            raise ValueError("UNRESOLVED_RECEIPT_BYTES_FORBIDDEN")


@dataclass(frozen=True)
class DispatchPermit:
    permit_id: str
    permit_digest: str
    change_id: str
    generation: int
    call_id: str
    expires_at: datetime
    checkpoint_seq: int
    signer_key_id: str
    signature: str
    repair_authorization_id: str | None = None
    lifecycle_epoch: int = 0


@dataclass(frozen=True)
class BarrierAcknowledgement:
    """Signed, domain-separated, process-attested acknowledgement for one base-wide barrier."""

    base_fingerprint: str
    tenant_id: str
    company_id: str
    lifecycle_epoch: int
    barrier_id: UUID
    barrier_origin_instance_id: str
    barrier_origin_service_epoch: int
    call_ids: tuple[str, ...]
    key_id: str
    key_version: str
    writer_service_id: str
    writer_host_id: str
    host_boot_id: str
    writer_process_instance_id: str
    process_attestation_ref: str
    writer_queue_epoch: int
    local_queue_closed: bool
    signed_at: str
    signature: bytes

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "base_fingerprint": self.base_fingerprint,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "lifecycle_epoch": self.lifecycle_epoch,
            "barrier_id": str(self.barrier_id),
            "barrier_origin_instance_id": self.barrier_origin_instance_id,
            "barrier_origin_service_epoch": self.barrier_origin_service_epoch,
            "call_ids": list(self.call_ids),
            "key_id": self.key_id,
            "key_version": self.key_version,
            "writer_service_id": self.writer_service_id,
            "writer_host_id": self.writer_host_id,
            "host_boot_id": self.host_boot_id,
            "writer_process_instance_id": self.writer_process_instance_id,
            "process_attestation_ref": self.process_attestation_ref,
            "writer_queue_epoch": self.writer_queue_epoch,
            "local_queue_closed": self.local_queue_closed,
            "signed_at": self.signed_at,
        }

    def signature_preimage(self) -> bytes:
        body = json.dumps(
            self.unsigned_dict(), sort_keys=True, ensure_ascii=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return b"ERP_MCP_R2:S13:PHYSICAL-WRITER-BARRIER:v1\n" + body


class ServingAuthorityLease(Protocol):
    """Proof that this process currently holds the host-wide serving authority mutex."""

    def assert_held(self) -> None: ...

    async def release(self) -> None:
        """Release the acquired host mutex exactly once."""
        ...


class ServingAuthorityMutex(Protocol):
    """One ACL-restricted host mutex shared by startup takeover and physical quiescence."""

    async def try_acquire(self) -> ServingAuthorityLease | None:
        """Perform a non-queued acquire, or return ``None`` when authority is already owned."""
        ...


@dataclass(frozen=True)
class FailureEvidence:
    """Writer-signed failure record; the ledger chooses T8 vs T9 from it, never from a caller flag."""

    stage: FailureStage
    refusal: WriterRefusal | None
    no_effect_proof: dict[str, Any] = field(default_factory=dict)
    signer_key_id: str = ""
    signature: str = ""

class OneCWritePort(Protocol):
    """The concrete COM adapter owns mandatory final pre-entry checks and queue fencing.

    The host-wide serving-authority mutex is outermost: both startup epoch takeover
    and ``quiesce`` acquire it before checking/updating the durable serving epoch.
    While holding it, ``quiesce`` also holds the exclusive physical-queue control,
    rechecks the active identity/epoch, then closes COM admission. A prior check or
    a queue-only lock is racy with takeover. This contract is single-host; a
    multi-host writer needs a shared fencing primitive before it can be enabled.
    """

    # Composition uses this declaration to reject accidental duck-typed skeletons. It is not
    # proof of trusted build provenance or deployment identity; those remain separate gates.
    operational: ClassVar[bool]

    async def verify_ticket(self, ticket: ApplyTicket) -> None: ...

    async def verify_permit(self, ticket: ApplyTicket, permit: DispatchPermit) -> None: ...

    async def authenticate_base(self, ticket: ApplyTicket) -> str: ...

    async def lookup_receipt(self, key: ReceiptLookupKey) -> ReceiptLookupResult:
        """Read the durable original receipt; absence/unavailability never proves no effect."""
        ...

    async def quiesce(self, base_fingerprint: str, tenant_id: str, company_id: str,
                      lifecycle_epoch: int,
                      barrier_id: UUID, barrier_origin_instance_id: str,
                      barrier_origin_service_epoch: int,
                      call_ids: tuple[str, ...],
                      authority_lease: ServingAuthorityLease) -> BarrierAcknowledgement:
        """Close the physical queue idempotently for the immutable barrier origin.

        Replaying a durable barrier after coordinator takeover repeats the original
        origin tuple and returns its exact stored acknowledgement. The current
        coordinator's serving identity authorizes database finalization separately.
        A conflicting barrier must fail closed until the prior close is reconciled.
        The awaitable may finish only after the underlying queue close has stopped
        accepting COM calls, even if that close runs on another thread.
        """
        ...

    async def create_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           context: InvocationContext,
                           payload: dict[str, Any]) -> bytes: ...

    async def post(self, ticket: ApplyTicket, permit: DispatchPermit,
                   context: InvocationContext) -> bytes: ...

    async def unpost(self, ticket: ApplyTicket, permit: DispatchPermit,
                     context: InvocationContext) -> bytes: ...

    async def close_after_drain(self) -> None:
        """Idempotently close the owned COM STA after every accepted physical call has finished."""
        ...


class NonOperationalWritePort:
    """Skeleton implementation of OneCWritePort: every method raises NotWired."""

    operational = False

    async def verify_ticket(self, ticket: ApplyTicket) -> None:
        raise NotWired

    async def verify_permit(self, ticket: ApplyTicket, permit: DispatchPermit) -> None:
        raise NotWired

    async def authenticate_base(self, ticket: ApplyTicket) -> str:
        raise NotWired

    async def lookup_receipt(self, key: ReceiptLookupKey) -> ReceiptLookupResult:
        raise NotWired

    async def quiesce(self, base_fingerprint: str, tenant_id: str, company_id: str,
                      lifecycle_epoch: int,
                      barrier_id: UUID, barrier_origin_instance_id: str,
                      barrier_origin_service_epoch: int,
                      call_ids: tuple[str, ...],
                      authority_lease: ServingAuthorityLease) -> BarrierAcknowledgement:
        raise NotWired

    async def create_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           context: InvocationContext,
                           payload: dict[str, Any]) -> bytes:
        raise NotWired

    async def post(self, ticket: ApplyTicket, permit: DispatchPermit,
                   context: InvocationContext) -> bytes:
        raise NotWired

    async def unpost(self, ticket: ApplyTicket, permit: DispatchPermit,
                     context: InvocationContext) -> bytes:
        raise NotWired

    async def close_after_drain(self) -> None:
        raise NotWired
