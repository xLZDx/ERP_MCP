"""R2-US-032 TC094/TC095: posted receipts retrieval - identity/company/Posted rules, exclusions,
refusals before any fetch and hostile rows. Pure fixtures; no I/O."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from business_ai_gateway.phase2 import posted_receipts
from business_ai_gateway.phase2.aliases import (
    AliasOutcome,
    AliasResolver,
    AliasScope,
    ResolutionResult,
    SupplierEntity,
)
from business_ai_gateway.phase2.posted_receipts import (
    Direction,
    ExclusionReason,
    Page,
    PostedReceiptsRetriever,
    ReceiptsRequest,
    RetrievalReason,
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
        doc("d-2", company="other-co"),
        doc("d-3", vendor="OTHER-VENDOR"),
        doc("d-1x", company="other-co", number="150"),  # same number, other company
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
        doc("sale"),
        doc("return"),
    ]
    kinds = ("RECEIPT",) * 8 + ("SALE", "RETURN")
    r, _ = retriever({None: page(rows, kinds=kinds)})
    res = r.retrieve(request())
    assert [d.doc_ref for d in res.listing.documents] == ["keep"]
    c = counts(res)
    assert c == {
        "WRONG_DIRECTION": 2, "UNPOSTED": 1, "DELETED": 1, "WRONG_COMPANY": 1,
        "WRONG_COUNTERPARTY": 1, "WRONG_CURRENCY": 1, "OUT_OF_PERIOD": 2,
    }
    assert res.proof.rows_seen == 10 and res.proof.kept_count == 1
    assert sum(c.values()) + res.proof.kept_count == res.proof.rows_seen  # nothing dropped silently


def test_tc095_lower_bound_is_inclusive_and_excluded_amounts_are_not_in_the_listing():
    r, _ = retriever({None: page([doc("lo", at=FROM, amount="1"), doc("bad", posted=False,
                                                                      amount="999")])})
    res = r.retrieve(request())
    assert [d.doc_ref for d in res.listing.documents] == ["lo"]
    assert sum(d.amount for d in res.listing.documents) == Decimal(1)


_PRECEDENCE = [
    # (reason, row kind, field changes): row i violates reason i AND every later one
    ("WRONG_DIRECTION", "SALE", {"company": "OTHER", "vendor": "OTHER", "currency": "EUR",
                                 "at": datetime(2026, 1, 1, tzinfo=FROM.tzinfo),
                                 "deleted": True, "posted": False}),
    ("WRONG_COMPANY", "RECEIPT", {"company": "OTHER", "vendor": "OTHER", "currency": "EUR",
                                  "at": datetime(2026, 1, 1, tzinfo=FROM.tzinfo),
                                  "deleted": True, "posted": False}),
    ("WRONG_COUNTERPARTY", "RECEIPT", {"vendor": "OTHER", "currency": "EUR",
                                       "at": datetime(2026, 1, 1, tzinfo=FROM.tzinfo),
                                       "deleted": True, "posted": False}),
    ("WRONG_CURRENCY", "RECEIPT", {"currency": "EUR",
                                   "at": datetime(2026, 1, 1, tzinfo=FROM.tzinfo),
                                   "deleted": True, "posted": False}),
    ("OUT_OF_PERIOD", "RECEIPT", {"at": datetime(2026, 1, 1, tzinfo=FROM.tzinfo),
                                  "deleted": True, "posted": False}),
    ("DELETED", "RECEIPT", {"deleted": True, "posted": False}),
    ("UNPOSTED", "RECEIPT", {"posted": False}),
]


@pytest.mark.parametrize("reason,kind,changes", _PRECEDENCE, ids=[p[0] for p in _PRECEDENCE])
def test_tc095_precedence_is_deterministic_one_reason_per_document(reason, kind, changes):
    row = doc("x", **changes)
    res = retriever({None: page([row], kinds=(kind,))})[0].retrieve(request())
    assert res.listing.documents == ()
    assert {k: v for k, v in counts(res).items() if v} == {reason: 1}  # exactly ONE reason


def test_all_seven_reasons_always_present_in_the_proof_even_when_zero():
    res = retriever({None: page([doc("a")])})[0].retrieve(request())
    assert [k for k, _ in res.proof.exclusions] == [e.value for e in (
        ExclusionReason.WRONG_DIRECTION, ExclusionReason.UNPOSTED, ExclusionReason.DELETED, ExclusionReason.WRONG_COMPANY,
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
    ({"amount": Decimal("1E+31")}, RetrievalReason.PAGE_ROW_INVALID),  # above ap _MAX_ADJUSTED
    ({"amount": Decimal("1E-9")}, RetrievalReason.PAGE_ROW_INVALID),  # finer than 8 decimals
    ({"amount": Decimal("1E-500")}, RetrievalReason.PAGE_ROW_INVALID),
    ({"amount": Decimal("1" * 60)}, RetrievalReason.PAGE_ROW_INVALID),  # absurd digit count
])
def test_bad_row_refuses_the_whole_page_and_surfaces_no_listing(changes, reason):
    rows = [doc("good"), forge(doc("bad"), **changes)]
    res = retriever({None: page(rows)})[0].retrieve(request())
    assert res.reason is reason and res.complete is False
    assert res.listing is None  # the good row is not surfaced from an unreliable page
    assert res.proof is not None and res.proof.complete is False
    assert res.proof.reason == reason.value


@pytest.mark.parametrize("amount", ["1E+30", "0.00000001", "-1E+30", "0"])
def test_amount_at_the_documented_bounds_is_accepted(amount):
    res = retriever({None: page([doc("a", amount=amount)])})[0].retrieve(request())
    assert res.complete is True


def test_non_document_row_and_malformed_page_are_refused_not_raised():
    for bad in ([object()], [None], [{"doc_ref": "x"}]):
        res = retriever({None: page(bad)})[0].retrieve(request())
        assert res.reason is RetrievalReason.PAGE_IDENTITY_INVALID and res.listing is None
    for bad_page in (None, "page", {"documents": ()}, 5):
        res = retriever({None: bad_page})[0].retrieve(request())
        assert res.reason is RetrievalReason.PAGE_INVALID and res.complete is False


# -- direction is enforced from the source-native kind ----------------------------------------------
def test_direction_is_passed_to_the_port_on_every_page():
    r, src = retriever({None: page([doc("a")], "tok-1", SNAP, 0),
                        "tok-1": page([doc("b")], None, SNAP, 1)})
    assert r.retrieve(request()).complete is True
    assert src.directions == [Direction.RECEIPT, Direction.RECEIPT]


def test_sale_and_return_rows_are_never_kept_and_are_counted_as_wrong_direction():
    rows = [doc("r"), doc("s"), doc("ret")]
    res = retriever({None: page(rows, kinds=("RECEIPT", "SALE", "RETURN"))})[0].retrieve(request())
    assert [d.doc_ref for d in res.listing.documents] == ["r"]
    assert counts(res)["WRONG_DIRECTION"] == 2 and res.proof.rows_seen == 3
    assert res.complete is True  # the exclusion is counted, the page is still honest


@pytest.mark.parametrize("kinds", [
    None, (), ("RECEIPT", "RECEIPT"), ("",), (" RECEIPT",), (None,), (1,), ("RECEI\u200bPT",), "R",
])
def test_page_without_a_well_formed_kind_per_row_is_refused_and_surfaces_no_listing(kinds):
    res = retriever({None: Page((doc("a"),), None, SNAP, None, kinds)})[0].retrieve(request())
    assert res.reason is RetrievalReason.PAGE_DIRECTION_UNPROVEN and res.complete is False
    assert res.listing is None and res.proof.listing_digest is None


class _LyingStr(str):
    """A str subclass whose comparisons always claim 'RECEIPT' (spoofing attempt)."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


