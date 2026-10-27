"""Functional tests for durable S13 barrier acknowledgement verification.

Acceptance slice: definitive pre-persist rejection is distinguishable from unknown outcomes;
ambiguous verifier outcomes keep the barrier closed and are recoverable by exact barrier-ID
retry. The module uses only in-memory fakes: no PostgreSQL, network, or COM.
"""
from __future__ import annotations

import asyncio
import hashlib
import unittest
from datetime import UTC, datetime
from uuid import UUID

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.write_port import BarrierAcknowledgement
from erp_mcp_private_writer.service import (
    BarrierAcknowledgementRejected,
    BarrierProgress,
    BarrierSnapshot,
    PrivateWriterService,
    ServiceError,
    StartupRecoveryState,
)


BASE = "a" * 64
SCOPE = Scope("tenant-1", "company-1")
BARRIER_ID = UUID("00000000-0000-4000-8000-000000000001")
ORIGIN_INSTANCE = "00000000-0000-4000-8000-000000000002"
HOST_BOOT_ID = "00000000-0000-4000-8000-000000000003"
WRITER_INSTANCE_ID = "00000000-0000-4000-8000-000000000004"


def _closed_snapshot() -> BarrierSnapshot:
    return BarrierSnapshot(
        scope=SCOPE,
        base_fingerprint=BASE,
        barrier_id=BARRIER_ID,
        expected_current_epoch=4,
        epoch=5,
        barrier_origin_instance_id=ORIGIN_INSTANCE,
        barrier_origin_service_epoch=8,
        call_ids=(),
        progress=BarrierProgress.CLOSED_WITH_HOLD,
        unresolved_call_ids=(),
    )


def _acknowledgement() -> BarrierAcknowledgement:
    return BarrierAcknowledgement(
        base_fingerprint=BASE,
        tenant_id=SCOPE.tenant_id,
        company_id=SCOPE.company_id,
        lifecycle_epoch=5,
        barrier_id=BARRIER_ID,
        barrier_origin_instance_id=ORIGIN_INSTANCE,
        barrier_origin_service_epoch=8,
        call_ids=(),
        key_id="test-key",
        key_version="1",
        writer_service_id="writer-test",
        writer_host_id="host-test",
        host_boot_id=HOST_BOOT_ID,
        writer_process_instance_id=WRITER_INSTANCE_ID,
        process_attestation_ref=WRITER_INSTANCE_ID,
        writer_queue_epoch=3,
        local_queue_closed=True,
        signed_at="2026-10-26T10:00:00.000000Z",
        signature=b"s" * 64,
    )


class FakeStore:
    """An in-memory durable barrier row with observable finish transitions."""

    def __init__(self) -> None:
        self.snapshot = _closed_snapshot()
        self.finish_calls: list[tuple[str, str, int]] = []

    async def lookup_barrier(self, barrier_id: UUID) -> BarrierSnapshot | None:
        assert barrier_id == BARRIER_ID
        return self.snapshot

    async def finish_barrier(
        self, snapshot: BarrierSnapshot, acknowledgement_ref: str,
        service_instance_id: str, service_epoch: int,
    ) -> BarrierSnapshot:
        assert snapshot.barrier_id == BARRIER_ID
        self.finish_calls.append((acknowledgement_ref, service_instance_id, service_epoch))
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
        return self.snapshot


class FakeLease:
    def __init__(self) -> None:
        self.releases = 0

    def assert_held(self) -> None:
        return None

    async def release(self) -> None:
        self.releases += 1


class FakeMutex:
    def __init__(self) -> None:
        self.lease = FakeLease()

    async def try_acquire(self) -> FakeLease:
        return self.lease


class FakeWriter:
    def __init__(self) -> None:
        self.ack = _acknowledgement()
        self.quiesce_calls = 0

    async def quiesce(self, *args) -> BarrierAcknowledgement:
        self.quiesce_calls += 1
        assert args[0] == BASE
        assert args[1:3] == (SCOPE.tenant_id, SCOPE.company_id)
        assert args[3] == 5
        assert args[4] == BARRIER_ID
        assert args[5:7] == (ORIGIN_INSTANCE, 8)
        assert args[7] == ()
        return self.ack


