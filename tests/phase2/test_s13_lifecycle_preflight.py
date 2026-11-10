"""Focused functional scenarios for the read-only S13 checkpoint preflight (CR131).

Story/gate map: S13 startup checkpoint preflight, local preparatory slice only. These
scenarios prove exact-scope latest selection, chain-before-provider ordering, stable
fail-closed reason mapping, and that even a valid checkpoint cannot produce READY while
the shared lifecycle fence is absent.

Run directly with the repository Python environment; intentionally does not require pytest.
"""
from __future__ import annotations

import asyncio
import hashlib
import unittest
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    Ed25519SignatureVerifier,
    FakeSigner,
    FakeVerifier,
    InMemoryCheckpointSink,
)
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleCoordinator,
    LifecycleReason,
    LifecycleStatus,
)


SCOPE = Scope("tenant-a", "company-a")
NOW = datetime(2026, 10, 17, tzinfo=UTC)


def signed_record(scope: Scope = SCOPE, seq: int = 3) -> CheckpointRecord:
    signer = FakeSigner()
    unsigned = CheckpointRecord(
        scope.tenant_id, scope.company_id, seq, f"{seq:064x}", NOW,
        signer.key_id, "", "test-sink", "TEST",
    )
    return CheckpointRecord(**{
        **unsigned.__dict__,
        "signature": signer.sign(unsigned.signing_payload()),
    })


def _synthetic_test_key(label: str) -> Ed25519PrivateKey:
    """Return a deterministic, synthetic TEST-only Ed25519 key."""
    seed = hashlib.sha256(f"ERP_MCP S13 TEST KEY ONLY:{label}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def ed25519_record(scope: Scope, seq: int, key_id: str,
                   private_key: Ed25519PrivateKey) -> CheckpointRecord:
    unsigned = CheckpointRecord(
        scope.tenant_id, scope.company_id, seq, f"{seq:064x}", NOW,
        key_id, "", "test-sink", "TEST",
    )
    return CheckpointRecord(**{
        **unsigned.__dict__,
        "signature": private_key.sign(unsigned.signing_payload()).hex(),
    })


def public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


class Ledger:
    def __init__(self, response=None, error: Exception | None = None, calls=None):
        self.response = {"ok": True, "count": 9} if response is None else response
        self.error = error
        self.calls = calls if calls is not None else []

    async def verify_chain(self, scope):
        self.calls.append(("chain", scope))
        if self.error:
            raise self.error
        return self.response

    async def lifecycle_checkpoint_suffix(self, scope, checkpoint_seq, checkpoint_hash):
        head_seq = self.response["count"]
        events = []
        for seq in range(checkpoint_seq + 1, head_seq + 1):
            events.append({
                "seq": seq,
                "event_id": f"00000000-0000-4000-8000-{seq:012d}",
                "change_id": f"00000000-0000-4000-9000-{seq:012d}",
                "event_type": "VERIFY_VERIFIED",
                "payload_found": None,
                "payload_nonempty": True,
                "record": {
                    "execution_state": "APPLIED",
                    "verification_state": "VERIFIED",
                    "call_ownership": "PROVEN_FINISHED",
                    "reservation_state": "CONSUMED",
                    "dispatch_state": "DISPATCHED",
                },
            })
        return {
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "checkpoint_seq": checkpoint_seq,
            "checkpoint_hash": checkpoint_hash,
            "anchor_matches": True,
            "head_seq": head_seq,
            "has_more": False,
            "events": events,
        }


class ExplodingGetDict(dict):
    def get(self, key, default=None):
        raise RuntimeError("untrusted chain result accessor")


class SlowLedger(Ledger):
    async def verify_chain(self, scope):
        self.calls.append(("chain", scope))
        await asyncio.sleep(60)


class Sink(InMemoryCheckpointSink):
    def __init__(self, calls, record=None, error=None):
        super().__init__()
        self.calls = calls
        self.record = record
        self.error = error

    async def latest(self, scope):
        self.calls.append(("latest", scope))
        if self.error:
            raise self.error
        return self.record


