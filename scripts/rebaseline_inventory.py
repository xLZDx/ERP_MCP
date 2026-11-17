"""Read-only Git/file inventory for the operator-authorized program rebaseline.

Stores hashes and paths, never file contents. Does not follow worktrees, vendors,
dependency folders or secrets. Output is evidence, not an acceptance verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True,
        encoding="utf-8", errors="replace", timeout=120,
    ).stdout


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(root, run_id):
    output = root / "docs/rebaseline/2026-11-17/FILE_INVENTORY.json"
    files = []
    bases = ("src", "scripts", "db", "docs", "reports", "core", "tests", "adapters", "testbed", "testlane", "governance", "config", "tools", ".harness-tools", ".harness", ".github")
    paths = [p for p in root.iterdir() if p.is_file()]
    for base in bases:
        paths.extend((root / base).rglob("*"))
    for path in paths:
            rel = path.relative_to(root)
            if any(p in {"node_modules", ".git", ".worktrees", "__pycache__", "rebaseline"} for p in rel.parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if path.parent != root and path.suffix.lower() not in {".py", ".ps1", ".sql", ".md", ".html", ".json", ".toml", ".yml", ".yaml", ".feature", ".csv", ".txt", ".rst", ".js", ".ts", ".cs", ".bsl", ".xml", ".sh", ".csproj", ".pdf", ".docx", ".xlsx"} and path.name not in {"Dockerfile", "LICENSE", "NOTICE"}:
                continue
            if path.name == ".git" or path.name.startswith(".env") or any(word in path.name.lower() for word in ("credential", "secret", "token")):
                files.append({"path": rel.as_posix(), "content": "EXCLUDED_SENSITIVE_NAME"})
                continue
            content = path.read_bytes()
            files.append({"path": rel.as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    data = {
        "run_id": run_id,
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
    write_json(output, data)
    print(f"Inventoried {len(files)} files and {len(data['refs'])} refs; output {output}")
    captured_refs = dict(row.split() for row in data["refs"])
    baseline = captured_refs["refs/remotes/origin/main"]
    branches = []
    cache = {}
    for ref, sha in captured_refs.items():
        if not ref.startswith(("refs/heads/", "refs/remotes/")):
            continue
        if sha not in cache:
            result = subprocess.run(["git", "merge-base", "--is-ancestor", sha, baseline], capture_output=True, timeout=120)
            merged = True if result.returncode == 0 else False if result.returncode == 1 else None
            counts = git("rev-list", "--left-right", "--count", f"{baseline}...{sha}").split() if merged is not None else (None, None)
            cache[sha] = (merged, counts, result.returncode)
        merged, counts, ancestry_exit = cache[sha]
        branches.append({"ref": ref, "sha": sha, "merged_into_origin_main": merged,
                         "ancestry_exit": ancestry_exit,
                         "main_only": int(counts[0]) if counts[0] is not None else None, "branch_only": int(counts[1]) if counts[1] is not None else None,
                         "disposition": "PROTECTED" if ref.endswith(("/main", "/master", "/HEAD")) else
                         "UNAVAILABLE" if merged is None else
                         "MERGED_REVIEW_WORKTREE_BEFORE_CLEANUP" if merged else "RETAIN_RECONCILE_UNIQUE_WORK"})
    write_json(output.parent / "BRANCH_INVENTORY.json", {"run_id": run_id, "baseline": baseline, "branches": branches})
    docs = {}
    code = {}
    trees = {}
    for row in data["refs"]:
        ref, sha = row.split()
        if sha not in trees:
            trees[sha] = git("ls-tree", "-r", sha).splitlines()
        for item in trees[sha]:
            meta, path = item.split("\t", 1)
            if meta.split()[1] != "blob":
                continue  # submodule commits remain identified by the Git tree
            blob = meta.split()[2]
            key = path + "@" + blob
            if not path.startswith(("docs/", "reports/", "core/")) and path != "PROJECT_PLAN.md":
                code.setdefault(key, {"path": path, "blob": blob, "refs": []})["refs"].append(ref)
            if path.startswith(("docs/", "reports/", "core/")) or path.endswith((".md", ".html", ".json", ".yaml", ".yml", ".csv", ".feature", ".txt", ".rst")):
                docs.setdefault(key, {"path": path, "blob": blob, "refs": []})["refs"].append(ref)
    write_json(output.parent / "DOCUMENT_VERSIONS.json", list(docs.values()))
    write_json(output.parent / "CODE_VERSIONS.json", list(code.values()))
    names = ("FILE_INVENTORY.json", "BRANCH_INVENTORY.json", "DOCUMENT_VERSIONS.json", "CODE_VERSIONS.json")
    complete = all(b["ancestry_exit"] in (0, 1) for b in branches)
    write_json(output.parent / "INVENTORY_RUN.json", {"run_id": run_id,
        "status": "COMPLETE" if complete else "PARTIAL",
        "baseline": baseline, "files": {name: hashlib.sha256((output.parent / name).read_bytes()).hexdigest() for name in names}})
    print(f"Classified {len(branches)} branches, {len(docs)} document versions and {len(code)} code/config/test versions across all refs")
    return complete


def main():
    root = Path(git("rev-parse", "--show-toplevel").strip())
    out = root / "docs/rebaseline/2026-11-17"
    out.mkdir(parents=True, exist_ok=True)
    lock = out / ".inventory.lock"
    with lock.open("x", encoding="ascii") as stream:
        stream.write(str(os.getpid()))
    run_id = str(uuid.uuid4())
    try:
        write_json(out / "INVENTORY_RUN.json", {"run_id": run_id, "status": "IN_PROGRESS"})
        complete = collect(root, run_id)
    except BaseException as exc:
        write_json(out / "INVENTORY_RUN.json", {"run_id": run_id, "status": "FAILED", "error_type": type(exc).__name__})
        raise
    finally:
        lock.unlink()
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
