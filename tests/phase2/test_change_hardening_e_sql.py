"""Focused PostgreSQL tests for db/phase2/012_dispatch_session_hardening.sql: batch E (A7-B01, C-M03, B6-h).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied and the actors of
test_change_ledger_sql._setup. Superuser access arranges only what no API can produce (back-dated counters, a legacy
approval row without a session, tampering probes) and reads results; it never removes a guard. A "session" is a login
role assumed with SET LOCAL SESSION AUTHORIZATION followed by SET LOCAL ROLE <actor> (see test_change_hardening_c_sql).

Item -> tests:
  E1 A7-B01 dispatch coupled to verify_dispatch_payload inside the ledger: e1_*
  E2 C-M03 approver session recorded; resolve / close refuse the approver's session: e2_*
  E3 B6-h verification ticks are spaced, sweep frequency cannot burn the bound: e3_*
"""
import asyncio
import hashlib
import json
import uuid

import asyncpg
import pytest
from _approval_envelope import FIXTURE_PAYLOAD
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_hardening_c_sql import login, sess, witness
from test_change_ledger_sql import C, T, L, _setup
from test_change_sweeps_sql import FAST, age_verify_counter, applied, counter, sweep

from business_ai_gateway.phase2.change import canonical_json

pytestmark = pytest.mark.integration

PAYLOAD = canonical_json(FIXTURE_PAYLOAD)


class E(L):
    """L whose approvals can be given inside a chosen login session (approver_login)."""

    approver_login = None

    async def approved(self, approver="clt_bob", **kw):
        if self.approver_login is None:
            return await super().approved(approver, **kw)
        cid = await self.validated(**kw)
        nonce = await sess(self, self.approver_login, approver, "issue_approval_nonce", cid)
        await sess(self, self.approver_login, approver, "approve", cid, nonce, await self.approval_digest(cid))
        return cid


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield E(db)


async def raw_record_call(led, cid, gen, call_id):
    """record_call WITHOUT the fixture helper that verifies the payload first (the ledger's own gate is under test)."""
    rows = await led.sql("clt_wri", "SELECT change_ledger.record_call($1,$2,$3,$4,$5)", T, C, cid, gen, call_id)
    return rows[0][0]


async def markers(led, cid):
    return await led.conn.fetchval("SELECT count(*) FROM change_ledger.change_dispatch_verifications "
                                   "WHERE change_id=$1", cid)


async def verified_events(led, cid):
    rows = await led.conn.fetch("SELECT payload FROM change_ledger.events WHERE change_id=$1 AND "
                                "event_type='DISPATCH_PAYLOAD_VERIFIED'", cid)
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"] for r in rows]


# ============================================================================ E1: dispatch needs the verification marker
async def test_e1_dispatch_without_verification_is_refused_then_allowed_after_it(led):
    cid, tok, call_id, _ = await led.permitted(request_id="e1a", base="base-1")
    gen = tok["generation"]
    await fails("FORBIDDEN_TRANSITION", raw_record_call(led, cid, gen, call_id))
    r = await led.rec(cid)
    assert r["dispatch_state"] == "PERMITTED"                       # nothing moved: the writer can verify and retry
    assert await led.conn.fetchval("SELECT state FROM change_ledger.dispatch_permits WHERE change_id=$1", cid) == "PERMITTED"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND "
                                   "event_type='DISPATCHED'", cid) == 0
    assert await markers(led, cid) == 0
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, gen, PAYLOAD) is True
    assert await markers(led, cid) == 1
    assert await raw_record_call(led, cid, gen, call_id) is True
    assert (await led.rec(cid))["dispatch_state"] == "DISPATCHED"


