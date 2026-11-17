"""Functional API qualification for the split S13 dev-anchor authority service.

This is a synthetic TEST fixture. It does not prove external provider freshness or production trust.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import sys
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.anchor_client import (
    DevAnchorClient,
    DevAnchorClientError,
)
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointKeyAuthorizationBasis,
    CheckpointRecord,
)
from business_ai_gateway.phase2.change_ledger.dev_anchor_service_s13.service import (
    DevAnchorConfig,
    create_app,
)
from erp_mcp_private_writer.dpapi_signer import (
    DpapiSignerError,
    WindowsDpapiEd25519Signer,
    verify_ed25519,
)


ROOT = Path(__file__).resolve().parents[2]
SERVICE_ID = "synthetic-s13-anchor"
LATESTNESS_AUTHORITY_ID = "synthetic-latestness-root"
KEY_AUTHORITY_ID = "synthetic-key-authority-root"
SERVICE_TOKEN = "synthetic-service-token-" + "s" * 40
ADMIN_TOKEN = "synthetic-admin-token-" + "a" * 40
SCOPE = Scope("synthetic-tenant", "synthetic-company")
CHECKPOINT_KEY_ID = "synthetic-checkpoint-key"


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


def _record(private_key: Ed25519PrivateKey) -> CheckpointRecord:
    unsigned = CheckpointRecord(
        tenant_id=SCOPE.tenant_id,
        company_id=SCOPE.company_id,
        seq=1,
        head_hash="a" * 64,
        signed_at=datetime(2026, 11, 17, tzinfo=UTC),
        key_id=CHECKPOINT_KEY_ID,
        signature="0" * 128,
        sink_id=SERVICE_ID,
        sink_kind="TEST",
    )
    return replace(unsigned, signature=private_key.sign(unsigned.signing_payload()).hex())


def _config(tmp_path: Path, latest_signer: _Signer, key_signer: _Signer) -> DevAnchorConfig:
    return DevAnchorConfig(
        service_id=SERVICE_ID,
        database_path=(tmp_path / "s13-anchor.sqlite3").resolve(),
        project_root=ROOT.resolve(),
        mode="dev",
        bind_host="127.0.0.1",
        bearer_token=SERVICE_TOKEN,
        admin_token=ADMIN_TOKEN,
        latestness_authority_id=LATESTNESS_AUTHORITY_ID,
        latestness_signer=latest_signer,
        key_authority_id=KEY_AUTHORITY_ID,
        key_authority_signer=key_signer,
    )


def test_split_authorities_bind_challenges_history_and_scope(tmp_path: Path) -> None:
    asyncio.run(_exercise_split_authorities(tmp_path))


def test_dpapi_signer_keeps_latestness_and_key_authority_domains_separate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    latest_seed = bytes(range(32))
    key_seed = bytes(range(1, 33))
    latest_private = Ed25519PrivateKey.from_private_bytes(latest_seed)
    key_private = Ed25519PrivateKey.from_private_bytes(key_seed)
    latest = WindowsDpapiEd25519Signer(
        key_id="latestness-test-key", key_version="test-v1",
        signer_role="checkpoint_latestness_authority",
        protected_seed_path=(tmp_path / "latestness.dpapi").resolve(),
        expected_public_key=_raw_public(latest_private),
    )
    key_auth = WindowsDpapiEd25519Signer(
        key_id="key-authority-test-key", key_version="test-v1",
        signer_role="checkpoint_key_authority",
        protected_seed_path=(tmp_path / "key-auth.dpapi").resolve(),
        expected_public_key=_raw_public(key_private),
    )
    seeds = {latest.key_id: latest_seed, key_auth.key_id: key_seed}
    monkeypatch.setattr(
        WindowsDpapiEd25519Signer, "_unprotect_seed", lambda signer: seeds[signer.key_id],
    )
    latest_message = b"ERP_MCP:S13:ANCHOR-LATESTNESS:v1\nchallenge"
    key_auth_message = b"ERP_MCP:S13:ANCHOR-KEY-AUTH:v1\nchallenge"
    latest_signature = latest.sign(latest_message)
    key_auth_signature = key_auth.sign(key_auth_message)
    assert verify_ed25519(
        public_key=latest.public_key_bytes, message=latest_message,
        signature=latest_signature,
    )
    assert verify_ed25519(
        public_key=key_auth.public_key_bytes, message=key_auth_message,
        signature=key_auth_signature,
    )
    with pytest.raises(DpapiSignerError, match="SIGNER_DOMAIN_REFUSED"):
        latest.sign(key_auth_message)
    with pytest.raises(DpapiSignerError, match="SIGNER_DOMAIN_REFUSED"):
        key_auth.sign(latest_message)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CurrentUser DPAPI is required")
def test_current_user_dpapi_blobs_work_for_separate_authority_roles(tmp_path: Path):
    import win32crypt

    cases = (
        ("latestness", "checkpoint_latestness_authority",
         b"ERP_MCP:S13:ANCHOR-LATESTNESS:v1\nprobe"),
        ("key-auth", "checkpoint_key_authority",
         b"ERP_MCP:S13:ANCHOR-KEY-AUTH:v1\nprobe"),
    )
    signers = {}
    for index, (label, role, message) in enumerate(cases):
        seed = bytes((index * 32 + offset) % 256 for offset in range(32))
        private_key = Ed25519PrivateKey.from_private_bytes(seed)
        protected = win32crypt.CryptProtectData(
            seed, "ERP_MCP synthetic S13 authority qualification", None, None, None, 0x1,
        )
        protected_path = (tmp_path / f"{label}.dpapi").resolve()
        protected_path.write_bytes(protected)
        signer = WindowsDpapiEd25519Signer(
            key_id=f"{label}-dpapi-test", key_version="synthetic-v1",
            signer_role=role,
            protected_seed_path=protected_path,
            expected_public_key=_raw_public(private_key),
        )
        signature = signer.sign(message)
        assert verify_ed25519(
            public_key=signer.public_key_bytes, message=message, signature=signature,
        )
        signers[label] = (signer, message)

    with pytest.raises(DpapiSignerError, match="SIGNER_DOMAIN_REFUSED"):
        signers["latestness"][0].sign(signers["key-auth"][1])
    with pytest.raises(DpapiSignerError, match="SIGNER_DOMAIN_REFUSED"):
        signers["key-auth"][0].sign(signers["latestness"][1])


async def _exercise_split_authorities(tmp_path: Path) -> None:
    latest_signer = _Signer(Ed25519PrivateKey.generate())
    key_signer = _Signer(Ed25519PrivateKey.generate())
    checkpoint_signer = Ed25519PrivateKey.generate()
    checkpoint_public = _raw_public(checkpoint_signer)
    assert latest_signer.public_key_bytes != key_signer.public_key_bytes
    config = _config(tmp_path, latest_signer, key_signer)
    app = create_app(config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        admin_headers = {
            "Authorization": f"Bearer {SERVICE_TOKEN}",
            "X-Anchor-Admin-Token": ADMIN_TOKEN,
        }
        registration = await http.post(
            "/v1/admin/keys/register",
            headers=admin_headers,
            json={
                "tenant_id": SCOPE.tenant_id,
                "company_id": SCOPE.company_id,
                "key_id": CHECKPOINT_KEY_ID,
                "public_key_hex": checkpoint_public.hex(),
                "role": "checkpoint_signer",
            },
        )
        assert registration.status_code == 201

        client = DevAnchorClient(
            base_url="http://127.0.0.1:8194",
            service_id=SERVICE_ID,
            service_token=SERVICE_TOKEN,
            latestness_authority_id=LATESTNESS_AUTHORITY_ID,
            latestness_public_key=latest_signer.public_key_bytes,
            key_authority_id=KEY_AUTHORITY_ID,
            key_authority_public_key=key_signer.public_key_bytes,
            http_client=http,
        )
        record = _record(checkpoint_signer)
        await client.write(record)
        assert await client.latest(SCOPE) == record
        assert await client.read_back(SCOPE, record.seq) == record

        latest_nonce = "1" * 64
        latestness = await client.attest_latest(SCOPE, record, latest_nonce)
        assert latestness is not None
        assert latestness.challenge_nonce == latest_nonce
        assert latestness.provider_id == SERVICE_ID
        assert latestness.authority_id == LATESTNESS_AUTHORITY_ID
        assert latestness.checkpoint_digest

        key_nonce = "2" * 64
        authorization = await client.authorize_checkpoint(SCOPE, record, key_nonce)
        assert authorization is not None
        assert authorization.challenge_nonce == key_nonce
        assert authorization.authority_id == KEY_AUTHORITY_ID
        assert authorization.basis is CheckpointKeyAuthorizationBasis.ACTIVE

        with pytest.raises(DevAnchorClientError, match="LATESTNESS_NONCE_REPLAY"):
            await client.attest_latest(SCOPE, record, latest_nonce)
        with pytest.raises(DevAnchorClientError, match="KEY_AUTH_NONCE_REPLAY"):
            await client.authorize_checkpoint(SCOPE, record, key_nonce)

        retired = await http.post(
            f"/v1/admin/keys/retire",
            headers=admin_headers,
            json={"tenant_id": SCOPE.tenant_id, "company_id": SCOPE.company_id,
                  "key_id": CHECKPOINT_KEY_ID},
        )
        assert retired.status_code == 201
        historical = await client.authorize_checkpoint(SCOPE, record, "3" * 64)
        assert historical is not None
        assert historical.basis is CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT
        assert historical.receipt_id
        assert historical.accepted_at is not None

        revoked = await http.post(
            "/v1/admin/keys/revoke",
            headers=admin_headers,
            json={"tenant_id": SCOPE.tenant_id, "company_id": SCOPE.company_id,
                  "key_id": CHECKPOINT_KEY_ID},
        )
        assert revoked.status_code == 201
        assert await client.authorize_checkpoint(SCOPE, record, "4" * 64) is None

        wrong_scope = Scope("synthetic-tenant-other", SCOPE.company_id)
        with pytest.raises(DevAnchorClientError, match="CHECKPOINT_SCOPE_INVALID"):
            await client.attest_latest(wrong_scope, record, "5" * 64)
        ready = await http.get(
            "/v1/ready", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )
        dispatch = await http.post(
            "/v1/dispatch", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )
        assert ready.json() == {"error": "ROUTE_NOT_FOUND"}
        assert dispatch.json() == {"error": "ROUTE_NOT_FOUND"}

