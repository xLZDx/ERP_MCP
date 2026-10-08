"""Phase 2 session guard: required PostgreSQL integration tests must really run.

With ERP_PHASE2_REQUIRE_PG=1 the run FAILS when
- any phase2 item marked ``integration`` was deselected, skipped or xfailed (a skip is not a pass), or
- fewer ``[sql]`` items of the shared port contract (test_ports_contract.py) executed than there
  are ``[fake]`` items (the SQL variant must be a full mirror of the fake variant).
"""
import os
import re
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
CONTRACT_FILE = "test_ports_contract.py"


def _required() -> bool:
    return os.environ.get("ERP_PHASE2_REQUIRE_PG") == "1"


def _variant(item) -> str | None:
    callspec = getattr(item, "callspec", None)
    return None if callspec is None else callspec.params.get("h")


def _is_phase2_integration(item) -> bool:
    try:
        in_dir = _HERE in Path(str(item.path)).resolve().parents
    except (AttributeError, OSError):
        return False
    return in_dir and item.get_closest_marker("integration") is not None


def _report_is_phase2_integration(report) -> bool:
    parts = str(report.location[0]).replace("\\", "/").split("/")
    return "phase2" in parts[:-1] and "integration" in report.keywords


class RequirePgGuard:
    """Collects what did not run; ``problems()`` is empty when the REQUIRE_PG contract holds."""

    def __init__(self):
        self.not_run: set[str] = set()
        self.fake_planned = 0
        self.sql_executed: set[str] = set()

    def plan(self, items) -> None:
        self.fake_planned = sum(1 for i in items if i.nodeid.split("::")[0].endswith(CONTRACT_FILE)
                                and _variant(i) == "fake")

    def deselected(self, items) -> None:
        self.not_run.update(i.nodeid + " (deselected)" for i in items if _is_phase2_integration(i))

    def observe(self, report) -> None:
        if report.skipped and _report_is_phase2_integration(report):
            kind = "xfailed" if hasattr(report, "wasxfail") else "skipped"
            self.not_run.add(f"{report.nodeid} ({kind})")
        if (report.when == "call" and report.nodeid.split("::")[0].endswith(CONTRACT_FILE)
                and (report.passed or report.failed) and "[" in report.nodeid
                and "sql" in re.split(r"[\[\]-]", report.nodeid.split("[", 1)[1])):
            self.sql_executed.add(report.nodeid)

    def problems(self) -> list[str]:
        out = []
        if self.not_run:
            out.append("integration tests did not run: " + "; ".join(sorted(self.not_run)))
        if len(self.sql_executed) < self.fake_planned:
            out.append(f"only {len(self.sql_executed)} [sql] contract items executed but "
                       f"{self.fake_planned} [fake] items exist")
        return out


_guard = RequirePgGuard()


def pytest_configure(config):
    config._phase2_guard_cls = RequirePgGuard


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    _guard.plan(items)  # before -k/-m deselection


def pytest_deselected(items):
    if _required():
        _guard.deselected(items)


def pytest_runtest_logreport(report):
    if _required():
        _guard.observe(report)


def pytest_sessionfinish(session, exitstatus):
    if not _required():
        return
    problems = _guard.problems()
    if problems:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line("ERP_PHASE2_REQUIRE_PG=1 violated: " + " | ".join(problems),
                                red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
