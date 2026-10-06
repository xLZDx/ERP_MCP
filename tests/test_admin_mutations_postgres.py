from __future__ import annotations

import asyncio
import json
import os
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import asyncpg
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from business_ai_gateway.admin_access import explain_access
from business_ai_gateway.admin_api import AdminRepository, register_admin_routes
from business_ai_gateway.admin_mutations import (
    AdminActor,
    AdminConflict,
    AdminMutationService,
    AdminValidationError,
    _expiry,
)
from business_ai_gateway.business_policy import CapabilityDenied, CapabilityPolicy
from business_ai_gateway.db import Database
from business_ai_gateway.principal import Principal
from business_ai_gateway.runtime import Runtime
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings

URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL BAG_PRIVILEGE_TEST_DATABASE_URL")


@pytest.mark.parametrize("value", [None, "", "   "])
def test_expiry_empty_means_no_expiry(value):
    assert _expiry(value) is None


@pytest.mark.parametrize("value", ["not-a-date", "2026-10-06T12:00:00", 123, object()])
def test_expiry_rejects_malformed_and_naive_values(value):
    with pytest.raises(AdminValidationError):
        _expiry(value)


def test_expiry_normalizes_timezone_to_utc():
    assert _expiry("2026-10-06T15:00:00+03:00").isoformat() == "2026-10-06T12:00:00+00:00"


@pytest.fixture
async def service():
    owner = await asyncpg.connect(URL)
    source = f"acc-{uuid4()}"
    company = uuid4()
    await owner.execute("INSERT INTO bag.sources(source_id,project,kind,display_name,base_url) VALUES($1,'onec','onec_auto','ACC test','https://approved.test/odata')", source)
    await owner.execute("INSERT INTO bag.companies(company_id,source_id,external_ref,display_name) VALUES($1,$2,'org','Company')", company, source)

    async def control(conn):
        await conn.execute("SET ROLE business_ai_control_api")

    pool = await asyncpg.create_pool(URL, min_size=1, max_size=4, setup=control)
    assert await pool.fetchval("SELECT current_user") == "business_ai_control_api"
    svc = AdminMutationService(SimpleNamespace(require_pool=lambda: pool), production=False)
    yield svc, owner, source, company
    await pool.close()
    await owner.close()


def grant_args(source, company, key=None):
    return {"actor": AdminActor(str(uuid4()), "client"), "principal_kind": "subject", "principal_id": "subject-id",
            "source_id": source, "company_id": company, "effect": "allow", "expires_at": "2099-01-01T00:00:00Z",
            "reason": "integration test", "request_id": uuid4(), "idempotency_key": key or str(uuid4())}


@pytest.mark.asyncio
async def test_control_role_grant_replay_conflict_exact_revoke_and_audit(service):
    svc, owner, source, company = service
    args = grant_args(source, company)
    first = await svc.create_grant(**args)
    assert await svc.create_grant(**args) == first
    with pytest.raises(AdminConflict):
        await svc.create_grant(**{**args, "effect": "deny"})
    with pytest.raises(AdminConflict):
        await svc.revoke_grant(actor=args["actor"], grant_id=UUID(first["id"]), expected_version=99,
                               reason="stale revoke", request_id=uuid4(), idempotency_key=str(uuid4()))
    revoked = await svc.revoke_grant(actor=args["actor"], grant_id=UUID(first["id"]), expected_version=1,
                                   reason="exact revoke", request_id=uuid4(), idempotency_key=str(uuid4()))
    assert revoked["row_version"] == 2
    audit_rows = await owner.fetch(
        """
        SELECT action, outcome, company_id
        FROM bag.admin_audit_events
        WHERE actor_subject=$1
        """,
        args["actor"].subject,
    )
    assert {row["outcome"] for row in audit_rows} == {"success", "conflict"}
    revoke_success = next(
        row
        for row in audit_rows
        if row["action"] == "grant.revoke" and row["outcome"] == "success"
    )
    assert revoke_success["company_id"] == company


