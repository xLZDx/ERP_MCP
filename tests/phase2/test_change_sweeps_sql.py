"""Focused PostgreSQL integration tests for db/phase2/006_change_sweeps.sql (recovery sweeps, anchor and
restart holds, T17 closure, REVOKE voiding, writer lease fence).

Contract: docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md revision 6. Needs ERP_PHASE2_TEST_DSN (superuser
DSN of a disposable cluster); without it: skip NOT_RUN, or fail when ERP_PHASE2_REQUIRE_PG=1. Each test has its own
throwaway database with all migrations applied. Sweep parameters are shrunk through the jsonb parameter of
recover_sweep(t,c,jsonb); superuser access only back-dates rows no API can age (expiry, deadlines, leases).
"""
import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_ledger_sql import BASE, BASES, C, DIGEST, KH, T, L, _setup  # noqa: F401

pytestmark = pytest.mark.integration

FAST = {"t12_interval_seconds": 0, "t12_jitter_seconds": 0, "verify_interval_seconds": 0}


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


CONTRACT_KEYS = {"claim_ttl_seconds", "permit_ttl_seconds", "t12_window_seconds", "t12_max_attempts",
                 "anchor_gap_window_seconds", "verify_max_attempts"}


async def sweep(led, **params):
    """008 (B5): contract constants are no longer worker parameters (NOT_ENTITLED). A test that shrinks one arranges
    the scope's policy row as superuser (the operator-set row, exactly what set_sweep_policy writes without its
    range floor); the remaining cadence keys stay parameters. Every call resets the row, so a call without
    contract keys runs with the ledger constants as before."""
    contract = {k: params.pop(k) for k in list(params) if k in CONTRACT_KEYS}
    if contract:
        await led.conn.execute(
            "INSERT INTO change_ledger.sweep_policy(tenant_id,company_id,params,updated_by) "
            "VALUES('T1','C1',$1::jsonb,'fixture') ON CONFLICT(tenant_id,company_id) DO UPDATE SET "
            "params=EXCLUDED.params", json.dumps(contract))
    else:
        await led.conn.execute("DELETE FROM change_ledger.sweep_policy WHERE tenant_id='T1' AND company_id='C1'")
    got = await led.call("clt_wrk", "recover_sweep", json.dumps(params))
    return json.loads(got) if isinstance(got, str) else got


async def events(led, cid, etype=None):
    return await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE ($1::uuid IS NULL OR change_id=$1) "
        "AND ($2::text IS NULL OR event_type=$2)", cid, etype)


async def counter(led, cid, kind):
    return await led.conn.fetchrow(
        "SELECT * FROM change_ledger.sweep_counters WHERE subject_id=$1 AND kind=$2", cid, kind)


async def failed_verify(led, **kw):
    cid, tok, _ = await led.dispatched(**kw)
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLIED"
    assert await led.verify(cid, False) == "FAILED_VERIFY"
    return cid


async def applied(led, **kw):
    cid, tok, _ = await led.dispatched(**kw)
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLIED"
    return cid


async def lock_busy_proof(led, cid, gen, code="LOCK_BUSY"):
    """The writer's signed class-a completion record of a pre-write LOCK_BUSY refusal (007: replaces the raw
    proof argument of complete_lock_busy)."""
    return await led.evidence(cid, "COMPLETION_PROOF",
                              {"class": "a", "result_returned": False, "stage": "PRE_WRITE", "refusal_code": code,
                               "no_effect_proof": {"proof": "platform lock busy before write"}},
                              role="clt_wri", gen=gen)


