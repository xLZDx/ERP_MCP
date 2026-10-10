"""Phase 2: deterministic comparison of posted 1C purchase documents.

Uses exact source-native identities. No fuzzy names, no formula for invoice
amounts, no write-back, no claim that a report is attested. Native journal and
MCP must independently resolve the same scoped source snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


def _timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("QUALIFIED_TIMESTAMP_REQUIRED")
    return value


@dataclass(frozen=True, slots=True)
class PurchaseScope:
    tenant_id: str
    source_id: str
    company_ref: str
    counterparty_ref: str
    from_inclusive: datetime
    until_exclusive: datetime
    currency: str

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.tenant_id, self.source_id, self.company_ref,
            self.counterparty_ref, self.currency,
        )):
            raise ValueError("PURCHASE_SCOPE_INVALID")
        if _timestamp(self.from_inclusive) >= _timestamp(self.until_exclusive):
            raise ValueError("PURCHASE_PERIOD_INVALID")


@dataclass(frozen=True, slots=True)
class PurchaseDocument:
    doc_ref: str
    company_ref: str
    counterparty_ref: str
    contract_ref: str
    number: str
    occurred_at: datetime
    amount: Decimal
    currency: str
    posted: bool
    deletion_mark: bool

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.doc_ref, self.company_ref, self.counterparty_ref,
            self.contract_ref, self.number, self.currency,
        )):
            raise ValueError("PURCHASE_DOCUMENT_IDENTITY_INVALID")
        _timestamp(self.occurred_at)
        if type(self.amount) is not Decimal or not self.amount.is_finite():
            raise ValueError("PURCHASE_FINITE_DECIMAL_REQUIRED")
        if type(self.posted) is not bool or type(self.deletion_mark) is not bool:
            raise ValueError("PURCHASE_POSTED_FLAG_UNQUALIFIED")


@dataclass(frozen=True, slots=True)
class PurchaseListing:
    scope: PurchaseScope
    snapshot_ref: str
    documents: tuple[PurchaseDocument, ...]
    complete: bool

    def __post_init__(self) -> None:
        if not self.snapshot_ref:
            raise ValueError("PURCHASE_SNAPSHOT_REF_REQUIRED")
        seen: set[str] = set()
        for doc in self.documents:
            if doc.doc_ref in seen:
                raise ValueError("DUPLICATE_PURCHASE_REF")
            seen.add(doc.doc_ref)


class PurchaseResultKind(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class PurchaseDifference:
    doc_ref: str
    field: str
    expected: str | None
    actual: str | None


@dataclass(frozen=True, slots=True)
class PurchaseComparison:
    state: PurchaseResultKind
    reason_code: str
    differences: tuple[PurchaseDifference, ...] = ()
    authority: str = "EVALUATION_ONLY"


def _listing_qualified(listing: PurchaseListing) -> bool:
    if type(listing.complete) is not bool or listing.complete is not True:
        return False
    s = listing.scope
    return all(
        d.company_ref == s.company_ref
        and d.counterparty_ref == s.counterparty_ref
        and d.currency == s.currency
        and s.from_inclusive <= d.occurred_at < s.until_exclusive
        and d.posted is True and d.deletion_mark is False
        for d in listing.documents
    )


def compare_posted_purchases(
    native: PurchaseListing, gateway: PurchaseListing,
) -> PurchaseComparison:
    if native.scope != gateway.scope:
        return PurchaseComparison(PurchaseResultKind.INCONCLUSIVE, "PURCHASE_SCOPE_MISMATCH")
    if native.snapshot_ref != gateway.snapshot_ref:
        return PurchaseComparison(PurchaseResultKind.INCONCLUSIVE, "PURCHASE_SNAPSHOT_MISMATCH")
    if not _listing_qualified(native):
        return PurchaseComparison(PurchaseResultKind.INCONCLUSIVE, "NATIVE_LISTING_UNQUALIFIED")
    if not _listing_qualified(gateway):
        return PurchaseComparison(PurchaseResultKind.INCONCLUSIVE, "GATEWAY_LISTING_UNQUALIFIED")
    if not native.documents and not gateway.documents:
        # Two empty listings prove nothing (same rule as reconciliation.py: no rows).
        return PurchaseComparison(PurchaseResultKind.INCONCLUSIVE, "PURCHASE_BOTH_LISTINGS_EMPTY")
    a = {d.doc_ref: d for d in native.documents}
    b = {d.doc_ref: d for d in gateway.documents}
    differences: list[PurchaseDifference] = []
    for ref in sorted(a.keys() | b.keys()):
        x, y = a.get(ref), b.get(ref)
        if x is None or y is None:
            differences.append(PurchaseDifference(ref, "DOCUMENT_PRESENCE", "present" if x else None, "present" if y else None))
            continue
        for field in (
            "company_ref", "counterparty_ref", "contract_ref", "number",
            "occurred_at", "amount", "currency", "posted", "deletion_mark",
        ):
            expected, actual = getattr(x, field), getattr(y, field)
            if expected != actual:
                differences.append(PurchaseDifference(ref, field, str(expected), str(actual)))
    if differences:
        return PurchaseComparison(
            PurchaseResultKind.MISMATCH, "PURCHASE_DOCUMENTS_DIFFER", tuple(differences)
        )
    return PurchaseComparison(PurchaseResultKind.MATCH, "POSTED_DOCUMENTS_EQUAL")
