"""Focused PostgreSQL tests for db/phase2/010_registry_session_hardening.sql: the three OPEN items left by B3 round 1
(docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md, batch B).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied and the actors of
test_change_ledger_sql._setup. Superuser access arranges only what no API can produce (a back-dated proposal, a cosign row
without a session, tampering probes) and reads results; it never removes a guard. A "session" below is a login role
assumed with SET LOCAL SESSION AUTHORIZATION followed by SET LOCAL ROLE <actor>: session_user is the login, the actor
is the registered principal, exactly the SET ROLE shape B3 closes for approvals.

Item -> tests:
  C1 registry changes need two persons: c1_direct_*, c1_dual_*, c1_bootstrap_*, c1_replay_*, c1_immutable_*
  C2 session independence of the cosign paths: c2_operator_resolve_*, c2_close_failed_verify_*, c2_anchor_release_*,
     c2_witness_*, c2_cosign_without_session_*
  C3 key-lock exclusion by business-key collision: NOT implemented (see the report); c3_pin_* pins the behaviour that
     was verified in 008/009 so that a later change cannot silently weaken it.
"""
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from _ed25519_fixtures import pub_hex
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_hardening_b2_sql import hold_of, restored_ledger
from test_change_ledger_sql import BASE, C, C2, ORG, T, T2, L, _setup, sha

pytestmark = pytest.mark.integration

NEW_KEY = pub_hex("vk-new")      # a synthetic Ed25519 public key (lane TEST): since 015 the only kind a new key may be


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


async def login(led, name, *member_of):
    """A NOLOGIN session identity that is a member of the given actor roles (fixture)."""
    name = f"{name}_{uuid.uuid4().hex[:8]}"          # roles are cluster-wide: a unique name per test database
    await led.conn.execute(f'CREATE ROLE "{name}" NOLOGIN')
    for r in member_of:
        await led.conn.execute(f'GRANT "{r}" TO "{name}"')
    return name


async def sess(led, who, role, fn, *args, t=T, c=C):
    """One call as actor `role` inside the session of login `who` (session_user = who)."""
    marks = ",".join(f"${i + 3}" for i in range(len(args)))
    async with led.conn.transaction():
        await led.conn.execute(f'SET LOCAL SESSION AUTHORIZATION "{who}"')
        await led.conn.execute(f'SET LOCAL ROLE "{role}"')
        await led.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
        return await led.conn.fetchval(f"SELECT change_ledger.{fn}($1,$2{',' if args else ''}{marks})", t, c, *args)


def principal_params(principal, person, caps, active=True):
    return json.dumps({"principal": principal, "person_id": person, "capabilities": caps, "active": active})


async def propose(led, kind, params, role="clt_dave", t=T, c=C):
    cid = await led.call(role, "propose_registry_change", kind, params if isinstance(params, str) else json.dumps(params),
                         t=t, c=c)
    dg = await led.conn.fetchval("SELECT params_digest FROM change_ledger.registry_changes WHERE change_id=$1", cid)
    return cid, dg


async def count(led, sql, *args):
    return await led.conn.fetchval(sql, *args)


async def principal_row(led, name, t=T, c=C):
    return await led.conn.fetchrow("SELECT * FROM change_ledger.principals WHERE tenant_id=$1 AND company_id=$2 AND "
                                   "principal=$3", t, c, name)


async def events(led, etype):
    rows = await led.conn.fetch("SELECT payload FROM change_ledger.events WHERE event_type=$1 ORDER BY seq", etype)
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"] for r in rows]


