"""Phase 2: per counterparty-contract debit/credit side comparison (R2-US-030, TC090).

A net-zero total (+x on one contract, -x on another) must never hide a one-sided
contract difference. Every contract is compared on its debit side and its credit side
separately; any differing side is MISMATCH and each side is reported. A missing,
unknown or duplicated contract is INCONCLUSIVE. All amounts are Decimal (no floats).
Like reconciliation.py this is evaluation only and never an attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, Inexact, localcontext

from business_ai_gateway.phase2.reconciliation import ComparisonState, TolerancePolicy

_EXACT = Context(prec=60, Emin=-999_999, Emax=999_999)
_EXACT.traps[Inexact] = True

UNKNOWN_CONTRACT_REFS = frozenset({"", "UNKNOWN", "unknown", "N/A", "n/a"})


def _side_amount(value: Decimal) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("FINITE_DECIMAL_REQUIRED")
    if value < 0:
        # A negative side amount is exactly how a netted figure would sneak in.
        raise ValueError("SIDE_AMOUNT_NEGATIVE")
    return value


@dataclass(frozen=True, slots=True)
class ContractSides:
    counterparty_ref: str
    contract_ref: str
    debit: Decimal
    credit: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.counterparty_ref, str) or not isinstance(self.contract_ref, str):
            raise ValueError("ROW_ANALYTIC_REF_REQUIRED")  # noqa: TRY004 - same contract as reconciliation.py
        _side_amount(self.debit)
        _side_amount(self.credit)


@dataclass(frozen=True, slots=True)
class SideReport:
    counterparty_ref: str
    contract_ref: str
    side: str  # "debit" | "credit"
    expected: Decimal
    actual: Decimal
    equal: bool


@dataclass(frozen=True, slots=True)
class NettingResult:
    state: ComparisonState
    reason_code: str
    policy_id: str
    sides: tuple[SideReport, ...]
    net_native: Decimal | None  # informational only; never used for the verdict
    net_gateway: Decimal | None
    authority: str = "EVALUATION_ONLY"


def _inconclusive(reason: str, policy: TolerancePolicy) -> NettingResult:
    return NettingResult(ComparisonState.INCONCLUSIVE, reason, policy.policy_id, (), None, None)


def _index(items: tuple[ContractSides, ...]) -> dict[tuple[str, str], ContractSides] | str:
    out: dict[tuple[str, str], ContractSides] = {}
    for item in items:
        if (item.counterparty_ref.strip() in UNKNOWN_CONTRACT_REFS
                or item.contract_ref.strip() in UNKNOWN_CONTRACT_REFS):
            return "UNKNOWN_CONTRACT"
        key = (item.counterparty_ref, item.contract_ref)
        if key in out:
            return "DUPLICATE_CONTRACT"
        out[key] = item
    return out


def compare_contract_sides(
    native: tuple[ContractSides, ...],
    gateway: tuple[ContractSides, ...],
    *,
    policy: TolerancePolicy,
) -> NettingResult:
    """Compare debit and credit sides of every counterparty-contract separately."""
    try:
        with localcontext(_EXACT):
            return _compare(native, gateway, policy)
    except ArithmeticError:
        return _inconclusive("DECIMAL_PRECISION_EXCEEDED", policy)


def _compare(
    native: tuple[ContractSides, ...],
    gateway: tuple[ContractSides, ...],
    policy: TolerancePolicy,
) -> NettingResult:
    if not native or not gateway:
        return _inconclusive("CONTRACT_SIDES_MISSING", policy)
    n_idx = _index(native)
    g_idx = _index(gateway)
    if isinstance(n_idx, str):
        return _inconclusive(n_idx, policy)
    if isinstance(g_idx, str):
        return _inconclusive(g_idx, policy)
    if n_idx.keys() != g_idx.keys():
        return _inconclusive("CONTRACT_SET_MISMATCH", policy)

    reports: list[SideReport] = []
    for key in sorted(n_idx):
        for side in ("debit", "credit"):
            expected = getattr(n_idx[key], side)
            actual = getattr(g_idx[key], side)
            reports.append(SideReport(key[0], key[1], side, expected, actual,
                                      abs(expected - actual) <= policy.allowed_abs_diff))
    net_native = sum((c.debit - c.credit for c in n_idx.values()), Decimal(0))
    net_gateway = sum((c.debit - c.credit for c in g_idx.values()), Decimal(0))
    if all(r.equal for r in reports):
        return NettingResult(ComparisonState.MATCH, "ALL_CONTRACT_SIDES_EQUAL",
                             policy.policy_id, tuple(reports), net_native, net_gateway)
    return NettingResult(ComparisonState.MISMATCH, "CONTRACT_SIDE_DIFFERS",
                         policy.policy_id, tuple(reports), net_native, net_gateway)
