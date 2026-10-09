"""R2-US-032 TC096 (pagination + alias proof part): COMPLETE only for a proven chain; every other
ending is complete=False with its own reason code; alias/direction/currency/period refusals stop
before any fetch; the proof digest is deterministic and sensitive to every bound input."""
from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest

from business_ai_gateway.phase2.aliases import (
    AliasResolver,
    AliasScope,
    Reference,
    SupplierEntity,
)
from business_ai_gateway.phase2.comparison_snapshot import canonical_digest
from business_ai_gateway.phase2.posted_receipts import (
    MAX_PAGES,
    MAX_ROWS,
    Direction,
    PostedReceiptsRetriever,
    ReceiptsProof,
    RetrievalReason,
    _proof_payload,
)
from business_ai_gateway.phase2.purchase_reconciliation import (
    PurchaseListing,
    PurchaseResultKind,
    PurchaseScope,
    compare_posted_purchases,
)
from tests.phase2._receipts_helpers import (
    COMPANY,
    FROM,
    REF,
    SNAP,
    UNTIL,
    VENDOR,
    FakeSource,
    doc,
    forge,
    page,
    request,
    resolver,
    retriever,
    scope,
    three_pages,
)


def run(script, **kw):
    r, src = retriever(script)
    return r.retrieve(request(), **kw), src


# -- complete chain --------------------------------------------------------------------------------
def test_tc096_three_page_chain_is_complete_with_proof():
    res, src = run(three_pages())
    assert res.complete is True and res.reason is RetrievalReason.OK
    assert [d.doc_ref for d in res.listing.documents] == ["d-1", "d-2", "d-3", "d-4"]
    assert res.listing.complete is True and res.listing.snapshot_ref == SNAP
    p = res.proof
    assert p.complete and p.terminal_page_reached and p.pages_fetched == 3
    assert p.page_tokens == (None, "tok-1", "tok-2")
    assert [t for _, t in src.calls] == [None, "tok-1", "tok-2"]  # each page continues the previous
    assert (p.alias_entity_id, p.alias_namespace, p.alias_value) == (VENDOR, "erp_code", VENDOR)
    assert (p.tenant_id, p.company_ref, p.counterparty_ref, p.currency) == (
        "t", COMPANY, VENDOR, "MDL")
    assert (p.from_inclusive, p.until_exclusive) == (scope().from_inclusive, scope().until_exclusive)
    assert (p.direction, p.source_id, p.snapshot_ref) == ("RECEIPT", "onec-reference", SNAP)
    assert p.rows_seen == 4 and p.kept_count == 4 and len(p.digest) == 64
    assert p.listing_digest and p.listing_digest != p.digest


def test_single_terminal_page_without_page_index_is_complete():
    res, _ = run({None: page([doc("a")])})
    assert res.complete and res.proof.page_tokens == (None,)


def test_complete_chain_feeds_a_matching_comparison():
    res, _ = run(three_pages())
    native = PurchaseListing(scope(), SNAP, res.listing.documents, True)
    assert compare_posted_purchases(native, res.listing).state is PurchaseResultKind.MATCH


# -- every stopped chain is complete=False with its own code ---------------------------------------
def _chain(second, first_next="tok-1"):
    return {None: page([doc("d-1")], first_next, SNAP, 0), "tok-1": second}