async def test_e1_marker_replay_is_idempotent_and_the_event_carries_digests_only(led):
    cid, tok, call_id, _ = await led.permitted(request_id="e1b", base="base-1")
    gen = tok["generation"]
    for _ in range(3):
        assert await led.call("clt_wri", "verify_dispatch_payload", cid, gen, PAYLOAD) is True
    assert await markers(led, cid) == 1
    ev = await verified_events(led, cid)
    assert len(ev) == 1
    assert set(ev[0]) == {"generation", "payload_digest", "verification_id", "wire_payload_sha256"}   # 018 adds the wire sha
    assert ev[0]["payload_digest"] == (await led.rec(cid))["payload_digest"]
    assert ev[0]["wire_payload_sha256"] == hashlib.sha256(PAYLOAD.encode("ascii")).hexdigest()
    assert "supplier_document_number" not in json.dumps(ev[0]) and "fixture" not in json.dumps(ev[0])
    # the requester may verify too (existing grant) and it is the same marker
    assert await led.call("clt_alice", "verify_dispatch_payload", cid, gen, PAYLOAD) is True
    assert await markers(led, cid) == 1


async def test_e1_a_substituted_payload_leaves_no_marker_and_dispatch_stays_refused(led):
    cid, tok, call_id, _ = await led.permitted(request_id="e1c", base="base-1")
    gen = tok["generation"]
    other = canonical_json({**FIXTURE_PAYLOAD, "comment": "substituted"})
    await fails("DIGEST_MISMATCH", led.call("clt_wri", "verify_dispatch_payload", cid, gen, other))
    assert await markers(led, cid) == 0 and await verified_events(led, cid) == []
    await fails("FORBIDDEN_TRANSITION", raw_record_call(led, cid, gen, call_id))
    assert (await led.rec(cid))["dispatch_state"] == "PERMITTED"


async def test_e1_a_marker_of_an_older_generation_does_not_authorize_the_new_claim(led):
    cid, tok, call_id, _ = await led.permitted(request_id="e1d", base="base-1")
    gen = tok["generation"]
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, gen, PAYLOAD) is True
    assert await led.call("clt_wrk", "cancel_permit", cid, gen) is True            # the claim is given back
    tok2 = await led.claimed(cid)
    assert tok2["generation"] == gen + 1
    call2 = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok2["token_id"], call2, "host-1", "sess-1")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, tok2["generation"])
    await fails("FORBIDDEN_TRANSITION", raw_record_call(led, cid, tok2["generation"], call2))
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, tok2["generation"], PAYLOAD) is True
    assert await markers(led, cid) == 2
    assert await raw_record_call(led, cid, tok2["generation"], call2) is True


async def test_e1_a_marker_for_another_payload_digest_does_not_count(led):
    cid, tok, call_id, _ = await led.permitted(request_id="e1e", base="base-1")
    gen = tok["generation"]
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, gen, PAYLOAD) is True
    # the stored change no longer carries the digest that was verified (tampering probe): the marker does not match
    await led.conn.execute("UPDATE change_ledger.records SET payload_digest=repeat('a',64) WHERE change_id=$1", cid)
    await fails("FORBIDDEN_TRANSITION", raw_record_call(led, cid, gen, call_id))
    await led.conn.execute("UPDATE change_ledger.records SET payload_digest=$2 WHERE change_id=$1", cid,
                           (await led.conn.fetchval("SELECT payload_digest FROM change_ledger.change_dispatch_verifications "
                                                    "WHERE change_id=$1", cid)))
    assert await raw_record_call(led, cid, gen, call_id) is True


async def test_e1_every_path_to_dispatched_is_gated_not_only_record_call(led):
    cid, tok, call_id, _ = await led.permitted(request_id="e1f", base="base-1")
    gen = tok["generation"]
    with pytest.raises(asyncpg.PostgresError, match="FORBIDDEN_TRANSITION"):
        await led.conn.execute("UPDATE change_ledger.dispatch_permits SET state='DISPATCHED' WHERE change_id=$1", cid)
    with pytest.raises(asyncpg.PostgresError, match="FORBIDDEN_TRANSITION"):
        await led.conn.fetchval("SELECT change_ledger.dispatch_cas($1,$2,'PERMITTED','DISPATCHED')", cid, gen)
    assert await led.conn.fetchval("SELECT state FROM change_ledger.dispatch_permits WHERE change_id=$1", cid) == "PERMITTED"
    # the other transitions of the same CAS stay untouched (cancel)
    assert await led.call("clt_wrk", "cancel_permit", cid, gen) is True


