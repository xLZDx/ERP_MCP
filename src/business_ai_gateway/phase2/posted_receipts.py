"""Phase 2 (R2-US-032): paginated retrieval of posted purchase receipts, with a proof record and a
three-way assessment.

Pure and read-only: the only collaborators are a page-source port (``fetch_page``) and an
``AliasResolver``; no network, file, database or Release 1 import, no wall clock, no write path.
Nothing here is a capability flag; results carry ``EVALUATION_ONLY`` authority and cannot promote.

Rules
- The request (``PurchaseScope`` + direction + supplier reference) is validated BEFORE any fetch:
  wrong direction / currency / period / bounds, and an alias that is not RESOLVED (exact namespaced
  reference inside the company scope) stop retrieval with a fixed reason code; nothing is guessed.
- A page is validated atomically before it is merged. A row with a missing/blank/ambiguous identity
  (see ``_identity``), a non-bool posted flag, a naive timestamp or a non-finite amount refuses the
  whole page (no listing is surfaced); the row is never skipped.
- Direction is ENFORCED, not asserted: the port receives the direction and every page carries a
  source-native document kind per row (``Page.kinds``, parallel to ``documents``). A page without a
  well-formed kind per row is refused (PAGE_DIRECTION_UNPROVEN); a row whose kind is not RECEIPT
  (sale, return, ...) is never kept and is counted under WRONG_DIRECTION.
- The alias scope is resolved through the shared normalisation (NFKC + casefold). To stop a request
  scope that differs only in case/form from the registered one from resolving, tenant and company
  must already be canonical (``clean_identity(x) == x``, i.e. lower-case) or the request is refused
  with ALIAS_SCOPE_VIOLATION. A missing supplier reference is refused (ALIAS_NOT_FOUND) BEFORE the
  resolver is called: names alone never resolve and must not enqueue review items.
- Kept rows: exact company, counterparty, currency, period [from, until), Posted, not deletion-marked.
  Every other row is counted under exactly ONE reason, first match wins in this order:
  WRONG_DIRECTION, WRONG_COMPANY, WRONG_COUNTERPARTY, WRONG_CURRENCY, OUT_OF_PERIOD, DELETED, UNPOSTED.
- COMPLETE only when a terminal page (no next token) was reached, the token chain was contiguous
  (no blank/repeated/regressed token, optional ``page_index`` gap-free), no ``doc_ref`` repeated in
  any page (kept or excluded), the snapshot ref never changed, and page/row counts stayed within the
  hard bounds. Otherwise ``complete=False`` plus a reason code; the retriever, not the port, decides.
  A single terminal page with zero rows and no ``page_index`` is EMPTY_UNPROVEN (not complete).
- When the source itself is unreliable (bad page, duplicate, snapshot change, token/page-chain
  defect) no listing is surfaced (``_NO_LISTING``); only honest truncation (SOURCE_ERROR,
  PAGE_LIMIT_HIT, ROW_LIMIT_HIT) keeps the validated earlier pages as an INCOMPLETE listing.
- The proof digest binds alias, company, counterparty, currency, period, direction, source id,
  snapshot ref, page tokens, exclusion counts and the canonical digest of the returned listing
  (which itself binds the direction). The digest is an INTEGRITY check against accidental or
  partial tampering, NOT authenticity: anyone can recompute it, so the assessment re-validates the
  proof content as well (see ``_completeness``).
- Reason codes are fixed constants; caller or source text is never echoed into them.

RESIDUAL RISK: the port is trusted to honour the scope it is given only as far as the per-row checks
above prove it; the chain cannot detect a source that silently skips a page while issuing a valid
token (``page_index`` is optional and only checked when the source supplies it).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, Protocol

from ._identity import canonical_guid, clean_identity, exact_text, is_empty_1c_ref
from .aliases import (
    AliasOutcome,
    AliasResolver,
    AliasScope,
    Reference,
    ResolutionResult,
    ResolveQuery,
)
from .comparison_snapshot import canonical_digest
from .purchase_reconciliation import (
    PurchaseDifference,
    PurchaseDocument,
    PurchaseListing,
    PurchaseResultKind,
    PurchaseScope,
    compare_posted_purchases,
    nfkc_stable,
)

__all__ = [
    "MAX_PAGES",
    "MAX_ROWS",
    "CompletenessVerdict",
    "Direction",
    "DiscrepancyVerdict",
    "ExclusionReason",
    "Page",
    "PageSource",
    "PostedReceiptsRetriever",
    "ReceiptsAssessment",
    "ReceiptsProof",
    "ReceiptsRequest",
    "RetrievalReason",
    "RetrievalResult",
    "assess_receipts",
]

MAX_PAGES: Final = 100
MAX_ROWS: Final = 10_000
_MAX_ADJUSTED: Final = 30  # same bounds as ap_account_strategy._amount_ok
_MIN_EXPONENT: Final = -8
_AUTHORITY: Final = "EVALUATION_ONLY"


class Direction(StrEnum):
    RECEIPT = "RECEIPT"  # purchase / inbound
    SALE = "SALE"  # sales / outbound: never accepted by this retriever


class ExclusionReason(StrEnum):
    WRONG_DIRECTION = "WRONG_DIRECTION"
    UNPOSTED = "UNPOSTED"
    DELETED = "DELETED"
    WRONG_COMPANY = "WRONG_COMPANY"
    WRONG_COUNTERPARTY = "WRONG_COUNTERPARTY"
    WRONG_CURRENCY = "WRONG_CURRENCY"
    OUT_OF_PERIOD = "OUT_OF_PERIOD"


_EXCLUSION_ORDER: Final = (
    ExclusionReason.WRONG_DIRECTION, ExclusionReason.UNPOSTED, ExclusionReason.DELETED, ExclusionReason.WRONG_COMPANY,
    ExclusionReason.WRONG_COUNTERPARTY, ExclusionReason.WRONG_CURRENCY,
    ExclusionReason.OUT_OF_PERIOD,
)


class RetrievalReason(StrEnum):
    OK = "OK"
    # refused before any fetch
    REQUEST_INVALID = "REQUEST_INVALID"
    SCOPE_INVALID = "SCOPE_INVALID"
    DIRECTION_NOT_RECEIPT = "DIRECTION_NOT_RECEIPT"
    CURRENCY_INVALID = "CURRENCY_INVALID"
    PERIOD_INVALID = "PERIOD_INVALID"
    BOUNDS_INVALID = "BOUNDS_INVALID"
    SOURCE_INVALID = "SOURCE_INVALID"
    RESOLVER_INVALID = "RESOLVER_INVALID"
    ALIAS_NOT_FOUND = "ALIAS_NOT_FOUND"
    ALIAS_AMBIGUOUS = "ALIAS_AMBIGUOUS"
    ALIAS_SCOPE_VIOLATION = "ALIAS_SCOPE_VIOLATION"
    ALIAS_REJECTED = "ALIAS_REJECTED"
    ALIAS_COUNTERPARTY_MISMATCH = "ALIAS_COUNTERPARTY_MISMATCH"
    # stopped mid-chain
    SOURCE_ERROR = "SOURCE_ERROR"
    PAGE_INVALID = "PAGE_INVALID"
    PAGE_IDENTITY_INVALID = "PAGE_IDENTITY_INVALID"
    PAGE_POSTED_FLAG_UNQUALIFIED = "PAGE_POSTED_FLAG_UNQUALIFIED"
    PAGE_ROW_INVALID = "PAGE_ROW_INVALID"
    PAGE_DIRECTION_UNPROVEN = "PAGE_DIRECTION_UNPROVEN"
    EMPTY_UNPROVEN = "EMPTY_UNPROVEN"
    SNAPSHOT_REF_INVALID = "SNAPSHOT_REF_INVALID"
    SNAPSHOT_CHANGED = "SNAPSHOT_CHANGED"
    TOKEN_MISSING = "TOKEN_MISSING"
    TOKEN_REPEATED = "TOKEN_REPEATED"
    TOKEN_REGRESSED = "TOKEN_REGRESSED"
    PAGE_GAP = "PAGE_GAP"
    DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
    PAGE_LIMIT_HIT = "PAGE_LIMIT_HIT"
    ROW_LIMIT_HIT = "ROW_LIMIT_HIT"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Reasons after which the rows read so far are NOT surfaced (the source itself is unreliable).
_NO_LISTING: Final = frozenset({
    RetrievalReason.PAGE_INVALID, RetrievalReason.PAGE_IDENTITY_INVALID,
    RetrievalReason.PAGE_POSTED_FLAG_UNQUALIFIED, RetrievalReason.PAGE_ROW_INVALID,
    RetrievalReason.PAGE_DIRECTION_UNPROVEN,
    RetrievalReason.SNAPSHOT_REF_INVALID, RetrievalReason.PROOF_UNAVAILABLE,
    RetrievalReason.INTERNAL_ERROR,
    RetrievalReason.DUPLICATE_DOCUMENT, RetrievalReason.SNAPSHOT_CHANGED,
    RetrievalReason.PAGE_GAP, RetrievalReason.TOKEN_MISSING, RetrievalReason.TOKEN_REPEATED,
    RetrievalReason.TOKEN_REGRESSED,
})


@dataclass(frozen=True, slots=True)
class Page:
    """One page served by the source. ``page_index`` is optional (0-based) extra chain evidence.
    ``kinds`` is the source-native document kind of each row (parallel to ``documents``, same
    length); ``PurchaseDocument`` carries no direction, so this is where it is proven."""
    documents: tuple[PurchaseDocument, ...]
    next_token: str | None
    snapshot_ref: str
    page_index: int | None = None
    kinds: tuple[str, ...] | None = None


class PageSource(Protocol):
    """Read-only port. Raises anything on failure; the retriever maps it to SOURCE_ERROR."""

    def fetch_page(
        self, scope: PurchaseScope, direction: Direction, continuation_token: str | None,
    ) -> Page: ...


@dataclass(frozen=True, slots=True)
class ReceiptsRequest:
    scope: PurchaseScope
    direction: Direction
    supplier_reference: Reference | None
    supplier_name: str = ""


@dataclass(frozen=True, slots=True)
class ReceiptsProof:
    alias_entity_id: str
    alias_namespace: str
    alias_value: str
    tenant_id: str
    company_ref: str
    counterparty_ref: str
    currency: str
    from_inclusive: datetime
    until_exclusive: datetime
    direction: str
    source_id: str
    snapshot_ref: str | None
    page_tokens: tuple[str | None, ...]
    pages_fetched: int
    rows_seen: int
    kept_count: int
    exclusions: tuple[tuple[str, int], ...]
    terminal_page_reached: bool
    complete: bool
    reason: str
    listing_digest: str | None
    digest: str


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    complete: bool
    reason: RetrievalReason
    listing: PurchaseListing | None
    proof: ReceiptsProof | None
    authority: str = _AUTHORITY


def _refused(reason: RetrievalReason) -> RetrievalResult:
    return RetrievalResult(False, reason, None, None)


# -- strict field checks ---------------------------------------------------------------------------
def _strict(value: object) -> bool:
    """A non-blank, already-clean identity: refused rather than repaired.

    Exactly ``str`` (never a subclass): a subclass can lie in ``__eq__``/``__ne__`` and so spoof the
    direction or identity comparisons that follow.
    """
    return (type(value) is str and bool(value) and exact_text(value) == value
            and nfkc_stable(value))  # compatibility spellings are refused


def _snapshot_ok(value: object) -> bool:
    """A strict snapshot ref that is not the empty 1C reference (which identifies no snapshot)."""
    return _strict(value) and not is_empty_1c_ref(value)


def _currency_ok(value: object) -> bool:
    return (type(value) is str and len(value) == 3 and value.isascii() and value.isalpha()
            and value.isupper())


def _aware(value: object) -> bool:
    """Exactly ``datetime`` (never a subclass: it could override the comparisons) and tz-aware."""
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _utc(value: datetime) -> datetime:
    """A plain UTC ``datetime``; call only on values that passed ``_aware``."""
    return value.astimezone(UTC)


def _ref_key(ref: str) -> str:
    """De-duplication key of a document reference: GUID spellings (case, braces, dashes) are one
    document; every other identifier stays case-sensitive. The source spelling is never rewritten."""
    return canonical_guid(ref) or ref


def _amount_ok(value: object) -> bool:
    return (type(value) is Decimal and value.is_finite() and value.adjusted() <= _MAX_ADJUSTED
            and value.as_tuple().exponent >= _MIN_EXPONENT)  # type: ignore[operator]


def _doc_payload(doc: PurchaseDocument) -> dict[str, object]:
    return {
        "doc_ref": doc.doc_ref, "company_ref": doc.company_ref,
        "counterparty_ref": doc.counterparty_ref, "contract_ref": doc.contract_ref,
        "number": doc.number, "occurred_at": doc.occurred_at, "amount": doc.amount,
        "currency": doc.currency, "posted": doc.posted, "deletion_mark": doc.deletion_mark,
    }


def _scope_payload(scope: PurchaseScope) -> dict[str, object]:
    return {
        "tenant_id": scope.tenant_id, "source_id": scope.source_id,
        "company_ref": scope.company_ref, "counterparty_ref": scope.counterparty_ref,
        "from_inclusive": scope.from_inclusive, "until_exclusive": scope.until_exclusive,
        "currency": scope.currency,
    }


def _listing_digest(listing: PurchaseListing) -> str:
    return canonical_digest({
        "scope": _scope_payload(listing.scope), "snapshot_ref": listing.snapshot_ref,
        "complete": listing.complete, "direction": Direction.RECEIPT.value,
        "documents": [_doc_payload(d) for d in sorted(listing.documents, key=lambda d: d.doc_ref)],
    })


def _proof_payload(p: ReceiptsProof) -> dict[str, object]:
    return {
        "alias_entity_id": p.alias_entity_id, "alias_namespace": p.alias_namespace,
        "alias_value": p.alias_value, "tenant_id": p.tenant_id, "company_ref": p.company_ref,
        "counterparty_ref": p.counterparty_ref, "currency": p.currency,
        "from_inclusive": p.from_inclusive, "until_exclusive": p.until_exclusive,
        "direction": p.direction, "source_id": p.source_id, "snapshot_ref": p.snapshot_ref,
        "page_tokens": list(p.page_tokens), "pages_fetched": p.pages_fetched,
        "rows_seen": p.rows_seen, "kept_count": p.kept_count,
        "exclusions": [[k, v] for k, v in p.exclusions],
        "terminal_page_reached": p.terminal_page_reached, "complete": p.complete,
        "reason": p.reason, "listing_digest": p.listing_digest,
    }


def _classify(doc: PurchaseDocument, scope: PurchaseScope,
              kind: str = Direction.RECEIPT.value) -> ExclusionReason | None:
    if kind != Direction.RECEIPT.value:
        return ExclusionReason.WRONG_DIRECTION
    if doc.company_ref != scope.company_ref:
        return ExclusionReason.WRONG_COMPANY
    if doc.counterparty_ref != scope.counterparty_ref:
        return ExclusionReason.WRONG_COUNTERPARTY
    if doc.currency != scope.currency:
        return ExclusionReason.WRONG_CURRENCY
    if not _utc(scope.from_inclusive) <= _utc(doc.occurred_at) < _utc(scope.until_exclusive):
        return ExclusionReason.OUT_OF_PERIOD
    if doc.deletion_mark is not False:
        return ExclusionReason.DELETED
    if doc.posted is not True:
        return ExclusionReason.UNPOSTED
    return None


def _check_row(doc: object) -> RetrievalReason | None:
    if type(doc) is not PurchaseDocument:
        return RetrievalReason.PAGE_IDENTITY_INVALID
    if not all(_strict(getattr(doc, f)) for f in (
        "doc_ref", "company_ref", "counterparty_ref", "contract_ref", "number", "currency",
    )):
        return RetrievalReason.PAGE_IDENTITY_INVALID
    if any(is_empty_1c_ref(getattr(doc, f)) for f in (
        "doc_ref", "company_ref", "counterparty_ref", "contract_ref",
    )):
        return RetrievalReason.PAGE_IDENTITY_INVALID  # the empty 1C reference identifies nothing
    if type(doc.posted) is not bool or type(doc.deletion_mark) is not bool:
        return RetrievalReason.PAGE_POSTED_FLAG_UNQUALIFIED
    if not _aware(doc.occurred_at) or not _amount_ok(doc.amount):
        return RetrievalReason.PAGE_ROW_INVALID
    return None


def _fresh_doc(doc: PurchaseDocument) -> PurchaseDocument:
    """A new document of exact types with a plain UTC timestamp built from one offset read."""
    return PurchaseDocument(
        doc.doc_ref, doc.company_ref, doc.counterparty_ref, doc.contract_ref, doc.number,
        doc.occurred_at, doc.amount, doc.currency, doc.posted, doc.deletion_mark)


def _fresh_scope(scope: PurchaseScope) -> PurchaseScope:
    return PurchaseScope(
        scope.tenant_id, scope.source_id, scope.company_ref, scope.counterparty_ref,
        scope.from_inclusive, scope.until_exclusive, scope.currency)


def _refreeze(listing: PurchaseListing) -> PurchaseListing:
    """A frozen copy (plain UTC datetimes, fresh objects) of an already type-checked listing."""
    return PurchaseListing(
        _fresh_scope(listing.scope), listing.snapshot_ref,
        tuple(_fresh_doc(d) for d in listing.documents), listing.complete)


def _keys_unique(docs: object) -> bool:
    return (type(docs) is tuple
            and len({_ref_key(d.doc_ref) for d in docs}) == len(docs))  # type: ignore[attr-defined]


def _check_scope(scope: object) -> RetrievalReason | None:
    if type(scope) is not PurchaseScope:
        return RetrievalReason.SCOPE_INVALID
    if not all(_strict(getattr(scope, f)) for f in (
        "tenant_id", "source_id", "company_ref", "counterparty_ref",
    )):
        return RetrievalReason.SCOPE_INVALID
    if is_empty_1c_ref(scope.company_ref) or is_empty_1c_ref(scope.counterparty_ref):
        return RetrievalReason.SCOPE_INVALID
    if not _currency_ok(scope.currency):
        return RetrievalReason.CURRENCY_INVALID
    if (not _aware(scope.from_inclusive) or not _aware(scope.until_exclusive)
            or _utc(scope.from_inclusive) >= _utc(scope.until_exclusive)):
        return RetrievalReason.PERIOD_INVALID
    return None


def _direction_ok(value: object) -> bool:
    return value is Direction.RECEIPT or (type(value) is str and value == "RECEIPT")


_ALIAS_REASONS: Final = {
    AliasOutcome.NOT_FOUND: RetrievalReason.ALIAS_NOT_FOUND,
    AliasOutcome.AMBIGUOUS: RetrievalReason.ALIAS_AMBIGUOUS,
    AliasOutcome.SCOPE_VIOLATION: RetrievalReason.ALIAS_SCOPE_VIOLATION,
}


class PostedReceiptsRetriever:
    """Retrieves a posted-receipts ``PurchaseListing`` page by page; never raises on bad input."""

    def __init__(self, source: PageSource, resolver: AliasResolver) -> None:
        self._source = source
        self._resolver = resolver

    def retrieve(
        self, request: ReceiptsRequest, *, max_pages: int = MAX_PAGES, max_rows: int = MAX_ROWS,
    ) -> RetrievalResult:
        try:
            return self._retrieve(request, max_pages, max_rows)
        except Exception:  # noqa: BLE001 - hostile input must end in a fixed code, never an exception
            return _refused(RetrievalReason.INTERNAL_ERROR)

    def _retrieve(self, request: object, max_pages: object, max_rows: object) -> RetrievalResult:
        if type(request) is not ReceiptsRequest:
            return _refused(RetrievalReason.REQUEST_INVALID)
        bad = _check_scope(request.scope)
        if bad is not None:
            return _refused(bad)
        try:
            scope = _fresh_scope(request.scope)  # plain UTC copy, one offset read
        except Exception:  # noqa: BLE001 - fixed code only
            return _refused(RetrievalReason.PERIOD_INVALID)
        if not _direction_ok(request.direction):
            return _refused(RetrievalReason.DIRECTION_NOT_RECEIPT)
        if (type(max_pages) is not int or type(max_rows) is not int
                or not 1 <= max_pages <= MAX_PAGES or not 1 <= max_rows <= MAX_ROWS):
            return _refused(RetrievalReason.BOUNDS_INVALID)
        if not callable(getattr(self._source, "fetch_page", None)):
            return _refused(RetrievalReason.SOURCE_INVALID)
        if not callable(getattr(self._resolver, "resolve", None)):
            return _refused(RetrievalReason.RESOLVER_INVALID)
        ref = request.supplier_reference
        if ref is not None and type(ref) is not Reference:
            return _refused(RetrievalReason.ALIAS_REJECTED)
        # the resolver normalises the scope (NFKC + casefold): only an already-canonical tenant and
        # company may reach it, otherwise "ACME" would silently resolve inside "acme"
        if (clean_identity(scope.tenant_id) != scope.tenant_id
                or clean_identity(scope.company_ref) != scope.company_ref):
            return _refused(RetrievalReason.ALIAS_SCOPE_VIOLATION)
        if ref is None:  # names never resolve; the resolver (side effects, not thread-safe) is not called
            return _refused(RetrievalReason.ALIAS_NOT_FOUND)
        try:
            resolved = self._resolver.resolve(
                AliasScope(scope.tenant_id, scope.company_ref),
                ResolveQuery(reference=ref, name=request.supplier_name),
            )
        except Exception:  # noqa: BLE001 - fixed code only, no text leak
            return _refused(RetrievalReason.ALIAS_REJECTED)
        if type(resolved) is not ResolutionResult:
            return _refused(RetrievalReason.ALIAS_REJECTED)
        if resolved.outcome is not AliasOutcome.RESOLVED:
            return _refused(_ALIAS_REASONS.get(resolved.outcome, RetrievalReason.ALIAS_REJECTED))
        entity_id = resolved.entity_id
        if not _strict(entity_id):  # exact str only: a subclass could lie in __eq__/__ne__
            return _refused(RetrievalReason.ALIAS_REJECTED)
        if entity_id != scope.counterparty_ref:
            return _refused(RetrievalReason.ALIAS_COUNTERPARTY_MISMATCH)
        return self._walk(scope, entity_id, ref, max_pages, max_rows)

    def _walk(self, scope: PurchaseScope, entity_id: str, ref: Reference, max_pages: int,
              max_rows: int) -> RetrievalResult:
        tokens: list[str | None] = []
        seen_tokens: set[str] = set()
        seen_refs: set[str] = set()
        kept: list[PurchaseDocument] = []
        counts = {r: 0 for r in _EXCLUSION_ORDER}
        rows = 0
        pages = 0
        snapshot: str | None = None
        token: str | None = None
        terminal = False
        reason = RetrievalReason.OK

        while True:
            if pages >= max_pages:
                reason = RetrievalReason.PAGE_LIMIT_HIT
                break
            tokens.append(token)
            try:
                page = self._source.fetch_page(scope, Direction.RECEIPT, token)
            except Exception:  # noqa: BLE001 - fixed code only, no text leak
                reason = RetrievalReason.SOURCE_ERROR
                break
            (reason, page_kept, page_counts, page_refs, n_rows,
             page_snap, page_next, page_idx) = self._accept_page(
                page, scope, snapshot, pages, token, seen_tokens, seen_refs, rows, max_rows,
            )
            if reason is not RetrievalReason.OK:
                break
            snapshot = page_snap
            pages += 1
            rows += n_rows
            kept.extend(page_kept)
            seen_refs |= page_refs
            for r, n in page_counts.items():
                counts[r] += n
            if page_next is None:
                terminal = True
                if rows == 0 and pages == 1 and page_idx is None:
                    reason = RetrievalReason.EMPTY_UNPROVEN  # nothing proves the source is empty
                break
            if token is not None:
                seen_tokens.add(token)
            token = page_next

        complete = reason is RetrievalReason.OK and terminal
        return self._finish(
            scope, entity_id, ref, snapshot, tokens, pages, rows, kept, counts, terminal, complete,
            reason,
        )

    @staticmethod
    def _accept_page(
        page: object, scope: PurchaseScope, snapshot: str | None, pages: int, token: str | None,
        seen_tokens: set[str], seen_refs: set[str], rows: int, max_rows: int,
    ) -> tuple[RetrievalReason, list[PurchaseDocument], dict[ExclusionReason, int], set[str], int,
               str | None, str | None, int | None]:
        def stop(r: RetrievalReason):
            return (r, [], {}, set(), 0, None, None, None)

        if type(page) is not Page:
            return stop(RetrievalReason.PAGE_INVALID)
        # every Page field is read exactly once; only these locals are used below and returned
        raw_docs, snap, idx, nxt, kinds = (
            page.documents, page.snapshot_ref, page.page_index, page.next_token, page.kinds)
        if type(raw_docs) not in (tuple, list):
            return stop(RetrievalReason.PAGE_INVALID)
        docs = tuple(raw_docs)  # one snapshot of the (possibly mutable) row container
        if not _snapshot_ok(snap):
            return stop(RetrievalReason.SNAPSHOT_REF_INVALID)
        if snapshot is not None and snap != snapshot:
            return stop(RetrievalReason.SNAPSHOT_CHANGED)
        if idx is not None:
            if type(idx) is not int:
                return stop(RetrievalReason.PAGE_INVALID)
            if idx < pages:
                return stop(RetrievalReason.TOKEN_REGRESSED)
            if idx > pages:
                return stop(RetrievalReason.PAGE_GAP)
        if nxt is not None:
            if not _strict(nxt):
                return stop(RetrievalReason.TOKEN_MISSING)
            if nxt == token:
                return stop(RetrievalReason.TOKEN_REPEATED)
            if nxt in seen_tokens:
                return stop(RetrievalReason.TOKEN_REGRESSED)
        if rows + len(docs) > max_rows:
            return stop(RetrievalReason.ROW_LIMIT_HIT)
        if (type(kinds) not in (tuple, list) or len(kinds) != len(docs)
                or not all(_strict(k) for k in kinds)):
            return stop(RetrievalReason.PAGE_DIRECTION_UNPROVEN)
        kinds = tuple(kinds)
        fresh: list[PurchaseDocument] = []
        for doc in docs:
            bad = _check_row(doc)
            if bad is not None:
                return stop(bad)
            try:
                fresh.append(_fresh_doc(doc))  # frozen exact-type copy with a plain UTC timestamp
            except Exception:  # noqa: BLE001 - fixed code only
                return stop(RetrievalReason.PAGE_ROW_INVALID)
        docs = tuple(fresh)
        page_refs: set[str] = set()
        for doc in docs:
            key = _ref_key(doc.doc_ref)
            if key in seen_refs or key in page_refs:
                return stop(RetrievalReason.DUPLICATE_DOCUMENT)
            page_refs.add(key)
        page_kept: list[PurchaseDocument] = []
        page_counts = {r: 0 for r in _EXCLUSION_ORDER}
        for doc, kind in zip(docs, kinds, strict=True):
            why = _classify(doc, scope, kind)
            if why is None:
                page_kept.append(doc)
            else:
                page_counts[why] += 1
        return RetrievalReason.OK, page_kept, page_counts, page_refs, len(docs), snap, nxt, idx

    @staticmethod
    def _finish(
        scope: PurchaseScope, entity_id: str, ref: Reference, snapshot: str | None,
        tokens: list[str | None], pages: int, rows: int, kept: list[PurchaseDocument],
        counts: dict[ExclusionReason, int], terminal: bool, complete: bool,
        reason: RetrievalReason,
    ) -> RetrievalResult:
        try:
            listing: PurchaseListing | None = None
            if snapshot is not None and reason not in _NO_LISTING:
                listing = PurchaseListing(
                    scope, snapshot, tuple(sorted(kept, key=lambda d: d.doc_ref)), complete,
                )
            draft = ReceiptsProof(
                entity_id, exact_text(ref.namespace), exact_text(ref.value), scope.tenant_id,
                scope.company_ref, scope.counterparty_ref, scope.currency, scope.from_inclusive,
                scope.until_exclusive, Direction.RECEIPT.value, scope.source_id, snapshot,
                tuple(tokens), pages, rows, len(kept),
                tuple((r.value, counts[r]) for r in _EXCLUSION_ORDER), terminal, complete,
                reason.value, _listing_digest(listing) if listing is not None else None, "",
            )
            proof = replace(draft, digest=canonical_digest(_proof_payload(draft)))
        except Exception:  # noqa: BLE001 - fixed code only, no text leak
            # keep the original stop reason; PROOF_UNAVAILABLE only when nothing else went wrong
            return _refused(reason if reason is not RetrievalReason.OK
                            else RetrievalReason.PROOF_UNAVAILABLE)
        return RetrievalResult(complete, reason, listing, proof)


# -- three-way assessment --------------------------------------------------------------------------
class CompletenessVerdict(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class DiscrepancyVerdict(StrEnum):
    NONE = "NONE"  # correctness is MATCH
    LISTED = "LISTED"  # correctness is MISMATCH; see ``discrepancies``
    NOT_ASSESSABLE = "NOT_ASSESSABLE"  # correctness is INCONCLUSIVE


@dataclass(frozen=True, slots=True)
class ReceiptsAssessment:
    """Three independent verdicts; never collapsed into one flag. Cannot promote anything."""
    completeness: CompletenessVerdict
    completeness_reason: str
    correctness: PurchaseResultKind
    correctness_reason: str
    discrepancy: DiscrepancyVerdict
    discrepancies: tuple[PurchaseDifference, ...]
    digest: str
    authority: str = _AUTHORITY


def _tokens_ok(tokens: object, pages: object) -> bool:
    if type(tokens) is not tuple or type(pages) is not int or pages != len(tokens):
        return False
    if not 1 <= pages <= MAX_PAGES or tokens[0] is not None:
        return False
    rest = tokens[1:]
    return all(_strict(t) for t in rest) and len(set(rest)) == len(rest)


def _counts_ok(proof: ReceiptsProof) -> bool:
    ex = proof.exclusions
    if type(ex) is not tuple or len(ex) != len(_EXCLUSION_ORDER):
        return False
    for item, expect in zip(ex, _EXCLUSION_ORDER, strict=True):
        if type(item) is not tuple or len(item) != 2:
            return False
        name, n = item
        if type(name) is not str or name != expect.value or type(n) is not int or n < 0:
            return False
    seen, kept = proof.rows_seen, proof.kept_count
    return (type(seen) is int and type(kept) is int and kept >= 0
            and seen == kept + sum(n for _, n in ex) and seen <= MAX_ROWS)


def _completeness(result: object) -> tuple[CompletenessVerdict, str]:
    try:
        return _completeness_unsafe(result)
    except Exception:  # noqa: BLE001 - forged objects with unset slots: fixed code only
        return CompletenessVerdict.INCOMPLETE, "PROOF_UNVERIFIABLE"


def _completeness_unsafe(result: object) -> tuple[CompletenessVerdict, str]:
    """COMPLETE only for a result whose proof CONTENT is internally consistent and whose rows are
    re-validated. The digests are an integrity check, not authenticity: a caller can recompute them
    for a forged result, so every digest-bound field is cross-checked against the listing as well."""
    inc = CompletenessVerdict.INCOMPLETE
    if type(result) is not RetrievalResult:
        return inc, "RESULT_INVALID"
    proof, listing = result.proof, result.listing
    if type(proof) is not ReceiptsProof or type(listing) is not PurchaseListing:
        reason = result.reason if type(result.reason) is RetrievalReason else None
        return inc, reason.value if reason and reason is not RetrievalReason.OK else "RESULT_INVALID"
    if not (result.complete is True and proof.complete is True and listing.complete is True
            and proof.terminal_page_reached is True and result.reason is RetrievalReason.OK):
        reason = result.reason if type(result.reason) is RetrievalReason else None
        return inc, reason.value if reason and reason is not RetrievalReason.OK else "RESULT_INCONSISTENT"
    frozen: PurchaseListing | None
    try:
        try:  # frozen plain-UTC copy: every later check and digest reads fixed values
            frozen = _refreeze(listing)
        except Exception:  # noqa: BLE001 - the specific checks below name the defect
            frozen = None
        if frozen is not None:
            listing = frozen
        if type(proof.digest) is not str or canonical_digest(_proof_payload(proof)) != proof.digest:
            return inc, "PROOF_DIGEST_MISMATCH"
        if (type(proof.listing_digest) is not str
                or _listing_digest(listing) != proof.listing_digest):
            return inc, "PROOF_LISTING_DIGEST_MISMATCH"
        s = listing.scope
        # every identity/period field is checked for its EXACT type before anything is compared, so
        # no str/datetime subclass (custom __eq__/__ne__/__lt__) can steer a comparison below
        if (type(s) is not PurchaseScope or _check_scope(s) is not None
                or not _snapshot_ok(listing.snapshot_ref)):
            return inc, "PROOF_SCOPE_MISMATCH"
        if (not all(_strict(getattr(proof, f)) for f in (
                "alias_entity_id", "alias_namespace", "alias_value", "tenant_id", "company_ref",
                "counterparty_ref", "source_id", "snapshot_ref", "direction", "reason"))
                or not _snapshot_ok(proof.snapshot_ref) or not _currency_ok(proof.currency)
                or not _aware(proof.from_inclusive) or not _aware(proof.until_exclusive)):
            return inc, "PROOF_CONTENT_INCONSISTENT"
        if proof.alias_entity_id != proof.counterparty_ref:
            return inc, "PROOF_CONTENT_INCONSISTENT"  # the resolved vendor is not the requested one
        if (proof.company_ref, proof.counterparty_ref, proof.currency, proof.source_id,
                proof.tenant_id, _utc(proof.from_inclusive), _utc(proof.until_exclusive),
                proof.snapshot_ref) != (
                s.company_ref, s.counterparty_ref, s.currency, s.source_id, s.tenant_id,
                _utc(s.from_inclusive), _utc(s.until_exclusive), listing.snapshot_ref):
            return inc, "PROOF_SCOPE_MISMATCH"
        if type(listing.documents) is not tuple:
            return inc, "PROOF_CONTENT_INCONSISTENT"
        docs = listing.documents
        if any(_check_row(d) is not None for d in docs):
            return inc, "PROOF_ROW_INVALID"
        if (proof.direction != Direction.RECEIPT.value or proof.reason != RetrievalReason.OK.value
                or not _counts_ok(proof) or proof.kept_count != len(docs)
                or not _tokens_ok(proof.page_tokens, proof.pages_fetched)
                or len({_ref_key(d.doc_ref) for d in docs}) != len(docs)):
            return inc, "PROOF_CONTENT_INCONSISTENT"
        if any(_classify(d, s) is not None for d in docs):
            return inc, "DOCUMENT_OUT_OF_SCOPE"
    except Exception:  # noqa: BLE001 - fixed code only, no text leak
        return inc, "PROOF_UNVERIFIABLE"
    if frozen is None:
        return inc, "PROOF_UNVERIFIABLE"
    return CompletenessVerdict.COMPLETE, "PAGINATION_PROVEN_COMPLETE"


def _safe_digest(listing: object) -> str | None:
    try:
        return _listing_digest(listing) if type(listing) is PurchaseListing else None  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - fixed code only, no text leak
        return None


def _native_ok(native: object) -> bool:
    """The caller-supplied native listing: exact types and a strict ``complete is True`` before it is
    compared (the comparison itself must never rely on its truthiness or custom comparisons)."""
    try:
        return (type(native) is PurchaseListing and native.complete is True
                and type(native.scope) is PurchaseScope and _check_scope(native.scope) is None
                and _snapshot_ok(native.snapshot_ref) and type(native.documents) is tuple
                and all(_check_row(d) is None for d in native.documents)
                and _keys_unique(native.documents))
    except Exception:  # noqa: BLE001 - fixed code only, no text leak
        return False


def assess_receipts(native: object, result: object) -> ReceiptsAssessment:
    """Never raises: a forged object (unset slots, hostile attributes) gives the fixed
    ASSESSMENT_UNVERIFIABLE result. See ``_assess`` for the rules."""
    try:
        return _assess(native, result)
    except Exception:  # noqa: BLE001 - fixed result, never an exception
        return _unverifiable()


def _unverifiable() -> ReceiptsAssessment:
    return ReceiptsAssessment(
        CompletenessVerdict.INCOMPLETE, "ASSESSMENT_UNVERIFIABLE", PurchaseResultKind.INCONCLUSIVE,
        "ASSESSMENT_DIGEST_UNAVAILABLE", DiscrepancyVerdict.NOT_ASSESSABLE, (),
        canonical_digest({"assessment": "UNVERIFIABLE", "authority": _AUTHORITY}),
    )


def _assess(native: object, result: object) -> ReceiptsAssessment:
    """Compare the retrieved gateway listing with the native journal listing; three verdicts.

    Correctness is only assessed against a gateway listing proven COMPLETE; otherwise it is
    INCONCLUSIVE (GATEWAY_NOT_PROVEN_COMPLETE) and the discrepancy NOT_ASSESSABLE, so a partial or
    forged result can never show MATCH/NONE. The assessment digest binds the proof digest, both
    listing digests, the snapshot ref and the scope."""
    completeness, c_reason = _completeness(result)
    correctness = PurchaseResultKind.INCONCLUSIVE
    k_reason = "GATEWAY_LISTING_MISSING"
    differences: tuple[PurchaseDifference, ...] = ()
    gateway = result.listing if type(result) is RetrievalResult else None
    if completeness is CompletenessVerdict.INCOMPLETE:
        k_reason = "GATEWAY_NOT_PROVEN_COMPLETE"
    elif not _native_ok(native):
        k_reason = "NATIVE_LISTING_UNQUALIFIED"
    elif type(gateway) is PurchaseListing:
        try:
            cmp = compare_posted_purchases(native, gateway)
            correctness, k_reason, differences = cmp.state, cmp.reason_code, cmp.differences
        except Exception:  # noqa: BLE001 - fixed code only, no text leak
            k_reason = "COMPARISON_FAILED"
    if correctness is PurchaseResultKind.MISMATCH:
        discrepancy = DiscrepancyVerdict.LISTED
    elif correctness is PurchaseResultKind.MATCH:
        discrepancy = DiscrepancyVerdict.NONE
    else:
        discrepancy = DiscrepancyVerdict.NOT_ASSESSABLE
    proof = result.proof if type(result) is RetrievalResult else None
    try:
        scope_bound = _scope_payload(gateway.scope) if type(gateway) is PurchaseListing else None
    except Exception:  # noqa: BLE001 - fixed code only, no text leak
        scope_bound = None
    try:
        digest = canonical_digest({
            "completeness": completeness.value, "completeness_reason": c_reason,
            "correctness": correctness.value, "correctness_reason": k_reason,
            "discrepancy": discrepancy.value,
            "differences": [[d.doc_ref, d.field, d.expected, d.actual] for d in differences],
            "proof_digest": proof.digest if type(proof) is ReceiptsProof and type(proof.digest) is str else None,
            "gateway_listing_digest": _safe_digest(gateway),
            "native_listing_digest": _safe_digest(native),
            "snapshot_ref": gateway.snapshot_ref if type(gateway) is PurchaseListing else None,
            "scope": scope_bound,
            "authority": _AUTHORITY,
        })
    except Exception:  # noqa: BLE001 - fixed result, never an exception
        return _unverifiable()
    return ReceiptsAssessment(
        completeness, c_reason, correctness, k_reason, discrepancy, tuple(differences), digest,
    )
