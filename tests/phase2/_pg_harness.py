"""Shared PostgreSQL test helpers.

G1 crash/restore tests provision uniquely named, invocation-owned containers and create isolated
throwaway databases inside them. Other Phase 2 suites may continue to use ERP_PHASE2_TEST_DSN.
"""
import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "phase2"
FILES = ("001_living_registry.sql", "002_job_cursor_functions.sql", "003_security_hardening.sql",
         "004_change_ledger.sql", "005_change_registry.sql", "006_change_sweeps.sql", "007_change_hardening_a.sql",
         "008_change_hardening_b.sql", "009_approval_digest_2.sql", "010_registry_session_hardening.sql",
         "011_event_hash_v2.sql", "012_dispatch_session_hardening.sql", "013_dispatched_invariant.sql",
         "014_ed25519_verify.sql", "015_ed25519_signatures.sql", "016_dispatch_receipt.sql", "017_receipt_hardening.sql",
         "018_wire_payload_receipt.sql")
D1, D2 = "1" * 64, "2" * 64
OBS_AT = datetime(2024, 1, 2, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)
DB_PREFIX = "g1x_"
REINIT_MARK = b"all server processes terminated; reinitializing"


def dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


def _unavailable(msg):
    if os.environ.get("ERP_PHASE2_REQUIRE_PG") == "1":
        pytest.fail("ERP_PHASE2_REQUIRE_PG=1 but " + msg)
    pytest.skip("NOT_RUN: " + msg)


def require_dsn():
    dsn = os.environ.get("ERP_PHASE2_TEST_DSN")
    if not dsn:
        _unavailable("ERP_PHASE2_TEST_DSN is not set")
    return dsn


