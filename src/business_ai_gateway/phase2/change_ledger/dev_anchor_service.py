"""Local, development-only HTTP anchor service for S13 checkpoint exercises.

This service is a separate process and keeps a SQLite append-only event history so S13 callers
can exercise the real HTTP, persistence, ordering, and replay boundaries. It is intentionally
marked TEST and is never composed by the gateway runtime. Its local signing key and database do
not establish production trust roots, external immutability, or protection from host-level
rollback. Its optional routine-retirement receipt is static synthetic input used to exercise the
historical-key contract; it is not an independently governed key-history service. Missing
configuration fails closed.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import hmac
import ipaddress
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ._common import Scope
from .checkpoint import (
    CheckpointKeyAuthorization,
    CheckpointKeyAuthorizationAuthority,
    CheckpointKeyAuthorizationBasis,
    CheckpointLatestnessAuthority,
    CheckpointLatestnessEvidence,
    CheckpointRecord,
    CheckpointSink,
    SignatureVerifier,
    checkpoint_identity,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_SERVICE_ID = "erp-mcp-dev-anchor-v1"
_SQLITE_APPLICATION_ID = 0x4552414E
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CHECKPOINT_SIGNATURE_RE = re.compile(r"^(?:[0-9a-f]{64}|[0-9a-f]{128})$")
_AUTHORITY_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$")
_MAX_BODY_BYTES = 16 * 1024
_MAX_IDENTIFIER = 128
_MAX_KEY_REGISTRY_BYTES = 16 * 1024
_MAX_REGISTERED_KEYS = 128
_PROOF_DOMAIN = b"erp-mcp-dev-anchor-latest|v1\0"
_KEY_AUTH_PROOF_DOMAIN = b"erp-mcp-dev-anchor-key-authorization|v1\0"
_AUTHORITY_KEY_ENV_PAIRS = {
    "ERP_MCP_DEV_ANCHOR_LATEST_PRIVATE_KEY_B64":
        "ERP_MCP_DEV_ANCHOR_LATEST_PUBLIC_KEY_B64",
    "ERP_MCP_DEV_ANCHOR_KEY_AUTH_PRIVATE_KEY_B64":
        "ERP_MCP_DEV_ANCHOR_KEY_AUTH_PUBLIC_KEY_B64",
}
_MAX_HISTORY_ROWS = 10000
_MAX_TOTAL_ROWS = 10000


class DevAnchorError(Exception):
    """Sanitized protocol failure; exception detail must never contain credentials or payloads."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _RegisteredCheckpointKey:
    public_key: Any
    basis: CheckpointKeyAuthorizationBasis
    receipt_id: str | None = None
    accepted_at: datetime | None = None
    accepted_through_seq: int | None = None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _scope_value(tenant_id: Any, company_id: Any) -> Scope:
    if (type(tenant_id) is not str or not tenant_id or len(tenant_id) > _MAX_IDENTIFIER
            or type(company_id) is not str or not company_id
            or len(company_id) > _MAX_IDENTIFIER):
        raise DevAnchorError("INVALID_SCOPE")
    return Scope(tenant_id, company_id)


def _record_dict(record: CheckpointRecord) -> dict[str, Any]:
    return {
        "tenant_id": record.tenant_id,
        "company_id": record.company_id,
        "seq": record.seq,
        "head_hash": record.head_hash,
        "signed_at": record.signed_at.isoformat(),
        "key_id": record.key_id,
        "signature": record.signature,
        "sink_id": record.sink_id,
        "sink_kind": record.sink_kind,
    }


def _anchor_event_digest(scope: Scope, revision: int, seq: int, event_id: str,
                        checkpoint_digest: str, previous_digest: str | None) -> str:
    event_body = {
        "tenant_id": scope.tenant_id, "company_id": scope.company_id,
        "revision": revision, "seq": seq, "event_id": event_id,
        "checkpoint_digest": checkpoint_digest, "previous_digest": previous_digest,
    }
    return hashlib.sha256(
        b"erp-mcp-dev-anchor-event|v1\0" + _canonical(event_body)
    ).hexdigest()


def _parse_record(value: Any) -> CheckpointRecord:
    fields = {"tenant_id", "company_id", "seq", "head_hash", "signed_at", "key_id",
              "signature", "sink_id", "sink_kind"}
    if type(value) is not dict or set(value) != fields:
        raise DevAnchorError("INVALID_CHECKPOINT")
    try:
        record = CheckpointRecord(
            tenant_id=value["tenant_id"], company_id=value["company_id"],
            seq=value["seq"], head_hash=value["head_hash"],
            signed_at=datetime.fromisoformat(value["signed_at"]), key_id=value["key_id"],
            signature=value["signature"], sink_id=value["sink_id"],
            sink_kind=value["sink_kind"],
        )
    except (TypeError, ValueError, KeyError):
        raise DevAnchorError("INVALID_CHECKPOINT") from None
    if (type(record.tenant_id) is not str or not record.tenant_id
            or len(record.tenant_id) > _MAX_IDENTIFIER
            or type(record.company_id) is not str or not record.company_id
            or len(record.company_id) > _MAX_IDENTIFIER
            or type(record.seq) is not int or record.seq < 1
            or type(record.head_hash) is not str or not _HASH_RE.fullmatch(record.head_hash)
            or type(record.signed_at) is not datetime or record.signed_at.tzinfo is None
            or record.signed_at.utcoffset() is None
            or type(record.key_id) is not str or not _KEY_ID_RE.fullmatch(record.key_id)
            or type(record.signature) is not str
            or not _CHECKPOINT_SIGNATURE_RE.fullmatch(record.signature)
            or type(record.sink_id) is not str or not record.sink_id
            or len(record.sink_id) > _MAX_IDENTIFIER or record.sink_kind != "TEST"):
        raise DevAnchorError("INVALID_CHECKPOINT")
    return record


def _verify_checkpoint(verifier: SignatureVerifier, record: CheckpointRecord) -> bool:
    try:
        return verifier.verify(record.key_id, record.signing_payload(), record.signature) is True
    except Exception:
        return False


def _private_key_from_environment():
    encoded = os.environ.get("ERP_MCP_DEV_ANCHOR_PRIVATE_KEY_B64", "")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != 32:
            raise ValueError
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception:
        raise DevAnchorError("SERVICE_CONFIGURATION_INVALID") from None


