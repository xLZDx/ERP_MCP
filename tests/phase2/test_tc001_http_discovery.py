"""Synthetic Streamable HTTP checks for the R1 discovery tools."""
from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import TestClient


@dataclass(frozen=True)
class Source:
    id: str
    project: str
    kind: str
    display_name: str
    tags: tuple[str, ...]
    read_only: bool


class DiscoveryRuntime:
    """Minimal runtime with two sources and the real principal boundary."""

    def __init__(self) -> None:
        self.audit_events: list[dict[str, Any]] = []
        self.capability_calls = 0
        self.sources = [
            Source("tenant-a", "demo", "synthetic", "Tenant A", ("test",), True),
            Source("rsv-a", "demo", "onec_auto", "RSV source", ("test",), True),
            Source("tenant-b", "demo", "synthetic", "Tenant B", ("test",), True),
        ]

        class Registry:
            async def require_source(inner_self, principal, source_id):
                if principal.subject != "synthetic-user" or source_id not in {"tenant-a", "rsv-a"}:
                    raise PermissionError("source access denied")
                return next(source for source in self.sources if source.id == source_id)

            async def list_allowed(inner_self, principal):
                if principal.subject != "synthetic-user":
                    raise PermissionError("unexpected synthetic principal")
                return self.sources[:1]

            async def save_capabilities(inner_self, capabilities):
                return {"drift_status": "UNCHANGED"}

            async def list_allowed_companies(inner_self, principal, source_id):
                if principal.subject != "synthetic-user" or source_id != "tenant-a":
                    raise PermissionError("company access denied")
                return [SimpleNamespace(
                    id=UUID("00000000-0000-0000-0000-000000000001"),
                    source_id="tenant-a",
                    external_ref="COMPANY-1",
                    display_name="Synthetic Company",
                    legal_name="Synthetic Company Ltd",
                    country_code="US",
                    is_default=True,
                )]

        class Audit:
            async def write(inner_self, **event):
                self.audit_events.append(event)

        class RateLimit:
            async def check(inner_self, *, subject, source_id, tool):
                return None

        class OneC:
            async def rsv_metadata(inner_self, source, *, operation, arguments, max_response_bytes):
                if source.id != "rsv-a" or operation != "ping":
                    raise ValueError("CAPABILITY_UNSUPPORTED")
                return {"data": {"status": "ok"}, "adapter": {"executable_sha256": "a" * 64}}
            async def summary(inner_self, source):
                return {"source_id": source.id, "entity_set_count": 1, "groups": {"Catalog": 1}}

            async def find(inner_self, source, contains, limit, include_property_types=False):
                return [{
                    "name": "Catalog_Items",
                    "entity_type": "Demo.CatalogItem",
                    "properties": ["Ref", "Description"],
                    "navigation_properties": [],
                }][:limit]

            async def capabilities(inner_self, source, *, refresh=False):
                self.capability_calls += 1
                return SimpleNamespace(
                    source_id=source.id,
                    platform_version="synthetic-1",
                    metadata_fingerprint="synthetic-metadata-v1",
                    metadata_supported=True,
                    json_supported=True,
                    atom_supported=False,
                    expand_supported=None,
                    entity_set_count=1,
                    adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                    compatibility_status=SimpleNamespace(value="SUPPORTED"),
                    evidence={"fixture": "synthetic"},
                    as_dict=lambda: {
                        "source_id": source.id,
                        "platform_version": "synthetic-1",
                        "metadata_fingerprint": "synthetic-metadata-v1",
                        "metadata_supported": True,
                        "json_supported": True,
                        "atom_supported": False,
                        "expand_supported": None,
                        "entity_set_count": 1,
                        "adapter_profile": "ODATA_JSON_V3",
                        "compatibility_status": "SUPPORTED",
                        "evidence": {"fixture": "synthetic"},
                    },
                )

        self.registry = Registry()
        self.audit = Audit()
        self.rate_limit = RateLimit()
        self.onec = OneC()
        self.rsv_bridge = object()

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture
def discovery_runtime() -> DiscoveryRuntime:
    return DiscoveryRuntime()


