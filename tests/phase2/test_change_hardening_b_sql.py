"""Focused PostgreSQL tests for db/phase2/008_change_hardening_b.sql, round 1: findings B1, B2, B3 of
docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md (batch B). Later rounds append B4-B6 tests to this file.

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied and the actors
(registered principals, default grant) of test_change_ledger_sql._setup. Superuser access arranges state no API can
produce (a deleted stored declaration, a registry row of legacy mode, a changed grant currency) and reads results.
"""
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_ledger_sql import BASE, C, C2, DEFAULT_GRANT, DIGEST, ORG, T, T2, L, _setup, exp, sha

pytestmark = pytest.mark.integration

RUNTIME = ["requester_role", "approver_role", "operator_role", "writer_role", "worker_role", "auditor_role",
           "checkpoint_role"]


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


async def _role(conn, name):
    """Roles are cluster-wide: create idempotently."""
    await conn.execute(f"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{name}') THEN "
                       f"CREATE ROLE {name} NOLOGIN; END IF; END $$")


async def grant(led, amount=1000, cu=50, post=50, gid=None, t=T, c=C, currency="EUR"):
    gid = gid or uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, currency, amount, cu, post,
                   datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC) + timedelta(hours=1), t=t, c=c)
    return gid


async def stored(led, cid):
    return await led.conn.fetchrow("SELECT * FROM change_ledger.change_budget WHERE change_id=$1", cid)


# ============================================================================ B1
async def test_b1_claim_refuses_a_null_grant_a_foreign_grant_and_a_changed_amount_and_leaves_nothing(led):
    other = await grant(led, 1000)
    cid = await led.approved(amount=40)
    cb = await stored(led, cid)
    assert (cb["grant_id"], cb["amount"]) == (DEFAULT_GRANT[(T, C)], 40)
    kw = dict(requester="clt_alice")
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "claim", cid, None, None, 40, False, False))
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "claim", cid, None, other, 40, False, False))
    await fails("DIGEST_MISMATCH", led.call("clt_alice", "claim", cid, None, cb["grant_id"], 1, False, False))
    await fails("DIGEST_MISMATCH", led.call("clt_alice", "claim", cid, None, cb["grant_id"], None, False, False))
    await fails("DIGEST_MISMATCH", led.call("clt_alice", "claim", cid, None, cb["grant_id"], 40, True, False))
    await fails("DIGEST_MISMATCH", led.call("clt_alice", "claim", cid, "f" * 64, cb["grant_id"], 40, False, False))
    assert await led.locks(cid) == (0, 0, 0) and await led.res_state(cid) is None
    r = await led.rec(cid)
    assert (r["authorization_state"], r["reservation_state"], r["claim_generation"]) == ("APPROVED", "NONE", 0)
    # the stored values claim: the reservation carries exactly the declared amount, counts and grant
    tok = await led.claimed(cid, **kw)
    assert tok["generation"] == 1
    row = await led.conn.fetchrow("SELECT * FROM change_ledger.reservations WHERE change_id=$1", cid)
    assert (row["grant_id"], row["amount"], row["state"]) == (cb["grant_id"], 40, "RESERVED")


async def test_b1_claim_is_refused_without_a_stored_declaration_and_without_a_reservation_row(led):
    cid = await led.approved(request_id="nobudget")
    await led.conn.execute("DELETE FROM change_ledger.change_budget WHERE change_id=$1", cid)   # arranged tampering
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "claim", cid, None, DEFAULT_GRANT[(T, C)], 0, False, False))
    assert await led.locks(cid) == (0, 0, 0) and await led.res_state(cid) is None
    assert (await led.rec(cid))["reservation_state"] == "NONE"
    # a change that never declared a budget cannot even be validated
    bare = await led.propose(request_id="bare", base="base-2", budget=False)
    await fails("SCHEMA_INVALID", led.call("clt_alice", "validate", bare))        # draft: key missing first
    await led.call("clt_alice", "declare_business_key", bare, sha("bare"), None, None)
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "validate", bare))
    assert (await led.rec(bare))["lifecycle"] == "PROPOSED"


