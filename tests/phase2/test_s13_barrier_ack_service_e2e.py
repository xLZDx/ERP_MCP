"""S13 private-writer quiescence journey through the production acknowledgement verifier.

The test uses a deterministic in-memory admission store and acknowledgement registry; it exercises
the real service, canonical Ed25519 acknowledgement verifier, process attestation, and exact replay
contract without PostgreSQL, network, 1C, COM, or local key material.
"""
from __future__ import annotations

import asyncio
import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.write_port import BarrierAcknowledgement
from erp_mcp_private_writer.barrier_ack_protocol import (
    barrier_acknowledgement_ref,
    barrier_acknowledgement_signed_bytes,
)
from erp_mcp_private_writer.barrier_ack_verifier import (
    BarrierAcknowledgementTrustContext,
    ProductionBarrierAcknowledgementVerifier,
)
from erp_mcp_private_writer.evidence_trust import (
    EvidenceScope,
    EvidenceTrustSnapshot,
    SignerKeyRef,
    TrustedProcessBinding,
    TrustedSigner,
)
from erp_mcp_private_writer.service import (
    AdmissionStoreError,
    BarrierProgress,
    BarrierSnapshot,
    PrivateWriterService,
    ServiceError,
    StartupRecoveryState,
)


BASE = "a" * 64
SCOPE = Scope("tenant-1", "company-1")
ORG = "org-1"
BARRIER_ID = UUID("00000000-0000-4000-8000-000000000001")
HOST_BOOT_ID = "00000000-0000-4000-8000-000000000003"
WRITER_INSTANCE_ID = "00000000-0000-4000-8000-000000000004"
WRITER_SEED = bytes(range(32))
SUPERVISOR_SEED = bytes(range(32, 64))
PROCESS_ATTESTATION_PREFIX = b"ERP_MCP_R2:S13:PROCESS-INSTANCE:v1\n"


