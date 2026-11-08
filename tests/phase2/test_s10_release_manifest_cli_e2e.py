from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CASE_IDS = [
    "R2-TC-124",
    "R2-TC-125",
    "R2-TC-126",
    "R2-TC-142",
    "R2-TC-143",
    "R2-TC-144",
]
R2_042_TASK_CODE_FILES = (
    "src/business_ai_gateway/phase2/capture_loop.py",
    "src/business_ai_gateway/phase2/capture_runtime.py",
    "src/business_ai_gateway/phase2/fakes.py",
    "src/business_ai_gateway/phase2/ports.py",
    "src/business_ai_gateway/phase2/scheduler.py",
    "src/business_ai_gateway/runtime.py",
)
PR_NUMBER = 53


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout


def _write_gh_shim(shim_dir: Path) -> None:
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        "import os\n"
        "import subprocess\n"
        "_check_output = subprocess.check_output\n"
        "def _shim(args, *positional, **keywords):\n"
        "    if isinstance(args, (list, tuple)) and list(args[:3]) == ['gh', 'pr', 'view']:\n"
        "        result = os.environ['S10_TEST_GH_RESPONSE']\n"
        "        return result if keywords.get('text') else result.encode()\n"
        "    return _check_output(args, *positional, **keywords)\n"
        "subprocess.check_output = _shim\n",
        encoding="utf-8",
    )


def _junit(source_head: str, cases: list[tuple[str, str, str]]) -> str:
    suite = ET.Element("testsuite", tests=str(len(cases)), failures="0", errors="0", skipped="0")
    for module_stem, case_id, outcome in cases:
        testcase = ET.SubElement(
            suite,
            "testcase",
            classname=f"{module_stem}.synthetic",
            name=f"{module_stem}_{case_id}_bounded_contract",
        )
        properties = ET.SubElement(testcase, "properties")
        ET.SubElement(properties, "property", name="candidate_head", value=source_head)
        if outcome == "NOT_RUN":
            ET.SubElement(testcase, "skipped", message="not executed")
        elif outcome == "FAIL":
            ET.SubElement(testcase, "failure", message="synthetic failure")
    return ET.tostring(suite, encoding="unicode")


