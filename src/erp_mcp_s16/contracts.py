"""Typed, fake-backed contracts for the isolated S16 approval and tool slice."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, Protocol, TypeVar
from uuid import UUID

from business_ai_gateway.phase2.change.errors import ErrorCode
from business_ai_gateway.phase2.change.proposal import (
    ChangeProposal,
    canonical_json,
    payload_to_dict,
)
from business_ai_gateway.phase2.change.transitions import BeginApplyEvidence
from business_ai_gateway.phase2.change.types import ChangeRecord
from erp_mcp_s15.verifier import ExpectedReceipt, OperationShape, VerificationResult

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Result(Generic[T]):
    value: T | None = None
    error: ErrorCode | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T) -> "Result[T]":
        return cls(value=value)

    @classmethod
    def refused(cls, error: ErrorCode) -> "Result[T]":
        return cls(error=error)


class PrincipalRole(StrEnum):
    REQUESTER = "REQUESTER"
    APPROVER = "APPROVER"
    READ_ONLY = "READ_ONLY"


class TokenClass(StrEnum):
    CHAT_WRITE = "CHAT_WRITE"
    APPROVER_SESSION = "APPROVER_SESSION"
    READ_ONLY = "READ_ONLY"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class TargetScope:
    tenant: str
    company: str
    organization: str
    base_fingerprint: str
    target_class: str

    def as_tuple(self) -> tuple[str, str, str, str, str]:
        return (self.tenant, self.company, self.organization, self.base_fingerprint, self.target_class)


@dataclass(frozen=True, slots=True)
class TargetVersion:
    value: str
    observed_at: datetime
    source_revision: str = ""


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    principal_id: str
    person_id: str
    roles: frozenset[PrincipalRole]
    token_class: TokenClass
    epoch: int
    scope: TargetScope
    session_id: str | None
    expires_at: datetime
    mfa_authenticated: bool = False


@dataclass(frozen=True, slots=True)
class ApproverSession:
    session_id: str
    principal: AuthenticatedPrincipal
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    expires_at: datetime
    csrf_secret: str


@dataclass(frozen=True, slots=True)
class PreviewSnapshot:
    change_id: UUID
    version: int
    scope: TargetScope
    target_version: TargetVersion
    canonical_preview_bytes: bytes
    preview_digest: str
    proposal: ChangeProposal
    approval_canonical_text: str
    approval_digest: str
    nonce_digest: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    change_id: UUID
    version: int
    scope: TargetScope
    requester_person_id: str
    approver_person_id: str
    approver_principal_id: str
    approver_epoch: int
    session_id: str
    nonce_digest: str
    decision_ref_digest: str
    preview_digest: str
    approval_digest: str
    decision: Literal["APPROVE", "REJECT"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionPage:
    decision_ref: str
    canonical_preview_bytes: bytes
    preview_digest: str
    expires_at: datetime
    confirmation_required: bool = False
    confirmation_phrase: str | None = None
    lifecycle_status: str | None = None
    authorization_status: str | None = None
    snapshot_version: int | None = None
    created_at: datetime | None = None
    approver_person_label: str | None = None
    decision_allowed: bool = False


@dataclass(frozen=True, slots=True)
class DecisionBinding:
    change_id: UUID
    version: int
    scope: TargetScope
    principal_id: str
    person_id: str
    session_id: str
    requester_person_id: str
    nonce_digest: str
    decision_ref_digest: str
    csrf_binding_digest: str
    preview_digest: str
    approval_digest: str
    expires_at: datetime
    confirmation_required: bool = False
    confirmation_phrase: str | None = None


@dataclass(frozen=True, slots=True)
class DomainReceipt:
    change_id: UUID
    status: str
    version: int
    scope: TargetScope
    proposal: ChangeProposal
    requester_person_id: str
    approval: ApprovalDecision | None
    target_version: TargetVersion
    snapshot: PreviewSnapshot
    s12_record: ChangeRecord | None = None
    document_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ApplyReceipt:
    change_id: UUID
    status: str
    correlation_id: str
    document_ref: str | None = None


@dataclass(frozen=True, slots=True)
class VerifyRequest:
    change_id: UUID
    document_ref: str | None = None
    expected: ExpectedReceipt | None = None
    shape: OperationShape | None = None


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    principal_id: str
    person_id: str
    roles: frozenset[PrincipalRole]
    epoch: int
    revoked: bool = False
    epoch_dependencies: tuple[tuple[str, int], ...] = ()
    display_label: str | None = None


@dataclass(frozen=True, slots=True)
class TargetRecord:
    scope: TargetScope
    version: TargetVersion
    allowed: bool = True
    amount_confirmation_threshold: str | None = None
    parent_verified: bool = False
    qualified_operations: frozenset[str] = frozenset({"CREATE_DRAFT", "UPDATE_DRAFT", "POST", "UNPOST"})
    business_key_free: bool | None = None
    business_state_digest: str | None = None
    qualified_currencies: frozenset[str] = frozenset()
    in_scope_refs: frozenset[str] | None = frozenset()


@dataclass(frozen=True, slots=True)
class ClaimToken:
    claim_id: str
    change_id: UUID
    version: int
    approval_digest: str


@dataclass(frozen=True, slots=True)
class Claimed:
    token: ClaimToken


@dataclass(frozen=True, slots=True)
class ClaimRefused:
    error: ErrorCode


ClaimResult = Claimed | ClaimRefused


class Clock(Protocol):
    def now(self) -> datetime: ...


class NonceSource(Protocol):
    def issue(self) -> str: ...


class ChangeStore(Protocol):
    def get(self, change_id: UUID) -> DomainReceipt | None: ...
    def insert_proposal(self, receipt: DomainReceipt) -> None: ...
    def save_approval(self, decision: ApprovalDecision, *, s12_record: ChangeRecord | None = None) -> None: ...
    def save_s12_record(self, change_id: UUID, s12_record: ChangeRecord) -> None: ...
    def save_apply_receipt(self, change_id: UUID, receipt: ApplyReceipt) -> None: ...
    def claim_once(self, change_id: UUID, *, expected_version: int,
                   expected_approval_digest: str, claimant_id: str,
                   s12_record: ChangeRecord | None = None) -> ClaimResult: ...
    def release_claim(self, change_id: UUID, claim: ClaimToken, *,
                      expected_record: ChangeRecord, released_record: ChangeRecord) -> bool: ...
    def get_decision_binding(self, decision_ref: str) -> DecisionBinding | None: ...
    def issue_decision_ref(self, decision_ref: str, binding: DecisionBinding) -> None: ...
    def consume_decision_ref_and_nonce(self, decision_ref: str, *, expected: DecisionBinding,
                                       decision: ApprovalDecision, s12_record: ChangeRecord) -> bool: ...


class PrincipalRegistryPort(Protocol):
    def current(self, principal_id: str) -> PrincipalRecord | None: ...
    def epochs_current(self, dependencies: tuple[tuple[str, int], ...]) -> bool: ...
    def are_independent(self, requester_person_id: str, approver_person_id: str) -> bool: ...


class TargetRegistryPort(Protocol):
    def current(self, scope: TargetScope) -> TargetRecord | None: ...
    def resolve_fingerprint(self, scope: TargetScope) -> str | None: ...


class KillSwitchPort(Protocol):
    def reading(self, scope: TargetScope) -> object: ...


class ApplyPort(Protocol):
    def apply(self, receipt: DomainReceipt, claim: ClaimToken) -> ApplyReceipt: ...


class VerifyPort(Protocol):
    def verify(self, document_ref: str, expected: ExpectedReceipt,
               shape: OperationShape) -> VerificationResult: ...


class BeginApplyEvidencePort(Protocol):
    def read(self, receipt: DomainReceipt, claim: ClaimToken,
             now: datetime) -> BeginApplyEvidence | ErrorCode: ...


class ProposalPort(Protocol):
    def build(self, requester: AuthenticatedPrincipal, raw_request: Mapping[str, object], *,
              now: datetime, expires_at: datetime, preview_digest: str,
              change_id: str) -> tuple[ChangeProposal, TargetRecord] | ErrorCode: ...
    def rollback(self, requester: AuthenticatedPrincipal, receipt: DomainReceipt, *,
                 now: datetime, expires_at: datetime, preview_digest: str,
                 change_id: str) -> tuple[ChangeProposal, TargetRecord] | ErrorCode: ...


def canonical_preview_bytes(proposal: ChangeProposal, *, target_version: str,
                            target_class: str) -> bytes:
    """Canonical allowlisted display bytes shared by issuance and every core revalidation."""
    value = {
        "change_id": proposal.change_id,
        "kind": proposal.kind.value,
        "scope": {"tenant": proposal.scope.tenant, "company": proposal.scope.company,
                  "organization": proposal.scope.organization,
                  "base_fingerprint": proposal.scope.base_fingerprint,
                  "target_class": target_class},
        "target_version": target_version,
        "requester_person_id": proposal.requester_person_id,
        "reason": proposal.reason,
        "payload": payload_to_dict(proposal.payload),
        "expires_at": proposal.expires_at.isoformat(),
    }
    return canonical_json(value).encode("utf-8")

