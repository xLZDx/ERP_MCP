"""Functional acceptance for the S13-03 dev-only signed anchor service.

Run: .venv/Scripts/python.exe -m pytest -q tests/phase2/test_s13_dev_anchor_service.py
These tests prove bounded synthetic TEST behavior only; they do not qualify production trust.
"""
from __future__ import annotations

import base64
import asyncio
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import time

import pytest
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    Ed25519SignatureVerifier,
    checkpoint_identity,
)
from business_ai_gateway.phase2.change_ledger import dev_anchor_service as anchor


TOKEN = "dev-anchor-test-token-" + "x" * 40
SCOPE = Scope("tenant-s13-test", "company-s13-test")
OTHER_SCOPE = Scope("tenant-other", "company-other")
LATEST_AUTHORITY_PRIVATE = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"ERP_MCP S13 synthetic latestness test authority").digest(),
)
KEY_AUTHORITY_PRIVATE = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"ERP_MCP S13 synthetic key authorization test authority").digest(),
)
LATEST_AUTHORITY_ID = "latest-test-v1"
KEY_AUTHORITY_ID = "key-auth-test-v1"


def _raw_public(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


@pytest.fixture
def keys():
    authority = Ed25519PrivateKey.generate()
    checkpoint = Ed25519PrivateKey.generate()
    denied = Ed25519PrivateKey.generate()
    verifier = Ed25519SignatureVerifier({
        "checkpoint-v1": _raw_public(checkpoint),
        "denied-v1": _raw_public(denied),
    })
    return authority, checkpoint, denied, verifier


@pytest.fixture
def configure(monkeypatch, tmp_path, keys):
    authority, checkpoint, _denied, _verifier = keys
    checkpoint_entry = {
        "tenant_id": SCOPE.tenant_id,
        "company_id": SCOPE.company_id,
        "key_id": "checkpoint-v1",
        "public_key_b64": _b64(_raw_public(checkpoint)),
    }

    def set_config(*, enabled="1", registry=None, database=None, token=TOKEN):
        database_path = Path(database or (tmp_path / "anchor.sqlite3"))
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_ENABLED", enabled)
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_DB", str(database_path))
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_TOKEN", token)
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_KEY_ID", "authority-test-v1")
        authority_private = authority.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_PRIVATE_KEY_B64", _b64(authority_private))
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_PUBLIC_KEY_B64", _b64(_raw_public(authority)))
        # The service now requires separate TEST keys for provider-latestness and
        # historical-key authorization. Keep both roles distinct from each other and
        # from the checkpoint signer configured below.
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_LATEST_KEY_ID", LATEST_AUTHORITY_ID)
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_KEY_AUTH_KEY_ID", KEY_AUTHORITY_ID)
        for role, private_key in (
            ("LATEST", LATEST_AUTHORITY_PRIVATE),
            ("KEY_AUTH", KEY_AUTHORITY_PRIVATE),
        ):
            private_raw = private_key.private_bytes(
                serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            monkeypatch.setenv(f"ERP_MCP_DEV_ANCHOR_{role}_PRIVATE_KEY_B64", _b64(private_raw))
            monkeypatch.setenv(
                f"ERP_MCP_DEV_ANCHOR_{role}_PUBLIC_KEY_B64", _b64(_raw_public(private_key)),
            )
        monkeypatch.setenv("ERP_MCP_DEV_ANCHOR_CHECKPOINT_KEYS_JSON",
                           json.dumps(registry if registry is not None else [checkpoint_entry]))
        return database_path

    set_config()
    return set_config


def _signed_record(private_key: Ed25519PrivateKey, *, scope=SCOPE, seq=1,
                   key_id="checkpoint-v1", head_byte="a") -> CheckpointRecord:
    record = CheckpointRecord(
        tenant_id=scope.tenant_id, company_id=scope.company_id, seq=seq,
        head_hash=head_byte * 64, signed_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
        key_id=key_id, signature="0" * 128, sink_id=anchor._SERVICE_ID,
        sink_kind="TEST",
    )
    return CheckpointRecord(
        **{**record.__dict__, "signature": private_key.sign(record.signing_payload()).hex()}
    )


def _retired_key_entry(private_key: Ed25519PrivateKey, *, accepted_through_seq=2,
                       accepted_at="2026-11-10T00:00:00+00:00", receipt_id="test-retirement-receipt"):
    return {
        "tenant_id": SCOPE.tenant_id,
        "company_id": SCOPE.company_id,
        "key_id": "checkpoint-v1",
        "public_key_b64": _b64(_raw_public(private_key)),
        "basis": "ROUTINE_RETIREMENT_RECEIPT",
        "receipt_id": receipt_id,
        "accepted_at": accepted_at,
        "accepted_through_seq": accepted_through_seq,
    }


def _headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _client(verifier, base_url="http://127.0.0.1:21831"):
    return anchor.DevHttpCheckpointSink(
        base_url, bearer_token=TOKEN, expected_key_id=LATEST_AUTHORITY_ID,
        authority_public_key_b64=_b64(_raw_public(LATEST_AUTHORITY_PRIVATE)),
        expected_key_authorization_id=KEY_AUTHORITY_ID,
        key_authorization_public_key_b64=_b64(_raw_public(KEY_AUTHORITY_PRIVATE)),
        checkpoint_verifier=verifier,
    )


def _put(client, record):
    return client.put("/v1/checkpoints", headers=_headers(),
                      json={"record": anchor._record_dict(record)})


def _bridge_to_test_server(monkeypatch, server):
    def bridge(method, url, **kwargs):
        path = url.removeprefix("http://127.0.0.1:21831")
        return server.request(method, path, json=kwargs.get("json"),
                              headers=kwargs.get("headers"))
    monkeypatch.setattr(anchor.httpx, "request", bridge)


def _resign_latest_response(authority, response, **changes):
    body = response.json()
    proof = body["proof"]
    proof.update(changes)
    signed_fields = {key: value for key, value in proof.items() if key != "signature"}
    canonical = json.dumps(
        signed_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    proof["signature"] = authority.sign(anchor._PROOF_DOMAIN + canonical).hex()
    return anchor.httpx.Response(response.status_code, json=body)


def test_s13_03_dev_service_requires_explicit_enable_loopback_and_bearer_auth(configure):
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as client:
        configure(enabled="0")
        assert client.get("/health").status_code == 503
        configure()
        assert client.get("/health").status_code == 204
        assert client.post("/v1/checkpoints/latest", json={}).status_code == 401
    with TestClient(anchor.app, client=("10.0.0.9", 1234)) as remote_client:
        assert remote_client.get("/health").status_code == 403
        assert remote_client.put("/v1/checkpoints", headers=_headers(), json={}).json() == {
            "error": "LOOPBACK_ONLY",
        }
    with pytest.raises(anchor.DevAnchorError, match="CLIENT_CONFIGURATION_INVALID"):
        anchor.DevHttpCheckpointSink(
            "http://example.com", bearer_token=TOKEN, expected_key_id="authority-test-v1",
            authority_public_key_b64="", expected_key_authorization_id=KEY_AUTHORITY_ID,
            key_authorization_public_key_b64="", checkpoint_verifier=object(),
        )


@pytest.mark.asyncio
async def test_first_store_initialization_does_not_block_asgi_event_loop(configure, monkeypatch):
    original_init = anchor._SQLiteAnchorStore.__init__

    for endpoint, method, payload in (
        ("/health", "get", None),
        ("/v1/checkpoints/read-back", "post", {
            "tenant_id": SCOPE.tenant_id, "company_id": SCOPE.company_id, "seq": 1,
        }),
    ):
        configure(database=str(Path(configure()) / f"{method}-{endpoint.rsplit('/', 1)[-1]}.db"))
        anchor._store_for.cache_clear()
        initialization_started = threading.Event()
        initialization_finished = threading.Event()

        def slow_initialization(self, database):
            initialization_started.set()
            time.sleep(0.15)
            try:
                original_init(self, database)
            finally:
                initialization_finished.set()

        monkeypatch.setattr(anchor._SQLiteAnchorStore, "__init__", slow_initialization)

        async def event_loop_remains_responsive():
            while not initialization_started.is_set():
                await asyncio.sleep(0.001)
            await asyncio.sleep(0.025)
            return not initialization_finished.is_set()

        transport = httpx.ASGITransport(app=anchor.app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            request = getattr(client, method)
            kwargs = {} if payload is None else {"json": payload, "headers": _headers()}
            response, stayed_responsive = await asyncio.gather(
                request(endpoint, **kwargs), event_loop_remains_responsive(),
            )

        assert response.status_code == (204 if endpoint == "/health" else 200)
        if payload is not None:
            assert response.json() == {"record": None}
        assert stayed_responsive, f"ASGI event loop blocked during {endpoint} store initialization"


def test_s13_03_checkpoint_signatures_are_exactly_scope_bound_and_unknown_keys_fail_closed(configure, keys):
    _authority, checkpoint, denied, _verifier = keys
    record = _signed_record(checkpoint)
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as client:
        assert _put(client, record).status_code == 200
        foreign = _signed_record(checkpoint, scope=OTHER_SCOPE, seq=1, head_byte="b")
        assert _put(client, foreign).json() == {"error": "CHECKPOINT_INVALID"}
        unknown = _signed_record(denied, seq=2, key_id="denied-v1", head_byte="c")
        assert _put(client, unknown).json() == {"error": "CHECKPOINT_INVALID"}
        mutated = CheckpointRecord(**{**record.__dict__, "head_hash": "d" * 64})
        assert _put(client, mutated).json() == {"error": "CHECKPOINT_INVALID"}
        read_back = client.post("/v1/checkpoints/read-back", headers=_headers(), json={
            "tenant_id": SCOPE.tenant_id, "company_id": SCOPE.company_id, "seq": 1,
        })
        assert read_back.json() == {"record": anchor._record_dict(record)}


def test_s13_03_append_is_idempotent_monotonic_conflict_safe_and_append_only(configure, keys):
    _authority, checkpoint, _denied, _verifier = keys
    first = _signed_record(checkpoint, seq=1)
    different_same_seq = _signed_record(checkpoint, seq=1, head_byte="b")
    second = _signed_record(checkpoint, seq=3, head_byte="c")
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as client:
        assert _put(client, first).json() == {"stored": True}
        assert _put(client, first).json() == {"stored": True}
        conflict = _put(client, different_same_seq)
        assert conflict.status_code == 409
        assert conflict.json() == {"error": "CHECKPOINT_CONFLICT"}
        assert _put(client, second).json() == {"stored": True}
        rollback = _put(client, _signed_record(checkpoint, seq=2, head_byte="d"))
        assert rollback.status_code == 409
        assert rollback.json() == {"error": "CHECKPOINT_ROLLBACK"}
        latest = client.post("/v1/checkpoints/latest", headers=_headers(), json={
            "tenant_id": SCOPE.tenant_id, "company_id": SCOPE.company_id, "nonce": "f" * 64,
        }).json()
        assert latest["record"] == anchor._record_dict(second)
        assert latest["proof"]["revision"] == 2
        with sqlite3.connect(configure()) as connection:
            with pytest.raises(sqlite3.IntegrityError, match="APPEND_ONLY"):
                connection.execute("UPDATE anchor_events SET seq=99 WHERE seq=1")
            with pytest.raises(sqlite3.IntegrityError, match="APPEND_ONLY"):
                connection.execute("DELETE FROM anchor_events WHERE seq=1")


@pytest.mark.asyncio
async def test_s13_03_latest_proof_is_nonce_bound_and_client_rejects_replayed_proof(configure, keys, monkeypatch):
    authority, checkpoint, _denied, verifier = keys
    record = _signed_record(checkpoint)
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        assert _put(server, record).status_code == 200
        client = _client(verifier)
        captured = []
        def bridge(method, url, **kwargs):
            response = server.request(method, url.removeprefix("http://127.0.0.1:21831"),
                                      json=kwargs.get("json"),
                                      headers=kwargs.get("headers"))
            captured.append(response)
            return response
        monkeypatch.setattr(anchor.httpx, "request", bridge)
        latest_record, latestness = await client.latest_checkpoint(SCOPE)
        assert latest_record == record
        assert (latestness.tenant_id, latestness.company_id) == (
            SCOPE.tenant_id, SCOPE.company_id,
        )
        assert latestness.checkpoint_digest
        assert latestness.authority_id == LATEST_AUTHORITY_ID
        assert latestness.authority_revision == 1
        assert latestness.authority_event_id and latestness.authority_event_digest
        replay = captured[-1]
        monkeypatch.setattr(anchor.httpx, "request", lambda *args, **kwargs: replay)
        with pytest.raises(anchor.DevAnchorError, match="LATEST_PROOF_INVALID"):
            await client.latest(SCOPE)


@pytest.mark.asyncio
async def test_s13_03_latest_proof_recomputes_signed_event_digest(configure, keys, monkeypatch):
    """An authority signature cannot make an event digest that omits the checkpoint valid."""
    authority, checkpoint, _denied, verifier = keys
    record = _signed_record(checkpoint)
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        assert _put(server, record).status_code == 200
        client = _client(verifier)

        def signed_inconsistent_proof(method, url, **kwargs):
            response = server.request(
                method, url.removeprefix("http://127.0.0.1:21831"),
                json=kwargs.get("json"), headers=kwargs.get("headers"),
            )
            if url.endswith("/v1/checkpoints/latest"):
                return _resign_latest_response(
                    LATEST_AUTHORITY_PRIVATE, response, event_digest="f" * 64,
                )
            return response

        monkeypatch.setattr(anchor.httpx, "request", signed_inconsistent_proof)
        with pytest.raises(anchor.DevAnchorError, match="LATEST_PROOF_INVALID"):
            await client.latest_checkpoint(SCOPE)

        _bridge_to_test_server(monkeypatch, server)
        latest_record, evidence = await client.latest_checkpoint(SCOPE)
        assert latest_record == record
        assert evidence.authority_revision == 1


@pytest.mark.asyncio
async def test_s13_03_current_authority_adapter_binds_nonce_and_refuses_mismatches(
        configure, keys, monkeypatch):
    """The compatibility adapter emits current evidence only for the exact retained record."""
    _authority, checkpoint, _denied, verifier = keys
    record = _signed_record(checkpoint)
    mismatched_record = _signed_record(checkpoint, seq=2, head_byte="b")
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        assert _put(server, record).status_code == 200
        client = _client(verifier)
        _bridge_to_test_server(monkeypatch, server)

        latest_nonce = hashlib.sha256(b"latestness challenge A").hexdigest()
        latestness = await client.attest_latest(SCOPE, record, latest_nonce)
        assert latestness is not None
        assert latestness.challenge_nonce == latest_nonce
        assert latestness.provider_id == client.sink_id
        assert latestness.checkpoint_digest == checkpoint_identity(record)
        assert await client.attest_latest(SCOPE, mismatched_record, latest_nonce) is None

        key_nonce = hashlib.sha256(b"key authorization challenge B").hexdigest()
        authorization = await client.authorize_checkpoint(SCOPE, record, key_nonce)
        assert authorization is not None
        assert authorization.challenge_nonce == key_nonce
        assert authorization.checkpoint_digest == checkpoint_identity(record)
        assert await client.authorize_checkpoint(SCOPE, mismatched_record, key_nonce) is None

        foreign_scope = Scope("tenant-foreign", SCOPE.company_id)
        with pytest.raises(anchor.DevAnchorError):
            await client.attest_latest(foreign_scope, record, latest_nonce)


@pytest.mark.asyncio
async def test_s13_03_empty_latest_proof_binds_zero_head_and_no_predecessor(
        configure, keys, monkeypatch):
    """The authenticated empty-head form is exact and rejects signed non-empty metadata."""
    authority, _checkpoint, _denied, verifier = keys
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        client = _client(verifier)
        _bridge_to_test_server(monkeypatch, server)
        record, evidence = await client.latest_checkpoint(SCOPE)
        assert record is None
        assert evidence.authority_revision == 0
        assert evidence.authority_event_id is None
        assert evidence.authority_event_digest is None

        def signed_nonempty_metadata(method, url, **kwargs):
            response = server.request(
                method, url.removeprefix("http://127.0.0.1:21831"),
                json=kwargs.get("json"), headers=kwargs.get("headers"),
            )
            if url.endswith("/v1/checkpoints/latest"):
                return _resign_latest_response(LATEST_AUTHORITY_PRIVATE, response, seq=1,
                                              previous_digest="a" * 64)
            return response

        monkeypatch.setattr(anchor.httpx, "request", signed_nonempty_metadata)
        with pytest.raises(anchor.DevAnchorError, match="LATEST_PROOF_INVALID"):
            await client.latest_checkpoint(SCOPE)


@pytest.mark.asyncio
async def test_s13_03_static_active_key_authorization_is_scoped_and_unregistered_key_is_denied(configure, keys, monkeypatch):
    authority, checkpoint, denied, verifier = keys
    registered = _signed_record(checkpoint)
    never_stored = _signed_record(checkpoint, seq=2, head_byte="b")
    unregistered = _signed_record(denied, key_id="denied-v1")
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        client = _client(verifier)
        _bridge_to_test_server(monkeypatch, server)
        assert _put(server, registered).status_code == 200
        authorization = await client.authorize_checkpoint(SCOPE, registered)
        assert authorization is not None
        assert authorization.basis.value == "ACTIVE"
        assert authorization.authority_revision == 1
        assert authorization.policy_version == "dev-static-key-registry-v1"
        assert authorization.receipt_id is None
        assert await client.authorize_checkpoint(SCOPE, never_stored) is None
        assert await client.authorize_checkpoint(SCOPE, unregistered) is None
        assert anchor.DevHttpCheckpointSink.kind == "TEST"
        assert anchor.DevHttpCheckpointSink.is_test_double is True


@pytest.mark.asyncio
async def test_s13_03_retired_checkpoint_requires_receipt_cutoff_and_cannot_write(configure, keys, monkeypatch):
    authority, checkpoint, _denied, verifier = keys
    first = _signed_record(checkpoint, seq=1, head_byte="a")
    cutoff = _signed_record(checkpoint, seq=2, head_byte="b")
    beyond_cutoff = _signed_record(checkpoint, seq=3, head_byte="c")
    after_retirement = _signed_record(checkpoint, seq=4, head_byte="d")
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        assert _put(server, first).status_code == 200
        assert _put(server, cutoff).status_code == 200
        assert _put(server, beyond_cutoff).status_code == 200

        retired_entry = _retired_key_entry(checkpoint, accepted_through_seq=2)
        configure(registry=[retired_entry])
        client = _client(verifier)
        _bridge_to_test_server(monkeypatch, server)

        accepted = await client.authorize_checkpoint(SCOPE, cutoff)
        assert accepted is not None
        assert accepted.basis.value == "ROUTINE_RETIREMENT_RECEIPT"
        assert accepted.receipt_id == "test-retirement-receipt"
        assert accepted.accepted_at.isoformat() == "2026-11-10T00:00:00+00:00"
        assert await client.authorize_checkpoint(SCOPE, beyond_cutoff) is None

        refused_write = _put(server, after_retirement)
        assert refused_write.status_code == 400
        assert refused_write.json() == {"error": "CHECKPOINT_INVALID"}


@pytest.mark.parametrize("mutate", [
    lambda entry: entry.update(basis="ACTIVE"),
    lambda entry: entry.update(receipt_id="  "),
    lambda entry: entry.update(accepted_at="2026-11-10T00:00:00"),
    lambda entry: entry.update(accepted_at="not-a-time"),
    lambda entry: entry.update(accepted_through_seq=True),
    lambda entry: entry.update(accepted_through_seq=0),
    lambda entry: entry.pop("accepted_through_seq"),
])
def test_s13_03_malformed_retirement_registry_fails_closed(configure, keys, mutate):
    _authority, checkpoint, _denied, _verifier = keys
    entry = _retired_key_entry(checkpoint)
    mutate(entry)
    encoded = json.dumps([entry])
    with pytest.raises(anchor.DevAnchorError, match="CHECKPOINT_KEY_REGISTRY_INVALID"):
        anchor._checkpoint_public_keys(encoded)


@pytest.mark.asyncio
async def test_s13_03_malformed_retirement_authority_proof_fails_closed(configure, keys, monkeypatch):
    authority, _checkpoint, _denied, verifier = keys
    client = _client(verifier)

    class MalformedResponse:
        is_error = False

        @staticmethod
        def json():
            return {"authorization": {"basis": "ROUTINE_RETIREMENT_RECEIPT",
                                      "receipt_id": "test-retirement-receipt"}}

    monkeypatch.setattr(anchor.httpx, "request", lambda *args, **kwargs: MalformedResponse())
    with pytest.raises(anchor.DevAnchorError, match="SERVICE_RESPONSE_INVALID"):
        await client.authorize_checkpoint(SCOPE, _signed_record(_checkpoint))


@pytest.mark.asyncio
async def test_s13_03_corrupt_exact_checkpoint_json_is_classified_as_store_integrity_failure(
        configure, keys, monkeypatch):
    authority, checkpoint, _denied, verifier = keys
    database = configure()
    record = _signed_record(checkpoint)
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        assert _put(server, record).status_code == 200
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER anchor_events_no_update")
            connection.execute(
                "UPDATE anchor_events SET checkpoint_json=? WHERE seq=?",
                ("{malformed-json", record.seq),
            )
        client = _client(verifier)
        _bridge_to_test_server(monkeypatch, server)
        with pytest.raises(anchor.DevAnchorError, match="STORE_INTEGRITY_FAILURE"):
            await client.read_back(SCOPE, record.seq)


@pytest.mark.asyncio
async def test_s13_03_corrupt_bounded_history_is_classified_as_store_integrity_failure(
        configure, keys, monkeypatch):
    authority, checkpoint, _denied, verifier = keys
    database = configure()
    record = _signed_record(checkpoint)
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as server:
        assert _put(server, record).status_code == 200
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER anchor_events_no_update")
            connection.execute(
                "UPDATE anchor_events SET event_digest=? WHERE seq=?",
                ("not-a-valid-event-digest", record.seq),
            )
        client = _client(verifier)
        _bridge_to_test_server(monkeypatch, server)
        with pytest.raises(anchor.DevAnchorError, match="STORE_INTEGRITY_FAILURE"):
            await client.latest_checkpoint(SCOPE)


@pytest.mark.asyncio
async def test_s13_03_client_rejects_malformed_success_response(configure, keys, monkeypatch):
    authority, _checkpoint, _denied, verifier = keys
    client = _client(verifier)

    class MalformedResponse:
        is_error = False

        @staticmethod
        def json():
            return {"record": None, "unexpected": "extra-field"}

    monkeypatch.setattr(anchor.httpx, "request", lambda *args, **kwargs: MalformedResponse())
    with pytest.raises(anchor.DevAnchorError, match="SERVICE_RESPONSE_INVALID"):
        await client.read_back(SCOPE, 1)


def test_s13_03_foreign_sqlite_application_id_is_refused(configure, tmp_path):
    database = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA application_id=123456")
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    configure(database=database)
    with pytest.raises(anchor.DevAnchorError, match="DATABASE_FILE_IDENTITY_MISMATCH"):
        anchor._SQLiteAnchorStore(database)


def test_s13_03_malformed_and_oversized_requests_fail_closed(configure):
    with TestClient(anchor.app, client=("127.0.0.1", 1234)) as client:
        malformed = client.put("/v1/checkpoints", headers=_headers(), content=b"not-json")
        assert malformed.status_code == 400
        assert malformed.json() == {"error": "INVALID_REQUEST"}
        response = client.post("/v1/checkpoints/latest", headers=_headers(),
                               content=b"{" + b" " * (16 * 1024 + 10) + b"}")
        assert response.status_code == 413
        assert response.json() == {"error": "REQUEST_TOO_LARGE"}




