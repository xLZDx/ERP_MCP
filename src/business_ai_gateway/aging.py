"""Pure, synthetic open-item aging contract; not a source adapter or accounting profile."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

_BUCKETS = ("not_due", "days_1_30", "days_31_60", "days_61_90", "days_91_plus")


def aggregate_open_items(rows: Any, *, as_of: date) -> list[dict[str, Any]]:
    """Group already-open synthetic items by counterparty and currency.

    Source-specific due-date, settlement/allocation, currency conversion and sign semantics
    must be validated in a semantic profile before any real 1C data may use this contract.
    Negative open amounts remain visible as credits and are never netted across items.
    """
    if not isinstance(rows, list):
        raise TypeError("open items must be a list")
    totals: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(
        lambda: {**dict.fromkeys(_BUCKETS, Decimal(0)), "credit": Decimal(0)}
    )
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("open item must be an object")
        try:
            counterparty = row["counterparty_id"]
            currency = row["currency"]
            due = date.fromisoformat(row["due_date"])
            amount = Decimal(str(row["open_amount"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError("open item is missing valid canonical fields") from exc
        if (
            not isinstance(counterparty, str)
            or not counterparty
            or not isinstance(currency, str)
            or not currency
            or not amount.is_finite()
        ):
            raise ValueError("open item has invalid counterparty, currency, or amount")
        buckets = totals[(counterparty, currency)]
        if amount < 0:
            buckets["credit"] += -amount
        elif amount > 0:
            overdue_days = (as_of - due).days
            bucket = (
                "not_due"
                if overdue_days <= 0
                else "days_1_30"
                if overdue_days <= 30
                else "days_31_60"
                if overdue_days <= 60
                else "days_61_90"
                if overdue_days <= 90
                else "days_91_plus"
            )
            buckets[bucket] += amount
    return [
        {
            "counterparty_id": counterparty,
            "currency": currency,
            "buckets": {name: str(values[name]) for name in _BUCKETS},
            "unapplied_credit": str(values["credit"]),
        }
        for (counterparty, currency), values in sorted(totals.items())
    ]
