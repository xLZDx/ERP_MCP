"""Read-only patch-equivalence and worktree-state evidence. Never deletes files."""
import json
import subprocess
from pathlib import Path


def run(args, cwd=None):
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "error": "timeout after 120 seconds"}


def main():
    out = Path("docs/rebaseline/2026-11-17")
    inventory = json.loads((out / "BRANCH_INVENTORY.json").read_text(encoding="utf-8"))
    branches = []
    cache = {}
    for b in inventory["branches"]:
        if b["sha"] not in cache:
            cache[b["sha"]] = run(["cherry", "origin/main", b["sha"]]) if not b["merged_into_origin_main"] else {"exit_code": 0, "stdout": ""}
        result = cache[b["sha"]]
        lines = result.get("stdout", "").splitlines()
        available = result["exit_code"] == 0
        branches.append({**b, "patch_comparison": result, "comparison_available": available,
                         "unique_patch_count": sum(x.startswith("+") for x in lines) if available else None,
                         "equivalent_patch_count": sum(x.startswith("-") for x in lines) if available else None})
        (out / "PATCH_EQUIVALENCE.json").write_text(json.dumps(branches, indent=2) + "\n", encoding="utf-8")
        print("Compared", b["ref"], flush=True)
    chunks = run(["worktree", "list", "--porcelain"])["stdout"].strip().split("\n\n")
    states = []
    for chunk in chunks:
        fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in chunk.splitlines())
        path = fields["worktree"]
        status = run(["status", "--porcelain=v1", "--untracked-files=all"], cwd=path)
        lines = status.get("stdout", "").splitlines()
        states.append({**fields, "status_exit": status["exit_code"],
                       "changed_count": len(lines) if status["exit_code"] == 0 else None, "changes": lines,
                       "cleanup": "NOT_AUTHORIZED_BY_INVENTORY; process/junction/ignored-file checks required"})
        (out / "WORKTREE_STATES.json").write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")
        print("Inspected", path, len(lines), flush=True)


if __name__ == "__main__":
    main()
