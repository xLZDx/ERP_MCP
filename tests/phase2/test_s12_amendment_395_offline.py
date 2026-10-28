"""CR-395 (S12 contract amendment 2026-10-28): AMOUNT_INCONSISTENT, PERIOD_CLOSED and GRANT_EXHAUSTED.

Offline and pure: no PostgreSQL, no 1C, no network, no clock (every instant is passed in), no randomness.
Contract text: docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md.

Run: .venv\\Scripts\\python.exe -m pytest -p no:cacheprovider -q tests/phase2/test_s12_amendment_395_offline.py

Conventions of the amount rule (VAT-inclusive, half-up to 0.01, Decimal-exact):
  amount     == round(quantity x price, 2)
  vat_amount == round(amount x rate / (100 + rate), 2) for VAT0 / VAT10 / VAT20; any other code: AMOUNT_INCONSISTENT.
"""
from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Context, Decimal

import pytest

import business_ai_gateway.phase2.change as ch
from business_ai_gateway.phase2.change import (
    Applied,
    BudgetCheck,
    ChangeKind,
    ErrorCode,
    Event,
    Execution,
    Grant,
    NextAction,
    Refusal,
    apply_transition,
)
from business_ai_gateway.phase2.change.proposal import DraftPayload, parse_writer_payload
from tests.phase2 import _change_helpers as h
from tests.phase2._change_helpers import T0, approved, claimed, raw_create

D = Decimal
INCONSISTENT = ErrorCode.AMOUNT_INCONSISTENT


# ---------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------

def _line(quantity="2", price="10.50", code="VAT20", amount="21.00", vat="3.50") -> dict:
    return {"item_ref": "it-1", "quantity": quantity, "price": price, "vat_rate_code": code, "amount": amount,
            "vat_amount": vat}


def _raw(*lines: dict, kind: str = "CREATE_DRAFT") -> dict:
    raw = raw_create()
    raw["payload"]["lines"] = list(lines) if lines else [_line()]
    if kind == "UPDATE_DRAFT":
        raw.update(kind=kind, target_ref="doc1", target_version="v1")
        raw["payload"]["expected_target_version"] = "v1"
    return raw


def _outcomes(raw: dict, **ctx_over):
    """The result of the proposal path and of the writer path for the same payload."""
    via_proposal = ch.parse_proposal(raw, h.ctx(**ctx_over))
    via_writer = parse_writer_payload(copy.deepcopy(raw["payload"]), ChangeKind.CREATE_DRAFT, h.SCOPE)
    return via_proposal, via_writer


def _accepted(raw: dict) -> None:
    proposal, writer = _outcomes(raw)
    assert type(proposal) is ch.ChangeProposal, proposal
    assert type(writer) is DraftPayload, writer
    assert writer == proposal.payload  # both paths normalise identically


def _inconsistent(raw: dict) -> None:
    proposal, writer = _outcomes(raw)
    assert type(proposal) is Refusal and proposal.code is INCONSISTENT, proposal
    assert type(writer) is Refusal and writer.code is INCONSISTENT, writer


def _step(record, event, now=T0, **over):
    return apply_transition(record, event, h.good(event, record, now, **over))


def _refused(res, code, transition=None):
    assert type(res) is Refusal, res
    assert res.code is ErrorCode(code), (res.code, code)
    if transition is not None:
        assert res.transition == transition


# ---------------------------------------------------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------------------------------------------------

def test_registry_has_the_three_new_codes_appended_last_with_their_next_actions():
    codes = [c.value for c in ErrorCode]
    assert len(codes) == 39 and codes[-3:] == ["AMOUNT_INCONSISTENT", "PERIOD_CLOSED", "GRANT_EXHAUSTED"]
    assert ch.ERROR_INFO[ErrorCode.AMOUNT_INCONSISTENT].next_action is NextAction.FIX_REQUEST
    assert ch.ERROR_INFO[ErrorCode.PERIOD_CLOSED].next_action is NextAction.CONTACT_OPERATOR
    assert ch.ERROR_INFO[ErrorCode.GRANT_EXHAUSTED].next_action is NextAction.CONTACT_OPERATOR
    messages = {ch.ERROR_INFO[c].message for c in (ErrorCode.AMOUNT_INCONSISTENT, ErrorCode.PERIOD_CLOSED,
                                                   ErrorCode.GRANT_EXHAUSTED, ErrorCode.BUDGET_EXCEEDED,
                                                   ErrorCode.DIGEST_MISMATCH)}
    assert len(messages) == 5  # the new codes are distinguishable from the codes they were split off from


