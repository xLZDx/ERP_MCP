"""Assemble bounded S10 release evidence without promoting NOT_RUN to release PASS."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

CASE_IDS = (
    "R2-TC-124",
    "R2-TC-125",
    "R2-TC-126",
    "R2-TC-142",
    "R2-TC-143",
    "R2-TC-144",
)
UAT_ROLES = ("user", "admin", "production")
MANIFEST_RELATIVE_PATH = Path("reports/S10_RELEASE_EVIDENCE_MANIFEST.json")
TASK_CODE_FILES = (
    "src/business_ai_gateway/phase2/capture_loop.py",
    "src/business_ai_gateway/phase2/capture_runtime.py",
    "src/business_ai_gateway/phase2/fakes.py",
    "src/business_ai_gateway/phase2/ports.py",
    "src/business_ai_gateway/phase2/scheduler.py",
    "src/business_ai_gateway/runtime.py",
    "src/business_ai_gateway/phase2/release_manifest.py",
    "scripts/assemble_s10_release_manifest.py",
)
STATUSES = {"PASS", "FAIL", "NOT_RUN", "NOT_VERIFIED"}
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_IN_TEST_NAME = re.compile(r"(?:R2[-_]?)?TC[-_]?([0-9]{3})", re.IGNORECASE)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_file(root: Path, relative_path: Any, *, prefix: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("evidence path is required")
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or path.parts[0].casefold() != prefix.casefold() or ".." in path.parts:
        raise ValueError("evidence path is outside its permitted directory")
    target = root / path
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("evidence path escapes the repository") from exc
    if target.is_symlink() or not target.is_file():
        raise ValueError("evidence artifact is unavailable")
    return target


def _github_pr(root: Path, pr_number: int) -> dict[str, Any]:
    raw = subprocess.check_output(
        ["gh", "pr", "view", str(pr_number), "--repo", "xLZDx/ERP_MCP",
         "--json", "url,state,headRefOid"],
        cwd=root,
        text=True,
    )
    result = json.loads(raw)
    if (not isinstance(result, dict) or result.get("state") != "OPEN"
            or not _COMMIT.fullmatch(str(result.get("headRefOid", "")))):
        raise ValueError("pull request is not open or has no exact head SHA")
    expected_url = f"https://github.com/xLZDx/ERP_MCP/pull/{pr_number}"
    if result.get("url") != expected_url:
        raise ValueError("pull request URL does not match the requested repository and number")
    return {"number": pr_number, "url": expected_url, "head_sha": result["headRefOid"]}


def _inspect_junit(
    root: Path, run: Any, *, source_head: str, evidence_head: str, current_head: str
) -> dict[str, str]:
    if not isinstance(run, dict) or set(run) != {
        "run_id", "owner", "command", "junit_path", "junit_sha256", "test_files"
    }:
        raise ValueError("invalid test run fields")
    if (not isinstance(run["run_id"], str) or not run["run_id"].strip()
            or run["owner"] not in {"functional-test-reviewer", "e2e-runner"}
            or not isinstance(run["command"], str) or not run["command"].strip()
            or not isinstance(run["junit_path"], str)
            or not _SHA256.fullmatch(str(run["junit_sha256"]))):
        raise ValueError("test run identity/result artifact mismatch")
    junit_path = _repo_file(root, run["junit_path"], prefix="reports")
    if not run["junit_path"].replace("\\", "/").startswith("reports/evidence/s10/test-runs/"):
        raise ValueError("JUnit evidence must be stored in the S10 test-run evidence directory")
    junit_bytes = junit_path.read_bytes()
    if len(junit_bytes) > 4_000_000:
        raise ValueError("JUnit result artifact is too large")
    if hashlib.sha256(junit_bytes).hexdigest() != run["junit_sha256"]:
        raise ValueError("JUnit artifact digest mismatch")
    try:
        snapshot_bytes = _git_bytes(root, "show", f"{evidence_head}:{run['junit_path']}")
        current_bytes = _git_bytes(root, "show", f"{current_head}:{run['junit_path']}")
    except subprocess.CalledProcessError as exc:
        raise ValueError("JUnit artifact is missing from the PR evidence snapshot") from exc
    if snapshot_bytes != junit_bytes or current_bytes != snapshot_bytes:
        raise ValueError("JUnit evidence artifact changed after its PR evidence snapshot")
    try:
        xml_root = ET.fromstring(junit_bytes)
    except ET.ParseError as exc:
        raise ValueError("JUnit result artifact is invalid") from exc
    testcases = [xml_root] if xml_root.tag == "testcase" else list(xml_root.iter("testcase"))
    if not testcases:
        raise ValueError("JUnit result has no test cases")

    files = run["test_files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("test source files are required")
    stems: set[str] = set()
    for relative_path, digest in files.items():
        source_path = Path(relative_path) if isinstance(relative_path, str) else Path("..")
        if (source_path.is_absolute() or not source_path.parts or source_path.parts[0].casefold() != "tests"
                or ".." in source_path.parts or not _SHA256.fullmatch(str(digest))):
            raise ValueError("test file digest mismatch")
        try:
            source_bytes = _git_bytes(root, "show", f"{source_head}:{relative_path}")
        except subprocess.CalledProcessError as exc:
            raise ValueError("test source is missing from the candidate source HEAD") from exc
        if hashlib.sha256(source_bytes).hexdigest() != digest:
            raise ValueError("test file digest does not match the candidate source HEAD")
        try:
            snapshot_bytes = _git_bytes(root, "show", f"{evidence_head}:{relative_path}")
            current_bytes = _git_bytes(root, "show", f"{current_head}:{relative_path}")
        except subprocess.CalledProcessError as exc:
            raise ValueError("test source is missing from the PR evidence snapshot or current head") from exc
        if snapshot_bytes != source_bytes or current_bytes != source_bytes:
            raise ValueError("test source changed after the tested source HEAD")
        stems.add(source_path.stem.casefold())

    outcomes: dict[str, list[str]] = {}
    observed_stems: set[str] = set()
    for testcase in testcases:
        name = f"{testcase.get('classname', '')}.{testcase.get('name', '')}"
        properties = testcase.find("properties")
        head_properties = [] if properties is None else [
            prop.get("value") for prop in properties.findall("property")
            if prop.get("name") == "candidate_head"
        ]
        if head_properties != [source_head]:
            raise ValueError("JUnit case is not bound to the exact candidate HEAD")
        observed_stems.update(stem for stem in stems if stem in name.casefold())
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            outcome = "FAIL"
        elif testcase.find("skipped") is not None:
            outcome = "NOT_RUN"
        else:
            outcome = "PASS"
        match = _CASE_IN_TEST_NAME.search(name)
        if match:
            case_id = f"R2-TC-{match.group(1)}"
            if case_id in CASE_IDS:
                outcomes.setdefault(case_id, []).append(outcome)
    if observed_stems != stems:
        raise ValueError("JUnit result does not identify every hashed test source file")
    return {
        case_id: "PASS" if all(status == "PASS" for status in statuses)
        else "NOT_RUN" if all(status == "NOT_RUN" for status in statuses)
        else "FAIL"
        for case_id, statuses in outcomes.items()
    }


def _assert_task_code_unchanged(root: Path, *, source_head: str, current_head: str) -> None:
    for relative_path in TASK_CODE_FILES:
        try:
            source_bytes = _git_bytes(root, "show", f"{source_head}:{relative_path}")
            current_bytes = _git_bytes(root, "show", f"{current_head}:{relative_path}")
        except subprocess.CalledProcessError as exc:
            raise ValueError("task implementation is missing from a candidate commit") from exc
        if current_bytes != source_bytes:
            raise ValueError("task implementation changed after the tested source HEAD")


def fixed_manifest_output_path(root: Path, output_path: Path) -> Path:
    """Validate the lexical destination and reject symlinks/junctions before resolving it."""
    root = root.resolve()
    candidate = output_path if output_path.is_absolute() else root / output_path
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("manifest output must be inside the repository") from exc
    if relative != MANIFEST_RELATIVE_PATH:
        raise ValueError("manifest output must use the fixed S10 evidence destination")

    current = root
    for component in MANIFEST_RELATIVE_PATH.parts:
        current /= component
        if current.is_symlink() or current.is_junction():
            raise ValueError("manifest output path cannot traverse symlinks or junctions")
    return root / MANIFEST_RELATIVE_PATH


def _assert_clean_candidate(root: Path, *, allowed_output: Path | None) -> None:
    status = _git_bytes(root, "status", "--porcelain", "-z", "--untracked-files=all")
    if status and not status.endswith(b"\0"):
        raise ValueError("cannot parse Git status while verifying the candidate worktree")
    records = status[:-1].split(b"\0") if status else []
    changed_paths = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            raise ValueError("cannot parse Git status while verifying the candidate worktree")
        if len(record) < 4 or record[2:3] != b" " or not record[3:]:
            raise ValueError("cannot parse Git status while verifying the candidate worktree")
        changed_paths.append(os.fsdecode(record[3:]))
        if b"R" in record[:2] or b"C" in record[:2]:
            if index >= len(records) or not records[index]:
                raise ValueError("cannot parse renamed Git path while verifying the candidate worktree")
            changed_paths.append(os.fsdecode(records[index]))
            index += 1
    if allowed_output is None:
        if changed_paths:
            raise ValueError("candidate worktree must be clean before manifest assembly")
        return
    fixed_manifest_output_path(root, allowed_output)
    allowed = MANIFEST_RELATIVE_PATH.as_posix()
    if set(changed_paths) - {allowed}:
        raise ValueError("candidate worktree has changes beyond the manifest output")


def _validate_uat(*, record: Any) -> None:
    if (not isinstance(record, dict)
            or set(record) != {"status", "evidence_path", "evidence_sha256"}
            or record["status"] not in {"NOT_RUN", "NOT_VERIFIED"}):
        raise ValueError("invalid UAT record")
    if record["evidence_path"] is not None or record["evidence_sha256"] is not None:
        raise ValueError("this bounded package cannot verify or accept UAT evidence")


def validate_manifest(manifest: Any, *, root: Path, allowed_output: Path | None = None) -> dict[str, Any]:
    """Validate case IDs, JUnit provenance, separate UAT lanes and fail-closed release state."""
    root = root.resolve()
    if allowed_output is not None:
        allowed_output = fixed_manifest_output_path(root, allowed_output)
    if (not isinstance(manifest, dict)
            or set(manifest) != {"schema_version", "package_status", "candidate", "case_ids", "cases",
                                 "test_runs", "uat", "release_decision", "native_evidence_level_inferred"}
            or manifest.get("schema_version") != 1
            or manifest.get("package_status") != "BOUNDED_ENGINEERING_EVIDENCE_ONLY"):
        raise ValueError("unsupported manifest schema")
    candidate = manifest.get("candidate")
    if (not isinstance(candidate, dict) or set(candidate) != {"source_head", "branch", "remote_branch_head", "pull_request"}
            or not _COMMIT.fullmatch(str(candidate.get("source_head", "")))
            or not isinstance(candidate.get("branch"), str) or not candidate["branch"].strip()
            or not _COMMIT.fullmatch(str(candidate.get("remote_branch_head", "")))
            or not isinstance(candidate["pull_request"], dict)
            or set(candidate["pull_request"]) != {"number", "url", "head_sha"}
            or type(candidate["pull_request"]["number"]) is not int or candidate["pull_request"]["number"] < 1
            or candidate["pull_request"]["url"] != (
                f"https://github.com/xLZDx/ERP_MCP/pull/{candidate['pull_request']['number']}" )
            or not _COMMIT.fullmatch(str(candidate["pull_request"]["head_sha"]))
            or candidate["remote_branch_head"] != candidate["pull_request"]["head_sha"]):
        raise ValueError("invalid candidate or pull request identity")
    current_head = _git(root, "rev-parse", "HEAD")
    if _git(root, "branch", "--show-current") != candidate["branch"]:
        raise ValueError("candidate branch identity mismatch")
    try:
        _git(root, "merge-base", "--is-ancestor", candidate["source_head"], candidate["pull_request"]["head_sha"])
        _git(root, "merge-base", "--is-ancestor", candidate["pull_request"]["head_sha"], current_head)
    except subprocess.CalledProcessError as exc:
        raise ValueError("source or evidence snapshot is not an ancestor of the current pull request head") from exc
    _assert_task_code_unchanged(
        root, source_head=candidate["source_head"], current_head=candidate["pull_request"]["head_sha"]
    )
    _assert_task_code_unchanged(root, source_head=candidate["source_head"], current_head=current_head)
    remote = _git(root, "ls-remote", "origin", f"refs/heads/{candidate['branch']}").split()
    if (len(remote) != 2 or remote[0] != current_head
            or remote[1] != f"refs/heads/{candidate['branch']}"):
        raise ValueError("remote candidate branch does not match pull request head")
    pull_request = _github_pr(root, candidate["pull_request"]["number"])
    if (pull_request["url"] != candidate["pull_request"]["url"]
            or pull_request["head_sha"] != current_head):
        raise ValueError("pull request head does not match the remote branch")
    _assert_clean_candidate(root, allowed_output=allowed_output)

    runs = manifest.get("test_runs")
    if not isinstance(runs, list):
        raise ValueError("test run list is required")
    runs_by_id: dict[str, dict[str, Any]] = {}
    run_case_outcomes: dict[str, dict[str, str]] = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str) or run["run_id"] in runs_by_id:
            raise ValueError("invalid or duplicate test run id")
        outcomes = _inspect_junit(
            root, run, source_head=candidate["source_head"],
            evidence_head=candidate["pull_request"]["head_sha"], current_head=current_head,
        )
        runs_by_id[run["run_id"]] = run
        run_case_outcomes[run["run_id"]] = outcomes

    cases = manifest.get("cases")
    if (manifest.get("case_ids") != list(CASE_IDS) or not isinstance(cases, list)
            or [case.get("id") for case in cases if isinstance(case, dict)] != list(CASE_IDS)):
        raise ValueError("manifest case IDs/order are incomplete")
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"id", "status", "evidence_run_ids", "note"}
                or case["status"] not in STATUSES
                or not isinstance(case["evidence_run_ids"], list)
                or not isinstance(case["note"], str) or not case["note"].strip()):
            raise ValueError("invalid case result")
        if len(set(case["evidence_run_ids"])) != len(case["evidence_run_ids"]):
            raise ValueError("duplicate case evidence run")
        if case["status"] in {"PASS", "FAIL"} and not case["evidence_run_ids"]:
            raise ValueError("actual result requires evidence")
        if case["status"] == "NOT_VERIFIED" and case["evidence_run_ids"]:
            raise ValueError("NOT_VERIFIED case cannot cite a test run")
        for run_id in case["evidence_run_ids"]:
            if run_id not in runs_by_id or run_case_outcomes[run_id].get(case["id"]) != case["status"]:
                raise ValueError("case result does not match the JUnit case outcome")

    uat = manifest.get("uat")
    if not isinstance(uat, dict) or set(uat) != set(UAT_ROLES):
        raise ValueError("user, admin and production UAT must be separate")
    for role in UAT_ROLES:
        _validate_uat(record=uat[role])

    by_case = {case["id"]: case for case in cases}
    if any(by_case[case_id]["status"] != "PASS" for case_id in ("R2-TC-142", "R2-TC-143")):
        raise ValueError("manifest structure and fail-closed guard must pass before assembly")
    referenced_runs = {run_id for case in cases for run_id in case["evidence_run_ids"]}
    if referenced_runs != set(runs_by_id):
        raise ValueError("manifest contains unreferenced test runs")
    # TC144 verifies that three role-specific UAT lanes exist and remain distinct.
    # Their actual execution statuses are separate records and may correctly stay NOT_RUN.
    if by_case["R2-TC-143"]["status"] == "PASS" and any(
        case["status"] in {"NOT_RUN", "NOT_VERIFIED"} for case in cases
    ) and manifest.get("release_decision") != "NO-GO":
        raise ValueError("NOT_RUN cannot be promoted to release PASS")
    if manifest.get("release_decision") != "NO-GO":
        raise ValueError("bounded S10 manifest cannot authorize a release")
    if manifest.get("native_evidence_level_inferred") is not False:
        raise ValueError("native evidence level must never be inferred")
    return manifest


def assemble_manifest(root: Path, *, source_head: str, cases: list[dict[str, Any]],
                      test_runs: list[dict[str, Any]], uat: dict[str, dict[str, Any]], pr_number: int,
                      output_path: Path | None = None) -> dict[str, Any]:
    """Bind test results to an exact source HEAD and allow later evidence-only PR commits."""
    root = root.resolve()
    if output_path is not None:
        output_path = fixed_manifest_output_path(root, output_path)
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    remote = _git(root, "ls-remote", "origin", f"refs/heads/{branch}").split()
    if len(remote) != 2 or remote[0] != head or remote[1] != f"refs/heads/{branch}":
        raise ValueError("remote branch does not match the current pull request head")
    if not _COMMIT.fullmatch(source_head):
        raise ValueError("invalid candidate source HEAD")
    try:
        _git(root, "merge-base", "--is-ancestor", source_head, head)
    except subprocess.CalledProcessError as exc:
        raise ValueError("candidate source HEAD is not an ancestor of the current branch") from exc
    _assert_task_code_unchanged(root, source_head=source_head, current_head=head)
    pull_request = _github_pr(root, pr_number)
    if pull_request["head_sha"] != head:
        raise ValueError("pull request head does not match the current remote branch")
    manifest = {
        "schema_version": 1,
        "package_status": "BOUNDED_ENGINEERING_EVIDENCE_ONLY",
        "candidate": {
            "source_head": source_head,
            "branch": branch,
            "remote_branch_head": remote[0],
            "pull_request": pull_request,
        },
        "case_ids": list(CASE_IDS),
        "cases": cases,
        "test_runs": test_runs,
        "uat": uat,
        "release_decision": "NO-GO",
        "native_evidence_level_inferred": False,
    }
    return validate_manifest(manifest, root=root, allowed_output=output_path)