@pytest.mark.asyncio
async def test_concurrent_idempotency_has_one_logical_grant(service):
    svc, owner, source, company = service
    args = grant_args(source, company)
    results = await asyncio.gather(*(svc.create_grant(**args) for _ in range(4)), return_exceptions=True)
    assert all(isinstance(result, (dict, AdminConflict)) for result in results)
    successes = [result for result in results if isinstance(result, dict)]
    assert successes
    assert len({result["id"] for result in successes}) == 1
    assert await svc.create_grant(**args) == successes[0]
    assert await owner.fetchval("SELECT count(*) FROM bag.access_grants WHERE created_by_subject=$1", args["actor"].subject) == 1


@pytest.mark.asyncio
async def test_foreign_company_and_invalid_expiry_fail_without_policy_write(service):
    svc, owner, source, company = service
    args = grant_args(source, uuid4())
    with pytest.raises(AdminValidationError):
        await svc.create_grant(**args)
    with pytest.raises(AdminConflict):
        await svc.create_grant(**{**args, "company_id": company})
    with pytest.raises(AdminValidationError):
        await svc.create_grant(**{**grant_args(source, company), "expires_at": "tomorrow"})
    assert await owner.fetchval("SELECT count(*) FROM bag.access_grants WHERE created_by_subject=$1", args["actor"].subject) == 0


@pytest.mark.asyncio
async def test_effective_access_is_paginated_at_151_companies_and_explains_group_denies(service):
    _svc, owner, source, company = service
    await owner.executemany("INSERT INTO bag.companies(company_id,source_id,external_ref,display_name) VALUES($1,$2,$3,$3)",
                           [(uuid4(), source, f"company-{index}") for index in range(150)])
    await owner.execute("INSERT INTO bag.access_grants(grant_id,principal_kind,principal_id,source_id,effect) VALUES($1,'group','finance',$2,'allow')", uuid4(), source)
    await owner.execute("INSERT INTO bag.access_grants(grant_id,principal_kind,principal_id,source_id,company_id,effect) VALUES($1,'subject','employee',$2,$3,'deny')", uuid4(), source, company)
    ctx = SimpleNamespace(token=SimpleNamespace(subject="employee"), groups=frozenset({"finance"}))
    args = {"ctx": ctx, "kind": "subject", "principal_id": "employee", "source_id": source,
            "entity_set": "Document_Sale", "limit": 50, "offset": 0}
    pages, offset = [], 0
    while offset is not None:
        result = await explain_access(owner, **{**args, "offset": offset})
        assert len(result["items"]) <= 50
        pages.extend(result["items"])
        offset = result["next_offset"]
    assert len(pages) == 151
    denied = next(item for item in pages if item["company_id"] == str(company))
    assert denied["detail_code"] == "EXPLICIT_DENY"
    assert {g["inheritance"] for g in denied["matching_grants"]} == {"direct", "inherited"}
    assert all(item["company_operation"] == "unsupported_or_stale_mapping" for item in pages)
    unknown = await explain_access(owner, **{**args, "principal_id": "another-employee"})
    assert all(item["data_acl"] == "unknown" for item in unknown["items"])
    filtered = await explain_access(owner, **args, effect="deny", inheritance="direct")
    assert len(filtered["items"]) == 1


