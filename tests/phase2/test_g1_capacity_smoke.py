"""G1 capacity drill smoke (S4b E5): runs the real CLI at a SMALL size and asserts the recount.

Needs ERP_PHASE2_TEST_DSN. Without it: skip NOT_RUN, or fail when ERP_PHASE2_REQUIRE_PG=1.
The expected numbers are derived here from the parameters, independently of the script's own
``all_ok`` flag, and the database is recounted from this test's OWN connection (the drill is run with
--keep-db --db-name, then the test counts cursors/outbox/jobs itself and drops the database), so a
drill that loses or duplicates a page/event turns this test red.
"""
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from _pg_harness import DB_PREFIX, admin_connect, require_dsn

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase2_capacity_drill.py"


def _secrets(dsn):
    u = urlsplit(dsn)
    return [s for s in {u.password, unquote(u.password or ""), u.username, dsn} if s and len(s) >= 3]


def _run(dsn, *args, extra_env=None):
    env = dict(os.environ, ERP_PHASE2_TEST_DSN=dsn, **(extra_env or {}))  # DSN only via the environment
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, timeout=600, check=False)


async def _drop(dsn, name):
    adm = await admin_connect(dsn)
    try:
        await adm.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await adm.close()


async def test_capacity_drill_small_run_recounts_clean(tmp_path):
    dsn = require_dsn()
    n, workers, pages, k = 5, 2, 3, 2
    name = DB_PREFIX + uuid.uuid4().hex[:8]
    out = tmp_path / "drill.json"
    try:
        r = _run(dsn, "--sources", str(n), "--workers", str(workers), "--pages", str(pages),
                 "--events", str(k), "--keep-db", "--db-name", name, "--out", str(out))
        # the failure message deliberately carries no raw stdout/stderr tails (they could hold secrets)
        assert r.returncode == 0, f"drill exited {r.returncode} (see rerun with the same arguments)"
        text = out.read_text(encoding="utf-8")
        rep = json.loads(text)
        for secret in _secrets(dsn):
            assert secret not in text and secret not in r.stdout and secret not in r.stderr
        assert rep["kept_database"] == name

        # independent recount from this test's own connection
        c = await admin_connect(dsn, database=name)
        try:
            assert await c.fetchval("SELECT coalesce(sum(version),0)::bigint FROM living.cursors") \
                == n * pages
            assert await c.fetchval("SELECT count(*) FROM living.cursors WHERE version=$1 AND "
                                    "cursor_value=$2", pages, f"p{pages}") == n
            assert await c.fetchval("SELECT count(*) FROM living.outbox") == n * pages * k
            assert await c.fetchval("SELECT count(DISTINCT event_id) FROM living.outbox") \
                == n * pages * k
            got = {r_["source_id"]: sorted(r_["ids"]) for r_ in await c.fetch(
                "SELECT source_id, array_agg(event_id) AS ids FROM living.outbox GROUP BY source_id")}
            want = {f"d{i:04d}": sorted(f"d{i:04d}-p{p}-e{e}" for p in range(1, pages + 1)
                                        for e in range(k)) for i in range(n)}
            assert got == want
            assert await c.fetchval("SELECT count(*) FROM living.jobs WHERE state='SUCCEEDED' AND "
                                    "fence=1 AND attempt=1 AND lease_owner IS NULL") == n
            assert await c.fetchval("SELECT count(*) FROM living.jobs") == n
        finally:
            await c.close()
    finally:
        await _drop(dsn, name)

    # the script's own report agrees with the independent recount
    rc = rep["db_recount"]
    assert rc["cursor_version_sum"] == n * pages and rc["outbox_rows"] == n * pages * k
    assert rep["error_count"] == 0 and rep["invariants"]["all_ok"] is True
    lat = rep["latency"]
    assert lat["commit_cursor_page"]["count"] == n * pages
    assert lat["acquire_job"]["count"] == n and lat["finish_job"]["count"] == n
    for op, st in lat.items():
        assert st["p50_ms"] <= st["p95_ms"] <= st["max_ms"], (op, st)
        assert st["p99_ms"] is None, (op, st)  # < 100 samples: no p99 is published


def test_capacity_drill_bad_password_exits_nonzero_and_never_leaks_it(tmp_path):
    dsn = require_dsn()
    u = urlsplit(dsn)
    if not u.password or not u.hostname:
        pytest.skip("NOT_RUN: DSN is not a URL with a password")
    bad_pw = "BadPw" + uuid.uuid4().hex
    bad = dsn.replace(u.password, bad_pw, 1)
    assert bad != dsn
    out = tmp_path / "bad.json"
    r = _run(bad, "--sources", "2", "--workers", "1", "--pages", "1", "--out", str(out))
    assert r.returncode != 0
    shown = r.stdout + r.stderr + (out.read_text(encoding="utf-8") if out.exists() else "")
    assert bad_pw not in shown and bad not in shown
    for secret in _secrets(dsn):
        assert secret not in shown


def _drill_module():
    spec = importlib.util.spec_from_file_location("phase2_capacity_drill_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_capacity_drill_refuses_remote_host_even_with_the_old_override():
    dsn = require_dsn()
    u = urlsplit(dsn)
    if not u.hostname:
        pytest.skip("NOT_RUN: DSN has no host")
    remote = dsn.replace(u.hostname, "db.example.invalid", 1)
    r = _run(remote, "--sources", "1", "--workers", "1", "--pages", "1",
             extra_env={"ERP_PHASE2_DRILL_ALLOW_REMOTE": "1"})
    assert r.returncode == 2 and "non-local" in r.stderr  # the override no longer exists
    assert "db.example.invalid" not in r.stdout


class _FakeConn:
    def __init__(self, ident):
        self._ident = ident

    async def fetchval(self, _sql):
        return self._ident

    async def close(self):
        pass


async def test_verify_cluster_accepts_only_the_container_cluster():
    mod = _drill_module()

    async def container():
        return 7001

    async def good():
        return _FakeConn(7001)

    async def other_cluster():
        return _FakeConn(9999)  # another local PostgreSQL (for example Release 1's)

    async def unreachable():
        raise OSError("connection refused")

    async def container_unknown():
        raise RuntimeError("docker exec failed")

    assert await mod.verify_cluster("x", connect=good, container_identifier=container) == 7001
    for conn_factory, ident in ((other_cluster, container), (unreachable, container),
                                (good, container_unknown)):
        with pytest.raises(mod.ClusterIdentityError):
            await mod.verify_cluster("x", connect=conn_factory, container_identifier=ident)


async def test_verify_cluster_real_dsn_matches_the_test_container():
    dsn = require_dsn()
    mod = _drill_module()
    assert type(await mod.verify_cluster(dsn)) is int


def test_worker_with_a_wrong_cluster_identity_exits_before_touching_anything():
    dsn = require_dsn()
    r = _run(dsn, "--worker", "--db", "postgres", "--indices", "0:0:1", "--pages", "1",
             extra_env={"ERP_PHASE2_DRILL_SYSID": "1"})
    assert r.returncode == 4 and "RESULT" not in r.stdout and "READY" not in r.stdout
    r2 = _run(dsn, "--worker", "--db", "postgres", "--indices", "0:0:1", "--pages", "1")
    assert r2.returncode == 4  # no identity supplied by a parent: refused too
