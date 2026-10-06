"""Supporting L1 evidence read through the public raw `onec_read` tool.

These do NOT change a scenario's status: raw rows are not the scenario's semantic tool and
Fake1C is synthetic. They prove what the synthetic source actually serves (so a later reviewed
profile can be validated against it) and expose seed inconsistencies. Company filtering is done
client-side here because Fake1C ignores $filter/$select.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.functional.support import harness as h
from tests.functional.support.evidence import record


async def raw(entity: str, top: int = 50):
    out = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": entity, "top": top})
    assert out.ok, out.text
    assert {r["method"] for r in out.upstream} <= {"GET", "HEAD"}
    rows = out.data["value"]
    assert len(rows) <= 200
    return rows, out


def org(rows, company):
    return [r for r in rows if r.get("Организация_Key") == company]


async def test_sc04_raw_unposted_document_has_no_movement_rows():
    docs, _ = await raw("Document_Sales")
    unposted = [d for d in docs if d["Posted"] is False]
    assert [d["Number"] for d in unposted] == ["SALE-002"]
    refs = {d["Ref_Key"] for d in unposted}
    for reg in ("AccumulationRegister_InventoryMovements", "AccumulationRegister_CashMovements"):
        rows, _ = await raw(reg)
        recorders = {r.get("Recorder_Key") or r.get("Recorder") for r in rows}
        assert refs.isdisjoint(recorders), f"unposted document has movements in {reg}"
    record("SC04", supporting_raw="Document_Sales SALE-002 Posted=false; no recorder match in movement registers")


async def test_sc01_raw_receivable_register_has_no_overdue_dimension():
    rows, _ = await raw("AccumulationRegister_ReceivableBalances")
    assert rows and all("СуммаBalance" in r for r in rows)
    assert not any("overdue" in k.lower() or "due" in k.lower() for r in rows for k in r)
    record("SC01", supporting_raw="receivable register carries amount only; no due-date field to derive overdue_30d")


async def test_sc11_raw_inventory_receipt_minus_expense_equals_net():
    rows, _ = await raw("AccumulationRegister_InventoryMovements")
    rows = org(rows, h.COMPANY_ONE)
    rec = sum(Decimal(str(r["Количество"])) for r in rows if r["RecordType"] == "Receipt")
    exp = sum(Decimal(str(r["Количество"])) for r in rows if r["RecordType"] == "Expense")
    assert (rec, exp, rec - exp) == (Decimal(7), Decimal(2), Decimal(5))
    record("SC11", supporting_raw="raw receipt 7 - expense 2 = 5 (magnitudes positive in source; sign is the tool's job)")


async def test_sc12_raw_cash_receipt_minus_expense_equals_net():
    rows, _ = await raw("AccumulationRegister_CashMovements")
    rows = org(rows, h.COMPANY_ONE)
    rec = sum(Decimal(str(r["Сумма"])) for r in rows if r["RecordType"] == "Receipt")
    exp = sum(Decimal(str(r["Сумма"])) for r in rows if r["RecordType"] == "Expense")
    assert (rec, exp, rec - exp) == (Decimal(10), Decimal(3), Decimal(7))
    record("SC12", supporting_raw="raw receipt 10 - expense 3 = 7")


async def test_sc09_raw_bank_and_cash_are_separate_registers():
    bank, _ = await raw("AccumulationRegister_BankBalances")
    cash, _ = await raw("AccumulationRegister_CashMovements")
    assert {r["БанковскийСчет_Key"] for r in bank}.isdisjoint({r["СчетДенежныхСредств_Key"] for r in cash})
    assert sum(Decimal(str(r["СуммаBalance"])) for r in org(bank, h.COMPANY_ONE)) == Decimal(250)
    record("SC09", supporting_raw="bank register 250 separate from cash register accounts")


async def test_seed_consistency_sc09_cash_fixture_matches_cash_register():
    """Scenario fixture says cash_balance=100; the served cash register nets to 7."""
    rows, _ = await raw("AccumulationRegister_CashMovements")
    net = sum((Decimal(str(r["Сумма"])) if r["RecordType"] == "Receipt" else -Decimal(str(r["Сумма"])))
              for r in org(rows, h.COMPANY_ONE))
    record("SC09", seed_defect=f"SEED-002 cash fixture 100 vs register net {net}")
    if net != Decimal(100):
        pytest.xfail(f"SEED-002: scenario fixture cash_balance=100 but Fake1C cash register nets to {net}")


async def test_seed_consistency_sc05_inventory_balance_matches_movement_net():
    """Fake1C inventory balance row (7) must equal receipts - expenses from its own movements."""
    bal, _ = await raw("AccumulationRegister_InventoryBalances")
    mov, _ = await raw("AccumulationRegister_InventoryMovements")
    balance = sum(Decimal(str(r["КоличествоBalance"])) for r in org(bal, h.COMPANY_ONE))
    net = sum((Decimal(str(r["Количество"])) if r["RecordType"] == "Receipt" else -Decimal(str(r["Количество"])))
              for r in org(mov, h.COMPANY_ONE))
    record("SC05", seed_defect=f"SEED-001 inventory balance {balance} vs movement net {net}")
    if balance != net:
        pytest.xfail(f"SEED-001: Fake1C inventory balance {balance} disagrees with movement net {net}")


async def test_raw_read_bounded_by_top():
    rows, _ = await raw("Document_Sales", top=1)
    assert len(rows) == 1
    record("SC04", bounded="onec_read top=1 returned exactly 1 row")