# ============================================================================ schema / privileges
async def test_006_objects_are_hardened_and_not_reachable_directly(led):
    c = led.conn
    for tbl in ("sweep_counters", "sweep_runs", "call_deadlines", "change_closures"):
        row = await c.fetchrow("SELECT c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner) o "
                               "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                               "WHERE n.nspname='change_ledger' AND c.relname=$1", tbl)
        assert tuple(row) == (True, True, "ledger_owner"), tbl
    bad = await c.fetch("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                        "WHERE n.nspname='change_ledger' AND NOT (p.prosecdef AND p.proconfig::text LIKE "
                        "'%search_path=pg_catalog%')")
    assert not bad
    cid = await led.propose()
    for role in ("clt_alice", "clt_bob", "clt_dave", "clt_wri", "clt_wrk", "clt_aud"):
        for stmt in ("INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind) "
                     "VALUES('T1','C1',gen_random_uuid(),'RESOLVE')",
                     "UPDATE change_ledger.call_deadlines SET deadline_seconds=1",
                     "DELETE FROM change_ledger.sweep_runs",
                     "UPDATE change_ledger.writer_leases SET lease_expires_at=now()",
                     f"SELECT change_ledger.triage_internal('T1','C1','{cid}','x')",
                     f"SELECT change_ledger.release_claim_internal('T1','C1','{cid}',true)",
                     "SELECT change_ledger.open_hold_internal('T1','C1',NULL,'ANCHOR_GAP','X','{}'::jsonb)"):
            with pytest.raises(Exception, match="permission denied"):
                await led.sql(role, stmt)
    # caller classes of the new operations
    deny = [("clt_alice", "recover_sweep", "'{}'::jsonb"), ("clt_wri", "recover_sweep", "'{}'::jsonb"),
            ("clt_alice", "operator_close_failed_verify", f"'{cid}','{cid}',true"),
            ("clt_wrk", "operator_close_failed_verify", f"'{cid}','{cid}',true"),
            ("clt_alice", "renew_writer_lease", f"'{cid}',1,10"), ("clt_wrk", "renew_writer_lease", f"'{cid}',1,10"),
            ("clt_wrk", "fence_check", f"'{cid}',1,'{cid}'"), ("clt_alice", "declare_unclean_restart", "NULL,'{}'::jsonb"),
            ("clt_alice", "declare_anchor_gap", "NULL,'{}'::jsonb"),
            ("clt_wri", "retry_verify", f"'{cid}','{cid}','{cid}','{cid}'"),                   # 007: evidence ids
            ("clt_alice", "retry_verify", f"'{cid}','{cid}','{cid}','{cid}'"),
            ("clt_alice", "complete_lock_busy", f"'{cid}',1,'{cid}','{{}}'::jsonb"),
            ("clt_wrk", "complete_lock_busy", f"'{cid}',1,'{cid}','{{}}'::jsonb")]            # writer only
    for role, fn, args in deny:
        await fails("permission denied", led.sql(role, f"SELECT change_ledger.{fn}('T1','C1',{args})"))


async def test_sweep_params_are_validated(led):
    for bad in ('{"nope":1}', '{"t12_max_attempts":-1}', '{"t12_max_attempts":"x"}', '[1]'):
        await fails("SCHEMA_INVALID", led.call("clt_wrk", "recover_sweep", bad))


# ============================================================================ T3
async def test_t3_expires_proposed_validated_and_approved_but_not_live_changes(led):
    prop = await led.propose(request_id="e1", base="base-1")
    val = await led.validated(request_id="e2", base="base-2")
    app = await led.approved(request_id="e3", base="base-3")
    live = await led.approved(request_id="e4", base="base-4")
    claimed = await led.approved(request_id="e5", base="base-5")
    await led.claimed(claimed, key="c" * 64)
    await led.conn.execute("UPDATE change_ledger.records SET created_at=now()-interval '2 hours', "
                           "expires_at=now()-interval '1 minute' WHERE change_id = ANY($1)", [prop, val, app])
    got = await sweep(led)
    assert sorted(got["T3"]) == sorted(str(x) for x in (prop, val, app))
    for cid in (prop, val, app):
        r = await led.rec(cid)
        assert (r["lifecycle"], r["authorization_state"], r["reservation_state"]) == ("EXPIRED_QUEUED", "EXPIRED", "NONE")
        assert await events(led, cid, "EXPIRED") == 1
    assert (await led.rec(live))["authorization_state"] == "APPROVED"
    assert (await led.rec(claimed))["authorization_state"] == "CLAIMED"
    await fails("APPROVAL_MISSING", led.claimed(app, key="d" * 64))
    await fails("FORBIDDEN_TRANSITION", led.call("clt_alice", "validate", prop))
    assert (await sweep(led))["T3"] == []                                   # idempotent
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True


# ============================================================================ T6r
async def test_t6r_releases_applying_without_permit_only_after_the_ttl(led):
    cid, tok, _ = await led.applying(request_id="r1", base="base-1")
    p, ptok, _, _ = await led.permitted(request_id="r2", base="base-2")
    assert (await sweep(led))["T6r"] == []                                  # default 60 s TTL not elapsed
    assert (await led.rec(cid))["execution_state"] == "APPLYING"
    got = await sweep(led, permit_ttl_seconds=0)
    assert got["T6r"] == [str(cid)]                                         # the PERMITTED one is not T6r
    r = await led.rec(cid)
    assert (r["authorization_state"], r["execution_state"], r["dispatch_state"]) == \
        ("APPROVED", "NOT_STARTED", "CANCELLED_UNDISPATCHED")
    assert await led.locks(cid) == (0, 0, 0)
    assert await led.conn.fetchval("SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1",
                                   tok["token_id"]) == "SUPERSEDED"
    assert await led.conn.fetchval("SELECT state FROM change_ledger.dispatch_permits WHERE change_id=$1",
                                   cid) == "CANCELLED_UNDISPATCHED"
    assert (await led.rec(p))["dispatch_state"] == "PERMITTED" and await led.locks(p) == (1, 1, 1)
    assert (await sweep(led, permit_ttl_seconds=0))["T6r"] == []            # idempotent
    # the released change can be claimed again (new generation)
    again = await led.claimed(cid, key="f" * 64)
    assert again["generation"] == 2


async def test_t6r_for_a_repair_hands_the_lock_back_to_the_parent(led):
    from test_change_ledger_sql import _failed_parent, _repair
    parent = await _failed_parent(led)
    rep = await _repair(led, parent)
    tok = await led.claimed(rep, key="5" * 64)
    await led.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s")
    assert await led.tl_owner(BASE, "doc1") == rep
    assert (await sweep(led, permit_ttl_seconds=0))["T6r"] == [str(rep)]
    assert await led.tl_owner(BASE, "doc1") == parent and await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert await led.locks(rep) == (0, 0, 0)


# ============================================================================ T9
async def test_t9_hard_deadline_makes_dispatched_apply_unknown_with_hold(led):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 5, 5, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    cid = await led.approved(request_id="d1", base="base-1")
    tok = await led.claimed(cid, grant=gid, amount=5)
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, tok["generation"])
    await led.call("clt_wri", "record_call", cid, tok["generation"], k)
    row = await led.conn.fetchrow("SELECT * FROM change_ledger.call_deadlines WHERE change_id=$1", cid)
    assert row["deadline_seconds"] == 120 and row["call_id"] == k          # CREATE_DRAFT: 120 s
    post = await led.conn.fetchval("SELECT change_ledger.call_deadline_seconds('POST')")
    assert post == 300
    other, _, _ = await led.dispatched(request_id="d2", base="base-2")
    assert (await sweep(led))["T9"] == []                                   # not past the deadline
    await led.conn.execute("UPDATE change_ledger.call_deadlines SET hard_deadline_at=now()-interval '1 second' "
                           "WHERE change_id=$1", cid)
    assert (await sweep(led))["T9"] == [str(cid)]
    r = await led.rec(cid)
    assert (r["execution_state"], r["call_ownership"], r["reservation_state"]) == \
        ("APPLY_UNKNOWN", "POSSIBLY_EXECUTING", "RESERVED")
    assert await led.locks(cid) == (1, 1, 1) and await led.res_state(cid) == "RESERVED"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.holds WHERE change_id=$1 AND "
                                   "cause='CALL_OWNERSHIP' AND released_at IS NULL", cid) == 1
    assert (await led.rec(other))["execution_state"] == "APPLYING"
    assert (await sweep(led))["T9"] == []                                   # idempotent, hold not duplicated
    assert await led.open_holds("CALL_OWNERSHIP") == 1
    # a late writer SUCCESS cannot turn the unknown outcome into APPLIED
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLY_UNKNOWN"
    assert (await led.rec(cid))["execution_state"] == "APPLY_UNKNOWN"


