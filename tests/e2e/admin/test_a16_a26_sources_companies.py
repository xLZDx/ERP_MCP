"""A16-A26: source probing and registration, egress policy, secrets, company registration.

All registrations happen through /admin/ as PLATFORM_ADMIN. The egress rows prove "no outbound
request" with local recorder servers: a recorder that receives nothing is evidence that the
gateway refused before connecting.
"""

from __future__ import annotations

import uuid

import pytest
from admin_support import (
    JWT_LIKE,
    LOG_DIR,
    TRANSCRIPT,
    AsgiServer,
    expect,
    fake1c_replaced_by,
    find_leaks,
    free_port,
    recorder_app,
    secret_values,
    unique,
)

pytestmark = [pytest.mark.admin]


def _source_body(env, **overrides):
    body = {"source_id": unique("e2e-src"), "display_name": "E2E candidate source",
            "base_url": env.fake1c_url, "username_secret_ref": "FAKE1C_USERNAME",
            "password_secret_ref": "FAKE1C_PASSWORD", "tags": [], "reason": "A-suite source row"}
    body.update(overrides)
    return body


def _probe_body(env, **overrides):
    body = {"base_url": env.fake1c_url, "username_secret_ref": "FAKE1C_USERNAME",
            "password_secret_ref": "FAKE1C_PASSWORD"}
    body.update(overrides)
    return body


def _sanitized(resp, env, extra_forbidden=()):
    """An error body must be exactly {"error": CODE} and carry no secret or credential."""
    body = resp.body
    assert isinstance(body, dict) and set(body) == {"error"}, resp.describe()
    leaks = find_leaks(resp.text, secret_values(env))
    assert not leaks, f"secret values leaked in error response: {leaks}"
    for marker in extra_forbidden:
        assert marker not in resp.text, f"{marker!r} echoed in {resp.describe()}"


# --------------------------------------------------------------------------------------- A16
def test_A16_probe_returns_safe_capability_summary(e2e_env, world):
    resp = expect(world.pa.post("/admin/v1/source-probes", _probe_body(e2e_env)), 200, "A16 probe")
    body = resp.body
    assert body["health"]["ok"] is True and body["health"]["status_code"] == 200
    assert body["egress"]["host"] == "127.0.0.1" and body["egress"]["port"] == 18766
    caps = body["capabilities"]
    assert caps["metadata_fingerprint"] and caps["metadata_supported"] is True
    assert caps["source_id"] == "candidate" and caps["register_capabilities"] == {}
    assert set(caps["evidence"].values()) <= {"ok", "unavailable"}
    assert not find_leaks(resp.text, secret_values(e2e_env)), "credentials in probe response"
    assert "@" not in resp.text, "URL userinfo or contact data in probe response"


def test_A16_probe_is_audited(e2e_env, world, evidence):
    """Contract evidence for A16 is 'audit': the probe request must leave an admin audit row."""
    resp = expect(world.pa.post("/admin/v1/source-probes", _probe_body(e2e_env)), 200, "A16")
    assert evidence.admin_events(resp), f"no admin audit row for probe {resp.request_id}"


# --------------------------------------------------------------------------------------- A17
def test_A17_register_fake1c_source_without_storing_secrets(e2e_env, world, evidence):
    step = world.ensure("source")
    resp = expect(step.resp, 201, "A17 register")
    body = resp.body
    assert body["source_id"] == world.source_id and body["read_only"] is True
    assert body["row_version"] == 1 and body["base_url"] == e2e_env.fake1c_url
    assert not find_leaks(resp.text, secret_values(e2e_env)), "plain secret in register response"
    row = evidence.one("SELECT * FROM bag.sources WHERE source_id=$1", world.source_id)
    assert row["username_secret_ref"] == "FAKE1C_USERNAME"
    assert row["password_secret_ref"] == "FAKE1C_PASSWORD"
    assert row["read_only"] is True and row["enabled"] is True
    dumped = str(row)
    assert not find_leaks(dumped, secret_values(e2e_env)), "plain secret stored in bag.sources"
    audit = evidence.admin_events(resp)
    assert len(audit) == 1 and audit[0]["action"] == "source.create"
    assert audit[0]["outcome"] == "success" and audit[0]["source_id"] == world.source_id
    detail = expect(world.pa.get(f"/admin/v1/sources/{world.source_id}"), 200, "A17 detail")
    assert not find_leaks(detail.text, secret_values(e2e_env))


# --------------------------------------------------------------------------------------- A18
@pytest.mark.parametrize("userinfo", ["user:p4ssw0rd-e2e-marker@", "user@"])
def test_A18_url_with_userinfo_rejected(e2e_env, world, evidence, userinfo):
    world.need("source")
    url = e2e_env.fake1c_url.replace("http://", f"http://{userinfo}", 1)
    before = evidence.count("sources")
    probe = world.pa.post("/admin/v1/source-probes", _probe_body(e2e_env, base_url=url))
    register = world.pa.post("/admin/v1/sources", _source_body(e2e_env, base_url=url))
    for resp in (probe, register):
        assert resp.status in (400, 403), resp.describe()
        _sanitized(resp, e2e_env, extra_forbidden=("p4ssw0rd-e2e-marker",))
    assert evidence.count("sources") == before, "source with userinfo URL was stored"


