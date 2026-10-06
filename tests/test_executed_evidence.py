import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.execute_evidence_tests import execute


@pytest.mark.parametrize("failures,errors,skipped", [(1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)])
def test_evidence_pass_requires_executed_tests_with_no_failures_or_skips(monkeypatch, failures, errors, skipped):
    def runner(command, **_kwargs):
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        report.write_text(f'<testsuites><testsuite tests="2" failures="{failures}" errors="{errors}" skipped="{skipped}"/></testsuites>')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", runner)
    evidence = execute(["synthetic_test.py"])
    assert evidence["passed"] is (failures == errors == skipped == 0)
    assert evidence["raw_test_output_included"] is False


def test_evidence_timeout_is_sanitized_nonpassing_artifact(monkeypatch):
    def runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("synthetic", 1, output="private fixture secret")

    monkeypatch.setattr(subprocess, "run", runner)
    evidence = execute(["synthetic_test.py"], timeout_seconds=1)
    assert evidence["passed"] is False and evidence["timed_out"] is True
    assert "private fixture secret" not in str(evidence)


def test_evidence_zero_exit_without_junit_cannot_close_gate(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    assert execute(["synthetic_test.py"])["passed"] is False