# ============================================================================ C1: one operator cannot widen the registry
async def test_c1_direct_widening_by_one_operator_is_refused_and_writes_nothing(led):
    n_events = await count(led, "SELECT count(*) FROM change_ledger.events")
    # a new principal
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_principal", "clt_wrk", "person-wrk",
                                                ["approver"], True))
    # a capability that was not there / another person / re-activation
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_principal", "clt_alice", "person-clt_alice",
                                                ["requester", "approver"], True))
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_principal", "clt_alice", "person-clt_bob",
                                                ["requester"], True))
    await led.arrange_principal("clt_mallory", "person-clt_mallory", ["requester"], False)
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_principal", "clt_mallory", "person-clt_mallory",
                                                ["requester"], True))
    # a new target, a target class change (clone -> production) and a revival of a revoked target
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_target", "base-new", ORG, "CLONE", "ACTIVE", None))
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_target", "base-1", ORG, "PROD", "ACTIVE", None))
    assert await count(led, "SELECT target_class FROM change_ledger.targets WHERE base_fingerprint='base-1'") == "DISPOSABLE_CLONE"
    # a new verifier key
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_verifier_key", "vk-new", "clt_wrk", NEW_KEY))
    assert await count(led, "SELECT count(*) FROM change_ledger.verifier_keys WHERE key_id='vk-new'") == 0
    assert await count(led, "SELECT count(*) FROM change_ledger.targets WHERE base_fingerprint='base-new'") == 0
    assert (await principal_row(led, "clt_wrk")) is None
    assert (await principal_row(led, "clt_alice"))["capabilities"] == ["requester"]
    assert await count(led, "SELECT count(*) FROM change_ledger.events WHERE event_type IN ('PRINCIPAL_REGISTERED',"
                       "'TARGET_REGISTERED','VERIFIER_KEY_REGISTERED') AND seq>$1", n_events) == 1   # only the arrangement
    # a non-operator still has no EXECUTE at all, and validation still comes first for an operator
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.call("clt_alice", "register_principal", "clt_wrk", "p", ["approver"], True)
    await fails("SCHEMA_INVALID", led.call("clt_dave", "register_principal", "clt_wrk", "p", ["boss"], True))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "register_target", "b", ORG, "SANDBOX", "ACTIVE", None))


async def test_c1_direct_narrowing_and_exact_repeats_stay_single_operator(led):
    # same person, fewer capabilities (the operator and witness capabilities of an active operator must stay), deactivation
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_principal", "clt_dave", "person-clt_dave",
                                                ["operator", "requester"], True))       # drops recovery_witness
    await led.call("clt_dave", "register_principal", "clt_dave", "person-clt_dave", ["operator", "recovery_witness"], True)
    await led.call("clt_dave", "register_principal", "clt_mallory", "person-clt_mallory", ["requester"], False)
    assert (await principal_row(led, "clt_mallory"))["active"] is False
    # revocation of a registered target, a shorter permission, an exact repeat of a key
    far = datetime.now(UTC) + timedelta(days=2)
    await led.conn.execute("UPDATE change_ledger.targets SET permission_expires_at=$1 WHERE base_fingerprint='base-2'", far)
    await led.call("clt_dave", "register_target", "base-2", ORG, "CLONE", "ACTIVE", far - timedelta(days=1))
    await led.call("clt_dave", "register_target", "base-3", ORG, "CLONE", "REVOKED", None)
    assert await count(led, "SELECT status FROM change_ledger.targets WHERE base_fingerprint='base-3'") == "REVOKED"
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_target", "base-3", ORG, "CLONE", "ACTIVE", None))
    await fails("TWO_PERSON_REQUIRED", led.call("clt_dave", "register_target", "base-2", ORG, "CLONE", "ACTIVE", None))
    await led.call("clt_dave", "register_verifier_key", "vk-wrk", "clt_wrk", pub_hex("vk-wrk"))
    await fails("FORBIDDEN_TRANSITION", led.call("clt_dave", "register_verifier_key", "vk-wrk", "clt_wrk", NEW_KEY))
    await led.call("clt_dave", "revoke_verifier_key", "vk-wrk")        # revocation only narrows


