"""A01-A15: session lifecycle, token boundary, role matrix, object scoping, CSRF, browser storage.

Every identity logs in through the real IdP form (authorization code + PKCE). Roles other than
the bootstrapped PLATFORM_ADMIN are bound through /admin/ by ``world`` (see admin_support.py).
"""

from __future__ import annotations

import re
import uuid

import pytest
from admin_support import (
    READ_PATHS,
    SESSION_COOKIE,
    AdminSession,
    anonymous,
    bearer,
    expect,
    find_leaks,
    secret_values,
    unique,
)

pytestmark = [pytest.mark.admin]

JWT_LIKE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")


def _no_admin_data(resp) -> bool:
    body = resp.body
    return not (isinstance(body, dict) and any(
        key in body for key in ("items", "access", "admin", "subject", "roles", "sources")))


# --------------------------------------------------------------------------------------- A01
def test_A01_login_me_logout_and_old_cookie_denied(e2e_env, world):
    session = AdminSession(e2e_env, "platform_admin")
    try:
        me = expect(session.get("/admin/v1/me"), 200, "A01 me after OIDC login")
        assert me.body["subject"] == "platform_admin"
        assert {"role": "PLATFORM_ADMIN", "source_id": None} in me.body["roles"]
        assert me.body["session_authenticated"] is True and me.body["csrf_token"]
        old_cookie = session.cookie
        assert old_cookie, "session cookie missing after login"
        before = expect(session.get("/admin/v1/overview"), 200, "A01 data while logged in")
        assert not _no_admin_data(before)

        out = session.logout()
        assert out.status == 302 and out.headers["location"].endswith("/admin/"), out.describe()
        assert SESSION_COOKIE in out.headers.get("set-cookie", ""), "logout must clear the cookie"

        for path in ("/admin/v1/me", "/admin/v1/overview", "/admin/v1/grants", "/admin/v1/audit"):
            replay = anonymous(e2e_env, "GET", path, cookie=old_cookie)
            assert replay.status == 401 and replay.error == "AUTH_REQUIRED", replay.describe()
            assert _no_admin_data(replay), f"protected data after logout: {replay.describe()}"
        stale_post = anonymous(e2e_env, "POST", "/admin/v1/grants", {"x": 1}, cookie=old_cookie,
                               headers={"X-CSRF-Token": me.body["csrf_token"],
                                        "Idempotency-Key": unique("e2e")})
        assert stale_post.status == 401, stale_post.describe()
    finally:
        session.close()


def test_A01_login_and_logout_are_audited(e2e_env, world, evidence):
    """Contract evidence for A01 is 'audit login/logout'. Looks for login/logout audit rows."""
    session = AdminSession(e2e_env, "platform_admin")
    try:
        session.logout()
    finally:
        session.close()
    rows = evidence.rows(
        "SELECT action, outcome FROM bag.admin_audit_events WHERE actor_subject='platform_admin' "
        "AND occurred_at >= $1 AND (action ILIKE '%login%' OR action ILIKE '%logout%')", world.t0)
    actions = {r["action"] for r in rows}
    assert any("login" in a for a in actions) and any("logout" in a for a in actions), (
        f"no login/logout audit rows for platform_admin since suite start: {sorted(actions)}")


# --------------------------------------------------------------------------------------- A02
@pytest.mark.parametrize("path", READ_PATHS + ("/admin/v1/me",))
def test_A02_no_session_gets_401_and_no_data(e2e_env, path):
    resp = anonymous(e2e_env, "GET", path)
    assert resp.status == 401 and resp.error == "AUTH_REQUIRED", resp.describe()
    assert _no_admin_data(resp), resp.describe()


def test_A02_no_session_mutation_and_garbage_credentials_rejected(e2e_env, world, evidence):
    before = evidence.snapshot()
    post = anonymous(e2e_env, "POST", "/admin/v1/grants", {"principal_kind": "subject"},
                     headers={"Idempotency-Key": unique("e2e")})
    assert post.status == 401, post.describe()
    garbage = anonymous(e2e_env, "GET", "/admin/v1/sources",
                        headers={"Authorization": "Bearer not-a-token"})
    assert garbage.status == 401 and _no_admin_data(garbage), garbage.describe()
    forged = anonymous(e2e_env, "GET", "/admin/v1/sources", cookie="forged-session-id")
    assert forged.status == 401 and _no_admin_data(forged), forged.describe()
    page = anonymous(e2e_env, "GET", "/admin/")
    assert page.status == 200 and "Admin Control Center" in page.text  # static shell only
    assert evidence.snapshot() == before, "unauthenticated calls changed domain state"


