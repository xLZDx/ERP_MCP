"""Least-privilege loader for coherent production evidence-trust snapshots.

The pool must authenticate directly as ``private_writer_evidence_ingest``. The SQL routine is the
only data access path; this adapter does not read trust tables or register evidence. It is inert
until explicitly composed by a caller.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from .evidence_trust import (
    EvidenceScope,
    EvidenceTrustSnapshot,
    OutcomeVersionFloor,
    SignerKeyRef,
    TrustSnapshotRequest,
    TrustedOracleArtifact,
    TrustedProcessBinding,
    TrustedSigner,
)
from .postgres_identity import (
    EVIDENCE_INGEST_SESSION_USER,
    has_expected_database_identity,
)


_MAX_TIMEOUT_SECONDS = 5.0
_MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 1_000_000
_MAX_JSON_INTEGER_DIGITS = 20
_MAX_SIGNERS = 4200
_MAX_PROCESSES = 16
_MAX_ORACLES = 16


class EvidenceTrustSourceError(RuntimeError):
    """Stable lookup failures without PostgreSQL or trust-registry details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PostgresEvidenceTrustSource:
    """Load one repeatable-read snapshot using only the narrowly granted SQL routine."""

    __slots__ = ("_pool", "_timeout")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("EVIDENCE_TRUST_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("EVIDENCE_TRUST_CONFIGURATION_IMMUTABLE")

    def __init__(self, pool: asyncpg.Pool, *, timeout_seconds: float = 3.0) -> None:
        if not isinstance(pool, asyncpg.Pool):
            raise ValueError("EVIDENCE_TRUST_POOL_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("EVIDENCE_TRUST_TIMEOUT_INVALID")
        self._pool = pool
        self._timeout = float(timeout_seconds)

    async def load_snapshot(self, request: TrustSnapshotRequest) -> EvidenceTrustSnapshot:
        if type(request) is not TrustSnapshotRequest:
            raise EvidenceTrustSourceError("TRUST_SNAPSHOT_REQUEST_INVALID")
        deadline = time.monotonic() + self._timeout
        try:
            async with asyncio.timeout(self._timeout):
                async with self._pool.acquire(timeout=self._timeout) as conn:
                    if conn.is_in_transaction():
                        raise EvidenceTrustSourceError("TRUST_SNAPSHOT_OUTCOME_UNKNOWN")
                    transaction = conn.transaction()
                    try:
                        await transaction.start()
                    except BaseException:
                        conn.terminate()
                        raise
                    try:
                        await self._execute_before_deadline(
                            conn, deadline,
                            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
                        )
                        await self._execute_before_deadline(
                            conn, deadline,
                            "SELECT pg_catalog.set_config('TimeZone', 'UTC', true)",
                        )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        await self._execute_before_deadline(
                            conn, deadline,
                            "SELECT pg_catalog.set_config('statement_timeout', $1, true)",
                            f"{max(1, math.ceil(remaining * 1000))}ms",
                        )
                        if not await has_expected_database_identity(
                                conn, EVIDENCE_INGEST_SESSION_USER, deadline):
                            raise EvidenceTrustSourceError("TRUST_DATABASE_IDENTITY_INVALID")
                        payload = await self._fetch_before_deadline(conn, deadline, request)
                        snapshot = self._decode(payload)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        async with asyncio.timeout(remaining):
                            await transaction.commit()
                        return snapshot
                    except BaseException:
                        try:
                            if conn.is_in_transaction():
                                remaining = max(0.001, min(1.0, deadline - time.monotonic()))
                                async with asyncio.timeout(remaining):
                                    await transaction.rollback()
                        except BaseException:
                            conn.terminate()
                        raise
        except EvidenceTrustSourceError:
            raise
        except asyncpg.PostgresError as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            message = str(exc)
            if sqlstate == "P0001":
                for code in (
                    "TRUST_REGISTRY_SERVICE_COLLISION", "TRUST_PROCESS_BINDING_UNAVAILABLE",
                    "TRUST_REGISTRY_REVISION_UNAVAILABLE", "TRUST_SIGNER_SCOPE_UNAVAILABLE",
                    "TRUST_ROTATION_CHAIN_TOO_DEEP", "TRUST_SNAPSHOT_REQUEST_INVALID",
                    "TRUST_SNAPSHOT_TRANSACTION_INVALID",
                ):
                    if code in message:
                        raise EvidenceTrustSourceError(code) from None
                raise EvidenceTrustSourceError("TRUST_SNAPSHOT_UNAVAILABLE") from None
            if sqlstate == "57014":
                raise EvidenceTrustSourceError("TRUST_SNAPSHOT_TIMEOUT") from None
            raise EvidenceTrustSourceError("TRUST_SNAPSHOT_LOOKUP_FAILED") from None
        except (TimeoutError, asyncio.TimeoutError):
            raise EvidenceTrustSourceError("TRUST_SNAPSHOT_TIMEOUT") from None
        except Exception:
            raise EvidenceTrustSourceError("TRUST_SNAPSHOT_LOOKUP_FAILED") from None

    async def _execute_before_deadline(self, conn: asyncpg.Connection, deadline: float,
                                      query: str, *args: Any) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            await conn.execute(query, *args)

    async def _fetch_before_deadline(self, conn: asyncpg.Connection, deadline: float,
                                     request: TrustSnapshotRequest) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        signer_ids = [key.key_id for key in request.signer_keys]
        signer_versions = [key.key_version for key in request.signer_keys]
        process_ids = [UUID(value) for value in request.process_instance_ids]
        async with asyncio.timeout(remaining):
            return await conn.fetchval(
                "SELECT change_ledger.private_writer_load_trust_snapshot_v1("
                "$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                request.scope.tenant_id, request.scope.company_id,
                request.scope.organization_ref, request.scope.base_fingerprint,
                request.operation_kind, signer_ids, signer_versions, process_ids,
                request.oracle_id, request.oracle_version,
                request.include_operation_oracle_policy,
            )

    @staticmethod
    def _decode(payload: object) -> EvidenceTrustSnapshot:
        try:
            if type(payload) is str:
                _check_json_text_limits(payload)
                document = json.loads(
                    payload,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_nonfinite_constant,
                    parse_float=_reject_json_float,
                    parse_int=_bounded_json_integer,
                )
            elif type(payload) is dict:
                # Driver-decoded JSON has no source text from which duplicate keys can be
                # recovered. Bound its already-materialized tree without serializing it first.
                document = payload
            else:
                raise ValueError
            _measure_json_value(document)
            if type(document) is not dict or set(document) != {
                    "revision", "loaded_at", "signers", "process_bindings", "oracle_artifacts",
                    "outcome_version_floors"}:
                raise ValueError
            signers_raw = _array(document["signers"], _MAX_SIGNERS)
            processes_raw = _array(document["process_bindings"], _MAX_PROCESSES)
            oracles_raw = _array(document["oracle_artifacts"], _MAX_ORACLES)
            floors_raw = _array(document["outcome_version_floors"], 3)
            signers = tuple(_signer(item) for item in signers_raw)
            processes = tuple(_process(item) for item in processes_raw)
            oracles = tuple(_oracle(item) for item in oracles_raw)
            floors = tuple(_floor(item) for item in floors_raw)
            return EvidenceTrustSnapshot(
                revision=_string(document["revision"]),
                loaded_at=_datetime(document["loaded_at"]),
                signers=signers,
                process_bindings=processes,
                oracle_artifacts=oracles,
                outcome_version_floors=floors,
            )
        except Exception:
            raise EvidenceTrustSourceError("TRUST_SNAPSHOT_PAYLOAD_INVALID") from None


def _array(value: Any, maximum: int) -> list[Any]:
    if type(value) is not list or len(value) > maximum:
        raise ValueError
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _check_json_text_limits(payload: str) -> None:
    """Bound UTF-8 bytes, nesting and JSON-value count before materializing the tree."""
    payload_length = len(payload)
    if payload_length > _MAX_SNAPSHOT_BYTES:
        raise ValueError
    if not payload.isascii():
        # Count through CPython's UTF-8 encoder in bounded chunks. This preserves strict
        # surrogate rejection without allocating a second UTF-8 copy of a multi-byte payload.
        byte_size = 0
        for offset in range(0, payload_length, 65_536):
            byte_size += len(payload[offset:offset + 65_536].encode("utf-8", errors="strict"))
            if byte_size > _MAX_SNAPSHOT_BYTES:
                raise ValueError

    containers: list[dict[str, str]] = []
    index = 0
    node_count = 0
    root_consumed = False
    while index < payload_length:
        character = payload[index]
        if character in " \t\r\n":
            index += 1
            continue
        if not containers:
            if root_consumed:
                raise ValueError
            node_count += 1
            if node_count > _MAX_JSON_NODES:
                raise ValueError
            index = _start_json_value(payload, index, containers)
            root_consumed = True
            continue

        current = containers[-1]
        kind, state = current["kind"], current["state"]
        if kind == "object" and state == "key_or_end":
            if character == "}":
                containers.pop()
                index += 1
            elif character == '"':
                index = _skip_json_string(payload, index)
                current["state"] = "colon"
            else:
                raise ValueError
        elif kind == "object" and state == "colon":
            if character != ":":
                raise ValueError
            current["state"] = "value"
            index += 1
        elif kind == "object" and state == "value":
            node_count += 1
            if node_count > _MAX_JSON_NODES:
                raise ValueError
            index = _start_json_value(payload, index, containers)
            current["state"] = "comma_or_end"
        elif kind == "object" and state == "comma_or_end":
            if character == ",":
                current["state"] = "key_or_end"
                index += 1
            elif character == "}":
                containers.pop()
                index += 1
            else:
                raise ValueError
        elif kind == "array" and state == "value_or_end":
            if character == "]":
                containers.pop()
                index += 1
            else:
                node_count += 1
                if node_count > _MAX_JSON_NODES:
                    raise ValueError
                index = _start_json_value(payload, index, containers)
                current["state"] = "comma_or_end"
        elif kind == "array" and state == "comma_or_end":
            if character == ",":
                current["state"] = "value_or_end"
                index += 1
            elif character == "]":
                containers.pop()
                index += 1
            else:
                raise ValueError
        else:
            raise ValueError
    if not root_consumed or containers:
        raise ValueError


def _start_json_value(payload: str, index: int, containers: list[dict[str, str]]) -> int:
    """Advance across one lexically bounded value; json.loads validates its full grammar."""
    payload_length = len(payload)
    character = payload[index]
    if character in "[{":
        if len(containers) >= _MAX_JSON_DEPTH:
            raise ValueError
        containers.append({"kind": "array" if character == "[" else "object",
                           "state": "value_or_end" if character == "[" else "key_or_end"})
        return index + 1
    if character == '"':
        return _skip_json_string(payload, index)
    end = index
    while end < payload_length and payload[end] not in " \t\r\n,]}:":
        end += 1
    if end == index:
        raise ValueError
    return end


def _skip_json_string(payload: str, index: int) -> int:
    payload_length = len(payload)
    index += 1
    while index < payload_length:
        character = payload[index]
        if character == '"':
            return index + 1
        if character == "\\":
            index += 2
        else:
            index += 1
    raise ValueError


def _measure_json_value(document: Any) -> None:
    stack: list[tuple[Any, int]] = [(document, 0)]
    nodes = 0
    size = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise ValueError
        if type(value) is dict:
            if depth == _MAX_JSON_DEPTH or nodes + len(value) > _MAX_JSON_NODES:
                raise ValueError
            size += 2 + max(0, len(value) - 1)
            for key, child in value.items():
                if type(key) is not str:
                    raise ValueError
                size += _json_string_size(key) + 1
                stack.append((child, depth + 1))
        elif type(value) is list:
            if depth == _MAX_JSON_DEPTH or nodes + len(value) > _MAX_JSON_NODES:
                raise ValueError
            size += 2 + max(0, len(value) - 1)
            stack.extend((child, depth + 1) for child in value)
        elif type(value) is str:
            size += _json_string_size(value)
        elif value is None:
            size += 4
        elif type(value) is bool:
            size += 4 if value else 5
        elif type(value) is int:
            if not -(2 ** 31) <= value <= 2 ** 31 - 1:
                raise ValueError
            size += len(str(value))
        else:
            # This closed snapshot contract has no floating-point or custom JSON values.
            raise ValueError
        if size > _MAX_SNAPSHOT_BYTES:
            raise ValueError


def _json_string_size(value: str) -> int:
    size = 2  # Surrounding JSON quotes.
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError
        if codepoint < 0x20:
            size += 2 if character in "\b\f\n\r\t" else 6
        elif character in {'"', "\\"}:
            size += 2
        elif codepoint <= 0x7F:
            size += 1
        elif codepoint <= 0x7FF:
            size += 2
        elif codepoint <= 0xFFFF:
            size += 3
        else:
            size += 4
        if size > _MAX_SNAPSHOT_BYTES:
            raise ValueError
    return size


def _bounded_json_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > _MAX_JSON_INTEGER_DIGITS:
        raise ValueError
    parsed = int(value)
    if not -(2 ** 31) <= parsed <= 2 ** 31 - 1:
        raise ValueError
    return parsed


def _reject_json_float(value: str) -> None:
    raise ValueError


def _reject_nonfinite_constant(value: str) -> None:
    if value in {"NaN", "Infinity", "-Infinity"}:
        raise ValueError
    raise ValueError


def _object(value: Any, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError
    return value


def _string(value: Any) -> str:
    if type(value) is not str or not value:
        raise ValueError
    return value


def _datetime(value: Any) -> datetime:
    if type(value) is not str:
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


def _hex(value: Any, length: int) -> bytes:
    if type(value) is not str or len(value) != length * 2:
        raise ValueError
    result = bytes.fromhex(value)
    if result.hex() != value:
        raise ValueError
    return result


def _key_ref(value: Any) -> SignerKeyRef:
    item = _object(value, {"key_id", "key_version"})
    return SignerKeyRef(_string(item["key_id"]), _string(item["key_version"]))


def _scope(value: Any) -> EvidenceScope:
    item = _object(value, {"tenant_id", "company_id", "organization_ref", "base_fingerprint"})
    return EvidenceScope(
        _string(item["tenant_id"]), _string(item["company_id"]),
        _string(item["organization_ref"]), _string(item["base_fingerprint"]),
    )


def _signer(value: Any) -> TrustedSigner:
    item = _object(value, {
        "key_id", "key_version", "public_key_hex", "signer_role", "service_id", "host_id",
        "valid_from", "valid_until", "revoked_at", "allowed_scopes", "rotation_history",
    })
    scopes = _array(item["allowed_scopes"], 4096)
    history = _array(item["rotation_history"], 129)
    revoked_at = item["revoked_at"]
    return TrustedSigner(
        key=SignerKeyRef(_string(item["key_id"]), _string(item["key_version"])),
        public_key=_hex(item["public_key_hex"], 32),
        signer_role=_string(item["signer_role"]), service_id=_string(item["service_id"]),
        host_id=_string(item["host_id"]), allowed_scopes=tuple(_scope(scope) for scope in scopes),
        valid_from=_datetime(item["valid_from"]), valid_until=_datetime(item["valid_until"]),
        revoked_at=None if revoked_at is None else _datetime(revoked_at),
        rotation_history=tuple(_key_ref(key) for key in history),
    )


def _process(value: Any) -> TrustedProcessBinding:
    item = _object(value, {
        "process_instance_id", "host_boot_id", "service_id", "host_id", "os_pid",
        "process_created_at", "supervisor_key_id", "supervisor_key_version", "signature_hex",
    })
    if type(item["os_pid"]) is not int:
        raise ValueError
    return TrustedProcessBinding(
        process_instance_id=_string(item["process_instance_id"]),
        host_boot_id=_string(item["host_boot_id"]), service_id=_string(item["service_id"]),
        host_id=_string(item["host_id"]), os_pid=item["os_pid"],
        process_created_at=_datetime(item["process_created_at"]),
        supervisor_key=SignerKeyRef(_string(item["supervisor_key_id"]),
                                    _string(item["supervisor_key_version"])),
        signature=_hex(item["signature_hex"], 64),
    )


def _oracle(value: Any) -> TrustedOracleArtifact:
    item = _object(value, {
        "tenant_id", "company_id", "organization_ref", "base_fingerprint", "operation_kind",
        "oracle_id", "oracle_version", "document_shape_revision", "configuration_fingerprint",
        "oracle_digest", "expected_effect_schema_version",
    })
    return TrustedOracleArtifact(
        scope=EvidenceScope(_string(item["tenant_id"]), _string(item["company_id"]),
                            _string(item["organization_ref"]), _string(item["base_fingerprint"])),
        operation_kind=_string(item["operation_kind"]), oracle_id=_string(item["oracle_id"]),
        oracle_version=_string(item["oracle_version"]),
        document_shape_revision=_string(item["document_shape_revision"]),
        configuration_fingerprint=_string(item["configuration_fingerprint"]),
        oracle_digest=_string(item["oracle_digest"]),
        expected_effect_schema_version=_string(item["expected_effect_schema_version"]),
    )


def _floor(value: Any) -> OutcomeVersionFloor:
    item = _object(value, {
        "tenant_id", "company_id", "organization_ref", "base_fingerprint", "operation_kind",
        "minimum_version",
    })
    if type(item["minimum_version"]) is not int:
        raise ValueError
    return OutcomeVersionFloor(
        scope=EvidenceScope(_string(item["tenant_id"]), _string(item["company_id"]),
                            _string(item["organization_ref"]), _string(item["base_fingerprint"])),
        operation_kind=_string(item["operation_kind"]), minimum_version=item["minimum_version"],
    )


__all__ = ["EvidenceTrustSourceError", "PostgresEvidenceTrustSource"]
