"""Pure, synthetic open-item aging contract; not a source adapter or accounting profile."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

_BUCKETS = ("not_due", "days_1_30", "days_31_60", "days_61_90", "days_91_plus")


def aggregate_open_items(rows: Any, *, as_of: date) -> list[dict[str, Any]]:
    """Group already-open synthetic items by counterparty and currency.

    Source-specific due-date, settlement/allocation, currency conversion and sign semantics
    must be validated in a semantic profile before any real 1C data may use this contract.
    Negative open amounts remain visible as credits and are never netted across items.
    """
    if type(as_of) is not date:
        raise ValueError('AGING_ASOF_INVALID')
    if not isinstance(rows, list):
        raise TypeError("open items must be a list")
    if len(rows) > 2000:
        raise ValueError('AGING_INPUT_LIMIT')
    totals: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(
        lambda: {**dict.fromkeys(_BUCKETS, Decimal(0)), "credit": Decimal(0)}
    )
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("open item must be an object")
        if set(row) != {'counterparty_id', 'currency', 'due_date', 'open_amount'}:
            raise ValueError('AGING_SCHEMA_INVALID')
        try:
            counterparty = row["counterparty_id"]
            currency = row["currency"]
            due = date.fromisoformat(row["due_date"])
            raw_amount = row['open_amount']
            if type(raw_amount) is not str or len(raw_amount) > 64:
                raise ValueError('invalid decimal representation')
            amount = Decimal(raw_amount)
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ValueError("open item is missing valid canonical fields") from None
        if (
            not isinstance(counterparty, str)
            or not counterparty
            or len(counterparty) > 128
            or any(ord(character) < 32 or ord(character) == 127 for character in counterparty)
            or not isinstance(currency, str)
            or not currency
            or len(currency) != 3 or not currency.isascii() or not currency.isupper() or not currency.isalpha()
            or not amount.is_finite()
            or amount.copy_abs() >= Decimal('1e28') or not -6 <= amount.as_tuple().exponent <= 28
        ):
            raise ValueError("open item has invalid counterparty, currency, or amount")
        buckets = totals[(counterparty, currency)]
        with localcontext() as context:
            context.prec = 120
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
