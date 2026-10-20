"""Focused PostgreSQL tests for db/phase2/013_dispatched_invariant.sql: batch F (GPT-PM F-02, one DISPATCHED invariant).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied and the actors of
test_change_ledger_sql._setup. The triggers under test are not role based, so each attempt is made at three levels:
a runtime role (SET LOCAL ROLE clt_*: stopped earlier by the missing privilege), the table owner (SET LOCAL ROLE
ledger_owner: has the privilege and a permissive RLS policy) and the superuser connection. Owner and superuser attempts
must fail with the ledger's FORBIDDEN_TRANSITION, i.e. from the trigger itself. Named limit (not tested, by design):
the owner / superuser can DISABLE or DROP the triggers; they are the trusted boundary.

Item -> tests:
  F1 permit INSERT only as NOT_PERMITTED: f1_*
  F2 permit transition guard (only PERMITTED -> DISPATCHED, DISPATCHED terminal): f2_*
  F3 records.dispatch_state follows the permit: f3_*
  F4 records INSERT only with the default dispatch_state: f4_*
  normal path / replay / cancel and re-dispatch of the next generation: f5_*
"""
import uuid

import asyncpg
import pytest
from _approval_envelope import FIXTURE_PAYLOAD
from _pg_harness import require_dsn, throwaway_db
from test_change_ledger_sql import C, T, L, _setup

from business_ai_gateway.phase2.change import canonical_json

pytestmark = pytest.mark.integration

PAYLOAD = canonical_json(FIXTURE_PAYLOAD)
RUNTIME = ("clt_alice", "clt_bob", "clt_dave", "clt_wri", "clt_wrk", "clt_aud")


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


async def as_owner(led, sql, *args):
    """The table owner (ledger_owner): has the privilege and the owner_all RLS policy, so only the trigger can stop it."""
    async with led.conn.transaction():
        await led.conn.execute("SET LOCAL ROLE ledger_owner")
        return await led.conn.execute(sql, *args)


async def refused(led, sql, *args, who=("owner", "super")):
    """The statement fails with FORBIDDEN_TRANSITION as table owner and as superuser; every runtime role is denied."""
    for role in RUNTIME:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, sql, *args)
    if "owner" in who:
        with pytest.raises(asyncpg.PostgresError, match="FORBIDDEN_TRANSITION"):
            await as_owner(led, sql, *args)
    if "super" in who:
        with pytest.raises(asyncpg.PostgresError, match="FORBIDDEN_TRANSITION"):
            await led.conn.execute(sql, *args)


async def permit_state(led, cid, gen=None):
    return await led.conn.fetchval("SELECT state FROM change_ledger.dispatch_permits WHERE change_id=$1 AND generation="
                                   "coalesce($2,(SELECT claim_generation FROM change_ledger.records WHERE change_id=$1))",
                                   cid, gen)


async def dstate(led, cid):
    return (await led.rec(cid))["dispatch_state"]


async def markers(led, cid):
    return await led.conn.fetchval("SELECT count(*) FROM change_ledger.change_dispatch_verifications "
                                   "WHERE change_id=$1", cid)


INSERT_PERMIT = ("INSERT INTO change_ledger.dispatch_permits(change_id,generation,state,call_id) "
                 "VALUES($1,$2,$3,gen_random_uuid())")


# ============================================================================ F1: a permit is born NOT_PERMITTED
async def test_f1_inserting_a_permit_in_any_other_state_is_refused(led):
    cid = await led.propose(request_id="f1a")
    for state in ("DISPATCHED", "PERMITTED", "CANCELLED_UNDISPATCHED"):
        await refused(led, INSERT_PERMIT, cid, 7, state)
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.dispatch_permits WHERE change_id=$1", cid) == 0
    # control: the same statement with the default state is accepted, so the refusals above are about the state
    await led.conn.execute(INSERT_PERMIT, cid, 7, "NOT_PERMITTED")
    assert await permit_state(led, cid, 7) == "NOT_PERMITTED"
    # a permit created DISPATCHED must not make the change look dispatched either
    assert await dstate(led, cid) == "NOT_PERMITTED"


async def test_f1_begin_apply_still_creates_its_permit_and_replay_is_idempotent(led):
    cid, tok, call_id = await led.applying(request_id="f1b", base="base-1")
    assert await permit_state(led, cid) == "NOT_PERMITTED"
    again = await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "host-1", "sess-1")
    assert again["state"] == "CONSUMED"                                 # replay of the consumed ticket: no second permit
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.dispatch_permits WHERE change_id=$1", cid) == 1


