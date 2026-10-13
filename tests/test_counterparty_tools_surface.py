"""Public MCP surface of counterparty_find and name resolution: isolation, audit hygiene, degradation (fakes, no DB)."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from business_ai_gateway.fixture_profiles import ProvisionalProfiles
from business_ai_gateway.semantic import SemanticProfileUnavailable
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from tests.test_analytics_balance_mapping import COMPANY, REF1, good_mapping, odata_row
from tests.test_analytics_balance_routing import SOURCE, make_caps
from tests.test_analytics_balance_routing import build as routing_build
from tests.test_analytics_balance_routing import call as routing_call
from tests.test_analytics_balance_routing import payload as routing_payload
from tests.test_counterparty_lookup import PROFILE
from tests.test_server_audit import RecordingAudit, TestRegistry
from tests.test_supplier_debt_mcp_integration import exact_5211_mapping

LOOKUP = ProvisionalProfiles(
    PROFILE, hashlib.sha256(PROFILE.read_bytes()).hexdigest(), environment="test"
).lookup("onec-818ha-reference", UUID("3e31afc5-351f-4f36-8074-99129fa3d911"), "counterparty.lookup")
ANALYTICS_PAGE = {"value": [odata_row()], "page": {"returned": 1, "has_more": False, "truncated": False}}


def catalog_row(ref=REF1, name="MOLDRETAIL GROUP SRL", **over):
    row = {"Ref_Key": ref, "Code": "00-000036", "Description": name, "DeletionMark": False, "IsFolder": False}
    row.update(over)
    return row


def build(*, lookup_rows=None, lookup_profile=True, source_denied=False, read_error=None):
    company = UUID(COMPANY)
    registry = TestRegistry()
    registry.require_company = AsyncMock(return_value=SimpleNamespace(external_ref=COMPANY))
    registry.save_capabilities = AsyncMock(return_value={"drift_status": "STABLE"})

    async def mapping_for(_source, _company, concept):
        if concept == "counterparty.lookup":
            if not lookup_profile:
                raise SemanticProfileUnavailable("no validated counterparty.lookup profile exists")
            return {"mapping": LOOKUP, "profile_kind": "VALIDATED_NATIVE",
                    "profile_fingerprint": "sha256:lookup", "audit_detail_code": None}
        return {"mapping": good_mapping(), "profile_kind": "VALIDATED_NATIVE",
                "profile_fingerprint": "sha256:profile", "audit_detail_code": None}

    registry.require_semantic_mapping = AsyncMock(side_effect=mapping_for)

    async def require_source_for_company(_p, _s, _c):
        if source_denied:
            raise PermissionError("denied")
        return SOURCE

    registry.require_source_for_company = require_source_for_company
    audit = RecordingAudit()
    read = (AsyncMock(side_effect=read_error) if read_error
            else AsyncMock(return_value={"value": [catalog_row()] if lookup_rows is None else lookup_rows}))
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=make_caps("AVAILABLE")),
        register_read=AsyncMock(return_value=ANALYTICS_PAGE), read=read)
    runtime = SimpleNamespace(
        audit=audit, registry=registry, rate_limit=SimpleNamespace(check=AsyncMock()), onec=onec,
        com_bindings=lambda: (), com_client=AsyncMock(return_value=None))
    return build_mcp(Settings(), runtime), audit, onec, company


def body(result):
    return json.loads(result.content[0].text)


async def find(mcp, company, **over):
    args = {"source_id": "source-1", "company_id": str(company), "name": "moldretail"}
    args.update(over)
    return await mcp.call_tool("counterparty_find", args)


async def test_find_returns_status_and_never_exposes_the_filter():
    mcp, audit, onec, company = build()
    out = body(await find(mcp, company))
    assert out["status"] == "PARTIAL" and out["matches"][0]["name"] == "MOLDRETAIL GROUP SRL"
    kwargs = onec.read.await_args.kwargs
    assert kwargs["entity_set"] == "Catalog_Контрагенты"
    assert kwargs["filter_expr"] == "substringof('moldretail', Description)"
    assert audit.events[-1]["outcome"] == "success"


async def test_audit_never_records_the_searched_text():
    mcp, audit, _onec, company = build()
    await find(mcp, company, name="Secret Supplier Name")
    dump = json.dumps(audit.events, default=str, ensure_ascii=False)
    assert "Secret Supplier" not in dump


async def test_foreign_source_is_denied_before_any_catalog_read():
    mcp, audit, onec, company = build(source_denied=True)
    with pytest.raises(UnexpectedToolError):
        await find(mcp, company)
    onec.read.assert_not_awaited()
    onec.capabilities.assert_not_awaited()
    assert audit.events[0]["outcome"] == "denied"


async def test_invalid_company_id_is_denied_before_any_call():
    mcp, audit, onec, company = build()
    with pytest.raises(UnexpectedToolError):
        await find(mcp, company, company_id="not-a-uuid")
    onec.read.assert_not_awaited()
    assert audit.events[-1]["detail_code"] == "INVALID_COMPANY_ID"


@pytest.mark.parametrize("name", ["a", "x" * 65, "ok\x00no"])
async def test_bad_search_text_is_rejected_before_the_source_is_read(name):
    mcp, audit, onec, company = build()
    with pytest.raises(UnexpectedToolError):
        await find(mcp, company, name=name)
    onec.read.assert_not_awaited()
    assert audit.events[-1]["outcome"] == "error"


async def test_missing_profile_fails_closed_without_reading_the_catalog():
    mcp, audit, onec, company = build(lookup_profile=False)
    with pytest.raises(UnexpectedToolError):
        await find(mcp, company)
    onec.read.assert_not_awaited()
    assert audit.events[-1]["outcome"] == "denied"


@pytest.mark.parametrize("extra", ["entity_set", "filter_expr", "select", "top", "route"])
async def test_caller_cannot_supply_catalog_filter_or_shape(extra):
    mcp, _audit, onec, company = build()
    with pytest.raises(ToolError):
        await find(mcp, company, **{extra: "Catalog_Номенклатура"})
    onec.read.assert_not_awaited()


async def test_tool_schema_has_exactly_three_parameters():
    mcp, *_ = build()
    schema = {t.name: t for t in await mcp.list_tools()}["counterparty_find"].input_schema
    assert set(schema["properties"]) == {"source_id", "company_id", "name"}
    assert schema.get("additionalProperties") is False


# ---------------------------------------------------------------- supplier names in the balance tool (main path)


async def test_balance_rows_get_names_from_one_batched_authorized_catalog_read(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda entity: entity == "Catalog_Контрагенты", raising=False)
    mcp, _audit, onec, _com, company = routing_build("AVAILABLE", mapping=exact_5211_mapping())
    onec.read = AsyncMock(return_value={
        "value": [{"Ref_Key": REF1, "Description": "ACME SRL"}],
        "page": {"has_more": False, "truncated": False},
    })
    summary = routing_payload(await routing_call(mcp, company))["supplier_summary"]
    assert summary["suppliers"][0]["supplier_name"] == "ACME SRL"
    assert summary["name_lookup_status"] == "COMPLETE"
    assert onec.read.await_count == 1


async def test_many_account_profile_has_no_supplier_summary_and_no_catalog_read(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda entity: True, raising=False)
    mcp, _audit, onec, _com, company = routing_build("AVAILABLE", mapping=good_mapping())
    onec.read = AsyncMock()
    result = routing_payload(await routing_call(mcp, company))
    assert result["supplier_summary"] is None
    onec.read.assert_not_awaited()


async def test_failing_catalog_read_fails_closed_without_leaking_its_text(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda entity: True, raising=False)
    mcp, _audit, onec, _com, company = routing_build("AVAILABLE", mapping=exact_5211_mapping())
    onec.read = AsyncMock(side_effect=RuntimeError("secret-host.internal exploded"))
    with pytest.raises(UnexpectedToolError) as raised:
        await routing_call(mcp, company)
    assert "secret-host" not in str(raised.value)


async def test_unknown_reference_is_reported_not_invented(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda entity: True, raising=False)
    mcp, _audit, onec, _com, company = routing_build("AVAILABLE", mapping=exact_5211_mapping())
    onec.read = AsyncMock(return_value={"value": [], "page": {"has_more": False, "truncated": False}})
    summary = routing_payload(await routing_call(mcp, company))["supplier_summary"]
    assert summary["suppliers"][0]["supplier_name"] is None
    assert summary["name_lookup_status"] == "PARTIAL"


# ---------------------------------------------------------------- every tool rejects unknown arguments


async def test_every_published_tool_schema_forbids_additional_properties():
    mcp, *_ = build()
    tools = await mcp.list_tools()
    assert len(tools) > 20
    assert [t.name for t in tools if t.input_schema.get("additionalProperties") is not False] == []


@pytest.mark.parametrize("misnamed", ["filter", "$filter", "query", "where"])
async def test_onec_read_with_a_misnamed_filter_is_rejected_not_answered_unfiltered(misnamed):
    mcp, _audit, onec, _company = build()
    with pytest.raises(ToolError) as raised:
        await mcp.call_tool("onec_read", {
            "source_id": "source-1", "entity_set": "ChartOfAccounts_Хозрасчетный",
            "select": ["Code"], misnamed: "Code eq '521.1'"})
    assert misnamed in str(raised.value)
    onec.read.assert_not_awaited()


# ---------------------------------------------------------------- tool descriptions steer the model


async def test_tool_descriptions_name_the_right_tool_and_the_timezone_rule():
    mcp, *_ = build()
    desc = {t.name: (t.description or "") for t in await mcp.list_tools()}
    assert "timezone" in desc["accounting_balance_and_turnovers"]
    assert "accounting_balance_by_analytics" in desc["accounting_balance_and_turnovers"]
    assert "counterparty_find" in desc["accounting_balance_and_turnovers"]
    assert "payable.balance" in desc["payable_balance"] and "fail closed" in desc["payable_balance"]
    assert "payable" in desc["payable_aging"]
    assert "ISO 8601 with offset" in desc["accounting_balance_by_analytics"]
    assert "counterparty names" in desc["accounting_balance_by_analytics"]
