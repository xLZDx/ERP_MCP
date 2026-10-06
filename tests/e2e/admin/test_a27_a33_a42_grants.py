"""A27-A33 and A42: access grants created and revoked by ACCESS_ADMIN, proven on the data plane.

The data plane is exercised only through the public MCP endpoint with IdP-issued tokens
(``admin_support.data_view``). Policy changes must take effect without a gateway restart; the
tests wait on the observable data-plane state (bounded) rather than sleeping a fixed time.
"""

from __future__ import annotations

import time
import uuid

import pytest
from admin_support import data_view, expect, unique, wait_until

pytestmark = [pytest.mark.admin]

POLICY_PROPAGATION_SECONDS = 45


def _wait_view(world, user, predicate, what):
    started = time.monotonic()
    wait_until(lambda: predicate(world.data_view(user)), timeout=POLICY_PROPAGATION_SECONDS,
               interval=1.0, what=what)
    return time.monotonic() - started


def _grant_payload(world, principal, **extra):
    body = {"principal_kind": "subject", "principal_id": principal, "source_id": world.source_id,
            "company_id": None, "effect": "allow", "reason": "grant idempotency test"}
    body.update(extra)
    return body


# --------------------------------------------------------------------------------------- A27
def test_A27_access_admin_creates_subject_grant(e2e_env, world, evidence):
    step = world.ensure("uc1_grant")
    resp = expect(step.resp, 201, "A27 subject grant")
    row = world.grant_row(resp.body["id"])
    assert row["principal_kind"] == "subject" and row["principal_id"] == "user_company_one"
    assert str(row["company_id"]) == world.company_id("one") and row["effect"] == "allow"
    assert row["revoked_at"] is None and row["row_version"] == 1
    assert row["created_by_subject"] == "access_admin" and row["create_reason"]
    audit = evidence.admin_events(resp)
    assert len(audit) == 1 and audit[0]["action"] == "grant.create"
    assert audit[0]["actor_subject"] == "access_admin" and audit[0]["outcome"] == "success"
    world.need("company_two")
    _wait_view(world, "user_company_one", lambda v: v.sees_company(world.company_id("one")),
               "user_company_one sees company one after the grant")
    view = world.data_view("user_company_one")
    assert view.sees_source(world.source_id) and not view.sees_company(world.company_id("two"))


# --------------------------------------------------------------------------------------- A28
def test_A28_access_admin_creates_group_grant(e2e_env, world, evidence):
    world.need("company_one")
    step = world.ensure("group_grant")
    resp = expect(step.resp, 201, "A28 group grant")
    row = world.grant_row(resp.body["id"])
    assert row["principal_kind"] == "group" and row["principal_id"] == step.data["group"]
    assert str(row["company_id"]) == world.company_id("two") and row["effect"] == "allow"
    audit = evidence.admin_events(resp)
    assert len(audit) == 1 and audit[0]["action"] == "grant.create"
    _wait_view(world, "user_company_two", lambda v: v.sees_company(world.company_id("two")),
               "user_company_two sees company two through the group grant")
    view = world.data_view("user_company_two")
    assert not view.sees_company(world.company_id("one")), "group grant leaked company one"


# --------------------------------------------------------------------------------------- A29
def test_A29_idempotent_replay_returns_same_result_single_row(e2e_env, world, evidence):
    world.need("roles")
    aa = world.role_session("ACCESS_ADMIN")
    principal, key = unique("e2e-idem"), unique("idem-key")
    payload = _grant_payload(world, principal)
    first = expect(aa.post("/admin/v1/grants", payload, key=key), 201, "A29 first")
    replay = expect(aa.post("/admin/v1/grants", payload, key=key), 201, "A29 replay")
    again = expect(aa.post("/admin/v1/grants", payload, key=key), 201, "A29 second replay")
    assert first.body == replay.body == again.body, (first.body, replay.body)
    assert evidence.count("access_grants", "principal_id=$1", principal) == 1, "duplicate row"
    success = evidence.count("admin_audit_events",
                             "idempotency_key=$1 AND outcome='success'", key)
    assert success == 1, f"replay wrote {success} success audit rows"
    expect(world.revoke_grant(aa, first.body["id"]), 200, "A29 cleanup")


