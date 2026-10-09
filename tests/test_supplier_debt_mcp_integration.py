"""Public MCP enrichment: supplier names cannot bypass raw catalog ACL/audit."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from tests.test_analytics_balance_mapping import REF1, good_mapping
from tests.test_analytics_balance_routing import SOURCE, build, call, payload
from tests.test_server_audit import TestRegistry


def exact_5211_mapping():
    mapping = good_mapping()
    mapping["accounts"] = mapping["accounts"][:1]
    return mapping


@pytest.mark.asyncio
async def test_complete_supplier_summary_authorized_catalog_read_is_audited(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda entity: entity == "Catalog_Контрагенты",
                        raising=False)
    mcp, audit, onec, _com, company = build("AVAILABLE", mapping=exact_5211_mapping())
    onec.read = AsyncMock(return_value={
        "value": [{"Ref_Key": REF1, "Description": "Verified Supplier"}],
        "page": {"has_more": False, "truncated": False},
    })
    result = payload(await call(mcp, company))
    summary = result["supplier_summary"]
    assert summary["status"] == "COMPLETE"
    assert summary["scope"] == "ACCOUNT_521_1_ONLY"
    assert summary["suppliers"][0]["supplier_name"] == "Verified Supplier"
    assert summary["total_balance_credit"] == "0"
    assert summary["total_balance_debit"] == "10.5"
    assert summary["name_lookup_status"] == "COMPLETE"
    assert onec.read.await_count == 1
    assert any(e["tool"] == "onec_read" and e["detail_code"] == "ACCESS_AUTHORIZED" for e in audit.events)
    assert any(e["tool"] == "onec_read" and e["outcome"] == "success" for e in audit.events)


@pytest.mark.asyncio
async def test_raw_catalog_denied_still_returns_ledger_but_no_name(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda _entity: True, raising=False)
    monkeypatch.setattr(TestRegistry, "require_source",
                        AsyncMock(side_effect=PermissionError("RAW_CATALOG_DENIED")))
    mcp, audit, onec, _com, company = build("AVAILABLE", mapping=exact_5211_mapping())
    onec.read = AsyncMock()
    result = payload(await call(mcp, company))
    summary = result["supplier_summary"]
    assert summary["status"] == "COMPLETE"
    assert summary["name_lookup_status"] == "DENIED_BY_POLICY"
    assert summary["suppliers"][0]["supplier_name"] is None
    onec.read.assert_not_awaited()
    assert any(e["tool"] == "onec_read" and e["outcome"] == "denied" for e in audit.events)



@pytest.mark.asyncio
async def test_name_lookup_audit_completion_failure_cannot_appear_as_success(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda _entity: True, raising=False)
    mcp, audit, onec, _com, company = build("AVAILABLE", mapping=exact_5211_mapping())
    onec.read = AsyncMock(return_value={
        "value": [{"Ref_Key": REF1, "Description": "Known"}],
        "page": {"has_more": False, "truncated": False},
    })
    original = audit.write

    async def failed_catalog_completion(**event):
        if (event.get("tool") == "onec_read" and event.get("outcome") == "success"
                and event.get("detail_code") != "ACCESS_AUTHORIZED"):
            raise RuntimeError("private-audit-failed")
        await original(**event)

    audit.write = failed_catalog_completion
    with pytest.raises(UnexpectedToolError) as error:
        await call(mcp, company)
    assert "private-audit-failed" not in str(error.value)
    assert onec.read.await_count == 1


@pytest.mark.asyncio
async def test_empty_complete_5211_returns_zero_in_first_response():
    mcp, _audit, onec, _com, company = build(
        "AVAILABLE", mapping=exact_5211_mapping(),
        odata_result={"value": [], "page": {"has_more": False, "truncated": False}},
    )
    result = payload(await call(mcp, company))
    summary = result["supplier_summary"]
    assert summary["status"] == "COMPLETE"
    assert summary["counterparty_count"] == 0
    assert summary["total_balance_credit"] == "0"
    assert summary["total_balance_debit"] == "0"
    assert summary["name_lookup_status"] == "NO_SUPPLIERS"
    assert not hasattr(onec, "read")


@pytest.mark.asyncio
async def test_many_account_profile_never_labels_partial_data_as_5211_report():
    mcp, _audit, _onec, _com, company = build("AVAILABLE", mapping=good_mapping())
    result = payload(await call(mcp, company))
    assert result["supplier_summary"] is None
