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
from tests.test_server_audit import RecordingAudit, TestRegistry
from tests.test_counterparty_lookup import PROFILE

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


# ---------------------------------------------------------------- name resolution in the balance tool


async def balance(mcp, company):
    return body(await mcp.call_tool("accounting_balance_by_analytics", {
        "source_id": "source-1", "company_id": str(company), "as_of": "2026-04-30T00:00:00+00:00"}))


def counterparty_slot(out):
    return next(slot for slot in out["rows"][0]["analytics"] if slot["role"] == "counterparty")


async def test_balance_rows_get_names_from_one_batched_profile_owned_read():
    mcp, _audit, onec, company = build(lookup_rows=[catalog_row(ref=REF1, name="ACME SRL")])
    out = await balance(mcp, company)
    slot = counterparty_slot(out)
    assert (slot["name"], slot["code"], slot["deleted"]) == ("ACME SRL", "00-000036", False)
    assert onec.read.await_count == 1
    assert onec.read.await_args.kwargs["filter_expr"] == f"Ref_Key eq guid'{REF1}'"
    assert out["account_totals"][0]["account"] == "521.1"
    assert out["warnings"] == []


async def test_balance_survives_a_missing_lookup_profile_with_a_warning():
    mcp, _audit, onec, company = build(lookup_profile=False)
    out = await balance(mcp, company)
    assert "name" not in counterparty_slot(out)
    assert out["warnings"] and out["warnings"][0].startswith("COUNTERPARTY_NAMES_UNAVAILABLE")
    onec.read.assert_not_awaited()
    assert out["row_count"] == 1


async def test_balance_survives_a_failing_catalog_read_without_leaking_its_text():
    mcp, _audit, _onec, company = build(read_error=RuntimeError("secret-host.internal exploded"))
    out = await balance(mcp, company)
    assert out["warnings"] == ["COUNTERPARTY_NAMES_UNAVAILABLE:RuntimeError"]
    assert "secret-host" not in json.dumps(out)


async def test_unknown_reference_is_reported_not_invented():
    mcp, _audit, _onec, company = build(lookup_rows=[])
    out = await balance(mcp, company)
    assert "name" not in counterparty_slot(out)
    assert out["warnings"] == ["COUNTERPARTY_NAME_NOT_FOUND:1"]


# ---------------------------------------------------------------- every tool rejects unknown arguments


async def test_every_published_tool_schema_forbids_additional_properties():
    mcp, *_ = build()
    tools = await mcp.list_tools()
    assert len(tools) > 20
    assert [t.name for t in tools if t.input_schema.get("additionalProperties") is not False] == []


@pytest.mark.parametrize("misnamed", ["filter", "$filter", "query", "where"])
async def test_onec_read_with_a_misnamed_filter_is_rejected_not_answered_unfiltered(misnamed):
    mcp, _audit, onec, company = build()
    with pytest.raises(ToolError) as raised:
        await mcp.call_tool("onec_read", {
            "source_id": "source-1", "entity_set": "ChartOfAccounts_Хозрасчетный",
            "select": ["Code"], misnamed: "Code eq '521.1'"})
    assert misnamed in str(raised.value)
    onec.read.assert_not_awaited()
