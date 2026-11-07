"""Exact public-contract differential oracle and negative controls for R2-TC-001."""
from __future__ import annotations

import copy
import json
from typing import Any


class DifferentialMismatch(AssertionError):
    pass


READ_ONLY_ANNOTATIONS = {
    "destructiveHint": False,
    "openWorldHint": True,
    "readOnlyHint": True,
}
COMPATIBILITY_CASES = {
    "source-health-ok",
    "source-health-error",
    "onec-read-valid",
}
ALLOWED_ADAPTER_OPERATIONS = {"health_read", "read"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_result(result: dict) -> dict:
    """Remove only nondeterministic MCP correlation IDs from compared results."""
    normalized = copy.deepcopy(result)
    roots = [normalized]
    if isinstance(normalized.get("result"), dict):
        roots.append(normalized["result"])
    for root in roots:
        structured = root.get("structuredContent")
        if isinstance(structured, dict) and isinstance(structured.get("error"), dict):
            structured["error"].pop("correlation_id", None)
        for block in root.get("content", []):
            if block.get("type") != "text":
                continue
            try:
                payload = json.loads(block.get("text", ""))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                payload["error"].pop("correlation_id", None)
                block["text"] = canonical(payload)
    return normalized


def input_schema_compatible(baseline: dict | None, candidate: dict | None) -> bool:
    if baseline is None or candidate is None:
        return baseline == candidate
    base = copy.deepcopy(baseline)
    cand = copy.deepcopy(candidate)
    if "additionalProperties" not in base and cand.get("additionalProperties") is False:
        cand.pop("additionalProperties")
    return canonical(base) == canonical(cand)


def assert_candidate_schema_strictness(snapshot: dict) -> None:
    published_tools = snapshot.get("all_candidate_tools", snapshot["tools"])
    non_strict = [
        tool.get("name", "<missing-name>")
        for tool in published_tools
        if not isinstance(tool.get("inputSchema"), dict)
        or tool["inputSchema"].get("additionalProperties") is not False
    ]
    if non_strict:
        raise DifferentialMismatch(
            f"candidate published tools without root additionalProperties=false: {sorted(non_strict)}"
        )


def _tool_differences(baseline: dict, candidate: dict) -> list[str]:
    differences = []
    try:
        assert_candidate_schema_strictness(candidate)
    except DifferentialMismatch as exc:
        differences.append(str(exc))
    base_tools = {tool["name"]: tool for tool in baseline["tools"]}
    cand_tools = {tool["name"]: tool for tool in candidate["tools"]}
    missing = sorted(set(base_tools) - set(cand_tools))
    if missing:
        differences.append(f"removed R1 tools: {missing}")
    for name in sorted(set(base_tools) & set(cand_tools)):
        base, cand = base_tools[name], cand_tools[name]
        if not input_schema_compatible(base.get("inputSchema"), cand.get("inputSchema")):
            differences.append(f"incompatible input schema: {name}")
        base_annotations = base.get("annotations")
        candidate_annotations = cand.get("annotations")
        if candidate_annotations != READ_ONLY_ANNOTATIONS:
            differences.append(f"incorrect candidate read-only annotations: {name}")
        if base_annotations not in (None, READ_ONLY_ANNOTATIONS):
            differences.append(f"unexpected baseline annotation contract: {name}")
    return differences


def _events_equal_for_compatibility(baseline: dict, candidate: dict, category: str) -> bool:
    def comparable(snapshot):
        return [
            event for event in snapshot[category]
            if event.get("source_id") != "synthetic-typo"
        ]
    return canonical(comparable(baseline)) == canonical(comparable(candidate))


def assert_access_receipt_invariants(snapshot: dict) -> None:
    """Receipts authorize dispatch before adapter effects; completion follows the read."""
    events = snapshot["event_log"]
    receipts = snapshot["access_receipts"]
    adapters = snapshot["adapter_side_effects"]
    completions = snapshot["completion_audit"]
    expected_pairs = {
        (event.get("tool"), event.get("source_id")) for event in adapters
        if event.get("source_id") != "synthetic-typo"
    }
    receipt_pairs = [(event.get("tool"), event.get("source_id")) for event in receipts]
    if len(receipt_pairs) != len(set(receipt_pairs)) or set(receipt_pairs) != expected_pairs:
        raise DifferentialMismatch(
            f"ACCESS_AUTHORIZED receipts do not match adapter dispatches: "
            f"receipts={receipt_pairs}, dispatches={sorted(expected_pairs)}"
        )
    for adapter in adapters:
        if adapter.get("source_id") == "synthetic-typo":
            continue
        pair = (adapter.get("tool"), adapter.get("source_id"))
        receipt = next(
            event for event in receipts
            if (event.get("tool"), event.get("source_id")) == pair
        )
        if events.index(receipt) >= events.index(adapter):
            raise DifferentialMismatch(f"ACCESS_AUTHORIZED receipt is after adapter dispatch: {pair}")
        if (receipt.get("outcome") != "success"
                or receipt.get("detail_code") != "ACCESS_AUTHORIZED"
                or receipt.get("policy_version") != "predispatch-audit-v1"
                or receipt.get("record_tool_outcome") is not False):
            raise DifferentialMismatch(f"ACCESS_AUTHORIZED receipt contract changed: {pair}")
        matching_completion = [
            event for event in completions
            if (event.get("tool"), event.get("source_id")) == pair
        ]
        if (len(matching_completion) != 1
                or events.index(matching_completion[0]) <= events.index(adapter)):
            raise DifferentialMismatch(f"completion audit missing or misplaced after dispatch: {pair}")


def assert_access_receipt_delta(baseline: dict, candidate: dict) -> None:
    baseline_receipts = [event for event in baseline["access_receipts"]
                         if event.get("source_id") != "synthetic-typo"]
    candidate_receipts = [event for event in candidate["access_receipts"]
                          if event.get("source_id") != "synthetic-typo"]
    base_by_pair = {
        (event.get("tool"), event.get("source_id")): event
        for event in baseline_receipts
    }
    candidate_by_pair = {
        (event.get("tool"), event.get("source_id")): event
        for event in candidate_receipts
    }
    if len(base_by_pair) != len(baseline_receipts):
        raise DifferentialMismatch("baseline contains duplicate ACCESS_AUTHORIZED receipts")
    if len(candidate_by_pair) != len(candidate_receipts):
        raise DifferentialMismatch("candidate contains duplicate ACCESS_AUTHORIZED receipts")
    if not set(base_by_pair) <= set(candidate_by_pair):
        raise DifferentialMismatch("candidate removed an existing ACCESS_AUTHORIZED receipt")
    for pair, receipt in candidate_by_pair.items():
        if pair in base_by_pair:
            if canonical(base_by_pair[pair]) != canonical(receipt):
                raise DifferentialMismatch(f"candidate changed existing access receipt: {pair}")
            continue
        if (receipt.get("outcome") != "success"
                or receipt.get("detail_code") != "ACCESS_AUTHORIZED"
                or receipt.get("policy_version") != "predispatch-audit-v1"
                or receipt.get("record_tool_outcome") is not False):
            raise DifferentialMismatch(f"candidate added a non-contract access receipt: {pair}")


def assert_candidate_input_probes(snapshot: dict) -> None:
    probes = {probe["case"]: probe for probe in snapshot["input_probes"]}
    typo = probes["onec-read-misspelled-filter"]
    result = typo["response"].get("result", {})
    if not result.get("isError"):
        raise DifferentialMismatch("candidate accepted unknown argument `filter`")
    if any(event.get("source_id") == "synthetic-typo"
           for event in snapshot["adapter_side_effects"]):
        raise DifferentialMismatch("misspelled onec_read filter reached the adapter")
    if any(event.get("source_id") == "synthetic-typo"
           for event in snapshot["acl_rate_decisions"] + snapshot["access_receipts"]
           + snapshot["completion_audit"]):
        raise DifferentialMismatch("misspelled onec_read filter reached handler authorization/audit")
    valid = probes["onec-read-valid"]
    if valid["response"].get("result", {}).get("isError"):
        raise DifferentialMismatch("candidate rejected valid declared onec_read input")
    dispatched = [event for event in snapshot["adapter_side_effects"]
                  if event.get("source_id") == "synthetic-read"]
    if not dispatched:
        raise DifferentialMismatch("valid declared onec_read input did not reach adapter")
    if (dispatched[0].get("arguments", {}).get("filter_expr") != "id eq 'synthetic-1'"
            or "filter" in dispatched[0].get("arguments", {})):
        raise DifferentialMismatch("valid declared onec_read filter did not reach adapter intact")


def assert_no_unauthorized_mutations(snapshot: dict) -> None:
    mutations = [
        event for event in snapshot["adapter_side_effects"]
        if event.get("operation") not in ALLOWED_ADAPTER_OPERATIONS
    ]
    if mutations:
        raise DifferentialMismatch(f"unauthorized adapter mutation observed: {mutations}")


def assert_r1_equivalent(baseline: dict, candidate: dict) -> None:
    differences = _tool_differences(baseline, candidate)
    if canonical(baseline["effective_settings"]) != canonical(candidate["effective_settings"]):
        differences.append("effective settings differ")
    base_calls = [call for call in baseline["calls"] if call["case"] in COMPATIBILITY_CASES]
    cand_calls = [call for call in candidate["calls"] if call["case"] in COMPATIBILITY_CASES]
    if canonical(base_calls) != canonical(cand_calls):
        differences.append("R1 MCP success/error outputs differ")
    for category in ("acl_rate_decisions", "completion_audit", "adapter_side_effects", "other_events"):
        if not _events_equal_for_compatibility(baseline, candidate, category):
            differences.append(f"R1 {category} differ")
    if baseline["other_events"] or candidate["other_events"]:
        differences.append("unclassified runtime events were observed")
    # ACCESS_AUTHORIZED is the sole approved additive audit receipt; validate it rather than
    # collapsing it into completion audits or silently discarding its ordering information.
    try:
        assert_candidate_schema_strictness(candidate)
        assert_access_receipt_invariants(candidate)
        assert_access_receipt_delta(baseline, candidate)
    except DifferentialMismatch as exc:
        differences.append(str(exc))
    try:
        assert_candidate_input_probes(candidate)
    except DifferentialMismatch as exc:
        differences.append(str(exc))
    try:
        assert_no_unauthorized_mutations(candidate)
        assert_no_unauthorized_mutations(baseline)
    except DifferentialMismatch as exc:
        differences.append(str(exc))
    if differences:
        raise DifferentialMismatch("; ".join(differences))


def _oracle_pair() -> tuple[dict, dict]:
    tools = [{
        "name": "source_health",
        "inputSchema": {"type": "object", "properties": {"source_id": {"type": "string"}},
                        "required": ["source_id"]},
        "annotations": None,
    }, {
        "name": "onec_read",
        "inputSchema": {
            "type": "object",
            "properties": {"entity_set": {"type": "string"},
                           "nested": {"type": "object", "properties": {"code": {"type": "string"}}}},
            "required": ["entity_set"],
        },
        "annotations": None,
    }]
    baseline = {
        "tools": copy.deepcopy(tools),
        "calls": [
            {"case": "source-health-ok", "response": {"result": {"value": "ok"}}},
            {"case": "source-health-error", "response": {"result": {"isError": True, "text": "SOURCE_TIMEOUT"}}},
        ],
        "effective_settings": {"environment": "test", "rate_limit_per_minute": 120},
        "acl_rate_decisions": [{"kind": "authorization", "source_id": "fixture", "decision": "allow"}],
        "completion_audit": [
            {"kind": "audit", "tool": "source_health", "source_id": "fixture", "outcome": "success"},
            {"kind": "audit", "tool": "onec_read", "source_id": "synthetic-read", "outcome": "success"},
        ],
        "access_receipts": [],
        "adapter_side_effects": [
            {"kind": "adapter", "tool": "source_health", "source_id": "fixture", "operation": "health_read"},
            {"kind": "adapter", "tool": "onec_read", "source_id": "synthetic-read", "operation": "read",
             "arguments": {"filter_expr": "id eq 'synthetic-1'", "top": 1}},
        ],
        "other_events": [],
        "event_log": [
            {"kind": "adapter", "tool": "source_health", "source_id": "fixture", "operation": "health_read"},
            {"kind": "audit", "tool": "source_health", "source_id": "fixture", "outcome": "success"},
            {"kind": "adapter", "tool": "onec_read", "source_id": "synthetic-read", "operation": "read",
             "arguments": {"filter_expr": "id eq 'synthetic-1'", "top": 1}},
            {"kind": "audit", "tool": "onec_read", "source_id": "synthetic-read", "outcome": "success"},
        ],
        "input_probes": [
            {"case": "onec-read-misspelled-filter", "response": {"result": {"isError": True}}},
            {"case": "onec-read-valid", "response": {"result": {"isError": False}}},
        ],
    }
    # Keep event categories as references into one ordered event stream so mutations in
    # negative controls alter the recorded event itself, just as they do in live evidence.
    baseline["event_log"] = [
        baseline["adapter_side_effects"][0],
        baseline["completion_audit"][0],
        baseline["adapter_side_effects"][1],
        baseline["completion_audit"][1],
    ]
    candidate = copy.deepcopy(baseline)
    for tool in candidate["tools"]:
        tool["annotations"] = copy.deepcopy(READ_ONLY_ANNOTATIONS)
        tool["inputSchema"]["additionalProperties"] = False
    receipts = [
        {"kind": "audit", "tool": pair[0], "source_id": pair[1],
         "outcome": "success", "detail_code": "ACCESS_AUTHORIZED",
         "policy_version": "predispatch-audit-v1", "record_tool_outcome": False}
        for pair in (("source_health", "fixture"), ("onec_read", "synthetic-read"))
    ]
    candidate["access_receipts"] = receipts
    candidate["event_log"] = [
        receipts[0], candidate["event_log"][0], candidate["event_log"][1],
        receipts[1], candidate["event_log"][2], candidate["event_log"][3],
    ]
    return baseline, candidate


def negative_controls() -> dict[str, bool]:
    """Prove each declared regression class is rejected by the current oracle."""
    baseline, accepted = _oracle_pair()
    assert_r1_equivalent(baseline, accepted)
    checks: dict[str, bool] = {}

    def rejected(label: str, mutation, *, invariant=False) -> None:
        altered = copy.deepcopy(accepted)
        mutation(altered)
        try:
            if invariant:
                assert_candidate_schema_strictness(altered)
                assert_candidate_input_probes(altered)
                assert_access_receipt_invariants(altered)
                assert_no_unauthorized_mutations(altered)
            else:
                assert_r1_equivalent(baseline, altered)
        except (DifferentialMismatch, KeyError, IndexError, TypeError):
            checks[label] = True
        else:
            checks[label] = False

    rejected("removed_tool", lambda x: x["tools"].pop(0))
    rejected("removed_property", lambda x: x["tools"][0]["inputSchema"]["properties"].pop("source_id"))
    rejected("incompatible_field_type", lambda x: x["tools"][0]["inputSchema"]["properties"]["source_id"].update({"type": "integer"}))
    rejected("changed_required", lambda x: x["tools"][0]["inputSchema"].update({"required": []}))
    rejected("nested_schema_mutation", lambda x: x["tools"][1]["inputSchema"]["properties"]["nested"]["properties"]["code"].update({"type": "integer"}))
    rejected("additional_properties_true", lambda x: x["tools"][0]["inputSchema"].update({"additionalProperties": True}))
    rejected("additional_properties_omitted", lambda x: x["tools"][0]["inputSchema"].pop("additionalProperties"), invariant=True)
    rejected("annotations_changed", lambda x: x["tools"][0].update({"annotations": {"readOnlyHint": False}}))
    rejected("success_mutation", lambda x: x["calls"][0]["response"]["result"].update({"value": "changed"}))
    rejected("completion_audit_outcome", lambda x: x["completion_audit"][0].update({"outcome": "denied"}))
    rejected("missing_receipt", lambda x: (x["access_receipts"].clear(), x["event_log"].pop(0)), invariant=True)
    rejected("misplaced_receipt", lambda x: (x["event_log"].remove(x["access_receipts"][0]), x["event_log"].append(x["access_receipts"][0])), invariant=True)
    rejected("unknown_argument_accepted", lambda x: x["input_probes"][0]["response"]["result"].update({"isError": False}), invariant=True)
    rejected("misspelled_filter_reached_adapter", lambda x: x["adapter_side_effects"].append({"kind": "adapter", "tool": "onec_read", "source_id": "synthetic-typo", "operation": "read", "arguments": {"filter": "id eq 'synthetic-1'"}}), invariant=True)
    rejected("valid_input_rejected", lambda x: x["input_probes"][1]["response"]["result"].update({"isError": True}), invariant=True)
    rejected("unauthorized_adapter_mutation", lambda x: x["adapter_side_effects"][0].update({"operation": "write"}), invariant=True)

    rejected(
        "error_mutation",
        lambda x: x["calls"][1]["response"]["result"].update({"text": "SOURCE_CHANGED"}),
    )
    if not all(checks.values()):
        failed = sorted(label for label, detected in checks.items() if not detected)
        raise DifferentialMismatch(f"negative controls failed to detect regressions: {failed}")
    return checks