@pytest.mark.asyncio
async def test_production_control_db_check_rejects_owner_and_privileged_membership(service):
    _svc, owner, _source, _company = service
    db = Database(URL)
    db.pool = owner
    with pytest.raises(RuntimeError, match="least-privilege"):
        await db.assert_control_api_role()
    login = "acc_control_" + uuid4().hex
    await owner.execute(f"CREATE ROLE {login} LOGIN PASSWORD 'acc-disposable-test' INHERIT")
    await owner.execute(f"GRANT business_ai_control_api TO {login}")
    conn = await asyncpg.connect(URL, user=login, password="acc-disposable-test")
    try:
        db.pool = conn
        await db.assert_control_api_role()
        await owner.execute(f"GRANT business_ai_admin TO {login}")
        with pytest.raises(RuntimeError, match="least-privilege"):
            await db.assert_control_api_role()
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_production_runtime_credential_cannot_have_admin_permissions(service):
    _svc, owner, _source, _company = service
    db = Database(URL)
    db.pool = owner
    with pytest.raises(RuntimeError, match="least-privilege"):
        await db.assert_runtime_role()
    login = "acc_app_" + uuid4().hex
    await owner.execute(f"CREATE ROLE {login} LOGIN PASSWORD 'acc-disposable-test' INHERIT")
    await owner.execute(f"GRANT business_ai_app TO {login}")
    conn = await asyncpg.connect(URL, user=login, password="acc-disposable-test")
    try:
        db.pool = conn
        await db.assert_runtime_role()
        await owner.execute(f"GRANT business_ai_control_api TO {login}")
        with pytest.raises(RuntimeError, match="least-privilege"):
            await db.assert_runtime_role()
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_role_binding_assignment_override_replays_and_exact_revokes(service):
    svc, _owner, source, company = service
    common = {"actor": AdminActor(str(uuid4()), "client"), "principal_kind": "group",
              "principal_id": "finance", "source_id": source, "expires_at": "2099-01-01T00:00:00Z",
              "reason": "role lifecycle", "request_id": uuid4(), "idempotency_key": str(uuid4())}
    binding = await svc.create_platform_role(**common, role_name="SOURCE_ADMIN")
    assert await svc.create_platform_role(**common, role_name="SOURCE_ADMIN") == binding
    await svc.revoke_platform_role(actor=common["actor"], binding_id=UUID(binding["id"]), expected_version=1,
                                  reason="revoke exact binding", request_id=uuid4(), idempotency_key=str(uuid4()))
    args = {**common, "company_id": company, "idempotency_key": str(uuid4())}
    assignment = await svc.assign_business_role(**args, role_id="VIEWER")
    assert await svc.assign_business_role(**args, role_id="VIEWER") == assignment
    await svc.revoke_business_role(actor=common["actor"], assignment_id=UUID(assignment["id"]), expected_version=1,
                                  reason="revoke exact assignment", request_id=uuid4(), idempotency_key=str(uuid4()))
    args["idempotency_key"] = str(uuid4())
    override = await svc.create_capability_override(**args, capability_key="accounting.read", effect="deny")
    assert await svc.create_capability_override(**args, capability_key="accounting.read", effect="deny") == override
    await svc.revoke_capability_override(actor=common["actor"], override_id=UUID(override["id"]), expected_version=1,
                                        reason="revoke exact override", request_id=uuid4(), idempotency_key=str(uuid4()))


@pytest.mark.asyncio
async def test_global_non_platform_role_is_rejected_and_expired_binding_is_ineffective(service):
    svc, owner, source, _company = service
    base = {"actor": AdminActor(str(uuid4()), "client"), "principal_kind": "subject",
            "principal_id": f"expired-{uuid4()}", "expires_at": None, "reason": "test",
            "request_id": uuid4(), "idempotency_key": str(uuid4())}
    with pytest.raises(AdminValidationError, match="must be source-scoped"):
        await svc.create_platform_role(**base, role_name="AUDITOR", source_id=None)
    await owner.execute(
        """INSERT INTO bag.platform_role_bindings(binding_id,principal_kind,principal_id,role_name,source_id,expires_at)
           VALUES($1,'subject',$2,'ACCESS_ADMIN',$3,now()-interval '1 second')""",
        uuid4(), base["principal_id"], source,
    )
    repository = AdminRepository(SimpleNamespace(require_pool=lambda: owner))
    assert await repository.resolve_bindings(base["principal_id"], frozenset()) == ()
    revoked_principal = f"revoked-{uuid4()}"
    await owner.execute(
        """INSERT INTO bag.platform_role_bindings(binding_id,principal_kind,principal_id,role_name,source_id,revoked_at)
           VALUES($1,'subject',$2,'ACCESS_ADMIN',$3,now())""",
        uuid4(), revoked_principal, source,
    )
    assert await repository.resolve_bindings(revoked_principal, frozenset()) == ()


