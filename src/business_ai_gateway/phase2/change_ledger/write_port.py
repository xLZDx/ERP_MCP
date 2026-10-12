"""NON-OPERATIONAL 1C write port skeleton (S12 section 7). No COM, OData or network code.

Every method raises ``NotWired``. The data types fix the shapes the real writer must honour: an apply
ticket, a dispatch permit for the current generation, and typed failure-stage evidence in which only a
PRE_WRITE refusal with an operation-specific no-effect proof is a definite (T8) outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


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


@dataclass(frozen=True)
class FailureEvidence:
    """Writer-signed failure record; the ledger chooses T8 vs T9 from it, never from a caller flag."""

    stage: FailureStage
    refusal: WriterRefusal | None
    no_effect_proof: dict[str, Any] = field(default_factory=dict)
    signer_key_id: str = ""
    signature: str = ""

    def is_definite_no_effect(self) -> bool:
        return (self.stage is FailureStage.PRE_WRITE and self.refusal is not None
                and bool(self.no_effect_proof))


class OneCWritePort(Protocol):
    async def verify_ticket(self, ticket: ApplyTicket) -> None: ...

    async def verify_permit(self, ticket: ApplyTicket, permit: DispatchPermit) -> None: ...

    async def authenticate_base(self, ticket: ApplyTicket) -> str: ...

    async def create_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           payload: dict[str, Any]) -> dict[str, Any]: ...

    async def update_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           payload: dict[str, Any]) -> dict[str, Any]: ...

    async def post(self, ticket: ApplyTicket, permit: DispatchPermit) -> dict[str, Any]: ...

    async def unpost(self, ticket: ApplyTicket, permit: DispatchPermit) -> dict[str, Any]: ...


class NonOperationalWritePort:
    """Skeleton implementation of OneCWritePort: every method raises NotWired."""

    async def verify_ticket(self, ticket: ApplyTicket) -> None:
        raise NotWired

    async def verify_permit(self, ticket: ApplyTicket, permit: DispatchPermit) -> None:
        raise NotWired

    async def authenticate_base(self, ticket: ApplyTicket) -> str:
        raise NotWired

    async def create_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           payload: dict[str, Any]) -> dict[str, Any]:
        raise NotWired

    async def update_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           payload: dict[str, Any]) -> dict[str, Any]:
        raise NotWired

    async def post(self, ticket: ApplyTicket, permit: DispatchPermit) -> dict[str, Any]:
        raise NotWired

    async def unpost(self, ticket: ApplyTicket, permit: DispatchPermit) -> dict[str, Any]:
        raise NotWired