class TypedRejectVerifier:
    async def verify_and_store(self, acknowledgement: BarrierAcknowledgement) -> str:
        assert acknowledgement is not None
        raise BarrierAcknowledgementRejected()


class StoreThenLoseResponseVerifier:
    """Durably records the immutable ref, but loses its first response."""

    def __init__(self) -> None:
        self.durable_refs: dict[UUID, str] = {}
        self.calls: list[tuple[UUID, str]] = []

    async def verify_and_store(self, acknowledgement: BarrierAcknowledgement) -> str:
        assert type(acknowledgement) is BarrierAcknowledgement
        ref = self.durable_refs.setdefault(acknowledgement.barrier_id, "immutable-ack-ref-1")
        self.calls.append((acknowledgement.barrier_id, ref))
        if len(self.calls) == 1:
            raise ConnectionError("response lost after durable insert")
        return ref


class StoreThenRaiseOnceVerifier:
    """Persist an immutable ref, lose one response by the selected failure mode, then replay."""

    def __init__(self, failure: type[BaseException]) -> None:
        self.failure = failure
        self.durable_refs: dict[UUID, str] = {}
        self.calls: list[tuple[UUID, str]] = []

    async def verify_and_store(self, acknowledgement: BarrierAcknowledgement) -> str:
        assert type(acknowledgement) is BarrierAcknowledgement
        ref = self.durable_refs.setdefault(acknowledgement.barrier_id, "immutable-ack-ref-2")
        self.calls.append((acknowledgement.barrier_id, ref))
        if len(self.calls) == 1:
            if self.failure is asyncio.CancelledError:
                raise asyncio.CancelledError()
            raise self.failure("verifier response unavailable")
        return ref


class MalformedRefVerifier:
    async def verify_and_store(self, acknowledgement: BarrierAcknowledgement) -> str:
        assert type(acknowledgement) is BarrierAcknowledgement
        return " immutable-ack-ref "


def _service(verifier) -> tuple[PrivateWriterService, FakeStore, FakeWriter, FakeMutex]:
    store = FakeStore()
    writer = FakeWriter()
    mutex = FakeMutex()
    service = PrivateWriterService(
        store, writer, host_id="host-test", base_fingerprint=BASE,
        serving_authority_mutex=mutex, barrier_wait_seconds=1.0,
        barrier_ack_verifier=verifier,
    )
    # This test starts at an already-started service boundary; startup recovery itself is
    # outside this verifier persistence acceptance slice.
    service._set_lifecycle_field("_startup_recovery", StartupRecoveryState(
        service_instance_id=service._service_instance_id,
        service_epoch=9,
        pending_calls=(),
        open_barriers=(),
        readiness_ref="test-readiness-ref",
    ))
    service._set_lifecycle_field("_service_epoch", 9)
    service._set_lifecycle_field("_startup_complete", True)
    return service, store, writer, mutex