async def test_b1_validate_derives_the_budget_precheck_and_has_no_caller_flags(led):
    c = led.conn
    sigs = await c.fetch("SELECT pg_get_function_identity_arguments(p.oid) a FROM pg_proc p JOIN pg_namespace n "
                         "ON n.oid=p.pronamespace WHERE n.nspname='change_ledger' AND p.proname='validate'")
    assert [s["a"] for s in sigs] == ["t text, c text, p_change_id uuid"]
    small = await grant(led, 10)
    over = await led.propose(request_id="over", grant=small, amount=11)
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "validate", over))
    assert (await led.rec(over))["lifecycle"] == "PROPOSED"
    fits = await led.propose(request_id="fits", grant=small, amount=10, base="base-2")
    assert await led.call("clt_alice", "validate", fits) == "VALIDATED"
    # the pre-check sees what other changes already reserved against the grant
    await led.conn.execute("UPDATE change_ledger.grants SET status='REVOKED' WHERE grant_id=$1", small)
    again = await led.propose(request_id="again", grant=DEFAULT_GRANT[(T, C)], base="base-3")
    await led.conn.execute("UPDATE change_ledger.change_budget SET grant_id=$2 WHERE change_id=$1", again, small)
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "validate", again))
    # a caller can no longer pass the flags: the 5-argument form does not exist
    with pytest.raises(asyncpg.UndefinedFunctionError):
        await c.fetchval("SELECT change_ledger.validate('T1','C1',$1,false,true)", again)


async def test_b1_currency_is_checked_at_declaration_and_at_claim(led):
    usd = await grant(led, 1000, currency="USD")
    cid = await led.propose(request_id="cur")
    await fails("CURRENCY_NOT_BUDGETED", led.call("clt_alice", "declare_budget", cid, usd, "EUR", 1, False, False))
    await fails("CURRENCY_NOT_BUDGETED", led.call("clt_alice", "declare_budget", cid, usd, "GBP", 1, False, False))
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "declare_budget", cid, uuid.uuid4(), "EUR", 1, False, False))
    await fails("SCHEMA_INVALID", led.call("clt_alice", "declare_budget", cid, usd, "EUR", -1, False, False))
    ok = await led.approved(request_id="cur2", base="base-2")
    await led.conn.execute("UPDATE change_ledger.grants SET currency='USD' WHERE grant_id=$1",
                           DEFAULT_GRANT[(T, C)])                     # the grant was re-denominated after approval
    await fails("CURRENCY_NOT_BUDGETED", led.claimed(ok))
    assert await led.locks(ok) == (0, 0, 0) and await led.res_state(ok) is None
    await fails("NOT_ENTITLED", led.call("clt_mallory", "declare_budget", ok, usd, "USD", 1, False, False))


async def test_b1_the_declared_budget_is_inside_the_approval_digest_and_frozen_after_approval(led):
    cid = await led.validated(request_id="dg")
    n0 = await led.call("clt_bob", "issue_approval_nonce", cid)       # 009: the text is stored per issued nonce
    d0 = await led.approval_digest(cid)
    assert await led.call("clt_alice", "declare_budget", cid, DEFAULT_GRANT[(T, C)], "EUR", 5, False, False) == "PROPOSED"
    assert (await led.rec(cid))["lifecycle"] == "PROPOSED"            # the earlier validation no longer stands
    await led.call("clt_alice", "validate", cid)
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)    # a new preview needs a new nonce and text
    d1 = await led.approval_digest(cid)
    assert d1 != d0
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", cid, nonce, d0))
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", cid, n0, d0))     # stale preview of the old budget
    await led.call("clt_bob", "approve", cid, nonce, d1)
    await fails("FORBIDDEN_TRANSITION", led.call("clt_alice", "declare_budget", cid, DEFAULT_GRANT[(T, C)], "EUR", 1,
                                                  False, False))
    assert (await stored(led, cid))["amount"] == 5