# --------------------------------------------------------------------------------------- A03
def test_A03_wrong_audience_token_is_denied(e2e_env, idp, world, evidence):
    before = evidence.snapshot()
    control = bearer(e2e_env, idp.token("platform_admin", audience="admin"), "GET",
                     "/admin/v1/me", subject="platform_admin")
    expect(control, 200, "A03 control: correct audience must work")
    wrong = idp.token("platform_admin", audience="data", scope=e2e_env.raw["scopes"]["admin"])
    for method, path, body in (("GET", "/admin/v1/me", None), ("GET", "/admin/v1/sources", None),
                               ("POST", "/admin/v1/grants", {"principal_kind": "subject"})):
        resp = bearer(e2e_env, wrong, method, path, body, subject="platform_admin")
        assert resp.status == 401 and _no_admin_data(resp), resp.describe()
    assert evidence.snapshot() == before


def test_A03_denial_is_audited(e2e_env, idp, world, evidence):
    """Contract evidence for A03/A04 is 'audit deny': the denied request must leave a trace."""
    wrong = idp.token("platform_admin", audience="data", scope=e2e_env.raw["scopes"]["admin"])
    resp = bearer(e2e_env, wrong, "GET", "/admin/v1/me", subject="platform_admin")
    assert resp.status == 401
    rid = resp.request_uuid
    found = evidence.rows(
        "SELECT request_id FROM bag.admin_audit_events WHERE request_id=$1 UNION ALL "
        "SELECT request_id FROM bag.audit_events WHERE request_id=$1", rid)
    assert found, f"no audit row for denied wrong-audience request {resp.request_id}"


# --------------------------------------------------------------------------------------- A04
def test_A04_token_without_admin_scope_is_denied(e2e_env, idp, world, evidence):
    before = evidence.snapshot()
    no_scope = idp.token("platform_admin", audience="admin", scope="openid")
    for method, path, body in (("GET", "/admin/v1/me", None), ("GET", "/admin/v1/audit", None),
                               ("POST", "/admin/v1/companies", {"source_id": "x"})):
        resp = bearer(e2e_env, no_scope, method, path, body, subject="platform_admin")
        assert resp.status == 401 and _no_admin_data(resp), resp.describe()
    expect(bearer(e2e_env, idp.token("platform_admin", audience="admin"), "GET", "/admin/v1/me",
                  subject="platform_admin"), 200, "A04 control with scope")
    assert evidence.snapshot() == before


# --------------------------------------------------------------------------------------- A05
def test_A05_data_plane_only_user_gets_no_admin_access(e2e_env, idp, world, evidence):
    session = AdminSession(e2e_env, "user_company_one")
    try:
        responses = [session.get(path) for path in READ_PATHS + ("/admin/v1/me",)]
        responses.append(bearer(e2e_env, idp.token("user_company_one", audience="admin"), "GET",
                                "/admin/v1/me", subject="user_company_one"))
        responses.append(session.post("/admin/v1/grants", {"principal_kind": "subject"}))
        for resp in responses:
            assert resp.status == 403, resp.describe()
            assert _no_admin_data(resp), resp.describe()
        denied = evidence.admin_events(responses[0])
        assert denied and denied[0]["outcome"] == "denied", (
            f"no 'denied' admin audit row for {responses[0].request_id}")
        assert denied[0]["actor_subject"] == "user_company_one"
    finally:
        session.close()


# --------------------------------------------------------------------------------------- A06
def _mut(resp, what, status=(200, 201)):
    return expect(resp, status, what)


def test_A06_platform_admin_reaches_every_read_surface(e2e_env, world):
    world.need("source", "company_one", "caps", "roles", "profile")
    pa = world.pa
    for path in READ_PATHS:
        _mut(pa.get(path), f"A06 read {path}", 200)
    sid = world.source_id
    detail = _mut(pa.get(f"/admin/v1/sources/{sid}"), "A06 source detail", 200)
    assert detail.body["source_id"] == sid and detail.body["read_only"] is True
    assert not find_leaks(detail.text, secret_values(e2e_env)), "credential value in detail"
    _mut(pa.get(f"/admin/v1/companies/{world.company_id('one')}"), "A06 company detail", 200)
    profile_id = world.steps["profile"].data["profile_id"]
    _mut(pa.get(f"/admin/v1/semantic-profiles/{profile_id}"), "A06 profile detail", 200)
    _mut(pa.get("/admin/v1/principals/resolve",
                params={"kind": "subject", "id": "user_company_one"}), "A06 resolve", 200)
    _mut(pa.get("/admin/v1/effective-access", params={
        "kind": "subject", "id": "user_company_one", "source_id": sid}), "A06 effective", 200)


