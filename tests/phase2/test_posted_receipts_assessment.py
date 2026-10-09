"""R2-US-032 TC096 (assessment part) and TC094/TC095 negatives: three independent verdicts
(completeness / correctness / discrepancy), never collapsed; EVALUATION_ONLY authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from business_ai_gateway.phase2.posted_receipts import (
    CompletenessVerdict,
    DiscrepancyVerdict,
    RetrievalReason,
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
    a = assess_receipts(native_of(res), res)  # native == exactly what the partial listing holds
    assert a.completeness is I and a.completeness_reason == reason
    assert a.correctness is N and a.correctness_reason == "GATEWAY_LISTING_UNQUALIFIED"
    assert a.discrepancy is DiscrepancyVerdict.NOT_ASSESSABLE and a.discrepancies == ()


def test_refused_page_has_no_listing_so_everything_is_inconclusive():
    res = retriever({None: page([_forged_flag()])})[0].retrieve(request())
    a = assess_receipts(PurchaseListing(scope(), SNAP, (), True), res)
    assert a.completeness is I and a.completeness_reason == "PAGE_POSTED_FLAG_UNQUALIFIED"
    assert a.correctness is N and a.correctness_reason == "GATEWAY_LISTING_MISSING"


def _forged_flag():
    from tests.phase2._receipts_helpers import forge
    return forge(doc("a"), posted=1)


def test_refused_before_fetch_is_incomplete_inconclusive():
    res = retriever(three_pages())[0].retrieve(request(direction="SALE"))
    a = assess_receipts(PurchaseListing(scope(), SNAP, (), True), res)
    assert a.completeness is I and a.completeness_reason == "DIRECTION_NOT_RECEIPT"
    assert a.correctness is N and a.discrepancy is DiscrepancyVerdict.NOT_ASSESSABLE


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
    assert a.correctness is N and a.correctness_reason == "GATEWAY_LISTING_MISSING"


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


def test_forged_proof_or_listing_cannot_claim_complete():
    res = get(three_pages())
    bad_digest = replace(res, proof=replace(res.proof, digest="0" * 64))
    assert assess_receipts(native_of(res), bad_digest).completeness_reason == "PROOF_DIGEST_MISMATCH"
    swapped = replace(res, listing=replace(res.listing, documents=res.listing.documents[:-1]))
    a = assess_receipts(native_of(res), swapped)
    assert a.completeness is I and a.completeness_reason == "PROOF_LISTING_DIGEST_MISMATCH"
    lying = replace(res, complete=True, reason=RetrievalReason.PAGE_LIMIT_HIT)
    assert assess_receipts(native_of(res), lying).completeness is I
    other_scope = replace(res.listing, scope=PurchaseScope(
        "t", "onec-reference", COMPANY, VENDOR, FROM, datetime(2026, 9, 2, tzinfo=UTC), "MDL"))
    forged = assess_receipts(native_of(res), replace(res, listing=other_scope))
    assert forged.completeness is I


def test_assessment_never_promotes_and_has_no_capability_surface():
    res = get(three_pages())
    a = assess_receipts(native_of(res), res)
    assert a.authority == "EVALUATION_ONLY"
    assert not any(hasattr(a, n) for n in ("promote", "approved", "capability", "attested"))
