"""U18 - run the Functional Tester suite (SC01..SC12) against the E2E stack.

The suite lives on branch qa/functional-tester-sc01-sc12 (tests/functional, env-var driven FT_*).
When it is not in this tree the test is SKIPPED with the explicit reason `FT-suite-not-merged`
(never a silent pass). When present, every FT test must pass with zero skips and zero errors:
the junit XML plus the exact code SHA are kept under .e2e/evidence/ as the FT report evidence.
"""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from user_support import E2E_DIR, ROOT

pytestmark = [pytest.mark.user]

FT_DIR = ROOT / "tests" / "functional"


def _git_head() -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                               text=True, check=True)
    return completed.stdout.strip()


def test_u18_functional_tester_sc01_sc12_pass_through_public_mcp_tools(e2e_env, idp, ids):
    if not FT_DIR.is_dir():
        pytest.skip("FT-suite-not-merged: tests/functional is absent in this tree "
                    "(branch qa/functional-tester-sc01-sc12)")

    evidence_dir = E2E_DIR / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    junit = evidence_dir / "u18-functional-junit.xml"
    host, ports = e2e_env.raw["host"], e2e_env.raw["ports"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FT_")}
    env.update({
        "FT_MCP_URL": e2e_env.mcp_url,
        "FT_ADMIN_DATABASE_URL": e2e_env.dsn("admin"),
        "FT_FAKE1C_URL": f"http://{host}:{ports['fake1c']}",
        "FT_SOURCE_ID": ids["source"],
        "FT_COMPANY_ONE_ID": ids["one"], "FT_COMPANY_TWO_ID": ids["two"],
        "FT_PRINCIPAL": ids["uc1"],
        "FT_BEARER_TOKEN": idp.token(ids["uc1"]),
        "FT_BEARER_TOKEN_NO_ACCESS": idp.token(ids["una"]),
        "FT_BEARER_TOKEN_COMPANY_TWO": idp.token(ids["uc2"]),
        "FT_GATEWAY_LOG": str(E2E_DIR / "logs" / "gateway.out.log"),
        "FT_EVIDENCE_OUT": str(evidence_dir / "u18-ft-evidence"),
        "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")]),
    })
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/functional", "-p", "no:cacheprovider", "-q",
         f"--junitxml={junit}"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800, check=False)
    tail = (completed.stdout + completed.stderr)[-2000:]
    assert junit.exists(), f"FT run produced no junit report:\n{tail}"

    suite = ET.parse(junit).getroot()
    suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
    counts = {key: int(suite.get(key, 0)) for key in ("tests", "failures", "errors", "skipped")}
    sha = _git_head()
    assert counts["tests"] > 0, f"FT suite collected no tests (code SHA {sha})\n{tail}"
    assert counts["failures"] == 0 and counts["errors"] == 0, (counts, sha, tail)
    assert counts["skipped"] == 0, f"FT cases skipped (not PASS): {counts} (code SHA {sha})\n{tail}"
    assert completed.returncode == 0, (completed.returncode, sha, tail)
    (evidence_dir / "u18-code-sha.txt").write_text(f"{sha}\n{counts}\n", encoding="utf-8")
