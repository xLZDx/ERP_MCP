"""pg_dump / pg_restore round trip of the change_ledger schema (migrations 001-007).

Closes the open gap "no pg_dump/pg_restore round trip was run" of core/DECISION_LOG.md. Self-contained on purpose:
it applies only db/phase2/001..007 and drives the ledger with its own small driver, so it does not depend on the
shared harness or on the other change-ledger test files.

Design. Database A gets 001-007, the runtime actors and a journey through the ledger functions (propose, validate,
approve, claim, begin_apply, checkpoint, permit, dispatch, a signed completion, a signed verification, a kill switch
event and a second tenant). `pg_dump -Fc -n change_ledger` runs INSIDE the disposable container, `pg_restore
--exit-on-error` restores into an empty database B of the same server (cluster-level roles are shared, so the roles
the grants refer to exist, exactly the precondition of a restore onto a prepared cluster). Then A and B are compared:
hash chain and head, row contents of every table, the catalog facts the hardening depends on (owners, ACLs, RLS flags
and policies, security definer + search_path settings, triggers, constraints, indexes) and the behaviour of the
guards (immutable event log, RLS, revoked raw functions), and B must keep chaining from the restored head.

Docker safety: the test only ever execs into the container that publishes the port of ERP_PHASE2_TEST_DSN and whose
name starts with r2-s13-dump- (and whose cluster identity equals the DSN's). Without ERP_PHASE2_TEST_DSN: skip
NOT_RUN, or fail when ERP_PHASE2_REQUIRE_PG=1.

Documented pg_dump limitation (asserted below, not hidden): a schema-selective dump (-n change_ledger) does not carry
the database-wide `ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC` of
004 (a pg_default_acl row without a schema). It only affects objects ledger_owner creates LATER; the ACL of every
existing object is dumped explicitly and is compared one by one.
"""
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import pytest
from _approval_envelope import FIXTURE_DIGEST, FIXTURE_PAYLOAD, ensure_envelope
from _ed25519_fixtures import pub_hex, sign_hex

from business_ai_gateway.phase2.change import canonical_json

pytestmark = pytest.mark.integration

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "phase2"
FILES = ("001_living_registry.sql", "002_job_cursor_functions.sql", "003_security_hardening.sql",
         "004_change_ledger.sql", "005_change_registry.sql", "006_change_sweeps.sql", "007_change_hardening_a.sql",
         "008_change_hardening_b.sql", "009_approval_digest_2.sql", "010_registry_session_hardening.sql",
         "011_event_hash_v2.sql", "012_dispatch_session_hardening.sql", "013_dispatched_invariant.sql",
         "014_ed25519_verify.sql", "015_ed25519_signatures.sql", "016_dispatch_receipt.sql", "017_receipt_hardening.sql")
CONTAINER_PREFIX = "r2-s13-dump-"

T, C = "T1", "C1"
T2, C2 = "T2", "C2"
ORG = "org-1"
DIGEST = FIXTURE_DIGEST  # S12-APPROVAL-2: the ledger recomputes the payload digest of the stored envelope
KH = "b" * 64
DEFAULT_GRANT = {(T, C): uuid.UUID("00000000-0000-4000-8000-0000000000a1"),
                 (T2, C2): uuid.UUID("00000000-0000-4000-8000-0000000000a2")}
ACTORS = {
    "clt_alice": (["requester_role"], [(T, C)]),
    "clt_bob": (["approver_role"], [(T, C)]),
    "clt_dave": (["operator_role", "requester_role"], [(T, C)]),
    "clt_wri": (["writer_role"], [(T, C)]),
    "clt_wrk": (["worker_role"], [(T, C)]),
    "clt_aud": (["auditor_role"], [(T, C)]),
    "clt_zed": (["requester_role"], [(T2, C2)]),
    "clt_chk": (["checkpoint_role"], [(T, C)]),
}
CAPS = {"clt_alice": ["requester"], "clt_bob": ["approver"], "clt_dave": ["operator", "requester", "recovery_witness"],
        "clt_zed": ["requester"]}
