"""Disposable PostgreSQL qualification of the legacy operator anchor-gap cosign bridge."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import uuid

import asyncpg
import pytest

pytest_plugins = ("test_s13_current_turn_sql",)

from test_change_ledger_sql import ACTORS, C, L, T
from test_s13_current_turn_sql import _expect_code, _ledger_snapshot, ledger

pytestmark = pytest.mark.integration

OLD = "change_ledger.anchor_gap_cosign(text,text,uuid,jsonb)"
V1 = "change_ledger.anchor_gap_cosign_v1(text,text,uuid,jsonb)"
V1_NAME = "change_ledger.anchor_gap_cosign_v1"


async def _login(ledger: L, label: str, actor: str = "clt_erin") -> str:
    login = f"s13_anchor_cosign_{label}_{uuid.uuid4().hex[:10]}"
    await ledger.conn.execute(f'CREATE ROLE "{login}" NOLOGIN')
    await ledger.conn.execute(f'GRANT "{actor}" TO "{login}"')
    return login


async def _call_as(ledger: L, conn: asyncpg.Connection, session: str, role: str,
                   hold_id: uuid.UUID, evidence: dict, *, t: str = T, c: str = C) -> uuid.UUID:
    async with conn.transaction():
        await conn.execute(f'SET LOCAL SESSION AUTHORIZATION "{session}"')
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        assert await conn.fetchval("SELECT session_user::text") == session
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
        result = await conn.fetchval("SELECT change_ledger.anchor_gap_cosign($1,$2,$3,$4::jsonb)",
                                     t, c, hold_id, json.dumps(evidence))
        assert await conn.fetchval("SELECT session_user::text") == session
        return result


async def _open_current_gap(ledger: L, label: str) -> asyncpg.Record:
    """Create an open hold through the existing anchor-check boundary on a synthetic head."""
    # The migration fixture has no event rows. Open one existing hold through the legacy
    # declaration API to establish a real ledger head, then compare the external hash at that
    # exact sequence through the anchor-check API.
    assert await ledger.call(
        "clt_wrk", "declare_anchor_gap", "base-8", json.dumps({"source": f"s13-cosign-fixture-{label}"}),
    ) in (0, 1)
    head = await ledger.call("clt_wrk", "ledger_head")
    assert head["seq"] > 0 and len(head["head_hash"]) == 64
    mismatched_hash = "0" * 64 if head["head_hash"] != "0" * 64 else "1" * 64
    result = await ledger.call("clt_wrk", "check_anchor", head["seq"], mismatched_hash)
    assert result["ok"] is False
    hold = await ledger.conn.fetchrow(
        "SELECT hold_id,tenant_id,company_id,base_fingerprint,cause,ext_seq,ext_head_hash,released_at "
        "FROM change_ledger.holds WHERE tenant_id=$1 AND company_id=$2 AND base_fingerprint=$3 "
        "AND cause='ANCHOR_GAP' AND released_at IS NULL ORDER BY opened_at,hold_id LIMIT 1", T, C, "base-1",
    )
    assert hold is not None, label
    assert hold["cause"] == "ANCHOR_GAP" and hold["released_at"] is None
    assert hold["ext_seq"] == head["seq"] and hold["ext_head_hash"] == mismatched_hash
    return hold


def _evidence(hold: asyncpg.Record, reconciliation: str = "synthetic current-head reconciliation") -> dict:
    return {
        "class": "a",
        "reconciliation": reconciliation,
        "ext_seq": hold["ext_seq"],
        "ext_head_hash": hold["ext_head_hash"],
    }


async def _wait_blocked(observer: asyncpg.Connection, waiting_pid: int, blocking_pid: int,
                        task: asyncio.Task, timeout: float = 8.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        last = await observer.fetchrow(
            "SELECT wait_event_type,pg_catalog.pg_blocking_pids(pid) AS blockers "
            "FROM pg_catalog.pg_stat_activity WHERE pid=$1", waiting_pid,
        )
        if last is not None and last["wait_event_type"] == "Lock" and blocking_pid in last["blockers"]:
            return
        if task.done():
            task.result()
            raise AssertionError(f"call finished before expected blocker: {last}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for pid={waiting_pid}; blocker={blocking_pid}; last={last}")


async def test_anchor_gap_cosign_legacy_owner_acl_identity_and_direct_v1_denial(ledger: L) -> None:
    conn = ledger.conn
    owner, security_definer, result_type, source = await conn.fetchrow(
        "SELECT pg_catalog.pg_get_userbyid(p.proowner),p.prosecdef,"
        "pg_catalog.pg_get_function_result(p.oid),p.prosrc FROM pg_catalog.pg_proc p WHERE p.oid=$1::regprocedure",
        OLD,
    )
    assert (owner, security_definer, result_type) == ("ledger_owner", True, "uuid")
    assert "anchor_gap_cosign_v1" in source
    acl = await conn.fetch(
        "SELECT r.rolname FROM pg_catalog.pg_proc p CROSS JOIN LATERAL "
        "pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a "
        "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE p.oid=$1::regprocedure "
        "AND a.privilege_type='EXECUTE' ORDER BY r.rolname", OLD,
    )
    assert [row["rolname"] for row in acl] == ["ledger_owner", "operator_role"]
    assert await conn.fetchval("SELECT pg_catalog.has_function_privilege('clt_erin',$1,'EXECUTE')", OLD)
    assert await conn.fetchval("SELECT pg_catalog.has_function_privilege('operator_role',$1,'EXECUTE')", OLD)
    assert not await conn.fetchval("SELECT pg_catalog.has_function_privilege('clt_wrk',$1,'EXECUTE')", OLD)
    assert not await conn.fetchval("SELECT pg_catalog.has_function_privilege('clt_erin',$1,'EXECUTE')", V1)

    hold = await _open_current_gap(ledger, "acl")
    login = await _login(ledger, "identity")
    evidence = _evidence(hold)
    cosign_id = await _call_as(ledger, conn, login, "clt_erin", hold["hold_id"], evidence)
    assert isinstance(cosign_id, uuid.UUID)
    row = await conn.fetchrow(
        "SELECT cosign_id,tenant_id,company_id,hold_id,signer,signer_session,evidence "
        "FROM change_ledger.hold_cosigns WHERE cosign_id=$1", cosign_id,
    )
    assert row is not None
    stored_evidence = json.loads(row["evidence"]) if isinstance(row["evidence"], str) else row["evidence"]
    assert (row["cosign_id"], row["tenant_id"], row["company_id"], row["hold_id"],
            row["signer"], row["signer_session"], stored_evidence) == (
        cosign_id, T, C, hold["hold_id"], "clt_erin", login,
        evidence,
    )
    for role in [*ACTORS.keys(), "requester_role", "approver_role", "operator_role", "writer_role",
                 "worker_role", "auditor_role", "checkpoint_role", "business_ai_private_writer",
                 "private_writer_evidence_ingest"]:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL ROLE "{role}"')
            with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
                await conn.fetchval(f"SELECT {V1_NAME}($1,$2,$3,$4::jsonb)",
                                    T, C, hold["hold_id"], json.dumps(evidence))
            assert denied.value.sqlstate == "42501"


async def test_anchor_gap_cosign_exact_retry_changed_evidence_and_distinct_witness(ledger: L) -> None:
    conn = ledger.conn
    hold = await _open_current_gap(ledger, "replay")
    erin, dave = await _login(ledger, "erin"), await _login(ledger, "dave", actor="clt_dave")
    first_evidence = _evidence(hold)
    before = await _ledger_snapshot(conn)
    first_id = await _call_as(ledger, conn, erin, "clt_erin", hold["hold_id"], first_evidence)
    after_first = await _ledger_snapshot(conn)
    assert after_first != before
    replay_id = await _call_as(ledger, conn, erin, "clt_erin", hold["hold_id"], first_evidence)
    assert replay_id == first_id
    assert await _ledger_snapshot(conn) == after_first

    changed_evidence = _evidence(hold, "second valid reconciliation observation")
    changed_id = await _call_as(ledger, conn, erin, "clt_erin", hold["hold_id"], changed_evidence)
    assert changed_id != first_id
    dave_id = await _call_as(ledger, conn, dave, "clt_dave", hold["hold_id"], first_evidence)
    assert dave_id not in {first_id, changed_id}
    rows = await conn.fetch(
        "SELECT cosign_id,signer,signer_session,evidence FROM change_ledger.hold_cosigns "
        "WHERE hold_id=$1 ORDER BY signer,signer_session", hold["hold_id"],
    )
    assert len(rows) == 3
    assert {(row["signer"], row["signer_session"], row["cosign_id"]) for row in rows} == {
        ("clt_erin", erin, first_id), ("clt_erin", erin, changed_id), ("clt_dave", dave, dave_id),
    }
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND event_type ILIKE '%COSIGN%'", T, C,
    ) == 0
    assert await conn.fetchval(
        "SELECT released_at IS NULL FROM change_ledger.holds WHERE hold_id=$1", hold["hold_id"],
    ) is True


async def test_anchor_gap_cosign_stale_external_head_and_invalid_holds_are_no_delta(ledger: L) -> None:
    conn = ledger.conn
    hold = await _open_current_gap(ledger, "invalid")
    login = await _login(ledger, "invalid")
    correct = _evidence(hold)
    before = await _ledger_snapshot(conn)
    stale = {**correct, "ext_seq": hold["ext_seq"] + 1}
    await _expect_code("COMPLETION_PROOF_MISSING", _call_as(ledger, conn, login, "clt_erin", hold["hold_id"], stale))
    assert await _ledger_snapshot(conn) == before
    stale_hash = {**correct, "ext_head_hash": "f" * 64}
    await _expect_code("COMPLETION_PROOF_MISSING", _call_as(ledger, conn, login, "clt_erin", hold["hold_id"], stale_hash))
    assert await _ledger_snapshot(conn) == before

    # Advance a genuine synthetic ledger head with a scoped policy event, then bind the open hold
    # to that newer external observation. Prior-head evidence must now fail without mutation.
    await ledger.call("clt_dave", "set_sweep_policy", json.dumps({"t12_window_seconds": 61}))
    newer_head = await ledger.call("clt_wrk", "ledger_head")
    newer_hash = "e" * 64 if newer_head["head_hash"] != "e" * 64 else "d" * 64
    updated = await ledger.call("clt_wrk", "check_anchor", newer_head["seq"], newer_hash)
    assert updated["ok"] is False
    refreshed = await conn.fetchrow(
        "SELECT ext_seq,ext_head_hash,released_at FROM change_ledger.holds WHERE hold_id=$1", hold["hold_id"],
    )
    assert refreshed is not None and refreshed["released_at"] is None
    assert (refreshed["ext_seq"], refreshed["ext_head_hash"]) == (newer_head["seq"], newer_hash)
    current_evidence = {**correct, "ext_seq": refreshed["ext_seq"], "ext_head_hash": refreshed["ext_head_hash"]}
    after_head_advance = await _ledger_snapshot(conn)
    await _expect_code(
        "COMPLETION_PROOF_MISSING",
        _call_as(ledger, conn, login, "clt_erin", hold["hold_id"], correct),
    )
    assert await _ledger_snapshot(conn) == after_head_advance

    assert await conn.execute(
        "UPDATE change_ledger.holds SET released_at=clock_timestamp(),release_evidence='{}'::jsonb "
        "WHERE hold_id=$1 AND released_at IS NULL", hold["hold_id"],
    ) == "UPDATE 1"
    released_snapshot = await _ledger_snapshot(conn)
    await _expect_code(
        "FORBIDDEN_TRANSITION",
        _call_as(ledger, conn, login, "clt_erin", hold["hold_id"], current_evidence),
    )
    assert await _ledger_snapshot(conn) == released_snapshot

    wrong = await _open_current_gap(ledger, "wrong-cause")
    assert await conn.execute(
        "UPDATE change_ledger.holds SET cause='RLC_UNCLEAN' WHERE hold_id=$1", wrong["hold_id"],
    ) == "UPDATE 1"
    wrong_snapshot = await _ledger_snapshot(conn)
    await _expect_code(
        "FORBIDDEN_TRANSITION",
        _call_as(ledger, conn, login, "clt_erin", wrong["hold_id"], _evidence(wrong)),
    )
    assert await _ledger_snapshot(conn) == wrong_snapshot

    await conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('clt_erin','T2','C2') "
        "ON CONFLICT DO NOTHING"
    )
    await conn.execute(
        "INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities) "
        "VALUES('T2','C2','clt_erin','person-s13-anchor-operator',ARRAY['operator','recovery_witness']) "
        "ON CONFLICT(tenant_id,company_id,principal) DO NOTHING"
    )
    await conn.execute(
        "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
        "VALUES('T2','C2','LEGACY',0,'SYNTHETIC_TEST') ON CONFLICT DO NOTHING"
    )
    foreign_snapshot = await _ledger_snapshot(conn)
    await _expect_code(
        "BASE_HOLD",
        _call_as(ledger, conn, login, "clt_erin", hold["hold_id"], correct, t="T2", c="C2"),
    )
    assert await _ledger_snapshot(conn) == foreign_snapshot


async def test_anchor_gap_cosign_revalidates_parent_snapshot_after_fences(ledger: L) -> None:
    conn = ledger.conn
    hold = await _open_current_gap(ledger, "stale-plan")
    login = await _login(ledger, "stale-plan")
    scope_holder, parent_holder, worker, observer = [await ledger.db.connect() for _ in range(4)]
    scope_tx, parent_tx = scope_holder.transaction(), parent_holder.transaction()
    task: asyncio.Task | None = None
    try:
        await scope_tx.start()
        await parent_tx.start()
        scope_pid = await scope_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        parent_pid = await parent_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        worker_pid = await worker.fetchval("SELECT pg_catalog.pg_backend_pid()")
        scope_key = f"s13-scope:v1:{len(T.encode())}:{T}:{len(C.encode())}:{C}"
        await scope_holder.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key,
        )
        await parent_holder.fetchrow(
            "SELECT hold_id FROM change_ledger.holds WHERE hold_id=$1 FOR UPDATE", hold["hold_id"],
        )
        cosigns_before = await conn.fetchval("SELECT count(*) FROM change_ledger.hold_cosigns WHERE hold_id=$1", hold["hold_id"])
        events_before = await conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C)
        task = asyncio.create_task(_call_as(ledger, worker, login, "clt_erin", hold["hold_id"], _evidence(hold)))
        await _wait_blocked(observer, worker_pid, scope_pid, task)
        await scope_tx.commit()
        await _wait_blocked(observer, worker_pid, parent_pid, task)
        locks = await observer.fetch(
            "SELECT classid::bigint AS namespace,granted FROM pg_catalog.pg_locks "
            "WHERE pid=$1 AND locktype='advisory'", worker_pid,
        )
        assert 7 in {row["namespace"] for row in locks if row["granted"]}
        assert 6 in {row["namespace"] for row in locks if row["granted"]}
        assert await conn.fetchval(
            "SELECT count(*) FROM change_ledger.hold_cosigns WHERE hold_id=$1", hold["hold_id"],
        ) == cosigns_before

        body = await conn.fetchval("SELECT p.prosrc FROM pg_catalog.pg_proc p WHERE p.oid=$1::regprocedure", V1)
        helper = await conn.fetchval(
            "SELECT p.prosrc FROM pg_catalog.pg_proc p WHERE p.oid="
            "'change_ledger.private_writer_take_global_fences_v1(text[])'::regprocedure"
        )
        assert "private_writer_take_scope_fence_v1" in body
        assert body.index("private_writer_take_scope_fence_v1") < body.index("private_writer_take_global_fences_v1")
        hold_key = "'hold-id:v1:'||pg_catalog.lower(p_hold_id::text)"
        cosign_key = "'hold-cosign-id:v1:'||pg_catalog.lower(cid::text)"
        global_plan = body.index("PERFORM change_ledger.private_writer_take_global_fences_v1(ARRAY[")
        global_plan_end = body.index("]);", global_plan)
        plan_slice = body[global_plan:global_plan_end]
        assert hold_key in plan_slice and cosign_key in plan_slice
        assert body.index("private_writer_take_global_fences_v1") < body.index("SELECT * INTO hint")
        locked_parent = body.index("SELECT * INTO h FROM")
        insert_child = body.index("INSERT INTO change_ledger.hold_cosigns")
        assert global_plan < locked_parent
        assert body.index(hold_key) < locked_parent and body.index(cosign_key) < locked_parent
        assert body.index("SELECT * INTO hint") < locked_parent < insert_child
        assert "FOR UPDATE" in body[locked_parent:insert_child]
        assert "ORDER BY 1" in helper and "pg_advisory_xact_lock(6,k)" in helper

        assert await parent_holder.execute(
            "UPDATE change_ledger.holds SET ext_seq=ext_seq+1,ext_head_hash=repeat('e',64) WHERE hold_id=$1",
            hold["hold_id"],
        ) == "UPDATE 1"
        await parent_tx.commit()
        with pytest.raises(asyncpg.PostgresError) as stale_error:
            await task
        assert stale_error.value.sqlstate == "P0001"
        assert str(stale_error.value).splitlines()[0] == "LOCK_PLAN_STALE"
        assert await conn.fetchval(
            "SELECT count(*) FROM change_ledger.hold_cosigns WHERE hold_id=$1", hold["hold_id"],
        ) == cosigns_before
        assert await conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C,
        ) == events_before
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for tx, blocker_conn in ((scope_tx, scope_holder), (parent_tx, parent_holder)):
            if blocker_conn.is_in_transaction():
                await tx.rollback()
        for item in (scope_holder, parent_holder, worker, observer):
            await item.close()
