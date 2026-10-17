"""Focused functional scenarios for the read-only S13 checkpoint preflight (CR131).

Story/gate map: S13 startup checkpoint preflight, local preparatory slice only. These
scenarios prove exact-scope latest selection, chain-before-provider ordering, stable
fail-closed reason mapping, and that even a valid checkpoint cannot produce READY while
the shared lifecycle fence is absent.

Run directly with the repository Python environment; intentionally does not require pytest.
"""
from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
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