# ============================================================================ T12
async def test_t12_five_durable_attempts_then_triage_with_alert(led):
    cid, _, _ = await led.unknown(request_id="a1", base="base-1")
    assert (await sweep(led))["changed"] == 0                               # default 3 min interval: not due
    assert (await counter(led, cid, "RESOLVE"))["attempts"] == 0
    await led.conn.execute("UPDATE change_ledger.sweep_counters SET next_attempt_at=now()-interval '1 second'")
    for n in range(1, 5):
        got = await sweep(led, **FAST)
        assert got["T12_ATTEMPT"] == [str(cid)] and got["T12"] == []
        assert (await counter(led, cid, "RESOLVE"))["attempts"] == n
        assert (await led.rec(cid))["execution_state"] == "APPLY_UNKNOWN"
    got = await sweep(led, **FAST)
    assert got["T12"] == [str(cid)]
    r = await led.rec(cid)
    assert (r["execution_state"], r["call_ownership"], r["reservation_state"]) == \
        ("TRIAGE_REQUIRED", "POSSIBLY_EXECUTING", "RESERVED")   # 008: every claim reserves
    assert await led.open_holds("CALL_OWNERSHIP") == 1 and await led.locks(cid) == (1, 1, 1)
    ctr = await counter(led, cid, "RESOLVE")
    assert ctr["attempts"] == 5 and ctr["close_reason"] == "ATTEMPTS"
    alert = await led.conn.fetchval("SELECT payload FROM change_ledger.events WHERE change_id=$1 AND "
                                    "event_type='TRIAGE_REQUIRED'", cid)
    assert json.loads(alert) == {"reason": "ATTEMPTS", "alert": True}
    assert (await sweep(led, **FAST))["changed"] == 0                       # terminal for the sweep


async def test_t12_window_triages_before_five_attempts_and_jitter_is_bounded(led):
    cid, _, _ = await led.unknown(request_id="w1", base="base-1")
    got = await sweep(led, t12_interval_seconds=0, t12_jitter_seconds=0, t12_window_seconds=0)
    assert got["T12"] == [str(cid)]
    assert (await counter(led, cid, "RESOLVE"))["close_reason"] == "WINDOW"
    assert (await led.rec(cid))["execution_state"] == "TRIAGE_REQUIRED"
    # next_attempt_at honours interval + jitter
    c2, _, _ = await led.unknown(request_id="w2", base="base-2")
    await sweep(led, t12_interval_seconds=0, t12_jitter_seconds=0)
    await sweep(led, t12_interval_seconds=100, t12_jitter_seconds=20)       # row exists, due at once (interval 0 earlier)
    row = await counter(led, c2, "RESOLVE")
    gap = (row["next_attempt_at"] - row["last_attempt_at"]).total_seconds()
    assert row["attempts"] == 2 and 100 <= gap <= 120


async def test_resolved_unknown_leaves_the_sweep(led):
    cid, _, _ = await led.unknown(request_id="x1", base="base-1")
    await sweep(led, **FAST)
    # 007: signed OBSERVATION (effect absent) + signed class-a COMPLETION_PROOF instead of the raw observation json
    assert await led.resolve_unknown(cid, False, proof="a") == "FAILED_APPLY"
    assert (await sweep(led, **FAST))["changed"] == 0
    assert (await counter(led, cid, "RESOLVE"))["attempts"] == 1