def test_A06_platform_admin_reaches_every_write_surface(e2e_env, world, evidence):
    world.need("source", "company_one", "caps", "roles")
    pa, sid = world.pa, world.source_id
    steps = []

    # source probe / refresh / update
    probe = _mut(pa.post("/admin/v1/source-probes", {
        "base_url": e2e_env.fake1c_url, "username_secret_ref": "FAKE1C_USERNAME",
        "password_secret_ref": "FAKE1C_PASSWORD"}), "A06 probe", 200)
    assert probe.body["capabilities"]["metadata_fingerprint"]
    steps.append("probe")
    _mut(pa.post(f"/admin/v1/sources/{sid}/capability-refresh", {"reason": "A06 refresh"}),
         "A06 refresh", 200)
    current = _mut(pa.get(f"/admin/v1/sources/{sid}"), "A06 detail", 200).body
    updated = _mut(pa.patch(f"/admin/v1/sources/{sid}", {
        "expected_version": current["row_version"], "display_name": current["display_name"],
        "base_url": current["base_url"], "username_secret_ref": current["username_secret_ref"],
        "password_secret_ref": current["password_secret_ref"], "tags": current["tags"],
        "enabled": True, "reason": "A06 no-op source update"}), "A06 source update", 200)
    assert updated.body["row_version"] == current["row_version"] + 1
    steps += ["refresh", "source-update"]

    # company create / update
    created = _mut(pa.post("/admin/v1/companies", {
        "source_id": sid, "external_ref": unique("e2e-a06"), "display_name": "A06 company",
        "reason": "A06 company"}), "A06 company create", 201)
    company = created.body["id"]
    _mut(pa.patch(f"/admin/v1/companies/{company}", {
        "expected_version": 1, "display_name": "A06 company renamed", "enabled": True,
        "is_default": False, "reason": "A06 rename"}), "A06 company update", 200)
    steps += ["company-create", "company-update"]

    # access grant create / revoke
    grant = _mut(world.scratch_grant(pa, company=company), "A06 grant create", 201)
    _mut(world.revoke_grant(pa, grant.body["id"]), "A06 grant revoke", 200)
    steps += ["grant-create", "grant-revoke"]

    # platform role create / revoke (step-up)
    stepped = world.pa_step_up()
    binding = _mut(stepped.post("/admin/v1/platform-role-bindings", {
        "principal_kind": "subject", "principal_id": unique("e2e-scratch"),
        "role_name": "AUDITOR", "source_id": sid, "reason": "A06 role"}), "A06 role create", 201)
    _mut(stepped.post(f"/admin/v1/platform-role-bindings/{binding.body['id']}/revoke", {
        "expected_version": 1, "reason": "A06 role revoke"}), "A06 role revoke", 200)
    steps += ["role-create", "role-revoke"]

    # business role assign / revoke, capability override create / revoke
    roles = _mut(pa.get("/admin/v1/business-roles"), "A06 business roles", 200).body["items"]
    role_id = roles[0]["role_id"]
    capability = next(c for r in roles for c in r["capabilities"])
    assignment = _mut(pa.post("/admin/v1/business-role-assignments", {
        "principal_kind": "subject", "principal_id": unique("e2e-scratch"), "role_id": role_id,
        "source_id": sid, "company_id": None, "reason": "A06 assign"}), "A06 assign", 201)
    _mut(pa.post(f"/admin/v1/business-role-assignments/{assignment.body['id']}/revoke", {
        "expected_version": 1, "reason": "A06 unassign"}), "A06 unassign", 200)
    override = _mut(pa.post("/admin/v1/capability-overrides", {
        "principal_kind": "subject", "principal_id": unique("e2e-scratch"),
        "capability_key": capability, "source_id": sid, "company_id": None, "effect": "deny",
        "reason": "A06 override"}), "A06 override", 201)
    _mut(pa.post(f"/admin/v1/capability-overrides/{override.body['id']}/revoke", {
        "expected_version": 1, "reason": "A06 override revoke"}), "A06 override revoke", 200)
    steps += ["assign", "unassign", "override", "override-revoke"]

    # semantic profile create / mapping / retire
    draft = _mut(world.create_profile(pa, sid), "A06 profile create", 201).body["id"]
    _mut(world.add_mapping(pa, draft), "A06 mapping", 201)
    _mut(pa.post(f"/admin/v1/semantic-profiles/{draft}/retire", {"reason": "A06 retire"}),
         "A06 retire", 200)
    steps += ["profile-create", "mapping", "retire"]

    audited = {r["action"] for r in evidence.admin_events_since(
        world.t0, actor_subject="platform_admin")}
    for action in ("source.update", "company.create", "grant.create", "platform_role.create",
                   "business_role.assign", "capability_override.create",
                   "semantic_profile.create", "semantic_mapping.create"):
        assert action in audited, f"A06 mutation {action} left no admin audit event ({steps})"


