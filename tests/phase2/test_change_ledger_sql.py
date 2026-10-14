"""Focused PostgreSQL integration tests for db/phase2/004_change_ledger.sql (schema change_ledger).

Contract: docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md revision 6. Needs ERP_PHASE2_TEST_DSN (a
superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when ERP_PHASE2_REQUIRE_PG=1.
Every test gets its own throwaway database (g1x_<uuid8>) with 001-004 applied; runtime actors are NOLOGIN
roles (clt_*) assumed with SET LOCAL ROLE, exactly like the living tests do. Superuser access is used only
to arrange state that no API can produce (clock back-dating, tampering) and to read results.
"""
import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from _approval_envelope import FIXTURE_DIGEST, ensure_envelope, fixture_digest_for
from _pg_harness import fails, require_dsn, throwaway_db

pytestmark = pytest.mark.integration

T, C = "T1", "C1"
T2, C2 = "T2", "C2"
ORG = "org-1"
BASE = "base-1"
BASES = [f"base-{i}" for i in range(1, 9)] + [f"race-{i}" for i in range(8)]
DIGEST = FIXTURE_DIGEST     # 009: the real payload digest of the fixture payload (target version v1), not a constant
KH = "b" * 64
HOST_PROOF_A = {"class": "a"}

ACTORS = {  # role -> (member of, scopes)
    "clt_alice": (["requester_role"], [(T, C)]),
    "clt_mallory": (["requester_role"], [(T, C)]),
    "clt_bob": (["approver_role"], [(T, C)]),
    "clt_carol": (["approver_role"], [(T, C)]),
    "clt_dave": (["operator_role", "requester_role"], [(T, C)]),
    "clt_erin": (["operator_role"], [(T, C)]),
    "clt_wri": (["writer_role"], [(T, C)]),
    "clt_wrk": (["worker_role"], [(T, C)]),
    "clt_aud": (["auditor_role"], [(T, C)]),
    "clt_both": (["requester_role", "approver_role"], [(T, C)]),
    "clt_zed": (["requester_role"], [(T2, C2)]),
    "clt_chk": (["checkpoint_role"], [(T, C)]),
}
# signing identities of the keyed-hash evidence / checkpoint stand-in: actor -> (key id, key material, key role)
SIGN_KEYS = {"clt_wrk": ("vk-wrk", "W" * 32, "clt_wrk"), "clt_wri": ("vk-wri", "R" * 32, "clt_wri"),
             "clt_chk": ("vk-chk", "C" * 32, "checkpoint_role")}
# 008 (B3): a scope without a registry_policy row is ENFORCED, so every actor of the fixtures is a registered
# principal (own person, capabilities of its role groups); B1: a default grant for the budget every change declares.
CAPS = {"clt_alice": ["requester"], "clt_mallory": ["requester"], "clt_bob": ["approver"], "clt_carol": ["approver"],
        "clt_dave": ["operator", "requester", "recovery_witness"], "clt_erin": ["operator", "recovery_witness"],
        "clt_both": ["requester", "approver"], "clt_zed": ["requester"]}
DEFAULT_GRANT = {(T, C): uuid.UUID("00000000-0000-4000-8000-0000000000a1"),
                 (T2, C2): uuid.UUID("00000000-0000-4000-8000-0000000000a2")}
RUNTIME_ROLES = ["requester_role", "approver_role", "operator_role", "writer_role", "worker_role",
                 "auditor_role", "checkpoint_role"]
JSON_FUNCS = {"issue_permit", "ledger_head", "verify_chain", "check_anchor"}
COMPOSITE_FUNCS = {"claim", "begin_apply"}


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def exp(hours=1):
    return datetime.now(UTC) + timedelta(hours=hours)


class L:
    """Thin test driver: one scoped call = one transaction under SET LOCAL ROLE."""

    def __init__(self, db):
        self.db, self.conn = db, db.conn

    async def call(self, role, name, *args, t=T, c=C, conn=None):
        conn = conn or self.conn
        marks = ",".join(f"${i + 3}" for i in range(len(args)))
        head = "SELECT * FROM" if name in COMPOSITE_FUNCS else "SELECT"
        sql = f"{head} change_ledger.{name}($1,$2{',' if args else ''}{marks})"
        async with conn.transaction():
            await conn.execute(f'SET LOCAL ROLE "{role}"')
            await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
            if name in COMPOSITE_FUNCS:
                return await conn.fetchrow(sql, t, c, *args)
            value = await conn.fetchval(sql, t, c, *args)
        if name in JSON_FUNCS and isinstance(value, str):
            return json.loads(value)
        return value

    async def sql(self, role, sql, *args, t=T, c=C):
        """Arbitrary statement as `role` with scope set (for direct-DML denial and RLS reads)."""
        async with self.conn.transaction():
            await self.conn.execute(f'SET LOCAL ROLE "{role}"')
            if t:
                await self.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
            return await self.conn.fetch(sql, *args)

    async def rec(self, cid):
        return await self.conn.fetchrow("SELECT * FROM change_ledger.records WHERE change_id=$1", cid)

    async def locks(self, cid):
        tl = await self.conn.fetchval(
            "SELECT count(*) FROM change_ledger.target_locks WHERE owner_change_id=$1", cid)
        kl = await self.conn.fetchval(
            "SELECT count(*) FROM change_ledger.key_locks WHERE owner_change_id=$1", cid)
        wl = await self.conn.fetchval(
            "SELECT count(*) FROM change_ledger.writer_leases WHERE owner_change_id=$1", cid)
        return tl, kl, wl

    async def res_state(self, cid):
        return await self.conn.fetchval(
            "SELECT state FROM change_ledger.reservations WHERE change_id=$1", cid)

    async def open_holds(self, cause=None):
        return await self.conn.fetchval(
            "SELECT count(*) FROM change_ledger.holds WHERE released_at IS NULL AND ($1::text IS NULL OR cause=$1)",
            cause)

    async def tl_owner(self, base, target):
        return await self.conn.fetchval(
            "SELECT owner_change_id FROM change_ledger.target_locks WHERE base_fingerprint=$1 AND target_ref=$2",
            base, target)

    # ---------------------------------------------------------------- flows
    async def propose(self, requester="clt_alice", base=BASE, request_id=None, digest=None,
                      target="doc1", kind="CREATE_DRAFT", parent=None, repair_for=None, t=T, c=C,
                      budget=True, key=None, grant=None, amount=0, declare_class=True):
        cid = uuid.uuid4()
        digest = digest or fixture_digest_for(kind)     # 009 payload rule: POST / UNPOST carry no payload
        got = await self.call(requester, "propose", cid, kind, base, ORG, requester,
                              request_id or uuid.uuid4().hex, digest, target, "v1", parent, exp(),
                              repair_for, t=t, c=c)
        assert got == cid
        if kind == "CREATE_DRAFT" and budget:      # 008 (B1): a draft creation needs its business key
            await self.call(requester, "declare_business_key", cid, key or sha(str(cid)), None, None, t=t, c=c)
        if budget and declare_class:               # 008 (B3): the registry is enforced: the class is declared
            await self.call(requester, "declare_target_class", cid, "CLONE", t=t, c=c)
        if budget:                                 # 008 (B1): the budget inputs are stored with the change
            await self.call(requester, "declare_budget", cid, grant or DEFAULT_GRANT[(t, c)], "EUR", amount,
                            False, False, t=t, c=c)
        return cid

    async def validated(self, **kw):
        cid = await self.propose(**kw)
        assert await self.call(kw.get("requester", "clt_alice"), "validate", cid) == "VALIDATED"
        return cid

    async def approved(self, approver="clt_bob", **kw):
        cid = await self.validated(**kw)
        nonce = await self.call(approver, "issue_approval_nonce", cid)
        await self.call(approver, "approve", cid, nonce, await self.approval_digest(cid))
        return cid

    async def claimed(self, cid, requester="clt_alice", key=None, grant=None, amount=None, observe=True):
        """claim reads the budget and the business key from the stored change. A test that wants another grant or
        amount than the default arranges the stored declaration as superuser (the approval is already given, so no API
        may change it); the claim arguments always equal the stored values."""
        if grant is not None or amount is not None:
            await self.conn.execute(
                "UPDATE change_ledger.change_budget SET grant_id=coalesce($2,grant_id), amount=coalesce($3,amount) "
                "WHERE change_id=$1", cid, grant, amount)
        cb = await self.conn.fetchrow("SELECT * FROM change_ledger.change_budget WHERE change_id=$1", cid)
        if await self.conn.fetchval("SELECT 1 FROM change_ledger.business_keys WHERE change_id=$1", cid):
            key = None                      # a declared business key is the one claim locks; a caller key is ignored
        tok = await self.call(requester, "claim", cid, key, cb["grant_id"] if cb else None,
                              cb["amount"] if cb else None, bool(cb and cb["counts_create_update"]),
                              bool(cb and cb["counts_post"]))
        if observe:      # 008 (B3): the registry is enforced, so the writer observes the target before begin_apply
            base = await self.conn.fetchval("SELECT base_fingerprint FROM change_ledger.records WHERE change_id=$1", cid)
            await self.call("clt_wri", "observe_target", tok["token_id"], base, "CLONE")
        return tok

    async def applying(self, requester="clt_alice", **kw):
        cid = await self.approved(requester=requester, **kw)
        tok = await self.claimed(cid, requester)
        call_id = uuid.uuid4()
        await self.call(requester, "begin_apply", tok["token_id"], call_id, "host-1", "sess-1")
        return cid, tok, call_id

    # ---------------------------------------------------------------- signed paths (007)
    async def head(self):
        return await self.call("clt_chk", "ledger_head")

    async def checkpoint_at(self, seq, head_hash, kind="REAL", read_back=True, role="clt_chk", sig=None,
                            key_id=None, sink_id="sink-1", signed_at=None):
        signed_at = signed_at or datetime.now(UTC)
        kid, kmat, _ = SIGN_KEYS["clt_chk"]
        kid = key_id or kid
        payload = await self.conn.fetchval("SELECT change_ledger.checkpoint_payload($1,$2,$3,$4,$5,$6,$7,$8)",
                                           T, C, seq, head_hash, signed_at, kid, kind, sink_id)
        return await self.call(role, "record_checkpoint", seq, head_hash, kind, sink_id, kid,
                               sig if sig is not None else sha(f"{kmat}:{payload}"), signed_at, read_back)

    async def checkpoint(self, kind="REAL", read_back=True, head_hash=None):
        head = await self.head()
        return await self.checkpoint_at(head["seq"], head_hash or head["head_hash"], kind, read_back)

    async def call_id_of(self, cid, gen=None):
        return await self.conn.fetchval(
            "SELECT call_id FROM change_ledger.dispatch_permits WHERE change_id=$1 AND generation="
            "coalesce($2,(SELECT claim_generation FROM change_ledger.records WHERE change_id=$1))", cid, gen)

    async def evidence(self, cid, kind, content, role="clt_wrk", gen=None, call_id=None, at=None, key=None,
                       bind=None, sig=None, ch=None):
        """Record one signed evidence record as `role`; generation / call id default to the current ones."""
        rec = await self.rec(cid)
        gen = rec["claim_generation"] if gen is None else gen
        call_id = call_id or await self.call_id_of(cid)
        if kind in ("COMPLETION_PROOF", "OBSERVATION"):
            content = {"generation": gen, "call_id": str(call_id), "nonce": uuid.uuid4().hex, **content}
        else:
            content = {"nonce": uuid.uuid4().hex, **content}
        at = at or datetime.now(UTC) + timedelta(seconds=1)
        ch = ch or await self.conn.fetchval("SELECT change_ledger.canonical_content_hash($1::jsonb)",
                                            json.dumps(content))
        b = bind or await self.conn.fetchval("SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
                                             cid, kind, ch, at, gen, call_id)
        kid, kmat, _ = SIGN_KEYS[key or role]
        return await self.call(role, "record_evidence", cid, kind, ch, at, json.dumps(content), kid, b,
                               sig if sig is not None else sha(f"{kmat}:{b}"), gen, call_id)

    async def complete(self, cid, gen, outcome, proof=None, code="STALE_VERSION", **kw):
        """Writer completion through complete_signed; the signed record is typed by `outcome`."""
        completion = None
        if outcome == "SUCCESS":
            completion = await self.evidence(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": True},
                                             role="clt_wri", gen=gen, **kw)
        elif outcome == "PRE_WRITE_REFUSAL":
            body = {"class": "a", "result_returned": False, "stage": "PRE_WRITE", "refusal_code": code}
            if proof is not None:
                body["no_effect_proof"] = proof
            completion = await self.evidence(cid, "COMPLETION_PROOF", body, role="clt_wri", gen=gen, **kw)
        return await self.call("clt_wri", "complete_signed", cid, gen, outcome, completion)

    async def verify(self, cid, passed, role="clt_wrk", fn="verify_signed", **kw):
        ids = [await self.evidence(cid, k, {"matches": passed}, role=role, **kw)
               for k in ("FIELD", "MOVEMENT", "VERSION")]
        return await self.call(role, fn, cid, *ids)

    async def observation(self, cid, present, role="clt_wrk", **extra):
        body = dict(extra)
        if present is not None:
            body["effect_present"] = present
        return await self.evidence(cid, "OBSERVATION", body, role=role)

    async def resolve_unknown(self, cid, found, proof=None, attributed=False):
        obs = await self.observation(cid, found)
        comp = None
        if proof:
            comp = await self.evidence(cid, "COMPLETION_PROOF", {"class": proof, "result_returned": False},
                                       role="clt_wri" if proof == "a" else "clt_wrk")
        return await self.call("clt_wrk", "resolve_unknown_signed", cid, obs, comp, found, attributed)

    async def cosign(self, role, cid, cls="a", attribution=False, present=None):
        """A witness cosign through a signed completion proof (class a by the writer, b by the worker); with
        `present` the matching signed OBSERVATION is recorded too (what operator_resolve requires)."""
        body = {"class": cls, "result_returned": False}
        if attribution:
            body["attribution_proof"] = True
        comp = await self.evidence(cid, "COMPLETION_PROOF", body, role="clt_wri" if cls == "a" else "clt_wrk")
        if present is not None:
            await self.observation(cid, present)
        return await self.call(role, "witness_cosign_signed", cid, comp)

    async def status(self, cid):
        st = await self.call("clt_aud", "read_status", cid)
        return json.loads(st) if isinstance(st, str) else st

    async def approval_digest(self, cid):
        """009 (S12-APPROVAL-2): store the canonical text for the newest issued nonce (as the trusted service does),
        then return the ledger-computed digest of the stored text."""
        await ensure_envelope(self, cid)
        return (await self.status(cid))["approval_digest"]

    async def permitted(self, **kw):
        cid, tok, call_id = await self.applying(**kw)
        await self.checkpoint()
        permit = await self.call("clt_wrk", "issue_permit", cid, tok["generation"])
        return cid, tok, call_id, permit

    async def dispatched(self, **kw):
        cid, tok, call_id, _ = await self.permitted(**kw)
        assert await self.call("clt_wri", "record_call", cid, tok["generation"], call_id) is True
        return cid, tok, call_id

    async def unknown(self, **kw):
        cid, tok, call_id = await self.dispatched(**kw)
        assert await self.complete(cid, tok["generation"], "UNKNOWN") == "APPLY_UNKNOWN"
        return cid, tok, call_id

    async def triage(self, **kw):
        cid, tok, call_id = await self.unknown(**kw)
        assert await self.resolve_unknown(cid, True, attributed=True) == "TRIAGE_REQUIRED"
        return cid, tok, call_id


