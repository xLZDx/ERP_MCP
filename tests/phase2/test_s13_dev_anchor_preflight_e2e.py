"""CLI configuration-boundary E2E cases; no DB or COM is contacted."""
from __future__ import annotations

import json
import os
import asyncio
import hashlib
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _pg_harness import disposable_cluster, throwaway_db
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.anchor_client import DevAnchorClient
from business_ai_gateway.phase2.change_ledger.checkpoint import CheckpointRecord
from business_ai_gateway.phase2.change_ledger.dev_anchor_service_s13.service import (
    DevAnchorConfig,
    create_app,
)
from test_change_ledger_sql import C, L, T, _setup


ROOT = Path(__file__).resolve().parents[2]
CLI_MODULE = "business_ai_gateway.phase2.change_ledger.dev_anchor_preflight"
PREFIX = "ERP_MCP_DEV_ANCHOR_"
SCOPE = Scope(T, C)
SERVICE_ID = "synthetic-s13-preflight-service"
LATESTNESS_ID = "synthetic-s13-preflight-latestness"
KEY_AUTH_ID = "synthetic-s13-preflight-key-auth"
CHECKPOINT_KEY_ID = "synthetic-s13-preflight-checkpoint"
POST_BASE_MIGRATIONS = (
    "019_ed25519_action_only.sql", "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql", "022_lifecycle_epoch_fence.sql",
    "023_lifecycle_activation_cap.sql", "024_restore_caller_lock_timeout.sql",
    "025_lifecycle_checkpoint_suffix.sql", "026_lifecycle_checkpoint_payload_minimization.sql",
    "027_private_writer_admission_schema.sql",
)


class _Signer:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key

    @property
    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _database_dsn(cluster_dsn: str, database_name: str) -> str:
    parts = urlsplit(cluster_dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/" + quote(database_name, safe=""),
                       parts.query, parts.fragment))


def _start_http_server(app, port: int, token: str):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="critical", access_log=False,
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise AssertionError("synthetic dev anchor server exited before health check")
        try:
            response = httpx.get(
                base_url + "/v1/health",
                headers={"Authorization": "Bearer " + token},
                timeout=0.25,
                trust_env=False,
            )
            if response.status_code == 200:
                return server, thread, base_url
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    server.should_exit = True
    thread.join(timeout=3)
    raise AssertionError("synthetic dev anchor server did not become healthy")


def _environment(**overrides: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "src"), environment.get("PYTHONPATH", "")) if part
    )
    environment.update({
        PREFIX + "MODE": "dev",
        PREFIX + "DATABASE_DSN": "postgresql://synthetic:synthetic@127.0.0.1:1/unavailable",
        PREFIX + "BASE_URL": "http://127.0.0.1:9",
        PREFIX + "SERVICE_ID": "synthetic-service",
        PREFIX + "BEARER_TOKEN": "synthetic-service-token-redact-me",
        PREFIX + "LATEST_AUTHORITY_ID": "synthetic-latestness",
        PREFIX + "LATEST_PUBLIC_KEY_HEX": "00",
        PREFIX + "KEY_AUTHORITY_ID": "synthetic-key-auth",
        PREFIX + "KEY_AUTHORITY_PUBLIC_KEY_HEX": "00",
        PREFIX + "CHECKPOINT_PUBLIC_KEYS_JSON": "{}",
        PREFIX + "TENANT_ID": "synthetic-tenant",
        PREFIX + "COMPANY_ID": "synthetic-company",
    })
    environment.update(overrides)
    return environment


def _invoke(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", CLI_MODULE], cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=15, check=False,
    )


def _payload(result, *secrets_to_redact):
    output = result.stdout + result.stderr
    for secret in secrets_to_redact:
        assert secret not in output
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_cli_rejects_non_dev_mode_without_network_and_redacts_credentials():
    dsn_user = "dsn-user-must-not-appear"
    token = "service-token-must-not-appear"
    result = _invoke(_environment(**{
        PREFIX + "MODE": "production",
        PREFIX + "DATABASE_DSN": f"postgresql://{dsn_user}:pw@127.0.0.1:1/missing",
        PREFIX + "BEARER_TOKEN": token,
    }))
    assert result.returncode == 2
    assert _payload(result, dsn_user, token) == {
        "status": "NOT_READY", "reason": "DEV_ONLY_REQUIRED",
    }