async def test_c1_dual_change_needs_a_second_person_and_is_applied_by_the_second(led):
    params = principal_params("clt_wrk", "person-wrk", ["approver"])
    cid, dg = await propose(led, "PRINCIPAL", params)
    assert (await principal_row(led, "clt_wrk")) is None                 # a proposal changes nothing
    row = await led.conn.fetchrow("SELECT kind, proposer, proposer_person, summary FROM change_ledger.registry_changes "
                                  "WHERE change_id=$1", cid)
    assert (row["kind"], row["proposer"], row["proposer_person"]) == ("PRINCIPAL", "clt_dave", "person-clt_dave")
    got = json.loads(await led.call("clt_erin", "approve_registry_change", cid, dg))
    assert got["kind"] == "PRINCIPAL" and got["replay"] is False and got["digest"] == dg and got["epoch"] >= 1
    r = await principal_row(led, "clt_wrk")
    assert (r["person_id"], r["capabilities"], r["active"], r["registered_by"]) == ("person-wrk", ["approver"], True, "clt_erin")
    ap = await led.conn.fetchrow("SELECT * FROM change_ledger.registry_change_approvals WHERE change_id=$1", cid)
    me = await led.conn.fetchval("SELECT session_user::text")
    assert (ap["approver"], ap["approver_person"], ap["proposer"], ap["proposer_person"], ap["params_digest"]) == (
        "clt_erin", "person-clt_erin", "clt_dave", "person-clt_dave", dg)
    assert ap["approver_session"] == me and ap["proposer_session"] == me
    prop = [e for e in await events(led, "REGISTRY_CHANGE_PROPOSED") if e["registry_change_id"] == str(cid)]
    done = [e for e in await events(led, "REGISTRY_CHANGE_APPLIED") if e["registry_change_id"] == str(cid)]
    assert len(prop) == 1 and len(done) == 1
    assert (done[0]["proposer_person"], done[0]["approver_person"], done[0]["digest"]) == (
        "person-clt_dave", "person-clt_erin", dg)
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True
    # a target and a verifier key take the same road; the key material never reaches the summary
    far = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    out = await led.dual("TARGET", {"base": "base-new", "organization": ORG, "class": "prod", "status": "ACTIVE",
                                    "permission_expires_at": far})
    assert out["kind"] == "TARGET"
    assert await count(led, "SELECT target_class FROM change_ledger.targets WHERE base_fingerprint='base-new'") == "PRODUCTION"
    out = await led.dual("VERIFIER_KEY", {"key_id": "vk-new", "role_name": "clt_wrk", "key_material": NEW_KEY})
    assert out["kind"] == "VERIFIER_KEY"
    assert await count(led, "SELECT role_name FROM change_ledger.verifier_keys WHERE key_id='vk-new'") == "clt_wrk"
    summary = await led.conn.fetchval("SELECT summary FROM change_ledger.registry_changes WHERE kind='VERIFIER_KEY'")
    summary = json.loads(summary) if isinstance(summary, str) else summary
    assert "key_material" not in summary and summary["key_material_sha256"] == sha(NEW_KEY)
    ev = json.dumps(await events(led, "REGISTRY_CHANGE_APPLIED"))
    assert NEW_KEY not in ev


