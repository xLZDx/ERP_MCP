"""Assemble same-revision image/SBOM/test metadata; this is never a production GO decision."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from scripts.engineering_checkpoint import check_checkpoint

HASH = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
ODATA_SHA = "cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5"
IMAGES = {"gateway": "erp-mcp-gateway", "odata_sidecar": "erp-mcp-odata-sidecar"}
SUITES = {"gateway-pytest", "odata-client", "odata-metadata", "odata-wrapper", "windows-rsv-privacy"}


def read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 64_000_000:
        raise ValueError("release evidence file unavailable")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("release evidence must be an object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_evidence(directory: Path, *, name: str, expected_commit: str, root: Path | None = None) -> dict:
    stem = IMAGES[name]
    sbom_path = directory / f"{stem}.cdx.json"
    provenance_path = directory / f"{stem}-provenance.json"
    provenance, sbom = read_json(provenance_path), read_json(sbom_path)
    if provenance.get("schema") != "erp-mcp-image-provenance/v1" or provenance.get("source_commit") != expected_commit:
        raise ValueError("image provenance revision mismatch")
    if provenance.get("source_tree", {}).get("worktree_clean") is not True:
        raise ValueError("image was built from a dirty worktree")
    digest = provenance.get("image", {}).get("config_digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("image config digest is invalid")
    if provenance["image"].get("reference") != f"{stem}:ci":
        raise ValueError("unexpected candidate image reference")
    expected_sbom = provenance.get("sbom", {})
    if (sbom.get("bomFormat") != "CycloneDX" or not isinstance(sbom.get("components"), list)
            or not sbom["components"] or expected_sbom.get("sha256") != sha256(sbom_path)
            or expected_sbom.get("component_count") != len(sbom["components"])):
        raise ValueError("SBOM content/provenance mismatch")
    if name == "odata_sidecar" and provenance.get("upstream_sha") != ODATA_SHA:
        raise ValueError("OData upstream revision mismatch")
    dependency_locks = []
    if root is not None:
        expected_lock = "requirements-runtime.lock" if name == "gateway" else "vendor/reference/1c-odata-v3/pnpm-lock.yaml"
        locks = [provenance.get("dependency_lock", {}), *provenance.get("additional_dependency_locks", [])]
        expected_paths = {expected_lock} | ({"adapters/odata-sidecar/package-lock.json"} if name == "odata_sidecar" else set())
        if {item.get("path") for item in locks} != expected_paths or len(locks) != len(expected_paths):
            raise ValueError("dependency lock inventory mismatch")
        for lock in locks:
            if lock.get("sha256") != sha256(root / lock["path"]):
                raise ValueError("dependency lock content mismatch")
            dependency_locks.append({"path": lock["path"], "sha256": lock["sha256"]})
    return {"source_commit": expected_commit, "image_reference": f"{stem}:ci",
            "config_digest": digest, "registry_manifest_digest": None,
            "registry_publication_proven": False, "sbom_sha256": sha256(sbom_path),
            "component_count": len(sbom["components"]), "provenance_sha256": sha256(provenance_path),
            "dependency_locks": dependency_locks}


def test_evidence(directory: Path, *, expected_commit: str) -> dict:
    summaries = {}
    for suite_id in sorted(SUITES):
        path = directory / f"{suite_id}.summary.json"
        summary = read_json(path)
        counts = summary.get("counts", {})
        if (type(summary.get("schema_version")) is not int or summary.get("schema_version") != 1 or summary.get("suite_id") != suite_id
                or summary.get("source_commit") != expected_commit
                or summary.get("passed") is not True or type(summary.get("exit_code")) is not int or summary.get("exit_code") != 0
                or not isinstance(summary.get("junit_sha256"), str) or not HASH.fullmatch(summary["junit_sha256"])
                or summary.get("raw_test_output_included") is not False
                or summary.get("native_evidence_level_inferred") is not False):
            raise ValueError("test summary identity/outcome mismatch")
        if (set(counts) != {"tests", "failures", "errors", "skipped"}
                or any(type(value) is not int or value < 0 for value in counts.values())
                or counts["tests"] <= 0 or counts["failures"] or counts["errors"]
                or counts["skipped"] > counts["tests"]):
            raise ValueError("invalid executed test counts")
        outcomes = summary.get("case_outcomes")
        if not isinstance(outcomes, list) or len(outcomes) != counts["tests"]:
            raise ValueError("test cases/counts mismatch")
        identifiers = set()
        for case in outcomes:
            if (not isinstance(case, dict) or set(case) != {"case_id_sha256", "outcome"}
                    or not isinstance(case["case_id_sha256"], str) or not HASH.fullmatch(case["case_id_sha256"])
                    or case["case_id_sha256"] in identifiers or case["outcome"] not in {"PASS", "SKIP"}):
                raise ValueError("invalid executed test case manifest")
            identifiers.add(case["case_id_sha256"])
        if sum(case["outcome"] == "SKIP" for case in outcomes) != counts["skipped"]:
            raise ValueError("test skip counts mismatch")
        summaries[suite_id] = {"counts": counts, "junit_sha256": summary["junit_sha256"],
                               "summary_sha256": sha256(path), "native_closure_inferred": False}
    return summaries


def assemble(root: Path, artifacts: Path, *, expected_commit: str, pr_head_commit: str, run_id: str) -> dict:
    if (not COMMIT.fullmatch(expected_commit) or not COMMIT.fullmatch(pr_head_commit)
            or not re.fullmatch(r"[0-9]{8,20}", run_id)):
        raise ValueError("invalid release revision/run identity")
    checkpoint = check_checkpoint(root)
    images = {name: image_evidence(artifacts / name, name=name, expected_commit=expected_commit, root=root) for name in IMAGES}
    tests = test_evidence(artifacts / "tests", expected_commit=expected_commit)
    public_files = ["reports/CURRENT_ENGINEERING_CHECKPOINT.json", "reports/IMPLEMENTATION_STATUS.md",
                    "reports/DOD_STATUS.md", "reports/RISK_STATUS.md", "docs/REQUIREMENTS_TRACEABILITY.md",
                    "docs/SCOPE_FREEZE_BASELINE_2026-10-06.md", "vendor/UPSTREAMS.md", "vendor/intake.json"]
    references = {name: {"sha256": sha256(root / name),
                        "url": f"https://github.com/xLZDx/ERP_MCP/blob/{expected_commit}/{name}"} for name in public_files}
    return {"schema_version": 1, "package_status": "ASSEMBLED_ENGINEERING_EVIDENCE_ONLY",
            "tested_revision": expected_commit, "pr_head_commit": pr_head_commit,
            "ci_run_id": run_id, "implementation_sha256": checkpoint["implementation_sha256"],
            "production_decision": "NO-GO", "dod_status": "PARTIAL", "images": images,
            "tests": tests, "references": references, "native_evidence_level_inferred": False,
            "upstreams": {"odata": ODATA_SHA, "aprovodka": "7b62c90e1fe74324605dc28d76f195200bb97252",
                          "rsv_data": "76fed8e6e16833fee1514969841b8d9a61c7c152",
                          "legacy_gpl_isolated_only": "fe12903af7a367a9d67dd055c13f4b59bb59d83c"},
            "mandatory_native_and_operator_gates_closed": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--pr-head-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(Path(__file__).resolve().parents[1], args.artifacts, expected_commit=args.commit,
                      pr_head_commit=args.pr_head_commit, run_id=args.run_id)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
