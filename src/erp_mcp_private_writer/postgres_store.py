"""Versioned PostgreSQL adapter for the S13 private-writer admission contract.

The adapter is deliberately inert until the additive S13 schema is installed and a caller injects
an authenticated, least-privilege pool. Every operation owns one short top-level transaction and
returns only after commit/rollback; this module never calls a 1C writer or performs network I/O.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator
from uuid import UUID

import asyncpg

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.uuid_contract import (
    is_canonical_nonzero_uuid,
    is_canonical_process_instance_uuid,
)
from business_ai_gateway.phase2.change_ledger.write_port import ServingAuthorityLease
from .service import (
    AdmissionDecision,
    AdmissionRefusal,
    AdmissionState,
    AdmissionStoreError,
    BarrierProgress,
    BarrierSnapshot,
    CallIdentity,
    CallSnapshot,
    StartupRecoveryState,
)
from .postgres_identity import (
    PRIVATE_WRITER_SESSION_USER,
    has_expected_database_identity,
)

_DOMAIN_CODES = frozenset({
    "STALE_EPOCH",
    "CALL_IDENTITY_CONFLICT",
    "WRITER_ADMISSION_CLOSED",
    "BASE_CALL_IN_PROGRESS",
    "NOT_ACCEPTED",
    "RECOVERY_EVIDENCE_REJECTED",
    "VERIFY_EVIDENCE_ID_CONFLICT",
    "EVIDENCE_IDENTITY_CONFLICT",
    "TARGET_OBSERVATION_CONFLICT",
    "RECEIPT_IDENTITY_CONFLICT",
    "T16_RESOLUTION_REQUIRED",
    "TERMINAL_EVIDENCE_REJECTED",
    "BARRIER_CONFLICT",
    "LOCK_PLAN_STALE",
    "LEDGER_LOCK_TIMEOUT",
    "MUTATION_TRANSACTION_INVALID",
    "STARTUP_RECOVERY_INVENTORY_LIMIT",
})
_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
_MAX_TRANSACTION_SECONDS = 5.0
_MAX_STARTUP_RECOVERY_INVENTORY_ITEMS = 200
_ROLLBACK_CLEANUP_SECONDS = 1.0


class _DeadlineConnection:
    """Connection view that refreshes PostgreSQL's statement timeout before each query."""

    def __init__(self, conn: asyncpg.Connection, deadline: float) -> None:
        self._conn = conn
        self._deadline = deadline

    async def _set_statement_timeout(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        timeout_ms = max(1, math.ceil(remaining * 1000))
        await self._conn.fetchval(
            "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
            f"{timeout_ms}ms",
        )
        return self._deadline - time.monotonic()

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if await self._set_statement_timeout() <= 0:
            raise TimeoutError
        return await self._conn.fetchval(sql, *args)


class PostgresAdmissionStore:
    """Call the S13 v1 routines using an injected asyncpg pool.

    Pool credentials and connection identity are supplied by the host. The adapter does not set a
    role, search path, tenant identity, or caller-provided authentication claim.
    """

    __slots__ = ("_pool", "_timeout")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("ADMISSION_STORE_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ADMISSION_STORE_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool, *, transaction_timeout_seconds: float = 5.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("ADMISSION_POOL_INVALID")
        if (isinstance(transaction_timeout_seconds, bool)
                or not isinstance(transaction_timeout_seconds, (int, float))
                or not 0 < transaction_timeout_seconds <= _MAX_TRANSACTION_SECONDS
                or not math.isfinite(transaction_timeout_seconds)):
            raise ValueError("ADMISSION_TIMEOUT_INVALID")
        self._pool = pool
        self._timeout = float(transaction_timeout_seconds)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[_DeadlineConnection]:
        """Bound one READ COMMITTED transaction; no caller-owned transaction is accepted."""
        deadline = time.monotonic() + self._timeout
        try:
            async with asyncio.timeout(self._timeout):
                async with self._pool.acquire(timeout=self._timeout) as conn:
                    if conn.is_in_transaction():
                        raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
                    transaction = conn.transaction()
                    try:
                        await transaction.start()
                    except BaseException:
                        # BEGIN may have reached PostgreSQL even if its response was lost.
                        # Do not return a connection with an unknown transaction state to the pool.
                        conn.terminate()
                        raise
                    bounded_conn = _DeadlineConnection(conn, deadline)
                    try:
                        # Isolation is the first SQL command after BEGIN, before any fence or
                        # statement_timeout configuration, as required by the S13 lock contract.
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            await conn.execute(
                                "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            isolation = await conn.fetchval("SHOW transaction_isolation")
                        if isolation != "read committed":
                            raise AdmissionStoreError("STORE_TRANSACTION_ISOLATION_INVALID")

                        # Start the server-side statement bound only after isolation is explicit.
                        if await bounded_conn._set_statement_timeout() <= 0:
                            raise TimeoutError
                        if not await has_expected_database_identity(
                                bounded_conn, PRIVATE_WRITER_SESSION_USER, deadline):
                            raise AdmissionStoreError("STORE_DATABASE_IDENTITY_INVALID")
                        yield bounded_conn

                        # Commit is part of the same deadline. Refresh the server-side timeout
                        # immediately before it, then also bound the client wait by what remains.
                        remaining = await bounded_conn._set_statement_timeout()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            await transaction.commit()
                    except BaseException as original:
                        try:
                            async with asyncio.timeout(_ROLLBACK_CLEANUP_SECONDS):
                                await transaction.rollback()
                        except BaseException:
                            # Never return a connection to the pool while its transaction state
                            # is uncertain. Closing it prevents accidental reuse after a hung
                            # rollback; the caller still receives an unknown outcome.
                            conn.terminate()
                            if not isinstance(original, asyncio.CancelledError):
                                raise AdmissionStoreError(
                                    "STORE_OUTCOME_UNKNOWN", outcome_unknown=True
                                ) from None
                        raise
        except AdmissionStoreError:
            raise
        except TimeoutError:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        except asyncpg.PostgresError as exc:
            raise self._translate_postgres_error(exc) from None
        except Exception:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None

    async def _call_json(self, sql: str, *args: Any) -> dict[str, Any]:
        async with self._transaction() as conn:
            value = await conn.fetchval(sql, *args)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        if type(value) is not dict:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return value

    @staticmethod
    def _translate_postgres_error(exc: asyncpg.PostgresError) -> AdmissionStoreError:
        sqlstate = getattr(exc, "sqlstate", None)
        message = getattr(exc, "message", None)
        if type(message) is not str:
            message = ""
        head = message.splitlines()[0].strip() if message else ""
        if sqlstate == "42501":
            return AdmissionStoreError("NOT_ENTITLED", sqlstate=sqlstate)
        if sqlstate == "P0001" and _CODE_RE.fullmatch(head) and head in _DOMAIN_CODES:
            return AdmissionStoreError(head, sqlstate=sqlstate)
        transport_code = {
            "55P03": "SQL_55P03",
            "57014": "SQL_57014",
            "40P01": "SQL_40P01",
        }.get(sqlstate)
        if transport_code is not None:
            return AdmissionStoreError(transport_code, sqlstate=sqlstate, outcome_unknown=True)
        return AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)

    @staticmethod
    def _uuid_text(value: str, *, field: str) -> str:
        if not is_canonical_nonzero_uuid(value):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return value

    @classmethod
    def _process_instance_uuid_text(cls, value: str, *, field: str) -> str:
        canonical = cls._uuid_text(value, field=field)
        if not is_canonical_process_instance_uuid(canonical):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return canonical

    @classmethod
    def _uuid_value_text(cls, value: UUID, *, field: str) -> str:
        if type(value) is not UUID:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return cls._uuid_text(str(value), field=field)

    @classmethod
    def _identity_json(cls, identity: CallIdentity) -> str:
        if type(identity) is not CallIdentity:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        required_text = (
            identity.tenant_id, identity.company_id, identity.organization_ref,
            identity.change_id, identity.call_id, identity.operation,
            identity.payload_digest, identity.permit_id, identity.permit_digest,
            identity.base_fingerprint, identity.host_id,
        )
        optional_text = (
            identity.target_ref, identity.target_version, identity.repair_authorization_id,
        )
        if (any(type(value) is not str or not value for value in required_text)
                or any(value is not None and type(value) is not str for value in optional_text)
                or identity.operation not in {"CREATE_DRAFT", "POST", "UNPOST"}):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if type(identity.generation) is not int or identity.generation <= 0:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if type(identity.epoch) is not int or identity.epoch <= 0:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        payload = {
            "tenant_id": identity.tenant_id,
            "company_id": identity.company_id,
            "organization_ref": identity.organization_ref,
            "change_id": cls._uuid_text(identity.change_id, field="change_id"),
            "generation": identity.generation,
            "call_id": cls._uuid_text(identity.call_id, field="call_id"),
            "operation": identity.operation,
            "target_ref": identity.target_ref,
            "target_version": identity.target_version,
            "epoch": identity.epoch,
            "payload_digest": identity.payload_digest,
            "permit_id": identity.permit_id,
            "permit_digest": identity.permit_digest,
            "base_fingerprint": identity.base_fingerprint,
            "host_id": identity.host_id,
            "repair_authorization_id": identity.repair_authorization_id,
        }
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _scope_json(scope: Scope) -> str:
        if (type(scope) is not Scope
                or type(scope.tenant_id) is not str or not scope.tenant_id
                or type(scope.company_id) is not str or not scope.company_id):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return json.dumps({"tenant_id": scope.tenant_id, "company_id": scope.company_id},
                          separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _mapping(value: Any, fields: set[str]) -> dict[str, Any]:
        if type(value) is not dict or set(value) != fields:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return value

    @classmethod
    def _decode_identity(cls, value: Any) -> CallIdentity:
        row = cls._mapping(value, {
            "tenant_id", "company_id", "organization_ref", "change_id", "generation",
            "call_id", "operation", "target_ref", "target_version", "epoch",
            "payload_digest", "permit_id", "permit_digest", "base_fingerprint", "host_id",
            "repair_authorization_id",
        })
        if (type(row["generation"]) is not int or type(row["epoch"]) is not int
                or row["generation"] <= 0 or row["epoch"] <= 0):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        for name in row.keys() - {"generation", "epoch", "target_ref", "target_version",
                                  "repair_authorization_id"}:
            if type(row[name]) is not str:
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if row["operation"] not in {"CREATE_DRAFT", "POST", "UNPOST"}:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        for name in ("target_ref", "target_version", "repair_authorization_id"):
            if row[name] is not None and type(row[name]) is not str:
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        cls._uuid_text(row["change_id"], field="change_id")
        cls._uuid_text(row["call_id"], field="call_id")
        try:
            return CallIdentity(**row)
        except (TypeError, ValueError):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None

    @classmethod
    def _decode_call_snapshot(cls, value: Any) -> CallSnapshot:
        row = cls._mapping(value, {
            "identity", "state", "dispatch_cas_id", "evidence_ref", "owner_instance_id",
        })
        identity = cls._decode_identity(row["identity"])
        try:
            state = AdmissionState(row["state"])
        except (TypeError, ValueError):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        cas_id = row["dispatch_cas_id"]
        if cas_id is not None:
            try:
                cas_id = UUID(cls._uuid_text(cas_id, field="dispatch_cas_id"))
            except (TypeError, ValueError):
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        evidence_ref = row["evidence_ref"]
        if (evidence_ref is not None
                and (type(evidence_ref) is not str or not evidence_ref
                     or evidence_ref != evidence_ref.strip())):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        owner_instance_id = row["owner_instance_id"]
        if owner_instance_id is not None:
            owner_instance_id = cls._process_instance_uuid_text(
                owner_instance_id, field="owner_instance_id",
            )
        if (state is AdmissionState.NOT_ACCEPTED
                and (cas_id is not None or evidence_ref is not None or owner_instance_id is not None)):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if (state is not AdmissionState.NOT_ACCEPTED and type(cas_id) is not UUID):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if (state is AdmissionState.POSSIBLY_EXECUTING and owner_instance_id is None):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if state is not AdmissionState.POSSIBLY_EXECUTING and owner_instance_id is not None:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if (state is AdmissionState.TERMINAL_WITH_EVIDENCE
                and evidence_ref is None):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return CallSnapshot(identity, state, cas_id, evidence_ref, owner_instance_id)

    @classmethod
    def _decode_barrier_snapshot(cls, value: Any) -> BarrierSnapshot:
        row = cls._mapping(value, {
            "scope", "base_fingerprint", "barrier_id", "expected_current_epoch", "epoch",
            "barrier_origin_instance_id", "barrier_origin_service_epoch",
            "call_ids", "progress", "acknowledgement_ref", "acknowledgement_digest",
            "quiesced_at",
            "unresolved_call_ids",
        })
        digest_value = row["acknowledgement_digest"]
        if isinstance(digest_value, str) and re.fullmatch(r"\\x[0-9a-f]{64}", digest_value):
            row["acknowledgement_digest"] = bytes.fromhex(digest_value[2:])
        quiesced_at_value = row["quiesced_at"]
        if isinstance(quiesced_at_value, str):
            try:
                row["quiesced_at"] = datetime.fromisoformat(quiesced_at_value.replace("Z", "+00:00"))
            except ValueError:
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        scope_row = cls._mapping(row["scope"], {"tenant_id", "company_id"})
        if (type(row["base_fingerprint"]) is not str
                or type(row["expected_current_epoch"]) is not int
                or row["expected_current_epoch"] < 0
                or type(row["epoch"]) is not int
                or row["epoch"] != row["expected_current_epoch"] + 1
                or row["epoch"] <= 0
                or type(row["barrier_origin_instance_id"]) is not str
                or not row["barrier_origin_instance_id"]
                or type(row["barrier_origin_service_epoch"]) is not int
                or row["barrier_origin_service_epoch"] <= 0
                or (row["acknowledgement_ref"] is not None
                    and (type(row["acknowledgement_ref"]) is not str
                         or not row["acknowledgement_ref"]
                         or row["acknowledgement_ref"] != row["acknowledgement_ref"].strip()))
                or (row["acknowledgement_digest"] is not None
                    and (type(row["acknowledgement_digest"]) is not bytes
                         or len(row["acknowledgement_digest"]) != 32))
                or (row["quiesced_at"] is not None
                    and (type(row["quiesced_at"]) is not datetime
                         or row["quiesced_at"].tzinfo is None
                         or row["quiesced_at"].utcoffset() is None))
                or type(row["call_ids"]) is not list
                or type(row["unresolved_call_ids"]) is not list
                or any(type(call_id) is not str for call_id in row["call_ids"] + row["unresolved_call_ids"])):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        try:
            barrier_id = UUID(cls._uuid_text(row["barrier_id"], field="barrier_id"))
            cls._process_instance_uuid_text(
                row["barrier_origin_instance_id"], field="barrier_origin_instance_id",
            )
            progress = BarrierProgress(row["progress"])
        except (TypeError, ValueError):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        for call_id in row["call_ids"] + row["unresolved_call_ids"]:
            cls._uuid_text(call_id, field="call_id")
        ordered_call_ids = tuple(sorted(row["call_ids"]))
        ordered_unresolved_ids = tuple(
            call_id for call_id in ordered_call_ids if call_id in set(row["unresolved_call_ids"])
        )
        if (ordered_call_ids != tuple(row["call_ids"])
                or len(set(row["call_ids"])) != len(row["call_ids"])
                or len(set(row["unresolved_call_ids"])) != len(row["unresolved_call_ids"])
                or ordered_unresolved_ids != tuple(row["unresolved_call_ids"])):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        quiesced_fields_present = all(row[name] is not None for name in (
            "acknowledgement_ref", "acknowledgement_digest", "quiesced_at"))
        quiesced_fields_absent = all(row[name] is None for name in (
            "acknowledgement_ref", "acknowledgement_digest", "quiesced_at"))
        if ((progress is BarrierProgress.QUIESCED
             and (not quiesced_fields_present or row["unresolved_call_ids"]))
                or (progress is BarrierProgress.CLOSED_WITH_HOLD and not quiesced_fields_absent)):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return BarrierSnapshot(
            Scope(**scope_row), row["base_fingerprint"], barrier_id,
            row["expected_current_epoch"], row["epoch"],
            row["barrier_origin_instance_id"], row["barrier_origin_service_epoch"],
            tuple(row["call_ids"]), progress, tuple(row["unresolved_call_ids"]),
            row["acknowledgement_ref"], row["acknowledgement_digest"], row["quiesced_at"],
        )

    @classmethod
    def _decode_startup_state(cls, value: Any) -> StartupRecoveryState:
        row = cls._mapping(value, {
            "service_instance_id", "service_epoch", "pending_calls", "open_barriers",
            "readiness_ref",
        })
        if (type(row["service_instance_id"]) is not str
                or type(row["service_epoch"]) is not int or row["service_epoch"] <= 0
                or type(row["pending_calls"]) is not list
                or type(row["open_barriers"]) is not list
                or (row["readiness_ref"] is not None and type(row["readiness_ref"]) is not str)):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        inventory_size = len(row["pending_calls"]) + len(row["open_barriers"])
        for barrier in row["open_barriers"]:
            if type(barrier) is not dict or type(barrier.get("call_ids")) is not list:
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
            inventory_size += len(barrier["call_ids"])
        if inventory_size > _MAX_STARTUP_RECOVERY_INVENTORY_ITEMS:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        service_instance_id = cls._process_instance_uuid_text(
            row["service_instance_id"], field="service_instance_id",
        )
        readiness_ref = (
            cls._uuid_text(row["readiness_ref"], field="readiness_ref")
            if row["readiness_ref"] is not None else None
        )
        barriers = tuple(cls._decode_barrier_snapshot(item) for item in row["open_barriers"])
        if any(item.progress is not BarrierProgress.CLOSED_WITH_HOLD for item in barriers):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return StartupRecoveryState(
            service_instance_id, row["service_epoch"],
            tuple(cls._decode_call_snapshot(item) for item in row["pending_calls"]),
            barriers,
            readiness_ref,
        )

    async def startup_recovery_state(
            self, service_instance_id: str,
            authority_lease: ServingAuthorityLease) -> StartupRecoveryState:
        if authority_lease is None:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        authority_lease.assert_held()
        service_instance_id = self._process_instance_uuid_text(
            service_instance_id, field="service_instance_id",
        )
        value = await self._call_json(
            "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_startup_recovery_state_v1($1::text))",
            service_instance_id,
        )
        return self._decode_startup_state(value)

    async def admit(self, identity: CallIdentity, process_instance_id: str,
                    service_epoch: int) -> AdmissionDecision:
        process_instance_id = self._process_instance_uuid_text(
            process_instance_id, field="process_instance_id",
        )
        value = await self._call_json(
            "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_admit_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
            "$2::text, $3::bigint))",
            self._identity_json(identity), process_instance_id, service_epoch,
        )
        row = self._mapping(value, {
            "identity", "state", "newly_admitted", "dispatch_cas_id", "owner_instance_id",
            "evidence_ref", "refusal_code",
        })
        decoded_identity = self._decode_identity(row["identity"])
        if decoded_identity != identity:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        try:
            state = AdmissionState(row["state"])
            refusal = AdmissionRefusal(row["refusal_code"]) if row["refusal_code"] is not None else None
        except (TypeError, ValueError):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        if type(row["newly_admitted"]) is not bool:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        if state is AdmissionState.NOT_ACCEPTED:
            if (row["newly_admitted"] is not False or row["dispatch_cas_id"] is not None
                    or row["owner_instance_id"] is not None or row["evidence_ref"] is not None
                    or refusal is None):
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
            return AdmissionDecision(decoded_identity, state, False, refusal_code=refusal)
        if refusal is not None or state not in {
            AdmissionState.ACCEPTED_NOT_INVOKED,
            AdmissionState.POSSIBLY_EXECUTING,
            AdmissionState.TERMINAL_WITH_EVIDENCE,
        }:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        try:
            dispatch_cas_id = UUID(self._uuid_text(row["dispatch_cas_id"], field="dispatch_cas_id"))
        except (TypeError, ValueError):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        owner_instance_id = row["owner_instance_id"]
        evidence_ref = row["evidence_ref"]
        if type(owner_instance_id) is not str:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        owner_instance_id = self._process_instance_uuid_text(
            owner_instance_id, field="owner_instance_id",
        )
        if (
            (evidence_ref is not None and (
                type(evidence_ref) is not str or not evidence_ref
                or evidence_ref != evidence_ref.strip()
            ))
            or (state is AdmissionState.TERMINAL_WITH_EVIDENCE and evidence_ref is None)
            or (row["newly_admitted"] and (
                state is not AdmissionState.ACCEPTED_NOT_INVOKED
                or owner_instance_id != process_instance_id
                or evidence_ref is not None
            ))
        ):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return AdmissionDecision(decoded_identity, state, row["newly_admitted"],
                                 dispatch_cas_id, owner_instance_id, evidence_ref, refusal)

    async def mark_invoking(self, identity: CallIdentity, dispatch_cas_id: UUID,
                            process_instance_id: str, service_epoch: int) -> bool:
        dispatch_cas_text = self._uuid_value_text(dispatch_cas_id, field="dispatch_cas_id")
        process_instance_id = self._process_instance_uuid_text(
            process_instance_id, field="process_instance_id",
        )
        async with self._transaction() as conn:
            value = await conn.fetchval(
                "SELECT change_ledger.private_writer_mark_invoking_v1("
                "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
                "$2::uuid, $3::text, $4::bigint)",
                self._identity_json(identity), dispatch_cas_text, process_instance_id, service_epoch,
            )
        if type(value) is not bool:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return value

    async def begin_com_entry(self, identity: CallIdentity, dispatch_cas_id: UUID,
                              process_instance_id: str, service_epoch: int) -> bool:
        if (type(service_epoch) is not int or service_epoch < 1):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        dispatch_cas_text = self._uuid_value_text(dispatch_cas_id, field="dispatch_cas_id")
        process_instance_id = self._process_instance_uuid_text(
            process_instance_id, field="process_instance_id",
        )
        async with self._transaction() as conn:
            value = await conn.fetchval(
                "SELECT change_ledger.private_writer_begin_com_entry_v1("
                "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
                "$2::uuid, $3::text, $4::bigint)",
                self._identity_json(identity), dispatch_cas_text, process_instance_id, service_epoch,
            )
        if type(value) is not bool:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return value

    async def record_terminal(self, identity: CallIdentity, dispatch_cas_id: UUID,
                              process_instance_id: str, receipt_ref: str) -> str:
        if type(receipt_ref) is not str or not receipt_ref:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        dispatch_cas_text = self._uuid_value_text(dispatch_cas_id, field="dispatch_cas_id")
        process_instance_id = self._process_instance_uuid_text(
            process_instance_id, field="process_instance_id",
        )
        return await self._call_text(
            "SELECT change_ledger.private_writer_record_terminal_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
            "$2::uuid, $3::text, $4::text)",
            self._identity_json(identity), dispatch_cas_text, process_instance_id, receipt_ref,
        )

    async def attach_recovered_receipt(self, identity: CallIdentity, dispatch_cas_id: UUID,
                                       active_service_instance_id: str, service_epoch: int,
                                       original_owner_instance_id: str,
                                       receipt_ref: str) -> str:
        if (type(receipt_ref) is not str or not receipt_ref
                or type(service_epoch) is not int or service_epoch < 1):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        dispatch_cas_text = self._uuid_value_text(dispatch_cas_id, field="dispatch_cas_id")
        active_service_instance_id = self._process_instance_uuid_text(
            active_service_instance_id, field="active_service_instance_id",
        )
        original_owner_instance_id = self._process_instance_uuid_text(
            original_owner_instance_id, field="original_owner_instance_id",
        )
        return await self._call_text(
            "SELECT change_ledger.private_writer_attach_recovered_receipt_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
            "$2::uuid, $3::text, $4::bigint, $5::text, $6::text)",
            self._identity_json(identity), dispatch_cas_text, active_service_instance_id,
            service_epoch, original_owner_instance_id, receipt_ref,
        )

    async def record_verified_success(self, identity: CallIdentity, dispatch_cas_id: UUID,
                                      active_service_instance_id: str, service_epoch: int,
                                      receipt_ref: str, outcome_evidence_ref: str,
                                      completion_proof_ref: str) -> str:
        if (type(active_service_instance_id) is not str or not active_service_instance_id
                or type(service_epoch) is not int or service_epoch < 1):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        dispatch_cas_text = self._uuid_value_text(dispatch_cas_id, field="dispatch_cas_id")
        active_service_instance_id = self._process_instance_uuid_text(
            active_service_instance_id, field="active_service_instance_id",
        )
        refs = (receipt_ref, outcome_evidence_ref, completion_proof_ref)
        if any(type(ref) is not str or not ref for ref in refs):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return await self._call_text(
            "SELECT change_ledger.private_writer_record_verified_success_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
            "$2::uuid, $3::text, $4::bigint, $5::text, $6::text, $7::text)",
            self._identity_json(identity), dispatch_cas_text, active_service_instance_id,
            service_epoch, *refs,
        )

    async def record_recovered_not_invoked(self, identity: CallIdentity,
                                           dispatch_cas_id: UUID,
                                           active_service_instance_id: str,
                                           service_epoch: int,
                                           no_effect_receipt_ref: str) -> str:
        if (type(service_epoch) is not int or service_epoch < 1
                or type(no_effect_receipt_ref) is not str or not no_effect_receipt_ref):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        dispatch_cas_text = self._uuid_value_text(dispatch_cas_id, field="dispatch_cas_id")
        active_service_instance_id = self._process_instance_uuid_text(
            active_service_instance_id, field="active_service_instance_id",
        )
        return await self._call_text(
            "SELECT change_ledger.private_writer_record_recovered_not_invoked_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
            "$2::uuid, $3::text, $4::bigint, $5::text)",
            self._identity_json(identity), dispatch_cas_text, active_service_instance_id,
            service_epoch, no_effect_receipt_ref,
        )

    async def record_recovered_terminal(self, identity: CallIdentity, dispatch_cas_id: UUID,
                                        active_service_instance_id: str, service_epoch: int,
                                        outcome_evidence_ref: str,
                                        completion_proof_ref: str,
                                        post_completion_challenge_ref: str,
                                        read_attestation_ref: str,
                                        resolution_event_id: UUID) -> str:
        if (type(active_service_instance_id) is not str or not active_service_instance_id
                or type(service_epoch) is not int or service_epoch < 1):
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        dispatch_cas_text = self._uuid_value_text(dispatch_cas_id, field="dispatch_cas_id")
        active_service_instance_id = self._process_instance_uuid_text(
            active_service_instance_id, field="active_service_instance_id",
        )
        resolution_event_text = self._uuid_value_text(
            resolution_event_id, field="resolution_event_id",
        )
        return await self._call_text(
            "SELECT change_ledger.private_writer_record_recovered_terminal_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb), "
            "$2::uuid, $3::text, $4::bigint, $5::text, $6::text, $7::text, $8::text, $9::uuid)",
            self._identity_json(identity), dispatch_cas_text, active_service_instance_id,
            service_epoch, outcome_evidence_ref,
            completion_proof_ref, post_completion_challenge_ref, read_attestation_ref,
            resolution_event_text,
        )

    async def lookup(self, identity: CallIdentity) -> CallSnapshot:
        value = await self._call_json(
            "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_lookup_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1, $1::jsonb)))",
            self._identity_json(identity),
        )
        return self._decode_call_snapshot(value)

    async def close_and_advance(self, base_fingerprint: str, scope: Scope,
                                expected_current_epoch: int,
                                barrier_id: UUID, service_instance_id: str,
                                service_epoch: int) -> BarrierSnapshot:
        if type(service_epoch) is not int or service_epoch < 1:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        barrier_id_text = self._uuid_value_text(barrier_id, field="barrier_id")
        service_instance_id = self._process_instance_uuid_text(
            service_instance_id, field="service_instance_id",
        )
        value = await self._call_json(
            "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_close_and_advance_v1("
            "$1::text, pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_scope_v1, $2::jsonb), "
            "$3::bigint, $4::uuid, $5::text, $6::bigint))",
            base_fingerprint, self._scope_json(scope), expected_current_epoch, barrier_id_text,
            service_instance_id, service_epoch,
        )
        return self._decode_barrier_snapshot(value)

    async def lookup_barrier(self, barrier_id: UUID) -> BarrierSnapshot | None:
        barrier_id_text = self._uuid_value_text(barrier_id, field="barrier_id")
        async with self._transaction() as conn:
            value = await conn.fetchval(
                "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_lookup_barrier_v1($1::uuid))",
                barrier_id_text,
            )
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True) from None
        return self._decode_barrier_snapshot(value)

    async def finish_barrier(self, snapshot: BarrierSnapshot,
                             acknowledgement_ref: str, service_instance_id: str,
                             service_epoch: int) -> BarrierSnapshot:
        if type(service_epoch) is not int or service_epoch < 1:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        service_instance_id = self._process_instance_uuid_text(
            service_instance_id, field="service_instance_id",
        )
        value = await self._call_json(
            "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_finish_barrier_v1("
            "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_barrier_snapshot_v1, $1::jsonb), "
            "$2::text, $3::text, $4::bigint))",
            json.dumps(self._barrier_json(snapshot), separators=(",", ":"), allow_nan=False),
            acknowledgement_ref, service_instance_id, service_epoch,
        )
        return self._decode_barrier_snapshot(value)

    @classmethod
    def _barrier_json(cls, snapshot: BarrierSnapshot) -> dict[str, Any]:
        if type(snapshot) is not BarrierSnapshot:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        cls._uuid_value_text(snapshot.barrier_id, field="barrier_id")
        cls._process_instance_uuid_text(
            snapshot.barrier_origin_instance_id, field="barrier_origin_instance_id",
        )
        if type(snapshot.call_ids) is not tuple or type(snapshot.unresolved_call_ids) is not tuple:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        for call_id in snapshot.call_ids + snapshot.unresolved_call_ids:
            cls._uuid_text(call_id, field="call_id")
        return {
            "scope": {"tenant_id": snapshot.scope.tenant_id, "company_id": snapshot.scope.company_id},
            "base_fingerprint": snapshot.base_fingerprint,
            "barrier_id": str(snapshot.barrier_id),
            "expected_current_epoch": snapshot.expected_current_epoch,
            "epoch": snapshot.epoch,
            "barrier_origin_instance_id": snapshot.barrier_origin_instance_id,
            "barrier_origin_service_epoch": snapshot.barrier_origin_service_epoch,
            "call_ids": list(snapshot.call_ids),
            "progress": snapshot.progress.value,
            "acknowledgement_ref": snapshot.acknowledgement_ref,
            "acknowledgement_digest": ("\\x" + snapshot.acknowledgement_digest.hex()
                                        if snapshot.acknowledgement_digest is not None else None),
            "quiesced_at": (snapshot.quiesced_at.isoformat()
                            if snapshot.quiesced_at is not None else None),
            "unresolved_call_ids": list(snapshot.unresolved_call_ids),
        }

    async def _call_text(self, sql: str, *args: Any) -> str:
        async with self._transaction() as conn:
            value = await conn.fetchval(sql, *args)
        if type(value) is not str or not value:
            raise AdmissionStoreError("STORE_OUTCOME_UNKNOWN", outcome_unknown=True)
        return value


__all__ = ["PostgresAdmissionStore"]
