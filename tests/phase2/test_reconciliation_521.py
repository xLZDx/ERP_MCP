"""R2-US-030 / TC088, TC089: account 521.1 six-balance and analytic-row comparison."""
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.reconciliation import (
    BalanceSix,
    ComparisonState,
    LedgerRow,
    LedgerScope,
    LedgerStatement,
    TolerancePolicy,
    compare_statements,
)

POLICY = TolerancePolicy("exact-v1", Decimal(0))
SIX = ("opening_debit", "opening_credit", "turnover_debit", "turnover_credit",
       "closing_debit", "closing_credit")


def six(**kw: str) -> BalanceSix:
    base = {"opening_debit": "0", "opening_credit": "20", "turnover_debit": "3",
            "turnover_credit": "7", "closing_debit": "0", "closing_credit": "24"}
    base.update(kw)
    return BalanceSix(*(Decimal(base[n]) for n in SIX))


def scope() -> LedgerScope:
    return LedgerScope("t", "real-reference", "818HA", "521.1",
                       datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC),
                       "MDL", "Europe/Chisinau", ("counterparty_ref", "contract_ref"))


def stmt(rows: tuple[LedgerRow, ...], *, complete: bool = True) -> LedgerStatement:
    totals = BalanceSix(*(sum((getattr(r.balance, n) for r in rows), Decimal(0)) for n in SIX))
    return LedgerStatement(scope(), "copy-1", totals, rows, complete, "rev")


def one_row(b: BalanceSix) -> LedgerStatement:
    return stmt((LedgerRow("A", "X", b),))


# ---- TC088: MATCH only when all six balances and every row match -------------------

def test_tc088_all_six_and_all_rows_equal_is_match():
    rows = (LedgerRow("A", "X", six()), LedgerRow("B", "Y", six(turnover_debit="5")))
    result = compare_statements(stmt(rows), stmt(rows), policy=POLICY)
    assert result.state is ComparisonState.MATCH
    assert result.differences == ()
    assert result.authority == "EVALUATION_ONLY"


@pytest.mark.parametrize("measure", SIX)
def test_tc088_any_single_balance_difference_is_mismatch(measure):
    # Each of the six values differs alone; none of them may be ignored.
    result = compare_statements(one_row(six()), one_row(six(**{measure: "99"})), policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    assert measure in {d.measure for d in result.differences}
    assert any(d.row_key is None for d in result.differences)
    assert any(d.row_key == ("A", "X") for d in result.differences)


def test_tc088_row_difference_with_equal_totals_is_mismatch():
    # Same six totals, but the amount sits on different contracts.
    native = stmt((LedgerRow("A", "X", six(turnover_debit="1")),
                   LedgerRow("B", "Y", six(turnover_debit="2"))))
    gateway = stmt((LedgerRow("A", "X", six(turnover_debit="2")),
                    LedgerRow("B", "Y", six(turnover_debit="1"))))
    assert native.totals == gateway.totals
    result = compare_statements(native, gateway, policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    assert all(d.row_key is not None for d in result.differences)
    assert {d.row_key for d in result.differences} == {("A", "X"), ("B", "Y")}


def test_tc088_missing_or_extra_row_is_never_match():
    two = stmt((LedgerRow("A", "X", six()), LedgerRow("B", "Y", six())))
    one = stmt((LedgerRow("A", "X", six()),))
    for native, gateway in ((two, one), (one, two)):
        result = compare_statements(native, gateway, policy=POLICY)
        assert result.state is not ComparisonState.MATCH


def test_tc088_missing_balance_cannot_be_constructed():
    with pytest.raises(ValueError, match="FINITE_DECIMAL_REQUIRED"):
        BalanceSix(Decimal(0), Decimal(0), None, Decimal(0), Decimal(0), Decimal(0))  # type: ignore[arg-type]


def test_tc088_incomplete_statement_is_inconclusive_on_either_side():
    full = one_row(six())
    partial = stmt((LedgerRow("A", "X", six()),), complete=False)
    assert compare_statements(full, partial, policy=POLICY).state is ComparisonState.INCONCLUSIVE
    assert compare_statements(partial, full, policy=POLICY).state is ComparisonState.INCONCLUSIVE


def test_tc088_statement_without_rows_is_inconclusive_not_match():
    empty = replace(one_row(six()), rows=())
    result = compare_statements(empty, empty, policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE


def test_tc088_totals_that_do_not_sum_the_rows_are_inconclusive():
    good = one_row(six())
    bad = replace(good, totals=six(closing_credit="25"))
    assert compare_statements(good, bad, policy=POLICY).state is ComparisonState.INCONCLUSIVE
    assert compare_statements(bad, good, policy=POLICY).state is ComparisonState.INCONCLUSIVE


# ---- TC089: equal closing balance with wrong opening/turnover is MISMATCH ----------

def test_tc089_equal_closing_wrong_opening_is_mismatch():
    native = one_row(six())  # opening 0/20, turnover 3/7, closing 0/24
    gateway = one_row(six(opening_debit="5", opening_credit="25"))  # same closing 0/24
    assert native.totals.closing_debit == gateway.totals.closing_debit
    assert native.totals.closing_credit == gateway.totals.closing_credit
    result = compare_statements(native, gateway, policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    assert {d.measure for d in result.differences if d.row_key is None} == {
        "opening_debit", "opening_credit"}


def test_tc089_equal_closing_wrong_turnover_is_mismatch():
    native = one_row(six())
    gateway = one_row(six(turnover_debit="10", turnover_credit="14"))
    assert native.totals.closing_credit == gateway.totals.closing_credit
    result = compare_statements(native, gateway, policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    measures = {d.measure for d in result.differences}
    assert measures == {"turnover_debit", "turnover_credit"}
    assert not measures & {"closing_debit", "closing_credit"}


def test_tc089_difference_beyond_tolerance_in_opening_only_is_mismatch():
    tol = TolerancePolicy("tol", Decimal("0.01"))
    within = compare_statements(one_row(six()), one_row(six(opening_credit="20.01")), policy=tol)
    beyond = compare_statements(one_row(six()), one_row(six(opening_credit="20.02")), policy=tol)
    assert within.state is ComparisonState.MATCH
    assert beyond.state is ComparisonState.MISMATCH
