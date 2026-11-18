"""Disposable PostgreSQL qualification of the signed T16 witness-cosign bridge."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

pytest_plugins = ("test_s13_current_turn_sql",)

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger
from test_change_ledger_sql import ACTORS, C, L, T
from test_s13_current_turn_sql import _ledger_snapshot, ledger

pytestmark = pytest.mark.integration

OLD = "change_ledger.witness_cosign_signed(text,text,uuid,uuid)"
V1 = "change_ledger.witness_cosign_signed_v1(text,text,uuid,uuid)"
V1_NAME = "change_ledger.witness_cosign_signed_v1"
DIRECT_ROLES = [
    *ACTORS.keys(), "requester_role", "approver_role", "operator_role", "writer_role",
    "worker_role", "auditor_role", "checkpoint_role", "business_ai_private_writer",
    "private_writer_evidence_ingest",
]


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


async def _expect_code(code: str, awaitable, *, sqlstate: str = "P0001") -> asyncpg.PostgresError:
    try:
        await awaitable
    except asyncpg.PostgresError as error:
        assert error.sqlstate == sqlstate, (error.sqlstate, str(error))
        assert str(error).splitlines()[0] == code, str(error)
        return error
    raise AssertionError(f"expected {code} ({sqlstate}); call succeeded")


async def _login(ledger: L, label: str, actor: str = "clt_erin") -> str:
    login = f"s13_cosign_{label}_{uuid.uuid4().hex[:10]}"
    await ledger.conn.execute(f'CREATE ROLE "{login}" NOLOGIN')
    await ledger.conn.execute(f'GRANT "{actor}" TO "{login}"')
    return login


async def _call_as(ledger: L, conn: asyncpg.Connection, session: str, role: str,
                   fn: str, *args, t: str = T, c: str = C):
    marks = ",".join(f"${i + 3}" for i in range(len(args)))
    async with conn.transaction():
        await conn.execute(f'SET LOCAL SESSION AUTHORIZATION "{session}"')
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        assert await conn.fetchval("SELECT session_user::text") == session
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
        result = await conn.fetchval(
            f"SELECT change_ledger.{fn}($1,$2{',' if args else ''}{marks})", t, c, *args,
        )
        assert await conn.fetchval("SELECT session_user::text") == session
        return result


async def _applying(ledger: L, label: str) -> tuple[uuid.UUID, dict, uuid.UUID]:
    conn = ledger.conn
    scope = Scope(T, C)
    base = hashlib.sha256(f"s13-witness-{label}".encode()).hexdigest()
    await conn.execute(
        "UPDATE change_ledger.lifecycle_fences SET state='READY',epoch=greatest(epoch,1) "
        "WHERE tenant_id=$1 AND company_id=$2", T, C,
    )
    await conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class,epoch) "
        "VALUES($1,$2,$3,'org-1','DISPOSABLE_CLONE',1) ON CONFLICT(tenant_id,company_id,base_fingerprint) "
        "DO UPDATE SET epoch=greatest(change_ledger.targets.epoch,1)", T, C, base,
    )
    change_id = await ledger.approved(request_id=f"s13-witness-{label}", kind="POST", base=base)
    budget = await conn.fetchrow(
        "SELECT grant_id,amount,counts_create_update,counts_post FROM change_ledger.change_budget "
        "WHERE change_id=$1", change_id,
    )
    requester = SqlChangeLedger(conn, actors={"requester": "clt_alice"}, private_writer_schema_enabled=True)
    token = await requester.claim(
        scope, change_id, grant_id=budget["grant_id"], amount=budget["amount"],
        counts_create_update=budget["counts_create_update"], counts_post=budget["counts_post"],
    )
    assert token is not None
    assert await ledger.call("clt_wri", "observe_target", token["token_id"], base, "CLONE") is True
    call_id = uuid.uuid4()
    await requester.begin_apply(scope, token["token_id"], call_id, "s13-test-host", "s13-test-session")
    permitted = await conn.execute(
        "UPDATE change_ledger.dispatch_permits SET state='PERMITTED', "
        "checkpoint_seq=(SELECT max(seq) FROM change_ledger.events),permit_digest=$3,"
        "issued_at=clock_timestamp(),expires_at=clock_timestamp()+interval '1 minute' "
        "WHERE change_id=$1 AND generation=$2 AND state='NOT_PERMITTED'",
        change_id, token["generation"], "a" * 64,
    )
    assert permitted == "UPDATE 1"
    await conn.execute(
        "UPDATE change_ledger.records SET dispatch_state='PERMITTED' WHERE change_id=$1", change_id,
    )
    await ledger.call("clt_wri", "require_dispatch_receipt", change_id, token["generation"])
    assert await ledger.call(
        "clt_wri", "verify_dispatch_payload", change_id, token["generation"], None,
    ) is True
    async with conn.transaction():
        permit_update = await conn.execute(
            "UPDATE change_ledger.dispatch_permits SET state='DISPATCHED' "
            "WHERE change_id=$1 AND generation=$2 AND state='PERMITTED'", change_id, token["generation"],
        )
        record_update = await conn.execute(
            "UPDATE change_ledger.records SET dispatch_state='DISPATCHED' "
            "WHERE change_id=$1 AND dispatch_state='PERMITTED'", change_id,
        )
    assert permit_update == "UPDATE 1"
    assert record_update == "UPDATE 1"
    return change_id, token, call_id


async def _triage(ledger: L, label: str) -> tuple[uuid.UUID, dict, uuid.UUID, uuid.UUID]:
    change_id, token, call_id = await _applying(ledger, label)
    completion_id = await ledger.evidence(
        change_id, "COMPLETION_PROOF",
        {"class": "a", "result_returned": False, "attribution_proof": True},
        role="clt_wri", gen=token["generation"], call_id=call_id,
    )
    # Fixture initialization only: migration 027 revokes the runtime completion and unknown-
    # resolution routes, so seed the minimal T16 record projection and open hold in this
    # invocation-owned disposable database. This does not claim to exercise those transitions;
    # the cosign wrapper below exercises its production CAS/evidence/hold checks. No trigger is
    # disabled and no ACL is changed.
    rec = await ledger.conn.fetchrow(
        "SELECT tenant_id,company_id,base_fingerprint FROM change_ledger.records WHERE change_id=$1", change_id,
    )
    assert rec is not None
    await ledger.conn.execute(
        "UPDATE change_ledger.records SET execution_state='TRIAGE_REQUIRED',"
        "call_ownership='POSSIBLY_EXECUTING',effect_known='UNKNOWN',"
        "attribution='UNPROVEN_OPERATOR_ATTESTED' WHERE change_id=$1", change_id,
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id) "
        "VALUES($1,$2,$3,'CALL_OWNERSHIP',$4)",
        rec["tenant_id"], rec["company_id"], rec["base_fingerprint"], change_id,
    )
    return change_id, token, call_id, completion_id


async def _unknown(ledger: L, label: str) -> tuple[uuid.UUID, dict, uuid.UUID, uuid.UUID]:
    change_id, token, call_id = await _applying(ledger, label)
    completion_id = await ledger.evidence(
        change_id, "COMPLETION_PROOF", {"class": "a", "result_returned": False},
        role="clt_wri", gen=token["generation"], call_id=call_id,
    )
    # Fixture initialization only for the conditional-conflict path. Runtime completion and
    # recovery entry points are revoked by migration 027; the production cosign wrapper still
    # checks the resulting current generation/call/dispatch CAS, linked receipt, and open hold.
    # This seed is not a test of the APPLY_UNKNOWN transition. No trigger is disabled and no ACL
    # is changed.
    rec = await ledger.conn.fetchrow(
        "SELECT tenant_id,company_id,base_fingerprint FROM change_ledger.records WHERE change_id=$1", change_id,
    )
    assert rec is not None
    await ledger.conn.execute(
        "UPDATE change_ledger.records SET execution_state='APPLY_UNKNOWN',"
        "call_ownership='POSSIBLY_EXECUTING',effect_known='UNKNOWN',"
        "attribution='UNPROVEN_OPERATOR_ATTESTED' WHERE change_id=$1", change_id,
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id) "
        "VALUES($1,$2,$3,'CALL_OWNERSHIP',$4)",
        rec["tenant_id"], rec["company_id"], rec["base_fingerprint"], change_id,
    )
    return change_id, token, call_id, completion_id


async def _attach_private_conditional_receipt(
        ledger: L, change_id: uuid.UUID, token: dict, call_id: uuid.UUID,
        completion_id: uuid.UUID) -> dict[str, object]:
    """Seed only the typed synthetic receipt/completion projections used by the DB boundary."""
    conn = ledger.conn
    rec = await conn.fetchrow(
        "SELECT r.tenant_id,r.company_id,r.organization_ref,r.base_fingerprint,r.change_id,"
        "r.claim_generation,r.payload_digest,r.auth_epoch_at_proposal,r.target_ref,r.target_version,"
        "p.call_id,p.generation FROM change_ledger.records r JOIN change_ledger.dispatch_permits p "
        "ON p.change_id=r.change_id AND p.generation=r.claim_generation WHERE r.change_id=$1", change_id,
    )
    assert rec is not None
    assert rec["generation"] == token["generation"] and rec["call_id"] == call_id
    assert rec["base_fingerprint"] and rec["organization_ref"]

    intent = await conn.fetchrow(
        "SELECT * FROM change_ledger.private_writer_dispatch_intents "
        "WHERE change_id=$1 AND claim_generation=$2", change_id, token["generation"],
    )
    assert intent is not None and intent["call_id"] == call_id
    intent_id, cas_id, permit_id = intent["dispatch_intent_id"], uuid.uuid4(), uuid.uuid4()
    process_id = str(uuid.uuid4())
    service_session = f"s13-synthetic-writer-{uuid.uuid4().hex[:10]}"
    service_id = "s13-synthetic-writer"
    host_id = "s13-disposable-host"
    key_id = f"s13-cosign-receipt-{uuid.uuid4().hex[:10]}"
    key_version = "synthetic-v1"
    public_key = hashlib.sha256(uuid.uuid4().bytes).digest()
    permit_digest = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    approval_digest = intent["approval_digest"]
    dispatch_generation = intent["dispatch_generation"]
    now = datetime.now(UTC)
    attempt = await conn.fetchrow(
        "SELECT * FROM change_ledger.dispatch_attempts WHERE change_id=$1", change_id,
    )
    assert attempt is None

    await conn.execute(
        "INSERT INTO change_ledger.private_writer_service_bindings(\"session_user\",base_fingerprint,"
        "writer_service_id,writer_host_id) VALUES($1,$2,$3,$4)",
        service_session, rec["base_fingerprint"], service_id, host_id,
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_versions(key_id,key_version,public_key,signer_role,"
        "service_id,host_id,valid_from,valid_until) VALUES($1,$2,$3,'writer_receipt',$4,$5,$6,$7)",
        key_id, key_version, public_key, service_id, host_id, now - timedelta(minutes=1), now + timedelta(hours=1),
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_scopes(key_id,key_version,tenant_id,company_id,"
        "organization_ref,base_fingerprint) VALUES($1,$2,$3,$4,$5,$6)",
        key_id, key_version, rec["tenant_id"], rec["company_id"], rec["organization_ref"], rec["base_fingerprint"],
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_permit_bindings(dispatch_intent_id,permit_id,permit_digest,"
        "checkpoint_seq,signer_key_id,signer_key_version,issued_at,expires_at) "
        "VALUES($1,$2,$3,1,$4,$5,$6,$7)",
        intent_id, permit_id, permit_digest, key_id, key_version, now - timedelta(seconds=1), now + timedelta(hours=1),
    )
    await conn.execute(
        "INSERT INTO change_ledger.dispatch_attempts(dispatch_cas_id,dispatch_intent_id,tenant_id,company_id,"
        "organization_ref,base_fingerprint,change_id,claim_generation,dispatch_generation,call_id,operation_kind,"
        "approval_digest,payload_digest,permit_id,permit_digest,expected_target_ref,expected_pre_version,auth_epoch,"
        "\"session_user\",writer_service_id,writer_host_id,writer_process_instance_id,service_epoch,state,"
        "invocation_started_at,com_entry_authorized_at) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'POST',$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,1,"
        "'POSSIBLY_EXECUTING',$22,$22)",
        cas_id, intent_id, rec["tenant_id"], rec["company_id"], rec["organization_ref"], rec["base_fingerprint"],
        change_id, token["generation"], dispatch_generation, call_id, approval_digest, rec["payload_digest"],
        permit_id, permit_digest, intent["target_ref"], intent["expected_pre_version"], intent["auth_epoch"], service_session,
        service_id, host_id, process_id, now,
    )

    common = {
        "tenant_id": rec["tenant_id"], "company_id": rec["company_id"],
        "organization_ref": rec["organization_ref"], "base_fingerprint": rec["base_fingerprint"],
        "change_id": change_id, "claim_generation": token["generation"],
        "dispatch_generation": dispatch_generation, "call_id": call_id,
        "dispatch_cas_id": cas_id, "dispatch_intent_id": intent_id, "operation_kind": "POST",
        "approval_digest": approval_digest, "payload_digest": rec["payload_digest"],
        "permit_id": permit_id, "permit_digest": permit_digest, "target_ref": rec["target_ref"],
        "pre_version": intent["expected_pre_version"], "auth_epoch": intent["auth_epoch"],
        "signer_key_id": key_id, "signer_key_version": key_version, "signer_role": "writer_receipt",
        "signer_service_id": service_id, "signer_host_id": host_id,
        "signed_at": now, "trust_registry_revision": 1, "verified_at": now,
        "validator_build_id": "s13-synthetic-e2e-fixture", "process_instance_id": process_id,
    }

    async def insert_private_evidence(kind: str, evidence_ref: str, signed: bytes,
                                      *, receipt_id: uuid.UUID | None = None) -> None:
        digest = hashlib.sha256(signed).hexdigest()
        values = dict(common)
        values.update({
            "evidence_ref": evidence_ref, "record_type": kind, "signed_bytes": signed,
            "signed_bytes_sha256": hashlib.sha256(signed).digest(), "record_digest": digest,
        })
        if kind == "DISPATCH_RECEIPT_V1":
            values.update({
                "writer_receipt_id": receipt_id, "writer_invocation_stage": "ENTERED",
                "writer_result_class": "CONDITIONAL_VERSION_CONFLICT", "writer_call_returned": True,
                "writer_returned_at": now,
            })
        else:
            values.update({"completion_proof_id": completion_id,
                           "completion_proof_class": "WRITER_CALL_RETURNED"})
        columns = list(values)
        placeholders = ",".join(f"${i}" for i in range(1, len(columns) + 1))
        await conn.execute(
            f"INSERT INTO change_ledger.private_writer_evidence({','.join(columns)}) VALUES({placeholders})",
            *(values[column] for column in columns),
        )

    receipt_ref = f"s13-witness-receipt-{uuid.uuid4()}"
    completion_ref = f"s13-witness-completion-{uuid.uuid4()}"
    receipt_id = uuid.uuid4()
    await insert_private_evidence(
        "DISPATCH_RECEIPT_V1", receipt_ref, b"synthetic conditional conflict receipt", receipt_id=receipt_id,
    )
    await insert_private_evidence("COMPLETION_PROOF_V1", completion_ref, b"synthetic completion proof")
    for kind, evidence_ref in (("WRITER_RECEIPT", receipt_ref), ("COMPLETION", completion_ref)):
        await conn.execute(
            "INSERT INTO change_ledger.private_writer_attempt_evidence(dispatch_cas_id,dispatch_intent_id,"
            "evidence_ref,evidence_purpose) VALUES($1,$2,$3,$4)", cas_id, intent_id, evidence_ref, kind,
        )
    return {
        "dispatch_intent_id": intent_id, "dispatch_cas_id": cas_id, "call_id": call_id,
        "generation": token["generation"], "completion_id": completion_id,
        "private_completion_ref": completion_ref, "receipt_ref": receipt_ref,
        "writer_receipt_id": receipt_id, "process_id": process_id,
    }


async def _wait_blocked(observer: asyncpg.Connection, pid: int, blocker: int,
                        task: asyncio.Task | None = None, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await observer.fetchrow(
            "SELECT wait_event_type,pg_catalog.pg_blocking_pids(pid) AS blockers "
            "FROM pg_catalog.pg_stat_activity WHERE pid=$1", pid,
        )
        if last is not None and last["wait_event_type"] == "Lock" and blocker in last["blockers"]:
            return
        if task is not None and task.done():
            task.result()
            raise AssertionError(f"call finished before expected blocker: {last}")
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for pid={pid}; blocker={blocker}; last={last}")


async def test_s13_witness_cosign_legacy_catalog_acl_identity_and_direct_v1_denial(ledger: L) -> None:
    conn = ledger.conn
    owner, security_definer, result_type, source = await conn.fetchrow(
        "SELECT pg_catalog.pg_get_userbyid(p.proowner),p.prosecdef,"
        "pg_catalog.pg_get_function_result(p.oid),p.prosrc FROM pg_catalog.pg_proc p WHERE p.oid=$1::regprocedure",
        OLD,
    )
    assert (owner, security_definer, result_type) == ("ledger_owner", True, "uuid")
    assert "witness_cosign_signed_v1" in source
    assert await conn.fetchval("SELECT pg_catalog.has_function_privilege('clt_erin',$1,'EXECUTE')", OLD)
    assert await conn.fetchval("SELECT pg_catalog.has_function_privilege('operator_role',$1,'EXECUTE')", OLD)
    assert not await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL "
        "pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a "
        "WHERE p.oid=$1::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE')", OLD,
    )
    granted_roles = await conn.fetch(
        "SELECT r.rolname FROM pg_catalog.pg_proc p CROSS JOIN LATERAL "
        "pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a "
        "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE p.oid=$1::regprocedure "
        "AND a.privilege_type='EXECUTE' ORDER BY r.rolname", OLD,
    )
    assert [row["rolname"] for row in granted_roles] == ["ledger_owner", "operator_role"]
    assert not await conn.fetchval("SELECT pg_catalog.has_function_privilege('clt_wri',$1,'EXECUTE')", OLD)
    assert not await conn.fetchval("SELECT pg_catalog.has_function_privilege('clt_wrk',$1,'EXECUTE')", OLD)
    assert not await conn.fetchval("SELECT pg_catalog.has_function_privilege('clt_erin',$1,'EXECUTE')", V1)

    change_id, token, call_id, completion_id = await _triage(ledger, "catalog")
    login = await _login(ledger, "identity")
    before = await _ledger_snapshot(conn)
    cosign_id = await _call_as(ledger, conn, login, "clt_erin", "witness_cosign_signed", change_id, completion_id)
    assert isinstance(cosign_id, uuid.UUID)
    row = await conn.fetchrow(
        "SELECT cosign_id,change_id,signer,signer_session,completion_proof,consumed_at "
        "FROM change_ledger.witness_cosigns WHERE cosign_id=$1", cosign_id,
    )
    assert row is not None
    assert (row["cosign_id"], row["change_id"], row["signer"], row["signer_session"]) == (
        cosign_id, change_id, "clt_erin", login,
    )
    assert _json(row["completion_proof"])["evidence_id"] == str(completion_id)
    assert row["consumed_at"] is None
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.witness_cosigns WHERE change_id=$1", change_id,
    ) == 1
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type ILIKE '%COSIGN%'", change_id,
    ) == 0
    assert await _ledger_snapshot(conn) != before

    for role in DIRECT_ROLES:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL ROLE "{role}"')
            with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
                await conn.fetchval(f"SELECT {V1_NAME}($1,$2,$3,$4)", T, C, change_id, completion_id)
            assert denied.value.sqlstate == "42501"


async def test_s13_witness_cosign_exact_retry_after_consumption_and_distinct_session(ledger: L) -> None:
    conn = ledger.conn
    change_id, token, call_id, _ = await _triage(ledger, "replay")
    completion_id = await ledger.evidence(
        change_id, "COMPLETION_PROOF",
        {"class": "a", "result_returned": False, "attribution_proof": True}, role="clt_wri",
    )
    first_session, second_session = await _login(ledger, "same"), await _login(ledger, "different")
    first_id = await _call_as(ledger, conn, first_session, "clt_erin", "witness_cosign_signed", change_id, completion_id)
    second_id = await _call_as(ledger, conn, second_session, "clt_erin", "witness_cosign_signed", change_id, completion_id)
    assert isinstance(second_id, uuid.UUID) and second_id != first_id
    # Migration 027 intentionally revokes the legacy terminal resolver. Model only the
    # already-consumed cosign as invocation-owned fixture state; keep the current Triage
    # record and open CALL_OWNERSHIP hold because terminal resolution is a separate contract.
    assert await conn.execute(
        "UPDATE change_ledger.witness_cosigns SET consumed_at=clock_timestamp() "
        "WHERE cosign_id=$1 AND consumed_at IS NULL", first_id,
    ) == "UPDATE 1"
    assert await conn.fetchval(
        "SELECT consumed_at IS NOT NULL FROM change_ledger.witness_cosigns WHERE cosign_id=$1", first_id,
    )
    assert await conn.fetchval(
        "SELECT execution_state='TRIAGE_REQUIRED' FROM change_ledger.records WHERE change_id=$1", change_id,
    )
    assert await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM change_ledger.holds WHERE change_id=$1 "
        "AND cause='CALL_OWNERSHIP' AND released_at IS NULL)", change_id,
    )
    consumed_snapshot = await _ledger_snapshot(conn)
    retry_id = await _call_as(ledger, conn, first_session, "clt_erin", "witness_cosign_signed", change_id, completion_id)
    assert retry_id == first_id
    assert await _ledger_snapshot(conn) == consumed_snapshot

    # With the CALL_OWNERSHIP hold released, a new session has no exact prior identity and
    # cannot mint another cosign, while the exact consumed replay above remains lookup-only.
    assert await conn.execute(
        "UPDATE change_ledger.holds SET released_at=clock_timestamp(),release_evidence='{}'::jsonb "
        "WHERE change_id=$1 AND cause='CALL_OWNERSHIP' AND released_at IS NULL", change_id,
    ) == "UPDATE 1"
    released_snapshot = await _ledger_snapshot(conn)
    third_session = await _login(ledger, "released-distinct")
    await _expect_code(
        "FORBIDDEN_TRANSITION",
        _call_as(ledger, conn, third_session, "clt_erin", "witness_cosign_signed", change_id, completion_id),
    )
    assert await _ledger_snapshot(conn) == released_snapshot

    rows = await conn.fetch(
        "SELECT cosign_id,signer,signer_session,completion_proof->>'evidence_id' AS evidence_id "
        "FROM change_ledger.witness_cosigns WHERE change_id=$1 ORDER BY signer_session", change_id,
    )
    assert len(rows) == 2
    assert {(r["signer"], r["evidence_id"]) for r in rows} == {("clt_erin", str(completion_id))}
    assert {r["signer_session"] for r in rows} == {first_session, second_session}
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.witness_cosigns WHERE change_id=$1", change_id,
    ) == 2
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type ILIKE '%COSIGN%'", change_id,
    ) == 0


async def test_s13_witness_cosign_distinct_authorized_witnesses(ledger: L) -> None:
    conn = ledger.conn
    change_id, _token, _call_id, completion_id = await _triage(ledger, "distinct-witnesses")
    erin_session = await _login(ledger, "witness-erin", actor="clt_erin")
    dave_session = await _login(ledger, "witness-dave", actor="clt_dave")

    erin_id = await _call_as(
        ledger, conn, erin_session, "clt_erin", "witness_cosign_signed", change_id, completion_id,
    )
    dave_id = await _call_as(
        ledger, conn, dave_session, "clt_dave", "witness_cosign_signed", change_id, completion_id,
    )

    assert isinstance(erin_id, uuid.UUID) and isinstance(dave_id, uuid.UUID)
    assert erin_id != dave_id
    rows = await conn.fetch(
        "SELECT cosign_id,signer,signer_session FROM change_ledger.witness_cosigns "
        "WHERE change_id=$1 ORDER BY signer", change_id,
    )
    assert {(row["signer"], row["cosign_id"], row["signer_session"]) for row in rows} == {
        ("clt_erin", erin_id, erin_session), ("clt_dave", dave_id, dave_session),
    }
    assert await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM change_ledger.holds WHERE change_id=$1 "
        "AND cause='CALL_OWNERSHIP' AND released_at IS NULL)", change_id,
    ) is True


async def test_s13_witness_cosign_concurrent_exact_retries_are_lookup_only(ledger: L) -> None:
    change_id, token, call_id, completion_id = await _triage(ledger, "race")
    login = await _login(ledger, "race")
    holder, first, second, observer = [await ledger.db.connect() for _ in range(4)]
    holder_tx = holder.transaction()
    first_task = second_task = None
    try:
        await holder_tx.start()
        holder_pid = await holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        first_pid = await first.fetchval("SELECT pg_catalog.pg_backend_pid()")
        second_pid = await second.fetchval("SELECT pg_catalog.pg_backend_pid()")
        scope_key = f"s13-scope:v1:{len(T.encode())}:{T}:{len(C.encode())}:{C}"
        await holder.fetchval("SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key)
        baseline = await _ledger_snapshot(ledger.conn)
        first_task = asyncio.create_task(
            _call_as(ledger, first, login, "clt_erin", "witness_cosign_signed", change_id, completion_id),
        )
        await _wait_blocked(observer, first_pid, holder_pid, first_task)
        second_task = asyncio.create_task(
            _call_as(ledger, second, login, "clt_erin", "witness_cosign_signed", change_id, completion_id),
        )
        await _wait_blocked(observer, second_pid, holder_pid, second_task)
        await holder_tx.commit()
        first_id, second_id = await asyncio.gather(first_task, second_task)
        assert isinstance(first_id, uuid.UUID) and second_id == first_id
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.witness_cosigns WHERE change_id=$1", change_id,
        ) == 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type ILIKE '%COSIGN%'", change_id,
        ) == 0
        assert await _ledger_snapshot(ledger.conn) != baseline
    finally:
        for task in (first_task, second_task):
            if task and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if holder.is_in_transaction():
            await holder_tx.rollback()
        for item in (holder, first, second, observer):
            await item.close()


async def test_s13_witness_cosign_apply_unknown_requires_exact_conditional_receipt_and_completion(
        ledger: L) -> None:
    change_id, token, call_id, completion_id = await _unknown(ledger, "conditional")
    login = await _login(ledger, "conditional")
    before = await _ledger_snapshot(ledger.conn)
    await _expect_code(
        "T16_RESOLUTION_REQUIRED",
        _call_as(ledger, ledger.conn, login, "clt_erin", "witness_cosign_signed", change_id, completion_id),
    )
    assert await _ledger_snapshot(ledger.conn) == before

    private = await _attach_private_conditional_receipt(ledger, change_id, token, call_id, completion_id)
    row = await ledger.conn.fetchrow(
        "SELECT r.execution_state,r.call_ownership,p.state,p.call_id,p.generation,h.cause,h.released_at "
        "FROM change_ledger.records r JOIN change_ledger.dispatch_permits p USING(change_id) "
        "JOIN change_ledger.holds h USING(change_id) WHERE r.change_id=$1 AND p.generation=$2 "
        "AND h.cause='CALL_OWNERSHIP'", change_id, token["generation"],
    )
    assert row is not None
    assert (row["execution_state"], row["call_ownership"], row["state"], row["call_id"], row["generation"]) == (
        "APPLY_UNKNOWN", "POSSIBLY_EXECUTING", "DISPATCHED", call_id, token["generation"],
    )
    assert row["released_at"] is None
    assert private["call_id"] == call_id and private["generation"] == token["generation"]
    before = await _ledger_snapshot(ledger.conn)
    cosign_id = await _call_as(ledger, ledger.conn, login, "clt_erin", "witness_cosign_signed", change_id, completion_id)
    assert isinstance(cosign_id, uuid.UUID)
    stored = await ledger.conn.fetchrow(
        "SELECT cosign_id,signer,signer_session,completion_proof FROM change_ledger.witness_cosigns "
        "WHERE cosign_id=$1", cosign_id,
    )
    assert stored is not None and stored["signer"] == "clt_erin" and stored["signer_session"] == login
    assert _json(stored["completion_proof"])["evidence_id"] == str(completion_id)
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.private_writer_attempt_evidence ae "
        "WHERE ae.dispatch_cas_id=$1 AND ae.evidence_purpose IN ('WRITER_RECEIPT','COMPLETION')", private["dispatch_cas_id"],
    ) == 2
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type ILIKE '%COSIGN%'", change_id,
    ) == 0
    assert await _ledger_snapshot(ledger.conn) != before
    after = await _ledger_snapshot(ledger.conn)
    assert await _call_as(ledger, ledger.conn, login, "clt_erin", "witness_cosign_signed", change_id, completion_id) == cosign_id
    assert await _ledger_snapshot(ledger.conn) == after


async def test_s13_witness_cosign_incomplete_and_foreign_bindings_refuse_without_delta(ledger: L) -> None:
    change_id, token, call_id, completion_id = await _unknown(ledger, "incomplete")
    login = await _login(ledger, "incomplete")
    before = await _ledger_snapshot(ledger.conn)
    await _expect_code(
        "T16_RESOLUTION_REQUIRED",
        _call_as(ledger, ledger.conn, login, "clt_erin", "witness_cosign_signed", change_id, completion_id),
    )
    assert await _ledger_snapshot(ledger.conn) == before

    foreign_id = uuid.uuid4()
    await _expect_code(
        "T16_RESOLUTION_REQUIRED",
        _call_as(ledger, ledger.conn, login, "clt_erin", "witness_cosign_signed", change_id, foreign_id),
    )
    assert await _ledger_snapshot(ledger.conn) == before

    # A caller with an authorized foreign scope cannot use the same change/evidence identity there.
    await ledger.conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES('clt_erin','T2','C2') "
        "ON CONFLICT DO NOTHING",
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities) "
        "VALUES('T2','C2','clt_erin','person-s13-foreign-operator',ARRAY['operator','recovery_witness']) "
        "ON CONFLICT(tenant_id,company_id,principal) DO NOTHING",
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
        "VALUES('T2','C2','LEGACY',0,'SYNTHETIC_TEST') ON CONFLICT DO NOTHING",
    )
    foreign_before = await _ledger_snapshot(ledger.conn)
    await _expect_code(
        "CHANGE_NOT_FOUND",
        _call_as(ledger, ledger.conn, login, "clt_erin", "witness_cosign_signed", change_id, completion_id,
                 t="T2", c="C2"),
    )
    assert await _ledger_snapshot(ledger.conn) == foreign_before


async def test_s13_witness_cosign_stale_completion_generation_refuses_without_delta(ledger: L) -> None:
    conn = ledger.conn
    change_id, token, call_id, stale_completion = await _triage(ledger, "stale-generation")
    # Supersede the old generation in the disposable fixture while preserving its permit row.
    assert await conn.execute(
        "UPDATE change_ledger.records SET claim_generation=claim_generation+1 WHERE change_id=$1", change_id,
    ) == "UPDATE 1"
    operator_session = await _login(ledger, "stale")
    before = await _ledger_snapshot(conn)
    await _expect_code(
        "TICKET_SUPERSEDED",
        _call_as(ledger, conn, operator_session, "clt_erin", "witness_cosign_signed", change_id, stale_completion),
    )
    assert await _ledger_snapshot(conn) == before


async def test_s13_witness_cosign_scope_global_parent_child_lock_order(ledger: L) -> None:
    change_id, token, call_id, completion_id = await _triage(ledger, "locks")
    login = await _login(ledger, "locks")
    scope_holder, record_holder, hold_holder, worker, observer = [await ledger.db.connect() for _ in range(5)]
    scope_tx, record_tx, hold_tx = scope_holder.transaction(), record_holder.transaction(), hold_holder.transaction()
    task: asyncio.Task | None = None
    try:
        await scope_tx.start()
        await record_tx.start()
        await hold_tx.start()
        scope_pid = await scope_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        record_pid = await record_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        hold_pid = await hold_holder.fetchval("SELECT pg_catalog.pg_backend_pid()")
        worker_pid = await worker.fetchval("SELECT pg_catalog.pg_backend_pid()")
        scope_key = f"s13-scope:v1:{len(T.encode())}:{T}:{len(C.encode())}:{C}"
        await scope_holder.fetchval("SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key)
        await record_holder.fetchrow(
            "SELECT change_id FROM change_ledger.records WHERE change_id=$1 FOR UPDATE", change_id,
        )
        await hold_holder.fetchrow(
            "SELECT hold_id FROM change_ledger.holds WHERE change_id=$1 AND cause='CALL_OWNERSHIP' "
            "AND released_at IS NULL FOR UPDATE", change_id,
        )
        task = asyncio.create_task(
            _call_as(ledger, worker, login, "clt_erin", "witness_cosign_signed", change_id, completion_id),
        )
        await _wait_blocked(observer, worker_pid, scope_pid, task)
        scope_wait = await observer.fetch(
            "SELECT classid::bigint AS namespace,granted FROM pg_catalog.pg_locks "
            "WHERE pid=$1 AND locktype='advisory'", worker_pid,
        )
        assert 7 in {row["namespace"] for row in scope_wait if not row["granted"]}
        assert 6 not in {row["namespace"] for row in scope_wait if row["granted"]}
        await scope_tx.commit()
        await _wait_blocked(observer, worker_pid, record_pid, task)
        advisory = await observer.fetch(
            "SELECT classid::bigint AS namespace,objid::bigint AS lock_key,granted FROM pg_catalog.pg_locks "
            "WHERE pid=$1 AND locktype='advisory' ORDER BY classid,objid", worker_pid,
        )
        namespaces = {row["namespace"] for row in advisory if row["granted"]}
        assert 7 in namespaces and 6 in namespaces and 3 in namespaces, advisory
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.witness_cosigns WHERE change_id=$1", change_id,
        ) == 0

        # The body and the shared helper bind the live lock plan: scope 7, sorted namespace 6,
        # then record parent, open hold child, and finally cosign insert.
        body = await ledger.conn.fetchval("SELECT p.prosrc FROM pg_catalog.pg_proc p WHERE p.oid=$1::regprocedure", V1)
        helper = await ledger.conn.fetchval(
            "SELECT p.prosrc FROM pg_catalog.pg_proc p WHERE p.oid='change_ledger.private_writer_take_global_fences_v1(text[])'::regprocedure"
        )
        assert "private_writer_take_scope_fence_v1" in body
        assert body.index("private_writer_take_scope_fence_v1") < body.index("private_writer_take_global_fences_v1")
        assert "ORDER BY 1" in helper and "pg_advisory_xact_lock(6,k)" in helper
        record_lock = body.index("FOR UPDATE")
        hold_start = body.index("SELECT * INTO call_hold")
        hold_lock = body.index("FOR UPDATE", hold_start)
        cosign_insert = body.index("INSERT INTO change_ledger.witness_cosigns", hold_lock + 1)
        assert record_lock < hold_lock < cosign_insert
        await record_tx.commit()
        await _wait_blocked(observer, worker_pid, hold_pid, task)
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.witness_cosigns WHERE change_id=$1", change_id,
        ) == 0
        await hold_tx.commit()
        result = await task
        assert isinstance(result, uuid.UUID)
    finally:
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for tx, conn in ((scope_tx, scope_holder), (record_tx, record_holder), (hold_tx, hold_holder)):
            if conn.is_in_transaction():
                await tx.rollback()
        for item in (scope_holder, record_holder, hold_holder, worker, observer):
            await item.close()