def _validate_authority_keypair() -> None:
    private_key = _private_key_from_environment()
    public_key = _public_key_from_base64(
        os.environ.get("ERP_MCP_DEV_ANCHOR_PUBLIC_KEY_B64", "")
    )
    from cryptography.hazmat.primitives import serialization

    private_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    public_raw = public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    if not hmac.compare_digest(private_raw, public_raw):
        raise DevAnchorError("SERVICE_CONFIGURATION_INVALID")
    registry = _checkpoint_public_keys(
        os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
    )
    if any(hmac.compare_digest(
            public_raw,
            key.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
    ) for key in registry.values()):
        raise DevAnchorError("SERVICE_KEY_ROLE_COLLISION")


def _authority_private_key_from_environment(env_name: str):
    public_env_name = _AUTHORITY_KEY_ENV_PAIRS.get(env_name)
    encoded_private = os.environ.get(env_name, "")
    encoded_public = "" if public_env_name is None else os.environ.get(public_env_name, "")
    try:
        raw = base64.b64decode(encoded_private, validate=True)
        if len(raw) != 32:
            raise ValueError
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key = Ed25519PrivateKey.from_private_bytes(raw)
        public_key = _public_key_from_base64(encoded_public)
        derived_public = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        configured_public = public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        if public_env_name is None or not hmac.compare_digest(derived_public, configured_public):
            raise ValueError
        return private_key
    except Exception:
        raise DevAnchorError("SERVICE_CONFIGURATION_INVALID") from None


def _validate_authority_keypairs() -> None:
    from cryptography.hazmat.primitives import serialization

    public_keys = []
    for private_env_name in _AUTHORITY_KEY_ENV_PAIRS:
        private_key = _authority_private_key_from_environment(private_env_name)
        public_keys.append(private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        ))
    if hmac.compare_digest(public_keys[0], public_keys[1]):
        raise DevAnchorError("SERVICE_KEY_ROLE_COLLISION")
    checkpoint_keys = _checkpoint_public_keys(
        os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
    )
    for authority_public in public_keys:
        for checkpoint_key in checkpoint_keys.values():
            checkpoint_public = checkpoint_key.public_key.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            )
            if hmac.compare_digest(authority_public, checkpoint_public):
                raise DevAnchorError("SERVICE_KEY_ROLE_COLLISION")


@lru_cache(maxsize=4)
def _checkpoint_public_keys(
        encoded: str) -> dict[tuple[str, str, str], _RegisteredCheckpointKey]:
    if type(encoded) is not str or not encoded or len(encoded) > _MAX_KEY_REGISTRY_BYTES:
        raise DevAnchorError("CHECKPOINT_KEY_REGISTRY_INVALID")
    try:
        entries = json.loads(encoded)
        if type(entries) is not list or not 1 <= len(entries) <= _MAX_REGISTERED_KEYS:
            raise ValueError
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        keys: dict[tuple[str, str, str], _RegisteredCheckpointKey] = {}
        for entry in entries:
            base_fields = {"tenant_id", "company_id", "key_id", "public_key_b64"}
            retired_fields = base_fields | {
                "basis", "receipt_id", "accepted_at", "accepted_through_seq",
            }
            if (type(entry) is not dict
                    or set(entry) not in (base_fields, retired_fields)
                    or type(entry["tenant_id"]) is not str or not entry["tenant_id"]
                    or len(entry["tenant_id"]) > _MAX_IDENTIFIER
                    or type(entry["company_id"]) is not str or not entry["company_id"]
                    or len(entry["company_id"]) > _MAX_IDENTIFIER
                    or type(entry["key_id"]) is not str
                    or not _KEY_ID_RE.fullmatch(entry["key_id"])
                    or type(entry["public_key_b64"]) is not str):
                raise ValueError
            public_key_bytes = base64.b64decode(entry["public_key_b64"], validate=True)
            if len(public_key_bytes) != 32:
                raise ValueError
            identity = (entry["tenant_id"], entry["company_id"], entry["key_id"])
            if identity in keys:
                raise ValueError
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            if set(entry) == base_fields:
                keys[identity] = _RegisteredCheckpointKey(
                    public_key, CheckpointKeyAuthorizationBasis.ACTIVE,
                )
            else:
                if entry["basis"] != CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT.value:
                    raise ValueError
                receipt_id = entry["receipt_id"]
                accepted_at_raw = entry["accepted_at"]
                accepted_through_seq = entry["accepted_through_seq"]
                if (type(receipt_id) is not str or not receipt_id
                        or receipt_id != receipt_id.strip() or len(receipt_id) > 256
                        or type(accepted_at_raw) is not str or not accepted_at_raw
                        or type(accepted_through_seq) is not int or accepted_through_seq < 1):
                    raise ValueError
                accepted_at = datetime.fromisoformat(accepted_at_raw.replace("Z", "+00:00"))
                if accepted_at.tzinfo is None or accepted_at.utcoffset() is None:
                    raise ValueError
                keys[identity] = _RegisteredCheckpointKey(
                    public_key, CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT,
                    receipt_id, accepted_at, accepted_through_seq,
                )
        return keys
    except Exception:
        raise DevAnchorError("CHECKPOINT_KEY_REGISTRY_INVALID") from None


def _verify_server_checkpoint(scope: Scope, record: CheckpointRecord) -> bool:
    try:
        registered_key = _checkpoint_public_keys(
            os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
        ).get((scope.tenant_id, scope.company_id, record.key_id))
        if registered_key is None or not _AUTHORITY_SIGNATURE_RE.fullmatch(record.signature):
            return False
        registered_key.public_key.verify(bytes.fromhex(record.signature), record.signing_payload())
        return True
    except Exception:
        return False


def _public_key_from_base64(value: str):
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 32:
            raise ValueError
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        raise DevAnchorError("CLIENT_CONFIGURATION_INVALID") from None


def _database_path_from_environment() -> Path:
    configured = os.environ.get("ERP_MCP_DEV_ANCHOR_DB", "")
    if configured:
        database = Path(configured).expanduser()
    else:
        state_root = (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
                      or str(Path.home() / ".local" / "state"))
        database = Path(state_root) / "ERP_MCP" / "dev-anchor" / "anchor.sqlite3"
    if not database.is_absolute():
        raise DevAnchorError("SERVICE_CONFIGURATION_INVALID")
    resolved = database.resolve()
    try:
        resolved.relative_to(_PROJECT_ROOT.resolve())
    except ValueError:
        return resolved
    raise DevAnchorError("DATABASE_PATH_INSIDE_PROJECT")


