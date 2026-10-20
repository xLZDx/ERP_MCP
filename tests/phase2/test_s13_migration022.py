"""Focused PostgreSQL acceptance scenarios for S13 migration 022.

Run directly, never through pytest:
  .venv/Scripts/python.exe tests/phase2/test_s13_migration022.py
Requires ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1 and Docker. Provisions one uniquely
named, invocation-owned loopback PostgreSQL container and a throwaway database.
The migration intentionally has no RECOVERING -> READY path and this test does not
claim a real writer integration.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import asyncpg

from _pg_harness import MIGRATIONS, disposable_cluster, throwaway_db
from test_change_ledger_sql import C, T, L, _setup


MIGRATION_CHAIN = [
    "019_ed25519_action_only.sql",
    "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql",
    "022_lifecycle_epoch_fence.sql",
]


async def apply_migration(conn: asyncpg.Connection, path: Path) -> None:
    raw = path.read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


async def expect_pg_error(needle: str, awaitable) -> None:
    try:
        await awaitable
    except asyncpg.PostgresError as error:
        assert needle in str(error), f"expected {needle!r}, got {error!s}"
        return
    raise AssertionError(f"expected PostgreSQL error containing {needle!r}")


def json_value(value):
    # L.call only decodes the older JSON function signatures listed by its base suite.
    return json.loads(value) if isinstance(value, str) else value


async def run() -> None:
    async with disposable_cluster() as (dsn, container, owner_token):
        async with throwaway_db(dsn) as db:
            for filename in MIGRATION_CHAIN[:-1]:
                await apply_migration(db.conn, MIGRATIONS / filename)
            await _setup(db.conn)
            await apply_migration(db.conn, MIGRATIONS / MIGRATION_CHAIN[-1])
            led = L(db)

            # Migration 022 is additive for existing scopes: legacy status is non-ready,
            # while existing event-backed behavior remains available before explicit recovery.
            status = json_value(await led.call("clt_wrk", "lifecycle_status"))
            assert status["state"] == "NOT_READY", status
            legacy_row = await db.conn.fetchrow(
                "SELECT state,epoch,reason FROM change_ledger.lifecycle_fences WHERE tenant_id=$1 AND company_id=$2",
                T, C)
            assert tuple(legacy_row) == ("LEGACY", 0, "LIFECYCLE_NOT_ACTIVATED"), tuple(legacy_row)
            legacy_change = await led.propose(kind="POST", target="legacy-compatible")
            assert await db.conn.fetchval(
                "SELECT count(*) FROM change_ledger.events WHERE change_id=$1", legacy_change) > 0

            # Authorization is checked independently of scope: operator-only callers cannot
            # start recovery, and a worker cannot use a scope it was not granted.
            await expect_pg_error("permission denied for function lifecycle_begin_recovery",
                                  led.call("clt_dave", "lifecycle_begin_recovery"))
            await expect_pg_error("SCOPE_NOT_GRANTED",
                                  led.call("clt_wrk", "lifecycle_status", t="T2", c="C2"))

            # A fully real ledger dispatch left APPLY_UNKNOWN creates one unresolved call and
            # a genuine permit while the scope is LEGACY. Its stored epoch must stay bound.
            permit_id, permit_token, _call_id = await led.unknown(
                kind="POST", target="recovery-unresolved")
            permit_epoch = await led.call("clt_wrk", "lifecycle_permit_epoch", permit_id,
                                          permit_token["generation"])
            assert permit_epoch == 0, permit_epoch
            assert await led.call("clt_wri", "lifecycle_writer_epoch", permit_id,
                                  permit_token["generation"], 0) is False

            first = json_value(await led.call("clt_wrk", "lifecycle_begin_recovery"))
            assert (first["state"], first["epoch"], first["unresolved_calls"]) == (
                "RECOVERING", 1, 1), first
            second = json_value(await led.call("clt_wrk", "lifecycle_begin_recovery"))
            assert (second["state"], second["epoch"], second["unresolved_calls"]) == (
                "RECOVERING", 2, 1), second
            assert await led.call("clt_wri", "lifecycle_writer_epoch", permit_id,
                                  permit_token["generation"], permit_epoch) is False

            # Both event-producing changes and permit updates fail closed in RECOVERING.
            events_before = await db.conn.fetchval("SELECT count(*) FROM change_ledger.events")
            await expect_pg_error("LIFECYCLE_NOT_READY",
                                  led.propose(kind="POST", target="must-not-append"))
            events_after = await db.conn.fetchval("SELECT count(*) FROM change_ledger.events")
            assert events_after == events_before, (events_before, events_after)
            await expect_pg_error("LIFECYCLE_NOT_READY", db.conn.execute(
                "UPDATE change_ledger.dispatch_permits SET state='CANCELLED_UNDISPATCHED' "
                "WHERE change_id=$1 AND generation=$2", permit_id, permit_token["generation"]))
            stored_epoch = await db.conn.fetchval(
                "SELECT lifecycle_epoch FROM change_ledger.dispatch_permits "
                "WHERE change_id=$1 AND generation=$2", permit_id, permit_token["generation"])
            assert stored_epoch == permit_epoch == 0, stored_epoch

            # The durable fence survives a client reconnect to the same disposable cluster.
            await db.conn.close()
            db.conn = await db.connect()
            led = L(db)
            after_reconnect = json_value(await led.call("clt_aud", "lifecycle_status"))
            assert (after_reconnect["state"], after_reconnect["epoch"]) == ("RECOVERING", 2), after_reconnect

            # This direct row change exists only in the disposable DB fixture. It tests the
            # writer predicate against a current epoch of 2; it is not a production READY path.
            await db.conn.execute(
                "UPDATE change_ledger.lifecycle_fences SET state='READY',epoch=2,"
                "reason='TEST_PREDICATE_ONLY' WHERE tenant_id=$1 AND company_id=$2", T, C)
            assert await led.call("clt_wri", "lifecycle_writer_epoch", permit_id,
                                  permit_token["generation"], 2) is False
            print(f"PASS: migration 022 scenarios on owned container {container}; owner token {owner_token[:8]}")


if __name__ == "__main__":
    asyncio.run(run())
