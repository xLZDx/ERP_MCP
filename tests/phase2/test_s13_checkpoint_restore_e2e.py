"""A real pg_restore behind the independent synthetic S13 anchor fails closed.

Run with ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1 to provision an invocation-owned
PostgreSQL 16 container. The anchor service and all keys are synthetic TEST fixtures.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _pg_harness import disposable_cluster, owned_cluster_exec, throwaway_db
from test_change_ledger_sql import C, T, L, _setup
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.anchor_client import DevAnchorClient
from business_ai_gateway.phase2.change_ledger.checkpoint import CheckpointRecord, Ed25519SignatureVerifier
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleCoordinator, LifecycleReason, LifecycleStatus,
)
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger


ROOT = Path(__file__).resolve().parents[2]
SERVICE_ID = "s13-dev-anchor-e2e"
LATESTNESS_AUTHORITY_ID = "e2e-latestness-authority"
KEY_AUTHORITY_ID = "e2e-key-authority"
CHECKPOINT_KEY_ID = "checkpoint-restore-e2e-key"
POST_BASE_MIGRATIONS = (
    "019_ed25519_action_only.sql", "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql", "022_lifecycle_epoch_fence.sql",
    "023_lifecycle_activation_cap.sql", "024_restore_caller_lock_timeout.sql",
    "025_lifecycle_checkpoint_suffix.sql", "026_lifecycle_checkpoint_payload_minimization.sql",
    "027_private_writer_admission_schema.sql",
)

_SERVICE_RUNNER = r"""
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from business_ai_gateway.phase2.change_ledger.dev_anchor_service import DevAnchorConfig, create_app

class EphemeralSigner:
    def __init__(self, seed_name, allowed_prefix):
        self._key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(os.environ[seed_name]))
        self.public_key_bytes = self._key.public_key().public_bytes_raw()
        self._allowed_prefixes = allowed_prefix
    def sign(self, message):
        if type(message) is not bytes or not any(message.startswith(prefix) for prefix in self._allowed_prefixes):
            raise ValueError("test signer domain refused")
        return self._key.sign(message)

service_id = "s13-dev-anchor-e2e"
config = DevAnchorConfig(
    service_id=service_id,
    database_path=Path(os.environ["ANCHOR_DB_PATH"]),
    project_root=Path(os.environ["ERP_MCP_PROJECT_ROOT"]),
    mode="dev",
    bind_host="127.0.0.1",
    bearer_token=os.environ["ANCHOR_BEARER_TOKEN"],
    admin_token=os.environ["ANCHOR_ADMIN_TOKEN"],
    latestness_authority_id="e2e-latestness-authority",
    latestness_signer=EphemeralSigner(
        "LATESTNESS_SEED", (b"ERP_MCP:S13:ANCHOR-LATESTNESS:v1\n",
                             b"ERP_MCP:S13:ANCHOR-HISTORY:PROVIDER:v1\n")),
    key_authority_id="e2e-key-authority",
    key_authority_signer=EphemeralSigner(
        "KEY_AUTH_SEED", (b"ERP_MCP:S13:ANCHOR-KEY-AUTH:v1\n",
                          b"ERP_MCP:S13:ANCHOR-HISTORY:KEY-AUTH:v1\n")),
)
app = create_app(config)
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["ANCHOR_PORT"]),
            log_level="critical", access_log=False)
