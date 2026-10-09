"""R2-US-032 TC096 (assessment part) and TC094/TC095 negatives: three independent verdicts
(completeness / correctness / discrepancy), never collapsed; EVALUATION_ONLY authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from business_ai_gateway.phase2.comparison_snapshot import canonical_digest
from business_ai_gateway.phase2.posted_receipts import (
    MAX_ROWS,
    CompletenessVerdict,
    DiscrepancyVerdict,
    RetrievalReason,
    _listing_digest,
    _proof_payload,
    assess_receipts,
)
from business_ai_gateway.phase2.purchase_reconciliation import (
    PurchaseListing,
    PurchaseResultKind,
    PurchaseScope,
)
from tests.phase2._receipts_helpers import (
    COMPANY,
    FROM,
    SNAP,
    UNTIL,
    VENDOR,
    doc,
    forge,
    page,
    request,
    retriever,
    scope,
    three_pages,
)

C, I = CompletenessVerdict, CompletenessVerdict.INCOMPLETE
M, X, N = PurchaseResultKind.MATCH, PurchaseResultKind.MISMATCH, PurchaseResultKind.INCONCLUSIVE


def get(script, **kw):
    return retriever(script)[0].retrieve(request(), **kw)


def native_of(res, *, snap=SNAP, complete=True, sc=None, mutate=None):
    docs = list(res.listing.documents)
    if mutate:
        docs = mutate(docs)
    return PurchaseListing(sc or scope(), snap, tuple(docs), complete)


def test_complete_and_match():
    res = get(three_pages())
    a = assess_receipts(native_of(res), res)
    assert (a.completeness, a.correctness, a.discrepancy) == (C.COMPLETE, M, DiscrepancyVerdict.NONE)
    assert a.discrepancies == () and a.authority == "EVALUATION_ONLY"
    assert a.completeness_reason == "PAGINATION_PROVEN_COMPLETE"
    assert a.correctness_reason == "POSTED_DOCUMENTS_EQUAL"


def test_complete_but_wrong_is_complete_plus_mismatch_with_differences_listed():
    res = get(three_pages())
    wrong = native_of(res, mutate=lambda ds: [replace(ds[0], amount=ds[0].amount + 1), *ds[1:]])
    a = assess_receipts(wrong, res)
    assert (a.completeness, a.correctness, a.discrepancy) == (C.COMPLETE, X, DiscrepancyVerdict.LISTED)
    assert [(d.doc_ref, d.field) for d in a.discrepancies] == [("d-1", "amount")]
    assert a.discrepancies[0].expected != a.discrepancies[0].actual


def test_missing_and_extra_documents_are_listed_by_presence():
    res = get(three_pages())
    native = native_of(res, mutate=lambda ds: [*ds[1:], doc("n-extra")])
    a = assess_receipts(native, res)
    assert a.correctness is X
    assert {(d.doc_ref, d.field) for d in a.discrepancies} == {
        ("d-1", "DOCUMENT_PRESENCE"), ("n-extra", "DOCUMENT_PRESENCE")}


@pytest.mark.parametrize("name", ["limit", "source_error", "snapshot", "duplicate"])
def test_partial_listing_that_would_otherwise_match_is_incomplete_and_inconclusive_never_match(name):
    # for the unreliable-source reasons the retriever surfaces no listing at all; the native side
    # below is then simply the first page's rows
    if name == "limit":
        res = get(three_pages(), max_pages=2)
        reason = "PAGE_LIMIT_HIT"
    elif name == "source_error":
        s = three_pages()
        s["tok-1"] = RuntimeError("x")
        res, reason = get(s), "SOURCE_ERROR"
    elif name == "snapshot":
        s = three_pages()
        s["tok-1"] = page([doc("d-3")], "tok-2", "snap-2", 1)
        res, reason = get(s), "SNAPSHOT_CHANGED"
    else:
        s = three_pages()
        s["tok-1"] = page([doc("d-1")], "tok-2", SNAP, 1)
        res, reason = get(s), "DUPLICATE_DOCUMENT"
    a = assess_receipts(native_of(res) if res.listing else _native_first_page(), res)
    assert a.completeness is I and a.completeness_reason == reason
    assert a.correctness is N and a.correctness_reason == "GATEWAY_NOT_PROVEN_COMPLETE"
    assert a.discrepancy is DiscrepancyVerdict.NOT_ASSESSABLE and a.discrepancies == ()


def _native_first_page():
    return PurchaseListing(scope(), SNAP, (doc("d-1"), doc("d-2", amount="10")), True)


def test_refused_page_has_no_listing_so_everything_is_inconclusive():
    res = retriever({None: page([_forged_flag()])})[0].retrieve(request())
    a = assess_receipts(PurchaseListing(scope(), SNAP, (), True), res)
    assert a.completeness is I and a.completeness_reason == "PAGE_POSTED_FLAG_UNQUALIFIED"
    assert a.correctness is N and a.correctness_reason == "GATEWAY_NOT_PROVEN_COMPLETE"


def _forged_flag():
    from tests.phase2._receipts_helpers import forge
    return forge(doc("a"), posted=1)


def test_refused_before_fetch_is_incomplete_inconclusive():
    res = retriever(three_pages())[0].retrieve(request(direction="SALE"))
    a = assess_receipts(PurchaseListing(scope(), SNAP, (), True), res)
    assert a.completeness is I and a.completeness_reason == "DIRECTION_NOT_RECEIPT"
    assert a.correctness is N and a.discrepancy is DiscrepancyVerdict.NOT_ASSESSABLE
    assert a.correctness_reason == "GATEWAY_NOT_PROVEN_COMPLETE"


def test_unqualified_native_listing_is_inconclusive_native_listing_unqualified():
    res = get(three_pages())
    a = assess_receipts(native_of(res, complete=False), res)
    assert a.completeness is C.COMPLETE  # gateway side is proven complete on its own
    assert a.correctness is N and a.correctness_reason == "NATIVE_LISTING_UNQUALIFIED"
    out = native_of(res, mutate=lambda ds: [*ds, doc("posted-out", posted=False)])
    assert assess_receipts(out, res).correctness_reason == "NATIVE_LISTING_UNQUALIFIED"


@pytest.mark.parametrize("junk", [None, "native", 5, object(), {}])
def test_non_listing_native_is_unqualified_never_raised(junk):
    res = get(three_pages())
    a = assess_receipts(junk, res)
    assert a.correctness is N and a.correctness_reason == "NATIVE_LISTING_UNQUALIFIED"
    assert a.completeness is C.COMPLETE


@pytest.mark.parametrize("junk", [None, "result", 5, object()])
def test_non_result_is_incomplete_and_inconclusive_never_raised(junk):
    res = get(three_pages())
    a = assess_receipts(native_of(res), junk)
    assert a.completeness is I and a.completeness_reason == "RESULT_INVALID"
    assert a.correctness is N and a.correctness_reason == "GATEWAY_NOT_PROVEN_COMPLETE"


def test_scope_mismatch_and_snapshot_mismatch_propagate_as_inconclusive():
    res = get(three_pages())
    other = PurchaseScope("t", "onec-reference", COMPANY, VENDOR, FROM, UNTIL, "EUR")
    a = assess_receipts(PurchaseListing(other, SNAP, (), True), res)
    assert a.correctness is N and a.correctness_reason == "PURCHASE_SCOPE_MISMATCH"
    assert a.completeness is C.COMPLETE  # completeness is independent of the native side
    a = assess_receipts(native_of(res, snap="snap-other"), res)
    assert a.correctness is N and a.correctness_reason == "PURCHASE_SNAPSHOT_MISMATCH"
    assert a.completeness is C.COMPLETE


def test_verdicts_are_independent_flipping_one_input_flips_only_its_verdict():
    res = get(three_pages())
    base = assess_receipts(native_of(res), res)
    # flip correctness only: a changed native amount
    wrong = assess_receipts(native_of(res, mutate=lambda d: [replace(d[0], amount=d[0].amount + 1),
                                                             *d[1:]]), res)
    assert (wrong.completeness, wrong.correctness) == (base.completeness, X)
    assert base.correctness is M
    # flip completeness only: truncate the chain, keep native untouched -> correctness degrades
    # because compare refuses an incomplete gateway; completeness flips independently of native
    partial = get(three_pages(), max_pages=2)
    flipped = assess_receipts(native_of(res), partial)
    assert flipped.completeness is I and base.completeness is C.COMPLETE
    # same native side, same correctness input class: native flip leaves completeness alone
    again = assess_receipts(native_of(res, complete=False), res)
    assert again.completeness is base.completeness and again.correctness is not base.correctness
    assert len({base.digest, wrong.digest, flipped.digest, again.digest}) == 4


def test_assessment_is_deterministic_and_frozen():
    res = get(three_pages())
    a, b = assess_receipts(native_of(res), res), assess_receipts(native_of(res), res)
    assert a == b and a.digest == b.digest and len(a.digest) == 64
    with pytest.raises(AttributeError):
        a.completeness = I


def reseal(res, *, listing=None, **proof_changes):
    """A forged result whose listing digest and proof digest are recomputed consistently."""
    listing = listing if listing is not None else res.listing
    proof = replace(res.proof, listing_digest=_listing_digest(listing), **proof_changes)
    proof = replace(proof, digest=canonical_digest(_proof_payload(proof)))
    return replace(res, listing=listing, proof=proof)


def _forged_verdict(res, forged):
    a = assess_receipts(native_of(res), forged)
    # a forged result must never show MATCH / NONE
    assert a.completeness is I and a.correctness is N
    assert a.correctness_reason == "GATEWAY_NOT_PROVEN_COMPLETE"
    assert a.discrepancy is DiscrepancyVerdict.NOT_ASSESSABLE and a.discrepancies == ()
    return a.completeness_reason


def test_forged_proof_or_listing_cannot_claim_complete():
    res = get(three_pages())
    bad_digest = replace(res, proof=replace(res.proof, digest="0" * 64))
    assert _forged_verdict(res, bad_digest) == "PROOF_DIGEST_MISMATCH"
    swapped = replace(res, listing=replace(res.listing, documents=res.listing.documents[:-1]))
    assert _forged_verdict(res, swapped) == "PROOF_LISTING_DIGEST_MISMATCH"
    lying = replace(res, complete=True, reason=RetrievalReason.PAGE_LIMIT_HIT)
    assert _forged_verdict(res, lying) == "PAGE_LIMIT_HIT"
    other_scope = replace(res.listing, scope=PurchaseScope(
        "t", "onec-reference", COMPANY, VENDOR, FROM, datetime(2026, 9, 2, tzinfo=UTC), "MDL"))
    assert _forged_verdict(res, replace(res, listing=other_scope)) == "PROOF_LISTING_DIGEST_MISMATCH"


@pytest.mark.parametrize("field", [
    "company_ref", "counterparty_ref", "currency", "source_id", "tenant_id", "from_inclusive",
    "until_exclusive", "snapshot_ref"])
def test_consistently_resealed_forgery_with_a_different_scope_is_a_scope_mismatch(field):
    # the listing is changed in exactly one of the eight proof-bound fields; the listing digest and
    # the proof digest are recomputed, so only the proof-vs-listing scope cross-check can fire
    res = get(three_pages())
    changed = {
        "company_ref": "other-co", "counterparty_ref": "OTHER-VENDOR", "currency": "EUR",
        "source_id": "other-source", "tenant_id": "other-tenant",
        "from_inclusive": datetime(2026, 8, 2, tzinfo=UTC),
        "until_exclusive": datetime(2026, 9, 2, tzinfo=UTC), "snapshot_ref": "snap-other",
    }[field]
    if field == "snapshot_ref":
        other = replace(res.listing, snapshot_ref=changed)
    else:
        other = replace(res.listing, scope=replace(res.listing.scope, **{field: changed}))
    forged = reseal(res, listing=other)
    assert forged.proof.listing_digest == _listing_digest(other)  # digests are consistent
    assert _forged_verdict(res, forged) == "PROOF_SCOPE_MISMATCH"


def test_consistently_resealed_forgery_with_an_out_of_scope_row_is_refused():
    res = get(three_pages())
    for extra in (doc("x-1", company="other-co"), doc("x-2", posted=False), doc("x-3", deleted=True),
                  doc("x-4", currency="EUR"), doc("x-5", vendor="OTHER")):
        listing = replace(res.listing, documents=(*res.listing.documents, extra))
        forged = reseal(res, listing=listing, kept_count=res.proof.kept_count + 1,
                        rows_seen=res.proof.rows_seen + 1)
        assert _forged_verdict(res, forged) == "DOCUMENT_OUT_OF_SCOPE"


def test_consistently_resealed_forgery_with_a_malformed_row_is_refused():
    res = get(three_pages())
    bad = forge(doc("x-1"), posted=1)
    listing = replace(res.listing, documents=(*res.listing.documents, bad))
    forged = reseal(res, listing=listing, kept_count=res.proof.kept_count + 1,
                    rows_seen=res.proof.rows_seen + 1)
    assert _forged_verdict(res, forged) == "PROOF_ROW_INVALID"


def _exclusions(**counts):
    names = ("WRONG_DIRECTION", "UNPOSTED", "DELETED", "WRONG_COMPANY", "WRONG_COUNTERPARTY",
             "WRONG_CURRENCY", "OUT_OF_PERIOD")
    return tuple((n, counts.get(n, 0)) for n in names)


@pytest.mark.parametrize("changes", [
    {"direction": "SALE"},
    {"direction": "receipt"},
    {"reason": "PAGE_LIMIT_HIT"},
    {"kept_count": 3},
    # sums are internally consistent (rows_seen == kept + exclusions) but the listing holds 4
    # documents: only the `kept_count != len(docs)` guard can fire
    {"kept_count": 3, "rows_seen": 3},
    {"rows_seen": 5},  # rows_seen != kept + exclusions
    {"rows_seen": MAX_ROWS + 1, "exclusions": _exclusions(UNPOSTED=MAX_ROWS - 3)},
    {"exclusions": _exclusions(UNPOSTED=1), "rows_seen": 4},  # sum(exclusions) mismatch
    {"exclusions": _exclusions(UNPOSTED=-1), "rows_seen": 3},
    {"exclusions": _exclusions()[:-1]},
    {"pages_fetched": 2},  # != len(page_tokens)
    {"pages_fetched": 0, "page_tokens": ()},
    {"page_tokens": ("tok-0", "tok-1", "tok-2")},  # first token must be None
    {"page_tokens": (None, "tok-1", "tok-1")},  # repeated token
    {"page_tokens": (None, "tok-1", "")},  # blank token
    {"page_tokens": [None, "tok-1", "tok-2"]},  # not a tuple
    {"page_tokens": (None,) * 1 + tuple(f"t{i}" for i in range(100)), "pages_fetched": 101},
], ids=["dir_sale", "dir_lower", "reason", "kept_count", "kept_len_only", "rows_seen", "rows_over_max",
        "excl_sum", "excl_negative", "excl_short", "pages_mismatch", "pages_zero", "first_token",
        "repeat_token", "blank_token", "tokens_list", "pages_over_max"])
def test_consistently_resealed_forgery_with_inconsistent_proof_content_is_refused(changes):
    res = get(three_pages())
    assert _forged_verdict(res, reseal(res, **changes)) == "PROOF_CONTENT_INCONSISTENT"


def _forge_listing(base: PurchaseListing, **changes) -> PurchaseListing:
    out = object.__new__(PurchaseListing)  # bypasses the duplicate-ref constructor validation
    for name in PurchaseListing.__slots__:
        object.__setattr__(out, name, changes.get(name, getattr(base, name)))
    return out


def test_consistently_resealed_forgery_with_a_duplicate_doc_ref_is_refused():
    res = get(three_pages())
    docs = (*res.listing.documents, res.listing.documents[0])
    listing = _forge_listing(res.listing, documents=docs)
    assert len(docs) == 5 and len({d.doc_ref for d in docs}) == 4
    # kept_count/rows_seen match len(docs), so every other proof-content guard passes
    forged = reseal(res, listing=listing, kept_count=5, rows_seen=5)
    assert _forged_verdict(res, forged) == "PROOF_CONTENT_INCONSISTENT"


def test_a_listing_with_a_duplicate_doc_ref_cannot_even_be_constructed():
    res = get(three_pages())
    with pytest.raises(ValueError, match="DUPLICATE_PURCHASE_REF"):
        replace(res.listing, documents=(*res.listing.documents, res.listing.documents[0]))


def test_genuine_result_passes_the_content_cross_checks():
    res = get(three_pages())
    assert assess_receipts(native_of(res), res).completeness is C.COMPLETE
    sale_excluded = get({None: page([doc("a"), doc("s")], kinds=("RECEIPT", "SALE"))})
    assert assess_receipts(native_of(sale_excluded), sale_excluded).completeness is C.COMPLETE


# -- the assessment digest binds proof / listings / snapshot / scope -------------------------------
def test_assessment_digest_binds_the_proof_digest():
    base = get(three_pages())
    s = three_pages()
    s[None] = page(s[None].documents, "tok-A", SNAP, 0)
    s["tok-A"] = s.pop("tok-1")  # same rows, same listing, different page tokens
    alt = get(s)
    assert alt.listing == base.listing and alt.proof.digest != base.proof.digest
    a, b = assess_receipts(native_of(base), base), assess_receipts(native_of(alt), alt)
    assert (a.completeness, a.correctness, a.discrepancy) == (b.completeness, b.correctness,
                                                              b.discrepancy)
    assert a.digest != b.digest


def test_assessment_digest_binds_the_native_listing_digest():
    res = get(three_pages())
    a = assess_receipts(native_of(res), res)
    wrong = assess_receipts(native_of(res, mutate=lambda d: [replace(d[0], amount=d[0].amount + 1),
                                                             *d[1:]]), res)
    assert wrong.digest != a.digest
    # same verdicts and no listed differences, only the native snapshot differs -> still distinct
    snap = assess_receipts(native_of(res, snap="snap-other"), res)
    assert snap.correctness is N and snap.digest not in {a.digest, wrong.digest}


def test_assessment_digest_binds_snapshot_ref_and_scope_of_the_gateway_listing():
    base = get(three_pages())
    other_snap = get(three_pages(snap="snap-2"))
    a = assess_receipts(native_of(base), base)
    b = assess_receipts(native_of(other_snap, snap="snap-2"), other_snap)
    assert (a.correctness, b.correctness) == (M, M) and a.digest != b.digest
    r2, _ = retriever(three_pages())
    shifted = PurchaseScope("t", "onec-reference", COMPANY, VENDOR, FROM,
                            datetime(2026, 9, 2, tzinfo=UTC), "MDL")
    c = r2.retrieve(request(sc=shifted))
    assert assess_receipts(native_of(c, sc=shifted), c).digest != a.digest


def test_assessment_never_promotes_and_has_no_capability_surface():
    res = get(three_pages())
    a = assess_receipts(native_of(res), res)
    assert a.authority == "EVALUATION_ONLY"
    assert not any(hasattr(a, n) for n in ("promote", "approved", "capability", "attested"))
