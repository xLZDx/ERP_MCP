import hashlib
import json

import pytest

from scripts.assemble_release_evidence import IMAGES, ODATA_SHA, SUITES, assemble, image_evidence
from scripts.assemble_release_evidence import test_evidence as verify_tests
from scripts.summarize_test_results import summarize
from tests.test_engineering_checkpoint import prepare

COMMIT = "a" * 40


def image_fixture(path, name):
    path.mkdir(parents=True)
    stem = IMAGES[name]
    sbom = path / f"{stem}.cdx.json"
    sbom.write_text(json.dumps({"bomFormat": "CycloneDX", "components": [{"name": "synthetic"}]}))
    provenance = {"schema": "erp-mcp-image-provenance/v1", "source_commit": COMMIT,
                  "source_tree": {"worktree_clean": True},
                  "image": {"reference": f"{stem}:ci", "config_digest": "sha256:" + "b" * 64},
                  "upstream_sha": ODATA_SHA if name == "odata_sidecar" else None,
                  "sbom": {"sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(), "component_count": 1}}
    target = path / f"{stem}-provenance.json"
    target.write_text(json.dumps(provenance))
    return target, provenance, sbom


@pytest.mark.parametrize("name", list(IMAGES))
def test_image_evidence_requires_exact_revision_and_real_sbom_hash(tmp_path, name):
    directory = tmp_path / name
    target, provenance, sbom = image_fixture(directory, name)
    result = image_evidence(directory, name=name, expected_commit=COMMIT)
    assert result["registry_publication_proven"] is False
    assert result["registry_manifest_digest"] is None
    sbom.write_text(json.dumps({"bomFormat": "CycloneDX", "components": [{"name": "changed"}]}))
    with pytest.raises(ValueError, match="SBOM"):
        image_evidence(directory, name=name, expected_commit=COMMIT)
    provenance["source_commit"] = "c" * 40
    target.write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="revision"):
        image_evidence(directory, name=name, expected_commit=COMMIT)


@pytest.mark.parametrize("mutation", ["dirty", "digest", "reference", "upstream", "component_count"])
def test_invalid_sidecar_provenance_cannot_assemble(mutation, tmp_path):
    target, provenance, _sbom = image_fixture(tmp_path / "sidecar", "odata_sidecar")
    if mutation == "dirty":
        provenance["source_tree"]["worktree_clean"] = False
    elif mutation == "digest":
        provenance["image"]["config_digest"] = "not-an-image-digest"
    elif mutation == "reference":
        provenance["image"]["reference"] = "unrelated:ci"
    elif mutation == "upstream":
        provenance["upstream_sha"] = "c" * 40
    else:
        provenance["sbom"]["component_count"] = 42
    target.write_text(json.dumps(provenance))
    with pytest.raises(ValueError):
        image_evidence(target.parent, name="odata_sidecar", expected_commit=COMMIT)


def test_dependency_locks_must_match_current_source_content_and_exact_paths(tmp_path):
    target, provenance, _sbom = image_fixture(tmp_path / "image", "odata_sidecar")
    root = tmp_path / "source"
    locks = ["vendor/reference/1c-odata-v3/pnpm-lock.yaml", "adapters/odata-sidecar/package-lock.json"]
    records = []
    for name in locks:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic locked dependency\n")
        records.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    provenance["dependency_lock"], provenance["additional_dependency_locks"] = records[0], records[1:]
    target.write_text(json.dumps(provenance))
    assert len(image_evidence(target.parent, name="odata_sidecar", expected_commit=COMMIT, root=root)["dependency_locks"]) == 2
    (root / locks[1]).write_bytes(b"changed dependency\n")
    with pytest.raises(ValueError, match="lock content"):
        image_evidence(target.parent, name="odata_sidecar", expected_commit=COMMIT, root=root)
    provenance["additional_dependency_locks"][0]["path"] = "../../private-file"
    target.write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="lock inventory"):
        image_evidence(target.parent, name="odata_sidecar", expected_commit=COMMIT, root=root)


