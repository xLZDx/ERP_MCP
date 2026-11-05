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
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "phase2"
NAME = "ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08"
PACKAGE = DOCS / "spec-v0.1" / NAME
ARCHIVE = DOCS / "artifacts" / f"{NAME}.zip"
TC001_BOUNDED_DECISION = DOCS / "TC001_BOUNDED_ACCEPTANCE.yaml"
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


def make_data(bounded_acceptance: dict | None = None):
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
    if bounded_acceptance is None:
        bounded_acceptance, _ = load_tc001_bounded_acceptance()
    else:
        validate_tc001_bounded_fields(bounded_acceptance)
    tc001 = [case for case in tests if case["id"] == "R2-TC-001"]
    if len(tc001) != 1:
        raise AssertionError("expected exactly one R2-TC-001")
    tc001[0]["bounded_acceptance"] = bounded_acceptance
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
    reqs, stories, cases = make_data(bounded)
    decision = TC001_BOUNDED_DECISION.read_bytes()
    save("docs/11_TC001_BOUNDED_ACCEPTANCE.yaml", decision)
    save(bounded["evidence_path"], evidence_bytes)
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
