"""G1 backup/restore proof: pg_dump of a populated living registry restored into a second database.

Needs ERP_PHASE2_TEST_DSN and the disposable container erp-phase2-test-pg (pg_dump / pg_restore run
inside it through docker exec, piped through the host, no files). Without them: skip NOT_RUN, or
fail when ERP_PHASE2_REQUIRE_PG=1.

ACLs are compared as EFFECTIVE ACLs (a NULL ACL is expanded with acldefault): pg_dump legitimately
stores an ACL equal to the default as NULL, which grants exactly the same privileges.

Proves that the restored database equals the source in: row digests of every living table and
identity-sequence state, constraints/FKs/indexes/columns, RLS flags and policies, table/column/
function/schema ACLs, owners, triggers, function definitions (prosecdef, proconfig, proacl), accepted
heads; and that after the restore immutability, role denials, bitemporal reads and cross-tenant
denial behave exactly like in the source (same outcomes, same sqlstate, same messages).
"""
import asyncpg
import pytest
from _pg_harness import (
    COMMIT,
    PROMOTE,
    attempt,
    attempt_plain,
    call,
    container_exec,
    container_guard,
    dt,
    ingest,
    populate,
    require_dsn,
    scope,
    throwaway_db,
)

pytestmark = pytest.mark.integration

STRUCT = {
    "functions": "SELECT p.oid::regprocedure::text, p.prosecdef, p.proconfig::text,"
                 " p.proowner::regrole::text,"
                 " coalesce(p.proacl, acldefault('f', p.proowner))::text, p.provolatile::text, p.proisstrict,"
                 " pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n"
                 " ON n.oid=p.pronamespace WHERE n.nspname='living' ORDER BY 1",
    "relations": "SELECT c.oid::regclass::text, c.relkind::text, c.relowner::regrole::text,"
                 " coalesce(c.relacl, acldefault(CASE WHEN c.relkind='S' THEN 's'::\"char\""
                 " ELSE 'r'::\"char\" END, c.relowner))::text, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c"
                 " JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='living'"
                 " AND c.relkind IN ('r','S','i') ORDER BY 1",
    "columns": "SELECT a.attrelid::regclass::text, a.attname, a.atttypid::regtype::text,"
               " a.attnotnull, a.attidentity::text, a.attgenerated::text, a.attacl::text,"
               " pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a JOIN pg_class c"
               " ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace"
               " LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum"
               " WHERE n.nspname='living' AND c.relkind='r' AND a.attnum>0"
               " AND NOT a.attisdropped ORDER BY 1,2",
    "schema": "SELECT nspname, nspowner::regrole::text,"
              " coalesce(nspacl, acldefault('n', nspowner))::text FROM pg_namespace"
              " WHERE nspname='living'",
    "default_acls": "SELECT defaclrole::regrole::text, defaclnamespace::regnamespace::text,"
                    " defaclobjtype::text, defaclacl::text FROM pg_default_acl ORDER BY 1,2,3",
    "policies": "SELECT tablename,policyname,cmd,roles::text,qual,with_check FROM pg_policies"
                " WHERE schemaname='living' ORDER BY 1,2",
    "constraints": "SELECT conrelid::regclass::text, conname, contype::text,"
                   " pg_get_constraintdef(oid) FROM pg_constraint"
                   " WHERE connamespace='living'::regnamespace ORDER BY 1,2",
    "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes"
               " WHERE schemaname='living' ORDER BY 1,2",
    "triggers": "SELECT tgrelid::regclass::text, tgname, tgenabled::text, pg_get_triggerdef(oid)"
                " FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text LIKE 'living.%'"
                " ORDER BY 1,2",
    "migrations": "SELECT version, checksum FROM living.schema_migrations ORDER BY 1",
    "accepted_heads": "SELECT tenant_id,source_id,model_key,revision_id,version"
                      " FROM living.accepted_heads ORDER BY 1,2,3",
}


async def structure(conn):
    return {k: [tuple(r) for r in await conn.fetch(q)] for k, q in STRUCT.items()}


