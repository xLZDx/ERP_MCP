"""No-silent-skip policy for the E2E suites.

With ``ERP_MCP_E2E_NO_SKIP=1`` (set by scripts/e2e/test.ps1) every skipped test whose reason is
not on the explicit allowlist is turned into a FAILURE, so the run exits non-zero; the terminal
summary always prints the skipped count and the EFFECTIVE allowlist. Collection-time skips
(module-level ``pytest.skip(allow_module_level=True)``, ``importorskip``) are failures too.
xfail is not a skip and is left alone.

The allowlist is ``ALLOWED_SKIP_REASONS`` (substrings of the skip reason; exactly one
declared EXTERNAL-GATE) and at most ``MAX_ALLOWED_SKIPS`` allowlisted skips may occur in a run
(the single declared node tests/e2e/admin/test_a38_a41_metadata_profiles.py). The env var
``ERP_MCP_E2E_ALLOWED_SKIP_REASONS`` (comma separated) exists only so the policy itself can be
tested; scripts/e2e/test.ps1 removes it from the environment. Blank entries are ignored and
every entry must start with ``EXTERNAL-GATE:`` or pytest aborts at configure time.
"""

from __future__ import annotations

import os

import pytest

NO_SKIP_VAR = "ERP_MCP_E2E_NO_SKIP"
EXTRA_VAR = "ERP_MCP_E2E_ALLOWED_SKIP_REASONS"
EXTRA_PREFIX = "EXTERNAL-GATE:"
MAX_ALLOWED_SKIPS = 1
ALLOWED_SKIP_REASONS: tuple[str, ...] = (
    "EXTERNAL-GATE: validated profile requires native reconciliation evidence",
)
_SEEN = {"skipped": 0, "unexpected": 0, "allowlisted": 0}


def _extra() -> tuple[str, ...]:
    entries = tuple(x.strip() for x in os.environ.get(EXTRA_VAR, "").split(","))
    return tuple(x for x in entries if x)


def _allowed() -> tuple[str, ...]:
    return ALLOWED_SKIP_REASONS + _extra()


def pytest_configure(config):
    bad = [x for x in _extra() if not x.startswith(EXTRA_PREFIX)]
    if bad:
        raise pytest.UsageError(
            f"{EXTRA_VAR} entries must start with {EXTRA_PREFIX!r}; rejected: {bad!r}")


def _reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


def _police(report, where: str, kind: str) -> None:
    _SEEN["skipped"] += 1
    if not os.environ.get(NO_SKIP_VAR):
        return
    reason = _reason(report)
    if any(allowed in reason for allowed in _allowed()):
        _SEEN["allowlisted"] += 1
        return
    _SEEN["unexpected"] += 1
    report.outcome = "failed"
    report.longrepr = (f"UNEXPECTED {kind} SKIP under {NO_SKIP_VAR}=1 (not on the allowlist): "
                       f"{where}: {reason}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not report.skipped or hasattr(report, "wasxfail"):
        return
    _police(report, item.nodeid, "")


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    report = outcome.get_result()
    if report.skipped:
        _police(report, str(getattr(collector, "nodeid", collector)), "COLLECTION-TIME")


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get(NO_SKIP_VAR) and _SEEN["allowlisted"] > MAX_ALLOWED_SKIPS:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(
        f"e2e skip policy: skipped={_SEEN['skipped']} unexpected={_SEEN['unexpected']} "
        f"allowlisted={_SEEN['allowlisted']} "
        f"(NO_SKIP={'on' if os.environ.get(NO_SKIP_VAR) else 'off'}) "
        f"effective_allowlist={list(_allowed())!r}")
    if os.environ.get(NO_SKIP_VAR) and _SEEN["allowlisted"] > MAX_ALLOWED_SKIPS:
        terminalreporter.write_line(
            f"e2e skip policy VIOLATION: {_SEEN['allowlisted']} allowlisted skips "
            f"> max {MAX_ALLOWED_SKIPS}")
