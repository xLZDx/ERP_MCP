"""A43-A44: the administrative audit view and the append-only guarantee of audit history."""

from __future__ import annotations

import pytest
from admin_support import (
    JWT_LIKE,
    attempt_sql,
    data_view,
    expect,
    find_leaks,
    secret_values,
)

pytestmark = [pytest.mark.admin]

ADMIN_AUDIT_COLUMNS = {
    "event_id", "occurred_at", "request_id", "actor_subject", "actor_client_id", "action",
    "target_type", "target_id", "source_id", "company_id", "reason", "idempotency_key",
    "policy_version", "before_fingerprint", "after_fingerprint", "safe_change_json", "outcome",
    "detail_code"}
ACCESS_AUDIT_COLUMNS = {
    "event_id", "occurred_at", "request_id", "principal_subject", "client_id", "tool_name",
    "source_id", "company_id", "outcome", "returned_items", "duration_ms", "detail_code",
    "adapter_kind", "adapter_version", "upstream_sha", "policy_version", "metadata_fingerprint",
    "response_bytes", "truncated"}


# --------------------------------------------------------------------------------------- A43
def test_A43_auditor_sees_complete_admin_audit_without_secrets(e2e_env, world):
    world.need("roles", "company_one", "uc1_grant")
    pa, aud = world.pa, world.role_session("AUDITOR")
    # Produce one success and one conflict in the auditor's scope right now.
    created = expect(world.scratch_grant(world.role_session("ACCESS_ADMIN")), 201, "A43 grant")
    duplicate = pa.post("/admin/v1/companies", {
        "source_id": world.source_id, "external_ref": e2e_env.raw["companies"]["one"],
        "display_name": "dup", "reason": "A43 conflict row"})
    assert duplicate.status == 409
    expect(world.revoke_grant(world.role_session("ACCESS_ADMIN"), created.body["id"]), 200,
           "A43 cleanup")

    listing = expect(aud.get("/admin/v1/audit", params={"limit": 200}), 200, "A43 audit view")
    events = listing.body["admin"]
    assert events, "auditor sees no admin audit events"
    by_request = {e["request_id"]: e for e in events}
    success = by_request[str(created.request_uuid)]
    conflict = by_request[str(duplicate.request_uuid)]

    for event, request in ((success, created), (conflict, duplicate)):
        assert set(event) == ADMIN_AUDIT_COLUMNS, (
            f"audit row shape changed: {sorted(set(event) ^ ADMIN_AUDIT_COLUMNS)}")
        assert event["actor_subject"] == "access_admin" or event is conflict
        assert event["actor_client_id"] == e2e_env.raw["idp"]["admin_client_id"]
        assert event["action"] and event["target_type"] and event["reason"]
        assert event["source_id"] == world.source_id
        assert event["idempotency_key"] == request.idem_key
        assert event["request_id"] == request.request_id
        assert event["outcome"] and event["occurred_at"] and event["policy_version"]
    assert success["outcome"] == "success" and success["target_id"] == created.body["id"]
    assert success["action"] == "grant.create" and success["after_fingerprint"]
    assert conflict["outcome"] == "conflict" and conflict["detail_code"]
    assert conflict["actor_subject"] == "platform_admin"

    for row in listing.body["access"]:
        assert set(row) == ACCESS_AUDIT_COLUMNS, "runtime audit row exposes unexpected columns"
    assert not find_leaks(listing.text, secret_values(e2e_env)), "secret value in audit view"
    assert not JWT_LIKE.search(listing.text), "token in audit view"
    for event in events:
        assert "password" not in str(event["safe_change_json"]).lower().replace(
            "password_secret_ref", ""), "credential-like content in safe_change_json"


# --------------------------------------------------------------------------------------- A44
AUDIT_TABLES = ("audit_events", "admin_audit_events")
ROLES = ("app", "control", "admin")  # runtime, control API and admin login roles


def test_A44_audit_history_is_append_only_for_runtime_and_control_roles(e2e_env, world,
                                                                        evidence):
    world.need("source", "company_one", "uc1_grant")
    world.ensure_uc1_access()
    data_view(e2e_env, world.data_token("user_company_one"), world.source_id)  # runtime audit rows
    # Instrument check: the same helper must report success for a harmless statement.
    ok = attempt_sql(e2e_env, "control", "SELECT count(*) FROM bag.admin_audit_events")
    assert ok[0] == "success", f"SQL probe instrument is broken: {ok}"
    targets = {}
    for table in AUDIT_TABLES:
        row = evidence.one(f"SELECT event_id FROM bag.{table} ORDER BY occurred_at DESC LIMIT 1")
        assert row, f"precondition: bag.{table} has no rows to target"
        targets[table] = row["event_id"]

    failures = []
    for role in ROLES:
        for table in AUDIT_TABLES:
            statements = {
                "UPDATE": (f"UPDATE bag.{table} SET detail_code='tamper' WHERE event_id=$1",
                           (targets[table],)),
                "UPDATE-all": (f"UPDATE bag.{table} SET detail_code='tamper'", ()),
                "DELETE": (f"DELETE FROM bag.{table} WHERE event_id=$1", (targets[table],)),
                "DELETE-all": (f"DELETE FROM bag.{table}", ()),
                "TRUNCATE": (f"TRUNCATE bag.{table}", ()),
            }
            for name, (sql, args) in statements.items():
                outcome, sqlstate, message = attempt_sql(e2e_env, role, sql, *args)
                if outcome != "error" or sqlstate != "42501":
                    failures.append(f"{role}/{table}/{name}: {outcome} {sqlstate} {message[:80]}")
    assert not failures, "audit history is mutable or denied for the wrong reason:\n" + "\n".join(
        failures)
    for table in AUDIT_TABLES:  # rows are still there, untouched
        assert evidence.scalar(f"SELECT count(*) AS n FROM bag.{table} WHERE detail_code="
                               "'tamper'") == 0