@pytest.mark.asyncio
async def test_company_scoped_capability_deny_blocks_unscoped_read(service):
    svc, owner, source, company = service
    subject = f"company-denied-{uuid4()}"
    await owner.execute(
        """INSERT INTO bag.capability_overrides(override_id,principal_kind,principal_id,capability_key,
           source_id,company_id,effect) VALUES($1,'subject',$2,'accounting.read',$3,$4,'deny')""",
        uuid4(), subject, source, company,
    )
    policy = CapabilityPolicy(svc.db, enabled=True)
    principal = Principal(subject, "client", frozenset(), frozenset(), {})
    with pytest.raises(CapabilityDenied):
        await policy.require(principal, "accounting.read", source_id=source)


@pytest.mark.asyncio
async def test_source_and_company_update_versions_audit_and_replay_without_probe(service):
    svc, owner, source, company = service
    calls = []

    async def preflight():
        calls.append("probe")

    actor = AdminActor(str(uuid4()), "client")
    args = {"actor": actor, "source_id": source, "expected_version": 1, "display_name": "Updated source",
            "base_url": "https://approved.test/odata", "username_secret_ref": "USER_REF", "password_secret_ref": "PASS_REF",
            "tags": [], "enabled": False, "reason": "Disable source", "request_id": uuid4(),
            "idempotency_key": str(uuid4()), "preflight": preflight}
    first = await svc.update_source(**args)
    assert first["row_version"] == 2 and first["enabled"] is False
    assert await svc.update_source(**args) == first
    assert calls == ["probe"]
    with pytest.raises(AdminConflict):
        await svc.update_source(**{**args, "idempotency_key": str(uuid4())})
    updated = await svc.update_company(actor=actor, company_id=company, expected_version=1, display_name="Updated company",
        legal_name=None, country_code="MD", enabled=False, is_default=False, reason="Disable company",
        request_id=uuid4(), idempotency_key=str(uuid4()))
    assert updated["row_version"] == 2 and updated["enabled"] is False
    success = await owner.fetch("SELECT before_fingerprint, after_fingerprint, safe_change_json FROM bag.admin_audit_events WHERE actor_subject=$1 AND outcome='success'", actor.subject)
    assert len(success) == 2
    assert all(row["before_fingerprint"] and row["after_fingerprint"] for row in success)


@pytest.mark.asyncio
async def test_connection_changes_stale_validated_profiles_even_with_identical_metadata(service):
    svc, owner, source, company = service
    profile = uuid4()
    evidence = {"native_reconciliation_cases": [{"case_id": str(index), "status": "PASS",
                 "native_report_ref": f"synthetic-native/{index}"} for index in range(10)]}
    await owner.execute("""INSERT INTO bag.semantic_profiles(profile_id,source_id,company_id,preset_id,
        profile_name,profile_version,status,metadata_fingerprint,capability_fingerprint,profile_fingerprint,
        preset_repository,preset_upstream_sha,created_by,validated_by,validated_at,validation_evidence_json)
        VALUES($1,$2,$3,'bp30','Synthetic profile',1,'VALIDATED','same-fp','cap-fp','profile-fp',
               'fixture','fixture','fixture','fixture',now(),$4::jsonb)""", profile, source, company, json.dumps(evidence))
    await svc.update_source(actor=AdminActor(str(uuid4()), "client"), source_id=source, expected_version=1,
        display_name="Repointed source", base_url="https://other-approved.test/odata", username_secret_ref="U",
        password_secret_ref="P", tags=[], enabled=True, reason="Connection change", request_id=uuid4(), idempotency_key=str(uuid4()))
    assert await owner.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile) == "STALE"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("BAG_ADMIN_TEST_REDIS_URL"), reason="requires disposable Redis BAG_ADMIN_TEST_REDIS_URL")
