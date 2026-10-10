"""Phase 2: deterministic comparison of posted 1C purchase documents.

Uses exact source-native identities. No fuzzy names, no formula for invoice
amounts, no write-back, no claim that a report is attested. Native journal and
MCP must independently resolve the same scoped source snapshot.

Trust boundary: the comparison never relies on ``==``/``<`` of caller-supplied objects. Constructors
accept exact ``str``/``datetime``/``Decimal`` only and keep plain UTC datetimes; the comparison works
on frozen copies built once from exact types, and any hostile or malformed input ends in a fixed
INCONCLUSIVE code (it never raises).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import NamedTuple

from ._identity import canonical_guid, is_empty_1c_ref


def utc_exact(value: object) -> datetime:
    """A plain UTC ``datetime`` built from ONE read of the offset; exact ``datetime`` only.

    A custom ``tzinfo`` may answer differently on every call, so the offset is read once and the
    result carries ``UTC`` itself, never the caller's tzinfo.
    """
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError("QUALIFIED_TIMESTAMP_REQUIRED")
    try:
        offset = value.utcoffset()
        if type(offset) is not timedelta:
            raise ValueError("QUALIFIED_TIMESTAMP_REQUIRED")
        u = value.replace(tzinfo=None) - offset
        return datetime(u.year, u.month, u.day, u.hour, u.minute, u.second, u.microsecond, tzinfo=UTC)
    except (ValueError, OverflowError, TypeError) as exc:
        raise ValueError("QUALIFIED_TIMESTAMP_REQUIRED") from exc


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _key(ref: str) -> str:
    """Identity key of a reference: GUID spellings are one reference, other text stays as is."""
    return canonical_guid(ref) or ref


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
        if not all(_text(v) for v in (
            self.tenant_id, self.source_id, self.company_ref,
            self.counterparty_ref, self.currency,
        )):
            raise ValueError("PURCHASE_SCOPE_INVALID")
        start, end = utc_exact(self.from_inclusive), utc_exact(self.until_exclusive)
        if start >= end:
            raise ValueError("PURCHASE_PERIOD_INVALID")
        object.__setattr__(self, "from_inclusive", start)
        object.__setattr__(self, "until_exclusive", end)


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
        if not all(_text(v) for v in (
            self.doc_ref, self.company_ref, self.counterparty_ref,
            self.contract_ref, self.number, self.currency,
        )):
            raise ValueError("PURCHASE_DOCUMENT_IDENTITY_INVALID")
        occurred = utc_exact(self.occurred_at)
        if type(self.amount) is not Decimal or not self.amount.is_finite():
            raise ValueError("PURCHASE_FINITE_DECIMAL_REQUIRED")
        if type(self.posted) is not bool or type(self.deletion_mark) is not bool:
            raise ValueError("PURCHASE_POSTED_FLAG_UNQUALIFIED")
        object.__setattr__(self, "occurred_at", occurred)


@dataclass(frozen=True, slots=True)
class PurchaseListing:
    scope: PurchaseScope
    snapshot_ref: str
    documents: tuple[PurchaseDocument, ...]
    complete: bool

    def __post_init__(self) -> None:
        if not _text(self.snapshot_ref) or is_empty_1c_ref(self.snapshot_ref):
            raise ValueError("PURCHASE_SNAPSHOT_REF_REQUIRED")  # the empty 1C reference is no snapshot
        if type(self.scope) is not PurchaseScope or type(self.documents) is not tuple:
            raise ValueError("PURCHASE_LISTING_INVALID")
        seen: set[str] = set()
        for doc in self.documents:
            if type(doc) is not PurchaseDocument:
                raise ValueError("PURCHASE_LISTING_INVALID")
            key = _key(doc.doc_ref)  # two spellings of one GUID are one document
            if key in seen:
                raise ValueError("DUPLICATE_PURCHASE_REF")
            seen.add(key)


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


class _Doc(NamedTuple):
    ref: str  # as the source spelled it
    company: str  # reference keys (canonical GUID or the text itself)
    counterparty: str
    contract: str
    number: str
    occurred_at: datetime
    amount: Decimal
    currency: str
    posted: bool
    deletion_mark: bool


class _Frozen(NamedTuple):
    # (tenant, source, company key, counterparty key, from UTC, until UTC, currency)
    scope: tuple[object, ...]
    snapshot_ref: str
    complete: bool
    docs: dict[str, _Doc]


def _freeze(listing: object) -> _Frozen | None:
    """Frozen copy of a listing from exact types only (None for anything else); each attribute is
    read once, so nothing downstream depends on the caller's objects."""
    if type(listing) is not PurchaseListing:
        return None
    s, snapshot, documents, complete = (
        listing.scope, listing.snapshot_ref, listing.documents, listing.complete)
    if type(s) is not PurchaseScope or type(documents) is not tuple:
        return None
    tenant, source, company, cparty, start, end, currency = (
        s.tenant_id, s.source_id, s.company_ref, s.counterparty_ref, s.from_inclusive,
        s.until_exclusive, s.currency)
    if not all(_text(v) for v in (tenant, source, company, cparty, currency, snapshot)):
        return None
    if is_empty_1c_ref(snapshot) or is_empty_1c_ref(company) or is_empty_1c_ref(cparty):
        return None
    start, end = utc_exact(start), utc_exact(end)
    if start >= end:
        return None
    docs: dict[str, _Doc] = {}
    for d in documents:
        if type(d) is not PurchaseDocument:
            return None
        ref, dco, dcp, dct, num, at, amount, cur, posted, deleted = (
            d.doc_ref, d.company_ref, d.counterparty_ref, d.contract_ref, d.number,
            d.occurred_at, d.amount, d.currency, d.posted, d.deletion_mark)
        if not all(_text(v) for v in (ref, dco, dcp, dct, num, cur)):
            return None
        if any(is_empty_1c_ref(v) for v in (ref, dco, dcp, dct)):
            return None
        if (type(amount) is not Decimal or not amount.is_finite()
                or type(posted) is not bool or type(deleted) is not bool):
            return None
        key = _key(ref)
        if key in docs:  # two spellings of one document
            return None
        docs[key] = _Doc(ref, _key(dco), _key(dcp), _key(dct), num, utc_exact(at), amount, cur,
                         posted, deleted)
    return _Frozen((tenant, source, _key(company), _key(cparty), start, end, currency),
                   snapshot, complete is True, docs)


