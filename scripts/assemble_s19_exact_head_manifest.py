"""Build a non-authorizing S19 index of artifacts bound to an exact Git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("reports/evidence/sprints")
SPRINT_ID = re.compile(r"^S(?:1[1-9])$")
COMMIT_ID = re.compile(r"^[0-9a-f]{40}$")
CATEGORIES = {"source", "configuration", "schema", "recipe", "check_result"}
NON_AUTHORIZING_NOTE = (
    "Artifact presence and SHA-256 binding do not validate result contents, pass a gate, "
    "establish C1/engineering completion or release readiness, or authorize production."
)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], cwd=root, text=True, timeout=30,
    ).strip()


def _commit_tree(root: Path, head: str) -> dict[str, tuple[str, str]]:
    if not isinstance(head, str) or not COMMIT_ID.fullmatch(head):
        raise ValueError("head_sha must be a full lowercase Git commit SHA")
    resolved = _git(root, "rev-parse", "--verify", f"{head}^{{commit}}")
    if resolved != head:
        raise ValueError("head_sha does not identify the exact commit object")
    raw = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-tree", "-r", "-z", head],
        cwd=root, timeout=30,
    )
    tree: dict[str, tuple[str, str]] = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, path_bytes = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split(" ")
        path = path_bytes.decode("utf-8", errors="strict")
        tree[path] = (mode, kind)
    return tree


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("artifact path must be a non-empty repository-relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("artifact path must not be absolute or traverse directories")
    return path.as_posix()


def build_manifest(root: Path, source: Any) -> dict[str, Any]:
    root = root.resolve()
    if not isinstance(source, dict) or set(source) != {"schema_version", "sprint_id", "head_sha", "artifacts"}:
        raise ValueError("input must contain only schema_version, sprint_id, head_sha, and artifacts")
    if type(source["schema_version"]) is not int or source["schema_version"] != 1:
        raise ValueError("unsupported input schema_version")
    sprint_id = source["sprint_id"]
    if not isinstance(sprint_id, str) or not SPRINT_ID.fullmatch(sprint_id):
        raise ValueError("sprint_id must be one of S11 through S19")
    head = source["head_sha"]
    tree = _commit_tree(root, head)
    artifacts = source["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("artifacts must be a non-empty list")

    seen: set[tuple[str, str]] = set()
    categories_seen: set[str] = set()
    recorded: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"item", "category", "status", "path", "reason"}:
            raise ValueError("each artifact must contain item, category, status, path, and reason")
        name, category, status = item["item"], item["category"], item["status"]
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("artifact item must be a non-empty name of at most 120 characters")
        if not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError("unsupported artifact category")
        categories_seen.add(category)
        key = (category, name)
        if key in seen:
            raise ValueError("duplicate artifact category/item")
        seen.add(key)

        if status == "RECORDED":
            path = _relative_path(item["path"])
            if item["reason"] is not None:
                raise ValueError("RECORDED artifacts must have reason=null")
            tree_item = tree.get(path)
            if tree_item is None:
                raise ValueError(f"artifact is missing from exact HEAD: {path}")
            mode, kind = tree_item
            if kind != "blob" or mode == "120000":
                raise ValueError(f"artifact must be a regular Git file, not a symlink: {path}")
            content = subprocess.check_output(
                ["git", "--no-replace-objects", "show", f"{head}:{path}"],
                cwd=root, timeout=30,
            )
            recorded.append({
                "item": name,
                "category": category,
                "status": "RECORDED_UNVERIFIED",
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "reason": None,
            })
        elif status == "NOT_RUN":
            reason = item["reason"]
            if item["path"] is not None or not isinstance(reason, str) or not reason.strip():
                raise ValueError("NOT_RUN requires path=null and a non-empty reason")
            recorded.append({
                "item": name,
                "category": category,
                "status": "NOT_RUN",
                "path": None,
                "sha256": None,
                "reason": reason.strip(),
            })
        else:
            raise ValueError("artifact status must be RECORDED or NOT_RUN")

    missing = CATEGORIES - categories_seen
    if missing:
        raise ValueError("every required category must be represented, including NOT_RUN: "
                         + ", ".join(sorted(missing)))

    recorded.sort(key=lambda x: (x["category"], x["item"].casefold()))
    return {
        "schema_version": 1,
        "manifest_kind": "EXACT_HEAD_EVIDENCE_INDEX",
        "sprint_id": sprint_id,
        "source_head": head,
        "artifacts": recorded,
        "assessment": "INDEX_ONLY_UNVERIFIED",
        "authorization": "NONE",
        "limitations": [NON_AUTHORIZING_NOTE],
    }


def _output_path(root: Path, sprint_id: str, output: Path) -> Path:
    expected = (root / MANIFEST_DIR / f"{sprint_id}_EXACT_HEAD_MANIFEST.json").resolve()
    try:
        resolved = output.resolve()
        resolved.relative_to((root / MANIFEST_DIR).resolve())
    except ValueError as exc:
        raise ValueError("output must be inside reports/evidence/sprints") from exc
    if resolved != expected:
        raise ValueError("output must use the sprint-specific exact-head manifest filename")
    current = root
    for part in (MANIFEST_DIR / f"{sprint_id}_EXACT_HEAD_MANIFEST.json").parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("manifest output path cannot contain symlinks")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON artifact inventory")
    parser.add_argument("--output", required=True, type=Path, help="reports/evidence/sprints/<sprint>_EXACT_HEAD_MANIFEST.json")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    input_path = args.input if args.input.is_absolute() else root / args.input
    output_arg = args.output if args.output.is_absolute() else root / args.output
    if input_path.resolve() == output_arg.resolve():
        raise ValueError("input and output paths must differ")
    source = json.loads(input_path.read_text(encoding="utf-8"))
    manifest = build_manifest(root, source)
    output_path = _output_path(root, manifest["sprint_id"], output_arg)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_path.parent,
            prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    print(f"S19 exact-head evidence index written (non-authorizing): {output_path}")


if __name__ == "__main__":
    main()