# --------------------------------------------------------------------------------------- A30
def test_A30_same_key_different_payload_conflicts(e2e_env, world, evidence):
    world.need("roles")
    aa = world.role_session("ACCESS_ADMIN")
    first_principal, second_principal, key = unique("e2e-a"), unique("e2e-b"), unique("idem-key")
    first = expect(aa.post("/admin/v1/grants", _grant_payload(world, first_principal), key=key),
                   201, "A30 first")
    for second_payload in (_grant_payload(world, second_principal),
                           _grant_payload(world, first_principal, effect="deny")):
        clash = aa.post("/admin/v1/grants", second_payload, key=key)
        assert clash.status == 409 and clash.body == {"error": "POLICY_VERSION_CONFLICT"}, (
            clash.describe())
        audit = evidence.admin_events(clash)
        assert audit and audit[0]["outcome"] == "conflict"
    assert evidence.count("access_grants", "principal_id=$1", second_principal) == 0
    rows = evidence.rows("SELECT effect, revoked_at FROM bag.access_grants WHERE principal_id=$1",
                         first_principal)
    assert [(r["effect"], r["revoked_at"]) for r in rows] == [("allow", None)], rows
    expect(world.revoke_grant(aa, first.body["id"]), 200, "A30 cleanup")


# --------------------------------------------------------------------------------------- A31
def test_A31_revoke_by_exact_grant_id_only(e2e_env, world, evidence):
    world.need("roles")
    aa = world.role_session("ACCESS_ADMIN")
    principal = unique("e2e-revoke")
    ids = [expect(world.scratch_grant(aa, principal=principal), 201, f"A31 create {i}").body["id"]
           for i in range(3)]
    target = ids[1]
    revoked = expect(world.revoke_grant(aa, target), 200, "A31 revoke exact")
    assert revoked.body["revoked"] is True and revoked.body["id"] == target
    states = {str(r["grant_id"]): r for r in evidence.rows(
        "SELECT grant_id, revoked_at, revoked_by_subject, row_version FROM bag.access_grants "
        "WHERE principal_id=$1", principal)}
    assert states[target]["revoked_at"] is not None
    assert states[target]["revoked_by_subject"] == "access_admin"
    for other in (ids[0], ids[2]):
        assert states[other]["revoked_at"] is None and states[other]["row_version"] == 1, (
            "revoking one grant touched another")
    audit = evidence.admin_events(revoked)
    assert audit and audit[0]["action"] == "grant.revoke" and str(audit[0]["target_id"]) == target
    again = world.revoke_grant(aa, target, version=2)
    assert again.status == 409, f"re-revoking must conflict: {again.describe()}"
    for other in (ids[0], ids[2]):
        expect(world.revoke_grant(aa, other), 200, "A31 cleanup")


# --------------------------------------------------------------------------------------- A32
def test_A32_stale_row_version_conflicts_without_lost_update(e2e_env, world, evidence):
    world.need("roles", "source")
    aa, pa = world.role_session("ACCESS_ADMIN"), world.pa
    grant = expect(world.scratch_grant(aa), 201, "A32 grant").body["id"]
    stale = world.revoke_grant(aa, grant, version=99)
    assert stale.status == 409 and stale.body == {"error": "POLICY_VERSION_CONFLICT"}
    row = world.grant_row(grant)
    assert row["revoked_at"] is None and row["row_version"] == 1, "stale revoke changed the grant"
    audit = evidence.admin_events(stale)
    assert audit and audit[0]["outcome"] == "conflict"
    expect(world.revoke_grant(aa, grant, version=1), 200, "A32 correct version succeeds")

    company = expect(pa.post("/admin/v1/companies", {
        "source_id": world.source_id, "external_ref": unique("e2e-a32"),
        "display_name": "version v1", "reason": "A32"}), 201, "A32 company").body["id"]

    def patch(version, name):
        return pa.patch(f"/admin/v1/companies/{company}", {
            "expected_version": version, "display_name": name, "enabled": True,
            "is_default": False, "reason": "A32 update"})

    expect(patch(1, "version v2"), 200, "A32 first writer")
    loser = patch(1, "lost update")
    assert loser.status == 409, loser.describe()
    row = evidence.one("SELECT display_name, row_version FROM bag.companies WHERE company_id=$1",
                       uuid.UUID(company))
    assert row == {"display_name": "version v2", "row_version": 2}, f"lost update: {row}"


