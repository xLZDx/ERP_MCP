# ruff: noqa: C408
"""Static scenario catalogue (questions, public tools, minimal missing interfaces).

Expected invariants come from testbed/scenarios/accounting_scenarios.json and the Fake1C seed
(oracle only; results always come from the live MCP tools). Nothing here is a test result.
"""

from __future__ import annotations

import json

from tests.functional.support.harness import REPO_ROOT

SEED = json.loads((REPO_ROOT / "testbed/fake1c/fixtures/seed.json").read_text(encoding="utf-8"))
FIX = SEED["scenario_fixtures"]

PERIOD_POINT = "2026-04-30T00:00:00+00:00"
PERIOD_START = "2026-04-01T00:00:00+00:00"
PERIOD_END = "2026-04-30T00:00:00+00:00"

# kind: how the public surface can represent the scenario
#   tool      -> an existing tool should answer it once its profile gate is open
#   missing   -> no existing public tool can represent it (NOT IMPLEMENTED)
SPECS = {
    "SC01": dict(
        slug="ar-overdue-30d", question="Receivables overdue more than 30 days",
        tool="receivable_balance", kind="missing", args="period",
        missing_regex=r"aging|overdue",
        missing="receivable_aging(source_id, company_id, as_of, bucket_days) -> open_balance and overdue_30d, "
                "on a validated due-date/settlement mapping (receivable_balance is point-in-time only; "
                "docs/SEMANTIC_PROFILES.md says aging stays unavailable)",
    ),
    "SC02": dict(
        slug="partial-payment", question="Invoice with partial payment remains open",
        tool="sales_documents", kind="missing", args="docs",
        missing_regex=r"settle|payment|invoice_open|open_item",
        missing="settlement_status(source_id, company_id, document_ref) -> invoice_total, payments_applied, "
                "open_balance (sales_documents exposes only document amount/posted state)",
    ),
    "SC03": dict(
        slug="overpayment", question="Customer overpayment is separated from receivable",
        tool="receivable_balance", kind="missing", args="period",
        missing_regex=r"settle|payment|advance|open_item",
        missing="same settlement_status interface with a separate unapplied_advance field",
    ),
    "SC04": dict(
        slug="unposted-document", question="Unposted document does not create accounting movement",
        tool="sales_documents", kind="tool", args="docs",
        missing="reviewed synthetic-fixture semantic profile for sales/accounting.posting_rows plus an "
                "AccountingRegister_* entity in Fake1C",
    ),
    "SC05": dict(
        slug="return", question="Return reduces the relevant movement",
        tool="inventory_movements", kind="missing", args="range",
        missing_regex=r"return",
        missing="inventory_movements/inventory_balance with a mapped return record type, a Fake1C return "
                "fixture exposed as register rows and a Balance virtual table (seed has receipt/expense only)",
    ),
    "SC06": dict(
        slug="vat-mixed", question="Different VAT treatments remain distinguishable",
        tool="sales_documents", kind="missing", args="docs",
        missing_regex=r"vat|tax",
        disposition="EXTERNAL-GATE",
        missing="DISPOSITION EXTERNAL-GATE: VAT views exist only when a source/company profile is validated "
                "(freeze 3.3 'VAT/tax views only when validated'); needs tax_base_by_vat_treatment(source_id, "
                "company_id, start, end) -> per-treatment base and total on a validated profile",
    ),
    "SC07": dict(
        slug="backdated-document", question="Backdated document appears in the correct accounting period",
        tool="sales_documents", kind="missing", args="docs",
        missing_regex=r"period_of|accounting_period|backdat",
        missing="document_accounting_period(source_id, company_id, document_ref) -> document_date and "
                "accounting_period; seed exposes no backdated document through any entity set",
    ),
    "SC08": dict(
        slug="duplicate-counterparty", question="Potential duplicate counterparties are identified without merge",
        tool="onec_read", kind="missing", args="none",
        missing_regex=r"duplicate",
        disposition="NOT IMPLEMENTED",
        missing="DISPOSITION NOT IMPLEMENTED: duplicate-counterparty detection is outside the frozen scope and "
                "needs an operator rebaseline; would need counterparty_duplicate_candidates(source_id, company_id) "
                "with merge_count=0 and a duplicate pair in the seed",
    ),
    "SC09": dict(
        slug="cash-bank", question="Cash and bank balances remain separate and sum to combined",
        tool="bank_balance", kind="tool", args="period", second_tool="cash_movements",
        missing="reviewed synthetic-fixture profiles for bank.balance/cash.movements; Fake1C has no Balance "
                "virtual table; seed cash_balance fixture (100) disagrees with register net (7)",
    ),
    "SC10": dict(
        slug="account-turnover", question="Opening, turnover and closing values reconcile",
        tool="accounting_balance_and_turnovers", kind="missing", args="turnover",
        missing_regex=r"^$",  # tool exists; the gap is data/capability, so always NOT IMPLEMENTED on Fake1C
        force_not_implemented=True,
        missing="Fake1C exposes no AccountingRegister_* entity or balanceAndTurnovers capability and no "
                "opening/closing data; needs such an entity plus a reviewed synthetic-fixture profile",
    ),
    "SC11": dict(
        slug="inventory-receipt-expense", question="Inventory movement signs reconcile to net quantity",
        tool="inventory_movements", kind="tool", args="range",
        missing="reviewed synthetic-fixture inventory.movements profile (receipt/expense literals, company "
                "dimension, timezone) - the register data already exists in Fake1C",
    ),
    "SC12": dict(
        slug="cash-receipt-expense", question="Cash movement signs reconcile to net amount",
        tool="cash_movements", kind="tool", args="range",
        missing="reviewed synthetic-fixture cash.movements profile - the register data already exists in Fake1C",
    ),
}


def build_args(spec: dict, source_id: str, company_id: str) -> dict:
    base = {"source_id": source_id, "company_id": company_id}
    kind = spec["args"]
    if kind == "period":
        return {**base, "period": PERIOD_POINT}
    if kind == "range":
        return {**base, "start_period": PERIOD_START, "end_period": PERIOD_END}
    if kind == "turnover":
        return {**base, "start_period": PERIOD_START, "end_period": PERIOD_END}
    if kind == "docs":
        return base
    return {"source_id": source_id, "entity_set": "Catalog_Counterparties", "top": 10}
