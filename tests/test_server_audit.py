from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.audit import AuditCorrelationMiddleware
from business_ai_gateway.semantic import SemanticMappingUnconfirmed
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

    async def require_source_for_company(self, _principal, source_id, _company_id):
        if source_id == "forbidden":
            raise PermissionError("company source access denied")
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


@pytest.mark.asyncio
async def test_account_turnovers_uses_confirmed_mapping_and_enforces_company_scope():
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    source = SimpleNamespace(id="source-1")
    capabilities = SimpleNamespace(
        adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
        metadata_fingerprint="sha256:metadata",
    )
    registry = TestRegistry()
    registry.require_account_turnovers_mapping = AsyncMock(
        return_value={
            "mapping": {
                "entity_set": "AccountingRegister_Хозрасчетный",
                "method": "balanceAndTurnovers",
                "company_scope": {"field": "Организация_Key", "value_type": "guid"},
                "output_fields": {
                    "account": "Account",
                    "opening_debit": "OpeningDebit",
                    "opening_credit": "OpeningCredit",
                    "debit_turnover": "DebitTurnover",
                    "credit_turnover": "CreditTurnover",
                    "closing_debit": "ClosingDebit",
                    "closing_credit": "ClosingCredit",
                },
            },
            "profile_fingerprint": "sha256:profile",
        }
    )
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    audit = RecordingAudit()
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=capabilities),
        register_read=AsyncMock(
            return_value={
                "value": [
                    {
                        "Account": "account-1",
                        "OpeningDebit": 1,
                        "OpeningCredit": 2,
                        "DebitTurnover": 3,
                        "CreditTurnover": 4,
                        "ClosingDebit": 5,
                        "ClosingCredit": 6,
                    }
                ],
                "page": {},
            }
        ),
    )
    runtime = SimpleNamespace(
        audit=audit,
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        onec=onec,
    )
    mcp = build_mcp(Settings(), runtime)
    result = await mcp.call_tool(
        "accounting_balance_and_turnovers",
        {
            "source_id": "source-1",
            "company_id": str(company_id),
            "start_period": "2026-01-01T00:00:00Z",
            "end_period": "2026-01-31T23:59:59Z",
        },
    )

    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["value"][0] == {
        "account": "account-1",
        "opening_debit": 1,
        "opening_credit": 2,
        "debit_turnover": 3,
        "credit_turnover": 4,
        "closing_debit": 5,
        "closing_credit": 6,
    }
    onec.register_read.assert_awaited_once_with(
        source,
        register_set="AccountingRegister_Хозрасчетный",
        method="balanceAndTurnovers",
        arguments={
            "Period": {
                "from": "2026-01-01T00:00:00+00:00",
                "to": "2026-01-31T23:59:59+00:00",
            },
            "Condition": "Организация_Key eq guid'f3727523-9689-4b73-973e-9754360fd0a0'",
        },
        top=Settings().max_rows,
    )
    assert audit.events[0]["company_id"] == company_id
    assert audit.events[0]["profile_fingerprint"] == "sha256:profile"