async def _setup(conn):
    await conn.execute(f"""
      DO $$ DECLARE r text; BEGIN
       FOREACH r IN ARRAY ARRAY{list(ACTORS)} LOOP
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
         EXECUTE format('CREATE ROLE %I NOLOGIN',r); END IF;
       END LOOP; END $$;""")
    for role, (groups, scopes) in ACTORS.items():
        for g in groups:
            await conn.execute(f'GRANT {g} TO "{role}"')
        for t, c in scopes:
            await conn.execute("SELECT change_ledger.add_role_scope($1,$2,$3)", role, t, c)
        if role in CAPS:                 # direct insert: no epoch bump, like the verifier keys below
            for t, c in scopes:
                await conn.execute(
                    "INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities) "
                    "VALUES($1,$2,$3,$4,$5)", t, c, role, "person-" + role, CAPS[role])
    for _actor, (kid, kmat, krole) in SIGN_KEYS.items():
        await conn.execute(
            "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
            "VALUES($1,$2,$3,$4,$5)", T, C, kid, krole, kmat)
    for b in BASES:
        await conn.execute(
            "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,"
            "target_class) VALUES($1,$2,$3,$4,'DISPOSABLE_CLONE')", T, C, b, ORG)
    await conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,"
        "target_class) VALUES($1,$2,'base-t2',$3,'DISPOSABLE_CLONE')", T2, C2, ORG)
    for (t, c), gid in DEFAULT_GRANT.items():
        await conn.execute(
            "INSERT INTO change_ledger.grants(grant_id,tenant_id,company_id,currency,amount_limit,count_limit,"
            "post_count_limit,window_start,window_end) VALUES($1,$2,$3,'EUR',1000000,100000,100000,"
            "now()-interval '1 day',now()+interval '3650 days')", gid, t, c)


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


# ============================================================================ schema / privileges
async def test_migration_applies_and_roles_are_safe(led):
    c = led.conn
    assert await c.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname='change_ledger'") == 1
    for r in RUNTIME_ROLES + ["ledger_owner"]:
        row = await c.fetchrow("SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=$1", r)
        assert tuple(row) == (False, False, False), r
    rows = await c.fetch("SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                         "pg_get_userbyid(c.relowner) o FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                         "WHERE n.nspname='change_ledger' AND c.relkind='r'")
    assert len(rows) >= 17
    for r in rows:
        assert r["relrowsecurity"] and r["relforcerowsecurity"], r["relname"]
        assert r["o"] == "ledger_owner", r["relname"]
    # every function except the plain SQL/trigger helpers is a hardened definer
    bad = await c.fetch("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                        "WHERE n.nspname='change_ledger' AND NOT (p.prosecdef AND p.proconfig::text LIKE "
                        "'%search_path=pg_catalog%')")
    assert not bad, [b[0] for b in bad]


@pytest.mark.parametrize("role", ["clt_alice", "clt_bob", "clt_dave", "clt_wri", "clt_wrk", "clt_aud"])
async def test_no_direct_dml_for_any_runtime_role(led, role):
    cid = await led.propose()
    stmts = [
        "INSERT INTO change_ledger.events(tenant_id,company_id,event_type,hash) VALUES('T1','C1','X',repeat('a',64))",
        "UPDATE change_ledger.events SET payload='{}'",
        "DELETE FROM change_ledger.events",
        "TRUNCATE change_ledger.events",
        "UPDATE change_ledger.records SET lifecycle='VALIDATED'",
        "DELETE FROM change_ledger.records",
        "INSERT INTO change_ledger.kill_switch_state(tenant_id,company_id,mode) VALUES('T1','C1','OFF')",
        "UPDATE change_ledger.targets SET status='REVOKED'",
        "DELETE FROM change_ledger.holds",
        "INSERT INTO change_ledger.holds(tenant_id,company_id,base_fingerprint,cause) VALUES('T1','C1','base-1','ANCHOR_GAP')",
        "UPDATE change_ledger.target_locks SET owner_change_id=gen_random_uuid()",
        "INSERT INTO change_ledger.checkpoints(tenant_id,company_id,ledger_seq,head_hash,sink_kind,sink_id,"
        "signer_key_id,signature,signed_at) VALUES('T1','C1',1,repeat('a',64),'REAL','s','k','s',now())",
        "UPDATE change_ledger.grants SET amount_limit=1",
        "DELETE FROM change_ledger.approvals",
        "UPDATE change_ledger.dispatch_permits SET state='DISPATCHED'",
        "SELECT change_ledger.append_event('T1','C1',NULL,'X','{}'::jsonb)",
        f"SELECT change_ledger.dispatch_cas('{cid}',1,'PERMITTED','DISPATCHED')",
        f"SELECT change_ledger.handoff_target_lock('T1','C1','base-1','doc1','{cid}','{cid}')",
        f"SELECT change_ledger.release_zero_effect('T1','C1','{cid}')",
        "SELECT change_ledger.budget_reserve('T1','C1',gen_random_uuid(),gen_random_uuid(),1)",
        "SELECT change_ledger.budget_consume('T1','C1',gen_random_uuid())",
        "SELECT change_ledger.budget_release('T1','C1',gen_random_uuid())",
    ]
    for s in stmts:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, s)


@pytest.mark.parametrize("role,fn,args", [
    ("clt_alice", "approve", "gen_random_uuid(),'x','x'"),            # requester never approves
    ("clt_alice", "kill_switch", "'STOP_ADMIT'"),
    ("clt_alice", "verify", "gen_random_uuid(),'{}'::jsonb,true"),
    ("clt_alice", "complete", "gen_random_uuid(),1,'SUCCESS','{}'::jsonb,NULL"),
    ("clt_alice", "resolve_unknown", "gen_random_uuid(),'{}'::jsonb,true,true"),
    ("clt_alice", "budget_admin", "NULL,'EUR',1,1,1,now(),now()+interval '1 day'"),
    ("clt_bob", "claim", "gen_random_uuid(),NULL,NULL,NULL,false,false"),
    ("clt_bob", "propose", "gen_random_uuid(),'POST','base-1','o','clt_bob','r','"+DIGEST+"',NULL,NULL,NULL,now()+interval '1 day',NULL"),
    ("clt_wri", "propose", "gen_random_uuid(),'POST','base-1','o','clt_wri','r','"+DIGEST+"',NULL,NULL,NULL,now()+interval '1 day',NULL"),
    ("clt_wri", "kill_switch", "'STOP_ADMIT'"),
    ("clt_wri", "verify", "gen_random_uuid(),'{}'::jsonb,true"),
    ("clt_wrk", "complete", "gen_random_uuid(),1,'SUCCESS','{}'::jsonb,NULL"),
    ("clt_wrk", "record_call", "gen_random_uuid(),1,gen_random_uuid()"),
    ("clt_wrk", "approve", "gen_random_uuid(),'x','x'"),
    ("clt_aud", "kill_switch", "'STOP_ADMIT'"),
    ("clt_aud", "propose", "gen_random_uuid(),'POST','base-1','o','clt_aud','r','"+DIGEST+"',NULL,NULL,NULL,now()+interval '1 day',NULL"),
    ("clt_erin", "approve", "gen_random_uuid(),'x','x'"),
])
async def test_caller_class_matrix_denies_other_classes(led, role, fn, args):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.sql(role, f"SELECT change_ledger.{fn}('T1','C1',{args})")


# ============================================================================ event log / hash chain
async def test_event_log_is_append_only_even_for_the_owner_path(led):
    cid = await led.propose(budget=False)     # 008: a bare proposal (no declarations) writes exactly one event
    c = led.conn  # superuser: privileges cannot help, the triggers must refuse
    await fails("IMMUTABLE_LEDGER", c.execute("UPDATE change_ledger.events SET payload='{}'::jsonb"))
    await fails("IMMUTABLE_LEDGER", c.execute("DELETE FROM change_ledger.events"))
    await fails("IMMUTABLE_LEDGER", c.execute("TRUNCATE change_ledger.events"))
    await fails("IMMUTABLE_LEDGER", c.execute("UPDATE change_ledger.events SET hash=hash"))
    assert await c.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1", cid) == 1


