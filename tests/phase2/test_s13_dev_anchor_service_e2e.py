"""Separate-process HTTP E2E for the development-only S13 anchor boundary."""
from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.anchor_client import DevAnchorClient
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    Ed25519SignatureVerifier,
)
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleCoordinator,
    LifecycleReason,
    LifecycleStatus,
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
        if type(message) is not bytes or not any(
                message.startswith(prefix) for prefix in self._allowed_prefixes):
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


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class _Ledger:
    """Diagnostic ledger fixture; effectful recovery/writer calls are observable failures."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.effectful_calls = 0

    async def verify_chain(self, scope: Scope) -> dict[str, object]:
        self.calls.append("verify_chain")
        return {"ok": True, "count": 1}

    async def lifecycle_checkpoint_suffix(
            self, scope: Scope, checkpoint_seq: int, checkpoint_hash: str,
    ) -> dict[str, object]:
        self.calls.append("lifecycle_checkpoint_suffix")
        return {
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "checkpoint_seq": checkpoint_seq,
            "checkpoint_hash": checkpoint_hash,
            "anchor_matches": True,
            "head_seq": 1,
            "has_more": False,
            "events": [],
        }

    async def recover(self, *_args: object, **_kwargs: object) -> None:
        self.effectful_calls += 1
        raise AssertionError("preflight must not invoke recovery")

    async def write(self, *_args: object, **_kwargs: object) -> None:
        self.effectful_calls += 1
        raise AssertionError("preflight must not invoke checkpoint write")

    async def dispatch(self, *_args: object, **_kwargs: object) -> None:
        self.effectful_calls += 1
        raise AssertionError("preflight must not invoke dispatch")


async def _wait_for_health(process: subprocess.Popen[bytes], url: str,
                           token: str) -> None:
    deadline = time.monotonic() + 12
    async with httpx.AsyncClient(timeout=0.25) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                raise AssertionError(f"anchor child exited with {process.returncode}: {stderr[-2000:]}")
            try:
                response = await client.get(
                    url + "/v1/health", headers={"Authorization": "Bearer " + token},
                )
                if response.is_success:
                    assert response.json() == {
                        "service_id": "s13-dev-anchor-e2e", "mode": "dev", "sink_kind": "TEST",
                    }
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.05)
    process.terminate()
    try:
        await asyncio.to_thread(process.wait, 5)
    except subprocess.TimeoutExpired:
        process.kill()
        await asyncio.to_thread(process.wait, 5)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    raise AssertionError(
        "separate anchor process did not become reachable before deadline; "
        f"exit={process.returncode}, stderr={stderr[-2000:]}"
    )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_separate_dev_anchor_http_preflight_remains_not_ready(tmp_path: Path) -> None:
    """Exercise real HTTP and authority signatures without enabling startup recovery or writes."""
    latestness_key = Ed25519PrivateKey.generate()
    key_authority_key = Ed25519PrivateKey.generate()
    checkpoint_key = Ed25519PrivateKey.generate()
    assert len({_public_key(latestness_key), _public_key(key_authority_key),
                _public_key(checkpoint_key)}) == 3

    port = _reserve_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    bearer_token = "e2e-bearer-token-that-is-not-a-project-secret"
    admin_token = "e2e-admin-token-that-is-not-a-project-secret"
    database_path = tmp_path / "anchor.sqlite3"
    environment = os.environ.copy()
    environment.update({
        "PYTHONPATH": os.pathsep.join((str(Path("src").resolve()), str(Path.cwd()))),
        "ANCHOR_DB_PATH": str(database_path),
        "ERP_MCP_PROJECT_ROOT": str(Path.cwd()),
        "ANCHOR_BEARER_TOKEN": bearer_token,
        "ANCHOR_ADMIN_TOKEN": admin_token,
        "ANCHOR_PORT": str(port),
        "LATESTNESS_SEED": _raw_seed(latestness_key).hex(),
        "KEY_AUTH_SEED": _raw_seed(key_authority_key).hex(),
    })
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [sys.executable, "-c", _SERVICE_RUNNER],
        cwd=Path.cwd(),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    client: DevAnchorClient | None = None
    try:
        await _wait_for_health(process, base_url, bearer_token)
        assert process.pid != os.getpid()

        async with httpx.AsyncClient(timeout=2, follow_redirects=False) as admin_client:
            response = await admin_client.post(
                base_url + "/v1/admin/keys/register",
                headers={
                    "Authorization": "Bearer " + bearer_token,
                    "X-Anchor-Admin-Token": admin_token,
                },
                json={
                    "tenant_id": "tenant-e2e",
                    "company_id": "company-e2e",
                    "key_id": "checkpoint-e2e-key",
                    "public_key_hex": _public_key(checkpoint_key).hex(),
                    "role": "checkpoint_signer",
                },
            )
            assert response.status_code == 201

        client = DevAnchorClient(
            base_url=base_url,
            service_id="s13-dev-anchor-e2e",
            service_token=bearer_token,
            latestness_authority_id="e2e-latestness-authority",
            latestness_public_key=_public_key(latestness_key),
            key_authority_id="e2e-key-authority",
            key_authority_public_key=_public_key(key_authority_key),
        )
        scope = Scope("tenant-e2e", "company-e2e")
        unsigned = CheckpointRecord(
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            seq=1,
            head_hash=hashlib.sha256(b"synthetic S13 dev anchor E2E").hexdigest(),
            signed_at=datetime.now(UTC),
            key_id="checkpoint-e2e-key",
            signature="",
            sink_id="s13-dev-anchor-e2e",
            sink_kind="TEST",
        )
        record = CheckpointRecord(
            **{**unsigned.__dict__, "signature": checkpoint_key.sign(unsigned.signing_payload()).hex()}
        )
        await client.write(record)
        assert await client.latest(scope) == record
        assert await client.read_back(scope, 1) == record

        ledger = _Ledger()
        coordinator = LifecycleCoordinator(
            ledger,
            client,
            Ed25519SignatureVerifier({"checkpoint-e2e-key": _public_key(checkpoint_key)}),
            key_authority=client,
            latestness_authority=client,
            dependency_timeout_seconds=2,
        )
        result = await coordinator.preflight(scope)

        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.SHARED_FENCE_UNAVAILABLE
        assert ledger.calls == ["verify_chain", "lifecycle_checkpoint_suffix"]
        assert ledger.effectful_calls == 0
    finally:
        if client is not None:
            await client.aclose()
        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 5)
        if process.stderr:
            process.stderr.close()
        for artifact in (database_path, database_path.with_name(database_path.name + "-wal"),
                         database_path.with_name(database_path.name + "-shm")):
            artifact.unlink(missing_ok=True)