@pytest.mark.asyncio
async def test_account_turnovers_company_denial_stops_before_1c():
    audit = RecordingAudit()
    rate_limit = SimpleNamespace(check=AsyncMock())
    onec = SimpleNamespace(
        capabilities=AsyncMock(),
        register_read=AsyncMock(),
    )
    runtime = SimpleNamespace(
        audit=audit,
        registry=TestRegistry(),
        rate_limit=rate_limit,
        onec=onec,
    )
    mcp = build_mcp(Settings(), runtime)
    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool(
            "accounting_balance_and_turnovers",
            {
                "source_id": "forbidden",
                "company_id": "f3727523-9689-4b73-973e-9754360fd0a0",
                "start_period": "2026-01-01T00:00:00Z",
                "end_period": "2026-01-31T23:59:59Z",
            },
        )
    assert audit.events[0]["outcome"] == "denied"
    assert audit.events[0]["company_id"] == UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    onec.capabilities.assert_not_awaited()
    onec.register_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_turnovers_unconfirmed_mapping_is_audited_and_not_dispatched():
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    registry = TestRegistry()
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    registry.require_account_turnovers_mapping = AsyncMock(
        side_effect=SemanticMappingUnconfirmed("mapping is only a candidate")
    )
    audit = RecordingAudit()
    onec = SimpleNamespace(
        capabilities=AsyncMock(
            return_value=SimpleNamespace(
                adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                metadata_fingerprint="sha256:metadata",
            )
        ),
        register_read=AsyncMock(),
    )
    runtime = SimpleNamespace(
        audit=audit,
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        onec=onec,
    )
    mcp = build_mcp(Settings(), runtime)

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool(
            "accounting_balance_and_turnovers",
            {
                "source_id": "source-1",
                "company_id": str(company_id),
                "start_period": "2026-01-01T00:00:00Z",
                "end_period": "2026-01-31T23:59:59Z",
            },
        )
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"] == "SEMANTIC_MAPPING_UNCONFIRMED"
    onec.register_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_sales_documents_uses_only_confirmed_profile_entity_and_company_filter():
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    source = SimpleNamespace(id="source-1")
    mapping = {
        "entity_set": "Document_РеализацияТоваровУслуг",
        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
        "output_fields": {
            "document_ref": "Ref_Key",
            "document_number": "Number",
            "date": "Date",
            "counterparty": "Контрагент_Key",
            "amount": "СуммаДокумента",
            "currency": "ВалютаДокумента_Key",
            "posted": "Posted",
        },
        "order_by": "Date",
    }
    registry = TestRegistry()
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    registry.require_semantic_mapping = AsyncMock(
        return_value={"mapping": mapping, "profile_fingerprint": "sha256:sales-profile"}
    )
    audit = RecordingAudit()
    capabilities = SimpleNamespace(
        adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
        metadata_fingerprint="sha256:metadata",
    )
    row = {
        "Ref_Key": "doc-1",
        "Number": "0001",
        "Date": "2026-01-01T00:00:00",
        "Контрагент_Key": "party-1",
        "СуммаДокумента": "100.00",
        "ВалютаДокумента_Key": "currency-1",
        "Posted": True,
    }
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=capabilities),
        read=AsyncMock(return_value={"value": [row], "page": {"has_more": False}}),
    )
    runtime = SimpleNamespace(
        audit=audit,
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        onec=onec,
    )
    mcp = build_mcp(Settings(), runtime)
    result = await mcp.call_tool(
        "sales_documents",
        {"source_id": "source-1", "company_id": str(company_id), "top": 10},
    )

    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["value"] == [
        {
            "document_ref": "doc-1",
            "document_number": "0001",
            "date": "2026-01-01T00:00:00",
            "counterparty": "party-1",
            "amount": "100.00",
            "currency": "currency-1",
            "posted": True,
        }
    ]
    onec.read.assert_awaited_once_with(
        source,
        entity_set="Document_РеализацияТоваровУслуг",
        select=list(mapping["output_fields"].values()),
        filter_expr="Организация_Key eq guid'f3727523-9689-4b73-973e-9754360fd0a0'",
        orderby="Date desc",
        expand=None,
        top=10,
        skip=0,
    )
    assert audit.events[-1]["profile_fingerprint"] == "sha256:sales-profile"


