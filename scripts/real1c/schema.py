"""Case-result schema validation (pure, returns error lists)."""

from __future__ import annotations

import re
from typing import Any

from .disposition import CATALOGUE_CLASSES, DISPOSITIONS, PASS
from .evidence import EVIDENCE_CLASSES

CASE_RESULT_SCHEMA_VERSION = 1
KINDS = ("ST", "AX", "NR", "INV", "RULE", "RL2", "ACL", "SYS")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")
_VALIDATED_CLAIM = re.compile(r"(?i)\bvalidated\b|PROFILE_VALIDATED|VALIDATED_NATIVE")
_REQUIRED = (
    "schema_version",
    "case_id",
    "kind",
    "title",
    "catalogue_class",
    "disposition",
    "reason_code",
    "evidence_classes",
    "observations",
    "tools_called",
    "oracle",
    "git_sha",
    "manifest_sha256",
    "finished_at",
)


def _check_obs(items: Any, name: str, errors: list[str]) -> list[dict[str, Any]]:
    good: list[dict[str, Any]] = []
    if not isinstance(items, list):
        errors.append(f"{name} must be a list")
        return good
    for i, o in enumerate(items):
        if not isinstance(o, dict) or not all(
            isinstance(o.get(k), str) for k in ("probe", "outcome", "detail")
        ):
            errors.append(f"{name}[{i}] must be {{probe, outcome, detail}} strings")
        else:
            good.append(o)
    return good


def validate_case_result(d: Any) -> list[str]:
    if not isinstance(d, dict):
        return ["result must be a dict"]
    errors = [f"missing key: {k}" for k in _REQUIRED if k not in d]
    if errors:
        return errors
    if d["schema_version"] != CASE_RESULT_SCHEMA_VERSION or isinstance(d["schema_version"], bool):
        errors.append(f"schema_version must be {CASE_RESULT_SCHEMA_VERSION}")
    for key in ("case_id", "title", "reason_code"):
        if not isinstance(d[key], str) or not d[key]:
            errors.append(f"{key} must be a non-empty string")
    if not isinstance(d["oracle"], str):
        errors.append("oracle must be a string")
    if d["kind"] not in KINDS:
        errors.append(f"kind must be one of {KINDS}")
    if d["catalogue_class"] is not None and d["catalogue_class"] not in CATALOGUE_CLASSES:
        errors.append("catalogue_class must be RR/NP/UG/EV/WD or None")
    if d["kind"] in ("ST", "AX") and d["catalogue_class"] is None:
        errors.append("catalogue kinds need a catalogue_class")
    if d["disposition"] not in DISPOSITIONS:
        errors.append(f"disposition must be one of {DISPOSITIONS}")
    ev = d["evidence_classes"]
    if not isinstance(ev, list) or not all(isinstance(x, str) for x in ev):
        errors.append("evidence_classes must be a list of strings")
        ev = []
    else:
        unknown = sorted(set(ev) - EVIDENCE_CLASSES)
        if unknown:
            errors.append(f"unknown evidence classes: {unknown}")
    obs = _check_obs(d["observations"], "observations", errors)
    sup = _check_obs(d.get("supplementary", []), "supplementary", errors)
    tools = d["tools_called"]
    if not isinstance(tools, list) or not all(isinstance(x, str) for x in tools):
        errors.append("tools_called must be a list of strings")
    if not isinstance(d["git_sha"], str) or not _HEX40.match(d["git_sha"]):
        errors.append("git_sha must be 40 lowercase hex")
    if not isinstance(d["manifest_sha256"], str) or not _HEX64.match(d["manifest_sha256"]):
        errors.append("manifest_sha256 must be 64 lowercase hex")
    if not isinstance(d["finished_at"], str) or not _ISO.match(d["finished_at"]):
        errors.append("finished_at must be an ISO timestamp")
    if "owner_action" in d and not isinstance(d["owner_action"], str):
        errors.append("owner_action must be a string")
    if "req_gap_refs" in d and not isinstance(d["req_gap_refs"], list):
        errors.append("req_gap_refs must be a list")
    if d["disposition"] == PASS:
        if d["catalogue_class"] != "RR":
            errors.append("PASS is allowed only for catalogue_class RR")
        if not obs:
            errors.append("PASS requires at least one observation")
        if set(ev) <= {"NONE"}:
            errors.append("PASS requires evidence_classes other than only NONE")
    if "NATIVE_COM_QUERY" in ev:
        for o in obs + sup:
            if _VALIDATED_CLAIM.search(o["detail"]):
                errors.append("NATIVE_COM_QUERY is comparison-only; no validated claim allowed")
                break
    return errors