def test_junit_summary_counts_actual_cases_not_declared_totals_and_contains_no_raw_data(tmp_path):
    report = tmp_path / "private.xml"
    report.write_text('<testsuites tests="999"><testsuite><testcase name="PRIVATE-CUSTOMER-NAME"/>'
                      '<testcase name="private skipped"><skipped message="PRIVATE-DOCUMENT"/></testcase>'
                      '</testsuite></testsuites>')
    result = summarize(report, suite_id="gateway-pytest", source_commit=COMMIT, exit_code=0)
    assert result["counts"] == {"tests": 2, "failures": 0, "errors": 0, "skipped": 1}
    assert result["passed"] is True and result["native_evidence_level_inferred"] is False
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("body,exit_code", [
    ('<testsuite/>', 0), ('<testsuite><testcase><failure>private</failure></testcase></testsuite>', 0),
    ('<testsuite><error>private</error></testsuite>', 0), ('<testsuite><testcase/></testsuite>', 1),
])
def test_empty_failed_or_nonzero_test_process_never_proves_pass(tmp_path, body, exit_code):
    report = tmp_path / "report.xml"
    report.write_text(body)
    assert summarize(report, suite_id="gateway-pytest", source_commit=COMMIT, exit_code=exit_code)["passed"] is False


def summaries(path):
    path.mkdir()
    for suite_id in SUITES:
        junit = path / "temporary.xml"
        junit.write_text('<testsuite><testcase name="synthetic"/></testsuite>')
        summary = summarize(junit, suite_id=suite_id, source_commit=COMMIT, exit_code=0)
        (path / f"{suite_id}.summary.json").write_text(json.dumps(summary))


def test_test_summaries_are_required_for_all_engines_platform_and_gateway(tmp_path):
    path = tmp_path / "tests"
    summaries(path)
    assert set(verify_tests(path, expected_commit=COMMIT)) == SUITES
    (path / "windows-rsv-privacy.summary.json").unlink()
    with pytest.raises(ValueError, match="unavailable"):
        verify_tests(path, expected_commit=COMMIT)


@pytest.mark.parametrize("mutation", ["revision", "counts", "skip", "case", "bool_count", "passed"])
def test_stale_or_fabricated_test_summaries_fail_validation(tmp_path, mutation):
    directory = tmp_path / "tests"
    summaries(directory)
    path = directory / "gateway-pytest.summary.json"
    data = json.loads(path.read_text())
    if mutation == "revision":
        data["source_commit"] = "c" * 40
    elif mutation == "counts":
        data["counts"]["tests"] = 999
    elif mutation == "skip":
        data["counts"]["skipped"] = 1
    elif mutation == "case":
        data["case_outcomes"][0]["case_id_sha256"] = "PRIVATE-IDENTITY"
    elif mutation == "bool_count":
        data["counts"]["tests"] = True
    else:
        data["passed"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify_tests(directory, expected_commit=COMMIT)


def test_complete_assembly_binds_two_images_all_test_suites_and_same_revision_report_links(tmp_path):
    from scripts.engineering_checkpoint import REPORTS, implementation_fingerprint

    root, artifacts = tmp_path / "source", tmp_path / "artifacts"
    root.mkdir()
    prepare(root)
    for name in ("reports/RISK_STATUS.md", "docs/REQUIREMENTS_TRACEABILITY.md",
                 "docs/SCOPE_FREEZE_BASELINE_2026-10-06.md", "vendor/UPSTREAMS.md", "vendor/intake.json"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("synthetic source reference\n")
    for name in IMAGES:
        target, provenance, _sbom = image_fixture(artifacts / name, name)
        lock_names = ["requirements-runtime.lock"] if name == "gateway" else [
            "vendor/reference/1c-odata-v3/pnpm-lock.yaml", "adapters/odata-sidecar/package-lock.json"]
        locks = []
        for lock_name in lock_names:
            path = root / lock_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic dependency lock\n")
            locks.append({"path": lock_name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        provenance["dependency_lock"], provenance["additional_dependency_locks"] = locks[0], locks[1:]
        target.write_text(json.dumps(provenance))
    summaries(artifacts / "tests")
    checkpoint_path = root / "reports/CURRENT_ENGINEERING_CHECKPOINT.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    old = checkpoint["implementation_sha256"]
    checkpoint["implementation_sha256"] = implementation_fingerprint(root)
    checkpoint_path.write_text(json.dumps(checkpoint))
    for name in REPORTS:
        path = root / name
        path.write_text(path.read_text().replace(old, checkpoint["implementation_sha256"]))
    result = assemble(root, artifacts, expected_commit=COMMIT, pr_head_commit="b" * 40, run_id="12345678901")
    assert result["production_decision"] == "NO-GO" and result["dod_status"] == "PARTIAL"
    assert result["mandatory_native_and_operator_gates_closed"] is False
    assert result["tested_revision"] != result["pr_head_commit"]
    assert set(result["images"]) == set(IMAGES) and set(result["tests"]) == SUITES
    assert all(f"/blob/{COMMIT}/" in reference["url"] for reference in result["references"].values())
