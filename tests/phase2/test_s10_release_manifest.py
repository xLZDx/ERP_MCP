from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import release_manifest as module

SOURCE_HEAD = "a" * 40
PR_HEAD = "b" * 40
PR_NUMBER = 53
BRANCH = "codex/s10-r2-canary-dev-20261108"
JUNIT_DIR = "reports/evidence/s10/test-runs"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _junit(run_case_ids, *, failing_case=None, skipped_case=None, candidate_head=SOURCE_HEAD):
    cases = []
    for case_id in run_case_ids:
        number = case_id[-3:]
        stem = "capture" if number in {"124", "125", "126"} else "manifest"
        failure = '<failure message="assertion failed"/>' if case_id == failing_case else ""
        skipped = '<skipped message="not executed"/>' if case_id == skipped_case else ""
        cases.append(
            f'<testcase classname="test_{stem}.test_s10_{number}" name="test_{case_id}">'
            f'<properties><property name="candidate_head" value="{candidate_head}"/></properties>'
            f"{failure}{skipped}</testcase>"
        )
    return ("<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>").encode("utf-8")


def _write_bytes(root: Path, relative_path: str, data: bytes) -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _create_directory_junction_or_symlink(link: Path, target: Path) -> None:
    junction_error = None
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", link.name, target.name],
                cwd=link.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and link.is_dir():
                return
            junction_error = result.stderr or result.stdout or f"mklink exited {result.returncode}"
        except OSError as exc:
            junction_error = str(exc)
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        details = f"; junction attempt: {junction_error}" if junction_error else ""
        pytest.skip(f"directory junction/symlink unavailable on this platform: {exc}{details}")


def _run(root, run_id, case_ids, test_path, *, failing_case=None, skipped_case=None,
         candidate_head=SOURCE_HEAD, tamper_digest=False):
    test_bytes = f"synthetic test source for {run_id}\n".encode("utf-8")
    _write_bytes(root, test_path, test_bytes)
    junit_path = f"{JUNIT_DIR}/{run_id}.xml"
    junit_bytes = _junit(
        case_ids, failing_case=failing_case, skipped_case=skipped_case, candidate_head=candidate_head
    )
    _write_bytes(root, junit_path, junit_bytes)
    return {
        "run_id": run_id,
        "owner": "functional-test-reviewer",
        "command": f"python -m pytest -q {test_path}",
        "junit_path": junit_path,
        "junit_sha256": "0" * 64 if tamper_digest else _sha256(junit_bytes),
        "test_files": {test_path: _sha256(test_bytes)},
    }


def _inputs(root):
    runs = [
        _run(root, "capture-tests", ["R2-TC-124", "R2-TC-125", "R2-TC-126"], "tests/capture.py"),
        _run(root, "manifest-tests", ["R2-TC-142", "R2-TC-143", "R2-TC-144"], "tests/manifest.py"),
    ]
    cases = [
        {"id": "R2-TC-124", "status": "PASS", "evidence_run_ids": ["capture-tests"], "note": "exact scope bound before work"},
        {"id": "R2-TC-125", "status": "PASS", "evidence_run_ids": ["capture-tests"], "note": "dev/test cannot grant production approval"},
        {"id": "R2-TC-126", "status": "PASS", "evidence_run_ids": ["capture-tests"], "note": "scope-owned jobs stop and drain"},
        {"id": "R2-TC-142", "status": "PASS", "evidence_run_ids": ["manifest-tests"], "note": "all acceptance IDs and observed outcomes are present"},
        {"id": "R2-TC-143", "status": "PASS", "evidence_run_ids": ["manifest-tests"], "note": "NOT_RUN remains distinct and release stays NO-GO"},
        {"id": "R2-TC-144", "status": "PASS", "evidence_run_ids": ["manifest-tests"], "note": "three separate UAT lanes are represented; their actual results remain separately recorded"},
    ]
    uat = {
        role: {"status": "NOT_RUN", "evidence_path": None, "evidence_sha256": None}
        for role in module.UAT_ROLES
    }
    return cases, runs, uat