class S13BarrierAcknowledgementTests(unittest.TestCase):
    def _assert_ambiguous_retry_replays_durable_reference(
            self, failure: type[BaseException]) -> None:
        verifier = StoreThenRaiseOnceVerifier(failure)
        service, store, _, _ = _service(verifier)

        async def exercise() -> tuple[
                ServiceError, BarrierSnapshot, BarrierSnapshot, BarrierSnapshot]:
            with self.assertRaises(ServiceError) as raised:
                await service.fence_scope(SCOPE, 4, BARRIER_ID)
            closed = store.snapshot
            completed = await service.fence_scope(SCOPE, 4, BARRIER_ID)
            replay = await service.fence_scope(SCOPE, 4, BARRIER_ID)
            return raised.exception, closed, completed, replay

        error, closed, completed, replay = asyncio.run(exercise())

        self.assertEqual(error.code, "BARRIER_ACK_VERIFY_UNKNOWN")
        self.assertTrue(error.outcome_unknown)
        self.assertIs(closed.progress, BarrierProgress.CLOSED_WITH_HOLD)
        self.assertIsNone(closed.acknowledgement_ref)
        self.assertEqual(verifier.durable_refs, {BARRIER_ID: "immutable-ack-ref-2"})
        self.assertEqual(verifier.calls, [
            (BARRIER_ID, "immutable-ack-ref-2"),
            (BARRIER_ID, "immutable-ack-ref-2"),
        ])
        self.assertIs(completed.progress, BarrierProgress.QUIESCED)
        self.assertEqual(completed.acknowledgement_ref, "immutable-ack-ref-2")
        self.assertEqual(replay, completed)
        self.assertEqual(len(store.finish_calls), 1)

    def test_verifier_timeout_is_unknown_and_exact_retry_replays(self) -> None:
        self._assert_ambiguous_retry_replays_durable_reference(TimeoutError)

    def test_verifier_cancellation_is_unknown_and_exact_retry_replays(self) -> None:
        self._assert_ambiguous_retry_replays_durable_reference(asyncio.CancelledError)

    def test_typed_definitive_rejection_is_not_reported_as_unknown(self) -> None:
        service, store, _, _ = _service(TypedRejectVerifier())

        async def exercise() -> ServiceError:
            with self.assertRaises(ServiceError) as raised:
                await service.fence_scope(SCOPE, 4, BARRIER_ID)
            return raised.exception

        error = asyncio.run(exercise())

        self.assertEqual(error.code, "BARRIER_ACK_REJECTED")
        self.assertFalse(error.outcome_unknown)
        self.assertIs(store.snapshot.progress, BarrierProgress.CLOSED_WITH_HOLD)
        self.assertEqual(store.finish_calls, [])

    def test_store_then_lost_response_is_unknown_and_exact_retry_completes(self) -> None:
        verifier = StoreThenLoseResponseVerifier()
        service, store, writer, mutex = _service(verifier)

        async def exercise() -> tuple[
                ServiceError, BarrierSnapshot, BarrierSnapshot, BarrierSnapshot]:
            with self.assertRaises(ServiceError) as raised:
                await service.fence_scope(SCOPE, 4, BARRIER_ID)
            after_unknown = store.snapshot
            completed = await service.fence_scope(SCOPE, 4, BARRIER_ID)
            replay = await service.fence_scope(SCOPE, 4, BARRIER_ID)
            return raised.exception, after_unknown, completed, replay

        error, after_unknown, completed, replay = asyncio.run(exercise())

        self.assertEqual(error.code, "BARRIER_ACK_VERIFY_UNKNOWN")
        self.assertTrue(error.outcome_unknown)
        self.assertEqual(verifier.durable_refs, {BARRIER_ID: "immutable-ack-ref-1"})
        self.assertIs(after_unknown.progress, BarrierProgress.CLOSED_WITH_HOLD)
        self.assertEqual(after_unknown.acknowledgement_ref, None)
        self.assertEqual(len(store.finish_calls), 1)

        self.assertIs(completed.progress, BarrierProgress.QUIESCED)
        self.assertEqual(completed.acknowledgement_ref, "immutable-ack-ref-1")
        self.assertEqual(verifier.calls, [
            (BARRIER_ID, "immutable-ack-ref-1"),
            (BARRIER_ID, "immutable-ack-ref-1"),
        ])
        self.assertEqual(store.finish_calls[0][0], "immutable-ack-ref-1")
        self.assertEqual(replay, completed)
        self.assertEqual(len(verifier.calls), 2)
        self.assertEqual(len(store.finish_calls), 1)
        self.assertGreaterEqual(writer.quiesce_calls, 1)
        self.assertEqual(mutex.lease.releases, writer.quiesce_calls)

    def test_malformed_returned_reference_is_unknown_and_keeps_barrier_closed(self) -> None:
        service, store, _, _ = _service(MalformedRefVerifier())

        async def exercise() -> ServiceError:
            with self.assertRaises(ServiceError) as raised:
                await service.fence_scope(SCOPE, 4, BARRIER_ID)
            return raised.exception

        error = asyncio.run(exercise())

        self.assertEqual(error.code, "BARRIER_ACK_VERIFY_UNKNOWN")
        self.assertTrue(error.outcome_unknown)
        self.assertIs(store.snapshot.progress, BarrierProgress.CLOSED_WITH_HOLD)
        self.assertEqual(store.finish_calls, [])


if __name__ == "__main__":
    unittest.main()
