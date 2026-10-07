"""The no-silent-skip policy itself: an unexpected skip must fail the run (exit non-zero).

Runs a throw-away pytest session in a subprocess; needs no environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.smoke]

HERE = Path(__file__).parent


def _run(tmp_path: Path, *, no_skip: bool, allowed: str = "") -> subprocess.CompletedProcess:
    (tmp_path / "test_probe.py").write_text(
        "import pytest\n\ndef test_skips():\n    pytest.skip('probe-reason')\n\n"
        "def test_ok():\n    assert True\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ERP_MCP_E2E_")}
    env["PYTHONPATH"] = str(HERE)
    if no_skip:
        env["ERP_MCP_E2E_NO_SKIP"] = "1"
    if allowed:
        env["ERP_MCP_E2E_ALLOWED_SKIP_REASONS"] = allowed
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "skip_policy", "-p", "no:cacheprovider", "-q",
         "-rs", str(tmp_path / "test_probe.py")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=False)


def test_unexpected_skip_fails_the_run_under_no_skip(tmp_path):
    result = _run(tmp_path, no_skip=True)
    assert result.returncode != 0, result.stdout
    assert "UNEXPECTED SKIP" in result.stdout and "probe-reason" in result.stdout
    assert "skipped=1 unexpected=1" in result.stdout


def test_allowlisted_skip_is_counted_but_does_not_fail(tmp_path):
    result = _run(tmp_path, no_skip=True, allowed="probe-reason")
    assert result.returncode == 0, result.stdout
    assert "skipped=1 unexpected=0" in result.stdout


def test_skip_is_tolerated_only_when_no_skip_mode_is_off(tmp_path):
    result = _run(tmp_path, no_skip=False)
    assert result.returncode == 0, result.stdout
    assert "skipped=1 unexpected=0" in result.stdout


def test_allowlist_holds_exactly_the_declared_external_gate_reason(tmp_path):
    import skip_policy

    assert skip_policy.ALLOWED_SKIP_REASONS == (
        "EXTERNAL-GATE: validated profile requires native reconciliation evidence",)
    # An unrelated skip reason is still a failure under NO_SKIP: the allowlist did not widen.
    result = _run(tmp_path, no_skip=True)
    assert result.returncode != 0 and "UNEXPECTED SKIP" in result.stdout
