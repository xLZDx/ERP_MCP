"""V2-S13 migration 023 PostgreSQL lifecycle safety journeys.

Run directly with the repository Python, never through pytest:
    .venv/Scripts/python.exe tests/phase2/test_s13_migration023_e2e.py

The runner owns a loopback-only disposable PostgreSQL container and throwaway database, applies
the complete 001-023 predecessor chain, and checks the lifecycle refusal and bounded-lock
contract across independent connections. This does not cover a real physical writer or 1C.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path

import asyncpg

from _pg_harness import disposable_cluster, docker, throwaway_db
from test_change_ledger_sql import C, L, T, _setup


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
POST_BASE_MIGRATIONS = (
    "019_ed25519_action_only.sql",
    "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql",
    "022_lifecycle_epoch_fence.sql",
    "023_lifecycle_activation_cap.sql",
)


async def apply(conn: asyncpg.Connection, filename: str) -> None:
    path = MIGRATIONS / filename
    raw = path.read_bytes()
    await conn.execute(
        "SELECT set_config('living.migration_checksum',$1,false)",
        hashlib.sha256(raw).hexdigest(),
    )
    await conn.execute(raw.decode("utf-8"))
    print(f"PROGRESS: applied {filename}", flush=True)


async def expect_error(needle: str, awaitable) -> asyncpg.PostgresError:
    try:
        await awaitable
    except asyncpg.PostgresError as error:
        assert needle in str(error), f"expected {needle!r}; got {error!s}"
        return error
    raise AssertionError(f"expected PostgreSQL error containing {needle!r}")


async def journey(db, led: L) -> None:
    observer = await db.connect()
    owner = await db.connect()
    locker = await db.connect()
    try:
        before = await observer.fetchrow(
            "SELECT state,epoch,reason FROM change_ledger.lifecycle_fences "
            "WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        assert tuple(before) == ("LEGACY", 0, "LIFECYCLE_NOT_ACTIVATED"), tuple(before)

        # The application worker no longer has EXECUTE after 023. The attempt is made on a
        # physically separate session and must not alter the durable fence.
        worker_error = await expect_error(
            "permission denied for function lifecycle_begin_recovery",
            led.call("clt_wrk", "lifecycle_begin_recovery", conn=observer),
        )
        assert worker_error.sqlstate == "42501", (worker_error.sqlstate, str(worker_error))
        worker_after = await observer.fetchrow(
            "SELECT state,epoch,reason FROM change_ledger.lifecycle_fences "
            "WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        assert tuple(worker_after) == tuple(before), (tuple(before), tuple(worker_after))
        print("PASS: worker recovery API denied (42501); durable fence unchanged")

        # Exercise the owner-authorized SECURITY DEFINER API directly. It must reject before
        # writing, even for this privileged caller. ledger_owner receives scope only in this
        # disposable fixture so assert_scope follows the production scope contract.
        privileged_error = await expect_error(
            "LIFECYCLE_COORDINATOR_UNAVAILABLE",
            led.call("ledger_owner", "lifecycle_begin_recovery", conn=owner),
        )
        assert privileged_error.sqlstate == "P0001", (privileged_error.sqlstate, str(privileged_error))
        privileged_after = await observer.fetchrow(
            "SELECT state,epoch,reason FROM change_ledger.lifecycle_fences "
            "WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        assert tuple(privileged_after) == tuple(before), (tuple(before), tuple(privileged_after))
        print("PASS: privileged recovery API fails closed (P0001); durable fence unchanged")

        # Hold the fence row on one independent connection. Writer epoch admission on another
        # reaches the migration-023 bounded FOR SHARE lock and must time out at its 5s cap.
        await locker.execute("BEGIN")
        await locker.fetchrow(
            "SELECT state FROM change_ledger.lifecycle_fences "
            "WHERE tenant_id=$1 AND company_id=$2 FOR UPDATE", T, C
        )
        await observer.execute("BEGIN")
        await observer.execute('SET LOCAL ROLE "clt_wri"')
        await observer.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        started = time.monotonic()
        try:
            try:
                await observer.fetchval(
                    "SELECT change_ledger.lifecycle_writer_epoch($1,$2,$3::uuid,$4,$5)",
                    T, C, "00000000-0000-4000-8000-000000000001", 1, 0,
                )
            except asyncpg.PostgresError as caught:
                error = caught
                assert "lock timeout" in str(error), str(error)
            else:
                raise AssertionError("writer gate succeeded while the lifecycle row was locked")
            elapsed = time.monotonic() - started
        finally:
            await observer.execute("ROLLBACK")
            await locker.execute("ROLLBACK")
        assert error.sqlstate == "55P03", (error.sqlstate, str(error))
        assert 4.0 <= elapsed < 7.0, f"5s configured lock cap not observed: {elapsed:.3f}s"
        after_contention = await observer.fetchrow(
            "SELECT state,epoch,reason FROM change_ledger.lifecycle_fences "
            "WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        assert tuple(after_contention) == tuple(before), (tuple(before), tuple(after_contention))
        print(f"PASS: lifecycle writer gate failed closed after {elapsed:.3f}s (55P03); fence unchanged")
    finally:
        for conn in (observer, owner, locker):
            if not conn.is_closed():
                await conn.close()


async def main() -> int:
    import os

    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    container_name = image_tag = image_id = volume_name = None
    async with disposable_cluster() as (dsn, container_name, token):
        identity = docker(
            "inspect", "--format",
            "{{.Config.Image}}|{{.Image}}|{{range .Mounts}}{{if eq .Type \"volume\"}}{{.Name}}{{end}}{{end}}",
            container_name, timeout=30,
        )
        assert identity.returncode == 0, identity.stderr.decode(errors="replace")
        image_tag, image_id, volume_name = identity.stdout.decode().strip().split("|", 2)
        async with throwaway_db(dsn, seed=False) as db:
            # throwaway_db applies 001-018; fixtures and the remaining predecessor chain follow.
            for filename in POST_BASE_MIGRATIONS[:3]:
                await apply(db.conn, filename)
            await _setup(db.conn)
            await db.conn.execute("SELECT change_ledger.add_role_scope('ledger_owner',$1,$2)", T, C)
            for filename in POST_BASE_MIGRATIONS[3:]:
                await apply(db.conn, filename)
            version_rows = await db.conn.fetch(
                "SELECT version FROM living.schema_migrations WHERE version IN ('001','018','019','020','021','022','023')"
            )
            versions = {row["version"] for row in version_rows}
            assert versions == {"001", "018", "019", "020", "021", "022", "023"}, versions
            print(f"PROGRESS: PostgreSQL {await db.conn.fetchval('SHOW server_version')} ready", flush=True)
            await journey(db, L(db))
    assert docker("inspect", container_name, timeout=30).returncode != 0, "owned container remains after cleanup"
    assert docker("volume", "inspect", volume_name, timeout=30).returncode != 0, "owned anonymous volume remains"
    digest = docker("image", "inspect", image_tag, "--format", "{{.Id}}", timeout=30)
    assert digest.returncode == 0 and digest.stdout.decode().strip() == image_id
    print(f"Suite: PASS — 1 V2-S13 migration 023 lifecycle safety journey; container={container_name}")
    print(f"CLEANUP: container={container_name} absent; anonymous_volume={volume_name} absent")
    print(f"IMAGE: {image_tag} {image_id}")
    print(f"DATABASE: disposable PostgreSQL 16 image configured by harness; ownership token={token[:8]}")
    print("LIMIT: no physical-writer/1C dispatch integration; that acceptance remains open")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
