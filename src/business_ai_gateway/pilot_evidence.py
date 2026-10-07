from __future__ import annotations

import re
from datetime import datetime
from typing import Any

BASE_PILOT_GATES = frozenset(
    {
        "ci_green",
        "production_config_review",
        "idp_authz_negative_tests",
        "secret_rotation_drill",
        "source_company_isolation",
        "source_capability_profiles",
        "ten_case_native_reconciliation",
        "zero_write_review",
        "audit_provenance_review",
        "performance_load_test",
        "resilience_drills",
        "backup_restore_drill",
        "rollback_drill",
        "operations_oncall",
        "privacy_security_review",
    }
)
GO_GATES = BASE_PILOT_GATES | {"pilot_user_acceptance", "production_release_approval"}
GATE_NAMES = GO_GATES
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT = re.compile(r"^[A-Z0-9][A-Z0-9._-]{2,127}$")
_GATE_FIELDS = {"status", "evidence"}
_EVIDENCE_FIELDS = {"artifact_id", "sha256", "reviewed_by", "reviewed_at"}


def _is_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_pilot_manifest(manifest: Any) -> tuple[list[str], bool]:
    """Validate a privacy-safe P9 manifest and whether its claimed decision is supported."""
    issues: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"], False

    allowed_top = {"schema_version", "decision", "release", "pilot_scope", "gates"}
    unknown_top = set(manifest) - allowed_top
    if unknown_top:
        issues.append(f"unknown top-level fields: {', '.join(sorted(unknown_top))}")
    if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1:
        issues.append("schema_version must be 1")

    decision = manifest.get("decision")
    if not isinstance(decision, str) or decision not in {
        "NOT_READY",
        "PILOT_READY",
        "PRODUCTION_GO",
    }:
        issues.append("decision must be NOT_READY, PILOT_READY, or PRODUCTION_GO")
        decision = None

    release = manifest.get("release")
    if not isinstance(release, dict):
        issues.append("release must be an object")
        release = {}
    if set(release) - {"commit_sha", "tag", "approved_by", "approved_at"}:
        issues.append("release contains unknown fields")
    if decision in {"PILOT_READY", "PRODUCTION_GO"}:
        if not isinstance(release.get("commit_sha"), str) or not _COMMIT.fullmatch(
            release["commit_sha"]
        ):
            issues.append("release.commit_sha must be the exact 40-character release commit")
        if decision == "PRODUCTION_GO":
            if not isinstance(release.get("tag"), str) or not release["tag"].strip():
                issues.append("production GO requires an immutable release tag")
            if not isinstance(release.get("approved_by"), str) or not release[
                "approved_by"
            ].strip():
                issues.append("production GO requires a named release approver")
            if not _is_timestamp(release.get("approved_at")):
                issues.append("production GO requires an offset-qualified approval timestamp")

    scope = manifest.get("pilot_scope")
    if not isinstance(scope, dict):
        issues.append("pilot_scope must be an object")
        scope = {}
    if set(scope) - {"pilot_id", "owner", "source_count", "company_count", "user_count"}:
        issues.append("pilot_scope contains unknown fields")
    if decision in {"PILOT_READY", "PRODUCTION_GO"}:
        for field in ("pilot_id", "owner"):
            if not isinstance(scope.get(field), str) or not scope[field].strip():
                issues.append(f"pilot_scope.{field} is required for a release decision")
        for field in ("source_count", "company_count", "user_count"):
            value = scope.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                issues.append(f"pilot_scope.{field} must be a positive integer")

    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        issues.append("gates must be an object")
        gates = {}
    if set(gates) != GATE_NAMES:
        missing = GATE_NAMES - set(gates)
        extra = set(gates) - GATE_NAMES
        if missing:
            issues.append(f"missing gates: {', '.join(sorted(missing))}")
        if extra:
            issues.append(f"unknown gates: {', '.join(sorted(extra))}")

    required = (
        BASE_PILOT_GATES
        if decision == "PILOT_READY"
        else GO_GATES
        if decision == "PRODUCTION_GO"
        else frozenset()
    )
    for name, gate in gates.items():
        if not isinstance(gate, dict):
            issues.append(f"gate {name} must be an object")
            continue
        if set(gate) - _GATE_FIELDS:
            issues.append(f"gate {name} contains unknown fields")
        status = gate.get("status")
        if not isinstance(status, str) or status not in {"NOT_PROVIDED", "VERIFIED"}:
            issues.append(f"gate {name} status must be NOT_PROVIDED or VERIFIED")
            continue
        evidence = gate.get("evidence")
        if status == "VERIFIED":
            if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_FIELDS:
                issues.append(f"verified gate {name} requires complete evidence metadata")
                continue
            if not isinstance(evidence.get("artifact_id"), str) or not _ARTIFACT.fullmatch(
                evidence["artifact_id"]
            ):
                issues.append(f"gate {name} has invalid artifact_id")
            if not isinstance(evidence.get("sha256"), str) or not _SHA.fullmatch(
                evidence["sha256"]
            ):
                issues.append(f"gate {name} requires a lowercase SHA-256 digest")
            for field in ("reviewed_by",):
                if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                    issues.append(f"gate {name} requires {field}")
            if not _is_timestamp(evidence.get("reviewed_at")):
                issues.append(f"gate {name} requires an offset-qualified reviewed_at")
        elif evidence is not None:
            issues.append(f"unverified gate {name} must not carry evidence metadata")
        if name in required and status != "VERIFIED":
            issues.append(f"release decision {decision} is blocked by gate {name}")

    ready = decision == "PRODUCTION_GO" and not issues
    return issues, ready
