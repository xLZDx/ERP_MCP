"""Phase 2 promotion service: guarded promote / rollback of an accepted head.

Pure logic over ``HeadAttestationPort`` plus a read-only ``AttestationReader``; no I/O, no wall
clock (time comes from the injected ``clock``). The SQL ``living.promote_head`` stays the final
authority; this service is the fail-closed pre-flight that gives every outcome a typed result and
guarantees that a rejected request never reaches the port's write call.

Guard order (first failure wins; nothing is written before every guard has passed):
input -> requester/approver independence -> evidence shape -> idempotent replay (acceptance_id
already recorded: identical arguments return the recorded version, different ones are
REJECTED_ACCEPTANCE_ID; this runs before any time-dependent guard so a retry after a lost response
still sees the recorded success) -> attestation lookup (must match revision and evidence_ref) ->
decision -> revocation -> expiry -> digest recomputed from the presented evidence (constant-time
compare) -> observer trust -> approver independence from attestation observer/proposer -> head CAS
-> single atomic ``promote_head``.

Rollback never mutates history: it promotes the content of an earlier accepted version as a NEW
head version. It does not restore rights: an attestation revoked after the original promotion
stays revoked, so a rollback needs evidence that is valid *now* (fresh approval when the original
one was revoked or expired). An unexpected error BEFORE the write call fails closed as
``FAILED_CLOSED`` (nothing written); a non-PortError raised at or after the write call is
``INDETERMINATE`` (the commit may have happened; retrying with the same acceptance_id is safe).
"""
from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from ._identity import clean_identity
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
    INDETERMINATE = "INDETERMINATE"


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
    """Strict identity normalisation (``_identity.clean_identity``: NFKC + casefold + trim, zero-width
    and other format/control characters make it invalid); empty string means 'no usable identity'."""
    return clean_identity(value)


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


# Codes meaning the caller may not read acceptances; the guards that follow still reject or fail closed.
_NO_READ_RIGHT = frozenset({"PERMISSION_DENIED", "SCOPE_NOT_GRANTED", "SCOPE_REVOKED"})

# Typed SQL rejections raised before anything is written; any other code at the write call is ambiguous.
_ROLLED_BACK_CODES = frozenset({
    "SCOPE_REVOKED", "SCOPE_NOT_GRANTED", "SOURCE_NOT_FOUND", "INVALID_ARGUMENT",
    "CHECK_VIOLATION", "SQL_40001", "SQL_40P01",
})


_SQL_STATE_CODE = re.compile(r"^SQL_[0-9A-Z]{5}$")
# SQL states this module handles: serialization/deadlock (rolled back) and the connection class
# (08xxx, 57P01 admin shutdown, 53300 too many connections: indeterminate at the write call).
_SQL_STATE_ALLOWED = re.compile(r"^SQL_(40001|40P01|08[0-9A-Z]{3}|57P01|53300)$")