"""


def _raw_seed(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _wait_for_health(process: subprocess.Popen[bytes], url: str, token: str) -> None:
    deadline = time.monotonic() + 12
    async with httpx.AsyncClient(timeout=0.25) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                raise AssertionError(f"anchor child exited with {process.returncode}: {stderr[-2000:]}")
            try:
                response = await client.get(url + "/v1/health", headers={"Authorization": "Bearer " + token})
                if response.is_success:
                    assert response.json() == {"service_id": SERVICE_ID, "mode": "dev", "sink_kind": "TEST"}
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.05)
    raise AssertionError("separate anchor process did not become reachable before deadline")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _signed_checkpoint(key: Ed25519PrivateKey, scope: Scope, seq: int, head_hash: str) -> CheckpointRecord:
    unsigned = CheckpointRecord(
        tenant_id=scope.tenant_id, company_id=scope.company_id, seq=seq,
        head_hash=head_hash, signed_at=datetime.now(UTC), key_id=CHECKPOINT_KEY_ID,
        signature="", sink_id=SERVICE_ID, sink_kind="TEST",
    )
    return CheckpointRecord(**{**unsigned.__dict__, "signature": key.sign(unsigned.signing_payload()).hex()})


async def _snapshot_ledger(conn: asyncpg.Connection) -> tuple[tuple[str, tuple[str, ...]], ...]:
    tables = await conn.fetch(
        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='change_ledger' ORDER BY tablename",
    )
    snapshot = []
    for table in tables:
        name = table["tablename"].replace('"', '""')
        rows = await conn.fetch(f'SELECT to_jsonb(row_data) FROM change_ledger."{name}" AS row_data')
        values = []
        for row in rows:
            value = row[0]
            if isinstance(value, str):
                value = json.loads(value)
            values.append(json.dumps(value, sort_keys=True, separators=(",", ":")))
        snapshot.append((table["tablename"], tuple(sorted(values))))
    return tuple(snapshot)


async def _restore_skew(tmp_path: Path) -> tuple[str, str]:
    service_process: subprocess.Popen[bytes] | None = None
    client: DevAnchorClient | None = None
    anchor_db = tmp_path / "restore-anchor.sqlite3"
    database_names: list[str] = []
    random_token = secrets.token_urlsafe(48)
    admin_token = secrets.token_urlsafe(48)
    latestness_key = Ed25519PrivateKey.generate()
    key_authority_key = Ed25519PrivateKey.generate()
    checkpoint_key = Ed25519PrivateKey.generate()
    port = _free_loopback_port()
    scope = Scope(T, C)

    async with disposable_cluster() as (dsn, container_name, owner_token):
        volume_result = subprocess.run(
            [_docker_exe(), "inspect", "--format", '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}',
             container_name], capture_output=True, text=True, timeout=30, check=False,
        )
        assert volume_result.returncode == 0, volume_result.stderr
        volume_names = volume_result.stdout.split()
        assert volume_names, "expected fixture-owned PostgreSQL anonymous data volume"

        environment = os.environ.copy()
        source_path = str(ROOT / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (source_path, environment.get("PYTHONPATH", "")) if part
        )
        environment.update({
            "ANCHOR_DB_PATH": str(anchor_db),
            "ERP_MCP_PROJECT_ROOT": str(ROOT),
            "ANCHOR_BEARER_TOKEN": random_token,
            "ANCHOR_ADMIN_TOKEN": admin_token,
            "ANCHOR_PORT": str(port),
            "LATESTNESS_SEED": _raw_seed(latestness_key).hex(),
            "KEY_AUTH_SEED": _raw_seed(key_authority_key).hex(),
        })
        process_env = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        service_process = subprocess.Popen(
            [sys.executable, "-c", _SERVICE_RUNNER], cwd=ROOT, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=process_env,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            await _wait_for_health(service_process, base_url, random_token)
            async with httpx.AsyncClient(timeout=3, follow_redirects=False) as admin_http:
                response = await admin_http.post(
                    base_url + "/v1/admin/keys/register",
                    headers={"Authorization": "Bearer " + random_token,
                             "X-Anchor-Admin-Token": admin_token},
                    json={"tenant_id": T, "company_id": C, "key_id": CHECKPOINT_KEY_ID,
                          "public_key_hex": _public_key(checkpoint_key).hex(),
                          "role": "checkpoint_signer"},
                )
                assert response.status_code == 201, response.text
            client = DevAnchorClient(
                base_url=base_url, service_id=SERVICE_ID, service_token=random_token,
                latestness_authority_id=LATESTNESS_AUTHORITY_ID,
                latestness_public_key=_public_key(latestness_key),
                key_authority_id=KEY_AUTHORITY_ID,
                key_authority_public_key=_public_key(key_authority_key),
            )

            async with throwaway_db(dsn, seed=False) as source:
                database_names.append(source.name)
                for migration in POST_BASE_MIGRATIONS[:3]:
                    await _apply(source.conn, migration)
                await _setup(source.conn)
                await source.conn.execute("SELECT change_ledger.add_role_scope('ledger_owner',$1,$2)", T, C)
                for migration in POST_BASE_MIGRATIONS[3:]:
                    await _apply(source.conn, migration)

                ledger_source = SqlChangeLedger(
                    source.conn, {"worker": "clt_wrk", "auditor": "clt_aud"},
                    private_writer_schema_enabled=True,
                )
                fixture = L(source)
                await fixture.propose(request_id="s13-restore-before-anchor")
                earlier_head = await ledger_source.ledger_head(scope)
                earlier_checkpoint = _signed_checkpoint(
                    checkpoint_key, scope, int(earlier_head["seq"]), earlier_head["head_hash"],
                )
                await client.write(earlier_checkpoint)
                assert await client.latest(scope) == earlier_checkpoint
                assert await client.latest(Scope("T_FOREIGN", C)) is None

                dump_path = f"/tmp/s13-restore-{owner_token}.dump"
                dump = owned_cluster_exec(
                    container_name, owner_token, "pg_dump", "-U", "postgres", "-d", source.name,
                    "-Fc", "-f", dump_path, timeout=120,
                )
                assert dump.returncode == 0, dump.stderr.decode(errors="replace")
                try:
                    await fixture.propose(request_id="s13-restore-after-anchor")
                    later_head = await ledger_source.ledger_head(scope)
                    assert int(later_head["seq"]) > int(earlier_head["seq"])
                    later_checkpoint = _signed_checkpoint(
                        checkpoint_key, scope, int(later_head["seq"]), later_head["head_hash"],
                    )
                    await client.write(later_checkpoint)
                    assert await client.latest(scope) == later_checkpoint

                    async with throwaway_db(dsn, migrate=False, seed=False) as restored:
                        database_names.append(restored.name)
                        restore = owned_cluster_exec(
                            container_name, owner_token, "pg_restore", "-U", "postgres", "-d",
                            restored.name, "--exit-on-error", dump_path, timeout=120,
                        )
                        assert restore.returncode == 0, restore.stderr.decode(errors="replace")
                        restored.conn = await restored.connect()
                        ledger_restored = SqlChangeLedger(
                            restored.conn, {"worker": "clt_wrk", "auditor": "clt_aud"},
                            private_writer_schema_enabled=True,
                        )
                        restored_head = await ledger_restored.ledger_head(scope)
                        assert restored_head == earlier_head
                        assert int(restored_head["seq"]) < later_checkpoint.seq

                        # A fresh HTTP client proves that persisted anchor state is independent of
                        # the source client and restored PostgreSQL database.
                        restarted_client = DevAnchorClient(
                            base_url=base_url, service_id=SERVICE_ID, service_token=random_token,
                            latestness_authority_id=LATESTNESS_AUTHORITY_ID,
                            latestness_public_key=_public_key(latestness_key),
                            key_authority_id=KEY_AUTHORITY_ID,
                            key_authority_public_key=_public_key(key_authority_key),
                        )
                        try:
                            assert await restarted_client.latest(scope) == later_checkpoint
                            events_before = await restored.conn.fetchval(
                                "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
                                T, C,
                            )
                            coordinator = LifecycleCoordinator(
                                ledger_restored,
                                restarted_client,
                                Ed25519SignatureVerifier({CHECKPOINT_KEY_ID: _public_key(checkpoint_key)}),
                                key_authority=restarted_client,
                                latestness_authority=restarted_client,
                                dependency_timeout_seconds=10,
                            )
                            ledger_before = await _snapshot_ledger(restored.conn)
                            result = await coordinator.preflight(scope)
                            ledger_after = await _snapshot_ledger(restored.conn)
                            assert result.status is LifecycleStatus.NOT_READY, result
                            assert result.reason is LifecycleReason.CHECKPOINT_NOT_ANCESTOR, result
                            assert result.checkpoint_seq == later_checkpoint.seq, result
                            assert result.chain_count == earlier_head["seq"], result
                            assert result.suffix_event_count == 0, result
                            assert not hasattr(LifecycleStatus, "READY")
                            assert not hasattr(coordinator, "recover")
                            assert not hasattr(coordinator, "dispatch")
                            assert ledger_after == ledger_before, "preflight mutated restored ledger"
                            assert await restored.conn.fetchval(
                                "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
                                T, C,
                            ) == events_before
                            print("PASS: pg_restore to an earlier head fails closed against independent TEST anchor")
                        finally:
                            await restarted_client.aclose()
                finally:
                    removed = owned_cluster_exec(container_name, owner_token, "rm", "-f", dump_path, timeout=30)
                    assert removed.returncode == 0, removed.stderr.decode(errors="replace")

            admin = await asyncpg.connect(dsn, timeout=10)
            try:
                remaining = await admin.fetch(
                    "SELECT datname FROM pg_database WHERE datname=ANY($1::text[])", database_names,
                )
                assert remaining == [], f"throwaway databases remain: {remaining}"
            finally:
                await admin.close()
        finally:
            if client is not None:
                await client.aclose()
            _stop_process(service_process)
            for suffix in ("", "-wal", "-shm"):
                Path(str(anchor_db) + suffix).unlink(missing_ok=True)

    return container_name, owner_token


async def _apply(conn: asyncpg.Connection, filename: str) -> None:
    path = ROOT / "db" / "phase2" / filename
    raw = path.read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


def _docker_exe() -> str:
    import shutil
    return (os.environ.get("ERP_PHASE2_DOCKER") or shutil.which("docker")
            or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")


@pytest.mark.e2e
def test_restore_behind_independent_dev_anchor_fails_closed(tmp_path: Path) -> None:
    if os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS") != "1":
        pytest.skip("NOT_RUN: set ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1 to create owned disposable PostgreSQL")
    container_name, owner_token = asyncio.run(_restore_skew(tmp_path))
    from _pg_harness import docker
    assert docker("inspect", container_name, timeout=30).returncode != 0, "owned PostgreSQL container remains"
    print(f"CLEANUP: owned PostgreSQL container removed; ownership token prefix={owner_token[:8]}")
    print("LIMIT: synthetic TEST keys/service only; no production provider, writer, or READY admission")
