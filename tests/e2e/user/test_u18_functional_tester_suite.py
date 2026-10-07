"""U18 - run the Functional Tester suite (SC01..SC12) against the E2E (OIDC) stack.

The suite lives in tests/functional (env-var driven FT_*). It is run in a subprocess against the
E2E gateway with real IdP-issued bearer tokens, and the junit XML is parsed with an EXACT
expectation (pytest counts xfail as "skipped", so a bare `skipped == 0` check cannot be used):

* SC01..SC12 each appear in `test_scenario_positive_contract`;
* SC01-SC05, SC07, SC09-SC12 PASSED (no skipped/xfail/failure/error element);
* SC06 is the ONLY allowed xfail "EXTERNAL-GATE" and SC08 the ONLY allowed xfail
  "NOT IMPLEMENTED" (Amendment A1 of docs/E2E_ACCEPTANCE_CONTRACT.md: U18 is reported as
  10 of 12 PASS plus these two declared dispositions, never as 12/12; an unexpected pass of
  either also fails U18 so the declaration must then be retired);
* every other test case passed: no failure, no error and no skip, EXCEPT the two dev-mode-only
  cases in `ALLOWED_SKIPS` (they revoke/re-add the dev principal's grant with scripts/admin.py and
  are skipped by design whenever a bearer token is configured; the same grant lifecycle is
  covered through the Admin API by U09/U10). The needs-oidc-identity cases really run because
  all three FT_BEARER_TOKEN* variables are wired.

The FT main identity (user_company_one) gets a TEMPORARY source-wide grant for the run (the
dev-mode principal of the FT stack had one too); it is revoked afterwards.

The junit XML, the gateway log snapshot and the exact code SHA are kept under .e2e/evidence/.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from user_support import E2E_DIR, ROOT

pytestmark = [pytest.mark.user]

FT_DIR = ROOT / "tests" / "functional"
SC_IDS = [f"SC{n:02d}" for n in range(1, 13)]
EXPECTED_XFAIL = {"SC06": "EXTERNAL-GATE", "SC08": "NOT IMPLEMENTED"}
POSITIVE_TEST = "test_scenario_positive_contract"
ALLOWED_SKIPS = {
    "test_revoked_source_grant_denies_before_any_upstream_request_and_restores",
    "test_company_scoped_grant_isolates_company_two_from_company_one",
}
DEV_MODE_SKIP_REASON = "grant manipulation via admin.py is a dev-mode case"


def _git_head() -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                               text=True, check=True)
    return completed.stdout.strip()


def classify_junit(junit: Path) -> dict[str, dict]:
    """testcase id -> {status: passed|failed|error|skipped|xfail, message}."""
    cases: dict[str, dict] = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        key = f"{case.get('classname')}::{case.get('name')}"
        status, message = "passed", ""
        for child in case:
            if child.tag in ("failure", "error"):
                status, message = ("failed" if child.tag == "failure" else "error"), (
                    child.get("message") or "")[:300]
            elif child.tag == "skipped":
                kind = child.get("type") or ""
                status = "xfail" if "xfail" in kind else "skipped"
                message = child.get("message") or ""
        cases[key] = {"status": status, "message": message}
    return cases


def check_ft_results(cases: dict[str, dict]) -> list[str]:
    """Problems versus the exact U18 definition (empty list = conforming)."""
    problems: list[str] = []
    positive = {}
    for key, result in cases.items():
        match = re.search(rf"{POSITIVE_TEST}\[(SC\d\d)\]", key)
        if match:
            positive[match.group(1)] = result
    for sc in SC_IDS:
        if sc not in positive:
            problems.append(f"{sc}: positive contract case missing from the junit report")
            continue
        result = positive[sc]
        if sc in EXPECTED_XFAIL:
            if result["status"] != "xfail" or EXPECTED_XFAIL[sc] not in result["message"]:
                problems.append(f"{sc}: expected xfail {EXPECTED_XFAIL[sc]!r}, got {result}")
        elif result["status"] != "passed":
            problems.append(f"{sc}: expected PASS, got {result}")
    for key, result in cases.items():
        is_expected_xfail = any(
            f"{POSITIVE_TEST}[{sc}]" in key for sc in EXPECTED_XFAIL)
        allowed_skip = (result["status"] == "skipped" and DEV_MODE_SKIP_REASON in result["message"]
                        and key.rsplit("::", 1)[-1] in ALLOWED_SKIPS)
        if result["status"] != "passed" and not is_expected_xfail and not allowed_skip:
            problems.append(f"{key}: {result['status']} {result['message']}")
    return problems


def test_u18_junit_definition_is_exact_not_vacuous(tmp_path):
    """The classifier itself: it must reject every deviation from the U18 definition."""
    def junit(cases: dict[str, str]) -> Path:
        root = ET.Element("testsuite")
        for sc in SC_IDS:
            case = ET.SubElement(root, "testcase", classname="tests.functional.t10",
                                 name=f"{POSITIVE_TEST}[{sc}]")
            kind = cases.get(sc, "pass")
            if kind == "xfail":
                ET.SubElement(case, "skipped", type="pytest.xfail",
                              message=f"xfail {EXPECTED_XFAIL.get(sc, '?')} {sc}")
            elif kind == "skip":
                ET.SubElement(case, "skipped", type="pytest.skip", message="needs-oidc-identity")
            elif kind == "fail":
                ET.SubElement(case, "failure", message="boom")
        path = tmp_path / f"{len(list(tmp_path.iterdir()))}.xml"
        ET.ElementTree(root).write(path)
        return path

    good = {"SC06": "xfail", "SC08": "xfail"}
    assert check_ft_results(classify_junit(junit(good))) == []
    assert check_ft_results(classify_junit(junit({**good, "SC03": "skip"})))  # a skip is not a pass
    assert check_ft_results(classify_junit(junit({**good, "SC03": "fail"})))
    assert check_ft_results(classify_junit(junit({"SC06": "xfail"})))  # SC08 must be xfail
    assert check_ft_results(classify_junit(junit({**good, "SC01": "xfail"})))  # unexpected xfail
    allowed = junit(good)
    root = ET.parse(allowed).getroot()
    extra = ET.SubElement(root, "testcase", classname="tests.functional.t30",
                          name=min(ALLOWED_SKIPS))
    ET.SubElement(extra, "skipped", type="pytest.skip", message=DEV_MODE_SKIP_REASON)
    ET.ElementTree(root).write(allowed)
    assert check_ft_results(classify_junit(allowed)) == []  # the two dev-mode cases are allowed
    other = ET.parse(allowed).getroot()
    other[-1].find("skipped").set("message", "needs-oidc-identity: set FT_BEARER_TOKEN_NO_ACCESS")
    ET.ElementTree(other).write(allowed)
    assert check_ft_results(classify_junit(allowed))  # same test, different reason: rejected
    wrong_reason = junit(good)
    text = wrong_reason.read_text(encoding="utf-8").replace("EXTERNAL-GATE", "OTHER")
    wrong_reason.write_text(text, encoding="utf-8")
    assert check_ft_results(classify_junit(wrong_reason))


def test_u18_functional_tester_sc01_sc12_pass_through_public_mcp_tools(
        e2e_env, idp, ids, grants):
    assert FT_DIR.is_dir(), "tests/functional is missing: the FT suite must be part of this tree"

    evidence_dir = E2E_DIR / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    junit = evidence_dir / "u18-functional-junit.xml"
    junit.unlink(missing_ok=True)
    host, ports = e2e_env.raw["host"], e2e_env.raw["ports"]
    # The gateway logs (uvicorn/logging write to stderr) are read LIVE by the FT log-hygiene and
    # request-correlation cases; the file is copied to the evidence directory afterwards.
    gateway_log = E2E_DIR / "logs" / "gateway.err.log"
    assert gateway_log.exists(), "gateway log missing"
    env = {k: v for k, v in os.environ.items() if not k.startswith("FT_")}
    env.update({
        "FT_MCP_URL": e2e_env.mcp_url,
        "FT_ADMIN_DATABASE_URL": e2e_env.dsn("admin"),
        "FT_FAKE1C_URL": f"http://{host}:{ports['fake1c']}",       # recording wrapper (testbed)
        "FT_SIDECAR_URL": f"http://{host}:{ports['sidecar']}",     # recording fake sidecar
        "FT_SOURCE_ID": ids["source"],
        "FT_COMPANY_ONE_ID": ids["one"], "FT_COMPANY_TWO_ID": ids["two"],
        "FT_PRINCIPAL": ids["uc1"],
        "FT_BEARER_TOKEN": idp.token(ids["uc1"]),
        "FT_BEARER_TOKEN_NO_ACCESS": idp.token(ids["una"]),
        "FT_BEARER_TOKEN_COMPANY_TWO": idp.token(ids["uc2"]),
        # Runs the no-access capability case. The E2E gateway keeps business-capability
        # enforcement OFF, so that case proves grant denial only (documented deviation).
        "FT_EXPECT_CAPABILITY_ENFORCEMENT": "0",
        "FT_GATEWAY_LOG": str(gateway_log),
        "FT_EVIDENCE_OUT": str(evidence_dir / "u18-ft-evidence"),
        "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")]),
    })
    with grants.temporary_source_wide(ids["uc1"]):
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/functional", "-p", "no:cacheprovider", "-q",
             "-rs", f"--junitxml={junit}"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800, check=False)
    tail = (completed.stdout + completed.stderr)[-2500:]
    assert junit.exists(), f"FT run produced no junit report:\n{tail}"

    shutil.copyfile(gateway_log, evidence_dir / "u18-gateway.err.log")
    sha = _git_head()
    cases = classify_junit(junit)
    assert len(cases) > 12, f"FT suite collected too few tests (code SHA {sha})\n{tail}"
    problems = check_ft_results(cases)
    assert not problems, f"U18 deviations (code SHA {sha}):\n" + "\n".join(problems) + f"\n{tail}"
    assert completed.returncode == 0, (completed.returncode, sha, tail)
    counts = {s: sum(1 for c in cases.values() if c["status"] == s)
              for s in ("passed", "xfail", "skipped", "failed", "error")}
    assert counts["skipped"] == len(ALLOWED_SKIPS) and counts["xfail"] == len(EXPECTED_XFAIL), counts
    (evidence_dir / "u18-code-sha.txt").write_text(f"{sha}\n{counts}\n", encoding="utf-8")