def test_cli_rejects_remote_anchor_before_database_connect_and_redacts_token():
    token = "service-token-must-not-appear"
    result = _invoke(_environment(**{
        PREFIX + "BASE_URL": "https://anchor.example.invalid",
        PREFIX + "BEARER_TOKEN": token,
    }))
    assert result.returncode == 2
    assert _payload(result, token) == {
        "status": "NOT_READY", "reason": "ANCHOR_URL_INVALID",
    }


def test_cli_rejects_non_loopback_database_before_network_and_redacts_credentials():
    username, password, token = (
        "db-user-must-not-appear", "db-password-must-not-appear",
        "service-token-must-not-appear",
    )
    result = _invoke(_environment(**{
        PREFIX + "DATABASE_DSN": f"postgresql://{username}:{password}@db.example.invalid:5432/testdb",
        PREFIX + "BEARER_TOKEN": token,
    }))
    assert result.returncode == 2
    assert _payload(result, username, password, token) == {
        "status": "NOT_READY", "reason": "DATABASE_URL_INVALID",
    }


@pytest.mark.parametrize("keys", [
    '{"duplicate":"00","duplicate":"11"}',
    '{"checkpoint-key":"not-hex"}',
])
def test_cli_rejects_malformed_checkpoint_registry_before_database_connect(keys):
    result = _invoke(_environment(**{PREFIX + "CHECKPOINT_PUBLIC_KEYS_JSON": keys}))
    assert result.returncode == 2
    assert _payload(result) == {
        "status": "NOT_READY", "reason": "PREFLIGHT_CONFIGURATION_INVALID",
    }


@pytest.mark.parametrize("authority_role", ["latestness", "key_authority"])
def test_cli_rejects_authority_key_in_checkpoint_registry_before_io(authority_role):
    latest_public = _raw_public(Ed25519PrivateKey.generate())
    key_authority_public = _raw_public(Ed25519PrivateKey.generate())
    checkpoint_public = latest_public if authority_role == "latestness" else key_authority_public
    result = _invoke(_environment(**{
        PREFIX + "LATEST_PUBLIC_KEY_HEX": latest_public.hex(),
        PREFIX + "KEY_AUTHORITY_PUBLIC_KEY_HEX": key_authority_public.hex(),
        PREFIX + "CHECKPOINT_PUBLIC_KEYS_JSON": json.dumps({
            "synthetic-checkpoint-key": checkpoint_public.hex(),
        }),
    }))
    assert result.returncode == 2
    assert _payload(result) == {
        "status": "NOT_READY", "reason": "PREFLIGHT_CONFIGURATION_INVALID",
    }


