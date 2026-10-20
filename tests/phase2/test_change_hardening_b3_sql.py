"""Focused PostgreSQL tests for db/phase2/008_change_hardening_b.sql, round 3: finding B6 (items a-q) of
docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md (batch B).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied and the actors of
test_change_ledger_sql._setup. Superuser access arranges only what no API can produce (a back-dated nonce, a released
halt hold, rows that a constraint must refuse) and reads results; it never removes a guard.

Item -> test: a b6a, b b6b, c b6c, d b6d, e b6e, f b6f, g b6g, h b6h, i b6i, j b6j, k b6k, l b6l, m b6m (size bound; the
hash-coverage half is documented in the migration, not implemented), n b6n, o b6o, p b6p, q b6q.
"""
import asyncio
import json
import uuid
from types import SimpleNamespace

import asyncpg
import pytest
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_hardening_b2_sql import add_base, sweep, wait_blocked
from test_change_ledger_sql import BASE, C, C2, DIGEST, ORG, T, T2, L, _failed_parent, _repair, _setup, exp, sha

from business_ai_gateway.phase2.change_ledger._common import LedgerError, Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger

pytestmark = pytest.mark.integration


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


def jl(v):
    return json.loads(v) if isinstance(v, str) else v


async def count(led, sql, *args):
    return await led.conn.fetchval(sql, *args)


async def verified_draft(led, rid, base=BASE, target="doc1"):
    cid, tok, _ = await led.dispatched(request_id=rid, base=base, target=target)
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLIED"
    assert await led.verify(cid, True) == "VERIFIED"
    return cid


# ============================================================================ (e) idempotent replays
async def test_b6e_repeated_approve_claim_issue_permit_and_begin_apply_return_the_existing_result(led):
    cid = await led.validated()
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    dg = await led.approval_digest(cid)
    a1 = await led.call("clt_bob", "approve", cid, nonce, dg)
    assert await led.call("clt_bob", "approve", cid, nonce, dg) == a1
    assert await count(led, "SELECT count(*) FROM change_ledger.approvals WHERE change_id=$1", cid) == 1
    assert await count(led, "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='APPROVED'",
                       cid) == 1
    await fails("FORBIDDEN_TRANSITION", led.call("clt_bob", "approve", cid, nonce, "f" * 64))  # not a replay
    tok = await led.claimed(cid)
    cb = await led.conn.fetchrow("SELECT * FROM change_ledger.change_budget WHERE change_id=$1", cid)
    again = await led.call("clt_alice", "claim", cid, None, cb["grant_id"], cb["amount"], False, False)
    assert again["token_id"] == tok["token_id"] and again["generation"] == tok["generation"] == 1
    await fails("DIGEST_MISMATCH", led.call("clt_alice", "claim", cid, None, cb["grant_id"], cb["amount"] + 1,
                                            False, False))
    assert await count(led, "SELECT count(*) FROM change_ledger.claim_tokens WHERE change_id=$1", cid) == 1
    assert await count(led, "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='CLAIMED'",
                       cid) == 1
    call_id = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "host-1", "sess-1")
    replay = await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "host-1", "sess-1")
    assert replay["token_id"] == tok["token_id"]
    await led.checkpoint()
    p1 = await led.call("clt_wrk", "issue_permit", cid, tok["generation"])
    p2 = await led.call("clt_wrk", "issue_permit", cid, tok["generation"])
    assert p1["permit_digest"] == p2["permit_digest"] and p1["expires_at"] == p2["expires_at"]
    assert await count(led, "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='PERMITTED'",
                       cid) == 1


async def test_b6e_begin_apply_replay_on_a_dead_change_is_refused(led):
    cid, tok, call_id = await led.applying(request_id="dead1")
    assert await led.complete(cid, tok["generation"], "PRE_WRITE_REFUSAL", proof={"proof": "no write"}) == "FAILED_APPLY"
    await fails("TICKET_SUPERSEDED", led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "h", "s"))
    assert (await led.rec(cid))["execution_state"] == "FAILED_APPLY"


