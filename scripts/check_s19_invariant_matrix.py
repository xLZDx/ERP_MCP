"""Check S19 invariant coverage and exact-head-bound boundary-result records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = Path("docs/phase2/S11_TEST_DESIGN_PACKAGE_2026-10-12.md")
EXPECTED_INVARIANTS = tuple(f"I{number}" for number in range(1, 16))
ACTIVE_SCENARIOS = frozenset(set(range(1, 48)) - {8})
INVARIANT_ID = re.compile(r"^I([0-9]+)\b")
SCENARIO_ID = re.compile(r"\bE([0-9]+)\b")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ASSERTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
GATE_MAPPING_MARKERS = ("E46", "E47", "map to gates and CT14, not to invariants")
MATRIX_HEADING = "## A. Invariant -> scenarios -> failing assertion at the enforcement boundary -> data-level negative control"
RESULT_FIELDS = {
    "invariant_id", "scenario_id", "assertion_id", "result", "tested_head",
    "evidence_commit", "evidence_path", "evidence_sha256", "reason",
}
RESULTS_FIELDS = {"schema_version", "selected_head", "results"}
RESULT_EVIDENCE_FIELDS = {
    "schema_version", "invariant_id", "scenario_id", "assertion_id", "result",
    "tested_head", "test_source_path", "test_source_sha256",
}
LIMITATION = (
    "PASS labels and SHA-256 bindings are recorded claims until reviewers adjudicate them; "
    "they do not establish real 1C observations, G8 passage, C1 engineering completion, "
    "release readiness, or production authorization. For NOT_RUN and BLOCKED rows, "
    "tested_head identifies the candidate revision under consideration, not a test that ran."
)


def _split_row(line: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        return []
    return [cell.strip() for cell in line.split("|")[1:-1]]


def inspect_matrix(text: str) -> dict[str, Any]:
    findings: list[str] = []
    invariant_rows: list[tuple[str, str, str]] = []
    document_lines = text.splitlines()
    try:
        section_start = document_lines.index(MATRIX_HEADING) + 1
    except ValueError:
        section_start = len(document_lines)
        findings.append("authoritative invariant matrix section is missing")
    section: list[str] = []
    for line in document_lines[section_start:]:
        if line.startswith("## "):
            break
        section.append(line)

    for line_number, line in enumerate(section, start=section_start + 1):
        cells = _split_row(line)
        if not cells or cells[0] == "Inv" or not cells[0].startswith("I"):
            continue
        match = INVARIANT_ID.match(cells[0])
        if not match:
            findings.append(f"line {line_number}: malformed invariant identifier")
            continue
        if len(cells) != 5:
            findings.append(f"line {line_number}: {match.group(0)} must have five table columns")
            continue
        invariant_rows.append((match.group(0), cells[1], cells[2]))

    observed_ids = [row[0] for row in invariant_rows]
    duplicates = sorted({identifier for identifier in observed_ids if observed_ids.count(identifier) > 1})
    if duplicates:
        findings.append("duplicate invariant rows: " + ", ".join(duplicates))
    missing_ids = sorted(set(EXPECTED_INVARIANTS) - set(observed_ids), key=lambda value: int(value[1:]))
    unexpected_ids = sorted(set(observed_ids) - set(EXPECTED_INVARIANTS))
    if missing_ids:
        findings.append("missing invariant rows: " + ", ".join(missing_ids))
    if unexpected_ids:
        findings.append("unexpected invariant rows: " + ", ".join(unexpected_ids))

    scenario_map: dict[str, set[str]] = {}
    for identifier, scenario_cell, assertion_cell in invariant_rows:
        matches = [f"E{value}" for value in SCENARIO_ID.findall(scenario_cell)]
        if not matches:
            findings.append(f"{identifier}: no scenario IDs are mapped")
        if len(matches) != len(set(matches)):
            findings.append(f"{identifier}: duplicate scenario ID in mapping")
        invalid = sorted({value for value in matches
                          if not value[1:].isdigit() or int(value[1:]) not in ACTIVE_SCENARIOS})
        if invalid:
            findings.append(f"{identifier}: invalid or reserved scenario IDs: " + ", ".join(invalid))
        if not assertion_cell.strip():
            findings.append(f"{identifier}: enforcement-boundary assertion is empty")
        scenario_map[identifier] = set(matches)

    special_gate_mapping_found = any(
        all(marker in line for marker in GATE_MAPPING_MARKERS)
        for line in section
    )
    if not special_gate_mapping_found:
        findings.append("E46 and E47 must be explicitly mapped to gate/CT14 outcomes outside invariants")
    else:
        scenario_map["E46/E47"] = {"E46", "E47"}

    mapped_scenarios = set().union(*scenario_map.values()) if scenario_map else set()
    expected_scenarios = {f"E{value}" for value in ACTIVE_SCENARIOS}
    missing_scenarios = sorted(expected_scenarios - mapped_scenarios,
                               key=lambda value: int(value[1:]))
    if missing_scenarios:
        findings.append("active scenarios are unmapped: " + ", ".join(missing_scenarios))

    return {
        "structural_status": "COMPLETE" if not findings else "INCOMPLETE",
        "invariant_rows": len(invariant_rows),
        "invariant_ids": observed_ids,
        "scenario_map": {key: sorted(value, key=lambda item: int(item[1:]))
                         for key, value in scenario_map.items()},
        "active_scenarios_expected": len(ACTIVE_SCENARIOS),
        "active_scenarios_mapped": len(mapped_scenarios & expected_scenarios),
        "findings": findings,
    }


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], cwd=root, text=True, timeout=30,
    ).strip()


def _resolve_commit(root: Path, value: Any, field: str) -> str:
    if not isinstance(value, str) or not FULL_SHA.fullmatch(value):
        raise ValueError(f"{field} must be a full lowercase Git commit SHA")
    resolved = _git(root, "rev-parse", "--verify", f"{value}^{{commit}}")
    if resolved != value:
        raise ValueError(f"{field} does not identify the exact commit object")
    return value


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "--no-replace-objects", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root, capture_output=True, text=True, timeout=30, check=False,
    )
    return result.returncode == 0


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("evidence_path must be a non-empty repository-relative POSIX path")
    parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("evidence_path must not be absolute or traverse directories")
    return value


def _tree_entry(root: Path, commit: str, path: str) -> tuple[str, str] | None:
    raw = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-tree", "-r", "-z", commit, "--", path],
        cwd=root, timeout=30,
    )
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, listed_path = entry.split(b"\t", 1)
        if listed_path.decode("utf-8", errors="strict") != path:
            continue
        mode, kind, _object_id = metadata.decode("ascii").split(" ")
        return mode, kind
    return None


def _validate_result_artifact(root: Path, row: dict[str, Any], selected_head: str) -> None:
    evidence_commit = _resolve_commit(root, row["evidence_commit"], "evidence_commit")
    tested_head = row["tested_head"]
    if not _is_ancestor(root, tested_head, evidence_commit):
        raise ValueError("tested_head is not an ancestor of evidence_commit")
    if not _is_ancestor(root, evidence_commit, selected_head):
        raise ValueError("evidence_commit is not an ancestor of selected_head")
    path = _relative_path(row["evidence_path"])
    entry = _tree_entry(root, evidence_commit, path)
    if entry is None:
        raise ValueError("evidence_path is not a tracked blob at evidence_commit")
    mode, kind = entry
    if kind != "blob" or mode not in {"100644", "100755"}:
        raise ValueError("evidence_path must identify a tracked regular Git blob")
    content = subprocess.check_output(
        ["git", "--no-replace-objects", "show", f"{evidence_commit}:{path}"],
        cwd=root, timeout=30,
    )
    digest = hashlib.sha256(content).hexdigest()
    if digest != row["evidence_sha256"]:
        raise ValueError("evidence_sha256 does not match the exact Git blob")
    evidence = json.loads(content.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    if not isinstance(evidence, dict) or set(evidence) != RESULT_EVIDENCE_FIELDS:
        raise ValueError("evidence JSON fields do not match the strict PASS evidence schema")
    if type(evidence["schema_version"]) is not int or evidence["schema_version"] != 1:
        raise ValueError("unsupported PASS evidence schema_version")
    if evidence["result"] != "PASS":
        raise ValueError("evidence JSON must declare result=PASS")
    for field in ("invariant_id", "scenario_id", "assertion_id", "result", "tested_head"):
        if evidence[field] != row[field]:
            raise ValueError(f"evidence JSON {field} does not match its result row")
    test_source_path = _relative_path(evidence["test_source_path"])
    if not test_source_path.startswith("tests/"):
        raise ValueError("test_source_path must point inside tests/")
    test_source_entry = _tree_entry(root, tested_head, test_source_path)
    if test_source_entry is None:
        raise ValueError("test_source_path is not tracked at tested_head")
    test_mode, test_kind = test_source_entry
    if test_kind != "blob" or test_mode not in {"100644", "100755"}:
        raise ValueError("test_source_path must identify a tracked regular Git blob")
    test_source_bytes = subprocess.check_output(
        ["git", "--no-replace-objects", "show", f"{tested_head}:{test_source_path}"],
        cwd=root, timeout=30,
    )
    if row["assertion_id"].encode("utf-8") not in test_source_bytes:
        raise ValueError("assertion_id is not present in the exact tested-head test source")
    source_digest = evidence["test_source_sha256"]
    if not isinstance(source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ValueError("test_source_sha256 must be a lowercase SHA-256 digest")
    if hashlib.sha256(test_source_bytes).hexdigest() != source_digest:
        raise ValueError("test_source_sha256 does not match the exact tested-head Git blob")


def inspect_results(root: Path, source: Any, selected_head: str,
                    scenario_map: dict[str, list[str]]) -> dict[str, Any]:
    findings: list[str] = []
    if not isinstance(source, dict) or set(source) != RESULTS_FIELDS:
        return {"result_rows": 0, "claimed_pass_invariants": [],
                "missing_pass_invariants": list(EXPECTED_INVARIANTS),
                "findings": ["results input must contain only schema_version, selected_head, and results"]}
    if type(source["schema_version"]) is not int or source["schema_version"] != 1:
        findings.append("unsupported results schema_version")
    if source["selected_head"] != selected_head:
        findings.append("results selected_head does not match the selected S19 head")
    rows = source["results"]
    if not isinstance(rows, list):
        findings.append("results must be a list")
        rows = []

    unique_rows: set[tuple[str, str, str]] = set()
    passed_invariants: set[str] = set()
    for index, row in enumerate(rows, start=1):
        label = f"result row {index}"
        if not isinstance(row, dict) or set(row) != RESULT_FIELDS:
            findings.append(f"{label}: fields do not match the strict result-row schema")
            continue
        invariant = row["invariant_id"]
        scenario = row["scenario_id"]
        assertion = row["assertion_id"]
        status = row["result"]
        if not isinstance(invariant, str) or invariant not in EXPECTED_INVARIANTS:
            findings.append(f"{label}: unknown invariant_id")
            continue
        if not isinstance(scenario, str) or scenario not in scenario_map.get(invariant, []):
            findings.append(f"{label}: scenario_id is not mapped to invariant_id in the source matrix")
            continue
        if not isinstance(assertion, str) or not ASSERTION_ID.fullmatch(assertion):
            findings.append(f"{label}: assertion_id is malformed")
            continue
        key = (invariant, scenario, assertion)
        if key in unique_rows:
            findings.append(f"{label}: duplicate invariant/scenario/assertion row")
            continue
        unique_rows.add(key)
        if not isinstance(status, str) or status not in {"PASS", "NOT_RUN", "BLOCKED"}:
            findings.append(f"{label}: result must be PASS, NOT_RUN, or BLOCKED")
            continue
        try:
            tested_head = _resolve_commit(root, row["tested_head"], f"{label} tested_head")
            if not _is_ancestor(root, tested_head, selected_head):
                raise ValueError("tested_head is not an ancestor of selected_head")
            if status == "PASS":
                if row["reason"] is not None:
                    raise ValueError("PASS result must have reason=null")
                if not isinstance(row["evidence_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["evidence_sha256"]):
                    raise ValueError("PASS result requires a lowercase evidence_sha256")
                _validate_result_artifact(root, row, selected_head)
                passed_invariants.add(invariant)
            else:
                if not isinstance(row["reason"], str) or not row["reason"].strip() or len(row["reason"]) > 500:
                    raise ValueError(f"{status} result requires a reason")
                if any(row[field] is not None for field in
                       ("evidence_commit", "evidence_path", "evidence_sha256")):
                    raise ValueError(f"{status} result must not claim a result evidence artifact")
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError) as exc:
            findings.append(f"{label}: {exc}")

    missing_pass = sorted(set(EXPECTED_INVARIANTS) - passed_invariants,
                          key=lambda value: int(value[1:]))
    if missing_pass:
        findings.append("invariants without a verified-digest PASS claim: " + ", ".join(missing_pass))
    return {
        "result_rows": len(rows),
        "claimed_pass_invariants": sorted(passed_invariants, key=lambda value: int(value[1:])),
        "missing_pass_invariants": missing_pass,
        "findings": findings,
    }


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", required=True, help="full selected S19 commit SHA")
    parser.add_argument("--results", type=Path,
                        help="strict JSON boundary-results record; omitted means results are NOT_RUN")
    parser.add_argument("--document", type=Path, default=REPO_ROOT / MATRIX_PATH,
                        help="S11 invariant-to-scenario markdown source")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    selected_head = args.head
    top_findings: list[str] = []
    try:
        selected_head = _resolve_commit(root, args.head, "--head")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError) as exc:
        top_findings.append(str(exc))

    document_argument = args.document if args.document.is_absolute() else root / args.document
    try:
        document_relative = document_argument.resolve().relative_to(root).as_posix()
        document_relative = _relative_path(document_relative)
    except (OSError, ValueError) as exc:
        document_relative = ""
        top_findings.append(f"matrix document must be a repository-relative tracked file: {exc.__class__.__name__}")
    try:
        if not document_relative:
            raise ValueError("matrix document path is outside the repository")
        matrix_entry = _tree_entry(root, selected_head, document_relative)
        if matrix_entry is None:
            raise ValueError("matrix document is absent from selected_head")
        matrix_mode, matrix_kind = matrix_entry
        if matrix_kind != "blob" or matrix_mode not in {"100644", "100755"}:
            raise ValueError("matrix document must be a tracked regular Git blob")
        matrix_bytes = subprocess.check_output(
            ["git", "--no-replace-objects", "show", f"{selected_head}:{document_relative}"],
            cwd=root, timeout=30,
        )
        matrix = inspect_matrix(matrix_bytes.decode("utf-8"))
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError) as exc:
        matrix_bytes = b""
        matrix = {"structural_status": "INCOMPLETE", "invariant_rows": 0,
                  "invariant_ids": [], "scenario_map": {}, "active_scenarios_expected": len(ACTIVE_SCENARIOS),
                  "active_scenarios_mapped": 0,
                  "findings": [f"cannot read matrix document from selected_head: {exc.__class__.__name__}"]}

    if args.results is None:
        results = {"result_rows": 0, "claimed_pass_invariants": [],
                   "missing_pass_invariants": list(EXPECTED_INVARIANTS),
                   "findings": ["boundary-results input is absent; PASS evidence remains NOT_RUN"]}
    else:
        results_path = args.results if args.results.is_absolute() else root / args.results
        try:
            results_source = json.loads(
                results_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
            results = inspect_results(root, results_source, selected_head,
                                      matrix.get("scenario_map", {}))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            results = {"result_rows": 0, "claimed_pass_invariants": [],
                       "missing_pass_invariants": list(EXPECTED_INVARIANTS),
                       "findings": [f"cannot read valid boundary-results JSON: {exc.__class__.__name__}"]}

    all_findings = top_findings + matrix["findings"] + results["findings"]
    complete = matrix["structural_status"] == "COMPLETE" and not results["missing_pass_invariants"] and not all_findings
    output = {
        "schema_version": 1,
        "assessment": "EXACT_HEAD_EVIDENCE_CLAIMS_UNADJUDICATED",
        "selected_head": selected_head,
        "matrix_document": document_relative or None,
        "matrix_sha256": hashlib.sha256(matrix_bytes).hexdigest() if matrix_bytes else None,
        "structural_status": matrix["structural_status"],
        "invariant_rows": matrix["invariant_rows"],
        "active_scenarios_expected": matrix["active_scenarios_expected"],
        "active_scenarios_mapped": matrix["active_scenarios_mapped"],
        "result_rows": results["result_rows"],
        "claimed_pass_invariants": results["claimed_pass_invariants"],
        "missing_pass_invariants": results["missing_pass_invariants"],
        "completeness_status": "RECORDED_PASS_CLAIMS_COMPLETE_UNADJUDICATED" if complete else "INCOMPLETE",
        "runtime_boundary_results": "RECORDED_UNADJUDICATED" if results["claimed_pass_invariants"] else "NOT_RUN",
        "gate_status": "UNCHANGED",
        "production_authorization": "NONE",
        "limitations": [LIMITATION],
        "findings": all_findings,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