def _qualified(f: _Frozen) -> bool:
    _, _, company, cparty, start, end, currency = f.scope
    return f.complete and all(
        d.company == company and d.counterparty == cparty and d.currency == currency
        and start <= d.occurred_at < end  # type: ignore[operator]
        and d.posted is True and d.deletion_mark is False
        for d in f.docs.values()
    )


_FIELDS = (
    "company", "counterparty", "contract", "number", "occurred_at", "amount", "currency", "posted",
    "deletion_mark",
)
_FIELD_NAMES = {
    "company": "company_ref", "counterparty": "counterparty_ref", "contract": "contract_ref",
}


def _inconclusive(code: str) -> PurchaseComparison:
    return PurchaseComparison(PurchaseResultKind.INCONCLUSIVE, code)


def compare_posted_purchases(native: object, gateway: object) -> PurchaseComparison:
    """Never raises: hostile or malformed input ends in INCONCLUSIVE ``PURCHASE_INPUT_INVALID``."""
    try:
        return _compare(native, gateway)
    except Exception:  # noqa: BLE001 - fixed code only, no text leak
        return _inconclusive("PURCHASE_INPUT_INVALID")


def _compare(native: object, gateway: object) -> PurchaseComparison:
    n, g = _freeze(native), _freeze(gateway)
    if n is None or g is None:
        return _inconclusive("PURCHASE_INPUT_INVALID")
    if n.scope != g.scope:
        return _inconclusive("PURCHASE_SCOPE_MISMATCH")
    if n.snapshot_ref != g.snapshot_ref:
        return _inconclusive("PURCHASE_SNAPSHOT_MISMATCH")
    if not _qualified(n):
        return _inconclusive("NATIVE_LISTING_UNQUALIFIED")
    if not _qualified(g):
        return _inconclusive("GATEWAY_LISTING_UNQUALIFIED")
    if not n.docs and not g.docs:
        # Two empty listings prove nothing (same rule as reconciliation.py: no rows).
        return _inconclusive("PURCHASE_BOTH_LISTINGS_EMPTY")
    differences: list[PurchaseDifference] = []
    for key in sorted(n.docs.keys() | g.docs.keys()):
        x, y = n.docs.get(key), g.docs.get(key)
        if x is None or y is None:
            shown = x.ref if x is not None else y.ref  # type: ignore[union-attr]
            differences.append(PurchaseDifference(
                shown, "DOCUMENT_PRESENCE", "present" if x is not None else None,
                "present" if y is not None else None))
            continue
        for field in _FIELDS:
            expected, actual = getattr(x, field), getattr(y, field)
            if expected != actual:
                differences.append(PurchaseDifference(
                    x.ref, _FIELD_NAMES.get(field, field), str(expected), str(actual)))
    if differences:
        return PurchaseComparison(
            PurchaseResultKind.MISMATCH, "PURCHASE_DOCUMENTS_DIFFER", tuple(differences)
        )
    return PurchaseComparison(PurchaseResultKind.MATCH, "POSTED_DOCUMENTS_EQUAL")