async def test_b6e_concurrent_propose_with_one_logical_key_returns_the_replay_not_a_unique_violation(led):
    a, b = await led.db.connect(), await led.db.connect()
    try:
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        tr = a.transaction()
        await tr.start()
        await a.execute('SET LOCAL ROLE "clt_alice"')
        await a.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        await a.fetchval("SELECT change_ledger.propose($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)", T, C, c1,
                         "CREATE_DRAFT", BASE, ORG, "clt_alice", "same-req", DIGEST, "doc1", "v1", None, exp(), None)
        pid = await b.fetchval("SELECT pg_backend_pid()")
        task = asyncio.create_task(led.call("clt_alice", "propose", c2, "CREATE_DRAFT", BASE, ORG, "clt_alice",
                                            "same-req", DIGEST, "doc1", "v1", None, exp(), None, conn=b))
        await wait_blocked(led, pid)                       # the second propose waits on the unique index
        await tr.commit()
        assert await task == c1                            # replay of the first, no raw 23505
        assert await count(led, "SELECT count(*) FROM change_ledger.records WHERE request_id='same-req'") == 1
        await fails("IDEMPOTENCY_CONFLICT", led.call("clt_alice", "propose", uuid.uuid4(), "CREATE_DRAFT", BASE, ORG,
                                                     "clt_alice", "same-req", "c" * 64, "doc1", "v1", None, exp(), None))
    finally:
        await a.close()
        await b.close()


# ============================================================================ (b) reject from APPROVED
async def test_b6b_an_unclaimed_approval_can_be_rejected_and_a_claimed_one_cannot(led):
    cid = await led.approved()
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    assert await led.call("clt_bob", "reject", cid, nonce) == "REJECTED"
    r = await led.rec(cid)
    assert (r["lifecycle"], r["authorization_state"]) == ("REJECTED", "VOIDED")
    await fails("APPROVAL_VOIDED", led.claimed(cid))
    ev = jl(await led.conn.fetchval("SELECT payload FROM change_ledger.events WHERE change_id=$1 AND "
                                    "event_type='REJECTED'", cid))
    assert ev["authorization_from"] == "APPROVED"
    c2 = await led.approved(request_id="rj2", base="base-2")
    await led.claimed(c2)
    await fails("FORBIDDEN_TRANSITION", led.call("clt_bob", "issue_approval_nonce", c2))
    assert (await led.rec(c2))["authorization_state"] == "CLAIMED"


# ============================================================================ (a) ROLLBACK_REFUSED at T8
async def test_b6a_an_unpost_refused_before_the_write_ends_in_rollback_refused(led):
    d = await verified_draft(led, "rr-d")
    u = await led.approved(kind="UNPOST", parent=d, request_id="rr-u")
    tok = await led.claimed(u)
    await led.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s")
    got = await led.complete(u, tok["generation"], "PRE_WRITE_REFUSAL", proof={"proof": "dependents exist"},
                             code="ROLLBACK_REFUSED")
    assert got == "ROLLBACK_REFUSED"
    r = await led.rec(u)
    assert (r["execution_state"], r["reservation_state"]) == ("ROLLBACK_REFUSED", "RELEASED")
    assert await led.locks(u) == (0, 0, 0)
    assert (await led.rec(d))["verification_state"] == "VERIFIED"                   # the original is untouched
    assert await led.complete(u, tok["generation"], "PRE_WRITE_REFUSAL", proof={"proof": "x"},
                              code="ROLLBACK_REFUSED") == "ROLLBACK_REFUSED"       # a replay returns it
    # the same code on a draft is an ordinary refusal
    c = await led.applying(request_id="rr-c", base="base-2")
    assert await led.complete(c[0], c[1]["generation"], "PRE_WRITE_REFUSAL", proof={"p": 1},
                              code="ROLLBACK_REFUSED") == "FAILED_APPLY"


