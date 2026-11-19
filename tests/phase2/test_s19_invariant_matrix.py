from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_s19_invariant_matrix.py"
SPEC = importlib.util.spec_from_file_location("s19_invariant_checker", CHECKER_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _run_git(root: Path, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, input=input_text, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def _matrix_text(*, row_overrides: dict[int, tuple[str, str]] | None = None,
                 include_gate_mapping: bool = True, trailing_sections: str = "") -> str:
    row_overrides = row_overrides or {}
    regular_scenarios = [number for number in range(1, 46) if number != 8]
    lines = [
        "# Test design fixture",
        checker.MATRIX_HEADING,
        "| Inv | Scenarios | Failing assertion | Negative control | Flags |",
        "| --- | --- | --- | --- | --- |",
    ]
    for number in range(1, 16):
        mapped = regular_scenarios[(number - 1) * 3:number * 3]
        scenarios = ", ".join(f"E{value}" for value in mapped)
        assertion = f"assertion-{number:02d} fails at the enforcement boundary"
        scenarios, assertion = row_overrides.get(number, (scenarios, assertion))
        lines.append(
            f"| I{number} | {scenarios} | {assertion} | synthetic fixture control | fixture only |"
        )
    if include_gate_mapping:
        lines.append("E46 gate validator and E47 CT14 record map to gates and CT14, not to invariants.")
    if trailing_sections:
        lines.extend(["## B. Later section", trailing_sections])
    return "\n".join(lines) + "\n"


def _git_commit(root: Path, message: str) -> str:
    _run_git(root, "add", "--all")
    _run_git(root, "commit", "-m", message)
    return _run_git(root, "rev-parse", "HEAD")


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fixture(tmp_path: Path, *, dirty_matrix: bool = False) -> dict[str, Any]:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    matrix_bytes = _matrix_text().encode("utf-8")
    matrix_path = root / "docs" / "matrix.md"
    matrix_path.parent.mkdir(parents=True)
    matrix_path.write_bytes(matrix_bytes)
    test_source = root / "tests" / "boundary_contract.py"
    test_source.parent.mkdir(parents=True)
    assertions = "\n".join(f"# assertion-{i:02d}" for i in range(1, 16)) + "\n"
    test_source.write_text(assertions, encoding="utf-8")

    _run_git(root, "init", "--initial-branch=main")
    _run_git(root, "config", "user.name", "S19 invariant matrix fixture")
    _run_git(root, "config", "user.email", "s19-invariant@example.invalid")
    tested_head = _git_commit(root, "synthetic tested source head")
    tested_source_bytes = subprocess.check_output(
        ["git", "--no-replace-objects", "show", f"{tested_head}:tests/boundary_contract.py"],
        cwd=root,
    )
    source_digest = hashlib.sha256(tested_source_bytes).hexdigest()

    results: list[dict[str, Any]] = []
    evidence_paths: dict[str, str] = {}
    for number in range(1, 16):
        invariant_id = f"I{number}"
        scenario_ids = [number for number in range(1, 46) if number != 8]
        scenario_id = f"E{scenario_ids[(number - 1) * 3]}"
        assertion_id = f"assertion-{number:02d}"
        evidence_path = f"evidence/{invariant_id}.json"
        evidence = {
            "schema_version": 1,
            "invariant_id": invariant_id,
            "scenario_id": scenario_id,
            "assertion_id": assertion_id,
            "result": "PASS",
            "tested_head": tested_head,
            "test_source_path": "tests/boundary_contract.py",
            "test_source_sha256": source_digest,
        }
        target = root / evidence_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_json_bytes(evidence))
        evidence_paths[invariant_id] = evidence_path
        results.append({
            "invariant_id": invariant_id,
            "scenario_id": scenario_id,
            "assertion_id": assertion_id,
            "result": "PASS",
            "tested_head": tested_head,
            "evidence_commit": None,
            "evidence_path": evidence_path,
            "evidence_sha256": None,
            "reason": None,
        })

    evidence_commit = _git_commit(root, "synthetic exact-head evidence")
    for row in results:
        row["evidence_commit"] = evidence_commit
        row["evidence_sha256"] = hashlib.sha256(
            (root / row["evidence_path"]).read_bytes()
        ).hexdigest()
    selected_head = evidence_commit
    results_input = {
        "schema_version": 1,
        "selected_head": selected_head,
        "results": results,
    }
    results_path = root / "results.json"
    results_path.write_bytes(_json_bytes(results_input))
    if dirty_matrix:
        matrix_path.write_text("worktree-only corrupt matrix\n", encoding="utf-8")
    return {
        "root": root,
        "tested_head": tested_head,
        "evidence_commit": evidence_commit,
        "selected_head": selected_head,
        "matrix_bytes": matrix_bytes,
        "test_source_digest": source_digest,
        "results": results_input,
        "results_path": results_path,
        "evidence_paths": evidence_paths,
    }


def _write_results(fixture: dict[str, Any], results: dict[str, Any], *, raw: str | None = None) -> None:
    path = fixture["results_path"]
    path.write_text(raw if raw is not None else json.dumps(results), encoding="utf-8")


def _run_checker(fixture: dict[str, Any], *, head: str | None = None,
                 results: str | None = "results.json", document: str = "docs/matrix.md"
                 ) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable, str(CHECKER_PATH), "--root", str(fixture["root"]),
        "--head", head or fixture["selected_head"], "--document", document,
    ]
    if results is not None:
        args.extend(["--results", results])
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)


