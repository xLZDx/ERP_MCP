"""SC04/SC05/SC07/SC09 (and later steps) through public MCP tools on Fake1C + fixture profiles.

Chain: MCP tool -> resolve_source/ACL -> registry (fixture profile) -> adapter -> fake sidecar /
Fake1C -> audit rows. Synthetic L1 evidence only; never native reconciliation."""

from __future__ import annotations

import os
from collections import defaultdict
from decimal import Decimal

import pytest

from tests.sc_stack import ORG_ONE, ORG_TWO
from tests.test_synthetic_fixture_profiles import _stack

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL")
ITEM_1 = "30000000-0000-0000-0000-000000000001"
ITEM_2 = "30000000-0000-0000-0000-000000000002"


async def _call(stack, tool, org=ORG_ONE, **arguments):
    result = await stack.call(
        tool, source_id=stack.source_id, company_id=str(stack.companies[org]), **arguments
    )
    assert not result.is_error
    body = stack.payload(result)
    assert body["profile_kind"] == "SYNTHETIC_FIXTURE"
    assert body["native_reconciliation"] == "NOT_RUN" and body["evidence_level"] == "L1"
    return body


@pytest.mark.asyncio
async def test_sc04_unposted_sale_has_no_accounting_posting(fake1c, fake_sidecar, tmp_path, monkeypatch):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        sales = (await _call(stack, "sales_documents"))["value"]
        posted = {r["document_number"]: r["posted"] for r in sales}
        assert posted["SALE-001"] is True and posted["SALE-003"] is False
        assert "SALE-002" not in posted  # belongs to organization two
        rows = (await _call(
            stack, "accounting_posting_rows",
            start_period="2025-01-01T00:00:00+00:00", end_period="2027-01-01T00:00:00+00:00",
        ))["value"]
        recorders = {r["recorder_ref"] for r in rows}
        by_number = {r["document_number"]: r["document_ref"] for r in sales}
        assert by_number["SALE-001"] in recorders
        assert by_number["SALE-003"] not in recorders
        assert len(await stack.audit_rows("accounting_posting_rows")) >= 2
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_sc07_backdated_sale_posts_to_its_accounting_period(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        sales = {r["document_number"]: r for r in (await _call(stack, "sales_documents"))["value"]}
        backdated = sales["SALE-004"]
        assert backdated["date"].startswith("2025-12-31")
        december = (await _call(
            stack, "accounting_posting_rows",
            start_period="2025-12-01T00:00:00+00:00", end_period="2026-01-01T00:00:00+00:00",
        ))["value"]
        assert [r["recorder_ref"] for r in december] == [backdated["document_ref"]]
        assert december[0]["period"][:7] == "2025-12"
        april = (await _call(
            stack, "accounting_posting_rows",
            start_period="2026-04-01T00:00:00+00:00", end_period="2026-04-30T00:00:00+00:00",
        ))["value"]
        assert backdated["document_ref"] not in {r["recorder_ref"] for r in april}
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_sc05_return_reduces_movement_and_reconciles_to_balance_per_item(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        moves = (await _call(
            stack, "inventory_movements",
            start_period="2026-04-01T00:00:00+00:00", end_period="2026-04-30T00:00:00+00:00",
        ))["value"]
        net: dict[str, Decimal] = defaultdict(Decimal)
        for row in moves:
            net[row["item_ref"]] += Decimal(row["quantity_delta"])
        item2 = [r for r in moves if r["item_ref"] == ITEM_2]
        assert [Decimal(r["quantity_delta"]) for r in item2] == [Decimal(10), Decimal(-3)]
        balance = (await _call(stack, "inventory_balance", period="2026-04-30T00:00:00+00:00"))
        by_item = {r["item_ref"]: Decimal(str(r["quantity"])) for r in balance["value"]}
        assert by_item == dict(net) == {ITEM_1: Decimal(5), ITEM_2: Decimal(7)}
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_sc09_cash_and_bank_remain_separate_and_sum_to_combined(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        cash = (await _call(
            stack, "cash_movements",
            start_period="2026-03-01T00:00:00+00:00", end_period="2026-05-01T00:00:00+00:00",
        ))["value"]
        cash_total = sum(Decimal(r["amount_delta"]) for r in cash)
        bank = (await _call(stack, "bank_balance", period="2026-05-01T00:00:00+00:00"))["value"]
        bank_total = sum(Decimal(str(r["amount"])) for r in bank)
        assert (cash_total, bank_total, cash_total + bank_total) == (100, 250, 350)
        april = (await _call(
            stack, "cash_movements",
            start_period="2026-04-01T00:00:00+00:00", end_period="2026-04-30T00:00:00+00:00",
        ))["value"]
        assert sum(Decimal(r["amount_delta"]) for r in april) == 7
        # company two sees none of company one's cash or bank rows
        assert (await _call(stack, "bank_balance", org=ORG_TWO,
                            period="2026-05-01T00:00:00+00:00"))["value"] == []
    finally:
        await stack.db.close()