# ---------------------------------------------------------------------------------------------------------------------
# AMOUNT_INCONSISTENT: amount = quantity x price
# ---------------------------------------------------------------------------------------------------------------------

def test_consistent_default_payload_is_accepted_on_both_paths():
    _accepted(_raw())


@pytest.mark.parametrize("amount", ["21.01", "20.99", "0", "210", "999.00", "2.10"])
def test_wrong_amount_is_refused_on_both_paths(amount):
    _inconsistent(_raw(_line(amount=amount, vat="3.50")))


def test_wrong_amount_is_refused_even_when_the_vat_amount_matches_the_wrong_amount():
    # amount 22.00 with VAT20 -> vat 3.67 is internally consistent for the amount, but amount != 2 x 10.50
    _inconsistent(_raw(_line(amount="22.00", vat="3.67")))


@pytest.mark.parametrize("code, amount, vat", [
    ("VAT20", "21.00", "3.51"), ("VAT20", "21.00", "3.49"), ("VAT20", "21.00", "0"), ("VAT20", "21.00", "21"),
    ("VAT10", "21.00", "1.90"), ("VAT10", "21.00", "1.92"), ("VAT10", "21.00", "3.50"),
    ("VAT0", "21.00", "0.01"), ("VAT0", "21.00", "3.50"),
])
def test_wrong_vat_amount_is_refused_on_both_paths(code, amount, vat):
    _inconsistent(_raw(_line(code=code, amount=amount, vat=vat)))


@pytest.mark.parametrize("code, vat", [("VAT20", "3.50"), ("VAT10", "1.91"), ("VAT0", "0")])
def test_correct_vat_amount_for_each_table_rate_is_accepted(code, vat):
    _accepted(_raw(_line(code=code, vat=vat)))


def test_the_same_vat_amount_cannot_satisfy_two_different_rates():
    _accepted(_raw(_line(code="VAT10", vat="1.91")))
    _inconsistent(_raw(_line(code="VAT20", vat="1.91")))  # the rate code is what selects the formula
    _inconsistent(_raw(_line(code="VAT10", vat="3.50")))


# ---- rounding edges (half-up) -----------------------------------------------------------------------------------

@pytest.mark.parametrize("price, good_amount, bad_amount", [
    ("0.005", "0.01", "0"),       # exactly half a cent rounds UP (banker's rounding would give 0.00)
    ("0.025", "0.03", "0.02"),    # banker's rounding would give 0.02
    ("0.015", "0.02", "0.01"),
    ("0.004999", "0", "0.01"),    # just below half rounds down
    ("0.005001", "0.01", "0"),    # just above half rounds up
])
def test_amount_rounding_is_half_up_at_the_half_cent_boundary(price, good_amount, bad_amount):
    _accepted(_raw(_line(quantity="1", price=price, code="VAT0", amount=good_amount, vat="0")))
    _inconsistent(_raw(_line(quantity="1", price=price, code="VAT0", amount=bad_amount, vat="0")))


@pytest.mark.parametrize("amount, good_vat, bad_vat", [
    ("0.03", "0.01", "0"),      # 0.03 x 20/120 = 0.005 exactly: half-up 0.01 (banker's rounding would give 0.00)
    ("0.15", "0.03", "0.02"),   # 0.025 exactly: half-up 0.03 (banker's rounding would give 0.02)
    ("0.09", "0.02", "0.01"),   # 0.015 exactly
    ("0.02", "0", "0.01"),      # 0.00333... rounds down
    ("0.04", "0.01", "0"),      # 0.00666... rounds up
])
def test_vat_rounding_is_half_up_at_the_half_cent_boundary(amount, good_vat, bad_vat):
    _accepted(_raw(_line(quantity="1", price=amount, code="VAT20", amount=amount, vat=good_vat)))
    _inconsistent(_raw(_line(quantity="1", price=amount, code="VAT20", amount=amount, vat=bad_vat)))


def test_vat_is_computed_from_the_rounded_amount_not_from_the_unrounded_product():
    # 1 x 0.1496 = 0.1496 -> amount 0.15; VAT20 of the stated 0.15 is 0.025 -> 0.03, while VAT20 of the unrounded
    # 0.1496 would be 0.02493 -> 0.02. The document total is the stated amount, so 0.03 is the consistent value.
    _accepted(_raw(_line(quantity="1", price="0.1496", code="VAT20", amount="0.15", vat="0.03")))
    _inconsistent(_raw(_line(quantity="1", price="0.1496", code="VAT20", amount="0.15", vat="0.02")))
    _inconsistent(_raw(_line(quantity="1", price="0.1496", code="VAT20", amount="0.1496", vat="0.02")))