# --------------------------------------------------------------------------------------- A33
def test_A33_revoke_denies_data_plane_without_restart(e2e_env, world, evidence):
    world.need("roles", "company_one", "company_two")
    aa = world.role_session("ACCESS_ADMIN")
    grant = world.ensure_uc1_access()
    company = world.company_id("one")
    _wait_view(world, "user_company_one", lambda v: v.sees_company(company),
               "baseline: user_company_one sees company one")
    try:
        row = world.grant_row(grant)
        revoked = expect(world.revoke_grant(aa, grant, version=row["row_version"]), 200,
                         "A33 revoke")
        latency = _wait_view(
            world, "user_company_one",
            lambda v: not v.sees_company(company) and not v.sees_source(world.source_id),
            "user_company_one denied after the revoke")
        audit = evidence.admin_events(revoked)
        assert audit and audit[0]["action"] == "grant.revoke"
        view = world.data_view("user_company_one")
        assert not view.sees_company(company), f"access persisted after revoke ({latency:.1f}s)"
        uc2 = world.data_view("user_company_two")
        assert uc2.sees_company(world.company_id("two")), "revoke affected another principal"
    finally:
        restored = world.ensure_uc1_access()
        assert restored
        _wait_view(world, "user_company_one", lambda v: v.sees_company(company),
                   "baseline restored for user_company_one")


# --------------------------------------------------------------------------------------- A42
def test_A42_explicit_deny_wins_over_allow(e2e_env, world, evidence):
    world.need("roles", "company_one", "company_two")
    aa = world.role_session("ACCESS_ADMIN")
    allow_id = world.ensure_uc1_access()
    company = world.company_id("one")
    _wait_view(world, "user_company_one", lambda v: v.sees_company(company),
               "baseline: allow works")
    deny_id = None
    try:
        deny = expect(aa.post("/admin/v1/grants", {
            "principal_kind": "subject", "principal_id": "user_company_one",
            "source_id": world.source_id, "company_id": company, "effect": "deny",
            "reason": "A42 explicit deny"}), 201, "A42 deny grant")
        deny_id = deny.body["id"]
        allow_row = world.grant_row(allow_id)
        assert allow_row["revoked_at"] is None and allow_row["effect"] == "allow", (
            "precondition: the allow grant must still be active next to the deny")
        _wait_view(world, "user_company_one", lambda v: not v.sees_company(company),
                   "deny wins over the still-active allow")
        explained = expect(aa.get("/admin/v1/effective-access", params={
            "kind": "subject", "id": "user_company_one", "source_id": world.source_id}), 200,
            "A42 effective access")
        assert "deny" in explained.text, "effective-access does not show the deny"
        uc2 = world.data_view("user_company_two")
        assert uc2.sees_company(world.company_id("two")), "deny leaked to another principal"
    finally:
        if deny_id:
            row = world.grant_row(deny_id)
            if row["revoked_at"] is None:
                expect(world.revoke_grant(aa, deny_id, version=row["row_version"]), 200,
                       "A42 remove deny")
    _wait_view(world, "user_company_one", lambda v: v.sees_company(company),
               "access recovers once the deny is revoked")
    assert data_view(e2e_env, world.data_token("user_company_one"), world.source_id
                     ).sees_company(company)
