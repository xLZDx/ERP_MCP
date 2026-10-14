"""Focused PostgreSQL integration tests for db/phase2/005_change_registry.sql (schema change_ledger).

Contract: docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md revision 6. Needs ERP_PHASE2_TEST_DSN (a
superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when ERP_PHASE2_REQUIRE_PG=1.
Every test gets its own throwaway database (g1x_<uuid8>) with all migrations of the harness applied; runtime
actors are the NOLOGIN roles (clt_*) of test_change_ledger_sql.py assumed with SET LOCAL ROLE. Superuser access
is used only to arrange state no API can produce (clock back-dating, target expiry by passing time) and to read.
Reconciled with db/phase2/007_change_hardening_a.sql (S13 batch A): ledger-computed approval digest, typed evidence
bound to generation and call id, signed completion / verification / cosign paths only, checkpoint identity.
Covers: principal registry / person independence, target registry, epoch dependencies and T15 revoke, signed
evidence, status/evidence reads and RLS, duplicate detection with approver-bound override, amount_consumed.
"""
import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from _pg_harness import FILES, MIGRATIONS, fails, require_dsn, throwaway_db
from test_change_ledger_sql import (
    BASE,
    BASES,
    C,
    C2,
    DEFAULT_GRANT,
    DIGEST,
    KH,
    ORG,
    SIGN_KEYS,
    T,
    T2,
    L,
    _failed_parent,
    _setup,
    exp,
)

pytestmark = pytest.mark.integration

KEYS = {"clt_wrk": ("vk-wrk", "W" * 32), "clt_wri": ("vk-wri", "R" * 32)}
NEW_TABLES = ["epochs", "principals", "registry_policy", "verifier_keys", "evidence_records", "business_keys",
              "override_bindings", "target_observations"]
_D = object()   # "use the current value" marker for generation / call id of a forged evidence record


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def js(v):
    return json.loads(v) if isinstance(v, str) else v


class R(L):
    """L (test_change_ledger_sql.py, reconciled for 007) plus the registry helpers.

    Evidence goes through L.evidence (typed, generation / call-id bound, signed with SIGN_KEYS) for ordinary flows;
    `pack` / `put` / `rec_ev` below build a record argument by argument so a test can corrupt one element."""

    async def jcall(self, role, name, *args, **kw):
        return js(await self.call(role, name, *args, **kw))

    async def reg(self, principal, person, caps, active=True):
        return await self.call("clt_dave", "register_principal", principal, person, caps, active)

    async def bind(self, cid, kind, ch, at, gen, call_id):
        return await self.conn.fetchval("SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
                                        cid, kind, ch, at, gen, call_id)

    async def pack(self, cid, kind, content=None, *, role="clt_wrk", gen=_D, call_id=_D, at=None, ch=None,
                   key_id=None, key_material=None, bind=None, sig=None, nonce=False):
        """The ordered record_evidence arguments after (t, c, change_id) as a dict; every element overridable."""
        content = dict(content or {})
        if kind == "AUTH_RECEIPT":
            gen = None if gen is _D else gen
            call_id = None if call_id is _D else call_id
        else:
            if gen is _D:
                gen = (await self.rec(cid))["claim_generation"]
            if call_id is _D:
                call_id = await self.call_id_of(cid)
        if kind in ("COMPLETION_PROOF", "OBSERVATION"):
            content = {"generation": gen, "call_id": str(call_id), **content}
        if nonce:
            content["nonce"] = uuid.uuid4().hex
        at = at or datetime.now(UTC) + timedelta(seconds=1)
        ch = ch or await self.conn.fetchval("SELECT change_ledger.canonical_content_hash($1::jsonb)",
                                            json.dumps(content))
        kid, kmat, _ = SIGN_KEYS[role]
        b = bind or await self.bind(cid, kind, ch, at, gen, call_id)
        s = sig if sig is not None else sha(f"{key_material or kmat}:{b}")
        return {"kind": kind, "ch": ch, "at": at, "content": json.dumps(content), "key_id": key_id or kid,
                "bind": b, "sig": s, "gen": gen, "call_id": call_id}

    async def put(self, role, cid, packed):
        return await self.call(role, "record_evidence", cid, *packed.values())

    async def rec_ev(self, cid, kind, content=None, role="clt_wrk", **kw):
        return await self.put(role, cid, await self.pack(cid, kind, content, role=role, **kw))

    async def grant(self, amount=100000):
        gid = uuid.uuid4()
        await self.call("clt_dave", "budget_admin", gid, "EUR", amount, 50, 50,
                        datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC) + timedelta(hours=1))
        return gid

    async def effect_tail(self, cid, tok, call_id=None, outcome="SUCCESS"):
        """begin_apply -> checkpoint -> permit -> DISPATCHED -> complete (writer); returns the call id."""
        call_id = call_id or uuid.uuid4()
        await self.call("clt_alice", "begin_apply", tok["token_id"], call_id, "h", "s")
        await self.checkpoint()
        await self.call("clt_wrk", "issue_permit", cid, tok["generation"])
        assert await self.call("clt_wri", "record_call", cid, tok["generation"], call_id) is True
        assert await self.complete(cid, tok["generation"], outcome) == "APPLIED"
        return call_id

    async def run(self, cid, grant=None, amount=None, verify=True, key=KH):
        tok = await self.claimed(cid, key=key, grant=grant, amount=amount)
        await self.effect_tail(cid, tok)
        if verify is not None:
            await self.verify(cid, verify)      # signed FIELD / MOVEMENT / VERSION records with matches = verify
        return tok

    async def target_expiry(self, base, when):
        await self.conn.execute("UPDATE change_ledger.targets SET permission_expires_at=$2 WHERE base_fingerprint=$1",
                                base, when)

    async def chain_ok(self):
        got = await self.jcall("clt_aud", "verify_chain")
        assert got["ok"] is True, got


@pytest.fixture
async def reg():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        r = R(db)
        for role, (kid, kmat) in KEYS.items():       # _setup already stored them: registering again is a no-op
            await r.call("clt_dave", "register_verifier_key", kid, role, kmat)
        yield r