# ---------------------------------------------------------------- Docker-owned disposable clusters
def _docker_exe():
    return (os.environ.get("ERP_PHASE2_DOCKER") or shutil.which("docker")
            or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")


def docker(*args, stdin=None, timeout=180):
    return subprocess.run([_docker_exe(), *args], input=stdin, capture_output=True,
                          timeout=timeout, check=False)


@asynccontextmanager
async def _owned_cluster_fixture(suffixes):
    """Provision uniquely named, loopback-only PostgreSQL fixture containers."""
    if os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS") != "1":
        _unavailable("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1 is required to provision disposable clusters")
    if not shutil.which(_docker_exe()) and not Path(_docker_exe()).is_file():
        _unavailable("Docker executable is unavailable")
    image = os.environ.get("ERP_PHASE2_TEST_IMAGE", "postgres:16")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,190}", image):
        _unavailable("ERP_PHASE2_TEST_IMAGE is not a safe Docker image reference")
    token = uuid.uuid4().hex
    label = "codex.g1.owner=" + token
    password = secrets.token_urlsafe(24)
    names = [f"r2-s13-dump-{token[:12]}-{suffix}" for suffix in suffixes]
    created = []
    try:
        for name in names:
            r = docker("run", "--detach", "--name", name, "--label", label,
                       "--publish", "127.0.0.1::5432", "--env", "POSTGRES_PASSWORD=" + password,
                       "--health-cmd", "pg_isready -U postgres", "--health-interval", "1s",
                       "--health-timeout", "3s", "--health-retries", "60", image, timeout=120)
            if r.returncode != 0:
                _unavailable("could not provision owned PostgreSQL cluster: " +
                             r.stderr.decode(errors="replace")[-1200:])
            created.append(name)
        dsns = []
        for name in names:
            r = docker("port", name, "5432/tcp", timeout=30)
            if r.returncode != 0:
                _unavailable("Docker did not expose the owned cluster port")
            m = re.fullmatch(r"127\.0\.0\.1:(\d+)\s*", r.stdout.decode().strip())
            if not m:
                _unavailable("owned cluster port is not bound only to loopback")
            dsns.append(f"postgresql://postgres:{password}@127.0.0.1:{int(m.group(1))}/postgres")
        for name, dsn in zip(names, dsns):
            last = None
            for _ in range(90):
                try:
                    c = await asyncpg.connect(dsn, timeout=2)
                    await c.close()
                    break
                except (OSError, asyncpg.PostgresError, TimeoutError) as e:
                    last = e
                    await asyncio.sleep(1)
            else:
                _unavailable(f"owned cluster {name} did not become ready: {last}")
        yield dsns, names, token
    finally:
        cleanup_errors = []
        for name in reversed(created):
            try:
                inspected = docker(
                    "inspect", "--format", "{{.Name}}|{{ index .Config.Labels \"codex.g1.owner\" }}",
                    name, timeout=30)
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_errors.append(f"{name}: ownership inspection failed: {error}")
                continue
            if (inspected.returncode != 0
                    or inspected.stdout.decode().strip() != "/" + name + "|" + token):
                reason = inspected.stderr.decode(errors="replace")[-500:]
                cleanup_errors.append(
                    f"{name}: ownership not verified; container left untouched ({reason})")
                continue
            try:
                # The official postgres image creates an anonymous data volume. `--volumes`
                # removes that fixture-owned anonymous volume together with this owned container.
                removed = docker("rm", "--force", "--volumes", name, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup_errors.append(f"{name}: removal failed after ownership verification: {error}")
                continue
            if removed.returncode != 0:
                cleanup_errors.append(
                    f"{name}: removal failed: {removed.stderr.decode(errors='replace')[-500:]}")
        if cleanup_errors:
            raise RuntimeError("owned test container cleanup errors: " + "; ".join(cleanup_errors))


@asynccontextmanager
async def disposable_cluster_pair():
    """Provision two owned, isolated PostgreSQL clusters; never attach to existing containers.

    Opt-in via ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1 plus Docker. Containers are uniquely named
    and ownership is verified with a random label before exact-name cleanup. No pre-existing
    container is inspected, stopped, reused, or removed.
    """
    async with _owned_cluster_fixture(("a", "b")) as (dsns, names, token):
        yield dsns[0], dsns[1], names, token


@asynccontextmanager
async def disposable_cluster():
    """Provision one invocation-owned cluster for crash-boundary scenarios."""
    async with _owned_cluster_fixture(("a",)) as (dsns, names, token):
        yield dsns[0], names[0], token


def owned_cluster_exec(name, token, *args, stdin=None, timeout=180):
    """Run a command only in one of this fixture's exactly named, label-verified containers."""
    if not re.fullmatch(r"r2-s13-dump-[0-9a-f]{12}-[ab]", name):
        raise AssertionError("refusing non-fixture container name")
    r = docker("inspect", "--format", "{{.Name}}|{{ index .Config.Labels \"codex.g1.owner\" }}",
               name, timeout=30)
    if r.returncode != 0 or r.stdout.decode().strip() != "/" + name + "|" + token:
        raise AssertionError("fixture container ownership check failed")
    flags = ["-i"] if stdin is not None else []
    return docker("exec", *flags, name, *args, stdin=stdin, timeout=timeout)


def owned_cluster_identity(name, token):
    if not re.fullmatch(r"r2-s13-dump-[0-9a-f]{12}-[ab]", name):
        raise AssertionError("refusing non-fixture container name")
    r = docker("inspect", "--format", "{{.Id}}|{{ index .Config.Labels \"codex.g1.owner\" }}",
               name, timeout=30)
    if r.returncode != 0:
        raise AssertionError("fixture container identity unavailable")
    identity, actual_token = r.stdout.decode().strip().split("|", 1)
    if actual_token != token or len(identity) < 32:
        raise AssertionError("fixture container ownership check failed")
    return identity


def owned_cluster_log_marks(name, token):
    owned_cluster_identity(name, token)
    result = docker("logs", name, timeout=60)
    if result.returncode != 0:
        raise AssertionError("could not read owned cluster logs: " + result.stderr.decode(errors="replace"))
    return (result.stdout + result.stderr).count(REINIT_MARK)


def owned_kill_backend(name, token, pid, sig="KILL"):
    result = owned_cluster_exec(name, token, "sh", "-c", f"kill -{sig} {int(pid)}")
    if result.returncode != 0:
        raise AssertionError("owned backend termination failed: " + result.stderr.decode(errors="replace"))


async def admin_connect(dsn, tries=90, database=None):
    last = None
    for _ in range(tries):
        try:
            kw = {"database": database} if database else {}
            return await asyncpg.connect(dsn, timeout=5, **kw)
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError, TimeoutError) as e:
            last = e
            await asyncio.sleep(1)
    raise last


async def wait_owned_cluster_recovered(dsn, name, token, timeout=120):
    """Wait until pg_isready and a real query succeed on this verified owned fixture."""
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        r = owned_cluster_exec(name, token, "pg_isready", "-U", "postgres", "-q")
        if r.returncode == 0:
            try:
                c = await asyncpg.connect(dsn, timeout=5)
                try:
                    if await c.fetchval("SELECT 1") == 1:
                        return
                finally:
                    await c.close()
            except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError, TimeoutError):
                pass
        await asyncio.sleep(1)
    raise AssertionError("postgres did not recover in time")


# ---------------------------------------------------------------- throwaway databases
class Db:
    def __init__(self, dsn, name):
        self.dsn, self.name, self.conn = dsn, name, None

    async def connect(self):
        return await admin_connect(self.dsn, tries=60, database=self.name)


def new_name():
    return DB_PREFIX + uuid.uuid4().hex[:8]