# ============================================================================ verification bookkeeping
async def test_stuck_verification_counts_attempts_then_fails_verify_unknown_with_halt(led):
    cid = await applied(led, request_id="v1", base="base-1")
    assert (await sweep(led))["VERIFY_DUE"] == []
    await led.conn.execute("UPDATE change_ledger.sweep_counters SET next_attempt_at=now()-interval '1 second'")
    for n in (1, 2):
        got = await sweep(led, **FAST)
        assert got["VERIFY_DUE"] == [str(cid)]
        assert (await counter(led, cid, "VERIFY"))["attempts"] == n
    assert (await led.rec(cid))["verification_state"] == "NOT_VERIFIED"
    got = await sweep(led, **FAST)
    assert got["VERIFY_EXHAUSTED"] == [str(cid)]
    r = await led.rec(cid)
    assert (r["verification_state"], r["effect_known"], r["execution_state"], r["reservation_state"]) == \
        ("FAILED_VERIFY", "UNKNOWN", "APPLIED", "CONSUMED")
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1 and await led.locks(cid) == (1, 0, 0)
    assert (await sweep(led, **FAST))["changed"] == 0
    # an unknown-effect failure cannot be repaired by UNPOST (needs effect_known = YES)
    from test_change_ledger_sql import _repair
    rep = await _repair(led, cid)
    await fails("PARENT_NOT_VERIFIED", led.claimed(rep, key="5" * 64))


async def test_verify_inconclusive_is_bounded_and_worker_only(led):
    cid = await applied(led, request_id="v2", base="base-1")
    # 007: the evidence is a signed OBSERVATION record that says inconclusive (no raw json argument)
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wrk", "verify_inconclusive", cid, None))
    plain = await led.observation(cid, True)                                   # an observation that is not inconclusive
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wrk", "verify_inconclusive", cid, plain))
    assert (await counter(led, cid, "VERIFY")) is None                          # nothing was counted
    for n in (1, 2):
        obs = await led.observation(cid, None, inconclusive=True, reader="down")
        got = await led.call("clt_wrk", "verify_inconclusive", cid, obs)
        assert json.loads(got) == {"attempts": n, "exhausted": False}
    obs = await led.observation(cid, None, inconclusive=True, reader="down")
    got = json.loads(await led.call("clt_wrk", "verify_inconclusive", cid, obs))
    assert got == {"attempts": 3, "exhausted": True}
    assert (await led.rec(cid))["verification_state"] == "FAILED_VERIFY"
    obs = await led.observation(cid, None, inconclusive=True, reader="down")
    await fails("FORBIDDEN_TRANSITION", led.call("clt_wrk", "verify_inconclusive", cid, obs))
    await fails("permission denied", led.call("clt_alice", "verify_inconclusive", cid, obs))


async def test_t17_retry_verify_is_bounded_by_three_and_a_pass_releases_the_halt(led):
    cid = await failed_verify(led, request_id="t17a", base="base-1")
    # 007: retry_verify takes the ids of signed FIELD / MOVEMENT / VERSION records; the verdict is derived from them
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wrk", "retry_verify", cid, None, None, None))
    assert (await counter(led, cid, "VERIFY_RETRY")) is None                    # a refused call is not counted
    assert await led.verify(cid, False, fn="retry_verify") == "FAILED_VERIFY"
    assert await led.verify(cid, False, fn="retry_verify") == "FAILED_VERIFY"
    assert await led.verify(cid, False, fn="retry_verify") == "FAILED_VERIFY"
    await fails("VERIFY_FAILED", led.verify(cid, True, fn="retry_verify"))      # the 4th attempt is refused
    assert (await counter(led, cid, "VERIFY_RETRY"))["attempts"] == 3
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1
    ok = await failed_verify(led, request_id="t17b", base="base-2")
    assert await led.verify(ok, True, fn="retry_verify") == "VERIFIED"
    r = await led.rec(ok)
    assert r["verification_state"] == "VERIFIED" and await led.locks(ok) == (0, 0, 0)
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.holds WHERE change_id=$1 AND "
                                   "released_at IS NOT NULL", ok) == 1
    await fails("FORBIDDEN_TRANSITION", led.verify(ok, True, fn="retry_verify"))


