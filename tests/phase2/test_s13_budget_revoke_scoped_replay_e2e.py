"""Disposable PostgreSQL qualification for scoped budget-revoke replay and races."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import uuid

import asyncpg
import pytest

pytest_plugins = ("test_s13_current_turn_sql",)

from test_change_ledger_sql import C, C2, L, T, T2
from test_s13_current_turn_sql import _ledger_snapshot, ledger

pytestmark = pytest.mark.integration


def _grant_key(grant_id: uuid.UUID) -> str:
    return f"grant-id:v1:{str(grant_id).lower()}"


def _scope_key(tenant: str, company: str) -> str:
    return (f"s13-scope:v1:{len(tenant.encode('utf-8'))}:{tenant}:"
            f"{len(company.encode('utf-8'))}:{company}")


async def _revoke(conn: asyncpg.Connection, tenant: str, company: str,
                  grant_id: uuid.UUID) -> tuple[str, str, str | None]:
    try:
        async with conn.transaction():
            await conn.execute('SET LOCAL ROLE "clt_dave"')
            await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", tenant, company)
            result = await conn.fetchval(
                "SELECT change_ledger.budget_revoke($1,$2,$3)", tenant, company, grant_id,
            )
        return ("ok", result, None)
    except asyncpg.PostgresError as error:
        return ("error", error.sqlstate, getattr(error, "message_primary", None)
                or str(error).splitlines()[0])


async def _wait_for_global_grant_lock(
        monitor: asyncpg.Connection, waiting_pid: int, blocker_pid: int,
        key: str, task: asyncio.Task, timeout: float = 8.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        last = await monitor.fetchrow(
            "SELECT wait_event_type,pg_catalog.pg_blocking_pids(pid) AS blockers "
            "FROM pg_catalog.pg_stat_activity WHERE pid=$1", waiting_pid,
        )
        identity = await monitor.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks WHERE pid=$1 "
            "AND locktype='advisory' AND classid=6::oid "
            "AND objid=((pg_catalog.hashtext($2)::bigint & 4294967295)::oid) "
            "AND objsubid=2 AND mode='ExclusiveLock' AND NOT granted)", waiting_pid, key,
        )
        if (last is not None and last["wait_event_type"] == "Lock"
                and blocker_pid in last["blockers"] and identity):
            return
        if task.done():
            task.result()
            raise AssertionError(f"revoke returned before global grant lock; activity={last}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for exact global grant lock; activity={last}")


async def _ensure_second_operator_scope(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) "
        "VALUES('operator_role',$1,$2) ON CONFLICT(role_name,tenant_id,company_id) DO NOTHING",
        T2, C2,
    )
    await conn.execute(
        "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
        "VALUES($1,$2,'LEGACY',0,'SYNTHETIC_TEST') "
        "ON CONFLICT(tenant_id,company_id) DO NOTHING", T2, C2,
    )


async def test_s13_budget_revoke_owner_replay_and_cross_scope_race(ledger: L) -> None:
    conn = ledger.conn
    await _ensure_second_operator_scope(conn)
    grant_id = uuid.uuid4()
    now = datetime.now(UTC)
    assert await ledger.call(
        "clt_dave", "budget_admin", grant_id, "EUR", 100, 3, 2,
        now - timedelta(minutes=1), now + timedelta(days=1),
    ) == grant_id
    assert await conn.fetchval(
        "SELECT status='ACTIVE' FROM change_ledger.grants WHERE grant_id=$1 "
        "AND tenant_id=$2 AND company_id=$3", grant_id, T, C,
    ) is True

    # Bind the actual candidate body to the promised lock plan: scope-7, global grant-ID
    # namespace-6, then the grant parent. The revoke path must not depend on namespace-2.
    body = await conn.fetchval(
        "SELECT p.prosrc FROM pg_catalog.pg_proc p "
        "WHERE p.oid='change_ledger.budget_revoke_v1(text,text,uuid)'::regprocedure",
    )
    scope_fence = body.index("private_writer_take_scope_fence_v1")
    global_fence = body.index("private_writer_take_global_fences_v1")
    parent_lock = body.index("SELECT * INTO ex FROM change_ledger.grants g")
    assert scope_fence < global_fence < parent_lock
    key_array_end = body.index("]", global_fence)
    key_array = body[global_fence:key_array_end]
    assert "'grant-id:v1:'||pg_catalog.lower(p_grant_id::text)" in key_array
    assert "FOR UPDATE" in body[parent_lock:]
    assert all(token not in body for token in (
        "private_writer_take_switch_fence_v1", "assert_switch_off", "kill_switch",
    ))

    owner_conn, foreign_conn, blocker, monitor = [await ledger.db.connect() for _ in range(4)]
    owner_pid = await owner_conn.fetchval("SELECT pg_catalog.pg_backend_pid()")
    foreign_pid = await foreign_conn.fetchval("SELECT pg_catalog.pg_backend_pid()")
    blocker_pid = await blocker.fetchval("SELECT pg_catalog.pg_backend_pid()")
    key = _grant_key(grant_id)
    scope_keys = {owner_pid: _scope_key(T, C), foreign_pid: _scope_key(T2, C2)}
    gate = blocker.transaction()
    tasks: list[asyncio.Task] = []
    gate_started = False
    gate_committed = False
    before_race = await _ledger_snapshot(conn)
    try:
        await gate.start()
        gate_started = True
        await blocker.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(6,pg_catalog.hashtext($1))", key,
        )
        owner_task = asyncio.create_task(_revoke(owner_conn, T, C, grant_id))
        foreign_task = asyncio.create_task(_revoke(foreign_conn, T2, C2, grant_id))
        tasks.extend((owner_task, foreign_task))
        # Poll one observer connection at a time; both contenders are already running and
        # queued behind the held grant-ID fence.
        await _wait_for_global_grant_lock(monitor, owner_pid, blocker_pid, key, owner_task)
        await _wait_for_global_grant_lock(monitor, foreign_pid, blocker_pid, key, foreign_task)

        # Each contender must own its separate scope-7 fence while both wait on the same
        # exact namespace-6 grant-ID fence; neither may take the kill-switch namespace-2 lock.
        for pid, scope in scope_keys.items():
            scope_wait = await monitor.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks WHERE pid=$1 "
                "AND locktype='advisory' AND classid=7::oid "
                "AND objid=((pg_catalog.hashtext($2)::bigint & 4294967295)::oid) "
                "AND objsubid=2 AND mode='ExclusiveLock' AND granted)", pid, scope,
            )
            assert scope_wait, (pid, scope)
        assert not await monitor.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks WHERE pid=ANY($1::int[]) "
            "AND locktype='advisory' AND classid=2::oid)", [owner_pid, foreign_pid],
        )
        assert await _ledger_snapshot(conn) == before_race

        await gate.commit()
        gate_committed = True
        owner_result, foreign_result = await asyncio.wait_for(
            asyncio.gather(owner_task, foreign_task), timeout=10,
        )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if gate_started and not gate_committed and blocker.is_in_transaction():
            await gate.rollback()
        for item in (owner_conn, foreign_conn, blocker, monitor):
            await item.close()

    assert owner_result == ("ok", "REVOKED", None)
    assert foreign_result == ("error", "P0001", "SCOPE_NOT_GRANTED")
    grant = await conn.fetchrow(
        "SELECT tenant_id,company_id,status FROM change_ledger.grants WHERE grant_id=$1", grant_id,
    )
    assert tuple(grant) == (T, C, "REVOKED")
    revoke_events = await conn.fetch(
        "SELECT seq,payload FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND event_type='BUDGET_GRANT_REVOKED' AND payload->>'grant_id'=$3", T, C, str(grant_id),
    )
    assert len(revoke_events) == 1
    payload = revoke_events[0]["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["by"] == "clt_dave"

    before_foreign_retry = await _ledger_snapshot(conn)
    assert await _revoke(conn, T2, C2, grant_id) == (
        "error", "P0001", "SCOPE_NOT_GRANTED",
    )
    assert await _ledger_snapshot(conn) == before_foreign_retry

    after_race = await _ledger_snapshot(conn)
    assert after_race != before_race
    assert await _revoke(conn, T, C, grant_id) == ("ok", "REVOKED", None)
    assert await _ledger_snapshot(conn) == after_race


async def test_s13_budget_revoke_outer_rollback_is_atomic(ledger: L) -> None:
    conn = ledger.conn
    grant_id = uuid.uuid4()
    now = datetime.now(UTC)
    assert await ledger.call(
        "clt_dave", "budget_admin", grant_id, "EUR", 100, 3, 2,
        now - timedelta(minutes=1), now + timedelta(days=1),
    ) == grant_id
    assert await conn.fetchval(
        "SELECT status='ACTIVE' FROM change_ledger.grants WHERE grant_id=$1 "
        "AND tenant_id=$2 AND company_id=$3", grant_id, T, C,
    ) is True
    before = await _ledger_snapshot(conn)

    with pytest.raises(RuntimeError, match="synthetic rollback before commit"):
        async with conn.transaction():
            await conn.execute('SET LOCAL ROLE "clt_dave"')
            await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
            assert await conn.fetchval(
                "SELECT change_ledger.budget_revoke($1,$2,$3)", T, C, grant_id,
            ) == "REVOKED"
            # Simulate a failure after SQL effects but before the caller commits the operation.
            raise RuntimeError("synthetic rollback before commit")

    assert await _ledger_snapshot(conn) == before
    assert await conn.fetchval(
        "SELECT status='ACTIVE' FROM change_ledger.grants WHERE grant_id=$1 "
        "AND tenant_id=$2 AND company_id=$3", grant_id, T, C,
    ) is True
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND event_type='BUDGET_GRANT_REVOKED' AND payload->>'grant_id'=$3",
        T, C, str(grant_id),
    ) == 0