def _prepare_repo(tmp_path: Path, *, mutate_test_after_source: bool = False,
                  tc143_outcome: str = "PASS", tc144_outcome: str | None = None) -> dict[str, Path | str]:
    repo = tmp_path / "candidate"
    (repo / "scripts").mkdir(parents=True)
    for package in (repo / "src/business_ai_gateway", repo / "src/business_ai_gateway/phase2"):
        package.mkdir(parents=True, exist_ok=True)
    (repo / "tests").mkdir()
    shutil.copy2(REPO / "scripts/assemble_s10_release_manifest.py", repo / "scripts")
    shutil.copy2(REPO / "src/business_ai_gateway/__init__.py", repo / "src/business_ai_gateway")
    shutil.copy2(REPO / "src/business_ai_gateway/phase2/__init__.py", repo / "src/business_ai_gateway/phase2")
    shutil.copy2(REPO / "src/business_ai_gateway/phase2/release_manifest.py", repo / "src/business_ai_gateway/phase2")
    for relative_path in R2_042_TASK_CODE_FILES:
        destination = repo / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative_path, destination)
    capture_path = repo / "tests/test_capture.py"
    manifest_path = repo / "tests/test_manifest.py"
    capture_path.write_text("# candidate-source capture tests\n", encoding="utf-8")
    manifest_path.write_text("# candidate-source manifest tests\n", encoding="utf-8")

    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "S10 CLI E2E Fixture"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "s10-e2e@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "synthetic S10 source candidate"], cwd=repo, check=True,
                   capture_output=True, text=True)
    source_head = _git(repo, "rev-parse", "HEAD")
    source_test_hashes = {
        "tests/test_capture.py": _sha256(_git_bytes(repo, "show", f"{source_head}:tests/test_capture.py")),
        "tests/test_manifest.py": _sha256(_git_bytes(repo, "show", f"{source_head}:tests/test_manifest.py")),
    }
    source_task_hashes = {
        path: _sha256(_git_bytes(repo, "show", f"{source_head}:{path}"))
        for path in R2_042_TASK_CODE_FILES
    }

    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], cwd=tmp_path, check=True,
                   capture_output=True, text=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True,
                   capture_output=True, text=True)

    junit_dir = repo / "reports/evidence/s10/test-runs"
    junit_dir.mkdir(parents=True, exist_ok=True)
    capture_junit_path = junit_dir / "capture-run.xml"
    capture_junit_path.write_text(_junit(source_head, [
        ("test_capture", case_id, "PASS") for case_id in CASE_IDS[:3]
    ]), encoding="utf-8")
    manifest_cases = [
        ("test_manifest", "R2-TC-142", "PASS"),
        ("test_manifest", "R2-TC-143", tc143_outcome),
    ]
    if tc144_outcome is not None:
        manifest_cases.append(("test_manifest", "R2-TC-144", tc144_outcome))
    manifest_junit_path = junit_dir / "manifest-run.xml"
    manifest_junit_path.write_text(_junit(source_head, manifest_cases), encoding="utf-8")

    # Simulate the later evidence-only PR commit. The negative fixture changes a hashed
    # source file to prove the assembler refuses evidence from a stale tested snapshot.
    if mutate_test_after_source:
        capture_path.write_text("# listed test source changed after tested source head\n", encoding="utf-8")
    (repo / "reports/s10-release-evidence-note.md").write_text(
        "Synthetic documentation/evidence-only PR update.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "synthetic evidence-only follow-up"], cwd=repo, check=True,
                   capture_output=True, text=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True,
                   capture_output=True, text=True)
    pr_head = _git(repo, "rev-parse", "HEAD")
    shim_dir = tmp_path / "gh-shim"
    _write_gh_shim(shim_dir)
    return {
        "repo": repo,
        "source_head": source_head,
        "pr_head": pr_head,
        "capture_hash": source_test_hashes["tests/test_capture.py"],
        "manifest_hash": source_test_hashes["tests/test_manifest.py"],
        "task_code_hashes": source_task_hashes,
        "capture_junit_path": "reports/evidence/s10/test-runs/capture-run.xml",
        "capture_junit_hash": _sha256(capture_junit_path.read_bytes()),
        "manifest_junit_path": "reports/evidence/s10/test-runs/manifest-run.xml",
        "manifest_junit_hash": _sha256(manifest_junit_path.read_bytes()),
        "shim_dir": shim_dir,
    }


def _run_record(run_id: str, owner: str, junit_path: str, junit_sha256: str,
                test_files: dict[str, str]) -> dict:
    return {
        "run_id": run_id,
        "owner": owner,
        "command": "uv run --locked --offline --extra dev python -m pytest -q <focused-suite>",
        "junit_path": junit_path,
        "junit_sha256": junit_sha256,
        "test_files": test_files,
    }


def _input(fixture: dict[str, Path | str], *, tc144_outcome: str | None = None) -> dict:
    source_head = str(fixture["source_head"])
    capture_run = _run_record(
        "capture-run",
        "e2e-runner",
        str(fixture["capture_junit_path"]),
        str(fixture["capture_junit_hash"]),
        {"tests/test_capture.py": str(fixture["capture_hash"])},
    )
    manifest_run = _run_record(
        "manifest-run",
        "functional-test-reviewer",
        str(fixture["manifest_junit_path"]),
        str(fixture["manifest_junit_hash"]),
        {"tests/test_manifest.py": str(fixture["manifest_hash"])},
    )
    cases = [
        {"id": "R2-TC-124", "status": "PASS", "evidence_run_ids": ["capture-run"], "note": "exact scope binding"},
        {"id": "R2-TC-125", "status": "PASS", "evidence_run_ids": ["capture-run"], "note": "dev/test is not production approval"},
        {"id": "R2-TC-126", "status": "PASS", "evidence_run_ids": ["capture-run"], "note": "scope-owned cancellation"},
        {"id": "R2-TC-142", "status": "PASS", "evidence_run_ids": ["manifest-run"], "note": "complete manifest IDs and results"},
        {"id": "R2-TC-143", "status": "PASS", "evidence_run_ids": ["manifest-run"], "note": "NOT_RUN is not release PASS"},
        {"id": "R2-TC-144", "status": tc144_outcome or "NOT_RUN",
         "evidence_run_ids": ["manifest-run"] if tc144_outcome is not None else [],
         "note": "three distinct UAT lanes" if tc144_outcome == "PASS" else "UAT remains not run"},
    ]
    uat = {role: {"status": "NOT_RUN", "evidence_path": None, "evidence_sha256": None}
           for role in ("user", "admin", "production")}
    return {
        "source_head": source_head,
        "pr_number": PR_NUMBER,
        "test_runs": [capture_run, manifest_run],
        "cases": cases,
        "uat": uat,
    }