# ============================================================================ T8 LOCK_BUSY
async def test_lock_busy_retries_five_times_with_a_gate_then_takes_the_definite_path(led):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 9, 9, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    cid = await led.approved(request_id="lb", base="base-1")
    fast = json.dumps({"lock_busy_interval_seconds": 0, "lock_busy_jitter_seconds": 0})
    slow = json.dumps({"lock_busy_interval_seconds": 3600, "lock_busy_jitter_seconds": 0})
    for n in range(1, 6):
        tok = await led.claimed(cid, grant=gid, amount=5)
        await led.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s")
        if n == 1:
            # 007: the no-effect proof is part of the signed completion record; no record = no refusal
            await fails("WRITE_REFUSED", led.call("clt_wri", "complete_lock_busy", cid, tok["generation"],
                                                  None, fast))
            # a signed refusal with another code is not a LOCK_BUSY refusal
            wrong = await lock_busy_proof(led, cid, tok["generation"], code="STALE_VERSION")
            await fails("WRITE_REFUSED", led.call("clt_wri", "complete_lock_busy", cid, tok["generation"],
                                                  wrong, fast))
            assert await counter(led, cid, "LOCK_BUSY") is None
        proof = await lock_busy_proof(led, cid, tok["generation"])
        assert await led.call("clt_wri", "complete_lock_busy", cid, tok["generation"], proof, fast) \
            == "APPROVED"
        r = await led.rec(cid)
        assert (r["authorization_state"], r["execution_state"], r["reservation_state"]) == \
            ("APPROVED", "NOT_STARTED", "RELEASED")
        assert await led.locks(cid) == (0, 0, 0)
        assert (await counter(led, cid, "LOCK_BUSY"))["attempts"] == n
        assert await events(led, cid, "LOCK_BUSY_RETRY") == n
    # the 6th busy refusal is definite
    tok = await led.claimed(cid, grant=gid, amount=5)
    await led.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s")
    proof = await lock_busy_proof(led, cid, tok["generation"])
    assert await led.call("clt_wri", "complete_lock_busy", cid, tok["generation"], proof, fast) == "FAILED_APPLY"
    assert await led.locks(cid) == (0, 0, 0) and (await led.rec(cid))["execution_state"] == "FAILED_APPLY"
    assert (await counter(led, cid, "LOCK_BUSY"))["close_reason"] == "DEFINITE"
    # the interval gate: a claim before next_attempt_at is refused, after it is allowed
    c2 = await led.approved(request_id="lb2", base="base-2")
    t2 = await led.claimed(c2, key="e" * 64)
    await led.call("clt_alice", "begin_apply", t2["token_id"], uuid.uuid4(), "h", "s")
    proof = await lock_busy_proof(led, c2, t2["generation"])
    assert await led.call("clt_wri", "complete_lock_busy", c2, t2["generation"], proof, slow) == "APPROVED"
    await fails("LOCK_BUSY", led.claimed(c2, key="e" * 64))
    assert (await led.rec(c2))["authorization_state"] == "APPROVED"
    await led.conn.execute("UPDATE change_ledger.sweep_counters SET next_attempt_at=now()-interval '1 second' "
                           "WHERE subject_id=$1", c2)
    await led.claimed(c2, key="e" * 64)
    # window: attempts inside a closed window go definite
    c3 = await led.approved(request_id="lb3", base="base-3")
    t3 = await led.claimed(c3, key="d" * 64)
    await led.call("clt_alice", "begin_apply", t3["token_id"], uuid.uuid4(), "h", "s")
    zero = json.dumps({"lock_busy_window_seconds": 0})
    proof = await lock_busy_proof(led, c3, t3["generation"])
    assert await led.call("clt_wri", "complete_lock_busy", c3, t3["generation"], proof, zero) == "FAILED_APPLY"


# ============================================================================ ANCHOR_GAP
async def test_anchor_gap_release_needs_a_real_readback_checkpoint_after_the_hold_and_a_good_chain(led):
    assert await led.call("clt_wrk", "declare_anchor_gap", None, '{"why":"sink down"}') == len(BASES)
    assert await led.open_holds("ANCHOR_GAP") == len(BASES)
    assert await led.call("clt_wrk", "declare_anchor_gap", None, '{}') == 0                # idempotent
    await fails("TARGET_REJECTED", led.call("clt_wrk", "declare_anchor_gap", "nope", '{}'))
    fresh = await led.approved(request_id="g1", base="base-1")
    await fails("BASE_HOLD", led.claimed(fresh))
    hold = await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE base_fingerprint='base-1'")
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "release_hold", hold, None))
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_dave", "release_hold", hold, '{"x":1}'))
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}'))
    # a TEST sink and a non-confirmed checkpoint never count; an older checkpoint (before the hold) neither
    await led.checkpoint(kind="TEST")
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}'))
    await led.checkpoint()
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_dave", "release_hold", hold, '{"store_accepted":"yes"}'))
    ts = await led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}')
    assert ts is not None and await led.open_holds("ANCHOR_GAP") == len(BASES) - 1
    await led.claimed(fresh)                                                                # base-1 usable again
    # a broken chain refuses the release even with a checkpoint
    other = await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE base_fingerprint='base-2'")
    await led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    await led.conn.execute("UPDATE change_ledger.events SET payload='{\"forged\":1}'::jsonb WHERE seq=2")
    await led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
    await fails("AUDIT_UNAVAILABLE", led.call("clt_dave", "release_hold", other, '{"store_accepted":true}'))


async def test_anchor_gap_bound_triages_unresolved_items_but_keeps_the_hold(led):
    unk, _, _ = await led.unknown(request_id="b1", base="base-1")
    other, _, _ = await led.unknown(request_id="b2", base="base-2")
    await led.call("clt_wrk", "declare_anchor_gap", "base-1", '{}')
    assert (await sweep(led))["ANCHOR_GAP_TRIAGE"] == []                                    # inside 15 minutes
    got = await sweep(led, anchor_gap_window_seconds=0)
    assert got["ANCHOR_GAP_TRIAGE"] == [str(unk)]
    assert (await led.rec(unk))["execution_state"] == "TRIAGE_REQUIRED"
    assert (await led.rec(other))["execution_state"] == "APPLY_UNKNOWN"                     # other base untouched
    assert await led.open_holds("ANCHOR_GAP") == 1 and await led.open_holds("CALL_OWNERSHIP") == 2
    assert await events(led, None, "ANCHOR_GAP_BOUND_EXCEEDED") == 1
    again = await sweep(led, anchor_gap_window_seconds=0)
    assert again["changed"] == 0 and await events(led, None, "ANCHOR_GAP_BOUND_EXCEEDED") == 1