def replace_once(old, new):
    def fn(text):
        assert text.count(old) == 1, ("mutation anchor not unique/found", old, text.count(old))
        return text.replace(old, new)
    return fn


async def apply_files(conn, mutate=None):
    for name in FILES:
        raw = (MIGRATIONS / name).read_bytes()
        text = raw.decode("utf-8")
        if mutate and name in mutate:
            text = mutate[name](text.replace("\r\n", "\n"))
            raw = text.encode("utf-8")
        await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                           hashlib.sha256(raw).hexdigest())
        await conn.execute(text)


async def seed_basic(conn):
    await conn.execute("""
      INSERT INTO living.tenants VALUES ('A'),('B');
      INSERT INTO living.sources(tenant_id,source_id,company_id) VALUES
        ('A','s1',NULL),('A','s3',NULL),('B','s1',NULL),('A','s4','c1'),('A','s5','c2');
      INSERT INTO living.role_scope(role_name,tenant_id,source_id,company_id) VALUES
        ('living_worker','A','s1',NULL),('living_reader','A','s1',NULL),
        ('living_promoter','A','s1',NULL),('living_publisher','A','s1',NULL),
        ('living_reader','A','s4','c1');
    """)
    await conn.execute(
        "SELECT living.set_trusted_reviewer('living_worker','A','s1',true,$1)", FUTURE)


@asynccontextmanager
async def throwaway_db(dsn, *, mutate=None, migrate=True, seed=True):
    name = new_name()
    assert name.startswith(DB_PREFIX)
    admin = await admin_connect(dsn)
    db = Db(dsn, name)
    created = False
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        created = True
        if migrate:
            db.conn = await db.connect()
            await apply_files(db.conn, mutate)
            if seed:
                await seed_basic(db.conn)
        yield db
    finally:
        if db.conn is not None:
            try:
                await asyncio.wait_for(db.conn.close(), 5)
            except Exception:  # noqa: BLE001 - connection may be dead after a crash cycle
                db.conn.terminate()
        admin.terminate()  # may already be dead after a crash cycle; terminate() never raises
        if created:
            adm = await admin_connect(dsn)  # fresh: the old one may have died in a crash cycle
            try:
                await adm.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            finally:
                await adm.close()


# ---------------------------------------------------------------- scoped calls
@asynccontextmanager
async def scope(conn, role, t="A", s="s1", company=None):
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {role}")
        await conn.fetchval("SELECT living.set_scope($1,$2,$3)", t, s, company)
        yield


async def call(conn, role, sql, *args, t="A", s="s1"):
    async with scope(conn, role, t, s):
        return await conn.fetchval(sql, *args)


async def attempt(conn, role, sql, *args, t="A", s="s1", company=None):
    """('ok', rows) or ('err', sqlstate, first message line); never leaves a tx open."""
    try:
        async with scope(conn, role, t, s, company):
            rows = await conn.fetch(sql, *args)
            return ("ok", [tuple(r) for r in rows])
    except asyncpg.PostgresError as e:
        return ("err", e.sqlstate, str(e).splitlines()[0])


async def attempt_plain(conn, sql, *args):
    try:
        async with conn.transaction():
            rows = await conn.fetch(sql, *args)
            return ("ok", [tuple(r) for r in rows])
    except asyncpg.PostgresError as e:
        return ("err", e.sqlstate, str(e).splitlines()[0])


async def fails(needle, coro):
    try:
        await coro
    except asyncpg.PostgresError as e:
        assert needle in str(e), (needle, str(e))
        return e
    raise AssertionError(f"expected failure containing {needle!r} but the call succeeded")


INGEST = ("SELECT living.ingest_observation($1,$2,$3::uuid,$4,$5::uuid,$6,$7,$8::timestamptz,"
          "$9::timestamptz,$10::uuid,'{}'::jsonb)")
COMMIT = "SELECT living.commit_cursor_page('A','s1','conn',$1,$2,$3,$4,$5,$6,$7,$8::jsonb)"
REC = "SELECT living.record_attestation('A','s1',$1,$2,$3,$4,$5,$6,$7)"
PROMOTE = "SELECT living.promote_head('A','s1','m1',0,$1,$2,'ev1')"


async def ingest(conn, obj, rev, kind="OBSERVED", digest=D1, eff=None, supersedes=None,
                 t="A", s="s1", obs_id=None):
    obs_id = obs_id or uuid.uuid4()
    return await call(conn, "living_worker", INGEST, t, s, obs_id, obj, rev, kind, digest, eff,
                      OBS_AT, supersedes, t=t, s=s)


async def seed_direct(conn, t, s, obj):
    await conn.execute(
        "INSERT INTO living.observations(tenant_id,source_id,observation_id,object_id,"
        "revision_id,kind,digest,observed_at) VALUES($1,$2,$3,$4,$5,'OBSERVED',$6,"
        "'2024-01-01Z')", t, s, uuid.uuid4(), obj, uuid.uuid4(), D1)