# ============================================================================ (c) kill switch unwind
@pytest.mark.parametrize("mode", ["STOP_ADMIT", "STOP_EFFECTS"])
async def test_b6c_a_stop_unwinds_claimed_and_permitted_states_in_the_sweep_without_waiting_for_a_ttl(led, mode):
    claimed = await led.approved(request_id="k1", base="base-1")
    await led.claimed(claimed)
    permitted, _, _, _ = await led.permitted(request_id="k2", base="base-2")
    applying, _, _ = await led.applying(request_id="k3", base="base-3")
    dispatched, _, _ = await led.dispatched(request_id="k4", base="base-4")
    assert await sweep(led) is not None
    assert (await led.rec(claimed))["authorization_state"] == "CLAIMED"             # no TTL elapsed, switch OFF
    await led.call("clt_dave", "kill_switch", mode)
    got = await sweep(led)
    assert got["T5x"] == [str(claimed)] and got["T6c"] == [str(permitted)] and got["T6r"] == [str(applying)]
    for cid in (claimed, permitted, applying):
        r = await led.rec(cid)
        assert (r["authorization_state"], r["execution_state"], r["reservation_state"]) == (
            "APPROVED", "NOT_STARTED", "RELEASED")                                  # released, not voided
    assert (await led.rec(permitted))["dispatch_state"] == "CANCELLED_UNDISPATCHED"
    r = await led.rec(dispatched)                                                    # a dispatched call is never touched
    assert (r["execution_state"], r["dispatch_state"]) == ("APPLYING", "DISPATCHED")


async def test_b6c_a_stop_sweep_releases_but_never_voids(led):
    app = await led.approved(request_id="sv1", base="base-1")
    claimed = await led.approved(request_id="sv2", base="base-2")
    await led.claimed(claimed, key="c" * 64)
    await led.call("clt_dave", "kill_switch", "STOP_ADMIT")
    got = await sweep(led)
    assert got["VOIDED"] == [] and got["T5x"] == [str(claimed)]                     # only REVOKE voids
    assert (await led.rec(app))["authorization_state"] == "APPROVED"
    assert (await led.rec(claimed))["authorization_state"] == "APPROVED"


# ============================================================================ (d) nonce EXPIRED persisted
async def test_b6d_an_expired_nonce_is_persisted_as_expired_by_the_sweep_and_by_the_next_nonce(led):
    cid = await led.validated()
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    dg = await led.approval_digest(cid)       # 009: the canonical text is stored for the issued nonce
    await led.conn.execute("UPDATE change_ledger.approval_nonces SET expires_at=now()-interval '1 second' "
                           "WHERE nonce=$1", nonce)                                  # arrangement: time passed
    await fails("APPROVAL_EXPIRED", led.call("clt_bob", "approve", cid, nonce, dg))
    assert await count(led, "SELECT state FROM change_ledger.approval_nonces WHERE nonce=$1", nonce) == "ISSUED"
    got = await sweep(led)
    assert got["NONCES_EXPIRED"] == 1
    assert await count(led, "SELECT state FROM change_ledger.approval_nonces WHERE nonce=$1", nonce) == "EXPIRED"
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_bob", "approve", cid, nonce, dg))
    # issue_approval_nonce persists the expiry of an older nonce of the same change
    n2 = await led.call("clt_bob", "issue_approval_nonce", cid)
    await led.conn.execute("UPDATE change_ledger.approval_nonces SET expires_at=now()-interval '1 second' "
                           "WHERE nonce=$1", n2)
    n3 = await led.call("clt_bob", "issue_approval_nonce", cid)
    assert await count(led, "SELECT state FROM change_ledger.approval_nonces WHERE nonce=$1", n2) == "EXPIRED"
    assert await led.call("clt_bob", "approve", cid, n3, await led.approval_digest(cid)) is not None  # 009: n3 has its own text


# ============================================================================ (f) repair authorization again
async def repair_applying(led):
    parent = await _failed_parent(led)
    rep = await _repair(led, parent)
    tok = await led.claimed(rep)
    call_id = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "h", "s")
    await led.checkpoint()
    return parent, rep, tok, call_id


async def test_b6f_issue_permit_and_dispatch_rerun_the_repair_authorization(led):
    parent, rep, tok, call_id = await repair_applying(led)
    await led.conn.execute("UPDATE change_ledger.holds SET released_at=now() WHERE cause='FAILED_VERIFY_HALT' "
                           "AND change_id=$1", parent)                              # arrangement: the halt is gone
    await fails("PARENT_NOT_VERIFIED", led.call("clt_wrk", "issue_permit", rep, tok["generation"]))
    assert (await led.rec(rep))["dispatch_state"] == "NOT_PERMITTED"


