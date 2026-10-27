"""Request-level checks of the private ingress boundary (no database, no COM, no real service)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from erp_mcp_private_writer import private_ingress as ingress
from erp_mcp_private_writer.private_auth import (
    PrivateWriterAuthenticationError,
    PrivateWriterAuthenticator,
)
from erp_mcp_private_writer.private_authorization import ConfiguredPrivateWriterAuthorizer
from erp_mcp_private_writer.runtime_composition import PrivateWriterRuntime
from erp_mcp_private_writer.service import PrivateWriterService

_URL = "http://127.0.0.1:8000"


def _app(monkeypatch, authenticate):
    # The factory insists on exact types, so bare instances stand in for the real objects and the
    # few methods the boundary calls are patched on the classes.
    service = object.__new__(PrivateWriterService)
    runtime = object.__new__(PrivateWriterRuntime)
    object.__setattr__(runtime, "service", service)
    monkeypatch.setattr(PrivateWriterService, "ready", property(lambda _self: True))
    monkeypatch.setattr(PrivateWriterAuthenticator, "authenticate", authenticate)
    return ingress.create_private_writer_app(
        service,
        object.__new__(PrivateWriterAuthenticator),
        call_authorizer=object.__new__(ConfiguredPrivateWriterAuthorizer),
        runtime=runtime,
    )


class _AsServerDoes:
    """TestClient reports scope['server'] as a list; real ASGI servers (uvicorn) send a tuple."""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and isinstance(scope.get("server"), list):
            scope = {**scope, "server": tuple(scope["server"])}
        await self._app(scope, receive, send)


def _client(app, peer="127.0.0.1"):
    return TestClient(_AsServerDoes(app), base_url=_URL, client=(peer, 50000))


@pytest.mark.parametrize("path", ["/v1/calls/dispatch", "/v1/calls/lookup"])
def test_an_unexpected_authenticator_failure_is_a_logged_503_not_a_500(monkeypatch, caplog, path):
    async def _boom(_self, _headers):
        raise RuntimeError("secret-detail")

    client = _client(_app(monkeypatch, _boom))
    with caplog.at_level("ERROR"):
        response = client.post(path, json={})

    assert response.status_code == 503
    assert response.json() == {"error": "AUTHENTICATION_UNAVAILABLE"}
    assert "RuntimeError" in caplog.text
    assert "secret-detail" not in caplog.text


def test_a_rejected_credential_is_401(monkeypatch):
    async def _reject(_self, _headers):
        raise PrivateWriterAuthenticationError("AUTHENTICATION_REQUIRED")

    response = _client(_app(monkeypatch, _reject)).post("/v1/calls/dispatch", json={})

    assert response.status_code == 401


def test_a_non_loopback_peer_is_refused_before_authentication(monkeypatch):
    calls = []

    async def _spy(_self, _headers):
        calls.append(1)

    response = _client(_app(monkeypatch, _spy), peer="10.1.2.3").post(
        "/v1/calls/dispatch", json={},
    )

    assert response.status_code == 403
    assert response.json() == {"error": "PRIVATE_LOOPBACK_REQUIRED"}
    assert calls == []


def _authenticated_client(monkeypatch):
    async def _ok(_self, _headers):
        return object()

    return _client(_app(monkeypatch, _ok))


@pytest.mark.parametrize("path", ["/v1/calls/dispatch", "/v1/calls/lookup"])
def test_malformed_and_unknown_field_bodies_are_400_before_any_service_call(monkeypatch, path):
    client = _authenticated_client(monkeypatch)

    not_json = client.post(path, content=b"{not json", headers={"content-type": "application/json"})
    unknown_field = client.post(path, json={"unexpected": 1})
    duplicate_key = client.post(
        path, content=b'{"ticket": {}, "ticket": {}}',
        headers={"content-type": "application/json"},
    )

    assert not_json.status_code == 400
    assert unknown_field.status_code == 400
    assert duplicate_key.status_code == 400
    assert unknown_field.json() == {"error": "INVALID_REQUEST"}


def test_an_oversized_body_is_413(monkeypatch):
    client = _authenticated_client(monkeypatch)

    response = client.post(
        "/v1/calls/dispatch", content=b'{"payload": "' + b"x" * (1_048_576 + 1) + b'"}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"error": "REQUEST_TOO_LARGE"}
