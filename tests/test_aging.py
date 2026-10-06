from datetime import date

import pytest

from business_ai_gateway.aging import aggregate_open_items


@pytest.fixture
def synthetic_open_items():
    return [
        {"counterparty_id": "customer-a", "currency": "USD", "due_date": "2026-10-10", "open_amount": "100.00"},
        {"counterparty_id": "customer-a", "currency": "USD", "due_date": "2026-09-06", "open_amount": "20"},
        {"counterparty_id": "customer-a", "currency": "USD", "due_date": "2026-08-07", "open_amount": "30"},
        {"counterparty_id": "customer-a", "currency": "USD", "due_date": "2026-07-08", "open_amount": "40"},
        {"counterparty_id": "customer-a", "currency": "USD", "due_date": "2026-07-07", "open_amount": "50"},
        {"counterparty_id": "customer-a", "currency": "EUR", "due_date": "2026-01-01", "open_amount": "-7"},
        {"counterparty_id": "customer-b", "currency": "USD", "due_date": "2026-01-01", "open_amount": "0"},
    ]


def test_synthetic_aging_contract_keeps_boundaries_currency_and_credits_separate(
    synthetic_open_items,
):
    result = aggregate_open_items(synthetic_open_items, as_of=date(2026, 10, 6))
    customer_usd = next(
        row for row in result
        if row["counterparty_id"] == "customer-a" and row["currency"] == "USD"
    )
    assert customer_usd["buckets"] == {
        "not_due": "100.00",
        "days_1_30": "20",
        "days_31_60": "30",
        "days_61_90": "40",
        "days_91_plus": "50",
    }
    customer_eur = next(row for row in result if row["currency"] == "EUR")
    assert customer_eur["unapplied_credit"] == "7"
    assert len([row for row in result if row["counterparty_id"] == "customer-a"]) == 2


@pytest.mark.parametrize(
    "rows",
    [
        [{"counterparty_id": "x", "currency": "USD", "due_date": "not-a-date", "open_amount": 1}],
        [{"counterparty_id": "x", "currency": "USD", "due_date": "2026-01-01", "open_amount": "NaN"}],
        [None],
        {"counterparty_id": "x"},
    ],
)
def test_synthetic_aging_contract_rejects_malformed_inputs(rows):
    with pytest.raises((TypeError, ValueError)):
        aggregate_open_items(rows, as_of=date(2026, 10, 6))