async def test_hash_chain_verifies_and_every_tamper_is_detected(led):
    cid = await led.approved()
    await led.call("clt_dave", "kill_switch", "OFF")   # NULL change_id event must chain too
    await led.call("clt_dave", "kill_switch", "OFF")
    ok = await led.call("clt_aud", "verify_chain")
    n = await led.conn.fetchval("SELECT count(*) FROM change_ledger.events")
    assert ok == {"ok": True, "count": n, "bad_seq": None} and n >= 5
    rows = await led.conn.fetch("SELECT seq, prev_hash, hash FROM change_ledger.events ORDER BY seq")
    assert [r["seq"] for r in rows] == list(range(1, n + 1))
    assert rows[0]["prev_hash"] is None
    for a, b in zip(rows, rows[1:]):
        assert b["prev_hash"] == a["hash"]
    head = await led.call("clt_aud", "ledger_head")
    assert head == {"seq": n, "head_hash": rows[-1]["hash"]}
    # the stored hash is what the documented formula yields (so an external verifier can recompute it)
    r2 = await led.conn.fetchrow("SELECT * FROM change_ledger.events WHERE seq=2")
    want = hashlib.sha256(f"{rows[0]['hash']}:2:{r2['change_id']}:{r2['event_type']}:{r2['payload']}"
                          .encode()).hexdigest()
    assert r2["hash"] == want

    async def tamper(stmt):
        await led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
        await led.conn.execute(stmt)
        await led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")

    await tamper("UPDATE change_ledger.events SET payload='{\"forged\":1}'::jsonb WHERE seq=2")
    assert await led.call("clt_aud", "verify_chain") == {"ok": False, "count": 1, "bad_seq": 2}


async def test_hash_chain_detects_deleted_and_reordered_rows(led):
    await led.approved()
    n = await led.conn.fetchval("SELECT count(*) FROM change_ledger.events")
    await led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    await led.conn.execute("DELETE FROM change_ledger.events WHERE seq=2")
    await led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
    got = await led.call("clt_aud", "verify_chain")
    assert n >= 3 and got == {"ok": False, "count": 1, "bad_seq": 3}


async def test_concurrent_appends_keep_one_gapless_verifiable_chain(led):
    conns = [await led.db.connect() for _ in range(4)]
    try:
        async def worker(k):
            for j in range(6):
                i = k * 6 + j
                await led.call("clt_alice", "propose", uuid.uuid4(), "CREATE_DRAFT", BASES[i % 8], ORG,
                               "clt_alice", f"conc-{i}", DIGEST, f"d{i}", "v1", None, exp(), None,
                               conn=conns[k])
        await asyncio.gather(*[worker(k) for k in range(4)])
    finally:
        for x in conns:
            await x.close()
    got = await led.call("clt_aud", "verify_chain")
    assert got == {"ok": True, "count": 24, "bad_seq": None}


# ============================================================================ scope / RLS
async def test_rls_tenant_isolation_and_scope_grants(led):
    a = await led.propose()
    z = await led.propose(requester="clt_zed", base="base-t2", t=T2, c=C2)
    # the auditor, scoped to T1/C1, sees only T1 rows in every scoped table
    for tbl in ("records", "events", "targets"):
        rows = await led.sql("clt_aud", f"SELECT tenant_id FROM change_ledger.{tbl}")
        assert rows and {r[0] for r in rows} == {T}, tbl
    assert [r[0] for r in await led.sql("clt_aud", "SELECT change_id FROM change_ledger.records")] == [a]
    # with the T2 scope the zed role sees only its own; 008 B6k: a requester reads through read_status, not the table
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.sql("clt_zed", "SELECT change_id FROM change_ledger.records", t=T2, c=C2)
    zs = await led.call("clt_zed", "read_status", z, t=T2, c=C2)
    assert (json.loads(zs) if isinstance(zs, str) else zs)["change_id"] == str(z)
    await fails("CHANGE_NOT_FOUND", led.call("clt_zed", "read_status", a, t=T2, c=C2))
    # no scope set at all: nothing visible
    assert await led.sql("clt_aud", "SELECT * FROM change_ledger.records", t=None) == []
    # a role cannot enter a scope it was not granted, and cannot call with arguments differing from its scope
    await fails("SCOPE_NOT_GRANTED", led.call("clt_aud", "ledger_head", t=T2, c=C2))
    async with led.conn.transaction():
        await led.conn.execute('SET LOCAL ROLE "clt_alice"')
        await led.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        with pytest.raises(asyncpg.PostgresError, match="SCOPE_NOT_GRANTED"):
            await led.conn.fetchval("SELECT change_ledger.validate($1,$2,$3)", T2, C2, z)
    # a change of another tenant cannot be touched from a granted scope (not found, not leaked)
    await fails("CHANGE_NOT_FOUND", led.call("clt_alice", "validate", z))
    # a role sees only its own role_scope rows
    with pytest.raises(asyncpg.InsufficientPrivilegeError):      # the grant table itself is not readable
        await led.sql("clt_aud", "SELECT role_name FROM change_ledger.role_scope")


# ============================================================================ T1 propose
async def test_propose_is_idempotent_on_the_logical_key(led):
    first = await led.propose(request_id="req-1")
    again = await led.call("clt_alice", "propose", uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_alice",
                           "req-1", DIGEST, "doc1", "v1", None, exp(), None)
    assert again == first
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.records") == 1
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE event_type='PROPOSED'") == 1
    await fails("IDEMPOTENCY_CONFLICT", led.call(
        "clt_alice", "propose", uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_alice", "req-1", "c" * 64,
        "doc1", "v1", None, exp(), None))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.records") == 1
    # another requester with the same request id is a different logical key
    other = await led.propose(requester="clt_mallory", request_id="req-1")
    assert other != first


async def test_propose_refuses_foreign_identity_unknown_or_revoked_target_and_bad_repair(led):
    args = (uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_mallory", "r", DIGEST, "d", "v1", None, exp(), None)
    await fails("NOT_ENTITLED", led.call("clt_alice", "propose", *args))        # identity is never an argument
    await fails("TARGET_REJECTED", led.call("clt_alice", "propose", uuid.uuid4(), "CREATE_DRAFT", "nope", ORG,
                                            "clt_alice", "r", DIGEST, "d", "v1", None, exp(), None))
    await led.conn.execute("UPDATE change_ledger.targets SET status='REVOKED' WHERE base_fingerprint='base-2'")
    await fails("TARGET_REJECTED", led.call("clt_alice", "propose", uuid.uuid4(), "CREATE_DRAFT", "base-2", ORG,
                                            "clt_alice", "r", DIGEST, "d", "v1", None, exp(), None))
    p = uuid.uuid4()
    await fails("SCHEMA_INVALID", led.call("clt_alice", "propose", uuid.uuid4(), "POST", BASE, ORG, "clt_alice",
                                           "r2", DIGEST, "d", "v1", p, exp(), p))   # repair must be UNPOST
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.records") == 0


# ============================================================================ T4 approval
async def test_approval_needs_a_distinct_person_and_a_single_use_bound_nonce(led):
    cid = await led.validated(requester="clt_both")
    # the requester's own identity can neither obtain a nonce nor approve
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_both", "issue_approval_nonce", cid))
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    dg = await led.approval_digest(cid)       # 009: the canonical text is stored for the issued nonce first
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_both", "approve", cid, nonce, dg))
    assert (await led.rec(cid))["authorization_state"] == "NONE"
    # a nonce is bound to its approver, its change and its digest
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_carol", "approve", cid, nonce, dg))
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_bob", "approve", cid, "bogus", dg))
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", cid, nonce, "d" * 64))
    other = await led.validated(request_id="other", base="base-2")
    await led.call("clt_carol", "issue_approval_nonce", other)          # 009: other has its own text and digest
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_bob", "approve", other, nonce,
                                                   await led.approval_digest(other)))
    # expiry
    await led.conn.execute("UPDATE change_ledger.approval_nonces SET expires_at=now()-interval '1 second' "
                           "WHERE nonce=$1", nonce)
    await fails("APPROVAL_EXPIRED", led.call("clt_bob", "approve", cid, nonce, dg))
    await led.conn.execute("UPDATE change_ledger.approval_nonces SET expires_at=now()+interval '1 hour' "
                           "WHERE nonce=$1", nonce)
    # valid approval consumes the nonce and writes an immutable approval record
    aid = await led.call("clt_bob", "approve", cid, nonce, dg)
    assert (await led.rec(cid))["authorization_state"] == "APPROVED"
    assert await led.conn.fetchval("SELECT state FROM change_ledger.approval_nonces WHERE nonce=$1", nonce) \
        == "CONSUMED"
    await fails("IMMUTABLE_LEDGER", led.conn.execute("UPDATE change_ledger.approvals SET digest=digest"))
    assert await led.conn.fetchval("SELECT approver FROM change_ledger.approvals WHERE approval_id=$1", aid) \
        == "clt_bob"
    # single use: even if the authorization were reset, the consumed nonce cannot approve again
    await led.conn.execute("UPDATE change_ledger.records SET authorization_state='NONE' WHERE change_id=$1", cid)
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_bob", "approve", cid, nonce, dg))
    # an approved change cannot be approved a second time with a fresh nonce
    await led.conn.execute("UPDATE change_ledger.records SET authorization_state='APPROVED' WHERE change_id=$1", cid)
    # (batch A, A2; 008 B6b) an APPROVED change may get a nonce (the approver can still reject it) but a second
    # approval with it is refused
    n2 = await led.call("clt_carol", "issue_approval_nonce", cid)
    await fails("FORBIDDEN_TRANSITION", led.call("clt_carol", "approve", cid, n2, dg))


async def test_reject_consumes_a_nonce_and_is_terminal(led):
    cid = await led.validated()
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_carol", "reject", cid, nonce))
    assert await led.call("clt_bob", "reject", cid, nonce) == "REJECTED"
    assert (await led.rec(cid))["lifecycle"] == "REJECTED"
    n2 = await led.call("clt_bob", "issue_approval_nonce", cid)
    await fails("FORBIDDEN_TRANSITION", led.call("clt_bob", "reject", cid, n2))
    await fails("FORBIDDEN_TRANSITION", led.call("clt_bob", "approve", cid, n2, DIGEST))


# ============================================================================ T5 claim
async def test_claim_takes_locks_lease_and_reservation_atomically_and_second_claim_is_refused(led):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 100, 5, 5, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    c1 = await led.approved(request_id="c1", target="doc1")
    tok = await led.claimed(c1, grant=gid, amount=60)
    assert tok["generation"] == 1 and tok["state"] == "ISSUED"
    assert await led.locks(c1) == (1, 1, 1)
    assert await led.res_state(c1) == "RESERVED"
    r = await led.rec(c1)
    assert (r["authorization_state"], r["claim_generation"], r["reservation_state"]) == ("CLAIMED", 1, "RESERVED")
    # same base: the single writer lease refuses any second claim, and nothing of it may leak
    c2 = await led.approved(request_id="c2", target="doc2")
    await fails("LOCK_BUSY", led.claimed(c2, key="c" * 64, grant=gid, amount=10))
    assert await led.locks(c2) == (0, 0, 0)
    assert await led.res_state(c2) is None
    r2 = await led.rec(c2)
    assert (r2["authorization_state"], r2["claim_generation"]) == ("APPROVED", 0)
    # drop the lease to isolate the other two locks: same target, then same business key
    await led.conn.execute("DELETE FROM change_ledger.writer_leases WHERE owner_change_id=$1", c1)
    c3 = await led.approved(request_id="c3", target="doc1")
    await fails("LOCK_BUSY", led.claimed(c3, key="d" * 64))
    c4 = await led.approved(request_id="c4", target="doc4")
    # 008: the key lock is the STORED business key; arrange c4 to carry the same key as c1 (validate would park it)
    await led.conn.execute("UPDATE change_ledger.business_keys SET key_hash=(SELECT key_hash FROM "
                           "change_ledger.business_keys WHERE change_id=$1) WHERE change_id=$2", c1, c4)
    await fails("LOCK_BUSY", led.claimed(c4))
    for x in (c3, c4):
        assert await led.locks(x) == (0, 0, 0)
        assert (await led.rec(x))["authorization_state"] == "APPROVED"
    # budget: 60 + 60 > 100 on the same grant is refused before any lock is taken
    c5 = await led.approved(request_id="c5", target="doc5", base="base-2")
    await fails("BUDGET_EXCEEDED", led.claimed(c5, key="e" * 64, grant=gid, amount=60))
    assert await led.locks(c5) == (0, 0, 0) and await led.res_state(c5) is None
    await led.claimed(c5, key="e" * 64, grant=gid, amount=40)
    assert await led.res_state(c5) == "RESERVED"