async def test_b1_a_create_draft_without_a_business_key_cannot_validate_or_claim(led):
    bare = await led.propose(request_id="nokey", budget=False)
    await led.call("clt_alice", "declare_budget", bare, DEFAULT_GRANT[(T, C)], "EUR", 0, False, False)
    await fails("SCHEMA_INVALID", led.call("clt_alice", "validate", bare))
    assert (await led.rec(bare))["lifecycle"] == "PROPOSED"
    # even an approved draft whose key row is gone (arranged) cannot take its locks
    cid = await led.approved(request_id="keygone", base="base-2")
    await led.conn.execute("DELETE FROM change_ledger.business_keys WHERE change_id=$1", cid)
    await fails("SCHEMA_INVALID", led.claimed(cid))
    assert await led.locks(cid) == (0, 0, 0) and await led.res_state(cid) is None
    # a key row that exists is the one claim locks, whatever the caller passes
    good = await led.approved(request_id="keyok", base="base-3", key="c" * 64)
    await fails("DIGEST_MISMATCH", led.call("clt_alice", "claim", good, "d" * 64, DEFAULT_GRANT[(T, C)], 0, False, False))
    await led.claimed(good)
    assert await led.conn.fetchval("SELECT key_hash FROM change_ledger.key_locks WHERE owner_change_id=$1", good) == "c" * 64


async def test_b1_claim_on_a_finished_or_running_change_is_a_forbidden_transition(led):
    # APPLYING
    cid, tok, _ = await led.applying(request_id="run")
    await fails("FORBIDDEN_TRANSITION", led.claimed(cid))
    assert (await led.rec(cid))["claim_generation"] == tok["generation"]
    # FAILED_APPLY
    f, ftok, _ = await led.applying(request_id="fail", base="base-2")
    assert await led.complete(f, ftok["generation"], "PRE_WRITE_REFUSAL", proof={"no_effect": "nothing written"}) == "FAILED_APPLY"
    await fails("FORBIDDEN_TRANSITION", led.claimed(f))
    # VERIFIED
    v, vtok, _ = await led.dispatched(request_id="ver", base="base-3")
    assert await led.complete(v, vtok["generation"], "SUCCESS") == "APPLIED"
    assert await led.verify(v, True) == "VERIFIED"
    await fails("FORBIDDEN_TRANSITION", led.claimed(v))
    # a change whose dispatch is recorded cannot be claimed again either (authorization arranged back to APPROVED)
    d, dtok, _ = await led.dispatched(request_id="disp", base="base-4")
    await led.conn.execute("UPDATE change_ledger.records SET authorization_state='APPROVED', execution_state='NOT_STARTED' "
                           "WHERE change_id=$1", d)
    await fails("FORBIDDEN_TRANSITION", led.claimed(d))
    for x in (cid, f, v, d):
        assert (await led.rec(x))["claim_generation"] >= 1


async def test_b1_record_reservation_state_equals_the_reservation_row_on_every_path(led):
    cid = await led.approved(request_id="rs", amount=7)
    assert (await led.rec(cid))["reservation_state"] == "NONE" and await led.res_state(cid) is None
    tok = await led.claimed(cid)
    assert (await led.rec(cid))["reservation_state"] == "RESERVED" == await led.res_state(cid)
    await led.call("clt_alice", "release_claim", tok["token_id"])
    assert (await led.rec(cid))["reservation_state"] == "RELEASED" == await led.res_state(cid)
    tok2 = await led.claimed(cid)
    assert tok2["generation"] == 2
    assert (await led.rec(cid))["reservation_state"] == "RESERVED" == await led.res_state(cid)
    await led.call("clt_wri", "observe_target", tok2["token_id"], BASE, "CLONE")
    await led.call("clt_alice", "begin_apply", tok2["token_id"], uuid.uuid4(), "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, 2)
    await led.call("clt_wri", "record_call", cid, 2, await led.call_id_of(cid))
    assert await led.complete(cid, 2, "SUCCESS") == "APPLIED"
    assert (await led.rec(cid))["reservation_state"] == "CONSUMED" == await led.res_state(cid)
    # every record in the ledger agrees with its reservation row (or has none and is not RESERVED)
    bad = await led.conn.fetch(
        "SELECT r.change_id FROM change_ledger.records r LEFT JOIN change_ledger.reservations s USING(change_id) "
        "WHERE coalesce(s.state,'NONE') IS DISTINCT FROM r.reservation_state")
    assert not bad


# ============================================================================ B2
async def test_b2_budget_admin_never_touches_another_scopes_grant(led):
    foreign = DEFAULT_GRANT[(T2, C2)]
    before = await led.conn.fetchrow("SELECT * FROM change_ledger.grants WHERE grant_id=$1", foreign)
    win = (datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC) + timedelta(hours=1))
    # operator scoped to A, grant of B, own scope A: the id collision must not overwrite it
    await fails("SCOPE_NOT_GRANTED", led.call("clt_dave", "budget_admin", foreign, "EUR", 1, 1, 1, *win))
    await fails("SCOPE_NOT_GRANTED", led.call("clt_dave", "budget_revoke", foreign))
    # operator scoped to A naming scope B is refused by the scope check itself
    await fails("SCOPE_NOT_GRANTED", led.call("clt_dave", "budget_admin", foreign, "EUR", 1, 1, 1, *win, t=T2, c=C2))
    await fails("SCOPE_NOT_GRANTED", led.sql("clt_dave", "SELECT change_ledger.budget_admin('T2','C2',$1,'EUR',1,1,1,$2,$3)",
                                            foreign, *win, t=None))
    after = await led.conn.fetchrow("SELECT * FROM change_ledger.grants WHERE grant_id=$1", foreign)
    assert dict(after) == dict(before)
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE event_type LIKE 'BUDGET_GRANT_%'") == 0
    with pytest.raises(asyncpg.InsufficientPrivilegeError):       # requester: no EXECUTE (the port maps 42501)
        await led.call("clt_alice", "budget_revoke", DEFAULT_GRANT[(T, C)])
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.call("clt_wrk", "budget_admin", uuid.uuid4(), "EUR", 1, 1, 1, *win)


