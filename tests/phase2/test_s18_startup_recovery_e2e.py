"""Disposable PostgreSQL startup epoch fencing and pending-call inventory.

The tests use only an invocation-owned throwaway database. They do not start or kill a writer
process, invoke COM/1C, or establish runtime readiness outside the synthetic database contract.
"""
from __future__ import annotations

import json
import uuid

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import apply_files, throwaway_db
from test_change_ledger_sql import C, L, T, _setup
from test_s13_completion_outcome_e2e import _admitted_attempt, _private_call, _seed_static_preconditions
from test_s13_current_turn_sql import (
    MIGRATIONS_019_027,
    _OwnedClusterDsn,
    _apply_migration,
    _safe_postgres_diagnostics,
)

pytest_plugins = ("test_s13_completion_outcome_e2e",)


@pytest_asyncio.fixture
async def ledger(owned_cluster_dsn: _OwnedClusterDsn):
    """Build the disposable database through the complete S13 migration chain (001–030)."""
    async with throwaway_db(owned_cluster_dsn.value, seed=False) as db:
        step = "base migrations 001–018"
        try:
            await apply_files(db.conn)
            for migration in MIGRATIONS_019_027:
                step = migration
                await _apply_migration(db.conn, migration)
            step = "synthetic S13 fixture setup"
            await _setup(db.conn)
            await db.conn.execute(
                "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
                "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE') ON CONFLICT DO NOTHING",
                T,
                C,
            )
            for migration in (
                "028_refusal_codes_parity.sql",
                "029_scoped_operator_reads.sql",
                "030_private_writer_consolidation.sql",
            ):
                step = migration
                await _apply_migration(db.conn, migration)
        except asyncpg.PostgresError as error:
            pytest.fail(
                f"PostgreSQL setup error in {step}: {_safe_postgres_diagnostics(error)}",
                pytrace=False,
            )
        yield L(db)


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_new_instance_reports_admitted_not_invoked_call(ledger):
    flow = await _admitted_attempt(ledger, "s18-restart-pending")
    before_restart = await ledger.conn.fetchrow(
        "SELECT state,writer_process_instance_id,com_entry_authorized_at "
        "FROM change_ledger.dispatch_attempts "
        "WHERE dispatch_cas_id=$1",
        flow["cas_id"],
    )
    assert before_restart is not None
    assert before_restart["state"] == "ACCEPTED_NOT_INVOKED"
    assert before_restart["writer_process_instance_id"] == flow["instance_id"]
    assert before_restart["com_entry_authorized_at"] is None

    restarted_instance = str(uuid.uuid4())
    recovered = await _private_call(
        ledger.conn,
        "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_startup_recovery_state_v1($1::text))",
        restarted_instance,
    )
    if isinstance(recovered, str):
        recovered = json.loads(recovered)

    assert recovered["service_instance_id"] == restarted_instance
    assert int(recovered["service_epoch"]) == int(flow["epoch"]) + 1
    assert recovered["readiness_ref"] is None
    assert recovered["open_barriers"] == []
    assert len(recovered["pending_calls"]) == 1
    pending = recovered["pending_calls"][0]
    assert pending["state"] == "ACCEPTED_NOT_INVOKED"
    assert pending["identity"]["call_id"] == str(flow["call_id"])