async def test_release_hold_never_releases_call_ownership_or_a_failed_verify_halt(led):
    cid = await failed_verify(led, request_id="h1", base="base-1")
    hold = await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE change_id=$1", cid)
    await fails("FORBIDDEN_TRANSITION", led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}'))
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1


# ============================================================================ RLC_UNCLEAN
async def test_unclean_restart_hold_blocks_and_is_released_only_by_the_resume_procedure(led):
    app = await led.approved(request_id="u1", base="base-1")
    assert await led.call("clt_wrk", "declare_unclean_restart", "base-1", '{"pid":7}') == 1
    assert await led.call("clt_wrk", "declare_unclean_restart", "base-1", '{}') == 0
    assert await led.open_holds("RLC_UNCLEAN") == 1
    await fails("BASE_HOLD", led.claimed(app))
    hold = await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE cause='RLC_UNCLEAN'")
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}'))
    ev = '{"resume_procedure":"S13_RESUME","completed":true}'
    await fails("BASE_HOLD", led.call("clt_dave", "release_hold", hold, ev))             # no sweep since the hold
    await sweep(led)
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "release_hold", hold,
                                                     '{"resume_procedure":"S13_RESUME","completed":false}'))
    assert await led.call("clt_dave", "release_hold", hold, ev) is not None
    assert await led.open_holds("RLC_UNCLEAN") == 0
    await led.claimed(app)
    await fails("permission denied", led.call("clt_alice", "release_hold", hold, ev))


async def test_unclean_release_refused_while_a_change_is_applying(led):
    await led.applying(request_id="u2", base="base-1")
    await led.call("clt_wrk", "declare_unclean_restart", "base-1", '{}')
    await sweep(led)
    hold = await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE cause='RLC_UNCLEAN'")
    await fails("BASE_HOLD", led.call("clt_dave", "release_hold", hold,
                                      '{"resume_procedure":"S13_RESUME","completed":true}'))
    await sweep(led, permit_ttl_seconds=0)                                                 # T6r settles it
    assert await led.call("clt_dave", "release_hold", hold,
                          '{"resume_procedure":"S13_RESUME","completed":true}') is not None


# ============================================================================ T17 operator closure
async def test_t17_operator_closure_needs_two_persons_and_completion_proof(led):
    cid = await failed_verify(led, request_id="c1", base="base-1")
    await led.conn.execute("UPDATE change_ledger.records SET effect_known='UNKNOWN' WHERE change_id=$1", cid)
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "operator_close_failed_verify", cid, uuid.uuid4(), True))
    # 007: the raw witness_cosign is revoked and a signed completion proof must carry class a or b, so a "weak"
    # cosign can no longer be created through the API: refuse it at the source ...
    await fails("permission denied", led.call("clt_erin", "witness_cosign", cid, '{"class":"a"}'))
    await fails("SCHEMA_INVALID", led.evidence(cid, "COMPLETION_PROOF", {"class": "x", "result_returned": False},
                                               role="clt_wri"))
    # ... and keep the guard of operator_close_failed_verify itself: a stored cosign whose proof lost its class
    weak = await led.cosign("clt_erin", cid, cls="a")
    await led.conn.execute("UPDATE change_ledger.witness_cosigns SET completion_proof='{\"note\":\"looks fine\"}'::jsonb "
                           "WHERE cosign_id=$1", weak)
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "operator_close_failed_verify", cid, weak, True))
    own = await led.cosign("clt_dave", cid, cls="a")
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_dave", "operator_close_failed_verify", cid, own, True))
    good = await led.cosign("clt_erin", cid, cls="b")
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_erin", "operator_close_failed_verify", cid, good, True))
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1 and await led.locks(cid) == (1, 0, 0)
    assert await led.call("clt_dave", "operator_close_failed_verify", cid, good, True) == "CLOSED"
    r = await led.rec(cid)
    assert (r["verification_state"], r["effect_known"], r["reservation_state"]) == ("FAILED_VERIFY", "YES", "CONSUMED")
    assert await led.open_holds("FAILED_VERIFY_HALT") == 0 and await led.locks(cid) == (0, 0, 0)
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.change_closures WHERE change_id=$1 AND "
                                   "witness='clt_erin' AND closed_by='clt_dave'", cid) == 1
    assert await led.conn.fetchval("SELECT consumed_at IS NOT NULL FROM change_ledger.witness_cosigns "
                                   "WHERE cosign_id=$1", good)
    await fails("FORBIDDEN_TRANSITION", led.call("clt_dave", "operator_close_failed_verify", cid, good, True))
    await fails("FORBIDDEN_TRANSITION", led.verify(cid, True, fn="retry_verify"))
    # the base is usable again
    await led.claimed(await led.approved(request_id="c1b", base="base-1", target="doc2"), key="8" * 64)


