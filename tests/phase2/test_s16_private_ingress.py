"""Private S16 ingress request-boundary tests using ASGI only; no listener is started."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from starlette.testclient import TestClient

from erp_mcp_s16.contracts import ApproverSession
from erp_mcp_s16.ingress import PrivateNetworkConfig, RouteAssessment, create_private_s16_app
from s16_helpers import ORIGIN, build_env


class _Authenticator:
    def __init__(self, env):
        self.env = env

    def authenticate(self, _scope, headers):
        now = datetime.now(UTC)
        if headers.get("authorization") == "Bearer synthetic-write":
            return replace(self.env.requester, expires_at=now + timedelta(hours=1))
        if headers.get("authorization") == "Bearer synthetic-read":
            from erp_mcp_s16.contracts import TokenClass
            return replace(self.env.requester, token_class=TokenClass.READ_ONLY)
        if headers.get("authorization") == "Bearer synthetic-expired":
            return replace(self.env.requester, expires_at=now - timedelta(seconds=1))
        if headers.get("authorization") == "Bearer synthetic-approver":
            principal = replace(self.env.session.principal, expires_at=now + timedelta(minutes=10))
            return replace(self.env.session, principal=principal,
                           idle_expires_at=now + timedelta(minutes=5),
                           expires_at=now + timedelta(minutes=10))
        if headers.get("authorization") == "Bearer synthetic-malformed-approver":
            principal = replace(self.env.session.principal, principal_id="",
                                expires_at=now + timedelta(minutes=10))
            return replace(self.env.session, principal=principal,
                           idle_expires_at=now + timedelta(minutes=5),
                           expires_at=now + timedelta(minutes=10))
        return None


class _RouteProbe:
    def __init__(self, assessment=None):
        self.assessment = assessment
        self.calls = []

    def assess(self, address, *, port):
        self.calls.append((address, port))
        return self.assessment or RouteAssessment((address,))


def _app(env, probe, calls):
    async def tool_app(scope, receive, send):
        calls.append(("tool", scope["path"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def approval_app(scope, receive, send):
        calls.append(("approval", scope["path"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = create_private_s16_app(
        tool_app, approval_app, _Authenticator(env), probe,
        PrivateNetworkConfig(origin=ORIGIN),
    )

    return TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 49000))


def _host():
    return {"host": "127.0.0.1:8443"}


def test_private_ingress_allows_positive_authenticated_private_request():
    env = build_env()
    calls = []
    probe = _RouteProbe()
    response = _app(env, probe, calls).post(
        "/mcp", headers={**_host(), "authorization": "Bearer synthetic-write"}, json={"method": "tools/list"},
    )
    assert response.status_code == 200
    assert calls == [("tool", "/mcp")]
    assert probe.calls == [("127.0.0.1", 8443)]


def test_private_ingress_allows_positive_approver_session_on_approval_route():
    env = build_env()
    calls = []
    response = _app(env, _RouteProbe(), calls).get(
        "/approval/pending", headers={**_host(), "authorization": "Bearer synthetic-approver"},
    )
    assert response.status_code == 200
    assert calls == [("approval", "/approval/pending")]


def test_private_ingress_rejects_malformed_approver_principal_before_approval_dispatch():
    env = build_env()
    calls = []
    response = _app(env, _RouteProbe(), calls).get(
        "/approval/pending",
        headers={**_host(), "authorization": "Bearer synthetic-malformed-approver"},
    )
    assert response.status_code == 403
    assert calls == []


def test_private_ingress_rejects_missing_auth_forwarding_host_and_foreign_origin_before_downstream():
    env = build_env()
    calls = []
    probe = _RouteProbe()
    client = _app(env, probe, calls)

    missing = client.post("/mcp", headers=_host(), json={})
    wrong_token = client.post("/mcp", headers={**_host(), "authorization": "Bearer synthetic-read"}, json={})
    expired = client.post("/mcp", headers={**_host(), "authorization": "Bearer synthetic-expired"}, json={})
    forwarded = client.post("/mcp", headers={**_host(), "authorization": "Bearer synthetic-write",
                                               "x-forwarded-host": "public.example"}, json={})
    wrong_host = client.post("/mcp", headers={"host": "public.example", "authorization": "Bearer synthetic-write"},
                             json={})
    foreign_origin = client.post(
        "/approval/pending/decision",
        headers={**_host(), "authorization": "Bearer synthetic-approver", "origin": "https://attacker.invalid",
                 "referer": "https://attacker.invalid/approval/pending"},
        data="decision=APPROVE",
    )
    assert missing.status_code == wrong_token.status_code == expired.status_code == 403
    assert forwarded.status_code == wrong_host.status_code == foreign_origin.status_code == 400 or (
        foreign_origin.status_code == 403 and forwarded.status_code == wrong_host.status_code == 400
    )
    assert calls == []


def test_private_ingress_refuses_proxy_redirect_and_unresolved_route_assessments():
    env = build_env()
    for assessment in (
        RouteAssessment(("127.0.0.1",), redirects=True),
        RouteAssessment(("127.0.0.1",), proxy_used=True),
        RouteAssessment((), unresolved=True),
    ):
        calls = []
        response = _app(env, _RouteProbe(assessment), calls).post(
            "/mcp", headers={**_host(), "authorization": "Bearer synthetic-write"}, json={})
        assert response.status_code == 400
        assert calls == []