class _SQLiteAnchorStore:
    """Development persistence; triggers prevent ordinary updates/deletes, not host rollback."""

    def __init__(self, database: Path):
        if not database.is_absolute():
            raise DevAnchorError("SERVICE_CONFIGURATION_INVALID")
        resolved = database.resolve()
        try:
            resolved.relative_to(_PROJECT_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise DevAnchorError("DATABASE_PATH_INSIDE_PROJECT")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.database = resolved
        with self._connection() as connection:
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            user_tables = connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'",
            ).fetchone()[0]
            if application_id not in {0, _SQLITE_APPLICATION_ID}:
                raise DevAnchorError("DATABASE_FILE_IDENTITY_MISMATCH")
            if application_id == 0 and user_tables:
                raise DevAnchorError("DATABASE_FILE_IDENTITY_MISMATCH")
            if application_id == 0:
                connection.execute(f"PRAGMA application_id={_SQLITE_APPLICATION_ID}")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS anchor_events (
                    tenant_id TEXT NOT NULL,
                    company_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    seq INTEGER NOT NULL CHECK (seq > 0),
                    event_id TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    checkpoint_digest TEXT NOT NULL,
                    previous_digest TEXT,
                    event_digest TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, company_id, revision),
                    UNIQUE (tenant_id, company_id, seq),
                    UNIQUE (event_id)
                );
                CREATE TRIGGER IF NOT EXISTS anchor_events_no_update
                BEFORE UPDATE ON anchor_events BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS anchor_events_no_delete
                BEFORE DELETE ON anchor_events BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5.0, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA trusted_schema=OFF")
            return connection
        except Exception:
            connection.close()
            raise

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validated_history(rows: list[sqlite3.Row], scope: Scope
                           ) -> tuple[CheckpointRecord | None, sqlite3.Row | None]:
        if len(rows) > _MAX_HISTORY_ROWS:
            raise DevAnchorError("HISTORY_LIMIT_EXCEEDED")
        previous_digest = None
        previous_seq = 0
        latest_record = None
        for expected_revision, row in enumerate(rows, start=1):
            record = _parse_record(json.loads(row["checkpoint_json"]))
            try:
                event_id_valid = str(UUID(row["event_id"])) == row["event_id"]
            except (ValueError, TypeError, AttributeError):
                event_id_valid = False
            if (not event_id_valid or row["revision"] != expected_revision
                    or type(row["seq"]) is not int or row["seq"] <= previous_seq
                    or record.tenant_id != scope.tenant_id
                    or record.company_id != scope.company_id or record.seq != row["seq"]
                    or not _verify_server_checkpoint(scope, record)
                    or row["previous_digest"] != previous_digest
                    or checkpoint_identity(record) != row["checkpoint_digest"]):
                raise DevAnchorError("STORE_INTEGRITY_FAILURE")
            expected_digest = _anchor_event_digest(
                scope, row["revision"], row["seq"], row["event_id"],
                row["checkpoint_digest"], row["previous_digest"],
            )
            if row["event_digest"] != expected_digest:
                raise DevAnchorError("STORE_INTEGRITY_FAILURE")
            previous_digest = row["event_digest"]
            previous_seq = row["seq"]
            latest_record = record
        return latest_record, None if not rows else rows[-1]

    def append(self, scope: Scope, record: CheckpointRecord) -> None:
        registered_key = _checkpoint_public_keys(
            os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
        ).get((scope.tenant_id, scope.company_id, record.key_id))
        if (record.tenant_id != scope.tenant_id or record.company_id != scope.company_id
                or record.sink_id != _SERVICE_ID or record.sink_kind != "TEST"
                or registered_key is None
                or registered_key.basis is not CheckpointKeyAuthorizationBasis.ACTIVE
                or not _verify_server_checkpoint(scope, record)):
            raise DevAnchorError("CHECKPOINT_INVALID")
        encoded = _canonical(_record_dict(record)).decode("ascii")
        record_digest = checkpoint_identity(record)
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT revision, seq, event_id, checkpoint_json, checkpoint_digest, "
                    "previous_digest, event_digest FROM anchor_events WHERE tenant_id=? "
                    "AND company_id=? ORDER BY revision ASC LIMIT ?",
                    (scope.tenant_id, scope.company_id, _MAX_HISTORY_ROWS + 1),
                ).fetchall()
                _, latest = self._validated_history(rows, scope)
                existing = next((row for row in rows if row["seq"] == record.seq), None)
                if existing is not None:
                    if encoded == existing["checkpoint_json"]:
                        connection.execute("COMMIT")
                        return
                    raise DevAnchorError("CHECKPOINT_CONFLICT")
                if latest is not None and record.seq == latest["seq"]:
                    raise DevAnchorError("CHECKPOINT_CONFLICT")
                if latest is not None and record.seq <= latest["seq"]:
                    raise DevAnchorError("CHECKPOINT_ROLLBACK")
                if len(rows) >= _MAX_HISTORY_ROWS:
                    raise DevAnchorError("HISTORY_LIMIT_EXCEEDED")
                total_count = connection.execute(
                    "SELECT count(*) FROM anchor_events",
                ).fetchone()[0]
                if total_count >= _MAX_TOTAL_ROWS:
                    raise DevAnchorError("STORE_CAPACITY_REACHED")
                revision = 1 if latest is None else latest["revision"] + 1
                previous_digest = None if latest is None else latest["event_digest"]
                event_id = str(uuid4())
                event_digest = _anchor_event_digest(
                    scope, revision, record.seq, event_id, record_digest, previous_digest,
                )
                connection.execute(
                    "INSERT INTO anchor_events(tenant_id,company_id,revision,seq,event_id,"
                    "checkpoint_json,checkpoint_digest,previous_digest,event_digest) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (scope.tenant_id, scope.company_id, revision, record.seq, event_id, encoded,
                     record_digest, previous_digest, event_digest),
                )
                connection.execute("COMMIT")
        except DevAnchorError:
            raise
        except sqlite3.IntegrityError:
            raise DevAnchorError("CHECKPOINT_CONFLICT") from None
        except sqlite3.Error:
            raise DevAnchorError("STORE_UNAVAILABLE") from None
        except (ValueError, TypeError, UnicodeError):
            raise DevAnchorError("STORE_INTEGRITY_FAILURE") from None

    def get(self, scope: Scope, seq: int) -> CheckpointRecord | None:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT checkpoint_json FROM anchor_events WHERE tenant_id=? "
                    "AND company_id=? AND seq=?", (scope.tenant_id, scope.company_id, seq),
                ).fetchone()
            return None if row is None else _parse_record(json.loads(row["checkpoint_json"]))
        except DevAnchorError:
            raise
        except sqlite3.Error:
            raise DevAnchorError("STORE_UNAVAILABLE") from None
        except (ValueError, TypeError, UnicodeError):
            raise DevAnchorError("STORE_INTEGRITY_FAILURE") from None

    def latest(self, scope: Scope) -> tuple[CheckpointRecord | None, sqlite3.Row | None]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT revision, seq, event_id, checkpoint_json, checkpoint_digest, "
                    "previous_digest, event_digest FROM anchor_events WHERE tenant_id=? "
                    "AND company_id=? ORDER BY revision ASC LIMIT ?",
                    (scope.tenant_id, scope.company_id, _MAX_HISTORY_ROWS + 1),
                ).fetchall()
            return self._validated_history(rows, scope)
        except DevAnchorError:
            raise
        except sqlite3.Error:
            raise DevAnchorError("STORE_UNAVAILABLE") from None
        except (ValueError, TypeError, UnicodeError):
            raise DevAnchorError("STORE_INTEGRITY_FAILURE") from None


