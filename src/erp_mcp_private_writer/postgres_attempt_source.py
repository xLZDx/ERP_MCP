"""Exact-scope immutable dispatch-attempt lookup for the evidence-ingest principal.

The injected pool must authenticate directly as ``private_writer_evidence_ingest``. The matching
SQL routine is candidate-only and its EXECUTE/result-type privileges remain withheld pending
independent database/security review. This adapter grants no authority to register evidence.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from uuid import UUID

import asyncpg

from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidence,
    OutcomeEvidenceV2,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
)
from business_ai_gateway.phase2.change_ledger.uuid_contract import is_canonical_nonzero_uuid
from .postgres_identity import (
    EVIDENCE_INGEST_SESSION_USER,
    has_expected_database_identity,
)


_MAX_TIMEOUT_SECONDS = 5.0
# Nine SQL-bounded text columns can each occupy 2,048 UTF-8 bytes and expand sixfold when
# PostgreSQL JSON-escapes control bytes; 128 KiB leaves bounded room for the fixed field names.
_MAX_CONTEXT_JSON_BYTES = 128 * 1024
_CONTEXT_JSON_SIZE_CHUNK = 16 * 1024
_CONTEXT_FIELDS = frozenset({
    "dispatch_cas_id", "dispatch_intent_id", "tenant_id", "company_id",
    "organization_ref", "base_fingerprint", "change_id", "claim_generation",
    "dispatch_generation", "call_id", "operation_kind", "approval_digest",
    "payload_digest", "permit_id", "permit_digest", "expected_target_ref",
    "expected_pre_version", "auth_epoch", "repair_authorization_id",
    "writer_service_id", "writer_host_id", "writer_process_instance_id",
    "onec_session_instance_id",
})
_RECORD_TYPES = (
    DispatchReceipt, OutcomeEvidence, OutcomeEvidenceV2, OutcomeEvidenceV3,
    CompletionProof, PostCompletionChallenge, PostCompletionReadAttestation,
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError


def _check_context_json_size(payload: str) -> None:
    """Reject oversized text without allocating a second copy of the whole payload."""
    if len(payload) > _MAX_CONTEXT_JSON_BYTES:
        raise ValueError
    byte_size = 0
    for offset in range(0, len(payload), _CONTEXT_JSON_SIZE_CHUNK):
        chunk = payload[offset:offset + _CONTEXT_JSON_SIZE_CHUNK]
        byte_size += len(chunk.encode("utf-8", errors="strict"))
        if byte_size > _MAX_CONTEXT_JSON_BYTES:
            raise ValueError


class EvidenceAttemptSourceError(RuntimeError):
    """Stable exact-attempt lookup failures without database details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class EvidenceAttemptContext:
    """Immutable database context needed to validate and register one signed envelope."""

    attempt: DispatchAttempt
    dispatch_intent_id: str
    payload_digest: str
    repair_authorization_id: str | None

    def __post_init__(self) -> None:
        if (type(self.attempt) is not DispatchAttempt
                or type(self.dispatch_intent_id) is not str
                or type(self.payload_digest) is not str
                or len(self.payload_digest) != 64
                or any(character not in "0123456789abcdef" for character in self.payload_digest)
                or (self.repair_authorization_id is not None
                    and type(self.repair_authorization_id) is not str)):
            raise ValueError("EVIDENCE_ATTEMPT_CONTEXT_INVALID")
        if (not is_canonical_nonzero_uuid(self.dispatch_intent_id)
                or (self.repair_authorization_id is not None
                    and not is_canonical_nonzero_uuid(self.repair_authorization_id))):
            raise ValueError("EVIDENCE_ATTEMPT_CONTEXT_INVALID") from None