async def test_claim_guards_owner_approval_hold_parent_and_release_then_reclaim(led):
    cid = await led.validated()
    await fails("APPROVAL_MISSING", led.claimed(cid))
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    await led.call("clt_bob", "approve", cid, nonce, await led.approval_digest(cid))
    await fails("NOT_ENTITLED", led.claimed(cid, requester="clt_mallory"))
    hold = uuid.uuid4()
    await led.conn.execute("INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause) "
                           "VALUES($1,$2,$3,$4,'RLC_UNCLEAN')", hold, T, C, BASE)
    await fails("BASE_HOLD", led.claimed(cid))
    await led.conn.execute("UPDATE change_ledger.holds SET released_at=now() WHERE hold_id=$1", hold)
    parent_child = await led.approved(kind="POST", parent=cid, request_id="post1", base="base-2")
    await fails("PARENT_NOT_VERIFIED", led.claimed(parent_child))
    tok = await led.claimed(cid)
    # release (T5x) and re-claim: generation moves forward, the old ticket is dead
    assert await led.call("clt_alice", "release_claim", tok["token_id"]) == "SUPERSEDED"
    assert await led.call("clt_alice", "release_claim", tok["token_id"]) == "SUPERSEDED"   # idempotent
    assert await led.locks(cid) == (0, 0, 0)
    assert (await led.rec(cid))["authorization_state"] == "APPROVED"
    tok2 = await led.claimed(cid)
    assert tok2["generation"] == 2
    await fails("TICKET_SUPERSEDED", led.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s"))


# ============================================================================ T6 / T6p
async def test_begin_apply_then_permit_needs_a_real_readback_checkpoint_covering_the_head(led):
    cid, tok, call_id = await led.applying()
    gen = tok["generation"]
    r = await led.rec(cid)
    assert (r["execution_state"], r["dispatch_state"]) == ("APPLYING", "NOT_PERMITTED")
    again = await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "host-1", "sess-1")
    assert again["token_id"] == tok["token_id"]          # replay returns the same ticket
    await fails("NOT_ENTITLED", led.call("clt_mallory", "begin_apply", tok["token_id"], call_id, "h", "s"))
    # 1. no checkpoint at all
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_wrk", "issue_permit", cid, gen))
    # 2. a checkpoint that was not read back is not even stored
    await fails("CHECKPOINT_UNAVAILABLE", led.checkpoint(read_back=False))
    # 3. a TEST sink covering the head never qualifies (require_real_checkpoint = 1)
    await led.checkpoint(kind="TEST")
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_wrk", "issue_permit", cid, gen))
    # 4. a REAL checkpoint whose head hash is not the ledger's event at that seq
    await led.checkpoint(head_hash="f" * 64)
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_wrk", "issue_permit", cid, gen))
    # 5. a REAL, correct checkpoint written BEFORE the APPLYING event does not cover it
    stale = await led.conn.fetchval("SELECT max(seq) FROM change_ledger.events WHERE event_type='CLAIMED'")
    h = await led.conn.fetchval("SELECT hash FROM change_ledger.events WHERE seq=$1", stale)
    await led.checkpoint_at(stale, h)
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_wrk", "issue_permit", cid, gen))
    assert (await led.rec(cid))["dispatch_state"] == "NOT_PERMITTED"
    # 6. a REAL read-back checkpoint of the current head: the permit is issued, dispatch = PERMITTED
    await led.checkpoint()
    permit = await led.call("clt_wrk", "issue_permit", cid, gen)
    assert permit["generation"] == gen and len(permit["permit_digest"]) == 64
    assert (await led.rec(cid))["dispatch_state"] == "PERMITTED"
    # 008 B6e: a repeated issue_permit returns the existing permit (no second PERMITTED event)
    again = await led.call("clt_wrk", "issue_permit", cid, gen)
    assert again["permit_digest"] == permit["permit_digest"] and again["expires_at"] == permit["expires_at"]
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND "
                                   "event_type='PERMITTED'", cid) == 1
    await fails("TICKET_SUPERSEDED", led.call("clt_wrk", "issue_permit", cid, gen + 1))


# ============================================================================ T6c / dispatch CAS
async def test_cancel_and_record_call_are_mutually_exclusive_sequentially(led):
    cid, tok, call_id, _ = await led.permitted(request_id="a", base="base-1")
    gen = tok["generation"]
    assert await led.call("clt_wrk", "cancel_permit", cid, gen) is True
    r = await led.rec(cid)
    assert (r["dispatch_state"], r["authorization_state"], r["execution_state"]) == \
        ("CANCELLED_UNDISPATCHED", "APPROVED", "NOT_STARTED")
    assert await led.locks(cid) == (0, 0, 0)
    assert await led.call("clt_wri", "record_call", cid, gen, call_id) is False
    assert await led.call("clt_wrk", "cancel_permit", cid, gen) is False
    # the other order: the writer's DISPATCHED wins, the cancel releases nothing
    c2, t2, call2, _ = await led.permitted(request_id="b", base="base-2")
    assert await led.call("clt_wri", "record_call", c2, t2["generation"], call2) is True
    assert await led.call("clt_wrk", "cancel_permit", c2, t2["generation"]) is False
    assert (await led.rec(c2))["dispatch_state"] == "DISPATCHED"
    assert await led.locks(c2) == (1, 1, 1)
    assert await led.call("clt_wri", "record_call", c2, t2["generation"], call2) is False   # at most once


@pytest.mark.parametrize("round_no", range(6))
async def test_cancel_vs_record_call_exactly_one_wins_under_real_concurrency(led, round_no):
    """Both sessions queue on the same change row while a third session holds it; when released they
    race on the one dispatch CAS. Exactly one may win and the ledger must reflect exactly that winner."""
    cid, tok, call_id, _ = await led.permitted(request_id=f"race{round_no}", base=f"race-{round_no}")
    gen = tok["generation"]
    c1, c2, c3 = [await led.db.connect() for _ in range(3)]
    try:
        tx = c3.transaction()
        await tx.start()
        await c3.execute("SELECT 1 FROM change_ledger.records WHERE change_id=$1 FOR UPDATE", cid)
        t_cancel = asyncio.create_task(led.call("clt_wrk", "cancel_permit", cid, gen, conn=c1))
        t_call = asyncio.create_task(led.call("clt_wri", "record_call", cid, gen, call_id, conn=c2))
        for _ in range(100):
            waiting = await c3.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                        "AND wait_event_type='Lock' AND pid<>pg_backend_pid()")
            if waiting >= 2:
                break
            await asyncio.sleep(0.1)
        assert waiting >= 2, "both racers must be queued before the race is released"
        await tx.commit()
        cancelled, dispatched = await asyncio.gather(t_cancel, t_call)
    finally:
        for x in (c1, c2, c3):
            await x.close()
    assert [cancelled, dispatched].count(True) == 1, (cancelled, dispatched)
    r = await led.rec(cid)
    permit = await led.conn.fetchval("SELECT state FROM change_ledger.dispatch_permits WHERE change_id=$1", cid)
    if dispatched:
        assert (r["dispatch_state"], permit) == ("DISPATCHED", "DISPATCHED")
        assert await led.locks(cid) == (1, 1, 1)
    else:
        assert (r["dispatch_state"], permit) == ("CANCELLED_UNDISPATCHED", "CANCELLED_UNDISPATCHED")
        assert await led.locks(cid) == (0, 0, 0)
    events = {e[0] for e in await led.conn.fetch(
        "SELECT event_type FROM change_ledger.events WHERE change_id=$1", cid)}
    assert ("DISPATCHED" in events) != ("PERMIT_CANCELLED" in events)


# ============================================================================ recover_sweep
async def test_recover_sweep_releases_expired_claim_reservation_and_expired_permit(led):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 5, 5, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    stale = await led.approved(request_id="s1", base="base-1")
    tok = await led.claimed(stale, grant=gid, amount=10)
    fresh = await led.approved(request_id="s2", base="base-2")
    await led.claimed(fresh, key="c" * 64, grant=gid, amount=10)
    await led.conn.execute("UPDATE change_ledger.claim_tokens SET issued_at=now()-interval '3 minutes' "
                           "WHERE token_id=$1", tok["token_id"])
    assert await led.call("clt_wrk", "recover_sweep") == 1
    assert await led.locks(stale) == (0, 0, 0)
    assert await led.res_state(stale) == "RELEASED"
    r = await led.rec(stale)
    assert (r["authorization_state"], r["reservation_state"]) == ("APPROVED", "RELEASED")
    assert await led.conn.fetchval("SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1",
                                   tok["token_id"]) == "SUPERSEDED"
    assert await led.locks(fresh) == (1, 1, 1) and await led.res_state(fresh) == "RESERVED"   # untouched
    assert await led.call("clt_wrk", "recover_sweep") == 0                                     # idempotent
    # permit TTL: PERMITTED and expired -> cancelled by the same CAS; a DISPATCHED permit is never touched
    p, ptok, _, _ = await led.permitted(request_id="s3", base="base-3")
    d, dtok, dcall = await led.dispatched(request_id="s4", base="base-4")
    await led.conn.execute("UPDATE change_ledger.dispatch_permits SET expires_at=now()-interval '1 second'")
    assert await led.call("clt_wrk", "recover_sweep") == 1
    assert (await led.rec(p))["dispatch_state"] == "CANCELLED_UNDISPATCHED" and await led.locks(p) == (0, 0, 0)
    assert (await led.rec(d))["dispatch_state"] == "DISPATCHED" and await led.locks(d) == (1, 1, 1)


# ============================================================================ T7 / T8 / T9 / T13 / T14
async def test_complete_outcomes_success_prewrite_refusal_and_verification(led):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 5, 5, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    # nothing may be completed as effect-bearing before the dispatch CAS
    cid, tok, call_id, _ = await led.permitted(request_id="o1", base="base-1")
    gen = tok["generation"]
    await fails("PERMIT_MISSING", led.complete(cid, gen, "SUCCESS"))
    await fails("PERMIT_MISSING", led.complete(cid, gen, "UNKNOWN"))
    await fails("SCHEMA_INVALID", led.complete(cid, gen, "WHATEVER"))
    await fails("TICKET_SUPERSEDED", led.complete(cid, gen + 1, "SUCCESS"))
    # PRE_WRITE refusal needs the no-effect proof; with it: FAILED_APPLY and everything released
    await fails("WRITE_REFUSED", led.complete(cid, gen, "PRE_WRITE_REFUSAL"))
    assert await led.complete(cid, gen, "PRE_WRITE_REFUSAL", proof={"proof": "no-effect"}) == "FAILED_APPLY"
    assert await led.locks(cid) == (0, 0, 0)
    assert (await led.rec(cid))["dispatch_state"] == "CANCELLED_UNDISPATCHED"
    # SUCCESS: APPLIED/PROVEN, reservation consumed, target lock kept until T13
    s, stok, scall = await led.dispatched(request_id="o2", base="base-2")
    assert await led.complete(s, stok["generation"], "SUCCESS") == "APPLIED"
    r = await led.rec(s)
    assert (r["attribution"], r["call_ownership"], r["execution_state"]) == ("PROVEN", "PROVEN_FINISHED", "APPLIED")
    assert await led.locks(s) == (1, 0, 0)
    assert await led.complete(s, stok["generation"], "SUCCESS") == "APPLIED"
    assert await led.verify(s, True) == "VERIFIED"
    assert await led.locks(s) == (0, 0, 0)
    # a failed verification halts the base and keeps the target lock
    f, ftok, _ = await led.dispatched(request_id="o3", base="base-3")
    await led.complete(f, ftok["generation"], "SUCCESS")
    assert await led.verify(f, False) == "FAILED_VERIFY"
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1 and await led.locks(f) == (1, 0, 0)
    assert (await led.rec(f))["effect_known"] == "YES"