async def test_t17_refund_needs_effect_not_yes_and_requester_cannot_close_own_change(led):
    cid = await failed_verify(led, request_id="c2", base="base-1")             # effect_known = YES
    w = await led.cosign("clt_erin", cid, cls="a")
    await fails("FORBIDDEN_TRANSITION", led.call("clt_dave", "operator_close_failed_verify", cid, w, False))
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 9, 9, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    c2 = await led.approved(request_id="c3", base="base-2", requester="clt_dave")
    t2 = await led.claimed(c2, requester="clt_dave", key="a" * 64, grant=gid, amount=5)
    k = uuid.uuid4()
    await led.call("clt_dave", "begin_apply", t2["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", c2, t2["generation"])
    await led.call("clt_wri", "record_call", c2, t2["generation"], k)
    assert await led.complete(c2, t2["generation"], "SUCCESS") == "APPLIED"
    assert await led.verify(c2, False) == "FAILED_VERIFY"
    await led.conn.execute("UPDATE change_ledger.records SET effect_known='NO' WHERE change_id=$1", c2)
    own = await led.cosign("clt_erin", c2, cls="a")
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_dave", "operator_close_failed_verify", c2, own, False))
    await led.conn.execute("GRANT operator_role TO clt_carol")
    await led.conn.execute("SELECT change_ledger.add_role_scope('clt_carol',$1,$2)", T, C)
    await led.conn.execute("UPDATE change_ledger.principals SET capabilities=ARRAY['approver','operator',"
                           "'recovery_witness'] WHERE principal='clt_carol'")      # 008: registered operator witness
    ok = await led.cosign("clt_carol", c2, cls="a")
    assert await led.call("clt_erin", "operator_close_failed_verify", c2, ok, False) == "CLOSED"
    r = await led.rec(c2)
    assert (r["effect_known"], r["reservation_state"]) == ("NO", "RELEASED")
    assert await led.res_state(c2) == "RELEASED"


async def test_t17_closure_refused_while_a_repair_owns_the_target_lock(led):
    from test_change_ledger_sql import _failed_parent, _repair
    parent = await _failed_parent(led)
    rep = await _repair(led, parent)
    await led.claimed(rep, key="5" * 64)
    w = await led.cosign("clt_erin", parent, cls="a")
    await fails("LOCK_BUSY", led.call("clt_dave", "operator_close_failed_verify", parent, w, True))
    assert await led.tl_owner(BASE, "doc1") == rep and await led.open_holds("FAILED_VERIFY_HALT") == 1


# ============================================================================ REVOKE
async def test_revoke_voids_unclaimed_approvals_and_released_claims_and_reenable_sweeps_first(led):
    app = await led.approved(request_id="rv1", base="base-1")
    claimed = await led.approved(request_id="rv2", base="base-2")
    tok = await led.claimed(claimed, key="c" * 64)
    validated = await led.validated(request_id="rv3", base="base-3")
    expired = await led.approved(request_id="rv4", base="base-4")
    await led.conn.execute("UPDATE change_ledger.records SET created_at=now()-interval '2 hours', "
                           "expires_at=now()-interval '1 minute' WHERE change_id=$1", expired)
    flying, _, _, _ = await led.permitted(request_id="rv5", base="base-5")
    # 008 B6c: a STOP_* sweep now unwinds claims and permits at once, so the "only REVOKE voids" check with a live
    # claim moved to test_b6c_a_stop_sweep_releases_but_never_voids (b3 file); this test goes straight to REVOKE
    await led.call("clt_dave", "kill_switch", "REVOKE")
    got = await sweep(led)
    assert got["VOIDED"] == [str(app)] and got["T5x"] == [str(claimed)]
    for cid in (app, claimed):
        r = await led.rec(cid)
        assert (r["authorization_state"], r["execution_state"]) == ("VOIDED", "NOT_STARTED")
    assert await events(led, app, "APPROVAL_VOIDED") == 1
    assert await events(led, claimed, "CLAIM_RELEASED") == 1
    assert await led.locks(claimed) == (0, 0, 0)
    assert await led.conn.fetchval("SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1",
                                   tok["token_id"]) == "SUPERSEDED"
    assert (await led.rec(validated))["authorization_state"] == "NONE"
    assert (await led.rec(expired))["authorization_state"] == "EXPIRED"      # T3 wins over voiding
    # 008 B6c: a stop mode cancels the undispatched permit at once (approval back to APPROVED); the next sweep voids it
    r = await led.rec(flying)
    assert (r["dispatch_state"], r["authorization_state"]) == ("CANCELLED_UNDISPATCHED", "APPROVED")
    assert (await sweep(led))["VOIDED"] == [str(flying)]
    assert (await sweep(led))["VOIDED"] == []                                # idempotent
    # re-enable runs the sweep first: a claim made stale meanwhile is settled before the switch is off
    runs = await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs")
    await led.call("clt_dave", "kill_switch", "OFF")
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs") == runs + 1
    await led.call("clt_dave", "kill_switch", "OFF")                          # already OFF: no sweep
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs") == runs + 1
    await fails("APPROVAL_VOIDED", led.claimed(app))                          # a new approval is needed
    nonce = await led.call("clt_bob", "issue_approval_nonce", app)
    await led.call("clt_bob", "approve", app, nonce, await led.approval_digest(app))     # 007: SQL-computed digest
    await led.claimed(app)


async def test_reenable_from_revoke_voids_even_without_an_explicit_sweep(led):
    app = await led.approved(request_id="rv6", base="base-1")
    await led.call("clt_dave", "kill_switch", "REVOKE")
    await led.call("clt_dave", "kill_switch", "OFF")
    assert (await led.rec(app))["authorization_state"] == "VOIDED"
    assert await led.conn.fetchval("SELECT mode FROM change_ledger.kill_switch_state") == "OFF"
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True


# ============================================================================ lease + fence
async def test_lease_renewal_and_fence_before_each_call(led):
    cid, tok, call_id = await led.applying(request_id="l1", base="base-1")
    gen = tok["generation"]
    await fails("PERMIT_MISSING", led.call("clt_wri", "renew_writer_lease", cid, gen, 60))   # no call in flight yet
    await fails("PERMIT_MISSING", led.call("clt_wri", "fence_check", cid, gen, call_id))
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, gen)
    fence = json.loads(await led.call("clt_wri", "fence_check", cid, gen, call_id))
    assert fence["ok"] is True and fence["permit_state"] == "PERMITTED"
    await fails("PERMIT_MISSING", led.call("clt_wri", "fence_check", cid, gen, uuid.uuid4()))
    await fails("TICKET_SUPERSEDED", led.call("clt_wri", "fence_check", cid, gen + 1, call_id))
    await fails("SCHEMA_INVALID", led.call("clt_wri", "renew_writer_lease", cid, gen, 0))
    first = await led.call("clt_wri", "renew_writer_lease", cid, gen, 60)
    assert first > datetime.now(UTC) and first < datetime.now(UTC) + timedelta(seconds=61)
    assert await led.call("clt_wri", "record_call", cid, gen, call_id) is True
    second = await led.call("clt_wri", "renew_writer_lease", cid, gen, 600)    # while DISPATCHED
    assert second > first
    row = await led.conn.fetchrow("SELECT * FROM change_ledger.writer_leases WHERE owner_change_id=$1", cid)
    assert row["renew_count"] == 2 and row["lease_expires_at"] == second
    assert await events(led, cid, "LEASE_RENEWED") == 2
    assert json.loads(await led.call("clt_wri", "fence_check", cid, gen, call_id))["permit_state"] == "DISPATCHED"
    # lapsed lease: lost for good
    await led.conn.execute("UPDATE change_ledger.writer_leases SET lease_expires_at=now()-interval '1 second' "
                           "WHERE owner_change_id=$1", cid)
    await fails("TICKET_SUPERSEDED", led.call("clt_wri", "renew_writer_lease", cid, gen, 60))
    await fails("TICKET_SUPERSEDED", led.call("clt_wri", "fence_check", cid, gen, call_id))
    # outside APPLYING nothing renews
    await led.complete(cid, gen, "SUCCESS")
    await fails("FORBIDDEN_TRANSITION", led.call("clt_wri", "renew_writer_lease", cid, gen, 60))