def test_a_str_subclass_kind_cannot_pass_the_direction_gate():
    sale = _LyingStr("SALE")
    res = retriever({None: page([doc("a")], kinds=(sale,))})[0].retrieve(request())
    assert res.reason is RetrievalReason.PAGE_DIRECTION_UNPROVEN and res.complete is False
    assert res.listing is None and res.proof.listing_digest is None


def test_a_str_subclass_in_a_document_field_is_refused():
    row = forge(doc("a"), counterparty_ref=_LyingStr(VENDOR))  # constructors refuse subclasses
    res = retriever({None: page([row], kinds=("RECEIPT",))})[0].retrieve(request())
    assert res.reason is RetrievalReason.PAGE_IDENTITY_INVALID and res.listing is None


def test_a_lowercase_kind_is_not_a_receipt():
    res = retriever({None: page([doc("a")], kinds=("receipt",))})[0].retrieve(request())
    assert res.listing.documents == () and counts(res)["WRONG_DIRECTION"] == 1


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
    requests = [
        request(direction=HOSTILE),
        request(sc=forge_scope(scope(), currency=HOSTILE)),
        request(sc=forge_scope(scope(), company_ref=HOSTILE)),
        request(sc=forge_scope(scope(), tenant_id=HOSTILE)),
        request(name=HOSTILE, ref=None),
        HOSTILE,
    ]
    for req in requests:
        res = r.retrieve(req)
        assert res.complete is False
        assert HOSTILE not in repr(res)  # the whole result, not just the reason
    assert src.calls == []


