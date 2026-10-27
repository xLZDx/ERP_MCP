"""Bounded PostgreSQL persistence for verified S13 physical barrier acknowledgements."""
from __future__ import annotations

import asyncio
import json
import math
import time
from uuid import UUID

import asyncpg

from business_ai_gateway.phase2.change_ledger.write_port import BarrierAcknowledgement

from .barrier_ack_protocol import (
    barrier_acknowledgement_record_json,
    barrier_acknowledgement_ref,
    validate_barrier_acknowledgement,
)
from .barrier_ack_verifier import BarrierAcknowledgementTrustRevisionStale
from .postgres_evidence_trust import (
    _bounded_json_integer,
    _check_json_text_limits,
    _measure_json_value,
    _reject_nonfinite_constant,
    _unique_object,
)
from .postgres_identity import EVIDENCE_INGEST_SESSION_USER, has_expected_database_identity

_MAX_TIMEOUT_SECONDS = 5.0
_MAX_LOOKUP_JSON_CHARS = 8 * 1024 * 1024


class BarrierAcknowledgementRegistrationError(RuntimeError):
    """Sanitized PostgreSQL failure; unknown outcome is never converted to rejection."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


class PostgresBarrierAcknowledgementRegistrar:
    """Persist exact verifier-approved message and signature through one short transaction.

    The routine EXECUTE grant is deliberately not added here. The adapter remains fail-closed
    unless an installation separately grants the function to an isolated, reviewed principal.
    """

    __slots__ = ("_pool", "_timeout")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("BARRIER_ACK_REGISTRAR_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("BARRIER_ACK_REGISTRAR_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool, *, timeout_seconds: float = 3.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("BARRIER_ACK_REGISTRAR_POOL_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("BARRIER_ACK_REGISTRAR_TIMEOUT_INVALID")
        self._pool = pool
        self._timeout = float(timeout_seconds)

    async def lookup_barrier_acknowledgement(self, barrier_id: UUID) -> dict[str, object] | None:
        if type(barrier_id) is not UUID or barrier_id.int == 0:
            raise BarrierAcknowledgementRegistrationError("BARRIER_ACK_LOOKUP_INPUT_INVALID")
        deadline = time.monotonic() + self._timeout
        try:
            async with self._pool.acquire(timeout=self._timeout) as conn:
                return await self._lookup_on_connection(conn, barrier_id, deadline)
        except BarrierAcknowledgementRegistrationError:
            raise
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise BarrierAcknowledgementRegistrationError("BARRIER_ACK_LOOKUP_TIMEOUT") from None
        except Exception:
            raise BarrierAcknowledgementRegistrationError("BARRIER_ACK_LOOKUP_UNAVAILABLE") from None

    async def _lookup_on_connection(self, conn: asyncpg.Connection, barrier_id: UUID,
                                    deadline: float) -> dict[str, object] | None:
        transaction = conn.transaction()
        try:
            if conn.is_in_transaction():
                raise BarrierAcknowledgementRegistrationError(
                    "BARRIER_ACK_LOOKUP_TRANSACTION_INVALID",
                )
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
                "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY",
            )
            await _execute_before_deadline(
                conn, deadline,
                "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                f"{max(1, math.ceil(max(0.0, deadline - time.monotonic()) * 1000))}ms",
            )
            if not await has_expected_database_identity(
                    conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                raise BarrierAcknowledgementRegistrationError(
                    "BARRIER_ACK_LOOKUP_DATABASE_IDENTITY_INVALID",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                payload = await conn.fetchval(
                    "SELECT change_ledger.private_writer_lookup_barrier_ack_v1($1)", barrier_id,
                )
            result = _decode_lookup_record(payload)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                await transaction.commit()
            return result
        except BarrierAcknowledgementRegistrationError:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise
        except asyncio.CancelledError:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise
        except TimeoutError:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise BarrierAcknowledgementRegistrationError("BARRIER_ACK_LOOKUP_TIMEOUT") from None
        except Exception:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise BarrierAcknowledgementRegistrationError("BARRIER_ACK_LOOKUP_UNAVAILABLE") from None

    async def register_barrier_acknowledgement(
            self, acknowledgement: BarrierAcknowledgement, *, acknowledgement_ref: str,
            signed_bytes: bytes, trust_revision: int) -> str:
        try:
            validate_barrier_acknowledgement(acknowledgement)
        except Exception:
            raise BarrierAcknowledgementRegistrationError(
                "BARRIER_ACK_REGISTRATION_INPUT_INVALID",
            ) from None
        if (type(acknowledgement_ref) is not str
                or acknowledgement_ref != barrier_acknowledgement_ref(acknowledgement)
                or type(signed_bytes) is not bytes
                or signed_bytes != acknowledgement.signature_preimage()
                or type(trust_revision) is not int
                or not 0 < trust_revision <= 9_223_372_036_854_775_807):
            raise BarrierAcknowledgementRegistrationError(
                "BARRIER_ACK_REGISTRATION_INPUT_INVALID",
            )

        payload = barrier_acknowledgement_record_json(acknowledgement)
        deadline = time.monotonic() + self._timeout
        try:
            async with self._pool.acquire(timeout=self._timeout) as conn:
                return await self._register_on_connection(
                    conn, payload, acknowledgement_ref, signed_bytes, trust_revision, deadline,
                )
        except BarrierAcknowledgementRegistrationError:
            raise
        except BarrierAcknowledgementTrustRevisionStale:
            raise
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise BarrierAcknowledgementRegistrationError(
                "BARRIER_ACK_REGISTRATION_TIMEOUT", outcome_unknown=False,
            ) from None
        except Exception:
            raise BarrierAcknowledgementRegistrationError(
                "BARRIER_ACK_REGISTRATION_UNAVAILABLE",
            ) from None

    async def _register_on_connection(self, conn: asyncpg.Connection, payload: str,
                                      acknowledgement_ref: str, signed_bytes: bytes,
                                      trust_revision: int, deadline: float) -> str:
        attempted = False
        transaction = conn.transaction()
        try:
            if conn.is_in_transaction():
                raise BarrierAcknowledgementRegistrationError(
                    "BARRIER_ACK_REGISTRATION_OUTCOME_UNKNOWN", outcome_unknown=True,
                )
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
                conn, deadline, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            )
            await _execute_before_deadline(
                conn, deadline,
                "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                f"{max(1, math.ceil(max(0.0, deadline - time.monotonic()) * 1000))}ms",
            )
            if not await has_expected_database_identity(
                    conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                raise BarrierAcknowledgementRegistrationError(
                    "BARRIER_ACK_REGISTRATION_DATABASE_IDENTITY_INVALID",
                )
            attempted = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                persisted_ref = await conn.fetchval(
                    "SELECT change_ledger.private_writer_register_barrier_ack_v1("
                    "pg_catalog.jsonb_populate_record("
                    "NULL::change_ledger.private_writer_barrier_ack_v1,$1::jsonb),$2,$3,$4)",
                    payload, acknowledgement_ref, signed_bytes, trust_revision,
                )
            if type(persisted_ref) is not str or persisted_ref != acknowledgement_ref:
                raise BarrierAcknowledgementRegistrationError(
                    "BARRIER_ACK_REGISTRATION_OUTCOME_UNKNOWN", outcome_unknown=True,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                await transaction.commit()
            return persisted_ref
        except BarrierAcknowledgementRegistrationError:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise
        except asyncpg.PostgresError as exc:
            await _rollback_or_terminate(conn, transaction, deadline)
            sqlstate = getattr(exc, "sqlstate", None)
            message = getattr(exc, "message", None)
            if sqlstate == "P0001" and message in {
                    "BARRIER_CONFLICT", "STALE_EPOCH", "RECOVERY_EVIDENCE_REJECTED"}:
                from .service import BarrierAcknowledgementRejected
                raise BarrierAcknowledgementRejected() from None
            if sqlstate == "P0001" and message == "EVIDENCE_TRUST_REVISION_STALE":
                raise BarrierAcknowledgementTrustRevisionStale() from None
            if sqlstate == "57014":
                raise BarrierAcknowledgementRegistrationError(
                    "BARRIER_ACK_REGISTRATION_TIMEOUT", outcome_unknown=attempted,
                ) from None
            raise BarrierAcknowledgementRegistrationError(
                "BARRIER_ACK_REGISTRATION_OUTCOME_UNKNOWN" if attempted
                else "BARRIER_ACK_REGISTRATION_UNAVAILABLE",
                outcome_unknown=attempted,
            ) from None
        except TimeoutError:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise BarrierAcknowledgementRegistrationError(
                "BARRIER_ACK_REGISTRATION_TIMEOUT", outcome_unknown=attempted,
            ) from None
        except asyncio.CancelledError:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise
        except Exception:
            await _rollback_or_terminate(conn, transaction, deadline)
            raise BarrierAcknowledgementRegistrationError(
                "BARRIER_ACK_REGISTRATION_OUTCOME_UNKNOWN" if attempted
                else "BARRIER_ACK_REGISTRATION_UNAVAILABLE",
                outcome_unknown=attempted,
            ) from None


async def _execute_before_deadline(conn: asyncpg.Connection, deadline: float,
                                   query: str, *args: object) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    async with asyncio.timeout(remaining):
        await conn.execute(query, *args)


def _decode_lookup_record(payload: object) -> dict[str, object] | None:
    if payload is None:
        return None
    try:
        if type(payload) is str:
            if len(payload) > _MAX_LOOKUP_JSON_CHARS:
                raise ValueError
            _check_json_text_limits(payload)
            document = json.loads(
                payload, object_pairs_hook=_unique_object,
                parse_constant=_reject_nonfinite_constant,
                parse_float=_reject_float, parse_int=_bounded_json_integer,
            )
        elif type(payload) is dict:
            document = payload
        else:
            raise ValueError
        if type(document) is not dict:
            raise ValueError
        _measure_json_value(document)
        return document
    except Exception:
        raise BarrierAcknowledgementRegistrationError(
            "BARRIER_ACK_LOOKUP_PAYLOAD_INVALID",
        ) from None


def _reject_float(_value: str) -> object:
    raise ValueError


async def _rollback_or_terminate(conn: asyncpg.Connection | None,
                                  transaction: asyncpg.Transaction | None,
                                  deadline: float) -> None:
    if conn is None or transaction is None:
        return
    try:
        if conn.is_in_transaction():
            remaining = max(0.001, min(1.0, deadline - time.monotonic()))
            async with asyncio.timeout(remaining):
                await transaction.rollback()
    except BaseException:
        conn.terminate()


__all__ = [
    "BarrierAcknowledgementRegistrationError",
    "PostgresBarrierAcknowledgementRegistrar",
]