async def test_b6f_a_foreign_hold_stops_the_permit_and_a_lost_halt_stops_the_dispatch(led):
    parent, rep, tok, call_id = await repair_applying(led)
    await led.call("clt_wrk", "declare_anchor_gap", BASE, json.dumps({"why": "test"}))
    await fails("BASE_HOLD", led.call("clt_wrk", "issue_permit", rep, tok["generation"]))


async def test_b6f_dispatch_of_a_repair_whose_halt_was_lost_is_refused(led):
    parent, rep, tok, call_id = await repair_applying(led)
    await led.call("clt_wrk", "issue_permit", rep, tok["generation"])
    await led.conn.execute("UPDATE change_ledger.holds SET released_at=now() WHERE cause='FAILED_VERIFY_HALT' "
                           "AND change_id=$1", parent)
    await fails("PARENT_NOT_VERIFIED", led.call("clt_wri", "record_call", rep, tok["generation"], call_id))
    assert (await led.rec(rep))["dispatch_state"] == "PERMITTED"


# ============================================================================ (g) T6 ownership row
async def test_b6g_the_ownership_row_stores_host_session_and_pre_image_hashes(led):
    cid, tok, call_id = await led.dispatched(request_id="own1")
    row = await led.conn.fetchrow("SELECT * FROM change_ledger.call_deadlines WHERE change_id=$1", cid)
    assert (row["writer_host"], row["onec_session"]) == ("host-1", "sess-1")
    pre = jl(row["pre_image_hashes"])
    assert pre["payload_digest"] == DIGEST and pre["target_version_sha256"] == sha("v1")
    assert pre["observed_fingerprint_sha256"] == sha(BASE)
    assert await count(led, "SELECT writer_host FROM change_ledger.dispatch_permits WHERE change_id=$1", cid) == "host-1"


# ============================================================================ (h) real verification attempts
async def test_b6h_one_signed_observation_is_one_attempt_and_a_replay_does_not_burn_the_bound(led):
    cid, tok, _ = await led.dispatched(request_id="va1")
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLIED"
    o1 = await led.observation(cid, None, inconclusive=True)
    r1 = jl(await led.call("clt_wrk", "verify_inconclusive", cid, o1))
    assert (r1["attempts"], r1["exhausted"]) == (1, False)
    for _ in range(3):                                                               # replays of the same evidence
        r = jl(await led.call("clt_wrk", "verify_inconclusive", cid, o1))
        assert (r["attempts"], r["exhausted"], r["replay"]) == (1, False, True)
    o2 = await led.observation(cid, None, inconclusive=True)
    assert jl(await led.call("clt_wrk", "verify_inconclusive", cid, o2))["attempts"] == 2
    o3 = await led.observation(cid, None, inconclusive=True)
    r3 = jl(await led.call("clt_wrk", "verify_inconclusive", cid, o3))
    assert (r3["attempts"], r3["exhausted"]) == (3, True)
    assert (await led.rec(cid))["verification_state"] == "FAILED_VERIFY"
    assert jl(await led.call("clt_wrk", "verify_inconclusive", cid, o1))["exhausted"] is True


# ============================================================================ (i) open holds are unique
async def test_b6i_at_most_one_open_hold_per_base_cause_and_change(led):
    ins = ("INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause) "
           "VALUES('T1','C1','base-1','ANCHOR_GAP')")
    await led.conn.execute(ins)
    with pytest.raises(asyncpg.UniqueViolationError):
        await led.conn.execute(ins)
    await led.conn.execute("INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause) "
                           "VALUES('T1','C1','base-2','ANCHOR_GAP')")                  # another base is fine
    await led.conn.execute("UPDATE change_ledger.holds SET released_at=now() WHERE base_fingerprint='base-1'")
    await led.conn.execute(ins)                                                         # a released hold does not count