# --------------------------------------------------------------------------------------- A19
def test_A19_disallowed_hosts_rejected_without_egress(e2e_env, world, evidence):
    world.need("source")
    hits: list[tuple[str, str]] = []
    port = free_port()
    before = evidence.count("sources")
    targets = [
        f"http://127.0.0.1:{port}/odata/standard.odata",  # right host, port not allowlisted
        "http://localhost:18766/odata/standard.odata",  # hostname not allowlisted
        "http://169.254.169.254/latest/meta-data",
        "http://e2e-disallowed.invalid/odata/standard.odata",
        "ftp://127.0.0.1:18766/odata/standard.odata",
    ]
    with AsgiServer(recorder_app(hits), port):
        for url in targets:
            probe = world.pa.post("/admin/v1/source-probes", _probe_body(e2e_env, base_url=url))
            register = world.pa.post("/admin/v1/sources", _source_body(e2e_env, base_url=url))
            for resp in (probe, register):
                assert resp.status in (400, 403), f"{url}: {resp.describe()}"
                _sanitized(resp, e2e_env)
    assert hits == [], f"gateway reached a disallowed host: {hits}"
    assert evidence.count("sources") == before, "a source with a disallowed host was stored"


# --------------------------------------------------------------------------------------- A20
def test_A20_unsafe_redirect_is_not_followed(e2e_env, world, evidence):
    world.need("source")
    canary_hits: list[tuple[str, str]] = []
    redirect_hits: list[tuple[str, str]] = []
    canary_port = free_port()
    target = f"http://127.0.0.1:{canary_port}/stolen"
    candidate = _source_body(e2e_env)
    before = evidence.count("sources")
    with (AsgiServer(recorder_app(canary_hits), canary_port),
          fake1c_replaced_by(e2e_env, lambda: recorder_app(redirect_hits, redirect_to=target))):
        probe = world.pa.post("/admin/v1/source-probes", _probe_body(e2e_env))
        register = world.pa.post("/admin/v1/sources", candidate)
    for resp in (probe, register):
        assert resp.status in (400, 403), resp.describe()
        _sanitized(resp, e2e_env, extra_forbidden=(str(canary_port),))
    assert redirect_hits, "the redirecting stand-in was never contacted: test proves nothing"
    assert all(m in {"GET", "HEAD"} for m, _ in redirect_hits), redirect_hits
    assert canary_hits == [], f"redirect target was contacted: {canary_hits}"
    assert evidence.count("sources") == before, "source behind a redirect was stored"


# --------------------------------------------------------------------------------------- A21
def test_A21_missing_or_broken_secret_reference_fails_closed(e2e_env, world, evidence):
    world.need("source")
    before = evidence.count("sources")
    marker = "E2E_MISSING_SECRET_REF"
    cases = {
        "missing-password-ref": {"password_secret_ref": marker},
        "missing-username-ref": {"username_secret_ref": marker},
        "empty-ref": {"password_secret_ref": ""},
    }
    for name, override in cases.items():
        probe = world.pa.post("/admin/v1/source-probes", _probe_body(e2e_env, **override))
        register = world.pa.post("/admin/v1/sources", _source_body(e2e_env, **override))
        for resp in (probe, register):
            assert resp.status >= 400, f"{name} accepted: {resp.describe()}"
            _sanitized(resp, e2e_env)
    assert evidence.count("sources") == before, "a source with a broken secret ref was stored"


# --------------------------------------------------------------------------------------- A22
def test_A22_no_secret_value_in_api_responses_audit_or_logs(e2e_env, world, evidence):
    world.need("source", "company_one", "roles", "caps")
    values = secret_values(e2e_env)
    planted = "prefix-" + next(iter(values.values())) + "-suffix"
    assert find_leaks(planted, values), "scanner self-check failed: planted secret not found"
    # Generate secret-adjacent activity, including failures, before scanning.
    world.pa.post("/admin/v1/source-probes", _probe_body(e2e_env))
    world.pa.post("/admin/v1/source-probes",
                  _probe_body(e2e_env, password_secret_ref="E2E_MISSING_SECRET_REF"))
    for path in ("/admin/v1/sources", f"/admin/v1/sources/{world.source_id}",
                 "/admin/v1/capabilities", "/admin/v1/audit", "/admin/v1/companies"):
        world.pa.get(path)
    assert len(TRANSCRIPT) > 20, "too little traffic recorded to make the scan meaningful"
    leaked_responses = [(r.method, r.path, find_leaks(r.text, values))
                        for r in TRANSCRIPT if find_leaks(r.text, values)]
    assert not leaked_responses, f"secret values in API responses: {leaked_responses[:5]}"
    jwt_responses = [(r.method, r.path) for r in TRANSCRIPT if JWT_LIKE.search(r.text)]
    assert not jwt_responses, f"token-like values in API responses: {jwt_responses[:5]}"
    audit_leaks = find_leaks(evidence.audit_dump_text(), values)
    assert not audit_leaks, f"secret values in audit/idempotency rows: {audit_leaks}"
    logs = sorted(LOG_DIR.glob("gateway*.log"))
    assert logs, f"no gateway log files found under {LOG_DIR} to scan"
    for path in logs:
        text = path.read_text(encoding="utf-8", errors="replace")
        leaks = find_leaks(text, {k: v for k, v in values.items()
                                  if not k.startswith("password:")})
        assert not leaks, f"secret values in {path}: {leaks}"


