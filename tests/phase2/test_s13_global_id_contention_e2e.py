"""S13 cross-scope global-ID advisory-fence E2E acceptance.

This scenario uses only one invocation-owned disposable PostgreSQL 16 cluster and a
throwaway database. It does not connect to the configured lane or a 1C/COM service.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import apply_files, disposable_cluster, throwaway_db
from test_change_ledger_sql import C, C2, DIGEST, L, ORG, T, T2, _setup, exp
from test_s13_current_turn_sql import MIGRATIONS_019_027, _apply_migration, _ledger_snapshot

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def isolated_s13_ledger() -> AsyncIterator[L]:
    """Provision and own every container and database used by this E2E scenario."""
    old_opt_in = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, container_name, owner_token):
            # Identity is safe to report; credentials remain inside the fixture helper.
            print(f"S13_E2E_DISPOSABLE_PG_CONTAINER={container_name}")
            print(f"S13_E2E_DISPOSABLE_PG_OWNER_LABEL_VERIFIED={bool(owner_token)}")
            async with throwaway_db(dsn, migrate=False, seed=False) as db:
                db.conn = await db.connect()
                await apply_files(db.conn)
                for migration in MIGRATIONS_019_027:
                    await _apply_migration(db.conn, migration)
                await _setup(db.conn)
                # `_setup` creates synthetic target/role fixtures for T1/C1 and T2/C2.
                # Candidate routines require an explicit lifecycle row for each scope.
                await db.conn.executemany(
                    "INSERT INTO change_ledger.lifecycle_fences "
                    "(tenant_id,company_id,state,epoch,reason) "
                    "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE') "
                    "ON CONFLICT(tenant_id,company_id) DO NOTHING",
                    [(T, C), (T2, C2)],
                )
                yield L(db)
    finally:
        if old_opt_in is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old_opt_in


async def _wait_for_namespace6_waits(
    observer: asyncpg.Connection,
    application_names: tuple[str, str],
    lock_key: str,
    tasks: tuple[asyncio.Task, asyncio.Task],
    timeout: float = 5.0,
) -> None:
    """Wait until both distinct scopes are blocked on the exact same namespace-6 key."""
    expected_hash = await observer.fetchval("SELECT pg_catalog.hashtext($1)", lock_key)
    expected_objid = int(expected_hash) & 0xFFFFFFFF
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for task in tasks:
            if task.done():
                await task
                raise AssertionError("cross-scope proposal returned before its namespace-6 fence")
        rows = await observer.fetch(
            "SELECT a.application_name,l.classid,l.objid,l.objsubid,l.granted "
            "FROM pg_catalog.pg_locks l "
            "JOIN pg_catalog.pg_stat_activity a ON a.pid=l.pid "
            "WHERE a.application_name=ANY($1::text[]) AND l.locktype='advisory' "
            "AND NOT l.granted",
            list(application_names),
        )
        waiting = {
            row["application_name"] for row in rows
            if int(row["classid"]) == 6
            and int(row["objid"]) == expected_objid
            and int(row["objsubid"]) == 2
        }
        if waiting == set(application_names):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("both proposals did not wait on the same namespace-6 record-ID fence")


async def _propose(
    ledger: L,
    conn: asyncpg.Connection,
    *,
    role: str,
    tenant: str,
    company: str,
    base: str,
    change_id: uuid.UUID,
    application_name: str,
) -> uuid.UUID:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    return await ledger.call(
        role,
        "propose",
        change_id,
        "CREATE_DRAFT",
        base,
        ORG,
        role,
        f"s13-e2e-{application_name}",
        DIGEST,
        f"target-{application_name}",
        "v1",
        None,
        exp(),
        None,
        t=tenant,
        c=company,
        conn=conn,
    )


@pytest.mark.asyncio
async def test_s13_uf54_cross_scope_global_change_id_waits_before_rows(isolated_s13_ledger: L) -> None:
    """UF54-GLOBAL-ID-CROSS-SCOPE-01: same global ID waits before either scope writes."""
    ledger = isolated_s13_ledger
    change_id = uuid.uuid4()
    lock_key = f"record-change-id:v1:{str(change_id).lower()}"
    application_names = ("s13-e2e-propose-t1", "s13-e2e-propose-t2")
    blocker = await ledger.db.connect()
    first = await ledger.db.connect()
    second = await ledger.db.connect()
    blocker_tx = blocker.transaction()
    tasks: tuple[asyncio.Task, asyncio.Task] | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        await blocker_tx.start()
        await blocker.fetchval("SELECT pg_catalog.pg_advisory_xact_lock(6,pg_catalog.hashtext($1))", lock_key)
        tasks = (
            asyncio.create_task(_propose(
                ledger, first, role="clt_alice", tenant=T, company=C, base="base-1",
                change_id=change_id, application_name=application_names[0],
            )),
            asyncio.create_task(_propose(
                ledger, second, role="clt_zed", tenant=T2, company=C2, base="base-t2",
                change_id=change_id, application_name=application_names[1],
            )),
        )
        await _wait_for_namespace6_waits(ledger.conn, application_names, lock_key, tasks)

        # Negative control: while the shared namespace-6 lock is held, neither scope may
        # acquire row/unique/trigger effects, despite holding separate scope fences.
        assert await _ledger_snapshot(ledger.conn) == before
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.records WHERE change_id=$1", change_id,
        ) == 0
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE change_id=$1", change_id,
        ) == 0

        # Positive control: after releasing the blocker, exactly one scope may reserve the
        # global identity; the other must refuse with the stable cross-scope conflict.
        await blocker_tx.commit()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        successes = [item for item in outcomes if item == change_id]
        failures = [item for item in outcomes if isinstance(item, BaseException)]
        assert len(successes) == 1, outcomes
        assert len(failures) == 1, outcomes
        conflict = failures[0]
        assert isinstance(conflict, asyncpg.PostgresError), repr(conflict)
        assert conflict.sqlstate == "P0001", (conflict.sqlstate, str(conflict))
        assert str(conflict).splitlines()[0] == "CHANGE_ID_CONFLICT", str(conflict)

        record = await ledger.conn.fetchrow(
            "SELECT tenant_id,company_id FROM change_ledger.records WHERE change_id=$1", change_id,
        )
        assert record is not None
        assert (record["tenant_id"], record["company_id"]) in {(T, C), (T2, C2)}
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.records WHERE change_id=$1", change_id,
        ) == 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE change_id=$1", change_id,
        ) == 1
    finally:
        if tasks is not None:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await blocker_tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await second.close()
        await first.close()
        await blocker.close()
