"""Read-only patch-equivalence and worktree-state evidence. Never deletes files."""
import json
import hashlib
import subprocess
from pathlib import Path

try:
    from scripts.rebaseline_lock import exclusive_guard
except ModuleNotFoundError:
    from rebaseline_lock import exclusive_guard


def run(args, cwd=None):
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "error": "timeout after 120 seconds"}


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(out):
    manifest = json.loads((out / "INVENTORY_RUN.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "COMPLETE":
        raise RuntimeError("Source inventory run is incomplete")
    content = (out / "BRANCH_INVENTORY.json").read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest["files"]["BRANCH_INVENTORY.json"]:
        raise RuntimeError("Source branch inventory does not match completed run")
    inventory = json.loads(content)
    if inventory.get("run_id") != manifest["run_id"] or inventory["baseline"] != manifest["baseline"]:
        raise RuntimeError("Source inventory provenance mismatch")
    baseline = inventory["baseline"]
    write_json(out / "DETAILS_RUN.json", {"run_id": manifest["run_id"], "status": "IN_PROGRESS", "baseline": baseline})
    branches = []
    cache = {}
    for b in inventory["branches"]:
        if b["sha"] not in cache:
            cache[b["sha"]] = run(["cherry", baseline, b["sha"]]) if b["merged_into_origin_main"] is not True else {"exit_code": 0, "stdout": ""}
        result = cache[b["sha"]]
        lines = result.get("stdout", "").splitlines()
        available = result["exit_code"] == 0
        branches.append({**b, "baseline": baseline, "run_id": manifest["run_id"], "patch_comparison": result, "comparison_available": available,
                         "unique_patch_count": sum(x.startswith("+") for x in lines) if available else None,
                         "equivalent_patch_count": sum(x.startswith("-") for x in lines) if available else None})
        write_json(out / "PATCH_EQUIVALENCE.json", branches)
        print("Compared", b["ref"], flush=True)
    listing = run(["worktree", "list", "--porcelain"])
    if listing["exit_code"] != 0:
        raise RuntimeError("Worktree listing unavailable")
    chunks = listing["stdout"].strip().split("\n\n")
    states = []
    for chunk in chunks:
        fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in chunk.splitlines())
        path = fields["worktree"]
        status = run(["status", "--porcelain=v1", "--untracked-files=all"], cwd=path)
        lines = status.get("stdout", "").splitlines()
        states.append({**fields, "status_exit": status["exit_code"],
                       "changed_count": len(lines) if status["exit_code"] == 0 else None, "changes": lines,
                       "cleanup": "NOT_AUTHORIZED_BY_INVENTORY; process/junction/ignored-file checks required"})
        write_json(out / "WORKTREE_STATES.json", states)
        print("Inspected", path, len(lines), flush=True)
    names = ("PATCH_EQUIVALENCE.json", "WORKTREE_STATES.json")
    complete = all(r["comparison_available"] for r in branches) and all(r["status_exit"] == 0 for r in states)
    write_json(out / "DETAILS_RUN.json", {"run_id": manifest["run_id"], "baseline": baseline,
        "status": "COMPLETE" if complete else "PARTIAL",
        "files": {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in names}})
    return complete


def main():
    out = Path("docs/rebaseline/2026-11-17")
    out.mkdir(parents=True, exist_ok=True)
    with exclusive_guard(out):
        marker = out / ".inventory.lock"
        marker.write_text("details", encoding="ascii")
        try:
            write_json(out / "DETAILS_RUN.json", {"status": "IN_PROGRESS"})
            complete = collect(out)
        except BaseException as exc:
            write_json(out / "DETAILS_RUN.json", {"status": "FAILED", "error_type": type(exc).__name__})
            raise
        finally:
            marker.unlink(missing_ok=True)
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
