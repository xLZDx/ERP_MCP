from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

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
async def test_company_read_uses_company_authorization_and_server_scope_filter():
    company_id = UUID("ee349d4d-02f5-4746-8ba9-f9ee24b8b0d7")
    source = SimpleNamespace(id="source-1")
    company = SimpleNamespace(
        id=company_id,
        source_id="source-1",
        external_ref="474f191a-d427-4495-962c-e55e67307efa",
    )
    registry = SimpleNamespace(
        require_company_source=AsyncMock(return_value=(source, company)),
        save_capabilities=AsyncMock(
            return_value={"drift_status": "STABLE", "drift_acknowledged_at": None}
        ),
    )
    registry.require_source = AsyncMock(side_effect=AssertionError("must not require source-wide grant"))
    capabilities = SimpleNamespace(
        adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
        metadata_fingerprint="metadata-fp",
    )
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=capabilities),
        metadata=AsyncMock(return_value=SimpleNamespace(entities=[])),
        read=AsyncMock(return_value={"value": [{"Amount": 10}]}),
    )
    scope = SimpleNamespace(
        mapping=AsyncMock(
            return_value=SimpleNamespace(
                company_property="Организация_Key",
                profile_fingerprint="profile-fp",
            )
        ),
        verify_metadata_property=lambda *_args, **_kwargs: None,
        filter_for=lambda *_args, **_kwargs: (
            "Организация_Key eq guid'474f191a-d427-4495-962c-e55e67307efa'"
        ),
        combine=lambda company_filter, caller: (
            f"({company_filter}) and ({caller})" if caller else company_filter
        ),
    )
    audit = RecordingAudit()
    runtime = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        capability_policy=SimpleNamespace(POLICY_VERSION="rbac-v1"),
        company_scope=scope,
        onec=onec,
        audit=audit,
    )
    mcp = build_mcp(Settings(), runtime)

    result = await mcp.call_tool(
        "onec_company_read",
        {
            "source_id": "source-1",
            "company_id": str(company_id),
            "entity_set": "Document_Sale",
            "filter_expr": "Amount gt 0",
        },
    )

    assert not result.is_error
    registry.require_company_source.assert_awaited_once()
    registry.require_source.assert_not_awaited()
    assert onec.read.await_args.kwargs["filter_expr"].startswith(
        "(Организация_Key eq guid'"
    )
    assert onec.read.await_args.kwargs["filter_expr"].endswith(") and (Amount gt 0)")
    assert audit.events[-1]["company_id"] == company_id


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
