"""Read-only, transaction-bounded trust snapshot loader for S13 barrier verification."""
from __future__ import annotations

import asyncio
import json
import math
import time

import asyncpg

from business_ai_gateway.phase2.change_ledger.write_port import BarrierAcknowledgement

from .barrier_ack_protocol import (
    barrier_acknowledgement_record_json,
    validate_barrier_acknowledgement,
)
from .barrier_ack_verifier import BarrierAcknowledgementTrustContext
from .postgres_evidence_trust import (
    PostgresEvidenceTrustSource,
    _bounded_json_integer,
    _check_json_text_limits,
    _measure_json_value,
    _reject_nonfinite_constant,
    _scope,
    _unique_object,
)
from .postgres_identity import EVIDENCE_INGEST_SESSION_USER, has_expected_database_identity

_MAX_TIMEOUT_SECONDS = 5.0
_MAX_PAYLOAD_CHARS = 16 * 1024 * 1024
_MAX_SCOPES = 4096


class BarrierAcknowledgementTrustSourceError(RuntimeError):
    """Stable read failures without PostgreSQL, principal, or trust-registry details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PostgresBarrierAcknowledgementTrustSource:
    """Load one coherent trust snapshot through the revoked-by-default S13 SQL routine."""

    __slots__ = ("_pool", "_timeout")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("BARRIER_ACK_TRUST_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("BARRIER_ACK_TRUST_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool, *, timeout_seconds: float = 3.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("BARRIER_ACK_TRUST_POOL_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("BARRIER_ACK_TRUST_TIMEOUT_INVALID")
        self._pool = pool
        self._timeout = float(timeout_seconds)

    async def load_barrier_snapshot(
            self, acknowledgement: BarrierAcknowledgement
    ) -> BarrierAcknowledgementTrustContext:
        try:
            validate_barrier_acknowledgement(acknowledgement)
        except Exception:
            raise BarrierAcknowledgementTrustSourceError(
                "BARRIER_ACK_TRUST_REQUEST_INVALID",
            ) from None
        deadline = time.monotonic() + self._timeout
        try:
            async with self._pool.acquire(timeout=self._timeout) as conn:
                payload = await self._load_on_connection(
                    conn, acknowledgement, deadline,
                )
            return self._decode(payload)
        except BarrierAcknowledgementTrustSourceError:
            raise
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise BarrierAcknowledgementTrustSourceError(
                "BARRIER_ACK_TRUST_TIMEOUT",
            ) from None
        except asyncpg.PostgresError as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            message = getattr(exc, "message", None)
            if sqlstate == "P0001" and message in {
                    "BARRIER_CONFLICT", "TRUST_PROCESS_BINDING_UNAVAILABLE",
                    "TRUST_SIGNER_SCOPE_UNAVAILABLE", "TRUST_REGISTRY_REVISION_UNAVAILABLE",
                    "TRUST_REGISTRY_SERVICE_COLLISION", "TRUST_ROTATION_CHAIN_TOO_DEEP",
                    "TRUST_SNAPSHOT_REQUEST_INVALID"}:
                raise BarrierAcknowledgementTrustSourceError(message) from None
            if sqlstate == "57014":
                raise BarrierAcknowledgementTrustSourceError(
                    "BARRIER_ACK_TRUST_TIMEOUT",
                ) from None
            raise BarrierAcknowledgementTrustSourceError(
                "BARRIER_ACK_TRUST_LOOKUP_FAILED",
            ) from None
        except Exception:
            raise BarrierAcknowledgementTrustSourceError(
                "BARRIER_ACK_TRUST_LOOKUP_FAILED",
            ) from None

    async def _load_on_connection(self, conn: asyncpg.Connection,
                                  acknowledgement: BarrierAcknowledgement,
                                  deadline: float) -> object:
        if conn.is_in_transaction():
            raise BarrierAcknowledgementTrustSourceError(
                "BARRIER_ACK_TRUST_TRANSACTION_INVALID",
            )
        transaction = conn.transaction()
        try:
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                async with asyncio.timeout(remaining):
                    await transaction.start()
            except BaseException:
                conn.terminate()
                raise
            await _execute_before_deadline(
                conn, deadline,
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
            )
            await _execute_before_deadline(
                conn, deadline,
                "SELECT pg_catalog.set_config('TimeZone', 'UTC', true)",
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            await _execute_before_deadline(
                conn, deadline,
                "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                f"{max(1, math.ceil(remaining * 1000))}ms",
            )
            if not await has_expected_database_identity(
                    conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                raise BarrierAcknowledgementTrustSourceError(
                    "BARRIER_ACK_TRUST_DATABASE_IDENTITY_INVALID",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                payload = await conn.fetchval(
                    "SELECT change_ledger.private_writer_load_barrier_ack_trust_v1("
                    "pg_catalog.jsonb_populate_record("
                    "NULL::change_ledger.private_writer_barrier_ack_v1,$1::jsonb))",
                    barrier_acknowledgement_record_json(acknowledgement),
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                await transaction.commit()
            if payload is None:
                raise BarrierAcknowledgementTrustSourceError(
                    "BARRIER_ACK_TRUST_CONTEXT_UNAVAILABLE",
                )
            return payload
        except BaseException:
            try:
                if conn.is_in_transaction():
                    remaining = max(0.001, min(1.0, deadline - time.monotonic()))
                    async with asyncio.timeout(remaining):
                        await transaction.rollback()
            except BaseException:
                conn.terminate()
            raise

    @staticmethod
    def _decode(payload: object) -> BarrierAcknowledgementTrustContext:
        try:
            if type(payload) is str:
                if len(payload) > _MAX_PAYLOAD_CHARS:
                    raise ValueError
                _check_json_text_limits(payload)
                document = json.loads(
                    payload,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_nonfinite_constant,
                    parse_float=_reject_float,
                    parse_int=_bounded_json_integer,
                )
            elif type(payload) is dict:
                document = payload
            else:
                raise ValueError
            _measure_json_value(document)
            if type(document) is not dict or set(document) != {"snapshot", "represented_scopes"}:
                raise ValueError
            scopes_raw = document["represented_scopes"]
            if type(scopes_raw) is not list or len(scopes_raw) > _MAX_SCOPES:
                raise ValueError
            scopes = tuple(_scope(value) for value in scopes_raw)
            if len(set(scopes)) != len(scopes) or scopes != tuple(sorted(
                    scopes, key=lambda scope: (scope.tenant_id, scope.company_id,
                                               scope.organization_ref, scope.base_fingerprint))):
                raise ValueError
            snapshot = PostgresEvidenceTrustSource._decode(document["snapshot"])
            return BarrierAcknowledgementTrustContext(snapshot, scopes)
        except Exception:
            raise BarrierAcknowledgementTrustSourceError(
                "BARRIER_ACK_TRUST_PAYLOAD_INVALID",
            ) from None


async def _execute_before_deadline(conn: asyncpg.Connection, deadline: float,
                                   query: str, *args: object) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    async with asyncio.timeout(remaining):
        await conn.execute(query, *args)


def _reject_float(_value: str) -> object:
    raise ValueError


__all__ = ["BarrierAcknowledgementTrustSourceError", "PostgresBarrierAcknowledgementTrustSource"]
