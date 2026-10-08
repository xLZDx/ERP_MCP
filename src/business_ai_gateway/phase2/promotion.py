"""Phase 2 promotion service: guarded promote / rollback of an accepted head.

Pure logic over ``HeadAttestationPort`` plus a read-only ``AttestationReader``; no I/O, no wall
clock (time comes from the injected ``clock``). The SQL ``living.promote_head`` stays the final
authority; this service is the fail-closed pre-flight that gives every outcome a typed result and
guarantees that a rejected request never reaches the port's write call.

Guard order (first failure wins; nothing is written before every guard has passed):
input -> requester/approver independence -> evidence shape -> attestation lookup -> decision ->
revocation -> expiry -> digest recomputed from the presented evidence -> observer trust -> approver
independence from attestation observer/proposer -> head CAS -> single atomic ``promote_head``.

Rollback never mutates history: it promotes the content of an earlier accepted version as a NEW
head version. It does not restore rights: an attestation revoked after the original promotion
stays revoked, so a rollback needs evidence that is valid *now* (fresh approval when the original
one was revoked or expired). Any unexpected error fails closed as ``FAILED_CLOSED``.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from .ports import AcceptanceView, HeadAttestationPort, PortError, Scope, evidence_digest

__all__ = [
    "AttestationReader", "AttestationView", "Evidence", "Outcome", "PromotionResult",
    "PromotionService", "normalize_identity",
]


class Outcome(StrEnum):
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    REJECTED_INPUT = "REJECTED_INPUT"
    REJECTED_CAS = "REJECTED_CAS"
    REJECTED_SELF_APPROVAL = "REJECTED_SELF_APPROVAL"
    REJECTED_UNTRUSTED = "REJECTED_UNTRUSTED"
    REJECTED_EVIDENCE = "REJECTED_EVIDENCE"
    REJECTED_REVOKED = "REJECTED_REVOKED"
    REJECTED_EXPIRED = "REJECTED_EXPIRED"
    REJECTED_TARGET = "REJECTED_TARGET"
    REJECTED_ACCEPTANCE_ID = "REJECTED_ACCEPTANCE_ID"
    FAILED_CLOSED = "FAILED_CLOSED"


@dataclass(frozen=True, slots=True)
class PromotionResult:
    outcome: Outcome
    new_version: int | None = None
    code: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in (Outcome.PROMOTED, Outcome.ROLLED_BACK)


@dataclass(frozen=True, slots=True)
class Evidence:
    """Evidence payload presented with a request; its digest is recomputed, never trusted."""
    revision_digest: str
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class AttestationView:
    attestation_id: UUID
    revision_id: UUID
    proposer: str
    observer: str
    evidence_ref: str
    evidence_digest: str
    decision: str
    expires_at: datetime
    revoked_at: datetime | None


@runtime_checkable
class AttestationReader(Protocol):
    """Read side the port contract does not expose (a SQL view / fake accessor implements it)."""

    async def find_attestation(self, scope: Scope, revision_id: UUID,
                               evidence_ref: str) -> AttestationView | None: ...

    async def is_trusted_reviewer(self, scope: Scope, subject: str) -> bool: ...


def normalize_identity(value: object) -> str:
    """NFKC + casefold + trim; empty string means 'no usable identity'."""
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).strip().casefold()


_PORT_CODES: dict[str, Outcome] = {
    "STALE_ACCEPTED_HEAD": Outcome.REJECTED_CAS,
    "APPROVER_NOT_INDEPENDENT": Outcome.REJECTED_SELF_APPROVAL,
    "NOT_A_PROMOTER": Outcome.REJECTED_UNTRUSTED,
    "PERMISSION_DENIED": Outcome.REJECTED_UNTRUSTED,
    "REVIEWER_NOT_TRUSTED": Outcome.REJECTED_UNTRUSTED,
    "EVIDENCE_REVOKED": Outcome.REJECTED_REVOKED,
    "EVIDENCE_EXPIRED": Outcome.REJECTED_EXPIRED,
    "EVIDENCE_DIGEST_MISMATCH": Outcome.REJECTED_EVIDENCE,
    "EVIDENCE_NOT_FOUND": Outcome.REJECTED_EVIDENCE,
    "EVIDENCE_NOT_APPROVED": Outcome.REJECTED_EVIDENCE,
    "INDEPENDENT_APPROVAL_REQUIRED": Outcome.REJECTED_EVIDENCE,
    "REVISION_NOT_OBSERVED": Outcome.REJECTED_EVIDENCE,
    "ACCEPTANCE_ID_REUSED": Outcome.REJECTED_ACCEPTANCE_ID,
}


def _is_digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


class PromotionService:
    def __init__(self, port: HeadAttestationPort, reader: AttestationReader,
                 clock: Callable[[], datetime]):
        self._port = port
        self._reader = reader
        self._clock = clock

    # ------------------------------------------------------------------ public API
    async def promote(self, scope: Scope, model_key: str, candidate: UUID, expected_version: int,
                      requester: str, approver: str, evidence: Evidence | None,
                      acceptance_id: UUID) -> PromotionResult:
        try:
            return await self._run(scope, model_key, candidate, expected_version, requester,
                                   approver, evidence, acceptance_id, Outcome.PROMOTED)
        except Exception as exc:  # noqa: BLE001 - fail closed; the one write call is atomic
            return self._failed(exc)

    async def rollback(self, scope: Scope, model_key: str, to_version: int,
                       expected_version: int, requester: str, approver: str,
                       evidence: Evidence | None, acceptance_id: UUID) -> PromotionResult:
        try:
            if (type(to_version) is not int or type(expected_version) is not int
                    or not 1 <= to_version < expected_version):
                return PromotionResult(Outcome.REJECTED_TARGET, code="ROLLBACK_TARGET_INVALID")
            approver_id = normalize_identity(approver)
            if not approver_id:
                return PromotionResult(Outcome.REJECTED_INPUT, code="IDENTITY_REQUIRED")
            head = await self._port.get_head(approver, scope, model_key)
            if head is None or head.version != expected_version:
                return PromotionResult(Outcome.REJECTED_CAS, code="STALE_ACCEPTED_HEAD")
            target = _accepted_at(await self._port.list_acceptances(approver, scope), model_key,
                                  to_version)
            if target is None or target.accepted_revision == head.revision_id:
                return PromotionResult(Outcome.REJECTED_TARGET, code="ROLLBACK_TARGET_UNKNOWN")
            return await self._run(scope, model_key, target.accepted_revision, expected_version,
                                   requester, approver, evidence, acceptance_id,
                                   Outcome.ROLLED_BACK)
        except Exception as exc:  # noqa: BLE001 - fail closed
            return self._failed(exc)

    # ------------------------------------------------------------------ core
    async def _run(self, scope, model_key, candidate, expected_version, requester, approver,
                   evidence, acceptance_id, success: Outcome) -> PromotionResult:
        requester_id, approver_id = normalize_identity(requester), normalize_identity(approver)
        if (not requester_id or not approver_id or not isinstance(model_key, str)
                or not model_key or not isinstance(candidate, UUID)
                or not isinstance(acceptance_id, UUID) or type(expected_version) is not int
                or expected_version < 0):
            return PromotionResult(Outcome.REJECTED_INPUT, code="INVALID_ARGUMENT")
        if approver_id == requester_id:
            return PromotionResult(Outcome.REJECTED_SELF_APPROVAL, code="APPROVER_IS_REQUESTER")
        if (not isinstance(evidence, Evidence) or not _is_digest(evidence.revision_digest)
                or not isinstance(evidence.evidence_ref, str) or not evidence.evidence_ref.strip()):
            return PromotionResult(Outcome.REJECTED_EVIDENCE, code="EVIDENCE_REQUIRED")
        att = await self._reader.find_attestation(scope, candidate, evidence.evidence_ref)
        if att is None or att.decision != "APPROVE":
            return PromotionResult(Outcome.REJECTED_EVIDENCE, code="EVIDENCE_NOT_APPROVED")
        if att.revoked_at is not None:
            return PromotionResult(Outcome.REJECTED_REVOKED, code="EVIDENCE_REVOKED")
        if att.expires_at <= self._clock():
            return PromotionResult(Outcome.REJECTED_EXPIRED, code="EVIDENCE_EXPIRED")
        recomputed = evidence_digest(evidence.revision_digest, evidence.evidence_ref)
        if att.evidence_digest != recomputed:
            return PromotionResult(Outcome.REJECTED_EVIDENCE, code="EVIDENCE_DIGEST_MISMATCH")
        if not await self._reader.is_trusted_reviewer(scope, att.observer):
            return PromotionResult(Outcome.REJECTED_UNTRUSTED, code="REVIEWER_NOT_TRUSTED")
        if approver_id in (normalize_identity(att.observer), normalize_identity(att.proposer)):
            return PromotionResult(Outcome.REJECTED_SELF_APPROVAL, code="APPROVER_NOT_INDEPENDENT")
        head = await self._port.get_head(approver, scope, model_key)
        if head is None or head.version != expected_version:
            return PromotionResult(Outcome.REJECTED_CAS, code="STALE_ACCEPTED_HEAD")
        try:
            version = await self._port.promote_head(
                approver, scope, model_key, expected_version, candidate, acceptance_id,
                evidence.evidence_ref)
        except PortError as exc:
            outcome = _PORT_CODES.get(exc.code)
            if outcome is None:
                return PromotionResult(Outcome.FAILED_CLOSED, code=exc.code)
            return PromotionResult(outcome, code=exc.code)
        return PromotionResult(success, new_version=version)

    @staticmethod
    def _failed(exc: Exception) -> PromotionResult:
        code = exc.code if isinstance(exc, PortError) else type(exc).__name__
        return PromotionResult(Outcome.FAILED_CLOSED, code=code)


def _accepted_at(acceptances: tuple[AcceptanceView, ...], model_key: str,
                 version: int) -> AcceptanceView | None:
    return next((a for a in acceptances
                 if a.model_key == model_key and a.to_version == version), None)