def _proof_payload(scope: Scope, nonce: str, revision: int, seq: int,
                   event_id: str | None, event_digest: str | None,
                   checkpoint_digest: str | None,
                   previous_digest: str | None, key_id: str) -> dict[str, Any]:
    return {
        "service_id": _SERVICE_ID,
        "key_id": key_id,
        "authority_id": key_id,
        "tenant_id": scope.tenant_id,
        "company_id": scope.company_id,
        "nonce": nonce,
        "revision": revision,
        "seq": seq,
        "event_id": event_id,
        "event_digest": event_digest,
        "checkpoint_digest": checkpoint_digest,
        "previous_digest": previous_digest,
    }


@lru_cache(maxsize=4)
def _store_for(database: str) -> _SQLiteAnchorStore:
    return _SQLiteAnchorStore(Path(database))


def _server_config() -> tuple[_SQLiteAnchorStore, str, str, str]:
    database = _database_path_from_environment()
    token = os.environ.get("ERP_MCP_DEV_ANCHOR_TOKEN", "")
    latest_key_id = os.environ.get("ERP_MCP_DEV_ANCHOR_LATEST_KEY_ID", "")
    key_auth_id = os.environ.get("ERP_MCP_DEV_ANCHOR_KEY_AUTH_KEY_ID", "")
    if (not database or type(token) is not str or len(token) < 32
            or not _KEY_ID_RE.fullmatch(latest_key_id)
            or not _KEY_ID_RE.fullmatch(key_auth_id)
            or latest_key_id == key_auth_id):
        raise DevAnchorError("SERVICE_CONFIGURATION_INVALID")
    try:
        _checkpoint_public_keys(
            os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
        )
        _validate_authority_keypairs()
        store = _store_for(str(database))
    except DevAnchorError:
        raise
    except (OSError, sqlite3.Error, ValueError):
        raise DevAnchorError("SERVICE_CONFIGURATION_INVALID") from None
    return store, token, latest_key_id, key_auth_id


async def _authorized(request: Request) -> tuple[_SQLiteAnchorStore, str, str, str] | JSONResponse:
    try:
        remote_ip = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return JSONResponse({"error": "LOOPBACK_ONLY"}, status_code=403)
    if not remote_ip.is_loopback:
        return JSONResponse({"error": "LOOPBACK_ONLY"}, status_code=403)
    if os.environ.get("ERP_MCP_DEV_ANCHOR_ENABLED") != "1":
        return JSONResponse({"error": "DEV_ANCHOR_DISABLED"}, status_code=503)
    try:
        database = _database_path_from_environment()
    except DevAnchorError as exc:
        return JSONResponse({"error": exc.code}, status_code=503)
    token = os.environ.get("ERP_MCP_DEV_ANCHOR_TOKEN", "")
    latest_key_id = os.environ.get("ERP_MCP_DEV_ANCHOR_LATEST_KEY_ID", "")
    key_auth_id = os.environ.get("ERP_MCP_DEV_ANCHOR_KEY_AUTH_KEY_ID", "")
    if (not database or type(token) is not str or len(token) < 32
            or not _KEY_ID_RE.fullmatch(latest_key_id)
            or not _KEY_ID_RE.fullmatch(key_auth_id)
            or latest_key_id == key_auth_id):
        return JSONResponse({"error": "SERVICE_CONFIGURATION_INVALID"}, status_code=503)
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode("utf-8"), f"Bearer {token}".encode("utf-8")):
        return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
    try:
        _validate_authority_keypairs()
        _checkpoint_public_keys(
            os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
        )
        # SQLite initialization may create directories, set WAL mode, and execute DDL.
        # Keep that work off the async request loop on the cache's first miss.
        store = await asyncio.to_thread(_store_for, str(database))
    except DevAnchorError as exc:
        return JSONResponse({"error": exc.code}, status_code=503)
    except (OSError, sqlite3.Error, ValueError):
        return JSONResponse({"error": "SERVICE_CONFIGURATION_INVALID"}, status_code=503)
    return store, token, latest_key_id, key_auth_id


async def health(_request: Request) -> Response:
    try:
        remote_ip = ipaddress.ip_address(
            _request.client.host if _request.client else "",
        )
    except ValueError:
        return Response(status_code=403)
    if not remote_ip.is_loopback:
        return Response(status_code=403)
    if os.environ.get("ERP_MCP_DEV_ANCHOR_ENABLED") != "1":
        return Response(status_code=503)
    try:
        # Health is also served on the event loop; its first store lookup can initialize
        # SQLite and must not block unrelated requests while doing so.
        await asyncio.to_thread(_server_config)
    except DevAnchorError:
        return Response(status_code=503)
    return Response(status_code=204)