def test_source_exception_text_is_not_echoed():
    r, _ = retriever({None: RuntimeError(HOSTILE)})
    res = r.retrieve(request())
    assert res.reason is RetrievalReason.SOURCE_ERROR
    assert HOSTILE not in repr(res)


# -- alias scope / resolver hygiene ----------------------------------------------------------------
def _scoped_resolver(tenant, company):
    res = AliasResolver(clock=lambda: datetime(2026, 10, 10, tzinfo=FROM.tzinfo))
    res.add_entity(SupplierEntity(VENDOR, AliasScope(tenant, company), "Moldretail SRL", (REF,)))
    return res


def _purchase_scope(tenant, company):
    return PurchaseScope(tenant, "onec-reference", company, VENDOR, FROM, UNTIL, "MDL")


def test_canonical_lowercase_tenant_and_company_still_resolve():
    src = FakeSource({None: page([doc("a", company="acme")])})
    out = PostedReceiptsRetriever(src, _scoped_resolver("acme", "acme")).retrieve(
        request(sc=_purchase_scope("acme", "acme")))
    assert out.complete is True


@pytest.mark.parametrize("tenant,company", [("ACME", "acme"), ("acme", "ACME"), ("Acme", "Acme")])
def test_non_canonical_tenant_or_company_never_resolves_inside_the_casefolded_scope(tenant, company):
    src = FakeSource({None: page([doc("a", company=company)])})
    out = PostedReceiptsRetriever(src, _scoped_resolver("acme", "acme")).retrieve(
        request(sc=_purchase_scope(tenant, company)))
    assert out.reason is RetrievalReason.ALIAS_SCOPE_VIOLATION and out.complete is False
    assert out.listing is None and out.proof is None and src.calls == []


def test_resolver_scope_violation_outcome_maps_to_alias_scope_violation():
    class Violating(AliasResolver):
        def resolve(self, scope_, query):
            return ResolutionResult(AliasOutcome.SCOPE_VIOLATION, code="SCOPE_INVALID")

    src = FakeSource({None: page([doc("a")])})
    out = PostedReceiptsRetriever(src, Violating(clock=lambda: FROM)).retrieve(request())
    assert out.reason is RetrievalReason.ALIAS_SCOPE_VIOLATION and src.calls == []


def test_missing_reference_is_refused_before_the_resolver_is_called():
    calls = []

    class Spy(AliasResolver):
        def resolve(self, scope_, query):
            calls.append(query)
            return ResolutionResult(AliasOutcome.NOT_FOUND)

    src = FakeSource({None: page([doc("a")])})
    out = PostedReceiptsRetriever(src, Spy(clock=lambda: FROM)).retrieve(
        request(ref=None, name="Moldretail SRL"))
    assert out.reason is RetrievalReason.ALIAS_NOT_FOUND and out.proof is None
    assert calls == [] and src.calls == []


def test_a_resolver_returning_a_look_alike_result_is_rejected():
    from types import SimpleNamespace

    class Fake(AliasResolver):
        def resolve(self, scope_, query):
            return SimpleNamespace(outcome=AliasOutcome.RESOLVED, entity_id=VENDOR)

    src = FakeSource({None: page([doc("a")])})
    out = PostedReceiptsRetriever(src, Fake(clock=lambda: FROM)).retrieve(request())
    assert out.reason is RetrievalReason.ALIAS_REJECTED and src.calls == []


# -- empty pages / proof failure -------------------------------------------------------------------
def test_single_empty_terminal_page_without_page_index_is_not_complete():
    res = retriever({None: page([])})[0].retrieve(request())
    assert res.reason is RetrievalReason.EMPTY_UNPROVEN and res.complete is False
    assert res.proof.complete is False and res.listing.complete is False


def test_empty_terminal_page_with_page_index_zero_is_complete():
    res = retriever({None: page([], None, SNAP, 0)})[0].retrieve(request())
    assert res.complete is True and res.reason is RetrievalReason.OK


def test_proof_failure_keeps_the_original_stop_reason(monkeypatch):
    def boom(_payload):
        raise RuntimeError(HOSTILE)

    monkeypatch.setattr(posted_receipts, "canonical_digest", boom)
    res = retriever({None: RuntimeError("down")})[0].retrieve(request())
    assert res.reason is RetrievalReason.SOURCE_ERROR and res.complete is False
    assert res.proof is None and res.listing is None and HOSTILE not in repr(res)
    ok = retriever({None: page([doc("a")])})[0].retrieve(request())
    assert ok.reason is RetrievalReason.PROOF_UNAVAILABLE and ok.complete is False