class EffectCountingSink(Sink):
    def __init__(self, calls, record=None, error=None):
        super().__init__(calls, record=record, error=error)
        self.write_calls = 0
        self.read_back_calls = 0

    async def write(self, record):
        self.write_calls += 1
        await super().write(record)

    async def read_back(self, scope, seq):
        self.read_back_calls += 1
        return await super().read_back(scope, seq)


class AnchorResultLedger(Ledger):
    def __init__(self, *, anchor_matches=True, response=None, error=None, calls=None):
        super().__init__(response=response, error=error, calls=calls)
        self.anchor_matches = anchor_matches

    async def lifecycle_checkpoint_suffix(self, scope, checkpoint_seq, checkpoint_hash):
        result = await super().lifecycle_checkpoint_suffix(
            scope, checkpoint_seq, checkpoint_hash,
        )
        result["anchor_matches"] = self.anchor_matches
        return result


class SlowSink(Sink):
    async def latest(self, scope):
        self.calls.append(("latest", scope))
        await asyncio.sleep(60)


class ExplodingVerifier:
    def verify(self, key_id, payload, signature):
        raise RuntimeError("private verifier diagnostic")


class ExplodingCheckpointRecord(CheckpointRecord):
    def __getattribute__(self, name):
        if name == "tenant_id" and object.__getattribute__(self, "_explode_field_access"):
            raise RuntimeError("untrusted checkpoint field accessor")
        return super().__getattribute__(name)


class ExplodingBool:
    def __bool__(self):
        raise RuntimeError("malformed scope equality result")


class MalformedScopeField:
    def __eq__(self, other):
        return ExplodingBool()