def _private_key(seed: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _signed_acknowledgement(origin_id: str, origin_epoch: int, queue_epoch: int = 3
                            ) -> BarrierAcknowledgement:
    unsigned = BarrierAcknowledgement(
        base_fingerprint=BASE,
        tenant_id=SCOPE.tenant_id,
        company_id=SCOPE.company_id,
        lifecycle_epoch=5,
        barrier_id=BARRIER_ID,
        barrier_origin_instance_id=origin_id,
        barrier_origin_service_epoch=origin_epoch,
        call_ids=(),
        key_id="writer-key",
        key_version="1",
        writer_service_id="writer-test",
        writer_host_id="host-test",
        host_boot_id=HOST_BOOT_ID,
        writer_process_instance_id=WRITER_INSTANCE_ID,
        process_attestation_ref=WRITER_INSTANCE_ID,
        writer_queue_epoch=queue_epoch,
        local_queue_closed=True,
        signed_at="2026-10-26T10:00:00.000000Z",
        signature=b"\x00" * 64,
    )
    return replace(unsigned, signature=_private_key(WRITER_SEED).sign(
        unsigned.signature_preimage(),
    ))


def _trusted_context(acknowledgement: BarrierAcknowledgement
                     ) -> BarrierAcknowledgementTrustContext:
    supervisor_ref = SignerKeyRef("supervisor-key", "1")
    writer_ref = SignerKeyRef(acknowledgement.key_id, acknowledgement.key_version)
    scope = EvidenceScope(SCOPE.tenant_id, SCOPE.company_id, ORG, BASE)
    created_at = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    attestation = PROCESS_ATTESTATION_PREFIX + canonical_json_bytes({
        "attestation_version": "1",
        "process_instance_id": WRITER_INSTANCE_ID,
        "host_boot_id": HOST_BOOT_ID,
        "service_id": acknowledgement.writer_service_id,
        "host_id": acknowledgement.writer_host_id,
        "os_pid": 4242,
        "process_created_at": "2026-10-26T09:00:00.000000Z",
        "supervisor_key_id": supervisor_ref.key_id,
        "supervisor_key_version": supervisor_ref.key_version,
    })
    process = TrustedProcessBinding(
        process_instance_id=WRITER_INSTANCE_ID,
        host_boot_id=HOST_BOOT_ID,
        service_id=acknowledgement.writer_service_id,
        host_id=acknowledgement.writer_host_id,
        os_pid=4242,
        process_created_at=created_at,
        supervisor_key=supervisor_ref,
        signature=_private_key(SUPERVISOR_SEED).sign(attestation),
    )
    valid_from = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    valid_until = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    writer = TrustedSigner(
        key=writer_ref,
        public_key=_public_key(_private_key(WRITER_SEED)),
        signer_role="writer_receipt",
        service_id=acknowledgement.writer_service_id,
        host_id=acknowledgement.writer_host_id,
        allowed_scopes=(scope,),
        valid_from=valid_from,
        valid_until=valid_until,
        revoked_at=None,
        rotation_history=(writer_ref,),
    )
    supervisor = TrustedSigner(
        key=supervisor_ref,
        public_key=_public_key(_private_key(SUPERVISOR_SEED)),
        signer_role="completion_supervisor",
        service_id="supervisor-test",
        host_id=acknowledgement.writer_host_id,
        allowed_scopes=(scope,),
        valid_from=valid_from,
        valid_until=valid_until,
        revoked_at=None,
        rotation_history=(supervisor_ref,),
    )
    snapshot = EvidenceTrustSnapshot(
        revision="7",
        loaded_at=datetime(2026, 10, 27, 0, 0, tzinfo=UTC),
        signers=(writer, supervisor),
        process_bindings=(process,),
        oracle_artifacts=(),
        outcome_version_floors=(),
    )
    return BarrierAcknowledgementTrustContext(snapshot, (scope,))


class InMemoryTrustSource:
    def __init__(self) -> None:
        self.loads: list[BarrierAcknowledgement] = []

    async def load_barrier_snapshot(self, acknowledgement: BarrierAcknowledgement
                                    ) -> BarrierAcknowledgementTrustContext:
        self.loads.append(acknowledgement)
        return _trusted_context(acknowledgement)


class InMemoryAcknowledgementRegistry:
    def __init__(self, *, lose_first_response: bool = False) -> None:
        self.records: dict[UUID, dict[str, object]] = {}
        self.lookup_calls = 0
        self.registration_calls = 0
        self.lose_first_response = lose_first_response

    async def lookup_barrier_acknowledgement(self, barrier_id: UUID
                                             ) -> dict[str, object] | None:
        self.lookup_calls += 1
        return self.records.get(barrier_id)

    async def register_barrier_acknowledgement(
            self, acknowledgement: BarrierAcknowledgement, *, acknowledgement_ref: str,
            signed_bytes: bytes, trust_revision: int) -> str:
        assert trust_revision == 7
        assert signed_bytes == barrier_acknowledgement_signed_bytes(acknowledgement)
        self.registration_calls += 1
        self.records[acknowledgement.barrier_id] = _registry_record(
            acknowledgement, acknowledgement_ref, signed_bytes,
        )
        if self.lose_first_response:
            self.lose_first_response = False
            raise ConnectionError("registration response lost after durable insert")
        return acknowledgement_ref


def _registry_record(acknowledgement: BarrierAcknowledgement,
                     reference: str, signed_bytes: bytes) -> dict[str, object]:
    return {
        "acknowledgement_ref": reference,
        "barrier_id": str(acknowledgement.barrier_id),
        "base_fingerprint": acknowledgement.base_fingerprint,
        "tenant_id": acknowledgement.tenant_id,
        "company_id": acknowledgement.company_id,
        "lifecycle_epoch": acknowledgement.lifecycle_epoch,
        "barrier_origin_instance_id": acknowledgement.barrier_origin_instance_id,
        "barrier_origin_service_epoch": acknowledgement.barrier_origin_service_epoch,
        "call_ids": list(acknowledgement.call_ids),
        "writer_service_id": acknowledgement.writer_service_id,
        "writer_host_id": acknowledgement.writer_host_id,
        "host_boot_id": acknowledgement.host_boot_id,
        "writer_process_instance_id": acknowledgement.writer_process_instance_id,
        "process_attestation_ref": acknowledgement.process_attestation_ref,
        "writer_queue_epoch": acknowledgement.writer_queue_epoch,
        "local_queue_closed": acknowledgement.local_queue_closed,
        "signed_at": acknowledgement.signed_at,
        "signed_bytes_hex": signed_bytes.hex(),
        "signature_hex": acknowledgement.signature.hex(),
        "signed_bytes_sha256": hashlib.sha256(signed_bytes).hexdigest(),
        "signer_key_id": acknowledgement.key_id,
        "signer_key_version": acknowledgement.key_version,
        "verified_at": "2026-10-27T00:01:00.000000Z",
    }


class InMemoryAdmissionStore:
    """Per-test barrier store that records admission closure before quiescence completion."""

    def __init__(self, current_epoch: int = 4) -> None:
        self.current_epoch = current_epoch
        self.snapshot: BarrierSnapshot | None = None
        self.events: list[str] = []
        self.finish_calls: list[str] = []

    async def lookup_barrier(self, barrier_id: UUID) -> BarrierSnapshot | None:
        assert barrier_id == BARRIER_ID
        return self.snapshot

    async def close_and_advance(
            self, base_fingerprint: str, scope: Scope, expected_current_epoch: int,
            barrier_id: UUID, origin_instance_id: str, origin_service_epoch: int,
    ) -> BarrierSnapshot:
        assert base_fingerprint == BASE
        assert scope == SCOPE
        if expected_current_epoch != self.current_epoch:
            raise AdmissionStoreError("STALE_EPOCH", sqlstate="P0001")
        self.current_epoch += 1
        self.snapshot = BarrierSnapshot(
            scope=scope,
            base_fingerprint=base_fingerprint,
            barrier_id=barrier_id,
            expected_current_epoch=expected_current_epoch,
            epoch=self.current_epoch,
            barrier_origin_instance_id=origin_instance_id,
            barrier_origin_service_epoch=origin_service_epoch,
            call_ids=(),
            progress=BarrierProgress.CLOSED_WITH_HOLD,
            unresolved_call_ids=(),
        )
        self.events.append("ADMISSION_CLOSED")
        return self.snapshot

    async def finish_barrier(
            self, snapshot: BarrierSnapshot, acknowledgement_ref: str,
            service_instance_id: str, service_epoch: int,
    ) -> BarrierSnapshot:
        assert self.snapshot is snapshot
        assert snapshot.progress is BarrierProgress.CLOSED_WITH_HOLD
        assert service_instance_id == snapshot.barrier_origin_instance_id
        assert service_epoch == snapshot.barrier_origin_service_epoch
        self.finish_calls.append(acknowledgement_ref)
        self.snapshot = BarrierSnapshot(
            scope=snapshot.scope,
            base_fingerprint=snapshot.base_fingerprint,
            barrier_id=snapshot.barrier_id,
            expected_current_epoch=snapshot.expected_current_epoch,
            epoch=snapshot.epoch,
            barrier_origin_instance_id=snapshot.barrier_origin_instance_id,
            barrier_origin_service_epoch=snapshot.barrier_origin_service_epoch,
            call_ids=snapshot.call_ids,
            progress=BarrierProgress.QUIESCED,
            unresolved_call_ids=(),
            acknowledgement_ref=acknowledgement_ref,
            acknowledgement_digest=hashlib.sha256(acknowledgement_ref.encode()).digest(),
            quiesced_at=datetime.now(UTC),
        )
        self.events.append("BARRIER_QUIESCED")
        return self.snapshot


class InMemoryWriter:
    def __init__(self) -> None:
        self.acknowledgements: list[BarrierAcknowledgement] = []

    async def quiesce(self, base_fingerprint: str, tenant_id: str, company_id: str,
                      lifecycle_epoch: int, barrier_id: UUID, origin_instance_id: str,
                      origin_service_epoch: int, call_ids: tuple[str, ...], _authority: object
                      ) -> BarrierAcknowledgement:
        assert (base_fingerprint, tenant_id, company_id) == (
            BASE, SCOPE.tenant_id, SCOPE.company_id,
        )
        assert lifecycle_epoch == 5
        assert barrier_id == BARRIER_ID
        assert call_ids == ()
        acknowledgement = _signed_acknowledgement(origin_instance_id, origin_service_epoch)
        self.acknowledgements.append(acknowledgement)
        return acknowledgement


class InMemoryAuthorityLease:
    def __init__(self) -> None:
        self.releases = 0

    def assert_held(self) -> None:
        return None

    async def release(self) -> None:
        self.releases += 1


class InMemoryAuthorityMutex:
    def __init__(self) -> None:
        self.lease = InMemoryAuthorityLease()

    async def try_acquire(self) -> InMemoryAuthorityLease:
        return self.lease


def _ready_service(store: InMemoryAdmissionStore, writer: InMemoryWriter,
                   verifier: ProductionBarrierAcknowledgementVerifier
                   ) -> tuple[PrivateWriterService, InMemoryAuthorityMutex]:
    mutex = InMemoryAuthorityMutex()
    service = PrivateWriterService(
        store,
        writer,
        host_id="host-test",
        base_fingerprint=BASE,
        serving_authority_mutex=mutex,
        barrier_wait_seconds=1.0,
        barrier_ack_verifier=verifier,
    )
    service._set_lifecycle_field("_startup_recovery", StartupRecoveryState(
        service_instance_id=service._service_instance_id,
        service_epoch=9,
        pending_calls=(),
        open_barriers=(),
        readiness_ref="test-readiness-ref",
    ))
    service._set_lifecycle_field("_service_epoch", 9)
    service._set_lifecycle_field("_startup_complete", True)
    return service, mutex


class S13BarrierAcknowledgementServiceE2ETests(unittest.TestCase):
    def test_fence_scope_closes_admission_verifies_ack_and_quiesces(self) -> None:
        trust = InMemoryTrustSource()
        registry = InMemoryAcknowledgementRegistry()
        verifier = ProductionBarrierAcknowledgementVerifier(trust, registry)
        store = InMemoryAdmissionStore()
        writer = InMemoryWriter()
        service, mutex = _ready_service(store, writer, verifier)

        async def exercise() -> BarrierSnapshot:
            return await service.fence_scope(SCOPE, 4, BARRIER_ID)

        result = asyncio.run(exercise())

        self.assertEqual(store.events, ["ADMISSION_CLOSED", "BARRIER_QUIESCED"])
        self.assertIs(result.progress, BarrierProgress.QUIESCED)
        self.assertEqual(result.acknowledgement_ref,
                         barrier_acknowledgement_ref(writer.acknowledgements[0]))
        self.assertEqual(trust.loads, [writer.acknowledgements[0]])
        self.assertEqual(registry.registration_calls, 1)
        self.assertEqual(len(registry.records), 1)
        self.assertEqual(store.finish_calls, [result.acknowledgement_ref])
        self.assertEqual(mutex.lease.releases, 1)

    def test_lost_registration_response_replays_exact_ack_without_reloading_trust(self) -> None:
        trust = InMemoryTrustSource()
        registry = InMemoryAcknowledgementRegistry(lose_first_response=True)
        verifier = ProductionBarrierAcknowledgementVerifier(trust, registry)
        store = InMemoryAdmissionStore()
        writer = InMemoryWriter()
        service, _ = _ready_service(store, writer, verifier)

        async def exercise() -> tuple[ServiceError, BarrierSnapshot, BarrierSnapshot]:
            try:
                await service.fence_scope(SCOPE, 4, BARRIER_ID)
            except ServiceError as error:
                unknown = error
            else:
                raise AssertionError("lost acknowledgement response must remain unknown")
            self.assertIs(store.snapshot.progress, BarrierProgress.CLOSED_WITH_HOLD)
            completed = await service.fence_scope(SCOPE, 4, BARRIER_ID)
            replay = await service.fence_scope(SCOPE, 4, BARRIER_ID)
            return unknown, completed, replay

        error, completed, replay = asyncio.run(exercise())

        self.assertEqual(error.code, "BARRIER_ACK_VERIFY_UNKNOWN")
        self.assertTrue(error.outcome_unknown)
        self.assertIs(completed.progress, BarrierProgress.QUIESCED)
        self.assertEqual(replay, completed)
        self.assertEqual(len(trust.loads), 1)
        self.assertEqual(registry.registration_calls, 1)
        self.assertEqual(registry.lookup_calls, 2)
        self.assertEqual(len(writer.acknowledgements), 2)
        self.assertEqual(len(store.finish_calls), 1)

    def test_stale_epoch_refuses_before_admission_or_writer_ack(self) -> None:
        trust = InMemoryTrustSource()
        registry = InMemoryAcknowledgementRegistry()
        verifier = ProductionBarrierAcknowledgementVerifier(trust, registry)
        store = InMemoryAdmissionStore(current_epoch=5)
        writer = InMemoryWriter()
        service, _ = _ready_service(store, writer, verifier)

        async def exercise() -> ServiceError:
            with self.assertRaises(ServiceError) as raised:
                await service.fence_scope(SCOPE, 4, BARRIER_ID)
            return raised.exception

        error = asyncio.run(exercise())

        self.assertEqual(error.code, "STALE_EPOCH")
        self.assertIsNone(store.snapshot)
        self.assertEqual(store.events, [])
        self.assertEqual(writer.acknowledgements, [])
        self.assertEqual(trust.loads, [])
        self.assertEqual(registry.registration_calls, 0)

    def test_changed_ack_tuple_cannot_replay_a_prior_barrier_record(self) -> None:
        trust = InMemoryTrustSource()
        registry = InMemoryAcknowledgementRegistry()
        verifier = ProductionBarrierAcknowledgementVerifier(trust, registry)
        store = InMemoryAdmissionStore()
        writer = InMemoryWriter()
        service, _ = _ready_service(store, writer, verifier)

        # Seed the same barrier identity with a valid, differently signed prior acknowledgement.
        async def seed_and_fence() -> ServiceError:
            origin = service._service_instance_id
            prior = _signed_acknowledgement(origin, 9, queue_epoch=2)
            prior_bytes = barrier_acknowledgement_signed_bytes(prior)
            registry.records[BARRIER_ID] = _registry_record(
                prior, barrier_acknowledgement_ref(prior), prior_bytes,
            )
            with self.assertRaises(ServiceError) as raised:
                await service.fence_scope(SCOPE, 4, BARRIER_ID)
            return raised.exception

        error = asyncio.run(seed_and_fence())

        self.assertEqual(error.code, "BARRIER_ACK_REJECTED")
        self.assertIs(store.snapshot.progress, BarrierProgress.CLOSED_WITH_HOLD)
        self.assertEqual(store.events, ["ADMISSION_CLOSED"])
        self.assertEqual(trust.loads, [])
        self.assertEqual(registry.registration_calls, 0)
        self.assertEqual(store.finish_calls, [])


if __name__ == "__main__":
    unittest.main()
