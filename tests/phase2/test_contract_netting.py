"""R2-US-030 / TC090: debit and credit sides per counterparty-contract, never netted."""
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.contract_netting import (
    ContractSides,
    compare_contract_sides,
)
from business_ai_gateway.phase2.reconciliation import ComparisonState, TolerancePolicy

POLICY = TolerancePolicy("exact-v1", Decimal(0))


def cs(cp: str, contract: str, debit: str, credit: str) -> ContractSides:
    return ContractSides(cp, contract, Decimal(debit), Decimal(credit))


def test_identical_sides_match_and_every_side_is_reported():
    rows = (cs("A", "X", "100", "0"), cs("A", "Y", "0", "40"))
    result = compare_contract_sides(rows, rows, policy=POLICY)
    assert result.state is ComparisonState.MATCH
    assert len(result.sides) == 4
    assert all(s.equal for s in result.sides)
    assert result.authority == "EVALUATION_ONLY"


def test_tc090_plus_x_minus_x_does_not_net_to_match():
    # Native: contract X owes +100 (debit), contract Y owes -100 (credit) -> net 0.
    # Gateway: same net 0, but the amounts sit on the opposite contracts.
    native = (cs("A", "X", "100", "0"), cs("A", "Y", "0", "100"))
    gateway = (cs("A", "X", "0", "100"), cs("A", "Y", "100", "0"))
    result = compare_contract_sides(native, gateway, policy=POLICY)
    assert result.net_native == result.net_gateway == Decimal(0)
    assert result.state is ComparisonState.MISMATCH
    assert result.reason_code == "CONTRACT_SIDE_DIFFERS"
    bad = {(s.contract_ref, s.side) for s in result.sides if not s.equal}
    assert bad == {("X", "debit"), ("X", "credit"), ("Y", "debit"), ("Y", "credit")}


def test_tc090_net_zero_native_vs_zero_gateway_is_mismatch_and_sides_reported():
    native = (cs("A", "X", "100", "0"), cs("A", "Y", "0", "100"))
    gateway = (cs("A", "X", "0", "0"), cs("A", "Y", "0", "0"))
    result = compare_contract_sides(native, gateway, policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    reported = {(s.contract_ref, s.side): (s.expected, s.actual) for s in result.sides}
    assert reported[("X", "debit")] == (Decimal(100), Decimal(0))
    assert reported[("Y", "credit")] == (Decimal(100), Decimal(0))
    assert reported[("X", "credit")] == (Decimal(0), Decimal(0))


def test_one_sided_difference_is_mismatch_only_on_that_side():
    native = (cs("A", "X", "100", "5"),)
    gateway = (cs("A", "X", "100", "6"),)
    result = compare_contract_sides(native, gateway, policy=POLICY)
    assert result.state is ComparisonState.MISMATCH
    assert [(s.side, s.equal) for s in result.sides] == [("debit", True), ("credit", False)]


def test_debit_and_credit_equal_difference_that_nets_out_per_contract_is_still_mismatch():
    # Same contract, +1 on debit and +1 on credit: net balance unchanged.
    result = compare_contract_sides((cs("A", "X", "10", "4"),), (cs("A", "X", "11", "5"),),
                                    policy=POLICY)
    assert result.state is ComparisonState.MISMATCH


def test_tolerance_applies_per_side():
    tol = TolerancePolicy("tol", Decimal("0.01"))
    ok = compare_contract_sides((cs("A", "X", "1.00", "0"),), (cs("A", "X", "1.01", "0"),), policy=tol)
    bad = compare_contract_sides((cs("A", "X", "1.00", "0"),), (cs("A", "X", "1.011", "0"),), policy=tol)
    assert ok.state is ComparisonState.MATCH
    assert bad.state is ComparisonState.MISMATCH


@pytest.mark.parametrize("native,gateway,reason", [
    ((cs("A", "X", "1", "0"),), (cs("A", "Y", "1", "0"),), "CONTRACT_SET_MISMATCH"),
    ((cs("A", "X", "1", "0"), cs("A", "Y", "1", "0")), (cs("A", "X", "1", "0"),),
     "CONTRACT_SET_MISMATCH"),
    ((cs("A", "", "1", "0"),), (cs("A", "", "1", "0"),), "UNKNOWN_CONTRACT"),
    ((cs("A", "X", "1", "0"),), (cs("A", "UNKNOWN", "1", "0"),), "UNKNOWN_CONTRACT"),
    ((cs("", "X", "1", "0"),), (cs("", "X", "1", "0"),), "UNKNOWN_CONTRACT"),
    ((cs("A", "X", "1", "0"), cs("A", "X", "2", "0")), (cs("A", "X", "3", "0"),),
     "DUPLICATE_CONTRACT"),
    ((), (cs("A", "X", "1", "0"),), "CONTRACT_SIDES_MISSING"),
    ((cs("A", "X", "1", "0"),), (), "CONTRACT_SIDES_MISSING"),
])
def test_unknown_missing_or_duplicate_contract_is_inconclusive(native, gateway, reason):
    result = compare_contract_sides(native, gateway, policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE
    assert result.reason_code == reason


def test_floats_nan_and_negative_sides_are_rejected():
    with pytest.raises(ValueError, match="FINITE_DECIMAL_REQUIRED"):
        ContractSides("A", "X", 1.0, Decimal(0))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="FINITE_DECIMAL_REQUIRED"):
        ContractSides("A", "X", Decimal("NaN"), Decimal(0))
    with pytest.raises(ValueError, match="SIDE_AMOUNT_NEGATIVE"):
        ContractSides("A", "X", Decimal(0), Decimal(-1))


def test_decimal_exact_no_float_rounding_and_ambient_precision_ignored():
    import decimal
    a = (cs("A", "X", "12345678.90", "0"),)
    b = (cs("A", "X", "12345678.91", "0"),)
    with decimal.localcontext() as ctx:
        ctx.prec = 4
        assert compare_contract_sides(a, a, policy=POLICY).state is ComparisonState.MATCH
        assert compare_contract_sides(a, b, policy=POLICY).state is ComparisonState.MISMATCH
    assert compare_contract_sides((cs("A", "X", "0.1", "0"),), (cs("A", "X", "0.1", "0"),),
                                  policy=POLICY).state is ComparisonState.MATCH


def test_precision_overflow_is_inconclusive():
    huge = "1" * 70
    rows = (cs("A", "X", huge, "0"),)
    result = compare_contract_sides(rows, rows, policy=POLICY)
    assert result.state is ComparisonState.INCONCLUSIVE
    assert result.reason_code == "DECIMAL_PRECISION_EXCEEDED"