# ============================================================================ F2: the permit transition guard
async def test_f2_a_permit_only_becomes_dispatched_from_permitted(led):
    # NOT_PERMITTED -> DISPATCHED with a valid marker: 012 accepted it (no issue_permit, no checkpoint, no TTL, no fence)
    cid, tok, call_id = await led.applying(request_id="f2a", base="base-1")
    gen = tok["generation"]
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, gen, PAYLOAD) is True
    assert await markers(led, cid) == 1
    await refused(led, "UPDATE change_ledger.dispatch_permits SET state='DISPATCHED' WHERE change_id=$1", cid)
    assert await permit_state(led, cid) == "NOT_PERMITTED" and await dstate(led, cid) == "NOT_PERMITTED"
    # CANCELLED_UNDISPATCHED -> DISPATCHED is refused for the same reason
    await led.conn.execute("UPDATE change_ledger.dispatch_permits SET state='CANCELLED_UNDISPATCHED' WHERE change_id=$1", cid)
    await refused(led, "UPDATE change_ledger.dispatch_permits SET state='DISPATCHED' WHERE change_id=$1", cid)
    assert await permit_state(led, cid) == "CANCELLED_UNDISPATCHED"


async def test_f2_a_dispatched_permit_cannot_leave_dispatched(led):
    cid, tok, call_id = await led.dispatched(request_id="f2b", base="base-1")
    for target in ("PERMITTED", "NOT_PERMITTED", "CANCELLED_UNDISPATCHED"):
        await refused(led, f"UPDATE change_ledger.dispatch_permits SET state='{target}' WHERE change_id=$1", cid)
    await refused(led, "SELECT change_ledger.dispatch_cas($1,$2,'DISPATCHED','PERMITTED')", cid, tok["generation"])
    assert await permit_state(led, cid) == "DISPATCHED" and await dstate(led, cid) == "DISPATCHED"
    # an update that does not change the state is not a transition
    await led.conn.execute("UPDATE change_ledger.dispatch_permits SET state='DISPATCHED' WHERE change_id=$1", cid)


# ============================================================================ F3: records.dispatch_state follows the permit
async def test_f3_direct_update_to_dispatched_is_refused_without_a_dispatched_permit(led):
    upd = "UPDATE change_ledger.records SET dispatch_state='DISPATCHED' WHERE change_id=$1"
    plain = await led.propose(request_id="f3a")                           # no permit at all
    await refused(led, upd, plain)
    assert await dstate(led, plain) == "NOT_PERMITTED"
    cid, tok, call_id, _ = await led.permitted(request_id="f3b", base="base-2")   # permit PERMITTED, no marker
    await refused(led, upd, cid)
    assert await dstate(led, cid) == "PERMITTED" and await permit_state(led, cid) == "PERMITTED"
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, tok["generation"], PAYLOAD) is True
    await refused(led, upd, cid)                                          # marker is there, the permit is still PERMITTED
    assert await dstate(led, cid) == "PERMITTED"
    # an earlier generation's DISPATCHED permit does not count: a re-claimed change is judged by its CURRENT generation
    assert await led.call("clt_wrk", "cancel_permit", cid, tok["generation"]) is True
    tok2 = await led.claimed(cid)
    call2 = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok2["token_id"], call2, "host-1", "sess-1")
    await refused(led, upd, cid)                                          # new generation: permit NOT_PERMITTED
    assert await dstate(led, cid) == "CANCELLED_UNDISPATCHED"


async def test_f3_dispatched_is_refused_when_the_verification_no_longer_matches(led):
    cid, tok, call_id = await led.dispatched(request_id="f3c", base="base-1")
    # a DISPATCHED permit exists, but the record is rolled back by hand and re-set after the digest changed under it:
    # the 012 gate (assert_dispatch_verified) is reused, so the changed digest is refused even with a DISPATCHED permit
    await led.conn.execute("ALTER TABLE change_ledger.records DISABLE TRIGGER records_dispatch_state_guard")
    await led.conn.execute("UPDATE change_ledger.records SET dispatch_state='PERMITTED' WHERE change_id=$1", cid)
    await led.conn.execute("ALTER TABLE change_ledger.records ENABLE TRIGGER records_dispatch_state_guard")
    await led.conn.execute("UPDATE change_ledger.records SET payload_digest=repeat('a',64) WHERE change_id=$1", cid)
    with pytest.raises(asyncpg.PostgresError, match="FORBIDDEN_TRANSITION"):
        await led.conn.execute("UPDATE change_ledger.records SET dispatch_state='DISPATCHED' WHERE change_id=$1", cid)
    with pytest.raises(asyncpg.PostgresError, match="FORBIDDEN_TRANSITION"):
        await as_owner(led, "UPDATE change_ledger.records SET dispatch_state='DISPATCHED' WHERE change_id=$1", cid)
    assert await dstate(led, cid) == "PERMITTED"


async def test_f3_dispatched_is_refused_when_the_same_statement_moves_the_proven_facts(led):
    cid, tok, call_id = await led.dispatched(request_id="f3d", base="base-1")
    await led.conn.execute("ALTER TABLE change_ledger.records DISABLE TRIGGER records_dispatch_state_guard")
    await led.conn.execute("UPDATE change_ledger.records SET dispatch_state='PERMITTED' WHERE change_id=$1", cid)
    await led.conn.execute("ALTER TABLE change_ledger.records ENABLE TRIGGER records_dispatch_state_guard")
    for extra in ("claim_generation=claim_generation+1", "payload_digest=repeat('c',64)"):
        with pytest.raises(asyncpg.PostgresError, match="FORBIDDEN_TRANSITION"):
            await led.conn.execute(f"UPDATE change_ledger.records SET dispatch_state='DISPATCHED', {extra} WHERE change_id=$1", cid)
    assert await dstate(led, cid) == "PERMITTED"