async def test_b2_every_limit_change_and_revocation_is_an_event_visible_in_verify_chain(led):
    gid = uuid.uuid4()
    await grant(led, 100, 5, 5, gid=gid)
    await grant(led, 250, 7, 6, gid=gid)                                    # update: same tenant and company
    row = await led.conn.fetchrow("SELECT * FROM change_ledger.grants WHERE grant_id=$1", gid)
    assert (row["amount_limit"], row["count_limit"], row["post_count_limit"]) == (250, 7, 6)
    evs = await led.conn.fetch("SELECT payload FROM change_ledger.events WHERE event_type='BUDGET_GRANT_SET' ORDER BY seq")
    pl = [json.loads(e["payload"]) if isinstance(e["payload"], str) else e["payload"] for e in evs]
    assert [p["update"] for p in pl] == [False, True] and pl[1]["previous"]["amount_limit"] == "100.00"
    assert pl[1]["amount_limit"] == "250" and pl[1]["grant_id"] == str(gid)
    await fails("FORBIDDEN_TRANSITION", grant(led, 250, gid=gid, currency="USD"))     # currency never changes
    assert await led.call("clt_dave", "budget_revoke", gid) == "REVOKED"
    assert await led.call("clt_dave", "budget_revoke", gid) == "REVOKED"                # idempotent, one event
    assert await led.conn.fetchval("SELECT status FROM change_ledger.grants WHERE grant_id=$1", gid) == "REVOKED"
    await fails("FORBIDDEN_TRANSITION", grant(led, 999, gid=gid))                       # no update of a revoked grant
    cid = await led.propose(request_id="rv")
    await fails("BUDGET_EXCEEDED", led.call("clt_alice", "declare_budget", cid, gid, "EUR", 1, False, False))
    kinds = [r["event_type"] for r in await led.conn.fetch(
        "SELECT event_type FROM change_ledger.events WHERE event_type LIKE 'BUDGET_GRANT_%' ORDER BY seq")]
    assert kinds == ["BUDGET_GRANT_SET", "BUDGET_GRANT_SET", "BUDGET_GRANT_REVOKED"]
    n = await led.conn.fetchval("SELECT count(*) FROM change_ledger.events")
    assert await led.call("clt_aud", "verify_chain") == {"ok": True, "count": n, "bad_seq": None}
    # the grant event is on the chain: tampering with its payload is detected
    await led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    await led.conn.execute("UPDATE change_ledger.events SET payload='{}'::jsonb WHERE event_type='BUDGET_GRANT_REVOKED'")
    await led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is False