async def test_e1_the_marker_table_is_immutable_and_not_writable_by_runtime_roles(led):
    cid, tok, _, _ = await led.permitted(request_id="e1g", base="base-1")
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, tok["generation"], PAYLOAD) is True
    for stmt in ("UPDATE change_ledger.change_dispatch_verifications SET verified_by='x'",
                 "DELETE FROM change_ledger.change_dispatch_verifications",
                 "TRUNCATE change_ledger.change_dispatch_verifications"):
        with pytest.raises(asyncpg.PostgresError, match="IMMUTABLE_LEDGER"):
            await led.conn.execute(stmt)
    for role in ("clt_wri", "clt_wrk", "clt_alice", "clt_aud"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, "INSERT INTO change_ledger.change_dispatch_verifications(tenant_id,company_id,change_id,"
                                "generation,payload_digest,verified_by) VALUES('T1','C1',$1,1,repeat('b',64),'x')", cid)
    seen = await led.sql("clt_aud", "SELECT count(*) FROM change_ledger.change_dispatch_verifications")
    assert seen[0][0] == 1
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.call("clt_wrk", "verify_dispatch_payload", cid, tok["generation"], PAYLOAD)


# ============================================================================ E2: the approver's session
async def test_e2_the_approver_session_is_recorded_from_session_user(led):
    a = await login(led, "clt_login_a", "clt_bob")
    led.approver_login = a
    by_login = await led.approved(request_id="e2-rec")
    led.approver_login = None
    by_super = await led.approved(request_id="e2-rec2", base="base-2")
    me = await led.conn.fetchval("SELECT session_user::text")
    q = "SELECT approver_session FROM change_ledger.approvals WHERE change_id=$1 AND decision='APPROVE'"
    assert await led.conn.fetchval(q, by_login) == a
    assert await led.conn.fetchval(q, by_super) == me


async def test_e2_operator_resolve_refuses_the_session_of_the_approver(led):
    a = await login(led, "clt_login_a", "clt_bob", "clt_dave")
    b = await login(led, "clt_login_b", "clt_dave", "clt_erin")
    c3 = await login(led, "clt_login_c", "clt_dave")
    led.approver_login = a
    cid, _, _ = await led.triage(request_id="e2-or")
    assert await led.conn.fetchval("SELECT approver_session FROM change_ledger.approvals WHERE change_id=$1", cid) == a
    w = await witness(led, cid, b)
    # the approving session cannot resolve, even as another actor (clt_dave) than the approving one (clt_bob)
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, a, "clt_dave", "operator_resolve", cid, w, True, False)
    assert (await led.rec(cid))["execution_state"] == "TRIAGE_REQUIRED"
    assert await led.conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns WHERE cosign_id=$1", w)
    # replay of the refusal changes nothing; another session resolves
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, a, "clt_dave", "operator_resolve", cid, w, True, False)
    assert await sess(led, c3, "clt_dave", "operator_resolve", cid, w, True, False) == "APPLIED"


async def test_e2_close_failed_verify_refuses_the_session_of_the_approver(led):
    a = await login(led, "clt_login_a", "clt_bob", "clt_dave")
    b = await login(led, "clt_login_b", "clt_dave", "clt_erin")
    c3 = await login(led, "clt_login_c", "clt_dave")
    led.approver_login = a
    cid, tok, _ = await led.dispatched(request_id="e2-cf", base="base-1")
    await led.complete(cid, tok["generation"], "SUCCESS")
    assert await led.verify(cid, False) == "FAILED_VERIFY"
    w = await witness(led, cid, b)
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, a, "clt_dave", "operator_close_failed_verify", cid, w, True)
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert await sess(led, c3, "clt_dave", "operator_close_failed_verify", cid, w, True) == "CLOSED"
    assert await led.open_holds("FAILED_VERIFY_HALT") == 0


