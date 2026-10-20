"""Fake gateways and payload builders for the test-lane MCP tests (offline, no network)."""
from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from testlane.phase2_mcp.gateway_client import GatewayError

COMPANY = "3e31afc5-351f-4f36-8074-99129fa3d911"
AS_OF = "2026-08-31T23:59:59+03:00"
START = "2026-01-01T00:00:00+03:00"
END = "2026-09-01T00:00:00+03:00"
ACC1 = "5659a89c-5098-11ee-aa2f-d85ed30dc416"
ACC2 = "5659a89d-5098-11ee-aa2f-d85ed30dc416"
SECRET_AMOUNT = Decimal("123456.78")
SECRET_NAME = "Secret Supplier LLC"
LABELS = {
    "profile_kind": "TEST_LANE_UNRECONCILED", "evidence_level": "L1",
    "native_reconciliation": "NOT_RUN",
    "warnings": ["TEST_LANE_PROFILE_NOT_RECONCILED_NOT_NATIVE"],
    "profile_fingerprint": "pf-1", "metadata_fingerprint": "mf-1",
}


def _row(account: str, **cols: Decimal | int) -> dict[str, Any]:
    base = dict.fromkeys(
        ("opening_debit", "opening_credit", "debit_turnover", "credit_turnover",
         "closing_debit", "closing_credit"), 0)
    base.update(cols)
    return {"account": account, **base}


def turnover_payload(has_more: bool = False, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = [
        _row(ACC1, closing_debit=SECRET_AMOUNT),
        _row(ACC1, debit_turnover=Decimal("10.50")),  # sparse repeated account row: must be summed
        _row(ACC2, closing_credit=Decimal(7)),
    ]
    page = {"returned": len(rows), "has_more": has_more, "truncated": False}
    return {"value": rows, "page": page, **LABELS, **(extra or {})}


def analytics_payload(*, status: str = "COMPLETE", debit: str = "100.00") -> dict[str, Any]:
    rows = [
        {"account": "521.1", "account_key": "ak-1", "currency_ref": None,
         "analytics": [{"slot": 1, "role": "cp", "ref": "cp-1", "type": "t"},
                       {"slot": 2, "role": "ct", "ref": "ct-1", "type": "t"}],
         "balance_debit": debit, "balance_credit": "0"},
        {"account": "521.1", "account_key": "ak-1", "currency_ref": None,
         "analytics": [{"slot": 1, "role": "cp", "ref": "cp-2", "type": "t"},
                       {"slot": 2, "role": "ct", "ref": "ct-2", "type": "t"}],
         "balance_debit": "0", "balance_credit": "55.5"},
    ]
    return {
        "rows": rows, "row_count": len(rows), "truncated": False,
        "supplier_summary": {"status": status, "suppliers": [{"supplier_name": SECRET_NAME}]},
        **LABELS, "profile_kind": "VALIDATED_MACHINE_RECONCILED",
    }


def purchase_payload(has_more: bool = True) -> dict[str, Any]:
    doc = {"document_ref": "d-1", "counterparty": "cp-1", "currency": "cur-1",
           "date": "2026-07-08T07:00:00", "document_number": "N1", "amount": 100, "posted": True}
    return {"value": [doc], "page": {"returned": 1, "has_more": has_more, "truncated": False},
            **LABELS}


class FakeGateway:
    def __init__(self, label: str, responses: dict[str, Any]) -> None:
        self.label = label
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        value = self.responses[tool]
        if isinstance(value, GatewayError):
            raise value
        return copy.deepcopy(value)


def standard_responses(*, has_more: bool = False) -> dict[str, Any]:
    return {
        "accounting_balance_and_turnovers": turnover_payload(has_more),
        "accounting_balance_by_analytics": analytics_payload(),
        "purchase_documents": purchase_payload(),
    }
