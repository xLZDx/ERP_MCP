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
from datetime import UTC, datetime, timedelta

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
from business_ai_gateway.phase2.change_ledger.lifecycle import LifecycleCoordinator as _BaseLifecycleCoordinator


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
                   private_key: Ed25519PrivateKey,
                   signed_at: datetime = NOW) -> CheckpointRecord:
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


class SyntheticTestKeyAuthorizationRegistry:
    """Test-only separation of Ed25519 validity from time-of-check authorization."""

    def __init__(self, public_keys: dict[str, bytes], states: dict[str, object]):
        self._crypto = Ed25519SignatureVerifier(public_keys)
        self._states = states

    def signature_is_valid(self, key_id: str, payload: bytes, signature: str) -> bool:
        return self._crypto.verify(key_id, payload, signature)

    def public_key_digest(self, key_id: str) -> str:
        return self._crypto.public_key_digest(key_id)

    @staticmethod
    def _valid_window(window: object, reference_time: datetime) -> bool:
        if (type(window) is not dict or set(window) != {"valid_from", "valid_until"}
                or type(reference_time) is not datetime
                or reference_time.tzinfo is None or reference_time.utcoffset() is None):
            return False
        valid_from = window["valid_from"]
        valid_until = window["valid_until"]
        if (type(valid_from) is not datetime or valid_from.tzinfo is None
                or valid_from.utcoffset() is None or type(valid_until) is not datetime
                or valid_until.tzinfo is None or valid_until.utcoffset() is None
                or valid_from >= valid_until):
            return False
        return valid_from <= reference_time < valid_until

    def authorized_at(self, key_id: str, reference_time: datetime) -> bool:
        if (type(key_id) is not str or type(reference_time) is not datetime
                or type(self._states) is not dict):
            return False
        state = self._states.get(key_id)
        if type(state) is not dict:
            return False
        if state.get("state") == "AUTHORIZED":
            if set(state) != {"state", "valid_from", "valid_until"}:
                return False
            return self._valid_window(
                {"valid_from": state["valid_from"],
                 "valid_until": state["valid_until"]},
                reference_time,
            )
        if state.get("state") == "RETIRED":
            if set(state) != {"state", "historical_rule"}:
                return False
            # A retired TEST key is not implicitly accepted. This explicit synthetic rule
            # is the only way the fixture allows historical authorization.
            return self._valid_window(state.get("historical_rule"), reference_time)
        return False


class SyntheticTestAuthorizationVerifier:
    """TEST ONLY: require crypto validity and registry authorization at injected time."""

    is_test_double = True

    def __init__(self, registry: SyntheticTestKeyAuthorizationRegistry,
                 reference_time: datetime):
        self._registry = registry
        self._reference_time = reference_time

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool:
        return (self._registry.signature_is_valid(key_id, payload, signature)
                and self._registry.authorized_at(key_id, self._reference_time))

    def public_key_digest(self, key_id: str) -> str:
        return self._registry.public_key_digest(key_id)


_DEFAULT_AUTH_RESPONSE = object()


class SyntheticKeyAuthorizationAuthority:
    """TEST ONLY: explicit authenticated-authority response for one checkpoint."""

    def __init__(self, scope: Scope, record: CheckpointRecord,
                 basis=CheckpointKeyAuthorizationBasis.ACTIVE,
                 receipt_id=None, accepted_at=None,
                 response=_DEFAULT_AUTH_RESPONSE, error=None, verifier=None):
        self.scope = scope
        self.record = record
        self.basis = basis
        self.receipt_id = receipt_id
        self.accepted_at = accepted_at
        self.error = error
        self.calls = []
        verifier = verifier or FakeVerifier()
        default_response = CheckpointKeyAuthorization(
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            key_id=record.key_id,
            public_key_digest=verifier.public_key_digest(record.key_id),
            checkpoint_digest=checkpoint_identity(record),
            authority_id="synthetic-test-authority",
            authority_revision=1,
            authority_event_id="evt-s13-test-1",
            policy_version="test-policy-v1",
            basis=basis,
            receipt_id=receipt_id,
            accepted_at=accepted_at,
        )
        self.response = default_response if response is _DEFAULT_AUTH_RESPONSE else response

    async def authorize_checkpoint(self, scope: Scope, record: CheckpointRecord):
        self.calls.append((scope, record))
        if self.error is not None:
            raise self.error
        return self.response


