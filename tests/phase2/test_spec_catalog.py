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
        if case["id"] not in {"R2-TC-001", "R2-TC-002", "R2-TC-003"}
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


def test_tc002_bounded_acceptance_is_satisfied_separately_from_product_status(catalogs):
    _, _, cases = catalogs
    matches = [case for case in cases if case["id"] == "R2-TC-002"]
    assert len(matches) == 1
    tc002 = matches[0]
    assert tc002["actual_status"] == "NOT_RUN"

    source_decision = yaml.safe_load(
        (ROOT / "docs" / "phase2" / "TC002_BOUNDED_ACCEPTANCE.yaml").read_text(encoding="utf-8")
    )
    package_decision = load("docs/12_TC002_BOUNDED_ACCEPTANCE.yaml")
    assert source_decision == package_decision
    bounded = tc002["bounded_acceptance"]
    assert bounded == package_decision["bounded_acceptance"]
    assert bounded["status"] == "SATISFIED"
    assert bounded["gpt_pm_adjudication_state"] == "APPROVED"
    assert bounded["gpt_pm_adjudication_request_id"] == "4d880fdb-82f1-4c68-9085-1cd353e51c31"
    assert bounded["gpt_pm_adjudication_job_id"] == "2896f4d4-f6a8-4138-ba5d-14f01eeea746"
    assert bounded["gpt_pm_adjudication_reply_id"] == "701d9c3a-ad00-528e-94f1-16f8ed9b03cd"
    assert re.fullmatch(r"[a-f0-9]{64}", bounded["gpt_pm_adjudication_receipt_sha256"])
    assert re.fullmatch(r"[a-f0-9]{64}", bounded["gpt_pm_adjudication_reply_sha256"])
    assert bounded["criterion"].startswith("All six pinned and all additional R1-marked items")
    assert bounded["source_backlog_path"] == "docs/PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md"
    assert bounded["source_ledger_path"] == "docs/phase2/TASK_LEDGER.md"
    assert bounded["gpt_pm_adjudication_package_receipt_path"] == "evidence/r2-tc002-gpt-pm-adjudication.json"

    evidence_bytes = (PKG / bounded["evidence_path"]).read_bytes()
    assert hashlib.sha256(evidence_bytes.replace(b"\r\n", b"\n")).hexdigest() == bounded["evidence_sha256"]
    evidence = json.loads(evidence_bytes)
    assert evidence["candidate"]["commit"] == bounded["exact_head"]
    assert evidence["product_status"] == "NOT_RUN"
    assert evidence["gherkin_status"] == "@not_implemented"
    assert evidence["regression"]["result"] == "PASS"
    assert evidence["regression"]["passed"] == 34
    assert evidence["regression"]["skipped"] == 1

    packaged_receipt_bytes = (PKG / bounded["gpt_pm_adjudication_package_receipt_path"]).read_bytes()
    packaged_receipt = json.loads(packaged_receipt_bytes)
    assert packaged_receipt["request_id"] == bounded["gpt_pm_adjudication_request_id"]
    assert packaged_receipt["candidate_head"] == bounded["exact_head"]
    assert packaged_receipt["bounded_status"] == "SATISFIED"
    assert packaged_receipt["product_status"] == "NOT_RUN"
    assert hashlib.sha256(packaged_receipt["reply_text"].encode("utf-8")).hexdigest() == packaged_receipt["reply_sha256"]
    assert packaged_receipt["reply_sha256"] == bounded["gpt_pm_adjudication_reply_sha256"]

    feature = (PKG / "acceptance" / "phase2.feature").read_text(encoding="utf-8")
    assert "  @not_implemented @R2TC002\n  Scenario: R2-TC-002" in feature

    builder = load_spec_builder()
    loaded_bounded, _, loaded_receipt = builder.load_tc002_bounded_acceptance()
    assert loaded_bounded == bounded
    assert loaded_receipt == packaged_receipt_bytes


