from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.purchase_reconciliation import (
    PurchaseDocument,
    PurchaseListing,
    PurchaseResultKind,
    PurchaseScope,
    compare_posted_purchases,
)

T0=datetime(2026,8,1,tzinfo=UTC)
T1=datetime(2026,8,15,tzinfo=UTC)
TEND=datetime(2026,9,1,tzinfo=UTC)


def scope(company="818HA", vendor="MOLDRETAIL-REF", currency="MDL"):
    return PurchaseScope("t", "onec-reference", company, vendor, T0, TEND, currency)


def doc(*, ref="posted-1", company="818HA", vendor="MOLDRETAIL-REF",
        currency="MDL", posted=True, deleted=False, amount="41.20", number="150"):
    return PurchaseDocument(
        doc_ref=ref, company_ref=company, counterparty_ref=vendor,
        contract_ref="contract-1", number=number, occurred_at=T1,
        amount=Decimal(amount), currency=currency,
        posted=posted, deletion_mark=deleted,
    )


def listing(*, docs=None, complete=True, snapshot="copy-1", source_scope=None):
    return PurchaseListing(
        scope=source_scope or scope(), snapshot_ref=snapshot,
        documents=tuple((doc(),) if docs is None else docs), complete=complete,
    )


def test_all_documents_and_fields_match():
    a=listing()
    r=compare_posted_purchases(a,a)
    assert r.state is PurchaseResultKind.MATCH
    assert r.authority=="EVALUATION_ONLY"


def test_missing_gateway_document_is_mismatch():
    a=listing()
    b=listing(docs=())
    r=compare_posted_purchases(a,b)
    assert r.state is PurchaseResultKind.MISMATCH
    assert r.differences[0].field=="DOCUMENT_PRESENCE"


def test_amount_mismatch_not_rounded_to_pass():
    a=listing()
    b=listing(docs=(doc(amount="41.21"),))
    r=compare_posted_purchases(a,b)
    assert r.state is PurchaseResultKind.MISMATCH
    assert {x.field for x in r.differences}=={"amount"}


@pytest.mark.parametrize("invalid",[
    doc(posted=False), doc(deleted=True), doc(company="another"),
    doc(vendor="another"), doc(currency="EUR"),
    replace(doc(), occurred_at=TEND),
])
def test_invalid_posting_scope_never_counts_as_match(invalid):
    native=listing()
    gateway=listing(docs=(invalid,))
    r=compare_posted_purchases(native,gateway)
    assert r.state is PurchaseResultKind.INCONCLUSIVE
    assert r.reason_code=="GATEWAY_LISTING_UNQUALIFIED"


def test_unposted_in_native_source_is_unqualified():
    r=compare_posted_purchases(listing(docs=(doc(posted=False),)),listing())
    assert r.state is PurchaseResultKind.INCONCLUSIVE


def test_company_scope_mismatch():
    r=compare_posted_purchases(listing(),listing(source_scope=scope(company="other")))
    assert r.reason_code=="PURCHASE_SCOPE_MISMATCH"


def test_supplier_scope_mismatch():
    r=compare_posted_purchases(listing(),listing(source_scope=scope(vendor="ambiguous-alias")))
    assert r.state is PurchaseResultKind.INCONCLUSIVE


def test_same_period_different_snapshot_not_ok():
    r=compare_posted_purchases(listing(),listing(snapshot="modified-1c"))
    assert r.reason_code=="PURCHASE_SNAPSHOT_MISMATCH"


def test_partial_pagination_refused():
    r=compare_posted_purchases(listing(),listing(complete=False))
    assert r.reason_code=="GATEWAY_LISTING_UNQUALIFIED"


def test_duplicate_doc_id_denied():
    with pytest.raises(ValueError,match="DUPLICATE_PURCHASE_REF"):
        listing(docs=(doc(),doc()))


def test_float_amount_is_denied():
    with pytest.raises(ValueError,match="FINITE_DECIMAL"):
        replace(doc(),amount=41.2)


def test_doc_name_number_change_detected():
    r=compare_posted_purchases(listing(),listing(docs=(doc(number="151"),)))
    assert r.state is PurchaseResultKind.MISMATCH
    assert r.differences[0].field=="number"


def test_two_empty_complete_listings_are_inconclusive_not_match():
    r=compare_posted_purchases(listing(docs=()), listing(docs=()))
    assert r.state is PurchaseResultKind.INCONCLUSIVE
    assert r.reason_code=="PURCHASE_BOTH_LISTINGS_EMPTY"
    assert r.differences==()
    assert r.authority=="EVALUATION_ONLY"


def test_one_empty_listing_is_still_a_mismatch():
    r=compare_posted_purchases(listing(docs=()), listing())
    assert r.state is PurchaseResultKind.MISMATCH
