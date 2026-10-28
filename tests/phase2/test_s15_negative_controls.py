"""S15 epic E15-5: the negative-control set (19 distortions, all red, none VERIFIED/MATCH).

Synthetic fixtures only: no real-1C movement read exists in S15 (plan A14). No mutation runs and
no deliberately broken implementation: each control is justified by the exact finding or
signed-multiset count it must produce, which the assertions below pin down.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from erp_mcp_s15 import negative_controls as nc
from erp_mcp_s15.ab_compare import (
    ComparisonStatus,
    DiffItem,
    ExpectedDifferences,
    LaneSnapshot,
    compare_ab,
)
from erp_mcp_s15.labels import LABEL_MACHINE_VERIFIED
from erp_mcp_s15.negative_controls import (
    NEGATIVE_CONTROLS,
    Control,
    MovementOp,
    Mutation,
    run_all,
    run_control,
)
from erp_mcp_s15.verifier import SUPPORTED_SHAPE, VerificationStatus, verify_receipt
from tests.phase2._s15_fixtures import full_declared_types

PLAN_IDS = [
    "P01_WRONG_ACCOUNT", "P02_WRONG_COUNTERPARTY", "P03_WRONG_PERIOD",
    "P04_MISSING_MOVEMENT_LINE", "P05_SWAPPED_DT_KT", "P06_DISTORTED_AMOUNT",
    "P07_EXTRA_DOCUMENT", "P08_DUPLICATED_MOVEMENT_ROW",
]
FACT_IDS = [
    "F01_EMPTY_ENUMERATION", "F02_EMPTY_DATE", "F03_DATE_SHIFT_ONE_DAY", "F04_OWN_DATE_SHIFT",
    "F05_NON_RESOLVING_REFERENCE", "F06_DELETION_MARKED_REFERENCE", "F07_TOTAL_OFF_BY_VAT",
    "F08_POSTED_DRAFT", "F09_DELETION_MARKED_DRAFT", "F10_IDENTITY_TEXT_COERCED_TO_NUMBER",
    "F11_MARKER_CHANGED",
]
BY_ID = {c.control_id: c for c in NEGATIVE_CONTROLS}

# control id -> (finding path, finding code) the verifier must report, and nothing else.
FIELD_EXPECTATION = {
    "F01_EMPTY_ENUMERATION": ("line.vat_rate", "EMPTY"),
    "F02_EMPTY_DATE": ("header.incoming_date", "MISMATCH"),
    "F03_DATE_SHIFT_ONE_DAY": ("header.incoming_date", "MISMATCH"),
    "F04_OWN_DATE_SHIFT": ("document.date", "MISMATCH"),
    "F05_NON_RESOLVING_REFERENCE": ("line.nomenclature", "NOT_RESOLVING"),
    "F06_DELETION_MARKED_REFERENCE": ("header.counterparty", "DELETION_MARKED"),
    "F07_TOTAL_OFF_BY_VAT": ("document.total", "MISMATCH"),
    "F08_POSTED_DRAFT": ("document.posted", "MISMATCH"),
    "F09_DELETION_MARKED_DRAFT": ("document.deletion_mark", "MISMATCH"),
    "F10_IDENTITY_TEXT_COERCED_TO_NUMBER": ("header.incoming_number", "MISMATCH"),
    "F11_MARKER_CHANGED": ("marker.change_id", "MISMATCH"),
}
# control id -> (extra_count, missing_count) of the signed multiset against the expected effect.
MOVEMENT_EXPECTATION = {
    "P01_WRONG_ACCOUNT": (1, 1), "P02_WRONG_COUNTERPARTY": (1, 1), "P03_WRONG_PERIOD": (1, 1),
    "P04_MISSING_MOVEMENT_LINE": (0, 1), "P05_SWAPPED_DT_KT": (1, 1),
    "P06_DISTORTED_AMOUNT": (1, 1), "P07_EXTRA_DOCUMENT": (1, 0),
    "P08_DUPLICATED_MOVEMENT_ROW": (1, 0),
}
# What each note must talk about (lower-case substring of the observable that would differ).
NOTE_SUBJECT = {
    "P01_WRONG_ACCOUNT": "debit", "P02_WRONG_COUNTERPARTY": "counterparty",
    "P03_WRONG_PERIOD": "period", "P04_MISSING_MOVEMENT_LINE": "movement items",
    "P05_SWAPPED_DT_KT": "debit/credit", "P06_DISTORTED_AMOUNT": "value",
    "P07_EXTRA_DOCUMENT": "document", "P08_DUPLICATED_MOVEMENT_ROW": "movement item",
    "F01_EMPTY_ENUMERATION": "line.vat_rate", "F02_EMPTY_DATE": "header.incoming_date",
    "F03_DATE_SHIFT_ONE_DAY": "header.incoming_date", "F04_OWN_DATE_SHIFT": "own date",
    "F05_NON_RESOLVING_REFERENCE": "nomenclature", "F06_DELETION_MARKED_REFERENCE":
    "counterparty", "F07_TOTAL_OFF_BY_VAT": "total", "F08_POSTED_DRAFT": "posted",
    "F09_DELETION_MARKED_DRAFT": "deletion_mark",
    "F10_IDENTITY_TEXT_COERCED_TO_NUMBER": "header.incoming_number",
    "F11_MARKER_CHANGED": "change_id",
}


# --- the set itself -----------------------------------------------------------------------------

def test_the_set_has_exactly_19_controls_with_unique_ids():
    ids = [c.control_id for c in NEGATIVE_CONTROLS]
    assert len(ids) == 19
    assert len(set(ids)) == 19
    assert ids == PLAN_IDS + FACT_IDS


def test_groups_match_the_plan_split_and_kinds():
    plan = [c for c in NEGATIVE_CONTROLS if c.group == "plan"]
    facts = [c for c in NEGATIVE_CONTROLS if c.group == "s14_fact"]
    assert [c.control_id for c in plan] == PLAN_IDS
    assert [c.control_id for c in facts] == FACT_IDS
    assert all(c.kind == "movement" for c in plan)
    assert all(c.kind == "field" for c in facts)
    assert set(FIELD_EXPECTATION) | set(MOVEMENT_EXPECTATION) == set(BY_ID)


def test_every_plan_distortion_class_is_present():
    text = " ".join(c.control_id for c in NEGATIVE_CONTROLS)
    for token in ("ACCOUNT", "COUNTERPARTY", "PERIOD", "MISSING_MOVEMENT", "SWAPPED_DT_KT",
                  "AMOUNT", "EXTRA_DOCUMENT", "DUPLICATED_MOVEMENT", "EMPTY_ENUMERATION",
                  "EMPTY_DATE", "DATE_SHIFT", "NON_RESOLVING_REFERENCE", "TOTAL_OFF_BY_VAT",
                  "POSTED", "DELETION_MARKED"):
        assert token in text


# --- assertion: each control red, never VERIFIED / MATCH ----------------------------------------

@pytest.mark.parametrize("control", NEGATIVE_CONTROLS, ids=[c.control_id for c in NEGATIVE_CONTROLS])
def test_control_is_detected_red_and_never_verified(control):
    outcome = run_control(control)
    assert outcome.detected is True
    assert outcome.status == "MISMATCH"
    assert outcome.status not in {VerificationStatus.VERIFIED.value, ComparisonStatus.MATCH.value}
    assert outcome.status != "INCONCLUSIVE"
    assert outcome.control_id == control.control_id
    assert outcome.kind == control.kind
    assert outcome.label == LABEL_MACHINE_VERIFIED


@pytest.mark.parametrize("control", NEGATIVE_CONTROLS, ids=[c.control_id for c in NEGATIVE_CONTROLS])
def test_control_carries_a_non_empty_observable_note(control):
    assert control.observable_note.strip() != ""
    assert control.description.strip() != ""
    assert control.observable_note != control.description
    assert len(control.observable_note) >= 25
    note = control.observable_note.lower()
    # Names the value that would be observed in contrast to the correct one.
    assert any(word in note for word in ("instead of", "than the", "differ"))
    assert NOTE_SUBJECT[control.control_id] in note
    assert run_control(control).note == control.observable_note


def test_notes_are_unique_per_control():
    notes = [c.observable_note for c in NEGATIVE_CONTROLS]
    assert len(set(notes)) == len(notes)


# --- each control is red for its intended reason --------------------------------------------------

@pytest.mark.parametrize("control_id", sorted(FIELD_EXPECTATION))
def test_field_control_yields_exactly_the_intended_verifier_finding(control_id):
    reader = nc._apply_field(BY_ID[control_id])
    result = verify_receipt(reader, nc.BASELINE_DOCUMENT_REF, nc.baseline_expected_receipt(),
                            SUPPORTED_SHAPE, writer_declared_types=full_declared_types())
    path, code = FIELD_EXPECTATION[control_id]
    assert result.status is VerificationStatus.MISMATCH
    assert [(f.path, f.code) for f in result.findings] == [(path, code)]


@pytest.mark.parametrize("control_id", sorted(MOVEMENT_EXPECTATION))
def test_movement_control_yields_the_intended_signed_multiset_difference(control_id):
    empty = LaneSnapshot(True)
    observed = LaneSnapshot(True, tuple(nc._apply_movement(BY_ID[control_id].movement_ops)))
    expected = ExpectedDifferences(added=tuple(nc._baseline_items()))
    result = compare_ab(empty, empty, empty, observed, expected)
    extra, missing = MOVEMENT_EXPECTATION[control_id]
    assert result.status is ComparisonStatus.MISMATCH
    assert (result.extra_count, result.missing_count) == (extra, missing)


# --- run_all and the pre-flight baseline ----------------------------------------------------------

def test_run_all_reports_every_control_detected_on_a_valid_baseline():
    report = run_all()
    assert report.baseline_ok is True
    assert report.undetected == ()
    assert report.all_detected is True
    assert len(report.outcomes) == 19
    assert [o.control_id for o in report.outcomes] == PLAN_IDS + FACT_IDS
    assert all(o.detected and o.status == "MISMATCH" for o in report.outcomes)
    assert not any(o.status in {"VERIFIED", "MATCH"} for o in report.outcomes)
    assert all(o.note.strip() for o in report.outcomes)
    assert report.label == LABEL_MACHINE_VERIFIED


def test_the_undistorted_baseline_is_verified_and_matches_so_reds_are_caused_by_the_control():
    result = verify_receipt(nc._apply_field(Control("BASE", "plan", "", "")),
                            nc.BASELINE_DOCUMENT_REF, nc.baseline_expected_receipt(),
                            SUPPORTED_SHAPE, writer_declared_types=full_declared_types())
    assert result.status is VerificationStatus.VERIFIED
    assert nc._movement_status(()) == "MATCH"


def test_the_baseline_without_a_type_declaration_is_not_verified():
    # The production controls declare the oracle types themselves; without a declaration the
    # baseline could never be VERIFIED, which is why that declaration is part of the harness.
    result = verify_receipt(nc._apply_field(Control("BASE", "plan", "", "")),
                            nc.BASELINE_DOCUMENT_REF, nc.baseline_expected_receipt(),
                            SUPPORTED_SHAPE)
    assert result.status is VerificationStatus.PARTIAL_UNVERIFIED


def test_running_every_control_leaves_no_state_behind_that_could_distort_the_baseline():
    # A control that leaked into shared state would turn the next undistorted baseline red.
    run_all()
    after = run_control(Control("BASE_AFTER", "plan", "", "reads same instead of same"))
    assert after.status == "VERIFIED"
    assert nc._movement_status(()) == "MATCH"
    # The baseline values are pinned to literals, not compared with another fresh copy.
    document = nc.baseline_stored_document()
    assert document.total == Decimal("21.82")
    assert document.header["header.incoming_date"] == "2026-01-14T00:00:00"
    assert document.posted is False and document.deletion_mark is False


def test_mutating_a_returned_baseline_document_does_not_change_the_next_baseline():
    first = nc.baseline_stored_document()
    first.header["header.incoming_number"] = "tampered"
    first.lines[0]["line.quantity"] = 999
    second = nc.baseline_stored_document()
    assert second.header["header.incoming_number"] == "00123"
    assert second.lines[0]["line.quantity"] == 1
    assert run_control(Control("BASE_AFTER", "plan", "", "x")).status == "VERIFIED"


def test_repeated_run_all_gives_identical_reports():
    assert run_all() == run_all()


def test_a_control_that_distorts_nothing_is_reported_undetected():
    report = run_all((Control("NOOP_FIELD", "plan", "nothing", "reads same instead of same"),))
    assert report.baseline_ok is True
    assert report.undetected == ("NOOP_FIELD",)
    assert report.all_detected is False
    assert report.outcomes[0].status == "VERIFIED"
    assert report.outcomes[0].detected is False


def test_a_movement_control_that_distorts_nothing_is_reported_undetected():
    noop = Control("NOOP_MOVE", "plan", "x", "reads same instead of same",
                   movement_ops=(MovementOp("replace", 0, "amount", "20.00"),))
    report = run_all((noop,))
    assert report.undetected == ("NOOP_MOVE",)
    assert report.outcomes[0].status == "MATCH"
    assert report.all_detected is False


def test_a_control_that_makes_the_read_inconclusive_is_not_counted_as_detected():
    unread = Control("UNREAD_TOTAL", "s14_fact", "total unread", "reads None instead of 21.82",
                     mutations=(Mutation("doc", "total", None),))
    outcome = run_control(unread)
    assert outcome.status == "INCONCLUSIVE"
    assert outcome.detected is False
    assert run_all((unread,)).all_detected is False


def test_one_undetected_control_among_detected_ones_fails_the_whole_report():
    noop = Control("NOOP", "plan", "x", "reads a instead of b")
    report = run_all(NEGATIVE_CONTROLS + (noop,))
    assert report.undetected == ("NOOP",)
    assert report.all_detected is False
    assert len(report.outcomes) == 20


def test_unknown_mutation_target_or_movement_op_is_refused_not_ignored():
    with pytest.raises(ValueError, match="CONTROL_TARGET_INVALID"):
        run_control(Control("BAD_T", "plan", "x", "n", mutations=(Mutation("nowhere", "k", 1),)))
    with pytest.raises(ValueError, match="CONTROL_OP_INVALID"):
        run_control(Control("BAD_O", "plan", "x", "n", movement_ops=(MovementOp("explode"),)))


def test_synthetic_reader_refuses_a_foreign_document_ref():
    reader = nc._apply_field(Control("BASE", "plan", "", ""))
    result = verify_receipt(reader, "00000000-0000-4000-8000-00000000ffff",
                            nc.baseline_expected_receipt(), SUPPORTED_SHAPE)
    assert result.status is VerificationStatus.INCONCLUSIVE


def test_movement_baseline_has_a_document_two_movement_lines_and_a_balance():
    kinds = sorted(i.kind for i in nc._baseline_items())
    assert kinds == ["balance", "document", "movement", "movement"]
    assert isinstance(nc._baseline_items()[0], DiffItem)


# --- CR-388: required-set coverage ---------------------------------------------------------------------

def test_required_control_ids_are_exactly_the_plan_and_fact_prefixes():
    assert nc.REQUIRED_CONTROL_IDS == frozenset(
        {f"P{n:02d}" for n in range(1, 9)} | {f"F{n:02d}" for n in range(1, 12)})
    assert {i.split("_", 1)[0] for i in PLAN_IDS + FACT_IDS} == nc.REQUIRED_CONTROL_IDS


def test_the_full_set_covers_the_required_set():
    report = run_all()
    assert report.covers_required_set is True
    assert report.all_detected is True


def test_an_empty_control_set_is_not_all_detected():
    report = run_all(())
    assert report.baseline_ok is True
    assert report.outcomes == () and report.undetected == ()
    assert report.covers_required_set is False
    assert report.all_detected is False


@pytest.mark.parametrize("dropped", PLAN_IDS + FACT_IDS)
def test_a_set_missing_any_single_required_control_is_not_all_detected(dropped):
    partial = tuple(c for c in NEGATIVE_CONTROLS if c.control_id != dropped)
    report = run_all(partial)
    assert len(report.outcomes) == 18
    assert report.undetected == ()  # everything that ran was detected ...
    assert report.covers_required_set is False
    assert report.all_detected is False  # ... but the set is incomplete


def test_only_the_plan_group_or_only_the_fact_group_is_not_all_detected():
    for group in ("plan", "s14_fact"):
        subset = tuple(c for c in NEGATIVE_CONTROLS if c.group == group)
        report = run_all(subset)
        assert report.undetected == ()
        assert report.all_detected is False


def test_extra_controls_beyond_the_required_set_keep_coverage():
    extra = Control("X01_EXTRA", "plan", "x", "reads 60 instead of 41 debit",
                    movement_ops=(MovementOp("replace", 0, "debit", "60"),))
    report = run_all(NEGATIVE_CONTROLS + (extra,))
    assert report.covers_required_set is True and report.all_detected is True
    assert len(report.outcomes) == 20


def test_a_failed_pre_flight_baseline_makes_all_detected_false_even_if_every_control_is_red(
        monkeypatch):
    posted = dataclasses.replace(nc.baseline_stored_document(), posted=True)
    monkeypatch.setattr(nc, "baseline_stored_document", lambda: posted)
    report = run_all()
    assert report.baseline_ok is False
    assert report.all_detected is False