STOPPED = {
    "repeated_token": (
        {None: page([doc("d-1")], "tok-1"), "tok-1": page([doc("d-2")], "tok-1")},
        RetrievalReason.TOKEN_REPEATED),
    "regressed_token": (
        {None: page([doc("d-1")], "tok-1"), "tok-1": page([doc("d-2")], "tok-2"),
         "tok-2": page([doc("d-3")], "tok-1")},
        RetrievalReason.TOKEN_REGRESSED),
    "blank_token": (
        {None: page([doc("d-1")], ""), },
        RetrievalReason.TOKEN_MISSING),
    "page_gap": (
        _chain(page([doc("d-2")], None, SNAP, 2)),
        RetrievalReason.PAGE_GAP),
    "index_regress": (
        _chain(page([doc("d-2")], None, SNAP, 0)),
        RetrievalReason.TOKEN_REGRESSED),
    "duplicate_across_pages": (
        _chain(page([doc("d-1")])),
        RetrievalReason.DUPLICATE_DOCUMENT),
    "duplicate_excluded_row_across_pages": (
        {None: page([doc("d-1", posted=False)], "tok-1"), "tok-1": page([doc("d-1")])},
        RetrievalReason.DUPLICATE_DOCUMENT),
    "duplicate_within_page": (
        {None: page([doc("d-1"), doc("d-1")])},
        RetrievalReason.DUPLICATE_DOCUMENT),
    "snapshot_changed": (
        _chain(page([doc("d-2")], None, "snap-2", 1)),
        RetrievalReason.SNAPSHOT_CHANGED),
    "source_error_page_2": (
        _chain(RuntimeError("boom")),
        RetrievalReason.SOURCE_ERROR),
    "source_error_base_text": (
        _chain(TimeoutError("slow")),
        RetrievalReason.SOURCE_ERROR),
}


# honest truncation keeps the validated earlier pages as an INCOMPLETE listing; every other stop
# means the source itself is unreliable and no listing is surfaced at all
_PARTIAL = {"source_error_page_2", "source_error_base_text"}


@pytest.mark.parametrize("name", sorted(STOPPED))
def test_tc096_stopped_chain_is_not_complete_and_carries_its_reason(name):
    script, reason = STOPPED[name]
    res, _ = run(script)
    assert res.complete is False and res.reason is reason
    assert res.proof.complete is False and res.proof.reason == reason.value
    assert res.proof.terminal_page_reached is False
    if name in _PARTIAL:
        assert res.listing is not None and res.listing.complete is False
        assert res.proof.listing_digest is not None
    else:
        assert res.listing is None and res.proof.listing_digest is None


def test_unreliable_source_reasons_are_never_given_a_partial_listing():
    from business_ai_gateway.phase2.posted_receipts import _NO_LISTING
    for r in (RetrievalReason.DUPLICATE_DOCUMENT, RetrievalReason.SNAPSHOT_CHANGED,
              RetrievalReason.PAGE_GAP, RetrievalReason.TOKEN_MISSING,
              RetrievalReason.TOKEN_REPEATED, RetrievalReason.TOKEN_REGRESSED,
              RetrievalReason.PAGE_DIRECTION_UNPROVEN):
        assert r in _NO_LISTING
    for r in (RetrievalReason.SOURCE_ERROR, RetrievalReason.PAGE_LIMIT_HIT,
              RetrievalReason.ROW_LIMIT_HIT):
        assert r not in _NO_LISTING


def test_stopped_chain_keeps_only_validated_earlier_pages_and_never_the_offending_page():
    script, _ = STOPPED["source_error_page_2"]
    res, _ = run(script)
    assert [d.doc_ref for d in res.listing.documents] == ["d-1"]
    assert res.proof.pages_fetched == 1 and res.proof.rows_seen == 1


@pytest.mark.parametrize("second,reason", [
    (page([forge(doc("d-2"), posted=1)]), RetrievalReason.PAGE_POSTED_FLAG_UNQUALIFIED),
    (page([forge(doc("d-2"), doc_ref="")]), RetrievalReason.PAGE_IDENTITY_INVALID),
    (page([doc("d-2")], None, ""), RetrievalReason.SNAPSHOT_REF_INVALID),
    (page([doc("d-2")], None, "snap-2", 1), RetrievalReason.SNAPSHOT_CHANGED),
    (page([doc("d-1")], None, SNAP, 1), RetrievalReason.DUPLICATE_DOCUMENT),
    (page([doc("d-2")], None, SNAP, 5), RetrievalReason.PAGE_GAP),
    (page([doc("d-2")], None, SNAP, 1, kinds=()), RetrievalReason.PAGE_DIRECTION_UNPROVEN),
], ids=["posted_flag", "blank_doc_ref", "blank_snapshot", "snapshot_changed", "duplicate",
        "gap", "no_kind"])
