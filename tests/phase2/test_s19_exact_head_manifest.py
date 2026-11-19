from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "scripts" / "assemble_s19_exact_head_manifest.py"
OUTPUT_RELATIVE = "reports/evidence/sprints/S19_EXACT_HEAD_MANIFEST.json"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _prepare_repo(tmp_path: Path) -> tuple[Path, str, dict[str, bytes]]:
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "src/service.py": b"source at committed head\n",
        "config/app.json": b'{"mode":"test"}\n',
        "db/schema.sql": b"CREATE TABLE evidence (id text);\n",
        "recipes/run.ps1": b"Write-Output 'synthetic recipe'\n",
        "reports/checks/suite.json": b'{"result":"NOT_RUN","tested_head":null}\n',
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "S19 manifest test")
    _git(root, "config", "user.email", "s19-manifest@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "synthetic exact-head fixture")
    head = _git(root, "rev-parse", "HEAD")

    # A manifest for HEAD must read Git objects, not silently take modified worktree bytes.
    (root / "src/service.py").write_bytes(b"uncommitted working-tree change\n")
    return root, head, files


def _artifact(item: str, category: str, *, path: str | None = None,
              status: str = "RECORDED", reason: str | None = None) -> dict[str, object]:
    return {"item": item, "category": category, "status": status, "path": path, "reason": reason}


def _valid_input(head: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "sprint_id": "S19",
        "head_sha": head,
        "artifacts": [
            _artifact("implementation", "source", path="src/service.py"),
            _artifact("runtime configuration", "configuration", path="config/app.json"),
            _artifact("database contract", "schema", path="db/schema.sql"),
            _artifact("operator recipe", "recipe", path="recipes/run.ps1"),
            _artifact("focused checks", "check_result", status="NOT_RUN",
                      reason="Sprint tests run after all S19 stories are coded."),
        ],
    }


def _run_builder(root: Path, inventory: dict[str, object], output: str = OUTPUT_RELATIVE
                 ) -> subprocess.CompletedProcess[str]:
    inventory_path = root / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(BUILDER), "--root", str(root), "--input", str(inventory_path),
         "--output", output], cwd=REPO_ROOT, capture_output=True, text=True,
    )


def test_builder_hashes_exact_git_head_and_marks_missing_checks_non_authorizing(tmp_path: Path) -> None:
    root, head, committed_files = _prepare_repo(tmp_path)
    result = _run_builder(root, _valid_input(head))

    assert result.returncode == 0, result.stderr
    manifest = json.loads((root / OUTPUT_RELATIVE).read_text(encoding="utf-8"))
    assert manifest["source_head"] == head
    by_item = {artifact["item"]: artifact for artifact in manifest["artifacts"]}
    recorded = by_item["implementation"]
    assert recorded == {
        "item": "implementation",
        "category": "source",
        "status": "RECORDED_UNVERIFIED",
        "path": "src/service.py",
        "sha256": hashlib.sha256(committed_files["src/service.py"]).hexdigest(),
        "reason": None,
    }
    assert recorded["sha256"] != hashlib.sha256((root / "src/service.py").read_bytes()).hexdigest()
    assert by_item["focused checks"] == {
        "item": "focused checks",
        "category": "check_result",
        "status": "NOT_RUN",
        "path": None,
        "sha256": None,
        "reason": "Sprint tests run after all S19 stories are coded.",
    }
    assert {artifact["category"] for artifact in manifest["artifacts"]} == {
        "source", "configuration", "schema", "recipe", "check_result",
    }
    assert manifest["assessment"] == "INDEX_ONLY_UNVERIFIED"
    assert manifest["authorization"] == "NONE"
    assert not {"gate_status", "engineering_status", "production_authorization"} & manifest.keys()


def test_builder_output_is_byte_deterministic_for_same_commit_and_inventory(tmp_path: Path) -> None:
    root, head, _ = _prepare_repo(tmp_path)
    inventory = _valid_input(head)

    first = _run_builder(root, inventory)
    first_bytes = (root / OUTPUT_RELATIVE).read_bytes() if first.returncode == 0 else b""
    second = _run_builder(root, inventory)

    assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
    assert first_bytes == (root / OUTPUT_RELATIVE).read_bytes()


def test_builder_requires_every_artifact_category_to_be_explicitly_present(tmp_path: Path) -> None:
    root, head, _ = _prepare_repo(tmp_path)
    inventory = _valid_input(head)
    inventory["artifacts"] = inventory["artifacts"][:-1]  # type: ignore[index]

    result = _run_builder(root, inventory)

    assert result.returncode != 0
    assert "every required category must be represented" in result.stderr
    assert not (root / OUTPUT_RELATIVE).exists()


@pytest.mark.parametrize("bad_path", ["../outside.txt", "src/../../outside.txt", "/outside.txt", "src\\service.py"])
def test_builder_rejects_unsafe_or_absolute_artifact_paths(tmp_path: Path, bad_path: str) -> None:
    root, head, _ = _prepare_repo(tmp_path)
    inventory = _valid_input(head)
    inventory["artifacts"][0]["path"] = bad_path  # type: ignore[index]

    result = _run_builder(root, inventory)

    assert result.returncode != 0
    assert not (root / OUTPUT_RELATIVE).exists()


def test_builder_rejects_artifact_absent_from_selected_head_without_replacing_prior_output(tmp_path: Path) -> None:
    root, head, _ = _prepare_repo(tmp_path)
    output = root / OUTPUT_RELATIVE
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous manifest remains intact\n")
    inventory = _valid_input(head)
    inventory["artifacts"][0]["path"] = "src/not-in-head.py"  # type: ignore[index]

    result = _run_builder(root, inventory)

    assert result.returncode != 0
    assert "missing from exact HEAD" in result.stderr
    assert output.read_bytes() == b"previous manifest remains intact\n"


def test_builder_rejects_abbreviated_commit_and_output_outside_manifest_directory(tmp_path: Path) -> None:
    root, head, _ = _prepare_repo(tmp_path)
    short_head = _valid_input(head)
    short_head["head_sha"] = head[:12]
    short_result = _run_builder(root, short_head)
    assert short_result.returncode != 0

    valid = _valid_input(head)
    outside_result = _run_builder(root, valid, "reports/outside.json")
    assert outside_result.returncode != 0
    assert not (root / "reports/outside.json").exists()

