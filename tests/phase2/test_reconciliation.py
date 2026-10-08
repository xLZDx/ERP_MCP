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


def D(value: str) -> Decimal:
    return Decimal(value)

def balance(*, open_d="0", open_c="20", turn_d="3", turn_c="7", close_d="0", close_c="24"):
    return BalanceSix(*(D(x) for x in (open_d, open_c, turn_d, turn_c, close_d, close_c)))

def scope(company="818HA",currency="MDL"):
    return LedgerScope("t", "real-reference", company, "521.1",
        datetime(2026,8,1,tzinfo=UTC), datetime(2026,9,1,tzinfo=UTC),
        currency, "Europe/Chisinau", ("counterparty_ref","contract_ref"))

def statement(value=None, *, company="818HA", currency="MDL", snapshot="copy-1",
              complete=True, rows=None, revision="report-A"):
    b = value or balance()
    return LedgerStatement(scope(company,currency), snapshot, b,
            tuple(rows if rows is not None else (LedgerRow("supplier-A","contract-A",b),)),
            complete, revision)

POLICY = TolerancePolicy("exact-v1", D("0"))

def test_exact_all_six_and_analytic_rows_match():
    a=statement()
    result=compare_statements(a, a, policy=POLICY)
    assert result.state is ComparisonState.MATCH and result.authority=="EVALUATION_ONLY"

