"""Build a derived, offline Phase 2 specification package from the current branch.

This is deliberately a NEW build, not a claim to reproduce the original ChatGPT
conversation archive byte-for-byte. Never reads .env, credentials or business data.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import subprocess
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "phase2"
NAME = "ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08"
PACKAGE = DOCS / "spec-v0.1" / NAME
ARCHIVE = DOCS / "artifacts" / f"{NAME}.zip"
TC001_BOUNDED_DECISION = DOCS / "TC001_BOUNDED_ACCEPTANCE.yaml"
TC002_BOUNDED_DECISION = DOCS / "TC002_BOUNDED_ACCEPTANCE.yaml"
TC001_BOUNDED_EXPECTED = {
    "case_id": "R2-TC-001",
    "product_status": "NOT_RUN",
    "status": "SATISFIED",
    "criterion": "R1 unchanged",
    "scope": "exercised R1 public MCP compatibility only; not full R1 equivalence",
    "exact_head": "5336867aab8070139e61fb39b6b4ba73a9ac59b0",
    "source_evidence_path": "artifacts/phase2/r2-tc001-5336867-evidence.json",
    "evidence_path": "evidence/r2-tc001-5336867-evidence.json",
    "evidence_sha256": "6669c29217d5729633c71d694912ee278b3ca8486b7804469f50da2967001853",
    "gpt_pm_decision_request_id": "3f51d1d2-49dc-49d5-871c-f916405d35d4",
    "transition_rule": (
        "The bounded acceptance may be SATISFIED only when the exact-HEAD differential "
        "evidence is PASS and the correlated GPT-PM adjudication accepts this bounded "
        "criterion. This does not change the canonical product_status from NOT_RUN."
    ),
    "limitations": [
        "Does not establish full R1 behavioral equivalence.",
        "Does not establish production acceptance, deployment, merge, or release authority.",
    ],
}
TC002_BOUNDED_EXPECTED = {
    "case_id": "R2-TC-002",
    "product_status": "NOT_RUN",
    "status": "SATISFIED",
    "criterion": (
        "All six pinned and all additional R1-marked items discoverable through "
        "the named backlog's supported row syntax retain exactly one ledger record "
        "with meaningful evidence, an unresolved or explicitly justified N/A "
        "disposition, and an actionable next step."
    ),
    "scope": "source-register integrity for R1-marked items in the named backlog only",
    "exact_head": "22647667e25fdd39ce26f48641c490eba1074f2b",
    "source_backlog_path": "docs/PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md",
    "source_backlog_sha256": "f8523d07104ecde561c511d9f5846e46c8efce7e8fc531ffc6194d735b8532de",
    "source_ledger_path": "docs/phase2/TASK_LEDGER.md",
    "source_ledger_section": "## S0 TC002 — R1 defect visibility and disposition",
    "source_ledger_section_sha256": "b6d5037d03ecb05e6e17e395ccd3ac90b3b57f215c3259bbd73eb06de7d2b591",
    "source_test_path": "tests/phase2/test_spec_bundle_mapping.py",
    "source_test_git_blob_sha256": "d7d5063bf1c2fa58bb4200500e358f17cf0339e0861368651b199dcbb9efeb1f",
    "source_evidence_path": "artifacts/phase2/r2-tc002-register-integrity-evidence.json",
    "evidence_path": "evidence/r2-tc002-register-integrity-evidence.json",
    "evidence_sha256": "9902229ce6ad526ea7b1d6da3f044e9bf589359d87be331f0b040d65ad7361bd",
    "prior_gpt_pm_review_request_id": "e2a6e04a-17cb-497a-91e3-71110f5870f4",
    "code_approval_request_id": "4e9bf80c-71f2-4808-bf56-0bdb4ca92522",
    "integration_code_review_request_id": "bce3e771-48b2-4a22-8b4d-d4fa89cbf09a",
    "normalization_confirmation_request_id": "ca62e7c4-a3d2-41f8-9e61-aafed5df2cab",
    "gpt_pm_adjudication_state": "APPROVED",
    "gpt_pm_adjudication_request_id": "4d880fdb-82f1-4c68-9085-1cd353e51c31",
    "gpt_pm_adjudication_payload_sha256": "bfc4f51d4b0a32c81a50b1cea8a9fdadaaae1e7c7f909e3925ff28afb1697cdb",
    "gpt_pm_adjudication_job_id": "2896f4d4-f6a8-4138-ba5d-14f01eeea746",
    "gpt_pm_adjudication_reply_id": "701d9c3a-ad00-528e-94f1-16f8ed9b03cd",
    "gpt_pm_adjudication_receipt_path": "artifacts/phase2/r2-tc002-gpt-pm-adjudication.json",
    "gpt_pm_adjudication_package_receipt_path": "evidence/r2-tc002-gpt-pm-adjudication.json",
    "gpt_pm_adjudication_receipt_sha256": "04147bb644b41be981703dcf8938e5a80547d96665b4ef42f7162e923c260fc3",
    "gpt_pm_adjudication_reply_sha256": "310f1d903f367850d2090289be27c175a3240dd4f6e1c491d9c107a24ca47b06",
    "transition_rule": (
        "The bounded status may be SATISFIED only when a correlated GPT-PM decision "
        "explicitly adjudicates this bounded criterion. A passing register-integrity "
        "regression alone cannot promote it. Canonical product_status remains NOT_RUN "
        "and the Gherkin case remains @not_implemented."
    ),
    "limitations": [
        "Does not cover undiscovered defects, unmarked source items, or items outside the named backlog.",
        "Does not prove every R1 defect has been fixed or that the backlog is exhaustive.",
        "Does not establish full R1 product acceptance, runtime acceptance, deployment, merge, or release authority.",
    ],
}
TC003_BOUNDED_DECISION = DOCS / "TC003_BOUNDED_ACCEPTANCE.yaml"
TC003_BOUNDED_EXPECTED = {
    "case_id": "R2-TC-003",
    "product_status": "NOT_RUN",
    "status": "SATISFIED",
    "criterion": "moving HEAD is not reported as deployment evidence",
    "scope": (
        "The release-evidence assembler does not infer deployment identity from tested "
        "revision, local HEAD, or PR head; absent provider attestation remains unknown "
        "and caller-supplied SHAs remain unverified claims."
    ),
    "exact_head": "b885f03ffd752b9b30a365fb0294c7e53f24a785",
    "source_evidence_path": "artifacts/phase2/r2-tc003-deployment-identity-evidence.json",
    "evidence_path": "evidence/r2-tc003-deployment-identity-evidence.json",
    "evidence_sha256": "8af815a097f937cbf3b60db2ac536371b6b3231af750fd630f75599de963505a",
    "assembler_path": "scripts/assemble_release_evidence.py",
    "assembler_worktree_sha256": "6ec5084613b3076499e823ff6611b3e8d6ee926da60aa8d43242c357610971de",
    "assembler_git_blob_oid": "236edacb5cf16f66671f6fb6da10b0c8766a79e2",
    "assembler_candidate_blob_sha256": "b5d4fc5123a8e5b510efc6770241a5a89fe3236991d9975d7db1e0ba14527710",
    "test_path": "tests/test_release_evidence_assembly.py",
    "test_worktree_sha256": "17b123fe38b7f3c3752394cdf51cdd1f6f4305bf40fcf9f753a105a76a783568",
    "test_git_blob_oid": "e91133d306dc6ae0256715490f8ea56541d63e94",
    "test_candidate_blob_sha256": "63c339bcf6687519dbfdfcb24e07d8460937b67cc7f652db77a248b952fdfa1f",
    "regression_command": (
        ".venv/Scripts/python.exe -m pytest -q "
        "tests/test_release_evidence_assembly.py::test_deployment_revision_defaults_to_unknown_instead_of_following_moving_head "
        "tests/test_release_evidence_assembly.py::test_deployment_revision_mismatch_is_kept_as_an_unverified_claim "
        "tests/test_release_evidence_assembly.py::test_deployment_revision_equal_to_pr_head_is_still_unverified "
        "tests/test_release_evidence_assembly.py::test_malformed_deployment_revision_is_rejected"
    ),
    "regression_passed": 4,
    "regression_result": "PASS",
    "prior_gpt_pm_review_request_id": "50c5099b-8d93-41f6-8e04-4a0b8f6e52dd",
    "gpt_pm_adjudication_state": "APPROVED",
    "gpt_pm_adjudication_request_id": "50c5099b-8d93-41f6-8e04-4a0b8f6e52dd",
    "gpt_pm_adjudication_job_id": "6eefd345-14a5-42dc-8b2c-481cbb5d86fc",
    "gpt_pm_adjudication_reply_id": "8e490bc5-d149-52dc-948a-1047ef786fff",
    "gpt_pm_adjudication_payload_sha256": "8c9c80da8b5ff42525a0e78ed1b0a6e21985a23565117cbc80d1734b23b92834",
    "gpt_pm_adjudication_receipt_path": "artifacts/phase2/r2-tc003-gpt-pm-adjudication.json",
    "gpt_pm_adjudication_package_receipt_path": "evidence/r2-tc003-gpt-pm-adjudication.json",
    "gpt_pm_adjudication_receipt_sha256": "9ebf1f76405813c21786700d65f78eb1fa456057bf97606000e755dc2086ecb3",
    "gpt_pm_adjudication_reply_sha256": "89469deb8993ca96af7c79a7eb6b6d4978658142e9dd531b155acf4906eaf7b3",
    "transition_rule": (
        "A correlated GPT-PM decision may mark only this bounded negative criterion "
        "SATISFIED. Canonical product_status remains NOT_RUN and Gherkin remains "
        "@not_implemented until an executable product scenario and authoritative "
        "provider deployment evidence exist."
    ),
    "absence_of_attestation_disposition": (
        "ACCEPTABLE for this bounded criterion only. It records that the named "
        "repository evidence does not identify a verified deployment; it does not "
        "assert that no external deployment exists."
    ),
    "limitations": [
        "Does not identify or verify an actual deployed revision.",
        "Does not prove that no deployment exists outside the named repository evidence.",
        "Does not establish product runtime acceptance, release readiness, merge, deployment, or production authorization.",
    ],
}

DOC_MAP = {
    "TDD_PHASE2_RU.md": "docs/01_TDD_RU.md",
    "PLAN_PHASE2_RU.md": "docs/02_PLAN_RU.md",
    "STORIES_PHASE2_RU.md": "docs/03_STORIES_RU.md",
    "TEST_PLAN_PHASE2_RU.md": "docs/04_TEST_PLAN_RU.md",
    "NATIVE_REPORT_PROTOCOL_RU.md": "docs/05_NATIVE_REPORT_PROTOCOL_RU.md",
    "DECISIONS_AND_SOURCES_RU.md": "docs/06_DECISIONS_SOURCES_RU.md",
    "CONTRACTS_AND_API_RU.md": "docs/07_DATA_MODEL_API_RU.md",
    "PACKAGE_COMPLETION_RU.md": "docs/08_COMPLETION_RU.md",
    "BRANCH_ISOLATION_AND_HANDOFF.md": "docs/09_HANDOFF_RU.md",
    "CUTOVER_PLAN_RU.md": "docs/10_CUTOVER_PLAN_RU.md",
}
# Safe to run repeatedly ONLY if existing package is our own previously generated output.
MARKER = "GENERATED_FROM_BRANCH_PHASE2_DO_NOT_CONFUSE_WITH_ORIGINAL_ZIP"


def save(rel: str, value: str | bytes) -> None:
    target = PACKAGE / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        target.write_bytes(value)
    else:
        target.write_text(value, encoding="utf-8", newline="\n")


def validate_tc001_bounded_fields(bounded: dict) -> None:
    if not isinstance(bounded, dict):
        raise ValueError("TC001_BOUNDED_DECISION_MISSING_ACCEPTANCE")
    expected_fields = set(TC001_BOUNDED_EXPECTED) - {"case_id", "product_status"}
    if set(bounded) != expected_fields:
        raise ValueError("TC001_BOUNDED_DECISION_FIELDS_MISMATCH")
    for field in (
        "status", "criterion", "scope", "exact_head", "source_evidence_path",
        "evidence_path", "evidence_sha256", "gpt_pm_decision_request_id",
        "transition_rule", "limitations",
    ):
        if bounded.get(field) != TC001_BOUNDED_EXPECTED[field]:
            raise ValueError(f"TC001_BOUNDED_DECISION_{field.upper()}_MISMATCH")


def resolve_tc001_source_evidence(source_ref: str | Path) -> Path:
    source_ref = Path(source_ref)
    if source_ref.is_absolute() or ".." in source_ref.parts or not source_ref.parts:
        raise ValueError("TC001_BOUNDED_SOURCE_EVIDENCE_PATH_INVALID")
    try:
        evidence_root = (ROOT / "artifacts" / "phase2").resolve(strict=True)
        evidence_path = (ROOT / source_ref).resolve(strict=True)
    except OSError as exc:
        raise ValueError("TC001_BOUNDED_SOURCE_EVIDENCE_NOT_FOUND") from exc
    try:
        evidence_path.relative_to(evidence_root)
    except ValueError as exc:
        raise ValueError("TC001_BOUNDED_SOURCE_EVIDENCE_OUTSIDE_ARTIFACTS_PHASE2") from exc
    if not evidence_path.is_file():
        raise ValueError("TC001_BOUNDED_SOURCE_EVIDENCE_NOT_FILE")
    return evidence_path


def load_tc001_bounded_acceptance() -> tuple[dict, bytes]:
    decision = yaml.safe_load(TC001_BOUNDED_DECISION.read_text(encoding="utf-8"))
    if not isinstance(decision, dict) or set(decision) != {
        "schema_version", "case_id", "product_status", "bounded_acceptance",
    } or decision.get("schema_version") != 1:
        raise ValueError("TC001_BOUNDED_DECISION_SCHEMA_MISMATCH")
    if decision.get("case_id") != TC001_BOUNDED_EXPECTED["case_id"]:
        raise ValueError("TC001_BOUNDED_DECISION_CASE_ID_MISMATCH")
    if decision.get("product_status") != TC001_BOUNDED_EXPECTED["product_status"]:
        raise ValueError("TC001_BOUNDED_DECISION_MUST_PRESERVE_PRODUCT_NOT_RUN")
    bounded = decision.get("bounded_acceptance")
    validate_tc001_bounded_fields(bounded)

    evidence_path = resolve_tc001_source_evidence(bounded["source_evidence_path"])

    package_ref = Path(bounded["evidence_path"])
    if package_ref.is_absolute() or ".." in package_ref.parts or not package_ref.parts:
        raise ValueError("TC001_BOUNDED_EVIDENCE_PATH_MUST_STAY_IN_PACKAGE")
    evidence_bytes = evidence_path.read_bytes()
    if hashlib.sha256(evidence_bytes).hexdigest() != bounded["evidence_sha256"]:
        raise ValueError("TC001_BOUNDED_EVIDENCE_SHA256_MISMATCH")
    evidence = json.loads(evidence_bytes)
    inventory = evidence.get("tool_inventory", {})
    negative_controls = evidence.get("negative_controls", {})
    if (
        evidence.get("scenario") != "R2-TC-001"
        or evidence.get("baseline", {}).get("requested_ref") != "57eb5b0696063237a43f5d1baf0a646278f5d832"
        or evidence.get("baseline", {}).get("commit") != "57eb5b0696063237a43f5d1baf0a646278f5d832"
        or evidence.get("candidate", {}).get("requested_ref") != bounded["exact_head"]
        or evidence.get("candidate", {}).get("commit") != bounded["exact_head"]
        or evidence.get("scope") != bounded["scope"]
        or evidence.get("differential_result") != "PASS"
        or evidence.get("product_acceptance_status") != "OPEN_PENDING_GPT_PM_ADJUDICATION"
        or evidence.get("test_harness", {}).get("status") != "PASS"
        or evidence.get("test_harness", {}).get("negative_controls") != "PASS"
        or len(negative_controls) != 17
        or not all(negative_controls.values())
        or len(inventory.get("baseline_r1", [])) != 19
        or inventory.get("candidate_missing") != []
        or len(inventory.get("candidate_additions", [])) != 9
    ):
        raise ValueError("TC001_BOUNDED_EVIDENCE_CONTENT_MISMATCH")
    return bounded, evidence_bytes


def validate_tc002_bounded_fields(bounded: dict) -> None:
    if not isinstance(bounded, dict):
        raise ValueError("TC002_BOUNDED_DECISION_MISSING_ACCEPTANCE")
    expected_fields = set(TC002_BOUNDED_EXPECTED) - {"case_id", "product_status"}
    if set(bounded) != expected_fields:
        raise ValueError("TC002_BOUNDED_DECISION_FIELDS_MISMATCH")
    decision_state = bounded.get("gpt_pm_adjudication_state")
    if (bounded.get("status"), decision_state) not in {
        ("PENDING_GPT_PM_ADJUDICATION", "PENDING"),
        ("SATISFIED", "APPROVED"),
    }:
        raise ValueError("TC002_BOUNDED_DECISION_STATUS_REQUIRES_ADJUDICATION")
    if bounded.get("status") == "PENDING_GPT_PM_ADJUDICATION" and any(
        bounded.get(field) is not None
        for field in (
            "gpt_pm_adjudication_receipt_sha256", "gpt_pm_adjudication_reply_sha256",
        )
    ):
        raise ValueError("TC002_BOUNDED_PENDING_DECISION_HAS_APPROVAL_RECEIPT")
    if bounded.get("status") == "SATISFIED" and not all(
        isinstance(bounded.get(field), str)
        and re.fullmatch(pattern, bounded[field])
        for field, pattern in (
            ("gpt_pm_adjudication_job_id", r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
            ("gpt_pm_adjudication_reply_id", r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
            ("gpt_pm_adjudication_receipt_sha256", r"[a-f0-9]{64}"),
            ("gpt_pm_adjudication_reply_sha256", r"[a-f0-9]{64}"),
        )
    ):
        raise ValueError("TC002_BOUNDED_SATISFIED_REQUIRES_DECISION_RECEIPT")
    package_receipt_ref = Path(bounded["gpt_pm_adjudication_package_receipt_path"])
    if package_receipt_ref.is_absolute() or ".." in package_receipt_ref.parts or not package_receipt_ref.parts:
        raise ValueError("TC002_BOUNDED_PM_PACKAGE_RECEIPT_PATH_INVALID")
    for field, expected in TC002_BOUNDED_EXPECTED.items():
        if field not in {
            "case_id", "product_status", "status", "gpt_pm_adjudication_state",
            "gpt_pm_adjudication_job_id", "gpt_pm_adjudication_reply_id",
            "gpt_pm_adjudication_receipt_sha256", "gpt_pm_adjudication_reply_sha256",
        } and bounded.get(field) != expected:
            raise ValueError(f"TC002_BOUNDED_DECISION_{field.upper()}_MISMATCH")


def _git_file_at_revision(revision: str, relative_path: str) -> bytes:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("TC002_BOUNDED_SOURCE_PATH_INVALID")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("TC002_BOUNDED_SOURCE_REVISION_INVALID")
    try:
        return subprocess.check_output(
            ["git", "show", f"{revision}:{path.as_posix()}"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("TC002_BOUNDED_SOURCE_REVISION_FILE_UNAVAILABLE") from exc


def _tc002_ledger_section(data: bytes, heading: str) -> bytes:
    lines = data.decode("utf-8").splitlines()
    try:
        start = lines.index(heading)
    except ValueError as exc:
        raise ValueError("TC002_BOUNDED_LEDGER_SECTION_MISSING") from exc
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return ("\n".join(lines[start:end]) + "\n").encode("utf-8")


def resolve_tc002_source_evidence(source_ref: str | Path) -> Path:
    source_ref = Path(source_ref)
    if source_ref.is_absolute() or ".." in source_ref.parts or not source_ref.parts:
        raise ValueError("TC002_BOUNDED_SOURCE_EVIDENCE_PATH_INVALID")
    try:
        evidence_root = (ROOT / "artifacts" / "phase2").resolve(strict=True)
        evidence_path = (ROOT / source_ref).resolve(strict=True)
    except OSError as exc:
        raise ValueError("TC002_BOUNDED_SOURCE_EVIDENCE_NOT_FOUND") from exc
    try:
        evidence_path.relative_to(evidence_root)
    except ValueError as exc:
        raise ValueError("TC002_BOUNDED_SOURCE_EVIDENCE_OUTSIDE_ARTIFACTS_PHASE2") from exc
    if not evidence_path.is_file():
        raise ValueError("TC002_BOUNDED_SOURCE_EVIDENCE_NOT_FILE")
    return evidence_path


def validate_tc002_pm_adjudication_receipt(bounded: dict) -> bytes | None:
    if bounded["status"] == "PENDING_GPT_PM_ADJUDICATION":
        return None
    receipt_path = resolve_tc002_source_evidence(bounded["gpt_pm_adjudication_receipt_path"])
    receipt_bytes = receipt_path.read_bytes()
    canonical_receipt = receipt_bytes.replace(b"\r\n", b"\n")
    if hashlib.sha256(canonical_receipt).hexdigest() != bounded["gpt_pm_adjudication_receipt_sha256"]:
        raise ValueError("TC002_BOUNDED_PM_RECEIPT_SHA256_MISMATCH")
    def reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("TC002_BOUNDED_PM_RECEIPT_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    receipt = json.loads(receipt_bytes, object_pairs_hook=reject_duplicate_json_keys)
    if not isinstance(receipt, dict):
        raise ValueError("TC002_BOUNDED_PM_RECEIPT_SCHEMA_MISMATCH")
    reply_text = receipt.get("reply_text")
    if not isinstance(reply_text, str):
        raise ValueError("TC002_BOUNDED_PM_RECEIPT_REPLY_MISSING")
    decision_labels = (
        "PROJECT:", "TASK:", "REQUEST_ID:", "FINAL VERDICT:",
        "COMMIT_UPDATE_PR42:", "BOUNDED_TC002:", "PRODUCT_TC002:",
    )
    if any(
        line.lstrip() != line and line.lstrip().startswith(decision_labels)
        for line in reply_text.splitlines()
    ):
        raise ValueError("TC002_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH")
    project_lines = re.findall(r"(?m)^PROJECT:[ \t]*(.*?)[ \t]*$", reply_text)
    task_lines = re.findall(r"(?m)^TASK:[ \t]*(.*?)[ \t]*$", reply_text)
    request_lines = re.findall(r"(?m)^REQUEST_ID:[ \t]*(.*?)[ \t]*$", reply_text)
    verdict_lines = re.findall(r"(?m)^FINAL VERDICT:[ \t]*(.*?)[ \t]*$", reply_text)
    commit_authorization_lines = re.findall(r"(?m)^COMMIT_UPDATE_PR42:[ \t]*(.*?)[ \t]*$", reply_text)
    bounded_status_lines = re.findall(r"(?m)^BOUNDED_TC002:[ \t]*(.*?)[ \t]*$", reply_text)
    product_status_lines = re.findall(r"(?m)^PRODUCT_TC002:[ \t]*(.*?)[ \t]*$", reply_text)
    if (
        set(receipt) != {
            "schema_version", "project_id", "conversation_id", "job_id", "request_id",
            "reply_id", "payload_hash", "correlated", "candidate_head", "verdict",
            "bounded_status", "product_status", "reply_text", "reply_sha256",
        }
        or receipt.get("schema_version") != 1
        or receipt.get("project_id") != "erp_mcp"
        or not isinstance(receipt.get("conversation_id"), str)
        or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", receipt["conversation_id"])
        or receipt.get("job_id") != bounded["gpt_pm_adjudication_job_id"]
        or receipt.get("request_id") != bounded["gpt_pm_adjudication_request_id"]
        or receipt.get("reply_id") != bounded["gpt_pm_adjudication_reply_id"]
        or receipt.get("payload_hash") != bounded["gpt_pm_adjudication_payload_sha256"]
        or receipt.get("correlated") is not True
        or receipt.get("candidate_head") != bounded["exact_head"]
        or receipt.get("verdict") != "APPROVE"
        or receipt.get("bounded_status") != "SATISFIED"
        or receipt.get("product_status") != "NOT_RUN"
        or project_lines != ["ERP_MCP"]
        or task_lines != ["R2-US-001 / R2-TC-002 — R1 Defect Register Integrity"]
        or hashlib.sha256(reply_text.encode("utf-8")).hexdigest()
        != bounded["gpt_pm_adjudication_reply_sha256"]
        or receipt.get("reply_sha256") != bounded["gpt_pm_adjudication_reply_sha256"]
        or request_lines != [bounded["gpt_pm_adjudication_request_id"]]
        or verdict_lines != ["APPROVE"]
        or commit_authorization_lines != ["AUTHORIZED"]
        or bounded_status_lines != ["SATISFIED"]
        or product_status_lines != ["NOT_RUN"]
    ):
        raise ValueError("TC002_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH")
    return canonical_receipt


def load_tc002_bounded_acceptance() -> tuple[dict, bytes, bytes | None]:
    decision = yaml.safe_load(TC002_BOUNDED_DECISION.read_text(encoding="utf-8"))
    if not isinstance(decision, dict) or set(decision) != {
        "schema_version", "case_id", "product_status", "bounded_acceptance",
    } or decision.get("schema_version") != 1:
        raise ValueError("TC002_BOUNDED_DECISION_SCHEMA_MISMATCH")
    if decision.get("case_id") != TC002_BOUNDED_EXPECTED["case_id"]:
        raise ValueError("TC002_BOUNDED_DECISION_CASE_ID_MISMATCH")
    if decision.get("product_status") != "NOT_RUN":
        raise ValueError("TC002_BOUNDED_DECISION_MUST_PRESERVE_PRODUCT_NOT_RUN")
    bounded = decision.get("bounded_acceptance")
    validate_tc002_bounded_fields(bounded)
    receipt_bytes = validate_tc002_pm_adjudication_receipt(bounded)

    evidence_path = resolve_tc002_source_evidence(bounded["source_evidence_path"])
    package_ref = Path(bounded["evidence_path"])
    if package_ref.is_absolute() or ".." in package_ref.parts or not package_ref.parts:
        raise ValueError("TC002_BOUNDED_EVIDENCE_PATH_MUST_STAY_IN_PACKAGE")
    evidence_bytes = evidence_path.read_bytes()
    canonical_evidence_bytes = evidence_bytes.replace(b"\r\n", b"\n")
    if hashlib.sha256(canonical_evidence_bytes).hexdigest() != bounded["evidence_sha256"]:
        raise ValueError("TC002_BOUNDED_EVIDENCE_SHA256_MISMATCH")

    candidate_head = bounded["exact_head"]
    backlog = _git_file_at_revision(candidate_head, bounded["source_backlog_path"])
    ledger = _git_file_at_revision(candidate_head, bounded["source_ledger_path"])
    test_blob = _git_file_at_revision(candidate_head, bounded["source_test_path"])
    test_worktree = (ROOT / bounded["source_test_path"]).read_bytes()
    if (
        hashlib.sha256(backlog).hexdigest() != bounded["source_backlog_sha256"]
        or hashlib.sha256(_tc002_ledger_section(ledger, bounded["source_ledger_section"])).hexdigest()
        != bounded["source_ledger_section_sha256"]
        or hashlib.sha256(test_blob).hexdigest() != bounded["source_test_git_blob_sha256"]
        or hashlib.sha256(test_worktree.replace(b"\r\n", b"\n")).hexdigest()
        != bounded["source_test_git_blob_sha256"]
    ):
        raise ValueError("TC002_BOUNDED_SOURCE_CONTENT_MISMATCH")

    evidence = json.loads(evidence_bytes)
    regression = evidence.get("regression", {})
    source_backlog = evidence.get("source_backlog", {})
    source_ledger = evidence.get("source_ledger", {})
    source_test = evidence.get("source_test", {})
    if (
        evidence.get("scenario") != "R2-TC-002"
        or evidence.get("bounded_criterion") != bounded["criterion"]
        or evidence.get("scope") != bounded["scope"]
        or evidence.get("candidate", {}).get("commit") != candidate_head
        or source_backlog.get("path") != bounded["source_backlog_path"]
        or source_backlog.get("sha256") != bounded["source_backlog_sha256"]
        or source_ledger.get("path") != bounded["source_ledger_path"]
        or source_ledger.get("section") != bounded["source_ledger_section"]
        or source_ledger.get("section_sha256") != bounded["source_ledger_section_sha256"]
        or source_test.get("path") != bounded["source_test_path"]
        or source_test.get("committed_git_blob_sha256") != bounded["source_test_git_blob_sha256"]
        or source_test.get("line_ending_normalization")
        != "CRLF-to-LF byte equality independently confirmed by GPT-PM in request "
        "ca62e7c4-a3d2-41f8-9e61-aafed5df2cab"
        or regression.get("command")
        != "python -m pytest -q --confcutdir=tests/phase2 tests/phase2/test_spec_bundle_mapping.py"
        or regression.get("result") != "PASS"
        or regression.get("exit_code") != 0
        or regression.get("passed") != 34
        or regression.get("skipped") != 1
        or regression.get("warnings") != 1
        or regression.get("execution_head") != "490cfb744f8322d87107e361455e84618d78b7d0"
        or source_test.get("tested_working_tree_sha256")
        != "b28a3daae5b98e8770aa1ca4e73a64863e38b496124ca9c285abbaf5cf9a4bad"
        or evidence.get("product_status") != "NOT_RUN"
        or evidence.get("gherkin_status") != "@not_implemented"
        or evidence.get("required_item_ids") != ["B2", "B3", "M2", "M5", "M7", "M8"]
        or evidence.get("prior_gpt_pm_review_request_id") != bounded["prior_gpt_pm_review_request_id"]
        or evidence.get("code_approval_request_id") != bounded["code_approval_request_id"]
        or evidence.get("normalization_confirmation_request_id") != bounded["normalization_confirmation_request_id"]
    ):
        raise ValueError("TC002_BOUNDED_EVIDENCE_CONTENT_MISMATCH")
    return bounded, canonical_evidence_bytes, receipt_bytes


def load_tc003_bounded_acceptance() -> tuple[dict, bytes, bytes]:
    decision = yaml.safe_load(TC003_BOUNDED_DECISION.read_text(encoding="utf-8"))
    if not isinstance(decision, dict) or set(decision) != {
        "schema_version", "case_id", "product_status", "bounded_acceptance",
    } or decision.get("schema_version") != 1:
        raise ValueError("TC003_BOUNDED_DECISION_SCHEMA_MISMATCH")
    if decision.get("case_id") != TC003_BOUNDED_EXPECTED["case_id"]:
        raise ValueError("TC003_BOUNDED_DECISION_CASE_ID_MISMATCH")
    if decision.get("product_status") != "NOT_RUN":
        raise ValueError("TC003_BOUNDED_DECISION_MUST_PRESERVE_PRODUCT_NOT_RUN")
    bounded = decision.get("bounded_acceptance")
    expected_fields = set(TC003_BOUNDED_EXPECTED) - {"case_id", "product_status"}
    if not isinstance(bounded, dict) or set(bounded) != expected_fields:
        raise ValueError("TC003_BOUNDED_DECISION_FIELDS_MISMATCH")
    for field, expected in TC003_BOUNDED_EXPECTED.items():
        if field not in {"case_id", "product_status"} and bounded.get(field) != expected:
            raise ValueError(f"TC003_BOUNDED_DECISION_{field.upper()}_MISMATCH")

    source_root = (ROOT / "artifacts" / "phase2").resolve(strict=True)
    evidence_source = (ROOT / bounded["source_evidence_path"]).resolve(strict=True)
    receipt_source = (ROOT / bounded["gpt_pm_adjudication_receipt_path"]).resolve(strict=True)
    for path in (evidence_source, receipt_source):
        try:
            path.relative_to(source_root)
        except ValueError as exc:
            raise ValueError("TC003_BOUNDED_SOURCE_EVIDENCE_OUTSIDE_ARTIFACTS_PHASE2") from exc
        if not path.is_file():
            raise ValueError("TC003_BOUNDED_SOURCE_EVIDENCE_NOT_FILE")
    for ref in (bounded["evidence_path"], bounded["gpt_pm_adjudication_package_receipt_path"]):
        package_ref = Path(ref)
        if package_ref.is_absolute() or ".." in package_ref.parts or not package_ref.parts:
            raise ValueError("TC003_BOUNDED_PACKAGE_PATH_INVALID")

    evidence_bytes = evidence_source.read_bytes().replace(b"\r\n", b"\n")
    receipt_bytes = receipt_source.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(evidence_bytes).hexdigest() != bounded["evidence_sha256"]:
        raise ValueError("TC003_BOUNDED_EVIDENCE_SHA256_MISMATCH")
    if hashlib.sha256(receipt_bytes).hexdigest() != bounded["gpt_pm_adjudication_receipt_sha256"]:
        raise ValueError("TC003_BOUNDED_PM_RECEIPT_SHA256_MISMATCH")

    def reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("TC003_BOUNDED_PM_RECEIPT_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    try:
        evidence = json.loads(evidence_bytes)
        receipt = json.loads(receipt_bytes, object_pairs_hook=reject_duplicate_json_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("TC003_BOUNDED_EVIDENCE_OR_RECEIPT_INVALID_JSON") from exc
    if not isinstance(evidence, dict) or not isinstance(receipt, dict):
        raise ValueError("TC003_BOUNDED_EVIDENCE_OR_RECEIPT_SCHEMA_MISMATCH")
    reply_text = receipt.get("reply_text")
    if not isinstance(reply_text, str):
        raise ValueError("TC003_BOUNDED_PM_RECEIPT_REPLY_MISSING")
    labels = ("PROJECT:", "TASK:", "REQUEST_ID:", "FINAL VERDICT:", "BOUNDED_TC003:", "PRODUCT_TC003:")
    if any(line.lstrip() != line and line.lstrip().startswith(labels) for line in reply_text.splitlines()):
        raise ValueError("TC003_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH")
    scalar_lines = {
        label: re.findall(rf"(?m)^{re.escape(label)}[ \t]*(.*?)[ \t]*$", reply_text)
        for label in labels
    }
    if (
        set(receipt) != {
            "schema_version", "project_id", "conversation_id", "job_id", "request_id",
            "reply_id", "payload_hash", "correlated", "candidate_head", "verdict",
            "bounded_status", "product_status", "reply_text", "reply_sha256",
        }
        or receipt.get("schema_version") != 1
        or receipt.get("project_id") != "erp_mcp"
        or receipt.get("job_id") != bounded["gpt_pm_adjudication_job_id"]
        or receipt.get("request_id") != bounded["gpt_pm_adjudication_request_id"]
        or receipt.get("reply_id") != bounded["gpt_pm_adjudication_reply_id"]
        or receipt.get("payload_hash") != bounded["gpt_pm_adjudication_payload_sha256"]
        or receipt.get("correlated") is not True
        or receipt.get("candidate_head") != bounded["exact_head"]
        or receipt.get("verdict") != "APPROVE"
        or receipt.get("bounded_status") != "SATISFIED"
        or receipt.get("product_status") != "NOT_RUN"
        or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", str(receipt.get("conversation_id", "")))
        or scalar_lines != {
            "PROJECT:": ["ERP_MCP"],
            "TASK:": ["R2-US-001 / R2-TC-003 — Moving HEAD is not deployment evidence"],
            "REQUEST_ID:": [bounded["gpt_pm_adjudication_request_id"]],
            "FINAL VERDICT:": ["APPROVE"],
            "BOUNDED_TC003:": ["SATISFIED"],
            "PRODUCT_TC003:": ["NOT_RUN"],
        }
        or hashlib.sha256(reply_text.encode("utf-8")).hexdigest() != bounded["gpt_pm_adjudication_reply_sha256"]
        or receipt.get("reply_sha256") != bounded["gpt_pm_adjudication_reply_sha256"]
    ):
        raise ValueError("TC003_BOUNDED_PM_RECEIPT_CONTENT_MISMATCH")

    for path_field, worktree_hash_field, blob_oid_field, blob_hash_field in (
        ("assembler_path", "assembler_worktree_sha256", "assembler_git_blob_oid", "assembler_candidate_blob_sha256"),
        ("test_path", "test_worktree_sha256", "test_git_blob_oid", "test_candidate_blob_sha256"),
    ):
        path = bounded[path_field]
        candidate_blob = _git_file_at_revision(bounded["exact_head"], path)
        worktree_blob = (ROOT / path).read_bytes()
        git_oid = subprocess.check_output(["git", "rev-parse", f"{bounded['exact_head']}:{path}"], cwd=ROOT, text=True).strip()
        if (
            git_oid != bounded[blob_oid_field]
            or hashlib.sha256(candidate_blob).hexdigest() != bounded[blob_hash_field]
            or hashlib.sha256(worktree_blob.replace(b"\r\n", b"\n")).hexdigest() != bounded[blob_hash_field]
            or not re.fullmatch(r"[a-f0-9]{64}", bounded[worktree_hash_field])
        ):
            raise ValueError("TC003_BOUNDED_SOURCE_CONTENT_MISMATCH")

    regression = evidence.get("regression", {})
    sources = evidence.get("sources", {})
    outcomes = {
        "deployment_sha_omitted": "UNKNOWN",
        "deployment_sha_differs_from_pr_head": "CLAIM_UNVERIFIED",
        "deployment_sha_equals_pr_head": "CLAIM_UNVERIFIED",
        "malformed_deployment_sha": "REJECTED",
    }
    if (
        evidence.get("scenario") != "R2-TC-003"
        or evidence.get("bounded_criterion") != bounded["criterion"]
        or evidence.get("scope") != bounded["scope"]
        or evidence.get("candidate", {}).get("commit") != bounded["exact_head"]
        or evidence.get("product_status") != "NOT_RUN"
        or evidence.get("gherkin_status") != "@not_implemented"
        or evidence.get("limitations") != bounded["limitations"]
        or regression.get("command") != bounded["regression_command"]
        or regression.get("execution_head") != bounded["exact_head"]
        or regression.get("result") != "PASS"
        or regression.get("exit_code") != 0
        or regression.get("passed") != 4
        or regression.get("outcomes") != outcomes
        or regression.get("owner") != "functional-test-reviewer"
        or sources.get("assembler", {}).get("path") != bounded["assembler_path"]
        or sources.get("assembler", {}).get("worktree_sha256") != bounded["assembler_worktree_sha256"]
        or sources.get("assembler", {}).get("candidate_git_blob_oid") != bounded["assembler_git_blob_oid"]
        or sources.get("assembler", {}).get("candidate_blob_sha256") != bounded["assembler_candidate_blob_sha256"]
        or sources.get("tests", {}).get("path") != bounded["test_path"]
        or sources.get("tests", {}).get("worktree_sha256") != bounded["test_worktree_sha256"]
        or sources.get("tests", {}).get("candidate_git_blob_oid") != bounded["test_git_blob_oid"]
        or sources.get("tests", {}).get("candidate_blob_sha256") != bounded["test_candidate_blob_sha256"]
        or sources.get("catalog", {}).get("case_actual_status") != "NOT_RUN"
        or sources.get("gherkin", {}).get("case_tag") != "@not_implemented"
        or sources.get("gate_manifest", {}).get("release_2") != "NO_GO"
        or sources.get("gate_manifest", {}).get("production_authorization") != "NONE"
        or evidence.get("provider_attestation", {}).get("status") != "NOT_FOUND_IN_NAMED_REPOSITORY_EVIDENCE"
        or evidence.get("provider_attestation", {}).get("does_not_prove_external_deployment_absence") is not True
        or evidence.get("implementation_invariants", {}).get("deployment_identity_inferred_from_head") is not False
        or evidence.get("implementation_invariants", {}).get("production_decision") != "NO-GO"
    ):
        raise ValueError("TC003_BOUNDED_EVIDENCE_CONTENT_MISMATCH")
    for source_name, source_path in (
        ("catalog", "docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/test_cases.yaml"),
        ("gherkin", "docs/phase2/spec-v0.1/ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08/acceptance/phase2.feature"),
        ("gate_manifest", "governance/GATE_MANIFEST.json"),
    ):
        source = sources.get(source_name, {})
        candidate_bytes = _git_file_at_revision(bounded["exact_head"], source_path)
        expected_candidate_hash = source.get("candidate_blob_sha256", source.get("sha256"))
        if hashlib.sha256(candidate_bytes).hexdigest() != expected_candidate_hash:
            raise ValueError("TC003_BOUNDED_RECORDED_SOURCE_HASH_MISMATCH")
        if source.get("candidate_git_blob_oid"):
            actual_oid = subprocess.check_output(
                ["git", "rev-parse", f"{bounded['exact_head']}:{source_path}"], cwd=ROOT, text=True,
            ).strip()
            if actual_oid != source["candidate_git_blob_oid"]:
                raise ValueError("TC003_BOUNDED_RECORDED_SOURCE_GIT_OID_MISMATCH")
    return bounded, evidence_bytes, receipt_bytes


def make_data(
    tc001_bounded_acceptance: dict | None = None,
    tc002_bounded_acceptance: dict | None = None,
    tc003_bounded_acceptance: dict | None = None,
):
    tdd = (DOCS / "TDD_PHASE2_RU.md").read_text(encoding="utf-8")
    stories_md = (DOCS / "STORIES_PHASE2_RU.md").read_text(encoding="utf-8")
    requirements = []
    for line in tdd.splitlines():
        m = re.match(r"^\|\s*(R2-REQ-\d{2})\s*\|\s*(.+?)\s*\|$", line)
        if m:
            requirements.append({"id": m.group(1), "statement": m.group(2), "status": "PLANNED"})
    stories, tests = [], []
    seen_story_ids = set()
    for line in stories_md.splitlines():
        if not re.match(r"^\|\s*R2-US-\d{3}\s*\|", line):
            continue
        cols = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cols) != 5:
            raise ValueError(f"story table row structure changed: {line[:100]}")
        story_id, stage, title, reqs, cases = cols
        # Later rows may repeat a canonical story to append implementation notes.
        # The first row remains the acceptance source for the 48-story spec bundle.
        if story_id in seen_story_ids:
            continue
        seen_story_ids.add(story_id)
        # The narrative may list related requirements after a semicolon.
        # Only the text before that separator defines formal acceptance links.
        formal_reqs = reqs.split(";", 1)[0]
        req_ids = [f"R2-REQ-{number}" for number in re.findall(r"\bREQ(\d{2})\b", formal_reqs)]
        stories.append({"id": story_id, "stage": stage, "title": title, "requirements": req_ids, "status": "PLANNED"})
        found = re.findall(r"(?:^|;\s*)TC(\d{3})\s+([^;]+)", cases)
        if len(found) != 3:
            raise ValueError(f"expected 3 tests for {story_id}; found {len(found)}")
        for j, (number, description) in enumerate(found):
            tests.append({
                "id": f"R2-TC-{number}",
                "story": story_id, "requirements": req_ids, "kind": ["positive", "negative", "boundary_recovery"][j],
                "expectation": description.strip(), "actual_status": "NOT_RUN",
            })
    if tc001_bounded_acceptance is None:
        tc001_bounded_acceptance, _ = load_tc001_bounded_acceptance()
    else:
        validate_tc001_bounded_fields(tc001_bounded_acceptance)
    if tc002_bounded_acceptance is None:
        tc002_bounded_acceptance, _, _ = load_tc002_bounded_acceptance()
    else:
        validate_tc002_bounded_fields(tc002_bounded_acceptance)
    if tc003_bounded_acceptance is None:
        tc003_bounded_acceptance, _, _ = load_tc003_bounded_acceptance()
    elif not isinstance(tc003_bounded_acceptance, dict) or set(tc003_bounded_acceptance) != set(TC003_BOUNDED_EXPECTED) - {"case_id", "product_status"}:
        raise ValueError("TC003_BOUNDED_DECISION_FIELDS_MISMATCH")
    else:
        for field, expected in TC003_BOUNDED_EXPECTED.items():
            if field not in {"case_id", "product_status"} and tc003_bounded_acceptance.get(field) != expected:
                raise ValueError(f"TC003_BOUNDED_DECISION_{field.upper()}_MISMATCH")
    tc001 = [case for case in tests if case["id"] == "R2-TC-001"]
    if len(tc001) != 1:
        raise AssertionError("expected exactly one R2-TC-001")
    tc001[0]["bounded_acceptance"] = tc001_bounded_acceptance
    tc002 = [case for case in tests if case["id"] == "R2-TC-002"]
    if len(tc002) != 1:
        raise AssertionError("expected exactly one R2-TC-002")
    tc002[0]["bounded_acceptance"] = tc002_bounded_acceptance
    tc003 = [case for case in tests if case["id"] == "R2-TC-003"]
    if len(tc003) != 1:
        raise AssertionError("expected exactly one R2-TC-003")
    tc003[0]["bounded_acceptance"] = tc003_bounded_acceptance
    if (len(requirements), len(stories), len(tests)) != (28, 48, 144):
        raise AssertionError((len(requirements), len(stories), len(tests)))
    if len({i["id"] for i in requirements}) != 28 or len({i["id"] for i in stories}) != 48 or len({i["id"] for i in tests}) != 144:
        raise AssertionError("duplicate identifier")
    known = {x["id"] for x in requirements}
    if any(set(s["requirements"]) - known for s in stories):
        raise AssertionError("unknown requirement")
    save("requirements.yaml", yaml.safe_dump(requirements, allow_unicode=True, sort_keys=False))
    save("stories.yaml", yaml.safe_dump(stories, allow_unicode=True, sort_keys=False))
    save("test_cases.yaml", yaml.safe_dump(tests, allow_unicode=True, sort_keys=False))
    return requirements, stories, tests


def schemas_and_fixtures():
    schemas = {
        "capture_request": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_id", "company_id", "recipe_id", "recipe_version", "scope_epoch", "idempotency_key", "environment"],
            "properties": {
                "source_id": {"type": "string", "minLength": 1},
                "company_id": {"type": "string", "format": "uuid"},
                "recipe_id": {"type": "string", "minLength": 1},
                "recipe_version": {"type": "integer", "minimum": 1},
                "scope_epoch": {"type": "integer", "minimum": 0},
                "idempotency_key": {"type": "string", "minLength": 8},
                "environment": {"enum": ["DEV_REFERENCE", "STAGING", "PROD"]},
            }
        },
        "model_event": {
            "type": "object", "additionalProperties": False,
            "required": ["event_id", "source_id", "recorded_at", "observed_at", "payload_sha256", "status"],
            "properties": {
                "event_id": {"type": "string", "format": "uuid"},
                "source_id": {"type": "string"},
                "recorded_at": {"type": "string", "format": "date-time"},
                "observed_at": {"type": "string", "format": "date-time"},
                "source_effective_at": {"type": ["string", "null"], "format": "date-time"},
                "payload_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "status": {"enum": ["OBSERVED", "ACCEPTED", "DRIFTED", "INCONCLUSIVE"]},
            }
        },
        "native_manifest": {
            "type": "object", "additionalProperties": False,
            "required": ["source_id", "company_id", "report_name", "period", "artifact_sha256", "evidence_status"],
            "properties": {
                "source_id": {"type": "string"}, "company_id": {"type": "string", "format": "uuid"},
                "report_name": {"type": "string", "minLength": 1},
                "period": {"type": "string"},
                "artifact_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "evidence_status": {"enum": ["UNATTESTED", "ORIGIN_VERIFIED", "ATTESTED", "REVOKED"]},
            }
        },
        "reconciliation_result": {
            "type": "object", "additionalProperties": False,
            "required": ["source_id", "company_id", "status", "opening_debit", "opening_credit", "turnover_debit", "turnover_credit", "closing_debit", "closing_credit"],
            "properties": {
                "source_id": {"type": "string"}, "company_id": {"type": "string", "format": "uuid"},
                "status": {"enum": ["MATCH", "MISMATCH", "INCONCLUSIVE", "NOT_RUN"]},
                **{f: {"type": "string", "pattern": r"^-?\d+\.\d{2}$"} for f in [
                    "opening_debit", "opening_credit", "turnover_debit", "turnover_credit", "closing_debit", "closing_credit"]},
            }
        },
    }
    examples = {
        "capture_request": {"source_id": "synthetic-source", "company_id": "00000000-0000-4000-8000-000000000001", "recipe_id": "ui_trial_balance", "recipe_version": 1, "scope_epoch": 1, "idempotency_key": "synthetic-0001", "environment": "DEV_REFERENCE"},
        "model_event": {"event_id": "00000000-0000-4000-8000-000000000002", "source_id": "synthetic-source", "recorded_at": "2026-01-01T12:00:00Z", "observed_at": "2026-01-01T11:59:50Z", "source_effective_at": None, "payload_sha256": "1"*64, "status": "OBSERVED"},
        "native_manifest": {"source_id": "synthetic-source", "company_id": "00000000-0000-4000-8000-000000000001", "report_name": "SYNTHETIC DEMO ONLY", "period": "2026-01", "artifact_sha256": "2"*64, "evidence_status": "UNATTESTED"},
        "reconciliation_result": {"source_id": "synthetic-source", "company_id": "00000000-0000-4000-8000-000000000001", "status": "NOT_RUN", "opening_debit": "0.00", "opening_credit": "100.00", "turnover_debit": "20.00", "turnover_credit": "5.00", "closing_debit": "0.00", "closing_credit": "85.00"},
    }
    for name, schema in schemas.items():
        save(f"schemas/{name}.schema.json", json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}, ensure_ascii=False, indent=2) + "\n")
        save(f"examples/{name}.json", json.dumps(examples[name], ensure_ascii=False, indent=2) + "\n")


def main():
    PACKAGE.parent.mkdir(parents=True, exist_ok=True)
    if PACKAGE.exists():
        marker_path = PACKAGE / ".generation_marker"
        if not marker_path.exists() or marker_path.read_text(encoding="utf-8") != MARKER:
            raise RuntimeError("PACKAGE_DESTINATION_EXISTS_UNOWNED")
        # Do not delete prior generated files. Only update expected files.
    else:
        PACKAGE.mkdir()
    save(".generation_marker", MARKER)
    for src, dest in DOC_MAP.items():
        file = DOCS / src
        if not file.exists():
            raise FileNotFoundError(file)
        save(dest, file.read_text(encoding="utf-8"))
    bounded, evidence_bytes = load_tc001_bounded_acceptance()
    tc002_bounded, tc002_evidence_bytes, tc002_receipt_bytes = load_tc002_bounded_acceptance()
    tc003_bounded, tc003_evidence_bytes, tc003_receipt_bytes = load_tc003_bounded_acceptance()
    reqs, stories, cases = make_data(bounded, tc002_bounded, tc003_bounded)
    decision = TC001_BOUNDED_DECISION.read_bytes()
    save("docs/11_TC001_BOUNDED_ACCEPTANCE.yaml", decision)
    save(bounded["evidence_path"], evidence_bytes)
    tc002_decision = TC002_BOUNDED_DECISION.read_bytes()
    save("docs/12_TC002_BOUNDED_ACCEPTANCE.yaml", tc002_decision)
    save(tc002_bounded["evidence_path"], tc002_evidence_bytes)
    if tc002_receipt_bytes is not None:
        save(tc002_bounded["gpt_pm_adjudication_package_receipt_path"], tc002_receipt_bytes)
    save("docs/13_TC003_BOUNDED_ACCEPTANCE.yaml", TC003_BOUNDED_DECISION.read_bytes())
    save(tc003_bounded["evidence_path"], tc003_evidence_bytes)
    save(tc003_bounded["gpt_pm_adjudication_package_receipt_path"], tc003_receipt_bytes)
    schemas_and_fixtures()
    save("README.md", "# Derived Phase 2 specification bundle\n\n"
         "This package is rebuilt from the committed Phase 2 documents on the local checkout. "
         "It is NOT byte-for-byte the original ZIP attached in the earlier ChatGPT turn. "
         "All product acceptance cases are NOT_RUN; bounded adjudication metadata does not change product status. "
         "No 1C/production work is represented.\n")
    save("acceptance/phase2.feature", (
        "# Specification-only Gherkin: steps deliberately NOT implemented, product results NOT_RUN.\n"
        "Feature: Phase 2 acceptance specifications\n\n"
        + "".join(
            f"  @not_implemented @R2TC{case['id'][-3:]}\n"
            f"  Scenario: {case['id']} {case['expectation']}\n"
            f"    Given a scoped test environment for {case['story']}\n"
            f"    When the relevant Phase 2 capability is exercised\n"
            f"    Then the product must demonstrate {case['expectation']}\n\n"
            for case in cases
        )).rstrip() + "\n")
    with (PACKAGE / "traceability.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["test_id", "story_id", "requirement_id", "expected", "actual_status"])
        for case in cases:
            for req in case["requirements"]:
                writer.writerow([case["id"], case["story"], req, case["expectation"], "NOT_RUN"])
    # All documents included in the offline index, without external scripts or CDN.
    links = "\n".join(
        f'<li><a href="{html.escape(dest, quote=True)}">{html.escape(src)}</a></li>'
        for src, dest in DOC_MAP.items()
    )
    save("index.html", (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<title>ERP_MCP Phase 2 — specification</title>"
        "<style>body{max-width:900px;margin:2rem auto;padding:1rem;font:1rem system-ui}"
        "li{margin:.55rem}a{color:#1673ad}</style><h1>Phase 2 — specification</h1>"
        "<p>Isolated project package. 144 product checks: NOT_RUN.</p><ul>"
        + links + "</ul></html>"
    ))
    save("validation_report.json", json.dumps({
        "package": NAME, "scope": "SPEC_L0_ONLY", "requirements": len(reqs),
        "stories": len(stories), "product_cases": len(cases),
        "product_tests": "NOT_RUN", "native_1c": "NOT_RUN", "production": "NOT_RUN",
    }, indent=2) + "\n")
    # Hash manifest covers every content file except the manifest itself.
    records = []
    for file in sorted(PACKAGE.rglob("*")):
        if file.is_file() and file.name != "MANIFEST.sha256":
            name = file.relative_to(PACKAGE).as_posix()
            records.append(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {name}")
    save("MANIFEST.sha256", "\n".join(records) + "\n")
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        for file in sorted(PACKAGE.rglob("*")):
            if file.is_file():
                arcname = f"{NAME}/{file.relative_to(PACKAGE).as_posix()}"
                info = zipfile.ZipInfo(arcname, date_time=(2026, 10, 8, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o644 << 16
                zipf.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(ARCHIVE) as zipf:
        if zipf.testzip() is not None:
            raise RuntimeError("ARCHIVE_CRC_FAILURE")
    print(f"PHASE2_REBUILT={ARCHIVE}")
    print(f"CONTENT_FILES={len(records)} REQUIREMENTS={len(reqs)} STORIES={len(stories)} CASES={len(cases)}")
    print(f"ZIP_SHA256={hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