class S13LifecyclePreflightTests(unittest.TestCase):
    def test_in_memory_latest_is_highest_sequence_for_exact_scope(self):
        sink = InMemoryCheckpointSink()
        other_company = Scope("tenant-a", "company-b")
        other_tenant = Scope("tenant-b", "company-a")
        for record in (
            signed_record(SCOPE, 2), signed_record(SCOPE, 8),
            signed_record(other_company, 99), signed_record(other_tenant, 100),
        ):
            asyncio.run(sink.write(record))

        latest = asyncio.run(sink.latest(SCOPE))
        self.assertIsNotNone(latest)
        self.assertEqual(latest.seq, 8)
        self.assertEqual((latest.tenant_id, latest.company_id),
                         (SCOPE.tenant_id, SCOPE.company_id))
        self.assertIsNone(asyncio.run(InMemoryCheckpointSink().latest(SCOPE)))

    def test_invalid_chain_does_not_read_latest_checkpoint(self):
        for chain_response in (
            {"ok": False, "count": 4},
            {"ok": True, "count": "bad"},
        ):
            with self.subTest(chain_response=chain_response):
                calls = []
                sink = Sink(calls, signed_record())
                result = asyncio.run(LifecycleCoordinator(
                    Ledger(response=chain_response, calls=calls), sink, FakeVerifier()
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, LifecycleReason.CHAIN_INVALID)
                self.assertEqual(calls, [("chain", SCOPE)])

    def test_dict_subclass_with_raising_get_maps_to_chain_invalid(self):
        calls = []
        result = asyncio.run(LifecycleCoordinator(
            Ledger(response=ExplodingGetDict(ok=True, count=9), calls=calls),
            Sink(calls, signed_record()), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_INVALID)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_chain_exception_maps_to_fixed_reason_without_sink_call(self):
        calls = []
        result = asyncio.run(LifecycleCoordinator(
            Ledger(error=RuntimeError("secret chain detail"), calls=calls),
            Sink(calls, signed_record()), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_UNAVAILABLE)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_chain_timeout_maps_to_chain_unavailable_without_provider_call(self):
        calls = []
        result = asyncio.run(LifecycleCoordinator(
            SlowLedger(calls=calls), Sink(calls, signed_record()), FakeVerifier(),
            dependency_timeout_seconds=0.001,
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_UNAVAILABLE)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_provider_exception_and_missing_record_have_fixed_reasons(self):
        for record, error, expected in (
            (None, RuntimeError("provider private detail"), LifecycleReason.CHECKPOINT_UNAVAILABLE),
            (None, None, LifecycleReason.CHECKPOINT_MISSING),
        ):
            with self.subTest(expected=expected):
                calls = []
                result = asyncio.run(LifecycleCoordinator(
                    Ledger(calls=calls), Sink(calls, record=record, error=error), FakeVerifier(),
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, expected)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertNotIn("private detail", repr(result))

    def test_checkpoint_latest_timeout_maps_to_checkpoint_unavailable(self):
        calls = []
        result = asyncio.run(LifecycleCoordinator(
            Ledger(calls=calls), SlowSink(calls), FakeVerifier(),
            dependency_timeout_seconds=0.001,
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_UNAVAILABLE)
        self.assertEqual(result.chain_count, 9)
        self.assertEqual(calls, [("chain", SCOPE), ("latest", SCOPE)])

    def test_dependency_timeout_must_be_finite_positive_number_not_bool(self):
        for timeout in (0, -0.1, float("inf"), float("nan"), True, "1"):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    LifecycleCoordinator(Ledger(), Sink([]), FakeVerifier(),
                                         dependency_timeout_seconds=timeout)

    def test_wrong_scope_record_is_rejected_before_signature_check(self):
        calls = []
        result = asyncio.run(LifecycleCoordinator(
            Ledger(calls=calls), Sink(calls, signed_record(Scope("tenant-x", "company-a"))),
            ExplodingVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_SCOPE_MISMATCH)
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])

    def test_bad_signature_and_verifier_exception_map_to_checkpoint_invalid(self):
        record = signed_record()
        bad_signature = CheckpointRecord(**{**record.__dict__, "signature": "0" * 64})
        for candidate, verifier in (
            (bad_signature, FakeVerifier()),
            (record, ExplodingVerifier()),
        ):
            with self.subTest(verifier=type(verifier).__name__):
                result = asyncio.run(LifecycleCoordinator(
                    Ledger(), Sink([], candidate), verifier,
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
                self.assertIsNone(result.checkpoint_seq)

    def test_ed25519_test_key_rotation_checks_signature_and_key_id_separately(self):
        previous_key = _synthetic_test_key("previous")
        current_key = _synthetic_test_key("current")
        previous_record = ed25519_record(SCOPE, 7, "s13-test-previous", previous_key)
        current_record = ed25519_record(SCOPE, 8, "s13-test-current", current_key)
        verifier = Ed25519SignatureVerifier({
            "s13-test-previous": public_key_bytes(previous_key),
            "s13-test-current": public_key_bytes(current_key),
        })

        # This proves only cryptographic validity against the explicit synthetic key snapshot.
        # It does not establish historical authorization, a grace period, rotation timing, or
        # revocation semantics; those policies are intentionally unspecified.
        for candidate in (previous_record, current_record):
            with self.subTest(valid_test_key=candidate.key_id):
                self.assertTrue(verifier.verify(
                    candidate.key_id, candidate.signing_payload(), candidate.signature,
                ))

        unknown_key_record = CheckpointRecord(**{
            **previous_record.__dict__, "key_id": "s13-test-unregistered",
        })
        mismatched_key_record = CheckpointRecord(**{
            **previous_record.__dict__, "key_id": "s13-test-current",
        })
        malformed_key_record = CheckpointRecord(**{
            **previous_record.__dict__, "key_id": object(),
        })
        bad_signature_record = CheckpointRecord(**{
            **previous_record.__dict__, "signature": "0" * 128,
        })

        for candidate in (unknown_key_record, mismatched_key_record,
                          malformed_key_record, bad_signature_record):
            with self.subTest(key_id=repr(candidate.key_id)):
                calls = []
                sink = EffectCountingSink(calls, candidate)
                result = asyncio.run(LifecycleCoordinator(
                    Ledger(calls=calls), sink, verifier,
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_INVALID)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual(sink.write_calls, 0)
                self.assertEqual(sink.read_back_calls, 0)

        # The protocol has no authoritative TEST revocation or verification-time policy.
        # Do not label an absent key ID "revoked" or claim that a historical signature is
        # authorized merely because its public key is in this verifier's input snapshot.

    def test_locally_valid_ancestor_checkpoint_still_cannot_make_preflight_ready(self):
        previous_key = _synthetic_test_key("previous")
        current_key = _synthetic_test_key("current")
        record = ed25519_record(SCOPE, 7, "s13-test-previous", previous_key)
        verifier = Ed25519SignatureVerifier({
            "s13-test-previous": public_key_bytes(previous_key),
            "s13-test-current": public_key_bytes(current_key),
        })
        calls = []
        sink = EffectCountingSink(calls, record)
        result = asyncio.run(LifecycleCoordinator(
            Ledger(calls=calls), sink, verifier,
        ).preflight(SCOPE))

        # The TEST sink and a valid local ancestor do not authenticate provider latestness.
        # Readiness must remain disabled even when signature, scope, and suffix checks pass.
        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual((result.checkpoint_seq, result.chain_count), (7, 9))
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])
        self.assertEqual(sink.write_calls, 0)
        self.assertEqual(sink.read_back_calls, 0)

    def test_restore_anchor_nonancestor_and_ahead_of_chain_both_fail_closed(self):
        for record, ledger, expected_reason in (
            (signed_record(seq=7), AnchorResultLedger(anchor_matches=False),
             LifecycleReason.CHECKPOINT_NOT_ANCESTOR),
            (signed_record(seq=10), Ledger(response={"ok": True, "count": 9}),
             LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        ):
            with self.subTest(seq=record.seq, expected=expected_reason):
                calls = []
                ledger.calls = calls
                sink = EffectCountingSink(calls, record)
                result = asyncio.run(LifecycleCoordinator(
                    ledger, sink, FakeVerifier(),
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, expected_reason)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual(sink.write_calls, 0)
                self.assertEqual(sink.read_back_calls, 0)

    def test_malformed_latest_values_map_to_checkpoint_invalid(self):
        valid = signed_record()
        bool_sequence = CheckpointRecord(**{**valid.__dict__, "seq": True})
        for candidate in (object(), bool_sequence):
            with self.subTest(candidate_type=type(candidate).__name__,
                              seq=getattr(candidate, "seq", None)):
                result = asyncio.run(LifecycleCoordinator(
                    Ledger(), Sink([], candidate), FakeVerifier(),
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
                self.assertIsNone(result.checkpoint_seq)
                self.assertIsNone(result.checkpoint_hash)

    def test_checkpoint_record_subclass_with_raising_field_access_is_invalid(self):
        valid = signed_record()
        malformed = ExplodingCheckpointRecord(**valid.__dict__)
        object.__setattr__(malformed, "_explode_field_access", True)
        result = asyncio.run(LifecycleCoordinator(
            Ledger(), Sink([], malformed), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
        self.assertIsNone(result.checkpoint_seq)

    def test_exact_record_with_malformed_scope_equality_is_invalid(self):
        malformed = signed_record()
        object.__setattr__(malformed, "tenant_id", MalformedScopeField())
        result = asyncio.run(LifecycleCoordinator(
            Ledger(), Sink([], malformed), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
        self.assertIsNone(result.checkpoint_seq)

    def test_valid_preflight_returns_checkpoint_evidence_but_never_ready(self):
        result = asyncio.run(LifecycleCoordinator(
            Ledger(), Sink([], signed_record(seq=7)), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual(result.checkpoint_seq, 7)
        self.assertEqual(result.checkpoint_hash, f"{7:064x}")
        self.assertEqual(result.chain_count, 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