def test_A06_platform_admin_is_authorized_for_validate_and_scope_mapping_surfaces(
        e2e_env, world, evidence):
    """Profile validation and company-scope mapping need NATIVE reconciliation evidence, which
    cannot exist in this synthetic environment and is never fabricated here. The PLATFORM_ADMIN
    must be AUTHORIZED for both surfaces (never 401/403) and the product must refuse fail-closed
    with its documented domain error (never 200/201) while a read-only role is denied (403)."""
    world.need("source", "caps", "roles")
    pa, aud = world.pa, world.role_session("AUDITOR")
    draft = _mut(world.create_profile(pa, world.source_id), "A06 profile", 201).body["id"]
    _mut(world.add_mapping(pa, draft), "A06 mapping", 201)
    validate_path = f"/admin/v1/semantic-profiles/{draft}/validate"
    no_native_evidence = {"validation_evidence": {"native_reconciliation_cases": []},
                          "reason": "A06 validation without native evidence"}

    refused = pa.post(validate_path, no_native_evidence)
    assert refused.status in (400, 409, 422), (
        f"validation without native evidence must be refused 4xx: {refused.describe()}")
    assert refused.error in {"INVALID_REQUEST", "CAPABILITY_UNSUPPORTED"}, refused.describe()
    forbidden = aud.post(validate_path, no_native_evidence)
    assert forbidden.status == 403 and forbidden.error == "PLATFORM_ROLE_DENIED", (
        f"the read-only role must not reach the validate surface: {forbidden.describe()}")
    assert evidence.scalar("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1",
                           uuid.UUID(draft)) != "VALIDATED"

    scope_body = {"profile_id": draft, "entity_set": "Document_Sales",
                  "company_property": "Organization_Key", "literal_kind": "guid",
                  "reason": "A06 scope mapping on a profile that is not VALIDATED"}
    scope = pa.post("/admin/v1/company-scope-mappings", scope_body)
    assert scope.status in (400, 409, 422), scope.describe()
    assert scope.error == "INVALID_REQUEST", scope.describe()
    audit = evidence.admin_events(scope)
    assert audit and audit[0]["outcome"] == "error" and audit[0]["actor_subject"] == (
        "platform_admin"), f"authorized refusal must be audited as an error, not a denial: {audit}"
    assert aud.post("/admin/v1/company-scope-mappings", scope_body).status == 403
    assert evidence.count("company_scope_mappings", "profile_id=$1", uuid.UUID(draft)) == 0
    _mut(pa.post(f"/admin/v1/semantic-profiles/{draft}/retire", {"reason": "A06 retire"}),
         "A06 retire", 200)


