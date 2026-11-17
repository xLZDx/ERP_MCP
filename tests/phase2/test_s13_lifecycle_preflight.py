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
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointKeyAuthorization,
    CheckpointKeyAuthorizationBasis,
    CheckpointLatestnessEvidence,
    CheckpointRecord,
    Ed25519SignatureVerifier,
    FakeSigner,
    FakeVerifier,
    InMemoryCheckpointSink,
    checkpoint_identity,
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
                   private_key: Ed25519PrivateKey, *, signed_at: datetime = NOW) -> CheckpointRecord:
    unsigned = CheckpointRecord(
        scope.tenant_id, scope.company_id, seq, f"{seq:064x}", signed_at,
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


def key_authorization(record: CheckpointRecord, *, basis=CheckpointKeyAuthorizationBasis.ACTIVE,
                      scope: Scope = SCOPE, key_id: str | None = None,
                      public_key_digest: str | None = None, checkpoint_digest: str | None = None,
                      authority_revision: int = 1, authority_event_id: str = "authority-event-1",
                      policy_version: str = "test-policy-v1", receipt_id: str | None = None,
                      accepted_at: datetime | None = None) -> CheckpointKeyAuthorization:
    """Synthetic authority response; it is not a production trust or receipt proof."""
    return CheckpointKeyAuthorization(
        tenant_id=scope.tenant_id,
        company_id=scope.company_id,
        key_id=record.key_id if key_id is None else key_id,
        public_key_digest=(FakeVerifier().public_key_digest(record.key_id)
                           if public_key_digest is None else public_key_digest),
        checkpoint_digest=(checkpoint_identity(record) if checkpoint_digest is None
                           else checkpoint_digest),
        challenge_nonce="0" * 64,
        authority_id="synthetic-authority",
        authority_revision=authority_revision,
        authority_event_id=authority_event_id,
        policy_version=policy_version,
        basis=basis,
        receipt_id=receipt_id,
        accepted_at=accepted_at,
    )


class KeyAuthority:
    """TEST ONLY. Supplies explicit synthetic authority decisions to the preflight port."""

    is_test_double = True

    def __init__(self, result=None, error: Exception | None = None, calls=None,
                 *, bind_challenge_nonce: bool = True):
        self.result = result
        self.error = error
        self.calls = calls if calls is not None else []
        self.bind_challenge_nonce = bind_challenge_nonce

    async def authorize_checkpoint(self, scope, record, challenge_nonce):
        self.calls.append((scope, record))
        if self.error:
            raise self.error
        if self.result is not None and self.bind_challenge_nonce:
            return replace(self.result, challenge_nonce=challenge_nonce)
        return self.result


class SlowKeyAuthority(KeyAuthority):
    async def authorize_checkpoint(self, scope, record, challenge_nonce):
        self.calls.append((scope, record))
        await asyncio.sleep(60)


class LatestnessAuthority:
    """TEST ONLY. Models a separately authenticated latestness port, never provider proof."""

    is_test_double = True

    def __init__(self, sink, *, evidence=None, error=None, calls=None,
                 bind_challenge_nonce: bool = True):
        self.sink = sink
        self.evidence = evidence
        self.error = error
        self.calls = calls if calls is not None else []
        self.bind_challenge_nonce = bind_challenge_nonce

    async def attest_latest(self, scope, record, challenge_nonce):
        self.calls.append("latestness")
        if self.error:
            raise self.error
        evidence = self.evidence
        if evidence is None:
            try:
                digest = None if record is None else checkpoint_identity(record)
            except Exception:
                digest = "0" * 64
            evidence = CheckpointLatestnessEvidence(
                tenant_id=scope.tenant_id,
                company_id=scope.company_id,
                checkpoint_digest=digest,
                challenge_nonce=challenge_nonce,
                provider_id="test-sink" if record is None else record.sink_id,
                provider_revision=1 if record is None else record.seq,
                authority_id="synthetic-latestness-authority",
                authority_revision=0 if record is None else 1,
                authority_event_id=(None if record is None
                                    else "00000000-0000-4000-8000-000000000001"),
                policy_version="synthetic-test-policy-v1",
                proof_digest=None if record is None else "1" * 64,
            )
        elif self.bind_challenge_nonce:
            evidence = replace(evidence, challenge_nonce=challenge_nonce)
        return evidence


class SlowLatestnessAuthority(LatestnessAuthority):
    async def attest_latest(self, scope, record, challenge_nonce):
        await asyncio.sleep(60)


def _test_coordinator(ledger, sink, verifier, **kwargs):
    """Build the coordinator with synthetic ports; sink is only used by the fake authority."""
    kwargs.setdefault("latestness_authority", LatestnessAuthority(sink))
    return LifecycleCoordinator(ledger, sink, verifier, **kwargs)


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


class SuffixCountingLedger(Ledger):
    def __init__(self, response=None, error: Exception | None = None, calls=None):
        super().__init__(response=response, error=error, calls=calls)
        self.suffix_calls = 0

    async def lifecycle_checkpoint_suffix(self, scope, checkpoint_seq, checkpoint_hash):
        self.suffix_calls += 1
        return await super().lifecycle_checkpoint_suffix(scope, checkpoint_seq, checkpoint_hash)


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
                result = asyncio.run(_test_coordinator(
                    Ledger(response=chain_response, calls=calls), sink, FakeVerifier()
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, LifecycleReason.CHAIN_INVALID)
                self.assertEqual(calls, [("chain", SCOPE)])

    def test_dict_subclass_with_raising_get_maps_to_chain_invalid(self):
        calls = []
        result = asyncio.run(_test_coordinator(
            Ledger(response=ExplodingGetDict(ok=True, count=9), calls=calls),
            Sink(calls, signed_record()), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_INVALID)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_chain_exception_maps_to_fixed_reason_without_sink_call(self):
        calls = []
        result = asyncio.run(_test_coordinator(
            Ledger(error=RuntimeError("secret chain detail"), calls=calls),
            Sink(calls, signed_record()), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_UNAVAILABLE)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_chain_timeout_maps_to_chain_unavailable_without_provider_call(self):
        calls = []
        result = asyncio.run(_test_coordinator(
            SlowLedger(calls=calls), Sink(calls, signed_record()), FakeVerifier(),
            dependency_timeout_seconds=0.001,
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_UNAVAILABLE)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_missing_latestness_authority_fails_before_sink_key_authority_or_suffix(self):
        calls = []
        ledger = SuffixCountingLedger(calls=calls)
        sink = EffectCountingSink(calls, signed_record())
        result = asyncio.run(LifecycleCoordinator(
            ledger, sink, FakeVerifier(),
            key_authority=KeyAuthority(key_authorization(signed_record())),
        ).preflight(SCOPE))
        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE)
        self.assertEqual(calls, [("chain", SCOPE), ("latest", SCOPE)])
        self.assertEqual(ledger.suffix_calls, 0)
        self.assertEqual(sink.write_calls, sink.read_back_calls, 0)

    def test_latestness_authority_exception_and_timeout_fail_closed(self):
        record = signed_record()
        for authority, timeout in (
            (LatestnessAuthority(Sink([], record), error=RuntimeError("private provider detail")), 1.0),
            (SlowLatestnessAuthority(Sink([], record)), 0.001),
        ):
            with self.subTest(authority=type(authority).__name__):
                ledger = SuffixCountingLedger()
                result = asyncio.run(_test_coordinator(
                    ledger, Sink([], record), FakeVerifier(), latestness_authority=authority,
                    key_authority=KeyAuthority(key_authorization(record)),
                    dependency_timeout_seconds=timeout,
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason,
                              LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE)
                self.assertEqual(ledger.suffix_calls, 0)
                self.assertNotIn("private provider detail", repr(result))

    def test_latestness_evidence_must_bind_exact_scope_checkpoint_and_provider_history(self):
        record = signed_record()
        valid = CheckpointLatestnessEvidence(
            tenant_id=SCOPE.tenant_id,
            company_id=SCOPE.company_id,
            checkpoint_digest=checkpoint_identity(record),
            challenge_nonce="0" * 64,
            provider_id=record.sink_id,
            provider_revision=record.seq,
            authority_id="synthetic-latestness-authority",
            authority_revision=1,
            authority_event_id="00000000-0000-4000-8000-000000000001",
            policy_version="synthetic-test-policy-v1",
            proof_digest="1" * 64,
        )
        invalid_evidence = (
            replace(valid, tenant_id="tenant-other"),
            replace(valid, company_id="company-other"),
            replace(valid, checkpoint_digest="f" * 64),
            replace(valid, authority_id=""),
            replace(valid, authority_revision=0),
            replace(valid, authority_event_id=""),
            replace(valid, proof_digest="not-a-digest"),
        )
        for evidence in invalid_evidence:
            with self.subTest(evidence=evidence):
                calls = []
                ledger = SuffixCountingLedger(calls=calls)
                authority = LatestnessAuthority(
                    Sink(calls, record), evidence=evidence, calls=calls,
                )
                result = asyncio.run(_test_coordinator(
                    ledger, Sink(calls, record), FakeVerifier(), latestness_authority=authority,
                    key_authority=KeyAuthority(key_authorization(record)),
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_LATESTNESS_INVALID)
                self.assertEqual(ledger.suffix_calls, 0)
                self.assertEqual(calls, [("chain", SCOPE), ("latest", SCOPE), "latestness"])

    def test_latestness_precedes_historical_key_authorization_and_suffix(self):
        record = signed_record()
        order = []

        class OrderedLedger(Ledger):
            async def verify_chain(self, scope):
                order.append("chain")
                return await super().verify_chain(scope)

            async def lifecycle_checkpoint_suffix(self, scope, checkpoint_seq, checkpoint_hash):
                order.append("suffix")
                return await super().lifecycle_checkpoint_suffix(scope, checkpoint_seq, checkpoint_hash)

        class OrderedKeyAuthority(KeyAuthority):
            async def authorize_checkpoint(self, scope, record, challenge_nonce):
                order.append("key_authorization")
                return await super().authorize_checkpoint(scope, record, challenge_nonce)

        sink = Sink([], record)
        latestness = LatestnessAuthority(sink, calls=order)
        key_authority = OrderedKeyAuthority(key_authorization(record))
        result = asyncio.run(_test_coordinator(
            OrderedLedger(), sink, FakeVerifier(), latestness_authority=latestness,
            key_authority=key_authority,
        ).preflight(SCOPE))
        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual(order, ["chain", "latestness", "key_authorization", "suffix"])

    def test_provider_exception_and_missing_record_have_fixed_reasons(self):
        for record, error, expected in (
            (None, RuntimeError("provider private detail"),
             LifecycleReason.CHECKPOINT_UNAVAILABLE),
            (None, None, LifecycleReason.CHECKPOINT_MISSING),
        ):
            with self.subTest(expected=expected):
                calls = []
                result = asyncio.run(_test_coordinator(
                    Ledger(calls=calls), Sink(calls, record=record, error=error), FakeVerifier(),
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, expected)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertNotIn("private detail", repr(result))

    def test_checkpoint_sink_timeout_maps_to_checkpoint_unavailable(self):
        calls = []
        result = asyncio.run(_test_coordinator(
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
                    _test_coordinator(Ledger(), Sink([]), FakeVerifier(),
                                         dependency_timeout_seconds=timeout)

    def test_wrong_scope_record_is_rejected_before_signature_check(self):
        calls = []
        result = asyncio.run(_test_coordinator(
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
                result = asyncio.run(_test_coordinator(
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

        # Signature validity and authority authorization are separate checks. This key map is
        # synthetic material for cryptographic verification only.
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
                result = asyncio.run(_test_coordinator(
                    Ledger(calls=calls), sink, verifier,
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_INVALID)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual(sink.write_calls, 0)
                self.assertEqual(sink.read_back_calls, 0)

        # A registered public key and valid signature do not authorize use without an authority
        # response; the policy decision is tested separately below.

    def test_key_authority_is_required_and_all_refusals_fail_closed_before_suffix(self):
        record = signed_record()
        for authority, expected_reason in (
            (None, LifecycleReason.CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE),
            (KeyAuthority(None), LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_DENIED),
            (KeyAuthority(error=RuntimeError("private authority detail")),
             LifecycleReason.CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE),
            (SlowKeyAuthority(), LifecycleReason.CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE),
        ):
            with self.subTest(expected=expected_reason, authority=type(authority).__name__):
                calls = []
                ledger = SuffixCountingLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                result = asyncio.run(_test_coordinator(
                    ledger, sink, FakeVerifier(), key_authority=authority,
                    dependency_timeout_seconds=0.001,
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, expected_reason)
                self.assertEqual(ledger.suffix_calls, 0)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual(sink.write_calls, 0)
                self.assertEqual(sink.read_back_calls, 0)
                self.assertNotIn("private authority detail", repr(result))

    def test_authority_decision_must_bind_scope_key_public_key_and_exact_checkpoint(self):
        key = _synthetic_test_key("binding")
        record = ed25519_record(SCOPE, 7, "s13-test-binding", key)
        evidence = key_authorization(
            record,
            public_key_digest=hashlib.sha256(public_key_bytes(key)).hexdigest(),
        )
        invalid_evidence = (
            replace(evidence, tenant_id="tenant-other"),
            replace(evidence, company_id="company-other"),
            replace(evidence, key_id="s13-test-other"),
            # Valid digest syntax is insufficient: the response must bind the actual key
            # resolved by this verifier, and rejection must happen before suffix evaluation.
            replace(evidence, public_key_digest="0" * 64),
            replace(evidence, public_key_digest="z" * 64),
            replace(evidence, checkpoint_digest="f" * 64),
            replace(evidence, authority_revision=0),
            replace(evidence, authority_event_id=""),
            replace(evidence, policy_version=""),
            replace(evidence, basis="ACTIVE"),
        )
        verifier = Ed25519SignatureVerifier({
            record.key_id: public_key_bytes(key),
        })
        self.assertNotEqual(evidence.public_key_digest, "0" * 64)
        for malformed in invalid_evidence:
            with self.subTest(evidence=malformed):
                calls = []
                ledger = SuffixCountingLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                result = asyncio.run(_test_coordinator(
                    ledger, sink, verifier, key_authority=KeyAuthority(malformed),
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_INVALID)
                self.assertEqual(ledger.suffix_calls, 0)
                self.assertEqual(sink.write_calls, sink.read_back_calls, 0)

    def test_routine_retirement_requires_a_separate_receipt_and_trusted_time(self):
        key = _synthetic_test_key("retirement")
        record = ed25519_record(SCOPE, 7, "s13-test-retired", key)
        public_digest = hashlib.sha256(public_key_bytes(key)).hexdigest()
        verifier = Ed25519SignatureVerifier({record.key_id: public_key_bytes(key)})
        malformed_receipts = (
            key_authorization(record, basis=CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT,
                              public_key_digest=public_digest, accepted_at=NOW),
            key_authorization(record, basis=CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT,
                              public_key_digest=public_digest, receipt_id="receipt-without-time"),
            key_authorization(record, basis=CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT,
                              public_key_digest=public_digest, receipt_id="naive-time",
                              accepted_at=datetime(2026, 10, 17)),
            key_authorization(record, basis=CheckpointKeyAuthorizationBasis.ACTIVE,
                              public_key_digest=public_digest, receipt_id="implicit-grace",
                              accepted_at=NOW),
        )
        for evidence in malformed_receipts:
            with self.subTest(receipt_id=evidence.receipt_id, accepted_at=evidence.accepted_at,
                              basis=evidence.basis):
                calls = []
                ledger = SuffixCountingLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                result = asyncio.run(_test_coordinator(
                    ledger, sink, verifier, key_authority=KeyAuthority(evidence),
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_INVALID)
                self.assertEqual(ledger.suffix_calls, 0)
                self.assertEqual(sink.write_calls, sink.read_back_calls, 0)

    def test_routine_retirement_with_broken_timezone_fails_closed(self):
        class BrokenTimezone(tzinfo):
            def utcoffset(self, dt):
                raise RuntimeError("timezone provider failed")

        key = _synthetic_test_key("broken-timezone")
        record = ed25519_record(SCOPE, 8, "s13-test-broken-timezone", key)
        public_digest = hashlib.sha256(public_key_bytes(key)).hexdigest()
        verifier = Ed25519SignatureVerifier({record.key_id: public_key_bytes(key)})
        evidence = key_authorization(
            record,
            basis=CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT,
            public_key_digest=public_digest,
            receipt_id="synthetic-receipt",
            accepted_at=datetime(2026, 10, 17, tzinfo=BrokenTimezone()),
        )
        calls = []
        ledger = SuffixCountingLedger(calls=calls)
        sink = EffectCountingSink(calls, record)

        result = asyncio.run(_test_coordinator(
            ledger, sink, verifier, key_authority=KeyAuthority(evidence),
        ).preflight(SCOPE))

        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_INVALID)
        self.assertEqual(ledger.suffix_calls, 0)
        self.assertEqual(sink.write_calls, 0)
        self.assertEqual(sink.read_back_calls, 0)

    def test_signed_at_alone_forged_receipt_and_compromise_revocation_do_not_authorize(self):
        key = _synthetic_test_key("revoked")
        # The checkpoint claims a timestamp before retirement, but that self-declared field is
        # not a trusted authority receipt. A trusted authority refusal remains decisive.
        record = ed25519_record(
            SCOPE, 7, "s13-test-revoked", key, signed_at=NOW - timedelta(days=365),
        )
        verifier = Ed25519SignatureVerifier({record.key_id: public_key_bytes(key)})
        public_digest = hashlib.sha256(public_key_bytes(key)).hexdigest()
        forged_receipt = key_authorization(
            record, basis=CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT,
            public_key_digest=public_digest, receipt_id="forged-receipt", accepted_at=NOW,
        )
        # A production authority must reject the forged/backdated receipt itself. These explicit
        # TEST authority outcomes model that refusal; they are not provider cryptography evidence.
        for authority in (KeyAuthority(None), KeyAuthority(None)):
            with self.subTest(authority_calls=len(authority.calls)):
                calls = []
                ledger = SuffixCountingLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                result = asyncio.run(_test_coordinator(
                    ledger, sink, verifier, key_authority=authority,
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_DENIED)
                self.assertEqual(ledger.suffix_calls, 0)
                self.assertEqual(sink.write_calls, sink.read_back_calls, 0)
        self.assertEqual(forged_receipt.receipt_id, "forged-receipt")

    def test_active_or_receipt_authorized_historical_key_reaches_only_later_fail_closed_check(self):
        for label, basis in (
            ("active", CheckpointKeyAuthorizationBasis.ACTIVE),
            ("historical", CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT),
        ):
            key = _synthetic_test_key(label)
            key_id = f"s13-test-{label}"
            record = ed25519_record(SCOPE, 7, key_id, key)
            evidence = key_authorization(
                record,
                basis=basis,
                public_key_digest=hashlib.sha256(public_key_bytes(key)).hexdigest(),
                receipt_id="synthetic-receipt" if basis is CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT else None,
                accepted_at=NOW if basis is CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT else None,
            )
            verifier = Ed25519SignatureVerifier({key_id: public_key_bytes(key)})
            with self.subTest(basis=basis):
                calls = []
                ledger = SuffixCountingLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                authority = KeyAuthority(evidence)
                result = asyncio.run(_test_coordinator(
                    ledger, sink, verifier, key_authority=authority,
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
                self.assertEqual(ledger.suffix_calls, 1)
                self.assertEqual(authority.calls, [(SCOPE, record)])
                self.assertEqual(sink.write_calls, 0)
                self.assertEqual(sink.read_back_calls, 0)
                self.assertFalse(hasattr(LifecycleCoordinator, "recover"))
                self.assertFalse(hasattr(LifecycleCoordinator, "dispatch"))

    def test_historical_key_receipt_still_cannot_make_preflight_ready_without_fence(self):
        previous_key = _synthetic_test_key("previous")
        current_key = _synthetic_test_key("current")
        record = ed25519_record(SCOPE, 7, "s13-test-previous", previous_key)
        verifier = Ed25519SignatureVerifier({
            "s13-test-previous": public_key_bytes(previous_key),
            "s13-test-current": public_key_bytes(current_key),
        })
        calls = []
        sink = EffectCountingSink(calls, record)
        authority = KeyAuthority(key_authorization(
            record,
            basis=CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT,
            public_key_digest=hashlib.sha256(public_key_bytes(previous_key)).hexdigest(),
            receipt_id="synthetic-pre-retirement-receipt",
            accepted_at=NOW,
        ))
        result = asyncio.run(_test_coordinator(
            Ledger(calls=calls), sink, verifier, key_authority=authority,
        ).preflight(SCOPE))

        # The TEST sink and a valid local ancestor do not authenticate provider latestness.
        # Readiness must remain disabled even when signature, scope, and suffix checks pass.
        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual((result.checkpoint_seq, result.chain_count), (7, 9))
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])
        self.assertEqual(len(authority.calls), 1)
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
                authority = KeyAuthority(key_authorization(record))
                result = asyncio.run(_test_coordinator(
                    ledger, sink, FakeVerifier(), key_authority=authority,
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, expected_reason)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual(len(authority.calls), 1)
                self.assertEqual(sink.write_calls, 0)
                self.assertEqual(sink.read_back_calls, 0)

    def test_malformed_latest_values_map_to_checkpoint_invalid(self):
        valid = signed_record()
        bool_sequence = CheckpointRecord(**{**valid.__dict__, "seq": True})
        for candidate in (object(), bool_sequence):
            with self.subTest(candidate_type=type(candidate).__name__,
                              seq=getattr(candidate, "seq", None)):
                result = asyncio.run(_test_coordinator(
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
        result = asyncio.run(_test_coordinator(
            Ledger(), Sink([], malformed), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
        self.assertIsNone(result.checkpoint_seq)

    def test_exact_record_with_malformed_scope_equality_is_invalid(self):
        malformed = signed_record()
        object.__setattr__(malformed, "tenant_id", MalformedScopeField())
        result = asyncio.run(_test_coordinator(
            Ledger(), Sink([], malformed), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
        self.assertIsNone(result.checkpoint_seq)

    def test_valid_preflight_returns_checkpoint_evidence_but_never_ready(self):
        record = signed_record(seq=7)
        result = asyncio.run(_test_coordinator(
            Ledger(), Sink([], record), FakeVerifier(),
            key_authority=KeyAuthority(key_authorization(record)),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual(result.checkpoint_seq, 7)
        self.assertEqual(result.checkpoint_hash, f"{7:064x}")
        self.assertEqual(result.chain_count, 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
