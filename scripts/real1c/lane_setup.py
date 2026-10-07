"""Control-plane setup of the real-1C lane, driven through the Admin Control Center API (/admin/v1).

Flow: probe -> register source -> capability refresh (+ drift acknowledge of first observation) -> company rows
(real organisation discovered from LIVE data + one clearly synthetic second company) -> platform roles -> grants.
The entity allowlist is not part of the Admin API; it is set afterwards by the operator CLI (source-upsert).
Only ids, statuses and counts are printed. Secrets are referenced by NAME (secret refs) and never read here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import requests

from scripts.real1c.gateway_client import AdminSession, LaneEnv

ROOT = Path(__file__).resolve().parents[2]
SOURCE_REAL = "onec-818ha-reference"
SOURCE_DRIFT = "onec-818ha-drift"
SOURCE_DOWN = "onec-818ha-down"
PROXY_REAL, PROXY_DRIFT, PROXY_DOWN = 8191, 8192, 8193
ODATA_PATH = "/erp_mcp_ref/odata/standard.odata"
SECRET_USER, SECRET_PASSWORD = "ERP_MCP_818HA_USER", "ERP_MCP_818HA_PASSWORD"
REASON = "real-1C 818HA lane"
SYNTHETIC_COMPANY_REF = "00000000-0000-4000-8000-00000000d00d"

ALLOW_PATTERNS = [
    "Catalog_Организации*", "Catalog_Контрагенты*", "Catalog_Валюты*", "Catalog_Банки",
    "Catalog_БанковскиеСчета*", "Catalog_ДоговорыКонтрагентов*", "Catalog_Номенклатура*",
    "Catalog_Склады*", "ChartOfAccounts_Хозрасчетный*", "AccountingRegister_Хозрасчетный*",
    "Document_РеализацияТоваровУслуг*", "Document_ПоступлениеТоваровУслуг*",
    "AccumulationRegister_ТоварыНаСкладах*", "AccumulationRegister_ВзаиморасчетыСКонтрагентами*",
]
DENY_PATTERNS = ["*Парол*", "*Password*", "*Secret*", "*Токен*"]


def url_for(port: int) -> str:
    return f"http://127.0.0.1:{port}{ODATA_PATH}"


def discover_real_organisations(odata_user: str, odata_password: str) -> list[dict]:
    """Read the organisation catalog from the LIVE publication (reader identity, bounded)."""
    r = requests.get(url_for(PROXY_REAL) + "/Catalog_Организации", params={"$format": "json", "$top": "50"},
                     auth=(odata_user, odata_password), timeout=120)
    r.raise_for_status()
    rows = r.json().get("value", [])
    return [{"ref": row["Ref_Key"], "name_len": len(row.get("Description", "")),
             "deletion_mark": bool(row.get("DeletionMark"))} for row in rows]


def cli(env: LaneEnv, *args: str) -> subprocess.CompletedProcess:
    import os

    proc_env = dict(os.environ)
    proc_env.update({"BAG_ADMIN_DATABASE_URL": env.dsn("admin"), "BAG_DATABASE_URL": env.dsn("app"),
                     "BAG_ENVIRONMENT": "test", "PYTHONPATH": str(ROOT / "src") + ";" + str(ROOT)})
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "admin.py"), *args], cwd=ROOT, env=proc_env,
                          capture_output=True, text=True, timeout=120, check=False)


def post_ok(label: str, response, expect: int) -> dict:
    ok = response.status_code == expect
    body = {}
    try:
        body = response.json()
    except ValueError:
        body = {}
    print(f"[{'ok' if ok else 'FAIL'}] {label}: HTTP {response.status_code}"
          + ("" if ok else f" {response.text[:200]}"))
    if not ok:
        raise SystemExit(f"setup step failed: {label}")
    return body


def main(odata_user: str, odata_password: str) -> dict:
    env = LaneEnv.load()
    orgs = discover_real_organisations(odata_user, odata_password)
    print(f"live organisations discovered: {len(orgs)}")
    if not orgs:
        raise SystemExit("no organisation discovered from live data")
    real_org = orgs[0]["ref"]
    assert re.fullmatch(r"[0-9a-f-]{36}", real_org)

    pa = AdminSession(env, "platform_admin")
    state: dict = {"orgs": len(orgs)}

    for sid, port, label in ((SOURCE_REAL, PROXY_REAL, "818HA reference (read-only)"),
                             (SOURCE_DRIFT, PROXY_DRIFT, "818HA lane drift/slow source"),
                             (SOURCE_DOWN, PROXY_DOWN, "818HA lane outage source")):
        probe = post_ok(f"probe {sid}", pa.post("/admin/v1/source-probes", {
            "base_url": url_for(port), "username_secret_ref": SECRET_USER, "password_secret_ref": SECRET_PASSWORD,
            "display_name": label, "platform_version_hint": "8.3.27.2342", "reason": REASON}), 200)
        state[f"probe_{sid}"] = {"entity_set_count": probe["capabilities"]["entity_set_count"],
                                 "compatibility": probe["capabilities"]["compatibility_status"]}
        post_ok(f"register {sid}", pa.post("/admin/v1/sources", {
            "source_id": sid, "display_name": label, "base_url": url_for(port),
            "username_secret_ref": SECRET_USER, "password_secret_ref": SECRET_PASSWORD,
            "tags": ["real-reference", "read-only"], "reason": f"{REASON}: register {sid}"}), 201)
        refreshed = post_ok(f"capability refresh {sid}", pa.post(
            f"/admin/v1/sources/{sid}/capability-refresh", {"reason": f"{REASON}: first metadata observation"}), 200)
        state[f"fingerprint_{sid}"] = refreshed.get("metadata_fingerprint")

    # operator CLI sets the narrow entity allowlist (not part of the Admin API)
    for sid, port, label in ((SOURCE_REAL, PROXY_REAL, "818HA reference (read-only)"),
                             (SOURCE_DRIFT, PROXY_DRIFT, "818HA lane drift/slow source"),
                             (SOURCE_DOWN, PROXY_DOWN, "818HA lane outage source")):
        done = cli(env, "source-upsert", "--source-id", sid, "--display-name", label, "--base-url", url_for(port),
                   "--username-secret", SECRET_USER, "--password-secret", SECRET_PASSWORD,
                   "--tags", "real-reference", "read-only", "--platform-version-hint", "8.3.27.2342",
                   "--allow", *ALLOW_PATTERNS, "--deny", *DENY_PATTERNS)
        print(f"[{'ok' if done.returncode == 0 else 'FAIL'}] CLI allowlist {sid}: rc={done.returncode} "
              f"{(done.stderr or done.stdout)[:160].strip()}")
        if done.returncode != 0:
            raise SystemExit("allowlist step failed")

    real_company = post_ok("register real company", pa.post("/admin/v1/companies", {
        "source_id": SOURCE_REAL, "external_ref": real_org, "display_name": "818 HA SRL (real reference org)",
        "is_default": True, "reason": f"{REASON}: real organisation discovered from live data"}), 201)
    synth_company = post_ok("register synthetic second company", pa.post("/admin/v1/companies", {
        "source_id": SOURCE_REAL, "external_ref": SYNTHETIC_COMPANY_REF,
        "display_name": "SYNTHETIC second company (not in 1C)", "is_default": False,
        "reason": f"{REASON}: cross-company isolation fixture, synthetic"}), 201)
    state["company_real_id"] = real_company["id"]
    state["company_synthetic_id"] = synth_company["id"]

    su = AdminSession(env, "platform_admin", step_up=True)
    sub = lambda user: env.raw["identities"][user]["sub"]
    bindings = {}
    for user, role in (("source_admin", "SOURCE_ADMIN"), ("access_admin", "ACCESS_ADMIN"),
                       ("profile_admin", "PROFILE_ADMIN"), ("auditor", "AUDITOR")):
        body = post_ok(f"bind {role}", su.post("/admin/v1/platform-role-bindings", {
            "principal_kind": "subject", "principal_id": sub(user), "role_name": role, "source_id": SOURCE_REAL,
            "reason": f"{REASON}: bind {role}"}), 201)
        bindings[role] = body["id"]
    state["bindings"] = bindings

    aa = AdminSession(env, "access_admin")
    g1 = post_ok("grant user_company_one -> real company", aa.post("/admin/v1/grants", {
        "principal_kind": "subject", "principal_id": sub("user_company_one"), "source_id": SOURCE_REAL,
        "company_id": real_company["id"], "effect": "allow", "reason": f"{REASON}: grant real company"}), 201)
    g2 = post_ok("grant user_company_two -> synthetic company", aa.post("/admin/v1/grants", {
        "principal_kind": "subject", "principal_id": sub("user_company_two"), "source_id": SOURCE_REAL,
        "company_id": synth_company["id"], "effect": "allow", "reason": f"{REASON}: grant synthetic company"}), 201)
    state["grants"] = {"user_company_one": g1["id"], "user_company_two": g2["id"]}
    for s in (pa, su, aa):
        s.close()
    return state


def _reader_credentials() -> tuple[str, str]:
    """Reader identity for live discovery: DPAPI CurrentUser blob decrypted in-process only."""
    import win32crypt

    blob = (Path("D:/secrets/erp_mcp") / "test_reader_password.dpapi").read_bytes()
    return "ERP_MCP_TEST_READER", win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8")


if __name__ == "__main__":
    print(json.dumps(main(*_reader_credentials()), ensure_ascii=False)[:1500])
