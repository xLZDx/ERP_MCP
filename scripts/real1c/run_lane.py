"""Orchestrator of the real 1C 818HA L2 lane (read-only).

    python -m scripts.real1c.run_lane [--dev]

Gates (any failure exits non-zero before a single story is evaluated):
  frozen catalogue sha256 -> reference manifest hash -> live COM fingerprint equals the manifest -> stack and
  loopback proxies reachable -> committed code tree (gate mode only).
After the run: the COM fingerprint must equal the pre-run one, and every generated output is swept for secrets
before it is written.  Raw evidence, secrets and PDFs never reach the outputs; only aggregates, hashes and booleans.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import pickle
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.real1c import documentation, native_checks, probes, raw_l2
from scripts.real1c.catalog import verify_frozen
from scripts.real1c.com_oracle import Oracle
from scripts.real1c.details_report import build_details
from scripts.real1c.disposition import Observed, decide
from scripts.real1c.lane import SRC_DOWN, SRC_DRIFT, SRC_REAL, Lane
from scripts.real1c.manifest import (
    check_post_run,
    sanitized_summary,
    verify_reference_manifest,
)
from scripts.real1c.report import build_csv, build_report
from scripts.real1c.sanitize import PUBLIC_KINDS, money_literals, public_copy, scan_for_secrets
from scripts.real1c.schema import CASE_RESULT_SCHEMA_VERSION, validate_case_result
from scripts.real1c.stories import UG_NEEDLE, evaluate_story

CATALOG = ROOT / "docs" / "REAL_1C_STORY_CATALOG_818HA.md"
REF_DIR = Path("D:/ERP_MCP_Testbed/1c/reference/scenario_pack")
MANIFEST = REF_DIR / "manifests" / "REAL1C_REFERENCE_MANIFEST.json"
READINESS = REF_DIR / "manifests" / "testbed_readiness.json"
RULES_CSV = REF_DIR / "real_reference" / "month_close_rules.csv"
INVOICES_CSV = REF_DIR / "real_reference" / "invoice_cases_21.csv"
SECRETS_DIR = Path("D:/secrets/erp_mcp")
OUT = ROOT / "reports" / "real1c"
OUT_DEV = ROOT / "reports" / "real1c_dev"
PRIVATE_DIR = Path("D:/ERP_MCP_Testbed/real1c_e2e/private_evidence")  # exact figures stay here, never in git
REPORT_NAME = "REAL_1C_818HA_L2_REPORT"
DETAILS_NAME = "REAL_1C_818HA_L2_TEST_DETAILS"
DATA_AS_OF = "2026-08-31"
GATED_PATHS = ("scripts/real1c", "tests/real1c", "docs/REAL_1C_STORY_CATALOG_818HA.md")


class GateFailure(Exception):
    """A pre-run gate failed; nothing was executed."""


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _o(probe: str, outcome: str, detail: str) -> dict[str, str]:
    return {"probe": probe, "outcome": outcome, "detail": detail}


def _secret_values(lane: Lane) -> list[str]:
    values: list[str] = [str(v) for v in lane.env.secrets.values() if isinstance(v, str) and len(v) >= 6]
    values += [u["password"] for u in lane.env.credentials.get("users", {}).values() if len(u.get("password", "")) >= 6]
    import win32crypt

    for name in ("test_reader_password.dpapi", "admin_1c_clone_password.dpapi"):
        blob = (SECRETS_DIR / name).read_bytes()  # a missing blob must stop the run: the sweep would be weaker
        values.append(win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8"))
    return [v for v in set(values) if v]


# ----------------------------------------------------------------------------------------------- proxy accounting
def _merge_proxy(acc: dict[str, Counter], snap: dict) -> None:
    acc["by_method"].update(snap.get("by_method", {}))
    acc["refused"].update(snap.get("refused_methods", {}))


def _proxy_snapshots(lane: Lane) -> dict:
    return {src: lane.proxy(src).requests() for src in (SRC_REAL, SRC_DRIFT, SRC_DOWN)}


# ----------------------------------------------------------------------------------------------- result builders
class Builder:
    def __init__(self, git_sha: str, manifest_sha: str):
        self.base = {"schema_version": CASE_RESULT_SCHEMA_VERSION, "git_sha": git_sha, "manifest_sha256": manifest_sha}

    def make(self, kind: str, case_id: str, title: str, disposition: str, reason: str, evidence: list[str],
             observations: list[dict], tools: list[str], oracle: str, *, cls: str | None = None,
             owner: str | None = None, supplementary: list[dict] | None = None) -> dict:
        result = {**self.base, "case_id": case_id, "kind": kind, "title": title, "catalogue_class": cls,
                  "disposition": disposition, "reason_code": reason, "evidence_classes": sorted(set(evidence)),
                  "observations": observations, "tools_called": sorted(set(tools)), "oracle": oracle,
                  "finished_at": _now()}
        if owner:
            result["owner_action"] = owner
        if supplementary:
            result["supplementary"] = supplementary
        return result


NATIVE_OWNER = ("Owner/accountant: export the native 1C UI report for this case (runbook "
                "native_reports/NATIVE_REPORT_CAPTURE_RUNBOOK.md); until then the COM comparison is context only.")
SIGNOFF_OWNER = "Accountant: sign off the month-close rule disposition (OACC) and supply the required documents."


def rl2_result(b: Builder, r: dict) -> dict:
    disposition, reason = decide("RR", Observed(oracle_match=r["ok"]))
    return b.make("RL2", r["case_id"], r["title"], disposition, reason, r["evidence_classes"], r["observations"],
                  r["tools_called"], "ONAT raw-L2 (gateway rows vs COM rows; comparison only)", cls="RR")


def nr_results(b: Builder, native: dict[str, dict], cases: dict[str, dict]) -> list[dict]:
    out = []
    for case_id, check in sorted(native.items()):
        verdict = check["verdict"]
        if verdict == "AGREES":
            disposition, reason, owner = "EVIDENCE_REQUIRED", "com_agrees_native_ui_report_required", NATIVE_OWNER
        elif verdict == "DISAGREES":
            disposition, reason, owner = "FINDING", "com_disagrees_with_candidate_assertion", None
        else:
            disposition, reason, owner = "INCONCLUSIVE", "not_computable_by_com", NATIVE_OWNER
        observations = [_o("candidate assertion", "stated", json.dumps(check["assertion"], ensure_ascii=False)),
                        _o("COM recomputation on the clone", verdict, json.dumps(check["observed"], ensure_ascii=False))]
        if check.get("notes"):
            observations.append(_o("note", "info", check["notes"]))
        out.append(b.make("NR", case_id, f"Native reconciliation: {cases.get(case_id, {}).get('subject', case_id)}",
                          disposition, reason, ["NATIVE_COM_QUERY"], observations, [],
                          "ONAT (COM comparison; native UI report pending)", cls="EV", owner=owner))
    return out


def inv_results(b: Builder, rows: list[dict]) -> list[dict]:
    with INVOICES_CSV.open(encoding="utf-8-sig", newline="") as fh:
        cases = list(csv.DictReader(fh))
    out = []
    for row, case in zip(rows, cases, strict=True):
        expect_missing = "not found" in case["result"].lower()
        problems = []
        if row["found"] == expect_missing:
            problems.append("presence differs from the prior observation")
        if row["found"] and not row["amount_match"]:
            problems.append("posted total differs from the PDF total")
        if row["found"] and row["date_match"] is not True:
            problems.append("registration date differs from the recorded one or could not be compared")
        if problems:
            disposition, reason, owner = "FINDING", "com_differs_from_recorded_invoice_state", None
        else:
            disposition, reason, owner = "EVIDENCE_REQUIRED", "com_consistent_native_ui_report_required", NATIVE_OWNER
        observations = [_o("posted purchase document found by incoming number", str(row["found"]),
                           f"documents={row['documents']} amount_match={row['amount_match']} date_match={row['date_match']} "
                           f"registered_in_july={row['pdf_date_in_july_registration']} expected_missing={expect_missing}")]
        if problems:
            observations.append(_o("differences", "FINDING", "; ".join(problems)))
        out.append(b.make("INV", f"INV-{row['index']:02d}", f"Supplier invoice {row['index']} of 21 (hash {row['number_sha8']})",
                          disposition, reason, ["NATIVE_COM_QUERY"], observations, [],
                          "ONAT (COM comparison; PDF and native report pending)", cls="EV", owner=owner))
    return out


def rule_results(b: Builder, ev: dict[str, Any], applicability: dict[str, dict]) -> list[dict]:
    with RULES_CSV.open(encoding="utf-8-sig", newline="") as fh:
        rules = list(csv.DictReader(fh))
    absent = not __import__("re").search(UG_NEEDLE["ST-002"], ev["disc"]["surface"])
    out = []
    for index, rule in enumerate(rules, start=1):
        code = (rule["analytic_account"] or rule["account"]).strip()
        needs_docs = bool((rule["required_documents"] or "").strip())
        if needs_docs:
            disposition, reason = decide("EV", Observed(evidence_required_observed=ev["evtool"]["evidence_required"],
                                                         data_returned=ev["evtool"]["data_returned"]))
            cls = "EV"
        else:
            disposition, reason = decide("UG", Observed(capability_absent_confirmed=absent))
            cls = "UG"
        app = applicability.get(code)
        observations = [_o("rule engine in the product surface", "ABSENT" if absent else "PRESENT",
                           "no month-close / rule-pack capability among public tools, admin routes and CLI commands"),
                        _o("account applicability on the clone",
                           "n/a" if app is None else ("MALFORMED CODE" if app.get("malformed") else
                                                      ("exists" if app["exists_in_chart"] else "not in chart")),
                           "no account code on this rule row" if app is None else
                           ("the rule book carries a malformed account code; it was not queried (owner data defect)"
                            if app.get("malformed") else
                            f"account {code}: in chart={app['exists_in_chart']}, August posting rows={app['august_posting_rows']}")),
                        _o("required documents", "listed" if needs_docs else "none", "documents are accountant-supplied evidence")]
        result = b.make("RULE", f"RULE-{index:03d}", f"Month-close rule row {rule['source_row']} (account {code or '-'})",
                        disposition, reason, ["REPO_STATIC", "NATIVE_COM_QUERY"] + (["GATEWAY_OBSERVATION"] if needs_docs else []),
                        observations, ["external_evidence_manifest"] if needs_docs else [],
                        "OACC accountant (rule not executable by the product)", cls=cls, owner=SIGNOFF_OWNER)
        result.update(documentation.select(result["case_id"], "RULE", cls, (), ev))
        result["queries"] = documentation._queries(ev, f"RULE-code {code}")
        out.append(result)
    return out


def acl_results(b: Builder, acl: dict, real_company: str) -> list[dict]:
    cases = [
        ("ACL-01", "Granted company reaches the profile gate (ACL passed)", acl["allowed_company"], "SEMANTIC_PROFILE_UNVALIDATED"),
        ("ACL-02", "Another company of the same source is denied", acl["other_company_denied"], "AccessDenied"),
        ("ACL-03", "Another principal is denied the real company", acl["other_user_real_company_denied"], "AccessDenied"),
        ("ACL-04", "Principal without grants is denied", acl["no_access_denied"], "AccessDenied"),
        ("ACL-05", "A grant on one source does not widen to another source", acl["cross_source_denied"], "AccessDenied"),
    ]
    out = []
    for case_id, title, row, want in cases:
        ok = row["detail"] == want and not row.get("transport_error")
        disposition, reason = decide("RR", Observed(oracle_match=ok))
        out.append(b.make("ACL", case_id, title, disposition, reason, ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"],
                          [_o("typed audit detail", row["detail"] or "-", f"expected {want}; outcome {row['outcome']}")],
                          ["receivable_balance"], "OACL (audit row)", cls="RR"))
    one_list = acl["company_one_list"]
    listed_ok = (acl["no_access_company_list"] == 0 and isinstance(one_list, list) and len(one_list) == 1
                 and one_list[0] == real_company)
    d, r = decide("RR", Observed(oracle_match=listed_ok))
    out.append(b.make("ACL", "ACL-06", "companies_list shows only granted companies", d, r,
                      ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"],
                      [_o("visible companies", "match" if listed_ok else "differ",
                          f"no-access principal sees {acl['no_access_company_list']}, granted principal sees "
                          f"{len(one_list) if isinstance(one_list, list) else None} (must be exactly the real company)")],
                      ["companies_list"], "OACL", cls="RR"))
    rv = acl.get("revoke_mid_session") or {}
    ok = (rv.get("revoke_http") == 200 and rv.get("before_detail") == "SEMANTIC_PROFILE_UNVALIDATED"
          and rv.get("after_detail") == "AccessDenied" and rv.get("regrant_http") == 201)
    d, r = decide("RR", Observed(oracle_match=ok))
    out.append(b.make("ACL", "ACL-07", "Grant revoked mid-session is denied on the next call", d, r,
                      ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"],
                      [_o("revoke / next call / restore", "ok" if ok else "differ",
                          f"revoke {rv.get('revoke_http')}, next call {rv.get('after_detail')}, restore {rv.get('regrant_http')}")],
                      ["receivable_balance"], "OACL", cls="RR"))
    return out


def sys_results(b: Builder, ev: dict[str, Any]) -> list[dict]:
    out = []

    def add(case_id: str, title: str, ok: bool | None, reason_ok: str, reason_bad: str, obs: list[dict], tools: list[str],
            evidence: list[str] | None = None) -> None:
        d, r = decide("RR", Observed(oracle_match=ok))
        if d == "FINDING":
            r = reason_bad
        elif d == "PASS":
            r = reason_ok
        out.append(b.make("SYS", case_id, title, d, r, evidence or ["GATEWAY_OBSERVATION"], obs, tools, "OFIX / observation", cls="RR"))

    head = ev["head"]
    add("SYS-01", "Health check by HEAD $metadata works against the real 1C publication", head["status"] == 200,
        "head_supported", "head_metadata_rejected_by_1c",
        [_o("HEAD $metadata on the real publication (loopback proxy in passthrough mode)", str(head["status"]),
            "proxy confirmed passthrough mode; 405 means the real 1C refuses HEAD. The lane keeps a HEAD-to-GET shim on every "
            "proxy so the gateway health check can run")], [])
    m = ev["malformed"]
    add("SYS-02", "Every rejected call still leaves one audit row", not m["unaudited"], "all_calls_audited",
        "malformed_calls_not_audited",
        [_o(c["case"], "audited" if c["audit_row"] else "NO AUDIT ROW", f"tool error={c['is_error']} detail={c['detail']}")
         for c in m["cases"]], ["receivable_aging", "onec_read", "receivable_balance"], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"])
    ident = ev["identity"]
    add("SYS-03", "Product reports the privilege of its upstream 1C identity", ident["product_reports_identity_privilege"],
        "identity_privilege_reported", "identity_privilege_not_reported",
        [_o("capabilities / health / status payloads", "reported" if ident["product_reports_identity_privilege"] else "NOT reported",
            f"reader COM write probe on the probe clone: {ident['reader_com_write_probe']}")], ["onec_capabilities", "source_health", "system_status"])
    port = ev["portfolio"]
    add("SYS-04", "companies_list supports paging for large portfolios", port["paging_parameters_supported"],
        "paging_supported", "no_paging_arguments",
        [_o("150-company portfolio", "single response", f"{port['visible_to_one'] + port['visible_to_two']} rows in {port['list_seconds']}s, "
            "no paging arguments on the tool")], ["companies_list"])
    lit = ev["literal"]
    typed = lit["http"] in (400, 422) and lit.get("error_code") == "INVALID_REQUEST"
    safe = lit["http"] >= 400 and not lit["row_created"] and not lit["echoes_literal"]
    add("SYS-05", "A literal password instead of a secret reference is refused with a typed validation error",
        typed and safe, "literal_secret_refused_typed",
        "literal_secret_refused_untyped" if safe else "literal_secret_accepted",
        [_o("POST /admin/v1/sources with a literal credential value in the reference field",
            f"HTTP {lit['http']} {lit.get('error_code')}",
            f"row created={lit['row_created']}, echoed={lit['echoes_literal']}; "
            + ("typed validation refusal" if typed else "refused safely but NOT as a typed validation error (a dependency failure, not input validation)"))],
        [], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"])
    adm = ev["admin"]
    gets = {k: v for k, v in adm.items() if k.startswith(("GET", "effective"))}
    add("SYS-06", "Admin Control Center lifecycle endpoints answer for the real source", all(v == 200 for v in gets.values()),
        "admin_endpoints_ok", "admin_endpoint_failed",
        [_o(k, str(v), "platform admin session") for k, v in sorted(gets.items())], [], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"])
    val = adm.get("profile validate without native evidence") or {}
    refused = (adm.get("profile draft create") == 201 and val.get("http") == 400 and val.get("error_code") == "INVALID_REQUEST"
               and adm.get("profile status after refused validation") == "DRAFT")
    add("SYS-07", "Profile validation without genuine native evidence is refused", refused,
        "validation_refused", "validated_without_native_evidence",
        [_o("draft created", str(adm.get("profile draft create")), "bp30 preset for the reference source"),
         _o("validate with three pending native cases", f"HTTP {val.get('http')} {val.get('error_code')}",
            "the API answers a generic INVALID_REQUEST; the reason (fewer than ten cases, status not PASS) is not typed"),
         _o("profile status afterwards", str(adm.get("profile status after refused validation")), "must stay DRAFT")],
        [], ["GATEWAY_OBSERVATION", "CONTROL_PLANE_ROWS"])
    return out


def head_probe(lane: Lane) -> dict:
    """HEAD $metadata straight through the lane proxy (passthrough) with the reader identity, in memory only."""
    import httpx

    from scripts.real1c.lane_setup import _reader_credentials

    user, password = _reader_credentials()
    ctl = lane.proxy(SRC_REAL)
    ctl.mode("passthrough")
    try:
        r = httpx.head("http://127.0.0.1:8191/erp_mcp_ref/odata/standard.odata/$metadata", auth=(user, password),
                       timeout=60, trust_env=False)
        status = r.status_code
    finally:
        ctl.mode("head_compat")
    return {"status": status}


# ----------------------------------------------------------------------------------------------- the run
async def collect(lane: Lane, oracle: Oracle, secrets: list[str]) -> dict[str, Any]:
    ev: dict[str, Any] = {}
    steps = [("head", lambda: asyncio.to_thread(head_probe, lane)), ("disc", lambda: probes.probe_discovery(lane)),
             ("gate", lambda: probes.probe_semantic_gate(lane)), ("evtool", lambda: probes.probe_evidence_tool(lane))]
    for name, fn in steps:
        t0 = time.monotonic()
        lane.probe_label = name
        ev[name] = await fn()
        print(f"[{name}] {time.monotonic() - t0:.1f}s", flush=True)
    acc = {"by_method": Counter(), "refused": Counter()}
    _merge_proxy(acc, lane.proxy(SRC_REAL).requests())
    lane.probe_label = "write"
    ev["write"] = await probes.probe_write_surface(lane, ev["disc"])
    for name, fn in (("acl", lambda: probes.probe_acl(lane)), ("expiring", lambda: probes.probe_expiring_grant(lane)),
                     ("admin", lambda: probes.probe_admin_lifecycle(lane)), ("literal", lambda: probes.probe_literal_secret(lane)),
                     ("identity", lambda: probes.probe_identity(lane)), ("malformed", lambda: probes.probe_malformed_audit(lane)),
                     ("portfolio", lambda: probes.probe_portfolio(lane)), ("drift", lambda: probes.probe_drift(lane)),
                     ("outage", lambda: probes.probe_outage(lane))):
        t0 = time.monotonic()
        lane.probe_label = name
        ev[name] = await fn()
        print(f"[{name}] {time.monotonic() - t0:.1f}s", flush=True)
    t0 = time.monotonic()
    ev["rl2"] = []
    for case in raw_l2.RL2_CASES:
        lane.probe_label = "rl2:" + case.__name__[:6].upper().replace("_", "-")
        ev["rl2"].append(await case(lane, oracle))
    lane.probe_label = "sweep"
    print(f"[rl2] {time.monotonic() - t0:.1f}s", flush=True)
    t0 = time.monotonic()
    ev["native"] = native_checks.run_all(oracle)
    ev["invoices"] = native_checks.invoice_rows(oracle)
    with RULES_CSV.open(encoding="utf-8-sig", newline="") as fh:
        rules = list(csv.DictReader(fh))
    codes = {(r["analytic_account"] or r["account"]).strip() for r in rules} - {""}
    ev["rule_applicability"] = native_checks.rule_applicability(oracle, codes)
    print(f"[native/invoices/rules] {time.monotonic() - t0:.1f}s", flush=True)
    for snap in _proxy_snapshots(lane).values():
        _merge_proxy(acc, snap)
    ev["proxy_acc"] = {"methods": sorted(acc["by_method"]), "by_method": dict(acc["by_method"]), "refused": dict(acc["refused"])}
    ev["call_log"] = list(lane.call_log)
    ev["query_log"] = list(oracle.query_log)
    ev["audit"] = await probes.probe_audit(lane)
    ev["secret"] = await probes.probe_secret_sweep(lane, secrets, [])
    return ev


def zero_write(pre: dict, post: dict, ev: dict) -> dict:
    acc = ev["proxy_acc"]
    write_seen = bool(set(acc["methods"]) - {"GET", "HEAD"}) or bool(acc["refused"])
    return {"pre": pre["content_fingerprint_sha256"], "post": post["content_fingerprint_sha256"],
            "fingerprint_equal": pre["content_fingerprint_sha256"] == post["content_fingerprint_sha256"]
            and pre["metadata_fingerprint"] == post["metadata_fingerprint"],
            "table_count": post["table_count"], "total_rows": post["total_rows"],
            "upstream_write_seen": write_seen, "methods": acc["by_method"]}


def related_index(results: list[dict]) -> dict[str, dict]:
    idx = {}
    for r in results:
        verdict = {"PASS": "oracle match", "FINDING": "differs"}.get(r["disposition"], r["disposition"])
        idx[r["case_id"]] = {"verdict": verdict, "title": r["title"]}
    return idx


def assemble(ev: dict, catalog, b: Builder) -> list[dict]:
    pre_supp = [rl2_result(b, r) for r in ev["rl2"]]
    with (REF_DIR / "real_reference" / "native_reconciliation_cases.csv").open(encoding="utf-8-sig", newline="") as fh:
        nr_meta = {r["case_id"]: r for r in csv.DictReader(fh)}
    supp = pre_supp + nr_results(b, ev["native"], nr_meta) + inv_results(b, ev["invoices"])
    supp += rule_results(b, ev, ev["rule_applicability"]) + acl_results(b, ev["acl"], ev["real_company"]) + sys_results(b, ev)
    ev["related"] = related_index(supp)
    base = {k: b.base[k] for k in ("schema_version", "git_sha", "manifest_sha256")}
    stories = []
    for story in catalog.stories:
        result = evaluate_story(story, ev, {**base, "finished_at": _now()})
        result.update(documentation.select(story.id, story.kind, story.catalogue_class, story.tools, ev))
        result.update({"question": story.title, "expected": story.expected, "negative": story.negative})
        stories.append(result)
    for result in supp:
        if result["kind"] != "RULE":
            result.update(documentation.select(result["case_id"], result["kind"], result["catalogue_class"], (), ev))
    return stories + supp


def sweep_outputs(texts: dict[str, str], secrets: list[str]) -> list[dict]:
    hits = []
    for name, text in texts.items():
        for secret in secrets:
            if secret in text:
                hits.append({"where": name, "kind": "literal_secret"})
        hits += [{"where": name, "kind": p} for p in scan_for_secrets(text)]
    return hits


DETAILS_LINK = {"en": "Every test in detail: request sent, answer received, why it is correct",
                "ru": "Каждый тест подробно: отправленный запрос, полученный ответ, почему это правильно"}
ACCEPTANCE = {
    "en": ("REAL 1C 818HA L2 ACCEPTANCE", "Gates", "Verdict", "Open items", "Owner actions"),
    "ru": ("REAL 1C 818HA L2 ACCEPTANCE", "Ворота", "Вердикт", "Открытые пункты", "Действия владельца"),
}


def acceptance_html(lang: str, summary: dict, details_href: str = "") -> str:
    import html

    title, gates, verdict, opens, _owner = ACCEPTANCE[lang]
    rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in summary["gates"].items())
    items = "".join(f"<li>{html.escape(x[lang])}</li>" for x in summary["open_items"])
    return (f'<section id="acceptance"><h2>{title}</h2><h3>{gates}</h3><table><tbody>{rows}</tbody></table>'
            f"<h3>{verdict}</h3><p>{html.escape(summary['verdict'][lang])}</p><h3>{opens}</h3><ul>{items}</ul>"
            + (f'<p><a href="{html.escape(details_href)}">{DETAILS_LINK[lang]}</a></p>' if details_href else "") + "</section>")


def build_summary(results: list[dict], ev: dict, gates: dict, git_sha: str, readiness: str) -> dict:
    stories = [r for r in results if r["kind"] in ("ST", "AX")]
    by_disp = Counter(r["disposition"] for r in stories)
    supp = Counter((r["kind"], r["disposition"]) for r in results if r["kind"] not in ("ST", "AX"))
    pass_count = by_disp.get("PASS", 0)
    findings = [r["case_id"] for r in results if r["disposition"] == "FINDING"]
    verdict_en = (f"Read-only lane executed against the 818HA reference clone at {git_sha[:12]}: {len(stories)} catalogue stories, "
                  f"{pass_count} PASS, {by_disp.get('SEMANTIC_PROFILE_UNVALIDATED', 0)} blocked by the semantic profile gate, "
                  f"{len(findings)} FINDING items across all cases. Business acceptance stays PENDING and production stays NO-GO: "
                  "no native 1C UI report has validated a semantic profile.")
    verdict_ru = (f"Линия только для чтения выполнена на эталонном клоне 818HA на {git_sha[:12]}: {len(stories)} историй каталога, "
                  f"{pass_count} PASS, {by_disp.get('SEMANTIC_PROFILE_UNVALIDATED', 0)} остановлены воротами семантического профиля, "
                  f"{len(findings)} FINDING по всем кейсам. Бизнес-приёмка остаётся PENDING, прод остаётся NO-GO: "
                  "ни один нативный отчёт интерфейса 1C ещё не валидировал семантический профиль.")
    return {
        "gates": gates, "readiness_verdict": readiness, "story_dispositions": dict(by_disp),
        "supplementary": {f"{k}:{d}": n for (k, d), n in sorted(supp.items())}, "findings": findings,
        "verdict": {"en": verdict_en, "ru": verdict_ru},
        "open_items": [
            {"en": "At least ten genuine native 1C UI reports are required before any semantic profile can be validated.",
             "ru": "Нужно не менее десяти настоящих нативных отчётов интерфейса 1C, иначе семантический профиль не валидировать."},
            {"en": "Manual business acceptance is PENDING; production is NO-GO.",
             "ru": "Ручная бизнес-приёмка PENDING; прод NO-GO."},
            {"en": "Hosted CI on the exact head is PENDING (recorded in the PR body, not in tracked docs).",
             "ru": "Hosted CI на точном head в статусе PENDING (фиксируется в теле PR, не в отслеживаемых доках)."},
        ],
    }


def functional_tester_md(summary: dict, results: list[dict], git_sha: str, manifest_sha: str, generated_at: str) -> str:
    lines = ["# Functional Tester report REAL-1C-818HA", "",
             f"- Git SHA (code under test): `{git_sha}`", f"- Reference manifest sha256: `{manifest_sha}`",
             f"- Generated at: {generated_at}", f"- Data as of: {DATA_AS_OF}", f"- Testbed readiness verdict: {summary['readiness_verdict']}", "",
             "## Story dispositions (90 ST + 40 AX)", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(summary["story_dispositions"].items())]
    lines += ["", "## Supplementary results", ""] + [f"- {k}: {v}" for k, v in summary["supplementary"].items()]
    lines += ["", "## FINDING cases", ""] + ([f"- {i}" for i in summary["findings"]] or ["- none"])
    lines += ["", "## REAL 1C 818HA L2 ACCEPTANCE", ""]
    lines += [f"- {k}: {v}" for k, v in summary["gates"].items()]
    lines += ["", summary["verdict"]["en"], "", "Open items:"] + [f"- {x['en']}" for x in summary["open_items"]]
    return "\n".join(lines) + "\n"


async def main_async(dev: bool, save_ev: str | None = None, load_ev: str | None = None) -> int:
    t_start = time.monotonic()
    gates: dict[str, str] = {}
    catalog = verify_frozen(CATALOG)
    gates["frozen catalogue sha256"] = f"OK {catalog.sha256[:16]}…"
    git_sha = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--", *GATED_PATHS)
    if dirty and not dev:
        raise GateFailure("gate mode requires a committed lane tree; uncommitted changes:\n" + dirty)
    gates["code tree"] = "committed" if not dirty else "DIRTY (dev mode)"
    manifest = verify_reference_manifest(MANIFEST)
    manifest_sha = manifest["manifest_sha256"]
    gates["reference manifest hash"] = f"OK {manifest_sha[:16]}…"
    readiness = json.loads(READINESS.read_text(encoding="utf-8")).get("verdict", "UNKNOWN")
    if readiness != "READY_FOR_SCENARIO_EXECUTION":
        raise GateFailure(f"testbed readiness is {readiness}")
    gates["testbed readiness"] = readiness
    oracle = Oracle()
    pre = oracle.fingerprint()
    check_post_run(manifest["pre_run_fingerprint"], {"sha256": pre["content_fingerprint_sha256"]})
    if pre["metadata_fingerprint"] != manifest["metadata_fingerprint"]:
        raise GateFailure("live metadata fingerprint differs from the manifest")
    gates["pre-run COM fingerprint equals manifest"] = f"OK {pre['content_fingerprint_sha256'][:16]}… ({pre['table_count']} tables, {pre['total_rows']} rows)"
    lane = await Lane.open()
    try:
        for src in (SRC_REAL, SRC_DRIFT, SRC_DOWN):
            lane.proxy(src).reset()
        status = await lane.call("auditor", "system_status", {})
        if status["is_error"]:
            raise GateFailure("gateway system_status failed")
        gates["gateway + sidecar + proxies"] = "reachable"
        secrets = [*_secret_values(lane), probes.LITERAL_CANARY]
        canary_json = json.dumps({"password": probes.LITERAL_CANARY})
        if not sweep_outputs({"selftest": canary_json}, secrets):
            raise GateFailure("secret sweep instrument is broken: a planted canary was not detected")
        ev_real_company = lane.real_company
        if dev and load_ev:  # dev-only replay of a previous collection (never acceptance evidence)
            ev, post = pickle.loads(Path(load_ev).read_bytes())
        else:
            ev = await collect(lane, oracle, secrets)
            post = oracle.fingerprint()
            if dev and save_ev:
                Path(save_ev).write_bytes(pickle.dumps((ev, post)))
        check_post_run({"sha256": pre["content_fingerprint_sha256"]}, {"sha256": post["content_fingerprint_sha256"]})
        gates["post-run COM fingerprint equals pre-run"] = "OK identical"
        ev["real_company"] = ev_real_company
        ev["zero_write"] = zero_write(pre, post, ev)
        gates["upstream methods seen by the lane proxies"] = f"{ev['zero_write']['methods']} (no write verb)" if not ev["zero_write"]["upstream_write_seen"] else "WRITE SEEN"
        builder = Builder(git_sha, manifest_sha)
        results = assemble(ev, catalog, builder)
        # two passes: the second one records the sweep of the generated outputs inside ST-083
        for _ in range(2):
            texts = {"case_results.json": json.dumps(results, ensure_ascii=False, indent=1), "case_results.csv": build_csv(
                [r for r in results if r["kind"] in ("ST", "AX")], catalog)}
            out_hits = sweep_outputs(texts, secrets)
            ev["secret"] = {**ev["secret"], "hits": ev["secret"]["hits"] + out_hits,
                            "sources_scanned": sorted(set(ev["secret"]["sources_scanned"]) | {"generated case_results.json/csv"})}
            results = assemble(ev, catalog, builder)
        bad = [(r["case_id"], e) for r in results for e in validate_case_result(r)]
        if bad:
            raise GateFailure(f"case results violate the schema: {bad[:5]}")
        gates["case result schema"] = f"OK {len(results)} results"
        private_results = results
        private_amounts = set()
        for r in private_results:
            if r["kind"] in PUBLIC_KINDS:
                private_amounts |= money_literals(json.dumps(r, ensure_ascii=False))
        results = [public_copy(r) if r["kind"] in PUBLIC_KINDS else r for r in private_results]
        bad = [(r["case_id"], e) for r in results for e in validate_case_result(r)]
        if bad:
            raise GateFailure(f"public case results violate the schema: {bad[:5]}")
        gates["public report view"] = f"exact monetary values of NR/RL2/INV removed ({len(private_amounts)} figures kept privately)"
        summary = build_summary(results, ev, gates, git_sha, readiness)
        generated_at = _now()
        mani = sanitized_summary(manifest)
        outputs: dict[str, str] = {}
        for lang, suffix in (("en", ""), ("ru", ".ru")):
            page = build_report([r for r in results], catalog, mani, git_sha, DATA_AS_OF, generated_at, lang=lang)
            details_name = f"{DETAILS_NAME}{suffix}.html"
            outputs[f"{REPORT_NAME}{suffix}.html"] = page.replace(
                "</main>", acceptance_html(lang, summary, details_name) + "</main>", 1)
            outputs[details_name] = build_details(results, catalog, git_sha, generated_at, lang=lang,
                                                  summary_href=f"{REPORT_NAME}{suffix}.html")
        outputs["case_results.json"] = json.dumps(results, ensure_ascii=False, indent=1)
        outputs["case_results.csv"] = build_csv([r for r in results if r["kind"] in ("ST", "AX")], catalog)
        outputs["summary.json"] = json.dumps({**summary, "mode": "DEV_REPLAY" if (dev and load_ev) else ("DEV" if dev else "GATE"),
                                               "git_sha": git_sha, "manifest_sha256": manifest_sha,
                                               "generated_at": generated_at, "elapsed_seconds": round(time.monotonic() - t_start)},
                                              ensure_ascii=False, indent=1)
        final_hits = sweep_outputs(outputs, [*secrets, *sorted(private_amounts)])
        if final_hits:
            raise GateFailure(f"secret sweep over generated outputs found {len(final_hits)} hit(s) {final_hits}; nothing written")
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
        (PRIVATE_DIR / f"case_results.private.{git_sha[:12]}.json").write_text(
            json.dumps(private_results, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        out_dir = OUT_DEV if dev else OUT
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in outputs.items():
            (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
        ft = functional_tester_md(summary, results, git_sha, manifest_sha, generated_at)
        if sweep_outputs({"ft": ft}, [*secrets, *sorted(private_amounts)]):
            raise GateFailure("secret sweep over the functional tester report failed")
        ft_path = (out_dir if dev else ROOT / "reports") / "FUNCTIONAL_TESTER_REAL-1C-818HA.md"
        ft_path.write_text(ft, encoding="utf-8", newline="\n")
        print(json.dumps({k: summary[k] for k in ("story_dispositions", "supplementary", "findings")}, ensure_ascii=False, indent=1))
        return 3 if ev["zero_write"]["upstream_write_seen"] or not ev["zero_write"]["fingerprint_equal"] else 0
    finally:
        await lane.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true", help="allow an uncommitted lane tree (results are not acceptance evidence)")
    parser.add_argument("--save-ev", help="dev only: pickle the collected observations")
    parser.add_argument("--load-ev", help="dev only: replay pickled observations instead of collecting")
    args = parser.parse_args()
    if args.load_ev and not args.dev:
        parser.error("--load-ev replays cached observations and is allowed only together with --dev")
    try:
        return asyncio.run(main_async(args.dev, args.save_ev, args.load_ev))
    except GateFailure as exc:
        print(f"GATE FAILURE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