async def test_unknown_outcome_keeps_lock_lease_reservation_and_opens_call_ownership_hold(led):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 5, 5, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    cid = await led.approved(request_id="u1", base="base-1")
    tok = await led.claimed(cid, grant=gid, amount=5)
    call_id = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, tok["generation"])
    await led.call("clt_wri", "record_call", cid, tok["generation"], call_id)
    assert await led.complete(cid, tok["generation"], "UNKNOWN") == "APPLY_UNKNOWN"
    r = await led.rec(cid)
    assert (r["execution_state"], r["call_ownership"], r["reservation_state"]) == \
        ("APPLY_UNKNOWN", "POSSIBLY_EXECUTING", "RESERVED")
    assert await led.locks(cid) == (1, 1, 1) and await led.res_state(cid) == "RESERVED"
    assert await led.open_holds("CALL_OWNERSHIP") == 1
    # the hold blocks every other claim on the base and cannot be released without completion proof
    other = await led.approved(request_id="u2", base="base-1", target="doc9")
    await fails("BASE_HOLD", led.claimed(other, key="e" * 64))
    hold = await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE cause='CALL_OWNERSHIP'")
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "release_hold", hold, '{"x":1}'))
    assert await led.open_holds("CALL_OWNERSHIP") == 1
    # the sweep never turns an unknown outcome into anything else
    assert await led.call("clt_wrk", "recover_sweep") == 0
    assert (await led.rec(cid))["execution_state"] == "APPLY_UNKNOWN"


# ============================================================================ T10 / T11 / T12
async def test_resolve_unknown_needs_completion_proof_and_never_attributes_presence(led):
    cid, tok, _ = await led.unknown(request_id="r1", base="base-1")
    # absence without an independent PROVEN_FINISHED proof is refused, nothing changes
    await fails("COMPLETION_PROOF_MISSING", led.resolve_unknown(cid, False))
    r = await led.rec(cid)
    assert r["execution_state"] == "APPLY_UNKNOWN" and await led.open_holds("CALL_OWNERSHIP") == 1
    # presence, even with an attribution claim: TRIAGE_REQUIRED, never APPLIED / PROVEN, hold and locks kept
    assert await led.resolve_unknown(cid, True, proof="a", attributed=True) == "TRIAGE_REQUIRED"
    r = await led.rec(cid)
    assert (r["execution_state"], r["attribution"], r["call_ownership"]) == \
        ("TRIAGE_REQUIRED", "NOT_APPLICABLE", "POSSIBLY_EXECUTING")
    assert r["reservation_state"] != "CONSUMED"
    assert await led.open_holds("CALL_OWNERSHIP") == 1 and await led.locks(cid) == (1, 1, 1)
    # absence WITH the proof (separate change): FAILED_APPLY, hold released, everything released
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 5, 5, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    c2 = await led.approved(request_id="r2", base="base-2")
    t2 = await led.claimed(c2, grant=gid, amount=5)
    k2 = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", t2["token_id"], k2, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", c2, t2["generation"])
    await led.call("clt_wri", "record_call", c2, t2["generation"], k2)
    await led.complete(c2, t2["generation"], "UNKNOWN")
    assert await led.resolve_unknown(c2, False, proof="b") == "FAILED_APPLY"
    assert await led.locks(c2) == (0, 0, 0) and await led.res_state(c2) == "RELEASED"
    assert (await led.rec(c2))["reservation_state"] == "RELEASED"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.holds WHERE change_id=$1 AND "
                                   "released_at IS NOT NULL", c2) == 1
    # T12 explicit: an inconclusive observation (no verdict) -> triage
    c3, _, _ = await led.unknown(request_id="r3", base="base-3")
    assert await led.resolve_unknown(c3, None) == "TRIAGE_REQUIRED"


# ============================================================================ T16
async def test_operator_resolve_needs_two_distinct_signers_and_completion_proof(led):
    gid = uuid.uuid4()
    await led.call("clt_dave", "budget_admin", gid, "EUR", 1000, 5, 5, datetime.now(UTC) - timedelta(hours=1),
                   datetime.now(UTC) + timedelta(hours=1))
    cid = await led.approved(request_id="t16", base="base-1")
    tok = await led.claimed(cid, grant=gid, amount=5)
    call_id = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, tok["generation"])
    await led.call("clt_wri", "record_call", cid, tok["generation"], call_id)
    await led.complete(cid, tok["generation"], "UNKNOWN")
    await led.resolve_unknown(cid, True)
    assert (await led.rec(cid))["execution_state"] == "TRIAGE_REQUIRED"
    # no witness co-signature at all
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "operator_resolve", cid, uuid.uuid4(), True, False))
    # the same person cannot be operator and witness
    own = await led.cosign("clt_dave", cid, present=True)
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_dave", "operator_resolve", cid, own, True, False))
    # an attributed claim without an attribution proof is refused
    good = await led.cosign("clt_erin", cid, present=True)
    await fails("ATTRIBUTION_UNPROVEN", led.call("clt_dave", "operator_resolve", cid, good, True, True))
    assert (await led.rec(cid))["execution_state"] == "TRIAGE_REQUIRED" and await led.open_holds("CALL_OWNERSHIP") == 1
    # valid: present and unattributed -> APPLIED with the explicit unproven marker; hold released; TL kept
    assert await led.call("clt_dave", "operator_resolve", cid, good, True, False) == "APPLIED"
    r = await led.rec(cid)
    assert (r["attribution"], r["reservation_state"], r["call_ownership"]) == \
        ("UNPROVEN_OPERATOR_ATTESTED", "CONSUMED", "PROVEN_FINISHED")
    assert await led.open_holds("CALL_OWNERSHIP") == 0 and await led.locks(cid) == (1, 0, 0)
    assert await led.conn.fetchval("SELECT consumed_at IS NOT NULL FROM change_ledger.witness_cosigns "
                                   "WHERE cosign_id=$1", good)
    await fails("FORBIDDEN_TRANSITION", led.call("clt_dave", "operator_resolve", cid, good, False, False))
    assert (await led.rec(cid))["reservation_state"] == "CONSUMED"          # a repeat cannot change accounting


async def test_operator_resolve_absent_releases_and_requester_cannot_witness_own_change(led):
    cid, tok, _ = await led.triage(request_id="t16b", base="base-1", requester="clt_dave")
    # dave is the requester of this change: he can neither sign as witness nor operate it
    own = await led.cosign("clt_dave", cid, cls="b", present=False)
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_erin", "operator_resolve", cid, own, False, False))
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_dave", "operator_resolve", cid, own, False, False))
    good = await led.cosign("clt_erin", cid, cls="b")
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_dave", "operator_resolve", cid, good, False, False))
    assert await led.open_holds("CALL_OWNERSHIP") == 1
    # the cosign of a third operator, resolved by a non-requester operator: absent -> FAILED_APPLY, all released
    await led.conn.execute("GRANT operator_role TO clt_carol")
    await led.conn.execute("SELECT change_ledger.add_role_scope('clt_carol',$1,$2)", T, C)
    # 008: the registry is enforced, so the third operator is registered with its capabilities (own person)
    await led.conn.execute("UPDATE change_ledger.principals SET capabilities=ARRAY['approver','operator',"
                           "'recovery_witness'] WHERE principal='clt_carol'")
    w = await led.cosign("clt_carol", cid)
    assert await led.call("clt_erin", "operator_resolve", cid, w, False, False) == "FAILED_APPLY"
    assert await led.locks(cid) == (0, 0, 0) and await led.open_holds("CALL_OWNERSHIP") == 0
    assert (await led.rec(cid))["reservation_state"] in ("RELEASED", "NONE")


# ============================================================================ repair (4.2)
async def _failed_parent(led, base=BASE, target="doc1"):
    """A POST whose verification failed: FAILED_VERIFY, effect_known YES, halt row open, TL kept."""
    ver = await led.approved(request_id=f"ver-{base}", base=base, target=target)
    # the POST needs a VERIFIED parent (the draft): arrange it through the real flow
    tok = await led.claimed(ver)
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", ver, tok["generation"])
    await led.call("clt_wri", "record_call", ver, tok["generation"], k)
    await led.complete(ver, tok["generation"], "SUCCESS")
    await led.verify(ver, True)
    post = await led.approved(kind="POST", parent=ver, request_id=f"post-{base}", base=base, target=target)
    tok = await led.claimed(post, key="9" * 64)
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", post, tok["generation"])
    await led.call("clt_wri", "record_call", post, tok["generation"], k)
    await led.complete(post, tok["generation"], "SUCCESS")
    assert await led.verify(post, False) == "FAILED_VERIFY"
    return post


async def _repair(led, parent, base=BASE, target="doc1", rid="rep"):
    return await led.approved(kind="UNPOST", parent=parent, repair_for=parent, base=base, target=target,
                              request_id=rid, approver="clt_carol")


async def test_repair_claim_hands_the_target_lock_over_atomically_and_hands_it_back(led):
    parent = await _failed_parent(led)
    assert await led.tl_owner(BASE, "doc1") == parent and await led.open_holds("FAILED_VERIFY_HALT") == 1
    # a plain change on the halted base is refused; so is an unrelated "repair"
    plain = await led.approved(request_id="plain", target="doc7")
    await fails("BASE_HOLD", led.claimed(plain, key="7" * 64))
    other_target = await _repair(led, parent, target="doc-other", rid="rep-wrong-target")
    await fails("PARENT_NOT_VERIFIED", led.claimed(other_target, key="6" * 64))
    assert await led.tl_owner(BASE, "doc1") == parent
    # another open hold of any other cause refuses the repair too and leaves parent lock and halt intact
    h = uuid.uuid4()
    await led.conn.execute("INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause) "
                           "VALUES($1,$2,$3,$4,'ANCHOR_GAP')", h, T, C, BASE)
    rep = await _repair(led, parent)
    await fails("BASE_HOLD", led.claimed(rep, key="5" * 64))
    assert await led.tl_owner(BASE, "doc1") == parent
    await led.conn.execute("UPDATE change_ledger.holds SET released_at=now() WHERE hold_id=$1", h)
    # a conflicting target owner (not the parent) refuses
    await led.conn.execute("UPDATE change_ledger.target_locks SET owner_change_id=$1 WHERE target_ref='doc1'", plain)
    await fails("LOCK_BUSY", led.claimed(rep, key="5" * 64))
    await led.conn.execute("UPDATE change_ledger.target_locks SET owner_change_id=$1 WHERE target_ref='doc1'", parent)
    # the matching approved repair: atomic handover, no gap, the halt stays open
    tok = await led.claimed(rep, key="5" * 64)
    assert await led.tl_owner(BASE, "doc1") == rep
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.target_locks WHERE target_ref='doc1'") == 1
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert await led.locks(rep) == (1, 1, 1)
    # T5x: claim released -> the lock goes back to the parent in the same transaction, halt untouched
    await led.call("clt_alice", "release_claim", tok["token_id"])
    assert await led.tl_owner(BASE, "doc1") == parent
    assert await led.locks(rep) == (0, 0, 0) and await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert (await led.rec(parent))["verification_state"] == "FAILED_VERIFY"
    # claim again -> begin_apply -> checkpoint -> permit -> cancel CAS (T6c): handed back
    tok = await led.claimed(rep, key="5" * 64)
    assert tok["generation"] == 2 and await led.tl_owner(BASE, "doc1") == rep
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", rep, tok["generation"])
    assert await led.call("clt_wrk", "cancel_permit", rep, tok["generation"]) is True
    assert await led.tl_owner(BASE, "doc1") == parent and await led.open_holds("FAILED_VERIFY_HALT") == 1
    # claim a third time -> PRE_WRITE refusal: handed back, repair is FAILED_APPLY (terminal)
    tok = await led.claimed(rep, key="5" * 64)
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    assert await led.complete(rep, tok["generation"], "PRE_WRITE_REFUSAL", proof={"proof": "stale"}) == "FAILED_APPLY"
    assert await led.tl_owner(BASE, "doc1") == parent and await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert await led.locks(rep) == (0, 0, 0)