_DEFAULT_LATESTNESS_RESPONSE = object()


class SyntheticLatestnessAuthority:
    """TEST ONLY: synthetic provider receipt bound to the exact returned record."""

    is_test_double = True

    def __init__(self, response=_DEFAULT_LATESTNESS_RESPONSE, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def attest_latest(self, scope: Scope, record: CheckpointRecord):
        self.calls.append((scope, record))
        if self.error is not None:
            raise self.error
        if self.response is not _DEFAULT_LATESTNESS_RESPONSE:
            return self.response
        proof = hashlib.sha256(
            b"S13 TEST ONLY latestness receipt|" + checkpoint_identity(record).encode(),
        ).hexdigest()
        return CheckpointLatestnessEvidence(
            tenant_id=scope.tenant_id,
            company_id=scope.company_id,
            checkpoint_digest=checkpoint_identity(record),
            provider_id=record.sink_id,
            provider_revision=7,
            authority_id="synthetic-latestness-authority",
            authority_revision=3,
            authority_event_id="evt-s13-latestness-1",
            policy_version="test-latestness-v1",
            proof_digest=proof,
        )


class SlowLatestnessAuthority(SyntheticLatestnessAuthority):
    async def attest_latest(self, scope: Scope, record: CheckpointRecord):
        self.calls.append((scope, record))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    cancelled = False


def make_coordinator(*args, latestness_authority=_DEFAULT_LATESTNESS_RESPONSE, **kwargs):
    """Supply an explicit test authority to legacy contract scenarios by default."""
    if latestness_authority is _DEFAULT_LATESTNESS_RESPONSE:
        latestness_authority = SyntheticLatestnessAuthority()
    return LifecycleCoordinator(*args, latestness_authority=latestness_authority, **kwargs)


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


class TraceLedger(Ledger):
    """Records every read-only lifecycle dependency call for effect-boundary assertions."""

    async def lifecycle_checkpoint_suffix(self, scope, checkpoint_seq, checkpoint_hash):
        self.calls.append(("suffix", scope))
        return await super().lifecycle_checkpoint_suffix(
            scope, checkpoint_seq, checkpoint_hash,
        )


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
                result = asyncio.run(make_coordinator(
                    Ledger(response=chain_response, calls=calls), sink, FakeVerifier()
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, LifecycleReason.CHAIN_INVALID)
                self.assertEqual(calls, [("chain", SCOPE)])

    def test_dict_subclass_with_raising_get_maps_to_chain_invalid(self):
        calls = []
        result = asyncio.run(make_coordinator(
            Ledger(response=ExplodingGetDict(ok=True, count=9), calls=calls),
            Sink(calls, signed_record()), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_INVALID)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_chain_exception_maps_to_fixed_reason_without_sink_call(self):
        calls = []
        result = asyncio.run(make_coordinator(
            Ledger(error=RuntimeError("secret chain detail"), calls=calls),
            Sink(calls, signed_record()), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHAIN_UNAVAILABLE)
        self.assertEqual(calls, [("chain", SCOPE)])

    def test_chain_timeout_maps_to_chain_unavailable_without_provider_call(self):
        calls = []
        result = asyncio.run(make_coordinator(
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
                result = asyncio.run(make_coordinator(
                    Ledger(calls=calls), Sink(calls, record=record, error=error), FakeVerifier(),
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, expected)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertNotIn("private detail", repr(result))

    def test_checkpoint_latest_timeout_maps_to_checkpoint_unavailable(self):
        calls = []
        result = asyncio.run(make_coordinator(
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
                    make_coordinator(Ledger(), Sink([]), FakeVerifier(),
                                         dependency_timeout_seconds=timeout)

    def test_wrong_scope_record_is_rejected_before_signature_check(self):
        calls = []
        result = asyncio.run(make_coordinator(
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
                result = asyncio.run(make_coordinator(
                    Ledger(), Sink([], candidate), verifier,
                ).preflight(SCOPE))
                self.assertEqual(result.status, LifecycleStatus.NOT_READY)
                self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
                self.assertIsNone(result.checkpoint_seq)

    def test_missing_latestness_authority_fails_closed_before_key_authorization(self):
        record = signed_record(seq=7)
        calls = []
        key_authority = SyntheticKeyAuthorizationAuthority(SCOPE, record)
        result = asyncio.run(_BaseLifecycleCoordinator(
            Ledger(calls=calls), EffectCountingSink(calls, record), FakeVerifier(),
            key_authority=key_authority,
        ).preflight(SCOPE))

        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE)
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])
        self.assertEqual(key_authority.calls, [])

    def test_latestness_authority_exception_and_timeout_fail_closed(self):
        record = signed_record(seq=7)
        for authority, timeout, expected_cancelled in (
            (SyntheticLatestnessAuthority(error=RuntimeError("private provider detail")), 0.1, None),
            (SlowLatestnessAuthority(), 0.001, True),
        ):
            with self.subTest(authority=type(authority).__name__):
                calls = []
                result = asyncio.run(_BaseLifecycleCoordinator(
                    Ledger(calls=calls), EffectCountingSink(calls, record), FakeVerifier(),
                    key_authority=SyntheticKeyAuthorizationAuthority(SCOPE, record),
                    latestness_authority=authority,
                    dependency_timeout_seconds=timeout,
                ).preflight(SCOPE))

                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                if expected_cancelled:
                    self.assertTrue(authority.cancelled)

    def test_latestness_evidence_must_bind_scope_record_provider_and_revisions(self):
        record = signed_record(seq=7)
        valid = asyncio.run(SyntheticLatestnessAuthority().attest_latest(SCOPE, record))
        malformed = (
            replace(valid, tenant_id="other-tenant"),
            replace(valid, company_id="other-company"),
            replace(valid, checkpoint_digest="not-a-digest"),
            replace(valid, checkpoint_digest="0" * 64),
            replace(valid, provider_id="other-provider"),
            replace(valid, provider_revision=0),
            replace(valid, provider_revision=True),
            replace(valid, authority_id=""),
            replace(valid, authority_revision=0),
            replace(valid, authority_event_id=""),
            replace(valid, policy_version=""),
            replace(valid, proof_digest="not-a-digest"),
            object(),
        )
        for evidence in malformed:
            with self.subTest(evidence_type=type(evidence).__name__,
                              provider_revision=getattr(evidence, "provider_revision", None)):
                calls = []
                authority = SyntheticLatestnessAuthority(response=evidence)
                key_authority = SyntheticKeyAuthorizationAuthority(SCOPE, record)
                result = asyncio.run(_BaseLifecycleCoordinator(
                    Ledger(calls=calls), EffectCountingSink(calls, record), FakeVerifier(),
                    key_authority=key_authority,
                    latestness_authority=authority,
                ).preflight(SCOPE))

                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_LATESTNESS_INVALID)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual(key_authority.calls, [])

    def test_latestness_authority_without_receipt_is_unavailable(self):
        record = signed_record(seq=7)
        calls = []
        result = asyncio.run(_BaseLifecycleCoordinator(
            Ledger(calls=calls), EffectCountingSink(calls, record), FakeVerifier(),
            latestness_authority=SyntheticLatestnessAuthority(response=None),
        ).preflight(SCOPE))

        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.CHECKPOINT_LATESTNESS_UNAVAILABLE)
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])

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
                result = asyncio.run(make_coordinator(
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
        result = asyncio.run(make_coordinator(
            Ledger(calls=calls), sink, verifier,
            key_authority=SyntheticKeyAuthorizationAuthority(
                SCOPE, record, verifier=verifier,
            ),
        ).preflight(SCOPE))

        # The TEST sink and a valid local ancestor do not authenticate provider latestness.
        # Readiness must remain disabled even when signature, scope, and suffix checks pass.
        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual((result.checkpoint_seq, result.chain_count), (7, 9))
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])
        self.assertEqual(sink.write_calls, 0)
        self.assertEqual(sink.read_back_calls, 0)

    def test_signed_at_without_authenticated_authority_does_not_authorize(self):
        record = signed_record(seq=7)
        calls = []
        ledger = TraceLedger(calls=calls)
        sink = EffectCountingSink(calls, record)
        authority = SyntheticKeyAuthorizationAuthority(SCOPE, record, response=None)

        result = asyncio.run(make_coordinator(
            ledger, sink, FakeVerifier(), key_authority=authority,
        ).preflight(SCOPE))

        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_DENIED)
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])
        self.assertEqual(len(authority.calls), 1)
        self.assertEqual([name for name, _ in calls], ["chain", "latest"])
        self.assertEqual((sink.write_calls, sink.read_back_calls), (0, 0))

    def test_authority_timeout_and_error_fail_closed_without_suffix_or_effects(self):
        record = signed_record(seq=7)
        for error in (RuntimeError("private authority failure"), TimeoutError()):
            with self.subTest(error=type(error).__name__):
                calls = []
                ledger = TraceLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                authority = SyntheticKeyAuthorizationAuthority(SCOPE, record, error=error)
                result = asyncio.run(make_coordinator(
                    ledger, sink, FakeVerifier(), key_authority=authority,
                ).preflight(SCOPE))

                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORITY_UNAVAILABLE)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual((sink.write_calls, sink.read_back_calls), (0, 0))

    def test_authority_evidence_must_bind_scope_key_checkpoint_and_history_fields(self):
        record = signed_record(seq=7)
        valid = SyntheticKeyAuthorizationAuthority(SCOPE, record).response
        bad_evidence = (
            replace(valid, tenant_id="other-tenant"),
            replace(valid, company_id="other-company"),
            replace(valid, key_id="other-key"),
            replace(valid, public_key_digest="not-a-digest"),
            replace(valid, public_key_digest="0" * 64),
            replace(valid, checkpoint_digest="0" * 64),
            replace(valid, authority_revision=0),
            replace(valid, authority_event_id=""),
            replace(valid, policy_version=""),
        )
        for evidence in bad_evidence:
            with self.subTest(evidence=evidence):
                calls = []
                ledger = TraceLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                authority = SyntheticKeyAuthorizationAuthority(
                    SCOPE, record, response=evidence,
                )
                result = asyncio.run(make_coordinator(
                    ledger, sink, FakeVerifier(), key_authority=authority,
                ).preflight(SCOPE))

                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_INVALID)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual((sink.write_calls, sink.read_back_calls), (0, 0))

    def test_routine_retirement_requires_distinct_receipt_and_aware_acceptance_time(self):
        record = signed_record(seq=7)
        routine = CheckpointKeyAuthorizationBasis.ROUTINE_RETIREMENT_RECEIPT
        valid_receipt = SyntheticKeyAuthorizationAuthority(
            SCOPE, record, basis=routine, receipt_id="receipt-1", accepted_at=NOW,
        ).response
        invalid_responses = (
            replace(valid_receipt, receipt_id=None),
            replace(valid_receipt, receipt_id=""),
            replace(valid_receipt, accepted_at=None),
            replace(valid_receipt, accepted_at=NOW.replace(tzinfo=None)),
        )
        for evidence in invalid_responses:
            with self.subTest(evidence=evidence):
                ledger = TraceLedger()
                sink = EffectCountingSink([], record)
                result = asyncio.run(make_coordinator(
                    ledger, sink, FakeVerifier(),
                    key_authority=SyntheticKeyAuthorizationAuthority(
                        SCOPE, record, response=evidence,
                    ),
                ).preflight(SCOPE))

                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_KEY_AUTHORIZATION_INVALID)
                self.assertEqual(ledger.calls, [("chain", SCOPE)])
                self.assertEqual((sink.write_calls, sink.read_back_calls), (0, 0))

        ledger = TraceLedger()
        sink = EffectCountingSink([], record)
        accepted = asyncio.run(make_coordinator(
            ledger, sink, FakeVerifier(),
            key_authority=SyntheticKeyAuthorizationAuthority(
                SCOPE, record, response=valid_receipt,
            ),
        ).preflight(SCOPE))
        self.assertIs(accepted.status, LifecycleStatus.NOT_READY)
        self.assertIs(accepted.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)

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
                result = asyncio.run(make_coordinator(
                    ledger, sink, FakeVerifier(),
                    key_authority=SyntheticKeyAuthorizationAuthority(SCOPE, record),
                ).preflight(SCOPE))
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, expected_reason)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual(sink.write_calls, 0)
                self.assertEqual(sink.read_back_calls, 0)

    def test_synthetic_key_authorization_uses_explicit_reference_time_and_fails_closed(self):
        valid_from = datetime(2026, 11, 1, tzinfo=UTC)
        valid_until = datetime(2026, 12, 1, tzinfo=UTC)
        inside_window = datetime(2026, 11, 15, tzinfo=UTC)
        private_key = _synthetic_test_key("authorization-window")
        key_id = "s13-test-window-key"
        # signed_at intentionally predates authorization; it is signed payload data, not
        # the authorization clock. Authorization uses only the injected reference time.
        record = ed25519_record(
            SCOPE, 7, key_id, private_key, signed_at=valid_from - timedelta(days=30),
        )
        public_keys = {key_id: public_key_bytes(private_key)}
        window = {"valid_from": valid_from, "valid_until": valid_until}
        cases = (
            ("authorized at inclusive start", {"state": "AUTHORIZED", **window},
             valid_from, True),
            ("authorized inside window", {"state": "AUTHORIZED", **window},
             inside_window, True),
            ("exclusive end", {"state": "AUTHORIZED", **window}, valid_until, False),
            ("before window", {"state": "AUTHORIZED", **window},
             valid_from - timedelta(microseconds=1), False),
            ("missing start", {"state": "AUTHORIZED", "valid_until": valid_until},
             inside_window, False),
            ("invalid start", {"state": "AUTHORIZED", "valid_from": "bad",
                                "valid_until": valid_until}, inside_window, False),
            ("reversed window", {"state": "AUTHORIZED", "valid_from": valid_until,
                                  "valid_until": valid_from}, inside_window, False),
            ("revoked", {"state": "REVOKED", **window}, inside_window, False),
            ("unknown", {"state": "UNKNOWN", **window}, inside_window, False),
            ("missing state", window, inside_window, False),
            ("malformed state", "AUTHORIZED", inside_window, False),
            ("retired without history rule", {"state": "RETIRED"}, inside_window, False),
            ("retired with explicit synthetic rule",
             {"state": "RETIRED", "historical_rule": window}, inside_window, True),
            ("retired rule exclusive end",
             {"state": "RETIRED", "historical_rule": window}, valid_until, False),
        )

        for label, state, reference_time, expected in cases:
            with self.subTest(case=label):
                states = {key_id: state} if state is not None else {}
                registry = SyntheticTestKeyAuthorizationRegistry(public_keys, states)
                # Crypto validity is independent of authorization state and time.
                self.assertTrue(registry.signature_is_valid(
                    key_id, record.signing_payload(), record.signature,
                ))
                self.assertEqual(
                    registry.authorized_at(key_id, reference_time), expected,
                )
                verifier = SyntheticTestAuthorizationVerifier(registry, reference_time)
                self.assertEqual(
                    verifier.verify(key_id, record.signing_payload(), record.signature),
                    expected,
                )

        # Conversely, signed_at is inside the key window here but the injected verification
        # time is at the exclusive end, so the signature remains valid while auth is denied.
        record_signed_inside_window = ed25519_record(
            SCOPE, 8, key_id, private_key,
            signed_at=valid_from + timedelta(days=1),
        )
        authorized_registry = SyntheticTestKeyAuthorizationRegistry(
            public_keys, {key_id: {"state": "AUTHORIZED", **window}},
        )
        self.assertTrue(authorized_registry.signature_is_valid(
            key_id, record_signed_inside_window.signing_payload(),
            record_signed_inside_window.signature,
        ))
        self.assertFalse(SyntheticTestAuthorizationVerifier(
            authorized_registry, valid_until,
        ).verify(key_id, record_signed_inside_window.signing_payload(),
                 record_signed_inside_window.signature))

        # An authorized current key does not authorize a prior key implicitly. The prior
        # key needs its own explicit state/rule; no fallback, grace period, or auto-previous
        # behavior is part of this TEST contract.
        current_key_id = "s13-test-current-window-key"
        registry = SyntheticTestKeyAuthorizationRegistry(
            {**public_keys, current_key_id: public_key_bytes(_synthetic_test_key("current"))},
            {key_id: {"state": "RETIRED"},
             current_key_id: {"state": "AUTHORIZED", **window}},
        )
        self.assertFalse(registry.authorized_at(key_id, inside_window))
        self.assertTrue(registry.authorized_at(current_key_id, inside_window))
        previous_verifier = SyntheticTestAuthorizationVerifier(registry, inside_window)
        self.assertTrue(registry.signature_is_valid(
            key_id, record.signing_payload(), record.signature,
        ))
        self.assertFalse(previous_verifier.verify(
            key_id, record.signing_payload(), record.signature,
        ))

    def test_synthetic_authorization_preflight_is_read_only_and_never_ready(self):
        valid_from = datetime(2026, 11, 1, tzinfo=UTC)
        valid_until = datetime(2026, 12, 1, tzinfo=UTC)
        reference_time = datetime(2026, 11, 15, tzinfo=UTC)
        key_id = "s13-test-authorized-key"
        private_key = _synthetic_test_key("authorized-preflight")
        record = ed25519_record(
            SCOPE, 7, key_id, private_key, signed_at=valid_from - timedelta(days=30),
        )
        states = {key_id: {"state": "AUTHORIZED", "valid_from": valid_from,
                           "valid_until": valid_until}}
        registry = SyntheticTestKeyAuthorizationRegistry(
            {key_id: public_key_bytes(private_key)}, states,
        )
        verifier = SyntheticTestAuthorizationVerifier(registry, reference_time)
        self.assertTrue(registry.signature_is_valid(
            key_id, record.signing_payload(), record.signature,
        ))
        self.assertTrue(registry.authorized_at(key_id, reference_time))

        calls = []
        ledger = TraceLedger(calls=calls)
        sink = EffectCountingSink(calls, record)
        result = asyncio.run(make_coordinator(
            ledger, sink, verifier,
            key_authority=SyntheticKeyAuthorizationAuthority(
                SCOPE, record, verifier=verifier,
            ),
        ).preflight(SCOPE))

        self.assertIs(result.status, LifecycleStatus.NOT_READY)
        self.assertIs(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual([name for name, _ in calls], ["chain", "latest", "suffix"])
        self.assertEqual((sink.write_calls, sink.read_back_calls), (0, 0))

    def test_unauthorized_synthetic_keys_fail_preflight_before_suffix_or_effects(self):
        valid_from = datetime(2026, 11, 1, tzinfo=UTC)
        valid_until = datetime(2026, 12, 1, tzinfo=UTC)
        reference_time = datetime(2026, 11, 15, tzinfo=UTC)
        key_id = "s13-test-unauthorized-key"
        private_key = _synthetic_test_key("unauthorized-preflight")
        record = ed25519_record(SCOPE, 7, key_id, private_key)
        public_keys = {key_id: public_key_bytes(private_key)}
        denied_states = (
            ("revoked", {"state": "REVOKED", "valid_from": valid_from,
                          "valid_until": valid_until}),
            ("unknown", {"state": "UNKNOWN", "valid_from": valid_from,
                          "valid_until": valid_until}),
            ("missing window", {"state": "AUTHORIZED", "valid_from": valid_from}),
            ("unexpected authorization metadata", {"state": "AUTHORIZED",
             "valid_from": valid_from, "valid_until": valid_until, "fallback": True}),
            ("reversed window", {"state": "AUTHORIZED", "valid_from": valid_until,
                                  "valid_until": valid_from}),
            ("retired without historical rule", {"state": "RETIRED"}),
            ("absent state", None),
        )
        for label, state in denied_states:
            with self.subTest(case=label):
                registry = SyntheticTestKeyAuthorizationRegistry(
                    public_keys, {} if state is None else {key_id: state},
                )
                self.assertTrue(registry.signature_is_valid(
                    key_id, record.signing_payload(), record.signature,
                ))
                verifier = SyntheticTestAuthorizationVerifier(registry, reference_time)
                self.assertFalse(verifier.verify(
                    key_id, record.signing_payload(), record.signature,
                ))

                calls = []
                ledger = TraceLedger(calls=calls)
                sink = EffectCountingSink(calls, record)
                result = asyncio.run(
                    make_coordinator(ledger, sink, verifier).preflight(SCOPE),
                )
                self.assertIs(result.status, LifecycleStatus.NOT_READY)
                self.assertIs(result.reason, LifecycleReason.CHECKPOINT_INVALID)
                self.assertEqual([name for name, _ in calls], ["chain", "latest"])
                self.assertEqual((sink.write_calls, sink.read_back_calls), (0, 0))

    def test_malformed_latest_values_map_to_checkpoint_invalid(self):
        valid = signed_record()
        bool_sequence = CheckpointRecord(**{**valid.__dict__, "seq": True})
        for candidate in (object(), bool_sequence):
            with self.subTest(candidate_type=type(candidate).__name__,
                              seq=getattr(candidate, "seq", None)):
                result = asyncio.run(make_coordinator(
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
        result = asyncio.run(make_coordinator(
            Ledger(), Sink([], malformed), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
        self.assertIsNone(result.checkpoint_seq)

    def test_exact_record_with_malformed_scope_equality_is_invalid(self):
        malformed = signed_record()
        object.__setattr__(malformed, "tenant_id", MalformedScopeField())
        result = asyncio.run(make_coordinator(
            Ledger(), Sink([], malformed), FakeVerifier(),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.CHECKPOINT_INVALID)
        self.assertIsNone(result.checkpoint_seq)

    def test_valid_preflight_returns_checkpoint_evidence_but_never_ready(self):
        result = asyncio.run(make_coordinator(
            Ledger(), Sink([], signed_record(seq=7)), FakeVerifier(),
            key_authority=SyntheticKeyAuthorizationAuthority(
                SCOPE, signed_record(seq=7),
            ),
        ).preflight(SCOPE))
        self.assertEqual(result.status, LifecycleStatus.NOT_READY)
        self.assertEqual(result.reason, LifecycleReason.SHARED_FENCE_UNAVAILABLE)
        self.assertEqual(result.checkpoint_seq, 7)
        self.assertEqual(result.checkpoint_hash, f"{7:064x}")
        self.assertEqual(result.chain_count, 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
