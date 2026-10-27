"""Bounded production lookup and re-verification of persisted writer evidence.

The adapter reads only exact immutable envelope references through the candidate SQL routine.
It has no table grants and performs no write. Its result is provisional evidence, not authority to
register records or release a safety hold; terminal SQL remains responsible for those transitions.
"""
from __future__ import annotations

import asyncio
import math
import time
from uuid import UUID

import asyncpg

from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
)
from business_ai_gateway.phase2.change_ledger.uuid_contract import is_canonical_nonzero_uuid

from .evidence_trust import EvidenceScope
from .postgres_attempt_source import (
    EvidenceAttemptSourceError,
    PostgresEvidenceAttemptSource,
)
from .postgres_evidence_trust import PostgresEvidenceTrustSource
from .postgres_identity import EVIDENCE_INGEST_SESSION_USER, has_expected_database_identity
from .production_evidence_verifier import (
    ProductionEvidenceVerificationError,
    ProductionEvidenceVerifier,
    VerifiedEvidenceRecord,
)
from .service import (
    CallIdentity,
    ConditionalConflictTerminalRecords,
    ResolvedReceiptEvidence,
)

_MAX_TIMEOUT_SECONDS = 5.0
_MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
_MAX_EVIDENCE_REF_BYTES = 256
_RECORD_NAMES = {
    DispatchReceipt: ("DISPATCH_NO_ENTRY_RECEIPT_V1", "DISPATCH_RECEIPT_V1"),
    OutcomeEvidenceV3: ("OUTCOME_EVIDENCE_V3",),
    CompletionProof: ("COMPLETION_PROOF_V1",),
    PostCompletionChallenge: ("POST_COMPLETION_CHALLENGE_V1",),
    PostCompletionReadAttestation: ("POST_COMPLETION_READ_ATTESTATION_V1",),
}


