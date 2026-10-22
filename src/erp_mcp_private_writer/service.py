"""Fail-closed orchestration boundary for the private S13 writer service.

This module deliberately contains no HTTP listener, database adapter, COM/OData client, or public
gateway registration. A durable admission adapter must atomically enforce the S13 epoch, unique
call identity, and shared mutation fence. Each adapter call must commit or roll back its own
top-level transaction before returning. In particular, no adapter transaction may span a writer
port call.

Only the process that durably wins a new admission may invoke the injected writer, and it can do so
at most once. Replays and uncertain outcomes are looked up; they are never dispatched again.
"""
from __future__ import annotations

import asyncio
import copy
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol
from uuid import UUID, uuid4

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.write_port import (
    ApplyTicket,
    DispatchPermit,
    OneCWritePort,
)

__all__ = [
    "AdmissionDecision",
    "AdmissionRefusal",
    "AdmissionState",
    "BarrierProgress",
    "BarrierSnapshot",
    "CallIdentity",
    "CallSnapshot",
    "PrivateWriterService",
    "ServiceError",
]


class ServiceError(Exception):
    """Stable service refusal; dependency error text is not included."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AdmissionState(StrEnum):
    NOT_ACCEPTED = "NOT_ACCEPTED"
    ACCEPTED_NOT_INVOKED = "ACCEPTED_NOT_INVOKED"
    POSSIBLY_EXECUTING = "POSSIBLY_EXECUTING"
    TERMINAL_WITH_EVIDENCE = "TERMINAL_WITH_EVIDENCE"


class AdmissionRefusal(StrEnum):
    STALE_EPOCH = "STALE_EPOCH"
    CALL_IDENTITY_CONFLICT = "CALL_IDENTITY_CONFLICT"
    WRITER_ADMISSION_CLOSED = "WRITER_ADMISSION_CLOSED"


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
    admission_id: UUID | None = None
    evidence_ref: str | None = None
    refusal_code: AdmissionRefusal | None = None


@dataclass(frozen=True)
class CallSnapshot:
    """Authoritative durable lookup result for an exact immutable call tuple."""

    identity: CallIdentity
    state: AdmissionState
    dispatch_cas_id: UUID | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True)
class BarrierSnapshot:
    """Complete pre-barrier call set returned atomically by the durable admission store."""

    scope: Scope
    barrier_id: UUID
    epoch: int
    call_ids: tuple[str, ...]
    progress: BarrierProgress
    unresolved_call_ids: tuple[str, ...]


class AdmissionStore(Protocol):
    """Durable adapter contract; every method is a bounded top-level DB transaction.

    ``admit`` atomically compares the epoch, checks the full call tuple, and inserts/returns the
    unique call record. It reports ``newly_admitted=True`` only to the process instance that won
    the insert; an identical replay returns the original owner and is lookup-only. Barrier methods
    return the same deterministically ordered, complete, unpaginated pre-barrier call set for each
    poll and persist QUIESCED only after every call has terminal evidence. ``record_terminal``
    validates writer evidence before committing it.
    """

    async def admit(self, identity: CallIdentity, process_instance_id: str) -> AdmissionDecision: ...

    async def mark_invoking(self, identity: CallIdentity, dispatch_cas_id: UUID,
                            process_instance_id: str) -> bool: ...

    async def record_terminal(self, identity: CallIdentity, dispatch_cas_id: UUID,
                              process_instance_id: str,
                              writer_result: dict[str, Any]) -> str: ...

    async def lookup(self, identity: CallIdentity) -> CallSnapshot: ...

    async def close_and_advance(self, scope: Scope, epoch: int,
                                barrier_id: UUID) -> BarrierSnapshot: ...

    async def finish_barrier(self, snapshot: BarrierSnapshot) -> BarrierSnapshot: ...


class PrivateWriterService:
    """Coordinate durable admission and one injected writer call, without retrying COM."""

    _WRITER_METHODS = {
        "CREATE_DRAFT": "create_draft",
        "UPDATE_DRAFT": "update_draft",
        "POST": "post",
        "UNPOST": "unpost",
    }

    def __init__(self, store: AdmissionStore, writer: OneCWritePort, *, host_id: str,
                 base_fingerprint: str,
                 barrier_wait_seconds: float = 5.0) -> None:
        for value in (host_id, base_fingerprint):
            if type(value) is not str or not value.strip():
                raise ValueError("WRITER_BINDING_INVALID")
        if (isinstance(barrier_wait_seconds, bool)
                or not isinstance(barrier_wait_seconds, (int, float))
                or not math.isfinite(barrier_wait_seconds) or barrier_wait_seconds <= 0):
            raise ValueError("BARRIER_TIMEOUT_INVALID")
        self._store = store
        self._writer = writer
        self._host_id = host_id
        self._service_instance_id = str(uuid4())
        self._base_fingerprint = base_fingerprint
        self._barrier_wait_seconds = float(barrier_wait_seconds)

    def _identity(self, ticket: ApplyTicket, permit: DispatchPermit) -> CallIdentity:
        if type(ticket) is not ApplyTicket or type(permit) is not DispatchPermit:
            raise ServiceError("CALL_IDENTITY_INVALID")
        if (type(ticket.generation) is not int or ticket.generation <= 0
                or type(permit.lifecycle_epoch) is not int or permit.lifecycle_epoch <= 0
                or permit.generation != ticket.generation
                or permit.change_id != ticket.change_id or permit.call_id != ticket.call_id
                or permit.repair_authorization_id != ticket.repair_authorization_id
                or ticket.base_fingerprint != self._base_fingerprint):
            raise ServiceError("CALL_IDENTITY_INVALID")
        if ticket.kind not in self._WRITER_METHODS:
            raise ServiceError("OPERATION_UNSUPPORTED")
        try:
            change_id = str(UUID(ticket.change_id))
            call_id = str(UUID(ticket.call_id))
        except (ValueError, TypeError, AttributeError):
            raise ServiceError("CALL_IDENTITY_INVALID") from None
        if not ticket.tenant_id or not ticket.company_id or not ticket.organization:
            raise ServiceError("CALL_SCOPE_INVALID")
        if (type(ticket.digest_set_hash) is not str or len(ticket.digest_set_hash) != 64
                or any(ch not in "0123456789abcdef" for ch in ticket.digest_set_hash)
                or type(permit.permit_id) is not str or not permit.permit_id
                or type(permit.permit_digest) is not str or not permit.permit_digest):
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
            payload_digest=ticket.digest_set_hash,
            permit_id=permit.permit_id,
            permit_digest=permit.permit_digest,
            base_fingerprint=ticket.base_fingerprint,
            host_id=self._host_id,
            repair_authorization_id=ticket.repair_authorization_id,
        )

    async def lookup(self, ticket: ApplyTicket, permit: DispatchPermit) -> CallSnapshot:
        """Return the durable status for the exact ticket/permit identity; never invoke the writer."""
        identity = self._identity(ticket, permit)
        try:
            snapshot = await self._store.lookup(identity)
        except Exception:
            raise ServiceError("OUTCOME_LOOKUP_UNAVAILABLE") from None
        if (type(snapshot) is not CallSnapshot or snapshot.identity != identity
                or type(snapshot.state) is not AdmissionState
                or (snapshot.state is not AdmissionState.NOT_ACCEPTED
                    and type(snapshot.dispatch_cas_id) is not UUID)
                or (snapshot.state is AdmissionState.TERMINAL_WITH_EVIDENCE
                    and (type(snapshot.evidence_ref) is not str or not snapshot.evidence_ref))):
            raise ServiceError("OUTCOME_LOOKUP_INVALID")
        return snapshot

    async def _lookup_admitted_call(self, ticket: ApplyTicket, permit: DispatchPermit,
                                    dispatch_cas_id: UUID) -> CallSnapshot:
        snapshot = await self.lookup(ticket, permit)
        if snapshot.dispatch_cas_id != dispatch_cas_id:
            raise ServiceError("DISPATCH_CAS_MISMATCH")
        return snapshot

    @staticmethod
    def _barrier_snapshot_valid(snapshot: Any, scope: Scope, epoch: int,
                                barrier_id: UUID) -> bool:
        if (type(snapshot) is not BarrierSnapshot or snapshot.scope != scope
                or snapshot.barrier_id != barrier_id or snapshot.epoch != epoch
                or type(snapshot.progress) is not BarrierProgress
                or type(snapshot.call_ids) is not tuple
                or type(snapshot.unresolved_call_ids) is not tuple
                or any(type(call_id) is not str or not call_id for call_id in snapshot.call_ids)
                or any(type(call_id) is not str or not call_id
                       for call_id in snapshot.unresolved_call_ids)
                or len(set(snapshot.call_ids)) != len(snapshot.call_ids)
                or len(set(snapshot.unresolved_call_ids)) != len(snapshot.unresolved_call_ids)
                or not set(snapshot.unresolved_call_ids).issubset(snapshot.call_ids)):
            return False
        if snapshot.progress is BarrierProgress.QUIESCED:
            return not snapshot.unresolved_call_ids
        return bool(snapshot.unresolved_call_ids)

    async def _bounded_barrier_call(self, call: Callable[[], Awaitable[Any]],
                                    deadline: float) -> Any:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            return await call()

    async def dispatch(self, ticket: ApplyTicket, permit: DispatchPermit,
                       payload: dict[str, Any]) -> CallSnapshot:
        """Admit once, mark invocation before I/O, and leave uncertainty unresolved without retry."""
        identity = self._identity(ticket, permit)
        if type(payload) is not dict:
            raise ServiceError("PAYLOAD_INVALID")
        try:
            writer_payload = copy.deepcopy(payload)
        except Exception:
            raise ServiceError("PAYLOAD_INVALID") from None
        try:
            await self._writer.verify_ticket(ticket)
            await self._writer.verify_permit(ticket, permit)
            actual_fingerprint = await self._writer.authenticate_base(ticket)
        except Exception:
            raise ServiceError("WRITER_PRECHECK_FAILED") from None
        if actual_fingerprint != identity.base_fingerprint:
            raise ServiceError("BASE_FINGERPRINT_MISMATCH")

        try:
            decision = await self._store.admit(identity, self._service_instance_id)
        except Exception:
            raise ServiceError("ADMISSION_UNAVAILABLE") from None
        if (type(decision) is not AdmissionDecision or decision.identity != identity
                or type(decision.state) is not AdmissionState
                or type(decision.newly_admitted) is not bool):
            raise ServiceError("ADMISSION_RESPONSE_INVALID")
        if decision.state is AdmissionState.NOT_ACCEPTED:
            if type(decision.refusal_code) is not AdmissionRefusal:
                raise ServiceError("CALL_NOT_ACCEPTED")
            raise ServiceError(decision.refusal_code.value)
        if (type(decision.admission_id) is not UUID
                or type(decision.dispatch_cas_id) is not UUID):
            raise ServiceError("ADMISSION_RESPONSE_INVALID")
        if (type(decision.owner_instance_id) is not str or not decision.owner_instance_id
                or (decision.newly_admitted
                    and decision.state is not AdmissionState.ACCEPTED_NOT_INVOKED)):
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
            )
        except Exception:
            raise ServiceError("INVOCATION_STAGE_UNKNOWN") from None
        if invocation_started is not True:
            return await self._lookup_admitted_call(ticket, permit, decision.dispatch_cas_id)

        writer_method = getattr(self._writer, self._WRITER_METHODS[identity.operation])
        try:
            result = await writer_method(ticket, permit, writer_payload) if identity.operation in {
                "CREATE_DRAFT", "UPDATE_DRAFT"} else await writer_method(ticket, permit)
        except asyncio.CancelledError:
            # Invocation may have reached COM. Preserve durable uncertainty; never dispatch again.
            raise
        except Exception:
            raise ServiceError("WRITER_OUTCOME_UNKNOWN") from None
        if type(result) is not dict:
            raise ServiceError("WRITER_OUTCOME_UNKNOWN")
        try:
            evidence_ref = await self._store.record_terminal(
                identity, decision.dispatch_cas_id, self._service_instance_id, result,
            )
        except Exception:
            raise ServiceError("OUTCOME_PERSISTENCE_UNKNOWN") from None
        if type(evidence_ref) is not str or not evidence_ref:
            raise ServiceError("OUTCOME_PERSISTENCE_UNKNOWN")
        return await self._lookup_admitted_call(ticket, permit, decision.dispatch_cas_id)

    async def fence_scope(self, scope: Scope, new_epoch: int, barrier_id: UUID) -> BarrierSnapshot:
        """Close admission atomically, wait within a bound, and never clear unresolved-call holds."""
        if (type(scope) is not Scope or type(new_epoch) is not int or new_epoch <= 0
                or type(barrier_id) is not UUID):
            raise ServiceError("BARRIER_REQUEST_INVALID")
        deadline = asyncio.get_running_loop().time() + self._barrier_wait_seconds
        try:
            snapshot = await self._bounded_barrier_call(
                lambda: self._store.close_and_advance(scope, new_epoch, barrier_id), deadline,
            )
        except TimeoutError:
            raise ServiceError("BARRIER_OUTCOME_UNKNOWN") from None
        except Exception:
            raise ServiceError("BARRIER_UNAVAILABLE") from None
        if not self._barrier_snapshot_valid(snapshot, scope, new_epoch, barrier_id):
            raise ServiceError("BARRIER_SNAPSHOT_INVALID")
        pre_barrier_call_ids = snapshot.call_ids
        while snapshot.unresolved_call_ids and asyncio.get_running_loop().time() < deadline:
            try:
                snapshot = await self._bounded_barrier_call(
                    lambda: self._store.finish_barrier(snapshot), deadline,
                )
            except TimeoutError:
                return BarrierSnapshot(scope, barrier_id, new_epoch, snapshot.call_ids,
                                       BarrierProgress.CLOSED_WITH_HOLD, snapshot.unresolved_call_ids)
            except Exception:
                raise ServiceError("BARRIER_UNAVAILABLE") from None
            if (not self._barrier_snapshot_valid(snapshot, scope, new_epoch, barrier_id)
                    or snapshot.call_ids != pre_barrier_call_ids):
                raise ServiceError("BARRIER_SNAPSHOT_INVALID")
            if snapshot.unresolved_call_ids:
                await asyncio.sleep(min(0.05, max(0.0, deadline - asyncio.get_running_loop().time())))
        if snapshot.unresolved_call_ids:
            return BarrierSnapshot(scope, barrier_id, new_epoch, snapshot.call_ids,
                                   BarrierProgress.CLOSED_WITH_HOLD, snapshot.unresolved_call_ids)
        if snapshot.progress is not BarrierProgress.QUIESCED:
            raise ServiceError("BARRIER_NOT_QUIESCED")
        return snapshot