async def test_repair_after_dispatch_does_not_hand_back_and_success_releases_the_halt(led):
    parent = await _failed_parent(led)
    rep = await _repair(led, parent)
    tok = await led.claimed(rep, key="5" * 64)
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", rep, tok["generation"])
    assert await led.call("clt_wri", "record_call", rep, tok["generation"], k) is True
    # DISPATCHED won: the cancel cannot hand anything back, the sweep cannot either
    assert await led.call("clt_wrk", "cancel_permit", rep, tok["generation"]) is False
    await led.conn.execute("UPDATE change_ledger.dispatch_permits SET expires_at=now()-interval '1 second'")
    assert await led.call("clt_wrk", "recover_sweep") == 0
    assert await led.tl_owner(BASE, "doc1") == rep
    # an unknown outcome keeps the repair as owner and opens CALL_OWNERSHIP next to the parent's halt
    await led.complete(rep, tok["generation"], "UNKNOWN")
    assert await led.tl_owner(BASE, "doc1") == rep
    assert await led.open_holds("CALL_OWNERSHIP") == 1 and await led.open_holds("FAILED_VERIFY_HALT") == 1
    # second repair of the same halt is impossible while the first one is unresolved
    rep2 = await _repair(led, parent, rid="rep2")
    await fails("BASE_HOLD", led.claimed(rep2, key="4" * 64))
    assert await led.tl_owner(BASE, "doc1") == rep


async def test_repair_applied_and_verified_releases_the_parent_halt(led):
    parent = await _failed_parent(led)
    rep = await _repair(led, parent)
    tok = await led.claimed(rep, key="5" * 64)
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", rep, tok["generation"])
    await led.call("clt_wri", "record_call", rep, tok["generation"], k)
    await led.complete(rep, tok["generation"], "SUCCESS")
    assert await led.verify(rep, True) == "VERIFIED"
    assert await led.open_holds("FAILED_VERIFY_HALT") == 0
    assert await led.tl_owner(BASE, "doc1") is None
    assert (await led.rec(parent))["verification_state"] == "FAILED_VERIFY"      # history is kept


async def test_repair_for_a_parent_that_is_not_failed_verify_is_refused(led):
    ok_parent = await led.approved(request_id="okp")
    tok = await led.claimed(ok_parent)
    k = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok["token_id"], k, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", ok_parent, tok["generation"])
    await led.call("clt_wri", "record_call", ok_parent, tok["generation"], k)
    await led.complete(ok_parent, tok["generation"], "SUCCESS")
    await led.verify(ok_parent, True)
    rep = await _repair(led, ok_parent)
    await fails("PARENT_NOT_VERIFIED", led.claimed(rep, key="5" * 64))


# ============================================================================ kill switch
@pytest.mark.parametrize("mode", ["STOP_ADMIT", "STOP_EFFECTS", "REVOKE"])
async def test_kill_switch_modes_refuse_admission_and_effect_steps_but_not_observation(led, mode):
    proposed = await led.propose(request_id="k1", base="base-1")
    validated = await led.validated(request_id="k2", base="base-2")
    nonce = await led.call("clt_bob", "issue_approval_nonce", validated)
    approved = await led.approved(request_id="k3", base="base-3")
    claimed = await led.approved(request_id="k4", base="base-4")
    ctok = await led.claimed(claimed, key="1" * 64)
    applying, atok, _ = await led.applying(request_id="k5", base="base-5")
    await led.checkpoint()
    permitted, ptok, pcall, _ = await led.permitted(request_id="k6", base="base-6")
    dispatched, dtok, _ = await led.dispatched(request_id="k7", base="base-7")
    await fails("permission denied", led.call("clt_alice", "kill_switch", mode))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "kill_switch", "PANIC"))
    assert await led.call("clt_dave", "kill_switch", mode) == mode
    await fails("KILL_SWITCH_ACTIVE", led.propose(request_id="k8", base="base-8"))
    await fails("KILL_SWITCH_ACTIVE", led.call("clt_alice", "validate", proposed))
    await fails("KILL_SWITCH_ACTIVE", led.call("clt_bob", "approve", validated, nonce, DIGEST))
    await fails("KILL_SWITCH_ACTIVE", led.claimed(approved, key="2" * 64))
    await fails("KILL_SWITCH_ACTIVE", led.call("clt_alice", "begin_apply", ctok["token_id"], uuid.uuid4(), "h", "s"))
    await fails("KILL_SWITCH_ACTIVE", led.call("clt_wrk", "issue_permit", applying, atok["generation"]))
    await fails("KILL_SWITCH_ACTIVE", led.call("clt_wri", "record_call", permitted, ptok["generation"], pcall))
    assert (await led.rec(permitted))["dispatch_state"] == "PERMITTED"
    # a pre-dispatch claim is released by the sweep (T5x) and a not-yet-dispatched permit can be cancelled
    assert await led.call("clt_wrk", "cancel_permit", permitted, ptok["generation"]) is True
    await led.conn.execute("UPDATE change_ledger.claim_tokens SET issued_at=now()-interval '3 minutes' "
                           "WHERE token_id=$1", ctok["token_id"])
    # REVOKE additionally voids the unclaimed approvals (contract section 6), so the sweep changes more
    # 008 B6c: a stop mode also unwinds the permit-less APPLYING change (T6r) at once: one more change than before
    assert await led.call("clt_wrk", "recover_sweep") == (4 if mode == "REVOKE" else 2)
    # in-flight DISPATCHED call follows the call: complete is allowed under every mode
    assert await led.complete(dispatched, dtok["generation"], "SUCCESS") == "APPLIED"
    assert await led.verify(dispatched, True) == "VERIFIED"
    # events of the switch are on the chain and the chain still verifies
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE event_type='KILL_SWITCH' "
                                   "AND payload->>'mode'=$1", mode) == 1
    await led.call("clt_dave", "kill_switch", "OFF")
    await led.propose(request_id="k9", base="base-8")


# ============================================================================ anchor
async def test_check_anchor_detects_a_restored_older_ledger_with_an_anchor_gap_hold(led):
    await led.approved(request_id="an1", base="base-1")
    await led.checkpoint()
    head = await led.call("clt_wrk", "ledger_head")
    assert await led.call("clt_wrk", "check_anchor", head["seq"], head["head_hash"]) == \
        {"ok": True, "holds_opened": 0}
    assert await led.open_holds() == 0
    # more history is anchored externally, then the ledger is "restored" to an older state
    later = await led.approved(request_id="an2", base="base-2")
    await led.checkpoint()
    anchored = await led.call("clt_wrk", "ledger_head")
    assert anchored["seq"] > head["seq"]
    await led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    await led.conn.execute("DELETE FROM change_ledger.events WHERE seq>$1", head["seq"])
    await led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
    got = await led.call("clt_wrk", "check_anchor", anchored["seq"], anchored["head_hash"])
    assert got["ok"] is False and got["holds_opened"] == len(BASES)
    assert await led.open_holds("ANCHOR_GAP") == len(BASES)
    # no further effect is possible on any base
    fresh = await led.approved(request_id="an3", base="base-3")
    await fails("BASE_HOLD", led.claimed(fresh, key="3" * 64))
    # idempotent: a second detection does not stack holds
    again = await led.call("clt_wrk", "check_anchor", anchored["seq"], anchored["head_hash"])
    assert again["holds_opened"] == 0 and await led.open_holds("ANCHOR_GAP") == len(BASES)
    # a diverged hash at an existing seq is detected too (same length, different history)
    await led.conn.execute("DELETE FROM change_ledger.holds")
    await fails("permission denied", led.sql("clt_aud", "SELECT change_ledger.check_anchor('T1','C1',1,'x')"))
    div = await led.call("clt_wrk", "check_anchor", head["seq"], "9" * 64)
    assert div["ok"] is False
    assert later is not None


# ============================================================================ S13 batch A (007_change_hardening_a.sql)
# One focused group per finding A1-A8 of docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md. Every assertion names a
# behavior the guard produces; nothing here removes or weakens a guard.
RAW_SIGS = [
    "change_ledger.complete(text,text,uuid,bigint,text,jsonb,jsonb)",
    "change_ledger.resolve_unknown(text,text,uuid,jsonb,boolean,boolean)",
    "change_ledger.verify(text,text,uuid,jsonb,boolean)",
    "change_ledger.witness_cosign(text,text,uuid,jsonb)",
]
RAW_CALLS = [
    ("complete", "gen_random_uuid(),1,'SUCCESS','{}'::jsonb,NULL"),
    ("resolve_unknown", "gen_random_uuid(),'{}'::jsonb,true,true"),
    ("verify", "gen_random_uuid(),'{}'::jsonb,true"),
    ("witness_cosign", "gen_random_uuid(),'{}'::jsonb"),
]


async def owner_call(led, sql, *args):
    """Call an internal function as ledger_owner (what the signed wrappers do); never granted to runtime roles."""
    await led.conn.execute("SELECT change_ledger.add_role_scope('ledger_owner',$1,$2)", T, C)
    async with led.conn.transaction():
        await led.conn.execute('SET LOCAL ROLE "ledger_owner"')
        await led.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await led.conn.fetchval(sql, T, C, *args)


async def ev_count(led, cid=None):
    return await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE ($1::uuid IS NULL OR change_id=$1)", cid)


async def test_a1_raw_completion_and_verdict_functions_are_closed_to_every_runtime_role(led):
    for sig in RAW_SIGS:
        for role in RUNTIME_ROLES:
            assert not await led.conn.fetchval("SELECT has_function_privilege($1,$2,'EXECUTE')", role, sig), (sig, role)
    for actor in ("clt_wri", "clt_wrk", "clt_dave", "clt_erin", "clt_alice", "clt_bob", "clt_aud", "clt_chk"):
        for fn, args in RAW_CALLS:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):      # port maps SQLSTATE 42501 to NOT_ENTITLED
                await led.sql(actor, f"SELECT change_ledger.{fn}('T1','C1',{args})")
    # the signed wrappers stay callable by their own class
    for role, sig in (("writer_role", "change_ledger.complete_signed(text,text,uuid,bigint,text,uuid)"),
                      ("worker_role", "change_ledger.verify_signed(text,text,uuid,uuid,uuid,uuid)"),
                      ("worker_role", "change_ledger.retry_verify(text,text,uuid,uuid,uuid,uuid)"),
                      ("worker_role", "change_ledger.verify_inconclusive(text,text,uuid,uuid)"),
                      ("writer_role", "change_ledger.complete_lock_busy(text,text,uuid,bigint,uuid,jsonb)"),
                      ("operator_role", "change_ledger.witness_cosign_signed(text,text,uuid,uuid)")):
        assert await led.conn.fetchval("SELECT has_function_privilege($1,$2,'EXECUTE')", role, sig), (role, sig)


