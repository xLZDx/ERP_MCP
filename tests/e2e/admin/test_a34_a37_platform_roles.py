"""A34-A37: platform role bindings, step-up authentication and the role/data-ACL boundary.

Step-up uses the test IdP's ``acr_values`` / ``max_age`` support (browser-style session) and its
headless ``acr`` / ``auth_age`` parameters (bearer tokens). The gateway accepts a step-up token
only when ``acr`` is approved and ``auth_time`` is at most 300 s old.
"""

from __future__ import annotations

import uuid

import pytest
from admin_support import bearer, expect, unique

pytestmark = [pytest.mark.admin]

STEP_UP_ERROR = "STEP_UP_REQUIRED"


def _binding_body(world, role="AUDITOR", principal=None, reason="role step-up test"):
    return {"principal_kind": "subject", "principal_id": principal or unique("e2e-scratch"),
            "role_name": role, "source_id": world.source_id, "reason": reason}


def _revoke(world, session, binding_id):
    return session.post(f"/admin/v1/platform-role-bindings/{binding_id}/revoke",
                        {"expected_version": 1, "reason": "cleanup"})


# --------------------------------------------------------------------------------------- A34
def test_A34_platform_admin_binds_platform_roles(e2e_env, world, evidence):
    step = world.ensure("roles")
    expect(step.resp, 201, "A34 role binding")
    bound = step.data["bound"]
    assert set(bound) == {"SOURCE_ADMIN", "ACCESS_ADMIN", "PROFILE_ADMIN", "AUDITOR"}
    users = {"SOURCE_ADMIN": "source_admin", "ACCESS_ADMIN": "access_admin",
             "PROFILE_ADMIN": "profile_admin", "AUDITOR": "auditor"}
    for role, binding_id in bound.items():
        row = evidence.one("SELECT * FROM bag.platform_role_bindings WHERE binding_id=$1",
                           uuid.UUID(binding_id))
        assert row["role_name"] == role and row["principal_id"] == users[role]
        assert row["principal_kind"] == "subject" and row["source_id"] == world.source_id
        assert row["revoked_at"] is None and row["created_by_subject"] == "platform_admin"
        assert row["created_by_client"] == e2e_env.raw["idp"]["admin_client_id"]
        assert row["reason"]
    audited = evidence.rows(
        "SELECT target_id FROM bag.admin_audit_events WHERE action='platform_role.create' AND "
        "outcome='success' AND actor_subject='platform_admin'")
    assert {str(r["target_id"]) for r in audited} >= set(bound.values())
    # The binding is effective: the bound identities now resolve their role on /me.
    for role, user in users.items():
        me = expect(world.role_session(role).get("/admin/v1/me"), 200, f"A34 me for {user}")
        assert {"role": role, "source_id": world.source_id} in me.body["roles"]
    listing = expect(world.pa.get("/admin/v1/platform-role-bindings"), 200, "A34 list").body
    assert {b["binding_id"] for b in listing["items"]} >= set(bound.values())


# --------------------------------------------------------------------------------------- A35
def test_A35_sensitive_role_mutation_requires_step_up_acr(e2e_env, idp, world, evidence):
    world.need("source")
    plain_session = world.pa  # ordinary login: basic ACR
    before = evidence.count("platform_role_bindings")

    session_attempt = plain_session.post("/admin/v1/platform-role-bindings", _binding_body(world))
    token_attempt = bearer(e2e_env, idp.token("platform_admin", audience="admin"), "POST",
                           "/admin/v1/platform-role-bindings", _binding_body(world),
                           subject="platform_admin")
    for resp in (session_attempt, token_attempt):
        assert resp.status == 403 and resp.error == STEP_UP_ERROR, resp.describe()
    # A random id keeps this safe even if the guard were missing (a 404 would then show up).
    revoke_attempt = _revoke(world, plain_session, str(uuid.uuid4()))
    assert revoke_attempt.status == 403 and revoke_attempt.error == STEP_UP_ERROR, (
        "role revoke must also need step-up: " + revoke_attempt.describe())
    assert evidence.count("platform_role_bindings") == before, "binding created without step-up"
    denied = evidence.admin_events(session_attempt)
    assert denied and denied[0]["outcome"] == "denied", "step-up denial not audited"

    stepped = world.pa_step_up()
    accepted = expect(stepped.post("/admin/v1/platform-role-bindings", _binding_body(world)), 201,
                      "A35 with step-up session")
    bearer_ok = expect(bearer(e2e_env, idp.step_up_token("platform_admin"), "POST",
                              "/admin/v1/platform-role-bindings", _binding_body(world),
                              subject="platform_admin"), 201, "A35 with step-up bearer")
    for created in (accepted, bearer_ok):
        audit = evidence.admin_events(created)
        assert audit and audit[0]["outcome"] == "success"
        expect(_revoke(world, stepped, created.body["id"]), 200, "A35 cleanup")