def test_unscripted_token_is_a_test_script_error_not_a_source_error():
    from tests.phase2._receipts_helpers import UnscriptedTokenError
    src = FakeSource({})
    with pytest.raises(UnscriptedTokenError):
        src.fetch_page(scope(), Direction.RECEIPT, "nope")


def test_retrieval_is_read_only_scope_passed_unchanged_and_result_frozen():
    r, src = retriever({None: page([doc("a")])})
    sc = scope()
    res = r.retrieve(request(sc=sc))
    assert src.calls[0][0] == sc  # the port gets a frozen plain-UTC copy, equal to the request scope
    assert src.calls[0][0].from_inclusive.tzinfo is UTC
    with pytest.raises(AttributeError):
        res.complete = False  # frozen


# -- hardening round: exact types / empty 1C refs / lying objects ------------------------------------
EMPTY_REF = "00000000-0000-0000-0000-000000000000"


class _LyingStr(str):
    """A str subclass that claims to equal anything and never to differ."""
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


class _LyingResolver:
    def __init__(self, entity_id):
        self.entity_id = entity_id

    def resolve(self, scope_, query):
        return ResolutionResult(AliasOutcome.RESOLVED, entity_id=self.entity_id)


def test_m01_resolver_entity_id_must_be_exact_str_never_a_lying_subclass():
    src = FakeSource({None: page([doc("d-1")])})
    res = PostedReceiptsRetriever(src, _LyingResolver(_LyingStr("foreign-vendor"))).retrieve(request())
    assert res.complete is False and res.reason is RetrievalReason.ALIAS_REJECTED
    assert res.listing is None and src.calls == []

    class Plain(str):
        pass
    res = PostedReceiptsRetriever(src, _LyingResolver(Plain(VENDOR))).retrieve(request())
    assert res.reason is RetrievalReason.ALIAS_REJECTED and src.calls == []
    res = PostedReceiptsRetriever(src, _LyingResolver("foreign-vendor")).retrieve(request())
    assert res.reason is RetrievalReason.ALIAS_COUNTERPARTY_MISMATCH and src.calls == []


class _LyingDT(datetime):
    """A datetime subclass whose comparisons always say 'inside the period'."""
    def __lt__(self, other):
        return True

    def __le__(self, other):
        return True

    def __ge__(self, other):
        return True

    def __gt__(self, other):
        return False


def _lying(y):
    from datetime import UTC
    return _LyingDT(y, 1, 1, tzinfo=UTC)


def test_m06_datetime_subclass_with_lying_comparisons_cannot_pass_the_period_check():
    far = forge(doc("d-2028"), occurred_at=_lying(2028))
    r, _ = retriever({None: page([doc("d-1"), far])})
    res = r.retrieve(request())
    assert res.complete is False and res.reason is RetrievalReason.PAGE_ROW_INVALID
    assert res.listing is None


class _NeverAfterDT(datetime):
    """Claims never to be >= anything, hiding from > until in the scope's own check."""
    def __ge__(self, other):
        return False


def test_m06_scope_bounds_must_be_exact_datetimes():
    from datetime import UTC
    bad = forge_scope(scope(), from_inclusive=_NeverAfterDT(2030, 1, 1, tzinfo=UTC))
    r, src = retriever({None: page([doc("d-1")])})
    res = r.retrieve(request(sc=bad))
    assert res.complete is False and res.reason is RetrievalReason.PERIOD_INVALID
    assert src.calls == []


@pytest.mark.parametrize("field", ["ref", "contract", "vendor", "company"])
@pytest.mark.parametrize("spelling", [EMPTY_REF, "{" + EMPTY_REF + "}", EMPTY_REF.replace("-", "")])
def test_m04_empty_1c_reference_in_a_row_refuses_the_page(field, spelling):
    row = doc(spelling) if field == "ref" else doc("d-2", **{field: spelling})
    r, _ = retriever({None: page([doc("d-1"), row])})
    res = r.retrieve(request())
    assert res.complete is False and res.reason is RetrievalReason.PAGE_IDENTITY_INVALID
    assert res.listing is None


def test_m04_empty_1c_reference_in_the_request_scope_is_refused_before_fetch():
    r, src = retriever({None: page([doc("d-1")])})
    res = r.retrieve(request(sc=scope(vendor=EMPTY_REF)))
    assert res.reason is RetrievalReason.SCOPE_INVALID and src.calls == []