@pytest.mark.e2e
def test_cli_signed_checkpoint_preflight_is_read_only_and_never_ready(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", "1")
    latest_private = Ed25519PrivateKey.generate()
    key_auth_private = Ed25519PrivateKey.generate()
    checkpoint_private = Ed25519PrivateKey.generate()
    service_token = secrets.token_urlsafe(48)
    admin_token = secrets.token_urlsafe(48)
    latest_signer = _Signer(latest_private)
    key_auth_signer = _Signer(key_auth_private)
    assert latest_signer.public_key_bytes != key_auth_signer.public_key_bytes
    port = _free_port()
    app = create_app(DevAnchorConfig(
        service_id=SERVICE_ID,
        database_path=(tmp_path / "synthetic-preflight-anchor.sqlite3").resolve(),
        project_root=ROOT.resolve(),
        mode="dev",
        bind_host="127.0.0.1",
        bearer_token=service_token,
        admin_token=admin_token,
        latestness_authority_id=LATESTNESS_ID,
        latestness_signer=latest_signer,
        key_authority_id=KEY_AUTH_ID,
        key_authority_signer=key_auth_signer,
    ))
    server, thread, base_url = _start_http_server(app, port, service_token)

    async def exercise() -> None:
        async with disposable_cluster() as (cluster_dsn, _name, _owner_token):
            async with throwaway_db(cluster_dsn, seed=False) as database:
                for filename in POST_BASE_MIGRATIONS[:3]:
                    raw = (ROOT / "db" / "phase2" / filename).read_bytes()
                    await database.conn.execute(
                        "SELECT set_config('living.migration_checksum',$1,false)",
                        hashlib.sha256(raw).hexdigest(),
                    )
                    await database.conn.execute(raw.decode("utf-8"))
                await _setup(database.conn)
                await database.conn.execute(
                    "SELECT change_ledger.add_role_scope('ledger_owner',$1,$2)", T, C,
                )
                for filename in POST_BASE_MIGRATIONS[3:]:
                    raw = (ROOT / "db" / "phase2" / filename).read_bytes()
                    await database.conn.execute(
                        "SELECT set_config('living.migration_checksum',$1,false)",
                        hashlib.sha256(raw).hexdigest(),
                    )
                    await database.conn.execute(raw.decode("utf-8"))

                fixture = L(database)
                await fixture.propose(request_id="s13-preflight-cli-read-only")
                from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger

                ledger = SqlChangeLedger(
                    database.conn, {"worker": "clt_wrk", "auditor": "clt_aud"},
                    private_writer_schema_enabled=True,
                )
                chain_before = await ledger.verify_chain(SCOPE)
                assert chain_before.get("ok") is True, chain_before
                head_before = await ledger.ledger_head(SCOPE)
                unsigned = CheckpointRecord(
                    T, C, int(head_before["seq"]), head_before["head_hash"],
                    datetime.now(UTC), CHECKPOINT_KEY_ID, "0" * 128,
                    SERVICE_ID, "TEST",
                )
                checkpoint = replace(
                    unsigned, signature=checkpoint_private.sign(unsigned.signing_payload()).hex(),
                )
                registration = httpx.post(
                    base_url + "/v1/admin/keys/register",
                    headers={
                        "Authorization": "Bearer " + service_token,
                        "X-Anchor-Admin-Token": admin_token,
                    },
                    json={
                        "tenant_id": T,
                        "company_id": C,
                        "key_id": CHECKPOINT_KEY_ID,
                        "public_key_hex": _raw_public(checkpoint_private).hex(),
                        "role": "checkpoint_signer",
                    },
                    timeout=3,
                    trust_env=False,
                )
                assert registration.status_code == 201, registration.text
                async with httpx.AsyncClient(timeout=3, trust_env=False) as client_http:
                    client = DevAnchorClient(
                        base_url=base_url,
                        service_id=SERVICE_ID,
                        service_token=service_token,
                        latestness_authority_id=LATESTNESS_ID,
                        latestness_public_key=latest_signer.public_key_bytes,
                        key_authority_id=KEY_AUTH_ID,
                        key_authority_public_key=key_auth_signer.public_key_bytes,
                        http_client=client_http,
                    )
                    await client.write(checkpoint)
                    assert await client.latest(SCOPE) == checkpoint
                    count_before = await database.conn.fetchval(
                        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
                        T, C,
                    )
                    environment = _environment(**{
                        PREFIX + "DATABASE_DSN": _database_dsn(cluster_dsn, database.name),
                        PREFIX + "BASE_URL": base_url,
                        PREFIX + "SERVICE_ID": SERVICE_ID,
                        PREFIX + "BEARER_TOKEN": service_token,
                        PREFIX + "LATEST_AUTHORITY_ID": LATESTNESS_ID,
                        PREFIX + "LATEST_PUBLIC_KEY_HEX": latest_signer.public_key_bytes.hex(),
                        PREFIX + "KEY_AUTHORITY_ID": KEY_AUTH_ID,
                        PREFIX + "KEY_AUTHORITY_PUBLIC_KEY_HEX": key_auth_signer.public_key_bytes.hex(),
                        PREFIX + "TENANT_ID": T,
                        PREFIX + "COMPANY_ID": C,
                        PREFIX + "CHECKPOINT_PUBLIC_KEYS_JSON": json.dumps({
                            CHECKPOINT_KEY_ID: _raw_public(checkpoint_private).hex(),
                        }),
                    })
                    result = _invoke(environment)
                    payload = _payload(result, service_token, admin_token, cluster_dsn)
                    head_after = await ledger.ledger_head(SCOPE)
                    count_after = await database.conn.fetchval(
                        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
                        T, C,
                    )
                    assert result.returncode == 0
                    assert payload == {
                        "status": "NOT_READY", "reason": "SHARED_FENCE_UNAVAILABLE",
                    }, payload
                    assert head_after == head_before
                    assert count_after == count_before
                    await client.aclose()

    try:
        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive(), "synthetic dev anchor HTTP server did not stop"
        anchor_db = tmp_path / "synthetic-preflight-anchor.sqlite3"
        for suffix in ("", "-wal", "-shm"):
            (Path(str(anchor_db) + suffix)).unlink(missing_ok=True)
