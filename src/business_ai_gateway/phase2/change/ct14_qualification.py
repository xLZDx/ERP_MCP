"""Offline, provenance-bound CT14 qualification record checks.

This module evaluates evidence eligibility only. It does not authorize or
perform a 1C operation and is not connected to a write port.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

RECORD_RELATIVE_PATH = Path("docs/phase2/artifacts/CT14_QUALIFICATION_RECORD_V1.json")
EXPECTED_RECORD_SHA256 = "ada2de7ef64e023b7a30abd4103b08aa0782932e70372366832de7a689234f6a"
VALID_STATES = frozenset({"SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE", "NOT_MEASURED"})
VALID_OBSERVATION_STATES = VALID_STATES | {"OBSERVED_WEAK"}
EXPECTED_SOURCES = {
    "docs/phase2/S11_TEST_DESIGN_PACKAGE_2026-10-12.md": (
        "eb12d608a6c7afb03e5a0d57f96bdf186721f88057a750cfbadf8079e7bd5c38",
        "a13c332a58cf3cb89cd526ad5a8011f16fa272311d7596995c0fdba038f35b1b",
    ),
    "docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md": (
        "204d1848793798baa0b2fa06f0b187e782069eeec29f179283b730a42aee0813",
        "628d527a78cb699e8dc8e88050b92f414bb8e7ce29862edc546fb22e8f8124a6",
    ),
    "docs/phase2/artifacts/CT14_METADATA_INVENTORY_IVAN_2026-10-27.json": (
        "13c4f98f30b6387e8b07df0719e1d20616e4ec4c237b07faa84699101c2f9283",
        "13c4f98f30b6387e8b07df0719e1d20616e4ec4c237b07faa84699101c2f9283",
    ),
    "docs/phase2/artifacts/CT14_DRAFT_DESTINATION_TYPES_2026-10-27.json": (
        "214896b219d37e23c67a2417c299aa12d5955e09eb3608b3ed4c6c94711c2425",
        "214896b219d37e23c67a2417c299aa12d5955e09eb3608b3ed4c6c94711c2425",
    ),
    "docs/phase2/artifacts/CT14_VAT_ENUMERATION_SEMANTICS_2026-10-27.json": (
        "a86d9dc9a01040263529f088c58e3423329067633c782ed59776b549f4e6b55b",
        "a86d9dc9a01040263529f088c58e3423329067633c782ed59776b549f4e6b55b",
    ),
    "docs/phase2/artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json": (
        "7d34ba423197851f0e2fd16d65a47eed2bfd6b43090d0367dd5566ee97fdf310",
        "7d34ba423197851f0e2fd16d65a47eed2bfd6b43090d0367dd5566ee97fdf310",
    ),
    "docs/phase2/artifacts/CT14_EFFECTIVE_RIGHTS_2026-10-27.json": (
        "4547abaeb7a9963a4ebbf24ed77493b6ed2916d3abcfcffba36debf324676ab6",
        "2f44531a67360b7e7388ca819ab4f796dedc54f214bbd21554509bd9e399f2a4",
    ),
}


def _canonical_source_sha256(data: bytes) -> str:
    """Hash UTF-8 source bytes with checkout-only CRLF normalized to LF."""
    data.decode("utf-8")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("CT14_SOURCE_ENCODING_INVALID")
    data = data.replace(b"\r\n", b"\n")
    if b"\r" in data:
        raise ValueError("CT14_SOURCE_LINE_ENDING_INVALID")
    return hashlib.sha256(data).hexdigest()


def _source_path(root: Path, relative: object) -> Path:
    if type(relative) is not str:
        raise ValueError("CT14_SOURCE_PATH_INVALID")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise ValueError("CT14_SOURCE_PATH_INVALID")
    candidate = (root / Path(*rel.parts)).resolve()
    resolved_root = root.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise ValueError("CT14_SOURCE_PATH_INVALID")
    return candidate


def _verify_sources(root: Path, sources: object) -> list[str]:
    if type(sources) is not list:
        return ["CT14_SOURCE_MANIFEST_INVALID"]
    reasons: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if type(source) is not dict:
            reasons.append("CT14_SOURCE_MANIFEST_INVALID")
            continue
        relative = source.get("path")
        try:
            path = _source_path(root, relative)
        except (TypeError, ValueError):
            reasons.append("CT14_SOURCE_PATH_INVALID")
            continue
        if relative in seen:
            reasons.append("CT14_SOURCE_DUPLICATE")
            continue
        seen.add(relative)
        expected_hashes = EXPECTED_SOURCES.get(relative)
        if expected_hashes is None or source.get("reviewed_sha256") != expected_hashes[1]:
            reasons.append("CT14_SOURCE_MANIFEST_INVALID")
            continue
        expected = source.get("canonical_sha256")
        if type(expected) is not str or expected != expected_hashes[0]:
            reasons.append("CT14_SOURCE_HASH_INVALID")
            continue
        try:
            actual = _canonical_source_sha256(path.read_bytes())
        except FileNotFoundError:
            reasons.append("CT14_SOURCE_EVIDENCE_MISSING")
            continue
        except (OSError, UnicodeDecodeError, ValueError):
            reasons.append("CT14_SOURCE_EVIDENCE_INVALID")
            continue
        if actual != expected:
            reasons.append("CT14_SOURCE_EVIDENCE_STALE")
            continue
        if path.suffix.lower() == ".json":
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                reasons.append("CT14_SOURCE_JSON_INVALID")
                continue
            clone = parsed.get("clone") if type(parsed) is dict else None
            if clone is not None and clone != "818HA_p2diff":
                reasons.append("CT14_SOURCE_SCOPE_MISMATCH")
    if seen != set(EXPECTED_SOURCES):
        reasons.append("CT14_SOURCE_MANIFEST_INCOMPLETE")
    return sorted(set(reasons))


def _validate_observations(record: dict[str, Any]) -> list[str]:
    items = record.get("capability_observations")
    if type(items) is not list:
        return ["CT14_CAPABILITY_RECORD_INVALID"]
    states_by_item_scope: dict[tuple[str, str], set[str]] = defaultdict(set)
    reasons: list[str] = []
    ids: set[str] = set()
    by_item_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if type(item) is not dict:
            reasons.append("CT14_CAPABILITY_RECORD_INVALID")
            continue
        item_id, scope_id, state = item.get("item_id"), item.get("scope_id"), item.get("status")
        if (type(item_id) is not str or not item_id or type(scope_id) is not str or not scope_id
                or type(state) is not str
                or state not in VALID_OBSERVATION_STATES):
            reasons.append("CT14_CAPABILITY_STATUS_INVALID")
            continue
        measurement_state = item.get("measurement_state")
        if measurement_state is not None and (
                type(measurement_state) is not str or measurement_state not in VALID_STATES):
            reasons.append("CT14_MEASUREMENT_STATE_INVALID")
            continue
        key = (item_id, scope_id)
        states_by_item_scope[key].add(state)
        observation_id = item.get("observation_id")
        if type(observation_id) is not str or not observation_id:
            reasons.append("CT14_OBSERVATION_ID_INVALID")
            continue
        if observation_id in ids:
            reasons.append("CT14_OBSERVATION_ID_INVALID")
            continue
        ids.add(observation_id)
        by_item_id[item_id] = item
        if item_id in {"9", "10b", "13"} and (state != "INCONCLUSIVE" or measurement_state != "NOT_MEASURED"):
            reasons.append("CT14_UNRESOLVED_LIMITATION_LOST")
    if (by_item_id.get("12-standard", {}).get("status") != "UNSUPPORTED"
            or by_item_id.get("12-custom", {}).get("status") != "SUPPORTED"):
        reasons.append("CT14_RIGHTS_SCOPE_DISTINCTION_LOST")
    marker = by_item_id.get("14", {}).get("limitation")
    if type(marker) is not str or "mutable" not in marker:
        reasons.append("CT14_MARKER_LIMITATION_LOST")
    if any(len(states) > 1 for states in states_by_item_scope.values()):
        reasons.append("CT14_EVIDENCE_CONTRADICTORY")
    return sorted(set(reasons))


def _verify_semantic_bindings(root: Path, record: dict[str, Any]) -> list[str]:
    """Reconcile the pinned summary fields with the source artifacts they cite."""
    by_role = {source.get("role"): source for source in record.get("sources", [])
               if type(source) is dict}
    try:
        metadata = json.loads(_source_path(root, by_role["metadata_inventory"]["path"]).read_text("utf-8"))
        draft = json.loads(_source_path(root, by_role["draft_destination_types"]["path"]).read_text("utf-8"))
        vat = json.loads(_source_path(root, by_role["vat_enumeration_semantics"]["path"]).read_text("utf-8"))
        rights = json.loads(_source_path(root, by_role["effective_rights"]["path"]).read_text("utf-8"))
        executor = json.loads(_source_path(root, by_role["executor_clone_facts"]["path"]).read_text("utf-8"))
        spike = _source_path(root, by_role["feasibility_spike"]["path"]).read_text("utf-8")
    except (KeyError, TypeError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return ["CT14_SOURCE_CORRELATION_FAILED"]

    scope = record.get("scope")
    configuration = metadata.get("configuration", {})
    rights_revisions = {item.get("revision_id"): item for item in record.get("rights_revisions", [])
                        if type(item) is dict}
    summary = record.get("parsed_source_summary", {})
    spike_revision = rights_revisions.get("CT14_SPIKE_2026-10-12", {})
    rights_revision = rights_revisions.get("CT14_EFFECTIVE_RIGHTS_2026-10-27", {})
    executor_revision = rights_revisions.get("CT14_EXECUTOR_CLONE_FACTS_2026-10-27", {})
    least_privilege = executor.get("least_privilege_run", {})
    effective_summary = least_privilege.get("effective_rights", "")
    match = re.fullmatch(r"(\d+) objects, (\d+) mismatches, (\d+) extra, (\d+) forbidden", effective_summary)
    metadata_summary = summary.get("metadata_inventory", {})
    draft_summary = summary.get("draft_destination_types", {})
    vat_summary = summary.get("vat_enumeration_semantics", {})
    rights_summary = summary.get("effective_rights", {})
    executor_summary = summary.get("executor_clone_facts", {})
    if (
        metadata.get("clone") != scope.get("clone")
        or metadata.get("platform_version") != scope.get("platform_version")
        or metadata.get("document") != scope.get("document_shape")
        or f"{configuration.get('name')} {configuration.get('version')}" != scope.get("configuration")
        or metadata_summary != {"clone": metadata.get("clone"), "platform_version": metadata.get("platform_version"),
                                "configuration": scope.get("configuration"), "document": metadata.get("document")}
        or draft_summary != {"sections": sorted(draft), "header_fields": len(draft.get("header", {})),
                             "goods_fields": len(draft.get("goods", {})),
                             "vat_enum_values": len(draft.get("vat_enum_values", []))}
        or vat.get("clone") != scope.get("clone")
        or vat_summary != {"clone": vat.get("clone"), "enumeration": vat.get("enumeration"),
                           "value_count": len(vat.get("values", []))}
        or rights.get("committed_objects") != rights_revision.get("reported_committed_objects")
        or len(rights.get("effective", {})) != rights_revision.get("reported_effective_mapping_entries")
        or len(rights.get("mismatch", {"invalid": True})) != rights_revision.get("reported_mismatch_count")
        or len(rights.get("extra_effective_beyond_committed", {"invalid": True}))
        != rights_revision.get("reported_extra_effective_count")
        or rights_summary != {"committed_objects": rights.get("committed_objects"),
                              "effective_mapping_entries": len(rights.get("effective", {})),
                              "mismatch_count": len(rights.get("mismatch", {})),
                              "extra_effective_count": len(rights.get("extra_effective_beyond_committed", {}))}
        or spike_revision.get("reported_right_entries") != 53
        or "53 entries" not in spike
        or "52 empty adoptions plus the document" not in spike
        or executor.get("clone") != scope.get("clone")
        or least_privilege.get("role_read_added") != executor_revision.get("added_read_rights")
        or executor_summary != {"clone": executor.get("clone"), "added_read_rights": least_privilege.get("role_read_added"),
                                "effective_summary": effective_summary}
        or match is None
        or int(match.group(1)) != executor_revision.get("reported_effective_object_count")
        or int(match.group(2)) != executor_revision.get("reported_mismatch_count")
        or int(match.group(3)) != executor_revision.get("reported_extra_count")
        or int(match.group(4)) != executor_revision.get("reported_forbidden_count")
    ):
        return ["CT14_SOURCE_CORRELATION_FAILED"]
    if _verify_spike_items(spike, record.get("capability_observations")):
        return ["CT14_SOURCE_CORRELATION_FAILED"]
    return []


def _verify_spike_items(spike: str, observations: object) -> list[str]:
    if type(observations) is not list:
        return ["CT14_CAPABILITY_RECORD_INVALID"]
    source_results: dict[str, str] = {}
    for line in spike.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10a", "10b", "11", "12", "13", "14"}:
            source_results[cells[0]] = cells[2]
    for item in observations:
        if type(item) is not dict:
            return ["CT14_CAPABILITY_RECORD_INVALID"]
        item_id = item.get("item_id")
        if type(item_id) is not str:
            return ["CT14_CAPABILITY_RECORD_INVALID"]
        source_id = item_id.split("-", 1)[0] if item_id in {"12-standard", "12-custom"} else item_id
        result = source_results.get(source_id)
        if result is None:
            return ["CT14_CAPABILITY_SOURCE_MISSING"]
        if item_id == "12-standard" and not result.startswith("UNSUPPORTED"):
            return ["CT14_CAPABILITY_SOURCE_MISMATCH"]
        if item_id == "12-custom" and "SUPPORTED on the clone with a custom extension role" not in result:
            return ["CT14_CAPABILITY_SOURCE_MISMATCH"]
        expected = item.get("status")
        if item_id not in {"12-standard", "12-custom"}:
            source_state = "OBSERVED_WEAK" if result.startswith("OBSERVED, weak") else result.split(",", 1)[0].split(" ", 1)[0]
            if source_state != expected:
                return ["CT14_CAPABILITY_SOURCE_MISMATCH"]
    return []


def evaluate_e47(repo_root: str | Path, requested_scope: object = None) -> dict[str, object]:
    """Evaluate the checked-in CT14 evidence record for governed CREATE_DRAFT.

    A BLOCKED result means authorization/qualification evidence is absent; it
    does not claim that COM draft creation is technically impossible.
    """
    root = Path(repo_root).resolve()
    record_path = root / RECORD_RELATIVE_PATH
    try:
        record_bytes = record_path.read_bytes()
        if _canonical_source_sha256(record_bytes) != EXPECTED_RECORD_SHA256:
            return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                    "reason_codes": ["CT14_RECORD_STALE"]}
        record = json.loads(record_bytes.decode("utf-8"))
    except FileNotFoundError:
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": ["CT14_RECORD_MISSING"]}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": ["CT14_RECORD_INVALID"]}
    if type(record) is not dict or record.get("schema") != "ERP_MCP_CT14_QUALIFICATION" \
            or record.get("schema_version") != 1 \
            or record.get("record_class") != "HISTORICAL_DISPOSABLE_CLONE_EVIDENCE":
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": ["CT14_RECORD_SCHEMA_INVALID"]}
    scope = record.get("scope")
    if (type(scope) is not dict or scope.get("clone") != "818HA_p2diff"
            or scope.get("evidence_is_current_runtime") is not False
            or scope.get("evidence_authorizes_operation") is not False):
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": ["CT14_RECORD_SCOPE_INVALID"]}
    if requested_scope is not None:
        scope_keys = ("clone", "database_type", "platform_version", "configuration", "document_shape", "channel")
        if (type(requested_scope) is not dict
                or any(type(requested_scope.get(key)) is not str or not requested_scope.get(key) for key in scope_keys)):
            return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                    "reason_codes": ["CT14_REQUESTED_SCOPE_INVALID"]}
        recorded_scope = {key: scope.get(key) for key in scope_keys if key != "channel"}
        recorded_scope["channel"] = scope.get("measured_channel")
        if any(requested_scope.get(key) != recorded_scope.get(key) for key in scope_keys):
            return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                    "reason_codes": ["CT14_REQUESTED_SCOPE_MISMATCH"]}

    reasons = _verify_sources(root, record.get("sources"))
    reasons.extend(_validate_observations(record))
    reasons.extend(_verify_semantic_bindings(root, record))
    if reasons:
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": sorted(set(reasons))}

    operations = record.get("operations")
    operation = operations.get("CREATE_DRAFT") if type(operations) is dict else None
    if type(operation) is not dict:
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": ["CT14_CREATE_DRAFT_PREDICATES_MISSING"]}
    required = ("capability_observed", "capability_qualified", "scope_qualified", "operation_authorized")
    if (any(key not in operation for key in required)
            or type(operation.get("capability_observed")) is not str
            or operation.get("capability_observed") not in VALID_STATES
            or any(type(operation.get(key)) is not bool for key in required[1:])):
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": ["CT14_CREATE_DRAFT_PREDICATES_INVALID"]}

    unmet = [f"CT14_{key.upper()}_NOT_SATISFIED" for key in required[1:] if operation.get(key) is not True]
    if operation.get("operation_authorized") is True:
        unmet.append("CT14_OPERATION_AUTHORITY_EVIDENCE_NOT_IN_SCOPE")
    decision = "BLOCKED" if unmet else "ELIGIBLE"
    if operation.get("decision") != decision or operation.get("reason_codes") != unmet:
        return {"operation": "CREATE_DRAFT", "decision": "BLOCKED", "evidence_status": "NOT_VERIFIED",
                "reason_codes": ["CT14_DECISION_CONTRADICTORY"]}
    return {"operation": "CREATE_DRAFT", "decision": decision, "evidence_status": "VERIFIED_BOUNDED_RECORD",
            "technical_feasibility": operation["capability_observed"], "reason_codes": unmet}


__all__ = ["evaluate_e47"]
