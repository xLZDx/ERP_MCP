"""No-silent-skip policy for the E2E suites.

With ``ERP_MCP_E2E_NO_SKIP=1`` (set by scripts/e2e/test.ps1) every skipped test whose reason is
not on the explicit allowlist is turned into a FAILURE, so the run exits non-zero; the terminal
summary always prints the skipped count. xfail is not a skip and is left alone.

The allowlist is ``ALLOWED_SKIP_REASONS`` (substrings of the skip reason; empty on purpose). The
env var ``ERP_MCP_E2E_ALLOWED_SKIP_REASONS`` (comma separated) exists only so the policy itself
can be tested; test.ps1 never sets it.
"""

from __future__ import annotations

import os

import pytest

NO_SKIP_VAR = "ERP_MCP_E2E_NO_SKIP"
ALLOWED_SKIP_REASONS: tuple[str, ...] = ()
_SEEN = {"skipped": 0, "unexpected": 0}


def _allowed() -> tuple[str, ...]:
    extra = tuple(x for x in os.environ.get("ERP_MCP_E2E_ALLOWED_SKIP_REASONS", "").split(",") if x)
    return ALLOWED_SKIP_REASONS + extra


def _reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not report.skipped or hasattr(report, "wasxfail"):
        return
    _SEEN["skipped"] += 1
    if not os.environ.get(NO_SKIP_VAR):
        return
    reason = _reason(report)
    if any(allowed in reason for allowed in _allowed()):
        return
    _SEEN["unexpected"] += 1
    report.outcome = "failed"
    report.longrepr = (f"UNEXPECTED SKIP under {NO_SKIP_VAR}=1 (not on the allowlist): "
                       f"{item.nodeid}: {reason}")


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(
        f"e2e skip policy: skipped={_SEEN['skipped']} unexpected={_SEEN['unexpected']} "
        f"(NO_SKIP={'on' if os.environ.get(NO_SKIP_VAR) else 'off'})")