# ---- zero rate, unknown rate code --------------------------------------------------------------------------------

def test_zero_rate_requires_a_zero_vat_amount_and_accepts_zero_amount_lines():
    _accepted(_raw(_line(code="VAT0", amount="21.00", vat="0")))
    _accepted(_raw(_line(quantity="1", price="0", code="VAT0", amount="0", vat="0")))
    _accepted(_raw(_line(quantity="1", price="0", code="VAT20", amount="0", vat="0")))
    _inconsistent(_raw(_line(quantity="1", price="0", code="VAT0", amount="0", vat="0.01")))
    _inconsistent(_raw(_line(quantity="1", price="0", code="VAT0", amount="0.01", vat="0")))


@pytest.mark.parametrize("code", ["VATX", "VAT18", "vat20", "NOVAT", "VAT_20"])
def test_unknown_rate_code_is_refused_whatever_the_amounts(code):
    # review resolution: the VAT amount of an unmapped code can not be verified, so the line fails closed
    for vat in ("0", "3.50", "17", "999999.123456"):
        _inconsistent(_raw(_line(code=code, vat=vat)))
    _inconsistent(_raw(_line(code=code, amount="21.01", vat="3.50")))
    _inconsistent(_raw(_line(code=code, amount="0", vat="0")))


# ---- magnitudes --------------------------------------------------------------------------------------------------

def test_product_filling_the_whole_amount_field_is_checked_exactly():
    product = D("999999999") * D("999999999")  # 999999998000000001: 18 digits, the widest integer part an amount holds
    text = format(product, "f")
    _accepted(_raw(_line(quantity="999999999", price="999999999", code="VAT0", amount=text, vat="0")))
    below = format(product - D("0.01"), "f")
    above = format(product + D("0.01"), "f")
    _inconsistent(_raw(_line(quantity="999999999", price="999999999", code="VAT0", amount=below, vat="0")))
    _inconsistent(_raw(_line(quantity="999999999", price="999999999", code="VAT0", amount=above, vat="0")))


def test_wide_operands_are_multiplied_without_precision_loss_and_rounded_once():
    # 999999999999999999.999999 x 0.01 = 9999999999999999.99999999 -> 10000000000000000.00 (24 exact digits)
    _accepted(_raw(_line(quantity="999999999999999999.999999", price="0.01", code="VAT0",
                         amount="10000000000000000", vat="0")))
    _inconsistent(_raw(_line(quantity="999999999999999999.999999", price="0.01", code="VAT0",
                             amount="9999999999999999.99", vat="0")))
    # 48-digit exact product 999999999999999999.999999 x 999999999999999999.999999 (about 1e36): every amount an amount
    # field can hold (18 integer digits) is different from it, so the line is inconsistent, not a crash or a wrap-around
    for amount in ("999999999999999999", "0", "1"):
        _inconsistent(_raw(_line(quantity="999999999999999999.999999", price="999999999999999999.999999", code="VAT0",
                                 amount=amount, vat="0")))
    # and the true 36-digit amount can not even be written into the field: schema refusal
    wide = Context(prec=80)
    huge = format(wide.multiply(D("999999999999999999.999999"), D("999999999999999999.999999")).quantize(D("0.01"), context=wide), "f")
    proposal, writer = _outcomes(_raw(_line(quantity="999999999999999999.999999", price="999999999999999999.999999",
                                            code="VAT0", amount=huge, vat="0")))
    assert type(proposal) is Refusal and proposal.code is ErrorCode.SCHEMA_INVALID
    assert type(writer) is Refusal and writer.code is ErrorCode.SCHEMA_INVALID


def test_vat_of_a_wide_amount_is_exact():
    amount = "999999999999999999"  # 18 digits
    expected = (D(amount) * 20 / 120).quantize(D("0.01"), rounding="ROUND_HALF_UP")  # 166666666666666666.50
    _accepted(_raw(_line(quantity="1", price=amount, code="VAT20", amount=amount, vat=format(expected, "f").rstrip("0"))))
    _inconsistent(_raw(_line(quantity="1", price=amount, code="VAT20", amount=amount,
                             vat=format(expected + D("0.01"), "f"))))


