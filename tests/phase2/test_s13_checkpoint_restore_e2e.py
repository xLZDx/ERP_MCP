"""S13 restore-skew E2E: real disposable PostgreSQL plus a separate TEST anchor process.

The PostgreSQL dump is captured at an earlier ledger head. The source then advances and its newer
checkpoint is retained by the independent loopback anchor service. Restoring the earlier dump must
be diagnosed as an anchor that is not an ancestor; preflight never exposes READY or admission.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _pg_harness import (
    disposable_cluster,
    docker,
    owned_cluster_exec,
    throwaway_db,
)
from test_change_ledger_sql import C, T, L, _setup
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    Ed25519SignatureVerifier,
)
from business_ai_gateway.phase2.change_ledger.dev_anchor_service import DevHttpCheckpointSink
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleCoordinator,
    LifecycleReason,
    LifecycleStatus,
)
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
POST_BASE_MIGRATIONS = (
    "019_ed25519_action_only.sql", "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql", "022_lifecycle_epoch_fence.sql",
    "023_lifecycle_activation_cap.sql", "024_restore_caller_lock_timeout.sql",
    "025_lifecycle_checkpoint_suffix.sql", "026_lifecycle_checkpoint_payload_minimization.sql",
    "027_private_writer_admission_schema.sql",
)
SCOPE = Scope(T, C)
SERVICE_ID = "erp-mcp-dev-anchor-v1"
LATEST_KEY_ID = "synthetic-restore-latest"
KEY_AUTH_KEY_ID = "synthetic-restore-key-auth"
CHECKPOINT_KEY_ID = "synthetic-restore-checkpoint"


async def _apply(conn: asyncpg.Connection, filename: str) -> None:
    raw = (MIGRATIONS / filename).read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _signed_checkpoint(private_key: Ed25519PrivateKey, seq: int, head_hash: str) -> CheckpointRecord:
    unsigned = CheckpointRecord(
        SCOPE.tenant_id, SCOPE.company_id, seq, head_hash, datetime.now(UTC),
        CHECKPOINT_KEY_ID, "0" * 128, SERVICE_ID, "TEST",
    )
    return replace(unsigned, signature=private_key.sign(unsigned.signing_payload()).hex())


async def _ledger_snapshot(conn: asyncpg.Connection) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Capture every row in every durable change_ledger table for a no-mutation oracle."""
    tables = await conn.fetch(
        "SELECT tablename FROM pg_catalog.pg_tables "
        "WHERE schemaname='change_ledger' ORDER BY tablename",
    )
    snapshot = []
    for table in tables:
        # Names come from pg_catalog; quote defensively before interpolating the identifier.
        name = table["tablename"].replace('"', '""')
        rows = await conn.fetch(
            f'SELECT to_jsonb(row_data) FROM change_ledger."{name}" AS row_data',
        )
        encoded = []
        for row in rows:
            value = row[0]
            if isinstance(value, str):
                value = json.loads(value)
            encoded.append(json.dumps(value, sort_keys=True, separators=(",", ":")))
        snapshot.append((table["tablename"], tuple(sorted(encoded))))
    return tuple(snapshot)


