"""Focused cross-connection acceptance for S13 migration 022 lifecycle fencing.

Run directly with the repository Python, never through pytest. The runner provisions one
invocation-owned loopback PostgreSQL cluster and a uniquely named disposable database.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import asyncpg
from _pg_harness import disposable_cluster, throwaway_db
from test_change_ledger_sql import C, T, L, _setup

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
PRIOR_MIGRATION_FILES = (
    "019_ed25519_action_only.sql",
    "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql",
)
MIGRATION_022 = "022_lifecycle_epoch_fence.sql"


async def apply(conn: asyncpg.Connection, path: Path) -> None:
    print(f"PROGRESS: applying {path.name}", flush=True)
    raw = path.read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))
    print(f"PROGRESS: applied {path.name}", flush=True)


async def lifecycle(led: L, role: str, name: str, *args, t: str = T, c: str = C):
    value = await led.call(role, name, *args, t=t, c=c)
    return json.loads(value) if isinstance(value, str) else value


async def test_cross_connection_recovery_fence(db, led: L) -> None:
    other = await db.connect()
    other_led = L(SimpleNamespace(conn=other))
    try:
        # Migration seeded each pre-existing authorized scope as LEGACY; status is fail closed.
        print("PROGRESS: cross-connection journey status read", flush=True)
        before = await lifecycle(led, "clt_wrk", "lifecycle_status")
        assert before["state"] == "NOT_READY", before

        permit_change_id, permit_token, _call_id, _permit = await led.permitted(
            request_id="s13-m022-cross-connection-permit")
        permit_epoch = await led.call("clt_wrk", "lifecycle_permit_epoch", permit_change_id,
                                      permit_token["generation"])
        assert permit_epoch == 0, permit_epoch

        first = await lifecycle(led, "clt_wrk", "lifecycle_begin_recovery")
        print("PROGRESS: first recovery epoch created", flush=True)
        assert first["state"] == "RECOVERING" and first["epoch"] == 1, first
        assert first["unresolved_calls"] >= 1, first

        # A physically separate connection observes the durable recovery state and cannot
        # mint a writer epoch. No READY transition exists in this staged migration.
        observed = await lifecycle(other_led, "clt_wrk", "lifecycle_status")
        assert observed["state"] == "RECOVERING" and observed["epoch"] == 1, observed
        assert await lifecycle(other_led, "clt_wri", "lifecycle_writer_epoch", permit_change_id,
                               permit_token["generation"], permit_epoch) is False
        assert await lifecycle(other_led, "clt_wri", "lifecycle_writer_epoch", permit_change_id,
                               permit_token["generation"], 1) is False

        # Repeated recovery advances a monotonic fence; the prior permit epoch stays stale.
        second = await lifecycle(other_led, "clt_wrk", "lifecycle_begin_recovery")
        print("PROGRESS: second recovery epoch created", flush=True)
        assert second["state"] == "RECOVERING" and second["epoch"] == 2, second
        observed = await lifecycle(led, "clt_wrk", "lifecycle_status")
        assert observed["state"] == "RECOVERING" and observed["epoch"] == 2, observed
        assert await lifecycle(led, "clt_wri", "lifecycle_writer_epoch", permit_change_id,
                               permit_token["generation"], 2) is False

        # A separate company scope remains unchanged (including across reconnection).
        # clt_wrk is granted only this fixture's second scope for the isolation probe.
        await db.conn.execute("SELECT change_ledger.add_role_scope('clt_wrk','T2','C2')")
        isolated = await lifecycle(other_led, "clt_wrk", "lifecycle_status", t="T2", c="C2")
        assert isolated["state"] == "NOT_READY", isolated
        await other.close()
        other = await db.connect()
        persisted = await lifecycle(L(SimpleNamespace(conn=other)), "clt_wrk", "lifecycle_status")
        assert persisted["state"] == "RECOVERING" and persisted["epoch"] == 2, persisted
        untouched = await lifecycle(L(SimpleNamespace(conn=other)), "clt_wrk", "lifecycle_status",
                                    t="T2", c="C2")
        assert untouched["state"] == "NOT_READY", untouched
    finally:
        if not other.is_closed():
            await other.close()
    print("PASS: separate connections observe durable RECOVERING; epoch advances; writer epoch is denied; scope isolation holds")


async def test_unresolved_calls_hold_recovery(db, led: L) -> None:
    # Create a legitimate unresolved dispatch through the SQL API while the scope is LEGACY.
    print("PROGRESS: creating unresolved dispatch", flush=True)
    change_id, _unresolved_token, _unresolved_call_id = await led.unknown(
        request_id="s13-m022-unresolved")
    print("PROGRESS: unresolved dispatch created", flush=True)
    stale_change_id, stale_token, stale_call_id, _permit = await led.permitted(
        base="base-2", request_id="s13-m022-stale-dispatch")
    await led.verify_dispatch(stale_change_id, stale_token["generation"])
    verified = await led.conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2)", stale_change_id, stale_token["generation"])
    assert verified is True, "stale-dispatch fixture must be payload-verified before recovery"
    permit_epoch = await led.call("clt_wrk", "lifecycle_permit_epoch", stale_change_id,
                                  stale_token["generation"])
    assert permit_epoch == 0, permit_epoch
    unresolved = await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.records WHERE tenant_id=$1 AND company_id=$2 "
        "AND (execution_state IN ('APPLYING','APPLY_UNKNOWN') OR call_ownership='POSSIBLY_EXECUTING' "
        "OR (dispatch_state='DISPATCHED' AND NOT (execution_state IN ('APPLIED','FAILED_APPLY') "
        "AND call_ownership='PROVEN_FINISHED')))" , T, C)
    assert unresolved >= 1, (change_id, unresolved)

    status = await lifecycle(led, "clt_wrk", "lifecycle_begin_recovery")
    print("PROGRESS: unresolved recovery fence started", flush=True)
    assert status["state"] == "RECOVERING" and status["unresolved_calls"] >= 1, status
    # While RECOVERING, the state predicate refuses before checking the persisted permit epoch.
    assert await lifecycle(led, "clt_wri", "lifecycle_writer_epoch", stale_change_id,
                           stale_token["generation"], 0) is False
    await db.conn.execute("SELECT change_ledger.add_role_scope('clt_wrk','T2','C2')")
    # Both a worker mutation and a stale physical-dispatch admission fail closed while recovering.
    try:
        print("PROGRESS: attempting fenced event mutation", flush=True)
        await led.call("clt_wrk", "declare_anchor_gap", "base-1", json.dumps({}))
    except asyncpg.PostgresError as error:
        assert "LIFECYCLE_NOT_READY" in str(error), str(error)
    else:
        raise AssertionError("event-producing mutation succeeded during RECOVERING")
    try:
        print("PROGRESS: attempting fenced stale dispatch", flush=True)
        await led.call("clt_wri", "record_call", stale_change_id,
                       stale_token["generation"], stale_call_id)
    except asyncpg.PostgresError as error:
        assert "LIFECYCLE_NOT_READY" in str(error), str(error)
    else:
        raise AssertionError("dispatch was admitted during RECOVERING")
    status_after = await lifecycle(led, "clt_wrk", "lifecycle_status")
    assert status_after["state"] == "RECOVERING", status_after
    # Test-only direct row injection exercises the exact READY/epoch predicate against an old permit.
    # It does not exercise or claim a public RECOVERING -> READY transition.
    await db.conn.execute(
        "UPDATE change_ledger.lifecycle_fences SET state='READY',epoch=2,reason='TEST_PREDICATE_ONLY' "
        "WHERE tenant_id=$1 AND company_id=$2", T, C)
    assert await lifecycle(led, "clt_wri", "lifecycle_writer_epoch", stale_change_id,
                           stale_token["generation"], 2) is False
    print("PASS: unresolved call reported; event mutation and fresh dispatch refused; fixture-only READY/epoch=2 rejects epoch-0 permit")


async def main() -> int:
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    print("PROGRESS: provisioning owned PostgreSQL", flush=True)
    async with disposable_cluster() as (dsn, container_name, _token):
        print(f"PROGRESS: owned PostgreSQL ready ({container_name})", flush=True)
        async with throwaway_db(dsn) as db:
            for filename in PRIOR_MIGRATION_FILES:
                await apply(db.conn, MIGRATIONS / filename)
            # Scope rows must exist before 022 so its migration-time compatibility seed is tested.
            await _setup(db.conn)
            await apply(db.conn, MIGRATIONS / MIGRATION_022)
            led = L(db)
            print("PROGRESS: first database ready", flush=True)
            await test_cross_connection_recovery_fence(db, led)
            # A new database is required so the unresolved flow starts in LEGACY state.
            async with throwaway_db(dsn) as second_db:
                for filename in PRIOR_MIGRATION_FILES:
                    await apply(second_db.conn, MIGRATIONS / filename)
                await _setup(second_db.conn)
                await apply(second_db.conn, MIGRATIONS / MIGRATION_022)
                print("PROGRESS: second database ready", flush=True)
                await test_unresolved_calls_hold_recovery(second_db, L(second_db))
    print(f"Suite: PASS — 2 focused S13 lifecycle journeys on owned PostgreSQL container {container_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
