"""Per-story evaluation: turns collected OBSERVATIONS into exactly one disposition per catalogue story.

The verdict is always produced by scripts.real1c.disposition.decide; nothing here forces a PASS.  A story that the
lane cannot exercise on the real source is reported INCONCLUSIVE with the reason, never silently PASS.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from scripts.real1c.catalog import Story
from scripts.real1c.disposition import Observed, decide
from scripts.real1c.probes import GATED_TOOLS, TOOL_ABBR
from scripts.real1c.sanitize import redact_text

GATED_SET = set(GATED_TOOLS)
SEMANTIC_OWNER = ("Owner/accountant: capture at least ten genuine native 1C UI report exports (runbook "
                  "docs/NATIVE_REPORT_CAPTURE_RUNBOOK.md) so the real-source profile can be validated; until "
                  "then every semantic story stays SEMANTIC_PROFILE_UNVALIDATED.")
EVIDENCE_OWNER = ("Owner/accountant: supply the external evidence for this case (hashed PDF, bank statement or "
                  "declaration) through the evidence plane; the lane never invents it.")
CAPABILITY_OWNER = "Operator: scope-rebaseline decision for the missing capability (see the REQ-GAP references)."
FINDING_OWNER = "Operator: triage this finding (product defect, catalogue correction or accepted limitation)."

# Requirement gaps (REQ-GAP-NN) most closely tied to a story; informational cross-references only.
REQ_GAP_REFS: dict[str, list[str]] = {
    "ST-001": ["REQ-GAP-01"], "ST-002": ["REQ-GAP-02"], "ST-007": ["REQ-GAP-03"], "ST-004": ["REQ-GAP-04", "REQ-GAP-06"],
    "ST-005": ["REQ-GAP-04"], "ST-006": ["REQ-GAP-07"], "ST-009": ["REQ-GAP-17"], "ST-010": ["REQ-GAP-05"],
    "ST-013": ["REQ-GAP-17"], "ST-014": ["REQ-GAP-08"], "ST-017": ["REQ-GAP-08"], "ST-019": ["REQ-GAP-18"],
    "ST-022": ["REQ-GAP-25"], "ST-024": ["REQ-GAP-09"], "ST-025": ["REQ-GAP-09"], "ST-026": ["REQ-GAP-09"],
    "ST-035": ["REQ-GAP-11"], "ST-038": ["REQ-GAP-10"], "ST-041": ["REQ-GAP-10"], "ST-042": ["REQ-GAP-07"],
    "ST-046": ["REQ-GAP-15"], "ST-052": ["REQ-GAP-14"], "ST-057": ["REQ-GAP-15"], "ST-063": ["REQ-GAP-24"],
    "ST-071": ["REQ-GAP-12"], "ST-073": ["REQ-GAP-12"], "ST-074": ["REQ-GAP-12"], "ST-077": ["REQ-GAP-12"],
    "ST-078": ["REQ-GAP-13"], "ST-080": ["REQ-GAP-13"], "ST-087": ["REQ-GAP-16"], "AX-004": ["REQ-GAP-18"],
    "AX-008": ["REQ-GAP-21"], "AX-029": ["REQ-GAP-20"], "AX-030": ["REQ-GAP-23"], "AX-039": ["REQ-GAP-19"],
    "ST-008": ["REQ-GAP-27"], "ST-033": ["REQ-GAP-27"], "ST-034": ["REQ-GAP-27"], "ST-021": ["REQ-GAP-15"],
}
# Raw-L2 / native-check cases that give observed context next to a story (never rewrite its acceptance meaning).
RELATED: dict[str, list[str]] = {
    "ST-001": ["NR-01"], "ST-004": ["NR-05"], "ST-005": ["NR-03", "NR-04"], "ST-009": ["RL2-07"], "ST-010": ["RL2-05", "RL2-10"],
    "ST-013": ["RL2-07"], "ST-016": ["RL2-02"], "ST-061": ["RL2-02"], "ST-063": ["NR-08", "INV-01"], "ST-064": ["NR-08"],
    "ST-018": ["NR-07"], "AX-021": ["NR-07"], "AX-024": ["RL2-03"], "AX-040": ["RL2-05"], "ST-029": ["RL2-05"],
    "ST-042": ["RL2-03"], "ST-045": ["RL2-03"], "AX-013": ["RL2-03", "RL2-04"], "AX-026": ["RL2-03", "RL2-04"],
    "ST-052": ["RL2-09"], "ST-006": ["RL2-03"], "AX-011": ["NR-05", "NR-06"], "AX-032": ["NR-05"], "ST-087": ["RL2-09"],
}

UG_NEEDLE: dict[str, str] = {
    "ST-002": r"proposal|clean.?up|month.?close|rule.?pack", "ST-007": r"fiscal|legal.?rule|rule.?pack",
    "ST-021": r"reconciliation.?(act|status)|акт.?сверк", "ST-024": r"statement|profit|loss|p&l|template",
    "ST-025": r"balance.?sheet|statement|template", "ST-026": r"cash.?flow|statement|template",
    "ST-027": r"comparative|statement|template", "ST-028": r"statement|template", "ST-029": r"statement|template",
    "ST-030": r"statement.?(diff|compare)|native.?report", "ST-031": r"vat.?(pre.?filing|declaration|return)|pre.?filing",
    "ST-035": r"portfolio|scan", "ST-036": r"risk", "ST-046": r"customs", "ST-053": r"payroll|withholding|rule.?pack",
    "ST-056": r"act.?generat|generate.?act", "ST-062": r"act.?(workflow|tracking)", "ST-071": r"onboard|wizard",
    "ST-073": r"dry.?run", "ST-074": r"bulk|csv", "ST-082": r"handoff|secret.?intake",
    "AX-008": r"intercompany|inter.?company|consolidat|related.?part", "AX-022": r"cash.?(limit|cap)|legal.?cap",
    "AX-029": r"change.?(history|log)|period.?lock", "AX-031": r"consolidat",
}

Handler = Callable[[Story, dict[str, Any]], "tuple[Observed, list[dict], list[str], list[str], str]"]


def _o(probe: str, outcome: str, detail: str) -> dict[str, str]:
    return {"probe": probe, "outcome": outcome, "detail": detail}


def _gate_default(story: Story, ev: dict[str, Any]):
    gated = [t for t in story.tools if t in GATED_SET]
    if not gated:
        obs = [_o("exercisable on the real source", "not exercisable",
                  "the story names no semantic data tool the lane can call; no executable observation exists")]
        return Observed(), obs, [], ["NONE"], "no gated tool to exercise"
    rows = [ev["gate"][t] for t in gated]
    untyped = [r["tool"] for r in rows if r.get("transport_error") or (r["is_error"] and r["detail_code"] is None)]
    if untyped:
        obs = [_o("gated call", "NO TYPED ANSWER", f"transport failure or error without an audit row for: {', '.join(untyped)}")]
        return (Observed(error="gated call produced no typed gateway answer"), obs, [r["tool"] for r in rows],
                ["GATEWAY_OBSERVATION"], "semantic profile gate")
    refused = all(r["refused"] for r in rows)
    data = any(r["data_returned"] for r in rows)
    observations = [_o(f"{r['tool']}(real company, 2026-08)", "REFUSED" if r["refused"] else ("DATA" if r["data_returned"] else "OTHER"),
                       f"typed denial {r['detail_code']} (audit outcome {r['outcome']}); rows returned: {r['data_returned']}")
                    for r in rows]
    return (Observed(profile_gate_refusal=True if refused else (False if not data else None), data_returned=data),
            observations, [r["tool"] for r in rows], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "semantic profile gate")


def _ug_default(story: Story, ev: dict[str, Any]):
    needle = UG_NEEDLE.get(story.id)
    surface = ev["disc"]["surface"]
    if needle is None:
        return Observed(), [_o("capability search", "no needle", "no search pattern defined for this story")], [], ["REPO_STATIC"], "no needle"
    hit = re.search(needle, surface)
    obs = [_o("product surface search", "ABSENT" if not hit else "PRESENT",
              f"pattern /{needle}/ over {ev['disc']['count']} public MCP tools, admin API routes and CLI commands: "
              f"{'no match' if not hit else 'matched ' + repr(hit.group(0))}")]
    return Observed(capability_absent_confirmed=not hit), obs, [], ["REPO_STATIC"], "capability search"


def _ev_default(story: Story, ev: dict[str, Any]):
    e = ev["evtool"]
    if e.get("transport_error"):
        return (Observed(error="evidence tool call failed at transport level"),
                [_o("external_evidence_manifest", "NO TYPED ANSWER", "transport failure")], ["external_evidence_manifest"],
                ["GATEWAY_OBSERVATION"], "evidence plane")
    obs = [_o("external_evidence_manifest(unknown evidence id, real company)", e["status"] or "NO_STATUS",
              f"typed refusal; audit {e['audit']}; rows returned: {e['data_returned']}; "
              f"business_acceptance={e['business_acceptance']}, native_approval_inferred={e['native_approval_inferred']}")]
    return (Observed(evidence_required_observed=e["evidence_required"], data_returned=e["data_returned"]), obs,
            ["external_evidence_manifest"], ["GATEWAY_OBSERVATION"], "evidence plane")


WRITE_ABUSE = {"action_post", "batch_endpoint", "absolute_url", "path_traversal"}


def _wd_default(story: Story, ev: dict[str, Any]):
    w, zw = ev["write"], ev["zero_write"]
    abuse = [c for c in w["cases"] if c["case"] in WRITE_ABUSE]
    typed = len(abuse) == len(WRITE_ABUSE) and all(c["is_error"] and not c.get("transport_error") and c["detail"] for c in abuse)
    get_seen = zw["methods"].get("GET", 0) > 0
    refused = (not w["tool_names_mutating"] and not w["upstream_write_seen"] and typed and not zw["upstream_write_seen"] and get_seen)
    obs = [_o("public tool names", "no mutating tool", f"{ev['disc']['count']} tools, none matches a write verb"),
           _o("write-shaped onec_read inputs", "REFUSED (typed)" if typed else "NOT a typed refusal",
              "; ".join(f"{c['case']}={c['detail']}{' (transport failure)' if c.get('transport_error') else ''}" for c in abuse)),
           _o("upstream methods seen by the loopback proxy", "GET/HEAD only" if not w["upstream_write_seen"] else "WRITE SEEN",
              f"methods={w['upstream_methods']} refused_at_proxy={w['refused_methods']}"),
           _o("database fingerprint", "unchanged" if zw["fingerprint_equal"] else "CHANGED",
              f"pre={zw['pre'][:12]}… post={zw['post'][:12]}…")]
    return (Observed(write_refused=refused, write_effect_detected=not zw["fingerprint_equal"]), obs,
            ["onec_read"], ["GATEWAY_OBSERVATION", "NATIVE_COM_QUERY"], "write surface")


# ----------------------------------------------------------------------------------------------- custom handlers
def _h_st072(story: Story, ev: dict[str, Any]):
    r = ev["acl"].get("revoke_mid_session") or {}
    ok = (r.get("revoke_http") == 200 and r.get("before_detail") == "SEMANTIC_PROFILE_UNVALIDATED"
          and r.get("after_detail") == "AccessDenied" and r.get("regrant_http") == 201)
    obs = [_o("same MCP session before revoke", "ACL passed" if r.get("before_detail") == "SEMANTIC_PROFILE_UNVALIDATED" else "unexpected",
              f"detail {r.get('before_detail')} (expected: denied only by the profile gate)"),
           _o("grant revoked through /admin/v1", f"HTTP {r.get('revoke_http')}", "revoke by access admin"),
           _o("same MCP session after revoke", str(r.get("after_detail")), "next call denied without reconnecting"),
           _o("restore", f"HTTP {r.get('regrant_http')}", "grant re-created for the following tests")]
    return Observed(oracle_match=ok), obs, ["receivable_balance"], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "OACL"


def _h_st075(story: Story, ev: dict[str, Any]):
    p = ev["portfolio"]
    paging = bool(p["paging_parameters_supported"])
    ok = (p["visible_to_one"] + p["visible_to_two"] == p["companies_created"] and p["overlap"] == 0
          and p["union_equals_all"] and p["companies_created"] == 150 and paging)
    obs = [_o("150 synthetic companies, two principals", "disjoint" if p["overlap"] == 0 else "OVERLAP",
              f"visible_to_one={p['visible_to_one']} visible_to_two={p['visible_to_two']} overlap={p['overlap']} "
              f"union equals all={p['union_equals_all']} list time={p['list_seconds']}s"),
           _o("paging parameters on companies_list", "supported" if paging else "none",
              "paging arguments exist" if paging else
              "the tool returns the whole visible list in one response; it has no paging arguments (150 rows fit), "
              "so the 'with paging' part of the story is not met")]
    return Observed(oracle_match=ok), obs, ["companies_list"], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "OACL"


def _h_st076(story: Story, ev: dict[str, Any]):
    a, m = ev["audit"], ev["malformed"]
    tamper_denied = bool(a["tamper"]) and all(v == "InsufficientPrivilegeError" for v in a["tamper"].values())
    complete = a["calls_made"] > 0 and a["calls_made"] == a["calls_with_audit_row"]
    ok = tamper_denied and complete and not m["unaudited"]
    obs = [_o("well-formed calls", "audited" if complete else "MISSING", f"{a['calls_with_audit_row']} of {a['calls_made']} calls have an audit row"),
           _o("UPDATE / DELETE / TRUNCATE on audit_events", "denied" if tamper_denied else "ALLOWED",
              f"roles app/admin/control (each attempt rolled back): {sorted(set(a['tamper'].values()))}"),
           _o("malformed calls", "NOT audited" if m["unaudited"] else "audited",
              f"no audit row for: {', '.join(m['unaudited']) or 'none'} (input rejected before the audit write)")]
    return Observed(oracle_match=ok), obs, ["all"], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "OACL"


def _h_st079(story: Story, ev: dict[str, Any]):
    d = ev["drift"]
    before, after, restored = d.get("before") or {}, d.get("after") or {}, d.get("after_restore") or {}
    read = d.get("read_while_drifted") or {}
    changed = bool(before.get("metadata_fingerprint")) and before.get("metadata_fingerprint") != after.get("metadata_fingerprint")
    ok = (changed and after.get("drift_status") == "DRIFTED" and read.get("detail") == "METADATA_DRIFTED"
          and restored.get("drift_status") == "DRIFTED" and d.get("ack_http") == 200)
    obs = [_o("metadata changed upstream (loopback proxy adds one EntitySet)", "fingerprint changed" if changed else "unchanged",
              f"{str(before.get('metadata_fingerprint'))[:12]}… -> {str(after.get('metadata_fingerprint'))[:12]}…, "
              f"drift_status={after.get('drift_status')}"),
           _o("data read while drifted", str(read.get("detail")), "fail-closed typed denial"),
           _o("metadata restored", str(restored.get("drift_status")), "still blocked until an explicit acknowledgement"),
           _o("acknowledgement by exact fingerprint", f"HTTP {d.get('ack_http')}", "unblocks the source")]
    return Observed(oracle_match=ok), obs, ["onec_read", "onec_capabilities"], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "OFIX"


SLOW_INJECTED_SECONDS = 6.0


def _h_st081(story: Story, ev: dict[str, Any]):
    f = ev["outage"]["fan_out"]
    from scripts.real1c.lane import SRC_DOWN, SRC_DRIFT, SRC_REAL

    real, slow, down = f[SRC_REAL], f[SRC_DRIFT], f[SRC_DOWN]
    real_payload, down_payload = real.get("payload") or {}, down.get("payload")
    threshold = SLOW_INJECTED_SECONDS - 0.5
    injected = slow["seconds"] >= threshold  # the slow fault really took effect
    ok = (not real["is_error"] and real_payload.get("ok") is True and injected
          and real["seconds"] < threshold and down["seconds"] < threshold
          and down_payload is not None and down_payload.get("ok") is False)
    obs = [_o("healthy source", "ok" if real_payload.get("ok") is True else "NOT ok",
              f"answered in {real['seconds']}s while another source was slow"),
           _o(f"slow source ({SLOW_INJECTED_SECONDS:g} s injected)", "fault effective" if injected else "FAULT NOT EFFECTIVE",
              f"{slow['seconds']}s; the others answered first"),
           _o("down source (503 injected)", "typed not-ok" if (down_payload or {}).get("ok") is False else "unexpected",
              f"payload {down_payload}, answered in {down['seconds']}s")]
    return Observed(oracle_match=ok), obs, ["source_health", "sources_list", "system_status"], ["GATEWAY_OBSERVATION"], "OFIX"


MIN_SWEEP_SOURCES = 12  # six logs and six control-plane tables


def _h_st083(story: Story, ev: dict[str, Any]):
    s = ev["secret"]
    ok = not s["hits"] and len(s["sources_scanned"]) >= MIN_SWEEP_SOURCES
    obs = [_o("secret sweep", "clean" if ok else ("HITS" if s["hits"] else "SWEEP TOO NARROW"),
              f"scanned {len(s['sources_scanned'])} sources: {', '.join(s['sources_scanned'])}; hits={len(s['hits'])}; "
              "literal values searched in raw, JSON-escaped, HTML-escaped and URL-quoted form")]
    return Observed(oracle_match=ok), obs, ["all"], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "artifact grep"


def _h_st084(story: Story, ev: dict[str, Any]):
    zw = ev["zero_write"]
    get_seen = zw["methods"].get("GET", 0) > 0
    ok = zw["fingerprint_equal"] and not zw["upstream_write_seen"] and get_seen
    obs = [_o("row-count fingerprint of six object kinds before/after the whole run", "equal" if zw["fingerprint_equal"] else "CHANGED",
              f"{zw['table_count']} tables, {zw['total_rows']} rows; sha256 {zw['pre'][:16]}… vs {zw['post'][:16]}… "
              "(detects added or removed rows, not an in-place edit that keeps counts)"),
           _o("upstream methods across all proxies", "GET/HEAD only" if (not zw["upstream_write_seen"] and get_seen) else "WRITE SEEN or no traffic",
              str(zw["methods"]))]
    return Observed(oracle_match=ok), obs, ["all"], ["GATEWAY_OBSERVATION", "NATIVE_COM_QUERY"], "ONAT fingerprint"


def _h_st085(story: Story, ev: dict[str, Any]):
    i = ev["identity"]
    obs = [_o("product reports the privilege of its upstream identity", "NO" if not i["product_reports_identity_privilege"] else "yes",
              "onec_capabilities / source_health / system_status expose no identity-privilege indicator"),
           _o("registered reader identity (COM write probe on the probe clone)", str(i["reader_com_write_probe"]),
              f"transaction rolled back: {i['reader_probe_rolled_back']}")]
    return (Observed(oracle_match=bool(i["product_reports_identity_privilege"])), obs, ["source_health", "onec_capabilities"],
            ["GATEWAY_OBSERVATION", "NATIVE_COM_QUERY"], "ONAT permission probe")


def _h_st086(story: Story, ev: dict[str, Any]):
    o = ev["outage"]
    during, health, after = o["read_during_outage"], o["recovered_health"], o["read_after_recovery"]
    health_ok = (health.get("payload") or {}).get("ok") is True
    ok = (during["is_error"] and during["detail"] == "OneCTransportError" and health_ok
          and not after["is_error"] and (after["rows"] or 0) >= 1)
    obs = [_o("read during outage", str(during["detail"]), "typed transport error; no cached rows shown"),
           _o("health after the upstream returns", "ok" if health_ok else "NOT ok", "recovered without a gateway restart"),
           _o("read after recovery", "rows returned" if (not after["is_error"] and (after["rows"] or 0) >= 1) else "FAILED",
              f"rows={after['rows']}")]
    return Observed(oracle_match=ok), obs, ["onec_read", "source_health"], ["GATEWAY_OBSERVATION"], "OFIX"


def _h_st054(story: Story, ev: dict[str, Any]):
    a = ev["acl"]
    obs = [_o("cross-source call with a grant on another source", str(a["cross_source_denied"]["detail"]),
              "a grant on source A does not widen to source B (supplementary; the story itself needs a mapped profile)")]
    return Observed(), obs, ["sources_list", "companies_list"], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "OACL"


def _h_st077(story: Story, ev: dict[str, Any]):
    e = ev["expiring"]
    created = e.get("create_http") == 201
    during_ok = e.get("during") == "SEMANTIC_PROFILE_UNVALIDATED"
    expired_ok = e.get("after_expiry") == "AccessDenied"
    works = created and during_ok and expired_ok
    obs = [_o("grant created with expires_at = now+8 s", f"HTTP {e.get('create_http')}", "through /admin/v1/grants"),
           _o("call while the grant is valid", str(e.get("during")), "ACL passed (profile gate answers)"),
           _o("call after expiry", str(e.get("after_expiry")), "denied automatically, no revoke performed")]
    # A probe that failed for any other reason proves nothing about the capability: it stays inconclusive.
    return (Observed(capability_absent_confirmed=False if works else None), obs, ["receivable_balance"],
            ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "OACL")


def _h_st022(story: Story, ev: dict[str, Any]):
    rows = list(ev["gate"].values())
    if any(r.get("transport_error") or (r["is_error"] and r["detail_code"] is None) for r in rows):
        return (Observed(error="a semantic tool call produced no typed gateway answer"),
                [_o("semantic data tools", "NO TYPED ANSWER", "transport failure or missing audit row")], [r["tool"] for r in rows],
                ["GATEWAY_OBSERVATION"], "semantic profile gate")
    refused = all(r["refused"] for r in rows)
    data = any(r["data_returned"] for r in rows)
    obs = [_o("all 13 semantic data tools (real company, 2026-08)", "REFUSED" if refused else ("DATA" if data else "OTHER"),
              "no number is served, so no provenance block can be inspected: " + ", ".join(sorted({r["detail_code"] or "-" for r in rows})))]
    return (Observed(profile_gate_refusal=True if refused else (False if not data else None), data_returned=data), obs,
            [r["tool"] for r in rows], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"], "semantic profile gate")


CUSTOM: dict[str, Handler] = {
    "ST-022": _h_st022, "ST-054": _h_st054, "ST-072": _h_st072, "ST-075": _h_st075, "ST-076": _h_st076, "ST-077": _h_st077,
    "ST-079": _h_st079, "ST-081": _h_st081, "ST-083": _h_st083, "ST-084": _h_st084, "ST-085": _h_st085, "ST-086": _h_st086,
}
DEFAULT: dict[str, Handler] = {"NP": _gate_default, "RR": _gate_default, "UG": _ug_default, "EV": _ev_default, "WD": _wd_default}


def evaluate_story(story: Story, ev: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    handler = CUSTOM.get(story.id) or DEFAULT[story.catalogue_class]
    try:
        observed, observations, tools, evidence, oracle = handler(story, ev)
    except Exception as exc:  # noqa: BLE001 - an evaluator defect must surface as ERROR on that story, never abort or pass
        message = redact_text(f"{type(exc).__name__}: {exc}")[:240]
        observed, observations, tools, evidence, oracle = (
            Observed(error=message), [_o("story evaluation", "ERROR", message)], [], ["NONE"], story.oracle)
    disposition, reason = decide(story.catalogue_class, observed)
    owner = {"SEMANTIC_PROFILE_UNVALIDATED": SEMANTIC_OWNER, "EVIDENCE_REQUIRED": EVIDENCE_OWNER,
             "CAPABILITY_UNSUPPORTED": CAPABILITY_OWNER, "FINDING": FINDING_OWNER}.get(disposition)
    supplementary = []
    for ref in RELATED.get(story.id, []):
        rel = ev["related"].get(ref)
        if rel:
            supplementary.append(_o(f"related {ref}", rel["verdict"], rel["title"]))
    result: dict[str, Any] = {
        **base, "case_id": story.id, "kind": story.kind, "title": story.title, "catalogue_class": story.catalogue_class,
        "disposition": disposition, "reason_code": reason, "evidence_classes": sorted(set(evidence)),
        "observations": observations, "tools_called": sorted(set(tools)), "oracle": oracle if oracle else story.oracle,
        "supplementary": supplementary, "priority": story.priority,
    }
    if owner:
        result["owner_action"] = owner
    if story.id in REQ_GAP_REFS:
        result["req_gap_refs"] = REQ_GAP_REFS[story.id]
    return result


def tool_name(abbr: str) -> str:
    return TOOL_ABBR.get(abbr, abbr)