async def test_f3_permitted_needs_a_permitted_permit_and_a_dispatched_record_cannot_fall_back(led):
    to_permitted = "UPDATE change_ledger.records SET dispatch_state='PERMITTED' WHERE change_id=$1"
    cid, tok, call_id = await led.applying(request_id="f3e", base="base-1")        # permit NOT_PERMITTED
    await refused(led, to_permitted, cid)
    assert await dstate(led, cid) == "NOT_PERMITTED"
    done, dtok, _ = await led.dispatched(request_id="f3f", base="base-2")          # permit and record DISPATCHED
    await refused(led, to_permitted, done)
    assert await dstate(led, done) == "DISPATCHED" and await permit_state(led, done) == "DISPATCHED"
    # an update that leaves the column unchanged is not a transition (record_call-like no-op, complete's CASE)
    await led.conn.execute("UPDATE change_ledger.records SET dispatch_state='DISPATCHED' WHERE change_id=$1", done)
    await led.conn.execute("UPDATE change_ledger.records SET dispatch_state=dispatch_state WHERE change_id=$1", done)


# ============================================================================ F4: records are born NOT_PERMITTED
async def test_f4_inserting_a_record_with_another_dispatch_state_is_refused(led):
    src = await led.propose(request_id="f4a")
    clone = ("INSERT INTO change_ledger.records SELECT (jsonb_populate_record(NULL::change_ledger.records, "
             "to_jsonb(r) || jsonb_build_object('change_id',gen_random_uuid(),'request_id',$2::text,"
             "'dispatch_state',$3::text))).* FROM change_ledger.records r WHERE r.change_id=$1")
    for state in ("DISPATCHED", "PERMITTED", "CANCELLED_UNDISPATCHED"):
        await refused(led, clone, src, "f4-" + state, state)
    n = await led.conn.fetchval("SELECT count(*) FROM change_ledger.records")
    assert n == 1
    await led.conn.execute(clone, src, "f4-control", "NOT_PERMITTED")                 # control: the clone itself is valid
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.records") == 2


# ============================================================================ normal path, replay, next generation
async def test_f5_normal_path_replay_and_events(led):
    cid, tok, call_id, permit = await led.permitted(request_id="f5a", base="base-1")
    gen = tok["generation"]
    replay_permit = await led.call("clt_wrk", "issue_permit", cid, gen)               # B6e replay of a live permit
    assert replay_permit["permit_digest"] == permit["permit_digest"]
    assert await dstate(led, cid) == "PERMITTED" and await permit_state(led, cid) == "PERMITTED"
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, gen, PAYLOAD) is True      # verify
    assert await led.call("clt_wri", "record_call", cid, gen, call_id) is True                  # dispatch
    assert await dstate(led, cid) == "DISPATCHED" and await permit_state(led, cid) == "DISPATCHED"
    ev = lambda t: led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type=$2", cid, t)
    assert await ev("DISPATCHED") == 1
    # replay of the dispatch: false, nothing moves, no second event
    assert await led.call("clt_wri", "record_call", cid, gen, call_id) is False
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, gen, PAYLOAD) is True      # idempotent marker
    assert await markers(led, cid) == 1 and await ev("DISPATCHED") == 1
    assert await dstate(led, cid) == "DISPATCHED"
    # the rest of the lifecycle that reads / keeps the dispatched state still works
    assert await led.complete(cid, gen, "UNKNOWN") == "APPLY_UNKNOWN"
    assert await dstate(led, cid) == "DISPATCHED"


async def test_f5_cancel_and_the_next_generation_dispatch_normally(led):
    cid, tok, call_id, _ = await led.permitted(request_id="f5b", base="base-1")
    gen = tok["generation"]
    assert await led.call("clt_wrk", "cancel_permit", cid, gen) is True
    assert await dstate(led, cid) == "CANCELLED_UNDISPATCHED" and await permit_state(led, cid, gen) == "CANCELLED_UNDISPATCHED"
    tok2 = await led.claimed(cid)
    call2 = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok2["token_id"], call2, "host-1", "sess-1")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, tok2["generation"])
    assert await dstate(led, cid) == "PERMITTED"
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, tok2["generation"], PAYLOAD) is True
    assert await led.call("clt_wri", "record_call", cid, tok2["generation"], call2) is True
    assert await dstate(led, cid) == "DISPATCHED" and await permit_state(led, cid) == "DISPATCHED"
    assert await permit_state(led, cid, gen) == "CANCELLED_UNDISPATCHED"              # history of generation 1 untouched
