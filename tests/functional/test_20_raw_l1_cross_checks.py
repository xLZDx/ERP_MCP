"""Independent cross-checks: semantic tool output vs raw rows read through the raw `onec_read` tool.

The raw path (EntitySet read) is a second public route to the same synthetic data, so a tool that
mis-signs or mis-scopes rows disagrees with it. Company filtering is client-side here (the raw
read is deliberately unprofiled). Synthetic L1 only.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from tests.functional.support import harness as h
from tests.functional.support.evidence import record
from tests.functional.support.specs import APRIL, CASH_WINDOW, args_for

D = Decimal


async def raw(entity: str):
    out = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": entity, "top": 100})
    assert out.ok, out.text
    assert h.no_write_reached_1c(out)
    rows = out.data["value"]
    assert len(rows) <= 200
    return [r for r in rows if r.get("Организация_Key") in (None, h.COMPANY_ONE)]


def in_window(period: str, window: dict) -> bool:
    return window["start_period"][:19] <= period[:19] < window["end_period"][:19]


async def test_sc11_sc05_tool_item_nets_match_raw_register_and_balance_register():
    raw_moves = [r for r in await raw("AccumulationRegister_InventoryMovements") if in_window(r["Period"], APRIL)]
    raw_net: dict[str, Decimal] = defaultdict(D)
    for r in raw_moves:
        raw_net[r["Номенклатура_Key"]] += D(str(r["Количество"])) * (1 if r["RecordType"] == "Receipt" else -1)
    tool = (await h.call("inventory_movements", args_for("inventory_movements", h.SOURCE_ID, h.COMPANY_ONE))).data["value"]
    tool_net: dict[str, Decimal] = defaultdict(D)
    for r in tool:
        tool_net[r["item_ref"]] += D(r["quantity_delta"])
    raw_balance = {r["Номенклатура_Key"]: D(str(r["КоличествоBalance"]))
                   for r in await raw("AccumulationRegister_InventoryBalances")}
    assert dict(tool_net) == dict(raw_net) == raw_balance, "movement net must equal balance register (seed consistency)"
    record("SC05", cross_check=f"tool per-item net == raw movements == raw balance register {dict(raw_balance)}")
    record("SC11", cross_check="tool signed deltas == raw receipt/expense magnitudes with sign applied")


async def test_sc12_sc09_cash_tool_matches_raw_register_for_both_windows():
    raw_cash = await raw("AccumulationRegister_CashMovements")

    def net(window):
        return sum(D(str(r["Сумма"])) * (1 if r["RecordType"] == "Receipt" else -1)
                   for r in raw_cash if in_window(r["Period"], window))

    for window in (APRIL, CASH_WINDOW):
        tool = (await h.call("cash_movements", args_for("cash_movements", h.SOURCE_ID, h.COMPANY_ONE, **window))).data["value"]
        assert sum(D(r["amount_delta"]) for r in tool) == net(window)
    assert (net(APRIL), net(CASH_WINDOW)) == (D(7), D(100))
    record("SC12", cross_check="April tool net 7 == raw receipt-expense")
    record("SC09", cross_check="window 2026-03-01..05-01 tool net 100 == raw; SEED-002 resolved")


async def test_sc04_unposted_document_has_no_raw_ledger_rows():
    sales = await raw("Document_Sales")
    unposted = {d["Ref_Key"] for d in sales if d["Posted"] is False}
    assert {d["Number"] for d in sales if d["Ref_Key"] in unposted} == {"SALE-003"}
    ledger = await raw("AccountingRegister_Ledger")
    assert unposted.isdisjoint({r["Recorder"] for r in ledger})
    record("SC04", cross_check="raw Document_Sales SALE-003 Posted=false has no raw AccountingRegister_Ledger row")


async def test_raw_read_bounded_by_top():
    out = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales", "top": 1})
    assert out.ok and len(out.data["value"]) == 1
    record("SC04", bounded="onec_read top=1 returned exactly 1 row")
