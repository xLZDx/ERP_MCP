"""Offline specification quality checks; NOT product or native-1C acceptance."""
import hashlib
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


def load(rel):
    return yaml.safe_load((PKG / rel).read_text(encoding="utf-8"))


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
