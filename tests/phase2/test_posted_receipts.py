"""R2-US-032 TC094/TC095: posted receipts retrieval - identity/company/Posted rules, exclusions,
refusals before any fetch and hostile rows. Pure fixtures; no I/O."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.posted_receipts import (
    Direction,
    ExclusionReason,
    PostedReceiptsRetriever,
    ReceiptsRequest,
    RetrievalReason,
)
from business_ai_gateway.phase2.purchase_reconciliation import (
    PurchaseListing,
    PurchaseResultKind,
    compare_posted_purchases,
)
from tests.phase2._receipts_helpers import (
    COMPANY,
    FROM,
    SNAP,
    UNTIL,
    VENDOR,
    FakeSource,
    doc,
    forge,
    forge_scope,
    page,
    request,
    resolver,
    retriever,
    scope,
)

HOSTILE = "EVIL\u200b<script>'; DROP TABLE x;--"


def counts(result):
    return dict(result.proof.exclusions)


# -- TC094: identity / company / Posted ------------------------------------------------------------
def test_tc094_only_requested_company_and_counterparty_returned_identity_round_trips():
    mine = doc("d-1", number="150", amount="41.20")
    rows = [
        mine,
        doc("d-2", company="OTHER-CO"),
        doc("d-3", vendor="OTHER-VENDOR"),
        doc("d-1x", company="OTHER-CO", number="150"),  # same number, other company
    ]
    r, src = retriever({None: page(rows)})
    res = r.retrieve(request())
    assert res.complete is True and res.reason is RetrievalReason.OK
    assert res.listing.documents == (mine,)  # every identity field round-trips exactly
    d = res.listing.documents[0]
    assert (d.doc_ref, d.company_ref, d.counterparty_ref, d.number, d.amount) == (
        "d-1", COMPANY, VENDOR, "150", Decimal("41.20"))
    assert counts(res)[ExclusionReason.WRONG_COMPANY] == 2
    assert counts(res)[ExclusionReason.WRONG_COUNTERPARTY] == 1
    assert res.authority == "EVALUATION_ONLY"
    assert src.calls == [(scope(), None)]


def test_tc094_posted_document_with_right_company_is_kept_and_listing_feeds_the_comparison():
    docs = [doc("d-1"), doc("d-2", amount="3")]
    r, _ = retriever({None: page(docs)})
    res = r.retrieve(request())
    native = PurchaseListing(scope(), SNAP, tuple(docs), True)
    cmp = compare_posted_purchases(native, res.listing)
    assert cmp.state is PurchaseResultKind.MATCH


def test_listing_is_sorted_by_doc_ref_regardless_of_source_order():
    r, _ = retriever({None: page([doc("b"), doc("a"), doc("c")])})
    assert [d.doc_ref for d in r.retrieve(request()).listing.documents] == ["a", "b", "c"]


# -- TC095: exclusions -----------------------------------------------------------------------------
def test_tc095_each_exclusion_counted_under_its_own_reason_and_never_listed():
    rows = [
        doc("keep"),
        doc("unposted", posted=False),
        doc("deleted", deleted=True),
        doc("company", company="OTHER"),
        doc("vendor", vendor="OTHER"),
        doc("currency", currency="EUR"),
        doc("before", at=datetime(2026, 7, 31, 23, 59, 59, tzinfo=FROM.tzinfo)),
        doc("until", at=UNTIL),  # [from, until): the upper bound is excluded
    ]
    r, _ = retriever({None: page(rows)})
    res = r.retrieve(request())
    assert [d.doc_ref for d in res.listing.documents] == ["keep"]
    c = counts(res)
    assert c == {
        "UNPOSTED": 1, "DELETED": 1, "WRONG_COMPANY": 1, "WRONG_COUNTERPARTY": 1,
        "WRONG_CURRENCY": 1, "OUT_OF_PERIOD": 2,
    }
    assert res.proof.rows_seen == 8 and res.proof.kept_count == 1
    assert sum(c.values()) + res.proof.kept_count == res.proof.rows_seen  # nothing dropped silently


def test_tc095_lower_bound_is_inclusive_and_excluded_amounts_are_not_in_the_listing():
    r, _ = retriever({None: page([doc("lo", at=FROM, amount="1"), doc("bad", posted=False,
                                                                      amount="999")])})
    res = r.retrieve(request())
    assert [d.doc_ref for d in res.listing.documents] == ["lo"]
    assert sum(d.amount for d in res.listing.documents) == Decimal(1)


def test_tc095_precedence_is_deterministic_one_reason_per_document():
    both = doc("x", posted=False, deleted=True)
    wrong = doc("y", company="OTHER", posted=False, deleted=True, currency="EUR")
    res = retriever({None: page([both, wrong])})[0].retrieve(request())
    assert counts(res)["DELETED"] == 1 and counts(res)["UNPOSTED"] == 0
    assert counts(res)["WRONG_COMPANY"] == 1 and counts(res)["WRONG_CURRENCY"] == 0


def test_all_six_reasons_always_present_in_the_proof_even_when_zero():
    res = retriever({None: page([doc("a")])})[0].retrieve(request())
    assert [k for k, _ in res.proof.exclusions] == [e.value for e in (
        ExclusionReason.UNPOSTED, ExclusionReason.DELETED, ExclusionReason.WRONG_COMPANY,
        ExclusionReason.WRONG_COUNTERPARTY, ExclusionReason.WRONG_CURRENCY,
        ExclusionReason.OUT_OF_PERIOD)]
    assert all(v == 0 for _, v in res.proof.exclusions)


def test_all_rows_excluded_is_an_empty_complete_listing_that_proves_nothing_downstream():
    res = retriever({None: page([doc("a", posted=False)])})[0].retrieve(request())
    assert res.complete is True and res.listing.documents == ()
    native = PurchaseListing(scope(), SNAP, (), True)
    assert compare_posted_purchases(native, res.listing).reason_code == (
        "PURCHASE_BOTH_LISTINGS_EMPTY")


# -- hostile rows refuse the page ------------------------------------------------------------------
@pytest.mark.parametrize("changes,reason", [
    ({"doc_ref": ""}, RetrievalReason.PAGE_IDENTITY_INVALID),
    ({"doc_ref": "   "}, RetrievalReason.PAGE_IDENTITY_INVALID),
    ({"doc_ref": "d\u200b-1"}, RetrievalReason.PAGE_IDENTITY_INVALID),  # zero-width: ambiguous
    ({"doc_ref": "d-1 "}, RetrievalReason.PAGE_IDENTITY_INVALID),  # never repaired
    ({"company_ref": "818АA"}, RetrievalReason.PAGE_IDENTITY_INVALID),  # mixed scripts
    ({"counterparty_ref": None}, RetrievalReason.PAGE_IDENTITY_INVALID),
    ({"contract_ref": ""}, RetrievalReason.PAGE_IDENTITY_INVALID),
    ({"number": 150}, RetrievalReason.PAGE_IDENTITY_INVALID),
    ({"posted": 1}, RetrievalReason.PAGE_POSTED_FLAG_UNQUALIFIED),
    ({"posted": None}, RetrievalReason.PAGE_POSTED_FLAG_UNQUALIFIED),
    ({"deletion_mark": "False"}, RetrievalReason.PAGE_POSTED_FLAG_UNQUALIFIED),
    ({"occurred_at": datetime(2026, 8, 5)}, RetrievalReason.PAGE_ROW_INVALID),  # noqa: DTZ001
    ({"occurred_at": "2026-08-05"}, RetrievalReason.PAGE_ROW_INVALID),
    ({"amount": Decimal("NaN")}, RetrievalReason.PAGE_ROW_INVALID),
    ({"amount": Decimal("Infinity")}, RetrievalReason.PAGE_ROW_INVALID),
    ({"amount": 41.2}, RetrievalReason.PAGE_ROW_INVALID),  # float never accepted
    ({"amount": Decimal("1E+500")}, RetrievalReason.PAGE_ROW_INVALID),
])
def test_bad_row_refuses_the_whole_page_and_surfaces_no_listing(changes, reason):
    rows = [doc("good"), forge(doc("bad"), **changes)]
    res = retriever({None: page(rows)})[0].retrieve(request())
    assert res.reason is reason and res.complete is False
    assert res.listing is None  # the good row is not surfaced from an unreliable page
    assert res.proof is not None and res.proof.complete is False
    assert res.proof.reason == reason.value


def test_non_document_row_and_malformed_page_are_refused_not_raised():
    for bad in ([object()], [None], [{"doc_ref": "x"}]):
        res = retriever({None: page(bad)})[0].retrieve(request())
        assert res.reason is RetrievalReason.PAGE_IDENTITY_INVALID and res.listing is None
    for bad_page in (None, "page", {"documents": ()}, 5):
        res = retriever({None: bad_page})[0].retrieve(request())
        assert res.reason is RetrievalReason.PAGE_INVALID and res.complete is False


def test_hostile_next_token_and_snapshot_are_refused():
    res = retriever({None: page([doc("a")], nxt="\u200b")})[0].retrieve(request())
    assert res.reason is RetrievalReason.TOKEN_MISSING
    res = retriever({None: page([doc("a")], snap="")})[0].retrieve(request())
    assert res.reason is RetrievalReason.SNAPSHOT_REF_INVALID and res.listing is None
    res = retriever({None: page([doc("a")], snap=None)})[0].retrieve(request())
    assert res.reason is RetrievalReason.SNAPSHOT_REF_INVALID


# -- refused before any fetch ----------------------------------------------------------------------
@pytest.mark.parametrize("direction", [Direction.SALE, "SALE", "receipt", "RECEIPT ", None, 1, ""])
def test_wrong_direction_refused_before_any_fetch(direction):
    r, src = retriever({None: page([doc("a")])})
    res = r.retrieve(request(direction=direction))
    assert res.reason is RetrievalReason.DIRECTION_NOT_RECEIPT
    assert res.complete is False and res.listing is None and res.proof is None
    assert src.calls == []


@pytest.mark.parametrize("currency", ["mdl", "MDLX", "MD", "M1L", "", " MDL", "\u041cDL", "M\u200bDL"])
def test_malformed_currency_refused_before_any_fetch(currency):
    r, src = retriever({None: page([doc("a")])})
    res = r.retrieve(request(sc=forge_scope(scope(), currency=currency)))
    assert res.reason is RetrievalReason.CURRENCY_INVALID
    assert src.calls == []


def test_wrong_period_refused_before_any_fetch():
    r, src = retriever({None: page([doc("a")])})
    for bad in (
        forge_scope(scope(), from_inclusive=UNTIL, until_exclusive=FROM),
        forge_scope(scope(), from_inclusive=FROM, until_exclusive=FROM),
        forge_scope(scope(), from_inclusive=datetime(2026, 8, 1)),  # noqa: DTZ001
        forge_scope(scope(), until_exclusive="2026-09-01"),
    ):
        assert r.retrieve(request(sc=bad)).reason is RetrievalReason.PERIOD_INVALID
    assert src.calls == []


def test_scope_identity_must_be_strict_before_any_fetch():
    r, src = retriever({None: page([doc("a")])})
    for field in ("tenant_id", "source_id", "company_ref", "counterparty_ref"):
        for bad in ("", " x", "x\u200b", None, 7):
            res = r.retrieve(request(sc=forge_scope(scope(), **{field: bad})))
            assert res.reason is RetrievalReason.SCOPE_INVALID
    assert src.calls == []


@pytest.mark.parametrize("junk", [None, "request", 5, object(), {"scope": scope()}])
def test_non_request_is_refused_never_raised(junk):
    r, src = retriever({None: page([doc("a")])})
    res = r.retrieve(junk)
    assert res.reason is RetrievalReason.REQUEST_INVALID and res.proof is None
    assert src.calls == []


def test_request_with_non_scope_is_refused():
    r, src = retriever({None: page([doc("a")])})
    res = r.retrieve(ReceiptsRequest("scope", Direction.RECEIPT, None))
    assert res.reason is RetrievalReason.SCOPE_INVALID and src.calls == []


@pytest.mark.parametrize("kw", [
    {"max_pages": 0}, {"max_pages": -1}, {"max_pages": 101}, {"max_pages": True},
    {"max_rows": 0}, {"max_rows": 10_001}, {"max_rows": "5"}, {"max_pages": 1.5},
])
def test_bounds_must_be_within_hard_limits(kw):
    r, src = retriever({None: page([doc("a")])})
    assert r.retrieve(request(), **kw).reason is RetrievalReason.BOUNDS_INVALID
    assert src.calls == []


def test_bad_collaborators_are_refused_not_raised():
    res = PostedReceiptsRetriever(object(), resolver()).retrieve(request())
    assert res.reason is RetrievalReason.SOURCE_INVALID
    res = PostedReceiptsRetriever(FakeSource({None: page([])}), object()).retrieve(request())
    assert res.reason is RetrievalReason.RESOLVER_INVALID


def test_reason_codes_never_echo_caller_input():
    r, src = retriever({None: page([doc("a")])})
    attempts = [
        request(direction=HOSTILE),
        request(sc=forge_scope(scope(), currency=HOSTILE)),
        request(sc=forge_scope(scope(), company_ref=HOSTILE)),
        request(name=HOSTILE, ref=None),
        r.retrieve(HOSTILE),
    ]
    for att in attempts:
        res = att if hasattr(att, "reason") else r.retrieve(att)
        assert HOSTILE not in repr(res.reason) and HOSTILE not in str(res.reason.value)
    assert src.calls == []


def test_source_exception_text_is_not_echoed():
    r, _ = retriever({None: RuntimeError(HOSTILE)})
    res = r.retrieve(request())
    assert res.reason is RetrievalReason.SOURCE_ERROR
    assert HOSTILE not in repr(res)


def test_retrieval_is_read_only_scope_passed_unchanged_and_result_frozen():
    r, src = retriever({None: page([doc("a")])})
    sc = scope()
    res = r.retrieve(request(sc=sc))
    assert src.calls[0][0] is sc
    with pytest.raises(AttributeError):
        res.complete = False  # frozen