# --------------------------------------------------------------------------------------- A07
def test_A07_source_admin_scoped_to_own_source(e2e_env, world, evidence):
    world.need("roles", "source_b", "company_b")
    sa, sid, other = world.role_session("SOURCE_ADMIN"), world.source_id, world.source_b_id
    listed = expect(sa.get("/admin/v1/sources"), 200, "A07 list").body["items"]
    assert [s["source_id"] for s in listed] == [sid], "SOURCE_ADMIN must only see its own source"
    own = expect(sa.get(f"/admin/v1/sources/{sid}"), 200, "A07 own detail").body
    expect(sa.post(f"/admin/v1/sources/{sid}/capability-refresh", {"reason": "A07 own refresh"}),
           200, "A07 own refresh")
    renamed = expect(sa.patch(f"/admin/v1/sources/{sid}", {
        "expected_version": own["row_version"], "display_name": own["display_name"],
        "base_url": own["base_url"], "username_secret_ref": own["username_secret_ref"],
        "password_secret_ref": own["password_secret_ref"], "tags": own["tags"], "enabled": True,
        "reason": "A07 own update"}), 200, "A07 own update")
    assert renamed.body["row_version"] == own["row_version"] + 1

    before = evidence.snapshot()
    other_row = evidence.one("SELECT row_version, updated_at FROM bag.sources WHERE source_id=$1",
                             other)
    attempts = [
        sa.get(f"/admin/v1/sources/{other}"),
        sa.post(f"/admin/v1/sources/{other}/capability-refresh", {"reason": "A07 cross"}),
        sa.patch(f"/admin/v1/sources/{other}", {
            "expected_version": 1, "display_name": "hijack", "base_url": e2e_env.fake1c_url,
            "username_secret_ref": "FAKE1C_USERNAME", "password_secret_ref": "FAKE1C_PASSWORD",
            "tags": [], "enabled": True, "reason": "A07 cross"}),
        sa.post(f"/admin/v1/sources/{other}/drift-acknowledgements", {
            "expected_fingerprint": "x", "reason": "A07 cross"}),
        sa.post("/admin/v1/companies", {"source_id": other, "external_ref": unique("x"),
                                        "display_name": "x", "reason": "A07 cross"}),
        sa.post("/admin/v1/sources", {"source_id": unique("sa-new"), "display_name": "x",
                                      "base_url": e2e_env.fake1c_url,
                                      "username_secret_ref": "FAKE1C_USERNAME",
                                      "password_secret_ref": "FAKE1C_PASSWORD", "reason": "x"}),
        sa.patch(f"/admin/v1/sources/{sid}", {  # confused deputy: repointing own source
            "expected_version": renamed.body["row_version"], "display_name": own["display_name"],
            "base_url": own["base_url"] + "/", "username_secret_ref": own["username_secret_ref"],
            "password_secret_ref": own["password_secret_ref"], "tags": [], "enabled": True,
            "reason": "A07 repoint"}),
    ]
    assert attempts[0].status == 404, attempts[0].describe()
    for resp in attempts[1:]:
        assert resp.status == 403, resp.describe()
    assert evidence.snapshot() == before, "cross-source attempts changed domain state"
    after_row = evidence.one("SELECT row_version, updated_at FROM bag.sources WHERE source_id=$1",
                             other)
    assert after_row == other_row, "other source was modified"
    denied = evidence.admin_events(attempts[1])
    assert denied and denied[0]["outcome"] == "denied", "cross-source denial not audited"


# --------------------------------------------------------------------------------------- A08
def test_A08_access_admin_grants_only(e2e_env, world, evidence):
    world.need("roles", "company_one")
    aa, sid = world.role_session("ACCESS_ADMIN"), world.source_id
    grant = expect(world.scratch_grant(aa, company=world.company_id("one")), 201, "A08 create")
    audit = evidence.admin_events(grant)
    assert audit and audit[0]["outcome"] == "success"
    assert audit[0]["actor_subject"] == "access_admin"
    expect(world.revoke_grant(aa, grant.body["id"]), 200, "A08 revoke")

    before = evidence.snapshot()
    forbidden = [
        aa.post("/admin/v1/platform-role-bindings", {
            "principal_kind": "subject", "principal_id": unique("x"), "role_name": "AUDITOR",
            "source_id": sid, "reason": "A08"}),
        aa.patch(f"/admin/v1/sources/{sid}", {"expected_version": 1, "display_name": "x",
                                              "base_url": e2e_env.fake1c_url,
                                              "username_secret_ref": "FAKE1C_USERNAME",
                                              "password_secret_ref": "FAKE1C_PASSWORD",
                                              "tags": [], "enabled": True, "reason": "A08"}),
        aa.post("/admin/v1/sources", {"source_id": unique("x"), "display_name": "x",
                                      "base_url": e2e_env.fake1c_url,
                                      "username_secret_ref": "FAKE1C_USERNAME",
                                      "password_secret_ref": "FAKE1C_PASSWORD", "reason": "A08"}),
        aa.post("/admin/v1/companies", {"source_id": sid, "external_ref": unique("x"),
                                        "display_name": "x", "reason": "A08"}),
        aa.post("/admin/v1/semantic-profiles", {"source_id": sid, "preset_id": "bp30",
                                                "profile_name": unique("x"), "reason": "A08"}),
        aa.post(f"/admin/v1/sources/{sid}/capability-refresh", {"reason": "A08"}),
    ]
    for resp in forbidden:
        assert resp.status == 403, resp.describe()
    assert evidence.snapshot() == before, "ACCESS_ADMIN forbidden calls changed domain state"


