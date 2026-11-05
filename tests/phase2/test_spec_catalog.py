"""Offline specification quality checks; NOT product or native-1C acceptance."""
import hashlib
import importlib.util
import json
import re
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "docs" / "phase2" / "spec-v0.1" / "ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08"
ZIP = ROOT / "docs" / "phase2" / "artifacts" / "ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08.zip"
SPEC_BUILDER_PATH = ROOT / "scripts" / "phase2" / "build_spec_bundle.py"


def load(rel):
    return yaml.safe_load((PKG / rel).read_text(encoding="utf-8"))


def load_spec_builder():
    spec = importlib.util.spec_from_file_location("phase2_spec_bundle_builder", SPEC_BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def catalogs():
    return load("requirements.yaml"), load("stories.yaml"), load("test_cases.yaml")


def test_counts_and_unique_ids(catalogs):
    requirements, stories, cases = catalogs
    assert (len(requirements), len(stories), len(cases)) == (28, 48, 144)
    for items in catalogs:
        assert len({x["id"] for x in items}) == len(items)


def test_all_requirements_traced(catalogs):
    requirements, stories, cases = catalogs
    req_ids = {r["id"] for r in requirements}
    story_ids = {s["id"] for s in stories}
    assert {r for s in stories for r in s["requirements"]} <= req_ids
    assert {c["story"] for c in cases} == story_ids
    assert all(set(c["requirements"]) <= req_ids for c in cases)


def test_not_run_is_explicit(catalogs):
    _, _, cases = catalogs
    assert all(c["actual_status"] == "NOT_RUN" for c in cases)


def test_tc001_bounded_acceptance_is_separate_from_product_status(catalogs):
    _, _, cases = catalogs
    tc001 = [case for case in cases if case["id"] == "R2-TC-001"]
    assert len(tc001) == 1
    tc001 = tc001[0]
    assert tc001["actual_status"] == "NOT_RUN"
    bounded = tc001["bounded_acceptance"]
    assert bounded == load("docs/11_TC001_BOUNDED_ACCEPTANCE.yaml")["bounded_acceptance"]
    assert bounded["status"] == "SATISFIED"
    assert bounded["criterion"] == "R1 unchanged"
    assert bounded["scope"] == "exercised R1 public MCP compatibility only; not full R1 equivalence"
    assert bounded["exact_head"] == "5336867aab8070139e61fb39b6b4ba73a9ac59b0"
    assert bounded["evidence_sha256"] == "6669c29217d5729633c71d694912ee278b3ca8486b7804469f50da2967001853"
    assert bounded["gpt_pm_decision_request_id"] == "3f51d1d2-49dc-49d5-871c-f916405d35d4"
    assert "does not change the canonical product_status from NOT_RUN" in bounded["transition_rule"]
    assert "Does not establish full R1 behavioral equivalence." in bounded["limitations"]
    assert "Does not establish production acceptance, deployment, merge, or release authority." in bounded["limitations"]
    assert bounded["source_evidence_path"] == "artifacts/phase2/r2-tc001-5336867-evidence.json"
    assert not Path(bounded["evidence_path"]).is_absolute()
    assert ".." not in Path(bounded["evidence_path"]).parts
    assert all(
        "bounded_acceptance" not in case
        for case in cases
        if case["id"] != "R2-TC-001"
    )

    evidence_path = PKG / bounded["evidence_path"]
    evidence_bytes = evidence_path.read_bytes()
    assert hashlib.sha256(evidence_bytes).hexdigest() == bounded["evidence_sha256"]
    evidence = json.loads(evidence_bytes)
    assert evidence["scenario"] == "R2-TC-001"
    assert evidence["candidate"]["commit"] == bounded["exact_head"]
    assert evidence["scope"] == bounded["scope"]
    assert evidence["differential_result"] == "PASS"
    assert evidence["product_acceptance_status"] == "OPEN_PENDING_GPT_PM_ADJUDICATION"
    assert evidence["test_harness"]["status"] == "PASS"
    assert evidence["test_harness"]["negative_controls"] == "PASS"
    assert len(evidence["negative_controls"]) == 17
    assert all(evidence["negative_controls"].values())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "OPEN"),
        ("gpt_pm_decision_request_id", "00000000-0000-0000-0000-000000000000"),
        ("criterion", "Full R1 behavioral equivalence"),
        ("scope", "full R1 equivalence and production acceptance"),
    ],
)
def test_tc001_decision_loader_rejects_bounded_contract_mutations(field, value, tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision_path = ROOT / "docs" / "phase2" / "TC001_BOUNDED_ACCEPTANCE.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    decision["bounded_acceptance"][field] = value
    mutated_path = tmp_path / "mutated-decision.yaml"
    mutated_path.write_text(yaml.safe_dump(decision, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(builder, "TC001_BOUNDED_DECISION", mutated_path)

    with pytest.raises(ValueError):
        builder.load_tc001_bounded_acceptance()


def test_tc001_decision_loader_rejects_unexpected_bounded_metadata(tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision_path = ROOT / "docs" / "phase2" / "TC001_BOUNDED_ACCEPTANCE.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    decision["bounded_acceptance"]["unreviewed_metadata"] = "must not be silently accepted"
    mutated_path = tmp_path / "unexpected-metadata.yaml"
    mutated_path.write_text(yaml.safe_dump(decision, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(builder, "TC001_BOUNDED_DECISION", mutated_path)

    with pytest.raises(ValueError, match="TC001_BOUNDED_DECISION_FIELDS_MISMATCH"):
        builder.load_tc001_bounded_acceptance()


@pytest.mark.parametrize(
    "source_path",
    [
        "../docs/phase2/TC001_BOUNDED_ACCEPTANCE.yaml",
        "artifacts/phase2/../../docs/phase2/TC001_BOUNDED_ACCEPTANCE.yaml",
    ],
)
def test_tc001_source_evidence_resolver_rejects_traversal(source_path):
    builder = load_spec_builder()
    with pytest.raises(ValueError):
        builder.resolve_tc001_source_evidence(source_path)


def test_tc001_source_evidence_resolver_rejects_absolute_outside_path(tmp_path):
    builder = load_spec_builder()
    outside_path = tmp_path / "outside-evidence.json"
    outside_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        builder.resolve_tc001_source_evidence(outside_path)


def test_three_distinct_kinds_per_story(catalogs):
    _, stories, cases = catalogs
    for s in stories:
        assert {c["kind"] for c in cases if c["story"] == s["id"]} == {
            "positive", "negative", "boundary_recovery",
        }


def test_gherkin_cases_not_claimed_executable(catalogs):
    _, _, cases = catalogs
    content = (PKG / "acceptance" / "phase2.feature").read_text(encoding="utf-8")
    assert len(re.findall(r"^  Scenario: R2-TC-\d{3} ", content, re.MULTILINE)) == len(cases)
    assert content.count("@not_implemented") == len(cases)


@pytest.mark.parametrize("name", ["capture_request", "model_event", "native_manifest", "reconciliation_result"])
def test_synthetic_example_validates_schema(name):
    schema = json.loads((PKG / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    instance = json.loads((PKG / "examples" / f"{name}.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=None).validate(instance)


def test_synthetic_reconciliation_net_arithmetic():
    e = json.loads((PKG / "examples" / "reconciliation_result.json").read_text(encoding="utf-8"))
    def D(name):
        return Decimal(e[name])
    assert D("closing_credit") - D("closing_debit") == (
        D("opening_credit") - D("opening_debit") + D("turnover_credit") - D("turnover_debit")
    )


def test_manifest_matches_files():
    entries = (PKG / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    assert len(entries) >= 25
    for entry in entries:
        digest, rel = entry.split("  ", 1)
        assert re.fullmatch(r"[a-f0-9]{64}", digest)
        assert ".." not in Path(rel).parts
        assert hashlib.sha256((PKG / rel).read_bytes()).hexdigest() == digest


def test_archive_integrity():
    with zipfile.ZipFile(ZIP) as arc:
        assert arc.testzip() is None
        assert any(name.endswith("MANIFEST.sha256") for name in arc.namelist())


def test_no_bogus_product_pass():
    report = json.loads((PKG / "validation_report.json").read_text(encoding="utf-8"))
    assert report["product_tests"] == "NOT_RUN"
    assert report["native_1c"] == "NOT_RUN"
    assert report["production"] == "NOT_RUN"
