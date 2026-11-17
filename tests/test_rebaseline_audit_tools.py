"""Isolated contract tests for the read-only program rebaseline evidence tools."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


lock_module = load_script("rebaseline_lock")
inventory = load_script("rebaseline_inventory")
details = load_script("rebaseline_branch_details")


class InventoryContractTests(unittest.TestCase):
    def fixture_root(self, base: Path) -> Path:
        root = base / "repo"
        (root / "docs/specs").mkdir(parents=True)
        (root / "config").mkdir()
        (root / "docs/specs/contract.yaml").write_text("version: 1\n", encoding="utf-8")
        (root / "docs/specs/scenarios.feature").write_text("Feature: acceptance\n", encoding="utf-8")
        (root / "docs/specs/records.csv").write_text("id,state\n1,open\n", encoding="utf-8")
        (root / "config/accounts.csv").write_text("id,name\n1,demo\n", encoding="utf-8")
        (root / ".env.local").write_text("never serialize this value\n", encoding="utf-8")
        (root / "credentials.json").write_text("never serialize this either\n", encoding="utf-8")
        return root

    def test_inventory_captures_local_csv_and_sensitive_names_without_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture_root(Path(temp))

            def fake_git(*args):
                if args[:2] == ("rev-parse", "HEAD"):
                    return "root-sha\n"
                if args[:2] == ("branch", "--show-current"):
                    return "isolated\n"
                if args[0] == "for-each-ref":
                    return "refs/remotes/origin/main base-sha\nrefs/remotes/origin/specs spec-sha\n"
                if args[:2] == ("worktree", "list"):
                    return "worktree /fixture\nHEAD root-sha\n"
                if args[:2] == ("diff", "--name-status"):
                    return ""
                if args[0] == "rev-list":
                    return "0 1\n"
                if args[0] == "ls-tree":
                    sha = args[2]
                    rows = {
                        "base-sha": ["100644 blob baseblob\tdocs/old.md"],
                        "spec-sha": [
                            "100644 blob yamlblob\tdocs/specs/contract.yaml",
                            "100644 blob csvblob\tdocs/specs/records.csv",
                            "100644 blob featureblob\tdocs/specs/scenarios.feature",
                        ],
                    }
                    return "\n".join(rows[sha]) + "\n"
                raise AssertionError(f"Unexpected Git query: {args!r}")

            def fake_process(args, **kwargs):
                self.assertEqual(args[:3], ["git", "merge-base", "--is-ancestor"])
                return subprocess.CompletedProcess(args, 1, "", "")

            with patch.object(inventory, "git", side_effect=fake_git), patch.object(
                inventory.subprocess, "run", side_effect=fake_process
            ):
                inventory.collect(root, "isolated-run")

            out = root / "docs/rebaseline/2026-11-17"
            files = json.loads((out / "FILE_INVENTORY.json").read_text(encoding="utf-8"))["files"]
            by_path = {row["path"]: row for row in files}
            self.assertIn("config/accounts.csv", by_path)
            self.assertEqual(by_path[".env.local"]["content"], "EXCLUDED_SENSITIVE_NAME")
            self.assertEqual(by_path["credentials.json"]["content"], "EXCLUDED_SENSITIVE_NAME")
            self.assertNotIn("never serialize", (out / "FILE_INVENTORY.json").read_text(encoding="utf-8"))

            versions = json.loads((out / "DOCUMENT_VERSIONS.json").read_text(encoding="utf-8"))
            remote_only = {row["path"]: row for row in versions}
            for path in ("docs/specs/contract.yaml", "docs/specs/records.csv", "docs/specs/scenarios.feature"):
                self.assertEqual(remote_only[path]["refs"], ["refs/remotes/origin/specs"])

    def test_unavailable_ancestry_makes_inventory_partial_and_not_cleanup_eligible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture_root(Path(temp))

            def fake_git(*args):
                if args[:2] == ("rev-parse", "HEAD"):
                    return "root-sha\n"
                if args[:2] == ("branch", "--show-current"):
                    return "isolated\n"
                if args[0] == "for-each-ref":
                    return "refs/remotes/origin/main base-sha\nrefs/heads/uncertain unknown-sha\n"
                if args[:2] == ("worktree", "list") or args[:2] == ("diff", "--name-status"):
                    return ""
                if args[0] == "ls-tree":
                    return "100644 blob docblob\tdocs/design.md\n"
                if args[0] == "rev-list":
                    return "0 0\n"
                raise AssertionError(f"Unexpected Git query: {args!r}")

            def fake_process(args, **kwargs):
                sha = args[3]
                return subprocess.CompletedProcess(args, 128 if sha == "unknown-sha" else 0, "", "repository unavailable")

            with patch.object(inventory, "git", side_effect=fake_git), patch.object(
                inventory.subprocess, "run", side_effect=fake_process
            ):
                inventory.collect(root, "uncertain-run")

            out = root / "docs/rebaseline/2026-11-17"
            run = json.loads((out / "INVENTORY_RUN.json").read_text(encoding="utf-8"))
            branch = next(b for b in json.loads((out / "BRANCH_INVENTORY.json").read_text(encoding="utf-8"))["branches"]
                          if b["ref"] == "refs/heads/uncertain")
            self.assertEqual(run["status"], "PARTIAL")
            self.assertIsNone(branch["merged_into_origin_main"])
            self.assertIsNone(branch["main_only"])
            self.assertIsNone(branch["branch_only"])
            self.assertEqual(branch["disposition"], "UNAVAILABLE")

    def test_interrupted_new_inventory_replaces_stale_complete_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            out = root / "docs/rebaseline/2026-11-17"
            out.mkdir(parents=True)
            marker = out / "INVENTORY_RUN.json"
            marker.write_text(json.dumps({"run_id": "old", "status": "COMPLETE"}), encoding="utf-8")

            def fake_git(*args):
                if args == ("rev-parse", "--show-toplevel"):
                    return f"{root}\n"
                raise OSError("simulated inventory interruption")

            with patch.object(inventory, "git", side_effect=fake_git), self.assertRaises(OSError):
                inventory.main()

            current = json.loads(marker.read_text(encoding="utf-8"))
            self.assertNotEqual(current["run_id"], "old")
            self.assertEqual(current["status"], "FAILED")
            self.assertFalse((out / ".inventory.lock").exists())

    def test_cli_exit_code_is_zero_for_complete_and_two_for_partial(self):
        for ancestry_exit, expected in ((0, 0), (128, 2)):
            with self.subTest(ancestry_exit=ancestry_exit), tempfile.TemporaryDirectory() as temp:
                root = self.fixture_root(Path(temp))

                def fake_git(*args):
                    if args == ("rev-parse", "--show-toplevel"):
                        return f"{root}\n"
                    if args[:2] == ("rev-parse", "HEAD"):
                        return "base-sha\n"
                    if args[:2] == ("branch", "--show-current"):
                        return "main\n"
                    if args[0] == "for-each-ref":
                        refs = "refs/remotes/origin/main base-sha\n"
                        if ancestry_exit == 128:
                            refs += "refs/heads/unknown unknown-sha\n"
                        return refs
                    if args[:2] == ("worktree", "list") or args[:2] == ("diff", "--name-status"):
                        return ""
                    if args[0] == "rev-list":
                        return "0 0\n"
                    if args[0] == "ls-tree":
                        return "100644 blob docblob\tdocs/design.md\n"
                    raise AssertionError(f"Unexpected Git query: {args!r}")

                def fake_process(args, **kwargs):
                    sha = args[3]
                    rc = ancestry_exit if sha == "unknown-sha" else 0
                    return subprocess.CompletedProcess(args, rc, "", "")

                with patch.object(inventory, "git", side_effect=fake_git), patch.object(
                    inventory.subprocess, "run", side_effect=fake_process
                ):
                    self.assertEqual(inventory.main(), expected)


class BranchDetailsContractTests(unittest.TestCase):
    def details_fixture(self, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        branch_bytes = json.dumps({
            "run_id": "run-17",
            "baseline": "saved-base-sha",
            "branches": [{"ref": "refs/heads/feature", "sha": "feature-sha", "merged_into_origin_main": False}],
        }).encode()
        (out / "BRANCH_INVENTORY.json").write_bytes(branch_bytes)
        (out / "INVENTORY_RUN.json").write_text(json.dumps({
            "run_id": "run-17", "status": "COMPLETE", "baseline": "saved-base-sha",
            "files": {"BRANCH_INVENTORY.json": hashlib.sha256(branch_bytes).hexdigest()},
        }), encoding="utf-8")

    def test_details_requires_complete_manifest_and_matching_inventory_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            self.details_fixture(out)
            manifest_path = out / "INVENTORY_RUN.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "PARTIAL"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(details, "run") as git_call, self.assertRaisesRegex(RuntimeError, "incomplete"):
                details.collect(out)
            git_call.assert_not_called()

            manifest["status"] = "COMPLETE"
            manifest["files"]["BRANCH_INVENTORY.json"] = "wrong-hash"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(details, "run") as git_call, self.assertRaisesRegex(RuntimeError, "does not match"):
                details.collect(out)
            git_call.assert_not_called()

    def test_cherry_uses_saved_baseline_and_current_failure_is_partial_with_unknown_counts(self):
        for cherry_result in (
            {"exit_code": 1, "stdout": "", "stderr": "git failed"},
            {"exit_code": None, "error": "timeout after 120 seconds"},
        ):
            with self.subTest(cherry_result=cherry_result), tempfile.TemporaryDirectory() as temp:
                out = Path(temp)
                self.details_fixture(out)
                calls = []

                def fake_run(args, cwd=None):
                    calls.append((args, cwd))
                    if args[0] == "cherry":
                        # Simulate origin/main changing after the inventory snapshot.
                        self.assertEqual(args, ["cherry", "saved-base-sha", "feature-sha"])
                        return cherry_result
                    if args[:2] == ["worktree", "list"]:
                        return {"exit_code": 0, "stdout": "worktree /isolated\nHEAD x\n", "stderr": ""}
                    if args[0] == "status":
                        return {"exit_code": 0, "stdout": "", "stderr": ""}
                    raise AssertionError(f"Unexpected Git query: {args!r}")

                with patch.object(details, "run", side_effect=fake_run):
                    details.collect(out)

                compared = json.loads((out / "PATCH_EQUIVALENCE.json").read_text(encoding="utf-8"))[0]
                final = json.loads((out / "DETAILS_RUN.json").read_text(encoding="utf-8"))
                self.assertIsNone(compared["unique_patch_count"])
                self.assertIsNone(compared["equivalent_patch_count"])
                self.assertFalse(compared["comparison_available"])
                self.assertEqual(final["status"], "PARTIAL")
                self.assertEqual(final["baseline"], "saved-base-sha")

    def test_cli_exit_code_is_zero_for_complete_and_two_for_partial(self):
        original_cwd = Path.cwd()
        try:
            for cherry_result, expected in (
                ({"exit_code": 0, "stdout": "", "stderr": ""}, 0),
                ({"exit_code": 1, "stdout": "", "stderr": "git failed"}, 2),
            ):
                with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    out = root / "docs/rebaseline/2026-11-17"
                    self.details_fixture(out)
                    os.chdir(root)

                    def fake_run(args, cwd=None):
                        if args[0] == "cherry":
                            self.assertEqual(args, ["cherry", "saved-base-sha", "feature-sha"])
                            return cherry_result
                        if args[:2] == ["worktree", "list"]:
                            return {"exit_code": 0, "stdout": "worktree /isolated\nHEAD x\n", "stderr": ""}
                        if args[0] == "status":
                            return {"exit_code": 0, "stdout": "", "stderr": ""}
                        raise AssertionError(f"Unexpected Git query: {args!r}")

                    try:
                        with patch.object(details, "run", side_effect=fake_run):
                            self.assertEqual(details.main(), expected)
                    finally:
                        os.chdir(original_cwd)
        finally:
            os.chdir(original_cwd)


class TemporaryGitIntegrationTests(unittest.TestCase):
    def git(self, root: Path, *args: str, input_text: str | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args], input=input_text, capture_output=True,
            encoding="utf-8", check=True,
        )
        return result.stdout.strip()

    def test_real_git_temp_repository_produces_complete_inventory_and_details(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            self.git(root, "init", "--quiet")
            blob = self.git(root, "hash-object", "-w", "--stdin", input_text="spec content\n")
            docs_tree = self.git(root, "mktree", input_text=f"100644 blob {blob}\tspec.md\n")
            tree = self.git(root, "mktree", input_text=f"040000 tree {docs_tree}\tdocs\n")
            commit = self.git(root, "commit-tree", tree, "-m", "temporary fixture")
            self.git(root, "update-ref", "refs/heads/main", commit)
            self.git(root, "update-ref", "refs/remotes/origin/main", commit)
            self.git(root, "symbolic-ref", "HEAD", "refs/heads/main")

            original_cwd = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(inventory.main(), 0)
                self.assertEqual(details.main(), 0)
                out = root / "docs/rebaseline/2026-11-17"
                inv_run = json.loads((out / "INVENTORY_RUN.json").read_text(encoding="utf-8"))
                details_run = json.loads((out / "DETAILS_RUN.json").read_text(encoding="utf-8"))
                self.assertEqual(inv_run["status"], "COMPLETE")
                self.assertEqual(details_run["status"], "COMPLETE")
            finally:
                os.chdir(original_cwd)


class CrossProcessGuardTests(unittest.TestCase):
    def start_holder(self, directory: Path) -> subprocess.Popen:
        ready = directory / "holder.ready"
        release = directory / "holder.release"
        code = "\n".join((
            "import sys, time",
            "from pathlib import Path",
            "from scripts.rebaseline_lock import exclusive_guard",
            "directory = Path(sys.argv[1])",
            "context = exclusive_guard(directory)",
            "context.__enter__()",
            "(directory / 'holder.ready').write_text('locked')",
            "print('LOCK_HELD', flush=True)",
            "deadline = time.monotonic() + 30",
            "while not (directory / 'holder.release').exists() and time.monotonic() < deadline:",
            "    time.sleep(0.02)",
            "context.__exit__(None, None, None)",
        ))
        child_env = os.environ.copy()
        existing = child_env.get("PYTHONPATH")
        child_env["PYTHONPATH"] = str(REPO) + (os.pathsep + existing if existing else "")
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(directory)], cwd=REPO, env=child_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        line = process.stdout.readline()
        if line.strip() != "LOCK_HELD":
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            self.fail(f"holder did not acquire guard: {line!r} {stdout!r} {stderr!r}")
        self.assertTrue(ready.exists())
        return process

    def test_second_process_cannot_acquire_guard_until_first_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            holder = self.start_holder(directory)
            try:
                with self.assertRaisesRegex(RuntimeError, "Another rebaseline collector"):
                    with lock_module.exclusive_guard(directory):
                        self.fail("second collector entered an already-held guard")
            finally:
                (directory / "holder.release").touch()
                holder.communicate(timeout=10)
            with lock_module.exclusive_guard(directory):
                self.assertTrue((directory / ".inventory.guard").exists())

    def test_killed_holder_releases_os_lock_and_guard_file_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            holder = self.start_holder(directory)
            guard = directory / ".inventory.guard"
            self.assertTrue(guard.exists())
            guard_identity = guard.stat().st_ino
            holder.kill()
            holder.communicate(timeout=10)
            with lock_module.exclusive_guard(directory):
                self.assertTrue(guard.exists())
                self.assertEqual(guard.stat().st_ino, guard_identity)

    def test_stale_run_marker_is_informational_and_does_not_replace_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            marker = directory / ".inventory.lock"
            marker.write_text("stale-pid:99999999", encoding="ascii")
            with lock_module.exclusive_guard(directory):
                self.assertEqual(marker.read_text(encoding="ascii"), "stale-pid:99999999")
                self.assertTrue((directory / ".inventory.guard").exists())
            self.assertTrue((directory / ".inventory.guard").exists())
            self.assertEqual(marker.read_text(encoding="ascii"), "stale-pid:99999999")


if __name__ == "__main__":
    unittest.main()