@pytest.mark.asyncio
async def test_inventory_balance_uses_exact_profile_and_point_in_time_company_condition():
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    source = SimpleNamespace(id="source-1")
    mapping = {
        "entity_set": "AccumulationRegister_ТоварыНаСкладах",
        "method": "Balance",
        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
        "output_fields": {
            "item_ref": "Номенклатура_Key",
            "warehouse_ref": "Склад_Key",
            "quantity": "КоличествоBalance",
        },
        "required_register_capabilities": [
            {"entity_set": "AccumulationRegister_ТоварыНаСкладах", "method": "Balance"}
        ],
    }
    registry = TestRegistry()
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    registry.require_semantic_mapping = AsyncMock(
        return_value={"mapping": mapping, "profile_fingerprint": "sha256:inventory-profile"}
    )
    audit = RecordingAudit()
    capabilities = SimpleNamespace(
        adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
        metadata_fingerprint="sha256:metadata",
    )
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=capabilities),
        register_read=AsyncMock(
            return_value={
                "value": [
                    {
                        "Номенклатура_Key": "item-1",
                        "Склад_Key": "warehouse-1",
                        "КоличествоBalance": "4.5",
                    }
                ],
                "page": {"has_more": False},
            }
        ),
    )
    runtime = SimpleNamespace(
        audit=audit,
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        onec=onec,
    )
    mcp = build_mcp(Settings(), runtime)
    result = await mcp.call_tool(
        "inventory_balance",
        {
            "source_id": "source-1",
            "company_id": str(company_id),
            "period": "2026-10-01T00:00:00Z",
        },
    )

    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["value"] == [
        {"item_ref": "item-1", "warehouse_ref": "warehouse-1", "quantity": "4.5"}
    ]
    onec.register_read.assert_awaited_once_with(
        source,
        register_set="AccumulationRegister_ТоварыНаСкладах",
        method="Balance",
        arguments={
            "Period": "2026-10-01T00:00:00+00:00",
            "Condition": "Организация_Key eq guid'f3727523-9689-4b73-973e-9754360fd0a0'",
        },
        top=Settings().max_rows,
    )
    assert audit.events[-1]["profile_fingerprint"] == "sha256:inventory-profile"


@pytest.mark.asyncio
async def test_unconfirmed_inventory_profile_is_audited_without_register_dispatch():
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    registry = TestRegistry()
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    registry.require_semantic_mapping = AsyncMock(
        side_effect=SemanticMappingUnconfirmed("not confirmed")
    )
    audit = RecordingAudit()
    onec = SimpleNamespace(
        capabilities=AsyncMock(
            return_value=SimpleNamespace(
                adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                metadata_fingerprint="sha256:metadata",
            )
        ),
        register_read=AsyncMock(),
    )
    runtime = SimpleNamespace(
        audit=audit,
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        onec=onec,
    )
    mcp = build_mcp(Settings(), runtime)

    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool(
            "inventory_balance",
            {
                "source_id": "source-1",
                "company_id": str(company_id),
                "period": "2026-10-01T00:00:00Z",
            },
        )
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"] == "SEMANTIC_MAPPING_UNCONFIRMED"
    onec.register_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_bank_balance_uses_only_confirmed_profile_and_exact_source_register():
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    source = SimpleNamespace(id="source-1")
    mapping = {
        "entity_set": "AccumulationRegister_ДенежныеСредстваБезналичные",
        "method": "Balance",
        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
        "output_fields": {
            "bank_account_ref": "БанковскийСчет_Key",
            "currency_ref": "Валюта_Key",
            "amount": "СуммаBalance",
        },
        "required_register_capabilities": [
            {
                "entity_set": "AccumulationRegister_ДенежныеСредстваБезналичные",
                "method": "Balance",
            }
        ],
    }
    registry = TestRegistry()
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    registry.require_semantic_mapping = AsyncMock(
        return_value={"mapping": mapping, "profile_fingerprint": "sha256:bank-profile"}
    )
    audit = RecordingAudit()
    capabilities = SimpleNamespace(
        adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
        metadata_fingerprint="sha256:metadata",
    )
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=capabilities),
        register_read=AsyncMock(
            return_value={
                "value": [{"БанковскийСчет_Key": "bank-1", "Валюта_Key": "MDL", "СуммаBalance": "5"}],
                "page": {"has_more": False},
            }
        ),
    )
    runtime = SimpleNamespace(
        audit=audit,
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        onec=onec,
    )
    mcp = build_mcp(Settings(), runtime)
    result = await mcp.call_tool(
        "bank_balance",
        {
            "source_id": "source-1",
            "company_id": str(company_id),
            "period": "2026-10-01T00:00:00Z",
        },
    )

    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["value"] == [
        {"bank_account_ref": "bank-1", "currency_ref": "MDL", "amount": "5"}
    ]
    onec.register_read.assert_awaited_once_with(
        source,
        register_set="AccumulationRegister_ДенежныеСредстваБезналичные",
        method="Balance",
        arguments={
            "Period": "2026-10-01T00:00:00+00:00",
            "Condition": "Организация_Key eq guid'f3727523-9689-4b73-973e-9754360fd0a0'",
        },
        top=Settings().max_rows,
    )
    assert audit.events[-1]["profile_fingerprint"] == "sha256:bank-profile"


