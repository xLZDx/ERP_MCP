"""Standalone dev-only S13 checkpoint anchor service.

The service owns a SQLite event history separate from PostgreSQL and the gateway process. It
authenticates its own responses with two distinct Ed25519 authority keys. It does not establish
host-admin rollback resistance, production retention, startup readiness, recovery, or dispatch.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Protocol
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..checkpoint import CheckpointRecord, checkpoint_identity

_ZERO_HASH = "0" * 64
_MAX_EVENTS = 100_000
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_ID = 128
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX128 = re.compile(r"^[0-9a-f]{128}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
LATESTNESS_SIGNING_DOMAIN = b"ERP_MCP:S13:ANCHOR-LATESTNESS:v1"
KEY_AUTH_SIGNING_DOMAIN = b"ERP_MCP:S13:ANCHOR-KEY-AUTH:v1"
_PROVIDER_HISTORY_DOMAIN = b"ERP_MCP:S13:ANCHOR-HISTORY:PROVIDER:v1"
_KEY_HISTORY_DOMAIN = b"ERP_MCP:S13:ANCHOR-HISTORY:KEY-AUTH:v1"
_POLICY_VERSION = "s13-dev-anchor-v1"
_LOGGER = logging.getLogger(__name__)


class AnchorServiceError(RuntimeError):
    """Stable, redacted refusal code for callers and API responses."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DevAnchorSigner(Protocol):
    """Dedicated Ed25519 signer for one authority domain."""

    public_key_bytes: bytes

    def sign(self, message: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class DevAnchorConfig:
    service_id: str
    database_path: Path
    project_root: Path
    mode: str
    bind_host: str
    bearer_token: str
    admin_token: str
    latestness_authority_id: str
    latestness_signer: DevAnchorSigner
    key_authority_id: str
    key_authority_signer: DevAnchorSigner


def canonical_json(value: object) -> bytes:
    """Canonical compact JSON used for event and authority signature preimages."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnchorServiceError("ANCHOR_TIME_INVALID")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: object) -> datetime:
    if type(value) is not str or not value or len(value) > 64:
        raise AnchorServiceError("CHECKPOINT_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise AnchorServiceError("CHECKPOINT_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AnchorServiceError("CHECKPOINT_INVALID")
    return parsed.astimezone(UTC)


def _parse_record(value: object, *, service_id: str) -> CheckpointRecord:
    fields = {
        "tenant_id", "company_id", "seq", "head_hash", "signed_at", "key_id",
        "signature", "sink_id", "sink_kind",
    }
    if type(value) is not dict or set(value) != fields:
        raise AnchorServiceError("CHECKPOINT_INVALID")
    tenant_id = value["tenant_id"]
    company_id = value["company_id"]
    seq = value["seq"]
    head_hash = value["head_hash"]
    key_id = value["key_id"]
    signature = value["signature"]
    sink_id = value["sink_id"]
    sink_kind = value["sink_kind"]
    if (type(tenant_id) is not str or not tenant_id or len(tenant_id) > _MAX_ID
            or type(company_id) is not str or not company_id or len(company_id) > _MAX_ID
            or type(seq) is not int or seq < 1
            or type(head_hash) is not str or _HEX64.fullmatch(head_hash) is None
            or type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None
            or type(signature) is not str or _HEX128.fullmatch(signature) is None
            or type(sink_id) is not str or sink_id != service_id
            or type(sink_kind) is not str or sink_kind != "TEST"):
        raise AnchorServiceError("CHECKPOINT_INVALID")
    signed_at = _parse_time(value["signed_at"])
    return CheckpointRecord(tenant_id, company_id, seq, head_hash, signed_at, key_id,
                            signature, sink_id, sink_kind)


def _record_json(record: CheckpointRecord) -> dict[str, object]:
    return {
        "tenant_id": record.tenant_id,
        "company_id": record.company_id,
        "seq": record.seq,
        "head_hash": record.head_hash,
        "signed_at": _utc_text(record.signed_at),
        "key_id": record.key_id,
        "signature": record.signature,
        "sink_id": record.sink_id,
        "sink_kind": record.sink_kind,
    }


def _valid_public_key(value: object) -> bool:
    if type(value) is not bytes or len(value) != 32:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(value)
        return True
    except Exception:
        return False


def _verify_checkpoint_signature(public_key: bytes, record: CheckpointRecord) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(record.signature), record.signing_payload())
        return True
    except Exception:
        return False


def _authority_preimage(domain: bytes, evidence: dict[str, object]) -> bytes:
    return domain + b"\n" + canonical_json(evidence)


def _latestness_evidence_digest(evidence: dict[str, object]) -> str:
    """Hash the latestness signed preimage without its self-referential proof_digest field."""
    unsigned = {key: value for key, value in evidence.items() if key != "proof_digest"}
    return hashlib.sha256(_authority_preimage(LATESTNESS_SIGNING_DOMAIN, unsigned)).hexdigest()


def _sign(signer: DevAnchorSigner, payload: bytes) -> str:
    try:
        signature = signer.sign(payload)
    except Exception:
        raise AnchorServiceError("ANCHOR_SIGNING_UNAVAILABLE") from None
    if type(signature) is not bytes or len(signature) != 64:
        raise AnchorServiceError("ANCHOR_SIGNING_UNAVAILABLE")
    return signature.hex()


def _verify_signed_hash(public_key: bytes, domain: bytes, event_hash: str,
                        signature_hex: str) -> bool:
    if _HEX64.fullmatch(event_hash) is None or _HEX128.fullmatch(signature_hex) is None:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(signature_hex), domain + b"\n" + bytes.fromhex(event_hash))
        return True
    except Exception:
        return False


def _validate_config(config: DevAnchorConfig) -> None:
    if type(config) is not DevAnchorConfig:
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    if config.mode != "dev":
        raise AnchorServiceError("DEV_ONLY_REQUIRED")
    try:
        host = ipaddress.ip_address(config.bind_host)
    except (TypeError, ValueError):
        raise AnchorServiceError("LOOPBACK_ONLY") from None
    if not host.is_loopback:
        raise AnchorServiceError("LOOPBACK_ONLY")
    if (type(config.service_id) is not str or not config.service_id
            or len(config.service_id) > _MAX_ID
            or type(config.latestness_authority_id) is not str
            or not config.latestness_authority_id
            or len(config.latestness_authority_id) > _MAX_ID
            or type(config.key_authority_id) is not str or not config.key_authority_id
            or len(config.key_authority_id) > _MAX_ID
            or config.latestness_authority_id == config.key_authority_id):
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    if (not isinstance(config.database_path, Path) or not config.database_path.is_absolute()
            or not isinstance(config.project_root, Path) or not config.project_root.is_absolute()):
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    try:
        database_path = config.database_path.resolve()
        project_root = config.project_root.resolve()
        database_path.relative_to(project_root)
    except ValueError:
        pass
    except OSError:
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID") from None
    else:
        raise AnchorServiceError("ANCHOR_STATE_MUST_BE_OUTSIDE_REPOSITORY")
    for token in (config.bearer_token, config.admin_token):
        if type(token) is not str or not 32 <= len(token) <= 512 or token.strip() != token:
            raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    if hmac.compare_digest(config.bearer_token, config.admin_token):
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    for signer in (config.latestness_signer, config.key_authority_signer):
        if not isinstance(getattr(signer, "public_key_bytes", None), bytes):
            raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
        if not callable(getattr(signer, "sign", None)):
            raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
        if not _valid_public_key(signer.public_key_bytes):
            raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    if hmac.compare_digest(config.latestness_signer.public_key_bytes,
                           config.key_authority_signer.public_key_bytes):
        raise AnchorServiceError("ANCHOR_AUTHORITY_KEYS_MUST_BE_DISTINCT")


class SQLiteAnchorStore:
    """Append-only SQLite event store for dev checkpoints, keys, and one-use challenges."""

    def __init__(self, path: Path, service_id: str, *,
                 latestness_signer: DevAnchorSigner,
                 key_authority_signer: DevAnchorSigner) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
        if type(service_id) is not str or not service_id or len(service_id) > _MAX_ID:
            raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
        self._path = path.resolve()
        self._service_id = service_id
        self._latestness_signer = latestness_signer
        self._key_authority_signer = key_authority_signer
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._checkpoints_by_scope: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        self._latest_checkpoints_by_scope: dict[tuple[str, str], dict[str, Any]] = {}
        self._keys_by_scope: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._used_nonce_hashes: set[str] = set()
        self._head_revision = 0
        self._head_hash = _ZERO_HASH
        self._projection_valid = True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()
            with self._connection() as connection:
                connection.execute("BEGIN")
                events = self._replay(connection)
                connection.execute("COMMIT")
            self._install_projection(events)
        except AnchorServiceError:
            raise
        except Exception:
            raise AnchorServiceError("ANCHOR_HISTORY_UNAVAILABLE") from None

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._path), timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS events(
                    revision INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    tenant_id TEXT,
                    company_id TEXT,
                    accepted_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    authority_kind TEXT NOT NULL,
                    authority_signature TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS used_nonces(
                    nonce_hash TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'ANCHOR_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'ANCHOR_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS used_nonces_no_update
                BEFORE UPDATE ON used_nonces BEGIN SELECT RAISE(ABORT, 'ANCHOR_APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS used_nonces_no_delete
                BEFORE DELETE ON used_nonces BEGIN SELECT RAISE(ABORT, 'ANCHOR_APPEND_ONLY'); END;
            """)

    @staticmethod
    def _event_core(*, revision: int, event_id: str, event_type: str,
                    tenant_id: str | None, company_id: str | None,
                    accepted_at: str, payload: dict[str, object]) -> dict[str, object]:
        return {
            "revision": revision,
            "event_id": event_id,
            "event_type": event_type,
            "tenant_id": tenant_id,
            "company_id": company_id,
            "accepted_at": accepted_at,
            "payload": payload,
        }

    def _replay(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT revision,event_id,event_type,tenant_id,company_id,accepted_at,"
            "payload_json,previous_hash,event_hash,authority_kind,authority_signature "
            "FROM events ORDER BY revision"
        ).fetchall()
        if len(rows) > _MAX_EVENTS:
            raise AnchorServiceError("ANCHOR_HISTORY_LIMIT")
        previous = _ZERO_HASH
        expected_revision = 1
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                if type(payload) is not dict:
                    raise ValueError
                core = self._event_core(
                    revision=row["revision"], event_id=row["event_id"],
                    event_type=row["event_type"], tenant_id=row["tenant_id"],
                    company_id=row["company_id"], accepted_at=row["accepted_at"],
                    payload=payload,
                )
                serialized = canonical_json(payload).decode("utf-8")
                expected_hash = hashlib.sha256(
                    bytes.fromhex(previous) + b"\n" + canonical_json(core)
                ).hexdigest()
            except Exception:
                raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT") from None
            if (row["revision"] != expected_revision
                    or row["payload_json"] != serialized
                    or row["previous_hash"] != previous
                    or not isinstance(row["event_hash"], str)
                    or not hmac.compare_digest(row["event_hash"], expected_hash)):
                raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")
            authority_kind = self._authority_kind(row["event_type"])
            if row["authority_kind"] != authority_kind:
                raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")
            signer = (self._latestness_signer if authority_kind == "PROVIDER"
                      else self._key_authority_signer)
            domain = (_PROVIDER_HISTORY_DOMAIN if authority_kind == "PROVIDER"
                      else _KEY_HISTORY_DOMAIN)
            if not _verify_signed_hash(signer.public_key_bytes, domain, expected_hash,
                                       row["authority_signature"]):
                raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")
            event = dict(core)
            event["event_hash"] = expected_hash
            events.append(event)
            previous = expected_hash
            expected_revision += 1
        self._validate_nonce_projection(connection, events)
        return events

    def _check_database_head(self, connection: sqlite3.Connection) -> None:
        if not self._projection_valid:
            raise AnchorServiceError("ANCHOR_HISTORY_CHANGED")
        actual = connection.execute(
            "SELECT revision,event_hash FROM events ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        actual_revision = 0 if actual is None else actual["revision"]
        actual_hash = _ZERO_HASH if actual is None else actual["event_hash"]
        if (actual_revision != self._head_revision
                or not isinstance(actual_hash, str)
                or not hmac.compare_digest(actual_hash, self._head_hash)):
            raise AnchorServiceError("ANCHOR_HISTORY_CHANGED")

    def _begin_checked_write(self, connection: sqlite3.Connection) -> None:
        """Acquire the SQLite writer lock and compare its tail with the startup-verified cache.

        The signed history is replayed once at startup; API requests use indexed in-memory
        projections and an O(log n) tail check instead of re-verifying every historical signature.
        SQLite append-only triggers protect prior rows from ordinary service connections. A local
        host administrator can still replace or roll back the database, which is outside this
        dev-only trust boundary.
        """
        connection.execute("BEGIN IMMEDIATE")
        self._check_database_head(connection)

    def _begin_checked_read(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN")
        self._check_database_head(connection)

    def _install_projection(self, events: list[dict[str, Any]]) -> None:
        """Build the indexed runtime view from the fully replay-verified event history."""
        checkpoints: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        latest_checkpoints: dict[tuple[str, str], dict[str, Any]] = {}
        keys: dict[tuple[str, str, str], dict[str, Any]] = {}
        nonce_hashes: set[str] = set()
        for event in events:
            event_type = event["event_type"]
            tenant, company = event["tenant_id"], event["company_id"]
            payload = event["payload"]
            if event_type == "CHECKPOINT_ACCEPTED":
                record = payload["record"]
                scope = (tenant, company)
                checkpoints.setdefault(scope, {})[record["seq"]] = event
                latest_checkpoints[scope] = event
            elif event_type == "KEY_REGISTERED":
                key = (tenant, company, payload["key_id"])
                keys[key] = {"registration": event, "retirement": None, "revoked": None}
            elif event_type in {"KEY_RETIRED", "KEY_COMPROMISE_REVOKED"}:
                state = keys.get((tenant, company, payload["key_id"]))
                if state is not None:
                    state["retirement" if event_type == "KEY_RETIRED" else "revoked"] = event
            elif event_type in {"LATESTNESS_ATTESTED", "KEY_AUTHORIZATION_ATTESTED"}:
                nonce_hashes.add(payload["challenge_nonce_hash"])
        self._events = events
        self._checkpoints_by_scope = checkpoints
        self._latest_checkpoints_by_scope = latest_checkpoints
        self._keys_by_scope = keys
        self._used_nonce_hashes = nonce_hashes
        self._head_revision = events[-1]["revision"] if events else 0
        self._head_hash = events[-1]["event_hash"] if events else _ZERO_HASH

    def _accept_committed_event(self, event: dict[str, Any]) -> None:
        """Advance cache after commit; poison it if an exceptional partial update occurs."""
        try:
            self._apply_committed_event(event)
        except Exception:
            self._projection_valid = False
            raise AnchorServiceError("ANCHOR_HISTORY_CHANGED") from None

    def _apply_committed_event(self, event: dict[str, Any]) -> None:
        """Apply one event to in-memory indexes after its SQLite commit succeeds."""
        event_type = event["event_type"]
        tenant, company = event["tenant_id"], event["company_id"]
        payload = event["payload"]
        if event_type == "CHECKPOINT_ACCEPTED":
            record = payload["record"]
            scope = (tenant, company)
            self._checkpoints_by_scope.setdefault(scope, {})[record["seq"]] = event
            self._latest_checkpoints_by_scope[scope] = event
        elif event_type == "KEY_REGISTERED":
            self._keys_by_scope[(tenant, company, payload["key_id"])] = {
                "registration": event, "retirement": None, "revoked": None,
            }
        elif event_type in {"KEY_RETIRED", "KEY_COMPROMISE_REVOKED"}:
            state = self._keys_by_scope[(tenant, company, payload["key_id"])]
            state["retirement" if event_type == "KEY_RETIRED" else "revoked"] = event
        elif event_type in {"LATESTNESS_ATTESTED", "KEY_AUTHORIZATION_ATTESTED"}:
            self._used_nonce_hashes.add(payload["challenge_nonce_hash"])
        self._events.append(event)
        self._head_revision = event["revision"]
        self._head_hash = event["event_hash"]

    @staticmethod
    def _rollback_if_active(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

    def _key_state(self, tenant: str, company: str, key_id: str
                   ) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
        state = self._keys_by_scope.get((tenant, company, key_id))
        if state is None:
            return None, None, None
        registration = state["registration"]
        retirement = state["retirement"]
        revoked = state["revoked"]
        status = "COMPROMISE_REVOKED" if revoked else "RETIRED" if retirement else "ACTIVE"
        return registration, status, retirement or revoked

    def _checkpoint_event(self, tenant: str, company: str, seq: int
                          ) -> dict[str, Any] | None:
        return self._checkpoints_by_scope.get((tenant, company), {}).get(seq)

    def _latest_checkpoint_event(self, tenant: str, company: str
                                 ) -> dict[str, Any] | None:
        return self._latest_checkpoints_by_scope.get((tenant, company))

    @staticmethod
    def _authority_kind(event_type: str) -> str:
        if event_type in {"CHECKPOINT_ACCEPTED", "LATESTNESS_ATTESTED"}:
            return "PROVIDER"
        if event_type in {
            "KEY_REGISTERED", "KEY_RETIRED", "KEY_COMPROMISE_REVOKED",
            "KEY_AUTHORIZATION_ATTESTED",
        }:
            return "KEY_AUTHORITY"
        raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")

    @staticmethod
    def _validate_nonce_projection(connection: sqlite3.Connection,
                                   events: list[dict[str, Any]]) -> None:
        expected: dict[str, tuple[str, str, str]] = {}
        for event in events:
            if event["event_type"] not in {"LATESTNESS_ATTESTED", "KEY_AUTHORIZATION_ATTESTED"}:
                continue
            payload = event["payload"]
            nonce_hash = payload.get("challenge_nonce_hash")
            if (type(nonce_hash) is not str or _HEX64.fullmatch(nonce_hash) is None
                    or type(event["tenant_id"]) is not str
                    or type(event["company_id"]) is not str):
                raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")
            if nonce_hash in expected:
                raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")
            expected[nonce_hash] = (event["tenant_id"], event["company_id"], event["event_id"])
        rows = connection.execute(
            "SELECT nonce_hash,tenant_id,company_id,event_id FROM used_nonces"
        ).fetchall()
        actual = {row["nonce_hash"]: (row["tenant_id"], row["company_id"], row["event_id"])
                  for row in rows}
        if actual != expected:
            raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")

    def _append_event(self, connection: sqlite3.Connection, event_type: str,
                      tenant_id: str | None, company_id: str | None,
                      payload: dict[str, object]) -> dict[str, object]:
        if len(payload) > 32:
            raise AnchorServiceError("ANCHOR_EVENT_INVALID")
        row = connection.execute(
            "SELECT revision,event_hash FROM events ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        revision = 1 if row is None else int(row["revision"]) + 1
        if revision > _MAX_EVENTS:
            raise AnchorServiceError("ANCHOR_HISTORY_LIMIT")
        previous_hash = _ZERO_HASH if row is None else row["event_hash"]
        event_id = str(uuid4())
        accepted_at = _utc_text(datetime.now(UTC))
        core = self._event_core(
            revision=revision, event_id=event_id, event_type=event_type,
            tenant_id=tenant_id, company_id=company_id,
            accepted_at=accepted_at, payload=payload,
        )
        event_hash = hashlib.sha256(
            bytes.fromhex(previous_hash) + b"\n" + canonical_json(core)
        ).hexdigest()
        authority_kind = self._authority_kind(event_type)
        signer = (self._latestness_signer if authority_kind == "PROVIDER"
                  else self._key_authority_signer)
        domain = (_PROVIDER_HISTORY_DOMAIN if authority_kind == "PROVIDER"
                  else _KEY_HISTORY_DOMAIN)
        signature = _sign(signer, domain + b"\n" + bytes.fromhex(event_hash))
        try:
            connection.execute(
                "INSERT INTO events(revision,event_id,event_type,tenant_id,company_id,accepted_at,"
                "payload_json,previous_hash,event_hash,authority_kind,authority_signature) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (revision, event_id, event_type, tenant_id, company_id, accepted_at,
                 canonical_json(payload).decode("utf-8"), previous_hash, event_hash,
                 authority_kind, signature),
            )
        except Exception:
            raise AnchorServiceError("ANCHOR_HISTORY_WRITE_FAILED") from None
        return {**core, "event_hash": event_hash}

    @staticmethod
    def _scope(tenant_id: object, company_id: object) -> tuple[str, str]:
        if (type(tenant_id) is not str or not tenant_id or len(tenant_id) > _MAX_ID
                or type(company_id) is not str or not company_id or len(company_id) > _MAX_ID):
            raise AnchorServiceError("SCOPE_INVALID")
        return tenant_id, company_id

    def register_key(self, tenant_id: object, company_id: object, key_id: object,
                     public_key_hex: object, role: object = "checkpoint_signer") -> bool:
        tenant, company = self._scope(tenant_id, company_id)
        if (type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None
                or type(public_key_hex) is not str or not re.fullmatch(r"[0-9a-f]{64}", public_key_hex)
                or role != "checkpoint_signer"):
            raise AnchorServiceError("KEY_REGISTRATION_INVALID")
        public_key = bytes.fromhex(public_key_hex)
        if not _valid_public_key(public_key):
            raise AnchorServiceError("KEY_REGISTRATION_INVALID")
        with self._lock, self._connection() as connection:
            try:
                self._begin_checked_write(connection)
                existing, _, _ = self._key_state(tenant, company, key_id)
                if existing is not None:
                    existing_payload = existing["payload"]
                    if (existing_payload.get("public_key_hex") != public_key_hex
                            or existing_payload.get("role") != role):
                        raise AnchorServiceError("KEY_ALREADY_REGISTERED")
                    connection.execute("COMMIT")
                    return False
                event = self._append_event(connection, "KEY_REGISTERED", tenant, company, {
                    "key_id": key_id, "public_key_hex": public_key_hex,
                    "role": "checkpoint_signer",
                })
                connection.execute("COMMIT")
                self._accept_committed_event(event)
                return True
            except AnchorServiceError:
                self._rollback_if_active(connection)
                raise
            except Exception:
                self._rollback_if_active(connection)
                raise AnchorServiceError("ANCHOR_HISTORY_WRITE_FAILED") from None

    def retire_key(self, tenant_id: object, company_id: object, key_id: object) -> bool:
        tenant, company = self._scope(tenant_id, company_id)
        if type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None:
            raise AnchorServiceError("KEY_ID_INVALID")
        with self._lock, self._connection() as connection:
            try:
                self._begin_checked_write(connection)
                registration, state, _ = self._key_state(tenant, company, key_id)
                if registration is None:
                    raise AnchorServiceError("KEY_NOT_ACTIVE")
                if state == "RETIRED":
                    connection.execute("COMMIT")
                    return False
                if state != "ACTIVE":
                    raise AnchorServiceError("KEY_NOT_ACTIVE")
                event = self._append_event(connection, "KEY_RETIRED", tenant, company,
                                           {"key_id": key_id, "receipt_id": str(uuid4())})
                connection.execute("COMMIT")
                self._accept_committed_event(event)
                return True
            except AnchorServiceError:
                self._rollback_if_active(connection)
                raise
            except Exception:
                self._rollback_if_active(connection)
                raise AnchorServiceError("ANCHOR_HISTORY_WRITE_FAILED") from None

    def compromise_revoke_key(self, tenant_id: object, company_id: object,
                               key_id: object) -> bool:
        tenant, company = self._scope(tenant_id, company_id)
        if type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None:
            raise AnchorServiceError("KEY_ID_INVALID")
        with self._lock, self._connection() as connection:
            try:
                self._begin_checked_write(connection)
                registration, state, _ = self._key_state(tenant, company, key_id)
                if registration is None:
                    raise AnchorServiceError("KEY_NOT_ACTIVE")
                if state == "COMPROMISE_REVOKED":
                    connection.execute("COMMIT")
                    return False
                event = self._append_event(connection, "KEY_COMPROMISE_REVOKED", tenant, company,
                                           {"key_id": key_id, "receipt_id": str(uuid4())})
                connection.execute("COMMIT")
                self._accept_committed_event(event)
                return True
            except AnchorServiceError:
                self._rollback_if_active(connection)
                raise
            except Exception:
                self._rollback_if_active(connection)
                raise AnchorServiceError("ANCHOR_HISTORY_WRITE_FAILED") from None

    def write_checkpoint(self, record: CheckpointRecord) -> dict[str, object]:
        if type(record) is not CheckpointRecord:
            raise AnchorServiceError("CHECKPOINT_INVALID")
        serialized = _record_json(record)
        parsed = _parse_record(serialized, service_id=self._service_id)
        try:
            identity = checkpoint_identity(parsed)
        except Exception:
            raise AnchorServiceError("CHECKPOINT_INVALID") from None
        with self._lock, self._connection() as connection:
            try:
                self._begin_checked_write(connection)
                registration, state, _ = self._key_state(
                    parsed.tenant_id, parsed.company_id, parsed.key_id)
                if registration is None or state != "ACTIVE":
                    raise AnchorServiceError("CHECKPOINT_KEY_NOT_ACTIVE")
                public_key_hex = registration["payload"].get("public_key_hex")
                if type(public_key_hex) is not str:
                    raise AnchorServiceError("ANCHOR_HISTORY_CORRUPT")
                public_key = bytes.fromhex(public_key_hex)
                if not _verify_checkpoint_signature(public_key, parsed):
                    raise AnchorServiceError("CHECKPOINT_SIGNATURE_INVALID")
                prior = self._checkpoints_by_scope.get(
                    (parsed.tenant_id, parsed.company_id), {})
                existing = prior.get(parsed.seq)
                if existing is not None:
                    if existing["payload"].get("checkpoint_digest") != identity:
                        raise AnchorServiceError("CHECKPOINT_CONFLICT")
                    connection.execute("COMMIT")
                    return _record_json(parsed)
                latest = self._latest_checkpoint_event(parsed.tenant_id, parsed.company_id)
                if latest is not None and parsed.seq <= int(latest["payload"]["record"]["seq"]):
                    raise AnchorServiceError("CHECKPOINT_ROLLBACK")
                provider_revision = (1 if latest is None
                                     else int(latest["payload"]["provider_revision"]) + 1)
                event = self._append_event(connection, "CHECKPOINT_ACCEPTED", parsed.tenant_id,
                                           parsed.company_id, {
                    "record": serialized,
                    "checkpoint_digest": identity,
                    "provider_revision": provider_revision,
                })
                connection.execute("COMMIT")
                self._accept_committed_event(event)
                return serialized
            except AnchorServiceError:
                self._rollback_if_active(connection)
                raise
            except Exception:
                self._rollback_if_active(connection)
                raise AnchorServiceError("ANCHOR_HISTORY_WRITE_FAILED") from None

    def latest_checkpoint(self, tenant_id: object, company_id: object
                           ) -> dict[str, object] | None:
        tenant, company = self._scope(tenant_id, company_id)
        with self._lock, self._connection() as connection:
            self._begin_checked_read(connection)
            connection.execute("COMMIT")
        latest = self._latest_checkpoint_event(tenant, company)
        if latest is None:
            return None
        return latest["payload"]["record"]

    def read_checkpoint(self, tenant_id: object, company_id: object, seq: object
                        ) -> dict[str, object] | None:
        tenant, company = self._scope(tenant_id, company_id)
        if type(seq) is not int or seq < 1:
            raise AnchorServiceError("CHECKPOINT_SEQUENCE_INVALID")
        with self._lock, self._connection() as connection:
            self._begin_checked_read(connection)
            connection.execute("COMMIT")
        event = self._checkpoint_event(tenant, company, seq)
        return None if event is None else event["payload"]["record"]

    def attest_latest(self, tenant_id: object, company_id: object,
                      checkpoint_digest: object, challenge_nonce: object,
                      *, authority_id: str, signer: DevAnchorSigner
                      ) -> tuple[dict[str, object], str]:
        tenant, company = self._scope(tenant_id, company_id)
        if (type(checkpoint_digest) is not str or _HEX64.fullmatch(checkpoint_digest) is None
                or type(challenge_nonce) is not str or _NONCE.fullmatch(challenge_nonce) is None):
            raise AnchorServiceError("LATESTNESS_REQUEST_INVALID")
        nonce_hash = hashlib.sha256(bytes.fromhex(challenge_nonce)).hexdigest()
        with self._lock, self._connection() as connection:
            try:
                self._begin_checked_write(connection)
                latest_event = self._latest_checkpoint_event(tenant, company)
                if latest_event is None:
                    raise AnchorServiceError("CHECKPOINT_NOT_FOUND")
                if latest_event["payload"].get("checkpoint_digest") != checkpoint_digest:
                    raise AnchorServiceError("CHECKPOINT_NOT_LATEST")
                if (nonce_hash in self._used_nonce_hashes or connection.execute(
                    "SELECT 1 FROM used_nonces WHERE nonce_hash=?", (nonce_hash,)
                ).fetchone() is not None):
                    raise AnchorServiceError("LATESTNESS_NONCE_REPLAY")
                authority_event = self._append_event(
                    connection, "LATESTNESS_ATTESTED", tenant, company, {
                        "checkpoint_digest": checkpoint_digest,
                        "challenge_nonce_hash": nonce_hash,
                        "provider_revision": latest_event["payload"]["provider_revision"],
                        "provider_event_id": latest_event["event_id"],
                    },
                )
                connection.execute(
                    "INSERT INTO used_nonces(nonce_hash,tenant_id,company_id,event_id) "
                    "VALUES(?,?,?,?)",
                    (nonce_hash, tenant, company, authority_event["event_id"]),
                )
                evidence: dict[str, object] = {
                    "tenant_id": tenant,
                    "company_id": company,
                    "checkpoint_digest": checkpoint_digest,
                    "challenge_nonce": challenge_nonce,
                    "provider_id": self._service_id,
                    "provider_revision": latest_event["payload"]["provider_revision"],
                    "authority_id": authority_id,
                    "authority_revision": authority_event["revision"],
                    "authority_event_id": authority_event["event_id"],
                    "policy_version": _POLICY_VERSION,
                }
                evidence["proof_digest"] = _latestness_evidence_digest(evidence)
                signature = _sign(signer, _authority_preimage(LATESTNESS_SIGNING_DOMAIN, evidence))
                connection.execute("COMMIT")
                self._accept_committed_event(authority_event)
                return evidence, signature
            except AnchorServiceError:
                self._rollback_if_active(connection)
                raise
            except Exception:
                self._rollback_if_active(connection)
                raise AnchorServiceError("ANCHOR_HISTORY_WRITE_FAILED") from None

    def authorize_checkpoint(self, record: CheckpointRecord, challenge_nonce: object,
                             *, authority_id: str, signer: DevAnchorSigner
                             ) -> tuple[dict[str, object], str]:
        if type(record) is not CheckpointRecord:
            raise AnchorServiceError("CHECKPOINT_INVALID")
        if type(challenge_nonce) is not str or _NONCE.fullmatch(challenge_nonce) is None:
            raise AnchorServiceError("KEY_AUTH_REQUEST_INVALID")
        try:
            digest = checkpoint_identity(record)
        except Exception:
            raise AnchorServiceError("CHECKPOINT_INVALID") from None
        nonce_hash = hashlib.sha256(bytes.fromhex(challenge_nonce)).hexdigest()
        with self._lock, self._connection() as connection:
            try:
                self._begin_checked_write(connection)
                if (nonce_hash in self._used_nonce_hashes or connection.execute(
                    "SELECT 1 FROM used_nonces WHERE nonce_hash=?", (nonce_hash,)
                ).fetchone() is not None):
                    raise AnchorServiceError("KEY_AUTH_NONCE_REPLAY")
                registration, state, terminal_event = self._key_state(
                    record.tenant_id, record.company_id, record.key_id)
                if registration is None or state == "COMPROMISE_REVOKED":
                    raise AnchorServiceError("CHECKPOINT_KEY_AUTHORIZATION_DENIED")
                if registration["payload"].get("role") != "checkpoint_signer":
                    raise AnchorServiceError("CHECKPOINT_KEY_AUTHORIZATION_DENIED")
                accepted = self._checkpoint_event(
                    record.tenant_id, record.company_id, record.seq)
                if (accepted is not None
                        and accepted["payload"].get("checkpoint_digest") != digest):
                    accepted = None
                if accepted is None:
                    raise AnchorServiceError("CHECKPOINT_KEY_AUTHORIZATION_DENIED")
                if state == "RETIRED":
                    if terminal_event is None or accepted["revision"] >= terminal_event["revision"]:
                        raise AnchorServiceError("CHECKPOINT_KEY_AUTHORIZATION_DENIED")
                    basis = "ROUTINE_RETIREMENT_RECEIPT"
                    receipt_id = f"checkpoint-accepted:{accepted['event_id']}"
                    accepted_at: str | None = accepted["accepted_at"]
                elif state == "ACTIVE":
                    basis = "ACTIVE"
                    receipt_id = None
                    accepted_at = None
                else:
                    raise AnchorServiceError("CHECKPOINT_KEY_AUTHORIZATION_DENIED")
                authority_event = self._append_event(
                    connection, "KEY_AUTHORIZATION_ATTESTED", record.tenant_id,
                    record.company_id, {
                        "key_id": record.key_id,
                        "checkpoint_digest": digest,
                        "challenge_nonce_hash": nonce_hash,
                        "basis": basis,
                        "receipt_id": receipt_id,
                    },
                )
                connection.execute(
                    "INSERT INTO used_nonces(nonce_hash,tenant_id,company_id,event_id) "
                    "VALUES(?,?,?,?)",
                    (nonce_hash, record.tenant_id, record.company_id,
                     authority_event["event_id"]),
                )
                evidence: dict[str, object] = {
                    "tenant_id": record.tenant_id,
                    "company_id": record.company_id,
                    "key_id": record.key_id,
                    "public_key_digest": hashlib.sha256(
                        bytes.fromhex(registration["payload"]["public_key_hex"])
                    ).hexdigest(),
                    "checkpoint_digest": digest,
                    "authority_id": authority_id,
                    "authority_revision": authority_event["revision"],
                    "authority_event_id": authority_event["event_id"],
                    "policy_version": _POLICY_VERSION,
                    "basis": basis,
                    "receipt_id": receipt_id,
                    "accepted_at": accepted_at,
                    "challenge_nonce": challenge_nonce,
                }
                signature = _sign(signer, _authority_preimage(KEY_AUTH_SIGNING_DOMAIN, evidence))
                connection.execute("COMMIT")
                self._accept_committed_event(authority_event)
                return evidence, signature
            except AnchorServiceError:
                self._rollback_if_active(connection)
                raise
            except Exception:
                self._rollback_if_active(connection)
                raise AnchorServiceError("ANCHOR_HISTORY_WRITE_FAILED") from None


def _status_for(code: str) -> int:
    if code == "AUTH_FAILED":
        return 401
    if code in {"DEV_ONLY_REQUIRED", "LOOPBACK_ONLY", "ANCHOR_AUTHORITY_KEYS_MUST_BE_DISTINCT",
                "ANCHOR_STATE_MUST_BE_OUTSIDE_REPOSITORY"}:
        return 403
    if code in {"ANCHOR_HISTORY_UNAVAILABLE", "ANCHOR_HISTORY_CORRUPT",
                "ANCHOR_HISTORY_WRITE_FAILED", "ANCHOR_HISTORY_CHANGED",
                "ANCHOR_SIGNING_UNAVAILABLE"}:
        return 503
    if code in {"CHECKPOINT_NOT_FOUND"}:
        return 404
    if code in {
        "CHECKPOINT_CONFLICT", "CHECKPOINT_ROLLBACK", "CHECKPOINT_NOT_LATEST",
        "LATESTNESS_NONCE_REPLAY", "KEY_AUTH_NONCE_REPLAY", "KEY_ALREADY_REGISTERED",
        "KEY_NOT_ACTIVE", "CHECKPOINT_KEY_NOT_ACTIVE",
    }:
        return 409
    if code in {"CHECKPOINT_KEY_AUTHORIZATION_DENIED"}:
        return 403
    return 400


def _authorization_ok(request: Request, token: str) -> bool:
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {token}"
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


async def _json_body(request: Request) -> dict[str, Any]:
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) < 0 or int(length) > _MAX_REQUEST_BYTES:
                raise AnchorServiceError("REQUEST_TOO_LARGE")
        except ValueError:
            raise AnchorServiceError("REQUEST_INVALID") from None
    body = await request.body()
    if len(body) > _MAX_REQUEST_BYTES:
        raise AnchorServiceError("REQUEST_TOO_LARGE")
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        value = json.loads(body, object_pairs_hook=unique_object)
    except Exception:
        raise AnchorServiceError("REQUEST_INVALID") from None
    if type(value) is not dict:
        raise AnchorServiceError("REQUEST_INVALID")
    return value


class _RequestBodyTooLarge(Exception):
    pass


class _BodyLimitASGI:
    """ASGI receive wrapper that bounds both fixed-length and chunked request bodies."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def __getattr__(self, name: str) -> Any:
        # Preserve Starlette's state/test-client surface through the ASGI body-limit wrapper.
        return getattr(self._app, name)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        length = None
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    length = int(value.decode("ascii"))
                except Exception:
                    length = _MAX_REQUEST_BYTES + 1
                break
        if length is not None and (length < 0 or length > _MAX_REQUEST_BYTES):
            await JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)(
                scope, receive, send)
            return
        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > _MAX_REQUEST_BYTES:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self._app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)(
                scope, receive, send)


def create_app(config: DevAnchorConfig, store: SQLiteAnchorStore | None = None) -> Starlette:
    """Build a dev-only ASGI app; no gateway route or production composition is registered."""
    _validate_config(config)
    anchor_store = store or SQLiteAnchorStore(
        config.database_path, config.service_id,
        latestness_signer=config.latestness_signer,
        key_authority_signer=config.key_authority_signer,
    )
    if anchor_store.path == config.project_root.resolve() or config.project_root.resolve() in anchor_store.path.parents:
        raise AnchorServiceError("ANCHOR_STATE_MUST_BE_OUTSIDE_REPOSITORY")
    if anchor_store.path != config.database_path.resolve():
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    if anchor_store._service_id != config.service_id:
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID")
    if (not hmac.compare_digest(anchor_store._latestness_signer.public_key_bytes,
                                config.latestness_signer.public_key_bytes)
            or not hmac.compare_digest(anchor_store._key_authority_signer.public_key_bytes,
                                       config.key_authority_signer.public_key_bytes)):
        raise AnchorServiceError("ANCHOR_CONFIG_INVALID")

    async def endpoint(request: Request) -> Response:
        if not _authorization_ok(request, config.bearer_token):
            return JSONResponse({"error": "AUTH_FAILED"}, status_code=401)
        try:
            route = request.url.path
            if route == "/v1/health" and request.method == "GET":
                # Liveness only: mutation endpoints separately fail closed if storage/signing dies.
                return JSONResponse({"service_id": config.service_id, "mode": "dev", "sink_kind": "TEST"})
            if route == "/v1/checkpoints" and request.method == "POST":
                body = await _json_body(request)
                if set(body) != {"record"}:
                    raise AnchorServiceError("REQUEST_INVALID")
                record = _parse_record(body["record"], service_id=config.service_id)
                stored = await asyncio.to_thread(anchor_store.write_checkpoint, record)
                return JSONResponse({"record": stored}, status_code=200)
            if route == "/v1/checkpoints/latest" and request.method == "GET":
                if (set(request.query_params.keys()) != {"tenant_id", "company_id"}
                        or any(len(request.query_params.getlist(name)) != 1
                               for name in ("tenant_id", "company_id"))):
                    raise AnchorServiceError("REQUEST_INVALID")
                record = await asyncio.to_thread(
                    anchor_store.latest_checkpoint, request.query_params.get("tenant_id"),
                    request.query_params.get("company_id"),
                )
                if record is None:
                    return JSONResponse({"error": "CHECKPOINT_NOT_FOUND"}, status_code=404)
                return JSONResponse({"record": record})
            if route == "/v1/checkpoints/read-back" and request.method == "GET":
                if (set(request.query_params.keys()) != {"tenant_id", "company_id", "seq"}
                        or any(len(request.query_params.getlist(name)) != 1
                               for name in ("tenant_id", "company_id", "seq"))):
                    raise AnchorServiceError("REQUEST_INVALID")
                seq_text = request.query_params.get("seq")
                if (type(seq_text) is not str or not seq_text.isascii()
                        or not seq_text.isdigit() or len(seq_text) > 18):
                    raise AnchorServiceError("CHECKPOINT_SEQUENCE_INVALID")
                record = await asyncio.to_thread(
                    anchor_store.read_checkpoint, request.query_params.get("tenant_id"),
                    request.query_params.get("company_id"), int(seq_text),
                )
                if record is None:
                    return JSONResponse({"error": "CHECKPOINT_NOT_FOUND"}, status_code=404)
                return JSONResponse({"record": record})
            if route == "/v1/latestness" and request.method == "POST":
                body = await _json_body(request)
                if set(body) != {"tenant_id", "company_id", "checkpoint_digest", "challenge_nonce"}:
                    raise AnchorServiceError("LATESTNESS_REQUEST_INVALID")
                evidence, signature = await asyncio.to_thread(
                    anchor_store.attest_latest, body["tenant_id"], body["company_id"],
                    body["checkpoint_digest"], body["challenge_nonce"],
                    authority_id=config.latestness_authority_id,
                    signer=config.latestness_signer,
                )
                return JSONResponse({"evidence": evidence, "signature": signature})
            if route == "/v1/key-authorizations" and request.method == "POST":
                body = await _json_body(request)
                if set(body) != {"record", "challenge_nonce"}:
                    raise AnchorServiceError("KEY_AUTH_REQUEST_INVALID")
                record = _parse_record(body["record"], service_id=config.service_id)
                evidence, signature = await asyncio.to_thread(
                    anchor_store.authorize_checkpoint, record, body["challenge_nonce"],
                    authority_id=config.key_authority_id,
                    signer=config.key_authority_signer,
                )
                return JSONResponse({"evidence": evidence, "signature": signature})
            if route.startswith("/v1/admin/keys/") and request.method == "POST":
                admin_supplied = request.headers.get("x-anchor-admin-token", "")
                if not hmac.compare_digest(admin_supplied.encode("utf-8"),
                                           config.admin_token.encode("utf-8")):
                    raise AnchorServiceError("AUTH_FAILED")
                body = await _json_body(request)
                if route == "/v1/admin/keys/register":
                    if set(body) != {"tenant_id", "company_id", "key_id", "public_key_hex", "role"}:
                        raise AnchorServiceError("KEY_REGISTRATION_INVALID")
                    changed = await asyncio.to_thread(
                        anchor_store.register_key, body["tenant_id"], body["company_id"],
                        body["key_id"], body["public_key_hex"], body["role"],
                    )
                    return JSONResponse({"accepted": True, "changed": changed},
                                        status_code=201 if changed else 200)
                if route in {"/v1/admin/keys/retire", "/v1/admin/keys/revoke"}:
                    if set(body) != {"tenant_id", "company_id", "key_id"}:
                        raise AnchorServiceError("REQUEST_INVALID")
                    method = (anchor_store.retire_key if route.endswith("/retire")
                              else anchor_store.compromise_revoke_key)
                    changed = await asyncio.to_thread(
                        method, body["tenant_id"], body["company_id"], body["key_id"],
                    )
                    return JSONResponse({"accepted": True, "changed": changed},
                                        status_code=201 if changed else 200)
            raise AnchorServiceError("ROUTE_NOT_FOUND")
        except AnchorServiceError as exc:
            return JSONResponse({"error": exc.code}, status_code=_status_for(exc.code))
        except _RequestBodyTooLarge:
            raise
        except Exception:
            _LOGGER.warning("dev anchor request refused code=ANCHOR_INTERNAL_ERROR")
            return JSONResponse({"error": "ANCHOR_INTERNAL_ERROR"}, status_code=503)

    app = Starlette(routes=[Route("/{path:path}", endpoint, methods=["GET", "POST"])])
    app.state.dev_anchor_config = config
    app.state.dev_anchor_store = anchor_store
    return _BodyLimitASGI(app)
