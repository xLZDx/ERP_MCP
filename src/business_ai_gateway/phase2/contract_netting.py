"""Phase 2: per counterparty-contract debit/credit side comparison (R2-US-030, TC090).

A net-zero total (+x on one contract, -x on another) must never hide a one-sided
contract difference. Every contract is compared on its debit side and its credit side
separately; any differing side is MISMATCH and each side is reported. A missing,
unknown, duplicated or malformed contract is INCONCLUSIVE. All amounts are Decimal (no floats).
Like reconciliation.py this is evaluation only and never an attestation.

Storno mapping: a side amount is never negative. A reversal (storno) must be mapped by the
caller to a POSITIVE amount on the opposite side; a negative side amount is how a netted figure
would sneak in, so it makes the comparison INCONCLUSIVE with ``NEGATIVE_SIDE`` (it is accepted by
the constructor so the verdict, not an exception, carries the reason).

Contract references are matched after ``clean_identity`` (NFKC, casefold, strip of spaces), so
``"A"``/``" a "`` are one counterparty. None, blank, unreadable or placeholder values
(``unknown``, ``n/a``, ``-``, ``none``, ``null`` ...) and the 1C empty reference (the all-zero
GUID in any dash/brace form) are unknown contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, Inexact, localcontext

from business_ai_gateway.phase2._identity import clean_identity
from business_ai_gateway.phase2.reconciliation import ComparisonState, TolerancePolicy

_EXACT = Context(prec=60, Emin=-999_999, Emax=999_999)
_EXACT.traps[Inexact] = True

# Compared after clean_identity (casefolded), so one lowercase spelling covers every case variant.
UNKNOWN_CONTRACT_REFS = frozenset({
    "", "unknown", "n/a", "none", "null", "nil", "undefined", "-", "--", "?", "unk",
})


def _side_amount(value: Decimal) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("FINITE_DECIMAL_REQUIRED")
    return value


@dataclass(frozen=True, slots=True)
class ContractSides:
    counterparty_ref: str | None
    contract_ref: str | None
    debit: Decimal
    credit: Decimal

    def __post_init__(self) -> None:
        for ref in (self.counterparty_ref, self.contract_ref):
            if ref is not None and not isinstance(ref, str):
                raise ValueError("ROW_ANALYTIC_REF_REQUIRED")  # same error contract as reconciliation.py
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


def _norm(ref: object) -> str:
    return clean_identity(ref) if isinstance(ref, str) else ""


def _is_unknown_ref(norm: str) -> bool:
    """Placeholder refs and the 1C empty reference (any all-zero GUID spelling) are unknown."""
    if norm in UNKNOWN_CONTRACT_REFS:
        return True
    bare = norm.strip("{}()").replace("-", "")
    return len(bare) == 32 and set(bare) == {"0"}


def _index(items: object) -> dict[tuple[str, str], ContractSides] | str:
    if not isinstance(items, tuple):
        return "CONTRACT_SIDES_INVALID"
    out: dict[tuple[str, str], ContractSides] = {}
    for item in items:
        if (not isinstance(item, ContractSides) or type(item.debit) is not Decimal
                or type(item.credit) is not Decimal):
            return "CONTRACT_SIDES_INVALID"
        cp, contract = _norm(item.counterparty_ref), _norm(item.contract_ref)
        if _is_unknown_ref(cp) or _is_unknown_ref(contract):
            return "UNKNOWN_CONTRACT"
        if item.debit < 0 or item.credit < 0:
            return "NEGATIVE_SIDE"
        if (cp, contract) in out:
            return "DUPLICATE_CONTRACT"
        out[(cp, contract)] = item
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
    if isinstance(native, tuple) and isinstance(gateway, tuple) and (not native or not gateway):
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
            reports.append(SideReport(n_idx[key].counterparty_ref.strip(),
                                      n_idx[key].contract_ref.strip(), side, expected, actual,
                                      abs(expected - actual) <= policy.allowed_abs_diff))
    net_native = sum((c.debit - c.credit for c in n_idx.values()), Decimal(0))
    net_gateway = sum((c.debit - c.credit for c in g_idx.values()), Decimal(0))
    if all(r.equal for r in reports):
        return NettingResult(ComparisonState.MATCH, "ALL_CONTRACT_SIDES_EQUAL",
                             policy.policy_id, tuple(reports), net_native, net_gateway)
    return NettingResult(ComparisonState.MISMATCH, "CONTRACT_SIDE_DIFFERS",
                         policy.policy_id, tuple(reports), net_native, net_gateway)
