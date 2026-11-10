"""Focused S13-03 functional coverage for the separate dev-only anchor service.

These cases use a separate ASGI app, SQLite file, and ephemeral Ed25519 keys. They prove the
local service/client contract only; they do not establish production retention or host-admin
rollback resistance.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from business_ai_gateway.phase2.change_ledger.anchor_client import (
    DevAnchorClient,
    DevAnchorClientError,
)
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointKeyAuthorizationBasis,
    CheckpointRecord,
)
from business_ai_gateway.phase2.change_ledger.dev_anchor_service.service import (
    AnchorServiceError,
    DevAnchorConfig,
    SQLiteAnchorStore,
    _validate_config,
    create_app,
)
from business_ai_gateway.phase2.change_ledger.dev_anchor_service import service as anchor_service


class EphemeralSigner:
    """Independent test-only authority key; no private key is persisted."""

    def __init__(self) -> None:
        self._private = Ed25519PrivateKey.generate()
        self.public_key_bytes = self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign(self, message: bytes) -> bytes:
        return self._private.sign(message)


def public_key_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


class DevAnchorServiceFunctionalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="s13-anchor-")
        root = Path(self.temp.name).resolve()
        self.root = root
        self.database = root / "state" / "anchor.sqlite3"
        self.service_id = "test-anchor-service"
        self.bearer = "b" * 48
        self.admin = "a" * 48
        self.latest_signer = EphemeralSigner()
        self.key_signer = EphemeralSigner()
        self.checkpoint_key = Ed25519PrivateKey.generate()
        self.config = DevAnchorConfig(
            service_id=self.service_id,
            database_path=self.database,
            project_root=root / "repo",
            mode="dev",
            bind_host="127.0.0.1",
            bearer_token=self.bearer,
            admin_token=self.admin,
            latestness_authority_id="latestness-test-root",
            latestness_signer=self.latest_signer,
            key_authority_id="key-auth-test-root",
            key_authority_signer=self.key_signer,
        )
        self.app = create_app(self.config)
        transport = httpx.ASGITransport(app=self.app)
        self.http = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8194")
        self.client = DevAnchorClient(
            base_url="http://127.0.0.1:8194",
            service_id=self.service_id,
            service_token=self.bearer,
            latestness_authority_id="latestness-test-root",
            latestness_public_key=self.latest_signer.public_key_bytes,
            key_authority_id="key-auth-test-root",
            key_authority_public_key=self.key_signer.public_key_bytes,
            http_client=self.http,
        )

    async def asyncTearDown(self) -> None:
        await self.http.aclose()
        self.temp.cleanup()

    async def _register_key(self, *, key_id: str = "checkpoint-key-1",
                            private_key: Ed25519PrivateKey | None = None) -> Ed25519PrivateKey:
        private_key = private_key or self.checkpoint_key
        response = await self.http.post(
            "/v1/admin/keys/register",
            headers={"Authorization": f"Bearer {self.bearer}",
                     "x-anchor-admin-token": self.admin},
            json={
                "tenant_id": "tenant-a", "company_id": "company-a", "key_id": key_id,
                "public_key_hex": public_key_bytes(private_key).hex(),
                "role": "checkpoint_signer",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return private_key

    async def _register_response(self, *, key_id: str, private_key: Ed25519PrivateKey,
                                 bearer: str | None = None,
                                 admin: str | None = None) -> httpx.Response:
        return await self.http.post(
            "/v1/admin/keys/register",
            headers={"Authorization": f"Bearer {bearer or self.bearer}",
                     "x-anchor-admin-token": admin or self.admin},
            json={
                "tenant_id": "tenant-a", "company_id": "company-a", "key_id": key_id,
                "public_key_hex": public_key_bytes(private_key).hex(),
                "role": "checkpoint_signer",
            },
        )

    def _record(self, seq: int, private_key: Ed25519PrivateKey | None = None,
                *, key_id: str = "checkpoint-key-1") -> CheckpointRecord:
        private_key = private_key or self.checkpoint_key
        unsigned = CheckpointRecord(
            "tenant-a", "company-a", seq,
            hashlib.sha256(f"ledger-head-{seq}".encode()).hexdigest(),
            datetime(2026, 11, 10, 12, 0, seq, tzinfo=UTC),
            key_id, "", self.service_id, "TEST",
        )
        return CheckpointRecord(
            unsigned.tenant_id, unsigned.company_id, unsigned.seq, unsigned.head_hash,
            unsigned.signed_at, unsigned.key_id,
            private_key.sign(unsigned.signing_payload()).hex(), unsigned.sink_id,
            unsigned.sink_kind,
        )

    async def _admin_action(self, path: str, key_id: str) -> httpx.Response:
        return await self.http.post(
            path,
            headers={"Authorization": f"Bearer {self.bearer}",
                     "x-anchor-admin-token": self.admin},
            json={"tenant_id": "tenant-a", "company_id": "company-a", "key_id": key_id},
        )

    async def test_checkpoint_round_trip_is_monotonic_idempotent_and_scope_bound(self):
        await self._register_key()
        scope = Scope("tenant-a", "company-a")
        record1 = self._record(1)
        await self.client.write(record1)
        await self.client.write(record1)  # exact replay is idempotent

        self.assertEqual(await self.client.latest(scope), record1)
        self.assertEqual(await self.client.read_back(scope, 1), record1)
        other_scope = Scope("tenant-b", "company-a")
        self.assertIsNone(await self.client.latest(other_scope))

        conflicting = CheckpointRecord(
            record1.tenant_id, record1.company_id, record1.seq, "f" * 64,
            record1.signed_at, record1.key_id,
            self.checkpoint_key.sign(CheckpointRecord(
                record1.tenant_id, record1.company_id, record1.seq, "f" * 64,
                record1.signed_at, record1.key_id, "", record1.sink_id, record1.sink_kind,
            ).signing_payload()).hex(), record1.sink_id, record1.sink_kind,
        )
        conflict = await self.http.post(
            "/v1/checkpoints", headers={"Authorization": f"Bearer {self.bearer}"},
            json={"record": {
                "tenant_id": conflicting.tenant_id, "company_id": conflicting.company_id,
                "seq": conflicting.seq, "head_hash": conflicting.head_hash,
                "signed_at": conflicting.signed_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "key_id": conflicting.key_id, "signature": conflicting.signature,
                "sink_id": conflicting.sink_id, "sink_kind": conflicting.sink_kind,
            }},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json().get("error"), "CHECKPOINT_CONFLICT")

        record3 = self._record(3)
        await self.client.write(record3)
        restarted_store = SQLiteAnchorStore(
            self.database, self.service_id,
            latestness_signer=self.latest_signer,
            key_authority_signer=self.key_signer,
        )
        self.assertEqual(restarted_store.latest_checkpoint("tenant-a", "company-a")["seq"], 3)
        rollback = await self.http.post(
            "/v1/checkpoints", headers={"Authorization": f"Bearer {self.bearer}"},
            json={"record": {
                "tenant_id": record1.tenant_id, "company_id": record1.company_id,
                "seq": 2, "head_hash": hashlib.sha256(b"head-2").hexdigest(),
                "signed_at": record1.signed_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "key_id": record1.key_id,
                "signature": self.checkpoint_key.sign(CheckpointRecord(
                    record1.tenant_id, record1.company_id, 2,
                    hashlib.sha256(b"head-2").hexdigest(), record1.signed_at,
                    record1.key_id, "", record1.sink_id, record1.sink_kind,
                ).signing_payload()).hex(),
                "sink_id": record1.sink_id, "sink_kind": record1.sink_kind,
            }},
        )
        self.assertEqual(rollback.status_code, 409)
        self.assertEqual(rollback.json().get("error"), "CHECKPOINT_ROLLBACK")

    async def test_service_auth_and_admin_mutations_require_distinct_tokens(self):
        body = {"tenant_id": "tenant-a", "company_id": "company-a",
                "key_id": "checkpoint-key-1",
                "public_key_hex": public_key_bytes(self.checkpoint_key).hex(),
                "role": "checkpoint_signer"}
        unauthenticated = await self.http.post("/v1/admin/keys/register", json=body)
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(unauthenticated.json().get("error"), "AUTH_FAILED")

        without_admin = await self.http.post(
            "/v1/admin/keys/register", headers={"Authorization": f"Bearer {self.bearer}"},
            json=body,
        )
        self.assertEqual(without_admin.status_code, 401)
        self.assertEqual(without_admin.json().get("error"), "AUTH_FAILED")

        await self._register_key()
        record = self._record(1)
        await self.client.write(record)
        with self.assertRaises(DevAnchorClientError) as caught:
            await self.client.write(self._record(0))
        self.assertEqual(caught.exception.code, "CHECKPOINT_INVALID")

    async def test_health_is_liveness_only_and_does_not_claim_storage_readiness(self):
        store = self.app.state.dev_anchor_store
        with patch.object(store, "latest_checkpoint", side_effect=AssertionError("health read storage")):
            response = await self.http.get(
                "/v1/health", headers={"Authorization": f"Bearer {self.bearer}"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body, {
            "service_id": self.service_id, "mode": "dev", "sink_kind": "TEST",
        })
        self.assertNotIn("ready", body)
        self.assertNotIn("database", body)

    async def test_history_projection_handles_reads_and_appends_without_full_replay(self):
        await self._register_key()
        first = self._record(1)
        await self.client.write(first)
        scope = Scope(first.tenant_id, first.company_id)
        store = self.app.state.dev_anchor_store

        # The constructor has already verified and projected the signed history. Requests must
        # use cached/indexed state plus a database-head check; they must not replay the log.
        with patch.object(store, "_replay", side_effect=AssertionError("request replayed history")):
            self.assertEqual(await self.client.latest(scope), first)
            self.assertEqual(await self.client.read_back(scope, 1), first)
            second = self._record(2)
            await self.client.write(second)
            self.assertEqual(await self.client.latest(scope), second)
            latestness = await self.client.attest_latest(scope, second, "6" * 64)
            self.assertEqual(latestness.checkpoint_digest,
                             hashlib.sha256(
                                 b"change-ledger-checkpoint-identity|v1\0"
                                 + second.signing_payload() + b"\0"
                                 + second.signature.encode("ascii")
                             ).hexdigest())
            authorization = await self.client.authorize_checkpoint(scope, second, "7" * 64)
            self.assertIsNotNone(authorization)

    async def test_history_event_cap_is_100k_and_excess_history_fails_closed_at_startup(self):
        self.assertEqual(anchor_service._MAX_EVENTS, 100_000)
        await self._register_key()
        await self.client.write(self._record(1))
        with patch.object(anchor_service, "_MAX_EVENTS", 1):
            with self.assertRaises(AnchorServiceError) as caught:
                SQLiteAnchorStore(
                    self.database, self.service_id,
                    latestness_signer=self.latest_signer,
                    key_authority_signer=self.key_signer,
                )
        self.assertEqual(caught.exception.code, "ANCHOR_HISTORY_LIMIT")

    async def test_post_commit_projection_failure_poison_cache_without_rollback_error(self):
        await self._register_key()
        store = self.app.state.dev_anchor_store
        record = self._record(1)
        with patch.object(store, "_apply_committed_event",
                          side_effect=RuntimeError("injected projection failure")):
            with self.assertRaises(DevAnchorClientError) as caught:
                await self.client.write(record)
        self.assertEqual(caught.exception.code, "ANCHOR_HISTORY_CHANGED")

        connection = sqlite3.connect(self.database)
        try:
            committed = connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='CHECKPOINT_ACCEPTED'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(committed, 1)

        scope = Scope(record.tenant_id, record.company_id)
        with self.assertRaises(DevAnchorClientError) as caught:
            await self.client.latest(scope)
        self.assertEqual(caught.exception.code, "ANCHOR_HISTORY_CHANGED")

    async def test_key_registration_is_idempotent_for_same_key_and_rejects_conflict(self):
        first = await self._register_response(
            key_id="stable-key", private_key=self.checkpoint_key,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json(), {"accepted": True, "changed": True})

        duplicate = await self._register_response(
            key_id="stable-key", private_key=self.checkpoint_key,
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json(), {"accepted": True, "changed": False})

        conflict = await self._register_response(
            key_id="stable-key", private_key=Ed25519PrivateKey.generate(),
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json().get("error"), "KEY_ALREADY_REGISTERED")

    async def test_latestness_and_key_authorization_are_signed_and_nonce_bound(self):
        await self._register_key()
        record = self._record(1)
        await self.client.write(record)
        scope = Scope(record.tenant_id, record.company_id)
        latest = await self.client.latest(scope)
        self.assertEqual(latest, record)

        latestness_nonce = "1" * 64
        latestness = await self.client.attest_latest(scope, record, latestness_nonce)
        self.assertEqual(latestness.challenge_nonce, latestness_nonce)
        self.assertEqual(latestness.provider_id, self.service_id)
        self.assertGreaterEqual(latestness.provider_revision, 1)

        # The proof digest hashes the exact authority-domain preimage without proof_digest;
        # the detached Ed25519 signature covers the complete evidence including proof_digest.
        response = await self.http.post(
            "/v1/latestness", headers={"Authorization": f"Bearer {self.bearer}"},
            json={"tenant_id": record.tenant_id, "company_id": record.company_id,
                  "checkpoint_digest": hashlib.sha256(
                      b"change-ledger-checkpoint-identity|v1\0" + record.signing_payload()
                      + b"\0" + record.signature.encode("ascii")
                  ).hexdigest(), "challenge_nonce": "2" * 64},
        )
        self.assertEqual(response.status_code, 200, response.text)
        envelope = response.json()
        evidence = envelope["evidence"]
        unsigned_evidence = {key: value for key, value in evidence.items()
                             if key != "proof_digest"}
        proof_preimage = b"ERP_MCP:S13:ANCHOR-LATESTNESS:v1\n" + json.dumps(
            unsigned_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        expected_proof = hashlib.sha256(proof_preimage).hexdigest()
        self.assertEqual(evidence["proof_digest"], expected_proof)
        Ed25519PublicKey.from_public_bytes(self.latest_signer.public_key_bytes).verify(
            bytes.fromhex(envelope["signature"]),
            b"ERP_MCP:S13:ANCHOR-LATESTNESS:v1\n" + json.dumps(
                evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
        )

        replay = await self.http.post(
            "/v1/latestness", headers={"Authorization": f"Bearer {self.bearer}"},
            json={"tenant_id": record.tenant_id, "company_id": record.company_id,
                  "checkpoint_digest": evidence["checkpoint_digest"],
                  "challenge_nonce": latestness_nonce},
        )
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json().get("error"), "LATESTNESS_NONCE_REPLAY")

        key_nonce = "3" * 64
        authorization = await self.client.authorize_checkpoint(scope, record, key_nonce)
        self.assertIsNotNone(authorization)
        assert authorization is not None
        self.assertEqual(authorization.challenge_nonce, key_nonce)
        self.assertIs(authorization.basis, CheckpointKeyAuthorizationBasis.ACTIVE)

        key_replay = await self.http.post(
            "/v1/key-authorizations", headers={"Authorization": f"Bearer {self.bearer}"},
            json={"record": {
                "tenant_id": record.tenant_id, "company_id": record.company_id,
                "seq": record.seq, "head_hash": record.head_hash,
                "signed_at": record.signed_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "key_id": record.key_id, "signature": record.signature,
                "sink_id": record.sink_id, "sink_kind": record.sink_kind,
            }, "challenge_nonce": key_nonce},
        )
        self.assertEqual(key_replay.status_code, 409)
        self.assertEqual(key_replay.json().get("error"), "KEY_AUTH_NONCE_REPLAY")

    async def test_key_retirement_preserves_only_prior_checkpoint_and_compromise_revokes_all(self):
        await self._register_key(key_id="routine-key")
        routine_record = self._record(1, key_id="routine-key")
        await self.client.write(routine_record)
        retired = await self._admin_action("/v1/admin/keys/retire", "routine-key")
        self.assertEqual(retired.status_code, 201)
        self.assertEqual(retired.json(), {"accepted": True, "changed": True})
        retired_again = await self._admin_action("/v1/admin/keys/retire", "routine-key")
        self.assertEqual(retired_again.status_code, 200)
        self.assertEqual(retired_again.json(), {"accepted": True, "changed": False})

        scope = Scope(routine_record.tenant_id, routine_record.company_id)
        auth = await self.client.authorize_checkpoint(scope, routine_record, "4" * 64)
        self.assertIsNotNone(auth)
        assert auth is not None
        self.assertIs(auth.basis, CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT)
        self.assertTrue(auth.receipt_id)
        self.assertIsNotNone(auth.accepted_at)

        later = self._record(2, key_id="routine-key")
        with self.assertRaises(DevAnchorClientError) as caught:
            await self.client.write(later)
        self.assertEqual(caught.exception.code, "CHECKPOINT_KEY_NOT_ACTIVE")

        revoked_private = Ed25519PrivateKey.generate()
        await self._register_key(key_id="compromised-key", private_key=revoked_private)
        compromised_record = self._record(3, revoked_private, key_id="compromised-key")
        await self.client.write(compromised_record)
        revoked = await self._admin_action("/v1/admin/keys/revoke", "compromised-key")
        self.assertEqual(revoked.status_code, 201)
        self.assertEqual(revoked.json(), {"accepted": True, "changed": True})
        revoked_again = await self._admin_action("/v1/admin/keys/revoke", "compromised-key")
        self.assertEqual(revoked_again.status_code, 200)
        self.assertEqual(revoked_again.json(), {"accepted": True, "changed": False})
        denied = await self.client.authorize_checkpoint(scope, compromised_record, "5" * 64)
        self.assertIsNone(denied)

    async def test_sqlite_history_tampering_fails_closed_on_reopen(self):
        await self._register_key()
        await self.client.write(self._record(1))
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("DROP TRIGGER events_no_update")
            connection.execute(
                "UPDATE events SET payload_json=? WHERE revision=1",
                (json.dumps({"tampered": True}),),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(AnchorServiceError) as caught:
            SQLiteAnchorStore(
                self.database, self.service_id,
                latestness_signer=self.latest_signer,
                key_authority_signer=self.key_signer,
            )
        self.assertEqual(caught.exception.code, "ANCHOR_HISTORY_CORRUPT")

    async def test_service_requires_dev_loopback_outside_repository_and_separate_authority_roots(self):
        with self.assertRaises(AnchorServiceError) as caught:
            _validate_config(replace(self.config, mode="production"))
        self.assertEqual(caught.exception.code, "DEV_ONLY_REQUIRED")

        with self.assertRaises(AnchorServiceError) as caught:
            _validate_config(replace(self.config, bind_host="0.0.0.0"))
        self.assertEqual(caught.exception.code, "LOOPBACK_ONLY")

        with self.assertRaises(AnchorServiceError) as caught:
            _validate_config(replace(
                self.config, database_path=self.config.project_root / "anchor.sqlite3",
            ))
        self.assertEqual(caught.exception.code, "ANCHOR_STATE_MUST_BE_OUTSIDE_REPOSITORY")

        with self.assertRaises(AnchorServiceError) as caught:
            _validate_config(replace(self.config, key_authority_signer=self.latest_signer))
        self.assertEqual(caught.exception.code, "ANCHOR_AUTHORITY_KEYS_MUST_BE_DISTINCT")


if __name__ == "__main__":
    unittest.main()
