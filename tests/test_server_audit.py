from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.audit import AuditCorrelationMiddleware
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings


class RecordingAudit:
    def __init__(self):
        self.events = []

    async def write(self, **event):
        self.events.append(event)


class TestRegistry:
    async def require_source(self, _principal, source_id):
        if source_id == "forbidden":
            raise PermissionError("source access denied")
        return SimpleNamespace(id=source_id)


def create_mcp(*, rate_limit_error=None):
    audit = RecordingAudit()
    rate_limit = SimpleNamespace(check=AsyncMock(side_effect=rate_limit_error))
    onec = SimpleNamespace(health=AsyncMock(return_value={"status": "ok"}))
    runtime = SimpleNamespace(
        audit=audit,
        registry=TestRegistry(),
        rate_limit=rate_limit,
        onec=onec,
    )
    return build_mcp(Settings(), runtime), audit, rate_limit, onec


def test_mcp_registers_audit_correlation_middleware():
    mcp, _audit, _rate_limit, _onec = create_mcp()

    assert any(isinstance(item, AuditCorrelationMiddleware) for item in mcp.middleware)


@pytest.mark.asyncio
async def test_source_health_success_is_audited_after_authorized_call():
    mcp, audit, rate_limit, onec = create_mcp()

    result = await mcp.call_tool("source_health", {"source_id": "source-1"})

    assert not result.is_error
    rate_limit.check.assert_awaited_once_with(
        subject="development-local", source_id="source-1", tool="source_health"
    )
    onec.health.assert_awaited_once()
    assert len(audit.events) == 1
    assert audit.events[0]["outcome"] == "success"
    assert audit.events[0]["source_id"] == "source-1"


@pytest.mark.asyncio
async def test_source_acl_denial_is_audited_and_stops_before_rate_limit():
    mcp, audit, rate_limit, onec = create_mcp()

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool("source_health", {"source_id": "forbidden"})

    assert len(audit.events) == 1
    assert audit.events[0]["outcome"] == "denied"
    assert audit.events[0]["detail_code"] == "PermissionError"
    rate_limit.check.assert_not_awaited()
    onec.health.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_outage_is_audited_as_denial_and_never_calls_source():
    mcp, audit, rate_limit, onec = create_mcp(
        rate_limit_error=ConnectionError("redis unavailable")
    )

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool("source_health", {"source_id": "source-1"})

    assert len(audit.events) == 1
    assert audit.events[0]["outcome"] == "denied"
    assert audit.events[0]["detail_code"] == "ConnectionError"
    rate_limit.check.assert_awaited_once()
    onec.health.assert_not_awaited()


@pytest.mark.asyncio
async def test_adapter_failure_is_audited_as_error():
    mcp, audit, _rate_limit, onec = create_mcp()
    onec.health.side_effect = TimeoutError("1C request timed out")

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool("source_health", {"source_id": "source-1"})

    assert len(audit.events) == 1
    assert audit.events[0]["outcome"] == "error"
    assert audit.events[0]["detail_code"] == "TimeoutError"
    assert audit.events[0]["source_id"] == "source-1"