# ============================================================================ schema / privileges
async def test_005_is_recorded_hardened_idempotent_and_not_directly_writable(reg):
    c = reg.conn
    assert await c.fetchval("SELECT count(*) FROM living.schema_migrations WHERE version='005'") == 1
    rows = await c.fetch("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner) o "
                         "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                         "WHERE n.nspname='change_ledger' AND c.relname = ANY($1)", NEW_TABLES)
    assert {r["relname"] for r in rows} == set(NEW_TABLES)
    for r in rows:
        assert r["relrowsecurity"] and r["relforcerowsecurity"] and r["o"] == "ledger_owner", r["relname"]
    bad = await c.fetch("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                        "WHERE n.nspname='change_ledger' AND NOT (p.prosecdef AND p.proconfig::text LIKE "
                        "'%search_path=pg_catalog%')")
    assert not bad
    # no runtime role may EXECUTE the internal helpers of this migration
    for fn in ("bump_epoch_internal", "revoke_core", "assert_target_effect", "evidence_ref", "assert_capability",
               "assert_independent", "evidence_binding", "norm_target_class",
               # 007 (A1): the raw completion / verification / cosign variants became internals of the signed ones
               "complete", "resolve_unknown", "verify", "witness_cosign"):
        got = await c.fetch(
            "SELECT r.rolname FROM pg_roles r JOIN pg_proc p ON p.proname=$1 JOIN pg_namespace n ON "
            "n.oid=p.pronamespace AND n.nspname='change_ledger' WHERE r.rolname = ANY($2) AND "
            "has_function_privilege(r.rolname, p.oid, 'EXECUTE')", fn,
            ["requester_role", "approver_role", "operator_role", "writer_role", "worker_role", "auditor_role"])
        assert not got, (fn, [g[0] for g in got])
    # re-applying the identical file is a recorded no-op
    raw = (MIGRATIONS / "005_change_registry.sql").read_bytes()
    before = await c.fetchval("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                              "WHERE n.nspname='change_ledger'")
    await c.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await c.execute(raw.decode("utf-8"))
    assert await c.fetchval("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                            "WHERE n.nspname='change_ledger'") == before
    assert "005_change_registry.sql" in FILES


@pytest.mark.parametrize("role", ["clt_alice", "clt_bob", "clt_dave", "clt_wri", "clt_wrk", "clt_aud"])
async def test_no_direct_dml_on_the_new_tables(reg, role):
    cid = await reg.propose()
    stmts = [
        "INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id) VALUES('T1','C1','x','p')",
        "UPDATE change_ledger.principals SET active=false",
        "DELETE FROM change_ledger.principals",
        "UPDATE change_ledger.registry_policy SET enforced=false",
        "INSERT INTO change_ledger.registry_policy(tenant_id,company_id,enforced) VALUES('T1','C1',true)",
        "INSERT INTO change_ledger.epochs(tenant_id,company_id,epoch_key,value) VALUES('T1','C1','k',1)",
        "UPDATE change_ledger.epochs SET value=0",
        "DELETE FROM change_ledger.epochs",
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES('T1','C1','x','r',repeat('k',16))",
        "UPDATE change_ledger.verifier_keys SET status='REVOKED'",
        "DELETE FROM change_ledger.evidence_records",
        "UPDATE change_ledger.evidence_records SET kind='FIELD'",
        f"INSERT INTO change_ledger.evidence_records(tenant_id,company_id,change_id,kind,content_hash,observed_at,"
        f"signer_key_id,signature,binding_hash,recorded_by) VALUES('T1','C1','{cid}','FIELD',repeat('a',64),now(),"
        f"'k','s',repeat('a',64),'x')",
        "UPDATE change_ledger.business_keys SET key_hash=repeat('a',64)",
        f"INSERT INTO change_ledger.override_bindings(change_id,approver,override_digest) "
        f"VALUES('{cid}','x',repeat('a',64))",
        "DELETE FROM change_ledger.target_observations",
        "UPDATE change_ledger.records SET declared_target_class='PRODUCTION'",
        "UPDATE change_ledger.records SET epoch_dependencies='{}'::jsonb",
        "UPDATE change_ledger.targets SET permission_expires_at=NULL",
        "SELECT change_ledger.bump_epoch_internal('T1','C1','k')",
        f"SELECT change_ledger.revoke_core('T1','C1','{cid}','EPOCH_DEPENDENCY')",
    ]
    for s in stmts:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await reg.sql(role, s)


@pytest.mark.parametrize("role,fn,args", [
    ("clt_alice", "register_principal", "'x','p',ARRAY['approver'],true"),
    ("clt_alice", "enforce_registry", ""),
    ("clt_alice", "register_target", "'b','o','CLONE','ACTIVE',NULL"),
    ("clt_alice", "register_verifier_key", "'k','clt_wrk',repeat('k',16)"),
    ("clt_alice", "bump_epoch", "'k'"),
    ("clt_alice", "revoke_stale", ""),
    ("clt_alice", "revoke_change", "gen_random_uuid(),'EPOCH_DEPENDENCY'"),
    ("clt_alice", "record_evidence", "gen_random_uuid(),'FIELD',repeat('a',64),now(),'{}'::jsonb,'k',repeat('a',64),'s',1,gen_random_uuid()"),
    ("clt_alice", "amount_consumed", "'d',gen_random_uuid()"),
    ("clt_alice", "bind_duplicate_override", "gen_random_uuid(),repeat('a',64)"),
    ("clt_alice", "verify_signed", "gen_random_uuid(),NULL,NULL,NULL"),
    ("clt_bob", "declare_business_key", "gen_random_uuid(),repeat('a',64),NULL,NULL"),
    ("clt_bob", "declare_target_class", "gen_random_uuid(),'CLONE'"),
    ("clt_bob", "record_evidence", "gen_random_uuid(),'FIELD',repeat('a',64),now(),'{}'::jsonb,'k',repeat('a',64),'s',1,gen_random_uuid()"),
    ("clt_bob", "read_evidence", "gen_random_uuid()"),
    ("clt_bob", "revoke_change", "gen_random_uuid(),'EPOCH_DEPENDENCY'"),
    ("clt_wri", "register_target", "'b','o','CLONE','ACTIVE',NULL"),
    ("clt_wri", "bump_epoch", "'k'"),
    ("clt_wri", "verify_signed", "gen_random_uuid(),NULL,NULL,NULL"),
    ("clt_wri", "read_status", "gen_random_uuid()"),
    ("clt_wri", "resolve_unknown_signed", "gen_random_uuid(),gen_random_uuid(),NULL,true,false"),
    ("clt_wrk", "register_principal", "'x','p',ARRAY['approver'],true"),
    ("clt_wrk", "bump_epoch", "'k'"),
    ("clt_wrk", "complete_signed", "gen_random_uuid(),1,'SUCCESS',gen_random_uuid()"),
    ("clt_wrk", "observe_target", "gen_random_uuid(),'b','CLONE'"),
    ("clt_wrk", "declare_target_class", "gen_random_uuid(),'CLONE'"),
    ("clt_aud", "record_evidence", "gen_random_uuid(),'FIELD',repeat('a',64),now(),'{}'::jsonb,'k',repeat('a',64),'s',1,gen_random_uuid()"),
    ("clt_aud", "revoke_change", "gen_random_uuid(),'EPOCH_DEPENDENCY'"),
    ("clt_aud", "register_principal", "'x','p',ARRAY['approver'],true"),
    ("clt_erin", "approve", "gen_random_uuid(),'x','x'"),
    # 007 (A1): the raw completion / verification / cosign variants are closed to every runtime role
    ("clt_wri", "complete", "gen_random_uuid(),1,'SUCCESS','{}'::jsonb,NULL"),
    ("clt_wrk", "resolve_unknown", "gen_random_uuid(),'{}'::jsonb,true,false"),
    ("clt_wrk", "verify", "gen_random_uuid(),'{}'::jsonb,true"),
    ("clt_erin", "witness_cosign", "gen_random_uuid(),'{}'::jsonb"),
    # 007 (A6): only the checkpoint identity records checkpoints
    ("clt_wrk", "record_checkpoint", "1,repeat('a',64),'REAL','s','vk-wrk','x',now(),true"),
])
async def test_new_operations_are_closed_to_other_caller_classes(reg, role, fn, args):
    pre = "'T1','C1'" + ("," + args if args else "")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await reg.sql(role, f"SELECT change_ledger.{fn}({pre})")


async def test_verifier_key_material_is_never_readable_and_keys_are_write_once(reg):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await reg.sql("clt_aud", "SELECT key_material FROM change_ledger.verifier_keys")
    rows = await reg.sql("clt_aud", "SELECT key_id, role_name, status FROM change_ledger.verifier_keys ORDER BY 1")
    # the shared _setup also stores the checkpoint identity's key (vk-chk) since 007 (A6)
    assert [tuple(r) for r in rows] == [("vk-chk", "checkpoint_role", "ACTIVE"), ("vk-wri", "clt_wri", "ACTIVE"),
                                        ("vk-wrk", "clt_wrk", "ACTIVE")]
    # same key again: no-op; a different material for the same id is refused; a bad key is refused
    await reg.call("clt_dave", "register_verifier_key", "vk-wrk", "clt_wrk", KEYS["clt_wrk"][1])
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_dave", "register_verifier_key", "vk-wrk", "clt_wrk", "x" * 32))
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "register_verifier_key", "k2", "clt_wrk", "short"))
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "register_verifier_key", "k2", "no_such_role", "x" * 32))


