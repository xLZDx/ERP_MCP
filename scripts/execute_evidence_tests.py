"""Record executed pytest evidence; skipped tests cannot prove a closed gate."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError

try:
    from .summarize_test_results import read_junit
except ImportError:
    from summarize_test_results import read_junit


def execute(paths: list[str], *, timeout_seconds: float = 120) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    timed_out = False
    report_status = 'MISSING'
    report_sha256 = None
    declared_nonpassing = False
    with tempfile.TemporaryDirectory(prefix="erp-mcp-evidence-") as directory:
        report = Path(directory) / "junit.xml"
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *paths, f"--junitxml={report}"],
                cwd=root, capture_output=True, text=True, timeout=timeout_seconds, check=False,
            )
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = 124
        except OSError:
            returncode = 127
            report_status = 'SPAWN_FAILED'
        counts = {name: 0 for name in ("tests", "failures", "errors", "skipped")}
        if report.is_file():
            try:
                parsed = read_junit(report)
                counts = parsed['counts']
                report_sha256 = parsed['junit_sha256']
                declared_nonpassing = parsed['declared_failure_signal'] or parsed['declared_skip_signal']
                report_status = 'VALID_ACTUAL_CASES'
            except (OSError, ValueError, DefusedXmlException, ParseError):
                report_status = 'INVALID_OR_OVERSIZED'
                counts['errors'] = 1
    return {
        "mode": "executed_pytest_contracts", "test_paths": paths,
        "returncode": returncode, "counts": counts, "timed_out": timed_out,
        "report_status": report_status, "junit_sha256": report_sha256,
        "actual_cases_required": True,
        "declared_nonpassing_signal": declared_nonpassing,
        "passed": returncode == 0 and counts["tests"] > 0
        and counts["failures"] == counts["errors"] == counts["skipped"] == 0 and not declared_nonpassing,
        "raw_test_output_included": False,
    }
