"""Differential assertions for the narrowly scoped executable R2-TC-001 scenario."""
from __future__ import annotations

import copy
import json
from typing import Any


class DifferentialMismatch(AssertionError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_tool(tool: dict) -> dict:
    return {
        "name": tool["name"],
        "inputSchema": tool.get("inputSchema"),
        "annotations": tool.get("annotations"),
    }


def normalize_result(result: dict) -> dict:
    """Strip only MCP correlation IDs; preserve business values and error decisions."""
    normalized = copy.deepcopy(result)
    structured = normalized.get("structuredContent")
    if isinstance(structured, dict) and isinstance(structured.get("error"), dict):
        structured["error"].pop("correlation_id", None)
    content = normalized.get("content", [])
    for block in content:
        if block.get("type") == "text":
            try:
                payload = json.loads(block.get("text", ""))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                payload["error"].pop("correlation_id", None)
                block["text"] = canonical(payload)
    return normalized


def normalize_audit(events: list[dict]) -> list[dict]:
    # Event order, decisions, detail codes and authorization outcomes remain significant.
    return [event for event in events if event.get("kind") != "process"]


def assert_r1_equivalent(baseline: dict, candidate: dict) -> None:
    differences = []
    base_tools = {tool["name"]: normalize_tool(tool) for tool in baseline["tools"]}
    cand_tools = {tool["name"]: normalize_tool(tool) for tool in candidate["tools"]}
    missing = sorted(set(base_tools) - set(cand_tools))
    if missing:
        differences.append(f"candidate removed baseline R1 tools: {missing}")
    changed = sorted(
        name for name, tool in base_tools.items()
        if name in cand_tools and canonical(tool) != canonical(cand_tools[name])
    )
    if changed:
        differences.append(f"candidate changed baseline R1 schema/annotations: {changed}")
    for key in ("calls", "audit", "side_effects"):
        if canonical(baseline[key]) != canonical(candidate[key]):
            differences.append(f"candidate changed R1 {key}")
    if differences:
        raise DifferentialMismatch("; ".join(differences))


def negative_controls(baseline: dict, candidate: dict) -> dict[str, bool]:
    outcomes = {}
    for label, mutate in (
        ("schema", lambda altered: altered["tools"][0]["inputSchema"].update({"type": "string"})),
        ("output", lambda altered: altered["calls"][0]["response"]["result"]["structuredContent"].update({"business_value": "altered"})),
        ("audit", lambda altered: altered["audit"].append({"kind": "audit", "outcome": "denied"})),
    ):
        altered = copy.deepcopy(candidate)
        mutate(altered)
        try:
            assert_r1_equivalent(baseline, altered)
        except DifferentialMismatch:
            outcomes[label] = True
        else:
            outcomes[label] = False
    if not all(outcomes.values()):
        raise DifferentialMismatch(f"negative oracle controls were not detected: {outcomes}")
    return outcomes
