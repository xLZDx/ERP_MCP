from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.business_policy import CapabilityDenied
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings


class RecordingAudit:
    def __init__(self):
        self.events = []

    async def write(self, **event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_generic_company_read_route_is_not_registered():
    mcp = build_mcp(Settings(), SimpleNamespace())

    with pytest.raises(Exception, match="Unknown tool: onec_company_read"):
        await mcp.call_tool(
            "onec_company_read",
            {"source_id": "source-1", "company_id": "company-b"},
        )


@pytest.mark.asyncio
async def test_business_capability_denial_stops_before_adapter():
    audit = RecordingAudit()
    source = SimpleNamespace(id="source-1")
    registry = SimpleNamespace(require_source=AsyncMock(return_value=source))
    policy = SimpleNamespace(
        POLICY_VERSION="rbac-v1",
        require=AsyncMock(side_effect=CapabilityDenied("denied")),
    )
    onec = SimpleNamespace(health=AsyncMock())
    runtime = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        capability_policy=policy,
        onec=onec,
        audit=audit,
    )
    settings = Settings(business_capability_enforcement_enabled=True)
    mcp = build_mcp(settings, runtime)

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool("source_health", {"source_id": "source-1"})

    policy.require.assert_awaited_once()
    onec.health.assert_not_awaited()
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"] == "CAPABILITY_DENIED"
