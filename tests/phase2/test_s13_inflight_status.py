"""S13 operator list/status SQL contract against disposable PostgreSQL."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import disposable_cluster, throwaway_db
from test_change_ledger_sql import C, L, T, _setup
from business_ai_gateway.phase2.change_ledger.sql_ledger import _S13_LEGACY_READS

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "phase2"


async def _apply(conn: asyncpg.Connection, name: str) -> None:
    raw = (MIGRATIONS / name).read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ledger():
    old = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, _name, _token):
            async with throwaway_db(dsn, seed=False) as db:
                for version in range(19, 27):
                    await _apply(db.conn, next(p.name for p in MIGRATIONS.glob(f"{version:03d}_*.sql")))
                await _setup(db.conn)
                await db.conn.execute(
                    "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
                    "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE'),('T2','C2','LEGACY',0,'TEST_FIXTURE') "
                    "ON CONFLICT DO NOTHING", T, C)
                legacy_ledger = L(db)
                applied_id, token, _call_id = await legacy_ledger.dispatched(
                    request_id="s13-applied-unverified", base="base-6", target="doc-s13-applied")
                assert await legacy_ledger.complete(applied_id, token["generation"], "SUCCESS") == "APPLIED"

                # Preserve this genuinely completed row across the private-writer cutover under test.
                await _apply(db.conn, next(p.name for p in MIGRATIONS.glob("027_*.sql")))
                await _apply(db.conn, "028_refusal_codes_parity.sql")
                await _apply(db.conn, "029_s12_budget_snapshot.sql")
                await _apply(db.conn, "030_s13_inflight_status_reads.sql")
                legacy_ledger.applied_unverified_id = applied_id
                yield legacy_ledger
    finally:
        if old is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old


def _decode_json(value):
    return json.loads(value) if isinstance(value, str) else value


async def test_operator_list_and_status_follow_live_ledger_transitions(ledger: L):
    change_id = await ledger.approved(request_id="s13-inflight-status")
    before = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0))
    row = next(item for item in before if item["change_id"] == str(change_id))
    assert row["execution_state"] == "NOT_STARTED"
    assert not ({"payload", "proposal", "evidence", "payload_json"} & set(row))

    token = await ledger.claimed(change_id)
    claimed = _decode_json(await ledger.call("clt_dave", "operator_status", change_id))
    assert claimed["change_id"] == str(change_id)
    assert claimed["execution"] == "NOT_STARTED"
    assert claimed["authorization"] == "CLAIMED"
    assert claimed["reservation"] == "RESERVED"
    assert not ({"payload", "proposal", "evidence", "payload_json"} & set(claimed))
    current = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0))
    assert any(item["change_id"] == str(change_id) and item["authorization_state"] == "CLAIMED"
               for item in current)

    missing_id = uuid4()
    try:
        await ledger.call("clt_dave", "operator_status", missing_id)
    except asyncpg.PostgresError as exc:
        assert str(exc).splitlines()[0] == "CHANGE_NOT_FOUND", str(exc)
    else:
        raise AssertionError("unknown change returned a fabricated status")

    # migration 027 intentionally revokes legacy begin_apply from runtime roles; this journey
    # stops at the permitted claim boundary and proves the operator view tracks that service state.
    assert token["generation"] == 1


async def test_list_includes_unverified_applied_until_successful_verification(ledger: L):
    change_id = ledger.applied_unverified_id
    record = await ledger.rec(change_id)
    assert (record["execution_state"], record["verification_state"]) == ("APPLIED", "NOT_VERIFIED")
    listed = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0))
    row = next(item for item in listed if item["change_id"] == str(change_id))
    assert row["execution_state"] == "APPLIED"
    assert row["verification_state"] == "NOT_VERIFIED"
    status = _decode_json(await ledger.call("clt_dave", "operator_status", change_id))
    assert status["execution"] == "APPLIED"
    assert status["verification"] == "NOT_VERIFIED"

    # Migration 027 revokes both verify_signed and verify from runtime roles. Change only the
    # verification projection in this disposable setup DB to model a successful verification.
    await ledger.conn.execute(
        "UPDATE change_ledger.records SET verification_state='VERIFIED', updated_at=clock_timestamp() "
        "WHERE change_id=$1 AND execution_state='APPLIED' AND verification_state='NOT_VERIFIED'", change_id)
    assert (await ledger.rec(change_id))["verification_state"] == "VERIFIED"
    after_verification = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0))
    assert all(item["change_id"] != str(change_id) for item in after_verification)


async def test_operator_status_and_list_do_not_reveal_another_company_record(ledger: L):
    foreign = await ledger.propose(requester="clt_zed", request_id="s13-foreign-scope",
                                   t="T2", c="C2", base="base-t2")
    try:
        await ledger.call("clt_dave", "operator_status", foreign, t=T, c=C)
    except asyncpg.PostgresError as exc:
        assert str(exc).splitlines()[0] == "CHANGE_NOT_FOUND", str(exc)
    else:
        raise AssertionError("operator status disclosed a foreign-company record")

    listed = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0, t=T, c=C))
    assert all(item["change_id"] != str(foreign) for item in listed)
    try:
        await ledger.call("clt_dave", "operator_status", foreign)
    except asyncpg.PostgresError as exc:
        assert str(exc).splitlines()[0] == "CHANGE_NOT_FOUND", str(exc)
    else:
        raise AssertionError("foreign-company record was distinguishable from an unknown ID")


async def test_list_excludes_terminal_lifecycle_and_authorization_transitions(ledger: L):
    # Lifecycle terminal states are reached through their public ledger transitions.
    rejected = await ledger.validated(request_id="s13-terminal-rejected")
    nonce = await ledger.call("clt_bob", "issue_approval_nonce", rejected)
    assert await ledger.call("clt_bob", "reject", rejected, nonce) == "REJECTED"

    first_key = "a" * 64
    first = await ledger.propose(request_id="s13-duplicate-source")
    await ledger.call("clt_alice", "declare_business_key", first, first_key, None, None)
    assert await ledger.call("clt_alice", "validate", first) == "VALIDATED"
    duplicate = await ledger.propose(request_id="s13-terminal-duplicate")
    await ledger.call("clt_alice", "declare_business_key", duplicate, first_key, None, None)
    assert await ledger.call("clt_alice", "validate", duplicate) == "DUPLICATE_PARKED"

    revoked = await ledger.approved(request_id="s13-terminal-revoked")
    assert await ledger.call("clt_dave", "revoke_change", revoked, "SESSION_REVOKED") == "REVOKED"

    voided = await ledger.approved(request_id="s13-terminal-voided")
    # A real approver epoch bump makes the recorded approval stale; the operator revocation API voids it.
    await ledger.call("clt_dave", "bump_epoch", "principal:clt_bob")
    assert await ledger.call("clt_dave", "revoke_change", voided, "EPOCH_DEPENDENCY") == "VOIDED"
    assert (await ledger.rec(voided))["authorization_state"] == "VOIDED"

    # The 027 private-writer cutover revokes the worker EXECUTE grant for legacy recover_sweep.
    # Invoke that same ledger transition from the disposable-cluster fixture's privileged setup connection.
    expired = await ledger.validated(request_id="s13-terminal-expired")
    await ledger.conn.execute("UPDATE change_ledger.records SET created_at=now()-interval '2 hours', "
                              "expires_at=now()-interval '1 second' "
                              "WHERE change_id=$1", expired)
    async with ledger.conn.transaction():
        await ledger.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", "T1", "C1")
        await ledger.conn.fetchval("SELECT change_ledger.recover_sweep($1,$2,'{}'::jsonb)", "T1", "C1")
    exp_record = await ledger.rec(expired)
    assert (exp_record["lifecycle"], exp_record["authorization_state"]) == ("EXPIRED_QUEUED", "EXPIRED")

    active = await ledger.validated(request_id="s13-terminal-control-active")
    listed = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0))
    listed_ids = {item["change_id"] for item in listed}
    assert str(active) in listed_ids
    assert not ({str(rejected), str(duplicate), str(expired), str(revoked), str(voided)} & listed_ids)


async def test_list_bounds_and_catalog_privileges_are_explicit(ledger: L):
    for limit, offset in ((0, 0), (101, 0), (50, -1)):
        with pytest.raises(asyncpg.PostgresError, match="INVALID_ARGUMENT"):
            await ledger.call("clt_dave", "list_inflight", limit, offset)

    rows = await ledger.conn.fetch(
        """SELECT p.proname, owner.rolname AS owner_name, p.prosecdef, p.proconfig,
                  has_function_privilege('operator_role', p.oid, 'EXECUTE') AS operator_exec,
                  has_function_privilege('auditor_role', p.oid, 'EXECUTE') AS auditor_exec,
                  has_function_privilege('requester_role', p.oid, 'EXECUTE') AS requester_exec,
                  has_function_privilege('approver_role', p.oid, 'EXECUTE') AS approver_exec,
                  has_function_privilege('writer_role', p.oid, 'EXECUTE') AS writer_exec,
                  has_function_privilege('worker_role', p.oid, 'EXECUTE') AS worker_exec,
                  has_function_privilege('checkpoint_role', p.oid, 'EXECUTE') AS checkpoint_exec
             FROM pg_proc p
             JOIN pg_namespace n ON n.oid=p.pronamespace
             JOIN pg_roles owner ON owner.oid=p.proowner
            WHERE n.nspname='change_ledger' AND p.proname=ANY($1::text[])""",
        ["list_inflight", "operator_status"],
    )
    assert {row["proname"] for row in rows} == {"list_inflight", "operator_status"}
    for row in rows:
        assert row["owner_name"] == "ledger_owner"
        assert row["prosecdef"] is True
        assert any("search_path=pg_catalog,pg_temp" == setting.replace(" ", "")
                   for setting in row["proconfig"] or [])
        assert row["operator_exec"] is True
        assert row["auditor_exec"] is True
        assert all(row[f"{role}_exec"] is False
                   for role in ("requester", "approver", "writer", "worker", "checkpoint"))


async def test_status_reads_are_allowed_in_s13_private_mode():
    assert {"list_inflight", "operator_status"} <= _S13_LEGACY_READS
