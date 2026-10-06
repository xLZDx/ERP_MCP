from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.models import Source
from business_ai_gateway.principal import Principal
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings


class RecordingAudit:
    def __init__(self):
        self.events = []

    async def write(self, **event):
        self.events.append(event)


def source():
    return Source(
        id="rsv-source",
        project="onec",
        kind="onec_auto",
        display_name="Synthetic",
        base_url="https://onec.example.test/odata",
        username_secret_ref=None,
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )


class Registry:
    def __init__(self, *, denied=False):
        self.denied = denied

    async def require_source(self, _principal, _source_id):
        if self.denied:
            raise PermissionError("source denied")
        return source()


def runtime(*, denied=False):
    audit = RecordingAudit()
    bridge = SimpleNamespace(metadata=AsyncMock(return_value={
        "source_id": "rsv-source",
        "adapter": {
            "kind": "rsv_data_metadata",
            "upstream_source_sha": "pinned",
            "executable_sha256": "a" * 64,
        },
        "operation": "config",
        "data": {"synthetic": True},
    }))
    value = SimpleNamespace(
        audit=audit,
        registry=Registry(denied=denied),
        rate_limit=SimpleNamespace(check=AsyncMock()),
        rsv_bridge=bridge,
        onec=SimpleNamespace(rsv_metadata=bridge.metadata),
    )
    return value, audit, bridge


@pytest.mark.asyncio
async def test_rsv_metadata_is_source_acl_checked_audited_and_normalized():
    runtime_value, audit, bridge = runtime()
    mcp = build_mcp(Settings(environment="test"), runtime_value)

    result = await mcp.call_tool("rsv_metadata", {
        "source_id": "rsv-source",
        "operation": "config",
    })

    assert not result.is_error
    bridge.metadata.assert_awaited_once_with(
        source(), operation="config", arguments=None, max_response_bytes=5_000_000
    )
    assert audit.events[-1]["outcome"] == "success"
    assert audit.events[-1]["source_id"] == "rsv-source"
    assert audit.events[-1]["upstream_sha"] == "76fed8e6e16833fee1514969841b8d9a61c7c152"
    assert audit.events[-1]["adapter_version"] == f"sha256:{'a' * 64}"
    assert "query" not in audit.events[-1]


@pytest.mark.asyncio
async def test_rsv_metadata_source_acl_denial_stops_before_bridge():
    runtime_value, audit, bridge = runtime(denied=True)
    mcp = build_mcp(Settings(environment="test"), runtime_value)

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool("rsv_metadata", {
            "source_id": "rsv-source",
            "operation": "config",
        })

    bridge.metadata.assert_not_awaited()
    assert audit.events[-1]["outcome"] == "denied"
    assert runtime_value.rate_limit.check.await_count == 0


@pytest.mark.asyncio
async def test_rsv_metadata_rejects_business_operation_before_bridge():
    runtime_value, audit, bridge = runtime()
    mcp = build_mcp(Settings(environment="test"), runtime_value)

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool("rsv_metadata", {
            "source_id": "rsv-source",
            "operation": "query",
            "arguments": {"table": "Catalog_Synthetic"},
        })

    bridge.metadata.assert_not_awaited()
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"] == "CAPABILITY_UNSUPPORTED"


@pytest.mark.asyncio
async def test_rsv_metadata_stays_disabled_in_production_until_secret_binding():
    runtime_value, audit, bridge = runtime()
    settings = Settings(
        environment="production",
        public_mcp_url="https://mcp.example.com/mcp",
        oauth_enabled=True,
        oauth_issuer="https://id.example.com/",
        oauth_audience="https://mcp.example.com/mcp",
        oauth_jwks_url="https://id.example.com/jwks",
        source_host_allowlist="onec.example.test",
            source_egress_cidrs="10.0.0.0/8",
        secret_provider="file",
    )
    mcp = build_mcp(settings, runtime_value)

    from business_ai_gateway import server

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        server,
        "current_principal",
        lambda **_kwargs: Principal(
            subject="tester",
            client_id="client",
            scopes=frozenset({"onec:read"}),
            groups=frozenset(),
            claims={},
        ),
    )
    try:
        with pytest.raises(UnexpectedToolError):
            await mcp.call_tool("rsv_metadata", {
                "source_id": "rsv-source",
                "operation": "config",
            })
    finally:
        monkeypatch.undo()

    bridge.metadata.assert_not_awaited()
    assert audit.events[-1]["detail_code"] == "CAPABILITY_UNSUPPORTED"
