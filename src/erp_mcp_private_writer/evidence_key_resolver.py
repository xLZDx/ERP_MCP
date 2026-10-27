"""Least-privilege PostgreSQL lookup for keys used to validate private-writer evidence.

The injected pool must authenticate directly as ``private_writer_evidence_ingest``. The database
function performs scope, role, service, host, validity-window, and revocation checks without
granting this process direct table access. This adapter only selects candidate public key bytes;
the caller must still verify the signature and independently validate the evidence envelope.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from datetime import datetime, timezone

import asyncpg

from .postgres_identity import (
    EVIDENCE_INGEST_SESSION_USER,
    has_expected_database_identity,
)


_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}\Z")
_SIGNER_ROLES = frozenset({
    "writer_receipt", "verification_worker", "completion_supervisor", "read_attestor",
    "checkpoint_signer",
})
_MAX_TIMEOUT_SECONDS = 5.0


class EvidenceKeyResolutionError(RuntimeError):
    """Stable errors that do not reveal connection, privilege, or PostgreSQL details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PostgresEvidenceKeyResolver:
    """Resolve one registered public key through the narrowly granted SQL routine.

    The pool is supplied by the host so authentication and secret handling remain outside this
    module. It is intentionally separate from ``PostgresAdmissionStore``: the latter must use the
    writer identity, while this routine rejects every session except evidence-ingest.
    """

    __slots__ = ("_pool", "_timeout")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("EVIDENCE_KEY_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("EVIDENCE_KEY_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool, *, timeout_seconds: float = 3.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("EVIDENCE_KEY_POOL_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("EVIDENCE_KEY_TIMEOUT_INVALID")
        self._pool = pool
        self._timeout = float(timeout_seconds)

    async def resolve(self, *, key_id: str, key_version: str, signer_role: str,
                      service_id: str, host_id: str, tenant_id: str, company_id: str,
                      organization_ref: str, base_fingerprint: str,
                      signed_at: datetime) -> bytes:
        """Return exactly 32 public-key bytes or fail closed with a stable error code."""
        self._validate(
            key_id=key_id, key_version=key_version, signer_role=signer_role,
            service_id=service_id, host_id=host_id, tenant_id=tenant_id,
            company_id=company_id, organization_ref=organization_ref,
            base_fingerprint=base_fingerprint, signed_at=signed_at,
        )
        deadline = time.monotonic() + self._timeout
        try:
            async with asyncio.timeout(self._timeout):
                async with self._pool.acquire(timeout=self._timeout) as conn:
                    if conn.is_in_transaction():
                        raise EvidenceKeyResolutionError("EVIDENCE_KEY_OUTCOME_UNKNOWN")
                    transaction = conn.transaction()
                    try:
                        await transaction.start()
                    except BaseException:
                        conn.terminate()
                        raise
                    try:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            await conn.execute(
                                "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY"
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        timeout_ms = max(1, math.ceil(remaining * 1000))
                        async with asyncio.timeout(remaining):
                            await conn.execute(
                                "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                                f"{timeout_ms}ms",
                            )
                        if not await has_expected_database_identity(
                                conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                            raise EvidenceKeyResolutionError(
                                "EVIDENCE_KEY_DATABASE_IDENTITY_INVALID",
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            public_key = await conn.fetchval(
                                "SELECT change_ledger.private_writer_resolve_signer_key_v1("
                                "$1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                                key_id, key_version, signer_role, service_id, host_id,
                                tenant_id, company_id, organization_ref, base_fingerprint,
                                signed_at.astimezone(timezone.utc),
                            )
                        if type(public_key) is not bytes or len(public_key) != 32:
                            raise EvidenceKeyResolutionError("EVIDENCE_KEY_UNAVAILABLE")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            await transaction.commit()
                        return public_key
                    except BaseException:
                        try:
                            if conn.is_in_transaction():
                                remaining = max(0.001, min(1.0, deadline - time.monotonic()))
                                async with asyncio.timeout(remaining):
                                    await transaction.rollback()
                        except BaseException:
                            conn.terminate()
                        raise
        except EvidenceKeyResolutionError:
            raise
        except asyncpg.PostgresError as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if sqlstate == "P0001" and "EVIDENCE_KEY_TRANSACTION_INVALID" in str(exc):
                raise EvidenceKeyResolutionError("EVIDENCE_KEY_TRANSACTION_INVALID") from None
            if sqlstate == "P0001" and "EVIDENCE_KEY_UNAVAILABLE" in str(exc):
                raise EvidenceKeyResolutionError("EVIDENCE_KEY_UNAVAILABLE") from None
            if sqlstate == "57014":
                raise EvidenceKeyResolutionError("EVIDENCE_KEY_LOOKUP_TIMEOUT") from None
            raise EvidenceKeyResolutionError("EVIDENCE_KEY_LOOKUP_FAILED") from None
        except (TimeoutError, asyncio.TimeoutError):
            raise EvidenceKeyResolutionError("EVIDENCE_KEY_LOOKUP_TIMEOUT") from None
        except Exception:
            raise EvidenceKeyResolutionError("EVIDENCE_KEY_LOOKUP_FAILED") from None

    @staticmethod
    def _validate(*, key_id: str, key_version: str, signer_role: str, service_id: str,
                  host_id: str, tenant_id: str, company_id: str, organization_ref: str,
                  base_fingerprint: str, signed_at: datetime) -> None:
        for value, max_length in (
            (key_id, 128), (key_version, 64), (service_id, 128), (host_id, 128),
            (tenant_id, 128), (company_id, 128), (organization_ref, 128),
        ):
            if (type(value) is not str or not value or len(value) > max_length
                    or value != value.strip()
                    or any(ord(character) < 32 or ord(character) == 127 for character in value)):
                raise EvidenceKeyResolutionError("EVIDENCE_KEY_REQUEST_INVALID")
        if (type(signer_role) is not str or signer_role not in _SIGNER_ROLES
                or type(base_fingerprint) is not str
                or not _FINGERPRINT_RE.fullmatch(base_fingerprint)
                or type(signed_at) is not datetime or signed_at.tzinfo is None
                or signed_at.utcoffset() is None):
            raise EvidenceKeyResolutionError("EVIDENCE_KEY_REQUEST_INVALID")


__all__ = ["EvidenceKeyResolutionError", "PostgresEvidenceKeyResolver"]
