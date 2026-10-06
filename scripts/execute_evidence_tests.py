"""Record executed pytest evidence; skipped tests cannot prove a closed gate."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree


def execute(paths: list[str]) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="erp-mcp-evidence-") as directory:
        report = Path(directory) / "junit.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *paths, f"--junitxml={report}"],
            cwd=root, capture_output=True, text=True, timeout=120, check=False,
        )
        counts = {name: 0 for name in ("tests", "failures", "errors", "skipped")}
        if report.is_file():
            for suite in ElementTree.parse(report).getroot().iter("testsuite"):
                for name in counts:
                    counts[name] += int(suite.get(name, "0"))
    return {
        "mode": "executed_pytest_contracts", "test_paths": paths,
        "returncode": result.returncode, "counts": counts,
        "passed": result.returncode == 0 and counts["tests"] > 0
        and counts["failures"] == counts["errors"] == counts["skipped"] == 0,
        "raw_test_output_included": False,
    }