async def test_c1_dual_change_refusals(led):
    params = principal_params("clt_wrk", "person-wrk", ["approver"])
    cid, dg = await propose(led, "PRINCIPAL", params)

    def approve(role="clt_erin", digest=dg, change=cid):
        return led.call(role, "approve_registry_change", change, digest)

    await fails("APPROVER_NOT_INDEPENDENT", approve("clt_dave"))                     # the proposer is the same person
    with pytest.raises(asyncpg.InsufficientPrivilegeError):                          # not an operator: no EXECUTE
        await approve("clt_bob")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.call("clt_bob", "propose_registry_change", "PRINCIPAL", params)
    await fails("DIGEST_MISMATCH", approve(digest="f" * 64))
    await fails("CHANGE_NOT_FOUND", approve(change=uuid.uuid4()))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "propose_registry_change", "BOGUS", params))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "propose_registry_change", "PRINCIPAL",
                                           principal_params("clt_wrk", "p", ["boss"])))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "propose_registry_change", "TARGET",
                                           json.dumps({"base": "b", "organization": ORG, "class": "SANDBOX",
                                                       "status": "ACTIVE", "permission_expires_at": None})))
    # an alias of the proposer (another account of the same person) is not a second person
    await led.arrange_principal("clt_erin", "person-clt_dave", ["operator", "recovery_witness"])
    await fails("APPROVER_NOT_INDEPENDENT", approve())
    # the approver needs the operator capability; the proposer must still be an operator
    await led.arrange_principal("clt_erin", "person-clt_erin", ["recovery_witness"])
    await fails("NOT_ENTITLED", approve())
    await led.arrange_principal("clt_erin", "person-clt_erin", ["operator", "recovery_witness"])
    await led.arrange_principal("clt_dave", "person-clt_dave", ["requester"])
    await fails("NOT_ENTITLED", approve())
    await led.arrange_principal("clt_dave", "person-clt_dave", ["operator", "requester", "recovery_witness"])
    # an expired proposal cannot be approved (the table is immutable: the fixture lifts the trigger for one UPDATE)
    await led.conn.execute("ALTER TABLE change_ledger.registry_changes DISABLE TRIGGER registry_changes_immutable")
    await led.conn.execute("UPDATE change_ledger.registry_changes SET expires_at=clock_timestamp()-interval '1 second' "
                           "WHERE change_id=$1", cid)
    await led.conn.execute("ALTER TABLE change_ledger.registry_changes ENABLE TRIGGER registry_changes_immutable")
    await fails("APPROVAL_EXPIRED", approve())
    assert (await principal_row(led, "clt_wrk")) is None
    assert await count(led, "SELECT count(*) FROM change_ledger.registry_change_approvals") == 0
    # a fresh proposal is a new one (the expired one is not replayed) and now goes through
    cid2, dg2 = await propose(led, "PRINCIPAL", params)
    assert cid2 != cid and dg2 == dg
    await led.call("clt_erin", "approve_registry_change", cid2, dg2)
    assert (await principal_row(led, "clt_wrk")) is not None


async def test_c1_dual_change_in_one_login_session_is_refused_even_through_two_actor_roles(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    b = await login(led, "clt_login_b", "clt_erin")
    params = principal_params("clt_wrk", "person-wrk", ["approver"])
    cid = await sess(led, a, "clt_dave", "propose_registry_change", "PRINCIPAL", params)
    dg = await led.conn.fetchval("SELECT params_digest FROM change_ledger.registry_changes WHERE change_id=$1", cid)
    assert await led.conn.fetchval("SELECT proposer_session FROM change_ledger.registry_changes WHERE change_id=$1",
                                   cid) == a
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):      # different persons, one session
        await sess(led, a, "clt_erin", "approve_registry_change", cid, dg)
    assert (await principal_row(led, "clt_wrk")) is None
    got = json.loads(await sess(led, b, "clt_erin", "approve_registry_change", cid, dg))
    assert got["replay"] is False and (await principal_row(led, "clt_wrk")) is not None
    ap = await led.conn.fetchrow("SELECT approver_session, proposer_session FROM change_ledger.registry_change_approvals")
    assert (ap["approver_session"], ap["proposer_session"]) == (b, a)


async def test_c1_bootstrap_lets_the_only_operator_add_a_second_operator_and_nothing_else(led):
    for r in ("clt_dave", "clt_erin"):
        await led.conn.execute("SELECT change_ledger.add_role_scope($1,$2,$3)", r, T2, C2)

    def reg(principal, person, caps):
        return led.call("clt_dave", "register_principal", principal, person, caps, True, t=T2, c=C2)

    await fails("TWO_PERSON_REQUIRED", reg("clt_bob", "P-B", ["approver"]))            # not an operator capability
    await reg("clt_dave", "P-D", ["operator"])                                         # the first operator person
    await fails("TWO_PERSON_REQUIRED", reg("clt_bob", "P-B", ["approver"]))            # still not
    await reg("clt_erin", "P-E", ["operator", "recovery_witness"])                    # the second person
    await fails("TWO_PERSON_REQUIRED", reg("clt_carol", "P-C", ["operator"]))          # two persons exist: no bootstrap
    out = await led.dual("PRINCIPAL", {"principal": "clt_bob", "person_id": "P-B", "capabilities": ["approver"],
                                       "active": True}, t=T2, c=C2)
    assert out["replay"] is False
    assert (await principal_row(led, "clt_bob", T2, C2))["person_id"] == "P-B"
    # the other scope is unaffected by this one
    assert (await principal_row(led, "clt_bob", T, C)) is not None and await count(
        led, "SELECT count(*) FROM change_ledger.principals WHERE tenant_id=$1 AND person_id='P-D'", T) == 0