def _fake_git(monkeypatch, root, *, dirty="", remote_head=PR_HEAD, head=PR_HEAD,
              pr_head=PR_HEAD, blob_overrides=None):
    blob_overrides = blob_overrides or {}
    project_root = Path(__file__).resolve().parents[2]

    def git(_root, *args):
        if args == ("rev-parse", "HEAD"):
            return head
        if args == ("branch", "--show-current"):
            return BRANCH
        if args == ("ls-remote", "origin", f"refs/heads/{BRANCH}"):
            return f"{remote_head}\trefs/heads/{BRANCH}"
        if args == ("status", "--porcelain"):
            return dirty
        if len(args) == 4 and args[:2] == ("merge-base", "--is-ancestor"):
            ancestor, descendant = args[2], args[3]
            if not ((ancestor == SOURCE_HEAD and descendant in {PR_HEAD, head})
                    or (ancestor == PR_HEAD and descendant == head)):
                raise module.subprocess.CalledProcessError(1, args)
            return ""
        raise AssertionError(args)

    def git_bytes(_root, *args):
        if len(args) == 2 and args[0] == "show":
            commit, relative_path = args[1].split(":", 1)
            if commit not in {SOURCE_HEAD, PR_HEAD, head}:
                raise module.subprocess.CalledProcessError(1, args)
            if (commit, relative_path) in blob_overrides:
                return blob_overrides[(commit, relative_path)]
            try:
                base = project_root if relative_path in module.TASK_CODE_FILES else root
                return (base / relative_path).read_bytes()
            except OSError as exc:
                raise module.subprocess.CalledProcessError(1, args) from exc
        raise AssertionError(args)

    monkeypatch.setattr(module, "_git", git)
    monkeypatch.setattr(module, "_git_bytes", git_bytes)
    monkeypatch.setattr(module, "_github_pr", lambda _root, number: {
        "number": number,
        "url": f"https://github.com/xLZDx/ERP_MCP/pull/{number}",
        "head_sha": pr_head,
    })


def test_tc142_manifest_records_complete_ids_results_and_distinct_not_run_uat(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path)

    result = module.assemble_manifest(
        tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER,
        output_path=tmp_path / module.MANIFEST_RELATIVE_PATH,
    )

    assert result["case_ids"] == list(module.CASE_IDS)
    assert [case["id"] for case in result["cases"]] == list(module.CASE_IDS)
    assert result["candidate"]["source_head"] == SOURCE_HEAD
    assert result["candidate"]["remote_branch_head"] == PR_HEAD
    assert result["candidate"]["pull_request"] == {
        "number": PR_NUMBER,
        "url": f"https://github.com/xLZDx/ERP_MCP/pull/{PR_NUMBER}",
        "head_sha": PR_HEAD,
    }
    assert all(run["junit_path"].startswith(f"{JUNIT_DIR}/") for run in result["test_runs"])
    assert [case["status"] for case in result["cases"]] == ["PASS"] * 6
    assert result["uat"] == {
        role: {"status": "NOT_RUN", "evidence_path": None, "evidence_sha256": None}
        for role in module.UAT_ROLES
    }
    assert result["release_decision"] == "NO-GO"
    assert result["native_evidence_level_inferred"] is False


def test_tc142_manifest_output_is_restricted_to_the_fixed_evidence_path(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path)
    result = module.assemble_manifest(
        tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER,
        output_path=tmp_path / module.MANIFEST_RELATIVE_PATH,
    )

    alternate = tmp_path / "reports/another_manifest.json"
    with pytest.raises(ValueError, match="fixed S10 evidence destination"):
        module.assemble_manifest(
            tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER,
            output_path=alternate,
        )
    with pytest.raises(ValueError, match="fixed S10 evidence destination"):
        module.validate_manifest(result, root=tmp_path, allowed_output=alternate)


def test_tc142_api_rejects_symlink_or_junction_output_parent_before_replacing_target(tmp_path):
    cases, runs, uat = _inputs(tmp_path)
    reports = tmp_path / "reports"
    real_reports = tmp_path / "reports-real"
    target = reports / module.MANIFEST_RELATIVE_PATH.name
    sentinel = b"preserve prior evidence manifest\n"
    target.write_bytes(sentinel)
    reports.rename(real_reports)
    _create_directory_junction_or_symlink(reports, real_reports)

    with pytest.raises(ValueError, match="manifest output path cannot traverse symlinks"):
        module.assemble_manifest(
            tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat,
            pr_number=PR_NUMBER, output_path=tmp_path / module.MANIFEST_RELATIVE_PATH,
        )

    assert target.read_bytes() == sentinel


def test_tc142_rejects_forged_outcome_and_tampered_or_uncommitted_junit(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    runs[0] = _run(
        tmp_path, "capture-tests", ["R2-TC-124", "R2-TC-125", "R2-TC-126"],
        "tests/capture.py", skipped_case="R2-TC-124",
    )
    _fake_git(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="does not match the JUnit case outcome"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)

    cases, runs, uat = _inputs(tmp_path)
    runs[0] = _run(
        tmp_path, "capture-tests", ["R2-TC-124", "R2-TC-125", "R2-TC-126"],
        "tests/capture.py", tamper_digest=True,
    )
    _fake_git(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="JUnit artifact digest mismatch"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)

    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path, blob_overrides={(PR_HEAD, runs[0]["junit_path"]): b"stale junit"})
    with pytest.raises(ValueError, match="JUnit evidence artifact changed after its PR evidence snapshot"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)