def call_http_tool(
    client: TestClient,
    name: str,
    session_id: str | None = None,
    arguments: dict[str, Any] | None = None,
):
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert response.status_code == 200, response.text
    new_session = response.headers.get("mcp-session-id", session_id)
    body = response.json()
    assert "error" not in body, body
    return body["result"], new_session


def test_sources_list_and_system_status_use_http_with_synthetic_scope(monkeypatch, discovery_runtime):
    from business_ai_gateway import server
    from business_ai_gateway.principal import Principal
    from business_ai_gateway.settings import Settings
    from mcp.server.transport_security import TransportSecuritySettings

    request_id = "synthetic-observation-request"

    class CapabilityObserver:
        async def refresh(self, *, source_id, access_token):
            assert source_id in {"tenant-a", "rsv-a"}
            assert access_token is None
            return {
                "source_id": source_id, "request_id": request_id,
                "observation_id": 1, "status": "STABLE",
            }

    async def get_capabilities(source_id, *, request_id: str, observation_id: int):
        assert source_id in {"tenant-a", "rsv-a"}
        assert (request_id, observation_id) == ("synthetic-observation-request", 1)
        source = next(item for item in discovery_runtime.sources if item.id == source_id)
        capabilities = await discovery_runtime.onec.capabilities(source, refresh=True)
        return capabilities, {"drift_status": "STABLE"}

    discovery_runtime.capability_observer = CapabilityObserver()
    discovery_runtime.registry.get_capabilities = get_capabilities

    expected_server = os.environ.get("TC001_EXPECT_SERVER_FILE")
    if expected_server:
        assert Path(server.__file__).resolve() == Path(expected_server).resolve()

    scopes = {"onec:read"}

    def synthetic_principal(*, oauth_enabled):
        return Principal(
            subject="synthetic-user",
            client_id="synthetic-client",
            scopes=frozenset(scopes),
            groups=frozenset(),
            claims={},
        )

    monkeypatch.setattr(server, "current_principal", synthetic_principal)
    settings = Settings(environment="test", public_mcp_url="http://gateway.test/mcp")
    app = server.build_mcp(settings, discovery_runtime).streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["gateway.test"],
            allowed_origins=["http://gateway.test"],
        ),
    )
    with TestClient(app, base_url="http://gateway.test") as client:
        initialized = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Origin": "http://gateway.test"},
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "tc001-http-test", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        session_id = initialized.headers.get("mcp-session-id")
        assert session_id

        notification = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "mcp-session-id": session_id, "Origin": "http://gateway.test"},
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert notification.status_code == 202, notification.text

        sources, session_id = call_http_tool(client, "sources_list", session_id)
        status, session_id = call_http_tool(client, "system_status", session_id)
        capabilities, session_id = call_http_tool(
            client,
            "onec_capabilities",
            session_id,
            {"source_id": "tenant-a"},
        )
        summary, session_id = call_http_tool(
            client, "onec_metadata_summary", session_id, {"source_id": "tenant-a"}
        )
        entities, session_id = call_http_tool(
            client,
            "onec_find_entities",
            session_id,
            {"source_id": "tenant-a", "contains": "Catalog", "limit": 10},
        )
        rsv, session_id = call_http_tool(
            client, "rsv_metadata", session_id,
            {"source_id": "rsv-a", "operation": "ping", "arguments": {}},
        )
        rsv_denied, session_id = call_http_tool(
            client, "rsv_metadata", session_id,
            {"source_id": "rsv-a", "operation": "execute", "arguments": {}},
        )
        companies, session_id = call_http_tool(
            client, "companies_list", session_id, {"source_id": "tenant-a"}
        )
        denied_company, session_id = call_http_tool(
            client, "companies_list", session_id, {"source_id": "tenant-b"}
        )
        invalid_company_period, session_id = call_http_tool(
            client,
            "accounting_balance_and_turnovers",
            session_id,
            {
                "source_id": "tenant-a",
                "company_id": "not-a-uuid",
                "start_period": "2026-01-01T00:00:00+00:00",
                "end_period": "2026-02-01T00:00:00+00:00",
            },
        )
        naive_period, session_id = call_http_tool(
            client,
            "accounting_balance_and_turnovers",
            session_id,
            {
                "source_id": "tenant-a",
                "company_id": "00000000-0000-0000-0000-000000000001",
                "start_period": "2026-04-01T00:00:00",
                "end_period": "2026-05-01T00:00:00",
            },
        )
        scopes.add("onec:read")
        denied_source, session_id = call_http_tool(
            client,
            "onec_capabilities",
            session_id,
            {"source_id": "tenant-b"},
        )
        scopes.clear()
        denied = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "mcp-session-id": session_id,
                "Origin": "http://gateway.test",
            },
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "sources_list", "arguments": {}},
            },
        )
        assert denied.status_code == 200, denied.text
        denied_result = denied.json()["result"]

    assert [json.loads(block["text"]) for block in sources["content"]] == [
        {
            "id": "tenant-a",
            "project": "demo",
            "kind": "synthetic",
            "display_name": "Tenant A",
            "tags": ["test"],
            "read_only": True,
        }
    ]
    assert [json.loads(block["text"]) for block in status["content"]] == [
        {
            "mode": "1c-production",
            "read_only": True,
            "subject": "synthetic-user",
            "accessible_sources": 1,
            "max_rows": 200,
            "capability_negotiation": True,
            "adapter_profiles": ["ODATA_JSON_V3", "ODATA_ATOM_V3", "HTTP_QUERY_FALLBACK"],
            "future_adapters": {"erp": "reserved", "ferma": "reserved"},
        }
    ]
    assert [json.loads(block["text"]) for block in capabilities["content"]] == [{
        "source_id": "tenant-a",
        "platform_version": "synthetic-1",
        "metadata_fingerprint": "synthetic-metadata-v1",
        "metadata_supported": True,
        "json_supported": True,
        "atom_supported": False,
        "expand_supported": None,
        "entity_set_count": 1,
        "adapter_profile": "ODATA_JSON_V3",
        "compatibility_status": "SUPPORTED",
        "evidence": {"fixture": "synthetic"},
        "drift_status": "STABLE",
    }]
    assert [json.loads(block["text"]) for block in summary["content"]] == [{
        "source_id": "tenant-a", "entity_set_count": 1, "groups": {"Catalog": 1}
    }]
    assert [json.loads(block["text"]) for block in entities["content"]] == [{
        "name": "Catalog_Items", "entity_type": "Demo.CatalogItem",
        "properties": ["Ref", "Description"], "navigation_properties": []
    }]
    assert [json.loads(block["text"]) for block in companies["content"]] == [{
        "company_id": "00000000-0000-0000-0000-000000000001",
        "source_id": "tenant-a",
        "external_ref": "COMPANY-1",
        "display_name": "Synthetic Company",
        "legal_name": "Synthetic Company Ltd",
        "country_code": "US",
        "default": True,
    }]
    assert denied_company["isError"] is True
    assert denied_company["content"] == [
        {"type": "text", "text": "Error executing tool companies_list"}
    ]
    assert invalid_company_period["isError"] is True
    assert invalid_company_period["isError"] is True
    assert invalid_company_period["content"] == [{
        "type": "text", "text": "Error executing tool accounting_balance_and_turnovers"
    }]
    assert discovery_runtime.capability_calls == 1
    assert naive_period["isError"] is True
    assert naive_period["content"] == [{
        "type": "text", "text": "Error executing tool accounting_balance_and_turnovers"
    }]
    assert discovery_runtime.capability_calls == 1
    assert [json.loads(block["text"]) for block in rsv["content"]] == [{
        "data": {"status": "ok"}, "adapter": {"executable_sha256": "a" * 64}
    }]
    assert rsv_denied["isError"] is True
    assert [(event["tool"], event["outcome"]) for event in discovery_runtime.audit_events[:3]] == [
        ("sources_list", "success"), ("system_status", "success"),
        ("onec_capabilities", "success"),
    ]
    assert denied_source["isError"] is True
    assert "Error executing tool onec_capabilities" == denied_source["content"][0]["text"]
    assert denied_result["isError"] is True
    assert denied_result["content"] == [
        {"type": "text", "text": "Error executing tool sources_list"}
    ]