async def test_c1_one_operator_cannot_remove_the_second_operator_and_reopen_the_bootstrap(led):
    for r in ("clt_dave", "clt_erin"):
        await led.conn.execute("SELECT change_ledger.add_role_scope($1,$2,$3)", r, T2, C2)

    def reg(principal, person, caps, active=True):
        return led.call("clt_dave", "register_principal", principal, person, caps, active, t=T2, c=C2)

    await reg("clt_dave", "P-D", ["operator"])
    await reg("clt_erin", "P-E", ["operator", "recovery_witness"])
    # deactivating, or stripping the operator or witness capability of an active operator person is a two-person change
    await fails("TWO_PERSON_REQUIRED", reg("clt_erin", "P-E", ["operator", "recovery_witness"], False))
    await fails("TWO_PERSON_REQUIRED", reg("clt_erin", "P-E", ["recovery_witness"]))
    await fails("TWO_PERSON_REQUIRED", reg("clt_erin", "P-E", ["operator"]))
    await fails("TWO_PERSON_REQUIRED", reg("clt_dave", "P-D", ["operator"], False))      # also for oneself
    row = await principal_row(led, "clt_erin", T2, C2)
    assert row["active"] is True and sorted(row["capabilities"]) == ["operator", "recovery_witness"]
    # so the count stays at two and the bootstrap stays closed
    await fails("TWO_PERSON_REQUIRED", reg("clt_carol", "P-C", ["operator"]))
    # the exact repeat stays allowed
    await reg("clt_erin", "P-E", ["operator", "recovery_witness"])


async def test_c1_replay_is_idempotent_for_proposal_and_approval(led):
    params = principal_params("clt_wrk", "person-wrk", ["approver"])
    cid, dg = await propose(led, "PRINCIPAL", params)
    again, dg2 = await propose(led, "PRINCIPAL", json.loads(params))                  # same content, any key order
    assert again == cid and dg2 == dg
    assert await count(led, "SELECT count(*) FROM change_ledger.registry_changes") == 1
    assert len([e for e in await events(led, "REGISTRY_CHANGE_PROPOSED")]) == 1
    first = json.loads(await led.call("clt_erin", "approve_registry_change", cid, dg))
    n_ev, n_ap = await count(led, "SELECT count(*) FROM change_ledger.events"), 1
    second = json.loads(await led.call("clt_erin", "approve_registry_change", cid, dg))
    assert first["replay"] is False and second["replay"] is True and second["digest"] == dg
    assert await count(led, "SELECT count(*) FROM change_ledger.events") == n_ev              # nothing applied twice
    assert await count(led, "SELECT count(*) FROM change_ledger.registry_change_approvals") == n_ap
    assert len([e for e in await events(led, "PRINCIPAL_REGISTERED") if e["principal"] == "clt_wrk"]) == 1
    # another operator cannot ride on the stored approval; the digest is still checked first
    await fails("FORBIDDEN_TRANSITION", led.call("clt_dave", "approve_registry_change", cid, dg))
    await fails("DIGEST_MISMATCH", led.call("clt_erin", "approve_registry_change", cid, "0" * 64))
    # proposing the same content after it was applied is a new proposal (a later re-registration)
    third, _ = await propose(led, "PRINCIPAL", params)
    assert third != cid
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True


