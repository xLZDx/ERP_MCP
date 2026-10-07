from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from business_ai_gateway.admin_api import AdminAPI, AdminRoleBinding
from business_ai_gateway.rate_limit import RateLimitExceeded


def request(path="/admin/", *, authorization=None):
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("mcp.example.test", 443),
        }
    )


@pytest.mark.asyncio
async def test_admin_ui_sets_browser_security_headers():
    api = object.__new__(AdminAPI)

    response = await AdminAPI.admin_ui(api, request())

    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_oidc_route_dependency_failures_are_redacted():
    class BrokenSessions:
        async def login(self, _request):
            raise RuntimeError("secret redis detail")

        async def callback(self, _request):
            raise RuntimeError("secret idp detail")

    api = object.__new__(AdminAPI)
    api.sessions = BrokenSessions()

    login = await AdminAPI.login(api, request("/admin/login"))
    callback = await AdminAPI.callback(api, request("/admin/callback"))

    assert login.status_code == 503
    assert login.body == b'{"error":"OIDC_LOGIN_UNAVAILABLE"}'
    assert callback.status_code == 401
    assert callback.body == b'{"error":"OIDC_LOGIN_FAILED"}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side_effect", "expected_status", "expected_error"),
    [
        (RateLimitExceeded("limit"), 429, b'{"error":"RATE_LIMITED"}'),
        (
            ConnectionError("redis unavailable"),
            503,
            b'{"error":"ADMIN_DEPENDENCY_UNAVAILABLE"}',
        ),
    ],
)
async def test_admin_rate_limit_fails_closed(side_effect, expected_status, expected_error):
    api = object.__new__(AdminAPI)
    api.sessions = None
    api.verifier = SimpleNamespace(
        verify_token=AsyncMock(
            return_value=SimpleNamespace(
                subject="admin-subject",
                client_id="admin-client",
                claims={"groups": []},
            )
        )
    )
    api.runtime = SimpleNamespace(
        start=AsyncMock(),
        rate_limit=SimpleNamespace(check=AsyncMock(side_effect=side_effect)),
    )
    api.repository = SimpleNamespace(
        resolve_bindings=AsyncMock(
            return_value=(AdminRoleBinding("PLATFORM_ADMIN", None),)
        )
    )

    response = await AdminAPI.authenticate(
        api, request("/admin/v1/me", authorization="Bearer token")
    )

    assert response.status_code == expected_status
    assert response.body == expected_error
    api.repository.resolve_bindings.assert_not_awaited()


def test_platform_role_step_up_requires_approved_recent_acr(monkeypatch):
    api = object.__new__(AdminAPI)
    api.settings = SimpleNamespace(
        admin_step_up_acr_values="urn:mfa,urn:phishing-resistant"
    )
    monkeypatch.setattr("business_ai_gateway.admin_api.time.time", lambda: 1000)
    token = SimpleNamespace(
        claims={"acr": "urn:mfa", "auth_time": 800},
    )
    ctx = SimpleNamespace(token=token)

    assert AdminAPI._step_up_guard(api, ctx) is None

    stale = SimpleNamespace(token=SimpleNamespace(claims={"acr": "urn:mfa", "auth_time": 600}))
    denied = AdminAPI._step_up_guard(api, stale)
    assert denied.status_code == 403
    assert denied.body == b'{"error":"STEP_UP_REQUIRED"}'


def test_platform_role_step_up_fails_closed_when_not_configured():
    api = object.__new__(AdminAPI)
    api.settings = SimpleNamespace(admin_step_up_acr_values="")
    ctx = SimpleNamespace(
        token=SimpleNamespace(claims={"acr": "urn:mfa", "auth_time": 1})
    )

    denied = AdminAPI._step_up_guard(api, ctx)

    assert denied.status_code == 403