async def test_a1_evidence_content_hash_generation_and_call_id_are_bound(led):
    cid, tok, call_id = await led.dispatched(request_id="a1h", base="base-1")
    gen = tok["generation"]
    n0 = await led.conn.fetchval("SELECT count(*) FROM change_ledger.evidence_records")
    # content_hash must be the hash of the content
    await fails("DIGEST_MISMATCH", led.evidence(cid, "OBSERVATION", {"x": 1}, ch="e" * 64))
    # the signature covers generation and call id: a binding made for another generation / call is refused
    at = datetime.now(UTC) + timedelta(seconds=1)
    full = {"generation": gen, "call_id": str(call_id), "nonce": "n-bound", "x": 1}
    ch = await led.conn.fetchval("SELECT change_ledger.canonical_content_hash($1::jsonb)", json.dumps(full))
    wrong = await led.conn.fetchval("SELECT change_ledger.evidence_binding($1,'OBSERVATION',$2,$3,$4,$5)",
                                    cid, ch, at, gen + 1, call_id)
    await fails("DIGEST_MISMATCH", led.evidence(cid, "OBSERVATION", {"nonce": "n-bound", "x": 1}, at=at,
                                                bind=wrong, sig=sha("W" * 32 + ":" + wrong)))
    wrong_call = await led.conn.fetchval("SELECT change_ledger.evidence_binding($1,'OBSERVATION',$2,$3,$4,$5)",
                                         cid, ch, at, gen, uuid.uuid4())
    await fails("DIGEST_MISMATCH", led.evidence(cid, "OBSERVATION", {"nonce": "n-bound", "x": 1}, at=at,
                                                bind=wrong_call, sig=sha("W" * 32 + ":" + wrong_call)))
    # another generation or another call id (consistently signed) is refused
    await fails("TICKET_SUPERSEDED", led.evidence(cid, "OBSERVATION", {"x": 2}, gen=gen + 1))
    await fails("PERMIT_MISSING", led.evidence(cid, "OBSERVATION", {"x": 3}, call_id=uuid.uuid4()))
    # the typed content must repeat the generation of the call
    await fails("SCHEMA_INVALID", led.evidence(cid, "OBSERVATION", {"x": 4, "generation": gen + 5}))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.evidence_records") == n0
    ok = await led.evidence(cid, "OBSERVATION", {"x": 5})
    row = await led.conn.fetchrow("SELECT generation, call_id FROM change_ledger.evidence_records "
                                  "WHERE evidence_id=$1", ok)
    assert (row["generation"], row["call_id"]) == (gen, call_id)


async def test_a1_outcome_is_derived_from_the_typed_signed_record_not_from_flags(led):
    cid, tok, call_id, _ = await led.permitted(request_id="a1o", base="base-1")
    gen = tok["generation"]
    other, otok, _, _ = await led.permitted(request_id="a1o2", base="base-2")
    refusal = {"class": "a", "result_returned": False, "stage": "PRE_WRITE", "refusal_code": "STALE_VERSION",
               "no_effect_proof": {"proof": "no-effect"}}
    succ = await led.evidence(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": True}, role="clt_wri")
    # a SUCCESS record cannot back a PRE_WRITE_REFUSAL
    await fails("WRITE_REFUSED", led.call("clt_wri", "complete_signed", cid, gen, "PRE_WRITE_REFUSAL", succ))
    # a refusal record cannot back SUCCESS
    ref = await led.evidence(cid, "COMPLETION_PROOF", refusal, role="clt_wri")
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_wri", "complete_signed", cid, gen, "SUCCESS", ref))
    # a worker (class b) proof never completes; a record of another change or generation is refused
    wproof = await led.evidence(cid, "COMPLETION_PROOF", {"class": "b", "result_returned": True}, role="clt_wrk")
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_wri", "complete_signed", cid, gen, "SUCCESS", wproof))
    foreign = await led.evidence(other, "COMPLETION_PROOF", refusal, role="clt_wri")
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wri", "complete_signed", cid, gen, "PRE_WRITE_REFUSAL", foreign))
    await fails("TICKET_SUPERSEDED", led.call("clt_wri", "complete_signed", cid, gen + 1, "PRE_WRITE_REFUSAL", ref))
    # refusal records that fail the typed rules: wrong stage, code outside the closed set, no or empty proof
    bad_stage = await led.evidence(cid, "COMPLETION_PROOF", {**refusal, "stage": "WRITE"}, role="clt_wri")
    await fails("WRITE_REFUSED", led.call("clt_wri", "complete_signed", cid, gen, "PRE_WRITE_REFUSAL", bad_stage))
    await fails("WRITE_REFUSED", led.complete(cid, gen, "PRE_WRITE_REFUSAL", proof={"p": 1}, code="BOGUS"))
    await fails("WRITE_REFUSED", led.complete(cid, gen, "PRE_WRITE_REFUSAL", proof=None))
    await fails("WRITE_REFUSED", led.complete(cid, gen, "PRE_WRITE_REFUSAL", proof={}))
    assert (await led.rec(cid))["execution_state"] == "APPLYING" and await led.locks(cid) == (1, 1, 1)
    # a call without a completion record at all
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wri", "complete_signed", cid, gen, "PRE_WRITE_REFUSAL", None))
    # the well-typed refusal and the well-typed success are accepted
    assert await led.call("clt_wri", "complete_signed", cid, gen, "PRE_WRITE_REFUSAL", ref) == "FAILED_APPLY"
    d, dtok, _ = await led.dispatched(request_id="a1o3", base="base-3")
    assert await led.complete(d, dtok["generation"], "SUCCESS") == "APPLIED"


async def test_a1_verdicts_and_resolutions_derive_from_signed_records(led):
    # verify: one mismatching record fails the verification, there is no caller flag to say otherwise
    cid, tok, _ = await led.dispatched(request_id="a1v", base="base-1")
    await led.complete(cid, tok["generation"], "SUCCESS")
    ids = [await led.evidence(cid, k, {"matches": m})
           for k, m in (("FIELD", True), ("MOVEMENT", False), ("VERSION", True))]
    assert await led.call("clt_wrk", "verify_signed", cid, *ids) == "FAILED_VERIFY"
    # retry_verify takes evidence ids; no evidence is EVIDENCE_UNSIGNED, passing records release the halt
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wrk", "retry_verify", cid, None, None, None))
    assert await led.verify(cid, True, fn="retry_verify") == "VERIFIED"
    assert await led.open_holds("FAILED_VERIFY_HALT") == 0
    # verify_inconclusive needs a signed observation that says inconclusive
    inc, itok, _ = await led.dispatched(request_id="a1i", base="base-2")
    await led.complete(inc, itok["generation"], "SUCCESS")
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wrk", "verify_inconclusive", inc, None))
    plain = await led.observation(inc, False)
    await fails("EVIDENCE_UNSIGNED", led.call("clt_wrk", "verify_inconclusive", inc, plain))
    obs = await led.observation(inc, None, inconclusive=True)
    got = json.loads(await led.call("clt_wrk", "verify_inconclusive", inc, obs))
    assert got == {"attempts": 1, "exhausted": False}
    # resolve_unknown_signed: the caller's found flag must equal the signed observation
    unk, _, _ = await led.unknown(request_id="a1u", base="base-3")
    o = await led.observation(unk, False)
    await fails("DIGEST_MISMATCH", led.call("clt_wrk", "resolve_unknown_signed", unk, o, None, True, False))
    assert (await led.rec(unk))["execution_state"] == "APPLY_UNKNOWN"
    # operator_resolve(present=false) needs a signed observation with effect_present = false
    tri, _, _ = await led.triage(request_id="a1t", base="base-4")          # triage recorded effect_present = true
    w = await led.cosign("clt_erin", tri, cls="b")
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "operator_resolve", tri, w, False, False))
    assert (await led.rec(tri))["execution_state"] == "TRIAGE_REQUIRED"
    assert await led.conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns "
                                   "WHERE cosign_id=$1", w)
    await led.observation(tri, False)
    assert await led.call("clt_dave", "operator_resolve", tri, w, False, False) == "FAILED_APPLY"
    # complete_lock_busy takes the writer's evidence id and only a LOCK_BUSY refusal record
    lb, lbtok, _ = await led.applying(request_id="a1l", base="base-5")
    await fails("WRITE_REFUSED", led.call("clt_wri", "complete_lock_busy", lb, lbtok["generation"], None))
    body = {"class": "a", "result_returned": False, "stage": "PRE_WRITE", "no_effect_proof": {"p": 1}}
    stale = await led.evidence(lb, "COMPLETION_PROOF", {**body, "refusal_code": "STALE_VERSION"}, role="clt_wri")
    await fails("WRITE_REFUSED", led.call("clt_wri", "complete_lock_busy", lb, lbtok["generation"], stale))
    busy = await led.evidence(lb, "COMPLETION_PROOF", {**body, "refusal_code": "LOCK_BUSY"}, role="clt_wri")
    assert await led.call("clt_wri", "complete_lock_busy", lb, lbtok["generation"], busy) == "APPROVED"


async def test_a1_witness_cosign_needs_a_completion_proof_of_the_current_generation(led):
    cid = await led.approved(request_id="a1w", base="base-1")
    tok1 = await led.claimed(cid)
    await led.call("clt_alice", "begin_apply", tok1["token_id"], uuid.uuid4(), "h", "s")
    old = await led.evidence(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": False}, role="clt_wri")
    # 008 (B5): the permit TTL is a ledger constant / the operator's policy row, no worker parameter any more
    await led.conn.execute("INSERT INTO change_ledger.sweep_policy(tenant_id,company_id,params,updated_by) "
                           "VALUES($1,$2,'{\"permit_ttl_seconds\":0}'::jsonb,'fixture')", T, C)
    await led.call("clt_wrk", "recover_sweep", "{}")                                          # T6r releases the claim
    await led.conn.execute("DELETE FROM change_ledger.sweep_policy")
    tok2 = await led.claimed(cid)
    assert tok2["generation"] == 2
    call2 = uuid.uuid4()
    await led.call("clt_alice", "begin_apply", tok2["token_id"], call2, "h", "s")
    await led.checkpoint()
    await led.call("clt_wrk", "issue_permit", cid, 2)
    assert await led.call("clt_wri", "record_call", cid, 2, call2) is True
    assert await led.complete(cid, 2, "SUCCESS") == "APPLIED"
    assert await led.verify(cid, False) == "FAILED_VERIFY"
    await fails("TICKET_SUPERSEDED", led.call("clt_erin", "witness_cosign_signed", cid, old))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.witness_cosigns WHERE change_id=$1", cid) == 0
    assert await led.cosign("clt_erin", cid)                                               # current generation


async def _approved_with_spare_nonce(led, builder, **kw):
    cid = await builder(**kw)
    nonce = uuid.uuid4().hex + uuid.uuid4().hex
    await led.conn.execute("INSERT INTO change_ledger.approval_nonces(nonce,change_id,approver,expires_at) "
                           "VALUES($1,$2,'clt_bob',now()+interval '1 hour')", nonce, cid)
    return cid, nonce


async def test_a2_finished_or_running_changes_cannot_be_approved_or_get_a_nonce_again(led):
    async def failed_apply(**kw):
        cid, tok, _, _ = await led.permitted(**kw)
        assert await led.complete(cid, tok["generation"], "PRE_WRITE_REFUSAL", proof={"p": 1}) == "FAILED_APPLY"
        return cid

    async def verified(**kw):
        cid, tok, _ = await led.dispatched(**kw)
        await led.complete(cid, tok["generation"], "SUCCESS")
        assert await led.verify(cid, True) == "VERIFIED"
        return cid

    async def applying(**kw):
        return (await led.applying(**kw))[0]

    async def triage(**kw):
        return (await led.triage(**kw))[0]

    cases = [("FAILED_APPLY", failed_apply), ("VERIFIED", verified), ("APPLYING", applying),
             ("TRIAGE_REQUIRED", triage)]
    for i, (expect, builder) in enumerate(cases, start=1):
        cid, nonce = await _approved_with_spare_nonce(led, builder, request_id=f"a2-{i}", base=f"base-{i}")
        r = await led.rec(cid)
        assert expect in (r["execution_state"], r["verification_state"]), (expect, dict(r))
        before = (r["authorization_state"], r["execution_state"], r["verification_state"], await ev_count(led, cid))
        await fails("FORBIDDEN_TRANSITION", led.call("clt_carol", "issue_approval_nonce", cid))
        await fails("FORBIDDEN_TRANSITION",
                    led.call("clt_bob", "approve", cid, nonce, (await led.status(cid))["approval_digest"]))  # 009: no new text can be stored once approved
        r = await led.rec(cid)
        after = (r["authorization_state"], r["execution_state"], r["verification_state"], await ev_count(led, cid))
        assert after == before
    # control: a REVOKED approval of an unstarted change may be approved again
    o = await led.approved(request_id="a2-r", base="base-5")
    assert await led.call("clt_dave", "revoke_change", o, "SESSION_REVOKED") == "REVOKED"
    nonce = await led.call("clt_bob", "issue_approval_nonce", o)
    await led.call("clt_bob", "approve", o, nonce, await led.approval_digest(o))
    assert (await led.rec(o))["authorization_state"] == "APPROVED"


async def test_a3_failed_verify_cannot_be_flipped_and_the_halt_stays_single(led):
    cid, tok, _ = await led.dispatched(request_id="a3", base="base-1")
    await led.complete(cid, tok["generation"], "SUCCESS")
    assert await led.verify(cid, False) == "FAILED_VERIFY"
    await fails("FORBIDDEN_TRANSITION", led.verify(cid, True))
    assert (await led.rec(cid))["verification_state"] == "FAILED_VERIFY"
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1 and await led.locks(cid) == (1, 0, 0)
    await fails("FORBIDDEN_TRANSITION", led.verify(cid, False))
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.holds WHERE change_id=$1 AND "
                                   "cause='FAILED_VERIFY_HALT'", cid) == 1
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND "
                                   "event_type LIKE 'VERIFY\\_%'", cid) == 1


