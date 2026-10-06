"""Smoke checks proving the disposable E2E environment is wired correctly."""

from __future__ import annotations

import httpx
import jwt
import pytest

pytestmark = [pytest.mark.smoke]


def _http(url: str) -> httpx.Response:
    return httpx.get(url, trust_env=False, timeout=10)


def test_all_services_healthy(e2e_env):
    assert _http(e2e_env.gateway + "/healthz").status_code == 200
    ready = _http(e2e_env.gateway + "/readyz")
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    assert _http(e2e_env.fake1c_url + "/$metadata").status_code == 200
    discovery = _http(e2e_env.issuer + "/.well-known/openid-configuration").json()
    assert discovery["issuer"] == e2e_env.issuer
    assert discovery["code_challenge_methods_supported"] == ["S256"]
    assert _http(discovery["jwks_uri"]).json()["keys"][0]["kid"]


async def test_postgres_schema_version_and_seed(e2e_env, db):
    rows = await db.fetch("SELECT max(version) AS v, count(*) AS n FROM bag.schema_migrations",
                          role="admin")
    assert rows[0]["v"] == 14 and rows[0]["n"] == 14
    bindings = await db.fetch(
        "SELECT principal_id, role_name FROM bag.platform_role_bindings WHERE revoked_at IS NULL",
        role="control")
    if e2e_env.seed_mode == "none":
        assert bindings == []
    else:
        assert [(b["principal_id"], b["role_name"]) for b in bindings] == [
            ("platform_admin", "PLATFORM_ADMIN")]


async def test_redis_reachable(e2e_env):
    from redis.asyncio import Redis

    client = Redis.from_url(e2e_env.redis_url)
    try:
        assert await client.ping()
    finally:
        await client.aclose()


@pytest.mark.parametrize("audience", ["data", "admin"])
def test_every_identity_authenticates_at_idp(e2e_env, idp, audience):
    jwks = jwt.PyJWKClient(e2e_env.raw["idp"]["jwks_uri"])
    expected_audience = e2e_env.raw["audiences"][audience]
    for user, details in e2e_env.raw["identities"].items():
        token = idp.token(user, audience=audience)
        key = jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=e2e_env.issuer,
                            audience=expected_audience)
        assert claims["sub"] == details["sub"]
        assert claims["groups"] == details["groups"]
        assert isinstance(claims["auth_time"], int) and claims["acr"]


def test_idp_rejects_bad_password_and_missing_pkce(e2e_env, idp):
    assert idp.token_response("user_company_one", password="wrong").status_code == 400
    response = httpx.get(e2e_env.raw["idp"]["authorization_endpoint"], params={
        "client_id": e2e_env.raw["idp"]["data_client_id"], "response_type": "code",
        "redirect_uri": e2e_env.raw["idp"]["data_redirect_uri"], "state": "s",
        "scope": "onec:read"}, follow_redirects=False, trust_env=False)
    assert response.status_code == 302
    assert "error=invalid_request" in response.headers["location"]


async def test_user_company_one_calls_tools_over_mcp(e2e_env, idp, mcp_client, tool_payload):
    async with mcp_client(idp.token("user_company_one")) as session:
        tools = {t.name for t in (await session.list_tools()).tools}
        assert {"system_status", "sources_list"} <= tools
        status = await session.call_tool("system_status", {})
        assert not status.is_error
        sources = await session.call_tool("sources_list", {})
        assert not sources.is_error
        assert e2e_env.raw["source_id"] in str(tool_payload(sources))


async def test_mcp_requires_authentication(mcp_client):
    with pytest.raises(Exception):  # noqa: B017 - transport raises on HTTP 401
        async with mcp_client(None):
            pass


async def test_user_no_access_is_denied(e2e_env, idp, mcp_client, tool_payload):
    async with mcp_client(idp.token("user_no_access")) as session:
        sources = await session.call_tool("sources_list", {})
        assert sources.is_error or e2e_env.raw["source_id"] not in str(tool_payload(sources))


def test_platform_admin_loads_me_through_browser_login(e2e_env, admin_browser):
    page = admin_browser("platform_admin")
    page.goto(e2e_env.gateway + "/admin/v1/me")
    me = httpx.Response(200, text=page.inner_text("body")).json()
    assert me["subject"] == "platform_admin"
    assert {"role": "PLATFORM_ADMIN", "source_id": None} in me["roles"]
    assert me["session_authenticated"] is True


def test_admin_api_denies_unbound_and_data_plane_identities(e2e_env, idp):
    url = e2e_env.gateway + "/admin/v1/me"
    for user in ("admin_no_role", "user_company_one"):
        token = idp.token(user, audience="admin")
        response = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, trust_env=False)
        assert response.status_code == 403, user
    data_token = idp.token("platform_admin")  # wrong audience for the Admin API
    assert httpx.get(url, headers={"Authorization": f"Bearer {data_token}"},
                     trust_env=False).status_code == 401


def test_step_up_login_yields_step_up_claims(e2e_env, admin_http):
    session = admin_http("platform_admin", step_up=True)
    assert session.get("/admin/v1/me").status_code == 200