async def test_dispatch_cas_is_fenced_by_lease_and_holds(led):
    lapsed, ltok, lcall, _ = await led.permitted(request_id="f1", base="base-1")
    await led.conn.execute("UPDATE change_ledger.writer_leases SET lease_expires_at=now()-interval '1 second' "
                           "WHERE owner_change_id=$1", lapsed)
    await fails("TICKET_SUPERSEDED", led.call("clt_wri", "record_call", lapsed, ltok["generation"], lcall))
    assert (await led.rec(lapsed))["dispatch_state"] == "PERMITTED"            # CAS did not happen
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.call_deadlines WHERE change_id=$1",
                                   lapsed) == 0
    held, htok, hcall, _ = await led.permitted(request_id="f2", base="base-2")
    await led.call("clt_wrk", "declare_unclean_restart", "base-2", '{}')
    await fails("BASE_HOLD", led.call("clt_wri", "record_call", held, htok["generation"], hcall))
    await fails("BASE_HOLD", led.call("clt_wri", "fence_check", held, htok["generation"], hcall))
    assert (await led.rec(held))["dispatch_state"] == "PERMITTED"
    # the cancel path is not fenced: the sweep can still cancel the held permit once it expires
    await led.conn.execute("UPDATE change_ledger.dispatch_permits SET expires_at=now()-interval '1 second' "
                           "WHERE change_id=$1", held)
    assert (await sweep(led))["T6c"] == [str(held)]


# ============================================================================ concurrency / chain
async def test_concurrent_sweeps_apply_each_transition_once_and_chain_stays_valid(led):
    ids = []
    for i in range(4):
        cid = await led.approved(request_id=f"cs{i}", base=f"base-{i + 1}")
        ids.append(cid)
    await led.conn.execute("UPDATE change_ledger.records SET created_at=now()-interval '2 hours', "
                           "expires_at=now()-interval '1 minute' WHERE change_id = ANY($1)", ids)
    conns = [await led.db.connect() for _ in range(3)]
    try:
        res = await asyncio.gather(*[led.call("clt_wrk", "recover_sweep", "{}", conn=cn) for cn in conns])
    finally:
        for cn in conns:
            await cn.close()
    assert sum(json.loads(r)["changed"] for r in res) == 4
    for cid in ids:
        assert await events(led, cid, "EXPIRED") == 1
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True