# ============================================================================ (j) tenant integrity
async def test_b6j_parents_and_children_cannot_cross_a_tenant(led):
    a = await led.propose()
    z = await led.propose(requester="clt_zed", base="base-t2", t=T2, c=C2)
    await fails("CHANGE_NOT_FOUND", led.propose(requester="clt_zed", base="base-t2", t=T2, c=C2,
                                                kind="UPDATE_DRAFT", parent=a))
    await fails("CHANGE_NOT_FOUND", led.propose(requester="clt_zed", base="base-t2", t=T2, c=C2, kind="UNPOST",
                                                parent=a, repair_for=a, request_id="x"))
    assert await count(led, "SELECT count(*) FROM pg_constraint WHERE conname='records_scope_change_uniq'") == 1
    with pytest.raises(asyncpg.ForeignKeyViolationError):                               # composite reference on records
        await led.conn.execute("UPDATE change_ledger.records SET parent_change_id=$1 WHERE change_id=$2", a, z)
    with pytest.raises(asyncpg.ForeignKeyViolationError):                               # ... and on a child table
        await led.conn.execute("INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause,change_id) "
                               "VALUES('T2','C2','base-t2','ANCHOR_GAP',$1)", a)
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await led.conn.execute("UPDATE change_ledger.change_budget SET tenant_id='T2', company_id='C2' "
                               "WHERE change_id=$1", a)
    # the tenant filter of the claim parent guard is defence in depth: the composite reference above makes a
    # foreign VERIFIED parent unrepresentable, so there is no state to arrange for a separate claim test


