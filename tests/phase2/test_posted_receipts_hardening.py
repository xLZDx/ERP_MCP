"""Same-root-cause hardening of posted receipts / purchase reconciliation: NFKC identity text, the
empty 1C reference as a snapshot, exact-type comparison input, single-read UTC copies, forged
result objects and GUID spelling keys."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.posted_receipts import (
    CompletenessVerdict,
    ReceiptsProof,
    RetrievalReason,
    RetrievalResult,
    _native_ok,
    _ref_key,
    assess_receipts,
)
from business_ai_gateway.phase2.purchase_reconciliation import (
    PurchaseDocument,
    PurchaseListing,
    PurchaseResultKind,
    PurchaseScope,
    compare_posted_purchases,
)
from tests.phase2._receipts_helpers import (
    FROM,
    INSIDE,
    SNAP,
    UNTIL,
    doc,
    forge,
    forge_scope,
    page,
    request,
    retriever,
    scope,
    three_pages,
)

GUID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
ZERO = "00000000-0000-0000-0000-000000000000"


def fullwidth(text: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c for c in text)


def get(script, **kw):
    return retriever(script)[0].retrieve(request(), **kw)


# -- (1) NFKC identity text -------------------------------------------------------------------------
@pytest.mark.parametrize("field", ["doc_ref", "company_ref", "counterparty_ref", "contract_ref"])
@pytest.mark.parametrize("value", [fullwidth(GUID), fullwidth(ZERO)])
def test_fullwidth_guid_spelling_in_a_row_is_refused(field, value):
    bad = forge(doc("d-1"), **{field: value})
    res = get({None: page([bad])})
    assert res.reason is RetrievalReason.PAGE_IDENTITY_INVALID and res.listing is None


def test_fullwidth_zero_guid_scope_is_refused():
    res = retriever({None: page([doc()])})[0].retrieve(
        request(sc=scope(company=fullwidth(ZERO))))
    assert res.reason is RetrievalReason.SCOPE_INVALID


def test_fullwidth_guid_dedupes_with_ascii_guid_key():
    assert _ref_key(fullwidth(GUID.upper())) == _ref_key(GUID)


# -- (2) snapshot_ref equal to the empty 1C reference -----------------------------------------------
@pytest.mark.parametrize("snap", [ZERO, "{" + ZERO + "}", fullwidth(ZERO)])
def test_empty_reference_snapshot_is_refused_on_a_page(snap):
    res = get({None: page([doc()], None, snap, 0)})
    assert res.reason is RetrievalReason.SNAPSHOT_REF_INVALID and res.listing is None


def test_listing_with_empty_reference_snapshot_cannot_be_built():
    with pytest.raises(ValueError):
        PurchaseListing(scope(), ZERO, (doc(),), True)


def test_two_listings_with_the_zero_guid_snapshot_are_not_the_same_snapshot():
    a = forge_listing(snapshot_ref=ZERO)
    r = compare_posted_purchases(a, a)
    assert r.state is PurchaseResultKind.INCONCLUSIVE


def forge_listing(**changes) -> PurchaseListing:
    base = PurchaseListing(scope(), SNAP, (doc(),), True)
    out = object.__new__(PurchaseListing)
    for name in PurchaseListing.__slots__:
        object.__setattr__(out, name, changes.get(name, getattr(base, name)))
    return out


def test_native_and_complete_checks_refuse_zero_snapshot():
    res = get(three_pages())
    assert _native_ok(forge_listing(snapshot_ref=ZERO)) is False
    bad_listing = forge_listing(snapshot_ref=ZERO, documents=res.listing.documents)
    forged = RetrievalResult(True, RetrievalReason.OK, bad_listing, res.proof)
    a = assess_receipts(res.listing, forged)
    assert a.completeness is CompletenessVerdict.INCOMPLETE


# -- (4) compare_posted_purchases never trusts caller objects ---------------------------------------
class LyingStr(str):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


class LyingDatetime(datetime):
    def __lt__(self, other):
        return True

    def __le__(self, other):
        return True

    def __ge__(self, other):
        return True

    def __gt__(self, other):
        return True

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = datetime.__hash__


def test_str_subclass_scope_cannot_produce_match():
    good = PurchaseListing(scope(), SNAP, (doc(),), True)
    liar = forge_listing(scope=forge_scope(scope(), company_ref=LyingStr("other")))
    r = compare_posted_purchases(good, liar)
    assert r.state is PurchaseResultKind.INCONCLUSIVE


def test_str_subclass_snapshot_cannot_produce_match():
    good = PurchaseListing(scope(), SNAP, (doc(),), True)
    r = compare_posted_purchases(good, forge_listing(snapshot_ref=LyingStr("zzz")))
    assert r.state is PurchaseResultKind.INCONCLUSIVE


def test_datetime_subclass_in_a_row_cannot_produce_match():
    good = PurchaseListing(scope(), SNAP, (doc(),), True)
    lie = LyingDatetime(2030, 1, 1, tzinfo=UTC)
    bad = forge_listing(documents=(forge(doc(), occurred_at=lie),))
    r = compare_posted_purchases(good, bad)
    assert r.state is PurchaseResultKind.INCONCLUSIVE


def test_complete_must_be_exactly_true_even_with_a_lying_truthy_object():
    good = PurchaseListing(scope(), SNAP, (doc(),), True)
    r = compare_posted_purchases(good, forge_listing(complete=LyingStr("x")))
    assert r.state is PurchaseResultKind.INCONCLUSIVE


@pytest.mark.parametrize("hostile", [None, object(), 5, "x"])
@pytest.mark.parametrize("side", ["native", "gateway"])
def test_hostile_non_listing_arguments_return_a_fixed_code(hostile, side):
    good = PurchaseListing(scope(), SNAP, (doc(),), True)
    args = (hostile, good) if side == "native" else (good, hostile)
    r = compare_posted_purchases(*args)
    assert r.state is PurchaseResultKind.INCONCLUSIVE and r.reason_code == "PURCHASE_INPUT_INVALID"


def test_unset_slots_listing_returns_a_fixed_code():
    good = PurchaseListing(scope(), SNAP, (doc(),), True)
    r = compare_posted_purchases(good, object.__new__(PurchaseListing))
    assert r.state is PurchaseResultKind.INCONCLUSIVE and r.reason_code == "PURCHASE_INPUT_INVALID"


def test_constructors_reject_subclass_inputs():
    with pytest.raises(ValueError):
        PurchaseScope("t", "s", LyingStr("c"), "v", FROM, UNTIL, "MDL")
    with pytest.raises(ValueError):
        PurchaseScope("t", "s", "c", "v", LyingDatetime(2026, 1, 1, tzinfo=UTC), UNTIL, "MDL")
    with pytest.raises(ValueError):
        PurchaseDocument("d", "c", "v", "k", "1", LyingDatetime(2026, 8, 5, tzinfo=UTC),
                         Decimal(1), "MDL", True, False)


# -- (5) tzinfo: one read, frozen plain UTC copies ----------------------------------------------------
class FlakyTz(tzinfo):
    """Returns a different offset on every call."""

    def __init__(self):
        self.n = 0

    def utcoffset(self, dt):
        self.n += 1
        return timedelta(hours=self.n)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "flaky"


def _plain_utc(value):
    return type(value) is datetime and value.tzinfo is UTC


def test_ingest_carries_plain_utc_copies_even_for_a_custom_tzinfo():
    flaky = datetime(2026, 8, 15, tzinfo=FlakyTz())
    bad = forge(doc("d-1"), occurred_at=flaky)
    sc = forge_scope(scope(), from_inclusive=datetime(2026, 8, 1, tzinfo=FlakyTz()),
                     until_exclusive=datetime(2026, 9, 1, 5, tzinfo=FlakyTz()))
    res = retriever({None: page([bad])})[0].retrieve(request(sc=sc))
    if res.listing is not None:
        assert all(_plain_utc(d.occurred_at) for d in res.listing.documents)
        assert _plain_utc(res.listing.scope.from_inclusive)
        assert _plain_utc(res.listing.scope.until_exclusive)
        assert _plain_utc(res.proof.from_inclusive)
    else:
        assert res.reason in (RetrievalReason.SCOPE_INVALID, RetrievalReason.PAGE_ROW_INVALID)


def test_non_utc_offsets_are_normalised_once_and_equal_to_the_utc_instant():
    plus3 = timezone_plus(3)
    d = doc("d-1", at=datetime(2026, 8, 15, 3, tzinfo=plus3))
    res = get({None: page([d])})
    assert res.complete is True
    assert all(_plain_utc(x.occurred_at) for x in res.listing.documents)
    assert res.listing.documents[0].occurred_at == INSIDE


def timezone_plus(hours):
    from datetime import timezone
    return timezone(timedelta(hours=hours))


def test_constructor_normalises_to_plain_utc():
    d = doc("d-1", at=datetime(2026, 8, 15, 3, tzinfo=timezone_plus(3)))
    assert _plain_utc(d.occurred_at) and d.occurred_at == INSIDE
    s = PurchaseScope("t", "s", "c", "v", FROM.astimezone(timezone_plus(2)), UNTIL, "MDL")
    assert _plain_utc(s.from_inclusive)


# -- (6) forged result objects ----------------------------------------------------------------------
def _unverifiable(a):
    return (a.completeness is CompletenessVerdict.INCOMPLETE
            and a.completeness_reason == "ASSESSMENT_UNVERIFIABLE"
            and a.correctness is PurchaseResultKind.INCONCLUSIVE)


@pytest.mark.parametrize("which", ["result", "proof", "listing"])
def test_unset_slot_objects_give_the_fixed_unverifiable_assessment(which):
    res = get(three_pages())
    if which == "result":
        forged = object.__new__(RetrievalResult)
    elif which == "proof":
        forged = RetrievalResult(True, RetrievalReason.OK, res.listing, object.__new__(ReceiptsProof))
    else:
        forged = RetrievalResult(True, RetrievalReason.OK, object.__new__(PurchaseListing), res.proof)
    a = assess_receipts(res.listing, forged)
    assert a.completeness is CompletenessVerdict.INCOMPLETE
    assert a.correctness is PurchaseResultKind.INCONCLUSIVE
    if which == "result":
        assert _unverifiable(a)


def test_unset_slot_native_listing_is_unqualified_not_an_exception():
    res = get(three_pages())
    a = assess_receipts(object.__new__(PurchaseListing), res)
    assert a.correctness is PurchaseResultKind.INCONCLUSIVE


# -- (8) GUID spelling keys --------------------------------------------------------------------------
def test_constructor_refuses_two_spellings_of_one_guid():
    with pytest.raises(ValueError, match="DUPLICATE_PURCHASE_REF"):
        PurchaseListing(scope(), SNAP, (doc(GUID.upper()), doc("{" + GUID + "}")), True)


def test_compare_refuses_a_forged_listing_with_two_spellings_of_one_guid():
    good = PurchaseListing(scope(), SNAP, (doc(GUID),), True)
    dup = forge_listing(documents=(doc(GUID.upper()), doc("{" + GUID + "}")))
    r = compare_posted_purchases(good, dup)
    assert r.state is PurchaseResultKind.INCONCLUSIVE and r.reason_code == "PURCHASE_INPUT_INVALID"
    assert _native_ok(dup) is False


def test_same_guid_in_a_different_spelling_is_the_same_document():
    a = PurchaseListing(scope(), SNAP, (doc(GUID),), True)
    b = PurchaseListing(scope(), SNAP, (doc("{" + GUID.upper() + "}"),), True)
    r = compare_posted_purchases(a, b)
    assert r.state is PurchaseResultKind.MATCH


def test_scope_refs_compare_by_canonical_form():
    co_a, co_b = GUID, "{" + GUID.upper() + "}"
    a = PurchaseListing(scope(company=co_a), SNAP, (doc(company=co_a),), True)
    b = PurchaseListing(scope(company=co_b), SNAP, (doc(company=co_b),), True)
    r = compare_posted_purchases(a, b)
    assert r.state is PurchaseResultKind.MATCH

