"""Read-only Git/file inventory for the operator-authorized program rebaseline.

Stores hashes and paths, never file contents. Does not follow worktrees, vendors,
dependency folders or secrets. Output is evidence, not an acceptance verdict.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True,
        encoding="utf-8", errors="replace",
    ).stdout


def main() -> None:
    root = Path(git("rev-parse", "--show-toplevel").strip())
    output = root / "docs/rebaseline/2026-11-17/FILE_INVENTORY.json"
    files = []
    for base in ("src", "scripts", "db", "docs", "reports", "tests", "adapters", "testbed", "testlane", ".harness-tools"):
        for path in (root / base).rglob("*"):
            rel = path.relative_to(root)
            if any(p in {"node_modules", ".git", ".worktrees", "__pycache__", "rebaseline"} for p in rel.parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".ps1", ".sql", ".md", ".html", ".json", ".toml", ".yml", ".yaml", ".feature", ".js", ".ts", ".cs", ".bsl", ".xml", ".sh", ".csproj"}:
                continue
            if any(word in path.name.lower() for word in ("credential", "secret", "token")):
                files.append({"path": rel.as_posix(), "content": "EXCLUDED_SENSITIVE_NAME"})
                continue
            content = path.read_bytes()
            files.append({"path": rel.as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    data = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "head": git("rev-parse", "HEAD").strip(),
        "branch": git("branch", "--show-current").strip(),
        "refs": git("for-each-ref", "--format=%(refname) %(objectname)").splitlines(),
        "worktrees": git("worktree", "list", "--porcelain"),
        "tracked_changes": git("diff", "--name-status", "HEAD").splitlines(),
        "files": sorted(files, key=lambda item: item["path"]),
        "limits": "Content hashes only; excluded dependency/worktree trees and sensitive names; no tests or runtime probes.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Inventoried {len(files)} files and {len(data['refs'])} refs; output {output}")
    baseline = git("rev-parse", "origin/main").strip()
    branches = []
    for row in git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/remotes").splitlines():
        ref, sha = row.split()
        merged = subprocess.run(["git", "merge-base", "--is-ancestor", sha, baseline]).returncode == 0
        counts = git("rev-list", "--left-right", "--count", f"{baseline}...{sha}").split()
        branches.append({"ref": ref, "sha": sha, "merged_into_origin_main": merged,
                         "main_only": int(counts[0]), "branch_only": int(counts[1]),
                         "disposition": "PROTECTED" if ref.endswith(("/main", "/master", "/HEAD")) else
                         "MERGED_REVIEW_WORKTREE_BEFORE_CLEANUP" if merged else "RETAIN_RECONCILE_UNIQUE_WORK"})
    (output.parent / "BRANCH_INVENTORY.json").write_text(json.dumps({"baseline": baseline, "branches": branches}, indent=2) + "\n", encoding="utf-8")
    docs = {}
    code = {}
    for row in data["refs"]:
        ref, sha = row.split()
        for item in git("ls-tree", "-r", sha).splitlines():
            meta, path = item.split("\t", 1)
            if meta.split()[1] != "blob":
                continue  # submodule commits remain identified by the Git tree
            blob = meta.split()[2]
            key = path + "@" + blob
            if not path.startswith(("docs/", "reports/", "core/")) and path != "PROJECT_PLAN.md":
                code.setdefault(key, {"path": path, "blob": blob, "refs": []})["refs"].append(ref)
            if path.endswith((".md", ".html", ".json")):
                docs.setdefault(key, {"path": path, "blob": blob, "refs": []})["refs"].append(ref)
    (output.parent / "DOCUMENT_VERSIONS.json").write_text(json.dumps(list(docs.values()), indent=2) + "\n", encoding="utf-8")
    (output.parent / "CODE_VERSIONS.json").write_text(json.dumps(list(code.values()), indent=2) + "\n", encoding="utf-8")
    print(f"Classified {len(branches)} branches, {len(docs)} document versions and {len(code)} code/config/test versions across all refs")


if __name__ == "__main__":
    main()