# ---- order of refusals and shape of the refusal ------------------------------------------------------------------

def test_amount_check_runs_after_structure_and_scope_and_before_reference_scope_and_shape():
    wrong = _line(amount="999.00")
    # structure first: an unknown key in the line is SCHEMA_INVALID although the amount is also wrong
    bad_structure = _raw(dict(wrong, extra="1"))
    assert ch.parse_proposal(bad_structure, h.ctx()).code is ErrorCode.SCHEMA_INVALID
    # scope next: a foreign organisation is SCOPE_MISMATCH although the amount is also wrong
    foreign = _raw(wrong)
    foreign["payload"]["organization_ref"] = "org-2"
    assert ch.parse_proposal(foreign, h.ctx()).code is ErrorCode.SCOPE_MISMATCH
    # amount before reference scope and shape qualification
    assert ch.parse_proposal(_raw(wrong), h.ctx(in_scope_refs=frozenset({"nothing"}))).code is INCONSISTENT
    assert ch.parse_proposal(_raw(wrong), h.ctx(qualified_currencies=frozenset())).code is INCONSISTENT
    two_lines = _raw(_line(), wrong)  # a wider-than-measured document with a bad second line
    assert ch.parse_proposal(two_lines, h.ctx()).code is INCONSISTENT
    # the same payload with a consistent amount reaches the later checks
    assert ch.parse_proposal(_raw(_line()), h.ctx(in_scope_refs=frozenset({"nothing"}))).code is ErrorCode.REF_OUT_OF_SCOPE
    assert ch.parse_proposal(_raw(_line()), h.ctx(qualified_currencies=frozenset())).code is ErrorCode.SHAPE_NOT_QUALIFIED
    assert ch.parse_proposal(_raw(_line(), _line()), h.ctx()).code is ErrorCode.SHAPE_NOT_QUALIFIED


def test_any_inconsistent_line_of_several_refuses_the_whole_document():
    for bad_index in (0, 1, 2):
        lines = [_line(), _line(), _line()]
        lines[bad_index] = _line(vat="3.51")
        proposal = ch.parse_proposal(_raw(*lines), h.ctx())
        assert type(proposal) is Refusal and proposal.code is INCONSISTENT, bad_index


def test_update_draft_is_checked_like_create_draft():
    assert type(ch.parse_proposal(_raw(kind="UPDATE_DRAFT"), h.ctx())) is ch.ChangeProposal
    bad = ch.parse_proposal(_raw(_line(amount="22.00", vat="3.67"), kind="UPDATE_DRAFT"), h.ctx())
    assert type(bad) is Refusal and bad.code is INCONSISTENT


def test_refusal_carries_only_the_fixed_code_and_message_never_the_numbers():
    res = ch.parse_proposal(_raw(_line(amount="123456.78", vat="7")), h.ctx())
    assert res.code is INCONSISTENT and res.transition == "propose"
    assert res.message == ch.ERROR_INFO[INCONSISTENT].message and res.next_action is NextAction.FIX_REQUEST
    assert "123456" not in repr(res) and "123456" not in res.message


def test_writer_post_and_unpost_payloads_are_not_touched_by_the_amount_rule():
    assert parse_writer_payload({}, ChangeKind.POST, h.SCOPE) is None
    assert parse_writer_payload({}, ChangeKind.UNPOST, h.SCOPE) is None


def test_writer_payload_with_wrong_amount_does_not_become_a_digest_bound_payload():
    ok_payload = parse_writer_payload(_raw()["payload"], ChangeKind.CREATE_DRAFT, h.SCOPE)
    assert type(ok_payload) is DraftPayload
    bad = parse_writer_payload(_raw(_line(amount="21.01"))["payload"], ChangeKind.CREATE_DRAFT, h.SCOPE)
    assert type(bad) is Refusal and bad.code is INCONSISTENT


def test_a_refused_amount_leaves_no_proposal_so_no_digest_can_be_approved_for_it():
    assert type(ch.parse_proposal(_raw(_line(amount="999.00")), h.ctx())) is Refusal
    assert type(ch.parse_proposal(_raw(), h.ctx())) is ch.ChangeProposal  # the honest twin still parses


# ---------------------------------------------------------------------------------------------------------------------
# PERIOD_CLOSED versus DIGEST_MISMATCH at T6 begin_apply
# ---------------------------------------------------------------------------------------------------------------------