# ============================================================================ (1) principal registry
async def test_person_independence_replaces_role_name_distinctness(reg):
    await reg.reg("clt_alice", "P-1", ["requester"])
    await reg.reg("clt_bob", "P-1", ["approver"])            # a second account of the SAME person
    cid = await reg.validated()
    await fails("APPROVER_NOT_INDEPENDENT", reg.call("clt_bob", "issue_approval_nonce", cid))
    # capability and active flag: a registered principal without the capability or inactive is refused
    await reg.reg("clt_carol", "P-3", ["operator"])
    await fails("NOT_ENTITLED", reg.call("clt_carol", "issue_approval_nonce", cid))
    await reg.reg("clt_carol", "P-3", ["approver"], False)
    await fails("NOT_ENTITLED", reg.call("clt_carol", "issue_approval_nonce", cid))
    # bob becomes a distinct person: a nonce is issued; then he is aliased again before approving
    await reg.reg("clt_bob", "P-2", ["approver"])
    nonce = await reg.call("clt_bob", "issue_approval_nonce", cid)
    await reg.reg("clt_bob", "P-1", ["approver"])
    dg = await reg.approval_digest(cid)        # 007 (A7): the digest is computed by the ledger, not opaque
    await fails("APPROVER_NOT_INDEPENDENT", reg.call("clt_bob", "approve", cid, nonce, dg))
    await reg.reg("clt_bob", "P-2", ["approver"], False)
    await fails("NOT_ENTITLED", reg.call("clt_bob", "approve", cid, nonce, dg))
    assert (await reg.rec(cid))["authorization_state"] == "NONE"
    await reg.reg("clt_bob", "P-2", ["approver"])
    aid = await reg.call("clt_bob", "approve", cid, nonce, dg)
    r = await reg.rec(cid)
    assert r["authorization_state"] == "APPROVED"
    deps = js(r["epoch_dependencies"])
    assert set(deps) == {f"target:{BASE}", "principal:clt_alice", "principal:clt_bob"}
    assert deps["principal:clt_bob"] == await reg.conn.fetchval(
        "SELECT value FROM change_ledger.epochs WHERE epoch_key='principal:clt_bob'")
    assert await reg.conn.fetchval("SELECT approver FROM change_ledger.approvals WHERE approval_id=$1", aid) == "clt_bob"
    # registration itself: operator-only content rules
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "register_principal", "clt_bob", "P", ["boss"], True))
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "register_principal", "ghost", "P", ["approver"], True))
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "register_principal", "clt_bob", "", ["approver"], True))
    assert await reg.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE "
                                   "event_type='PRINCIPAL_REGISTERED'") >= 7
    await reg.chain_ok()


async def test_repair_approver_must_be_a_different_person_than_the_failed_parents_requester(reg):
    parent = await _failed_parent(reg)                       # requested by clt_alice
    await reg.reg("clt_carol", "P-same", ["approver"])
    await reg.reg("clt_alice", "P-same", ["requester"])      # carol is the same person as the parent's requester
    rep = await reg.validated(kind="UNPOST", parent=parent, repair_for=parent, request_id="rep-x",
                              requester="clt_mallory", target="doc1")
    nonce = await reg.call("clt_carol", "issue_approval_nonce", rep)
    dg = await reg.approval_digest(rep)
    await fails("APPROVER_NOT_INDEPENDENT", reg.call("clt_carol", "approve", rep, nonce, dg))
    nonce_b = await reg.call("clt_bob", "issue_approval_nonce", rep)
    dg_b = await reg.approval_digest(rep)      # 009: the digest binds the nonce, so bob's nonce has its own text
    assert dg_b != dg
    await reg.call("clt_bob", "approve", rep, nonce_b, dg_b)
    assert (await reg.rec(rep))["authorization_state"] == "APPROVED"


async def test_operator_resolve_compares_persons_and_capabilities(reg):
    cid, _, _ = await reg.triage(request_id="p-or")           # requested by clt_alice, TRIAGE_REQUIRED
    await reg.reg("clt_dave", "P-OP", ["operator"])
    await reg.reg("clt_erin", "P-OP", ["operator", "recovery_witness"])   # witness is the operator's alias
    # 007 (A1): the witness signs through witness_cosign_signed over a signed completion proof (class a, writer);
    # triage() already recorded the signed OBSERVATION (effect_present = true) that operator_resolve(present) needs
    w = await reg.cosign("clt_erin", cid)
    await fails("APPROVER_NOT_INDEPENDENT", reg.call("clt_dave", "operator_resolve", cid, w, True, False))
    # the witness is the requester's alias
    await reg.reg("clt_alice", "P-REQ", ["requester"])
    await reg.reg("clt_erin", "P-WIT", ["operator", "recovery_witness"])
    await reg.reg("clt_carol", "P-REQ", ["operator", "recovery_witness"])
    await reg.conn.execute("GRANT operator_role TO clt_carol")
    wc = await reg.cosign("clt_carol", cid)
    await fails("APPROVER_NOT_INDEPENDENT", reg.call("clt_dave", "operator_resolve", cid, wc, True, False))
    # capability: a witness without recovery_witness cannot even sign
    await reg.reg("clt_erin", "P-WIT", ["operator"])
    await fails("NOT_ENTITLED", reg.cosign("clt_erin", cid))
    await reg.reg("clt_erin", "P-WIT", ["operator", "recovery_witness"])
    good = await reg.cosign("clt_erin", cid)
    # the operator without the operator capability is refused, nothing is released
    await reg.reg("clt_dave", "P-OP", ["approver"])
    await fails("NOT_ENTITLED", reg.call("clt_dave", "operator_resolve", cid, good, True, False))
    assert await reg.open_holds("CALL_OWNERSHIP") == 1
    await reg.reg("clt_dave", "P-OP", ["operator"])
    assert await reg.call("clt_dave", "operator_resolve", cid, good, True, False) == "APPLIED"
    assert await reg.open_holds("CALL_OWNERSHIP") == 0


async def test_enforced_registry_refuses_unregistered_actors_and_cannot_be_switched_off(reg):
    assert await reg.call("clt_dave", "enforce_registry") is True
    assert await reg.call("clt_dave", "enforce_registry") is True            # idempotent
    # 008: the fixtures register every actor (an unregistered scope is enforced by default); arrange "not registered"
    await reg.conn.execute("DELETE FROM change_ledger.principals WHERE principal IN ('clt_alice','clt_bob','clt_mallory')")
    await fails("NOT_ENTITLED", reg.propose())                               # alice is not registered
    await reg.reg("clt_alice", "P-A", ["requester"])
    cid = await reg.validated(declare_class=False)
    await fails("NOT_ENTITLED", reg.call("clt_bob", "issue_approval_nonce", cid))   # bob is not registered
    await reg.reg("clt_bob", "P-B", ["approver"])
    # class declaration must precede approval (it is inside the approved digest) and match the registry
    await fails("SCHEMA_INVALID", reg.call("clt_alice", "declare_target_class", cid, "BOGUS"))
    await fails("TARGET_REJECTED", reg.call("clt_alice", "declare_target_class", cid, "PROD"))
    await fails("NOT_ENTITLED", reg.call("clt_mallory", "declare_target_class", cid, "CLONE"))
    assert await reg.call("clt_alice", "declare_target_class", cid, "CLONE") == "DISPOSABLE_CLONE"
    nonce = await reg.call("clt_bob", "issue_approval_nonce", cid)
    await reg.call("clt_bob", "approve", cid, nonce, await reg.approval_digest(cid))
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_alice", "declare_target_class", cid, "CLONE"))
    # a change that never declared a class cannot take effect once the registry is enforced
    nocls = await reg.approved(request_id="nocls", base="base-2", declare_class=False)
    await fails("TARGET_REJECTED", reg.claimed(nocls))
    tok = await reg.claimed(cid, observe=False)
    await fails("TARGET_REJECTED", reg.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s"))
    await fails("TARGET_REJECTED", reg.call("clt_wri", "observe_target", tok["token_id"], "base-2", "CLONE"))
    await fails("TARGET_REJECTED", reg.call("clt_wri", "observe_target", tok["token_id"], BASE, "PROD"))
    await fails("TARGET_REJECTED", reg.call("clt_wri", "observe_target", tok["token_id"], BASE, "STAGING"))
    await fails("SCHEMA_INVALID", reg.call("clt_wri", "observe_target", tok["token_id"], BASE, "BOGUS"))
    assert await reg.conn.fetchval("SELECT count(*) FROM change_ledger.target_observations") == 0
    assert await reg.call("clt_wri", "observe_target", tok["token_id"], BASE, "CLONE") is True
    assert await reg.call("clt_wri", "observe_target", tok["token_id"], BASE, "CLONE") is True   # idempotent
    await reg.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s")
    assert (await reg.rec(cid))["execution_state"] == "APPLYING"
    # the switch is one-way: no API turns it off and the row cannot be rewritten by a runtime role
    assert await reg.conn.fetchval("SELECT enforced FROM change_ledger.registry_policy") is True
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await reg.sql("clt_dave", "UPDATE change_ledger.registry_policy SET enforced=false")
    await reg.chain_ok()


# ============================================================================ (2) target registry
async def test_register_target_normalizes_classes_and_limits_proposals(reg):
    far = datetime.now(UTC) + timedelta(days=1)
    await reg.call("clt_dave", "register_target", "base-new", ORG, "CLONE", "ACTIVE", far)
    await reg.call("clt_dave", "register_target", "base-prod", ORG, "prod", "ACTIVE", None)
    rows = await reg.conn.fetch("SELECT base_fingerprint, target_class FROM change_ledger.targets "
                                "WHERE base_fingerprint IN ('base-new','base-prod') ORDER BY 1")
    assert [tuple(r) for r in rows] == [("base-new", "DISPOSABLE_CLONE"), ("base-prod", "PRODUCTION")]
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "register_target", "b", ORG, "SANDBOX", "ACTIVE", None))
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "register_target", "b", ORG, "CLONE", "PAUSED", None))
    # registered organization is binding at proposal; a mismatch or an expired permission is refused
    args = (uuid.uuid4(), "CREATE_DRAFT", "base-new", "other-org", "clt_alice", "r", DIGEST, "d", "v1", None, exp(), None)
    await fails("TARGET_REJECTED", reg.call("clt_alice", "propose", *args))
    assert await reg.propose(base="base-new") is not None
    await reg.call("clt_dave", "register_target", "base-new", ORG, "CLONE", "ACTIVE",
                   datetime.now(UTC) - timedelta(seconds=1))
    await fails("TARGET_REJECTED", reg.propose(base="base-new", request_id="late"))
    await reg.call("clt_dave", "register_target", "base-new", ORG, "CLONE", "REVOKED", far)
    await fails("TARGET_REJECTED", reg.propose(base="base-new", request_id="revoked"))
    assert await reg.conn.fetchval("SELECT epoch FROM change_ledger.targets WHERE base_fingerprint='base-new'") == 2
    assert await reg.conn.fetchval("SELECT value FROM change_ledger.epochs WHERE epoch_key='target:base-new'") == 3


