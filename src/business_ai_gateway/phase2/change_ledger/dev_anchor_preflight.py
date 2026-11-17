"""One-shot, development-only read-only lifecycle diagnostic.

This command cannot authorize startup or recovery. Its only successful outcome is the
coordinator's existing ``NOT_READY`` diagnostic, and it never writes to the ledger.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

import asyncpg

from ._common import Scope
from .anchor_client import DevAnchorClient, _is_loopback_url
from .checkpoint import Ed25519SignatureVerifier
from .lifecycle import LifecycleCoordinator
from .sql_ledger import SqlChangeLedger

_PREFIX = "ERP_MCP_DEV_ANCHOR_"
_TIMEOUT_SECONDS = 5.0
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX_32_BYTES = re.compile(r"^[0-9a-f]{64}$")


class _ConfigurationError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _Config:
    database_dsn: str
    base_url: str
    service_id: str
    bearer_token: str
    latest_authority_id: str
    latest_public_key: bytes
    key_authority_id: str
    key_authority_public_key: bytes
    checkpoint_public_keys: dict[str, bytes]
    tenant_id: str
    company_id: str


def _required(name: str, *, maximum: int) -> str:
    value = os.environ.get(_PREFIX + name)
    if type(value) is not str or not value or len(value) > maximum or "\x00" in value:
        raise _ConfigurationError("PREFLIGHT_CONFIGURATION_INVALID")
    return value


def _is_loopback_database_dsn(value: str) -> bool:
    """Only allow an explicit loopback PostgreSQL URI for this dev-only command."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname
                or parsed.query or parsed.fragment or not parsed.path or parsed.path == "/"
                or parsed.username is None or parsed.password is None):
            return False
        # Do not trust local resolver configuration: accept only literal loopback IPs.
        if not ip_address(parsed.hostname).is_loopback:
            return False
        # Accessing .port validates malformed and out-of-range explicit ports.
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        return True
    except (ValueError, TypeError):
        return False


def _public_key(name: str) -> bytes:
    value = _required(name, maximum=64)
    if _HEX_32_BYTES.fullmatch(value) is None:
        raise _ConfigurationError("PREFLIGHT_CONFIGURATION_INVALID")
    return bytes.fromhex(value)


def _checkpoint_keys() -> dict[str, bytes]:
    raw = _required("CHECKPOINT_PUBLIC_KEYS_JSON", maximum=65536)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise _ConfigurationError("PREFLIGHT_CONFIGURATION_INVALID") from None
    if type(value) is not dict or not value or len(value) > 256:
        raise _ConfigurationError("PREFLIGHT_CONFIGURATION_INVALID")
    result: dict[str, bytes] = {}
    for key_id, encoded in value.items():
        if (type(key_id) is not str or _KEY_ID.fullmatch(key_id) is None
                or type(encoded) is not str or _HEX_32_BYTES.fullmatch(encoded) is None):
            raise _ConfigurationError("PREFLIGHT_CONFIGURATION_INVALID")
        result[key_id] = bytes.fromhex(encoded)
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _load_config() -> _Config:
    if os.environ.get(_PREFIX + "MODE") != "dev":
        raise _ConfigurationError("DEV_ONLY_REQUIRED")

    base_url = _required("BASE_URL", maximum=2048)
    if not _is_loopback_url(base_url):
        raise _ConfigurationError("ANCHOR_URL_INVALID")

    database_dsn = _required("DATABASE_DSN", maximum=4096)
    if not _is_loopback_database_dsn(database_dsn):
        raise _ConfigurationError("DATABASE_URL_INVALID")
    service_id = _required("SERVICE_ID", maximum=128)
    bearer_token = _required("BEARER_TOKEN", maximum=512)
    latest_authority_id = _required("LATEST_AUTHORITY_ID", maximum=128)
    latest_public_key = _public_key("LATEST_PUBLIC_KEY_HEX")
    key_authority_id = _required("KEY_AUTHORITY_ID", maximum=128)
    key_authority_public_key = _public_key("KEY_AUTHORITY_PUBLIC_KEY_HEX")
    checkpoint_public_keys = _checkpoint_keys()
    tenant_id = _required("TENANT_ID", maximum=128)
    company_id = _required("COMPANY_ID", maximum=128)

    if (not service_id.strip() or not latest_authority_id.strip()
            or not key_authority_id.strip() or not tenant_id.strip() or not company_id.strip()
            or latest_authority_id == key_authority_id
            or latest_public_key == key_authority_public_key):
        raise _ConfigurationError("PREFLIGHT_CONFIGURATION_INVALID")

    return _Config(
        database_dsn=database_dsn,
        base_url=base_url,
        service_id=service_id,
        bearer_token=bearer_token,
        latest_authority_id=latest_authority_id,
        latest_public_key=latest_public_key,
        key_authority_id=key_authority_id,
        key_authority_public_key=key_authority_public_key,
        checkpoint_public_keys=checkpoint_public_keys,
        tenant_id=tenant_id,
        company_id=company_id,
    )


async def _run(config: _Config) -> tuple[dict[str, str], int]:
    client: DevAnchorClient | None = None
    connection: asyncpg.Connection | None = None
    try:
        # Construct before connecting so the anchor client repeats its own loopback/config checks.
        try:
            client = DevAnchorClient(
                base_url=config.base_url,
                service_id=config.service_id,
                service_token=config.bearer_token,
                latestness_authority_id=config.latest_authority_id,
                latestness_public_key=config.latest_public_key,
                key_authority_id=config.key_authority_id,
                key_authority_public_key=config.key_authority_public_key,
            )
            verifier = Ed25519SignatureVerifier(config.checkpoint_public_keys)
        except Exception:
            return {"status": "NOT_READY", "reason": "PREFLIGHT_CONFIGURATION_INVALID"}, 2
        connection = await asyncio.wait_for(
            asyncpg.connect(config.database_dsn, timeout=_TIMEOUT_SECONDS),
            timeout=_TIMEOUT_SECONDS,
        )
        ledger = SqlChangeLedger(
            connection,
            actors={"worker": "clt_wrk", "auditor": "clt_aud"},
            private_writer_schema_enabled=True,
        )
        coordinator = LifecycleCoordinator(
            ledger,
            client,
            verifier,
            key_authority=client,
            latestness_authority=client,
            dependency_timeout_seconds=_TIMEOUT_SECONDS,
        )
        result = await asyncio.wait_for(
            coordinator.preflight(Scope(config.tenant_id, config.company_id)),
            timeout=_TIMEOUT_SECONDS * 4,
        )
        return {"status": result.status.value, "reason": result.reason.value}, 0
    except Exception:
        # Do not surface exception text: drivers and transports may include credentials or hosts.
        return {"status": "NOT_READY", "reason": "PREFLIGHT_UNAVAILABLE"}, 0
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        if connection is not None:
            try:
                await asyncio.wait_for(connection.close(), timeout=_TIMEOUT_SECONDS)
            except Exception:
                pass


def main() -> int:
    try:
        config = _load_config()
    except _ConfigurationError as exc:
        payload = {"status": "NOT_READY", "reason": exc.reason}
        exit_code = 2
    except Exception:
        payload = {"status": "NOT_READY", "reason": "PREFLIGHT_CONFIGURATION_INVALID"}
        exit_code = 2
    else:
        try:
            payload, exit_code = asyncio.run(_run(config))
        except Exception:
            payload, exit_code = {"status": "NOT_READY", "reason": "PREFLIGHT_UNAVAILABLE"}, 0
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