def _post_claim():
    return claimed(kind=ChangeKind.POST, parent_change_id="parent9", target_ref="doc9")


@pytest.mark.parametrize("record_factory", [claimed, _post_claim], ids=["create", "post"])
def test_period_closed_is_refused_with_the_distinct_code_with_or_without_a_digest_change(record_factory):
    for digest_equal in (True, False):
        record = record_factory()
        res = _step(record, Event.BEGIN_APPLY, period_closed=True, state_digest_equal=digest_equal)
        _refused(res, "PERIOD_CLOSED", "T6")


def test_state_change_without_an_observed_closed_period_stays_digest_mismatch():
    for kwargs in ({"state_digest_equal": False}, {"state_digest_equal": False, "period_closed": False}):
        _refused(_step(_post_claim(), Event.BEGIN_APPLY, **kwargs), "DIGEST_MISMATCH", "T6")


def test_open_period_and_equal_state_digest_begin_the_apply():
    res = _step(_post_claim(), Event.BEGIN_APPLY, period_closed=False, state_digest_equal=True)
    assert type(res) is Applied and res.record.execution is Execution.APPLYING


def test_period_closed_refusal_changes_nothing_and_the_change_can_not_proceed_to_a_permit():
    record = _post_claim()
    res = _step(record, Event.BEGIN_APPLY, period_closed=True)
    _refused(res, "PERIOD_CLOSED")
    assert record.execution is Execution.NOT_STARTED
    # no APPLYING state exists, so the permit step is refused too
    assert type(_step(record, Event.ISSUE_PERMIT)) is Refusal


def test_period_guard_sits_between_fingerprint_and_state_digest_guards():
    # earlier guards win over PERIOD_CLOSED
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_closed=True, version_equals_approved=False), "STALE_VERSION")
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_closed=True, fingerprint_authenticated=False), "TARGET_REJECTED")
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_closed=True, kill=h.UNREADABLE), "KILL_SWITCH_ACTIVE")
    # PERIOD_CLOSED wins over the later guards
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_closed=True, writer_lock_held=False), "PERIOD_CLOSED")
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_closed=True, ownership_row_committed=False), "PERIOD_CLOSED")


# ---------------------------------------------------------------------------------------------------------------------
# GRANT_EXHAUSTED versus BUDGET_EXCEEDED
# ---------------------------------------------------------------------------------------------------------------------

VALID_FROM = T0
VALID_TO = T0 + timedelta(days=30)
INSIDE = T0 + timedelta(days=1)


def grant(limit="100", reserved="0", consumed="0", currency="RUB") -> Grant:
    return Grant("g1", currency, D(limit), VALID_FROM, VALID_TO, D(reserved), D(consumed))


@pytest.mark.parametrize("reserved, consumed", [("100", "0"), ("0", "100"), ("40", "60"), ("99.99", "0.01")])
def test_nothing_left_and_a_positive_request_is_grant_exhausted(reserved, consumed):
    g = grant(reserved=reserved, consumed=consumed)
    for amount in ("0.01", "1", "100", "1000000"):
        assert ch.reserve(g, D(amount), "RUB", INSIDE) is ErrorCode.GRANT_EXHAUSTED, amount


def test_zero_request_on_an_exhausted_grant_is_still_accepted_and_changes_nothing():
    g = grant(reserved="40", consumed="60")
    res = ch.reserve(g, D(0), "RUB", INSIDE)
    assert type(res) is Grant and (res.reserved, res.consumed, res.limit) == (D("40"), D("60"), D("100"))


def test_zero_limit_grant_has_nothing_left_for_any_positive_request():
    assert ch.reserve(grant(limit="0"), D("0.01"), "RUB", INSIDE) is ErrorCode.GRANT_EXHAUSTED
    assert type(ch.reserve(grant(limit="0"), D(0), "RUB", INSIDE)) is Grant


@pytest.mark.parametrize("reserved, consumed, amount", [
    ("0", "0", "100.01"),        # larger than the whole limit, nothing spent yet
    ("40", "0", "60.01"),        # larger than the remainder
    ("0", "70", "30.01"),
    ("99.99", "0", "0.02"),      # remainder is one cent, request is two
    ("50", "49.99", "0.02"),
])
def test_request_larger_than_a_non_zero_remainder_stays_budget_exceeded(reserved, consumed, amount):
    assert ch.reserve(grant(reserved=reserved, consumed=consumed), D(amount), "RUB", INSIDE) is ErrorCode.BUDGET_EXCEEDED