async def test_b2_identity_and_registry_helpers_are_not_executable_by_any_runtime_role(led):
    for fn in ("person_of", "same_person", "epoch_value", "registry_enforced"):
        got = await led.conn.fetch(
            "SELECT r.rolname FROM pg_roles r JOIN pg_proc p ON p.proname=$1 JOIN pg_namespace n ON "
            "n.oid=p.pronamespace AND n.nspname='change_ledger' WHERE r.rolname = ANY($2) AND "
            "has_function_privilege(r.rolname, p.oid, 'EXECUTE')", fn, RUNTIME)
        assert not got, (fn, [g[0] for g in got])
    for role in RUNTIME:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, "SELECT change_ledger.registry_enforced('T2','C2')", t=None)
    # the new internals are closed as well
    for fn in ("budget_precheck", "assert_session_independent", "assert_registry_for_effect"):
        got = await led.conn.fetch(
            "SELECT r.rolname FROM pg_roles r JOIN pg_proc p ON p.proname=$1 JOIN pg_namespace n ON "
            "n.oid=p.pronamespace AND n.nspname='change_ledger' WHERE r.rolname = ANY($2) AND "
            "has_function_privilege(r.rolname, p.oid, 'EXECUTE')", fn, RUNTIME)
        assert not got, fn


# ============================================================================ B3
async def test_b3_a_scope_without_a_registry_policy_row_is_enforced_and_refuses_unregistered_actors(led):
    c = led.conn
    assert await c.fetchval("SELECT count(*) FROM change_ledger.registry_policy") == 0
    assert await c.fetchval("SELECT column_default FROM information_schema.columns WHERE table_schema='change_ledger' "
                            "AND table_name='registry_policy' AND column_name='enforced'") == "true"
    await _role(c, "clt_new")
    await c.execute("GRANT requester_role TO clt_new")
    await c.execute("SELECT change_ledger.add_role_scope('clt_new',$1,$2)", T, C)
    await fails("NOT_ENTITLED", led.call("clt_new", "propose", uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_new", "r1",
                                         DIGEST, "d", "v1", None, exp(), None))
    assert await c.fetchval("SELECT count(*) FROM change_ledger.records") == 0
    # registered: accepted
    await led.dual("PRINCIPAL", {"principal": "clt_new", "person_id": "person-new", "capabilities": ["requester"],
                                 "active": True})        # 010 (C1): a new principal needs two operators
    assert await led.call("clt_new", "propose", uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_new", "r2", DIGEST, "d",
                          "v1", None, exp(), None) is not None
    # an approver without registration is refused as well, and enforce_registry stores the row it implies
    cid = await led.validated(request_id="ap")
    await c.execute("DELETE FROM change_ledger.principals WHERE principal='clt_carol'")
    await fails("NOT_ENTITLED", led.call("clt_carol", "issue_approval_nonce", cid))
    assert await led.call("clt_dave", "enforce_registry") is True
    assert await c.fetchval("SELECT enforced FROM change_ledger.registry_policy WHERE tenant_id=$1", T) is True
    assert await led.call("clt_dave", "enforce_registry") is True


async def test_b3_claim_and_issue_permit_refuse_a_non_clone_target_while_the_registry_is_not_enforced(led):
    c = led.conn
    cid = await led.approved(request_id="nc", base="base-1")
    stg = await led.approved(request_id="nc3", base="base-3")     # approved while base-3 still is a clone
    live, ltok, _ = await led.applying(request_id="nc2", base="base-2")
    await led.checkpoint()
    # legacy mode is only reachable by arrangement (no API turns enforcement off)
    await c.execute("INSERT INTO change_ledger.registry_policy(tenant_id,company_id,enforced) VALUES($1,$2,false)", T, C)
    assert await led.claimed(cid) is not None                     # a disposable clone still works in legacy mode
    await c.execute("UPDATE change_ledger.targets SET target_class='STAGING' WHERE base_fingerprint='base-3'")
    await c.execute("UPDATE change_ledger.records SET declared_target_class='STAGING' WHERE change_id=$1", stg)
    await fails("NOT_ENTITLED", led.claimed(stg))
    assert await led.locks(stg) == (0, 0, 0) and (await led.rec(stg))["authorization_state"] == "APPROVED"
    await c.execute("UPDATE change_ledger.targets SET target_class='PRODUCTION' WHERE base_fingerprint='base-2'")
    await c.execute("UPDATE change_ledger.records SET declared_target_class='PRODUCTION' WHERE change_id=$1", live)
    await fails("NOT_ENTITLED", led.call("clt_wrk", "issue_permit", live, ltok["generation"]))
    assert (await led.rec(live))["dispatch_state"] == "NOT_PERMITTED"
    # enforced again (the row flips): both succeed, the target class is then governed by the registry rules
    await c.execute("UPDATE change_ledger.registry_policy SET enforced=true")
    await c.execute("UPDATE change_ledger.targets SET target_class='DISPOSABLE_CLONE' WHERE base_fingerprint='base-2'")
    await c.execute("UPDATE change_ledger.records SET declared_target_class='DISPOSABLE_CLONE' WHERE change_id=$1", live)
    permit = await led.call("clt_wrk", "issue_permit", live, ltok["generation"])
    assert permit["generation"] == ltok["generation"]


