"""REQ-003 / S1.2 AC-3: Python grant evaluation distinguishes empty from insufficient."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.change.errors import ErrorCode
from business_ai_gateway.phase2.change.policy import Grant, reserve
from business_ai_gateway.phase2.change.transitions import Event, apply_transition
from business_ai_gateway.phase2.change.types import BudgetCheck
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger
from tests.phase2 import _change_helpers as h
from uuid import uuid4

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def grant(*, limit="10", reserved="0", consumed="0"):
    return Grant("grant-1", "RUB", Decimal(limit), NOW - timedelta(days=1), NOW + timedelta(days=1),
                 Decimal(reserved), Decimal(consumed))


@pytest.mark.parametrize("reserved,consumed", [("10", "0"), ("4", "6"), ("6", "4")])
def test_positive_request_with_no_remaining_grant_produces_exhausted(reserved, consumed):
    result = reserve(grant(reserved=reserved, consumed=consumed), Decimal("0.01"), "RUB", NOW)
    assert result is ErrorCode.GRANT_EXHAUSTED


def test_nonzero_remainder_that_is_too_small_keeps_budget_exceeded():
    result = reserve(grant(consumed="9.99"), Decimal("0.02"), "RUB", NOW)
    assert result is ErrorCode.BUDGET_EXCEEDED


def test_full_grant_allows_zero_amount_but_unknown_currency_and_outside_window_fail_closed():
    full = grant(reserved="10")
    assert type(reserve(full, Decimal("0"), "RUB", NOW)) is Grant
    assert reserve(full, Decimal("0.01"), "EUR", NOW) is ErrorCode.CURRENCY_NOT_BUDGETED
    assert reserve(grant(), Decimal("1"), "RUB", NOW + timedelta(days=2)) is ErrorCode.BUDGET_EXCEEDED


def test_missing_or_malformed_budget_result_is_not_treated_as_success():
    assert reserve(object(), Decimal("1"), "RUB", NOW) is ErrorCode.SCHEMA_INVALID


def test_s12_claim_guard_keeps_exhausted_distinct_from_other_budget_refusals():
    for budget, expected in ((BudgetCheck.EXHAUSTED, "GRANT_EXHAUSTED"),
                             (BudgetCheck.EXCEEDED, "BUDGET_EXCEEDED"),
                             (BudgetCheck.NOT_CHECKED, "BUDGET_EXCEEDED")):
        result = apply_transition(h.approved(), Event.CLAIM,
                                  h.good(Event.CLAIM, h.approved(), budget=budget))
        assert type(result).__name__ == "Refusal"
        assert result.code.value == expected


@pytest.mark.asyncio
async def test_synthetic_exhausted_budget_snapshot_maps_to_budget_check():
    class SnapshotLedger(SqlChangeLedger):
        async def invoke(self, key, scope, *args, as_class=None):
            assert key == "budget_snapshot"
            assert scope == Scope("tenant-1", "company-1")
            return {"check": "EXHAUSTED"}

    ledger = SnapshotLedger(conn=None)

    result = await ledger.budget_snapshot(
        Scope("tenant-1", "company-1"), uuid4(), Decimal("0.01"), "RUB"
    )

    assert result is BudgetCheck.EXHAUSTED

