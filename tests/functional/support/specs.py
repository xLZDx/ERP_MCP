# ruff: noqa: C408
"""Static scenario catalogue (questions, public tools, dispositions).

Expected invariants come from testbed/scenarios/accounting_scenarios.json (`FIX`, seed
scenario_fixtures) and the product lane's declared Fake1C data (docs/SEMANTIC_PROFILES.md,
core/DECISION_LOG.md SC steps 1-4). They are the ORACLE only; results always come from the live MCP
tools. Nothing here is a test result.
"""

from __future__ import annotations

import json

from tests.functional.support.harness import REPO_ROOT

SEED = json.loads((REPO_ROOT / "testbed/fake1c/fixtures/seed.json").read_text(encoding="utf-8"))
FIX = SEED["scenario_fixtures"]

AS_OF = "2026-04-30T00:00:00+00:00"
APRIL = {"start_period": "2026-04-01T00:00:00+00:00", "end_period": "2026-04-30T00:00:00+00:00"}
DECEMBER = {"start_period": "2025-12-01T00:00:00+00:00", "end_period": "2026-01-01T00:00:00+00:00"}
WIDE = {"start_period": "2025-01-01T00:00:00+00:00", "end_period": "2027-01-01T00:00:00+00:00"}
CASH_WINDOW = {"start_period": "2026-03-01T00:00:00+00:00", "end_period": "2026-05-01T00:00:00+00:00"}
BANK_AS_OF = "2026-05-01T00:00:00+00:00"

PARTY_OVERDUE = "10000000-0000-0000-0000-000000000001"
PARTY_PARTIAL = "10000000-0000-0000-0000-000000000004"
PARTY_OVERPAID = "10000000-0000-0000-0000-000000000005"
# The two duplicate counterparties of seed.json (C001 and C001D, both "Synthetic customer").
PARTY_DUP_A = "10000000-0000-0000-0000-000000000001"
PARTY_DUP_B = "10000000-0000-0000-0000-000000000003"
ITEM_1 = "30000000-0000-0000-0000-000000000001"
ITEM_2 = "30000000-0000-0000-0000-000000000002"

# tool: primary public tool; neg_tool: a related tool with NO fixture profile (capability negative);
# disposition: fixed non-PASS status for scenarios that stay out of reach by decision.
SPECS = {
    "SC01": dict(slug="ar-overdue-30d", question="Receivables overdue more than 30 days",
                 tools=["receivable_aging"], neg_tool="payable_aging"),
    "SC02": dict(slug="partial-payment", question="Invoice with partial payment remains open",
                 tools=["receivable_aging"], neg_tool="payable_aging"),
    "SC03": dict(slug="overpayment", question="Customer overpayment is separated from receivable",
                 tools=["receivable_aging"], neg_tool="payable_aging"),
    "SC04": dict(slug="unposted-document", question="Unposted document does not create accounting movement",
                 tools=["sales_documents", "accounting_posting_rows"], neg_tool="purchase_documents"),
    "SC05": dict(slug="return", question="Return reduces the relevant movement",
                 tools=["inventory_movements", "inventory_balance"], neg_tool="receivable_balance"),
    "SC06": dict(slug="vat-mixed", question="Different VAT treatments remain distinguishable",
                 tools=["sales_documents"], neg_tool="purchase_documents",
                 disposition="EXTERNAL-GATE", missing_regex=r"vat|tax",
                 missing="VAT/tax views exist only when a source/company profile is validated (freeze 3.3 "
                         "'VAT/tax views only when validated'); no VAT tool or fixture profile exists"),
    "SC07": dict(slug="backdated-document", question="Backdated document appears in the correct accounting period",
                 tools=["sales_documents", "accounting_posting_rows"], neg_tool="purchase_documents"),
    "SC08": dict(slug="duplicate-counterparty", question="Potential duplicate counterparties are identified without merge",
                 tools=["counterparty_duplicate_candidates"], neg_tool="purchase_documents"),
    "SC09": dict(slug="cash-bank", question="Cash and bank balances remain separate and sum to combined",
                 tools=["cash_movements", "bank_balance"], neg_tool="payable_balance"),
    "SC10": dict(slug="account-turnover", question="Opening, turnover and closing values reconcile",
                 tools=["accounting_balance_and_turnovers"], neg_tool="receivable_balance"),
    "SC11": dict(slug="inventory-receipt-expense", question="Inventory movement signs reconcile to net quantity",
                 tools=["inventory_movements"], neg_tool="receivable_balance"),
    "SC12": dict(slug="cash-receipt-expense", question="Cash movement signs reconcile to net amount",
                 tools=["cash_movements"], neg_tool="payable_balance"),
}


def args_for(tool: str, source_id: str, company_id: str, **extra) -> dict:
    base = {"source_id": source_id, "company_id": company_id}
    if tool in {"receivable_aging", "payable_aging"}:
        return {**base, "as_of": AS_OF, **extra}
    if tool == "counterparty_duplicate_candidates":
        return {**base, **extra}  # input is exactly source_id, company_id, top (default 2000)
    if tool in {"inventory_balance", "receivable_balance", "payable_balance"}:
        return {**base, "period": AS_OF, **extra}
    if tool == "bank_balance":
        return {**base, "period": BANK_AS_OF, **extra}
    if tool in {"inventory_movements", "cash_movements", "accounting_posting_rows",
                "accounting_balance_and_turnovers"}:
        return {**base, **APRIL, **extra}
    return {**base, **extra}