# --------------------------------------------------------------------------------------- A23
def test_A23_register_synthetic_company_one(e2e_env, world, evidence):
    step = world.ensure("company_one")
    resp = expect(step.resp, 201, "A23 register company one")
    assert resp.body["source_id"] == world.source_id and resp.body["row_version"] == 1
    assert resp.body["external_ref"] == e2e_env.raw["companies"]["one"]
    audit = evidence.admin_events(resp)
    assert len(audit) == 1 and audit[0]["action"] == "company.create"
    assert audit[0]["outcome"] == "success" and audit[0]["source_id"] == world.source_id
    detail = expect(world.pa.get(f"/admin/v1/companies/{resp.body['id']}"), 200, "A23 detail")
    assert detail.body["display_name"] == "Synthetic Company One" and detail.body["enabled"]


# --------------------------------------------------------------------------------------- A24
def test_A24_register_synthetic_company_two(e2e_env, world, evidence):
    one = world.need("company_one").data["company_id"]
    step = world.ensure("company_two")
    resp = expect(step.resp, 201, "A24 register company two")
    assert resp.body["id"] != one and resp.body["source_id"] == world.source_id
    assert resp.body["external_ref"] == e2e_env.raw["companies"]["two"]
    audit = evidence.admin_events(resp)
    assert len(audit) == 1 and audit[0]["action"] == "company.create"
    listed = expect(world.pa.get("/admin/v1/companies"), 200, "A24 list").body["items"]
    assert {c["company_id"] for c in listed} >= {one, resp.body["id"]}


# --------------------------------------------------------------------------------------- A25
def test_A25_company_with_mismatching_source_rejected(e2e_env, world, evidence):
    world.need("company_one", "source_b", "company_b", "roles")
    pa, sid = world.pa, world.source_id
    before = evidence.snapshot()
    unknown = pa.post("/admin/v1/companies", {
        "source_id": unique("no-such-source"), "external_ref": unique("x"),
        "display_name": "orphan", "reason": "A25 unknown source"})
    foreign_company_grant = pa.post("/admin/v1/grants", {
        "principal_kind": "subject", "principal_id": unique("e2e-scratch"), "source_id": sid,
        "company_id": world.company_id("b"), "effect": "allow", "reason": "A25 company/source"})
    moved = pa.patch(f"/admin/v1/companies/{world.company_id('one')}", {
        "expected_version": 1, "source_id": world.source_b_id, "display_name": "moved",
        "enabled": True, "is_default": False, "reason": "A25 move"})
    for resp in (unknown, foreign_company_grant, moved):
        assert resp.status == 400, resp.describe()
        _sanitized(resp, e2e_env)
    assert evidence.snapshot() == before, "a mismatching source/company request changed state"
    row = evidence.one("SELECT source_id, display_name FROM bag.companies WHERE company_id=$1",
                       uuid.UUID(world.company_id("one")))
    assert row["source_id"] == sid and row["display_name"] == "Synthetic Company One"


# --------------------------------------------------------------------------------------- A26
def test_A26_duplicate_external_reference_is_deterministic(e2e_env, world, evidence):
    world.need("company_one")
    pa, sid = world.pa, world.source_id
    ref = e2e_env.raw["companies"]["one"]
    original = evidence.one("SELECT company_id, display_name, row_version FROM bag.companies "
                            "WHERE source_id=$1 AND external_ref=$2", sid, ref)
    outcomes = []
    for attempt in range(3):
        resp = pa.post("/admin/v1/companies", {
            "source_id": sid, "external_ref": ref, "display_name": f"overwrite attempt {attempt}",
            "reason": "A26 duplicate"})
        outcomes.append((resp.status, resp.body))
        audit = evidence.admin_events(resp)
        assert audit and audit[0]["outcome"] == "conflict", f"attempt {attempt}: not audited"
    assert len({str(o) for o in outcomes}) == 1, f"non-deterministic duplicate handling: {outcomes}"
    assert outcomes[0][0] == 409 and outcomes[0][1] == {"error": "POLICY_VERSION_CONFLICT"}
    after = evidence.rows("SELECT company_id, display_name, row_version FROM bag.companies "
                          "WHERE source_id=$1 AND external_ref=$2", sid, ref)
    assert after == [original], "duplicate registration overwrote or duplicated the company"