async def _read_body_limited(request: Request) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_BODY_BYTES:
            raise DevAnchorError("REQUEST_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


async def put_checkpoint(request: Request) -> Response:
    auth = await _authorized(request)
    if isinstance(auth, JSONResponse):
        return auth
    store, _, _, _ = auth
    try:
        raw = await _read_body_limited(request)
        value = json.loads(raw)
        if type(value) is not dict or set(value) != {"record"}:
            raise DevAnchorError("INVALID_REQUEST")
        record = _parse_record(value["record"])
        scope = _scope_value(record.tenant_id, record.company_id)
        if record.sink_id != _SERVICE_ID:
            raise DevAnchorError("SINK_ID_MISMATCH")
        await asyncio.to_thread(store.append, scope, record)
        return JSONResponse({"stored": True})
    except DevAnchorError as exc:
        if exc.code == "REQUEST_TOO_LARGE":
            return JSONResponse({"error": exc.code}, status_code=413)
        status = 409 if exc.code in {"CHECKPOINT_CONFLICT", "CHECKPOINT_ROLLBACK"} else 400
        if exc.code in {"STORE_UNAVAILABLE", "STORE_INTEGRITY_FAILURE", "STORE_CAPACITY_REACHED",
                        "HISTORY_LIMIT_EXCEEDED"}:
            status = 503
        return JSONResponse({"error": exc.code}, status_code=status)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)


async def read_checkpoint(request: Request) -> Response:
    auth = await _authorized(request)
    if isinstance(auth, JSONResponse):
        return auth
    store, _, _, _ = auth
    try:
        raw = await _read_body_limited(request)
        value = json.loads(raw)
        if type(value) is not dict or set(value) != {"tenant_id", "company_id", "seq"}:
            raise DevAnchorError("INVALID_REQUEST")
        scope = _scope_value(value["tenant_id"], value["company_id"])
        if type(value["seq"]) is not int or value["seq"] < 1:
            raise DevAnchorError("INVALID_REQUEST")
        record = await asyncio.to_thread(store.get, scope, value["seq"])
        return JSONResponse({"record": None if record is None else _record_dict(record)})
    except DevAnchorError as exc:
        if exc.code == "REQUEST_TOO_LARGE":
            return JSONResponse({"error": exc.code}, status_code=413)
        return JSONResponse({"error": exc.code}, status_code=503 if exc.code == "STORE_UNAVAILABLE" else 400)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)


async def latest_checkpoint(request: Request) -> Response:
    auth = await _authorized(request)
    if isinstance(auth, JSONResponse):
        return auth
    store, _, latest_key_id, _ = auth
    try:
        raw = await _read_body_limited(request)
        value = json.loads(raw)
        if type(value) is not dict or set(value) != {"tenant_id", "company_id", "nonce"}:
            raise DevAnchorError("INVALID_REQUEST")
        scope = _scope_value(value["tenant_id"], value["company_id"])
        nonce = value["nonce"]
        if type(nonce) is not str or len(nonce) != 64 or not _HASH_RE.fullmatch(nonce):
            raise DevAnchorError("INVALID_REQUEST")
        registered_scopes = _checkpoint_public_keys(
            os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
        )
        if not any(tenant == scope.tenant_id and company == scope.company_id
                   for tenant, company, _ in registered_scopes):
            return JSONResponse({"error": "SCOPE_NOT_REGISTERED"}, status_code=404)
        record, row = await asyncio.to_thread(store.latest, scope)
        revision = 0 if row is None else row["revision"]
        seq = 0 if row is None else row["seq"]
        event_id = None if row is None else row["event_id"]
        event_digest = None if row is None else row["event_digest"]
        checkpoint_digest = None if row is None else row["checkpoint_digest"]
        previous_digest = None if row is None else row["previous_digest"]
        proof = _proof_payload(
            scope, nonce, revision, seq, event_id, event_digest, checkpoint_digest,
            previous_digest, latest_key_id,
        )
        signature = _authority_private_key_from_environment(
            "ERP_MCP_DEV_ANCHOR_LATEST_PRIVATE_KEY_B64"
        ).sign(
            _PROOF_DOMAIN + _canonical(proof)
        ).hex()
        return JSONResponse({"record": None if record is None else _record_dict(record),
                             "proof": {**proof, "signature": signature}})
    except DevAnchorError as exc:
        if exc.code == "REQUEST_TOO_LARGE":
            return JSONResponse({"error": exc.code}, status_code=413)
        return JSONResponse({"error": exc.code}, status_code=503 if "STORE" in exc.code or "CONFIG" in exc.code else 400)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)


async def authorize_checkpoint(request: Request) -> Response:
    auth = await _authorized(request)
    if isinstance(auth, JSONResponse):
        return auth
    store, _, _, key_auth_id = auth
    try:
        raw = await _read_body_limited(request)
        value = json.loads(raw)
        if type(value) is not dict or set(value) != {"record", "nonce"}:
            raise DevAnchorError("INVALID_REQUEST")
        record = _parse_record(value["record"])
        scope = _scope_value(record.tenant_id, record.company_id)
        nonce = value["nonce"]
        if type(nonce) is not str or len(nonce) != 64 or not _HASH_RE.fullmatch(nonce):
            raise DevAnchorError("INVALID_REQUEST")
        if record.sink_id != _SERVICE_ID or record.sink_kind != "TEST":
            raise DevAnchorError("CHECKPOINT_INVALID")
        if not _verify_server_checkpoint(scope, record):
            return JSONResponse({"error": "AUTHORIZATION_DENIED"}, status_code=403)
        # Authorization is only for a checkpoint this append-only service actually retained.
        # Validate the bounded event chain before trusting the exact stored record.
        await asyncio.to_thread(store.latest, scope)
        stored_record = await asyncio.to_thread(store.get, scope, record.seq)
        if stored_record != record:
            return JSONResponse({"error": "AUTHORIZATION_DENIED"}, status_code=403)
        registered_key = _checkpoint_public_keys(
            os.environ.get("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON", "")
        ).get((scope.tenant_id, scope.company_id, record.key_id))
        if registered_key is None:
            return JSONResponse({"error": "AUTHORIZATION_DENIED"}, status_code=403)
        if (registered_key.basis is CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT
                and (registered_key.accepted_through_seq is None
                     or record.seq > registered_key.accepted_through_seq)):
            return JSONResponse({"error": "AUTHORIZATION_DENIED"}, status_code=403)
        from cryptography.hazmat.primitives import serialization

        public_key_digest = hashlib.sha256(registered_key.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )).hexdigest()
        authority_event_id = hashlib.sha256(
            b"erp-mcp-dev-anchor-static-key|v1\0"
            + _canonical([
                scope.tenant_id, scope.company_id, record.key_id, public_key_digest,
                registered_key.basis.value, registered_key.receipt_id,
                None if registered_key.accepted_at is None else registered_key.accepted_at.isoformat(),
                registered_key.accepted_through_seq,
            ])
        ).hexdigest()
        proof = {
            "service_id": _SERVICE_ID,
            "authority_key_id": key_auth_id,
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "checkpoint_key_id": record.key_id,
            "public_key_digest": public_key_digest,
            "checkpoint_digest": checkpoint_identity(record),
            "authority_id": key_auth_id,
            "authority_revision": 1,
            "authority_event_id": authority_event_id,
            "policy_version": "dev-static-key-registry-v1",
            "basis": registered_key.basis.value,
            "receipt_id": registered_key.receipt_id,
            "accepted_at": (None if registered_key.accepted_at is None
                            else registered_key.accepted_at.isoformat()),
            "nonce": nonce,
        }
        signature = _authority_private_key_from_environment(
            "ERP_MCP_DEV_ANCHOR_KEY_AUTH_PRIVATE_KEY_B64"
        ).sign(
            _KEY_AUTH_PROOF_DOMAIN + _canonical(proof)
        ).hex()
        return JSONResponse({"authorization": {**proof, "signature": signature}})
    except DevAnchorError as exc:
        if exc.code == "REQUEST_TOO_LARGE":
            return JSONResponse({"error": exc.code}, status_code=413)
        status = 503 if "STORE" in exc.code or "CONFIG" in exc.code else 400
        return JSONResponse({"error": exc.code}, status_code=status)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)