async def test_c1_immutable_tables_are_closed_to_every_writer_and_the_params_are_unreadable(led):
    cid, dg = await propose(led, "VERIFIER_KEY", {"key_id": "vk-new", "role_name": "clt_wrk", "key_material": NEW_KEY})
    await led.call("clt_erin", "approve_registry_change", cid, dg)
    for stmt in ("UPDATE change_ledger.registry_changes SET kind='TARGET'", "DELETE FROM change_ledger.registry_changes",
                 "TRUNCATE change_ledger.registry_changes",
                 "UPDATE change_ledger.registry_change_approvals SET approver='x'",
                 "DELETE FROM change_ledger.registry_change_approvals",
                 "TRUNCATE change_ledger.registry_change_approvals"):
        with pytest.raises(asyncpg.PostgresError):                                       # superuser too: the trigger
            await led.conn.execute(stmt)
    for role in ("clt_dave", "clt_erin", "clt_aud"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, "SELECT params FROM change_ledger.registry_changes")
        rows = await led.sql(role, "SELECT kind, summary, params_digest FROM change_ledger.registry_changes")
        assert len(rows) == 1 and rows[0]["params_digest"] == dg
        assert len(await led.sql(role, "SELECT change_id FROM change_ledger.registry_change_approvals")) == 1
    for role in ("clt_dave", "clt_alice", "clt_bob", "clt_wri", "clt_wrk"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, "INSERT INTO change_ledger.registry_change_approvals(change_id,tenant_id,company_id,"
                                "approver,approver_session,proposer,proposer_session,params_digest) "
                                f"VALUES('{cid}','T1','C1','x','x','y','y',repeat('a',64))")
    # another scope sees nothing of it (row-level security)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.sql("clt_zed", "SELECT change_id FROM change_ledger.registry_changes", t=T2, c=C2)
    for role in ("clt_alice", "clt_bob", "clt_wri"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.call(role, "propose_registry_change", "PRINCIPAL", principal_params("clt_wrk", "p", ["approver"]))
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.call(role, "approve_registry_change", cid, dg)


# ============================================================================ C2: sessions of the cosign paths
async def witness(led, cid, who, cls="a"):
    """A recovery-witness cosign signed by actor clt_erin inside the session of login `who`."""
    comp = await led.evidence(cid, "COMPLETION_PROOF", {"class": cls, "result_returned": False}, role="clt_wri")
    return await sess(led, who, "clt_erin", "witness_cosign_signed", cid, comp)


async def test_c2_operator_resolve_refuses_the_session_of_the_witness(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    b = await login(led, "clt_login_b", "clt_dave")
    cid, _, _ = await led.triage(request_id="c2-or")                # alice requested; the signed observation exists
    w = await witness(led, cid, a)
    assert await led.conn.fetchval("SELECT signer_session FROM change_ledger.witness_cosigns WHERE cosign_id=$1", w) == a
    # different persons dave / erin, but ONE session: refused, the cosign is not consumed, nothing is released
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, a, "clt_dave", "operator_resolve", cid, w, True, False)
    assert await led.conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns WHERE cosign_id=$1", w)
    assert await led.open_holds("CALL_OWNERSHIP") == 1
    assert (await led.rec(cid))["execution_state"] == "TRIAGE_REQUIRED"
    # another session resolves with the same cosign
    assert await sess(led, b, "clt_dave", "operator_resolve", cid, w, True, False) == "APPLIED"
    assert await led.open_holds("CALL_OWNERSHIP") == 0
    assert await led.conn.fetchval("SELECT consumed_at IS NOT NULL FROM change_ledger.witness_cosigns WHERE cosign_id=$1", w)


async def test_c2_the_witness_and_the_operator_may_not_share_the_session_of_the_requester(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    b = await login(led, "clt_login_b", "clt_dave", "clt_erin")
    cid, _, _ = await led.triage(request_id="c2-req")
    await led.conn.execute("UPDATE change_ledger.records SET requester_session=$2 WHERE change_id=$1", cid, a)
    # a witness inside the proposing session is refused when it signs, and nothing is stored
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await witness(led, cid, a)
    assert await count(led, "SELECT count(*) FROM change_ledger.witness_cosigns WHERE change_id=$1", cid) == 0
    w = await witness(led, cid, b)
    # the operator inside the proposing session is refused when it consumes
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, a, "clt_dave", "operator_resolve", cid, w, True, False)
    c3 = await login(led, "clt_login_c", "clt_dave")
    assert await sess(led, c3, "clt_dave", "operator_resolve", cid, w, True, False) == "APPLIED"


async def test_c2_a_cosign_without_a_recorded_session_cannot_be_consumed_by_a_real_session(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    b = await login(led, "clt_login_b", "clt_dave")
    cid, _, _ = await led.triage(request_id="c2-null")
    w = await witness(led, cid, a)
    await led.conn.execute("UPDATE change_ledger.witness_cosigns SET signer_session=NULL WHERE cosign_id=$1", w)
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, b, "clt_dave", "operator_resolve", cid, w, True, False)
    assert (await led.rec(cid))["execution_state"] == "TRIAGE_REQUIRED"


async def test_c2_the_signer_session_is_taken_from_the_database_not_from_the_caller(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    cid, _, _ = await led.triage(request_id="c2-rec")
    w = await witness(led, cid, a)
    assert await led.conn.fetchval("SELECT signer_session FROM change_ledger.witness_cosigns WHERE cosign_id=$1", w) == a
    me = await led.conn.fetchval("SELECT session_user::text")
    w2 = await led.cosign("clt_erin", cid)                          # a superuser session records its own login
    assert await led.conn.fetchval("SELECT signer_session FROM change_ledger.witness_cosigns WHERE cosign_id=$1", w2) == me


async def test_c2_close_failed_verify_refuses_the_session_of_the_witness(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    b = await login(led, "clt_login_b", "clt_dave")
    cid, tok, _ = await led.dispatched(request_id="c2-cf", base="base-1")
    await led.complete(cid, tok["generation"], "SUCCESS")
    assert await led.verify(cid, False) == "FAILED_VERIFY"
    w = await witness(led, cid, a)
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, a, "clt_dave", "operator_close_failed_verify", cid, w, True)
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert await sess(led, b, "clt_dave", "operator_close_failed_verify", cid, w, True) == "CLOSED"
    assert await led.open_holds("FAILED_VERIFY_HALT") == 0


async def test_c2_anchor_gap_release_refuses_the_session_of_the_cosigner(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    b = await login(led, "clt_login_b", "clt_dave")
    _, anchored, _ = await restored_ledger(led)
    hold = await hold_of(led, "base-1")
    good = {"class": "a", "reconciliation": "lost events accounted from the archive of the external sink",
            "ext_seq": anchored["seq"], "ext_head_hash": anchored["head_hash"]}
    cos = await sess(led, a, "clt_erin", "anchor_gap_cosign", hold, json.dumps(good))
    assert await led.conn.fetchval("SELECT signer_session FROM change_ledger.hold_cosigns WHERE cosign_id=$1", cos) == a
    release = json.dumps({"two_person_cosign": str(cos)})
    with pytest.raises(asyncpg.PostgresError, match="APPROVER_NOT_INDEPENDENT"):
        await sess(led, a, "clt_dave", "release_hold", hold, release)
    assert await hold_of(led, "base-1") == hold
    assert await led.conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.hold_cosigns WHERE cosign_id=$1", cos)
    assert await sess(led, b, "clt_dave", "release_hold", hold, release) is not None
    assert await hold_of(led, "base-1") is None


# ============================================================================ C3: not implemented; verified behaviour pinned
async def test_c3_pin_the_same_business_key_on_one_base_is_parked_and_the_key_lock_excludes_a_second_claim(led):
    key = sha("shared-business-key")
    first = await led.propose(request_id="k1", key=key)
    assert await led.call("clt_alice", "validate", first) == "VALIDATED"
    second = await led.propose(request_id="k2", key=key, target="doc2")
    assert await led.call("clt_alice", "validate", second) == "DUPLICATE_PARKED"
    # another base is another key space
    other = await led.propose(request_id="k3", key=key, base="base-2", target="doc3")
    assert await led.call("clt_alice", "validate", other) == "VALIDATED"
    # the first change holds the key lock from its claim on: no other change can take it
    nonce = await led.call("clt_bob", "issue_approval_nonce", first)
    await led.call("clt_bob", "approve", first, nonce, await led.approval_digest(first))
    await led.claimed(first)
    assert await count(led, "SELECT count(*) FROM change_ledger.key_locks WHERE owner_change_id=$1", first) == 1
    with pytest.raises(asyncpg.UniqueViolationError):
        await led.conn.execute("INSERT INTO change_ledger.key_locks(tenant_id,company_id,base_fingerprint,key_hash,"
                               "owner_change_id) VALUES($1,$2,$3,$4,$5)", T, C, BASE, key, second)
