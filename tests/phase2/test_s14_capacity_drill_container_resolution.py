"""S14: the capacity drill may only resolve a disposable container (approved name prefix).

No database and no docker: ``docker`` is a fake callable (``docker(*args, timeout=...)`` returning an object
with ``returncode`` and ``stdout`` bytes) and the environment is monkeypatched. The key regression: an
arbitrary container name in ERP_PHASE2_TEST_CONTAINER must never qualify as the disposable cluster.
"""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase2_capacity_drill.py"
PORT = 55432
DSN = f"postgresql://postgres:pw@127.0.0.1:{PORT}/postgres"
OK_A = "r2-s13-dump-abc123"
OK_B = "erp-s14-digest-xyz789"
REJECT = "TEST_CONTAINER_NOT_RUNNING"


@pytest.fixture(scope="module")
def drill():
    spec = importlib.util.spec_from_file_location("phase2_capacity_drill_resolution_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ERP_PHASE2_TEST_CONTAINER", raising=False)


def _r(stdout="", returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=stdout.encode())


class FakeDocker:
    """running: {name: published host port}. ``ps`` honours the name / publish filter like docker does."""

    def __init__(self, running, ps_rc=0, port_rc=0, sysid=None):
        self.running = dict(running)
        self.ps_rc = ps_rc
        self.port_rc = port_rc
        self.sysid = sysid
        self.calls = []

    def __call__(self, *args, timeout=None, **kw):
        self.calls.append(args)
        if args[0] == "ps":
            flt = args[args.index("--filter") + 1]
            key, _, val = flt.partition("=")
            if key == "name":
                pat = val.strip("^$")
                names = [n for n in self.running if n == pat]
            else:
                names = [n for n, p in self.running.items() if str(p) == val]
            return _r("\n".join(names), self.ps_rc)
        if args[0] == "port":
            p = self.running.get(args[1])
            return _r(f"0.0.0.0:{p}\n[::]:{p}\n" if p is not None else "", self.port_rc)
        if args[0] == "exec":
            return _r(f"{self.sysid}\n")
        raise AssertionError(f"unexpected docker call {args}")

    def inspected(self, name):
        return [c for c in self.calls if name in c]


def test_1_single_approved_container_on_dsn_port_is_returned_for_both_prefixes(drill):
    for name in (OK_A, OK_B):
        assert drill._disposable_container(DSN, FakeDocker({name: PORT})) == name


def test_2_no_matching_container_is_rejected(drill):
    for running in ({}, {OK_A: PORT + 1}):
        with pytest.raises(drill.ClusterIdentityError, match=REJECT):
            drill._disposable_container(DSN, FakeDocker(running))


def test_3_two_matching_containers_without_explicit_selection_are_rejected(drill):
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, FakeDocker({OK_A: PORT, OK_B: PORT}))


def test_explicit_approved_selection_resolves_the_ambiguity(drill, monkeypatch):
    monkeypatch.setenv("ERP_PHASE2_TEST_CONTAINER", OK_B)
    assert drill._disposable_container(DSN, FakeDocker({OK_A: PORT, OK_B: PORT})) == OK_B


def test_4_arbitrary_name_selected_by_env_never_qualifies(drill, monkeypatch):
    monkeypatch.setenv("ERP_PHASE2_TEST_CONTAINER", "important-postgres")
    fake = FakeDocker({"important-postgres": PORT})
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, fake)
    assert fake.inspected("important-postgres") == [] and fake.calls == []  # docker was never asked


def test_4b_approved_container_cannot_be_displaced_by_env_naming_another(drill, monkeypatch):
    monkeypatch.setenv("ERP_PHASE2_TEST_CONTAINER", "important-postgres")
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, FakeDocker({OK_A: PORT, "important-postgres": PORT}))


def test_4c_prefix_must_be_at_the_start_of_the_name(drill, monkeypatch):
    monkeypatch.setenv("ERP_PHASE2_TEST_CONTAINER", "prod-" + OK_A)
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, FakeDocker({"prod-" + OK_A: PORT}))


def test_5_explicit_approved_container_publishing_a_different_port_is_rejected(drill, monkeypatch):
    monkeypatch.setenv("ERP_PHASE2_TEST_CONTAINER", OK_A)
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, FakeDocker({OK_A: PORT + 1}))


def test_6_docker_ps_failure_is_rejected(drill):
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, FakeDocker({OK_A: PORT}, ps_rc=1))


def test_7_docker_port_failure_is_rejected(drill):
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, FakeDocker({OK_A: PORT}, port_rc=1))


def test_8_auto_selected_single_container_with_unapproved_name_is_rejected(drill):
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(DSN, FakeDocker({"erpmcp-e2e-real1c-postgres-1": PORT}))


@pytest.mark.parametrize("dsn", [
    "postgresql://postgres:pw@127.0.0.1/postgres",
    "host=127.0.0.1 dbname=postgres user=postgres",
])
def test_9_dsn_without_a_port_is_rejected(drill, dsn):
    fake = FakeDocker({OK_A: PORT})
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        drill._disposable_container(dsn, fake)
    assert fake.calls == []


class _Conn:
    def __init__(self, ident):
        self.ident = ident

    async def fetchval(self, _sql):
        return self.ident

    async def close(self):
        pass


def _verify(drill, monkeypatch, fake, dsn_ident):
    import _pg_harness

    monkeypatch.setattr(_pg_harness, "docker", fake)

    async def connect():
        return _Conn(dsn_ident)

    return asyncio.run(drill.verify_cluster(DSN, connect=connect))


def test_10a_verify_cluster_matching_system_identifier_of_approved_container(drill, monkeypatch):
    fake = FakeDocker({OK_A: PORT}, sysid=7123456789012345678)
    assert _verify(drill, monkeypatch, fake, 7123456789012345678) == 7123456789012345678
    assert any(c[0] == "exec" and c[1] == OK_A for c in fake.calls)  # identity proven through the approved container


def test_10b_verify_cluster_different_system_identifier_is_rejected(drill, monkeypatch):
    fake = FakeDocker({OK_A: PORT}, sysid=111)
    with pytest.raises(drill.ClusterIdentityError, match="DSN_IS_NOT_THE_TEST_CONTAINER"):
        _verify(drill, monkeypatch, fake, 222)


def test_10c_verify_cluster_unapproved_container_is_rejected_before_any_exec(drill, monkeypatch):
    fake = FakeDocker({"important-postgres": PORT}, sysid=333)
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        _verify(drill, monkeypatch, fake, 333)  # identifiers match, name does not
    assert not any(c[0] == "exec" for c in fake.calls)


def test_10d_verify_cluster_env_naming_unapproved_container_is_rejected(drill, monkeypatch):
    monkeypatch.setenv("ERP_PHASE2_TEST_CONTAINER", "important-postgres")
    fake = FakeDocker({OK_A: PORT, "important-postgres": PORT}, sysid=444)
    with pytest.raises(drill.ClusterIdentityError, match=REJECT):
        _verify(drill, monkeypatch, fake, 444)
    assert not any(c[0] == "exec" for c in fake.calls)
