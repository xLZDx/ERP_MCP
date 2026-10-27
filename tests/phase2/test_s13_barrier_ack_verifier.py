"""Focused behavior tests for the S13 production acknowledgement trust boundary.

This module tests the production verifier with deterministic in-memory trust/registry ports. The
PostgreSQL candidate routines are qualified separately against a fresh invocation-owned cluster.
"""
from __future__ import annotations

import asyncio
import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from erp_mcp_private_writer.barrier_ack_protocol import (
    barrier_acknowledgement_ref,
    barrier_acknowledgement_signed_bytes,
)
from erp_mcp_private_writer.barrier_ack_verifier import (
    BarrierAcknowledgementTrustContext,
    BarrierAcknowledgementTrustRevisionStale,
    BarrierAcknowledgementVerifierError,
    ProductionBarrierAcknowledgementVerifier,
    _PROCESS_ATTESTATION_PREFIX,
)
from erp_mcp_private_writer.evidence_trust import (
    EvidenceScope,
    EvidenceTrustSnapshot,
    SignerKeyRef,
    TrustedProcessBinding,
    TrustedSigner,
)
from erp_mcp_private_writer.service import BarrierAcknowledgementRejected
from test_private_writer_barrier_ack import _acknowledgement


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
SCOPE = EvidenceScope("tenant-1", "company-1", "org-1", "a" * 64)
SUPERVISOR_KEY = SignerKeyRef("supervisor-key", "1")


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _attestation(process: TrustedProcessBinding) -> bytes:
    return _PROCESS_ATTESTATION_PREFIX + canonical_json_bytes({
        "attestation_version": "1",
        "process_instance_id": process.process_instance_id,
        "host_boot_id": process.host_boot_id,
        "service_id": process.service_id,
        "host_id": process.host_id,
        "os_pid": process.os_pid,
        "process_created_at": process.process_created_at.astimezone(UTC).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ),
        "supervisor_key_id": process.supervisor_key.key_id,
        "supervisor_key_version": process.supervisor_key.key_version,
    })


def _signed_ack(private_key: Ed25519PrivateKey | None = None):
    key = private_key or Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    unsigned = replace(_acknowledgement(), signed_at="2026-10-27T11:00:00.000000Z")
    return replace(unsigned, signature=key.sign(unsigned.signature_preimage()))


def _trust_context(ack, *, revision: str = "1", signer_scopes=None,
                   supervisor_scopes=None, revoked_at=None, bad_attestation=False):
    writer_private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    supervisor_private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    writer_key = SignerKeyRef(ack.key_id, ack.key_version)
    scope_set = signer_scopes if signer_scopes is not None else (SCOPE,)
    supervisor_scope_set = supervisor_scopes if supervisor_scopes is not None else (SCOPE,)
    writer = TrustedSigner(
        key=writer_key, public_key=_public_key(writer_private), signer_role="writer_receipt",
        service_id=ack.writer_service_id, host_id=ack.writer_host_id,
        allowed_scopes=scope_set, valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1), revoked_at=revoked_at,
        rotation_history=(writer_key,),
    )
    supervisor = TrustedSigner(
        key=SUPERVISOR_KEY, public_key=_public_key(supervisor_private),
        signer_role="completion_supervisor", service_id="supervisor-test",
        host_id=ack.writer_host_id, allowed_scopes=supervisor_scope_set,
        valid_from=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=1),
        revoked_at=revoked_at, rotation_history=(SUPERVISOR_KEY,),
    )
    process_unsigned = TrustedProcessBinding(
        process_instance_id=ack.writer_process_instance_id,
        host_boot_id=ack.host_boot_id, service_id=ack.writer_service_id,
        host_id=ack.writer_host_id, os_pid=321,
        process_created_at=datetime(2026, 10, 27, 10, 30, tzinfo=UTC),
        supervisor_key=SUPERVISOR_KEY, signature=b"s" * 64,
    )
    signature = supervisor_private.sign(_attestation(process_unsigned))
    if bad_attestation:
        signature = bytes([signature[0] ^ 1]) + signature[1:]
    process = replace(process_unsigned, signature=signature)
    snapshot = EvidenceTrustSnapshot(
        revision=revision, loaded_at=NOW, signers=(writer, supervisor),
        process_bindings=(process,), oracle_artifacts=(), outcome_version_floors=(),
    )
    return BarrierAcknowledgementTrustContext(snapshot, (SCOPE,))


def _replace_process_binding(context, **changes):
    process = context.snapshot.process_bindings[0]
    snapshot = replace(
        context.snapshot, process_bindings=(replace(process, **changes),),
    )
    return replace(context, snapshot=snapshot)


