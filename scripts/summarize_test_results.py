"""Aggregate actual JUnit cases without publishing test names, payloads or tracebacks."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError

MAX_JUNIT_BYTES = 16_000_000
MAX_TEST_CASES = 100_000


def read_junit(path: Path) -> dict:
    """Shared bounded hardened reader. Suite-declared totals cannot manufacture executed cases."""
    if path.is_symlink() or path.stat().st_size > MAX_JUNIT_BYTES:
        raise ValueError("test report input limit")
    with path.open('rb') as stream:
        raw = stream.read(MAX_JUNIT_BYTES + 1)
    if not raw or len(raw) > MAX_JUNIT_BYTES:
        raise ValueError("test report input limit")
    root = ElementTree.fromstring(raw, forbid_dtd=True)
    tag = lambda item: item.tag.rsplit("}", 1)[-1]
    if tag(root) not in {"testsuite", "testsuites"}:
        raise ValueError("not a JUnit report")
    cases = [item for item in root.iter() if tag(item) == "testcase"]
    if len(cases) > MAX_TEST_CASES:
        raise ValueError('test report case limit')
    declared_failures = declared_skips = False
    for suite in root.iter():
        if tag(suite) not in {'testsuite', 'testsuites'}:
            continue
        for attribute in ('failures', 'errors', 'skipped'):
            value = suite.get(attribute)
            if value is not None:
                if not value.isdecimal() or len(value) > 9:
                    raise ValueError('invalid JUnit negative signal')
                if int(value):
                    if attribute == 'skipped':
                        declared_skips = True
                    else:
                        declared_failures = True
    outcomes = []
    for index, case in enumerate(cases):
        children = {tag(child) for child in case}
        outcome = "ERROR" if "error" in children else "FAIL" if "failure" in children else "SKIP" if "skipped" in children else "PASS"
        identity = f"{index}\0{case.get('classname', '')}\0{case.get('name', '')}".encode()
        outcomes.append({"case_id_sha256": hashlib.sha256(identity).hexdigest(), "outcome": outcome})
    counts = {
        "tests": len(cases),
        "failures": sum(tag(item) == "failure" for item in root.iter()),
        "errors": sum(tag(item) == "error" for item in root.iter()),
        "skipped": sum(any(tag(child) == "skipped" for child in item) for item in cases),
    }
    return {'junit_sha256': hashlib.sha256(raw).hexdigest(), 'counts': counts, 'case_outcomes': outcomes,
            'declared_failure_signal': declared_failures, 'declared_skip_signal': declared_skips}


def summarize(path: Path, *, suite_id: str, source_commit: str, exit_code: int) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", suite_id) or not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise ValueError("invalid test report identity")
    if type(exit_code) is not int:
        raise ValueError("invalid test exit code")
    parsed = read_junit(path)
    counts = parsed['counts']
    return {"schema_version": 1, "suite_id": suite_id, "source_commit": source_commit, **parsed,
            "exit_code": exit_code, "passed": exit_code == 0 and counts["tests"] > 0
            and counts["failures"] == counts["errors"] == 0 and not parsed['declared_failure_signal'],
            "raw_test_output_included": False, "native_evidence_level_inferred": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--suite-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = summarize(args.junit, suite_id=args.suite_id, source_commit=args.commit, exit_code=args.exit_code)
        with args.output.open('x', encoding='utf-8') as output:
            output.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    except (OSError, ValueError, DefusedXmlException, ParseError):
        raise SystemExit('JUNIT_EVIDENCE_INVALID: private diagnostics withheld') from None
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
