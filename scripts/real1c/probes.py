"""Evidence-gathering probes for the real-1C lane. Every probe returns plain dicts of OBSERVATIONS (no verdicts):
the verdict is produced afterwards by scripts.real1c.disposition.decide from these facts."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from pathlib import Path
from typing import Any

import asyncpg

from scripts.real1c.gateway_client import AdminSession, mcp_session
from scripts.real1c.lane import MUTATING_NAME, SRC_DOWN, SRC_DRIFT, SRC_REAL, Lane
from scripts.real1c.sanitize import scan_for_secrets

ROOT = Path(__file__).resolve().parents[2]
PERIOD_START, PERIOD_END, AS_OF = "2026-08-01", "2026-08-31", "2026-08-31"
LITERAL_CANARY = "Pa55 w0rd literal!"  # planted as a literal secret: it must never appear in logs, rows or outputs

# abbreviation used by the frozen catalogue -> public MCP tool name
TOOL_ABBR = {
    "ABT": "accounting_balance_and_turnovers", "APR": "accounting_posting_rows", "INVB": "inventory_balance",
    "INVM": "inventory_movements", "CASH": "cash_movements", "BANK": "bank_balance",
    "ARB": "receivable_balance", "APB": "payable_balance", "ARA": "receivable_aging", "APA": "payable_aging",
    "DUP": "counterparty_duplicate_candidates", "SAL": "sales_documents", "PUR": "purchase_documents",
    "READ": "onec_read", "EVM": "external_evidence_manifest", "CO": "companies_list", "SRC": "sources_list",
    "HLT": "source_health", "CAP": "onec_capabilities", "META": "onec_metadata_summary",
    "FIND": "onec_find_entities", "RSV": "rsv_metadata", "STAT": "system_status",
}
GATED_TOOLS = ("ABT", "APR", "INVB", "INVM", "CASH", "BANK", "ARB", "APB", "ARA", "APA", "DUP", "SAL", "PUR")


def gated_args(tool_abbr: str, source: str, company: str) -> dict[str, Any]:
    base = {"source_id": source, "company_id": company}
    if tool_abbr in ("ABT", "INVM", "CASH", "APR"):
        args = {**base, "start_period": PERIOD_START, "end_period": PERIOD_END}
        if tool_abbr in ("INVM", "CASH", "APR"):
            args["top"] = 5
        return args
    if tool_abbr in ("INVB", "BANK", "ARB", "APB"):
        return {**base, "period": AS_OF}
    if tool_abbr in ("ARA", "APA"):
        return {**base, "as_of": "2026-08-31T23:59:59+03:00", "top": 5}  # explicit Europe/Chisinau offset
    if tool_abbr == "DUP":
        return {**base, "top": 5}
    return {**base, "top": 5}  # SAL / PUR


def product_surface_text(tools: list[dict[str, str]]) -> str:
    """Names + descriptions of public MCP tools, admin API routes and CLI sub-commands (lower-case)."""
    parts = [f"{t['name']} {t['description']}" for t in tools]
    routes = re.findall(r'"(/admin/v1/[^"]+)"', (ROOT / "src/business_ai_gateway/admin_api.py").read_text(encoding="utf-8"))
    commands = re.findall(r'add_parser\("([^"]+)"', (ROOT / "scripts/admin.py").read_text(encoding="utf-8"))
    if len(routes) < 10 or len(commands) < 5:  # a refactor that empties the regexes must not turn every miss into "absent"
        raise RuntimeError(f"product surface scan matched too little: {len(routes)} admin routes, {len(commands)} CLI commands")
    return " ".join(parts + routes + commands).lower()


async def probe_discovery(lane: Lane) -> dict:
    tools = await lane.list_tools("auditor")
    names = [t["name"] for t in tools]
    return {"tools": tools, "names": names, "count": len(names),
            "mutating_names": [n for n in names if re.search(MUTATING_NAME, n)],
            "surface": product_surface_text(tools)}


async def probe_semantic_gate(lane: Lane) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for abbr in GATED_TOOLS:
        tool = TOOL_ABBR[abbr]
        r = await lane.call("user_company_one", tool, gated_args(abbr, SRC_REAL, lane.real_company))
        detail = (r["audit"] or {}).get("detail_code")
        out[abbr] = {"tool": tool, "is_error": r["is_error"], "detail_code": detail, "transport_error": r["transport_error"],
                     "outcome": (r["audit"] or {}).get("outcome"),
                     "refused": bool(r["is_error"] and detail == "SEMANTIC_PROFILE_UNVALIDATED"),
                     "data_returned": bool(not r["is_error"] and r["payload"])}
    return out


async def probe_evidence_tool(lane: Lane) -> dict:
    r = await lane.call("user_company_one", "external_evidence_manifest",
                        {"source_id": SRC_REAL, "company_id": lane.real_company, "evidence_id": "0" * 32})
    payload = r["payload"] if isinstance(r["payload"], dict) else {}
    status = payload.get("status")
    return {"status": status, "audit": r["audit"], "transport_error": r["transport_error"],
            "business_acceptance": payload.get("business_acceptance"),
            "native_approval_inferred": payload.get("native_approval_inferred"),
            "evidence_required": (not r["transport_error"]) and status in {"CAPABILITY_UNSUPPORTED", "EVIDENCE_REQUIRED", "NOT_FOUND"},
            "data_returned": bool(payload.get("facts") or payload.get("rows"))}


ABUSE_CASES = [
    ("action_post", {"entity_set": "Document_РеализацияТоваровУслуг(guid'00000000-0000-0000-0000-000000000000')/Post"}),
    ("batch_endpoint", {"entity_set": "$batch"}),
    ("absolute_url", {"entity_set": "http://evil.example/x"}),
    ("path_traversal", {"entity_set": "../Catalog_Контрагенты"}),
    ("function_call_filter", {"entity_set": "Catalog_Организации", "filter_expr": "ПровестиДокумент(1) eq true"}),
    ("filter_statement_injection", {"entity_set": "Catalog_Организации", "filter_expr": "Description eq 'x'; DELETE"}),
    ("entity_outside_allowlist", {"entity_set": "Catalog_Сотрудники"}),
    ("entity_not_in_metadata", {"entity_set": "Catalog_ЭтогоНеСуществует"}),
]


async def probe_write_surface(lane: Lane, disc: dict) -> dict:
    proxy = lane.proxy(SRC_REAL)
    proxy.reset()
    cases = []
    for name, args in ABUSE_CASES:
        r = await lane.call("auditor", "onec_read", {"source_id": SRC_REAL, "top": 1, **args})
        value = r["payload"].get("value") if isinstance(r["payload"], dict) else None
        cases.append({"case": name, "is_error": r["is_error"], "transport_error": r["transport_error"],
                      "detail": (r["audit"] or {}).get("detail_code"),
                      "rows": len(value) if isinstance(value, list) else None})
    seen = proxy.requests()
    upstream_methods = set(seen.get("by_method", {}))
    return {"cases": cases, "tool_names_mutating": disc["mutating_names"],
            "upstream_methods": sorted(upstream_methods), "refused_methods": seen.get("refused_methods", {}),
            "upstream_write_seen": bool(upstream_methods - {"GET", "HEAD"}) or bool(seen.get("refused_methods")),
            "paths": seen.get("paths", {})}


# ----------------------------------------------------------------------------- ACL / grants
async def _grant_row(lane: Lane, principal: str, company: str | None) -> dict | None:
    row = await lane.db.fetchrow(
        "select grant_id, row_version from bag.access_grants where principal_id=$1 and source_id=$2 "
        "and company_id is not distinct from $3::uuid and effect='allow' and revoked_at is null "
        "order by created_at desc limit 1", principal, SRC_REAL, company)
    return dict(row) if row else None


async def probe_acl(lane: Lane) -> dict:
    real, syn = lane.real_company, lane.syn_company
    obs: dict[str, Any] = {}

    async def gate(user: str, company: str, source: str = SRC_REAL) -> dict:
        r = await lane.call(user, "receivable_balance", {"source_id": source, "company_id": company, "period": AS_OF})
        a = r["audit"] or {}
        return {"is_error": r["is_error"], "detail": a.get("detail_code"), "outcome": a.get("outcome"),
                "transport_error": r["transport_error"]}

    obs["allowed_company"] = await gate("user_company_one", real)
    obs["other_company_denied"] = await gate("user_company_one", syn)
    obs["other_user_real_company_denied"] = await gate("user_company_two", real)
    obs["no_access_denied"] = await gate("user_no_access", real)
    obs["cross_source_denied"] = await gate("user_company_one", real, SRC_DRIFT)
    listed = await lane.call("user_no_access", "companies_list", {"source_id": SRC_REAL})
    obs["no_access_company_list"] = (len(listed["payload"]) if (isinstance(listed["payload"], list) and not listed["is_error"]) else None)
    one = await lane.call("user_company_one", "companies_list", {"source_id": SRC_REAL})
    obs["company_one_list"] = ([c["company_id"] for c in one["payload"]]
                               if (isinstance(one["payload"], list) and not one["is_error"]) else None)
    bad = await lane.call("user_company_one", "receivable_balance",
                          {"source_id": SRC_REAL, "company_id": "not-a-uuid-not-a-uuid-not-a-uuid-1234", "period": AS_OF})
    obs["invalid_company_id"] = (bad["audit"] or {}).get("detail_code")

    # revoke mid-session (same MCP session before/after) + re-grant (the grant is restored even if a step raises)
    aa = AdminSession(lane.env, "access_admin")
    grant = await _grant_row(lane, "user_company_one", real)
    if grant:
        from scripts.real1c.gateway_client import call_tool

        async def last_detail(since: Any) -> str | None:
            for _ in range(8):
                row = await lane.db.fetchrow(
                    "select detail_code from bag.audit_events where tool_name='receivable_balance' and "
                    "principal_subject='user_company_one' and occurred_at >= $1 order by occurred_at desc limit 1", since)
                if row:
                    return row["detail_code"]
                await asyncio.sleep(0.1)
            return None

        revoked = False
        result: dict[str, Any] = {}
        try:
            async with mcp_session(lane.env, lane.token("user_company_one")) as session:
                t0 = await lane.db.fetchval("select clock_timestamp()")
                before = await call_tool(session, "receivable_balance",
                                         {"source_id": SRC_REAL, "company_id": real, "period": AS_OF})
                before_detail = await last_detail(t0)
                lane.probe_label = "acl:revoke"
                lane.log_call("user_company_one", "receivable_balance",
                              {"source_id": SRC_REAL, "company_id": real, "period": AS_OF},
                              {**before, "audit": {"detail_code": before_detail}, "ms": None})
                resp = aa.post(f"/admin/v1/grants/{grant['grant_id']}/revoke",
                               {"expected_version": grant["row_version"], "reason": "real-1C lane: revoke mid-session test"})
                revoked = resp.status_code == 200
                t1 = await lane.db.fetchval("select clock_timestamp()")
                after = await call_tool(session, "receivable_balance",
                                        {"source_id": SRC_REAL, "company_id": real, "period": AS_OF})
                after_detail = await last_detail(t1)
                lane.log_call("user_company_one", "receivable_balance",
                              {"source_id": SRC_REAL, "company_id": real, "period": AS_OF},
                              {**after, "audit": {"detail_code": after_detail}, "ms": None})
                lane.probe_label = "acl"
            result = {"revoke_http": resp.status_code, "before_detail": before_detail, "before_is_error": before["is_error"],
                      "after_detail": after_detail, "after_is_error": after["is_error"]}
        finally:
            regrant_http = None
            if revoked:
                regrant = aa.post("/admin/v1/grants", {
                    "principal_kind": "subject", "principal_id": "user_company_one", "source_id": SRC_REAL,
                    "company_id": real, "effect": "allow", "reason": "real-1C lane: restore after revoke test"})
                regrant_http = regrant.status_code
        obs["revoke_mid_session"] = {**result, "regrant_http": regrant_http}
    aa.close()
    return obs


async def probe_expiring_grant(lane: Lane) -> dict:
    """ST-077: a time-boxed grant (expires_at) must stop working by itself."""
    aa = AdminSession(lane.env, "access_admin")
    expiry = (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=8)).isoformat(timespec="seconds")
    resp = aa.post("/admin/v1/grants", {
        "principal_kind": "subject", "principal_id": "user_no_access", "source_id": SRC_REAL,
        "company_id": lane.real_company, "effect": "allow", "expires_at": expiry,
        "reason": "real-1C lane: time-boxed access test"})
    result: dict[str, Any] = {"create_http": resp.status_code, "response_keys": sorted((resp.json() or {}).keys()) if resp.status_code == 201 else []}
    if resp.status_code == 201:
        first = await lane.call("user_no_access", "receivable_balance",
                                {"source_id": SRC_REAL, "company_id": lane.real_company, "period": AS_OF})
        await asyncio.sleep(10)
        second = await lane.call("user_no_access", "receivable_balance",
                                 {"source_id": SRC_REAL, "company_id": lane.real_company, "period": AS_OF})
        result["during"] = (first["audit"] or {}).get("detail_code")
        result["after_expiry"] = (second["audit"] or {}).get("detail_code")
    aa.close()
    return result


async def probe_admin_lifecycle(lane: Lane) -> dict:
    """Admin Control Center lifecycle on the real source: effective access, overview, audit, profile draft."""
    pa = AdminSession(lane.env, "platform_admin")
    obs: dict[str, Any] = {}
    for label, path in (("overview", "/admin/v1/overview"), ("sources", "/admin/v1/sources"),
                        ("companies", "/admin/v1/companies"), ("grants", "/admin/v1/grants"),
                        ("capabilities", "/admin/v1/capabilities"), ("audit", "/admin/v1/audit"),
                        ("profiles", "/admin/v1/semantic-profiles")):
        r = pa.get(path)
        obs[f"GET {label}"] = r.status_code
    ui = pa.get("/admin/")
    obs["GET /admin/ (UI shell)"] = ui.status_code
    eff = pa.get(f"/admin/v1/effective-access?kind=subject&id=user_company_one&source_id={SRC_REAL}")
    obs["effective-access user_company_one"] = eff.status_code
    pf = AdminSession(lane.env, "profile_admin")
    created = pf.post("/admin/v1/semantic-profiles", {
        "source_id": SRC_REAL, "company_id": None, "preset_id": "bp30", "profile_name": "real-1c-818ha-draft",
        "profile_definition": {}, "reason": "real-1C lane: draft profile for the reference source"})
    obs["profile draft create"] = created.status_code
    if created.status_code == 201:
        pid = created.json()["id"]
        # Honest negative probe: three cases that are explicitly NOT native confirmations (pending owner reports).
        pending = [{"case_id": f"NR-{i:02d}", "native_report_ref": f"pending://owner-native-ui-report/NR-{i:02d}",
                    "status": "NEEDS_NATIVE_CONFIRMATION"} for i in (2, 3, 4)]
        val = pf.post(f"/admin/v1/semantic-profiles/{pid}/validate", {
            "validation_evidence": {"native_reconciliation_cases": pending},
            "reason": "real-1C lane: validation attempt without genuine native evidence (must be refused)"})
        try:
            val_code = val.json().get("error")
        except ValueError:
            val_code = None
        obs["profile validate without native evidence"] = {"http": val.status_code, "error_code": val_code, "body": val.text[:160]}
        status = await lane.db.fetchval("select status from bag.semantic_profiles where profile_id=$1::uuid", pid)
        obs["profile status after refused validation"] = status
    pa.close()
    pf.close()
    return obs


# ----------------------------------------------------------------------------- audit / secrets
class _Rollback(Exception):
    """Forces rollback of the audit-tamper probe transaction."""


async def probe_audit(lane: Lane) -> dict:
    expected = [c for c in lane.calls if c["expected"]]
    total = len(expected)
    with_audit = sum(1 for c in expected if c["audit"] is not None)
    tamper: dict[str, Any] = {}
    for role in ("app", "admin", "control"):
        conn = await asyncpg.connect(lane.env.dsn(role))
        for verb, sql in (("UPDATE", "update bag.audit_events set outcome=outcome where false"),
                          ("DELETE", "delete from bag.audit_events where false"),
                          ("TRUNCATE", "truncate bag.audit_events")):
            try:
                async with conn.transaction():  # rolled back below, so a permitted TRUNCATE can never destroy the evidence
                    await conn.execute(sql)
                    tamper[f"{role}:{verb}"] = "ALLOWED"
                    raise _Rollback
            except _Rollback:
                pass
            except Exception as exc:  # noqa: BLE001 - the denial class is the observation
                tamper[f"{role}:{verb}"] = type(exc).__name__
        await conn.close()
    sample = await lane.db.fetchrow("select * from bag.audit_events order by occurred_at desc limit 1")
    return {"calls_made": total, "calls_with_audit_row": with_audit, "tamper": tamper,
            "audit_columns": sorted(sample.keys()) if sample else []}


SWEEP_LOGS = ("gateway.out.log", "gateway.err.log", "real_sidecar.out.log", "real_sidecar.err.log", "idp.out.log",
              "sidecar.out.log")


def _secret_variants(secret: str) -> set[str]:
    import html
    import json
    from urllib.parse import quote

    return {secret, json.dumps(secret)[1:-1], html.escape(secret), html.escape(secret, quote=False), quote(secret, safe="")}


async def probe_secret_sweep(lane: Lane, secrets: list[str], extra_text: list[tuple[str, str]]) -> dict:
    if not [x for x in secrets if x]:
        raise RuntimeError("secret sweep needs at least one real secret value to search for")
    texts: list[tuple[str, str]] = list(extra_text)
    logs = Path(r"D:\ERP_MCP_Testbed\real1c_e2e\logs")
    for name in SWEEP_LOGS:
        p = logs / name
        if not p.exists():
            raise RuntimeError(f"secret sweep cannot run: required log {name} is missing")
        raw = p.read_bytes()
        encoding = "utf-16" if (raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in raw[:2000]) else "utf-8"
        texts.append((name, raw.decode(encoding, errors="replace")))
    for table in ("audit_events", "semantic_profile_events", "source_capabilities", "sources", "companies",
                  "access_grants"):
        rows = await lane.db.fetch(f"select to_jsonb(t)::text as j from bag.{table} t")
        texts.append((f"bag.{table}", "\n".join(r["j"] for r in rows)))
    hits: list[dict] = []
    for where, text in texts:
        for secret in secrets:
            if secret and any(v in text for v in _secret_variants(secret)):
                hits.append({"where": where, "kind": "literal_secret"})
        for pattern in scan_for_secrets(text):
            hits.append({"where": where, "kind": pattern})
    return {"sources_scanned": [w for w, _ in texts], "hits": hits}


# ----------------------------------------------------------------------------- outage / drift
async def _ensure_source_grant(lane: Lane, source: str) -> None:
    exists = await lane.db.fetchval(
        "select 1 from bag.access_grants where principal_id='auditor' and source_id=$1 and company_id is null "
        "and effect='allow' and revoked_at is null", source)
    if not exists:
        pa = AdminSession(lane.env, "platform_admin")
        resp = pa.post("/admin/v1/grants", {"principal_kind": "subject", "principal_id": "auditor",
                                           "source_id": source, "company_id": None, "effect": "allow",
                                           "reason": "real-1C lane: source-level reader for outage/drift tests"})
        pa.close()
        if resp.status_code != 201:
            raise RuntimeError(f"grant for {source} failed: HTTP {resp.status_code}")


async def probe_outage(lane: Lane) -> dict:
    await _ensure_source_grant(lane, SRC_DRIFT)
    await _ensure_source_grant(lane, SRC_DOWN)
    slow, down = lane.proxy(SRC_DRIFT), lane.proxy(SRC_DOWN)
    slow.mode("slow", delay=6)
    down.mode("down")
    started = time.monotonic()

    async def timed(source: str) -> dict:
        t0 = time.monotonic()
        r = await lane.call("auditor", "source_health", {"source_id": source}, correlate=False)
        return {"source": source, "seconds": round(time.monotonic() - t0, 2), "is_error": r["is_error"],
                "payload": r["payload"] if not r["is_error"] else None}

    results = await asyncio.gather(timed(SRC_REAL), timed(SRC_DRIFT), timed(SRC_DOWN))
    by_source = {r["source"]: r for r in results}
    for source, entry in by_source.items():
        row = await lane.db.fetchrow(
            "select outcome, detail_code from bag.audit_events where tool_name='source_health' and source_id=$1 "
            "order by occurred_at desc limit 1", source)
        entry["detail"] = row["detail_code"] if row else None
        entry["outcome"] = row["outcome"] if row else None
    during_read = await lane.call("auditor", "onec_read", {"source_id": SRC_DOWN, "entity_set": "Catalog_Валюты", "top": 1})
    slow.mode("head_compat")
    down.mode("head_compat")
    recovered = await timed(SRC_DOWN)
    read_after = await lane.call("auditor", "onec_read", {"source_id": SRC_DOWN, "entity_set": "Catalog_Валюты", "top": 1})
    return {"fan_out": by_source, "wall_seconds": round(time.monotonic() - started, 2),
            "read_during_outage": {"is_error": during_read["is_error"],
                                   "detail": (during_read["audit"] or {}).get("detail_code")},
            "recovered_health": recovered,
            "read_after_recovery": {"is_error": read_after["is_error"],
                                    "rows": len((read_after["payload"] or {}).get("value", [])) if isinstance(read_after["payload"], dict) else None}}


async def probe_drift(lane: Lane) -> dict:
    await _ensure_source_grant(lane, SRC_DRIFT)
    proxy = lane.proxy(SRC_DRIFT)
    pa = AdminSession(lane.env, "platform_admin")
    before = await lane.db.fetchrow(
        "select metadata_fingerprint, drift_status from bag.source_capabilities where source_id=$1", SRC_DRIFT)
    proxy.mode("drift")
    refreshed = pa.post(f"/admin/v1/sources/{SRC_DRIFT}/capability-refresh", {"reason": "real-1C lane: drift observation"})
    after = await lane.db.fetchrow(
        "select metadata_fingerprint, drift_status from bag.source_capabilities where source_id=$1", SRC_DRIFT)
    read = await lane.call("auditor", "onec_read", {"source_id": SRC_DRIFT, "entity_set": "Catalog_Валюты", "top": 1})
    gated = await lane.call("user_company_one", "receivable_balance",
                            {"source_id": SRC_DRIFT, "company_id": lane.real_company, "period": AS_OF})
    proxy.mode("head_compat")
    restored = pa.post(f"/admin/v1/sources/{SRC_DRIFT}/capability-refresh", {"reason": "real-1C lane: drift restore"})
    row = await lane.db.fetchrow(
        "select metadata_fingerprint, drift_status from bag.source_capabilities where source_id=$1", SRC_DRIFT)
    ack_http = None
    if row and row["drift_status"] == "DRIFTED":
        ack = pa.post(f"/admin/v1/sources/{SRC_DRIFT}/drift-acknowledgements", {
            "expected_fingerprint": row["metadata_fingerprint"], "reason": "real-1C lane: acknowledge restored metadata"})
        ack_http = ack.status_code
    pa.close()
    return {"before": dict(before) if before else None, "drifted_refresh_http": refreshed.status_code,
            "after": dict(after) if after else None,
            "read_while_drifted": {"is_error": read["is_error"], "detail": (read["audit"] or {}).get("detail_code")},
            "gated_while_drifted": {"is_error": gated["is_error"], "detail": (gated["audit"] or {}).get("detail_code")},
            "restore_http": restored.status_code, "after_restore": dict(row) if row else None, "ack_http": ack_http}


# ----------------------------------------------------------------------------- audit gaps / identity / portfolio
async def probe_malformed_audit(lane: Lane) -> dict:
    """Does a malformed call leave an audit row?  (Story: one audit row per call.)"""
    cases = [
        ("aging naive as_of", "user_company_one", "receivable_aging",
         {"source_id": SRC_REAL, "company_id": lane.real_company, "as_of": "2026-08-31", "top": 5}),
        ("aging top=0", "user_company_one", "receivable_aging",
         {"source_id": SRC_REAL, "company_id": lane.real_company, "as_of": "2026-08-31T00:00:00+03:00", "top": 0}),
        ("onec_read top=-1", "auditor", "onec_read", {"source_id": SRC_REAL, "entity_set": "Catalog_Валюты", "top": -1}),
        ("invalid company uuid", "user_company_one", "receivable_balance",
         {"source_id": SRC_REAL, "company_id": "not-a-uuid-not-a-uuid-not-a-uuid-1234", "period": AS_OF}),
    ]
    rows = []
    for label, user, tool, args in cases:
        r = await lane.call(user, tool, args, expect_audit=False)
        rows.append({"case": label, "is_error": r["is_error"], "audit_row": r["audit"] is not None,
                     "detail": (r["audit"] or {}).get("detail_code")})
    return {"cases": rows, "unaudited": [c["case"] for c in rows if not c["audit_row"]]}


async def probe_identity(lane: Lane) -> dict:
    caps = await lane.call("auditor", "onec_capabilities", {"source_id": SRC_REAL})
    status = await lane.call("auditor", "system_status", {})
    health = await lane.call("auditor", "source_health", {"source_id": SRC_REAL})
    text = " ".join(str(x["payload"]).lower() for x in (caps, status, health))
    keys = ("privilege", "write_capable", "rw_identity", "read_only_identity", "identity_class")
    zero_write = Path(r"D:\ERP_MCP_Testbed\1c\reference\scenario_pack\manifests\com_zero_write_probe.json")
    import json

    probe = json.loads(zero_write.read_text(encoding="utf-8")) if zero_write.exists() else {}
    return {"product_reports_identity_privilege": any(k in text for k in keys),
            "reader_com_write_probe": probe.get("write_probe"), "reader_probe_rolled_back": probe.get("transaction_rolled_back")}


async def probe_literal_secret(lane: Lane) -> dict:
    pa = AdminSession(lane.env, "platform_admin")
    resp = pa.post("/admin/v1/sources", {
        "source_id": "onec-818ha-literal-secret-probe", "display_name": "must be refused",
        "base_url": "http://127.0.0.1:8191/erp_mcp_ref/odata/standard.odata",
        "username_secret_ref": "Admin_1C", "password_secret_ref": LITERAL_CANARY, "tags": [],
        "reason": "real-1C lane: a literal secret instead of a secret reference must be refused"})
    existing = await lane.db.fetchval("select count(*) from bag.sources where source_id='onec-818ha-literal-secret-probe'")
    pa.close()
    try:
        code = resp.json().get("error")
    except ValueError:
        code = None
    return {"http": resp.status_code, "error_code": code, "row_created": int(existing or 0),
            "echoes_literal": LITERAL_CANARY in resp.text}


async def probe_portfolio(lane: Lane, companies: int = 150) -> dict:
    """ST-075: 150 companies on a synthetic portfolio source; two principals with disjoint company grants."""
    import os
    import subprocess
    import sys
    import uuid

    source = "onec-818ha-portfolio"
    env = dict(os.environ)
    env.update({"BAG_ADMIN_DATABASE_URL": lane.env.dsn("admin"), "BAG_DATABASE_URL": lane.env.dsn("app"),
                "BAG_ENVIRONMENT": "test", "PYTHONPATH": str(ROOT / "src") + ";" + str(ROOT)})

    def cli(*args: str) -> int:
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "admin.py"), *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120, check=False).returncode

    base = "http://127.0.0.1:8191/erp_mcp_ref/odata/standard.odata"
    source_rc = cli("source-upsert", "--source-id", source, "--display-name",
                    "SYNTHETIC portfolio fixture (150 companies)", "--base-url", base,
                    "--username-secret", "ERP_MCP_818HA_USER", "--password-secret", "ERP_MCP_818HA_PASSWORD",
                    "--tags", "synthetic-fixture", "--allow", "Catalog_Валюты")
    if source_rc != 0:
        raise RuntimeError(f"portfolio probe: source-upsert failed with exit code {source_rc}")
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"real1c-portfolio-{i}")) for i in range(companies)]
    sem = asyncio.Semaphore(8)

    async def up(i: int, cid: str) -> int:
        async with sem:
            return await asyncio.to_thread(cli, "company-upsert", "--company-id", cid, "--source-id", source,
                                           "--external-ref", str(uuid.uuid5(uuid.NAMESPACE_URL, f"ghost-org-{i}")),
                                           "--display-name", f"SYNTHETIC portfolio company {i:03d}")

    created = await asyncio.gather(*(up(i, cid) for i, cid in enumerate(ids)))

    async def grant(principal: str, cid: str) -> int:
        async with sem:
            return await asyncio.to_thread(cli, "grant-add", "--kind", "subject", "--principal", principal,
                                           "--source-id", source, "--company-id", cid)

    half = companies // 2
    grants = await asyncio.gather(*([grant("user_company_one", c) for c in ids[:half]]
                                    + [grant("user_company_two", c) for c in ids[half:]]))
    t0 = time.monotonic()
    one = await lane.call("user_company_one", "companies_list", {"source_id": source})
    two = await lane.call("user_company_two", "companies_list", {"source_id": source})
    seconds = round(time.monotonic() - t0, 2)
    a = {c["company_id"] for c in (one["payload"] or [])}
    b = {c["company_id"] for c in (two["payload"] or [])}
    created_ok = sum(1 for rc in created if rc == 0)
    grants_ok = sum(1 for rc in grants if rc == 0)
    return {"companies_created": created_ok, "grants_created": grants_ok,
            "visible_to_one": len(a), "visible_to_two": len(b), "overlap": len(a & b),
            "union_equals_all": (a | b) == set(ids), "list_seconds": seconds,
            "paging_parameters_supported": False,
            "passed": created_ok == companies and grants_ok == companies and not (a & b) and (a | b) == set(ids)}