def _run_cli(fixture: dict[str, Path | str], source: dict, *, gh_state: str = "OPEN",
             gh_head: str | None = None,
             output_relpath: str = "reports/S10_RELEASE_EVIDENCE_MANIFEST.json",
             input_relpath: str | None = None) -> subprocess.CompletedProcess[str]:
    repo = Path(str(fixture["repo"]))
    input_path = repo / input_relpath if input_relpath else repo.parent / "S10_RELEASE_EVIDENCE_MANIFEST.input.json"
    output_path = repo / output_relpath
    input_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(source), encoding="utf-8")
    env = os.environ.copy()
    shim_dir = str(fixture["shim_dir"])
    env["PYTHONPATH"] = shim_dir
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["S10_TEST_GH_RESPONSE"] = json.dumps({
        "url": f"https://github.com/xLZDx/ERP_MCP/pull/{PR_NUMBER}",
        "state": gh_state,
        "headRefOid": gh_head or str(fixture["pr_head"]),
    })
    env["PATH"] = shim_dir + os.pathsep + env["PATH"]
    return subprocess.run(
        [sys.executable, str(repo / "scripts/assemble_s10_release_manifest.py"),
         "--input", str(input_path), "--output", str(output_path)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_assembles_manifest_with_source_head_remote_head_and_open_pr_bound(tmp_path: Path) -> None:
    fixture = _prepare_repo(tmp_path, tc144_outcome="NOT_RUN")
    output = Path(str(fixture["repo"])) / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"previous complete manifest\n")
    result = _run_cli(fixture, _input(fixture, tc144_outcome="NOT_RUN"))

    assert result.returncode == 0, result.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    candidate = manifest["candidate"]
    assert candidate["source_head"] == fixture["source_head"]
    assert candidate["remote_branch_head"] == fixture["pr_head"]
    assert candidate["pull_request"] == {
        "number": PR_NUMBER,
        "url": f"https://github.com/xLZDx/ERP_MCP/pull/{PR_NUMBER}",
        "head_sha": fixture["pr_head"],
    }
    assert candidate["source_head"] != candidate["remote_branch_head"]
    changed_paths = _git(Path(str(fixture["repo"])), "diff", "--name-only",
                         f"{fixture['source_head']}..{fixture['pr_head']}").splitlines()
    assert changed_paths and all(path.startswith("reports/") for path in changed_paths)
    repo = Path(str(fixture["repo"]))
    for path, expected_hash in dict(fixture["task_code_hashes"]).items():
        assert _sha256(_git_bytes(repo, "show", f"{fixture['source_head']}:{path}")) == expected_hash
        assert _sha256(_git_bytes(repo, "show", f"{fixture['pr_head']}:{path}")) == expected_hash
        assert _sha256(_git_bytes(repo, "show", f"HEAD:{path}")) == expected_hash
    assert manifest["case_ids"] == CASE_IDS
    assert [case["id"] for case in manifest["cases"]] == CASE_IDS
    assert manifest["cases"][-1]["status"] == "NOT_RUN"
    assert manifest["cases"][-1]["evidence_run_ids"] == ["manifest-run"]
    assert set(manifest["uat"]) == {"user", "admin", "production"}
    assert all(record["status"] == "NOT_RUN" and record["evidence_path"] is None
               and record["evidence_sha256"] is None for record in manifest["uat"].values())
    assert manifest["release_decision"] == "NO-GO"
    assert manifest["native_evidence_level_inferred"] is False
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))