app = Starlette(routes=[
    Route("/health", health, methods=["GET"]),
    Route("/v1/checkpoints", put_checkpoint, methods=["PUT"]),
    Route("/v1/checkpoints/read-back", read_checkpoint, methods=["POST"]),
    Route("/v1/checkpoints/latest", latest_checkpoint, methods=["POST"]),
    Route("/v1/checkpoints/authorize", authorize_checkpoint, methods=["POST"]),
])


@dataclass(frozen=True)
class LegacyLatestnessReceipt:
    """Verified v1 transport receipt, including the empty-store response.

    This preserves the legacy API shape. It is not the current lifecycle authority
    envelope; attest_latest constructs that only for an exact retained checkpoint.
    """

    tenant_id: str
    company_id: str
    checkpoint_digest: str | None
    authority_id: str
    authority_revision: int
    authority_event_id: str | None
    authority_event_digest: str | None
    challenge_nonce: str
    proof_digest: str


class DevHttpCheckpointSink(
        CheckpointSink, CheckpointKeyAuthorizationAuthority, CheckpointLatestnessAuthority):
    """TEST-only sink/key-authority client for the separate dev process; never use in production."""

    kind = "TEST"
    is_test_double = True

    def __init__(self, base_url: str, *, bearer_token: str, expected_key_id: str,
                 authority_public_key_b64: str, expected_key_authorization_id: str,
                 key_authorization_public_key_b64: str,
                 checkpoint_verifier: SignatureVerifier,
                 timeout_seconds: float = 3.0):
        if type(base_url) is not str:
            raise DevAnchorError("CLIENT_CONFIGURATION_INVALID")
        try:
            parsed = urlsplit(base_url)
            host_ip = ipaddress.ip_address(parsed.hostname or "")
            port = parsed.port
        except ValueError:
            raise DevAnchorError("CLIENT_CONFIGURATION_INVALID") from None
        if (parsed.scheme != "http" or not host_ip.is_loopback
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or (port is not None and not 1 <= port <= 65535)
                or type(bearer_token) is not str or len(bearer_token) < 32
                or type(expected_key_id) is not str or not _KEY_ID_RE.fullmatch(expected_key_id)
                or type(expected_key_authorization_id) is not str
                or not _KEY_ID_RE.fullmatch(expected_key_authorization_id)
                or expected_key_id == expected_key_authorization_id
                or not callable(getattr(checkpoint_verifier, "verify", None))
                or isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 10):
            raise DevAnchorError("CLIENT_CONFIGURATION_INVALID")
        self.sink_id = _SERVICE_ID
        self._base_url = base_url.rstrip("/")
        self._token = bearer_token
        self._key_id = expected_key_id
        self._public_key = _public_key_from_base64(authority_public_key_b64)
        self._key_authorization_id = expected_key_authorization_id
        self._key_authorization_public_key = _public_key_from_base64(
            key_authorization_public_key_b64
        )
        from cryptography.hazmat.primitives import serialization

        latest_public_bytes = self._public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        key_auth_public_bytes = self._key_authorization_public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        if hmac.compare_digest(latest_public_bytes, key_auth_public_bytes):
            raise DevAnchorError("AUTHORITY_KEY_ROLE_COLLISION")
        self._checkpoint_verifier = checkpoint_verifier
        self._timeout = timeout_seconds
        self._latest_seen: dict[tuple[str, str], tuple[int, int, str | None]] = {}

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.request(
                method, self._base_url + path, json=payload,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(self._timeout), trust_env=False, follow_redirects=False,
            )
            if response.is_error:
                code = "SERVICE_UNAVAILABLE"
                try:
                    body = response.json()
                    if (type(body) is dict and type(body.get("error")) is str
                            and re.fullmatch(r"[A-Z_]{1,64}", body["error"])):
                        code = body["error"]
                except ValueError:
                    pass
                raise DevAnchorError(code)
            value = response.json()
            if type(value) is not dict:
                raise DevAnchorError("SERVICE_RESPONSE_INVALID")
            return value
        except DevAnchorError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise DevAnchorError("SERVICE_UNAVAILABLE") from None

    async def write(self, record: CheckpointRecord) -> None:
        if (type(record) is not CheckpointRecord or record.sink_id != self.sink_id
                or record.sink_kind != self.kind
                or not _verify_checkpoint(self._checkpoint_verifier, record)):
            raise DevAnchorError("CHECKPOINT_INVALID")
        value = await asyncio.to_thread(
            self._request, "PUT", "/v1/checkpoints", {"record": _record_dict(record)},
        )
        if value != {"stored": True}:
            raise DevAnchorError("SERVICE_RESPONSE_INVALID")

    async def read_back(self, scope: Scope, seq: int) -> CheckpointRecord | None:
        if type(seq) is not int or seq < 1:
            raise DevAnchorError("INVALID_REQUEST")
        value = await asyncio.to_thread(
            self._request, "POST", "/v1/checkpoints/read-back",
            {"tenant_id": scope.tenant_id, "company_id": scope.company_id, "seq": seq},
        )
        if set(value) != {"record"}:
            raise DevAnchorError("SERVICE_RESPONSE_INVALID")
        record = None if value["record"] is None else _parse_record(value["record"])
        if record is not None and (record.tenant_id != scope.tenant_id
                                   or record.company_id != scope.company_id
                                   or record.seq != seq
                                   or record.sink_id != self.sink_id or record.sink_kind != self.kind
                                   or not _verify_checkpoint(self._checkpoint_verifier, record)):
            raise DevAnchorError("SERVICE_RESPONSE_INVALID")
        return record

    async def latest_checkpoint(
            self, scope: Scope, challenge_nonce: str | None = None
    ) -> tuple[CheckpointRecord | None, LegacyLatestnessReceipt]:
        nonce = os.urandom(32).hex() if challenge_nonce is None else challenge_nonce
        if type(nonce) is not str or not _HASH_RE.fullmatch(nonce):
            raise DevAnchorError("LATEST_PROOF_INVALID")
        value = await asyncio.to_thread(
            self._request, "POST", "/v1/checkpoints/latest",
            {"tenant_id": scope.tenant_id, "company_id": scope.company_id, "nonce": nonce},
        )
        if set(value) != {"record", "proof"} or type(value["proof"]) is not dict:
            raise DevAnchorError("SERVICE_RESPONSE_INVALID")
        proof = value["proof"]
        proof_fields = {"service_id", "key_id", "authority_id", "tenant_id", "company_id", "nonce", "revision",
                        "seq", "event_id", "event_digest", "checkpoint_digest",
                        "previous_digest", "signature"}
        if set(proof) != proof_fields:
            raise DevAnchorError("SERVICE_RESPONSE_INVALID")
        signature = proof["signature"]
        if (type(signature) is not str
                or not _AUTHORITY_SIGNATURE_RE.fullmatch(signature)):
            raise DevAnchorError("LATEST_PROOF_INVALID")
        signed_fields = {key: proof[key] for key in proof_fields if key != "signature"}
        try:
            self._public_key.verify(bytes.fromhex(signature), _PROOF_DOMAIN + _canonical(signed_fields))
        except Exception:
            raise DevAnchorError("LATEST_PROOF_INVALID") from None
        if (proof["service_id"] != _SERVICE_ID
                or proof["key_id"] != self._key_id
                or proof["authority_id"] != self._key_id
                or proof["tenant_id"] != scope.tenant_id or proof["company_id"] != scope.company_id
                or proof["nonce"] != nonce or type(proof["revision"]) is not int
                or proof["revision"] < 0 or type(proof["seq"]) is not int
                or proof["seq"] < 0):
            raise DevAnchorError("LATEST_PROOF_INVALID")
        record = None if value["record"] is None else _parse_record(value["record"])
        if record is None:
            if (proof["revision"] != 0 or proof["seq"] != 0
                    or proof["event_id"] is not None
                    or proof["event_digest"] is not None or proof["checkpoint_digest"] is not None):
                raise DevAnchorError("LATEST_PROOF_INVALID")
            if proof["previous_digest"] is not None:
                raise DevAnchorError("LATEST_PROOF_INVALID")
            seq = 0
        else:
            try:
                event_id_valid = (type(proof["event_id"]) is str
                                  and str(UUID(proof["event_id"])) == proof["event_id"])
            except (ValueError, TypeError, AttributeError):
                event_id_valid = False
            previous_digest = proof["previous_digest"]
            if (record.tenant_id != scope.tenant_id or record.company_id != scope.company_id
                    or record.sink_id != self.sink_id or record.sink_kind != self.kind
                    or not _verify_checkpoint(self._checkpoint_verifier, record)
                    or proof["revision"] < 1 or not event_id_valid
                    or proof["seq"] != record.seq
                    or type(proof["event_digest"]) is not str
                    or not _HASH_RE.fullmatch(proof["event_digest"])
                    or (proof["revision"] == 1 and previous_digest is not None)
                    or (proof["revision"] > 1
                        and (type(previous_digest) is not str
                             or not _HASH_RE.fullmatch(previous_digest)))
                    or proof["checkpoint_digest"] != checkpoint_identity(record)):
                raise DevAnchorError("LATEST_PROOF_INVALID")
            if proof["event_digest"] != _anchor_event_digest(
                    scope, proof["revision"], proof["seq"], proof["event_id"],
                    proof["checkpoint_digest"], previous_digest):
                raise DevAnchorError("LATEST_PROOF_INVALID")
            seq = record.seq
        previous = self._latest_seen.get((scope.tenant_id, scope.company_id))
        if previous is not None:
            prev_revision, prev_seq, prev_event_digest = previous
            if (proof["revision"] < prev_revision or seq < prev_seq
                    or (proof["revision"] == prev_revision
                        and (seq != prev_seq or proof["event_digest"] != prev_event_digest))
                    or (proof["revision"] > prev_revision and seq <= prev_seq)):
                raise DevAnchorError("LATEST_ROLLBACK")
        if (previous is None and len(self._latest_seen) >= _MAX_REGISTERED_KEYS
                and (scope.tenant_id, scope.company_id) not in self._latest_seen):
            raise DevAnchorError("SCOPE_LIMIT_REACHED")
        self._latest_seen[(scope.tenant_id, scope.company_id)] = (
            proof["revision"], seq, proof["event_digest"],
        )
        return record, LegacyLatestnessReceipt(
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            checkpoint_digest=None if record is None else checkpoint_identity(record),
            authority_id=proof["authority_id"],
            authority_revision=proof["revision"],
            authority_event_id=proof["event_id"],
            authority_event_digest=proof["event_digest"],
            challenge_nonce=nonce,
            proof_digest=hashlib.sha256(_PROOF_DOMAIN + _canonical(signed_fields)).hexdigest(),
        )

    async def latest(self, scope: Scope) -> CheckpointRecord | None:
        record, _ = await self.latest_checkpoint(scope)
        return record

    async def attest_latest(
            self, scope: Scope, record: CheckpointRecord, challenge_nonce: str
    ) -> CheckpointLatestnessEvidence | None:
        observed, receipt = await self.latest_checkpoint(scope, challenge_nonce)
        if observed is None or receipt.checkpoint_digest != checkpoint_identity(record):
            return None
        if observed != record:
            return None
        return CheckpointLatestnessEvidence(
            tenant_id=scope.tenant_id, company_id=scope.company_id,
            checkpoint_digest=receipt.checkpoint_digest,
            challenge_nonce=receipt.challenge_nonce, provider_id=self.sink_id,
            provider_revision=receipt.authority_revision,
            authority_id=receipt.authority_id, authority_revision=receipt.authority_revision,
            authority_event_id=receipt.authority_event_id,
            policy_version="dev-anchor-latest-v1", proof_digest=receipt.proof_digest,
        )

    async def authorize_checkpoint(
            self, scope: Scope, record: CheckpointRecord, challenge_nonce: str | None = None
    ) -> CheckpointKeyAuthorization | None:
        if (type(record) is not CheckpointRecord
                or record.tenant_id != scope.tenant_id
                or record.company_id != scope.company_id
                or record.sink_id != self.sink_id or record.sink_kind != self.kind
                or not _verify_checkpoint(self._checkpoint_verifier, record)):
            raise DevAnchorError("CHECKPOINT_INVALID")
        nonce = os.urandom(32).hex() if challenge_nonce is None else challenge_nonce
        if type(nonce) is not str or not _HASH_RE.fullmatch(nonce):
            raise DevAnchorError("KEY_AUTHORIZATION_PROOF_INVALID")
        try:
            value = await asyncio.to_thread(
                self._request, "POST", "/v1/checkpoints/authorize",
                {"record": _record_dict(record), "nonce": nonce},
            )
        except DevAnchorError as exc:
            if exc.code == "AUTHORIZATION_DENIED":
                return None
            raise
        if set(value) != {"authorization"} or type(value["authorization"]) is not dict:
            raise DevAnchorError("SERVICE_RESPONSE_INVALID")
        proof = value["authorization"]
        proof_fields = {
            "service_id", "authority_key_id", "tenant_id", "company_id",
            "checkpoint_key_id", "public_key_digest", "checkpoint_digest", "authority_id",
            "authority_revision", "authority_event_id", "policy_version", "basis",
            "receipt_id", "accepted_at", "nonce", "signature",
        }
        if set(proof) != proof_fields:
            raise DevAnchorError("SERVICE_RESPONSE_INVALID")
        signature = proof["signature"]
        if (type(signature) is not str
                or not _AUTHORITY_SIGNATURE_RE.fullmatch(signature)):
            raise DevAnchorError("KEY_AUTHORIZATION_PROOF_INVALID")
        signed_fields = {key: proof[key] for key in proof_fields if key != "signature"}
        try:
            self._key_authorization_public_key.verify(
                bytes.fromhex(signature), _KEY_AUTH_PROOF_DOMAIN + _canonical(signed_fields),
            )
            basis = CheckpointKeyAuthorizationBasis(proof["basis"])
            accepted_at = (None if proof["accepted_at"] is None else
                           datetime.fromisoformat(proof["accepted_at"].replace("Z", "+00:00")))
        except Exception:
            raise DevAnchorError("KEY_AUTHORIZATION_PROOF_INVALID") from None
        basis_details_valid = (
            basis is CheckpointKeyAuthorizationBasis.ACTIVE
            and proof["receipt_id"] is None and accepted_at is None
        ) or (
            basis is CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT
            and type(proof["receipt_id"]) is str and bool(proof["receipt_id"])
            and len(proof["receipt_id"]) <= 256
            and type(accepted_at) is datetime and accepted_at.tzinfo is not None
            and accepted_at.utcoffset() is not None
        )
        if (proof["service_id"] != _SERVICE_ID
                or proof["authority_key_id"] != self._key_authorization_id
                or proof["tenant_id"] != scope.tenant_id
                or proof["company_id"] != scope.company_id
                or proof["checkpoint_key_id"] != record.key_id
                or proof["checkpoint_digest"] != checkpoint_identity(record)
                or type(proof["public_key_digest"]) is not str
                or not _HASH_RE.fullmatch(proof["public_key_digest"])
                or proof["authority_id"] != self._key_authorization_id
                or type(proof["authority_revision"]) is not int
                or proof["authority_revision"] != 1
                or type(proof["authority_event_id"]) is not str
                or not _HASH_RE.fullmatch(proof["authority_event_id"])
                or proof["policy_version"] != "dev-static-key-registry-v1"
                or not basis_details_valid
                or proof["nonce"] != nonce):
            raise DevAnchorError("KEY_AUTHORIZATION_PROOF_INVALID")
        return CheckpointKeyAuthorization(
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            key_id=record.key_id,
            public_key_digest=proof["public_key_digest"],
            checkpoint_digest=proof["checkpoint_digest"],
            challenge_nonce=nonce,
            authority_id=proof["authority_id"],
            authority_revision=proof["authority_revision"],
            authority_event_id=proof["authority_event_id"],
            policy_version=proof["policy_version"],
            basis=basis,
            receipt_id=proof["receipt_id"],
            accepted_at=accepted_at,
        )


