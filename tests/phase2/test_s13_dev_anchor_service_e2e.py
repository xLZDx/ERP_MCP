"""Child-process E2E for the TEST-only S13 development anchor service.

Uses only generated Ed25519 keys and a temporary SQLite database. This exercises process and
HTTP boundaries; it does not establish production latestness or anti-rollback guarantees.
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
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointKeyAuthorizationBasis,
    CheckpointRecord,
    Ed25519SignatureVerifier,
    checkpoint_identity,
)
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleCoordinator,
    LifecycleReason,
    LifecycleStatus,
)
from business_ai_gateway.phase2.change_ledger.dev_anchor_service import (
    DevAnchorError,
    DevHttpCheckpointSink,
)


ROOT = Path(__file__).resolve().parents[2]
SCOPE = Scope("synthetic-tenant", "synthetic-company")
SERVICE_KEY_ID = "synthetic-dev-anchor"
CHECKPOINT_KEY_ID = "synthetic-checkpoint-key"
ROTATED_CHECKPOINT_KEY_ID = "synthetic-checkpoint-key-v2"
UNKNOWN_KEY_ID = "synthetic-unregistered-key"
SINK_ID = "erp-mcp-dev-anchor-v1"
LOWER_SCOPE = Scope("synthetic-tenant", "synthetic-company-lower")


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _record(private_key: Ed25519PrivateKey, *, seq: int, head_char: str,
            key_id: str = CHECKPOINT_KEY_ID, scope: Scope = SCOPE) -> CheckpointRecord:
    unsigned = CheckpointRecord(
        tenant_id=scope.tenant_id,
        company_id=scope.company_id,
        seq=seq,
        head_hash=head_char * 64,
        signed_at=datetime.now(UTC),
        key_id=key_id,
        signature="0" * 128,
        sink_id=SINK_ID,
        sink_kind="TEST",
    )
    return replace(unsigned, signature=private_key.sign(unsigned.signing_payload()).hex())


def _record_json(record: CheckpointRecord) -> dict[str, object]:
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


def _anchor_event_digest(proof: dict[str, object]) -> str:
    event = {
        "tenant_id": proof["tenant_id"],
        "company_id": proof["company_id"],
        "revision": proof["revision"],
        "seq": proof["seq"],
        "event_id": proof["event_id"],
        "checkpoint_digest": proof["checkpoint_digest"],
        "previous_digest": proof["previous_digest"],
    }
    canonical = json.dumps(
        event, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(b"erp-mcp-dev-anchor-event|v1\0" + canonical).hexdigest()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _start_service(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "business_ai_gateway.phase2.change_ledger.dev_anchor_service"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _wait_healthy(process: subprocess.Popen[str], base_url: str) -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"dev anchor child exited before health check: {process.returncode}")
        try:
            response = httpx.get(base_url + "/health", timeout=0.25, trust_env=False)
            if response.status_code == 204:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise AssertionError("dev anchor child did not become healthy within 8 seconds")


def _stop_service(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_dev_anchor_http_persistence_auth_and_fail_closed(tmp_path: Path) -> None:
    """Exercise authenticated persistence, restart, ordering, and refusal boundaries."""
    asyncio.run(_exercise_dev_anchor(tmp_path))


async def _exercise_dev_anchor(tmp_path: Path) -> None:
    database = tmp_path / "dev-anchor.sqlite3"
    service_private = Ed25519PrivateKey.generate()
    checkpoint_private = Ed25519PrivateKey.generate()
    rotated_checkpoint_private = Ed25519PrivateKey.generate()
    unknown_private = Ed25519PrivateKey.generate()
    service_public = _raw_public(service_private)
    checkpoint_public = _raw_public(checkpoint_private)
    rotated_checkpoint_public = _raw_public(rotated_checkpoint_private)
    unknown_public = _raw_public(unknown_private)
    assert service_public != checkpoint_public
    token = secrets.token_urlsafe(48)
    port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    child_env = os.environ.copy()
    src_dir = str(ROOT / "src")
    child_env["PYTHONPATH"] = os.pathsep.join(
        item for item in (src_dir, child_env.get("PYTHONPATH", "")) if item
    )
    child_env.update({
        "ERP_MCP_DEV_ANCHOR_ENABLED": "1",
        "ERP_MCP_DEV_ANCHOR_DB": str(database),
        "ERP_MCP_DEV_ANCHOR_TOKEN": token,
        "ERP_MCP_DEV_ANCHOR_KEY_ID": SERVICE_KEY_ID,
        "ERP_MCP_DEV_ANCHOR_PRIVATE_KEY_B64": _b64(service_private.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )),
        "ERP_MCP_DEV_ANCHOR_PUBLIC_KEY_B64": _b64(service_public),
        "ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON": json.dumps([
            {
                "tenant_id": scope.tenant_id,
                "company_id": scope.company_id,
                "key_id": CHECKPOINT_KEY_ID,
                "public_key_b64": _b64(checkpoint_public),
            }
            for scope in (SCOPE, LOWER_SCOPE)
        ]),
        "ERP_MCP_DEV_ANCHOR_HOST": "127.0.0.1",
        "ERP_MCP_DEV_ANCHOR_PORT": str(port),
    })
    verifier = Ed25519SignatureVerifier({
        CHECKPOINT_KEY_ID: checkpoint_public,
        ROTATED_CHECKPOINT_KEY_ID: rotated_checkpoint_public,
        UNKNOWN_KEY_ID: unknown_public,
    })
    process: subprocess.Popen[str] | None = None
    restarted: subprocess.Popen[str] | None = None
    try:
        process = _start_service(child_env)
        _wait_healthy(process, base_url)
        sink = DevHttpCheckpointSink(
            base_url,
            bearer_token=token,
            expected_key_id=SERVICE_KEY_ID,
            authority_public_key_b64=_b64(service_public),
            checkpoint_verifier=verifier,
        )
        first = _record(checkpoint_private, seq=1, head_char="a")
        retired_second = _record(checkpoint_private, seq=2, head_char="b")
        second = _record(rotated_checkpoint_private, seq=2, head_char="c",
                         key_id=ROTATED_CHECKPOINT_KEY_ID)

        await sink.write(first)
        assert await sink.read_back(SCOPE, 1) == first
        assert await sink.latest(SCOPE) == first
        authorization = await sink.authorize_checkpoint(SCOPE, first)
        assert authorization is not None
        assert authorization.basis is CheckpointKeyAuthorizationBasis.ACTIVE
        assert (authorization.tenant_id, authorization.company_id, authorization.key_id) == (
            SCOPE.tenant_id, SCOPE.company_id, CHECKPOINT_KEY_ID,
        )

        with httpx.Client(timeout=2, trust_env=False) as client:
            unauthorized = client.put(
                base_url + "/v1/checkpoints", json={"record": _record_json(first)},
                headers={"Authorization": "Bearer " + secrets.token_urlsafe(48)},
            )
            assert unauthorized.status_code == 401
            assert unauthorized.json() == {"error": "AUTH_REQUIRED"}

            malformed = client.put(
                base_url + "/v1/checkpoints", content=b"{not-json",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            assert malformed.status_code == 400
            assert malformed.json() == {"error": "INVALID_REQUEST"}

        unknown = _record(unknown_private, seq=3, head_char="c", key_id=UNKNOWN_KEY_ID)
        assert await sink.authorize_checkpoint(SCOPE, unknown) is None
        with pytest.raises(DevAnchorError, match="CHECKPOINT_INVALID"):
            await sink.write(unknown)

        # Restart with a narrowly bounded synthetic retirement receipt for the old key and a
        # newly active key. This is test configuration, not production custody evidence.
        accepted_at = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
        receipt_id = "synthetic-rotation-receipt-001"
        child_env["ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON"] = json.dumps([
            {
                "tenant_id": SCOPE.tenant_id,
                "company_id": SCOPE.company_id,
                "key_id": CHECKPOINT_KEY_ID,
                "public_key_b64": _b64(checkpoint_public),
                "basis": CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT.value,
                "receipt_id": receipt_id,
                "accepted_at": accepted_at.isoformat(),
                "accepted_through_seq": 1,
            },
            {
                "tenant_id": SCOPE.tenant_id,
                "company_id": SCOPE.company_id,
                "key_id": ROTATED_CHECKPOINT_KEY_ID,
                "public_key_b64": _b64(rotated_checkpoint_public),
            },
            {
                "tenant_id": LOWER_SCOPE.tenant_id,
                "company_id": LOWER_SCOPE.company_id,
                "key_id": CHECKPOINT_KEY_ID,
                "public_key_b64": _b64(checkpoint_public),
            },
        ])
        _stop_service(process)
        process = None
        restarted = _start_service(child_env)
        _wait_healthy(restarted, base_url)
        with httpx.Client(timeout=2, trust_env=False) as client:
            nonce = secrets.token_hex(32)
            latest_proof = client.post(
                base_url + "/v1/checkpoints/latest",
                json={"tenant_id": SCOPE.tenant_id, "company_id": SCOPE.company_id,
                      "nonce": nonce},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert latest_proof.status_code == 200
            first_proof = latest_proof.json()["proof"]
            assert first_proof["revision"] == 1
            assert first_proof["seq"] == first.seq
            assert first_proof["nonce"] == nonce
            assert first_proof["previous_digest"] is None
            assert first_proof["checkpoint_digest"] == checkpoint_identity(first)
            assert first_proof["event_digest"] == _anchor_event_digest(first_proof)
        restarted_sink = DevHttpCheckpointSink(
            base_url,
            bearer_token=token,
            expected_key_id=SERVICE_KEY_ID,
            authority_public_key_b64=_b64(service_public),
            checkpoint_verifier=verifier,
        )
        assert await restarted_sink.read_back(SCOPE, 1) == first
        assert await restarted_sink.latest(SCOPE) == first
        retired_authorization = await restarted_sink.authorize_checkpoint(SCOPE, first)
        assert retired_authorization is not None
        assert retired_authorization.basis is CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT
        assert retired_authorization.receipt_id == receipt_id
        assert retired_authorization.accepted_at == accepted_at

        assert await restarted_sink.authorize_checkpoint(SCOPE, retired_second) is None
        with pytest.raises(DevAnchorError, match="CHECKPOINT_INVALID"):
            await restarted_sink.write(retired_second)

        await restarted_sink.write(second)
        assert await restarted_sink.read_back(SCOPE, 2) == second
        assert await restarted_sink.latest(SCOPE) == second

        with httpx.Client(timeout=2, trust_env=False) as client:
            nonce = secrets.token_hex(32)
            latest_proof = client.post(
                base_url + "/v1/checkpoints/latest",
                json={"tenant_id": SCOPE.tenant_id, "company_id": SCOPE.company_id,
                      "nonce": nonce},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert latest_proof.status_code == 200
            second_proof = latest_proof.json()["proof"]
            assert second_proof["revision"] == 2
            assert second_proof["seq"] == second.seq
            assert second_proof["nonce"] == nonce
            assert second_proof["previous_digest"] == first_proof["event_digest"]
            assert second_proof["checkpoint_digest"] == checkpoint_identity(second)
            assert second_proof["event_digest"] == _anchor_event_digest(second_proof)

        # Even a trusted-signature response is rejected if its event hash does not commit
        # to the returned checkpoint row. This exercises the client trust boundary with an
        # independently signed but internally inconsistent proof.
        inconsistent_proof = dict(second_proof)
        inconsistent_proof["checkpoint_digest"] = "0" * 64
        signed_fields = {key: value for key, value in inconsistent_proof.items()
                         if key != "signature"}
        inconsistent_proof["signature"] = service_private.sign(
            b"erp-mcp-dev-anchor-latest|v1\0" + json.dumps(
                signed_fields, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True, allow_nan=False,
            ).encode("ascii")
        ).hex()
        inconsistent_response = httpx.Response(200, json={
            "record": _record_json(second), "proof": inconsistent_proof,
        })
        with patch(
            "business_ai_gateway.phase2.change_ledger.dev_anchor_service.httpx.request",
            return_value=inconsistent_response,
        ):
            with pytest.raises(DevAnchorError, match="LATEST_PROOF_INVALID"):
                await restarted_sink.latest_checkpoint(SCOPE)

        # A second receipt-bound query after rotation proves the returned retirement basis is
        # limited to seq 1 while seq 2 is authorized by the newly active key.
        rotated_latest, rotated_evidence = await restarted_sink.latest_checkpoint(SCOPE)
        assert rotated_latest == second and rotated_evidence is not None
        new_key_authorization = await restarted_sink.authorize_checkpoint(SCOPE, second)
        assert new_key_authorization is not None
        assert new_key_authorization.basis is CheckpointKeyAuthorizationBasis.ACTIVE
        assert new_key_authorization.key_id == ROTATED_CHECKPOINT_KEY_ID

        latest_record, latestness = await restarted_sink.latest_checkpoint(SCOPE)
        assert latest_record == second
        assert latestness is not None
        assert (latestness.tenant_id, latestness.company_id) == (
            SCOPE.tenant_id, SCOPE.company_id,
        )
        assert latestness.checkpoint_digest
        assert latestness.authority_id == "erp-mcp-dev-anchor-v1"
        assert latestness.authority_revision == 2
        assert latestness.authority_event_id and latestness.authority_event_digest

        order: list[str] = []

        class RecordingLedger:
            async def verify_chain(self, scope: Scope) -> dict[str, object]:
                order.append("verify_chain")
                assert scope == SCOPE
                return {"ok": True, "count": 2}

            async def lifecycle_checkpoint_suffix(
                    self, scope: Scope, checkpoint_seq: int, checkpoint_hash: str,
                    limit: int = 128) -> dict[str, object]:
                order.append("suffix")
                assert scope == SCOPE and checkpoint_seq == 2
                assert checkpoint_hash == second.head_hash and limit == 128
                return {
                    "tenant_id": SCOPE.tenant_id,
                    "company_id": SCOPE.company_id,
                    "checkpoint_seq": 2,
                    "checkpoint_hash": second.head_hash,
                    "anchor_matches": True,
                    "head_seq": 2,
                    "has_more": False,
                    "events": [],
                }

        class RecordingLatestness:
            is_test_double = True

            async def latest_checkpoint(self, scope: Scope):
                order.append("latestness")
                return await restarted_sink.latest_checkpoint(scope)

        class RecordingKeyAuthority:
            is_test_double = True

            async def authorize_checkpoint(self, scope: Scope, record: CheckpointRecord):
                order.append("key_authorization")
                return await restarted_sink.authorize_checkpoint(scope, record)

        result = await LifecycleCoordinator(
            RecordingLedger(), verifier,
            key_authority=RecordingKeyAuthority(),
            latestness_authority=RecordingLatestness(),
        ).preflight(SCOPE)
        assert result.status is LifecycleStatus.NOT_READY
        assert result.reason is LifecycleReason.SHARED_FENCE_UNAVAILABLE
        assert order == ["verify_chain", "latestness", "key_authorization", "suffix"]

        # A correctly signed older sequence is refused after restart, proving the retained
        # latest sequence remains 2 rather than merely checking the read-back history.
        # A second synthetic scope makes seq 1 strictly older than its current seq 2.
        lower_latest = _record(checkpoint_private, seq=2, head_char="e", scope=LOWER_SCOPE)
        lower_stale = _record(checkpoint_private, seq=1, head_char="f", scope=LOWER_SCOPE)
        with httpx.Client(timeout=2, trust_env=False) as client:
            stored = client.put(
                base_url + "/v1/checkpoints", json={"record": _record_json(lower_latest)},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert stored.status_code == 200
            rollback = client.put(
                base_url + "/v1/checkpoints", json={"record": _record_json(lower_stale)},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert rollback.status_code == 409
            assert rollback.json() == {"error": "CHECKPOINT_ROLLBACK"}
    finally:
        for child in (process, restarted):
            if child is not None:
                _stop_service(child)
        for sidecar in (database, Path(str(database) + "-wal"), Path(str(database) + "-shm")):
            sidecar.unlink(missing_ok=True)
            assert not sidecar.exists(), f"temporary SQLite artifact remains: {sidecar.name}"