# --------------------------------------------------------------------------------------- A09
def test_A09_profile_admin_profiles_only(e2e_env, world, evidence):
    world.need("roles", "caps")
    pra, sid = world.role_session("PROFILE_ADMIN"), world.source_id
    created = expect(world.create_profile(pra, sid), 201, "A09 create")
    pid = created.body["id"]
    expect(world.add_mapping(pra, pid), 201, "A09 mapping")
    expect(pra.get("/admin/v1/semantic-profiles"), 200, "A09 list")
    expect(pra.post(f"/admin/v1/semantic-profiles/{pid}/retire", {"reason": "A09 retire"}), 200,
           "A09 retire")

    before = evidence.snapshot()
    forbidden = [
        world.scratch_grant(pra),
        pra.post("/admin/v1/companies", {"source_id": sid, "external_ref": unique("x"),
                                         "display_name": "x", "reason": "A09"}),
        pra.post("/admin/v1/sources", {"source_id": unique("x"), "display_name": "x",
                                       "base_url": e2e_env.fake1c_url,
                                       "username_secret_ref": "FAKE1C_USERNAME",
                                       "password_secret_ref": "FAKE1C_PASSWORD", "reason": "A09"}),
        pra.post("/admin/v1/platform-role-bindings", {
            "principal_kind": "subject", "principal_id": unique("x"), "role_name": "AUDITOR",
            "source_id": sid, "reason": "A09"}),
        pra.post(f"/admin/v1/sources/{sid}/capability-refresh", {"reason": "A09"}),
        pra.get("/admin/v1/grants"),
    ]
    for resp in forbidden:
        assert resp.status == 403, resp.describe()
    assert evidence.snapshot() == before, "PROFILE_ADMIN forbidden calls changed domain state"


# --------------------------------------------------------------------------------------- A10
def test_A10_auditor_reads_but_cannot_mutate(e2e_env, world, evidence):
    world.need("roles", "company_one", "caps")
    aud, sid = world.role_session("AUDITOR"), world.source_id
    for path in ("/admin/v1/audit", "/admin/v1/sources", "/admin/v1/grants",
                 "/admin/v1/companies", "/admin/v1/platform-role-bindings",
                 "/admin/v1/semantic-profiles", "/admin/v1/capabilities"):
        expect(aud.get(path), 200, f"A10 read {path}")
    before = evidence.snapshot()
    company = world.company_id("one")
    mutations = [
        ("POST", "/admin/v1/grants", {"principal_kind": "subject", "principal_id": unique("x"),
                                      "source_id": sid, "effect": "allow", "reason": "A10"}),
        ("POST", f"/admin/v1/grants/{uuid.uuid4()}/revoke", {"expected_version": 1, "reason": "x"}),
        ("POST", "/admin/v1/sources", {"source_id": unique("x"), "display_name": "x",
                                       "base_url": e2e_env.fake1c_url,
                                       "username_secret_ref": "FAKE1C_USERNAME",
                                       "password_secret_ref": "FAKE1C_PASSWORD", "reason": "A10"}),
        ("PATCH", f"/admin/v1/sources/{sid}", {"expected_version": 1, "display_name": "x",
                                               "base_url": e2e_env.fake1c_url,
                                               "username_secret_ref": "FAKE1C_USERNAME",
                                               "password_secret_ref": "FAKE1C_PASSWORD",
                                               "tags": [], "enabled": True, "reason": "A10"}),
        ("POST", f"/admin/v1/sources/{sid}/capability-refresh", {"reason": "A10"}),
        ("POST", f"/admin/v1/sources/{sid}/drift-acknowledgements", {"expected_fingerprint": "x",
                                                                      "reason": "A10"}),
        ("POST", "/admin/v1/companies", {"source_id": sid, "external_ref": unique("x"),
                                         "display_name": "x", "reason": "A10"}),
        ("PATCH", f"/admin/v1/companies/{company}", {"expected_version": 1, "display_name": "x",
                                                     "enabled": True, "is_default": False,
                                                     "reason": "A10"}),
        ("POST", "/admin/v1/platform-role-bindings", {
            "principal_kind": "subject", "principal_id": unique("x"), "role_name": "AUDITOR",
            "source_id": sid, "reason": "A10"}),
        ("POST", "/admin/v1/business-role-assignments", {
            "principal_kind": "subject", "principal_id": unique("x"), "role_id": "VIEWER",
            "source_id": sid, "reason": "A10"}),
        ("POST", "/admin/v1/capability-overrides", {
            "principal_kind": "subject", "principal_id": unique("x"), "capability_key": "x",
            "source_id": sid, "effect": "deny", "reason": "A10"}),
        ("POST", "/admin/v1/semantic-profiles", {"source_id": sid, "preset_id": "bp30",
                                                 "profile_name": unique("x"), "reason": "A10"}),
        ("POST", f"/admin/v1/semantic-profiles/{uuid.uuid4()}/retire", {"reason": "A10"}),
        ("POST", "/admin/v1/company-scope-mappings", {"profile_id": str(uuid.uuid4()),
                                                      "entity_set": "x", "reason": "A10"}),
    ]
    for method, path, body in mutations:
        resp = aud.request(method, path, body)
        assert resp.status == 403, f"A10 {resp.describe()}"
    assert evidence.snapshot() == before, "AUDITOR mutation attempts changed domain state"