@pytest.mark.parametrize("reserved, consumed, amount", [("99.99", "0", "0.01"), ("40", "0", "60"), ("0", "70", "30")])
def test_request_equal_to_the_remainder_is_admitted_and_then_the_grant_is_exhausted(reserved, consumed, amount):
    g = ch.reserve(grant(reserved=reserved, consumed=consumed), D(amount), "RUB", INSIDE)
    assert type(g) is Grant and g.reserved + g.consumed == g.limit
    assert ch.reserve(g, D("0.01"), "RUB", INSIDE) is ErrorCode.GRANT_EXHAUSTED


def test_window_miss_is_budget_exceeded_even_for_an_exhausted_grant():
    exhausted = grant(consumed="100")
    assert ch.reserve(exhausted, D("1"), "RUB", VALID_FROM - timedelta(microseconds=1)) is ErrorCode.BUDGET_EXCEEDED
    assert ch.reserve(exhausted, D("1"), "RUB", VALID_TO) is ErrorCode.BUDGET_EXCEEDED  # window end is open
    assert ch.reserve(exhausted, D("1"), "RUB", VALID_TO + timedelta(days=1)) is ErrorCode.BUDGET_EXCEEDED
    assert ch.reserve(exhausted, D("1"), "RUB", VALID_FROM) is ErrorCode.GRANT_EXHAUSTED  # first instant inside
    assert ch.reserve(exhausted, D("1"), "RUB", VALID_TO - timedelta(microseconds=1)) is ErrorCode.GRANT_EXHAUSTED
    # an unexhausted grant outside the window is the same code
    assert ch.reserve(grant(), D("1"), "RUB", VALID_TO) is ErrorCode.BUDGET_EXCEEDED


def test_currency_mismatch_is_checked_before_exhaustion():
    assert ch.reserve(grant(consumed="100"), D("1"), "USD", INSIDE) is ErrorCode.CURRENCY_NOT_BUDGETED


def test_invalid_amount_on_an_exhausted_grant_is_schema_invalid_not_exhausted():
    for bad in (D("-1"), D("NaN"), 1, "1", None):
        assert ch.reserve(grant(consumed="100"), bad, "RUB", INSIDE) is ErrorCode.SCHEMA_INVALID


@pytest.mark.parametrize("event, record_factory, expected_transition", [
    (Event.VALIDATE, h.proposed, "T2"), (Event.CLAIM, approved, "T5"),
])
def test_engine_maps_each_budget_evidence_to_its_own_code_and_leaves_the_record_untouched(
        event, record_factory, expected_transition):
    expected = {BudgetCheck.EXHAUSTED: "GRANT_EXHAUSTED", BudgetCheck.EXCEEDED: "BUDGET_EXCEEDED",
                BudgetCheck.NOT_CHECKED: "BUDGET_EXCEEDED", BudgetCheck.CURRENCY_NOT_BUDGETED: "CURRENCY_NOT_BUDGETED"}
    for check, code in expected.items():
        record = record_factory()
        _refused(_step(record, event, budget=check), code, expected_transition)
    assert type(_step(record_factory(), event, budget=BudgetCheck.OK)) is Applied


def test_policy_outcome_flows_through_the_engine_as_the_matching_code():
    """reserve() result -> evidence -> claim refusal, for an exhausted grant and for an oversized request."""
    def evidence(result):
        if isinstance(result, Grant):
            return BudgetCheck.OK
        return {ErrorCode.GRANT_EXHAUSTED: BudgetCheck.EXHAUSTED, ErrorCode.BUDGET_EXCEEDED: BudgetCheck.EXCEEDED,
                ErrorCode.CURRENCY_NOT_BUDGETED: BudgetCheck.CURRENCY_NOT_BUDGETED}.get(result, BudgetCheck.NOT_CHECKED)

    exhausted = ch.reserve(grant(reserved="100"), D("5"), "RUB", INSIDE)
    oversized = ch.reserve(grant(reserved="98"), D("5"), "RUB", INSIDE)
    _refused(_step(approved(), Event.CLAIM, budget=evidence(exhausted)), "GRANT_EXHAUSTED", "T5")
    _refused(_step(approved(), Event.CLAIM, budget=evidence(oversized)), "BUDGET_EXCEEDED", "T5")
    _refused(_step(h.proposed(), Event.VALIDATE, budget=evidence(exhausted)), "GRANT_EXHAUSTED", "T2")