def ev_digest(revision_digest, evidence):
    return hashlib.sha256(f"{revision_digest}:{evidence}".encode()).hexdigest()


async def attest(conn, rev, digest=D1, evidence="ev1", proposer="prop", att=None):
    return await call(conn, "living_worker", REC, att or uuid.uuid4(), rev, proposer, evidence,
                      ev_digest(digest, evidence), "APPROVE", FUTURE)


async def make_event(conn, eid, n=1):
    base = {"event_id": eid, "n": n}
    d = await conn.fetchval("SELECT encode(sha256(convert_to($1::jsonb::text,'UTF8')),'hex')",
                            json.dumps(base))
    return {**base, "digest": d}


async def page(conn, *eids):
    return json.dumps([await make_event(conn, e) for e in eids])


async def source_epoch(conn):
    return await conn.fetchval(
        "SELECT scope_epoch FROM living.sources WHERE tenant_id='A' AND source_id='s1'")


async def cursor_and_job(conn, worker="w1", secs=300, key="k1"):
    """Cursor 'conn' at p0 (version 0) plus a RUNNING job held by `worker`; returns (job, fence)."""
    await call(conn, "living_worker", "SELECT living.create_cursor('A','s1','conn','p0')")
    j = uuid.uuid4()
    await call(conn, "living_worker",
               "SELECT living.enqueue_job('A','s1',$1,'sync',$2,$3,'{}'::jsonb)", j, "c" * 64, key)
    f = await call(conn, "living_worker", "SELECT living.acquire_job('A','s1',$1,$2,$3)",
                   j, worker, secs)
    return j, f


async def populate(c):
    """A representative populated living registry; returns ids needed by later assertions."""
    info = {}
    o1, r1, r2, r3 = (uuid.uuid4() for _ in range(4))
    await ingest(c, "obj1", r1, obs_id=o1, eff=dt(2024, 1, 1))
    await ingest(c, "obj1", r2, digest=D2, eff=dt(2024, 2, 1), supersedes=o1)
    await ingest(c, "obj2", r3, eff=None)
    await ingest(c, "obj3", uuid.uuid4(), kind="GAP", digest=None)
    await ingest(c, "obj2", uuid.uuid4(), kind="ATTESTATION_REVOKED", digest=None)
    await ingest(c, "obj4", uuid.uuid4(), kind="SOURCE_UNAVAILABLE", digest=None)
    for t, s in (("B", "s1"), ("A", "s3"), ("A", "s4")):
        await seed_direct(c, t, s, f"obj-{t}-{s}")
    # accepted head with attestation
    await attest(c, r2, digest=D2)
    for m in ("m1", "m2"):
        await call(c, "living_promoter", "SELECT living.create_head('A','s1',$1)", m)
    acc = uuid.uuid4()
    assert await call(c, "living_promoter", PROMOTE, r2, acc) == 1
    # cursor, job with fence, outbox pages
    j1, f1 = await cursor_and_job(c)
    ep = await source_epoch(c)
    p1 = await page(c, "e1", "e2")
    p2 = await page(c, "e3")
    assert await call(c, "living_worker", COMMIT, j1, "w1", f1, "p0", 0, ep, "p1", p1) == 1
    assert await call(c, "living_worker", COMMIT, j1, "w1", f1, "p1", 1, ep, "p2", p2) == 2
    await call(c, "living_worker",
               "SELECT living.enqueue_job('A','s1',$1,'sync',$2,'k2','{}'::jsonb)",
               uuid.uuid4(), "d" * 64)
    # outbox delivery state: e1 DELIVERED, e2 leased
    async with scope(c, "living_publisher"):
        claimed = await c.fetch("SELECT event_id,claim_generation FROM "
                                "living.claim_outbox('A','s1',2,60,5) ORDER BY seq")
    gen = {r["event_id"]: r["claim_generation"] for r in claimed}
    await call(c, "living_publisher",
               "SELECT living.finish_outbox('A','s1','conn','e1',$1,true,5)", gen["e1"])
    info.update(
        rev=r2, acc=acc, job=j1, fence=f1, epoch=ep, page1=p1, page2=p2, page_other=await page(c, "zz"),
        k_late=await c.fetchval("SELECT max(recorded_at) FROM living.observations "
                                "WHERE tenant_id='A' AND source_id='s1'"),
        k_mid=await c.fetchval("SELECT recorded_at FROM living.observations WHERE "
                               "tenant_id='A' AND source_id='s1' ORDER BY ingest_seq "
                               "OFFSET 2 LIMIT 1"))
    return info