async def data_digests(conn):
    tables = [r[0] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='living' ORDER BY 1")]
    out = {}
    for t in tables:
        out[t] = tuple(await conn.fetchrow(
            f"SELECT count(*), md5(coalesce(string_agg(x::text, E'\\n' ORDER BY x::text),''))"
            f" FROM living.{t} x"))
    seqs = await conn.fetch("SELECT sequencename,last_value FROM pg_sequences"
                            " WHERE schemaname='living' ORDER BY 1")
    out["__sequences__"] = [tuple(r) for r in seqs]
    return out


async def battery(c, info):
    """Behaviour outcomes; compared source-vs-restore, so only deterministic inputs are used."""
    o = {}
    for role in ("living_worker", "living_reader", "living_promoter"):
        for tag, stmt in (("upd", "UPDATE living.observations SET object_id='x'"),
                          ("del", "DELETE FROM living.observations"),
                          ("trunc", "TRUNCATE living.observations"),
                          ("head", "UPDATE living.accepted_heads SET version=99")):
            o[f"{role}:{tag}"] = await attempt(c, role, stmt)
    o["owner:upd"] = await attempt_plain(c, "UPDATE living.observations SET object_id='x'")
    o["owner:del"] = await attempt_plain(c, "DELETE FROM living.observations")
    o["owner:trunc_cascade"] = await attempt_plain(c, "TRUNCATE living.observations CASCADE")
    o["owner:trunc_outbox"] = await attempt_plain(c, "TRUNCATE living.outbox")
    o["owner:outbox_content"] = await attempt_plain(
        c, "UPDATE living.outbox SET content='{}'::jsonb")
    o["owner:head_direct"] = await attempt_plain(c, "UPDATE living.accepted_heads SET version=9")
    o["worker:claim_outbox"] = await attempt(c, "living_worker",
                                             "SELECT * FROM living.claim_outbox('A','s1',1,60,5)")
    o["reader:provenance"] = await attempt(c, "living_reader",
                                           "SELECT provenance FROM living.observations")
    o["worker:add_role_scope"] = await attempt(
        c, "living_worker", "SELECT living.add_role_scope('living_reader','A','s1')")
    o["worker:trusted"] = await attempt(
        c, "living_worker",
        "SELECT living.set_trusted_reviewer('living_worker','A','s1',true,now())")
    o["reader:insert_tenant"] = await attempt(c, "living_reader",
                                              "INSERT INTO living.tenants VALUES('Z')")
    known = ("SELECT object_id,revision_id,kind,digest,available,latest_kind,revoked,recorded_at,"
             "ingest_seq FROM living.as_known_at('A','s1',$1) ORDER BY object_id")
    eff = ("SELECT object_id,revision_id,source_effective_at,effective_unknown,revoked,ingest_seq"
           " FROM living.as_effective_at('A','s1',$1,$2) ORDER BY object_id,effective_unknown")
    for tag, k in (("late", info["k_late"]), ("mid", info["k_mid"])):
        o[f"known:{tag}"] = await attempt(c, "living_reader", known, k)
        o[f"eff:jan:{tag}"] = await attempt(c, "living_reader", eff, dt(2024, 1, 15), k)
        o[f"eff:mar:{tag}"] = await attempt(c, "living_reader", eff, dt(2024, 3, 1), k)
    # cross-tenant / cross-source / spoofing
    for t, s, co in (("B", "s1", None), ("A", "s3", None), ("A", "s4", None), ("A", "s5", "c2")):
        o[f"setscope:{t}/{s}/{co}"] = await attempt(
            c, "living_reader", "SELECT 1 WHERE false", t=t, s=s, company=co)
    o["reader:visible"] = await attempt(
        c, "living_reader", "SELECT tenant_id,source_id,object_id FROM living.observations"
        " ORDER BY ingest_seq")
    o["reader:tenants"] = await attempt(c, "living_reader", "SELECT tenant_id FROM living.tenants")
    async with c.transaction():
        await c.execute("SET LOCAL ROLE living_reader")
        await c.execute("SELECT set_config('living.tenant_id','B',true),"
                        "set_config('living.source_id','s1',true)")
        o["spoof:obs"] = await c.fetchval("SELECT count(*) FROM living.observations")
        o["spoof:sources"] = await c.fetchval("SELECT count(*) FROM living.sources")
    # head / cursor APIs: replay is idempotent, conflicting replay is rejected
    o["promote:replay"] = await attempt(c, "living_promoter", PROMOTE, info["rev"], info["acc"])
    o["promote:stale"] = await attempt(
        c, "living_promoter", PROMOTE, info["rev"], __import__("uuid").UUID(int=1))
    args = (info["job"], "w1", info["fence"], "p1", 1, info["epoch"], "p2")
    o["page:replay_identical"] = await attempt(c, "living_worker", COMMIT, *args, info["page2"])
    o["page:replay_conflict"] = await attempt(
        c, "living_worker", COMMIT, *args, info["page_other"])
    return o


def _pipe_dump_restore(src, dst):
    dump = container_exec("pg_dump", "-U", "postgres", "-Fc", src)
    assert dump.returncode == 0, dump.stderr.decode()
    assert len(dump.stdout) > 1000
    rest = container_exec("pg_restore", "-U", "postgres", "-d", dst, "--exit-on-error",
                          stdin=dump.stdout)
    assert rest.returncode == 0, rest.stderr.decode()


async def test_pg_dump_restore_is_identical_and_guards_still_hold():
    dsn = require_dsn()
    await container_guard(dsn)
    async with throwaway_db(dsn) as src, throwaway_db(dsn, migrate=False) as dst:
        c = src.conn
        info = await populate(c)
        kinds = {r[0] for r in await c.fetch("SELECT DISTINCT kind FROM living.observations")}
        assert {"OBSERVED", "GAP", "ATTESTATION_REVOKED", "SOURCE_UNAVAILABLE"} <= kinds
        counts = {r[0]: r[1] for r in (await data_digests(c)).items() if r[0] != "__sequences__"}
        for t in ("observations", "accepted_heads", "acceptance_events", "attestations", "jobs",
                  "cursors", "outbox", "role_scope", "trusted_reviewers", "sources", "tenants"):
            assert counts[t][0] > 0, f"populate left {t} empty"
        _pipe_dump_restore(src.name, dst.name)
        d = await dst.connect()
        try:
            s_struct, d_struct = await structure(c), await structure(d)
            for k in STRUCT:
                assert s_struct[k], f"structure section {k} is empty (vacuous comparison)"
                assert s_struct[k] == d_struct[k], f"restore mismatch in {k}"
            assert await data_digests(c) == await data_digests(d)
            b_src, b_dst = await battery(c, info), await battery(d, info)
            # the battery must be meaningful, not vacuously equal
            assert "IMMUTABLE_LEDGER" in b_src["owner:upd"][2]
            assert "IMMUTABLE_LEDGER" in b_src["owner:trunc_cascade"][2]
            assert b_src["living_worker:upd"][1] == "42501"
            assert b_src["setscope:B/s1/None"][1] == "P0001"
            assert "SCOPE_NOT_GRANTED" in b_src["setscope:B/s1/None"][2]
            assert b_src["promote:replay"] == ("ok", [(1,)])
            assert "CONFLICTING_PAGE_REPLAY" in b_src["page:replay_conflict"][2]
            assert b_src["known:late"][0] == "ok" and len(b_src["known:late"][1]) >= 3
            assert b_src["spoof:obs"] == 0
            assert b_src == b_dst
            # restored DB keeps working: identity sequence continues, API still enforces scope
            nxt = await d.fetchval("SELECT max(ingest_seq) FROM living.observations") + 1
            await ingest(d, "after-restore", __import__("uuid").uuid4())
            assert await d.fetchval(
                "SELECT max(ingest_seq) FROM living.observations") == nxt
            with pytest.raises(asyncpg.PostgresError, match="SCOPE_NOT_GRANTED"):
                async with scope(d, "living_reader", "B", "s1"):
                    pass
            assert await call(d, "living_reader",
                              "SELECT count(*) FROM living.observations") >= 1
        finally:
            await d.close()