def test_valid_first_page_then_unreliable_second_page_surfaces_no_listing(second, reason):
    res, src = run({None: page([doc("d-1")], "tok-1", SNAP, 0), "tok-1": second})
    assert res.reason is reason and res.complete is False
    assert res.listing is None  # the valid page 1 is not surfaced from an unreliable chain
    assert res.proof.listing_digest is None and res.proof.reason == reason.value
    assert res.proof.pages_fetched == 1 and res.proof.rows_seen == 1
    assert [t for _, t in src.calls] == [None, "tok-1"]


def test_page_index_must_be_an_int():
    for bad in ("0", 0.0, True, [0]):
        res, _ = run({None: page([doc("d-1")], None, SNAP, bad)})
        assert res.reason is RetrievalReason.PAGE_INVALID and res.complete is False
        assert res.listing is None


def test_residual_risk_pin_without_page_index_a_silently_skipped_page_is_complete():
    # RESIDUAL RISK (documented in the module docstring): with no page_index the retriever cannot
    # tell that the source silently dropped a page behind a valid-looking token. This pins the
    # CURRENT behaviour so a change is a conscious decision; with page_index the same skip is
    # PAGE_GAP (see "page_gap" above).
    res, _ = run({None: page([doc("d-1")], "tok-1"), "tok-1": page([doc("d-9")])})
    assert res.complete is True and res.reason is RetrievalReason.OK
    res, _ = run({None: page([doc("d-1")], "tok-1", SNAP, 0),
                  "tok-1": page([doc("d-9")], None, SNAP, 2)})
    assert res.complete is False and res.reason is RetrievalReason.PAGE_GAP


def test_partial_listing_is_inconclusive_downstream_even_if_it_would_otherwise_match():
    script, _ = STOPPED["source_error_page_2"]
    res, _ = run(script)
    native = PurchaseListing(scope(), SNAP, res.listing.documents, True)
    cmp = compare_posted_purchases(native, res.listing)
    assert cmp.state is PurchaseResultKind.INCONCLUSIVE
    assert cmp.reason_code == "GATEWAY_LISTING_UNQUALIFIED"


def test_source_error_on_first_page_has_no_listing_but_a_proof():
    res, _ = run({None: ConnectionError("down")})
    assert res.reason is RetrievalReason.SOURCE_ERROR and res.listing is None
    assert res.proof.snapshot_ref is None and res.proof.listing_digest is None
    assert res.proof.pages_fetched == 0


def test_page_limit_hit_is_not_complete():
    res, src = run(three_pages(), max_pages=2)
    assert res.reason is RetrievalReason.PAGE_LIMIT_HIT and res.complete is False
    assert len(src.calls) == 2  # the third page is never requested
    assert res.listing.complete is False and res.proof.pages_fetched == 2
    assert [d.doc_ref for d in res.listing.documents] == ["d-1", "d-2", "d-3"]


def test_page_limit_exactly_enough_for_a_terminal_page_is_complete():
    res, _ = run(three_pages(), max_pages=3)
    assert res.complete is True


def test_row_limit_hit_is_not_complete_and_does_not_merge_the_page():
    res, _ = run(three_pages(), max_rows=2)
    assert res.reason is RetrievalReason.ROW_LIMIT_HIT and res.complete is False
    assert [d.doc_ref for d in res.listing.documents] == ["d-1", "d-2"]
    res, _ = run(three_pages(), max_rows=4)
    assert res.complete is True


def test_endless_chain_terminates_at_the_hard_page_bound():
    class Endless:
        calls = 0

        def fetch_page(self, sc, direction, token):
            Endless.calls += 1
            return page([doc(f"d-{Endless.calls}")], f"tok-{Endless.calls}")

    out = PostedReceiptsRetriever(Endless(), resolver()).retrieve(request())
    assert out.reason is RetrievalReason.PAGE_LIMIT_HIT and out.complete is False
    assert Endless.calls == MAX_PAGES


def test_huge_page_is_stopped_by_the_hard_row_bound():
    big = [doc(f"d-{i}") for i in range(MAX_ROWS + 1)]
    res, _ = run({None: page(big)})
    assert res.reason is RetrievalReason.ROW_LIMIT_HIT and res.complete is False