async def _repair_unknown(led, parent, rid):
    return await led.unknown(kind="UNPOST", parent=parent, repair_for=parent, target="doc1", request_id=rid,
                             approver="clt_carol")


async def test_a4_t11_and_t16_absent_on_a_repair_hand_the_target_lock_back_to_the_parent(led):
    parent = await _failed_parent(led)
    # T11: unknown outcome of a repair resolved as absent
    r1, _, _ = await _repair_unknown(led, parent, "a4-1")
    assert await led.tl_owner(BASE, "doc1") == r1
    assert await led.resolve_unknown(r1, False, proof="b") == "FAILED_APPLY"
    assert await led.tl_owner(BASE, "doc1") == parent and await led.locks(r1) == (0, 0, 0)
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1 and await led.open_holds("CALL_OWNERSHIP") == 0
    # T16: unknown outcome of a second repair, triaged, resolved absent by two operators
    r2, _, _ = await _repair_unknown(led, parent, "a4-2")
    assert await led.resolve_unknown(r2, True) == "TRIAGE_REQUIRED"
    w = await led.cosign("clt_erin", r2, cls="b", present=False)
    assert await led.call("clt_dave", "operator_resolve", r2, w, False, False) == "FAILED_APPLY"
    assert await led.tl_owner(BASE, "doc1") == parent and await led.locks(r2) == (0, 0, 0)
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1 and await led.open_holds("CALL_OWNERSHIP") == 0
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.target_locks WHERE target_ref='doc1'") == 1
    # a new repair claim succeeds because the parent owns the lock again
    r3 = await _repair(led, parent, rid="a4-3")
    await led.claimed(r3, key="3" * 64)
    assert await led.tl_owner(BASE, "doc1") == r3


async def test_a5_null_inputs_fail_closed_and_change_nothing(led):
    cid, tok, _ = await led.dispatched(request_id="a5", base="base-1")
    gen = tok["generation"]
    before = (await ev_count(led, cid), (await led.rec(cid))["execution_state"])
    # NULL generation: the fence must not be skipped (wrapper and the raw internal)
    await fails("SCHEMA_INVALID", led.call("clt_wri", "complete_signed", cid, None, "UNKNOWN", None))
    await fails("SCHEMA_INVALID", owner_call(
        led, "SELECT change_ledger.complete($1,$2,$3,NULL,'SUCCESS','{}'::jsonb,NULL)", cid))
    await fails("SCHEMA_INVALID", owner_call(
        led, "SELECT change_ledger.complete($1,$2,$3,$4,NULL,'{}'::jsonb,NULL)", cid, gen))
    assert (await ev_count(led, cid), (await led.rec(cid))["execution_state"]) == before
    # NULL found on the raw resolve_unknown: refused; the signed inconclusive path goes to triage explicitly
    unk, _, _ = await led.unknown(request_id="a5u", base="base-2")
    await fails("SCHEMA_INVALID", owner_call(
        led, "SELECT change_ledger.resolve_unknown($1,$2,$3,'{}'::jsonb,NULL,false)", unk))
    assert (await led.rec(unk))["execution_state"] == "APPLY_UNKNOWN"
    assert await led.resolve_unknown(unk, None) == "TRIAGE_REQUIRED"
    # NULL present / attributed on operator_resolve: refused, the cosign stays unconsumed, nothing changes
    tri, _, _ = await led.triage(request_id="a5t", base="base-3")
    w = await led.cosign("clt_erin", tri, cls="b", present=False)
    n = await ev_count(led, tri)
    await fails("SCHEMA_INVALID", led.call("clt_dave", "operator_resolve", tri, w, None, False))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "operator_resolve", tri, w, False, None))
    assert (await led.rec(tri))["execution_state"] == "TRIAGE_REQUIRED" and await ev_count(led, tri) == n
    assert await led.conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns "
                                   "WHERE cosign_id=$1", w)
    assert await led.open_holds("CALL_OWNERSHIP") == 2                      # unk (triaged) and tri still hold


async def test_a6_only_the_checkpoint_identity_writes_checkpoints_and_signs_permits(led):
    cid, tok, call_id = await led.applying(request_id="a6", base="base-1")
    gen = tok["generation"]
    head = await led.head()
    for role in ("clt_wrk", "clt_wri", "clt_alice", "clt_bob", "clt_dave", "clt_aud"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):             # NOT_ENTITLED in the port
            await led.checkpoint_at(head["seq"], head["head_hash"], "REAL", True, role=role)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.sql("clt_wrk", "SELECT change_ledger.attach_permit_signature("
                      "'T1','C1',gen_random_uuid(),1,'vk-chk','x')")
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == 0
    # rows not written by the checkpoint identity never gate issue_permit, whatever they claim
    for verified in (False, True):
        await led.conn.execute(
            "INSERT INTO change_ledger.checkpoints(tenant_id,company_id,ledger_seq,head_hash,sink_kind,sink_id,"
            "signer_key_id,signature,signed_at,read_back_confirmed,verified) VALUES($1,$2,$3,$4,'REAL','forged',"
            "'vk-chk','x',now(),true,$5)", T, C, head["seq"], head["head_hash"], verified)
        await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_wrk", "issue_permit", cid, gen))
    # a bad signature, an unknown key, a key of another identity and a signature over another head are refused
    sa = datetime.now(UTC)
    other_payload = await led.conn.fetchval("SELECT change_ledger.checkpoint_payload($1,$2,$3,$4,$5,$6,$7,$8)",
                                            T, C, head["seq"], "f" * 64, sa, "vk-chk", "REAL", "sink-1")
    for kw in (dict(sig="0" * 64), dict(key_id="vk-unknown"), dict(key_id="vk-wrk"),
               dict(sig=sha("C" * 32 + ":" + other_payload), signed_at=sa)):
        await fails("CHECKPOINT_UNAVAILABLE", led.checkpoint_at(head["seq"], head["head_hash"], **kw))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == 2
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_wrk", "issue_permit", cid, gen))
    # the checkpoint identity with a valid keyed signature: stored verified, permit issued
    await led.checkpoint()
    row = await led.conn.fetchrow("SELECT sink_kind, read_back_confirmed, verified, written_by "
                                  "FROM change_ledger.checkpoints WHERE written_by IS NOT NULL")
    assert tuple(row) == ("REAL", True, True, "clt_chk")
    permit = await led.call("clt_wrk", "issue_permit", cid, gen)
    good = sha("C" * 32 + ":change-ledger-permit|v1|" + permit["permit_digest"])
    for role in ("clt_wrk", "clt_wri"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.call(role, "attach_permit_signature", cid, gen, "vk-chk", good)
    await fails("CHECKPOINT_UNAVAILABLE",
                led.call("clt_chk", "attach_permit_signature", cid, gen, "vk-chk", "0" * 64))
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_chk", "attach_permit_signature", cid, gen, "vk-wrk", good))
    assert await led.conn.fetchval("SELECT signature FROM change_ledger.dispatch_permits "
                                   "WHERE change_id=$1", cid) is None
    await led.call("clt_chk", "attach_permit_signature", cid, gen, "vk-chk", good)
    got = await led.conn.fetchrow("SELECT signer_key_id, signature FROM change_ledger.dispatch_permits "
                                  "WHERE change_id=$1", cid)
    assert tuple(got) == ("vk-chk", good)


async def test_a7_approval_digest_is_computed_in_sql_from_the_stored_change(led):
    a = await led.validated(request_id="a7a", target="docA")          # same base, same payload, same version
    b = await led.validated(request_id="a7b", target="docB")
    nonce = await led.call("clt_bob", "issue_approval_nonce", a)       # 009: the digest is that of the stored text
    await led.call("clt_bob", "issue_approval_nonce", b)
    await led.approval_digest(a)
    await led.approval_digest(b)
    sa, sb = await led.status(a), await led.status(b)
    assert sa["payload_digest"] == sb["payload_digest"] == DIGEST
    assert sa["target_version"] == sb["target_version"] == "v1"
    assert (sa["target_ref"], sb["target_ref"]) == ("docA", "docB")
    assert len(sa["approval_digest"]) == 64 and sa["approval_digest"] != sb["approval_digest"]
    assert sa["approval_digest"] != DIGEST
    assert sa["rule_table_version"] and sa["allowed_effects"] == [] and sa["parent_change_id"] is None
    # the parent changes the digest too, and POST carries server-derived allowed effects
    p1 = await led.propose(kind="POST", parent=a, request_id="a7p1", base="base-2", target="docP")
    p2 = await led.propose(kind="POST", parent=b, request_id="a7p2", base="base-2", target="docP")
    for p in (p1, p2):
        await led.call("clt_bob", "issue_approval_nonce", p)
        await led.approval_digest(p)
    s1, s2 = await led.status(p1), await led.status(p2)
    assert s1["approval_digest"] != s2["approval_digest"] and len(s1["allowed_effects"]) == 2
    assert s1["parent_change_id"] == str(a)
    # approve compares against the SQL digest: another change's digest and the opaque payload digest are refused
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", a, nonce, sb["approval_digest"]))
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", a, nonce, DIGEST))
    assert (await led.rec(a))["authorization_state"] == "NONE"
    await led.call("clt_bob", "approve", a, nonce, sa["approval_digest"])
    done = await led.status(a)
    assert done["approved_digest"] == sa["approval_digest"] == done["approval_digest"]
    stored = await led.conn.fetchval("SELECT digest FROM change_ledger.approvals WHERE change_id=$1", a)
    assert stored == sa["approval_digest"]


async def test_a8_two_person_cosign_compares_persons_and_capabilities_under_an_enforced_registry(led):
    cid, tok, _ = await led.dispatched(request_id="a8", base="base-1")
    await led.complete(cid, tok["generation"], "SUCCESS")
    assert await led.verify(cid, False) == "FAILED_VERIFY"
    w = await led.cosign("clt_erin", cid)                                   # signed before the registry is enforced
    await led.conn.execute("GRANT operator_role TO clt_carol")

    async def reg(principal, person, caps):
        await led.call("clt_carol", "register_principal", principal, person, caps, True)

    await reg("clt_carol", "P-ADMIN", ["operator"])
    await reg("clt_dave", "P-OP", ["operator"])
    await reg("clt_erin", "P-OP", ["operator", "recovery_witness"])         # the witness is the operator's alias
    await reg("clt_alice", "P-REQ", ["requester"])
    assert await led.call("clt_carol", "enforce_registry") is True

    def close():
        return led.call("clt_dave", "operator_close_failed_verify", cid, w, True)

    await fails("APPROVER_NOT_INDEPENDENT", close())                        # different role names, one person
    await reg("clt_erin", "P-WIT", ["operator"])                            # distinct person, no witness capability
    await fails("NOT_ENTITLED", close())
    await reg("clt_erin", "P-WIT", ["operator", "recovery_witness"])
    await reg("clt_dave", "P-OP", ["approver"])                             # the operator lacks the capability
    await fails("NOT_ENTITLED", close())
    assert await led.open_holds("FAILED_VERIFY_HALT") == 1
    assert await led.conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns "
                                   "WHERE cosign_id=$1", w)
    await reg("clt_dave", "P-OP", ["operator"])
    assert await close() == "CLOSED"
    assert await led.open_holds("FAILED_VERIFY_HALT") == 0
