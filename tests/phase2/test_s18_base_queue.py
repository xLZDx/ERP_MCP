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
