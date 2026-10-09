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
    with pytest.raises(ValueError, match="ROW_ANALYTIC_REF_REQUIRED"):
        ContractSides(5, "X", Decimal(0), Decimal(0))  # type: ignore[arg-type]


@pytest.mark.parametrize("side", ["native", "gateway"])
def test_negative_side_is_inconclusive_negative_side_not_an_exception(side):
    # Documented storno mapping: a reversal is a positive amount on the opposite side; a negative
    # side amount would let a netted figure through, so the verdict is INCONCLUSIVE/NEGATIVE_SIDE.
    good = (cs("A", "X", "1", "0"),)
    for bad in ((cs("A", "X", "-1", "0"),), (cs("A", "X", "1", "-0.01"),)):
        native, gateway = (bad, good) if side == "native" else (good, bad)
        result = compare_contract_sides(native, gateway, policy=POLICY)
        assert result.state is ComparisonState.INCONCLUSIVE
        assert result.reason_code == "NEGATIVE_SIDE"
        assert result.sides == ()


@pytest.mark.parametrize("native,gateway", [
    ([cs("A", "X", "1", "0")], (cs("A", "X", "1", "0"),)),
    ((cs("A", "X", "1", "0"),), [cs("A", "X", "1", "0")]),
    (None, (cs("A", "X", "1", "0"),)),
    ((cs("A", "X", "1", "0"),), "rows"),
    (("not-a-row",), (cs("A", "X", "1", "0"),)),
    ((cs("A", "X", "1", "0"),), (None,)),
    ((cs("A", "X", "1", "0"), object()), (cs("A", "X", "1", "0"),)),
    ((("A", "X", Decimal(1), Decimal(0)),), (cs("A", "X", "1", "0"),)),
])
def test_wrong_container_or_item_type_is_inconclusive_never_attribute_error(native, gateway):
    result = compare_contract_sides(native, gateway, policy=POLICY)  # type: ignore[arg-type]
    assert result.state is ComparisonState.INCONCLUSIVE
    assert result.reason_code == "CONTRACT_SIDES_INVALID"


@pytest.mark.parametrize("ref", [None, "", "  ", "-", " - ", "--", "Unknown", " UNKNOWN ", "N/A", "n/A",
                                 "None", "NULL", "?", "	"])
def test_unknown_contract_variants_are_inconclusive(ref):
    for rows in ((ContractSides("A", ref, Decimal(1), Decimal(0)),),
                 (ContractSides(ref, "X", Decimal(1), Decimal(0)),)):
        result = compare_contract_sides(rows, rows, policy=POLICY)
        assert (result.state, result.reason_code) == (ComparisonState.INCONCLUSIVE, "UNKNOWN_CONTRACT")


def test_case_and_whitespace_variants_are_the_same_contract():
    native = (cs("Acme", "C-1", "5", "2"),)
    gateway = (cs("  acme ", "c-1  ", "5", "2"),)
    result = compare_contract_sides(native, gateway, policy=POLICY)
    assert result.state is ComparisonState.MATCH
    assert [(s.counterparty_ref, s.contract_ref) for s in result.sides] == [("Acme", "C-1")] * 2
    # the same contract spelled two ways inside one side is a duplicate, not two contracts
    dup = (cs("Acme", "C-1", "5", "0"), cs(" ACME", "c-1 ", "0", "2"))
    again = compare_contract_sides(dup, native, policy=POLICY)
    assert (again.state, again.reason_code) == (ComparisonState.INCONCLUSIVE, "DUPLICATE_CONTRACT")


def test_same_contract_under_different_counterparties_is_two_contracts():
    native = (cs("A", "X", "10", "0"), cs("B", "X", "0", "10"))
    swapped = (cs("A", "X", "0", "10"), cs("B", "X", "10", "0"))
    result = compare_contract_sides(native, swapped, policy=POLICY)
    assert result.net_native == result.net_gateway == Decimal(0)
    assert result.state is ComparisonState.MISMATCH
    assert {(s.counterparty_ref, s.side) for s in result.sides if not s.equal} == {
        ("A", "debit"), ("A", "credit"), ("B", "debit"), ("B", "credit")}
    assert compare_contract_sides(native, native, policy=POLICY).state is ComparisonState.MATCH
    # a counterparty present on one side only is a different contract set, not a collapse onto X
    only_a = compare_contract_sides(native, (cs("A", "X", "10", "0"),), policy=POLICY)
    assert (only_a.state, only_a.reason_code) == (ComparisonState.INCONCLUSIVE, "CONTRACT_SET_MISMATCH")


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


ZERO_GUID_VARIANTS = [
    "00000000-0000-0000-0000-000000000000",
    "{00000000-0000-0000-0000-000000000000}",
    "(00000000-0000-0000-0000-000000000000)",
    "00000000000000000000000000000000",
    "{00000000000000000000000000000000}",
    " 00000000-0000-0000-0000-000000000000 ",
]


@pytest.mark.parametrize("ref", ZERO_GUID_VARIANTS)
def test_1c_empty_reference_zero_guid_is_unknown_contract(ref):
    for rows in ((ContractSides("A", ref, Decimal(5), Decimal(0)),),
                 (ContractSides(ref, "X", Decimal(5), Decimal(0)),)):
        result = compare_contract_sides(rows, rows, policy=POLICY)
        assert (result.state, result.reason_code) == (ComparisonState.INCONCLUSIVE, "UNKNOWN_CONTRACT")


def test_zero_guid_on_one_side_only_is_inconclusive_and_not_merged_with_other_missing_refs():
    zero = (ContractSides("A", "00000000-0000-0000-0000-000000000000", Decimal(5), Decimal(0)),)
    blank = (ContractSides("A", "", Decimal(5), Decimal(0)),)
    for native, gateway in ((zero, blank), (blank, zero), (zero, zero)):
        result = compare_contract_sides(native, gateway, policy=POLICY)
        assert (result.state, result.reason_code) == (ComparisonState.INCONCLUSIVE, "UNKNOWN_CONTRACT")


def test_non_zero_guid_is_a_normal_contract():
    ref = "00000000-0000-0000-0000-000000000001"
    rows = (ContractSides("A", ref, Decimal(5), Decimal(0)),)
    assert compare_contract_sides(rows, rows, policy=POLICY).state is ComparisonState.MATCH