def _exact_record(ack) -> dict[str, object]:
    signed_bytes = barrier_acknowledgement_signed_bytes(ack)
    return {
        "acknowledgement_ref": barrier_acknowledgement_ref(ack),
        "barrier_id": str(ack.barrier_id), "base_fingerprint": ack.base_fingerprint,
        "tenant_id": ack.tenant_id, "company_id": ack.company_id,
        "lifecycle_epoch": ack.lifecycle_epoch,
        "barrier_origin_instance_id": ack.barrier_origin_instance_id,
        "barrier_origin_service_epoch": ack.barrier_origin_service_epoch,
        "call_ids": list(ack.call_ids), "writer_service_id": ack.writer_service_id,
        "writer_host_id": ack.writer_host_id, "host_boot_id": ack.host_boot_id,
        "writer_process_instance_id": ack.writer_process_instance_id,
        "process_attestation_ref": ack.process_attestation_ref,
        "writer_queue_epoch": ack.writer_queue_epoch, "local_queue_closed": True,
        "signed_at": ack.signed_at, "signed_bytes_hex": signed_bytes.hex(),
        "signature_hex": ack.signature.hex(),
        "signed_bytes_sha256": hashlib.sha256(signed_bytes).hexdigest(),
        "signer_key_id": ack.key_id, "signer_key_version": ack.key_version,
        "verified_at": "2026-10-27T12:00:00.000000Z",
    }


class TrustSource:
    def __init__(self, *contexts, events=None):
        self.contexts = list(contexts)
        self.calls = []
        self.events = events if events is not None else []

    async def load_barrier_snapshot(self, acknowledgement):
        self.calls.append(acknowledgement.barrier_id)
        if not self.contexts:
            raise AssertionError("unexpected trust reload")
        context = self.contexts.pop(0)
        self.events.append(f"trust:{context.snapshot.revision}")
        return context


class Registrar:
    def __init__(self, *, prior=None, register_results=(), events=None):
        self.prior = prior
        self.register_results = list(register_results)
        self.lookups = []
        self.registrations = []
        self.events = events if events is not None else []

    async def lookup_barrier_acknowledgement(self, barrier_id):
        self.lookups.append(barrier_id)
        self.events.append("lookup")
        return self.prior

    async def register_barrier_acknowledgement(
            self, acknowledgement, *, acknowledgement_ref, signed_bytes, trust_revision):
        self.registrations.append((acknowledgement_ref, signed_bytes, trust_revision))
        self.events.append(f"register:{trust_revision}")
        if self.register_results:
            outcome = self.register_results.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        self.prior = _exact_record(acknowledgement)
        return acknowledgement_ref


def _verifier(trust, registrar):
    return ProductionBarrierAcknowledgementVerifier(trust, registrar, timeout_seconds=1.0)


class S13ProductionBarrierAcknowledgementVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_signed_ack_with_independent_supervisor_is_registered(self):
        ack = _signed_ack()
        trust = TrustSource(_trust_context(ack))
        registrar = Registrar()

        ref = await _verifier(trust, registrar).verify_and_store(ack)

        self.assertEqual(ref, barrier_acknowledgement_ref(ack))
        self.assertEqual(len(trust.calls), 1)
        self.assertEqual(registrar.lookups, [ack.barrier_id])
        self.assertEqual(registrar.registrations, [(
            ref, barrier_acknowledgement_signed_bytes(ack), 1,
        )])

    async def test_signer_scope_signature_and_process_attestation_fail_before_registry(self):
        ack = _signed_ack()
        wrong_scope = EvidenceScope("tenant-1", "company-1", "other-org", "a" * 64)
        cases = (
            ("scope", _trust_context(ack, signer_scopes=(wrong_scope,)), ack),
            ("signature", _trust_context(ack), replace(
                ack, signature=bytes([ack.signature[0] ^ 1]) + ack.signature[1:],
            )),
            ("process binding", _replace_process_binding(
                _trust_context(ack), host_id="other-host",
            ), ack),
            ("attestation", _trust_context(ack, bad_attestation=True), ack),
            ("supervisor scope", _trust_context(
                ack, supervisor_scopes=(wrong_scope,),
            ), ack),
        )
        for label, context, candidate in cases:
            with self.subTest(label=label):
                trust = TrustSource(context)
                registrar = Registrar()
                with self.assertRaises(BarrierAcknowledgementRejected):
                    await _verifier(trust, registrar).verify_and_store(candidate)
                self.assertEqual(registrar.lookups, [ack.barrier_id])
                self.assertEqual(registrar.registrations, [])

    async def test_exact_replay_precedes_trust_reload_even_after_simulated_revocation(self):
        ack = _signed_ack()
        # A revoked signer would fail a fresh verification. Existing exact immutable proof must
        # be resolved first, without asking the trust provider for its current status.
        revoked = _trust_context(ack, revoked_at=NOW - timedelta(seconds=1))
        trust = TrustSource(revoked)
        registrar = Registrar(prior=_exact_record(ack))

        ref = await _verifier(trust, registrar).verify_and_store(ack)

        self.assertEqual(ref, barrier_acknowledgement_ref(ack))
        self.assertEqual(registrar.lookups, [ack.barrier_id])
        self.assertEqual(registrar.registrations, [])
        self.assertEqual(trust.calls, [])

    async def test_stale_revision_does_lookup_before_one_fresh_snapshot_retry(self):
        ack = _signed_ack()
        events = []
        trust = TrustSource(_trust_context(ack, revision="1"),
                            _trust_context(ack, revision="2"), events=events)
        registrar = Registrar(register_results=(
            BarrierAcknowledgementTrustRevisionStale(),
        ), events=events)

        ref = await _verifier(trust, registrar).verify_and_store(ack)

        self.assertEqual(ref, barrier_acknowledgement_ref(ack))
        self.assertEqual(registrar.lookups, [ack.barrier_id, ack.barrier_id])
        self.assertEqual([entry[2] for entry in registrar.registrations], [1, 2])
        self.assertEqual(len(trust.calls), 2)
        self.assertEqual(events, [
            "lookup", "trust:1", "register:1", "lookup", "trust:2", "register:2",
        ])

    async def test_stale_retry_exact_winner_replays_before_revoked_snapshot_reload(self):
        ack = _signed_ack()
        revoked = _trust_context(ack, revision="2", revoked_at=NOW - timedelta(seconds=1))
        trust = TrustSource(_trust_context(ack, revision="1"), revoked)
        registrar = Registrar(register_results=(BarrierAcknowledgementTrustRevisionStale(),))

        async def lookup_with_competing_exact_commit(barrier_id):
            registrar.lookups.append(barrier_id)
            if len(registrar.lookups) == 2:
                registrar.prior = _exact_record(ack)
            return registrar.prior

        registrar.lookup_barrier_acknowledgement = lookup_with_competing_exact_commit
        ref = await _verifier(trust, registrar).verify_and_store(ack)

        self.assertEqual(ref, barrier_acknowledgement_ref(ack))
        self.assertEqual(len(registrar.lookups), 2)
        self.assertEqual(len(registrar.registrations), 1)
        self.assertEqual(len(trust.calls), 1)

    async def test_second_stale_revision_fails_closed_after_exactly_one_retry(self):
        ack = _signed_ack()
        trust = TrustSource(_trust_context(ack, revision="1"),
                            _trust_context(ack, revision="2"))
        registrar = Registrar(register_results=(
            BarrierAcknowledgementTrustRevisionStale(),
            BarrierAcknowledgementTrustRevisionStale(),
        ))

        with self.assertRaises(BarrierAcknowledgementVerifierError) as raised:
            await _verifier(trust, registrar).verify_and_store(ack)

        self.assertEqual(raised.exception.code, "BARRIER_ACK_TRUST_REVISION_UNSTABLE")
        self.assertEqual(len(registrar.registrations), 2)
        self.assertEqual(registrar.lookups, [ack.barrier_id, ack.barrier_id])
        self.assertEqual(len(trust.calls), 2)

    async def test_timeout_and_cancellation_after_commit_remain_exactly_replayable(self):
        for failure in (TimeoutError("response timed out"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__):
                ack = _signed_ack()
                trust = TrustSource(_trust_context(ack))
                registrar = Registrar()

                async def commit_then_lose_response(
                        acknowledgement, *, acknowledgement_ref, signed_bytes, trust_revision):
                    registrar.registrations.append((
                        acknowledgement_ref, signed_bytes, trust_revision,
                    ))
                    registrar.prior = _exact_record(acknowledgement)
                    raise failure

                registrar.register_barrier_acknowledgement = commit_then_lose_response
                verifier = _verifier(trust, registrar)
                with self.assertRaises(type(failure)):
                    await verifier.verify_and_store(ack)

                # Retrying by the same barrier ID returns the committed exact tuple without
                # another trust load or registration, even though the first response was lost.
                ref = await verifier.verify_and_store(ack)
                self.assertEqual(ref, barrier_acknowledgement_ref(ack))
                self.assertEqual(registrar.lookups, [ack.barrier_id, ack.barrier_id])
                self.assertEqual(len(registrar.registrations), 1)
                self.assertEqual(len(trust.calls), 1)


if __name__ == "__main__":
    unittest.main()