# --------------------------------------------------------------------------------------- A36
def test_A36_step_up_with_old_auth_time_rejected_until_fresh(e2e_env, idp, world, evidence):
    world.need("source")
    before = evidence.count("platform_role_bindings")
    acr = e2e_env.raw["step_up_acr"]
    rejected = []
    for label, age in (("auth 10 min old", 600), ("auth in the future", -3600)):
        token = idp.token("platform_admin", audience="admin", acr=acr, auth_age=age)
        resp = bearer(e2e_env, token, "POST", "/admin/v1/platform-role-bindings",
                      _binding_body(world), subject="platform_admin")
        assert resp.status == 403 and resp.error == STEP_UP_ERROR, f"{label}: {resp.describe()}"
        audit = evidence.admin_events(resp)
        assert audit and audit[0]["outcome"] == "denied", f"{label}: not audited"
        rejected.append(resp)
    assert evidence.count("platform_role_bindings") == before, "stale auth created a binding"
    fresh = expect(bearer(e2e_env, idp.step_up_token("platform_admin"), "POST",
                          "/admin/v1/platform-role-bindings", _binding_body(world),
                          subject="platform_admin"), 201, "A36 fresh authentication accepted")
    expect(_revoke(world, world.pa_step_up(), fresh.body["id"]), 200, "A36 cleanup")


# --------------------------------------------------------------------------------------- A37
def test_A37_platform_role_never_widens_data_access(e2e_env, idp, world, evidence):
    world.need("roles", "company_one", "company_two", "uc1_grant", "group_grant")
    one, two = world.company_id("one"), world.company_id("two")
    world.ensure_uc1_access()
    baseline_uc1 = world.data_view("user_company_one")
    baseline_una = world.data_view("user_no_access")
    assert baseline_uc1.sees_company(one) and not baseline_uc1.sees_company(two), baseline_uc1
    assert not baseline_una.sees_source(world.source_id) and not baseline_una.companies, (
        f"precondition: user_no_access must have no data access, got {baseline_una}")
    grants_before = evidence.count("access_grants")

    stepped = world.pa_step_up()
    bindings = []
    try:
        for user, role in (("user_company_one", "AUDITOR"), ("user_no_access", "ACCESS_ADMIN")):
            created = expect(stepped.post("/admin/v1/platform-role-bindings", _binding_body(
                world, role=role, principal=world.sub(user), reason="A37 role/ACL boundary")),
                201, f"A37 bind {role} to {user}")
            bindings.append(created.body["id"])
        # The roles are real on the admin plane ...
        auditor = bearer(e2e_env, idp.token("user_company_one", audience="admin"), "GET",
                         "/admin/v1/audit", subject="user_company_one")
        access_admin = bearer(e2e_env, idp.token("user_no_access", audience="admin"), "GET",
                              "/admin/v1/grants", subject="user_no_access")
        assert auditor.status == 200 and access_admin.status == 200, (
            auditor.describe(), access_admin.describe())
        # ... and still grant no data-plane access.
        after_uc1 = world.data_view("user_company_one")
        after_una = world.data_view("user_no_access")
        assert after_uc1.sees_company(one) and not after_uc1.sees_company(two), after_uc1
        assert not after_una.sees_source(world.source_id) and not after_una.companies, (
            f"platform role widened data access for user_no_access: {after_una}")
        assert evidence.count("access_grants") == grants_before, "role binding created a grant"
    finally:
        cleanup = world.pa_step_up()
        for binding_id in bindings:
            expect(_revoke(world, cleanup, binding_id), 200, "A37 cleanup binding")