# -- alias proof -----------------------------------------------------------------------------------
def test_exact_reference_resolves_and_is_bound_in_the_proof():
    res, src = run(three_pages())
    assert res.proof.alias_entity_id == VENDOR and len(src.calls) == 3


def test_name_only_request_is_refused_before_the_resolver_and_enqueues_nothing():
    scope_ = AliasScope("t", COMPANY)
    extra = (SupplierEntity("OTHER-1", scope_, "Twin SRL"), SupplierEntity("OTHER-2", scope_, "twin srl"))
    res_ = resolver(extra_entities=extra)
    src = FakeSource(three_pages())
    res = PostedReceiptsRetriever(src, res_).retrieve(request(ref=None, name="TWIN SRL"))
    assert res.reason is RetrievalReason.ALIAS_NOT_FOUND and res.complete is False
    assert res.listing is None and res.proof is None and src.calls == []
    assert res_.queue_items(scope_) == ()  # no review item / side effect from a name-only request


def test_reference_shared_by_two_entities_is_ambiguous_and_nothing_is_fetched():
    shared = Reference("erp_code", "SHARED")
    scope_ = AliasScope("t", COMPANY)
    extra = (SupplierEntity("A", scope_, "A SRL", (shared,)),
             SupplierEntity("B", scope_, "B SRL", (shared,)))
    r, src = retriever(three_pages(), extra_entities=extra)
    res = r.retrieve(request(ref=shared))
    assert res.reason is RetrievalReason.ALIAS_AMBIGUOUS and src.calls == []


def test_name_alone_never_resolves():
    r, src = retriever(three_pages())
    res = r.retrieve(request(ref=None, name="Moldretail SRL"))
    assert res.reason is RetrievalReason.ALIAS_NOT_FOUND and src.calls == []


def test_same_alias_in_another_company_is_not_visible():
    # the supplier is registered only under company 818HA; ask for company other-co
    r, src = retriever({None: page([doc("a", company="other-co")])})
    res = r.retrieve(request(sc=scope(company="other-co")))
    assert res.reason is RetrievalReason.ALIAS_NOT_FOUND and src.calls == []


def test_same_reference_in_two_companies_resolves_each_in_its_own_scope():
    res_ = resolver(extra_entities=(
        SupplierEntity(VENDOR, AliasScope("t", "other-co"), "Moldretail SRL", (REF,)),))
    src = FakeSource({None: page([doc("a", company="other-co")])})
    out = PostedReceiptsRetriever(src, res_).retrieve(request(sc=scope(company="other-co")))
    assert out.complete and out.proof.company_ref == "other-co"


def test_other_tenant_is_not_visible():
    sc = scope()
    other = PurchaseScope("other-tenant", sc.source_id, COMPANY, VENDOR, FROM, UNTIL, "MDL")
    r, src = retriever(three_pages())
    assert r.retrieve(request(sc=other)).reason is RetrievalReason.ALIAS_NOT_FOUND
    assert src.calls == []


def test_resolved_entity_must_be_the_requested_counterparty():
    r, src = retriever(three_pages())
    res = r.retrieve(request(sc=scope(vendor="SOMEONE-ELSE")))
    assert res.reason is RetrievalReason.ALIAS_COUNTERPARTY_MISMATCH and src.calls == []