SIGN_KEYS = {"clt_wrk": ("vk-wrk", pub_hex("vk-wrk"), "clt_wrk"), "clt_wri": ("vk-wri", pub_hex("vk-wri"), "clt_wri"),
             "clt_chk": ("vk-chk", pub_hex("vk-chk"), "checkpoint_role")}   # synthetic Ed25519 keys (lane TEST), 015
JSON_FUNCS = {"issue_permit", "ledger_head", "verify_chain", "check_anchor"}
COMPOSITE_FUNCS = {"claim", "begin_apply"}


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def exp(hours=1):
    return datetime.now(UTC) + timedelta(hours=hours)


# ---------------------------------------------------------------------------------------------- environment
def _unavailable(msg):
    if os.environ.get("ERP_PHASE2_REQUIRE_PG") == "1":
        pytest.fail("ERP_PHASE2_REQUIRE_PG=1 but " + msg)
    pytest.skip("NOT_RUN: " + msg)


def _docker(*args, timeout=300):
    exe = (os.environ.get("ERP_PHASE2_DOCKER") or shutil.which("docker")
           or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    return subprocess.run([exe, *args], capture_output=True, timeout=timeout, check=False)


async def _guarded_container(dsn):
    """The disposable container behind the DSN: published port match, name prefix, identical cluster identity."""
    port = urlsplit(dsn).port
    if not port:
        _unavailable("the DSN has no explicit port")
    try:
        ps = _docker("ps", "--filter", f"publish={port}", "--format", "{{.Names}}", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        _unavailable(f"docker is unavailable ({e})")
    names = ps.stdout.decode().split()
    if ps.returncode != 0 or len(names) != 1 or not names[0].startswith(CONTAINER_PREFIX):
        _unavailable(f"no single {CONTAINER_PREFIX}* container publishes port {port} (got {names})")
    name = names[0]
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        via_dsn = await conn.fetchval("SELECT system_identifier FROM pg_control_system()")
    finally:
        await conn.close()
    r = _docker("exec", name, "psql", "-U", "postgres", "-Atc", "SELECT system_identifier FROM pg_control_system()",
                timeout=60)
    assert r.returncode == 0, r.stderr.decode()
    assert int(r.stdout.decode().strip()) == via_dsn, "the DSN does not point at the container"
    return name


# ---------------------------------------------------------------------------------------------- driver
class L:
    """One scoped call = one transaction under SET LOCAL ROLE (same convention as the ledger tests)."""

    def __init__(self, conn):
        self.conn = conn

    async def call(self, role, name, *args, t=T, c=C):
        conn = self.conn
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
        async with self.conn.transaction():
            await self.conn.execute(f'SET LOCAL ROLE "{role}"')
            if t:
                await self.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
            return await self.conn.fetch(sql, *args)

    async def propose(self, requester="clt_alice", base="base-1", target="doc1", t=T, c=C):
        cid = uuid.uuid4()
        got = await self.call(requester, "propose", cid, "CREATE_DRAFT", base, ORG, requester, uuid.uuid4().hex,
                              DIGEST, target, "v1", None, exp(), None, t=t, c=c)
        assert got == cid
        # 008: the business key, the declared target class and the budget inputs are stored with the change
        await self.call(requester, "declare_business_key", cid, sha(str(cid)), None, None, t=t, c=c)
        await self.call(requester, "declare_target_class", cid, "CLONE", t=t, c=c)
        await self.call(requester, "declare_budget", cid, DEFAULT_GRANT[(t, c)], "EUR", 0, False, False, t=t, c=c)
        return cid

    async def validated(self, requester="clt_alice", **kw):
        cid = await self.propose(requester=requester, **kw)
        assert await self.call(requester, "validate", cid,
                               **{k: v for k, v in kw.items() if k in ("t", "c")}) == "VALIDATED"
        return cid

    async def status(self, cid):
        st = await self.call("clt_aud", "read_status", cid)
        return json.loads(st) if isinstance(st, str) else st

    async def approved(self, **kw):
        cid = await self.validated(**kw)
        nonce = await self.call("clt_bob", "issue_approval_nonce", cid)
        await self.call("clt_bob", "approve", cid, nonce, await ensure_envelope(self, cid))
        return cid

    async def checkpoint(self):
        head = await self.call("clt_chk", "ledger_head")
        signed_at = datetime.now(UTC)
        kid, kmat, _ = SIGN_KEYS["clt_chk"]
        payload = await self.conn.fetchval("SELECT change_ledger.checkpoint_payload($1,$2,$3,$4,$5,$6,$7,$8)",
                                           T, C, head["seq"], head["head_hash"], signed_at, kid, "REAL", "sink-1")
        await self.call("clt_chk", "record_checkpoint", head["seq"], head["head_hash"], "REAL", "sink-1", kid,
                        sign_hex(kid, payload), signed_at, True)
        return head

    async def evidence(self, cid, kind, content, role, gen, call_id):
        content = {"generation": gen, "call_id": str(call_id), "nonce": uuid.uuid4().hex, **content} \
            if kind in ("COMPLETION_PROOF", "OBSERVATION") else {"nonce": uuid.uuid4().hex, **content}
        at = datetime.now(UTC) + timedelta(seconds=1)
        ch = await self.conn.fetchval("SELECT change_ledger.canonical_content_hash($1::jsonb)", json.dumps(content))
        b = await self.conn.fetchval("SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
                                     cid, kind, ch, at, gen, call_id)
        kid, kmat, _ = SIGN_KEYS[role]
        return await self.call(role, "record_evidence", cid, kind, ch, at, json.dumps(content), kid, b,
                               sign_hex(kid, b), gen, call_id)


async def _migrate(conn):
    for name in FILES:
        raw = (MIGRATIONS / name).read_bytes()
        await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
        await conn.execute(raw.decode("utf-8"))


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
        if role in CAPS:                 # direct insert: no epoch bump (008 asserts capabilities)
            for t, c in scopes:
                await conn.execute(
                    "INSERT INTO change_ledger.principals(tenant_id,company_id,principal,person_id,capabilities) "
                    "VALUES($1,$2,$3,$4,$5)", t, c, role, "person-" + role, CAPS[role])
    for _actor, (kid, kmat, krole) in SIGN_KEYS.items():
        await conn.execute("INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,"
                           "key_material) VALUES($1,$2,$3,$4,$5)", T, C, kid, krole, kmat)
    for b in ("base-1", "base-2", "base-3", "base-4"):
        await conn.execute("INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,"
                           "organization_ref,target_class) VALUES($1,$2,$3,$4,'DISPOSABLE_CLONE')", T, C, b, ORG)
    await conn.execute("INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,"
                       "target_class) VALUES($1,$2,'base-t2',$3,'DISPOSABLE_CLONE')", T2, C2, ORG)
    for (t, c), gid in DEFAULT_GRANT.items():
        await conn.execute(
            "INSERT INTO change_ledger.grants(grant_id,tenant_id,company_id,currency,amount_limit,count_limit,"
            "post_count_limit,window_start,window_end) VALUES($1,$2,$3,'EUR',1000000,100000,100000,"
            "now()-interval '1 day',now()+interval '3650 days')", gid, t, c)


async def _journey(led):
    """Several chained events: full happy path of change 1, a validated change, an approved+claimed change, a kill
    switch event (NULL change_id), checkpoints, and a second tenant with its own chain."""
    cid = await led.approved()
    tok = await led.call("clt_alice", "claim", cid, None, DEFAULT_GRANT[(T, C)], 0, False, False)
    call_id = uuid.uuid4()
    await led.call("clt_wri", "observe_target", tok["token_id"], "base-1", "CLONE")   # 008: registry enforced
    await led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "host-1", "sess-1")
    await led.checkpoint()
    permit = await led.call("clt_wrk", "issue_permit", cid, tok["generation"])
    assert permit["generation"] == tok["generation"]
    # 012 (A7-B01): the writer verifies the exact payload first; record_call refuses a dispatch without the marker
    assert await led.call("clt_wri", "verify_dispatch_payload", cid, tok["generation"],
                          canonical_json(FIXTURE_PAYLOAD)) is True
    assert await led.call("clt_wri", "record_call", cid, tok["generation"], call_id) is True
    comp = await led.evidence(cid, "COMPLETION_PROOF", {"class": "a", "result_returned": True}, "clt_wri",
                              tok["generation"], call_id)
    assert await led.call("clt_wri", "complete_signed", cid, tok["generation"], "SUCCESS", comp) == "APPLIED"
    ids = [await led.evidence(cid, k, {"matches": True}, "clt_wrk", tok["generation"], call_id)
           for k in ("FIELD", "MOVEMENT", "VERSION")]
    assert await led.call("clt_wrk", "verify_signed", cid, *ids) == "VERIFIED"
    await led.validated(base="base-2", target="doc2")
    await led.approved(base="base-3", target="doc3")
    await led.call("clt_dave", "kill_switch", "OFF")
    await led.checkpoint()
    z = await led.validated(requester="clt_zed", base="base-t2", target="docz", t=T2, c=C2)
    assert z
    return cid


# ---------------------------------------------------------------------------------------------- fingerprints
_ACL = ("(SELECT string_agg(a.grantee::regrole::text||'='||a.privilege_type||CASE WHEN a.is_grantable THEN '*' "
        "ELSE '' END, ',' ORDER BY a.grantee::regrole::text, a.privilege_type) "
        "FROM aclexplode(coalesce({acl}, acldefault({kind}, {owner}))) a)")

CATALOG_SQL = {
    "schema": "SELECT n.nspname||' owner='||pg_get_userbyid(n.nspowner)||' acl='||"
              + _ACL.format(acl="n.nspacl", kind="'n'", owner="n.nspowner")
              + " FROM pg_namespace n WHERE n.nspname='change_ledger'",
    "relations": "SELECT c.relname||' kind='||c.relkind::text||' owner='||pg_get_userbyid(c.relowner)||' rls='||"
                 "c.relrowsecurity||' force='||c.relforcerowsecurity||' persist='||c.relpersistence::text||' acl='||"
                 "coalesce(" + _ACL.format(acl="c.relacl", kind="(CASE WHEN c.relkind='S' THEN 's' ELSE 'r' END)::\"char\"",
                                         owner="c.relowner") + ",'')"
                 " FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='change_ledger' "
                 "AND c.relkind IN ('r','S','v','m','p')",
    "columns": "SELECT c.relname||'.'||a.attname||' type='||format_type(a.atttypid,a.atttypmod)||' notnull='||"
               "a.attnotnull||' ident='||a.attidentity::text||' gen='||a.attgenerated::text||' def='||"
               "coalesce(pg_get_expr(d.adbin,d.adrelid),'')||' acl='||"
               "coalesce((SELECT string_agg(x.grantee::regrole::text||'='||x.privilege_type,',' ORDER BY 1) "
               "FROM aclexplode(a.attacl) x),'') FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
               "JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid "
               "AND d.adnum=a.attnum WHERE n.nspname='change_ledger' AND c.relkind='r' AND a.attnum>0 "
               "AND NOT a.attisdropped",
    "policies": "SELECT p.polrelid::regclass||' '||p.polname||' cmd='||p.polcmd::text||' permissive='||p.polpermissive"
                "||' roles='||coalesce((SELECT string_agg(r.rolname,',' ORDER BY r.rolname) FROM pg_roles r "
                "WHERE r.oid=ANY(p.polroles)),'PUBLIC')||' using='||coalesce(pg_get_expr(p.polqual,p.polrelid),'')"
                "||' check='||coalesce(pg_get_expr(p.polwithcheck,p.polrelid),'') FROM pg_policy p "
                "JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='change_ledger'",
    "functions": "SELECT p.oid::regprocedure||' owner='||pg_get_userbyid(p.proowner)||' secdef='||p.prosecdef||"
                 "' config='||coalesce(p.proconfig::text,'')||' vol='||p.provolatile::text||' strict='||p.proisstrict||"
                 "' leak='||p.proleakproof||' lang='||(SELECT lanname FROM pg_language WHERE oid=p.prolang)||"
                 "' src='||md5(p.prosrc)||' acl='||coalesce("
                 + _ACL.format(acl="p.proacl", kind="'f'", owner="p.proowner") + ",'')"
                 " FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='change_ledger'",
    "triggers": "SELECT t.tgrelid::regclass||' '||t.tgname||' enabled='||t.tgenabled::text||' '||"
                "pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='change_ledger' AND NOT t.tgisinternal",
    "constraints": "SELECT k.conrelid::regclass||' '||k.conname||' '||pg_get_constraintdef(k.oid) FROM pg_constraint k "
                   "JOIN pg_namespace n ON n.oid=k.connamespace WHERE n.nspname='change_ledger'",
    "indexes": "SELECT tablename||' '||indexname||' '||indexdef FROM pg_indexes WHERE schemaname='change_ledger'",
    # the per-database default ACLs of ledger_owner (004 L1395-1396): see the module docstring
    "default_acls": "SELECT pg_get_userbyid(d.defaclrole)||' ns='||coalesce(d.defaclnamespace::regnamespace::text,'-')"
                    "||' type='||d.defaclobjtype::text||' acl='||d.defaclacl::text FROM pg_default_acl d "
                    "WHERE pg_get_userbyid(d.defaclrole)='ledger_owner'",
}


async def catalog(conn):
    return {k: sorted(r[0] for r in await conn.fetch(sql)) for k, sql in CATALOG_SQL.items()}


async def table_data(conn):
    """name -> (row count, md5 over the sorted row texts). Superuser reads bypass RLS."""
    names = [r[0] for r in await conn.fetch(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='change_ledger' AND c.relkind='r' ORDER BY 1")]
    out = {}
    for nm in names:
        out[nm] = tuple(await conn.fetchrow(
            f"SELECT count(*), coalesce(md5(string_agg(x::text, E'\\n' ORDER BY x::text)),'') "
            f'FROM change_ledger."{nm}" x'))
    return out


async def chain_state(conn):
    """Per scope: verify_chain result, head and the full ordered (seq, prev_hash, hash) list."""
    led, out = L(conn), {}
    for t, c, role in ((T, C, "clt_aud"), (T2, C2, "clt_zed")):
        rows = await conn.fetch("SELECT seq, prev_hash, hash FROM change_ledger.events WHERE tenant_id=$1 "
                                "AND company_id=$2 ORDER BY seq", t, c)
        out[(t, c)] = {
            "verify": await led.call(role, "verify_chain", t=t, c=c) if role == "clt_aud" else None,
            "rows": [tuple(r) for r in rows],
        }
    return out


async def probe(conn):
    """Behaviour of the guards, observed identically in A and B (read-only: nothing is committed)."""
    led, got = L(conn), {}

    async def err(coro):
        try:
            await coro
        except asyncpg.PostgresError as e:
            return e.sqlstate, str(e).splitlines()[0]
        return "NO_ERROR", ""

    # immutable event log, even for the superuser (triggers, not privileges)
    for label, stmt in (("update", "UPDATE change_ledger.events SET payload='{}'::jsonb"),
                        ("delete", "DELETE FROM change_ledger.events"),
                        ("truncate", "TRUNCATE change_ledger.events"),
                        ("update_hash", "UPDATE change_ledger.events SET hash=hash"),
                        ("approvals_update", "UPDATE change_ledger.approvals SET digest=digest")):
        got["immutable_" + label] = await err(conn.execute(stmt))
    # RLS: scoped visibility
    got["rls_aud_records"] = sorted({r[0] for r in await led.sql("clt_aud", "SELECT tenant_id FROM change_ledger.records")})
    got["rls_aud_events"] = sorted({r[0] for r in await led.sql("clt_aud", "SELECT tenant_id FROM change_ledger.events")})
    # 008 (B6k): a requester has no direct SELECT on records (status goes through read_status)
    got["rls_zed_records"] = (await err(led.sql("clt_zed", "SELECT tenant_id FROM change_ledger.records",
                                                t=T2, c=C2)))[0]
    got["rls_no_scope"] = await led.sql("clt_aud", "SELECT * FROM change_ledger.records", t=None)
    got["rls_scope_not_granted"] = await err(led.call("clt_aud", "ledger_head", t=T2, c=C2))
    got["rls_grant_table_unreadable"] = (await err(led.sql("clt_aud", "SELECT role_name FROM change_ledger.role_scope")))[0]
    # revoked raw functions and direct DML for a runtime role
    for label, stmt in (
            ("append_event", "SELECT change_ledger.append_event('T1','C1',NULL,'X','{}'::jsonb)"),
            ("budget_reserve", "SELECT change_ledger.budget_reserve('T1','C1',gen_random_uuid(),gen_random_uuid(),1)"),
            ("dispatch_cas", "SELECT change_ledger.dispatch_cas(gen_random_uuid(),1,'PERMITTED','DISPATCHED')"),
            ("insert_event", "INSERT INTO change_ledger.events(tenant_id,company_id,event_type,hash) "
                             "VALUES('T1','C1','X',repeat('a',64))"),
            ("delete_records", "DELETE FROM change_ledger.records"),
            ("update_records", "UPDATE change_ledger.records SET lifecycle='VALIDATED'")):
        got["denied_" + label] = (await err(led.sql("clt_alice", stmt)))[0]
    # a legitimate read still works for the auditor (the grants were not over-restricted by the round trip)
    got["aud_verify"] = await led.call("clt_aud", "verify_chain")
    got["aud_head"] = await led.call("clt_aud", "ledger_head")
    return got


# ---------------------------------------------------------------------------------------------- fixture
class RoundTrip:
    pass


@pytest.fixture
async def rt():
    dsn = os.environ.get("ERP_PHASE2_TEST_DSN")
    if not dsn:
        _unavailable("ERP_PHASE2_TEST_DSN is not set")
    container = await _guarded_container(dsn)
    tag = uuid.uuid4().hex[:8]
    name_a, name_b = f"r2dump_a_{tag}", f"r2dump_b_{tag}"
    admin = await asyncpg.connect(dsn, timeout=10)
    conn_a = conn_b = None
    try:
        await admin.execute(f'CREATE DATABASE "{name_a}"')
        conn_a = await asyncpg.connect(dsn, database=name_a, timeout=10)
        await _migrate(conn_a)
        await _setup(conn_a)
        await _journey(L(conn_a))
        x = RoundTrip()
        x.a_chain, x.a_cat, x.a_data = await chain_state(conn_a), await catalog(conn_a), await table_data(conn_a)
        x.a_probe = await probe(conn_a)
        path = f"/tmp/{name_a}.dump"
        d = _docker("exec", container, "pg_dump", "-U", "postgres", "-d", name_a, "-Fc", "-n", "change_ledger",
                    "-f", path)
        assert d.returncode == 0, d.stderr.decode()
        await admin.execute(f'CREATE DATABASE "{name_b}"')
        r = _docker("exec", container, "pg_restore", "-U", "postgres", "-d", name_b, "--exit-on-error", path)
        x.restore_rc, x.restore_err = r.returncode, r.stderr.decode()
        _docker("exec", container, "rm", "-f", path)
        conn_b = await asyncpg.connect(dsn, database=name_b, timeout=10)
        x.a, x.b = conn_a, conn_b
        x.b_has_living = await conn_b.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname='living'")
        yield x
    finally:
        for c in (conn_a, conn_b):
            if c is not None:
                try:
                    await c.close(timeout=5)
                except Exception:  # noqa: BLE001
                    c.terminate()
        for nm in (name_a, name_b):
            await admin.execute(f'DROP DATABASE IF EXISTS "{nm}" WITH (FORCE)')
        await admin.close()


# ---------------------------------------------------------------------------------------------- tests
async def test_dump_restore_completes_and_the_source_journey_is_real(rt):
    assert rt.restore_rc == 0, rt.restore_err
    # the dump is schema-selective: B really is a restore of change_ledger only, not a re-migration
    assert rt.b_has_living == 0
    assert await rt.b.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname='change_ledger'") == 1
    # the journey produced a real, multi-event chain in A (the comparisons below are not trivially empty)
    t1 = rt.a_chain[(T, C)]
    assert len(t1["rows"]) >= 15 and t1["verify"] == {"ok": True, "count": len(t1["rows"]), "bad_seq": None}
    assert len(rt.a_chain[(T2, C2)]["rows"]) >= 2
    kinds = {r[0] for r in await rt.a.fetch("SELECT DISTINCT event_type FROM change_ledger.events")}
    assert {"PROPOSED", "APPROVED", "CLAIMED"} <= kinds, kinds
    assert rt.a_data["checkpoints"][0] == 2 and rt.a_data["dispatch_permits"][0] == 1
    assert await rt.a.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id IS NULL") >= 1
    rec = await rt.a.fetchrow("SELECT execution_state, verification_state FROM change_ledger.records "
                              "WHERE verification_state='VERIFIED'")
    assert rec is not None and rec["execution_state"] == "APPLIED"


async def test_hash_chain_and_head_survive_the_round_trip(rt):
    assert rt.restore_rc == 0, rt.restore_err
    b_chain = await chain_state(rt.b)
    for scope in ((T, C), (T2, C2)):
        a_rows, b_rows = rt.a_chain[scope]["rows"], b_chain[scope]["rows"]
        assert b_rows == a_rows, scope                       # seq, prev_hash and hash of every event, in order
        assert [r[0] for r in b_rows] == list(range(1, len(b_rows) + 1))
        assert b_rows[0][1] is None
        assert all(y[1] == x[2] for x, y in zip(b_rows, b_rows[1:]))
    # the restored database verifies its own chain with the restored verify_chain function
    assert b_chain[(T, C)]["verify"] == rt.a_chain[(T, C)]["verify"]
    assert b_chain[(T, C)]["verify"]["ok"] is True
    a_head = await L(rt.a).call("clt_aud", "ledger_head")
    b_head = await L(rt.b).call("clt_aud", "ledger_head")
    assert b_head == a_head == {"seq": len(rt.a_chain[(T, C)]["rows"]), "head_hash": rt.a_chain[(T, C)]["rows"][-1][2]}
    # the stored checkpoints (external anchors) still match the restored chain
    assert (await rt.b.fetch("SELECT ledger_seq, head_hash FROM change_ledger.checkpoints ORDER BY ledger_seq")) \
        == (await rt.a.fetch("SELECT ledger_seq, head_hash FROM change_ledger.checkpoints ORDER BY ledger_seq"))
    for ledger_seq, head_hash in await rt.b.fetch("SELECT ledger_seq, head_hash FROM change_ledger.checkpoints"):
        assert await rt.b.fetchval("SELECT hash FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
                                   "AND seq=$3", T, C, ledger_seq) == head_hash


async def test_every_table_is_restored_row_for_row(rt):
    assert rt.restore_rc == 0, rt.restore_err
    b_data = await table_data(rt.b)
    assert set(b_data) == set(rt.a_data) and len(b_data) >= 17
    assert {k: v for k, v in b_data.items() if v != rt.a_data[k]} == {}
    assert b_data["events"][0] == rt.a_data["events"][0] > 15
    assert b_data["records"][0] == rt.a_data["records"][0] >= 4


async def test_hardening_catalog_is_restored_identically_except_the_documented_default_acl(rt):
    assert rt.restore_rc == 0, rt.restore_err
    b_cat = await catalog(rt.b)
    # sanity: the fingerprint sees the things the hardening depends on
    assert any("rls=true force=true owner=ledger_owner" in r or "owner=ledger_owner rls=true force=true" in r
               for r in rt.a_cat["relations"])
    assert any("secdef=true" in r and "search_path=pg_catalog" in r for r in rt.a_cat["functions"])
    assert any("events_immutable" in r for r in rt.a_cat["triggers"]) and rt.a_cat["policies"]
    for facet in CATALOG_SQL:
        if facet == "default_acls":
            continue
        assert b_cat[facet] == rt.a_cat[facet], (facet, sorted(set(rt.a_cat[facet]) ^ set(b_cat[facet]))[:6])
    # documented pg_dump limit: the database-wide default ACLs of ledger_owner are not part of a -n dump
    # (the schema-scoped REVOKE ALL ON TABLES of 004 leaves no pg_default_acl row: it revokes from an empty default)
    assert rt.a_cat["default_acls"] == ["ledger_owner ns=- type=f acl={ledger_owner=X/ledger_owner}"]
    assert b_cat["default_acls"] == []


async def test_guards_behave_the_same_in_the_restored_database(rt):
    assert rt.restore_rc == 0, rt.restore_err
    b_probe = await probe(rt.b)
    assert b_probe == rt.a_probe
    p = b_probe
    for k in ("update", "delete", "truncate", "update_hash", "approvals_update"):
        assert p["immutable_" + k][0] != "NO_ERROR" and "IMMUTABLE_LEDGER" in p["immutable_" + k][1], k
    assert p["rls_aud_records"] == p["rls_aud_events"] == [T] and p["rls_zed_records"] == "42501"
    assert p["rls_no_scope"] == []
    assert p["rls_scope_not_granted"][1].count("SCOPE_NOT_GRANTED") == 1
    assert p["rls_grant_table_unreadable"] == "42501"
    for k in ("append_event", "budget_reserve", "dispatch_cas", "insert_event", "delete_records", "update_records"):
        assert p["denied_" + k] == "42501", k
    assert p["aud_verify"]["ok"] is True
    # the data are still there after the (failed) tamper attempts, in the restored database
    assert await rt.b.fetchval("SELECT count(*) FROM change_ledger.events") == sum(
        len(v["rows"]) for v in rt.a_chain.values())


async def test_restored_ledger_keeps_chaining_from_the_restored_head(rt):
    assert rt.restore_rc == 0, rt.restore_err
    led = L(rt.b)
    head = await led.call("clt_aud", "ledger_head")
    before = await rt.b.fetchval("SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
                                 T, C)
    cid = await led.propose(base="base-4", target="doc4")
    assert await led.call("clt_alice", "validate", cid) == "VALIDATED"
    new = await rt.b.fetch("SELECT seq, prev_hash, hash, event_type FROM change_ledger.events WHERE tenant_id=$1 "
                           "AND company_id=$2 AND seq>$3 ORDER BY seq", T, C, head["seq"])
    assert len(new) >= 2 and new[0]["event_type"] == "PROPOSED"
    assert [r["seq"] for r in new] == list(range(head["seq"] + 1, head["seq"] + 1 + len(new)))
    assert new[0]["prev_hash"] == head["head_hash"]
    assert all(y["prev_hash"] == x["hash"] for x, y in zip(new, new[1:]))
    after = await led.call("clt_aud", "verify_chain")
    assert after == {"ok": True, "count": before + len(new), "bad_seq": None}
    assert await led.call("clt_aud", "ledger_head") == {"seq": head["seq"] + len(new), "head_hash": new[-1]["hash"]}
    # the other tenant's chain is untouched by it, and the source database A did not move
    assert (await chain_state(rt.b))[(T2, C2)]["rows"] == rt.a_chain[(T2, C2)]["rows"]
    assert await L(rt.a).call("clt_aud", "ledger_head") == head
    # the restored checkpoint machinery works too: a new checkpoint of the new head is accepted
    assert (await led.checkpoint())["seq"] == head["seq"] + len(new)
