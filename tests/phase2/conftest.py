"""Phase 2 session guard: required PostgreSQL integration tests must really run."""
import os
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_not_run: list[str] = []


def _is_phase2_integration(item) -> bool:
    try:
        in_dir = _HERE in Path(str(item.path)).resolve().parents
    except (AttributeError, OSError):
        return False
    return in_dir and item.get_closest_marker("integration") is not None


def _required() -> bool:
    return os.environ.get("ERP_PHASE2_REQUIRE_PG") == "1"


def pytest_deselected(items):
    if _required():
        _not_run.extend(i.nodeid + " (deselected)" for i in items if _is_phase2_integration(i))


def pytest_runtest_logreport(report):
    if _required() and report.skipped and "test_g1_postgres_integration" in report.nodeid:
        _not_run.append(report.nodeid + " (skipped)")


def pytest_sessionfinish(session, exitstatus):
    if _required() and _not_run:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line("ERP_PHASE2_REQUIRE_PG=1 but integration tests did not run: "
                                + "; ".join(sorted(set(_not_run))), red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
