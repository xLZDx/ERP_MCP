from __future__ import annotations

import copy
import json
from pathlib import Path

from business_ai_gateway.pilot_evidence import GATE_NAMES, validate_pilot_manifest

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "deploy/pilot/evidence.manifest.template.json"
)


def _manifest():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def _verified_go_manifest():
    manifest = _manifest()
    manifest["decision"] = "PRODUCTION_GO"
    manifest["release"] = {
        "commit_sha": "a" * 40,
        "tag": "erp-mcp-pilot-1.0.0",
        "approved_by": "release-owner",
        "approved_at": "2026-10-06T12:00:00Z",
    }
    manifest["pilot_scope"] = {
        "pilot_id": "PILOT-001",
        "owner": "pilot-owner",
        "source_count": 1,
        "company_count": 1,
        "user_count": 2,
    }
    for name in GATE_NAMES:
        manifest["gates"][name] = {
            "status": "VERIFIED",
            "evidence": {
                "artifact_id": f"EVIDENCE-{name.upper()}",
                "sha256": "b" * 64,
                "reviewed_by": "independent-reviewer",
                "reviewed_at": "2026-10-06T12:00:00+00:00",
            },
        }
    return manifest


def test_empty_template_is_valid_but_never_claims_readiness():
    issues, go_ready = validate_pilot_manifest(_manifest())
    assert issues == []
    assert go_ready is False


def test_production_go_is_blocked_by_missing_evidence():
    manifest = _manifest()
    manifest["decision"] = "PRODUCTION_GO"
    issues, go_ready = validate_pilot_manifest(manifest)

    assert go_ready is False
    assert any("ci_green" in issue for issue in issues)
    assert any("ten_case_native_reconciliation" in issue for issue in issues)


def test_complete_reviewed_evidence_is_required_for_go():
    manifest = _verified_go_manifest()
    issues, go_ready = validate_pilot_manifest(manifest)
    assert issues == []
    assert go_ready is True

    bad_digest = copy.deepcopy(manifest)
    bad_digest["gates"]["zero_write_review"]["evidence"]["sha256"] = "not-a-digest"
    issues, go_ready = validate_pilot_manifest(bad_digest)
    assert go_ready is False
    assert any("zero_write_review" in issue for issue in issues)


def test_manifest_rejects_freeform_fields_and_unhashable_decisions():
    manifest = _manifest()
    manifest["customer_name"] = "must-not-be-stored"
    manifest["decision"] = ["PRODUCTION_GO"]

    issues, go_ready = validate_pilot_manifest(manifest)
    assert go_ready is False
    assert any("unknown top-level" in issue for issue in issues)
    assert any("decision must be" in issue for issue in issues)
