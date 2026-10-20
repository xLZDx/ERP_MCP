"""Focused PostgreSQL acceptance for S13 migrations 023-024.

Run directly (never through pytest):
  .venv/Scripts/python.exe tests/phase2/test_s13_migration023.py
The test creates an invocation-owned loopback PostgreSQL container and throwaway database,
applies migrations 001-024, and removes only the container and anonymous volume it created.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from uuid import uuid4

import asyncpg

from _pg_harness import MIGRATIONS, disposable_cluster, throwaway_db
from test_change_ledger_sql import C, L, T, _setup, exp
from _approval_envelope import fixture_digest_for


MIGRATION_CHAIN = [
    "019_ed25519_action_only.sql",
    "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql",
    "022_lifecycle_epoch_fence.sql",
    "023_lifecycle_activation_cap.sql",
    "024_restore_caller_lock_timeout.sql",
]
MIGRATION_023 = "023_lifecycle_activation_cap.sql"
RECOVERY_SIGNATURE = "change_ledger.lifecycle_begin_recovery(text,text)"


async def apply_migration(conn: asyncpg.Connection, path: Path) -> None:
    raw = path.read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


async def expect_pg_error(needle: str, awaitable) -> asyncpg.PostgresError:
    try:
        await awaitable
    except asyncpg.PostgresError as error:
        assert needle in str(error), f"expected {needle!r}, got {error!s}"
        return error
    raise AssertionError(f"expected PostgreSQL error containing {needle!r}")


async def scoped_call(conn: asyncpg.Connection, role: str, sql: str, *args,
                      lock_timeout: str | None = None):
    async with conn.transaction():
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        if lock_timeout is not None:
            await conn.fetchval("SELECT set_config('lock_timeout',$1,true)", lock_timeout)
        return await conn.fetchval(sql, T, C, *args)


async def expect_lock_timeout(awaitable, *, max_seconds: float) -> float:
    started = time.monotonic()
    error = await expect_pg_error("lock timeout", awaitable)
    elapsed = time.monotonic() - started
    assert error.sqlstate == "55P03", (error.sqlstate, str(error))
    assert elapsed < max_seconds, f"lock wait took {elapsed:.3f}s, cap was {max_seconds:.3f}s"
    return elapsed


async def lock_fence_row(conn: asyncpg.Connection):
    tx = conn.transaction()
    await tx.start()
    await conn.fetchrow(
        "SELECT 1 FROM change_ledger.lifecycle_fences WHERE tenant_id=$1 AND company_id=$2 FOR UPDATE",
        T, C)
    return tx


async def propose_with_timeout(conn: asyncpg.Connection, *, lock_timeout: str | None):
    return await scoped_call(
        conn, "clt_alice",
        "SELECT change_ledger.propose($1::text,$2::text,$3::uuid,$4::text,$5::text,$6::text,"
        "$7::text,$8::text,$9::text,$10::text,$11::text,$12::uuid,$13::timestamptz,$14::uuid)",
        uuid4(), "POST", "base-1", "org-1", "clt_alice", uuid4().hex,
        fixture_digest_for("POST"), "m023-event-target", "v1", None, exp(), None,
        lock_timeout=lock_timeout)


async def propose_and_show_timeout(conn: asyncpg.Connection, lock_timeout: str, base: str):
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_alice"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        await conn.fetchval("SELECT set_config('lock_timeout',$1,true)", lock_timeout)
        await conn.fetchval(
            "SELECT change_ledger.propose($1::text,$2::text,$3::uuid,$4::text,$5::text,$6::text,"
            "$7::text,$8::text,$9::text,$10::text,$11::text,$12::uuid,$13::timestamptz,$14::uuid)",
            T, C, uuid4(), "POST", base, "org-1", "clt_alice", uuid4().hex,
            fixture_digest_for("POST"), "m024-success-event", "v1", None, exp(), None)
        return await conn.fetchval("SHOW lock_timeout")


async def update_permit_with_timeout(conn: asyncpg.Connection, cid, generation, lock_timeout: str):
    async with conn.transaction():
        await conn.execute("SELECT set_config('change_ledger.tenant_id',$1,true)", T)
        await conn.execute("SELECT set_config('change_ledger.company_id',$1,true)", C)
        await conn.execute("SELECT set_config('lock_timeout',$1,true)", lock_timeout)
        return await conn.fetchval(
            "UPDATE change_ledger.dispatch_permits SET expires_at=expires_at "
            "WHERE change_id=$1 AND generation=$2 RETURNING change_id", cid, generation)


async def update_permit_and_show_timeout(conn: asyncpg.Connection, cid, generation, lock_timeout: str):
    async with conn.transaction():
        await conn.execute("SELECT set_config('change_ledger.tenant_id',$1,true)", T)
        await conn.execute("SELECT set_config('change_ledger.company_id',$1,true)", C)
        await conn.execute("SELECT set_config('lock_timeout',$1,true)", lock_timeout)
        await conn.fetchval(
            "UPDATE change_ledger.dispatch_permits SET expires_at=expires_at "
            "WHERE change_id=$1 AND generation=$2 RETURNING change_id", cid, generation)
        return await conn.fetchval("SHOW lock_timeout")


async def writer_epoch_and_show_timeout(conn: asyncpg.Connection, cid, generation, lock_timeout: str):
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_wri"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        await conn.fetchval("SELECT set_config('lock_timeout',$1,true)", lock_timeout)
        allowed = await conn.fetchval(
            "SELECT change_ledger.lifecycle_writer_epoch($1::text,$2::text,$3::uuid,$4::bigint,$5::bigint)",
            T, C, cid, generation, 0)
        return allowed, await conn.fetchval("SHOW lock_timeout")


async def test_recovery_is_denied_and_fail_closed(db, led: L) -> None:
    assert not await db.conn.fetchval(
        "SELECT has_function_privilege('clt_wrk',$1,'EXECUTE')", RECOVERY_SIGNATURE)
    await expect_pg_error("permission denied for function lifecycle_begin_recovery",
                          led.call("clt_wrk", "lifecycle_begin_recovery"))

    before = await db.conn.fetchrow(
        "SELECT state,epoch,reason,updated_at FROM change_ledger.lifecycle_fences WHERE tenant_id=$1 AND company_id=$2",
        T, C)
    assert tuple(before[:3]) == ("LEGACY", 0, "LIFECYCLE_NOT_ACTIVATED"), tuple(before)
    # Exercise the owner-capable direct-call path with a transaction-local valid scope.
    async with db.conn.transaction():
        # ledger_owner is the privileged SECURITY DEFINER owner; temporarily give it the
        # worker membership needed by row_in_scope, only inside this disposable database.
        await db.conn.execute("GRANT worker_role TO ledger_owner")
        await db.conn.execute(
            "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('ledger_owner',$1,$2)",
            T, C)
        await db.conn.execute("SET LOCAL ROLE ledger_owner")
        await db.conn.execute("SELECT set_config('change_ledger.tenant_id',$1,true)", T)
        await db.conn.execute("SELECT set_config('change_ledger.company_id',$1,true)", C)
        await expect_pg_error("LIFECYCLE_COORDINATOR_UNAVAILABLE", db.conn.fetchval(
            "SELECT change_ledger.lifecycle_begin_recovery($1,$2)", T, C))
    after = await db.conn.fetchrow(
        "SELECT state,epoch,reason,updated_at FROM change_ledger.lifecycle_fences WHERE tenant_id=$1 AND company_id=$2",
        T, C)
    assert tuple(after) == tuple(before), (tuple(before), tuple(after))


async def test_migration_is_idempotent(db) -> None:
    before = await db.conn.fetchrow("SELECT version,checksum,applied_at FROM living.schema_migrations WHERE version='023'")
    assert before is not None
    await apply_migration(db.conn, MIGRATIONS / MIGRATION_023)
    after = await db.conn.fetchrow("SELECT version,checksum,applied_at FROM living.schema_migrations WHERE version='023'")
    assert tuple(after) == tuple(before), (tuple(before), tuple(after))


async def test_success_restores_caller_lock_timeout(db, led: L) -> None:
    base = "m024-timeout-restore-base"
    await db.conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class) "
        "VALUES($1,$2,$3,'org-1','DISPOSABLE_CLONE')", T, C, base)
    cid, token, _call_id = await led.unknown(base=base, kind="POST", target="m024-timeout-restore")
    generation = token["generation"]
    event_conn = await db.connect()
    permit_conn = await db.connect()
    writer_conn = await db.connect()
    try:
        for setting, expected in (("0", "0"), ("150ms", "150ms")):
            event_value = await propose_and_show_timeout(event_conn, setting, base)
            assert event_value == expected, ("event guard", setting, event_value)

            permit_value = await update_permit_and_show_timeout(
                permit_conn, cid, generation, setting)
            assert permit_value == expected, ("permit guard", setting, permit_value)

            writer_allowed, writer_value = await writer_epoch_and_show_timeout(
                writer_conn, cid, generation, setting)
            assert writer_allowed is False  # LEGACY is not READY; row acquisition still succeeds.
            assert writer_value == expected, ("writer epoch", setting, writer_value)
    finally:
        for conn in (event_conn, permit_conn, writer_conn):
            await conn.close()
    print("PASS: successful event, permit, and writer-epoch lock acquisitions restore "
          "caller lock_timeout for default and short settings")


async def test_timeout_savepoint_restores_setting_and_outer_transaction(db) -> None:
    holder = await db.connect()
    caller = await db.connect()
    tx = await lock_fence_row(holder)
    outer = caller.transaction()
    await outer.start()
    try:
        await caller.execute('SET LOCAL ROLE "clt_alice"')
        await caller.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        await caller.fetchval("SELECT set_config('lock_timeout','150ms',true)")

        savepoint = caller.transaction()
        await savepoint.start()
        await expect_pg_error("lock timeout", propose_with_timeout_in_open_transaction(caller))
        await savepoint.rollback()

        restored = await caller.fetchval("SHOW lock_timeout")
        assert restored == "150ms", restored
        assert await caller.fetchval("SELECT 1") == 1
        print("PASS: caught lifecycle lock timeout rolls back to savepoint, restores 150ms, "
              "and leaves outer transaction usable")
    finally:
        await outer.rollback()
        await tx.rollback()
        await holder.close()
        await caller.close()


async def propose_with_timeout_in_open_transaction(conn: asyncpg.Connection):
    return await conn.fetchval(
        "SELECT change_ledger.propose($1::text,$2::text,$3::uuid,$4::text,$5::text,$6::text,"
        "$7::text,$8::text,$9::text,$10::text,$11::text,$12::uuid,$13::timestamptz,$14::uuid)",
        T, C, uuid4(), "POST", "base-1", "org-1", "clt_alice", uuid4().hex,
        fixture_digest_for("POST"), "m024-timeout-savepoint", "v1", None, exp(), None)


async def test_bounded_lock_waits(db, led: L) -> None:
    # Prepare a genuine permit before holding the lifecycle fence row.
    cid, token, _call_id = await led.unknown(kind="POST", target="m023-lock-guard")
    generation = token["generation"]
    holder = await db.connect()
    event_conn = await db.connect()
    permit_conn = await db.connect()
    writer_conn = await db.connect()
    try:
        # No caller override: migration 023 must turn PostgreSQL's unlimited (0) into <=5s.
        tx = await lock_fence_row(holder)
        try:
            default_timeout = await expect_lock_timeout(
                    propose_with_timeout(event_conn, lock_timeout=None), max_seconds=7.0)
        finally:
            await tx.rollback()
        assert 4.0 <= default_timeout < 7.0, (
            "default lock wait should demonstrate the configured five-second cap; "
            f"observed {default_timeout:.3f}s")

        # Events/permit guard custom short timeout: an event insertion must retain 150ms.
        tx = await lock_fence_row(holder)
        try:
            short_event = await expect_lock_timeout(
                propose_with_timeout(event_conn, lock_timeout="150ms"), max_seconds=1.5)
        finally:
            await tx.rollback()
        assert short_event < 1.5, short_event

        # Exercise the actual permit BEFORE UPDATE trigger while the same scope row is locked.
        tx = await lock_fence_row(holder)
        try:
            short_permit = await expect_lock_timeout(
                    update_permit_with_timeout(permit_conn, cid, generation, "150ms"), max_seconds=1.5)
        finally:
            await tx.rollback()
        assert short_permit < 1.5, short_permit

        # Exercise the writer pre-call epoch function directly, with a shorter caller timeout.
        tx = await lock_fence_row(holder)
        try:
            short_writer = await expect_lock_timeout(
                scoped_call(writer_conn, "clt_wri",
                            "SELECT change_ledger.lifecycle_writer_epoch($1::text,$2::text,$3::uuid,$4::bigint,$5::bigint)",
                            cid, generation, 0, lock_timeout="150ms"), max_seconds=1.5)
        finally:
            await tx.rollback()
        assert short_writer < 1.5, short_writer
        print("PASS: lifecycle event, dispatch permit, and writer-epoch waits are bounded; "
              f"default={default_timeout:.3f}s, caller-short="
              f"{short_event:.3f}/{short_permit:.3f}/{short_writer:.3f}s")
    finally:
        for conn in (event_conn, permit_conn, writer_conn, holder):
            await conn.close()


async def run() -> None:
    async with disposable_cluster() as (dsn, container, owner_token):
        async with throwaway_db(dsn) as db:
            # throwaway_db applies 001-018 and seeds the isolated base registry.
            for filename in MIGRATION_CHAIN[:-3]:
                await apply_migration(db.conn, MIGRATIONS / filename)
            await _setup(db.conn)
            for filename in MIGRATION_CHAIN[-3:]:
                await apply_migration(db.conn, MIGRATIONS / filename)
            versions = await db.conn.fetch("SELECT version FROM living.schema_migrations ORDER BY version")
            installed = {row["version"] for row in versions}
            expected = {f"{version:03d}" for version in range(1, 25)}
            assert installed == expected, (sorted(installed), sorted(expected))

            led = L(db)
            await test_recovery_is_denied_and_fail_closed(db, led)
            await test_migration_is_idempotent(db)
            await test_bounded_lock_waits(db, led)
            await test_success_restores_caller_lock_timeout(db, led)
            await test_timeout_savepoint_restores_setting_and_outer_transaction(db)
            print(f"PASS: S13 migration 023-024 focused acceptance on owned PostgreSQL container "
                  f"{container}; owner token {owner_token[:8]}")


if __name__ == "__main__":
    asyncio.run(run())