async def test_e2_an_approval_without_a_recorded_session_fails_closed_for_a_real_session_only(led):
    b = await login(led, "clt_login_b", "clt_dave", "clt_erin")
    c3 = await login(led, "clt_login_c", "clt_dave")
    cid, _, _ = await led.triage(request_id="e2-legacy")            # approved in the (superuser) fixture session
    # arrange a legacy row: an approval written before 012 has no session (the immutable guard is lifted for the probe)
    await led.conn.execute("ALTER TABLE change_ledger.approvals DISABLE TRIGGER approvals_immutable")
    await led.conn.execute("UPDATE change_ledger.approvals SET approver_session=NULL WHERE change_id=$1", cid)
    await led.conn.execute("ALTER TABLE change_ledger.approvals ENABLE TRIGGER approvals_immutable")
    w = await witness(led, cid, b)
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, c3, "clt_dave", "operator_resolve", cid, w, True, False)
    assert (await led.rec(cid))["execution_state"] == "TRIAGE_REQUIRED"
    # a superuser session keeps the current behaviour
    assert await led.call("clt_dave", "operator_resolve", cid, w, True, False) == "APPLIED"


async def test_e2_a_different_session_of_the_same_login_family_is_not_blocked_and_existing_flows_work(led):
    # the approval was given by the (superuser) fixture session; a real, different session resolves normally
    b = await login(led, "clt_login_b", "clt_dave", "clt_erin")
    c3 = await login(led, "clt_login_c", "clt_dave")
    cid, _, _ = await led.triage(request_id="e2-ok")
    w = await witness(led, cid, b)
    assert await sess(led, c3, "clt_dave", "operator_resolve", cid, w, True, False) == "APPLIED"


# ============================================================================ E3: spaced verification ticks
async def test_e3_interval_zero_sweeps_cannot_burn_the_verification_bound(led):
    cid = await applied(led, request_id="e3a", base="base-1")
    for _ in range(6):
        got = await sweep(led, **FAST)                              # verify_interval_seconds = 0, called back to back
        assert got["VERIFY_EXHAUSTED"] == []
    row = await counter(led, cid, "VERIFY")
    assert row["attempts"] == 1 and row["closed_at"] is None
    assert (row["next_attempt_at"] - row["last_attempt_at"]).total_seconds() >= 5
    assert (await led.rec(cid))["verification_state"] == "NOT_VERIFIED"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND "
                                   "event_type='VERIFY_ATTEMPT'", cid) == 1


async def test_e3_a_tick_counts_again_once_the_spacing_elapsed_and_the_bound_still_holds(led):
    cid = await applied(led, request_id="e3b", base="base-1")
    assert (await sweep(led, **FAST))["VERIFY_DUE"] == [str(cid)]
    for n in (2,):
        await age_verify_counter(led)
        assert (await sweep(led, **FAST))["VERIFY_DUE"] == [str(cid)]
        assert (await counter(led, cid, "VERIFY"))["attempts"] == n
    await age_verify_counter(led)
    assert (await sweep(led, **FAST))["VERIFY_EXHAUSTED"] == [str(cid)]
    assert (await led.rec(cid))["verification_state"] == "FAILED_VERIFY"
    assert (await counter(led, cid, "VERIFY"))["attempts"] == 3