@pytest.mark.parametrize(
    ("status", "adjudication_state"),
    [
        ("SATISFIED", "PENDING"),
        ("PENDING_GPT_PM_ADJUDICATION", "APPROVED"),
        ("SATISFIED", "REJECTED"),
    ],
)
def test_tc002_loader_rejects_unadjudicated_or_inconsistent_status(
    status, adjudication_state, tmp_path, monkeypatch,
):
    builder = load_spec_builder()
    decision_path = ROOT / "docs" / "phase2" / "TC002_BOUNDED_ACCEPTANCE.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    decision["bounded_acceptance"]["status"] = status
    decision["bounded_acceptance"]["gpt_pm_adjudication_state"] = adjudication_state
    mutated_path = tmp_path / "mutated-tc002-decision.yaml"
    mutated_path.write_text(yaml.safe_dump(decision, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(builder, "TC002_BOUNDED_DECISION", mutated_path)

    with pytest.raises(ValueError, match="TC002_BOUNDED_DECISION_STATUS_REQUIRES_ADJUDICATION"):
        builder.load_tc002_bounded_acceptance()


def test_tc002_yaml_cannot_claim_approval_with_fake_receipt_hashes(tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision_path = ROOT / "docs" / "phase2" / "TC002_BOUNDED_ACCEPTANCE.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    bounded = decision["bounded_acceptance"]
    bounded["status"] = "SATISFIED"
    bounded["gpt_pm_adjudication_state"] = "APPROVED"
    bounded["gpt_pm_adjudication_job_id"] = "11111111-2222-4333-8444-555555555555"
    bounded["gpt_pm_adjudication_reply_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    bounded["gpt_pm_adjudication_receipt_sha256"] = "a" * 64
    bounded["gpt_pm_adjudication_reply_sha256"] = "b" * 64
    mutated_path = tmp_path / "fake-tc002-approval.yaml"
    mutated_path.write_text(yaml.safe_dump(decision, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(builder, "TC002_BOUNDED_DECISION", mutated_path)

    with pytest.raises(ValueError, match="TC002_BOUNDED_PM_RECEIPT_SHA256_MISMATCH"):
        builder.load_tc002_bounded_acceptance()


def test_tc002_loader_and_generated_package_use_canonical_lf_evidence(tmp_path, monkeypatch):
    builder = load_spec_builder()
    bounded, loaded_bytes, _ = builder.load_tc002_bounded_acceptance()
    source_path = ROOT / bounded["source_evidence_path"]
    canonical_source = source_path.read_bytes().replace(b"\r\n", b"\n")
    assert loaded_bytes == canonical_source
    assert b"\r\n" not in loaded_bytes

    crlf_path = tmp_path / "tc002-evidence-crlf.json"
    crlf_path.write_bytes(canonical_source.replace(b"\n", b"\r\n"))
    original_resolver = builder.resolve_tc002_source_evidence
    monkeypatch.setattr(
        builder,
        "resolve_tc002_source_evidence",
        lambda reference: crlf_path if reference == bounded["source_evidence_path"] else original_resolver(reference),
    )
    _, normalized_bytes, _ = builder.load_tc002_bounded_acceptance()
    assert normalized_bytes == canonical_source
    assert b"\r\n" not in normalized_bytes

    packaged_bytes = (PKG / bounded["evidence_path"]).read_bytes()
    assert packaged_bytes == canonical_source
    assert b"\r\n" not in packaged_bytes


def _tc002_synthetic_approved_receipt(tmp_path, monkeypatch, *, extra_reply_lines=""):
    builder = load_spec_builder()
    bounded = yaml.safe_load(
        (ROOT / "docs" / "phase2" / "TC002_BOUNDED_ACCEPTANCE.yaml").read_text(encoding="utf-8")
    )["bounded_acceptance"]
    reply_text = (
        f"REQUEST_ID: {bounded['gpt_pm_adjudication_request_id']}\n"
        "PROJECT: ERP_MCP\n"
        "TASK: R2-US-001 / R2-TC-002 — R1 Defect Register Integrity\n"
        "FINAL VERDICT: APPROVE\n"
        "COMMIT_UPDATE_PR42: AUTHORIZED\n"
        "BOUNDED_TC002: SATISFIED\n"
        "PRODUCT_TC002: NOT_RUN\n"
        f"{extra_reply_lines}"
        "TC002_ADJUDICATION_JSON:"
    )
    reply_sha256 = hashlib.sha256(reply_text.encode("utf-8")).hexdigest()
    receipt = {
        "schema_version": 1,
        "project_id": "erp_mcp",
        "conversation_id": "12345678-1234-4234-8234-123456789abc",
        "job_id": bounded["gpt_pm_adjudication_job_id"],
        "request_id": bounded["gpt_pm_adjudication_request_id"],
        "reply_id": bounded["gpt_pm_adjudication_reply_id"],
        "payload_hash": bounded["gpt_pm_adjudication_payload_sha256"],
        "correlated": True,
        "candidate_head": bounded["exact_head"],
        "verdict": "APPROVE",
        "bounded_status": "SATISFIED",
        "product_status": "NOT_RUN",
        "reply_text": reply_text,
        "reply_sha256": reply_sha256,
    }
    receipt_path = tmp_path / "synthetic-tc002-pm-receipt.json"
    _write_tc002_synthetic_receipt(builder, receipt_path, bounded, receipt, monkeypatch)
    return builder, bounded, receipt, receipt_path


def _write_tc002_synthetic_receipt(builder, receipt_path, bounded, receipt, monkeypatch):
    bounded["gpt_pm_adjudication_reply_sha256"] = hashlib.sha256(
        receipt["reply_text"].encode("utf-8")
    ).hexdigest()
    receipt["reply_sha256"] = bounded["gpt_pm_adjudication_reply_sha256"]
    raw = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    receipt_path.write_bytes(raw)
    bounded["gpt_pm_adjudication_receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(builder, "resolve_tc002_source_evidence", lambda _: receipt_path)
    return raw


def test_tc002_receipt_parser_accepts_correlated_scalar_adjudication(tmp_path, monkeypatch):
    builder, bounded, receipt, _ = _tc002_synthetic_approved_receipt(tmp_path, monkeypatch)
    builder.validate_tc002_pm_adjudication_receipt(bounded)
    assert receipt["reply_text"].endswith("TC002_ADJUDICATION_JSON:")
    assert receipt["reply_text"].count("TC002_ADJUDICATION_JSON:") == 1


@pytest.mark.parametrize("extra_reply_lines", [
    "FINAL VERDICT: MODIFY\n",
    "FINAL VERDICT: APPROVE\n",
    "PROJECT: ERP_MCP\n",
    "TASK: R2-US-001 / R2-TC-002 — R1 Defect Register Integrity\n",
])
def test_tc002_receipt_parser_rejects_ambiguous_or_conflicting_scalar_lines(
    extra_reply_lines, tmp_path, monkeypatch,
):
    builder, bounded, receipt, receipt_path = _tc002_synthetic_approved_receipt(
        tmp_path, monkeypatch, extra_reply_lines=extra_reply_lines,
    )
    _write_tc002_synthetic_receipt(builder, receipt_path, bounded, receipt, monkeypatch)
    with pytest.raises(ValueError, match="TC002_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH"):
        builder.validate_tc002_pm_adjudication_receipt(bounded)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("REQUEST_ID: 4d880fdb-82f1-4c68-9085-1cd353e51c31", "REQUEST_ID: 00000000-0000-0000-0000-000000000000"),
        ("PROJECT: ERP_MCP", "PROJECT: OTHER"),
        ("TASK: R2-US-001 / R2-TC-002 — R1 Defect Register Integrity", "TASK: R2-US-001 / R2-TC-003 — Wrong criterion"),
        ("FINAL VERDICT: APPROVE", "FINAL VERDICT: MODIFY"),
        ("COMMIT_UPDATE_PR42: AUTHORIZED", "COMMIT_UPDATE_PR42: NOT_AUTHORIZED"),
        ("BOUNDED_TC002: SATISFIED", "BOUNDED_TC002: OPEN"),
        ("PRODUCT_TC002: NOT_RUN", "PRODUCT_TC002: PASS"),
    ],
)
def test_tc002_receipt_parser_rejects_wrong_scalar_decisions(
    old, new, tmp_path, monkeypatch,
):
    builder, bounded, receipt, receipt_path = _tc002_synthetic_approved_receipt(tmp_path, monkeypatch)
    assert old in receipt["reply_text"]
    receipt["reply_text"] = receipt["reply_text"].replace(old, new, 1)
    _write_tc002_synthetic_receipt(builder, receipt_path, bounded, receipt, monkeypatch)
    with pytest.raises(ValueError, match="TC002_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH"):
        builder.validate_tc002_pm_adjudication_receipt(bounded)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "00000000-0000-0000-0000-000000000000"),
        ("job_id", "00000000-0000-0000-0000-000000000000"),
        ("reply_id", "00000000-0000-0000-0000-000000000000"),
        ("project_id", "other-project"),
        ("candidate_head", "0" * 40),
        ("verdict", "MODIFY"),
        ("bounded_status", "OPEN"),
        ("product_status", "PASS"),
        ("correlated", False),
        ("payload_hash", "0" * 64),
    ],
)
def test_tc002_receipt_parser_rejects_mismatched_correlated_receipt_fields(
    field, value, tmp_path, monkeypatch,
):
    builder, bounded, receipt, receipt_path = _tc002_synthetic_approved_receipt(tmp_path, monkeypatch)
    receipt[field] = value
    _write_tc002_synthetic_receipt(builder, receipt_path, bounded, receipt, monkeypatch)
    with pytest.raises(ValueError, match="TC002_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH"):
        builder.validate_tc002_pm_adjudication_receipt(bounded)


def test_tc002_receipt_parser_rejects_wrong_reply_and_receipt_hashes(tmp_path, monkeypatch):
    builder, bounded, receipt, receipt_path = _tc002_synthetic_approved_receipt(tmp_path, monkeypatch)
    builder.validate_tc002_pm_adjudication_receipt(bounded)

    bounded["gpt_pm_adjudication_reply_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="TC002_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH"):
        builder.validate_tc002_pm_adjudication_receipt(bounded)

    bounded["gpt_pm_adjudication_reply_sha256"] = receipt["reply_sha256"]
    bounded["gpt_pm_adjudication_receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="TC002_BOUNDED_PM_RECEIPT_SHA256_MISMATCH"):
        builder.validate_tc002_pm_adjudication_receipt(bounded)


def test_tc002_loader_rejects_product_status_transition(tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision_path = ROOT / "docs" / "phase2" / "TC002_BOUNDED_ACCEPTANCE.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    decision["product_status"] = "PASS"
    mutated_path = tmp_path / "product-status-changed.yaml"
    mutated_path.write_text(yaml.safe_dump(decision, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(builder, "TC002_BOUNDED_DECISION", mutated_path)

    with pytest.raises(ValueError, match="TC002_BOUNDED_DECISION_MUST_PRESERVE_PRODUCT_NOT_RUN"):
        builder.load_tc002_bounded_acceptance()


@pytest.mark.parametrize("extra_field", ["case", "bounded"])
def test_tc002_loader_rejects_unreviewed_metadata(extra_field, tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision_path = ROOT / "docs" / "phase2" / "TC002_BOUNDED_ACCEPTANCE.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    if extra_field == "case":
        decision["unreviewed"] = True
    else:
        decision["bounded_acceptance"]["unreviewed"] = True
    mutated_path = tmp_path / "unexpected-tc002-metadata.yaml"
    mutated_path.write_text(yaml.safe_dump(decision, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(builder, "TC002_BOUNDED_DECISION", mutated_path)

    with pytest.raises(ValueError, match="TC002_BOUNDED_DECISION_SCHEMA_MISMATCH|TC002_BOUNDED_DECISION_FIELDS_MISMATCH"):
        builder.load_tc002_bounded_acceptance()


def test_tc002_loader_rejects_tampered_evidence_hash(tmp_path, monkeypatch):
    builder = load_spec_builder()
    source = ROOT / "artifacts" / "phase2" / "r2-tc002-register-integrity-evidence.json"
    tampered = tmp_path / "tampered-evidence.json"
    tampered.write_bytes(source.read_bytes() + b" ")
    original_resolver = builder.resolve_tc002_source_evidence
    monkeypatch.setattr(
        builder,
        "resolve_tc002_source_evidence",
        lambda path: tampered if path == "artifacts/phase2/r2-tc002-register-integrity-evidence.json" else original_resolver(path),
    )

    with pytest.raises(ValueError, match="TC002_BOUNDED_EVIDENCE_SHA256_MISMATCH"):
        builder.load_tc002_bounded_acceptance()


def test_tc002_loader_rejects_changed_pinned_backlog_source(monkeypatch):
    builder = load_spec_builder()
    original = builder._git_file_at_revision

    def changed_backlog(revision, path):
        if path == builder.TC002_BOUNDED_EXPECTED["source_backlog_path"]:
            return original(revision, path) + b"tampered"
        return original(revision, path)

    monkeypatch.setattr(builder, "_git_file_at_revision", changed_backlog)
    with pytest.raises(ValueError, match="TC002_BOUNDED_SOURCE_CONTENT_MISMATCH"):
        builder.load_tc002_bounded_acceptance()


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


def test_tc003_bounded_acceptance_is_separate_from_product_status():
    cases = load("test_cases.yaml")
    matches = [case for case in cases if case["id"] == "R2-TC-003"]
    assert len(matches) == 1
    case = matches[0]
    assert case["actual_status"] == "NOT_RUN"

    source_decision = yaml.safe_load(
        (ROOT / "docs" / "phase2" / "TC003_BOUNDED_ACCEPTANCE.yaml").read_text(encoding="utf-8")
    )
    package_decision = load("docs/13_TC003_BOUNDED_ACCEPTANCE.yaml")
    assert source_decision == package_decision
    bounded = case["bounded_acceptance"]
    assert bounded == package_decision["bounded_acceptance"]
    assert bounded["status"] == "SATISFIED"
    assert bounded["criterion"] == "moving HEAD is not reported as deployment evidence"
    assert package_decision["product_status"] == "NOT_RUN"
    assert bounded["gpt_pm_adjudication_request_id"] == "50c5099b-8d93-41f6-8e04-4a0b8f6e52dd"
    assert bounded["gpt_pm_adjudication_job_id"] == "6eefd345-14a5-42dc-8b2c-481cbb5d86fc"
    assert bounded["gpt_pm_adjudication_reply_id"] == "8e490bc5-d149-52dc-948a-1047ef786fff"
    assert bounded["exact_head"] == "b885f03ffd752b9b30a365fb0294c7e53f24a785"

    evidence_bytes = (PKG / bounded["evidence_path"]).read_bytes()
    assert hashlib.sha256(evidence_bytes).hexdigest() == bounded["evidence_sha256"]
    evidence = json.loads(evidence_bytes)
    assert evidence["product_status"] == "NOT_RUN"
    assert evidence["gherkin_status"] == "@not_implemented"
    assert evidence["regression"]["execution_head"] == bounded["exact_head"]
    assert evidence["regression"]["result"] == "PASS"
    assert evidence["regression"]["passed"] == 4
    assert evidence["provider_attestation"]["does_not_prove_external_deployment_absence"] is True

    receipt_bytes = (PKG / bounded["gpt_pm_adjudication_package_receipt_path"]).read_bytes()
    assert hashlib.sha256(receipt_bytes).hexdigest() == bounded["gpt_pm_adjudication_receipt_sha256"]
    receipt = json.loads(receipt_bytes)
    assert receipt["candidate_head"] == bounded["exact_head"]
    assert receipt["bounded_status"] == "SATISFIED"
    assert receipt["product_status"] == "NOT_RUN"
    assert hashlib.sha256(receipt["reply_text"].encode("utf-8")).hexdigest() == bounded["gpt_pm_adjudication_reply_sha256"]

    feature = (PKG / "acceptance" / "phase2.feature").read_text(encoding="utf-8")
    assert "  @not_implemented @R2TC003\n  Scenario: R2-TC-003" in feature
    manifest = {}
    for line in (PKG / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, rel_path = line.split("  ", 1)
        manifest[rel_path] = digest
    for rel_path in (
        "docs/13_TC003_BOUNDED_ACCEPTANCE.yaml",
        bounded["evidence_path"],
        bounded["gpt_pm_adjudication_package_receipt_path"],
    ):
        assert manifest[rel_path] == hashlib.sha256((PKG / rel_path).read_bytes()).hexdigest()

    builder = load_spec_builder()
    loaded_bounded, loaded_evidence, loaded_receipt = builder.load_tc003_bounded_acceptance()
    assert loaded_bounded == bounded
    assert loaded_evidence == evidence_bytes
    assert loaded_receipt == receipt_bytes


def _write_mutated_tc003_decision(builder, decision, tmp_path, monkeypatch):
    path = tmp_path / "mutated-tc003-decision.yaml"
    path.write_text(yaml.safe_dump(decision, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(builder, "TC003_BOUNDED_DECISION", path)


def test_tc003_loader_rejects_product_status_promotion(tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision = yaml.safe_load(builder.TC003_BOUNDED_DECISION.read_text(encoding="utf-8"))
    decision["product_status"] = "PASS"
    _write_mutated_tc003_decision(builder, decision, tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="TC003_BOUNDED_DECISION_MUST_PRESERVE_PRODUCT_NOT_RUN"):
        builder.load_tc003_bounded_acceptance()


def test_tc003_loader_rejects_tampered_pm_receipt(tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision = yaml.safe_load(builder.TC003_BOUNDED_DECISION.read_text(encoding="utf-8"))
    bounded = decision["bounded_acceptance"]
    original_path = ROOT / bounded["gpt_pm_adjudication_receipt_path"]
    mutated_name = f".tc003-receipt-tamper-{tmp_path.name}.json"
    mutated_path = original_path.with_name(mutated_name)
    mutated_path.write_bytes(original_path.read_bytes() + b" ")
    expected = dict(builder.TC003_BOUNDED_EXPECTED)
    expected["gpt_pm_adjudication_receipt_path"] = str(Path("artifacts/phase2") / mutated_name).replace("\\", "/")
    monkeypatch.setattr(builder, "TC003_BOUNDED_EXPECTED", expected)
    bounded["gpt_pm_adjudication_receipt_path"] = expected["gpt_pm_adjudication_receipt_path"]
    _write_mutated_tc003_decision(builder, decision, tmp_path, monkeypatch)
    try:
        with pytest.raises(ValueError, match="TC003_BOUNDED_PM_RECEIPT_SHA256_MISMATCH"):
            builder.load_tc003_bounded_acceptance()
    finally:
        mutated_path.unlink(missing_ok=True)


def test_tc003_loader_rejects_duplicate_pm_receipt_json_keys(tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision = yaml.safe_load(builder.TC003_BOUNDED_DECISION.read_text(encoding="utf-8"))
    bounded = decision["bounded_acceptance"]
    original_path = ROOT / bounded["gpt_pm_adjudication_receipt_path"]
    receipt_bytes = original_path.read_bytes()
    needle = b'"schema_version": 1,'
    assert receipt_bytes.count(needle) == 1
    duplicate_receipt = receipt_bytes.replace(needle, b'"schema_version": 1, "schema_version": 1,', 1)
    mutated_name = f".tc003-receipt-duplicate-{tmp_path.name}.json"
    mutated_path = original_path.with_name(mutated_name)
    mutated_path.write_bytes(duplicate_receipt)
    expected = dict(builder.TC003_BOUNDED_EXPECTED)
    expected["gpt_pm_adjudication_receipt_path"] = str(Path("artifacts/phase2") / mutated_name).replace("\\", "/")
    expected["gpt_pm_adjudication_receipt_sha256"] = hashlib.sha256(duplicate_receipt).hexdigest()
    monkeypatch.setattr(builder, "TC003_BOUNDED_EXPECTED", expected)
    bounded["gpt_pm_adjudication_receipt_path"] = expected["gpt_pm_adjudication_receipt_path"]
    bounded["gpt_pm_adjudication_receipt_sha256"] = expected["gpt_pm_adjudication_receipt_sha256"]
    _write_mutated_tc003_decision(builder, decision, tmp_path, monkeypatch)
    try:
        with pytest.raises(ValueError, match="TC003_BOUNDED_PM_RECEIPT_DUPLICATE_JSON_KEY"):
            builder.load_tc003_bounded_acceptance()
    finally:
        mutated_path.unlink(missing_ok=True)


def test_tc003_loader_rejects_source_blob_identity_mismatch(tmp_path, monkeypatch):
    builder = load_spec_builder()
    decision = yaml.safe_load(builder.TC003_BOUNDED_DECISION.read_text(encoding="utf-8"))
    expected = dict(builder.TC003_BOUNDED_EXPECTED)
    expected["assembler_git_blob_oid"] = "0" * 40
    monkeypatch.setattr(builder, "TC003_BOUNDED_EXPECTED", expected)
    decision["bounded_acceptance"]["assembler_git_blob_oid"] = expected["assembler_git_blob_oid"]
    _write_mutated_tc003_decision(builder, decision, tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="TC003_BOUNDED_SOURCE_CONTENT_MISMATCH"):
        builder.load_tc003_bounded_acceptance()