async def test_effects_are_limited_to_the_registered_target_at_every_effect_step(reg):
    cid = await reg.validated(request_id="eff", target="doc-eff")
    assert await reg.call("clt_alice", "declare_target_class", cid, "clone") == "DISPOSABLE_CLONE"
    nonce = await reg.call("clt_bob", "issue_approval_nonce", cid)
    await reg.call("clt_bob", "approve", cid, nonce, await reg.approval_digest(cid))
    past =datetime.now(UTC) - timedelta(seconds=1)
    # claim: expiry, revocation and organization drift each refuse and leave nothing behind
    for col, bad, good in (("permission_expires_at", past, None), ("status", "REVOKED", "ACTIVE"),
                           ("organization_ref", "drifted", ORG)):
        await reg.conn.execute(f"UPDATE change_ledger.targets SET {col}=$1 WHERE base_fingerprint=$2", bad, BASE)
        await fails("TARGET_REJECTED", reg.claimed(cid))
        assert await reg.locks(cid) == (0, 0, 0) and (await reg.rec(cid))["authorization_state"] == "APPROVED"
        await reg.conn.execute(f"UPDATE change_ledger.targets SET {col}=$1 WHERE base_fingerprint=$2", good, BASE)
    # a class declared at declare time must still equal the registry at claim time
    await reg.conn.execute("UPDATE change_ledger.targets SET target_class='PRODUCTION' WHERE base_fingerprint=$1", BASE)
    await fails("TARGET_REJECTED", reg.claimed(cid))
    await reg.conn.execute("UPDATE change_ledger.targets SET target_class='DISPOSABLE_CLONE' WHERE base_fingerprint=$1",
                           BASE)
    tok = await reg.claimed(cid)
    call_id = uuid.uuid4()
    await reg.target_expiry(BASE, past)
    await fails("TARGET_REJECTED", reg.call("clt_alice", "begin_apply", tok["token_id"], call_id, "h", "s"))
    await reg.target_expiry(BASE, None)
    await reg.call("clt_alice", "begin_apply", tok["token_id"], call_id, "h", "s")
    await reg.checkpoint()
    await reg.target_expiry(BASE, past)
    await fails("TARGET_REJECTED", reg.call("clt_wrk", "issue_permit", cid, tok["generation"]))
    await reg.target_expiry(BASE, None)
    await reg.call("clt_wrk", "issue_permit", cid, tok["generation"])
    await reg.target_expiry(BASE, past)
    await fails("TARGET_REJECTED", reg.call("clt_wri", "record_call", cid, tok["generation"], call_id))
    assert (await reg.rec(cid))["dispatch_state"] == "PERMITTED"       # the refusal wrote nothing
    await reg.target_expiry(BASE, None)
    assert await reg.call("clt_wri", "record_call", cid, tok["generation"], call_id) is True


# ============================================================================ (3) epochs and T15
async def test_only_listed_epoch_dependencies_void_a_change(reg):
    gid = await reg.grant()
    assert await reg.call("clt_dave", "bump_epoch", "source:other") == 1
    assert await reg.call("clt_dave", "bump_epoch", "source:other") == 2
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "bump_epoch", ""))
    # an unrelated epoch never touches the change
    a = await reg.approved(request_id="e1")
    await reg.call("clt_dave", "bump_epoch", "source:unrelated")
    assert await reg.call("clt_wrk", "revoke_stale") == 0
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_wrk", "revoke_change", a, "EPOCH_DEPENDENCY"))
    tok_a = await reg.claimed(a, grant=gid, amount=10)
    assert tok_a["generation"] == 1
    await reg.call("clt_alice", "release_claim", tok_a["token_id"])
    # a listed dependency: added before approval, bumped afterwards
    b = await reg.validated(request_id="e2", base="base-2")
    deps = js(await reg.call("clt_alice", "add_epoch_dependency", b, "source:s1"))
    assert "source:s1" in deps and js(await reg.call("clt_alice", "add_epoch_dependency", b, "source:s1")) == deps
    await fails("NOT_ENTITLED", reg.call("clt_mallory", "add_epoch_dependency", b, "source:s2"))
    nonce = await reg.call("clt_bob", "issue_approval_nonce", b)
    await reg.call("clt_bob", "approve", b, nonce, await reg.approval_digest(b))   # the listed dependency is inside it
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_alice", "add_epoch_dependency", b, "source:s2"))
    await reg.call("clt_dave", "bump_epoch", "source:s1")
    await fails("EPOCH_CHANGED", reg.claimed(b, key="c" * 64, grant=gid, amount=10))
    assert await reg.locks(b) == (0, 0, 0) and await reg.res_state(b) is None
    # the approver's entitlement is a dependency from the approval on
    c = await reg.approved(request_id="e3", base="base-3")
    assert "principal:clt_bob" in js((await reg.rec(c))["epoch_dependencies"])
    await reg.reg("clt_bob", "P-B", ["approver"])
    await fails("EPOCH_CHANGED", reg.claimed(c, key="d" * 64))
    # sweep: voids exactly the stale ones (b and c), never the unrelated one
    assert await reg.call("clt_wrk", "revoke_stale") == 3   # b, c and a (a was approved by bob)
    assert await reg.call("clt_wrk", "revoke_stale") == 0
    for x in (a, b, c):
        assert (await reg.rec(x))["authorization_state"] == "VOIDED"
        await fails("APPROVAL_VOIDED", reg.claimed(x, key="e" * 64))
    assert await reg.call("clt_wrk", "revoke_change", b, "EPOCH_DEPENDENCY") == "VOIDED"       # idempotent
    # approve on a stale proposal: the target registry changed after propose
    d = await reg.validated(request_id="e4", base="base-4")
    await reg.call("clt_dave", "register_target", "base-4", ORG, "CLONE", "ACTIVE", None)
    n4 = await reg.call("clt_bob", "issue_approval_nonce", d)
    # the ledger's own digest of the stored change (007 compares the digest before the epochs): the failure left
    # is the stale registry epoch, not an opaque digest
    await fails("EPOCH_CHANGED", reg.call("clt_bob", "approve", d, n4, await reg.approval_digest(d)))
    assert (await reg.rec(d))["authorization_state"] == "NONE"
    await reg.chain_ok()


