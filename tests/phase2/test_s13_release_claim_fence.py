"""Focused disposable-PG qualification for candidate S13 release_claim behavior.

This slice covers issued-token release, replay/refusal/authorization/expiry branches, repair
handoff, and one deterministic frozen-plan mutation. It does not claim the full S13 race matrix.
Run only with: uv run pytest -q -s tests/phase2/test_s13_release_claim_fence.py
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import disposable_cluster
from test_change_ledger_sql import _repair
from test_s13_current_turn_sql import L, _OwnedClusterDsn, _expect_code, _ledger_snapshot, ledger

pytestmark = pytest.mark.integration

T = "T1"
C = "C1"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def owned_cluster_dsn() -> AsyncIterator[_OwnedClusterDsn]:
    """Use the shared invocation-owned PG16 harness and expose generated identity only."""
    old_opt_in = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, name, _owner_token):
            print(f"S13_DISPOSABLE_PG_CONTAINER={name}")
            yield _OwnedClusterDsn(dsn)
    finally:
        if old_opt_in is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old_opt_in


async def _wait_for_namespace7_wait(conn: asyncpg.Connection, application_name: str,
                                    task: asyncio.Task, scenario_id: str,
                                    scope_key: str, timeout: float = 5.0) -> int:
    """Return the exact contender PID waiting on the expected exclusive namespace-7 tuple."""
    deadline = asyncio.get_running_loop().time() + timeout
    last_wait: str | None = None
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            await task
            raise AssertionError(f"{scenario_id}: release_claim did not wait on namespace 7")
        row = await conn.fetchrow(
            """SELECT a.pid,a.wait_event_type,a.wait_event,EXISTS (
                   SELECT 1 FROM pg_catalog.pg_locks l
                   WHERE l.pid=a.pid AND l.locktype='advisory' AND l.classid=7::oid
                     AND l.objid=((pg_catalog.hashtext($2)::bigint & 4294967295)::oid)
                     AND l.objsubid=2 AND l.mode='ExclusiveLock' AND NOT l.granted
                 ) AS waiting_on_expected_lock
                 FROM pg_catalog.pg_stat_activity a WHERE a.application_name=$1""",
            application_name,
            scope_key,
        )
        if row:
            last_wait = (
                f"pid={row['pid']} wait_event_type={row['wait_event_type']} "
                f"wait_event={row['wait_event']} target_lock={row['waiting_on_expected_lock']}"
            )
        if (row and row["wait_event_type"] == "Lock" and row["wait_event"] == "advisory"
                and row["waiting_on_expected_lock"]):
            return row["pid"]
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{scenario_id}: namespace-7 tuple wait was not observed; {last_wait}"
    )


async def _wait_for_global_fence_wait(conn: asyncpg.Connection, application_name: str,
                                     task: asyncio.Task, scenario_id: str,
                                     global_key: str, timeout: float = 5.0) -> int:
    """Return contender PID waiting on the exact namespace-6 identity tuple."""
    deadline = asyncio.get_running_loop().time() + timeout
    last_wait: str | None = None
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            await task
            raise AssertionError(f"{scenario_id}: release_claim did not wait on namespace 6")
        row = await conn.fetchrow(
            """SELECT a.pid,a.wait_event_type,a.wait_event,EXISTS (
                   SELECT 1 FROM pg_catalog.pg_locks l
                   WHERE l.pid=a.pid AND l.locktype='advisory' AND l.classid=6::oid
                     AND l.objid=((pg_catalog.hashtext($2)::bigint & 4294967295)::oid)
                     AND l.objsubid=2 AND l.mode='ExclusiveLock' AND NOT l.granted
                 ) AS waiting_on_expected_lock
                 FROM pg_catalog.pg_stat_activity a WHERE a.application_name=$1""",
            application_name,
            global_key,
        )
        if row:
            last_wait = (
                f"pid={row['pid']} wait_event_type={row['wait_event_type']} "
                f"wait_event={row['wait_event']} target_lock={row['waiting_on_expected_lock']}"
            )
        if (row and row["wait_event_type"] == "Lock" and row["wait_event"] == "advisory"
                and row["waiting_on_expected_lock"]):
            return row["pid"]
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{scenario_id}: namespace-6 tuple wait was not observed; {last_wait}"
    )


async def _wait_for_blocker_pid(conn: asyncpg.Connection, application_name: str,
                                task: asyncio.Task, scenario_id: str,
                                blocker_pid: int, timeout: float = 5.0) -> int:
    """Return contender PID blocked by the sole fixture-held parent record row lock."""
    deadline = asyncio.get_running_loop().time() + timeout
    last_wait: str | None = None
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            await task
            raise AssertionError(f"{scenario_id}: release_claim did not wait for parent row lock")
        row = await conn.fetchrow(
            """SELECT a.pid,a.wait_event_type,a.wait_event,
                      $2::integer=ANY(pg_catalog.pg_blocking_pids(a.pid)) AS blocked_by_fixture
                 FROM pg_catalog.pg_stat_activity a WHERE a.application_name=$1""",
            application_name,
            blocker_pid,
        )
        if row:
            last_wait = (
                f"pid={row['pid']} wait_event_type={row['wait_event_type']} "
                f"wait_event={row['wait_event']} blocked_by_fixture={row['blocked_by_fixture']}"
            )
        if (row and row["wait_event_type"] == "Lock" and row["wait_event"] == "transactionid"
                and row["blocked_by_fixture"]):
            return row["pid"]
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{scenario_id}: expected parent row-lock wait was not observed; {last_wait}"
    )


async def _call_release_claim(conn: asyncpg.Connection, application_name: str,
                              token_id: object, *, role: str = "clt_alice",
                              tenant: str = T, company: str = C) -> str:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", tenant, company)
        return await conn.fetchval(
            "SELECT change_ledger.release_claim($1,$2,$3)", tenant, company, token_id
        )


async def _claimed(ledger: L) -> tuple[object, asyncpg.Record]:
    change_id = await ledger.approved()
    token = await ledger.claimed(change_id, observe=False)
    return change_id, token


async def _seed_failed_verify_parent(ledger: L) -> uuid.UUID:
    """Seed only the canonical parent/hold/target-lock facts required for a repair claim.

    Candidate migration 027 intentionally revokes the legacy dispatch/verification routes, so the
    disposable fixture seeds the historical FAILED_VERIFY parent facts directly. The repair
    proposal, approval, claim, and release then use the candidate/bridged runtime entry functions.
    """
    parent_id = uuid.uuid4()
    await ledger.conn.execute(
        "INSERT INTO change_ledger.records "
        "(change_id,tenant_id,company_id,base_fingerprint,organization_ref,kind,requester,"
        "request_id,payload_digest,target_ref,target_version,lifecycle,authorization_state,"
        "execution_state,verification_state,call_ownership,attribution,effect_known,"
        "reservation_state,dispatch_state,auth_epoch_at_proposal,expires_at) "
        "VALUES($1,$2,$3,'base-1','org-1','POST','clt_alice',$4,$5,'doc1','v1',"
        "'VALIDATED','APPROVED','APPLIED','FAILED_VERIFY','PROVEN_FINISHED','PROVEN','YES',"
        "'CONSUMED','NOT_PERMITTED',0,pg_catalog.clock_timestamp()+interval '1 hour')",
        parent_id,
        T,
        C,
        f"s13-repair-parent-{parent_id.hex}",
        "a" * 64,
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.target_locks "
        "(tenant_id,company_id,base_fingerprint,target_ref,owner_change_id) "
        "VALUES($1,$2,'base-1','doc1',$3)", T, C, parent_id
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.holds "
        "(tenant_id,company_id,base_fingerprint,cause,change_id) "
        "VALUES($1,$2,'base-1','FAILED_VERIFY_HALT',$3)", T, C, parent_id
    )
    return parent_id


async def _scope_event_count(ledger: L, change_id: object) -> int:
    return await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND change_id=$3", T, C, change_id
    )


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_waits_then_releases_resources_once(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-ENTRY-01: exact namespace-7 wait then one release effect."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id, token = await _claimed(ledger)
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-release-claim"
    scenario_id = "S13-UF54-RELEASE-CLAIM-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        events_before = await _scope_event_count(ledger, change_id)
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(
            _call_release_claim(contender, application_name, token["token_id"])
        )
        waiter_pid = await _wait_for_namespace7_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: any record/resource/event state changed before release"
        )
        assert await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_unlock(7,pg_catalog.hashtext($1))", scope_key
        ) is True

        result = await asyncio.wait_for(task, timeout=10)
        assert result == "SUPERSEDED", f"{scenario_id}: release outcome mismatch (waiter PID {waiter_pid})"
        released_token = await ledger.conn.fetchrow(
            "SELECT token_id,change_id,generation,state FROM change_ledger.claim_tokens "
            "WHERE token_id=$1", token["token_id"]
        )
        assert tuple(released_token) == (token["token_id"], change_id, 1, "SUPERSEDED")
        record = await ledger.conn.fetchrow(
            "SELECT authorization_state,execution_state,reservation_state "
            "FROM change_ledger.records WHERE change_id=$1", change_id
        )
        assert tuple(record) == ("APPROVED", "NOT_STARTED", "RELEASED")
        reservation = await ledger.conn.fetchrow(
            "SELECT state FROM change_ledger.reservations WHERE change_id=$1", change_id
        )
        assert reservation["state"] == "RELEASED"
        for relation in ("target_locks", "key_locks", "writer_leases"):
            assert await ledger.conn.fetchval(
                f"SELECT count(*) FROM change_ledger.{relation} WHERE owner_change_id=$1", change_id
            ) == 0, f"{scenario_id}: release left an owned {relation} row"
        events_after = await _scope_event_count(ledger, change_id)
        assert events_after == events_before + 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3 AND event_type='CLAIM_RELEASED'", T, C, change_id
        ) == 1
        after = await _ledger_snapshot(ledger.conn)
        assert after != before

        replay = await _call_release_claim(ledger.conn, "s13-uf54-release-replay", token["token_id"])
        assert replay == "SUPERSEDED"
        assert await _ledger_snapshot(ledger.conn) == after
        assert await _scope_event_count(ledger, change_id) == events_after
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await blocker.fetchval("SELECT pg_catalog.pg_advisory_unlock_all()")
        except asyncpg.PostgresError:
            pass
        await contender.close()
        await blocker.close()


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_missing_target_lock_refuses_without_delta(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-MISSING-TARGET-01: missing required owner returns LOCK_BUSY."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id, token = await _claimed(ledger)
    deleted = await ledger.conn.execute(
        "DELETE FROM change_ledger.target_locks WHERE owner_change_id=$1", change_id
    )
    assert deleted == "DELETE 1"
    before = await _ledger_snapshot(ledger.conn)
    events_before = await _scope_event_count(ledger, change_id)
    with pytest.raises(asyncpg.PostgresError, match="LOCK_BUSY"):
        await _call_release_claim(ledger.conn, "s13-uf54-release-missing-target", token["token_id"])
    assert await _ledger_snapshot(ledger.conn) == before
    assert await _scope_event_count(ledger, change_id) == events_before
    assert await ledger.conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]
    ) == "ISSUED"


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_wrong_target_owner_refuses_without_delta(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-WRONG-OWNER-01: another valid same-scope owner returns LOCK_BUSY."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id, token = await _claimed(ledger)
    other_change_id = await ledger.propose(budget=False, declare_class=False)
    moved = await ledger.conn.execute(
        "UPDATE change_ledger.target_locks SET owner_change_id=$2 WHERE owner_change_id=$1",
        change_id,
        other_change_id,
    )
    assert moved == "UPDATE 1"
    before = await _ledger_snapshot(ledger.conn)
    events_before = await _scope_event_count(ledger, change_id)
    with pytest.raises(asyncpg.PostgresError, match="LOCK_BUSY"):
        await _call_release_claim(ledger.conn, "s13-uf54-release-wrong-owner", token["token_id"])
    assert await _ledger_snapshot(ledger.conn) == before
    assert await _scope_event_count(ledger, change_id) == events_before
    assert await ledger.conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]
    ) == "ISSUED"


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_missing_token_refuses_without_delta(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-MISSING-TOKEN-01: absent token returns TICKET_SUPERSEDED."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    scenario_id = "S13-UF54-RELEASE-CLAIM-MISSING-TOKEN-01"
    before = await _ledger_snapshot(ledger.conn)
    await _expect_code(
        "TICKET_SUPERSEDED",
        _call_release_claim(ledger.conn, "s13-uf54-release-missing-token", uuid.uuid4()),
    )
    assert await _ledger_snapshot(ledger.conn) == before, (
        f"{scenario_id}: missing-token refusal changed ledger rows or events"
    )


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_wrong_scope_token_refuses_without_delta(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-WRONG-SCOPE-01: foreign-scope record returns CHANGE_NOT_FOUND."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id, token = await _claimed(ledger)
    # The independent fixture requester has access only to T2/C2. Seed that scope's required
    # lifecycle row, then present a valid T1/C1 token through the T2/C2 entry boundary.
    await ledger.conn.execute(
        "INSERT INTO change_ledger.lifecycle_fences"
        "(tenant_id,company_id,state,epoch,reason) VALUES('T2','C2','LEGACY',0,'TEST_FIXTURE')"
    )
    before = await _ledger_snapshot(ledger.conn)
    await _expect_code(
        "CHANGE_NOT_FOUND",
        _call_release_claim(
            ledger.conn, "s13-uf54-release-wrong-scope", token["token_id"],
            role="clt_zed", tenant="T2", company="C2",
        ),
    )
    assert await ledger.conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]
    ) == "ISSUED"
    assert await _ledger_snapshot(ledger.conn) == before, (
        "S13-UF54-RELEASE-CLAIM-WRONG-SCOPE-01: foreign-scope refusal changed ledger rows or events"
    )


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_worker_can_release_issued_token(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-WORKER-AUTH-01: worker_role is an authorized release caller."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id, token = await _claimed(ledger)
    before_events = await _scope_event_count(ledger, change_id)
    assert await ledger.conn.fetchval(
        "SELECT pg_catalog.has_function_privilege('clt_wrk',"
        "'change_ledger.release_claim(text,text,uuid)','EXECUTE')"
    ) is True
    result = await _call_release_claim(
        ledger.conn, "s13-uf54-release-worker", token["token_id"], role="clt_wrk"
    )
    assert result == "SUPERSEDED"
    assert await ledger.conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]
    ) == "SUPERSEDED"
    record = await ledger.conn.fetchrow(
        "SELECT authorization_state,execution_state,reservation_state "
        "FROM change_ledger.records WHERE change_id=$1", change_id
    )
    assert tuple(record) == ("APPROVED", "NOT_STARTED", "RELEASED")
    assert await _scope_event_count(ledger, change_id) == before_events + 1
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 "
        "AND event_type='CLAIM_RELEASED'", change_id
    ) == 1
    assert await ledger.locks(change_id) == (0, 0, 0)


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_expired_record_marks_authorization_expired(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-EXPIRED-01: release preserves expiry outcome and zero-effect cleanup."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id, token = await _claimed(ledger)
    await ledger.conn.execute(
        "UPDATE change_ledger.records SET "
        "created_at=pg_catalog.statement_timestamp()-interval '2 seconds', "
        "expires_at=pg_catalog.statement_timestamp()-interval '1 second' "
        "WHERE change_id=$1", change_id
    )
    events_before = await _scope_event_count(ledger, change_id)
    result = await _call_release_claim(
        ledger.conn, "s13-uf54-release-expired", token["token_id"]
    )
    assert result == "SUPERSEDED"
    assert await ledger.conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]
    ) == "SUPERSEDED"
    record = await ledger.conn.fetchrow(
        "SELECT authorization_state,execution_state,reservation_state "
        "FROM change_ledger.records WHERE change_id=$1", change_id
    )
    assert tuple(record) == ("EXPIRED", "NOT_STARTED", "RELEASED")
    assert await ledger.conn.fetchval(
        "SELECT state FROM change_ledger.reservations WHERE change_id=$1", change_id
    ) == "RELEASED"
    assert await ledger.locks(change_id) == (0, 0, 0)
    assert await _scope_event_count(ledger, change_id) == events_before + 1
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 "
        "AND event_type='CLAIM_RELEASED'", change_id
    ) == 1


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_repair_hands_target_lock_back_to_parent(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-REPAIR-HANDOFF-01: release waits for and restores repair parent."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    scenario_id = "S13-UF54-RELEASE-CLAIM-REPAIR-HANDOFF-01"
    parent_id = await _seed_failed_verify_parent(ledger)
    repair_id = await _repair(ledger, parent_id, rid="s13-release-repair-handoff")
    token = await ledger.claimed(repair_id, key="5" * 64, observe=False)
    token_id = token["token_id"]
    assert await ledger.tl_owner("base-1", "doc1") == repair_id
    assert await ledger.locks(repair_id) == (1, 1, 1)
    assert await ledger.open_holds("FAILED_VERIFY_HALT") == 1

    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-release-repair-parent-lock"
    lock_tx = blocker.transaction()
    parent_lock_held = False
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        events_before = await _scope_event_count(ledger, repair_id)
        blocker_pid = await blocker.fetchval("SELECT pg_catalog.pg_backend_pid()")
        await lock_tx.start()
        await blocker.fetchrow(
            "SELECT change_id FROM change_ledger.records WHERE change_id=$1 FOR UPDATE", parent_id
        )
        parent_lock_held = True
        task = asyncio.create_task(
            _call_release_claim(contender, application_name, token_id)
        )
        waiter_pid = await _wait_for_blocker_pid(
            ledger.conn, application_name, task, scenario_id, blocker_pid
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: release changed records/resources/events before parent lock release"
        )
        await lock_tx.rollback()
        parent_lock_held = False

        result = await asyncio.wait_for(task, timeout=10)
        assert result == "SUPERSEDED", f"{scenario_id}: unexpected result from PID {waiter_pid}"
        assert await ledger.conn.fetchval(
            "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token_id
        ) == "SUPERSEDED"
        repair_record = await ledger.conn.fetchrow(
            "SELECT repair_for,authorization_state,execution_state,reservation_state "
            "FROM change_ledger.records WHERE change_id=$1", repair_id
        )
        assert tuple(repair_record) == (parent_id, "APPROVED", "NOT_STARTED", "RELEASED")
        assert await ledger.tl_owner("base-1", "doc1") == parent_id
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.target_locks "
            "WHERE base_fingerprint='base-1' AND target_ref='doc1'"
        ) == 1
        assert await ledger.locks(repair_id) == (0, 0, 0)
        assert await ledger.open_holds("FAILED_VERIFY_HALT") == 1
        assert (await ledger.rec(parent_id))["verification_state"] == "FAILED_VERIFY"
        assert await _scope_event_count(ledger, repair_id) == events_before + 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 "
            "AND event_type='CLAIM_RELEASED'", repair_id
        ) == 1
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if parent_lock_held:
            try:
                await lock_tx.rollback()
            except (asyncpg.PostgresError, asyncpg.InterfaceError):
                pass
        await contender.close()
        await blocker.close()


@pytest.mark.asyncio
async def test_s13_uf54_release_claim_refuses_parent_mutated_after_plan_snapshot(ledger: L) -> None:
    """S13-UF54-RELEASE-CLAIM-PLAN-STALE-01: namespace-6 wait exposes frozen-plan recheck."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    scenario_id = "S13-UF54-RELEASE-CLAIM-PLAN-STALE-01"
    change_id, token = await _claimed(ledger)
    global_key = f"record-change-id:v1:{str(change_id).lower()}"
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-release-plan-stale"
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        events_before = await _scope_event_count(ledger, change_id)
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_lock(6,pg_catalog.hashtext($1))", global_key
        )
        task = asyncio.create_task(
            _call_release_claim(contender, application_name, token["token_id"])
        )
        waiter_pid = await _wait_for_global_fence_wait(
            ledger.conn, application_name, task, scenario_id, global_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: release changed state before acquiring the namespace-6 fence"
        )

        updated = await ledger.conn.execute(
            "UPDATE change_ledger.records SET updated_at=pg_catalog.clock_timestamp() "
            "WHERE change_id=$1", change_id
        )
        assert updated == "UPDATE 1"
        mutated_snapshot = await _ledger_snapshot(ledger.conn)
        assert mutated_snapshot != before, f"{scenario_id}: fixture mutation was not observable"
        assert await _scope_event_count(ledger, change_id) == events_before
        assert await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_unlock(6,pg_catalog.hashtext($1))", global_key
        ) is True

        await _expect_code(
            "LOCK_PLAN_STALE", asyncio.wait_for(task, timeout=10)
        )
        assert await _ledger_snapshot(ledger.conn) == mutated_snapshot, (
            f"{scenario_id}: stale-plan refusal changed state beyond the controlled fixture mutation"
        )
        assert await _scope_event_count(ledger, change_id) == events_before
        assert await ledger.conn.fetchval(
            "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]
        ) == "ISSUED"
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await blocker.fetchval("SELECT pg_catalog.pg_advisory_unlock_all()")
        except asyncpg.PostgresError:
            pass
        await contender.close()
        await blocker.close()
