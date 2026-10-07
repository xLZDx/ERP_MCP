import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import summarize_test_results
from scripts.execute_evidence_tests import execute


@pytest.mark.parametrize("failures,errors,skipped", [(1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)])
def test_evidence_pass_requires_executed_tests_with_no_failures_or_skips(monkeypatch, failures, errors, skipped):
    def runner(command, **_kwargs):
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        child = '<failure/>' if failures else '<error/>' if errors else '<skipped/>' if skipped else ''
        report.write_text(f'<testsuites><testsuite tests="2"><testcase>{child}</testcase><testcase/></testsuite></testsuites>')
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


def install_report(monkeypatch, xml):
    def runner(command, **_kwargs):
        report = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--junitxml=')))
        report.write_text(xml, encoding='utf-8')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', runner)


def test_declared_total_does_not_invent_executed_cases(monkeypatch):
    install_report(monkeypatch, '<testsuite tests="999999"/>')
    result = execute(['synthetic_test.py'])
    assert result['counts']['tests'] == 0 and result['passed'] is False
    install_report(monkeypatch, '<testsuite tests="999999"><testcase/><testcase/></testsuite>')
    result = execute(['synthetic_test.py'])
    assert result['counts']['tests'] == 2 and result['passed'] is True


@pytest.mark.parametrize('xml', [
    '<testsuite><private-token>', '<private-payload/>',
    '<!DOCTYPE testsuite [<!ENTITY secret "private-secret">]><testsuite><testcase name="&secret;"/></testsuite>',
])
def test_malformed_wrong_root_or_dtd_cannot_pass_or_leak(monkeypatch, xml):
    install_report(monkeypatch, xml)
    result = execute(['synthetic_test.py'])
    assert result['passed'] is False and result['report_status'] == 'INVALID_OR_OVERSIZED'
    assert 'private-' not in str(result)


@pytest.mark.parametrize('attribute', ['errors', 'failures', 'skipped'])
def test_declared_negative_signal_is_not_silently_ignored(monkeypatch, attribute):
    install_report(monkeypatch, f'<testsuite {attribute}="1"><testcase/></testsuite>')
    result = execute(['synthetic_test.py'])
    assert result['passed'] is False and result['declared_nonpassing_signal'] is True


def test_oversized_report_and_excess_cases_are_nonpassing(monkeypatch):
    install_report(monkeypatch, '<testsuite><testcase/><testcase/></testsuite>')
    monkeypatch.setattr(summarize_test_results, 'MAX_TEST_CASES', 1)
    assert execute(['synthetic_test.py'])['passed'] is False
    monkeypatch.setattr(summarize_test_results, 'MAX_TEST_CASES', 100000)
    monkeypatch.setattr(summarize_test_results, 'MAX_JUNIT_BYTES', 16)
    assert execute(['synthetic_test.py'])['passed'] is False


def test_spawn_error_is_sanitized_and_nonpassing(monkeypatch):
    def runner(*_args, **_kwargs):
        raise OSError('private executable path token')
    monkeypatch.setattr(subprocess, 'run', runner)
    result = execute(['synthetic_test.py'])
    assert result['passed'] is False and result['returncode'] == 127
    assert 'private executable' not in str(result)


def test_summary_cli_refuses_overwrite_without_touching_user_artifact(tmp_path, monkeypatch):
    report, output = tmp_path / 'junit.xml', tmp_path / 'existing.json'
    report.write_text('<testsuite><testcase name="private-fixture-name"/></testsuite>')
    output.write_text('owned existing artifact')
    monkeypatch.setattr(sys, 'argv', ['summary', '--junit', str(report), '--suite-id', 'fixture',
                        '--commit', 'a' * 40, '--exit-code', '0', '--output', str(output)])
    with pytest.raises(SystemExit, match='JUNIT_EVIDENCE_INVALID'):
        summarize_test_results.main()
    assert output.read_text() == 'owned existing artifact'


def test_summary_cli_malformed_private_report_is_sanitized_and_creates_no_artifact(tmp_path, monkeypatch):
    report, output = tmp_path / 'junit.xml', tmp_path / 'new.json'
    report.write_text('<!DOCTYPE private-document><testsuite><testcase/></testsuite>')
    monkeypatch.setattr(sys, 'argv', ['summary', '--junit', str(report), '--suite-id', 'fixture',
                        '--commit', 'a' * 40, '--exit-code', '0', '--output', str(output)])
    with pytest.raises(SystemExit) as failure:
        summarize_test_results.main()
    assert 'private-document' not in str(failure.value) and not output.exists()
