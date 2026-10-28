"""S15 epic E15-3: A<->B comparison (multisets, baseline netting, INCONCLUSIVE, value hiding)."""
from __future__ import annotations

from collections import Counter

import pytest

from erp_mcp_s15.ab_compare import (
    ComparisonStatus,
    DiffItem,
    ExpectedDifferences,
    LaneSnapshot,
    compare_ab,
    compare_via_readers,
    signed_difference,
)
from erp_mcp_s15.labels import LABEL_MACHINE_READ

S = ComparisonStatus

DOC = DiffItem("document", "DOC-7001")
MOV1 = DiffItem("movement", "DOC-7001|2026-03|41|521.1|CPX", "20.00")
MOV2 = DiffItem("movement", "DOC-7001|2026-03|18|521.1|CPX", "1.82")
BAL = DiffItem("balance", "521.1|CPX", "21.82")
NOISE = DiffItem("balance", "60.1|UNRELATED", "999.99")
EFFECT = (DOC, MOV1, MOV2, BAL)


def snap(*items: DiffItem, complete: bool = True) -> LaneSnapshot:
    return LaneSnapshot(complete, tuple(items))


def compare(post_b_items, *, base_a=(), base_b=(), post_a=(), expected_added=EFFECT,
            expected_removed=(), show_values=False):
    return compare_ab(snap(*base_a), snap(*base_b), snap(*post_a), snap(*post_b_items),
                      ExpectedDifferences(tuple(expected_added), tuple(expected_removed)),
                      show_values=show_values)


# --- label and match --------------------------------------------------------------------------------

def test_exact_expected_effect_is_a_machine_read_match_not_a_native_pass():
    result = compare(EFFECT)
    assert result.status is S.MATCH
    assert result.label == LABEL_MACHINE_READ
    assert "not native 1C PASS" in result.label
    assert "not accountant attested" in result.attestation
    assert (result.extra_count, result.missing_count) == (0, 0)


def test_no_change_and_no_expectation_is_a_match():
    assert compare((), expected_added=()).status is S.MATCH


def test_expected_removed_items_only_in_a_are_matched():
    result = compare((), post_a=(DOC,), expected_added=(), expected_removed=(DOC,))
    assert result.status is S.MATCH


def test_order_of_items_is_irrelevant():
    assert compare(tuple(reversed(EFFECT))).status is S.MATCH


# --- assertion 2: multisets, extra and missing -----------------------------------------------------

def test_extra_item_is_red():
    result = compare(EFFECT + (DiffItem("document", "DOC-OTHER"),))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (1, 0)


def test_missing_item_is_red():
    result = compare((DOC, MOV1, BAL))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (0, 1)


def test_duplicated_identical_movement_row_is_red_where_a_set_would_hide_it():
    result = compare(EFFECT + (MOV1,))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (1, 0)


def test_expected_duplicate_rows_must_both_be_present():
    expected = (DOC, MOV1, MOV1)
    assert compare((DOC, MOV1, MOV1), expected_added=expected).status is S.MATCH
    result = compare((DOC, MOV1), expected_added=expected)
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (0, 1)


def test_same_key_with_different_value_is_both_extra_and_missing():
    bad = DiffItem("movement", MOV1.key, "20.01")
    result = compare((DOC, bad, MOV2, BAL))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (1, 1)


def test_item_present_in_a_but_not_expected_removed_is_red():
    result = compare(EFFECT, post_a=(DiffItem("document", "ONLY-IN-A"),))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (0, 1)


def test_signed_difference_counts_b_minus_a_and_drops_zero():
    signed = signed_difference([DOC, MOV1, MOV1], [MOV1, BAL, BAL])
    assert signed == Counter({DOC: -1, MOV1: -1, BAL: 2})
    assert signed_difference([DOC], [DOC]) == Counter()


# --- assertion 3: baseline neither masks nor imitates ----------------------------------------------

