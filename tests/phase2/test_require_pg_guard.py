"""End-to-end proof of the conftest REQUIRE_PG guard, in a child pytest process.

The child runs a copy of tests/phase2/conftest.py in a temporary ``.../phase2`` rootdir, so the real
hooks (pytest_runtest_logreport, pytest_deselected, pytest_sessionfinish -> exitstatus) are what is
exercised, not just RequirePgGuard's methods. No database or DSN is involved.
"""
import os
import subprocess
import sys
from pathlib import Path

_CONFTEST = Path(__file__).resolve().parent / "conftest.py"
_INI = "[pytest]\nmarkers =\n    integration: needs an external system\n"
_SKIPPED = ("import pytest\n\n@pytest.mark.integration\ndef test_needs_pg():\n"
            "    pytest.skip('no dsn')\n\ndef test_plain():\n    pass\n")
_PASSING = ("import pytest\n\n@pytest.mark.integration\ndef test_needs_pg():\n    pass\n")


def _run(tmp_path, source, require, *extra):
    phase2 = tmp_path / "phase2"
    phase2.mkdir()
    (phase2 / "conftest.py").write_bytes(_CONFTEST.read_bytes())
    (phase2 / "test_child.py").write_text(source)
    (tmp_path / "pytest.ini").write_text(_INI)
    env = {k: v for k, v in os.environ.items()
           if k not in ("ERP_PHASE2_REQUIRE_PG", "ERP_PHASE2_TEST_DSN", "PYTEST_ADDOPTS")}
    if require:
        env["ERP_PHASE2_REQUIRE_PG"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c",
         str(tmp_path / "pytest.ini"), "--rootdir", str(tmp_path), str(phase2), *extra],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60, check=False)


def test_required_pg_makes_a_skipped_integration_test_fail_the_run(tmp_path):
    r = _run(tmp_path, _SKIPPED, True)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "ERP_PHASE2_REQUIRE_PG=1 violated" in out and "test_needs_pg (skipped)" in out, out


def test_required_pg_makes_a_deselected_integration_test_fail_the_run(tmp_path):
    r = _run(tmp_path, _PASSING, True, "-m", "not integration")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "(deselected)" in out, out


def test_required_pg_with_an_integration_test_that_ran_exits_zero(tmp_path):
    r = _run(tmp_path, _PASSING, True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_without_required_pg_a_skipped_integration_test_exits_zero(tmp_path):
    r = _run(tmp_path, _SKIPPED, False)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "violated" not in out