def _output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout)


def _make_unrelated_commit(root: Path) -> str:
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=root,
        input="unrelated history\n", check=True, capture_output=True, text=True,
    ).stdout.strip()
    tree = _run_git(root, "mktree", input_text=f"100644 blob {blob}\tunrelated.txt\n")
    return _run_git(root, "commit-tree", tree, "-m", "unrelated history")


def test_matrix_requires_exact_i1_to_i15_and_maps_all_46_scenarios_with_special_rows() -> None:
    result = checker.inspect_matrix(_matrix_text())

    assert result["structural_status"] == "COMPLETE"
    assert result["invariant_ids"] == [f"I{i}" for i in range(1, 16)]
    assert result["active_scenarios_expected"] == 46
    assert result["active_scenarios_mapped"] == 46
    assert result["scenario_map"]["E46/E47"] == ["E46", "E47"]
    assert not result["findings"]


@pytest.mark.parametrize("mutation, finding", [
    ("missing", "missing invariant rows: I15"),
    ("duplicate", "duplicate invariant rows: I1"),
    ("malformed", "malformed invariant identifier"),
])
def test_matrix_rejects_missing_duplicate_and_malformed_invariant_rows(mutation: str, finding: str) -> None:
    text = _matrix_text()
    lines = text.splitlines()
    if mutation == "missing":
        lines = [line for line in lines if not line.startswith("| I15 |")]
    elif mutation == "duplicate":
        row = next(line for line in lines if line.startswith("| I1 |"))
        lines.append(row)
    else:
        lines.append("| I-bad | malformed id | E1 | assertion | note |")

    result = checker.inspect_matrix("\n".join(lines) + "\n")

    assert result["structural_status"] == "INCOMPLETE"
    assert any(finding in value for value in result["findings"])


@pytest.mark.parametrize("mutation, finding", [
    (("E8", "assertion"), "invalid or reserved scenario IDs: E8"),
    (("E48", "assertion"), "invalid or reserved scenario IDs: E48"),
    (("", "assertion"), "I1: no scenario IDs are mapped"),
    (("E1", ""), "I1: enforcement-boundary assertion is empty"),
])
def test_matrix_rejects_missing_assertions_and_reserved_or_unknown_scenarios(
    mutation: tuple[str, str], finding: str,
) -> None:
    result = checker.inspect_matrix(_matrix_text(row_overrides={1: mutation}))

    assert result["structural_status"] == "INCOMPLETE"
    assert any(finding in value for value in result["findings"])


def test_matrix_requires_e46_e47_gate_and_ct14_mapping_outside_invariants() -> None:
    result = checker.inspect_matrix(_matrix_text(include_gate_mapping=False))

    assert result["structural_status"] == "INCOMPLETE"
    assert "E46 and E47 must be explicitly mapped to gate/CT14 outcomes outside invariants" in result["findings"]
    assert result["active_scenarios_mapped"] == 44


def test_matrix_parser_stops_at_next_section_and_ignores_later_fake_rows() -> None:
    trailing = "| I1 | duplicate outside section | E8 | | |\n| I99 | fake | E999 | assertion | |"
    result = checker.inspect_matrix(_matrix_text(trailing_sections=trailing))

    assert result["structural_status"] == "COMPLETE"
    assert result["invariant_rows"] == 15
    assert result["active_scenarios_mapped"] == 46