class WriterEvidenceResolutionError(RuntimeError):
    """Stable resolver refusals without database rows or envelope contents."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PostgresWriterEvidenceResolver:
    """Load exact signed records and verify them against one fresh production trust snapshot."""

    __slots__ = ("_attempt_source", "_pool", "_timeout", "_verifier")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("WRITER_EVIDENCE_RESOLVER_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("WRITER_EVIDENCE_RESOLVER_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool,
                 attempt_source: PostgresEvidenceAttemptSource,
                 verifier: ProductionEvidenceVerifier, *, timeout_seconds: float = 3.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("WRITER_EVIDENCE_POOL_INVALID")
        if (type(attempt_source) is not PostgresEvidenceAttemptSource
                or getattr(attempt_source, "_pool", None) is not pool):
            raise ValueError("WRITER_EVIDENCE_ATTEMPT_SOURCE_INVALID")
        if type(verifier) is not ProductionEvidenceVerifier:
            raise ValueError("WRITER_EVIDENCE_VERIFIER_INVALID")
        trust_source = getattr(verifier, "_source", None)
        if (type(trust_source) is not PostgresEvidenceTrustSource
                or getattr(trust_source, "_pool", None) is not pool):
            raise ValueError("WRITER_EVIDENCE_TRUST_SOURCE_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("WRITER_EVIDENCE_TIMEOUT_INVALID")
        self._pool = pool
        self._attempt_source = attempt_source
        self._verifier = verifier
        self._timeout = float(timeout_seconds)

    async def load_receipt(self, identity: CallIdentity, dispatch_cas_id: UUID,
                           receipt_ref: str) -> ResolvedReceiptEvidence:
        self._check_request(identity, dispatch_cas_id, (receipt_ref,))
        attempt_context = await self._load_attempt(identity, dispatch_cas_id)
        envelopes, record_types = await self._load_envelopes(
            identity, dispatch_cas_id, (receipt_ref,),
        )
        verified = await self._verify(envelopes, attempt_context.attempt)
        if (len(verified) != 1 or type(verified[0].record) is not DispatchReceipt
                or record_types[0] not in _RECORD_NAMES[DispatchReceipt]
                or self.evidence_ref(verified[0].record) != receipt_ref):
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_VERIFICATION_INVALID")
        receipt = verified[0].record
        return ResolvedReceiptEvidence(
            attempt_context.attempt, receipt, verified[0],
            EvidenceScope(identity.tenant_id, identity.company_id,
                          identity.organization_ref, identity.base_fingerprint),
        )

    async def load_conditional_conflict_terminal_records(
            self, identity: CallIdentity, dispatch_cas_id: UUID,
            receipt_ref: str, outcome_evidence_ref: str,
            completion_proof_ref: str, post_completion_challenge_ref: str,
            read_attestation_ref: str) -> ConditionalConflictTerminalRecords:
        refs = (receipt_ref, outcome_evidence_ref, completion_proof_ref,
                post_completion_challenge_ref, read_attestation_ref)
        self._check_request(identity, dispatch_cas_id, refs)
        attempt_context = await self._load_attempt(identity, dispatch_cas_id)
        envelopes, record_types = await self._load_envelopes(identity, dispatch_cas_id, refs)
        verified = await self._verify(envelopes, attempt_context.attempt)
        records = tuple(value.record for value in verified)
        expected_types = (DispatchReceipt, OutcomeEvidenceV3, CompletionProof,
                          PostCompletionChallenge, PostCompletionReadAttestation)
        if (tuple(type(value) for value in records) != expected_types
                or any(record_type not in _RECORD_NAMES[type(record)]
                       for record_type, record in zip(record_types, records, strict=True))
                or any(self.evidence_ref(record) != reference
                       for record, reference in zip(records, refs, strict=True))):
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_RECORD_SET_INVALID")
        if (len(verified) != 5
                or any(value.record is not record
                       for value, record in zip(verified, records, strict=True))):
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_VERIFICATION_INVALID")
        return ConditionalConflictTerminalRecords(
            attempt=attempt_context.attempt,
            receipt=records[0],
            outcome=records[1],
            completion=records[2],
            post_completion_challenge=records[3],
            read_attestation=records[4],
            verified_records=verified,
            expected_scope=EvidenceScope(
                identity.tenant_id, identity.company_id,
                identity.organization_ref, identity.base_fingerprint,
            ),
        )

    async def _load_attempt(self, identity: CallIdentity, dispatch_cas_id: UUID):
        try:
            context = await self._attempt_source.load_for_identity(
                dispatch_cas_id=dispatch_cas_id, call_id=identity.call_id,
                tenant_id=identity.tenant_id, company_id=identity.company_id,
                organization_ref=identity.organization_ref,
                base_fingerprint=identity.base_fingerprint,
            )
        except EvidenceAttemptSourceError:
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_ATTEMPT_UNAVAILABLE") from None
        attempt = context.attempt
        if (type(attempt) is not DispatchAttempt
                or attempt.dispatch_cas_id != str(dispatch_cas_id)
                or attempt.call_id != identity.call_id
                or attempt.tenant_id != identity.tenant_id
                or attempt.company_id != identity.company_id
                or attempt.organization_ref != identity.organization_ref
                or attempt.base_fingerprint != identity.base_fingerprint
                or attempt.change_id != identity.change_id
                or attempt.claim_generation != identity.generation
                or attempt.operation_kind != identity.operation
                or attempt.auth_epoch != identity.epoch
                or attempt.permit_id != identity.permit_id
                or attempt.permit_digest != identity.permit_digest
                or attempt.expected_target_ref != identity.target_ref
                or attempt.expected_pre_version != identity.target_version
                or context.payload_digest != identity.payload_digest
                or context.repair_authorization_id != identity.repair_authorization_id
                or attempt.writer_host_id != identity.host_id):
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_ATTEMPT_MISMATCH")
        return context

    async def _load_envelopes(self, identity: CallIdentity, dispatch_cas_id: UUID,
                              refs: tuple[str, ...]) -> tuple[tuple[bytes, ...], tuple[str, ...]]:
        deadline = time.monotonic() + self._timeout
        try:
            async with asyncio.timeout(self._timeout):
                async with self._pool.acquire(timeout=self._timeout) as conn:
                    if conn.is_in_transaction():
                        raise WriterEvidenceResolutionError("WRITER_EVIDENCE_OUTCOME_UNKNOWN")
                    transaction = conn.transaction()
                    try:
                        await transaction.start()
                    except BaseException:
                        conn.terminate()
                        raise
                    try:
                        await self._execute(conn, deadline,
                                            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        await self._execute(
                            conn, deadline,
                            "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                            f"{max(1, math.ceil(remaining * 1000))}ms",
                        )
                        if not await has_expected_database_identity(
                                conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                            raise WriterEvidenceResolutionError(
                                "WRITER_EVIDENCE_DATABASE_IDENTITY_INVALID",
                            )
                        rows = await self._fetch_rows(conn, deadline, identity,
                                                      dispatch_cas_id, refs)
                        envelopes = self._validate_rows(rows, refs)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            await transaction.commit()
                        return envelopes
                    except BaseException:
                        try:
                            if conn.is_in_transaction():
                                remaining = max(0.001, min(1.0, deadline - time.monotonic()))
                                async with asyncio.timeout(remaining):
                                    await transaction.rollback()
                        except BaseException:
                            conn.terminate()
                        raise
        except WriterEvidenceResolutionError:
            raise
        except asyncpg.PostgresError as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            message = getattr(exc, "message", None)
            if sqlstate == "57014":
                raise WriterEvidenceResolutionError("WRITER_EVIDENCE_LOOKUP_TIMEOUT") from None
            if sqlstate == "42501" and message == "NOT_ENTITLED":
                raise WriterEvidenceResolutionError("WRITER_EVIDENCE_NOT_FOUND") from None
            if sqlstate == "P0001" and message == "SCHEMA_INVALID":
                raise WriterEvidenceResolutionError("WRITER_EVIDENCE_REQUEST_INVALID") from None
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_LOOKUP_FAILED") from None
        except TimeoutError:
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_LOOKUP_TIMEOUT") from None
        except Exception:
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_LOOKUP_FAILED") from None

    async def _fetch_rows(self, conn: asyncpg.Connection, deadline: float,
                          identity: CallIdentity, dispatch_cas_id: UUID,
                          refs: tuple[str, ...]):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            return await conn.fetch(
                "SELECT evidence_ref,record_type,signed_bytes FROM "
                "change_ledger.private_writer_load_evidence_records_v1(" 
                "$1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                dispatch_cas_id, UUID(identity.call_id), identity.tenant_id,
                identity.company_id, identity.organization_ref, identity.base_fingerprint,
                UUID(identity.change_id), identity.generation, identity.operation, list(refs),
            )

    @classmethod
    def _validate_rows(cls, rows: object, refs: tuple[str, ...]
                       ) -> tuple[tuple[bytes, ...], tuple[str, ...]]:
        try:
            if type(rows) is not list or len(rows) != len(refs):
                raise ValueError
            envelopes: list[bytes] = []
            record_types: list[str] = []
            for row, expected_ref in zip(rows, refs, strict=True):
                if (row["evidence_ref"] != expected_ref
                        or type(row["record_type"]) is not str
                        or row["record_type"] not in {
                            name for values in _RECORD_NAMES.values() for name in values
                        }
                        or type(row["signed_bytes"]) is not bytes
                        or not 1 <= len(row["signed_bytes"]) <= _MAX_ENVELOPE_BYTES):
                    raise ValueError
                envelopes.append(row["signed_bytes"])
                record_types.append(row["record_type"])
            return tuple(envelopes), tuple(record_types)
        except Exception:
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_RECORD_SET_INVALID") from None

    async def _verify(self, envelopes: tuple[bytes, ...],
                      attempt: DispatchAttempt) -> tuple[VerifiedEvidenceRecord, ...]:
        try:
            verified = await self._verifier.verify_set(envelopes, attempt=attempt)
        except ProductionEvidenceVerificationError:
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_VERIFICATION_FAILED") from None
        except Exception:
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_VERIFICATION_FAILED") from None
        if (type(verified) is not tuple or not verified
                or any(type(value) is not VerifiedEvidenceRecord for value in verified)):
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_VERIFICATION_INVALID")
        return verified

    @staticmethod
    def evidence_ref(record: object) -> str:
        """Derive the canonical immutable reference from the parsed signed record."""
        if type(record) is DispatchReceipt:
            name = ("DISPATCH_NO_ENTRY_RECEIPT_V1" if record.result_class == "PRE_WRITE_NO_EFFECT"
                    else "DISPATCH_RECEIPT_V1")
        elif type(record) is OutcomeEvidenceV3:
            name = "OUTCOME_EVIDENCE_V3"
        elif type(record) is CompletionProof:
            name = "COMPLETION_PROOF_V1"
        elif type(record) is PostCompletionChallenge:
            name = "POST_COMPLETION_CHALLENGE_V1"
        elif type(record) is PostCompletionReadAttestation:
            name = "POST_COMPLETION_READ_ATTESTATION_V1"
        else:
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_RECORD_TYPE_INVALID")
        return f"private-writer:evidence:v1:{name}:{record.calculated_digest()}"

    @staticmethod
    def _check_request(identity: CallIdentity, dispatch_cas_id: UUID,
                       refs: tuple[str, ...]) -> None:
        if (type(identity) is not CallIdentity or type(dispatch_cas_id) is not UUID
                or dispatch_cas_id.int == 0 or not is_canonical_nonzero_uuid(identity.call_id)
                or not is_canonical_nonzero_uuid(identity.change_id)
                or type(refs) is not tuple or not 1 <= len(refs) <= 5
                or any(type(value) is not str or not value or value != value.strip()
                       or not value.isascii() or len(value) > _MAX_EVIDENCE_REF_BYTES
                       or any(ord(character) < 32 or ord(character) == 127 for character in value)
                       for value in refs)):
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_REQUEST_INVALID")
        if len(set(refs)) != len(refs):
            raise WriterEvidenceResolutionError("WRITER_EVIDENCE_REQUEST_INVALID")

    @staticmethod
    async def _execute(conn: asyncpg.Connection, deadline: float,
                       query: str, *args: object) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            await conn.execute(query, *args)


__all__ = ["PostgresWriterEvidenceResolver", "WriterEvidenceResolutionError"]