def test_tc142_every_junit_case_must_bind_exact_tested_source_head(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    runs[0] = _run(
        tmp_path, "capture-tests", ["R2-TC-124", "R2-TC-125", "R2-TC-126"],
        "tests/capture.py", candidate_head="c" * 40,
    )
    _fake_git(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not bound to the exact candidate HEAD"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)


def test_tc143_skipped_testcase_remains_not_run_and_cannot_grant_go(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    runs[0] = _run(
        tmp_path, "capture-tests", ["R2-TC-124", "R2-TC-125", "R2-TC-126"],
        "tests/capture.py", skipped_case="R2-TC-124",
    )
    cases[0]["status"] = "NOT_RUN"
    _fake_git(monkeypatch, tmp_path)

    result = module.assemble_manifest(
        tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER
    )
    assert result["cases"][0]["status"] == "NOT_RUN"
    result["release_decision"] = "GO"
    with pytest.raises(ValueError, match="NOT_RUN cannot be promoted"):
        module.validate_manifest(result, root=tmp_path)


def test_tc144_requires_three_distinct_lanes_and_rejects_claimed_uat_pass(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path)
    del uat["admin"]
    with pytest.raises(ValueError, match="must be separate"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)

    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path)
    result = module.assemble_manifest(
        tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER
    )
    assert set(result["uat"]) == {"user", "admin", "production"}
    assert all(record == {"status": "NOT_RUN", "evidence_path": None, "evidence_sha256": None}
               for record in result["uat"].values())
    assert result["cases"][-1]["id"] == "R2-TC-144"
    assert result["cases"][-1]["status"] == "PASS"


@pytest.mark.parametrize("role", ["user", "admin", "production"])
def test_tc144_rejects_self_attested_uat_pass_for_every_role(tmp_path, monkeypatch, role):
    cases, runs, uat = _inputs(tmp_path)
    uat[role]["status"] = "PASS"
    _fake_git(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="invalid UAT record"):
        module.assemble_manifest(
            tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER
        )


def test_tc144_rejects_unsigned_uat_evidence_even_when_status_is_unverified(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    uat["user"] = {
        "status": "NOT_VERIFIED",
        "evidence_path": "reports/evidence/s10/uat/user/attestation.json",
        "evidence_sha256": "0" * 64,
    }
    _fake_git(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="cannot verify or accept UAT evidence"):
        module.assemble_manifest(
            tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER
        )


def test_tc142_rejects_stale_pr_and_remote_heads_and_task_blob_drift(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path, pr_head="c" * 40)
    with pytest.raises(ValueError, match="pull request head does not match the current remote branch"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)

    _fake_git(monkeypatch, tmp_path, remote_head="c" * 40)
    with pytest.raises(ValueError, match="remote branch does not match"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)

    _fake_git(monkeypatch, tmp_path, blob_overrides={(PR_HEAD, "tests/manifest.py"): b"drifted tested source"})
    with pytest.raises(ValueError, match="test source changed after the tested source HEAD"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)


@pytest.mark.parametrize("relative_path", [
    "src/business_ai_gateway/phase2/capture_loop.py",
    "src/business_ai_gateway/phase2/capture_runtime.py",
    "src/business_ai_gateway/phase2/fakes.py",
    "src/business_ai_gateway/phase2/ports.py",
    "src/business_ai_gateway/phase2/scheduler.py",
    "src/business_ai_gateway/runtime.py",
])
def test_tc124_through_tc144_rejects_drift_in_each_captured_implementation_file(
    tmp_path, monkeypatch, relative_path
):
    cases, runs, uat = _inputs(tmp_path)
    assert relative_path in module.TASK_CODE_FILES
    _fake_git(monkeypatch, tmp_path, blob_overrides={(PR_HEAD, relative_path): b"drifted implementation"})

    with pytest.raises(ValueError, match="task implementation changed after the tested source HEAD"):
        module.assemble_manifest(
            tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER
        )


def test_tc142_rejects_stale_or_dirty_candidate_and_invalid_pr_identity(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path)
    result = module.assemble_manifest(
        tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER
    )
    result["candidate"]["source_head"] = "c" * 40
    with pytest.raises(ValueError, match="source or evidence snapshot is not an ancestor"):
        module.validate_manifest(result, root=tmp_path)

    _fake_git(monkeypatch, tmp_path, dirty=" M source.py")
    with pytest.raises(ValueError, match="must be clean"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)

    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_github_pr", lambda _root, number: {
        "number": number,
        "url": f"https://github.com/other/repo/pull/{number}",
        "head_sha": PR_HEAD,
    })
    with pytest.raises(ValueError, match="invalid candidate or pull request identity"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)


def test_tc142_rejects_incomplete_case_ids_and_unreferenced_runs(tmp_path, monkeypatch):
    cases, runs, uat = _inputs(tmp_path)
    _fake_git(monkeypatch, tmp_path)
    cases.pop()
    with pytest.raises(ValueError, match="IDs/order are incomplete"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)

    cases, runs, uat = _inputs(tmp_path)
    orphan = dict(runs[0])
    orphan["run_id"] = "orphan-run"
    runs.append(orphan)
    _fake_git(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="unreferenced test runs"):
        module.assemble_manifest(tmp_path, source_head=SOURCE_HEAD, cases=cases, test_runs=runs, uat=uat, pr_number=PR_NUMBER)
