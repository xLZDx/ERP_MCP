from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_sha256() -> str:
    tracked_and_untracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    digest = hashlib.sha256()
    for raw_path in sorted(path for path in tracked_and_untracked if path):
        path = ROOT / raw_path.decode("utf-8")
        digest.update(raw_path)
        digest.update(b"\0")
        if path.is_dir():
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            digest.update(revision.encode("ascii"))
        else:
            digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a local image's CI provenance and SBOM hash")
    parser.add_argument("--image", required=True)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstream-sha")
    args = parser.parse_args()

    lock_path = ROOT / args.lock
    sbom_path = args.sbom.resolve()
    output_path = args.output.resolve()
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("components"):
        raise SystemExit("Trivy output is not a non-empty CycloneDX SBOM")

    inspected = json.loads(
        subprocess.run(
            ["docker", "image", "inspect", args.image],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )[0]
    worktree_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    provenance = {
        "schema": "erp-mcp-image-provenance/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "source_tree": {
            "sha256": source_tree_sha256(),
            "worktree_clean": not bool(worktree_status),
        },
        "image": {
            "reference": args.image,
            "config_digest": inspected["Id"],
            "repo_digests": inspected.get("RepoDigests", []),
            "os": inspected.get("Os"),
            "architecture": inspected.get("Architecture"),
            "labels": inspected.get("Config", {}).get("Labels") or {},
        },
        "base_image": args.base_image,
        "dependency_lock": {
            "path": args.lock.replace("\\", "/"),
            "sha256": sha256(lock_path),
        },
        "upstream_sha": args.upstream_sha,
        "sbom": {
            "format": "CycloneDX JSON",
            "path": sbom_path.name,
            "component_count": len(sbom["components"]),
            "sha256": sha256(sbom_path),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