def test_same_ending_balance_but_different_turnover_is_mismatch():
    a=statement()
    # Closing amounts are deliberately equal even though movement totals differ.
    b=statement(balance(turn_d="4",turn_c="8"))
    result=compare_statements(a,b,policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    assert {x.measure for x in result.differences}=={"turnover_debit","turnover_credit"}

def test_cross_company_is_inconclusive():
    result=compare_statements(statement(),statement(company="other"),policy=POLICY)
    assert result.reason_code=="SCOPE_MISMATCH"

def test_currency_mismatch_is_inconclusive():
    result=compare_statements(statement(),statement(currency="EUR"),policy=POLICY)
    assert result.reason_code=="SCOPE_MISMATCH"

def test_different_source_snapshot_is_inconclusive():
    result=compare_statements(statement(),statement(snapshot="copy-2"),policy=POLICY)
    assert result.reason_code=="SOURCE_SNAPSHOT_MISMATCH"

def test_missing_page_cannot_be_pass():
    result=compare_statements(statement(),statement(complete=False),policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE
    assert result.reason_code=="GATEWAY_INCOMPLETE_OR_INCONSISTENT"

def test_missing_analytic_row_is_mismatch_even_if_totals_agree():
    b=balance()
    row1=LedgerRow("A","X",BalanceSix(*(x/2 for _,x in b.items())))
    row2=LedgerRow("B","Y",BalanceSix(*(x/2 for _,x in b.items())))
    a=statement(b,rows=(row1,row2))
    other=statement(b,rows=(LedgerRow("A","X",b),))
    result=compare_statements(a,other,policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    assert any(x.measure=="ROW_MISSING" for x in result.differences)

def test_duplicate_analytic_contract_denied():
    row=LedgerRow("A","X",balance())
    with pytest.raises(ValueError,match="DUPLICATE_ANALYTIC_ROW"):
        statement(rows=(row,row))

def test_float_forbidden_even_if_value_looks_correct():
    with pytest.raises(ValueError,match="FINITE_DECIMAL_REQUIRED"):
        replace(balance(),opening_credit=20.0)

def test_nan_infinite_forbidden():
    with pytest.raises(ValueError,match="FINITE_DECIMAL_REQUIRED"):
        replace(balance(),opening_credit=D("NaN"))

def test_negative_tolerance_denied():
    with pytest.raises(ValueError,match="TOLERANCE_POLICY_INVALID"):
        TolerancePolicy("bad", D("-0.01"))

def test_allowed_tolerance_applied_symmetrically():
    a=statement()
    b=statement(balance(close_c="24.01"))
    result=compare_statements(a,b,policy=TolerancePolicy("round-v1",D("0.01")))
    assert result.state is ComparisonState.MATCH

def test_unsupported_period_is_inconclusive_not_implicitly_adjusted():
    other=statement()
    shifted=replace(other.scope,end_exclusive=datetime(2026,9,2,tzinfo=UTC))
    result=compare_statements(other,replace(other,scope=shifted),policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE

def test_inconsistent_rows_cannot_match_wrong_totals():
    a=statement()
    other=statement(balance(turn_d="4"))
    # Replace total alone, keep old row values.
    other=replace(other,rows=a.rows)
    result=compare_statements(a,other,policy=POLICY)
    assert result.reason_code=="GATEWAY_INCOMPLETE_OR_INCONSISTENT"

def test_report_revision_not_an_automatic_attestation():
    result=compare_statements(statement(revision="untrusted-native"),statement(revision="mcp"),policy=POLICY)
    assert result.state is ComparisonState.MATCH
    assert result.authority=="EVALUATION_ONLY"

TOL = TolerancePolicy("tol-v1", D("0.01"))

@pytest.mark.parametrize("native_close,gateway_close,state", [
    ("24.00", "24.01", ComparisonState.MATCH),      # exactly tolerance, gateway higher
    ("24.01", "24.00", ComparisonState.MATCH),      # exactly tolerance, gateway lower
    ("24.00", "24.011", ComparisonState.MISMATCH),  # tolerance + 0.001, gateway higher
    ("24.011", "24.00", ComparisonState.MISMATCH),  # tolerance + 0.001, gateway lower
])
def test_tolerance_boundary_both_directions(native_close, gateway_close, state):
    a=statement(balance(close_c=native_close))
    b=statement(balance(close_c=gateway_close))
    result=compare_statements(a,b,policy=TOL)
    assert result.state is state
    if state is ComparisonState.MISMATCH:
        assert {x.measure for x in result.differences}=={"closing_credit"}
        assert result.reason_code=="VALUES_DIFFER"

def test_arithmetic_ignores_ambient_decimal_precision():
    import decimal
    big = balance(open_c="12345678.91", close_c="12345678.91", turn_d="0", turn_c="0")
    a=statement(big)
    with decimal.localcontext() as ctx:
        ctx.prec = 4
        result=compare_statements(a,a,policy=POLICY)
    assert result.state is ComparisonState.MATCH
    assert result.reason_code=="ALL_SIX_AND_ROWS_EQUAL"

def test_tolerance_boundary_with_low_ambient_precision():
    import decimal
    a=statement(balance(close_c="12345678.90"))
    b=statement(balance(close_c="12345678.91"))
    with decimal.localcontext() as ctx:
        ctx.prec = 4
        assert compare_statements(a,b,policy=TOL).state is ComparisonState.MATCH
        b2=statement(balance(close_c="12345678.911"))
        assert compare_statements(a,b2,policy=TOL).state is ComparisonState.MISMATCH

def test_seventy_digit_decimal_is_inconclusive_precision_exceeded():
    huge = "1" * 70
    a=statement(balance(open_c=huge, close_c=huge, turn_d="0", turn_c="0"))
    result=compare_statements(a,a,policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE
    assert result.reason_code=="DECIMAL_PRECISION_EXCEEDED"

def test_both_statements_with_empty_rows_are_inconclusive_native_side():
    a=statement(rows=())
    b=statement(rows=())
    result=compare_statements(a,b,policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE
    assert result.reason_code=="NATIVE_INCOMPLETE_OR_INCONSISTENT"

def test_native_side_totals_not_matching_rows_is_native_inconsistent():
    good=statement()
    bad=replace(statement(balance(turn_d="4")),rows=good.rows)
    result=compare_statements(bad,good,policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE
    assert result.reason_code=="NATIVE_INCOMPLETE_OR_INCONSISTENT"
