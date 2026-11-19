"""Regressions for S18 base-queue unresolved-call admission."""
from __future__ import annotations

from uuid import uuid4

import pytest

from business_ai_gateway.phase2.base_queue import (
    BaseQueueRefused,
    BaseWorkQueue,
    QueueWorkKind,
)
from business_ai_gateway.phase2.change.types import CallOwnership


def test_mark_unknown_without_in_flight_target_preserves_queue_schedule():
    queue = BaseWorkQueue("base-a")
    first = queue.enqueue(uuid4(), "target-a", QueueWorkKind.MUTATION)
    second = queue.enqueue(uuid4(), "target-b", QueueWorkKind.MUTATION)

    with pytest.raises(BaseQueueRefused) as refusal:
        queue.mark_unknown("target-a", CallOwnership.POSSIBLY_EXECUTING)

    assert str(refusal.value) == BaseQueueRefused.TARGET_WORK_NOT_IN_FLIGHT
    assert queue.queued_count == 2
    assert queue.in_flight_count == 0
    assert queue.unresolved_targets() == ()
    assert queue.next_ready() == first
    queue.complete(first.work_id)
    assert queue.next_ready() == second


def test_mark_unknown_requires_matching_in_flight_target():
    queue = BaseWorkQueue("base-a")
    active = queue.enqueue(uuid4(), "target-a", QueueWorkKind.MUTATION)
    verification = queue.enqueue(uuid4(), "target-b", QueueWorkKind.VERIFY_READ)
    queue.enqueue(uuid4(), "target-b", QueueWorkKind.MUTATION)
    assert queue.next_ready() == verification
    queue.complete(verification.work_id)
    assert queue.next_ready() == active

    queue.mark_unknown("target-a", CallOwnership.POSSIBLY_EXECUTING)

    assert queue.unresolved_targets() == (("target-a", CallOwnership.POSSIBLY_EXECUTING),)
    with pytest.raises(BaseQueueRefused) as refusal:
        queue.mark_unknown("target-b", CallOwnership.POSSIBLY_EXECUTING)
    assert str(refusal.value) == BaseQueueRefused.TARGET_WORK_NOT_IN_FLIGHT
    assert queue.unresolved_targets() == (("target-a", CallOwnership.POSSIBLY_EXECUTING),)
    assert queue.next_ready() is None
    assert queue.queued_count == 1
    assert queue.in_flight_count == 1


def test_mark_unknown_cannot_claim_finished_and_release_base_mutation_hold():
    queue = BaseWorkQueue("base-a")
    active = queue.enqueue(uuid4(), "target-a", QueueWorkKind.MUTATION)
    other_target = queue.enqueue(uuid4(), "target-b", QueueWorkKind.MUTATION)
    assert queue.next_ready() == active
    queue.mark_unknown("target-a", CallOwnership.POSSIBLY_EXECUTING)

    with pytest.raises(BaseQueueRefused) as refusal:
        queue.mark_unknown("target-a", CallOwnership.PROVEN_FINISHED)

    assert str(refusal.value) == BaseQueueRefused.INVALID_WORK
    assert queue.unresolved_targets() == (("target-a", CallOwnership.POSSIBLY_EXECUTING),)
    assert queue.next_ready() is None
    assert queue.in_flight_count == 1
    assert queue.queued_count == 1

    queue.complete(active.work_id)
    assert queue.next_ready() is None
    queue.prove_finished("target-a")

    assert queue.next_ready() == other_target


def test_capacity_refuses_twenty_first_item_without_evicting_pending_work():
    queue = BaseWorkQueue("base-a")
    admitted = [queue.enqueue(uuid4(), f"target-{index}", QueueWorkKind.MUTATION)
                for index in range(20)]

    with pytest.raises(BaseQueueRefused) as refusal:
        queue.enqueue(uuid4(), "target-overflow", QueueWorkKind.MUTATION)

    assert str(refusal.value) == BaseQueueRefused.QUEUE_FULL
    assert queue.queued_count == 20
    assert queue.in_flight_count == 0
    for expected in admitted:
        selected = queue.next_ready()
        assert selected == expected
        queue.complete(selected.work_id)
    assert queue.is_drained


def test_verification_read_is_scheduled_before_an_older_mutation():
    queue = BaseWorkQueue("base-a")
    mutation = queue.enqueue(uuid4(), "target-a", QueueWorkKind.MUTATION)
    verification = queue.enqueue(uuid4(), "target-b", QueueWorkKind.VERIFY_READ)

    assert queue.next_ready() == verification
    queue.complete(verification.work_id)
    assert queue.next_ready() == mutation


def test_proven_finished_target_remains_parked_without_holding_other_work_or_base():
    first_base = BaseWorkQueue("base-a")
    second_base = BaseWorkQueue("base-b")
    in_flight = first_base.enqueue(uuid4(), "target-a", QueueWorkKind.MUTATION)
    assert first_base.next_ready() == in_flight
    first_base.mark_unknown("target-a", CallOwnership.POSSIBLY_EXECUTING)
    first_base.complete(in_flight.work_id)
    first_base.prove_finished("target-a")

    parked = first_base.enqueue(uuid4(), "target-a", QueueWorkKind.MUTATION)
    other_target = first_base.enqueue(uuid4(), "target-b", QueueWorkKind.MUTATION)
    other_base = second_base.enqueue(uuid4(), "target-a", QueueWorkKind.MUTATION)

    assert first_base.next_ready() == other_target
    assert first_base.next_ready() is None
    assert first_base.queued_count == 1
    assert second_base.next_ready() == other_base
    assert parked.target_id == "target-a"


def test_shutdown_closes_admission_and_drains_existing_active_and_pending_work():
    queue = BaseWorkQueue("base-a")
    active = queue.enqueue(uuid4(), "target-active", QueueWorkKind.MUTATION)
    assert queue.next_ready() == active
    verification = queue.enqueue(uuid4(), "target-read", QueueWorkKind.VERIFY_READ)
    pending_mutation = queue.enqueue(uuid4(), "target-pending", QueueWorkKind.MUTATION)

    queue.begin_shutdown()

    assert queue.admission_closed
    assert not queue.is_drained
    with pytest.raises(BaseQueueRefused) as refusal:
        queue.enqueue(uuid4(), "target-late", QueueWorkKind.VERIFY_READ)
    assert str(refusal.value) == BaseQueueRefused.ADMISSION_CLOSED
    assert queue.queued_count == 2
    assert queue.in_flight_count == 1

    assert queue.next_ready() == verification
    queue.complete(verification.work_id)
    assert queue.next_ready() == pending_mutation
    queue.complete(pending_mutation.work_id)
    assert not queue.is_drained
    queue.complete(active.work_id)
    assert queue.is_drained