async def test_t15_revoke_voids_a_claimed_change_and_releases_everything_but_never_after_dispatch(reg):
    gid = await reg.grant()
    cid = await reg.approved(request_id="t15", target="doc-t15")
    tok = await reg.claimed(cid, grant=gid, amount=25)
    assert await reg.locks(cid) == (1, 1, 1) and await reg.res_state(cid) == "RESERVED"
    await reg.call("clt_dave", "bump_epoch", f"target:{BASE}")
    await fails("EPOCH_CHANGED", reg.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s"))
    await fails("NOT_ENTITLED", reg.call("clt_wrk", "revoke_change", cid, "ROLE_REVOKED"))     # worker: epoch only
    await fails("SCHEMA_INVALID", reg.call("clt_dave", "revoke_change", cid, "BECAUSE"))
    assert await reg.call("clt_wrk", "revoke_change", cid, "EPOCH_DEPENDENCY") == "VOIDED"
    r = await reg.rec(cid)
    assert (r["authorization_state"], r["execution_state"], r["reservation_state"]) == ("VOIDED", "NOT_STARTED", "RELEASED")
    assert await reg.locks(cid) == (0, 0, 0) and await reg.res_state(cid) == "RELEASED"
    assert await reg.conn.fetchval("SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1",
                                   tok["token_id"]) == "SUPERSEDED"
    await fails("TICKET_SUPERSEDED", reg.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s"))
    await fails("APPROVAL_VOIDED", reg.claimed(cid))
    # operator-asserted causes revoke (not void) an APPROVED change
    o = await reg.approved(request_id="t15o", base="base-2")
    assert await reg.call("clt_dave", "revoke_change", o, "SESSION_REVOKED") == "REVOKED"
    await fails("APPROVAL_VOIDED", reg.claimed(o, key="2" * 64))
    # after begin_apply or dispatch the contract has no pre-dispatch revoke: refused, nothing changes
    ap, aptok, _ = await reg.applying(request_id="t15a", base="base-3")
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_dave", "revoke_change", ap, "SESSION_REVOKED"))
    dp, _, _ = await reg.dispatched(request_id="t15d", base="base-4")
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_dave", "revoke_change", dp, "SESSION_REVOKED"))
    assert (await reg.rec(dp))["authorization_state"] == "CLAIMED" and await reg.locks(dp) == (1, 1, 1)
    # a change that was never approved has nothing to revoke
    p = await reg.propose(request_id="t15p", base="base-5")
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_dave", "revoke_change", p, "SESSION_REVOKED"))
    await reg.chain_ok()


async def test_t15_revoke_of_a_claimed_repair_hands_the_target_lock_back_to_the_parent(reg):
    parent = await _failed_parent(reg)
    rep = await reg.approved(kind="UNPOST", parent=parent, repair_for=parent, request_id="rep-t15",
                             target="doc1", approver="clt_carol")
    await reg.claimed(rep, key="5" * 64)
    assert await reg.tl_owner(BASE, "doc1") == rep
    await reg.reg("clt_carol", "P-C", ["approver"])             # bumps the approver's principal epoch
    assert await reg.call("clt_wrk", "revoke_stale") == 1
    assert await reg.tl_owner(BASE, "doc1") == parent
    assert await reg.open_holds("FAILED_VERIFY_HALT") == 1
    assert await reg.locks(rep) == (0, 0, 0)
    r = await reg.rec(rep)
    assert (r["authorization_state"], r["execution_state"]) == ("VOIDED", "NOT_STARTED")
    assert (await reg.rec(parent))["verification_state"] == "FAILED_VERIFY"


# ============================================================================ (4) signed evidence
async def test_record_evidence_refuses_unsigned_misbound_and_foreign_signatures(reg):
    # 007 (A1): a record needs the change's current generation and the call id of its permit, so the changes are
    # taken to begin_apply (permit row NOT_PERMITTED); the content is hashed and bound, generation and call id too
    cid, tok, call_id = await reg.applying(request_id="ev")
    other, otok, ocall = await reg.applying(request_id="ev2", base="base-2")
    gen = tok["generation"]
    at = datetime.now(UTC)
    body = {"matches": True, "f": 1}
    ev = await reg.rec_ev(cid, "FIELD", body, at=at)
    assert await reg.rec_ev(cid, "FIELD", body, at=at) == ev                                # idempotent
    assert await reg.conn.fetchval("SELECT count(*) FROM change_ledger.evidence_records") == 1
    assert await reg.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE event_type='EVIDENCE_RECORDED'") == 1
    ok = {"matches": True}
    # unsigned or signed by something the ledger does not trust
    await fails("EVIDENCE_UNSIGNED", reg.rec_ev(cid, "VERSION", ok, at=at, sig=""))
    a = await reg.pack(cid, "VERSION", ok, at=at)
    a["sig"] = None
    await fails("EVIDENCE_UNSIGNED", reg.put("clt_wrk", cid, a))
    a = await reg.pack(cid, "VERSION", ok, at=at)
    a["key_id"] = None
    await fails("EVIDENCE_UNSIGNED", reg.put("clt_wrk", cid, a))
    await fails("EVIDENCE_UNSIGNED", reg.rec_ev(cid, "VERSION", ok, at=at, key_id="vk-unknown"))
    await fails("EVIDENCE_UNSIGNED", reg.rec_ev(cid, "VERSION", ok, at=at, key_material="Z" * 32))   # wrong key material
    await fails("EVIDENCE_UNSIGNED", reg.rec_ev(cid, "VERSION", ok, at=at, sig="f" * 64))
    # wrongly bound: each element of (change_id, kind, content_hash, observed_at, generation, call_id) is part of the
    # binding (the last two are new in 007); a valid signature over a wrong binding does not help
    ch = (await reg.pack(cid, "VERSION", ok, at=at))["ch"]
    wrk_key = SIGN_KEYS["clt_wrk"][1]
    for bad in (await reg.bind(other, "VERSION", ch, at, gen, call_id), await reg.bind(cid, "FIELD", ch, at, gen, call_id),
                await reg.bind(cid, "VERSION", sha("x"), at, gen, call_id),
                await reg.bind(cid, "VERSION", ch, at + timedelta(microseconds=1), gen, call_id),
                await reg.bind(cid, "VERSION", ch, at, gen + 1, call_id),
                await reg.bind(cid, "VERSION", ch, at, gen, uuid.uuid4()), "0" * 64):
        await fails("DIGEST_MISMATCH", reg.rec_ev(cid, "VERSION", ok, at=at, bind=bad, sig=sha(f"{wrk_key}:{bad}")))
    # a valid signature over a binding of ANOTHER change does not help either
    cid_bind = (await reg.pack(cid, "VERSION", ok, at=at))["bind"]
    foreign = await reg.pack(other, "VERSION", ok, at=at, bind=cid_bind, sig=sha(f"{wrk_key}:{cid_bind}"))
    await fails("DIGEST_MISMATCH", reg.put("clt_wrk", other, foreign))
    # 007: content_hash must be the hash of the content, whatever is bound and signed
    await fails("DIGEST_MISMATCH", reg.rec_ev(cid, "VERSION", ok, at=at, ch=sha("not-the-content")))
    # 007: generation and call id are fenced against the change's current claim and its permit
    await fails("TICKET_SUPERSEDED", reg.rec_ev(cid, "VERSION", ok, at=at, gen=gen + 1))
    await fails("PERMIT_MISSING", reg.rec_ev(cid, "VERSION", ok, at=at, call_id=uuid.uuid4()))
    await fails("PERMIT_MISSING", reg.rec_ev(cid, "VERSION", ok, at=at, call_id=ocall))     # another change's call
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "VERSION", ok, at=at, gen=None))
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "OBSERVATION", {"effect_present": False, "generation": gen + 5}))
    # key / caller: the key belongs to one identity; the writer may record only completion proofs
    await fails("NOT_ENTITLED", reg.rec_ev(cid, "VERSION", ok, role="clt_wrk", key_id="vk-wri", key_material="R" * 32))
    await fails("NOT_ENTITLED", reg.rec_ev(cid, "FIELD", ok, role="clt_wri"))
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "BOGUS", ok))
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "FIELD", ok, at=datetime.now(UTC) + timedelta(hours=1)))
    await fails("CHANGE_NOT_FOUND", reg.rec_ev(uuid.uuid4(), "FIELD", ok, gen=1, call_id=uuid.uuid4()))
    # a revoked key stops signing at once
    await reg.call("clt_dave", "revoke_verifier_key", "vk-wrk")
    await fails("EVIDENCE_UNSIGNED", reg.rec_ev(cid, "OBSERVATION", {"effect_present": False}))
    assert await reg.conn.fetchval("SELECT count(*) FROM change_ledger.evidence_records") == 1
    # records are immutable even for the superuser path
    await fails("IMMUTABLE_LEDGER", reg.conn.execute("UPDATE change_ledger.evidence_records SET content='{}'::jsonb"))
    await fails("IMMUTABLE_LEDGER", reg.conn.execute("DELETE FROM change_ledger.evidence_records"))
    await fails("IMMUTABLE_LEDGER", reg.conn.execute("TRUNCATE change_ledger.evidence_records"))
    await reg.chain_ok()