# --------------------------------------------------------------------------------------- A11
def test_A11_authenticated_user_without_role_denied_everywhere(e2e_env, idp, world, evidence):
    session = AdminSession(e2e_env, "admin_no_role")
    try:
        before = evidence.snapshot()
        paths = READ_PATHS + ("/admin/v1/me", f"/admin/v1/sources/{world.source_id}",
                              "/admin/v1/principals/resolve?kind=subject&id=x",
                              f"/admin/v1/effective-access?kind=subject&id=x&source_id={world.source_id}")
        responses = [session.get(path) for path in paths]
        responses.append(session.post("/admin/v1/grants", {"principal_kind": "subject"}))
        responses.append(bearer(e2e_env, idp.token("admin_no_role", audience="admin"), "GET",
                                "/admin/v1/me", subject="admin_no_role"))
        for resp in responses:
            assert resp.status == 403, resp.describe()
            assert _no_admin_data(resp), resp.describe()
        denied = evidence.admin_events(responses[0])
        assert denied and denied[0]["outcome"] == "denied", "A11 denial not audited"
        assert evidence.snapshot() == before
    finally:
        session.close()


# --------------------------------------------------------------------------------------- A12
def test_A12_object_ids_of_other_source_denied_without_oracle(e2e_env, world, evidence):
    world.need("roles", "source_b", "company_b", "grant_b", "profile_b")
    sa, aa, pra = (world.role_session("SOURCE_ADMIN"), world.role_session("ACCESS_ADMIN"),
                   world.role_session("PROFILE_ADMIN"))
    other_company = world.company_id("b")
    other_grant = world.steps["grant_b"].data["grant_id"]
    other_profile = world.steps["profile_b"].data["profile_id"]
    missing = str(uuid.uuid4())
    before = evidence.snapshot()
    company_row = evidence.one("SELECT row_version, display_name, enabled FROM bag.companies "
                               "WHERE company_id=$1", uuid.UUID(other_company))
    grant_row = evidence.one("SELECT row_version, revoked_at FROM bag.access_grants "
                             "WHERE grant_id=$1", uuid.UUID(other_grant))
    profile_row = evidence.one("SELECT status, profile_fingerprint FROM bag.semantic_profiles "
                               "WHERE profile_id=$1", uuid.UUID(other_profile))

    def company_patch(company_id):
        return sa.patch(f"/admin/v1/companies/{company_id}", {
            "expected_version": 1, "display_name": "hijack", "enabled": False,
            "is_default": False, "reason": "A12"})

    foreign, absent = company_patch(other_company), company_patch(missing)
    assert foreign.status == absent.status == 403 and foreign.body == absent.body, (
        foreign.describe(), absent.describe())
    seen, unseen = (sa.get(f"/admin/v1/companies/{other_company}"),
                    sa.get(f"/admin/v1/companies/{missing}"))
    assert seen.status == unseen.status == 404 and seen.body == unseen.body

    g_foreign, g_absent = world.revoke_grant(aa, other_grant), world.revoke_grant(aa, missing)
    assert g_foreign.status == g_absent.status == 403 and g_foreign.body == g_absent.body

    detail, no_detail = (pra.get(f"/admin/v1/semantic-profiles/{other_profile}"),
                         pra.get(f"/admin/v1/semantic-profiles/{missing}"))
    assert detail.status == no_detail.status == 404 and detail.body == no_detail.body
    for path in ("mappings", "validate", "retire"):
        foreign_op = pra.post(f"/admin/v1/semantic-profiles/{other_profile}/{path}", {
            "canonical_concept": "sales", "reason": "A12"})
        absent_op = pra.post(f"/admin/v1/semantic-profiles/{missing}/{path}", {
            "canonical_concept": "sales", "reason": "A12"})
        assert foreign_op.status == absent_op.status == 403, (foreign_op.describe(),
                                                               absent_op.describe())

    assert evidence.snapshot() == before
    assert evidence.one("SELECT row_version, display_name, enabled FROM bag.companies WHERE "
                        "company_id=$1", uuid.UUID(other_company)) == company_row
    assert evidence.one("SELECT row_version, revoked_at FROM bag.access_grants WHERE "
                        "grant_id=$1", uuid.UUID(other_grant)) == grant_row
    assert evidence.one("SELECT status, profile_fingerprint FROM bag.semantic_profiles WHERE "
                        "profile_id=$1", uuid.UUID(other_profile)) == profile_row