# ============================================================================ (k) reads go through read_status
async def test_b6k_requesters_and_approvers_have_no_direct_select_on_records_tokens_and_holds(led):
    cid = await led.approved()
    await led.claimed(cid)
    for role in ("clt_alice", "clt_bob", "clt_both"):
        for tbl in ("records", "claim_tokens", "holds"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await led.sql(role, f"SELECT count(*) FROM change_ledger.{tbl}")
    for role in ("clt_aud", "clt_dave", "clt_wrk"):                                      # other classes keep their reads
        assert await led.sql(role, "SELECT count(*) FROM change_ledger.records")
    st = jl(await led.call("clt_alice", "read_status", cid))
    assert st["authorization"] == "CLAIMED" and "open_holds" in st
    assert jl(await led.call("clt_bob", "read_status", cid))["change_id"] == str(cid)


# ============================================================================ (l) approval type and MFA flag
async def test_b6l_the_approval_type_is_derived_by_the_server_and_stored_with_the_approval_and_the_event(led):
    cid = await led.approved()
    row = await led.conn.fetchrow("SELECT approval_type, mfa_verified FROM change_ledger.approvals WHERE change_id=$1", cid)
    assert (row["approval_type"], row["mfa_verified"]) == ("TEST_LANE_AUTO", False)       # a clone target
    ev = jl(await led.conn.fetchval("SELECT payload FROM change_ledger.events WHERE change_id=$1 AND "
                                    "event_type='APPROVED'", cid))
    assert (ev["approval_type"], ev["mfa_verified"]) == ("TEST_LANE_AUTO", False)
    await led.conn.execute("UPDATE change_ledger.principals SET mfa=true WHERE principal='clt_carol'")
    c2 = await led.approved(approver="clt_carol", request_id="l2", base="base-2")
    assert await count(led, "SELECT mfa_verified FROM change_ledger.approvals WHERE change_id=$1", c2) is True
    # a staging target: HUMAN, and TEST_LANE_AUTO cannot be stored for it even by a superuser insert
    await led.conn.execute("INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,"
                           "target_class) VALUES('T1','C1','stg-1',$1,'STAGING')", ORG)
    s = await led.propose(base="stg-1", declare_class=False)
    await led.call("clt_alice", "declare_target_class", s, "STAGING")
    assert await led.call("clt_alice", "validate", s) == "VALIDATED"
    nonce = await led.call("clt_bob", "issue_approval_nonce", s)
    await led.call("clt_bob", "approve", s, nonce, await led.approval_digest(s))
    assert await count(led, "SELECT approval_type FROM change_ledger.approvals WHERE change_id=$1", s) == "HUMAN"
    await led.conn.execute("INSERT INTO change_ledger.approval_nonces(nonce,change_id,approver,expires_at) "
                           "VALUES('n-lane',$1,'clt_bob',now()+interval '1 hour')", s)
    await fails("NOT_ENTITLED", led.conn.execute(
        "INSERT INTO change_ledger.approvals(change_id,approver,nonce,digest,decision,approval_type) "
        "VALUES($1,'clt_bob','n-lane',repeat('a',64),'APPROVE','TEST_LANE_AUTO')", s))


# ============================================================================ (m) evidence size bound
async def test_b6m_oversized_evidence_is_refused_before_it_is_stored(led):
    cid, tok, _ = await led.dispatched(request_id="sz1")
    await fails("SCHEMA_INVALID", led.evidence(cid, "FIELD", {"matches": True, "pad": "x" * 20000}))
    assert await count(led, "SELECT count(*) FROM change_ledger.evidence_records WHERE change_id=$1 AND kind='FIELD'",
                       cid) == 0
    assert await led.evidence(cid, "FIELD", {"matches": True, "pad": "x" * 1000}) is not None
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLIED"


# ============================================================================ (n) advisory locks, two-int form
async def test_b6n_every_advisory_lock_uses_the_two_int_form_with_a_namespace_constant(led):
    holder = await led.db.connect()
    try:
        hl = L(SimpleNamespace(conn=holder))
        tr = holder.transaction()
        await tr.start()
        await hl.validated(request_id="lk1")                                             # key lock + chain lock
        await hl.call("clt_wrk", "declare_anchor_gap", None, json.dumps({}))             # hold lock
        await hl.call("clt_dave", "kill_switch", "STOP_ADMIT")                           # kill-switch lock
        rows = await holder.fetch("SELECT classid::int AS ns, objsubid FROM pg_locks WHERE pid=pg_backend_pid() "
                                  "AND locktype='advisory'")
        assert {r["ns"] for r in rows} == {1, 2, 3, 4}
        assert {r["objsubid"] for r in rows} == {2}                                      # two-int form only
        await tr.rollback()
    finally:
        await holder.close()


# ============================================================================ (o) TRUNCATE guards
@pytest.mark.parametrize("tbl", ["checkpoints", "approvals", "change_closures", "override_bindings"])
async def test_b6o_truncate_is_refused_on_the_insert_only_objects(led, tbl):
    await fails("IMMUTABLE_LEDGER", led.conn.execute(f"TRUNCATE change_ledger.{tbl}"))


# ============================================================================ (p) indexes
async def test_b6p_the_sweep_and_lookup_indexes_exist(led):
    defs = {r["indexname"]: r["indexdef"] for r in await led.conn.fetch(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='change_ledger'")}
    partial = {"claim_tokens_issued_idx": "ISSUED", "dispatch_permits_permitted_idx": "PERMITTED",
               "records_exec_idx": "APPLYING", "records_expiry_idx": "NOT_STARTED",
               "records_repair_idx": "repair_for IS NOT NULL", "records_parent_idx": "parent_change_id IS NOT NULL"}
    for name, frag in partial.items():
        assert name in defs and "WHERE" in defs[name] and frag in defs[name], name
    for name in ("reservations_grant_idx", "approvals_change_idx", "witness_cosigns_change_idx",
                 "sweep_runs_scope_idx", "holds_open_uniq"):
        assert name in defs, name


# ============================================================================ (q) port inside a transaction
async def test_b6q_the_port_refuses_a_connection_that_is_already_in_a_transaction(led):
    cid = await led.propose()
    port = SqlChangeLedger(led.conn, {"auditor": "clt_aud"})
    scope = Scope(T, C)
    st = await port.read_status(scope, cid, as_class="auditor")
    assert st["change_id"] == str(cid)
    before = await led.conn.fetchval("SELECT current_user")
    async with led.conn.transaction():
        with pytest.raises(LedgerError) as e:
            await port.read_status(scope, cid, as_class="auditor")
        assert e.value.code == "TRANSACTION_ACTIVE"
        assert await led.conn.fetchval("SELECT current_user") == before                   # no assumed role leaked
        assert await led.conn.fetchval("SELECT current_setting('change_ledger.tenant_id', true)") in (None, "")
    assert (await port.read_status(scope, cid, as_class="auditor"))["change_id"] == str(cid)
