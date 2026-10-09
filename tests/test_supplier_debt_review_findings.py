"""Review findings: bounded catalog paging/ACL, canonical refs and response budgets."""
from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.settings import Settings
from business_ai_gateway.supplier_debt_summary import supplier_filter_batches
from tests import test_analytics_balance_routing as routing
from tests.test_analytics_balance_mapping import REF1, good_mapping, odata_row
from tests.test_analytics_balance_routing import SOURCE, build, call, payload


def _mapping():
    mapping = good_mapping()
    mapping["accounts"] = mapping["accounts"][:1]
    return mapping


def _source(monkeypatch):
    monkeypatch.setattr(SOURCE, "entity_allowed", lambda n: n == "Catalog_Контрагенты",
                        raising=False)


def _refs(n):
    return [f"{i:08x}-1111-4111-8111-111111111111" for i in range(1, n + 1)]


def _rows(refs):
    return {"value": [odata_row(ExtDimension1=ref) for ref in refs],
            "page": {"has_more": False, "truncated": False}}


def _catalog_names(refs, *, with_page=True, uppercase=False, long_name=0):
    vals = [{"Ref_Key": ref.upper() if uppercase else ref,
             "Description": "S" * long_name if long_name else f"Supplier-{ref[:8]}"}
            for ref in refs]
    result = {"value": vals}
    if with_page:
        result["page"] = {"has_more": False, "truncated": False}
    return result


def test_predicate_batches_are_guid_only_and_under_the_limit():
    refs = _refs(160)
    batches = supplier_filter_batches(refs, max_filter_chars=4000)
    assert len(batches) >= 2
    assert [ref for group, _ in batches for ref in group] == refs
    assert all(len(filter_expr) <= 4000 for _group, filter_expr in batches)
    assert all(" or " not in s or len(s.split(" or ")) == len(group)
               for group, s in batches)
    with pytest.raises(ValueError, match="SUPPLIER_CATALOG_FILTER_LIMIT"):
        supplier_filter_batches(refs[:1], max_filter_chars=20)


@pytest.mark.asyncio
async def test_150_supplier_names_use_separate_scoped_audited_batches(monkeypatch):
    _source(monkeypatch)
    refs = _refs(150)
    mcp, audit, onec, _com, company = build(
        "AVAILABLE", mapping=_mapping(), odata_result=_rows(refs)
    )

    async def catalog_read(_source, **kwargs):
        assert kwargs["entity_set"] == "Catalog_Контрагенты"
        assert len(kwargs["filter_expr"]) <= Settings().max_filter_chars
        selected = re.findall(r"guid'([0-9a-f-]{36})'", kwargs["filter_expr"])
        assert len(selected) < kwargs["top"]
        return _catalog_names(selected)

    onec.read = AsyncMock(side_effect=catalog_read)
    result = payload(await call(mcp, company))
    summary = result["supplier_summary"]
    assert summary["status"] == "COMPLETE"
    assert summary["name_lookup_status"] == "COMPLETE"
    assert summary["counterparty_count"] == 150
    assert all(item["supplier_name"] for item in summary["suppliers"])
    assert onec.read.await_count == len(
        supplier_filter_batches(refs, max_filter_chars=Settings().max_filter_chars))
    assert len([e for e in audit.events
                if e["tool"] == "onec_read" and e["detail_code"] == "ACCESS_AUTHORIZED"
                ]) == onec.read.await_count


@pytest.mark.parametrize("no_page", [False, True])
async def test_catalog_guid_case_is_canonical_and_pageless_supported(monkeypatch, no_page):
    _source(monkeypatch)
    mcp, _audit, onec, _com, company = build("AVAILABLE", mapping=_mapping())
    onec.read = AsyncMock(return_value=_catalog_names([REF1], with_page=not no_page,
                                                      uppercase=True))
    summary = payload(await call(mcp, company))["supplier_summary"]
    assert summary["status"] == "COMPLETE"
    assert summary["name_lookup_status"] == "COMPLETE"
    assert summary["suppliers"][0]["supplier_name"] == f"Supplier-{REF1[:8]}"


@pytest.mark.asyncio
async def test_pageless_at_top_is_inconclusive_not_complete(monkeypatch):
    _source(monkeypatch)
    mcp, _audit, onec, _com, company = build("AVAILABLE", mapping=_mapping())
    onec.read = AsyncMock(return_value=_catalog_names([REF1, _refs(1)[0]],
                                                      with_page=False))
    summary = payload(await call(mcp, company))["supplier_summary"]
    assert summary["name_lookup_status"] == "INCOMPLETE"
    assert summary["suppliers"][0]["supplier_name"] is None


@pytest.mark.asyncio
async def test_unrequested_guid_is_never_accepted_as_supplier(monkeypatch):
    _source(monkeypatch)
    mcp, audit, onec, _com, company = build("AVAILABLE", mapping=_mapping())
    onec.read = AsyncMock(return_value=_catalog_names([_refs(1)[0]]))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert any(str(e.get("detail_code", "")).startswith("SUPPLIER_CATALOG_RESPONSE_INVALID") for e in audit.events)


@pytest.mark.asyncio
async def test_mid_batch_policy_revoke_discards_earlier_names(monkeypatch):
    _source(monkeypatch)
    refs = _refs(150)
    mcp, _audit, onec, _com, company = build(
        "AVAILABLE", mapping=_mapping(), odata_result=_rows(refs)
    )
    first = True

    async def catalog_read(_source, **kwargs):
        nonlocal first
        if first:
            first = False
            selected = re.findall(r"guid'([0-9a-f-]{36})'", kwargs["filter_expr"])
            return _catalog_names(selected)
        raise PermissionError("policy revoked")

    onec.read = AsyncMock(side_effect=catalog_read)
    summary = payload(await call(mcp, company))["supplier_summary"]
    assert summary["name_lookup_status"] == "DENIED_BY_POLICY"
    assert not any(row["supplier_name"] for row in summary["suppliers"])


@pytest.mark.asyncio
async def test_merged_response_limit_is_enforced_before_success_audit(monkeypatch):
    _source(monkeypatch)
    monkeypatch.setattr(routing, "Settings", lambda: Settings(max_response_bytes=10_000))
    refs = _refs(4)
    mcp, audit, onec, _com, company = routing.build(
        "AVAILABLE", mapping=_mapping(), odata_result=_rows(refs)
    )
    # The catalog fits under 10 KB, but duplicating the labels in the
    # supplier summary alongside the ledger exceeds the MCP response cap.
    onec.read = AsyncMock(return_value=_catalog_names(refs, long_name=2100))
    with pytest.raises(UnexpectedToolError):
        await routing.call(mcp, company)
    assert any(str(e.get("detail_code", "")).startswith("RESPONSE_TOO_LARGE") for e in audit.events)
    assert not any(e.get("tool") == "accounting_balance_by_analytics"
                   and e.get("outcome") == "success"
                   and e.get("detail_code", "").startswith("route=")
                   for e in audit.events)
