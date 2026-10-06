from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.requests import Request

from business_ai_gateway.admin_api import AdminAPI
from business_ai_gateway.admin_session import AdminSessionManager
from business_ai_gateway.settings import Settings


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def ping(self):
        return True

    async def setex(self, key, _ttl, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, key):
        self.data.pop(key, None)

    async def getdel(self, key):
        return self.data.pop(key, None)


class FakeVerifier:
    async def verify_token(self, _token):
        return SimpleNamespace(
            subject="admin-1",
            expires_at=int(time.time()) + 3600,
        )


def request(path="/admin/", *, query="", cookies=None, headers=None):
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    if cookies:
        raw_headers.append(
            (
                b"cookie",
                "; ".join(f"{key}={value}" for key, value in cookies.items()).encode(),
            )
        )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )


def settings():
    return Settings(
        environment="test",
        oauth_enabled=True,
        oauth_issuer="https://id.example.test/",
        oauth_audience="https://mcp.example.test/mcp",
        oauth_jwks_url="https://id.example.test/jwks",
        admin_api_enabled=True,
        admin_ui_enabled=True,
        admin_oauth_audience="https://mcp.example.test/admin",
        admin_oidc_authorization_url="https://id.example.test/authorize",
        admin_oidc_token_url="https://id.example.test/token",
        admin_oidc_client_id="erp-admin",
        admin_oidc_redirect_uri="http://127.0.0.1:8000/admin/callback",
    )


@pytest.mark.asyncio
async def test_login_uses_state_nonce_pkce_and_httponly_login_cookie():
    redis = FakeRedis()
    manager = AdminSessionManager(settings(), redis, FakeVerifier())

    response = await manager.login(request("/admin/login"))

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.path == "/authorize"
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"][0]
    assert query["state"][0]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert manager._login_key(query["state"][0]) in redis.data


@pytest.mark.asyncio
async def test_callback_creates_opaque_session_and_deletes_one_time_login_state(monkeypatch):
    redis = FakeRedis()
    state = "state-1"
    redis.data[f"erp_mcp:admin:login:{state}"] = json.dumps(
        {"nonce": "nonce-1", "verifier": "verifier-1", "created_at": 1}
    )

    async def token_endpoint(_request):
        return httpx.Response(
            200,
            json={"access_token": "access.jwt", "id_token": "id.jwt"},
        )

    manager = AdminSessionManager(
        settings(),
        redis,
        FakeVerifier(),
        transport=httpx.MockTransport(token_endpoint),
    )

    async def verify_id_token(_raw, *, nonce):
        assert nonce == "nonce-1"
        return {"sub": "admin-1"}

    monkeypatch.setattr(manager, "_verify_id_token", verify_id_token)

    response = await manager.callback(
        request(
            "/admin/callback",
            query=f"code=code-1&state={state}",
            cookies={manager.LOGIN_COOKIE: state},
        )
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin/"
    assert manager._login_key(state) not in redis.data
    sessions = [key for key in redis.data if key.startswith("erp_mcp:admin:session:")]
    assert len(sessions) == 1
    record = json.loads(redis.data[sessions[0]])
    assert record["access_token"] == "access.jwt"
    assert record["csrf_token"]
    assert "HttpOnly" in response.headers.getlist("set-cookie")[-1]
    assert "SameSite=strict" in response.headers.getlist("set-cookie")[-1]


@pytest.mark.asyncio
async def test_session_resolution_is_idle_and_absolute_expiry_bounded(monkeypatch):
    redis = FakeRedis()
    manager = AdminSessionManager(settings(), redis, FakeVerifier())
    monkeypatch.setattr("business_ai_gateway.admin_session.time.time", lambda: 1000)
    redis.data[manager._session_key("sid")] = json.dumps(
        {
            "access_token": "token",
            "csrf_token": "csrf",
            "subject": "admin-1",
            "last_seen": 990,
            "absolute_expires_at": 1200,
        }
    )

    result = await manager.resolve(
        request("/admin/v1/me", cookies={manager.SESSION_COOKIE: "sid"})
    )

    assert result is not None
    assert result.session_id == "sid"
    assert result.csrf_token == "csrf"


@pytest.mark.asyncio
async def test_cookie_session_mutation_requires_matching_csrf_token():
    redis = FakeRedis()
    manager = AdminSessionManager(settings(), redis, FakeVerifier())
    redis.data[manager._session_key("sid")] = json.dumps(
        {
            "access_token": "token",
            "csrf_token": "csrf",
            "subject": "admin-1",
            "last_seen": int(time.time()),
            "absolute_expires_at": int(time.time()) + 3600,
        }
    )
    api = object.__new__(AdminAPI)
    api.sessions = manager

    denied = await AdminAPI.csrf_guard(
        api,
        request(
            "/admin/v1/grants",
            cookies={manager.SESSION_COOKIE: "sid"},
            headers={"x-csrf-token": "wrong"},
        ),
    )
    allowed = await AdminAPI.csrf_guard(
        api,
        request(
            "/admin/v1/grants",
            cookies={manager.SESSION_COOKIE: "sid"},
            headers={"x-csrf-token": "csrf"},
        ),
    )

    assert denied.status_code == 403
    assert allowed is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["endpoint", "nonce", "subject", "access"])
