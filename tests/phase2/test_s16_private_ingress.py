"""Private S16 ingress request-boundary tests using ASGI only; no listener is started."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
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
                           created_at=now, last_seen_at=now,
                           idle_expires_at=now + timedelta(minutes=5),
                           expires_at=now + timedelta(minutes=10))
        if headers.get("authorization") == "Bearer synthetic-malformed-approver":
            principal = replace(self.env.session.principal, principal_id="",
                                expires_at=now + timedelta(minutes=10))
            return replace(self.env.session, principal=principal,
                           created_at=now, last_seen_at=now,
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


def _asgi_app(env, probe, calls, *, config=None):
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
        config or PrivateNetworkConfig(origin=ORIGIN),
    )
    return app


def _app(env, probe, calls):
    return TestClient(_asgi_app(env, probe, calls), base_url=ORIGIN, client=("127.0.0.1", 49000))


def _host():
    return {"host": "127.0.0.1:8443"}


def _post_scope(headers):
    return {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "https", "path": "/mcp", "raw_path": b"/mcp",
        "query_string": b"", "headers": [(k.encode("latin-1"), v.encode("latin-1"))
                                             for k, v in headers.items()],
        "client": ("127.0.0.1", 49000), "server": ("127.0.0.1", 8443),
    }


def _run_asgi(app, scope, messages):
    pending = iter(messages)
    sent = []

    async def receive():
        return next(pending)

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


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


@pytest.mark.parametrize("emit_start,expected_statuses", [(False, []), (True, [200])])
def test_private_ingress_propagates_downstream_failure_without_synthesizing_second_response(
        emit_start, expected_statuses):
    env = build_env()
    sent = []

    async def failing_downstream(_scope, _receive, send):
        if emit_start:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("downstream failed")

    app = create_private_s16_app(
        failing_downstream, failing_downstream, _Authenticator(env), _RouteProbe(),
        PrivateNetworkConfig(origin=ORIGIN),
    )
    scope = _post_scope({**_host(), "authorization": "Bearer synthetic-write"})
    scope["method"] = "GET"

    async def receive():
        raise AssertionError("GET downstream does not need a request body")

    async def capture(message):
        sent.append(message)

    with pytest.raises(RuntimeError, match="downstream failed"):
        asyncio.run(app(scope, receive, capture))

    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert [message["status"] for message in starts] == expected_statuses
    assert all(message["status"] != 400 for message in starts)


def test_private_ingress_fails_closed_for_malicious_scope_type_before_auth_or_dispatch():
    class MaliciousScopeType:
        def __eq__(self, _other):
            raise RuntimeError("scope type comparison must not escape the boundary")

    class Authenticator:
        def __init__(self):
            self.calls = 0

        def authenticate(self, _scope, _headers):
            self.calls += 1
            return None

    downstream_calls = []
    auth = Authenticator()
    probe = _RouteProbe()

    async def downstream(_scope, _receive, _send):
        downstream_calls.append("called")

    app = create_private_s16_app(
        downstream, downstream, auth, probe, PrivateNetworkConfig(origin=ORIGIN),
    )
    sent = _run_asgi(app, {"type": MaliciousScopeType()}, [])

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 400
    assert auth.calls == 0
    assert probe.calls == []
    assert downstream_calls == []


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


def test_private_ingress_rejects_huge_decimal_content_length_before_route_or_downstream():
    env = build_env()
    calls = []
    probe = _RouteProbe()
    app = _asgi_app(env, probe, calls)
    scope = _post_scope({**_host(), "authorization": "Bearer synthetic-write",
                         "content-length": "9" * 1024})
    sent = _run_asgi(app, scope, [{"type": "http.request", "body": b"", "more_body": False}])

    assert sent[0]["status"] == 413
    assert probe.calls == []
    assert calls == []


def test_private_ingress_rejects_explicit_zero_origin_port():
    env = build_env()
    calls = []
    probe = _RouteProbe()

    with pytest.raises(ValueError, match="PRIVATE_ORIGIN_INVALID"):
        _asgi_app(env, probe, calls, config=PrivateNetworkConfig(origin="https://127.0.0.1:0"))

    assert probe.calls == []
    assert calls == []


def test_private_ingress_bounds_chunked_post_and_rejects_malformed_more_body_before_dispatch():
    env = build_env()
    calls = []
    probe = _RouteProbe()
    app = _asgi_app(env, probe, calls, config=PrivateNetworkConfig(origin=ORIGIN, max_body_bytes=4))
    headers = {**_host(), "authorization": "Bearer synthetic-write"}
    oversized = _run_asgi(app, _post_scope(headers), [
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"45", "more_body": False},
    ])
    malformed = _run_asgi(app, _post_scope(headers), [
        {"type": "http.request", "body": b"", "more_body": 1},
    ])
    empty_flood = _run_asgi(app, _post_scope(headers), [
        *({"type": "http.request", "body": b"", "more_body": True} for _ in range(8192)),
        {"type": "http.request", "body": b"", "more_body": False},
    ])

    assert oversized[0]["status"] == 413
    assert malformed[0]["status"] == 400
    assert empty_flood[0]["status"] == 413
    assert len(probe.calls) == 3
    assert calls == []