async def _session(led, login, role, name, *args, t=T, c=C):
    """One call as `role` assumed with SET ROLE inside the session of `login` (session_user = login)."""
    marks = ",".join(f"${i + 3}" for i in range(len(args)))
    async with led.conn.transaction():
        await led.conn.execute(f'SET LOCAL SESSION AUTHORIZATION "{login}"')
        await led.conn.execute(f'SET LOCAL ROLE "{role}"')
        await led.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
        return await led.conn.fetchval(f"SELECT change_ledger.{name}($1,$2{',' if args else ''}{marks})", t, c, *args)


async def test_b3_self_approval_through_set_role_is_refused(led):
    c = led.conn
    for r in ("clt_login", "clt_login2"):
        await _role(c, r)
    await c.execute("GRANT clt_alice, clt_bob, requester_role, approver_role TO clt_login")
    await c.execute("GRANT clt_bob TO clt_login2")
    for r in ("clt_login", "clt_login2", "requester_role"):
        await c.execute("SELECT change_ledger.add_role_scope($1,$2,$3)", r, T, C)
    cid = uuid.uuid4()
    args = (cid, "CREATE_DRAFT", BASE, ORG, "clt_alice", "self-1", DIGEST, "doc1", "v1", None, exp(), None)
    # (a) the group roles are not registered principals: NOT_ENTITLED, nothing is written
    with pytest.raises(asyncpg.PostgresError, match="NOT_ENTITLED"):
        await _session(led, "clt_login", "requester_role", "propose", cid, "CREATE_DRAFT", BASE, ORG, "requester_role",
                       "self-0", DIGEST, "doc1", "v1", None, exp(), None)
    assert await c.fetchval("SELECT count(*) FROM change_ledger.records") == 0
    # (b) registered aliases: alice proposes inside the login session, then that session assumes bob
    assert await _session(led, "clt_login", "clt_alice", "propose", *args) == cid
    assert await c.fetchval("SELECT requester_session FROM change_ledger.records WHERE change_id=$1", cid) == "clt_login"
    await _session(led, "clt_login", "clt_alice", "declare_business_key", cid, sha("self"), None, None)
    await _session(led, "clt_login", "clt_alice", "declare_budget", cid, DEFAULT_GRANT[(T, C)], "EUR", 0, False, False)
    assert await _session(led, "clt_login", "clt_alice", "validate", cid) == "VALIDATED"
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await _session(led, "clt_login", "clt_bob", "issue_approval_nonce", cid)
    # a genuine approval session obtains the nonce; the proposing session cannot spend it through SET ROLE
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    dg = await led.approval_digest(cid)
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await _session(led, "clt_login", "clt_bob", "approve", cid, nonce, dg)
    assert (await led.rec(cid))["authorization_state"] == "NONE"
    # a person alias of the proposing session is refused too (login registered as the same person as login2)
    await c.execute("INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities) "
                    "VALUES($1,$2,'clt_login','P-ONE','{}'),($1,$2,'clt_login2','P-ONE','{}')", T, C)
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await _session(led, "clt_login2", "clt_bob", "approve", cid, nonce, dg)
    await c.execute("DELETE FROM change_ledger.principals WHERE principal='clt_login2'")
    # an independent session (other login, other person) may approve
    aid = await _session(led, "clt_login2", "clt_bob", "approve", cid, nonce, dg)
    assert aid is not None and (await led.rec(cid))["authorization_state"] == "APPROVED"
