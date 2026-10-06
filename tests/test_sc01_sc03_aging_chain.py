"""SC01-SC03: receivable aging through the public MCP tool (synthetic L1, never native)."""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from tests.sc_stack import ORG_ONE, ORG_TWO, PG_MARKS
from tests.test_synthetic_fixture_profiles import _stack

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = PG_MARKS
AS_OF = "2026-04-30T00:00:00+00:00"
OVERDUE = "10000000-0000-0000-0000-000000000001"
PARTIAL = "10000000-0000-0000-0000-000000000004"
OVERPAID = "10000000-0000-0000-0000-000000000005"


async def _aging(stack, org=ORG_ONE, tool="receivable_aging", **extra):
    result = await stack.call(
        tool, source_id=stack.source_id, company_id=str(stack.companies[org]), as_of=AS_OF, **extra
    )
    assert not result.is_error
    return stack.payload(result)


def _by_party(body, key):
    return {r["counterparty_id"]: r for r in body[key]}


@pytest.mark.asyncio
async def test_sc01_sc02_sc03_aging_buckets_partial_payment_and_overpayment(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        body = await _aging(stack)
        assert body["status"] == "PASS" and body["kind"] == "AR"
        assert body["profile_kind"] == "SYNTHETIC_FIXTURE" and body["evidence_level"] == "L1"
        assert body["native_reconciliation"] == "NOT_RUN" and body["native_approval_inferred"] is False
        assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" in body["warnings"]
        rows = _by_party(body, "rows")
        summary = _by_party(body, "summary")
        # SC01: 500 open, 420 overdue more than 30 days
        buckets = rows[OVERDUE]["buckets"]
        overdue = sum(Decimal(buckets[k]) for k in ("days_31_60", "days_61_90", "days_91_plus"))
        assert overdue == 420 and Decimal(summary[OVERDUE]["open_balance"]) == 500
        assert (buckets["days_61_90"], buckets["days_31_60"], buckets["days_1_30"]) == ("200", "220", "80")
        # SC02: invoice 1000, 250 applied, 750 open
        assert Decimal(summary[PARTIAL]["charged_total"]) == 1000
        assert Decimal(summary[PARTIAL]["payments_applied"]) == 250
        assert Decimal(summary[PARTIAL]["open_balance"]) == 750
        assert rows[PARTIAL]["buckets"]["days_1_30"] == "750"
        # SC03: invoice open 0, unapplied advance 125 kept separate from receivable
        assert Decimal(summary[OVERPAID]["open_balance"]) == 0
        assert Decimal(summary[OVERPAID]["unapplied_credit"]) == 125
        assert rows[OVERPAID]["unapplied_credit"] == "125"
        assert sum(Decimal(v) for v in rows[OVERPAID]["buckets"].values()) == 0
        # company two's 999 charge never reaches company one output
        assert "999" not in json.dumps(body["rows"]) + json.dumps(body["summary"])
        audit = await stack.audit_rows("receivable_aging")
        assert any(r["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE" for r in audit)
        assert len(json.dumps(body).encode()) < 20_000
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_aging_is_company_scoped_and_other_company_sees_only_its_own_items(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        body = await _aging(stack, org=ORG_TWO)
        summary = _by_party(body, "summary")
        assert list(summary) == [OVERDUE]
        assert summary[OVERDUE]["open_balance"] == "999"
        with pytest.raises(UnexpectedToolError):
            await stack.call(
                "receivable_aging", source_id=stack.source_id,
                company_id=str(uuid.uuid4()), as_of=AS_OF,
            )
        rows = await stack.audit_rows("receivable_aging")
        assert rows[-1]["outcome"] == "denied"
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_truncation_is_inconclusive_and_never_a_partial_answer(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        body = await _aging(stack, top=3)
        assert body["status"] == "INCONCLUSIVE" and body["reason"] == "AGING_ROWS_TRUNCATED"
        assert body["rows"] == [] and body["summary"] == [] and body["truncated"] is True
        audit = await stack.audit_rows("receivable_aging")
        assert audit[-1]["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE:AGING_ROWS_TRUNCATED"
        assert audit[-1]["outcome"] == "error"
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_unconfirmed_opening_items_and_missing_payable_profile_fail_closed(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        provider = stack.runtime.registry.synthetic_profiles
        for company in stack.companies.values():
            provider._sources[stack.source_id]["companies"][str(company)]["concepts"][
                "receivable.open_items"
            ]["opening_items_known"] = False
        body = await _aging(stack)
        assert body["status"] == "INCONCLUSIVE" and body["reason"] == "OPENING_ITEMS_UNCONFIRMED"
        with pytest.raises(UnexpectedToolError):
            await stack.call(
                "payable_aging", source_id=stack.source_id,
                company_id=str(stack.companies[ORG_ONE]), as_of=AS_OF,
            )
        rows = await stack.audit_rows("payable_aging")
        assert rows[-1]["detail_code"] == "SEMANTIC_PROFILE_UNVALIDATED"
        before = len(await stack.audit_rows("receivable_aging"))
        stack.runtime.onec.read = AsyncMock()
        with pytest.raises(UnexpectedToolError):
            await stack.call(
                "receivable_aging", source_id=stack.source_id,
                company_id=str(stack.companies[ORG_ONE]), as_of="2026-04-30",
            )
        # a naive as_of is rejected at input validation: no upstream read, no new audit row
        stack.runtime.onec.read.assert_not_awaited()
        assert len(await stack.audit_rows("receivable_aging")) == before
    finally:
        await stack.db.close()
