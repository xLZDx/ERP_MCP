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
GATE = "EXTERNAL-GATE: probe-reason"


def _run(tmp_path: Path, *, no_skip: bool, allowed: str = "", reason: str = "probe-reason",
         body: str | None = None) -> subprocess.CompletedProcess:
    (tmp_path / "test_probe.py").write_text(
        body if body is not None else
        f"import pytest\n\ndef test_skips():\n    pytest.skip({reason!r})\n\n"
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
    assert "UNEXPECTED" in result.stdout and "probe-reason" in result.stdout
    assert "skipped=1 unexpected=1" in result.stdout


def test_allowlisted_skip_is_counted_but_does_not_fail(tmp_path):
    result = _run(tmp_path, no_skip=True, allowed=GATE, reason=GATE)
    assert result.returncode == 0, result.stdout
    assert "skipped=1 unexpected=0 allowlisted=1" in result.stdout


def test_skip_is_tolerated_only_when_no_skip_mode_is_off(tmp_path):
    result = _run(tmp_path, no_skip=False)
    assert result.returncode == 0, result.stdout
    assert "skipped=1 unexpected=0" in result.stdout


def test_allowlist_holds_exactly_the_declared_external_gate_reason(tmp_path):
    import skip_policy

    assert skip_policy.ALLOWED_SKIP_REASONS == (
        "EXTERNAL-GATE: validated profile requires native reconciliation evidence",)
    assert skip_policy.MAX_ALLOWED_SKIPS == 1
    # An unrelated skip reason is still a failure under NO_SKIP: the allowlist did not widen.
    result = _run(tmp_path, no_skip=True)
    assert result.returncode != 0 and "UNEXPECTED" in result.stdout


@pytest.mark.parametrize("widener", [" ", ",", " , ,  ", "   ,"])
def test_blank_env_entries_cannot_widen_the_allowlist(tmp_path, widener):
    result = _run(tmp_path, no_skip=True, allowed=widener)
    assert result.returncode != 0, result.stdout
    assert "skipped=1 unexpected=1" in result.stdout


@pytest.mark.parametrize("entry", ["probe-reason", "p", "EXTERNAL-GATE: ok,probe-reason"])
def test_non_prefixed_env_entry_is_rejected_at_configure_time(tmp_path, entry):
    result = _run(tmp_path, no_skip=True, allowed=entry)
    assert result.returncode != 0, result.stdout
    assert "must start with 'EXTERNAL-GATE:'" in result.stdout + result.stderr
    assert "passed" not in result.stdout


def test_effective_allowlist_is_printed_in_the_terminal_summary(tmp_path):
    result = _run(tmp_path, no_skip=True, allowed=" " + GATE + " , ", reason=GATE)
    assert result.returncode == 0, result.stdout
    assert ("effective_allowlist=['EXTERNAL-GATE: validated profile requires native "
            f"reconciliation evidence', '{GATE}']") in result.stdout


@pytest.mark.parametrize("body", [
    "import pytest\npytest.skip('module-level-probe', allow_module_level=True)\n",
    "import pytest\npytest.importorskip('definitely_not_installed_module_xyz')\n",
])
def test_collection_time_skip_is_a_failure_under_no_skip(tmp_path, body):
    result = _run(tmp_path, no_skip=True, body=body)
    assert result.returncode != 0, result.stdout
    assert "UNEXPECTED COLLECTION-TIME SKIP" in result.stdout
    assert "unexpected=1" in result.stdout


def test_collection_time_skip_is_tolerated_when_no_skip_is_off(tmp_path):
    result = _run(tmp_path, no_skip=False,
                  body="import pytest\npytest.skip('x', allow_module_level=True)\n")
    # Exit 5 = "no tests collected" (plain pytest behaviour), never a collection error (2).
    assert result.returncode == 5, result.stdout
    assert "skipped=1 unexpected=0" in result.stdout and "UNEXPECTED" not in result.stdout


def test_more_than_one_allowlisted_skip_fails_the_run(tmp_path):
    body = ("import pytest\n\ndef test_a():\n    pytest.skip('EXTERNAL-GATE: two')\n\n"
            "def test_b():\n    pytest.skip('EXTERNAL-GATE: two')\n")
    result = _run(tmp_path, no_skip=True, allowed="EXTERNAL-GATE: two", body=body)
    assert result.returncode != 0, result.stdout
    assert "unexpected=0 allowlisted=2" in result.stdout
    assert "VIOLATION" in result.stdout


def test_exactly_one_allowlisted_skip_is_within_the_limit(tmp_path):
    body = "import pytest\n\ndef test_a():\n    pytest.skip('EXTERNAL-GATE: one')\n"
    result = _run(tmp_path, no_skip=True, allowed="EXTERNAL-GATE: one", body=body)
    assert result.returncode == 0, result.stdout
    assert "allowlisted=1" in result.stdout
