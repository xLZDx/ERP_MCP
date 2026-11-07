from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from business_ai_gateway.adapters.onec.adapter import OneCAdapter
from business_ai_gateway.models import Source
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings


@pytest.mark.e2e
def test_incomplete_credentials_refusal_does_not_stop_gateway_health():
    source = Source(
        id="tc017-health-source",
        project="phase2",
        kind="onec_odata",
        display_name="TC017 health source",
        base_url="https://1c.example.test/odata/standard.odata",
        username_secret_ref="username-ref",
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )

    class Secrets:
        calls: list[str] = []

        async def get(self, ref: str) -> str:
            self.calls.append(ref)
            return "must-not-be-read"

    class SourceClient:
        calls: list[str] = []

        async def head_metadata(self, requested_source, *, username, password):
            self.calls.append(requested_source.id)
            raise AssertionError("incomplete credentials must stop before source I/O")

    secrets = Secrets()
    source_client = SourceClient()
    settings = Settings()

    class Registry:
        async def require_source(self, _principal, source_id):
            assert source_id == source.id
            return source

    class Runtime:
        audit = type("Audit", (), {"write": staticmethod(_no_op)})()
        registry = Registry()
        rate_limit = type("RateLimit", (), {"check": staticmethod(_no_op)})()
        onec = OneCAdapter(settings, secrets, source_client)

        async def start(self):
            return None

        async def close(self):
            return None

    mcp = build_mcp(settings, Runtime())

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request):
        return JSONResponse({"status": "ok"})

    app = mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True)
    with TestClient(app) as http:
        with pytest.raises(UnexpectedToolError) as refusal:
            # Invoke the registered MCP tool in the same live ASGI app process.
            import anyio

            async def call_tool():
                return await mcp.call_tool("source_health", {"source_id": source.id})

            anyio.run(call_tool)

        error_payload = json.loads(str(refusal.value))
        assert error_payload["error"]["code"] == "INTERNAL_ERROR"
        assert error_payload["error"]["tool"] == "source_health"
        assert error_payload["error"]["source_id"] is None
        assert secrets.calls == []
        assert source_client.calls == []

        health = http.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}


async def _no_op(*_args, **_kwargs):
    return None