def _start_anchor(tmp_path: Path, port: int, token: str,
                  latest_private: Ed25519PrivateKey,
                  key_auth_private: Ed25519PrivateKey,
                  checkpoint_private: Ed25519PrivateKey
                  ) -> tuple[subprocess.Popen[str], DevHttpCheckpointSink, Path,
                             Ed25519SignatureVerifier]:
    latest_public = _raw_public(latest_private)
    key_auth_public = _raw_public(key_auth_private)
    checkpoint_public = _raw_public(checkpoint_private)
    database = tmp_path / "restore-anchor.sqlite3"
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (src, env.get("PYTHONPATH", "")) if part
    )
    env.update({
        "ERP_MCP_DEV_ANCHOR_ENABLED": "1",
        "ERP_MCP_DEV_ANCHOR_DB": str(database),
        "ERP_MCP_DEV_ANCHOR_TOKEN": token,
        "ERP_MCP_DEV_ANCHOR_LATEST_KEY_ID": LATEST_KEY_ID,
        "ERP_MCP_DEV_ANCHOR_LATEST_PRIVATE_KEY_B64": _b64(latest_private.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )),
        "ERP_MCP_DEV_ANCHOR_LATEST_PUBLIC_KEY_B64": _b64(latest_public),
        "ERP_MCP_DEV_ANCHOR_KEY_AUTH_KEY_ID": KEY_AUTH_KEY_ID,
        "ERP_MCP_DEV_ANCHOR_KEY_AUTH_PRIVATE_KEY_B64": _b64(key_auth_private.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )),
        "ERP_MCP_DEV_ANCHOR_KEY_AUTH_PUBLIC_KEY_B64": _b64(key_auth_public),
        "ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON": json.dumps([{
            "tenant_id": SCOPE.tenant_id,
            "company_id": SCOPE.company_id,
            "key_id": CHECKPOINT_KEY_ID,
            "public_key_b64": _b64(checkpoint_public),
        }]),
        "ERP_MCP_DEV_ANCHOR_HOST": "127.0.0.1",
        "ERP_MCP_DEV_ANCHOR_PORT": str(port),
    })
    process = subprocess.Popen(
        [sys.executable, "-m", "business_ai_gateway.phase2.change_ledger.dev_anchor_service"],
        cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = "" if process.stderr is None else process.stderr.read()
            raise AssertionError(f"anchor child exited before health check: {detail}")
        try:
            response = httpx.get(base_url + "/health", timeout=0.25, trust_env=False)
            if response.status_code == 204:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        detail = "" if process.stderr is None else process.stderr.read()
        raise AssertionError(f"anchor child did not become healthy: {detail}")
    verifier = Ed25519SignatureVerifier({CHECKPOINT_KEY_ID: checkpoint_public})
    sink = DevHttpCheckpointSink(
        base_url, bearer_token=token, expected_key_id=LATEST_KEY_ID,
        authority_public_key_b64=_b64(latest_public),
        expected_key_authorization_id=KEY_AUTH_KEY_ID,
        key_authorization_public_key_b64=_b64(key_auth_public),
        checkpoint_verifier=verifier,
    )
    return process, sink, database, verifier


def _stop_anchor(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def _restore_skew(tmp_path: Path) -> tuple[str, str, list[str]]:
    container_name = ""
    owner_token = ""
    volume_names: list[str] = []
    database_names: list[str] = []
    service_process: subprocess.Popen[str] | None = None
    anchor_db: Path | None = None
    random_token = secrets.token_urlsafe(48)
    latest_private = Ed25519PrivateKey.generate()
    key_auth_private = Ed25519PrivateKey.generate()
    checkpoint_private = Ed25519PrivateKey.generate()
    port = _free_loopback_port()

    async with disposable_cluster() as (dsn, container_name, owner_token):
        mounts = docker(
            "inspect", "--format",
            '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}',
            container_name, timeout=30,
        )
        assert mounts.returncode == 0, mounts.stderr.decode(errors="replace")
        volume_names = mounts.stdout.decode().split()
        assert volume_names, "expected fixture-owned PostgreSQL anonymous data volume"

        service_process, sink, anchor_db, verifier = _start_anchor(
            tmp_path, port, random_token, latest_private, key_auth_private, checkpoint_private,
        )
        try:
            async with throwaway_db(dsn, seed=False) as source:
                database_names.append(source.name)
                for migration in POST_BASE_MIGRATIONS[:3]:
                    await _apply(source.conn, migration)
                await _setup(source.conn)
                await source.conn.execute(
                    "SELECT change_ledger.add_role_scope('ledger_owner',$1,$2)", T, C,
                )
                for migration in POST_BASE_MIGRATIONS[3:]:
                    await _apply(source.conn, migration)

                ledger_source = SqlChangeLedger(
                    source.conn, {"worker": "clt_wrk", "auditor": "clt_aud"},
                    private_writer_schema_enabled=True,
                )
                fixture = L(source)
                await fixture.propose(request_id="s13-restore-before-anchor")
                earlier_head = await ledger_source.ledger_head(SCOPE)
                earlier_checkpoint = _signed_checkpoint(
                    checkpoint_private, int(earlier_head["seq"]), earlier_head["head_hash"],
                )
                await sink.write(earlier_checkpoint)

                dump_path = f"/tmp/s13-restore-{owner_token}.dump"
                dump = owned_cluster_exec(
                    container_name, owner_token,
                    "pg_dump", "-U", "postgres", "-d", source.name, "-Fc", "-f", dump_path,
                    timeout=120,
                )
                assert dump.returncode == 0, dump.stderr.decode(errors="replace")

                await fixture.propose(request_id="s13-restore-after-anchor")
                later_head = await ledger_source.ledger_head(SCOPE)
                assert int(later_head["seq"]) > int(earlier_head["seq"])
                later_checkpoint = _signed_checkpoint(
                    checkpoint_private, int(later_head["seq"]), later_head["head_hash"],
                )
                await sink.write(later_checkpoint)
                latest_record, latestness = await sink.latest_checkpoint(SCOPE)
                assert latest_record == later_checkpoint
                assert latestness.authority_revision == 2

                async with throwaway_db(dsn, migrate=False, seed=False) as restored:
                    database_names.append(restored.name)
                    restore = owned_cluster_exec(
                        container_name, owner_token, "pg_restore", "-U", "postgres",
                        "-d", restored.name, "--exit-on-error", dump_path, timeout=120,
                    )
                    assert restore.returncode == 0, restore.stderr.decode(errors="replace")
                    restored.conn = await restored.connect()
                    ledger_restored = SqlChangeLedger(
                        restored.conn, {"worker": "clt_wrk", "auditor": "clt_aud"},
                        private_writer_schema_enabled=True,
                    )
                    restored_head = await ledger_restored.ledger_head(SCOPE)
                    assert restored_head == earlier_head
                    assert int(restored_head["seq"]) < later_checkpoint.seq
                    # A new client must recover the retained latest checkpoint from the running
                    # service itself; preflight cannot pass using the source client's cache.
                    restored_sink = DevHttpCheckpointSink(
                        f"http://127.0.0.1:{port}",
                        bearer_token=random_token,
                        expected_key_id=LATEST_KEY_ID,
                        authority_public_key_b64=_b64(_raw_public(latest_private)),
                        expected_key_authorization_id=KEY_AUTH_KEY_ID,
                        key_authorization_public_key_b64=_b64(_raw_public(key_auth_private)),
                        checkpoint_verifier=verifier,
                    )
                    persisted_checkpoint, persisted_latestness = (
                        await restored_sink.latest_checkpoint(SCOPE)
                    )
                    assert persisted_checkpoint == later_checkpoint
                    assert persisted_latestness.authority_revision == 2
                    events_before = await restored.conn.fetchval(
                        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
                        T, C,
                    )

                    coordinator = LifecycleCoordinator(
                        ledger_restored,
                        restored_sink,
                        verifier,
                        key_authority=restored_sink,
                        latestness_authority=restored_sink,
                        dependency_timeout_seconds=10,
                    )
                    ledger_before_preflight = await _ledger_snapshot(restored.conn)
                    result = await coordinator.preflight(SCOPE)
                    ledger_after_preflight = await _ledger_snapshot(restored.conn)
                    assert result.status is LifecycleStatus.NOT_READY, result
                    assert result.reason is LifecycleReason.CHECKPOINT_NOT_ANCESTOR, result
                    assert result.checkpoint_seq == later_checkpoint.seq, result
                    assert result.chain_count == earlier_head["seq"], result
                    assert result.suffix_event_count == 0, result
                    assert not hasattr(LifecycleStatus, "READY")
                    assert not hasattr(coordinator, "recover")
                    assert not hasattr(coordinator, "dispatch")
                    # No table or row is excluded: preflight is diagnostic and must leave the
                    # complete restored ledger snapshot unchanged, including holds and permits.
                    assert ledger_after_preflight == ledger_before_preflight
                    assert await restored.conn.fetchval(
                        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
                        T, C,
                    ) == events_before
                    print(
                        "PASS: restored PostgreSQL head is behind independent TEST anchor; "
                        "preflight fails closed as CHECKPOINT_NOT_ANCESTOR",
                        flush=True,
                    )

                removed_dump = owned_cluster_exec(
                    container_name, owner_token, "rm", "-f", dump_path, timeout=30,
                )
                assert removed_dump.returncode == 0, removed_dump.stderr.decode(errors="replace")
            admin = await asyncpg.connect(dsn, timeout=10)
            try:
                remaining = await admin.fetch(
                    "SELECT datname FROM pg_database WHERE datname=ANY($1::text[])",
                    database_names,
                )
                assert remaining == [], f"throwaway databases remain: {remaining}"
            finally:
                await admin.close()
        finally:
            if service_process is not None:
                _stop_anchor(service_process)
            if anchor_db is not None:
                for suffix in ("", "-wal", "-shm"):
                    candidate = Path(str(anchor_db) + suffix)
                    if candidate.exists():
                        candidate.unlink()

    return container_name, owner_token, volume_names


def test_restore_behind_external_anchor_fails_closed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A true pg_restore to an earlier head cannot pass the independent anchor check."""
    monkeypatch.setenv("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", "1")
    container_name, owner_token, volume_names = asyncio.run(_restore_skew(tmp_path))
    assert docker("inspect", container_name, timeout=30).returncode != 0, \
        "invocation-owned PostgreSQL container remains after cleanup"
    for volume in volume_names:
        assert docker("volume", "inspect", volume, timeout=30).returncode != 0, \
            f"invocation-owned PostgreSQL volume remains after cleanup: {volume}"
    assert not list(tmp_path.glob("restore-anchor.sqlite3*")), "anchor service SQLite files remain"
    print(f"CLEANUP: owned PostgreSQL container and {len(volume_names)} volume(s) absent")
    print(f"OWNERSHIP: verified invocation token prefix {owner_token[:8]}")
    print("LIMIT: synthetic TEST keys/service only; no production provider or host-rollback resistance")