def test_unrelated_baseline_difference_does_not_mask_a_missing_expected_effect():
    # NOISE already differed before the operation and still does; the effect did not happen.
    result = compare((NOISE,), base_b=(NOISE,))
    assert result.status is S.MISMATCH
    assert result.missing_count == len(EFFECT)
    assert result.extra_count == 0


def test_unrelated_baseline_difference_does_not_break_a_correct_effect():
    result = compare(EFFECT + (NOISE,), base_b=(NOISE,))
    assert result.status is S.MATCH


def test_baseline_difference_identical_to_an_expected_item_does_not_imitate_it():
    # DOC was already only-in-B before; it is expected as a NEW effect and is still just the old one.
    result = compare((DOC,), base_b=(DOC,), expected_added=(DOC,))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (0, 1)


def test_baseline_difference_that_disappears_is_reported():
    result = compare(EFFECT, base_b=(NOISE,))
    assert result.status is S.MISMATCH
    assert result.missing_count == 1  # the baseline noise is gone from B: -1 versus baseline


def test_baseline_difference_in_a_is_netted_symmetrically():
    result = compare(EFFECT, base_a=(NOISE,), post_a=(NOISE,))
    assert result.status is S.MATCH


# --- assertion 4: INCONCLUSIVE ---------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["base_a", "base_b", "post_a", "post_b"])
def test_any_incomplete_snapshot_is_inconclusive_never_match(which):
    snaps = {"base_a": snap(), "base_b": snap(), "post_a": snap(), "post_b": snap(*EFFECT)}
    snaps[which] = LaneSnapshot(False, snaps[which].items)
    result = compare_ab(snaps["base_a"], snaps["base_b"], snaps["post_a"], snaps["post_b"],
                        ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE
    assert result.status is not S.MATCH
    assert result.label == LABEL_MACHINE_READ


def test_incomplete_snapshot_with_matching_items_is_still_inconclusive():
    # The items agree perfectly; only the completeness flag can prevent a false MATCH.
    result = compare_ab(snap(), snap(), snap(), LaneSnapshot(False, EFFECT),
                        ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


@pytest.mark.parametrize("bad", [None, "snapshot", (True, ())])
def test_non_snapshot_input_is_inconclusive(bad):
    result = compare_ab(snap(), snap(), bad, snap(*EFFECT), ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


def test_snapshot_complete_flag_must_be_literally_true():
    result = compare_ab(snap(), snap(), snap(), LaneSnapshot(1, EFFECT),  # type: ignore[arg-type]
                        ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


class FakeLaneReader:
    def __init__(self, lanes, fail_on=None, error=None):
        self.lanes = lanes
        self.fail_on = fail_on
        self.error = error or RuntimeError("lane down")
        self.calls: list[str] = []

    def read_snapshot(self, lane):
        self.calls.append(lane)
        if lane == self.fail_on:
            raise self.error
        return self.lanes[lane]


def test_via_readers_reads_both_lanes_and_matches():
    reader = FakeLaneReader({"A": snap(), "B": snap(*EFFECT)})
    result = compare_via_readers(reader, "A", "B", (snap(), snap()), ExpectedDifferences(EFFECT))
    assert result.status is S.MATCH
    assert reader.calls == ["A", "B"]


@pytest.mark.parametrize("failing", ["A", "B"])
@pytest.mark.parametrize("error", [RuntimeError("x"), TimeoutError(), ConnectionError()])
def test_via_readers_failed_read_is_inconclusive(failing, error):
    reader = FakeLaneReader({"A": snap(), "B": snap(*EFFECT)}, fail_on=failing, error=error)
    result = compare_via_readers(reader, "A", "B", (snap(), snap()), ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


def test_via_readers_incomplete_lane_result_is_inconclusive():
    reader = FakeLaneReader({"A": snap(), "B": LaneSnapshot(False, EFFECT)})
    result = compare_via_readers(reader, "A", "B", (snap(), snap()), ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


def test_via_readers_incomplete_baseline_is_inconclusive():
    reader = FakeLaneReader({"A": snap(), "B": snap(*EFFECT)})
    result = compare_via_readers(reader, "A", "B", (LaneSnapshot(False), snap()),
                                 ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


# --- values hidden unless show_values=True --------------------------------------------------------------

def test_values_and_keys_are_hidden_by_default():
    extra = DiffItem("movement", "SECRET-KEY-77", "123456.78")
    result = compare(EFFECT + (extra,))
    assert result.status is S.MISMATCH and result.extra_count == 1
    assert result.extra_items == () and result.missing_items == ()
    text = repr(result)
    assert "SECRET-KEY-77" not in text and "123456.78" not in text


def test_values_are_shown_only_when_requested():
    extra = DiffItem("movement", "SECRET-KEY-77", "123456.78")
    result = compare(EFFECT[:3] + (extra,), show_values=True)
    assert result.status is S.MISMATCH
    assert dict(result.extra_items) == {extra: 1}
    assert dict(result.missing_items) == {BAL: 1}


def test_show_values_defaults_to_false_in_via_readers_as_well():
    secret = DiffItem("document", "HIDDEN-DOC")
    reader = FakeLaneReader({"A": snap(), "B": snap(*EFFECT, secret)})
    hidden = compare_via_readers(reader, "A", "B", (snap(), snap()), ExpectedDifferences(EFFECT))
    shown = compare_via_readers(reader, "A", "B", (snap(), snap()), ExpectedDifferences(EFFECT),
                                show_values=True)
    assert hidden.extra_items == () and "HIDDEN-DOC" not in repr(hidden)
    assert dict(shown.extra_items) == {secret: 1}


def test_match_and_inconclusive_carry_no_items_even_with_show_values():
    assert compare(EFFECT, show_values=True).extra_items == ()
    inc = compare_ab(snap(), snap(), LaneSnapshot(False), snap(), ExpectedDifferences(),
                     show_values=True)
    assert inc.status is S.INCONCLUSIVE and inc.extra_items == () and inc.missing_items == ()


def test_show_values_must_be_keyword_only():
    with pytest.raises(TypeError):
        compare_ab(snap(), snap(), snap(), snap(), ExpectedDifferences(), True)  # type: ignore[misc]


# --- CR-388: item validation (kind set, decimal values for movement and balance) -----------------

BAD_ITEMS = [
    DiffItem("other", "K"),  # unknown kind
    DiffItem("", "K"),
    DiffItem("MOVEMENT", "K", "1.00"),  # kinds are case-sensitive
    DiffItem("movement", "K"),  # movement without a value
    DiffItem("movement", "K", ""),
    DiffItem("balance", "K", ""),
    DiffItem("movement", "K", "abc"),
    DiffItem("movement", "K", "1e3"),
    DiffItem("movement", "K", " 1.00"),
    DiffItem("movement", "K", "1.00 "),
    DiffItem("movement", "K", "20."),
    DiffItem("movement", "K", ".5"),
    DiffItem("balance", "K", "+5"),
    DiffItem("balance", "K", "NaN"),
    DiffItem("balance", "K", "1,5"),
    DiffItem("movement", "K", None),
    DiffItem("movement", "K", 20),
    DiffItem("document", None),
    DiffItem("document", 7),
    DiffItem("document", "K", None),
    "not-an-item",
    None,
    ("document", "K", ""),
]
BAD_IDS = [f"bad{i}" for i in range(len(BAD_ITEMS))]


@pytest.mark.parametrize("bad", BAD_ITEMS, ids=BAD_IDS)
@pytest.mark.parametrize("where", ["base_a", "base_b", "post_a", "post_b"])
def test_invalid_item_in_any_snapshot_is_inconclusive_never_match(where, bad):
    snaps = {"base_a": snap(), "base_b": snap(), "post_a": snap(), "post_b": snap(*EFFECT)}
    snaps[where] = LaneSnapshot(True, snaps[where].items + (bad,))
    result = compare_ab(snaps["base_a"], snaps["base_b"], snaps["post_a"], snaps["post_b"],
                        ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE
    assert (result.extra_count, result.missing_count) == (0, 0)


@pytest.mark.parametrize("bad", BAD_ITEMS, ids=BAD_IDS)
@pytest.mark.parametrize("side", ["added", "removed"])
def test_invalid_item_in_the_expected_differences_is_inconclusive(side, bad):
    expected = (ExpectedDifferences(EFFECT + (bad,)) if side == "added"
                else ExpectedDifferences(EFFECT, (bad,)))
    result = compare_ab(snap(), snap(), snap(), snap(*EFFECT), expected)
    assert result.status is S.INCONCLUSIVE


def test_an_unreadable_value_cannot_be_hidden_by_an_equal_unreadable_value_on_the_other_side():
    # Two identical garbage movement rows would cancel in a signed multiset; they must not.
    garbage = DiffItem("movement", "K", "garbage")
    result = compare_ab(snap(garbage), snap(), snap(garbage), snap(garbage),
                        ExpectedDifferences())
    assert result.status is S.INCONCLUSIVE


def test_non_container_items_are_inconclusive():
    for items in (None, "abc", {DOC}, iter(EFFECT), 5):
        bad = LaneSnapshot(True, items)  # type: ignore[arg-type]
        result = compare_ab(snap(), snap(), snap(), bad, ExpectedDifferences())
        assert result.status is S.INCONCLUSIVE, items


def test_non_expected_differences_object_is_inconclusive():
    for bad in (None, EFFECT, {"added": EFFECT}):
        result = compare_ab(snap(), snap(), snap(), snap(*EFFECT), bad)  # type: ignore[arg-type]
        assert result.status is S.INCONCLUSIVE


@pytest.mark.parametrize("value", ["0", "0.00", "-5", "-0.01", "123456789012345678.123456789"])
@pytest.mark.parametrize("kind", ["movement", "balance"])
def test_well_formed_decimal_values_are_accepted(kind, value):
    item = DiffItem(kind, "K", value)
    assert compare((item,), expected_added=(item,)).status is S.MATCH


def test_document_items_may_have_an_empty_value_and_carry_no_decimal_requirement():
    item = DiffItem("document", "DOC-1", "")
    assert compare((item,), expected_added=(item,)).status is S.MATCH


def test_via_readers_invalid_item_from_a_lane_is_inconclusive():
    bad = DiffItem("movement", "K", "not-a-number")
    reader = FakeLaneReader({"A": snap(), "B": snap(*EFFECT, bad)})
    result = compare_via_readers(reader, "A", "B", (snap(), snap()), ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


def test_via_readers_non_snapshot_from_a_lane_is_inconclusive():
    reader = FakeLaneReader({"A": snap(), "B": None})
    result = compare_via_readers(reader, "A", "B", (snap(), snap()), ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


def test_via_readers_invalid_item_in_the_baseline_is_inconclusive():
    bad_baseline = LaneSnapshot(True, (DiffItem("bogus", "K"),))
    reader = FakeLaneReader({"A": snap(), "B": snap(*EFFECT)})
    result = compare_via_readers(reader, "A", "B", (bad_baseline, snap()),
                                 ExpectedDifferences(EFFECT))
    assert result.status is S.INCONCLUSIVE


# --- CR-388: balance items are deltas (compared like any other signed fact) ----------------------------

def test_balance_delta_is_compared_by_exact_value_and_net_of_the_baseline():
    assert compare(EFFECT).status is S.MATCH
    wrong = DiffItem("balance", BAL.key, "21.83")
    result = compare((DOC, MOV1, MOV2, wrong))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (1, 1)


def test_an_absolute_balance_that_includes_the_pre_operation_amount_is_not_a_match():
    # The reader must supply the DELTA 21.82; an absolute balance (100.00 + 21.82) differs.
    absolute = DiffItem("balance", BAL.key, "121.82")
    result = compare((DOC, MOV1, MOV2, absolute))
    assert result.status is S.MISMATCH
    assert (result.extra_count, result.missing_count) == (1, 1)