def _safe_code(code: object, fallback: str) -> str:
    """Outward error code: only known promotion codes and allow-listed SQL states pass.

    Any other well-formed SQL state is the fixed ``SQL_ERROR``; a raw exception class name or an
    arbitrary code text (possibly attacker- or database-controlled) is never returned."""
    if type(code) is not str:
        return fallback
    if (code in _PORT_CODES or code in _ROLLED_BACK_CODES or code in _NO_READ_RIGHT
            or _SQL_STATE_ALLOWED.fullmatch(code)):
        return code
    if _SQL_STATE_CODE.fullmatch(code):
        return "SQL_ERROR"
    return fallback


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
            target = _accepted_at(await self._port.list_acceptances(approver, scope), model_key,
                                  to_version)
            if target is None:
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
        # Idempotent replay (mirrors living.promote_head): decided before any time-dependent guard.
        try:
            accepted = await self._port.list_acceptances(approver, scope)
        except PortError as exc:
            if type(exc.code) is not str or exc.code not in _NO_READ_RIGHT:
                raise  # transient read failure: never mask a possibly committed promotion as a rejection
            accepted = ()  # no read right: the normal guards below still fail closed / reject
        recorded = next((a for a in accepted if a.acceptance_id == acceptance_id), None)
        if recorded is not None:
            if (recorded.model_key == model_key and recorded.from_version == expected_version
                    and recorded.accepted_revision == candidate
                    and recorded.approver_subject == approver
                    and recorded.independent_evidence_ref == evidence.evidence_ref):
                return PromotionResult(success, new_version=recorded.to_version)
            return PromotionResult(Outcome.REJECTED_ACCEPTANCE_ID, code="ACCEPTANCE_ID_REUSED")
        if success is Outcome.ROLLED_BACK:
            head = await self._port.get_head(approver, scope, model_key)
            if (head is not None and head.version == expected_version
                    and head.revision_id == candidate):
                return PromotionResult(Outcome.REJECTED_TARGET, code="ROLLBACK_TARGET_UNKNOWN")
        att = await self._reader.find_attestation(scope, candidate, evidence.evidence_ref)
        if att is not None and (att.revision_id != candidate
                                or att.evidence_ref != evidence.evidence_ref):
            return PromotionResult(Outcome.REJECTED_EVIDENCE, code="ATTESTATION_MISMATCH")
        if att is None or att.decision != "APPROVE":
            return PromotionResult(Outcome.REJECTED_EVIDENCE, code="EVIDENCE_NOT_APPROVED")
        if att.revoked_at is not None:
            return PromotionResult(Outcome.REJECTED_REVOKED, code="EVIDENCE_REVOKED")
        if att.expires_at <= self._clock():
            return PromotionResult(Outcome.REJECTED_EXPIRED, code="EVIDENCE_EXPIRED")
        recomputed = evidence_digest(evidence.revision_digest, evidence.evidence_ref)
        if not isinstance(att.evidence_digest, str) or not hmac.compare_digest(
                att.evidence_digest.encode("utf-8"), recomputed.encode("utf-8")):
            return PromotionResult(Outcome.REJECTED_EVIDENCE, code="EVIDENCE_DIGEST_MISMATCH")
        if await self._reader.is_trusted_reviewer(scope, att.observer) is not True:
            return PromotionResult(Outcome.REJECTED_UNTRUSTED, code="REVIEWER_NOT_TRUSTED")
        observer_id, proposer_id = normalize_identity(att.observer), normalize_identity(att.proposer)
        if not observer_id or not proposer_id:  # an invalid id is never a distinct person
            return PromotionResult(Outcome.REJECTED_SELF_APPROVAL, code="APPROVER_NOT_INDEPENDENT")
        if approver_id in (observer_id, proposer_id):
            return PromotionResult(Outcome.REJECTED_SELF_APPROVAL, code="APPROVER_NOT_INDEPENDENT")
        head = await self._port.get_head(approver, scope, model_key)
        if head is None or head.version != expected_version:
            return PromotionResult(Outcome.REJECTED_CAS, code="STALE_ACCEPTED_HEAD")
        try:
            version = await self._port.promote_head(
                approver, scope, model_key, expected_version, candidate, acceptance_id,
                evidence.evidence_ref)
        except PortError as exc:  # typed SQL rejection: the transaction rolled back, nothing written
            if type(exc.code) is not str:  # unhashable/non-text code: never raise, the commit may have landed
                return PromotionResult(Outcome.INDETERMINATE, code="WRITE_RESULT_UNKNOWN")
            outcome = _PORT_CODES.get(exc.code)
            if outcome is not None:
                return PromotionResult(outcome, code=exc.code)
            if exc.code in _ROLLED_BACK_CODES:
                return PromotionResult(Outcome.FAILED_CLOSED, code=_safe_code(exc.code, "PORT_REJECTED"))
            # unknown code (e.g. a connection error while committing): the commit may have landed
            return PromotionResult(Outcome.INDETERMINATE,
                                   code=_safe_code(exc.code, "WRITE_RESULT_UNKNOWN"))
        except Exception:  # noqa: BLE001 - the commit may have happened; fixed code, no class name
            return PromotionResult(Outcome.INDETERMINATE, code="WRITE_EXCEPTION")
        if type(version) is not int or version != expected_version + 1:
            return PromotionResult(Outcome.INDETERMINATE, code="UNEXPECTED_VERSION")
        return PromotionResult(success, new_version=version)

    @staticmethod
    def _failed(exc: Exception) -> PromotionResult:
        code = (_safe_code(exc.code, "PREWRITE_PORT_ERROR") if isinstance(exc, PortError)
                else "PREWRITE_FAILURE")
        return PromotionResult(Outcome.FAILED_CLOSED, code=code)


def _accepted_at(acceptances: tuple[AcceptanceView, ...], model_key: str,
                 version: int) -> AcceptanceView | None:
    return next((a for a in acceptances
                 if a.model_key == model_key and a.to_version == version), None)