class PostgresEvidenceAttemptSource:
    """Read one immutable dispatch attempt through the exact-selector SQL function."""

    __slots__ = ("_pool", "_timeout")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("EVIDENCE_ATTEMPT_SOURCE_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("EVIDENCE_ATTEMPT_SOURCE_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool, *, timeout_seconds: float = 3.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("EVIDENCE_ATTEMPT_POOL_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("EVIDENCE_ATTEMPT_TIMEOUT_INVALID")
        self._pool = pool
        self._timeout = float(timeout_seconds)

    async def load_for_record(self, record: object) -> EvidenceAttemptContext:
        """Return the exact attempt selected by signed identity and full database scope."""
        selectors = self._selectors(record)
        return await self._load_for_selectors(selectors)

    async def load_for_identity(self, *, dispatch_cas_id: UUID, call_id: str,
                                tenant_id: str, company_id: str,
                                organization_ref: str,
                                base_fingerprint: str) -> EvidenceAttemptContext:
        """Load by explicit CAS and caller identity when an envelope lacks a CAS field."""
        values = (tenant_id, company_id, organization_ref, base_fingerprint)
        if (type(dispatch_cas_id) is not UUID or dispatch_cas_id.int == 0
                or any(type(value) is not str or not value or value != value.strip()
                       or len(value) > 128
                       or any(ord(character) < 32 or ord(character) == 127 for character in value)
                       for value in values)
                or type(call_id) is not str):
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_REQUEST_INVALID")
        if not is_canonical_nonzero_uuid(call_id):
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_REQUEST_INVALID") from None
        parsed_call_id = UUID(call_id)
        return await self._load_for_selectors(
            (dispatch_cas_id, parsed_call_id, tenant_id, company_id,
             organization_ref, base_fingerprint),
        )

    async def _load_for_selectors(self, selectors: tuple[object, ...]) -> EvidenceAttemptContext:
        deadline = time.monotonic() + self._timeout
        try:
            async with asyncio.timeout(self._timeout):
                async with self._pool.acquire(timeout=self._timeout) as conn:
                    if conn.is_in_transaction():
                        raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_OUTCOME_UNKNOWN")
                    transaction = conn.transaction()
                    try:
                        await transaction.start()
                    except BaseException:
                        conn.terminate()
                        raise
                    try:
                        await self._execute_before_deadline(
                            conn, deadline,
                            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY",
                        )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        timeout_ms = max(1, math.ceil(remaining * 1000))
                        await self._execute_before_deadline(
                            conn, deadline,
                            "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                            f"{timeout_ms}ms",
                        )
                        if not await has_expected_database_identity(
                                conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                            raise EvidenceAttemptSourceError(
                                "EVIDENCE_ATTEMPT_DATABASE_IDENTITY_INVALID",
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            payload = await conn.fetchval(
                                "SELECT pg_catalog.to_jsonb(change_ledger."
                                "private_writer_evidence_attempt_v1($1,$2,$3,$4,$5,$6))",
                                *selectors,
                            )
                        if payload is None or payload == "null":
                            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_NOT_FOUND")
                        context = self._decode(payload)
                        if (context.attempt.dispatch_cas_id != str(selectors[0])
                                or context.attempt.call_id != str(selectors[1])
                                or context.attempt.tenant_id != selectors[2]
                                or context.attempt.company_id != selectors[3]
                                or context.attempt.organization_ref != selectors[4]
                                or context.attempt.base_fingerprint != selectors[5]):
                            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_CONTEXT_INVALID")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            await transaction.commit()
                        return context
                    except BaseException:
                        try:
                            if conn.is_in_transaction():
                                remaining = max(0.001, min(1.0, deadline - time.monotonic()))
                                async with asyncio.timeout(remaining):
                                    await transaction.rollback()
                        except BaseException:
                            conn.terminate()
                        raise
        except EvidenceAttemptSourceError:
            raise
        except asyncpg.PostgresError as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            message = getattr(exc, "message", None)
            if sqlstate == "P0001" and message == "EVIDENCE_ATTEMPT_CONTEXT_INVALID":
                raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_CONTEXT_INVALID") from None
            if sqlstate == "P0001" and message == "SCHEMA_INVALID":
                raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_REQUEST_INVALID") from None
            if sqlstate == "57014":
                raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_LOOKUP_TIMEOUT") from None
            if sqlstate == "42501":
                raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_NOT_AUTHORIZED") from None
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_LOOKUP_FAILED") from None
        except (TimeoutError, asyncio.TimeoutError):
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_LOOKUP_TIMEOUT") from None
        except Exception:
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_LOOKUP_FAILED") from None

    @staticmethod
    def _selectors(record: object) -> tuple[object, ...]:
        if type(record) not in _RECORD_TYPES:
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_REQUEST_INVALID")
        names = (
            "dispatch_cas_id", "call_id", "tenant_id", "company_id",
            "organization_ref", "base_fingerprint",
        )
        if any(type(getattr(record, name, None)) is not str
               or not getattr(record, name, "") for name in names):
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_REQUEST_INVALID")
        selectors = tuple(getattr(record, name) for name in names)
        if (not is_canonical_nonzero_uuid(selectors[0])
                or not is_canonical_nonzero_uuid(selectors[1])):
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_REQUEST_INVALID") from None
        dispatch_cas_id = UUID(selectors[0])
        call_id = UUID(selectors[1])
        return (dispatch_cas_id, call_id, *selectors[2:])

    @staticmethod
    async def _execute_before_deadline(conn: asyncpg.Connection, deadline: float,
                                       query: str, *args: object) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            await conn.execute(query, *args)

    @staticmethod
    def _decode(payload: object) -> EvidenceAttemptContext:
        try:
            if type(payload) is not str:
                raise ValueError
            _check_context_json_size(payload)
            document = json.loads(
                payload, object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
                parse_float=_reject_json_constant,
            )
            if type(document) is not dict or set(document) != _CONTEXT_FIELDS:
                raise ValueError
            if any(type(document[name]) is not str for name in (
                    "dispatch_cas_id", "dispatch_intent_id", "tenant_id", "company_id",
                    "organization_ref", "base_fingerprint", "change_id", "call_id",
                    "operation_kind", "approval_digest", "payload_digest", "permit_id",
                    "permit_digest", "writer_service_id", "writer_host_id",
                    "writer_process_instance_id")):
                raise ValueError
            if any(type(document[name]) is not int for name in (
                    "claim_generation", "dispatch_generation", "auth_epoch")):
                raise ValueError
            if any(type(document[name]) not in (str, type(None)) for name in (
                    "expected_target_ref", "expected_pre_version", "repair_authorization_id",
                    "onec_session_instance_id")):
                raise ValueError
            attempt = DispatchAttempt(
                tenant_id=document["tenant_id"], company_id=document["company_id"],
                organization_ref=document["organization_ref"],
                base_fingerprint=document["base_fingerprint"], change_id=document["change_id"],
                claim_generation=document["claim_generation"],
                dispatch_generation=document["dispatch_generation"],
                dispatch_cas_id=document["dispatch_cas_id"], call_id=document["call_id"],
                operation_kind=document["operation_kind"],
                approval_digest=document["approval_digest"], auth_epoch=document["auth_epoch"],
                permit_id=document["permit_id"], permit_digest=document["permit_digest"],
                expected_target_ref=document["expected_target_ref"],
                expected_pre_version=document["expected_pre_version"],
                writer_service_id=document["writer_service_id"],
                writer_host_id=document["writer_host_id"],
                writer_process_instance_id=document["writer_process_instance_id"],
                onec_session_instance_id=document["onec_session_instance_id"],
            )
            return EvidenceAttemptContext(
                attempt=attempt, dispatch_intent_id=document["dispatch_intent_id"],
                payload_digest=document["payload_digest"],
                repair_authorization_id=document["repair_authorization_id"],
            )
        except EvidenceAttemptSourceError:
            raise
        except Exception:
            raise EvidenceAttemptSourceError("EVIDENCE_ATTEMPT_CONTEXT_INVALID") from None


__all__ = ["EvidenceAttemptContext", "EvidenceAttemptSourceError", "PostgresEvidenceAttemptSource"]