async def test_completion_proof_class_and_auth_receipt_rules(reg):
    cid, tok, call_id = await reg.applying(request_id="cp")      # 007: records need a generation and a permit row
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "COMPLETION_PROOF", {}))
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "COMPLETION_PROOF", {"class": "c", "result_returned": False}))  # forced kill: disabled
    await fails("NOT_ENTITLED", reg.rec_ev(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": False}, role="clt_wrk"))
    await fails("NOT_ENTITLED", reg.rec_ev(cid, "COMPLETION_PROOF", {"class": "b", "result_returned": False}, role="clt_wri"))
    # 007: a missing result_returned / matches key must be refused (NULL comparison used to fail open)
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "COMPLETION_PROOF", {"class": "b"}, role="clt_wrk"))
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "FIELD", {"k": "v"}))
    # 007: the typed content needs result_returned and the generation / call id inside the content must match
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "COMPLETION_PROOF",
                                              {"class": "b", "result_returned": False, "generation": 99}, role="clt_wrk"))
    assert await reg.rec_ev(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": False}, role="clt_wri")
    assert await reg.rec_ev(cid, "COMPLETION_PROOF", {"class": "b", "result_returned": False}, role="clt_wrk")
    await fails("SCHEMA_INVALID", reg.rec_ev(cid, "AUTH_RECEIPT", {"approval_id": str(uuid.uuid4())}))
    aid = await reg.conn.fetchval("SELECT approval_id FROM change_ledger.approvals WHERE change_id=$1", cid)
    assert await reg.rec_ev(cid, "AUTH_RECEIPT", {"approval_id": str(aid)})


# ============================================================================ (5) reads and RLS
async def test_read_status_and_read_evidence_are_scoped_and_rls_filters_direct_reads(reg):
    # 007: evidence needs a generation and a permit row, so the change is read at CLAIMED / APPLYING
    cid, tok, _ = await reg.applying(request_id="rd")                    # alice's, approved by bob
    mine2 = await reg.propose(request_id="rd2", base="base-2", requester="clt_mallory")
    ev = await reg.rec_ev(cid, "FIELD", {"matches": True, "k": "v"})
    st = await reg.jcall("clt_alice", "read_status", cid)
    assert (st["lifecycle"], st["authorization"], st["execution"], st["verification"], st["dispatch"],
            st["reservation"], st["call_ownership"], st["attribution"]) == \
        ("VALIDATED", "CLAIMED", "APPLYING", "NOT_VERIFIED", "NOT_PERMITTED", "RESERVED", "NONE", "NOT_APPLICABLE")  # 008: claim reserves
    assert st["approver"] == "clt_bob" and st["evidence_count"] == 1 and st["epoch_current"] is True
    assert st["requester"] == "clt_alice" and st["open_holds"] == 0
    assert st["approval_digest"] == await reg.approval_digest(cid)       # 007 (A7): the ledger-computed digest
    assert await reg.jcall("clt_aud", "read_status", cid) == st
    assert (await reg.jcall("clt_bob", "read_status", cid))["change_id"] == str(cid)
    await fails("CHANGE_NOT_FOUND", reg.call("clt_mallory", "read_status", cid))          # not leaked to another requester
    await fails("CHANGE_NOT_FOUND", reg.call("clt_alice", "read_status", mine2))
    await fails("CHANGE_NOT_FOUND", reg.call("clt_alice", "read_status", uuid.uuid4()))
    await fails("SCOPE_NOT_GRANTED", reg.call("clt_zed", "read_status", cid))             # tenant isolation
    # the epoch flag turns false once a listed dependency moves
    await reg.call("clt_dave", "bump_epoch", f"target:{BASE}")
    assert (await reg.jcall("clt_aud", "read_status", cid))["epoch_current"] is False
    # read_evidence
    out = await reg.jcall("clt_alice", "read_evidence", cid)
    assert [e["evidence_id"] for e in out] == [str(ev)] and out[0]["kind"] == "FIELD"
    assert out[0]["content"] == {"matches": True, "k": "v"}
    assert "key_material" not in json.dumps(out)
    assert await reg.jcall("clt_aud", "read_evidence", cid) == out
    await fails("CHANGE_NOT_FOUND", reg.call("clt_mallory", "read_evidence", cid))
    assert await reg.jcall("clt_mallory", "read_evidence", mine2) == []
    # RLS on direct reads: owner requester and auditor see the row; others and other tenants do not
    q = "SELECT evidence_id FROM change_ledger.evidence_records"
    assert [r[0] for r in await reg.sql("clt_alice", q)] == [ev]
    assert [r[0] for r in await reg.sql("clt_aud", q)] == [ev]
    assert await reg.sql("clt_mallory", q) == []
    assert await reg.sql("clt_zed", q, t=T2, c=C2) == []
    assert await reg.sql("clt_aud", q, t=None) == []                                      # no scope: nothing
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await reg.sql("clt_bob", q)


async def test_signed_wrappers_reference_records_and_extend_without_changing_004_behavior(reg):
    # ---- complete_signed: the outcome evidence is a writer-signed proof class a, typed by the outcome (007)
    cid, tok, call_id = await reg.dispatched(request_id="sw1", base="base-1")
    gen = tok["generation"]
    await fails("EVIDENCE_UNSIGNED", reg.call("clt_wri", "complete_signed", cid, gen, "SUCCESS", None))
    worker_proof = await reg.evidence(cid, "COMPLETION_PROOF", {"class": "b", "result_returned": True}, role="clt_wrk")
    await fails("COMPLETION_PROOF_MISSING", reg.call("clt_wri", "complete_signed", cid, gen, "SUCCESS", worker_proof))
    await fails("SCHEMA_INVALID", reg.call("clt_wri", "complete_signed", cid, gen, "WHATEVER", worker_proof))
    other, _, _ = await reg.dispatched(request_id="sw1o", base="base-2")
    foreign = await reg.evidence(other, "COMPLETION_PROOF", {"class": "a", "result_returned": True}, role="clt_wri")
    await fails("EVIDENCE_UNSIGNED", reg.call("clt_wri", "complete_signed", cid, gen, "SUCCESS", foreign))
    # 007 (A1): the outcome comes from the record content, not from the caller's flag
    no_result = await reg.evidence(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": False}, role="clt_wri")
    await fails("COMPLETION_PROOF_MISSING", reg.call("clt_wri", "complete_signed", cid, gen, "SUCCESS", no_result))
    await fails("WRITE_REFUSED", reg.call("clt_wri", "complete_signed", cid, gen, "PRE_WRITE_REFUSAL", no_result))
    writer_proof = await reg.evidence(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": True}, role="clt_wri")
    await fails("WRITE_REFUSED", reg.call("clt_wri", "complete_signed", cid, gen, "PRE_WRITE_REFUSAL", writer_proof))
    assert (await reg.rec(cid))["execution_state"] == "APPLYING"          # the refusals wrote nothing
    assert await reg.call("clt_wri", "complete_signed", cid, gen, "SUCCESS", writer_proof) == "APPLIED"
    ref = await reg.conn.fetchval("SELECT payload->>'evidence_id' FROM change_ledger.events WHERE change_id=$1 AND "
                                  "event_type='COMPLETE_SUCCESS'", cid)
    assert ref == str(writer_proof)
    # ---- verify_signed: field + movement + version read AFTER the effect; the verdict is derived from the records
    await fails("EVIDENCE_UNSIGNED", reg.call("clt_wrk", "verify_signed", cid, None, None, None))
    f = await reg.evidence(cid, "FIELD", {"matches": True})
    m = await reg.evidence(cid, "MOVEMENT", {"matches": True})
    v = await reg.evidence(cid, "VERSION", {"matches": True})
    await fails("EVIDENCE_UNSIGNED", reg.call("clt_wrk", "verify_signed", cid, m, f, v))      # wrong slots
    stale = await reg.evidence(cid, "VERSION", {"matches": True}, at=datetime.now(UTC) - timedelta(hours=1))
    await fails("VERIFY_FAILED", reg.call("clt_wrk", "verify_signed", cid, f, m, stale))
    assert (await reg.rec(cid))["verification_state"] == "NOT_VERIFIED"
    assert await reg.call("clt_wrk", "verify_signed", cid, f, m, v) == "VERIFIED"
    assert await reg.call("clt_wrk", "verify_signed", cid, None, None, None) == "VERIFIED"      # idempotent
    assert await reg.locks(cid) == (0, 0, 0)
    # a failed verification (007: derived from signed records with matches = false, no longer a caller flag) opens
    # the halt exactly like 004 and cannot be flipped to VERIFIED afterwards (A3)
    bad, btok, _ = await reg.dispatched(request_id="sw2", base="base-3")
    await reg.complete(bad, btok["generation"], "SUCCESS")
    assert await reg.verify(bad, False) == "FAILED_VERIFY"
    assert await reg.open_holds("FAILED_VERIFY_HALT") == 1
    await fails("FORBIDDEN_TRANSITION", reg.verify(bad, True))
    assert (await reg.rec(bad))["verification_state"] == "FAILED_VERIFY" and await reg.open_holds("FAILED_VERIFY_HALT") == 1
    # ---- resolve_unknown_signed
    u, utok, _ = await reg.unknown(request_id="sw3", base="base-4")
    obs = await reg.observation(u, False)
    await fails("COMPLETION_PROOF_MISSING", reg.call("clt_wrk", "resolve_unknown_signed", u, obs, None, False, False))
    await fails("EVIDENCE_UNSIGNED", reg.call("clt_wrk", "resolve_unknown_signed", u, None, None, False, False))
    cp_b = await reg.evidence(u, "COMPLETION_PROOF", {"class": "b", "result_returned": False}, role="clt_wrk")
    # 007: the found flag must equal the signed observation's effect_present
    await fails("DIGEST_MISMATCH", reg.call("clt_wrk", "resolve_unknown_signed", u, obs, cp_b, True, False))
    assert await reg.call("clt_wrk", "resolve_unknown_signed", u, obs, cp_b, False, False) == "FAILED_APPLY"
    assert await reg.locks(u) == (0, 0, 0)
    t2, _, _ = await reg.unknown(request_id="sw4", base="base-5")
    obs2 = await reg.observation(t2, True)
    assert await reg.call("clt_wrk", "resolve_unknown_signed", t2, obs2, None, True, True) == "TRIAGE_REQUIRED"
    # ---- witness_cosign_signed -> operator_resolve (attribution proof comes from the signed record; the verdict
    # from the signed observation recorded above)
    cp_a = await reg.evidence(t2, "COMPLETION_PROOF", {"class": "a", "result_returned": False, "attribution_proof": True},
                              role="clt_wri")
    w = await reg.call("clt_erin", "witness_cosign_signed", t2, cp_a)
    assert await reg.call("clt_dave", "operator_resolve", t2, w, True, True) == "APPLIED"
    assert (await reg.rec(t2))["attribution"] == "PROVEN"
    await fails("EVIDENCE_UNSIGNED", reg.call("clt_erin", "witness_cosign_signed", t2, f))
    await reg.chain_ok()


# ============================================================================ (6) duplicates
async def _keyed(reg, rid, key, base=BASE, target=None, kind="CREATE_DRAFT", override=None, just=None, validate=True,
                 requester="clt_alice"):
    cid = await reg.propose(request_id=rid, base=base, target=target or f"doc-{rid}", kind=kind, requester=requester)
    await reg.call(requester, "declare_business_key", cid, key, override, just)
    if validate:
        return cid, await reg.call(requester, "validate", cid)
    return cid, None


async def test_duplicate_business_key_parks_and_the_override_needs_the_approvers_binding(reg):
    k1, k2 = "1" * 64, "2" * 64
    a, st = await _keyed(reg, "a", k1)
    assert st == "VALIDATED"
    b, st = await _keyed(reg, "b", k1)
    assert st == "DUPLICATE_PARKED"
    assert await reg.call("clt_alice", "validate", b) == "DUPLICATE_PARKED"            # terminal
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_alice", "declare_business_key", b, k2, None, None))
    nonce = await reg.call("clt_bob", "issue_approval_nonce", b)
    await fails("FORBIDDEN_TRANSITION", reg.approval_digest(b))     # 009: no canonical text is stored for a parked change
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_bob", "approve", b, nonce, "e" * 64))
    # another base or another key is not a duplicate; the 004 caller flag no longer exists (008): a collision parks server-side
    assert (await _keyed(reg, "c", k1, base="base-2"))[1] == "VALIDATED"
    assert (await _keyed(reg, "d", k2))[1] == "VALIDATED"
    assert (await _keyed(reg, "e", k2))[1] == "DUPLICATE_PARKED"                                # collides with "d"
    # an override naming something else, or a pair of collisions, still parks
    assert (await _keyed(reg, "f", k1, override="not-the-colliding-change", just="reason"))[1] == "DUPLICATE_PARKED"
    # a matching override validates but needs the approver-bound digest
    o, st = await _keyed(reg, "o", k1, override=str(a), just="same supplier invoice re-issued")
    assert st == "VALIDATED"
    odg = await reg.conn.fetchval("SELECT override_digest FROM change_ledger.business_keys WHERE change_id=$1", o)
    assert odg == sha(f"{o}:{k1}:{a}:same supplier invoice re-issued")
    assert await reg.conn.fetchval("SELECT override_required FROM change_ledger.business_keys WHERE change_id=$1", o)
    n_bob = await reg.call("clt_bob", "issue_approval_nonce", o)
    dg_o = await reg.approval_digest(o)     # 007 (A7): the digest covers the key and the override (business state)
    await fails("DUPLICATE_SUSPECTED", reg.call("clt_bob", "approve", o, n_bob, dg_o))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):                                          # requester cannot bind
        await reg.call("clt_alice", "bind_duplicate_override", o, odg)
    await fails("DIGEST_MISMATCH", reg.call("clt_bob", "bind_duplicate_override", o, "9" * 64))
    assert await reg.call("clt_carol", "bind_duplicate_override", o, odg) is True
    await fails("DUPLICATE_SUSPECTED", reg.call("clt_bob", "approve", o, n_bob, dg_o))               # carol's binding is carol's
    assert await reg.call("clt_carol", "bind_duplicate_override", o, odg) is True                    # idempotent
    n_carol = await reg.call("clt_carol", "issue_approval_nonce", o)
    dg_c = await reg.approval_digest(o)        # 009: the digest binds the nonce, so carol's nonce has its own text
    assert dg_c != dg_o
    await reg.call("clt_carol", "approve", o, n_carol, dg_c)
    assert (await reg.rec(o))["authorization_state"] == "APPROVED"
    # after approval the key and the override are frozen (they are inside the digest)
    await fails("FORBIDDEN_TRANSITION", reg.call("clt_alice", "declare_business_key", o, k2, None, None))
    # claim: the declared key is the key lock; a different key argument is refused
    # (L.claimed ignores a caller key for a keyed draft, so the mismatching key is passed to claim directly)
    await fails("DIGEST_MISMATCH", reg.call("clt_alice", "claim", o, "3" * 64, DEFAULT_GRANT[(T, C)], 0, False, False))
    await reg.claimed(o, key=None)
    assert await reg.conn.fetchval("SELECT key_hash FROM change_ledger.key_locks WHERE owner_change_id=$1", o) == k1
    # shape checks
    await fails("SCHEMA_INVALID", reg.call("clt_alice", "declare_business_key", a, "short", None, None))
    await fails("SCHEMA_INVALID", reg.call("clt_alice", "declare_business_key", a, k1, "x", None))
    await fails("NOT_ENTITLED", reg.call("clt_mallory", "declare_business_key", a, k1, None, None))
    post = await reg.propose(kind="POST", parent=a, request_id="post-x", base="base-3")
    await fails("SCHEMA_INVALID", reg.call("clt_alice", "declare_business_key", post, k1, None, None))
    await reg.chain_ok()


async def test_update_draft_key_change_is_rechecked_and_the_own_document_is_not_a_collision(reg):
    k1, k2, k3 = "1" * 64, "2" * 64, "3" * 64
    a, _ = await _keyed(reg, "a", k1, target="docA")
    other, _ = await _keyed(reg, "other", k3, target="docO")
    # the update keeps the document's own key: no collision with its own history
    u, st = await _keyed(reg, "u", k1, target="docA", kind="UPDATE_DRAFT")
    assert st == "VALIDATED"
    # the update moves the document onto another document's key: parked
    u2, st = await _keyed(reg, "u2", k3, target="docA", kind="UPDATE_DRAFT")
    assert st == "DUPLICATE_PARKED"
    # a key change after validation (before approval) sends the change back to PROPOSED and re-checks
    u3, st = await _keyed(reg, "u3", k2, target="docA", kind="UPDATE_DRAFT")
    assert st == "VALIDATED"
    assert await reg.call("clt_alice", "declare_business_key", u3, k2, None, None) == "VALIDATED"     # unchanged: idempotent
    assert await reg.call("clt_alice", "declare_business_key", u3, k3, None, None) == "PROPOSED"
    assert (await reg.rec(u3))["lifecycle"] == "PROPOSED"
    ev = await reg.conn.fetchrow("SELECT payload FROM change_ledger.events WHERE change_id=$1 AND "
                                 "event_type='BUSINESS_KEY_DECLARED' ORDER BY seq DESC LIMIT 1", u3)
    assert js(ev["payload"])["key_changed"] is True and js(ev["payload"])["revalidate"] is True
    assert await reg.call("clt_alice", "validate", u3) == "DUPLICATE_PARKED"
    # rejected or voided changes no longer hold their key
    r, _ = await _keyed(reg, "r", "4" * 64)
    nonce = await reg.call("clt_bob", "issue_approval_nonce", r)
    await reg.call("clt_bob", "reject", r, nonce)
    assert (await _keyed(reg, "r2", "4" * 64))[1] == "VALIDATED"


@pytest.mark.parametrize("round_no", range(3))
async def test_concurrent_validation_of_one_business_key_validates_exactly_one(reg, round_no):
    key = sha(f"conc-{round_no}")
    ids = []
    for i in range(3):
        cid, _ = await _keyed(reg, f"c{round_no}-{i}", key, validate=False)
        ids.append(cid)
    conns = [await reg.db.connect() for _ in ids]
    try:
        res = await asyncio.gather(*[reg.call("clt_alice", "validate", cid, conn=cn)
                                     for cid, cn in zip(ids, conns, strict=True)])
    finally:
        for x in conns:
            await x.close()
    assert sorted(res) == ["DUPLICATE_PARKED", "DUPLICATE_PARKED", "VALIDATED"], res


# ============================================================================ (7) amount_consumed
async def test_amount_consumed_reconciles_post_unpost_and_repair(reg):
    gid = await reg.grant()
    other_grant = await reg.grant()

    async def consumed(doc, g=None):
        return await reg.call("clt_aud", "amount_consumed", doc, g or gid)

    draft = await reg.approved(request_id="d", target="docA", base="base-1")
    await reg.run(draft)
    assert await consumed("docA") == 0
    post1 = await reg.approved(kind="POST", parent=draft, request_id="p1", target="docA", base="base-1")
    tok = await reg.claimed(post1, grant=gid, amount=300)
    assert await reg.conn.fetchval("SELECT amount FROM change_ledger.reservations WHERE change_id=$1", post1) == 300
    assert await consumed("docA") == 0                                       # RESERVED is not consumed
    await reg.effect_tail(post1, tok)
    assert await consumed("docA") == 300 and await consumed("docA", other_grant) == 0
    assert await consumed("docB") == 0
    assert await reg.verify(post1, True) == "VERIFIED"
    # a second POST of the same document reserves only the unconsumed part (nothing)
    post2 = await reg.approved(kind="POST", parent=draft, request_id="p2", target="docA", base="base-1")
    t2 = await reg.claimed(post2, grant=gid, amount=300)
    assert await reg.conn.fetchval("SELECT amount FROM change_ledger.reservations WHERE change_id=$1", post2) == 0
    await reg.call("clt_alice", "release_claim", t2["token_id"])
    # a larger amount reserves only the difference
    post2b = await reg.approved(kind="POST", parent=draft, request_id="p2b", target="docA", base="base-1")
    t2b = await reg.claimed(post2b, grant=gid, amount=350)
    assert await reg.conn.fetchval("SELECT amount FROM change_ledger.reservations WHERE change_id=$1", post2b) == 50
    await reg.call("clt_alice", "release_claim", t2b["token_id"])
    # an applied UNPOST reverses the POST in the reconciliation; its own amount is not document consumption
    un = await reg.approved(kind="UNPOST", parent=post1, request_id="u1", target="docA", base="base-1")
    await reg.run(un, grant=gid, amount=100)
    assert await consumed("docA") == 0
    assert await reg.res_state(post1) == "CONSUMED" and await reg.res_state(un) == "CONSUMED"
    post3 = await reg.approved(kind="POST", parent=draft, request_id="p3", target="docA", base="base-1")
    await reg.claimed(post3, grant=gid, amount=300)
    assert await reg.conn.fetchval("SELECT amount FROM change_ledger.reservations WHERE change_id=$1", post3) == 300
    # a refused UNPOST (FAILED_APPLY) reverses nothing
    # ---- repair: the failed parent stays CONSUMED as history until the repair is APPLIED
    d2 = await reg.approved(request_id="d2", target="docB", base="base-2")
    await reg.run(d2)
    bad = await reg.approved(kind="POST", parent=d2, request_id="pb", target="docB", base="base-2")
    await reg.run(bad, grant=gid, amount=500, verify=False)
    assert await consumed("docB") == 500
    rep = await reg.approved(kind="UNPOST", parent=bad, repair_for=bad, request_id="rb", target="docB", base="base-2",
                             approver="clt_carol")
    rtok = await reg.claimed(rep, key="5" * 64, grant=gid, amount=50)
    assert await consumed("docB") == 500                                     # claimed is not applied
    await reg.effect_tail(rep, rtok)
    assert await consumed("docB") == 0                                       # the repair APPLIED reconciles the parent
    assert await reg.res_state(bad) == "CONSUMED"                            # history kept, not refunded
    assert (await reg.rec(bad))["verification_state"] == "FAILED_VERIFY"
    assert await reg.verify(rep, True) == "VERIFIED"
    assert await reg.open_holds("FAILED_VERIFY_HALT") == 0 and await consumed("docB") == 0
    # an UNPOST that was refused before the write does not reverse anything
    p4 = await reg.approved(kind="POST", parent=d2, request_id="p4", target="docB", base="base-2")
    await reg.run(p4, grant=gid, amount=200)
    assert await consumed("docB") == 200
    u4 = await reg.approved(kind="UNPOST", parent=p4, request_id="u4", target="docB", base="base-2")
    t4 = await reg.claimed(u4, grant=gid, amount=10)
    call = uuid.uuid4()
    await reg.call("clt_alice", "begin_apply", t4["token_id"], call, "h", "s")
    assert await reg.complete(u4, t4["generation"], "PRE_WRITE_REFUSAL", proof={"proof": "dependents"},
                              code="ROLLBACK_REFUSED") == "ROLLBACK_REFUSED"  # 007 typed record; 008 B6a: T8 outcome
    assert await consumed("docB") == 200
    await reg.chain_ok()