async def test_real_http_routes_oidc_session_csrf_policy_replay_and_logout(service):
    svc, owner, source, company = service
    subject = str(uuid4())
    await owner.execute("INSERT INTO bag.platform_role_bindings(binding_id,principal_kind,principal_id,role_name) VALUES($1,'subject',$2,'PLATFORM_ADMIN')", uuid4(), subject)
    settings = Settings(environment="test", database_url=URL, admin_control_database_url=URL,
        redis_url=os.environ["BAG_ADMIN_TEST_REDIS_URL"], oauth_enabled=True,
        public_mcp_url="https://gateway.test/mcp", oauth_issuer="https://identity.test/",
        oauth_audience="https://gateway.test/mcp", oauth_jwks_url="https://identity.test/jwks",
        admin_api_enabled=True, admin_mutations_enabled=True, admin_ui_enabled=True,
        admin_oauth_audience="https://gateway.test/admin", admin_oidc_client_id="admin-client",
        admin_oidc_authorization_url="https://identity.test/authorize", admin_oidc_token_url="https://identity.test/token",
        admin_oidc_redirect_uri="https://gateway.test/admin/callback")
    runtime = Runtime(settings)
    runtime.admin_db.pool = svc.db.require_pool()
    mcp = build_mcp(settings, runtime)
    api = register_admin_routes(mcp, settings, runtime)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    api.verifier._jwks = SimpleNamespace(get_signing_key_from_jwt=lambda raw: SimpleNamespace(key=key.public_key()))
    claims = {"iss": settings.oauth_issuer, "sub": subject, "iat": int(time.time()), "exp": int(time.time()) + 300,
              "aud": settings.admin_oauth_audience, "scope": "erp_mcp:admin", "azp": "admin-client"}
    access = jwt.encode(claims, key, algorithm="RS256")
    app = mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://gateway.test") as client:
            assert (await client.get("/admin/")).status_code == 200
            assert (await client.get("/admin/v1/me")).status_code == 401
            data_token = jwt.encode({**claims, "scope": "onec:read"}, key, algorithm="RS256")
            assert (await client.get("/admin/v1/me", headers={"Authorization": "Bearer " + data_token})).status_code == 401
            login = await client.get("/admin/login")
            assert login.status_code == 302
            query = parse_qs(urlparse(login.headers["location"]).query)

            async def token_endpoint(request):
                form = parse_qs(request.content.decode())
                assert form["grant_type"] == ["authorization_code"]
                assert form["code_verifier"][0]
                id_token = jwt.encode({**claims, "aud": "admin-client", "nonce": query["nonce"][0]}, key, algorithm="RS256")
                return httpx.Response(200, json={"access_token": access, "id_token": id_token})

            api.sessions.transport = httpx.MockTransport(token_endpoint)
            callback_url = "/admin/callback?code=synthetic-code&state=" + query["state"][0]
            callback = await client.get(callback_url)
            assert callback.status_code == 302
            assert "HttpOnly" in callback.headers.get_list("set-cookie")[-1]
            assert "SameSite=strict" in callback.headers.get_list("set-cookie")[-1]
            assert (await client.get(callback_url)).status_code == 400
            me = await client.get("/admin/v1/me")
            assert me.status_code == 200
            assert me.json()["session_authenticated"]
            csrf = me.json()["csrf_token"]
            roles = await client.get("/admin/v1/business-roles")
            assert isinstance(roles.json()["items"][0]["capabilities"], list)
            page = await client.get("/admin/v1/sources", params={"source_id": source, "limit": 1})
            assert len(page.json()["items"]) == 1
            assert page.json()["next_offset"] is None
            body = {"principal_kind": "subject", "principal_id": "http-employee", "source_id": source,
                    "company_id": str(company), "effect": "allow", "reason": "HTTP contract test"}
            headers = {"Idempotency-Key": str(uuid4())}
            assert (await client.post("/admin/v1/grants", json=body, headers=headers)).status_code == 403
            assert (await client.post("/admin/v1/grants", json=body, headers={**headers, "X-CSRF-Token": "wrong"})).status_code == 403
            headers["X-CSRF-Token"] = csrf
            first = await client.post("/admin/v1/grants", json=body, headers=headers)
            assert first.status_code == 201, first.text
            replay = await client.post("/admin/v1/grants", json=body, headers=headers)
            assert replay.json() == first.json()
            assert await owner.fetchval("SELECT count(*) FROM bag.access_grants WHERE created_by_subject=$1", subject) == 1
            assert (await client.post("/admin/logout", headers={"X-CSRF-Token": csrf})).status_code == 302
            assert (await client.get("/admin/v1/me")).status_code == 401
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("BAG_ADMIN_TEST_REDIS_URL"), reason="requires disposable Redis BAG_ADMIN_TEST_REDIS_URL")
async def test_real_http_cross_source_exact_target_mutations_have_no_write_side_effects(service):
    svc, owner, source_a, _company_a = service
    source_b = f"acc-target-{uuid4()}"
    company_b, grant_id, assignment_id, override_id, profile_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    subject = f"cross-source-{uuid4()}"
    await owner.execute(
        "INSERT INTO bag.sources(source_id,project,kind,display_name,base_url) VALUES($1,'onec','onec_auto','Target B','https://approved.test/odata')",
        source_b,
    )
    await owner.execute(
        "INSERT INTO bag.companies(company_id,source_id,external_ref,display_name) VALUES($1,$2,'org-b','Company B')",
        company_b, source_b,
    )
    await owner.executemany(
        """INSERT INTO bag.platform_role_bindings(binding_id,principal_kind,principal_id,role_name,source_id)
           VALUES($1,'subject',$2,$3,$4)""",
        [(uuid4(), subject, "ACCESS_ADMIN", source_a), (uuid4(), subject, "PROFILE_ADMIN", source_a)],
    )
    await owner.execute(
        """INSERT INTO bag.access_grants(grant_id,principal_kind,principal_id,source_id,company_id,effect)
           VALUES($1,'subject','victim',$2,$3,'allow')""",
        grant_id, source_b, company_b,
    )
    await owner.execute(
        """INSERT INTO bag.business_role_assignments(assignment_id,principal_kind,principal_id,role_id,source_id,company_id)
           VALUES($1,'subject','victim','VIEWER',$2,$3)""",
        assignment_id, source_b, company_b,
    )
    await owner.execute(
        """INSERT INTO bag.capability_overrides(override_id,principal_kind,principal_id,capability_key,source_id,company_id,effect)
           VALUES($1,'subject','victim','accounting.read',$2,$3,'deny')""",
        override_id, source_b, company_b,
    )
    await owner.execute(
        """INSERT INTO bag.semantic_profiles(profile_id,source_id,company_id,preset_id,profile_name,profile_version,status,
           metadata_fingerprint,capability_fingerprint,profile_fingerprint,preset_repository,preset_upstream_sha,created_by)
           VALUES($1,$2,$3,'bp30','Target B profile',1,'DRAFT','meta','caps','profile','fixture','fixture','fixture')""",
        profile_id, source_b, company_b,
    )
    settings = Settings(
        environment="test", database_url=URL, admin_control_database_url=URL,
        redis_url=os.environ["BAG_ADMIN_TEST_REDIS_URL"], oauth_enabled=True,
        public_mcp_url="https://gateway.test/mcp", oauth_issuer="https://identity.test/",
        oauth_audience="https://gateway.test/mcp", oauth_jwks_url="https://identity.test/jwks",
        admin_api_enabled=True, admin_mutations_enabled=True, admin_ui_enabled=False,
        admin_oauth_audience="https://gateway.test/admin",
    )
    runtime = Runtime(settings)
    runtime.admin_db.pool = svc.db.require_pool()
    mcp = build_mcp(settings, runtime)
    api = register_admin_routes(mcp, settings, runtime)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    api.verifier._jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _raw: SimpleNamespace(key=key.public_key()))
    claims = {
        "iss": settings.oauth_issuer, "sub": subject, "iat": int(time.time()),
        "exp": int(time.time()) + 300, "aud": settings.admin_oauth_audience,
        "scope": settings.admin_oauth_required_scope,
    }
    access = jwt.encode(claims, key, algorithm="RS256")
    app = mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True)
    routes = [
        (f"/admin/v1/grants/{grant_id}/revoke", {"expected_version": 1, "reason": "negative test"}),
        (f"/admin/v1/business-role-assignments/{assignment_id}/revoke", {"expected_version": 1, "reason": "negative test"}),
        (f"/admin/v1/capability-overrides/{override_id}/revoke", {"expected_version": 1, "reason": "negative test"}),
        (f"/admin/v1/semantic-profiles/{profile_id}/mappings", {"canonical_concept": "test", "mapping": {}, "reason": "negative test"}),
        (f"/admin/v1/semantic-profiles/{profile_id}/validate", {"validation_evidence": {}, "reason": "negative test"}),
        (f"/admin/v1/semantic-profiles/{profile_id}/retire", {"reason": "negative test"}),
        ("/admin/v1/company-scope-mappings", {"profile_id": str(profile_id), "entity_set": "Document_Test",
         "company_property": "Organization_Key", "literal_kind": "guid", "reason": "negative test"}),
    ]
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://gateway.test") as client:
            for path, body in routes:
                response = await client.post(
                    path, json=body,
                    headers={"Authorization": "Bearer " + access, "Idempotency-Key": str(uuid4())},
                )
                assert response.status_code == 403, (path, response.status_code, response.text)
        grant_after = await owner.fetchrow(
            "SELECT revoked_at,row_version FROM bag.access_grants WHERE grant_id=$1", grant_id
        )
        assignment_after = await owner.fetchrow(
            "SELECT revoked_at,row_version FROM bag.business_role_assignments WHERE assignment_id=$1", assignment_id
        )
        override_after = await owner.fetchrow(
            "SELECT revoked_at,row_version FROM bag.capability_overrides WHERE override_id=$1", override_id
        )
        profile_after = await owner.fetchrow(
            "SELECT status,profile_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        )
        assert tuple(grant_after.values()) == (None, 1)
        assert tuple(assignment_after.values()) == (None, 1)
        assert tuple(override_after.values()) == (None, 1)
        assert tuple(profile_after.values()) == ("DRAFT", "profile")
        assert await owner.fetchval("SELECT count(*) FROM bag.semantic_mappings WHERE profile_id=$1", profile_id) == 0
        assert await owner.fetchval("SELECT count(*) FROM bag.company_scope_mappings WHERE profile_id=$1", profile_id) == 0
        assert await owner.fetchval(
            "SELECT count(*) FROM bag.admin_audit_events WHERE actor_subject=$1 AND outcome='success'", subject
        ) == 0
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_failed_attempt_is_retryable_with_the_same_key_and_payload(service):
    """P8: a transient failure must not poison the idempotency key (A29/A30 stay intact)."""
    svc, owner, source, _company = service
    actor, key = AdminActor(str(uuid4()), "client"), str(uuid4())
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("source down")
        return {"metadata_fingerprint": "fp-1"}

    args = {"actor": actor, "source_id": source, "reason": "refresh", "request_id": uuid4(),
            "idempotency_key": key, "refresh": flaky}
    with pytest.raises(RuntimeError):
        await svc.refresh_capabilities(**args)
    again = await svc.refresh_capabilities(**{**args, "request_id": uuid4()})
    assert again == {"metadata_fingerprint": "fp-1"}
    # Replay of the now-successful attempt does not execute again.
    assert await svc.refresh_capabilities(**{**args, "request_id": uuid4()}) == again
    assert len(calls) == 2
    # Same key, different payload is still a conflict.
    with pytest.raises(AdminConflict):
        await svc.refresh_capabilities(**{**args, "source_id": source + "-other"})
    outcomes = [r["outcome"] for r in await owner.fetch(
        "SELECT outcome FROM bag.admin_audit_events WHERE actor_subject=$1 ORDER BY occurred_at",
        actor.subject)]
    assert outcomes[:2] == ["error", "success"]
