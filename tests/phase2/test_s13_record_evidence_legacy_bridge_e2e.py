"""Disposable S13 qualification for the legacy record_evidence bridge.

All ledger rows, signatures, and keys in this module are synthetic and belong to the
invocation-owned PostgreSQL database. The application calls use only the old 12-argument
record_evidence wrapper; versioned entry points are probed only for denied ACL and explicit
global-ID fixture cases.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
import json
import time
import uuid

import asyncpg
import pytest
from _ed25519_fixtures import sign_hex
from _approval_envelope import ensure_envelope

pytest_plugins = ("test_s13_current_turn_sql",)

from business_ai_gateway.phase2.change_ledger._common import LedgerError, Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger
from test_change_ledger_sql import ACTORS, C, L, SIGN_KEYS, T, T2, C2
from test_s13_current_turn_sql import _ledger_snapshot, ledger

pytestmark = pytest.mark.integration

OLD = "change_ledger.record_evidence(text,text,uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid)"
REMOVED_10_ARG = "change_ledger.record_evidence(text,text,uuid,text,text,timestamptz,jsonb,text,text,text)"
V1 = "change_ledger.record_evidence_v1(text,text,uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid,uuid)"
ALL_RUNTIME_ROLES = [
    *ACTORS.keys(), "requester_role", "approver_role", "operator_role", "writer_role",
    "worker_role", "auditor_role", "checkpoint_role", "business_ai_private_writer",
    "private_writer_evidence_ingest",
]


async def _expected(code: str, awaitable) -> asyncpg.PostgresError | LedgerError:
    try:
        await awaitable
    except (LedgerError, asyncpg.PostgresError) as error:
        if isinstance(error, asyncpg.PostgresError):
            assert error.sqlstate == "P0001", (error.sqlstate, str(error))
            actual = str(error).splitlines()[0]
        else:
            actual = error.code
        assert actual == code, (actual, str(error))
        return error
    raise AssertionError(f"expected refusal {code}; call succeeded")


async def _evidence_args(
        ledger: L, change_id: uuid.UUID, kind: str, content: dict, *, role: str = "clt_wrk",
        key_id: str | None = None, generation: int = 1, call_id: uuid.UUID | None = None,
        observed_at: datetime | None = None,
) -> tuple:
    key_id = key_id or SIGN_KEYS[role][0]
    call_id = call_id or await ledger.call_id_of(change_id, generation)
    if kind in ("COMPLETION_PROOF", "OBSERVATION"):
        content = {"generation": generation, "call_id": str(call_id), **content}
    observed_at = observed_at or datetime.now(UTC)
    content_json = json.dumps(content, sort_keys=True, separators=(",", ":"))
    content_hash = await ledger.conn.fetchval(
        "SELECT change_ledger.canonical_content_hash($1::jsonb)", content_json,
    )
    binding = await ledger.conn.fetchval(
        "SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
        change_id, kind, content_hash, observed_at, generation, call_id,
    )
    return (change_id, kind, content_hash, observed_at, content_json, key_id, binding,
            sign_hex(key_id, binding), generation, call_id)


async def _record(ledger: L, role: str, args: tuple, *, t: str = T, c: str = C,
                  conn: asyncpg.Connection | None = None):
    return await ledger.call(role, "record_evidence", *args, t=t, c=c, conn=conn)


async def _record_with_identity(ledger: L, role: str, args: tuple) -> tuple[uuid.UUID, tuple]:
    conn = ledger.conn
    async with conn.transaction():
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        before = await conn.fetchrow("SELECT current_user,session_user")
        result = await conn.fetchval(
            "SELECT change_ledger.record_evidence($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
            T, C, *args,
        )
        after = await conn.fetchrow("SELECT current_user,session_user")
        assert after == before
    return result, tuple(before)


async def _wait_blocked(observer: asyncpg.Connection, pid: int, blocker_pid: int,
                        task: asyncio.Task, timeout: float = 8.0) -> asyncpg.Record:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await observer.fetchrow(
            "SELECT wait_event_type,pg_catalog.pg_blocking_pids(pid) AS blockers "
            "FROM pg_catalog.pg_stat_activity WHERE pid=$1", pid,
        )
        if last and last["wait_event_type"] == "Lock" and blocker_pid in last["blockers"]:
            return last
        if task.done():
            task.result()
            raise AssertionError(f"candidate completed before expected lock wait: {last}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for candidate lock; pid={pid}; last={last}")


async def _t2_applying(ledger: L, request_id: str) -> tuple[uuid.UUID, dict, uuid.UUID]:
    conn = ledger.conn
    await conn.execute(
        "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
        "VALUES($1,$2,'READY',1,'S13_TEST_FIXTURE') ON CONFLICT(tenant_id,company_id) "
        "DO UPDATE SET state='READY',epoch=greatest(change_ledger.lifecycle_fences.epoch,1)", T2, C2,
    )
    await conn.execute(
        "UPDATE change_ledger.targets SET epoch=greatest(epoch,1) "
        "WHERE tenant_id=$1 AND company_id=$2 AND base_fingerprint='base-t2'", T2, C2,
    )
    for role in ("clt_bob", "clt_wri", "clt_wrk"):
        await conn.execute(
            "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES($1,$2,$3) "
            "ON CONFLICT DO NOTHING", role, T2, C2,
        )
    await conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('clt_zed',$1,$2) "
        "ON CONFLICT DO NOTHING", T2, C2,
    )
    await conn.execute(
        "INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities) "
        "VALUES($1,$2,'clt_bob','person-clt-bob-s13-test',ARRAY['approver']) ON CONFLICT DO NOTHING", T2, C2,
    )
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,$3,'clt_wrk',$4) ON CONFLICT(tenant_id,company_id,key_id) DO NOTHING",
        T2, C2, SIGN_KEYS["clt_wrk"][0], SIGN_KEYS["clt_wrk"][1],
    )
    change_id = await ledger.propose(
        requester="clt_zed", request_id=request_id, base="base-t2", target=f"doc-{request_id}", t=T2, c=C2,
    )
    assert await ledger.call("clt_zed", "validate", change_id, t=T2, c=C2) == "VALIDATED"
    nonce = await ledger.call("clt_bob", "issue_approval_nonce", change_id, t=T2, c=C2)
    approval_digest = await ensure_envelope(ledger, change_id, requester="clt_zed")
    approval_id = await ledger.call("clt_bob", "approve", change_id, nonce, approval_digest, t=T2, c=C2)
    assert isinstance(approval_id, uuid.UUID)
    budget = await conn.fetchrow(
        "SELECT grant_id,amount,counts_create_update,counts_post "
        "FROM change_ledger.change_budget WHERE change_id=$1", change_id,
    )
    adapter = SqlChangeLedger(conn, actors={"requester": "clt_zed"}, private_writer_schema_enabled=True)
    token = await adapter.claim(
        Scope(T2, C2), change_id, grant_id=budget["grant_id"], amount=budget["amount"],
        counts_create_update=budget["counts_create_update"], counts_post=budget["counts_post"],
    )
    assert token is not None
    assert await ledger.call("clt_wri", "observe_target", token["token_id"], "base-t2", "CLONE", t=T2, c=C2)
    call_id = uuid.uuid4()
    await adapter.begin_apply(Scope(T2, C2), token["token_id"], call_id, "s13-test-host", "s13-test-session")
    assert await conn.execute(
        "UPDATE change_ledger.dispatch_permits SET state='PERMITTED', "
        "checkpoint_seq=(SELECT max(seq) FROM change_ledger.events),permit_digest=$3, "
        "issued_at=clock_timestamp(),expires_at=clock_timestamp()+interval '1 minute' "
        "WHERE change_id=$1 AND generation=$2 AND state='NOT_PERMITTED'",
        change_id, token["generation"], "b" * 64,
    ) == "UPDATE 1"
    await conn.execute("UPDATE change_ledger.records SET dispatch_state='PERMITTED' WHERE change_id=$1", change_id)
    return change_id, token, call_id


async def _fixture_v1_insert(ledger: L, args: tuple, evidence_id: uuid.UUID, *, t: str, c: str):
    """Fixture-only explicit-ID probe; ordinary app behavior always uses the old wrapper."""
    await ledger.conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('postgres',$1,$2) "
        "ON CONFLICT DO NOTHING", t, c,
    )
    async with ledger.conn.transaction():
        await ledger.conn.execute("SELECT pg_catalog.set_config('change_ledger.tenant_id',$1,true)", t)
        await ledger.conn.execute("SELECT pg_catalog.set_config('change_ledger.company_id',$1,true)", c)
        return await ledger.conn.fetchval(
            "SELECT change_ledger.record_evidence_v1($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
            t, c, *args, evidence_id,
        )


async def _applying(ledger: L, request_id: str = "s13-evidence") -> tuple[uuid.UUID, dict, uuid.UUID]:
    conn = ledger.conn
    await conn.execute(
        "UPDATE change_ledger.lifecycle_fences SET state='READY',epoch=greatest(epoch,1) "
        "WHERE tenant_id=$1 AND company_id=$2", T, C,
    )
    await conn.execute(
        "UPDATE change_ledger.targets SET epoch=greatest(epoch,1) "
        "WHERE tenant_id=$1 AND company_id=$2 AND base_fingerprint='base-1'", T, C,
    )
    change_id = await ledger.approved(request_id=request_id)
    budget = await conn.fetchrow(
        "SELECT grant_id,amount,counts_create_update,counts_post "
        "FROM change_ledger.change_budget WHERE change_id=$1", change_id,
    )
    adapter = SqlChangeLedger(conn, actors={"requester": "clt_alice"}, private_writer_schema_enabled=True)
    token = await adapter.claim(
        Scope(T, C), change_id, grant_id=budget["grant_id"], amount=budget["amount"],
        counts_create_update=budget["counts_create_update"], counts_post=budget["counts_post"],
    )
    assert token is not None
    assert await ledger.call("clt_wri", "observe_target", token["token_id"], "base-1", "CLONE") is True
    call_id = uuid.uuid4()
    await adapter.begin_apply(Scope(T, C), token["token_id"], call_id, "s13-test-host", "s13-test-session")
    permit_update = await conn.execute(
        "UPDATE change_ledger.dispatch_permits SET state='PERMITTED', "
        "checkpoint_seq=(SELECT max(seq) FROM change_ledger.events),permit_digest=$3, "
        "issued_at=clock_timestamp(),expires_at=clock_timestamp()+interval '1 minute' "
        "WHERE change_id=$1 AND generation=$2 AND state='NOT_PERMITTED'",
        change_id, token["generation"], "a" * 64,
    )
    assert permit_update == "UPDATE 1"
    await conn.execute(
        "UPDATE change_ledger.records SET dispatch_state='PERMITTED' WHERE change_id=$1", change_id,
    )
    assert token["generation"] == 1
    assert await ledger.conn.fetchval(
        "SELECT call_id FROM change_ledger.dispatch_permits WHERE change_id=$1 AND generation=1",
        change_id,
    ) == call_id
    return change_id, token, call_id


@pytest.mark.asyncio
async def test_s13_record_evidence_bridge_catalog_acl_identity_and_direct_v1_denial(ledger: L) -> None:
    conn = ledger.conn
    owner = await conn.fetchval(
        "SELECT pg_catalog.pg_get_userbyid(p.proowner) FROM pg_catalog.pg_proc p WHERE p.oid=$1::regprocedure", OLD,
    )
    security_definer = await conn.fetchval(
        "SELECT p.prosecdef FROM pg_catalog.pg_proc p WHERE p.oid=$1::regprocedure", OLD,
    )
    result = await conn.fetchval("SELECT pg_catalog.pg_get_function_result($1::regprocedure)", OLD)
    source = await conn.fetchval("SELECT p.prosrc FROM pg_catalog.pg_proc p WHERE p.oid=$1::regprocedure", OLD)
    assert (owner, security_definer, result) == ("ledger_owner", True, "uuid")
    assert "record_evidence_v1" in source
    assert await conn.fetchval("SELECT pg_catalog.to_regprocedure($1) IS NULL", REMOVED_10_ARG)
    assert not await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p, "
        "LATERAL pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) acl "
        "WHERE p.oid=$1::regprocedure AND acl.grantee=0 AND acl.privilege_type='EXECUTE')", OLD,
    )

    for role in ALL_RUNTIME_ROLES:
        expected_execute = role in {"worker_role", "writer_role"} or (
            role in ACTORS and bool({"worker_role", "writer_role"} & set(ACTORS[role][0]))
        )
        assert bool(await conn.fetchval(
            "SELECT pg_catalog.has_function_privilege($1,$2,'EXECUTE')", role, OLD,
        )) is expected_execute, (role, expected_execute)
        assert not await conn.fetchval(
            "SELECT pg_catalog.has_function_privilege($1,$2,'EXECUTE')", role, V1,
        ), role

    change_id, _token, _call_id = await _applying(ledger, "s13-evidence-direct-denial")
    for role in ALL_RUNTIME_ROLES:
        tenant, company = (T2, C2) if role == "clt_zed" else (T, C)
        with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
            async with conn.transaction():
                await conn.execute(f'SET LOCAL ROLE "{role}"')
                await conn.execute("SELECT pg_catalog.set_config('change_ledger.tenant_id',$1,true)", tenant)
                await conn.execute("SELECT pg_catalog.set_config('change_ledger.company_id',$1,true)", company)
                await conn.fetchval(
                    "SELECT change_ledger.record_evidence_v1($1,$2,$3,'FIELD',$4,$5,$6,$7,$8,$9,1,$10,$11)",
                    tenant, company, change_id, "0" * 64, datetime.now(UTC), '{"matches":true}',
                    "vk-wrk", "0" * 64, "0" * 128, uuid.uuid4(), uuid.uuid4(),
                )
        assert denied.value.sqlstate == "42501", (role, denied.value.sqlstate, str(denied.value))
        assert "permission denied" in str(denied.value).lower(), (role, str(denied.value))


@pytest.mark.asyncio
async def test_s13_record_evidence_all_kinds_and_worker_writer_boundaries(ledger: L) -> None:
    change_id, token, call_id = await _applying(ledger, "s13-evidence-kinds")
    approval_id = await ledger.conn.fetchval(
        "SELECT approval_id FROM change_ledger.approvals WHERE change_id=$1 LIMIT 1",
        change_id,
    )
    assert approval_id is not None
    cases = (
        ("FIELD", {"matches": True}, "clt_wrk"),
        ("MOVEMENT", {"matches": True}, "clt_wrk"),
        ("VERSION", {"matches": True}, "clt_wrk"),
        ("AUTH_RECEIPT", {"approval_id": str(approval_id)}, "clt_wrk"),
        ("COMPLETION_PROOF", {"class": "b", "result_returned": False}, "clt_wrk"),
        ("COMPLETION_PROOF", {"class": "a", "result_returned": True}, "clt_wri"),
        ("OBSERVATION", {"effect_present": True}, "clt_wrk"),
    )
    seen = []
    for i, (kind, content, role) in enumerate(cases):
        args = await _evidence_args(ledger, change_id, kind, {**content, "case": i}, role=role,
                                   generation=token["generation"], call_id=call_id)
        if i == 0:
            evidence_id, identity = await _record_with_identity(ledger, role, args)
            assert identity == ("clt_wrk", "postgres")
        elif i == 5:
            evidence_id, identity = await _record_with_identity(ledger, role, args)
            assert identity == ("clt_wri", "postgres")
        else:
            evidence_id = await _record(ledger, role, args)
        seen.append(evidence_id)
    assert len(set(seen)) == len(cases)
    rows = await ledger.conn.fetch(
        "SELECT evidence_id,kind,recorded_by,generation,call_id FROM change_ledger.evidence_records "
        "WHERE change_id=$1 ORDER BY kind,recorded_by,evidence_id", change_id,
    )
    assert len(rows) == len(cases)
    assert all(row["generation"] == token["generation"] and row["call_id"] == call_id for row in rows)
    assert {(row["kind"], row["recorded_by"]) for row in rows} == {
        ("FIELD", "clt_wrk"), ("MOVEMENT", "clt_wrk"), ("VERSION", "clt_wrk"),
        ("AUTH_RECEIPT", "clt_wrk"), ("OBSERVATION", "clt_wrk"),
        ("COMPLETION_PROOF", "clt_wrk"), ("COMPLETION_PROOF", "clt_wri"),
    }
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='EVIDENCE_RECORDED'",
        change_id,
    ) == len(cases)

    before = await _ledger_snapshot(ledger.conn)
    worker_class_a = await _evidence_args(
        ledger, change_id, "COMPLETION_PROOF", {"class": "a", "result_returned": True, "case": "deny"},
        role="clt_wrk", generation=token["generation"], call_id=call_id,
    )
    await _expected("NOT_ENTITLED", _record(ledger, "clt_wrk", worker_class_a))
    writer_field = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "case": "deny"}, role="clt_wri",
        generation=token["generation"], call_id=call_id,
    )
    await _expected("NOT_ENTITLED", _record(ledger, "clt_wri", writer_field))
    assert await _ledger_snapshot(ledger.conn) == before


@pytest.mark.asyncio
async def test_s13_record_evidence_exact_natural_replay_and_changed_tuple_no_delta(ledger: L) -> None:
    change_id, token, call_id = await _applying(ledger, "s13-evidence-replay")
    args = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "source": "synthetic"},
        generation=token["generation"], call_id=call_id,
    )
    first = await _record(ledger, "clt_wrk", args)
    after_first = await _ledger_snapshot(ledger.conn)
    replay = await _record(ledger, "clt_wrk", args)
    assert replay == first
    assert await _ledger_snapshot(ledger.conn) == after_first
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.evidence_records WHERE change_id=$1 AND evidence_id=$2",
        change_id, first,
    ) == 1
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='EVIDENCE_RECORDED'",
        change_id,
    ) == 1

    changed = list(args)
    changed[3] = args[3] + timedelta(seconds=1)
    changed[6] = await ledger.conn.fetchval(
        "SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
        change_id, args[1], args[2], changed[3], token["generation"], call_id,
    )
    changed[7] = sign_hex(args[5], changed[6])
    before_refusal = await _ledger_snapshot(ledger.conn)
    await _expected("EVIDENCE_IDENTITY_CONFLICT", _record(ledger, "clt_wrk", tuple(changed)))
    assert await _ledger_snapshot(ledger.conn) == before_refusal


@pytest.mark.asyncio
async def test_s13_record_evidence_stale_generation_and_wrong_call_refuse_no_delta(ledger: L) -> None:
    change_id, token, call_id = await _applying(ledger, "s13-evidence-stale")
    wrong_call = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "case": "wrong-call"},
        generation=token["generation"], call_id=uuid.uuid4(),
    )
    before_wrong_call = await _ledger_snapshot(ledger.conn)
    await _expected("PERMIT_MISSING", _record(ledger, "clt_wrk", wrong_call))
    assert await _ledger_snapshot(ledger.conn) == before_wrong_call

    # Supersede the old generation in the disposable fixture while preserving its permit row.
    assert await ledger.conn.execute(
        "UPDATE change_ledger.records SET claim_generation=claim_generation+1 WHERE change_id=$1", change_id,
    ) == "UPDATE 1"
    old_generation = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "case": "old-generation"},
        generation=token["generation"], call_id=call_id,
    )
    before_old_generation = await _ledger_snapshot(ledger.conn)
    await _expected("TICKET_SUPERSEDED", _record(ledger, "clt_wrk", old_generation))
    assert await _ledger_snapshot(ledger.conn) == before_old_generation


@pytest.mark.asyncio
async def test_s13_record_evidence_global_id_collision_is_refused_with_no_delta(ledger: L) -> None:
    conn = ledger.conn
    change_id, token, call_id = await _applying(ledger, "s13-evidence-id-owner")
    owner_args = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "owner": "scope-one"},
        generation=token["generation"], call_id=call_id,
    )
    evidence_id = await _record(ledger, "clt_wrk", owner_args)

    # The legacy wrapper does not accept evidence_id. Probe the v1 collision boundary only as
    # the disposable database owner; ordinary actor execution is separately denied above.
    same_scope_args = await _evidence_args(
        ledger, change_id, "MOVEMENT", {"matches": True, "collision": "same-scope"},
        generation=token["generation"], call_id=call_id,
    )
    await conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('postgres',$1,$2) "
        "ON CONFLICT DO NOTHING", T, C,
    )
    before_same_scope = await _ledger_snapshot(conn)
    await _expected("EVIDENCE_IDENTITY_CONFLICT", _fixture_v1_insert(
        ledger, same_scope_args, evidence_id, t=T, c=C,
    ))
    assert await _ledger_snapshot(conn) == before_same_scope

    t2_change, t2_token, t2_call = await _t2_applying(ledger, "s13-evidence-foreign-id")
    foreign_args = await _evidence_args(
        ledger, t2_change, "FIELD", {"matches": True, "collision": "cross-scope"},
        generation=t2_token["generation"], call_id=t2_call,
    )
    await conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('postgres',$1,$2) "
        "ON CONFLICT DO NOTHING", T2, C2,
    )
    before_cross_scope = await _ledger_snapshot(conn)
    await _expected("EVIDENCE_IDENTITY_CONFLICT", _fixture_v1_insert(
        ledger, foreign_args, evidence_id, t=T2, c=C2,
    ))
    assert await _ledger_snapshot(conn) == before_cross_scope
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.evidence_records WHERE evidence_id=$1", evidence_id,
    ) == 1


@pytest.mark.asyncio
async def test_s13_record_evidence_key_rotation_race_waits_at_material_fence(ledger: L) -> None:
    conn = ledger.conn
    change_id, token, call_id = await _applying(ledger, "s13-evidence-key-race")
    await _t2_applying(ledger, "s13-evidence-key-revoke-t2")
    await conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('clt_dave',$1,$2) "
        "ON CONFLICT DO NOTHING", T2, C2,
    )
    await conn.execute(
        "INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities) "
        "VALUES($1,$2,'clt_dave','person-clt-dave-s13-test',ARRAY['operator','requester','recovery_witness']) "
        "ON CONFLICT DO NOTHING", T2, C2,
    )
    args = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "race": "key-revocation"},
        generation=token["generation"], call_id=call_id,
    )
    key_material = SIGN_KEYS["clt_wrk"][1]
    holder, worker, operator, observer = [await ledger.db.connect() for _ in range(4)]
    transaction = holder.transaction()
    record_task: asyncio.Task | None = None
    revoke_task: asyncio.Task | None = None
    try:
        await transaction.start()
        blocker_pid = await holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        await holder.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1,17017))", key_material,
        )
        before = await _ledger_snapshot(conn)
        worker_pid = await worker.fetchval("SELECT pg_catalog.pg_backend_pid()")

        record_task = asyncio.create_task(_record(ledger, "clt_wrk", args, conn=worker))
        await _wait_blocked(observer, worker_pid, blocker_pid, record_task)
        locks = await observer.fetch(
            "SELECT locktype,mode,granted,objsubid,classid::text::bigint AS classid "
            "FROM pg_catalog.pg_locks WHERE pid=$1", worker_pid,
        )
        assert any(row["locktype"] == "advisory" and not row["granted"] and row["objsubid"] == 1
                   for row in locks), locks
        assert any(row["locktype"] == "advisory" and row["granted"] and row["classid"] == 7
                   for row in locks), locks
        assert not any(row["locktype"] == "advisory" and row["granted"] and row["classid"] == 6
                       for row in locks), locks
        relation_locks = await observer.fetch(
            "SELECT relation::regclass::text AS relation,mode FROM pg_catalog.pg_locks "
            "WHERE pid=$1 AND relation IN ('change_ledger.records'::regclass, "
            "'change_ledger.evidence_records'::regclass, 'change_ledger.events'::regclass)", worker_pid,
        )
        assert relation_locks == [], relation_locks
        assert await _ledger_snapshot(conn) == before, "blocked evidence call changed ledger state"

        operator_pid = await operator.fetchval("SELECT pg_catalog.pg_backend_pid()")
        revoke_task = asyncio.create_task(
            ledger.call("clt_dave", "revoke_verifier_key", "vk-wrk", t=T2, c=C2, conn=operator),
        )
        await _wait_blocked(observer, operator_pid, blocker_pid, revoke_task)
        await transaction.commit()

        result = await asyncio.gather(record_task, revoke_task, return_exceptions=True)
        record_result, revoke_result = result
        assert revoke_result is None, revoke_result
        assert await conn.fetchval(
            "SELECT status FROM change_ledger.verifier_keys WHERE tenant_id=$1 AND company_id=$2 AND key_id='vk-wrk'",
            T, C,
        ) == "ACTIVE"
        assert await conn.fetchval(
            "SELECT status FROM change_ledger.verifier_keys WHERE tenant_id=$1 AND company_id=$2 AND key_id='vk-wrk'",
            T2, C2,
        ) == "REVOKED"
        revoked_events = await conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND event_type='VERIFIER_KEY_REVOKED' AND payload->>'key_id'='vk-wrk'", T2, C2,
        )
        assert revoked_events == 1
        evidence_count = await conn.fetchval(
            "SELECT count(*) FROM change_ledger.evidence_records WHERE change_id=$1 AND kind='FIELD' "
            "AND content_hash=$2", change_id, args[2],
        )
        evidence_events = await conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='EVIDENCE_RECORDED' "
            "AND payload->>'content_hash'=$2", change_id, args[2],
        )
        if isinstance(record_result, BaseException):
            pytest.fail(f"T1 evidence should use the unchanged T1 key after T2 revocation: {record_result}")
        else:
            assert isinstance(record_result, uuid.UUID), record_result
            assert (evidence_count, evidence_events) == (1, 1)
        assert revoked_events == 1
    finally:
        if record_task and not record_task.done():
            record_task.cancel()
            with suppress(asyncio.CancelledError):
                await record_task
        if revoke_task and not revoke_task.done():
            revoke_task.cancel()
            with suppress(asyncio.CancelledError):
                await revoke_task
        if holder.is_in_transaction():
            await transaction.rollback()
        for item in (holder, worker, operator, observer):
            await item.close()


@pytest.mark.parametrize("winner", ["record", "revoke"])
@pytest.mark.asyncio
async def test_s13_record_evidence_same_scope_record_vs_key_revocation_race(ledger: L, winner: str) -> None:
    """Both orderings serialize on the same scope and leave either one row or no evidence at all."""
    conn = ledger.conn
    change_id, token, call_id = await _applying(ledger, f"s13-evidence-same-scope-{winner}")
    args = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "race": f"same-scope-{winner}"},
        generation=token["generation"], call_id=call_id,
    )
    holder, worker, operator, observer = [await ledger.db.connect() for _ in range(4)]
    holder_tx = holder.transaction()
    record_task: asyncio.Task | None = None
    revoke_task: asyncio.Task | None = None
    try:
        await holder_tx.start()
        holder_pid = await holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        worker_pid = await worker.fetchval("SELECT pg_catalog.pg_backend_pid()")
        operator_pid = await operator.fetchval("SELECT pg_catalog.pg_backend_pid()")
        await holder.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1,17017))",
            SIGN_KEYS["clt_wrk"][1],
        )
        before = await _ledger_snapshot(conn)

        if winner == "record":
            record_task = asyncio.create_task(_record(ledger, "clt_wrk", args, conn=worker))
            await _wait_blocked(observer, worker_pid, holder_pid, record_task)
            revoke_task = asyncio.create_task(
                ledger.call("clt_dave", "revoke_verifier_key", "vk-wrk", conn=operator),
            )
            await _wait_blocked(observer, operator_pid, worker_pid, revoke_task)
        else:
            revoke_task = asyncio.create_task(
                ledger.call("clt_dave", "revoke_verifier_key", "vk-wrk", conn=operator),
            )
            await _wait_blocked(observer, operator_pid, holder_pid, revoke_task)
            record_task = asyncio.create_task(_record(ledger, "clt_wrk", args, conn=worker))
            await _wait_blocked(observer, worker_pid, operator_pid, record_task)

        await holder_tx.commit()
        record_result, revoke_result = await asyncio.gather(record_task, revoke_task, return_exceptions=True)
        assert revoke_result is None, revoke_result
        assert await conn.fetchval(
            "SELECT status FROM change_ledger.verifier_keys WHERE tenant_id=$1 AND company_id=$2 AND key_id='vk-wrk'",
            T, C,
        ) == "REVOKED"
        assert await conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND event_type='VERIFIER_KEY_REVOKED' AND payload->>'key_id'='vk-wrk'", T, C,
        ) == 1
        evidence_rows = await conn.fetch(
            "SELECT evidence_id,kind,content_hash FROM change_ledger.evidence_records "
            "WHERE change_id=$1 AND kind='FIELD' AND content_hash=$2", change_id, args[2],
        )
        evidence_events = await conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3 AND event_type='EVIDENCE_RECORDED' AND payload->>'content_hash'=$4",
            T, C, change_id, args[2],
        )

        if winner == "record":
            assert isinstance(record_result, uuid.UUID), record_result
            assert len(evidence_rows) == 1 and evidence_rows[0]["evidence_id"] == record_result
            assert evidence_events == 1
            after_ordered_writes = await _ledger_snapshot(conn)
            await _expected("EVIDENCE_UNSIGNED", _record(ledger, "clt_wrk", args))
            assert await _ledger_snapshot(conn) == after_ordered_writes
        else:
            assert isinstance(record_result, asyncpg.PostgresError), record_result
            assert record_result.sqlstate == "P0001", (record_result.sqlstate, str(record_result))
            assert str(record_result).splitlines()[0] == "EVIDENCE_UNSIGNED", record_result
            assert evidence_rows == [] and evidence_events == 0
            after_revoke = await _ledger_snapshot(conn)
            await _expected("EVIDENCE_UNSIGNED", _record(ledger, "clt_wrk", args))
            assert await _ledger_snapshot(conn) == after_revoke
        assert await _ledger_snapshot(conn) != before
    finally:
        for task in (record_task, revoke_task):
            if task and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if holder.is_in_transaction():
            await holder_tx.rollback()
        for item in (holder, worker, operator, observer):
            await item.close()


@pytest.mark.asyncio
async def test_s13_record_evidence_lock_order_key_global_parent_child_event(ledger: L) -> None:
    """Stage real PostgreSQL locks and observe key -> namespace-6 -> parent -> child -> event order."""
    conn = ledger.conn
    change_id, token, call_id = await _applying(ledger, "s13-evidence-lock-order")
    args = await _evidence_args(
        ledger, change_id, "FIELD", {"matches": True, "lock_order": "synthetic"},
        generation=token["generation"], call_id=call_id,
    )
    before = await _ledger_snapshot(conn)
    key_holder, id_holder, parent_holder, child_holder, event_holder, worker, probe, observer = [
        await ledger.db.connect() for _ in range(8)
    ]
    probe_pid = await probe.fetchval("SELECT pg_catalog.pg_backend_pid()")
    blocker_conns = (key_holder, id_holder, parent_holder, child_holder, event_holder)
    txs = [item.transaction() for item in blocker_conns]
    record_task: asyncio.Task | None = None
    parent_probe: asyncio.Task | None = None
    try:
        await txs[0].start()
        key_pid = await key_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        worker_pid = await worker.fetchval("SELECT pg_catalog.pg_backend_pid()")
        await key_holder.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1,17017))",
            SIGN_KEYS["clt_wrk"][1],
        )
        record_task = asyncio.create_task(_record(ledger, "clt_wrk", args, conn=worker))
        await _wait_blocked(observer, worker_pid, key_pid, record_task)
        key_wait = await observer.fetch(
            "SELECT locktype,granted,objsubid,classid::text::bigint AS namespace "
            "FROM pg_catalog.pg_locks WHERE pid=$1", worker_pid,
        )
        assert any(row["locktype"] == "advisory" and not row["granted"] and row["objsubid"] == 1
                   for row in key_wait), key_wait
        assert any(row["locktype"] == "advisory" and row["granted"] and row["namespace"] == 7
                   for row in key_wait), key_wait
        assert not any(row["locktype"] == "advisory" and row["namespace"] == 6 for row in key_wait), key_wait
        assert not await observer.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks WHERE pid=$1 "
            "AND relation IN ('change_ledger.records'::regclass, 'change_ledger.evidence_records'::regclass, "
            "'change_ledger.events'::regclass))", worker_pid,
        ), "namespace-6 or relation access preceded verifier-material fence"

        await txs[1].start()
        id_pid = await id_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        record_key = f"record-change-id:v1:{str(change_id).lower()}"
        await id_holder.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(6,pg_catalog.hashtext($1))", record_key,
        )
        await txs[0].commit()
        await _wait_blocked(observer, worker_pid, id_pid, record_task)
        global_wait = await observer.fetch(
            "SELECT classid::text::bigint AS namespace,granted,objsubid FROM pg_catalog.pg_locks "
            "WHERE pid=$1 AND locktype='advisory'", worker_pid,
        )
        assert any(row["namespace"] == 6 and not row["granted"] and row["objsubid"] == 2
                   for row in global_wait), global_wait
        assert not await observer.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks WHERE pid=$1 "
            "AND relation IN ('change_ledger.records'::regclass, 'change_ledger.evidence_records'::regclass, "
            "'change_ledger.events'::regclass))", worker_pid,
        ), "record parent was touched before namespace-6 global identity fences"

        await txs[2].start()
        parent_pid = await parent_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        await parent_holder.fetchrow(
            "SELECT change_id FROM change_ledger.records WHERE change_id=$1 FOR UPDATE", change_id,
        )
        await txs[1].commit()
        await _wait_blocked(observer, worker_pid, parent_pid, record_task)
        parent_probe = asyncio.create_task(probe.fetchrow(
            "SELECT change_id FROM change_ledger.records WHERE change_id=$1 FOR UPDATE", change_id,
        ))
        await _wait_blocked(observer, probe_pid, worker_pid, parent_probe)

        await txs[3].start()
        child_pid = await child_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        await child_holder.execute("LOCK TABLE change_ledger.evidence_records IN ACCESS EXCLUSIVE MODE")
        await txs[2].commit()
        await _wait_blocked(observer, worker_pid, child_pid, record_task)
        child_relation = await observer.fetchrow(
            "SELECT mode,granted FROM pg_catalog.pg_locks WHERE pid=$1 "
            "AND relation='change_ledger.evidence_records'::regclass AND mode='AccessShareLock'",
            worker_pid,
        )
        assert child_relation is not None and child_relation["granted"] is False, child_relation
        await txs[4].start()
        event_pid = await event_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        await event_holder.execute("LOCK TABLE change_ledger.events IN ACCESS EXCLUSIVE MODE")
        await txs[3].commit()
        await _wait_blocked(observer, worker_pid, event_pid, record_task)
        event_relation = await observer.fetchrow(
            "SELECT mode,granted FROM pg_catalog.pg_locks WHERE pid=$1 "
            "AND relation='change_ledger.events'::regclass AND NOT granted",
            worker_pid,
        )
        child_write = await observer.fetchrow(
            "SELECT mode,granted FROM pg_catalog.pg_locks WHERE pid=$1 "
            "AND relation='change_ledger.evidence_records'::regclass AND mode='RowExclusiveLock'",
            worker_pid,
        )
        assert event_relation is not None and event_relation["granted"] is False, event_relation
        assert child_write is not None and child_write["granted"] is True, child_write

        await txs[4].commit()
        result = await record_task
        assert isinstance(result, uuid.UUID)
        assert (await parent_probe)["change_id"] == change_id
        rows = await conn.fetch(
            "SELECT evidence_id,kind,content_hash FROM change_ledger.evidence_records WHERE change_id=$1 "
            "AND content_hash=$2", change_id, args[2],
        )
        assert len(rows) == 1 and rows[0]["evidence_id"] == result
        assert await conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='EVIDENCE_RECORDED' "
            "AND payload->>'content_hash'=$2", change_id, args[2],
        ) == 1
        after = await _ledger_snapshot(conn)
        before_by_table = dict(before)
        after_by_table = dict(after)
        excluded = {"evidence_records", "events"}
        assert {name: rows for name, rows in before_by_table.items() if name not in excluded} == {
            name: rows for name, rows in after_by_table.items() if name not in excluded
        }
        assert len(after_by_table["evidence_records"]) == len(before_by_table["evidence_records"]) + 1
        assert len(after_by_table["events"]) == len(before_by_table["events"]) + 1
    finally:
        if record_task and not record_task.done():
            record_task.cancel()
            with suppress(asyncio.CancelledError):
                await record_task
        if parent_probe and not parent_probe.done():
            parent_probe.cancel()
            with suppress(asyncio.CancelledError):
                await parent_probe
        for tx, item in zip(txs, blocker_conns, strict=True):
            if item.is_in_transaction():
                await tx.rollback()
        for item in (key_holder, id_holder, parent_holder, child_holder, event_holder, worker, probe, observer):
            await item.close()