def test_invalid_reference_or_resolver_failure_is_refused_not_raised():
    r, src = retriever(three_pages())
    assert r.retrieve(request(ref=Reference("", ""))).reason is RetrievalReason.ALIAS_REJECTED
    assert r.retrieve(request(ref="erp_code:X")).reason is RetrievalReason.ALIAS_REJECTED

    class Boom(AliasResolver):
        def resolve(self, scope_, query):
            raise RuntimeError("x")

    boom = Boom(clock=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    out = PostedReceiptsRetriever(src, boom).retrieve(request())
    assert out.reason is RetrievalReason.ALIAS_REJECTED
    assert src.calls == []


def test_sale_direction_stops_before_alias_and_fetch():
    r, src = retriever(three_pages())
    assert r.retrieve(request(direction=Direction.SALE)).reason is (
        RetrievalReason.DIRECTION_NOT_RECEIPT)
    assert src.calls == []


# -- proof digest ----------------------------------------------------------------------------------
def test_same_inputs_give_the_same_proof_digest_and_a_new_source_instance_does_too():
    a, _ = run(three_pages())
    b, _ = run(three_pages())
    assert a.proof.digest == b.proof.digest and a.proof.listing_digest == b.proof.listing_digest
    assert a.proof == b.proof


def test_source_row_order_within_a_page_does_not_change_the_digest():
    s1 = three_pages()
    s2 = three_pages()
    s2[None] = page([doc("d-2", amount="10"), doc("d-1")], "tok-1", SNAP, 0)
    assert run(s1)[0].proof.digest == run(s2)[0].proof.digest


def _digest(script, **kw):
    return run(script, **kw)[0].proof.digest


def test_any_changed_page_token_filter_or_identity_changes_the_digest():
    base = _digest(three_pages())

    s = three_pages()
    s["tok-2"] = page([doc("d-4", amount="7.01")])
    assert _digest(s) != base  # a row amount

    s = three_pages()
    s["tok-1"] = page([doc("d-3", amount="5.5", number="999")], "tok-2", SNAP, 1)
    assert _digest(s) != base  # a row identity

    s = three_pages()
    s[None] = page([doc("d-1"), doc("d-2", amount="10"), doc("x", posted=False)], "tok-1", SNAP, 0)
    assert _digest(s) != base  # an excluded row changes the exclusion counts

    s = three_pages()
    s[None] = page(s[None].documents, "tok-A", SNAP, 0)
    s["tok-A"] = s.pop("tok-1")
    assert _digest(s) != base  # a page token

    assert _digest(three_pages(snap="snap-2")) != base  # snapshot ref

    r, _ = retriever(three_pages())
    eur = r.retrieve(request(sc=scope(currency="EUR")))
    assert eur.proof.digest != base and eur.proof.currency == "EUR"  # the currency filter


_CHANGED = {
    "alias_entity_id": "X", "alias_namespace": "other_ns", "alias_value": "OTHER",
    "tenant_id": "t2", "company_ref": "c2", "counterparty_ref": "v2", "currency": "EUR",
    "from_inclusive": datetime(2026, 7, 1, tzinfo=UTC), "until_exclusive": datetime(2026, 10, 1, tzinfo=UTC),
    "direction": "SALE", "source_id": "other-src", "snapshot_ref": "snap-9",
    "page_tokens": (None, "tok-1"), "pages_fetched": 9, "rows_seen": 99, "kept_count": 99,
    "exclusions": (("WRONG_DIRECTION", 1),), "terminal_page_reached": False, "complete": False,
    "reason": "PAGE_LIMIT_HIT", "listing_digest": "0" * 64,
}


def test_every_proof_field_except_the_digest_is_covered_by_the_sensitivity_table():
    assert set(_CHANGED) == {f.name for f in fields(ReceiptsProof)} - {"digest"}
    assert set(_proof_payload(run(three_pages())[0].proof)) == set(_CHANGED)


@pytest.mark.parametrize("field", sorted(_CHANGED))
def test_changing_one_bound_proof_field_alone_changes_the_digest(field):
    proof = run(three_pages())[0].proof
    assert getattr(proof, field) != _CHANGED[field]
    other = replace(proof, **{field: _CHANGED[field]})
    assert canonical_digest(_proof_payload(other)) != proof.digest


def test_scope_changes_change_the_digest():
    base = _digest(three_pages())
    r, _ = retriever(three_pages())
    shifted = PurchaseScope("t", "onec-reference", COMPANY, VENDOR, FROM,
                            datetime(2026, 9, 2, tzinfo=UTC), "MDL")
    assert r.retrieve(request(sc=shifted)).proof.digest != base
    other_src = PurchaseScope("t", "onec-copy", COMPANY, VENDOR, FROM, UNTIL, "MDL")
    r2, _ = retriever(three_pages())
    assert r2.retrieve(request(sc=other_src)).proof.digest != base
