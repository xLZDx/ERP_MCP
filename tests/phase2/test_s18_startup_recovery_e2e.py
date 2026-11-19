"""Disposable PostgreSQL startup epoch fencing for an empty recovery inventory.

This proves the migration-backed database boundary only: a new synthetic service instance
advances the durable epoch and receives a readiness reference when its inventory is empty.
It does not start or kill a writer process, invoke COM/1C, or establish runtime readiness.
"""
from __future__ import annotations

import json
import uuid

import pytest

pytest_plugins = ("test_s13_completion_outcome_e2e",)

from test_s13_completion_outcome_e2e import _private_call, _seed_static_preconditions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_new_instance_advances_durable_epoch_for_empty_inventory(ledger):
    _, initial_epoch, initial_instance = await _seed_static_preconditions(ledger)
    initial_fence = await ledger.conn.fetchrow(
        "SELECT service_instance_id,service_epoch,readiness_ref "
        "FROM change_ledger.private_writer_serving_fences"
    )
    assert initial_fence is not None
    assert initial_fence["service_instance_id"] == initial_instance
    assert int(initial_fence["service_epoch"]) == initial_epoch
    assert initial_fence["readiness_ref"] is not None

    restarted_instance = str(uuid.uuid4())
    recovered = await _private_call(
        ledger.conn,
        "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_startup_recovery_state_v1($1::text))",
        restarted_instance,
    )
    if isinstance(recovered, str):
        recovered = json.loads(recovered)

    assert recovered["service_instance_id"] == restarted_instance
    assert int(recovered["service_epoch"]) == initial_epoch + 1
    assert recovered["readiness_ref"] is not None
    assert recovered["open_barriers"] == []
    assert recovered["pending_calls"] == []

    current_fence = await ledger.conn.fetchrow(
        "SELECT service_instance_id,service_epoch,readiness_ref "
        "FROM change_ledger.private_writer_serving_fences"
    )
    assert current_fence is not None
    assert current_fence["service_instance_id"] == restarted_instance
    assert int(current_fence["service_epoch"]) == initial_epoch + 1
    assert str(current_fence["readiness_ref"]) == recovered["readiness_ref"]
