"""Per-test documentation: which request each test sent and what came back (shape only, never business values).

Pure functions over the collected evidence (`ev["call_log"]`, `ev["query_log"]`); the result is attached to every
case result as `calls` / `queries` / `channel_note` and rendered by details_report.py.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from scripts.real1c.probes import GATED_TOOLS, TOOL_ABBR
from scripts.real1c.sanitize import redact_business_values

MAX_CALLS = 4
MAX_QUERIES = 4
_NUMBER_IN_QUERY = re.compile(r'(НомерВходящегоДокумента\s*=\s*")([^"]*)(")')
_NAME_IN_QUERY = re.compile(r'(ПОДОБНО\s*"%)([^%"]*)(%")')

# Tests whose request is not an MCP tool call: the channel is described in words instead.
CHANNEL_NOTES: dict[str, str] = {
    "ST-083": "No tool call. The sweep reads gateway/sidecar/IdP logs and control-plane tables (rows as JSON) and searches every "
              "real secret value, a planted canary, and credential patterns in raw, JSON-, HTML- and URL-escaped form.",
    "ST-084": "No tool call. COM read-only row counts of 1184 metadata objects are taken before and after the whole run, and the "
              "loopback proxies count the HTTP methods that reached the real 1C.",
    "SYS-01": "HTTP HEAD <real 1C publication>/$metadata through the loopback proxy switched to passthrough mode, with the "
              "registered reader identity (credential kept in memory only).",
    "SYS-05": "Admin API: POST /admin/v1/sources as platform_admin, with a literal credential value in the password-reference field.",
    "SYS-06": "Admin API as platform_admin: GET overview, sources, companies, grants, capabilities, audit, semantic-profiles, "
              "effective-access, and the /admin/ UI shell.",
    "SYS-07": "Admin API as profile_admin: POST /admin/v1/semantic-profiles (draft), then POST …/validate with three cases whose "
              "status is NEEDS_NATIVE_CONFIRMATION.",
    "ST-077": "Admin API: POST /admin/v1/grants with expires_at = now + 8 s for a principal without access, then two MCP calls "
              "(inside the validity window and after it).",
    "ST-079": "Admin API: capability-refresh with the loopback proxy in drift mode (one extra EntitySet), a data read and a "
              "semantic call while drifted, capability-refresh after restore, drift acknowledgement by exact fingerprint.",
    "ST-081": "Three source_health calls issued concurrently: healthy source, slow source (6 s injected), down source (503 injected).",
    "ST-086": "source_health and onec_read against a source whose upstream is switched down, then up again, without restarting the gateway.",
    "ST-075": "CLI: 150 synthetic companies and two disjoint grant sets are created on a synthetic portfolio source; then two "
              "companies_list MCP calls, one per principal.",
    "ST-076": "MCP calls with malformed arguments, plus SQL attempts (UPDATE/DELETE/TRUNCATE inside rolled-back transactions) "
              "on the audit table with the application, admin and control roles.",
    "ST-085": "MCP onec_capabilities, source_health and system_status payloads are searched for any privilege indicator of the "
              "upstream identity; the reader identity was probed separately by a COM write attempt on the probe clone.",
}

STORY_PROBES: dict[str, tuple[str, ...]] = {
    "ST-054": ("acl",), "ST-072": ("acl:revoke",), "ST-075": ("portfolio",), "ST-076": ("malformed",), "ST-077": ("expiring",),
    "ST-079": ("drift",), "ST-081": ("outage",), "ST-086": ("outage",), "ST-085": ("identity",),
    "SYS-02": ("malformed",), "SYS-03": ("identity",), "SYS-04": ("portfolio",), "ACL-07": ("acl:revoke",),
}
ACL_ORDER = {"ACL-01": 0, "ACL-02": 1, "ACL-03": 2, "ACL-04": 3, "ACL-05": 4}


def clean_query(text: str) -> str:
    """A COM query as documentation: owner-supplied identifiers are replaced by short hashes."""
    def mask(m: re.Match[str]) -> str:
        return m.group(1) + "<sha8:" + hashlib.sha256(m.group(2).encode()).hexdigest()[:8] + ">" + m.group(3)

    masked = _NAME_IN_QUERY.sub(mask, _NUMBER_IN_QUERY.sub(mask, text))
    return " ".join(redact_business_values(masked).split())[:600]


def _by_probe(ev: dict[str, Any], *labels: str) -> list[dict]:
    return [c for c in ev.get("call_log", []) if c["probe"] in labels]


def _queries(ev: dict[str, Any], *labels: str) -> list[dict]:
    items = [clean_query(text) for label, text in ev.get("query_log", []) if label in labels]
    return [{"text": t} for t in items[:MAX_QUERIES]] + ([{"text": f"… {len(items) - MAX_QUERIES} more queries"}] if len(items) > MAX_QUERIES else [])


def _gated_calls(ev: dict[str, Any], tools: list[str]) -> list[dict]:
    names = {TOOL_ABBR[t] for t in tools}
    return [c for c in ev.get("call_log", []) if c["probe"] == "gate" and c["tool"] in names]


def select(case_id: str, kind: str, catalogue_class: str | None, story_tools: tuple[str, ...], ev: dict[str, Any]
           ) -> dict[str, Any]:
    """Return {'calls': [...], 'calls_total': n, 'queries': [...], 'channel_note': str} for one case."""
    calls: list[dict] = []
    queries: list[dict] = []
    note = CHANNEL_NOTES.get(case_id, "")
    if kind in ("ST", "AX"):
        if case_id in STORY_PROBES:
            calls = _by_probe(ev, *STORY_PROBES[case_id])
            if case_id == "ST-054":
                calls = [c for c in calls if c["arguments"].get("source_id") == "onec-818ha-drift"]
            if case_id == "ST-086":
                calls = [c for c in calls if c["tool"] in {"onec_read", "source_health"}]
        elif case_id == "ST-022":
            calls = _by_probe(ev, "gate")
        elif case_id in CHANNEL_NOTES:
            pass
        elif catalogue_class in ("NP", "RR") and any(t in GATED_TOOLS for t in story_tools):
            calls = _gated_calls(ev, [t for t in story_tools if t in GATED_TOOLS])
        elif catalogue_class == "EV":
            calls = _by_probe(ev, "evtool")
        elif catalogue_class == "WD":
            calls = _by_probe(ev, "write")
        elif catalogue_class == "UG":
            note = ("No request is sent: the capability is searched in the product surface (public MCP tool names and "
                    "descriptions, admin API routes, CLI sub-commands) with the pattern shown in the observation.")
        else:
            note = "The story names no tool the lane can call on the real source, so no request exists to document."
    elif kind == "RL2":
        calls = _by_probe(ev, f"rl2:{case_id}")
        queries = _queries(ev, case_id)
        note = "Gateway rows (onec_read through the real sidecar) are compared with a read-only COM query of the clone."
    elif kind == "ACL":
        if case_id in ACL_ORDER:
            probe_calls = [c for c in _by_probe(ev, "acl") if c["tool"] == "receivable_balance"]
            calls = probe_calls[ACL_ORDER[case_id]: ACL_ORDER[case_id] + 1]
        elif case_id == "ACL-06":
            calls = [c for c in _by_probe(ev, "acl") if c["tool"] == "companies_list"]
        elif case_id == "ACL-07":
            calls = _by_probe(ev, "acl:revoke")
            note = CHANNEL_NOTES.get("ACL-07", "Revoke through the Admin API between the two calls (same MCP session).")
    elif kind == "SYS":
        if case_id in STORY_PROBES:
            calls = _by_probe(ev, *STORY_PROBES[case_id])
    elif kind in ("NR", "INV"):
        queries = _queries(ev, case_id)
        note = "COM read-only query on the reference clone (comparison evidence, not a native UI report)."
    elif kind == "RULE":
        note = "COM read-only applicability queries (account exists in the chart; August posting rows) and the product-surface search."
    total = len(calls)
    return {"calls": calls[:MAX_CALLS], "calls_total": total, "queries": queries, "channel_note": note}