@pytest.mark.parametrize(
    ("tool", "concept", "register"),
    [
        (
            "receivable_balance",
            "receivable.balance",
            "AccumulationRegister_TestReceivables",
        ),
        ("payable_balance", "payable.balance", "AccumulationRegister_TestPayables"),
    ],
)
@pytest.mark.asyncio
async def test_settlement_balance_uses_company_scoped_confirmed_mapping(tool, concept, register):
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    source = SimpleNamespace(id="source-1")
    mapping = {
        "entity_set": register,
        "method": "Balance",
        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
        "output_fields": {
            "counterparty_ref": "Контрагент_Key",
            "contract_ref": "Договор_Key",
            "amount": "СуммаBalance",
        },
        "required_register_capabilities": [{"entity_set": register, "method": "Balance"}],
    }
    registry = TestRegistry()
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    registry.require_semantic_mapping = AsyncMock(
        return_value={"mapping": mapping, "profile_fingerprint": f"sha256:{concept}"}
    )
    audit = RecordingAudit()
    capabilities = SimpleNamespace(
        adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
        metadata_fingerprint="sha256:metadata",
    )
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=capabilities),
        register_read=AsyncMock(
            return_value={
                "value": [{"Контрагент_Key": "party-1", "Договор_Key": "deal-1", "СуммаBalance": "9"}]
            }
        ),
    )
    mcp = build_mcp(
        Settings(),
        SimpleNamespace(
            audit=audit,
            registry=registry,
            rate_limit=SimpleNamespace(check=AsyncMock()),
            onec=onec,
        ),
    )
    result = await mcp.call_tool(
        tool,
        {
            "source_id": "source-1",
            "company_id": str(company_id),
            "period": "2026-10-01T00:00:00Z",
        },
    )
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["concept"] == concept
    assert payload["value"] == [
        {"counterparty_ref": "party-1", "contract_ref": "deal-1", "amount": "9"}
    ]
    onec.register_read.assert_awaited_once_with(
        source,
        register_set=register,
        method="Balance",
        arguments={
            "Period": "2026-10-01T00:00:00+00:00",
            "Condition": "Организация_Key eq guid'f3727523-9689-4b73-973e-9754360fd0a0'",
        },
        top=Settings().max_rows,
    )


@pytest.mark.parametrize(
    ("tool", "concept"),
    [
        ("receivable_balance", "receivable.balance"),
        ("payable_balance", "payable.balance"),
    ],
)
@pytest.mark.asyncio
async def test_unconfirmed_settlement_mapping_is_denied_before_register_read(tool, concept):
    company_id = UUID("f3727523-9689-4b73-973e-9754360fd0a0")
    registry = TestRegistry()
    registry.require_company = AsyncMock(
        return_value=SimpleNamespace(external_ref=str(company_id))
    )
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})
    registry.require_semantic_mapping = AsyncMock(
        side_effect=SemanticMappingUnconfirmed("mapping is not confirmed")
    )
    audit = RecordingAudit()
    onec = SimpleNamespace(
        capabilities=AsyncMock(
            return_value=SimpleNamespace(
                adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
                metadata_fingerprint="sha256:metadata",
            )
        ),
        register_read=AsyncMock(),
    )
    mcp = build_mcp(
        Settings(),
        SimpleNamespace(
            audit=audit,
            registry=registry,
            rate_limit=SimpleNamespace(check=AsyncMock()),
            onec=onec,
        ),
    )
    with pytest.raises(UnexpectedToolError):
        await mcp.call_tool(
            tool,
            {
                "source_id": "source-1",
                "company_id": str(company_id),
                "period": "2026-10-01T00:00:00Z",
            },
        )
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"] == "SEMANTIC_MAPPING_UNCONFIRMED"
    onec.register_read.assert_not_awaited()
