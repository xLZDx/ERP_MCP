"""Regression contract for reused T16 operator-resolution checkpoints.

Only synthetic in-memory collaborators are used. The verifier is the real Ed25519 verifier so a
syntactically valid signature cannot be mistaken for cryptographic verification.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    CheckpointUnavailable,
    DispatchGate,
    Ed25519SignatureVerifier,
)


SCOPE = Scope("synthetic-tenant", "synthetic-company")
EVENT_ID = "11111111-1111-4111-8111-111111111111"
CALL_HOLD_ID = "22222222-2222-4222-8222-222222222222"
HOLD_IDS = [
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
]
EVENT_SEQ = 17
EVENT_HASH = "a" * 64
SIGNED_AT = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
SINK_ID = "synthetic-real-shape-sink"
HISTORICAL_KEY_ID = "historical-checkpoint-key"


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )


def _resolution() -> dict[str, object]:
    return {
        "checkpoint_required": True,
        "execution_state": "APPLIED",
        "event_id": EVENT_ID,
        "hold_id": CALL_HOLD_ID,
        "event_seq": EVENT_SEQ,
        "event_hash": EVENT_HASH,
        "checkpoint_signed_at": SIGNED_AT,
        "checkpoint_hold_ids": list(HOLD_IDS),
    }


class _CurrentSigner:
    """Synthetic contract stub; false marker only opens the gate branch under test.

    It is not a configured runtime signer and deliberately raises if reuse tries to sign anew.
    """

    is_test_double = False
    key_id = "current-checkpoint-key"
    key_version = "current-v2"

    def __init__(self) -> None:
        self.sign_calls = 0

    def sign(self, _payload: bytes) -> str:
        self.sign_calls += 1
        raise AssertionError("reused checkpoint must not be signed with the current key")


class _ReadbackSink:
    is_test_double = True
    kind = "REAL"
    sink_id = SINK_ID

    def __init__(self, record: CheckpointRecord) -> None:
        self.record = record
        self.read_back_calls: list[tuple[Scope, int]] = []
        self.write_calls = 0

    async def read_back(self, scope: Scope, seq: int) -> CheckpointRecord | None:
        self.read_back_calls.append((scope, seq))
        if (self.record.tenant_id, self.record.company_id, self.record.seq) == (
                scope.tenant_id, scope.company_id, seq):
            return self.record
        return None

    async def write(self, _record: CheckpointRecord) -> None:
        self.write_calls += 1
        raise AssertionError("read-back reuse must not append another checkpoint")

    async def latest(self, _scope: Scope) -> CheckpointRecord | None:
        return self.record


class _ResolutionLedger:
    private_writer_schema_enabled = True

    def __init__(self) -> None:
        self.record_checkpoint_calls: list[tuple[object, ...]] = []
        self.release_calls: list[tuple[object, ...]] = []

    async def record_checkpoint_s13(self, *args) -> int:
        self.record_checkpoint_calls.append(args)
        return EVENT_SEQ

    async def release_hold(self, *args) -> datetime:
        self.release_calls.append(args)
        return SIGNED_AT


class _RuntimeAuthority:
    """Synthetic contract stub for the enabled-branch probe; never qualification evidence."""

    is_test_double = False

    async def require_provider_qualified(self, *_args, **_kwargs) -> None:
        return None

    async def require_admission_ready(self, _scope: Scope) -> None:
        return None


def _record(private_key: Ed25519PrivateKey | None, signature: str) -> CheckpointRecord:
    record = CheckpointRecord(
        SCOPE.tenant_id,
        SCOPE.company_id,
        EVENT_SEQ,
        EVENT_HASH,
        SIGNED_AT,
        HISTORICAL_KEY_ID,
        signature,
        SINK_ID,
        "REAL",
    )
    if private_key is None:
        return record
    return CheckpointRecord(**{
        **record.__dict__,
        "signature": private_key.sign(record.signing_payload()).hex(),
    })


def _gate(record: CheckpointRecord):
    sink = _ReadbackSink(record)
    signer = _CurrentSigner()
    ledger = _ResolutionLedger()
    verifier_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    verifier = Ed25519SignatureVerifier({HISTORICAL_KEY_ID: _public_key(verifier_key)})
    gate = DispatchGate(
        ledger,
        sink,
        signer,
        verifier,
        real_checkpoint_sink=True,
        private_writer_schema_enabled=True,
        runtime_authority=_RuntimeAuthority(),
    )
    return gate, ledger, sink, signer, verifier_key


def test_reused_exact_readback_with_forged_hex_signature_fails_before_database_effects():
    forged = _record(None, "5" * 128)
    gate, ledger, sink, signer, _verifier_key = _gate(forged)

    with pytest.raises(CheckpointUnavailable, match="READ_BACK_MISMATCH"):
        asyncio.run(gate.checkpoint_operator_resolution(SCOPE, _resolution()))

    assert sink.read_back_calls == [(SCOPE, EVENT_SEQ)]
    assert sink.write_calls == 0
    assert signer.sign_calls == 0
    assert ledger.record_checkpoint_calls == []
    assert ledger.release_calls == []


def test_valid_historical_key_readback_is_verified_and_reused_without_current_resigning():
    historical_private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    signed_historical_record = _record(historical_private_key, "0" * 128)
    gate, ledger, sink, signer, verifier_key = _gate(signed_historical_record)

    result = asyncio.run(gate.checkpoint_operator_resolution(SCOPE, _resolution()))

    assert verifier_key is not None
    assert result == {
        "event_id": EVENT_ID,
        "event_seq": EVENT_SEQ,
        "checkpoint_seq": EVENT_SEQ,
        "released_hold_ids": [*HOLD_IDS, CALL_HOLD_ID],
    }
    assert sink.read_back_calls == [(SCOPE, EVENT_SEQ)]
    assert sink.write_calls == 0
    assert signer.sign_calls == 0
    assert len(ledger.record_checkpoint_calls) == 1
    stored_call = ledger.record_checkpoint_calls[0]
    assert stored_call == (
        SCOPE,
        EVENT_SEQ,
        EVENT_HASH,
        "REAL",
        SINK_ID,
        HISTORICAL_KEY_ID,
        signed_historical_record.signature,
        SIGNED_AT,
        True,
    )
    assert [call[1] for call in ledger.release_calls] == [
        UUID(value) for value in (*HOLD_IDS, CALL_HOLD_ID)
    ]