def test_cli_reads_matrix_from_selected_head_and_without_results_stays_not_run(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, dirty_matrix=True)
    result = _run_checker(fixture, results=None)
    output = _output(result)

    assert result.returncode == 1
    assert output["matrix_sha256"] == hashlib.sha256(fixture["matrix_bytes"]).hexdigest()
    assert output["structural_status"] == "COMPLETE"
    assert output["completeness_status"] == "INCOMPLETE"
    assert output["runtime_boundary_results"] == "NOT_RUN"
    assert output["missing_pass_invariants"] == [f"I{i}" for i in range(1, 16)]
    assert output["gate_status"] == "UNCHANGED"
    assert output["production_authorization"] == "NONE"


def test_cli_accepts_fifteen_exact_head_pass_claims_as_unadjudicated_only(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 0, result.stderr
    assert output["assessment"] == "I1_I15_MATRIX_CLAIM_CHECK_UNADJUDICATED"
    assert output["claim_scope"] == "I1-I15 only"
    assert output["structural_status"] == "COMPLETE"
    assert output["completeness_status"] == "I1_I15_PASS_CLAIMS_COMPLETE_UNADJUDICATED"
    assert output["claimed_pass_invariants"] == [f"I{i}" for i in range(1, 16)]
    assert output["missing_pass_invariants"] == []
    assert output["runtime_boundary_results"] == "I1_I15_PASS_CLAIMS_RECORDED_UNADJUDICATED"
    assert output["active_scenarios_expected"] == 46
    assert output["active_scenarios_mapped"] == 46
    assert output["scenario_lane_coverage"] == "NOT_ADJUDICATED"
    assert output["g8_evidence"] is False
    assert output["gate_status"] == "UNCHANGED"
    assert output["production_authorization"] == "NONE"
    assert "do not establish real 1C observations" in output["limitations"][0]


def test_cli_requires_pass_for_every_invariant(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["results"]["results"] = fixture["results"]["results"][:-1]
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 1
    assert output["completeness_status"] == "INCOMPLETE"
    assert output["missing_pass_invariants"] == ["I15"]


@pytest.mark.parametrize("field", ["selected_head", "tested_head", "evidence_commit"])
def test_cli_rejects_wrong_or_non_ancestor_commit_binding(tmp_path: Path, field: str) -> None:
    fixture = _fixture(tmp_path)
    unrelated = _make_unrelated_commit(fixture["root"])
    if field == "selected_head":
        fixture["results"]["selected_head"] = fixture["tested_head"]
    else:
        row = fixture["results"]["results"][0]
        row[field] = unrelated
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 1
    assert output["completeness_status"] == "INCOMPLETE"
    assert output["findings"]


@pytest.mark.parametrize("bad_path", ["../outside.json", "/outside.json", "evidence\\I1.json", "evidence/missing.json"])
def test_cli_rejects_missing_or_out_of_root_evidence_paths(tmp_path: Path, bad_path: str) -> None:
    fixture = _fixture(tmp_path)
    fixture["results"]["results"][0]["evidence_path"] = bad_path
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 1
    assert output["completeness_status"] == "INCOMPLETE"
    assert output["findings"]


def test_cli_rejects_symlink_evidence_blob(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    root = fixture["root"]
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=root, input="target\n",
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    _run_git(root, "update-index", "--add", "--cacheinfo",
             f"120000,{blob},evidence/link.json")
    tree = _run_git(root, "write-tree")
    evidence_commit = _run_git(root, "commit-tree", tree, "-p", fixture["selected_head"],
                               "-m", "synthetic symlink evidence")
    row = fixture["results"]["results"][0]
    row["evidence_commit"] = evidence_commit
    row["evidence_path"] = "evidence/link.json"
    row["evidence_sha256"] = hashlib.sha256(b"target\n").hexdigest()
    fixture["results"]["selected_head"] = evidence_commit
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture, head=evidence_commit)
    output = _output(result)

    assert result.returncode == 1
    assert any("tracked regular Git blob" in finding for finding in output["findings"])


def test_cli_rejects_evidence_blob_sha_mismatch_without_crashing(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["results"]["results"][0]["evidence_sha256"] = "0" * 64
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 1
    assert any("evidence_sha256 does not match" in finding for finding in output["findings"])


@pytest.mark.parametrize("mutation, finding", [
    ("evidence-field", "evidence JSON tested_head does not match its result row"),
    ("evidence-result", "evidence JSON must declare result=PASS"),
    ("duplicate-evidence-key", "duplicate JSON object key"),
    ("missing-test-source", "test_source_path is not tracked at tested_head"),
    ("test-source-digest", "test_source_sha256 does not match"),
    ("assertion-absent", "assertion_id is not present"),
])
def test_cli_rejects_mismatched_evidence_json_and_test_source(
    tmp_path: Path, mutation: str, finding: str,
) -> None:
    fixture = _fixture(tmp_path)
    root = fixture["root"]
    row = fixture["results"]["results"][0]
    evidence_file = root / row["evidence_path"]
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    if mutation == "evidence-field":
        evidence["tested_head"] = fixture["evidence_commit"]
    elif mutation == "evidence-result":
        evidence["result"] = "NOT_RUN"
    elif mutation == "duplicate-evidence-key":
        evidence_file.write_text(
            '{"schema_version":1,"schema_version":1,'
            + json.dumps({key: value for key, value in evidence.items()
                          if key != "schema_version"}, sort_keys=True)[1:],
            encoding="utf-8",
        )
    elif mutation == "missing-test-source":
        evidence["test_source_path"] = "tests/not-present.py"
    elif mutation == "test-source-digest":
        evidence["test_source_sha256"] = "0" * 64
    elif mutation == "assertion-absent":
        evidence["assertion_id"] = "no-such-assertion"
        row["assertion_id"] = "no-such-assertion"
    if mutation != "duplicate-evidence-key":
        evidence_file.write_bytes(_json_bytes(evidence))
    evidence_commit = _git_commit(root, f"mutate {mutation} evidence")
    row["evidence_commit"] = evidence_commit
    row["evidence_sha256"] = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
    fixture["results"]["selected_head"] = evidence_commit
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture, head=evidence_commit)
    output = _output(result)

    assert result.returncode == 1
    assert any(finding in value for value in output["findings"])


def test_cli_rejects_duplicate_json_keys_and_duplicate_result_rows(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    duplicate_key = (
        '{"schema_version":1,"schema_version":1,"selected_head":"'
        + fixture["selected_head"] + '","results":[]}'
    )
    _write_results(fixture, fixture["results"], raw=duplicate_key)
    duplicate_key_result = _run_checker(fixture)
    duplicate_key_output = _output(duplicate_key_result)
    assert duplicate_key_result.returncode == 1
    assert duplicate_key_output["completeness_status"] == "INCOMPLETE"
    assert any("cannot read valid boundary-results JSON" in finding
               for finding in duplicate_key_output["findings"])

    fixture = _fixture(tmp_path / "duplicate-row")
    duplicate_rows = fixture["results"]["results"]
    duplicate_rows.append(dict(duplicate_rows[0]))
    _write_results(fixture, fixture["results"])
    duplicate_row_result = _run_checker(fixture)
    duplicate_row_output = _output(duplicate_row_result)
    assert duplicate_row_result.returncode == 1
    assert any("duplicate invariant/scenario/assertion row" in finding
               for finding in duplicate_row_output["findings"])


@pytest.mark.parametrize("results_value", [None, {}, "not-a-list"])
def test_cli_malformed_result_list_is_incomplete_json_not_a_crash(
    tmp_path: Path, results_value: Any,
) -> None:
    fixture = _fixture(tmp_path)
    fixture["results"]["results"] = results_value
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 1
    assert output["completeness_status"] == "INCOMPLETE"
    assert output["missing_pass_invariants"] == [f"I{i}" for i in range(1, 16)]


@pytest.mark.parametrize("bad_row", [
    {"result": "FAIL"},
    {"result": "NOT_RUN", "reason": None},
    {"result": "BLOCKED", "reason": "dependency unavailable", "evidence_path": "evidence/I1.json"},
])
def test_non_pass_results_require_reason_and_must_not_claim_evidence(
    tmp_path: Path, bad_row: dict[str, Any],
) -> None:
    fixture = _fixture(tmp_path)
    row = fixture["results"]["results"][0]
    row["result"] = bad_row["result"]
    if "reason" in bad_row:
        row["reason"] = bad_row["reason"]
    if "evidence_path" in bad_row:
        row["evidence_path"] = bad_row["evidence_path"]
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 1
    assert output["completeness_status"] == "INCOMPLETE"
    assert output["findings"]


def test_not_run_with_reason_is_preserved_without_any_evidence_claim(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    for row in fixture["results"]["results"]:
        row.update({
            "result": "NOT_RUN",
            "reason": "Boundary scenario was not executed.",
            "evidence_commit": None,
            "evidence_path": None,
            "evidence_sha256": None,
        })
    _write_results(fixture, fixture["results"])

    result = _run_checker(fixture)
    output = _output(result)

    assert result.returncode == 1
    assert output["completeness_status"] == "INCOMPLETE"
    assert output["runtime_boundary_results"] == "NOT_RUN"
    assert output["missing_pass_invariants"] == [f"I{i}" for i in range(1, 16)]