async def test_e3_the_check_sits_in_sql_not_only_in_the_schedule(led):
    cid = await applied(led, request_id="e3c", base="base-1")
    sql = "SELECT change_ledger.verify_attempt_internal('T1','C1',$1,$2,3,0)"
    first = json.loads(await led.conn.fetchval(sql, cid, "SWEEP_STUCK"))
    assert first == {"attempts": 1, "exhausted": False}
    for _ in range(5):                                              # direct burst with interval 0: not counted
        again = json.loads(await led.conn.fetchval(sql, cid, "SWEEP_STUCK"))
        assert again == {"attempts": 1, "exhausted": False, "throttled": True}
    assert (await counter(led, cid, "VERIFY"))["attempts"] == 1
    # a real signed inconclusive observation is an attempt by evidence, not a tick: it is counted at once
    obs = await led.observation(cid, None, inconclusive=True, reader="down")
    assert json.loads(await led.call("clt_wrk", "verify_inconclusive", cid, obs)) == {"attempts": 2, "exhausted": False}


async def test_e3_the_spacing_is_a_documented_constant_with_a_floor_of_one_second(led):
    assert json.loads(await led.conn.fetchval("SELECT change_ledger.sweep_constants()"))["verify_min_tick_seconds"] == 5
    assert await led.conn.fetchval("SELECT change_ledger.verify_tick_min_spacing('T1','C1')") == 5
    for bad in ('{"verify_min_tick_seconds":0}', '{"verify_min_tick_seconds":0.5}', '{"verify_min_tick_seconds":3601}',
                '{"verify_min_tick_seconds":"2"}'):
        await fails("SCHEMA_INVALID", led.call("clt_dave", "set_sweep_policy", bad))
    for role in ("clt_wrk", "clt_wri", "clt_alice", "clt_aud"):
        await fails("permission denied", led.call(role, "set_sweep_policy", '{"verify_min_tick_seconds":2}'))
    merged = json.loads(await led.call("clt_dave", "set_sweep_policy", '{"verify_min_tick_seconds":2}'))
    assert merged == {"verify_min_tick_seconds": 2}
    assert await led.conn.fetchval("SELECT change_ledger.verify_tick_min_spacing('T1','C1')") == 2
    # a policy row that bypassed the validation (superuser probe) still cannot go below one second
    await led.conn.execute("UPDATE change_ledger.sweep_policy SET params='{\"verify_min_tick_seconds\":0}'")
    assert await led.conn.fetchval("SELECT change_ledger.verify_tick_min_spacing('T1','C1')") == 1
    # the worker cannot lower it through the sweep parameters either: its value is overridden by the effective policy
    await led.conn.execute("DELETE FROM change_ledger.sweep_policy")
    await led.call("clt_wrk", "recover_sweep", '{"verify_min_tick_seconds":0}')
    assert await led.conn.fetchval("SELECT change_ledger.verify_tick_min_spacing('T1','C1')") == 5


async def test_e3_a_policy_of_one_second_lets_a_second_tick_count_after_one_second(led):
    await led.call("clt_dave", "set_sweep_policy", '{"verify_min_tick_seconds":1}')
    cid = await applied(led, request_id="e3d", base="base-1")
    await led.conn.execute("DELETE FROM change_ledger.sweep_policy")      # sweep() resets the row; re-set it below
    await led.call("clt_dave", "set_sweep_policy", '{"verify_min_tick_seconds":1}')
    got = await led.call("clt_wrk", "recover_sweep", json.dumps(FAST))
    assert json.loads(got)["VERIFY_DUE"] == [str(cid)]
    assert (await counter(led, cid, "VERIFY"))["attempts"] == 1
    # due again at once but inside the spacing: not counted
    await led.conn.execute("UPDATE change_ledger.sweep_counters SET next_attempt_at=now()-interval '1 second' "
                           "WHERE kind='VERIFY'")
    await led.call("clt_wrk", "recover_sweep", json.dumps(FAST))
    assert (await counter(led, cid, "VERIFY"))["attempts"] == 1
    await asyncio.sleep(1.2)
    await led.call("clt_wrk", "recover_sweep", json.dumps(FAST))
    assert (await counter(led, cid, "VERIFY"))["attempts"] == 2