def test_cli_rejects_output_outside_fixed_manifest_path_without_touching_source(tmp_path: Path) -> None:
    fixture = _prepare_repo(tmp_path)
    repo = Path(str(fixture["repo"]))
    protected = repo / "src/business_ai_gateway/runtime.py"
    before = protected.read_bytes()
    result = _run_cli(
        fixture,
        _input(fixture),
        output_relpath="src/business_ai_gateway/runtime.py",
    )

    assert result.returncode != 0
    assert "output path must be reports/S10_RELEASE_EVIDENCE_MANIFEST.json" in result.stderr
    assert protected.read_bytes() == before
    assert not (repo / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json").exists()


def test_cli_rejects_input_output_collision_without_overwriting_input(tmp_path: Path) -> None:
    fixture = _prepare_repo(tmp_path)
    repo = Path(str(fixture["repo"]))
    manifest_path = repo / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json"
    expected_input = json.dumps(_input(fixture)).encode("utf-8")
    result = _run_cli(
        fixture,
        _input(fixture),
        input_relpath="reports/S10_RELEASE_EVIDENCE_MANIFEST.json",
    )

    assert result.returncode != 0
    assert "input and output paths must differ" in result.stderr
    assert manifest_path.read_bytes() == expected_input
    assert not list(manifest_path.parent.glob(f".{manifest_path.name}.*.tmp"))


def test_tc144_pass_proves_distinct_lanes_without_inferencing_that_uat_ran(tmp_path: Path) -> None:
    fixture = _prepare_repo(tmp_path, tc144_outcome="PASS")
    result = _run_cli(fixture, _input(fixture, tc144_outcome="PASS"))

    assert result.returncode == 0, result.stderr
    manifest = json.loads((Path(str(fixture["repo"])) / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json").read_text())
    assert manifest["cases"][-1]["status"] == "PASS"
    assert set(manifest["uat"]) == {"user", "admin", "production"}
    assert all(manifest["uat"][role] == {
        "status": "NOT_RUN", "evidence_path": None, "evidence_sha256": None,
    } for role in ("user", "admin", "production"))
    assert manifest["release_decision"] == "NO-GO"


def test_cli_rejects_not_run_case_or_uat_with_artifact_claims(tmp_path: Path) -> None:
    fixture = _prepare_repo(tmp_path, tc144_outcome="PASS")
    source = _input(fixture, tc144_outcome="PASS")
    source["cases"][-1]["status"] = "NOT_RUN"
    result = _run_cli(fixture, source)
    assert result.returncode != 0
    assert "case result does not match the JUnit case outcome" in result.stderr
    assert not (Path(str(fixture["repo"])) / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json").exists()

    source = _input(fixture)
    source["uat"]["user"] = {
        "status": "NOT_RUN", "evidence_path": "reports/evidence/s10/uat/user.json",
        "evidence_sha256": "a" * 64,
    }
    result = _run_cli(fixture, source)
    assert result.returncode != 0
    assert "this bounded package cannot verify or accept UAT evidence" in result.stderr
    assert not (Path(str(fixture["repo"])) / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json").exists()

    source = _input(fixture, tc144_outcome="PASS")
    source["uat"]["user"] = {
        "status": "PASS", "evidence_path": None, "evidence_sha256": None,
    }
    result = _run_cli(fixture, source)
    assert result.returncode != 0
    assert "invalid UAT record" in result.stderr
    assert not (Path(str(fixture["repo"])) / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json").exists()


def test_cli_derives_case_status_from_junit_and_rejects_closed_or_stale_pr(tmp_path: Path) -> None:
    fixture = _prepare_repo(tmp_path, tc143_outcome="NOT_RUN")
    source = _input(fixture)
    result = _run_cli(fixture, source)
    assert result.returncode != 0
    assert "JUnit case outcome" in result.stderr or "case result" in result.stderr

    result = _run_cli(fixture, _input(fixture), gh_state="CLOSED")
    assert result.returncode != 0
    assert "pull request is not open" in result.stderr
    result = _run_cli(fixture, _input(fixture), gh_head="0" * 40)
    assert result.returncode != 0
    assert "pull request head does not match" in result.stderr


def test_cli_rejects_later_pr_commit_that_changes_a_listed_test_source(tmp_path: Path) -> None:
    fixture = _prepare_repo(tmp_path, mutate_test_after_source=True, tc144_outcome="NOT_RUN")
    output = Path(str(fixture["repo"])) / "reports/S10_RELEASE_EVIDENCE_MANIFEST.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    previous_output = b"preserve the prior manifest on validation failure\n"
    output.write_bytes(previous_output)
    result = _run_cli(fixture, _input(fixture))

    assert result.returncode != 0
    assert "test source changed after the tested source HEAD" in result.stderr
    assert output.read_bytes() == previous_output
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))