# --------------------------------------------------------------------------------------- A13
def test_A13_mutation_with_valid_csrf_is_accepted_and_audited(e2e_env, world, evidence):
    world.need("source", "company_one")
    pa = world.pa
    resp = expect(world.scratch_grant(pa, company=world.company_id("one")), 201, "A13 valid CSRF")
    rows = evidence.admin_events(resp)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["outcome"] == "success" and row["action"] == "grant.create"
    assert row["actor_subject"] == "platform_admin"
    assert row["actor_client_id"] == e2e_env.raw["idp"]["admin_client_id"]
    assert row["idempotency_key"] == resp.idem_key and row["reason"]
    assert str(row["target_id"]) == resp.body["id"]
    expect(world.revoke_grant(pa, resp.body["id"]), 200, "A13 cleanup")


# --------------------------------------------------------------------------------------- A14
def test_A14_missing_or_invalid_csrf_rejected_without_side_effect(e2e_env, world, evidence):
    world.need("source", "company_one")
    pa = world.pa
    principal = unique("e2e-csrf")
    other = AdminSession(e2e_env, "platform_admin")
    try:
        assert other.csrf and other.csrf != pa.csrf
        attempts = {
            "missing": pa.post("/admin/v1/grants", {
                "principal_kind": "subject", "principal_id": principal,
                "source_id": world.source_id, "effect": "allow", "reason": "A14 missing"},
                csrf=False),
            "invalid": pa.post("/admin/v1/grants", {
                "principal_kind": "subject", "principal_id": principal,
                "source_id": world.source_id, "effect": "allow", "reason": "A14 invalid"},
                csrf="not-the-csrf-token"),
            "other-session": pa.post("/admin/v1/grants", {
                "principal_kind": "subject", "principal_id": principal,
                "source_id": world.source_id, "effect": "allow", "reason": "A14 foreign"},
                csrf=other.csrf),
        }
        for name, resp in attempts.items():
            assert resp.status == 403 and resp.error == "CSRF_DENIED", f"{name}: {resp.describe()}"
            audit = evidence.admin_events(resp)
            assert audit and audit[0]["outcome"] == "denied", f"{name}: CSRF denial not audited"
        assert evidence.count("access_grants", "principal_id=$1", principal) == 0, (
            "a CSRF-rejected request created a grant")
        assert evidence.count("admin_idempotency", "idempotency_key=$1",
                              attempts["missing"].idem_key) == 0
        no_logout = pa.post("/admin/logout", csrf=False)
        assert no_logout.status == 403 and no_logout.error == "CSRF_DENIED"
        assert pa.alive(), "a CSRF-rejected logout must not end the session"
        forged = anonymous(e2e_env, "POST", "/admin/v1/grants", {"principal_kind": "subject"},
                           headers={"X-CSRF-Token": pa.csrf, "Idempotency-Key": unique("e2e")})
        assert forged.status == 401, forged.describe()
    finally:
        other.close()


# --------------------------------------------------------------------------------------- A15
def test_A15_no_token_in_browser_storage_and_cookie_is_httponly(e2e_env, world, browser_login):
    page = browser_login("platform_admin")
    storage = page.evaluate("""() => ({
        local: Object.entries(localStorage), session: Object.entries(sessionStorage),
        cookie: document.cookie, state: JSON.stringify(state)})""")
    assert storage["local"] == [] and storage["session"] == [], (
        f"browser storage not empty: {[k for k, _ in storage['local'] + storage['session']]}")
    assert SESSION_COOKIE not in storage["cookie"], "session cookie readable from JavaScript"
    for blob in (storage["cookie"], storage["state"]):
        assert not JWT_LIKE.search(blob), "JWT-like value reachable from page JavaScript"
    cookies = {c["name"]: c for c in page.context.cookies()}
    session_cookie = cookies[SESSION_COOKIE]
    assert session_cookie["httpOnly"] is True and session_cookie["sameSite"] == "Strict"
    assert session_cookie["path"] == "/admin"
    for forbidden in ("access_token", "refresh_token", "id_token"):
        assert forbidden not in storage["state"]
    page.goto(e2e_env.gateway + "/admin/")
    page.wait_for_selector(".content")
    again = page.evaluate("() => [Object.keys(localStorage).length, "
                          "Object.keys(sessionStorage).length]")
    assert again == [0, 0]
