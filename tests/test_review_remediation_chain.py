"""Review remediation F1-F6: aging fails closed and is audited honestly (MCP -> adapter -> sidecar)."""

from __future__ import annotations

import json
import os
import re
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.adapters.onec.sidecar_client import UPSTREAM_SHA, ODataSidecarClient
from business_ai_gateway.fixture_profiles import profile_provenance
from tests.sc_stack import ORG_ONE
from tests.test_synthetic_fixture_profiles import _stack

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
needs_pg = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL")
AS_OF = "2026-04-30T00:00:00+00:00"
MARKER = "SYNTHETIC_FIXTURE_PROFILE"


def _tamper_sidecar(stack, mutate):
    """Route sidecar traffic through a proxy that rewrites read responses (raw bytes)."""
    original = stack.runtime.onec.sidecar._client
    upstream = httpx.AsyncClient(base_url=str(original.base_url), headers=original.headers)

    async def handler(request: httpx.Request) -> httpx.Response:
        response = await upstream.post(
            request.url.path, content=request.content, headers={"content-type": "application/json"}
        )
        body = response.content
        if request.url.path.endswith("/v1/read") and b'"register_read"' not in request.content:
            body = mutate(body)
        return httpx.Response(response.status_code, content=body)

    stack.runtime.onec.sidecar._client = httpx.AsyncClient(
        base_url=str(original.base_url), headers=original.headers,
        transport=httpx.MockTransport(handler),
    )


async def _call(stack, **extra):
    return await stack.call(
        "receivable_aging", source_id=stack.source_id,
        company_id=str(stack.companies[ORG_ONE]), as_of=AS_OF, **extra,
    )


def _set_truncated(body: bytes) -> bytes:
    data = json.loads(body)
    data["page"]["truncated"] = True
    data["page"]["has_more"] = True
    return json.dumps(data).encode()


@needs_pg
@pytest.mark.asyncio
async def test_f1_page_truncated_flag_makes_aging_inconclusive_and_audited_error(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        _tamper_sidecar(stack, _set_truncated)
        body = stack.payload(await _call(stack))
        assert body["status"] == "INCONCLUSIVE" and body["reason"] == "AGING_ROWS_TRUNCATED"
        assert body["truncated"] is True and body["rows"] == [] and body["summary"] == []
        row = (await stack.audit_rows("receivable_aging"))[-1]
        assert row["outcome"] == "error"
        assert row["detail_code"] == f"{MARKER}:AGING_ROWS_TRUNCATED"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_f2_imprecise_float_amount_is_rejected_not_rounded(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        _tamper_sidecar(
            stack,
            lambda b: re.sub(rb'"Amount":\s*[-0-9.eE]+', b'"Amount":1234567890123456.78', b, count=1),
        )
        body = stack.payload(await _call(stack))
        assert body["status"] == "INCONCLUSIVE" and body["reason"] == "SETTLEMENT_FACT_INVALID"
        assert body["rows"] == [] and body["summary"] == []
        row = (await stack.audit_rows("receivable_aging"))[-1]
        assert row["outcome"] == "error" and row["detail_code"] == f"{MARKER}:SETTLEMENT_FACT_INVALID"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_f4_unhashable_record_type_is_bad_data_but_internal_bug_is_error(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        _tamper_sidecar(
            stack, lambda b: re.sub(rb'"RecordType":\s*"[^"]*"', b'"RecordType":["x"]', b, count=1)
        )
        body = stack.payload(await _call(stack))
        assert body["reason"] == "SETTLEMENT_FACT_INVALID"
        assert (await stack.audit_rows("receivable_aging"))[-1]["outcome"] == "error"
    finally:
        await stack.db.close()
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        def boom(*args, **kwargs):
            raise TypeError("internal defect")

        monkeypatch.setattr("business_ai_gateway.settlement_collector.evaluate_aging", boom)
        with pytest.raises(UnexpectedToolError):
            await _call(stack)
        row = (await stack.audit_rows("receivable_aging"))[-1]
        assert row["outcome"] == "error"
        assert row["detail_code"] == f"{MARKER}:TypeError"
        assert row["profile_fingerprint"].startswith("synthetic-fixture:")
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_f5_response_without_value_list_is_not_an_empty_pass(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        stack.runtime.onec.read = AsyncMock(return_value={"page": {"truncated": False}})
        body = stack.payload(await _call(stack))
        assert body["status"] == "INCONCLUSIVE" and body["reason"] == "SOURCE_RESPONSE_INVALID"
        assert (await stack.audit_rows("receivable_aging"))[-1]["outcome"] == "error"
    finally:
        await stack.db.close()


def test_f6_unknown_profile_provenance_raises_instead_of_claiming_native():
    with pytest.raises(ValueError, match="PROFILE_PROVENANCE_UNKNOWN"):
        profile_provenance({})
    assert profile_provenance({"profile_kind": "VALIDATED_NATIVE"})["profile_kind"] == "VALIDATED_NATIVE"


@pytest.mark.asyncio
async def test_f1_sidecar_client_read_propagates_page_flags():
    page = {"returned": 1, "has_more": True, "truncated": True}

    async def respond(request):
        return httpx.Response(200, json={
            "source_id": "source-1", "adapter": {"kind": "ODATA_JSON_V3", "upstream_sha": UPSTREAM_SHA},
            "operation": "query", "data": [{"a": 1}], "page": page,
        })

    from tests.test_odata_sidecar_client import source

    client = ODataSidecarClient(
        base_url="http://odata-sidecar:8765", token="t" * 48, timeout_seconds=2,
        max_response_bytes=10000, max_rows=200, transport=httpx.MockTransport(respond),
    )
    result = await client.read(
        source(),
        username="u", password="p", entity_set="Document_Invoice", select=None,
        filter_expr=None, orderby=None, expand=None, top=5, skip=0,
    )
    assert result["page"] == page and result["value"] == [{"a": 1}]
