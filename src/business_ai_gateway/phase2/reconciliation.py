"""Phase 2: deterministic six-column trial-balance reconciliation.

This module compares already-authorized, independently sourced observations.
It is NOT a native report reader, evidence attestor, or validation approval API.
All reported financial values use Decimal; mismatch never auto-promotes a profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Context, Decimal, Inexact, localcontext
from enum import StrEnum

# Fixed, ambient-independent context: enough digits that 1C amounts are summed and
# compared exactly; Inexact is trapped so silent rounding can never decide a verdict.
_EXACT = Context(prec=60, Emin=-999_999, Emax=999_999)
_EXACT.traps[Inexact] = True


def _money(value: Decimal) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("FINITE_DECIMAL_REQUIRED")
    return value


def _ts(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value


@dataclass(frozen=True, slots=True)
class BalanceSix:
    opening_debit: Decimal
    opening_credit: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _money(getattr(self, name))

    def items(self) -> tuple[tuple[str, Decimal], ...]:
        return tuple((name, getattr(self, name)) for name in self.__dataclass_fields__)


@dataclass(frozen=True, slots=True)
class LedgerScope:
    tenant_id: str
    source_id: str
    company_id: str
    account: str
    start_inclusive: datetime
    end_exclusive: datetime
    currency_code: str
    timezone_name: str
    grouping: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("tenant_id", "source_id", "company_id", "account", "currency_code", "timezone_name"):
            if not getattr(self, name) or not isinstance(getattr(self, name), str):
                raise ValueError("INVALID_LEDGER_SCOPE")
        _ts(self.start_inclusive)
        _ts(self.end_exclusive)
        if self.start_inclusive >= self.end_exclusive:
            raise ValueError("INVALID_LEDGER_PERIOD")
        if self.start_inclusive.utcoffset() != self.end_exclusive.utcoffset():
            # DST transition is legitimate if zone-aware, but before qualification of
            # the concrete 1C instance do not silently claim a common cutoff.
            raise ValueError("PERIOD_OFFSET_CHANGE_UNQUALIFIED")
        if len(self.grouping) == 0 or len(set(self.grouping)) != len(self.grouping):
            raise ValueError("GROUPING_REQUIRED")


@dataclass(frozen=True, slots=True)
class LedgerRow:
    counterparty_ref: str
    contract_ref: str
    balance: BalanceSix

    def __post_init__(self) -> None:
        if not self.counterparty_ref or not self.contract_ref:
            raise ValueError("ROW_ANALYTIC_REF_REQUIRED")


@dataclass(frozen=True, slots=True)
class LedgerStatement:
    scope: LedgerScope
    snapshot_ref: str
    totals: BalanceSix
    rows: tuple[LedgerRow, ...]
    complete: bool
    report_revision: str

    def __post_init__(self) -> None:
        if not self.snapshot_ref or not self.report_revision:
            raise ValueError("REPRODUCIBLE_SOURCE_SNAPSHOT_REQUIRED")
        seen: set[tuple[str, str]] = set()
        for row in self.rows:
            key = (row.counterparty_ref, row.contract_ref)
            if key in seen:
                raise ValueError("DUPLICATE_ANALYTIC_ROW")
            seen.add(key)


@dataclass(frozen=True, slots=True)
class TolerancePolicy:
    policy_id: str
    allowed_abs_diff: Decimal

    def __post_init__(self) -> None:
        if not self.policy_id or _money(self.allowed_abs_diff) < 0:
            raise ValueError("TOLERANCE_POLICY_INVALID")


class ComparisonState(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class Difference:
    row_key: tuple[str, str] | None
    measure: str
    expected: Decimal | None
    actual: Decimal | None


@dataclass(frozen=True, slots=True)
class Comparison:
    state: ComparisonState
    reason_code: str
    policy_id: str
    differences: tuple[Difference, ...]
    authority: str = "EVALUATION_ONLY"


def _aggregates_consistent(statement: LedgerStatement, tolerance: Decimal) -> bool:
    if not statement.complete or not statement.rows:
        return False
    for name, reported in statement.totals.items():
        computed = sum((getattr(row.balance, name) for row in statement.rows), Decimal(0))
        if abs(computed - reported) > tolerance:
            return False
    return True


def compare_statements(
    native: LedgerStatement,
    gateway: LedgerStatement,
    *,
    policy: TolerancePolicy,
) -> Comparison:
    """Compare six accounting totals and every analytic row.

    The caller must separately attest native provenance, independent origin and
    exact source snapshot consistency. Numeric MATCH is NEVER native PASS.
    """
    try:
        with localcontext(_EXACT):
            return _compare(native, gateway, policy)
    except ArithmeticError:
        # Values beyond the fixed exact precision cannot be compared without rounding.
        return Comparison(ComparisonState.INCONCLUSIVE, "DECIMAL_PRECISION_EXCEEDED",
                          policy.policy_id, ())


def _compare(native: LedgerStatement, gateway: LedgerStatement, policy: TolerancePolicy) -> Comparison:
    if native.scope != gateway.scope:
        return Comparison(ComparisonState.INCONCLUSIVE, "SCOPE_MISMATCH", policy.policy_id, ())
    if native.snapshot_ref != gateway.snapshot_ref:
        return Comparison(ComparisonState.INCONCLUSIVE, "SOURCE_SNAPSHOT_MISMATCH", policy.policy_id, ())
    if not _aggregates_consistent(native, policy.allowed_abs_diff):
        return Comparison(ComparisonState.INCONCLUSIVE, "NATIVE_INCOMPLETE_OR_INCONSISTENT", policy.policy_id, ())
    if not _aggregates_consistent(gateway, policy.allowed_abs_diff):
        return Comparison(ComparisonState.INCONCLUSIVE, "GATEWAY_INCOMPLETE_OR_INCONSISTENT", policy.policy_id, ())

    diff: list[Difference] = []
    for name, expected in native.totals.items():
        actual = getattr(gateway.totals, name)
        if abs(expected - actual) > policy.allowed_abs_diff:
            diff.append(Difference(None, name, expected, actual))
    native_rows = {(r.counterparty_ref, r.contract_ref): r.balance for r in native.rows}
    gateway_rows = {(r.counterparty_ref, r.contract_ref): r.balance for r in gateway.rows}
    for key in sorted(native_rows.keys() | gateway_rows.keys()):
        expected = native_rows.get(key)
        actual = gateway_rows.get(key)
        if expected is None or actual is None:
            diff.append(Difference(key, "ROW_MISSING", None, None))
            continue
        for name, value in expected.items():
            observed = getattr(actual, name)
            if abs(value - observed) > policy.allowed_abs_diff:
                diff.append(Difference(key, name, value, observed))
    if diff:
        return Comparison(ComparisonState.MISMATCH, "VALUES_DIFFER", policy.policy_id, tuple(diff))
    return Comparison(ComparisonState.MATCH, "ALL_SIX_AND_ROWS_EQUAL", policy.policy_id, ())