async def test_callback_failures_are_safe_and_state_cannot_be_replayed(monkeypatch, failure):
    redis = FakeRedis()
    redis.data["erp_mcp:admin:login:state"] = json.dumps(
        {"nonce": "nonce", "verifier": "verifier"}
    )

    async def endpoint(_request):
        if failure == "endpoint":
            return httpx.Response(500, text="sensitive upstream message")
        return httpx.Response(200, json={"access_token": "access", "id_token": "id"})

    manager = AdminSessionManager(settings(), redis, FakeVerifier(), transport=httpx.MockTransport(endpoint))

    async def verify_id(_raw, *, nonce):
        if failure == "nonce":
            raise PermissionError("sensitive verification detail")
        return {"sub": "other" if failure == "subject" else "admin-1"}

    monkeypatch.setattr(manager, "_verify_id_token", verify_id)
    if failure == "access":
        async def invalid(_token):
            return None
        monkeypatch.setattr(manager.verifier, "verify_token", invalid)
    req = request("/admin/callback", query="code=c&state=state", cookies={manager.LOGIN_COOKIE: "state"})
    first, second = await asyncio.gather(manager.callback(req), manager.callback(req))
    assert first.status_code in {401, 502}
    assert second.status_code == 400
    assert "sensitive" not in first.body.decode()
    assert not any(":session:" in key for key in redis.data)


@pytest.mark.asyncio
@pytest.mark.parametrize("absolute,last_seen", [(1000, 999), (5000, 0)])
async def test_expired_sessions_are_invalidated(monkeypatch, absolute, last_seen):
    redis = FakeRedis()
    manager = AdminSessionManager(settings(), redis, FakeVerifier())
    monkeypatch.setattr("business_ai_gateway.admin_session.time.time", lambda: 2000)
    redis.data[manager._session_key("sid")] = json.dumps({
        "access_token": "token", "csrf_token": "csrf", "last_seen": last_seen,
        "absolute_expires_at": absolute,
    })
    assert await manager.resolve(request(cookies={manager.SESSION_COOKIE: "sid"})) is None
    assert manager._session_key("sid") not in redis.data


@pytest.mark.asyncio
async def test_logout_invalidates_server_session():
    redis = FakeRedis()
    manager = AdminSessionManager(settings(), redis, FakeVerifier())
    redis.data[manager._session_key("sid")] = "record"
    result = await manager.logout(request(cookies={manager.SESSION_COOKIE: "sid"}))
    assert manager._session_key("sid") not in redis.data
    assert "Max-Age=0" in result.headers["set-cookie"]


@pytest.mark.asyncio
async def test_bearer_authentication_does_not_require_cookie_csrf():
    api = object.__new__(AdminAPI)
    api.sessions = AdminSessionManager(settings(), FakeRedis(), FakeVerifier())
    req = request(cookies={api.sessions.SESSION_COOKIE: "expired"}, headers={"authorization": "Bearer explicit-token"})
    assert await api.csrf_guard(req) is None