def main() -> None:
    """Run only on loopback. Production runtime must not import or compose this module."""
    host = os.environ.get("ERP_MCP_DEV_ANCHOR_HOST", "127.0.0.1")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise SystemExit("ERP_MCP_DEV_ANCHOR_HOST must be a loopback IP") from None
    if not ip.is_loopback:
        raise SystemExit("DEV_ANCHOR_LOOPBACK_ONLY")
    if os.environ.get("ERP_MCP_DEV_ANCHOR_ENABLED") != "1":
        raise SystemExit("DEV_ANCHOR_EXPLICIT_ENABLE_REQUIRED")
    try:
        port = int(os.environ.get("ERP_MCP_DEV_ANCHOR_PORT", "21831"))
    except ValueError:
        raise SystemExit("ERP_MCP_DEV_ANCHOR_PORT_INVALID") from None
    if not 1 <= port <= 65535:
        raise SystemExit("ERP_MCP_DEV_ANCHOR_PORT_INVALID")
    try:
        _server_config()
        _validate_authority_keypairs()
    except DevAnchorError:
        raise SystemExit("DEV_ANCHOR_CONFIGURATION_INVALID") from None
    import uvicorn

    uvicorn.run("business_ai_gateway.phase2.change_ledger.dev_anchor_service:app",
                host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
