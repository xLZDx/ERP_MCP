"""Behavioral tests for drift classification: failure must never look like drift."""
from __future__ import annotations

import pytest

from business_ai_gateway.phase2.drift import CaptureOutcome, FailureCounter, classify
from business_ai_gateway.phase2.drift import CaptureOutcomeKind as K
from business_ai_gateway.phase2.drift import DriftEventKind as E
from business_ai_gateway.phase2.temporal import EventKind

H1 = "a" * 64
H2 = "b" * 64
NON_DRIFT_KINDS = [K.OK_PARTIAL, K.TIMEOUT, K.OUTAGE, K.ACCESS_DENIED, K.CURSOR_LOST]


@pytest.mark.parametrize("kind,event", [
    (K.OK_PARTIAL, E.GAP),
    (K.TIMEOUT, E.SOURCE_UNAVAILABLE),
    (K.OUTAGE, E.SOURCE_UNAVAILABLE),
    (K.ACCESS_DENIED, E.ACCESS_DENIED),
    (K.CURSOR_LOST, E.RESNAPSHOT_REQUIRED),
])
def test_failure_outcomes_map_to_exact_single_event(kind, event):
    decision = classify(CaptureOutcome(kind), H1)
    assert decision.events == (event,)


@pytest.mark.parametrize("kind", NON_DRIFT_KINDS)
@pytest.mark.parametrize("previous", [None, H1])
def test_failures_never_drift_never_remove_never_move_baseline(kind, previous):
    decision = classify(CaptureOutcome(kind), previous)
    assert E.STRUCTURAL_DRIFT not in decision.events
    assert decision.removal_permitted is False
    assert decision.accepted_hash == previous
    assert decision.baseline_established is False


def test_complete_capture_with_different_hash_is_drift_and_advances_baseline():
    decision = classify(CaptureOutcome(K.OK_COMPLETE, H2), H1)
    assert decision.events == (E.STRUCTURAL_DRIFT,)
    assert decision.accepted_hash == H2
    assert decision.removal_permitted is True


def test_complete_capture_with_same_hash_is_quiet():
    decision = classify(CaptureOutcome(K.OK_COMPLETE, H1), H1)
    assert decision.events == ()
    assert decision.accepted_hash == H1


def test_first_complete_capture_establishes_baseline_without_drift():
    decision = classify(CaptureOutcome(K.OK_COMPLETE, H1), None)
    assert decision.events == ()
    assert decision.accepted_hash == H1
    assert decision.baseline_established is True


def test_schema_changed_with_hash_is_compared_not_assumed_drift():
    assert classify(CaptureOutcome(K.SCHEMA_CHANGED, H1), H1).events == ()
    assert classify(CaptureOutcome(K.SCHEMA_CHANGED, H2), H1).events == (E.STRUCTURAL_DRIFT,)


def test_schema_changed_or_complete_without_hash_requires_resnapshot_and_keeps_baseline():
    for kind in (K.SCHEMA_CHANGED, K.OK_COMPLETE):
        decision = classify(CaptureOutcome(kind), H1)
        assert decision.events == (E.RESNAPSHOT_REQUIRED,)
        assert decision.accepted_hash == H1
        assert decision.removal_permitted is False


@pytest.mark.parametrize("kind", NON_DRIFT_KINDS)
def test_hash_on_incomplete_outcome_is_rejected(kind):
    with pytest.raises(ValueError, match="HASH_NOT_ALLOWED_FOR_INCOMPLETE_OUTCOME"):
        CaptureOutcome(kind, H2)


@pytest.mark.parametrize("bad", ["", "xyz", "A" * 64, "a" * 63, 5])
def test_malformed_hash_rejected(bad):
    with pytest.raises(ValueError, match="STRUCTURAL_HASH_INVALID"):
        CaptureOutcome(K.OK_COMPLETE, bad)
    with pytest.raises(ValueError, match="PREVIOUS_HASH_INVALID"):
        classify(CaptureOutcome(K.OK_COMPLETE, H1), bad)


def test_invalid_kind_and_outcome_types_rejected():
    with pytest.raises(TypeError, match="OUTCOME_KIND_INVALID"):
        CaptureOutcome("TIMEOUT")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="OUTCOME_REQUIRED"):
        classify("TIMEOUT", H1)  # type: ignore[arg-type]


def test_event_names_stay_aligned_with_temporal_ledger_kinds():
    assert E.GAP.value == EventKind.GAP.value
    assert E.SOURCE_UNAVAILABLE.value == EventKind.SOURCE_UNAVAILABLE.value


# ---- consecutive failure counting -------------------------------------------------

def test_failures_increment_and_escalate_at_threshold():
    counter = FailureCounter(threshold=3)
    flags = []
    for kind in (K.TIMEOUT, K.OUTAGE, K.ACCESS_DENIED):
        counter = counter.advance(kind)
        flags.append(counter.escalate)
    assert counter.consecutive_failures == 3
    assert flags == [False, False, True]


def test_cursor_loss_counts_as_failure():
    assert FailureCounter().advance(K.CURSOR_LOST).consecutive_failures == 1


def test_complete_success_resets_counter():
    counter = FailureCounter(2, 3).advance(K.OK_COMPLETE)
    assert counter.consecutive_failures == 0
    assert FailureCounter(2, 3).advance(K.SCHEMA_CHANGED).consecutive_failures == 0


def test_partial_is_neutral_neither_failure_nor_reset():
    counter = FailureCounter(2, 3)
    assert counter.advance(K.OK_PARTIAL).consecutive_failures == 2


def test_counter_does_not_mutate_drift_state_and_is_immutable():
    before = classify(CaptureOutcome(K.TIMEOUT), H1)
    counter = FailureCounter(threshold=1).advance(K.TIMEOUT)
    after = classify(CaptureOutcome(K.TIMEOUT), H1)
    assert counter.escalate is True
    assert before == after
    assert after.accepted_hash == H1
    with pytest.raises(AttributeError):
        counter.consecutive_failures = 0  # type: ignore[misc]


@pytest.mark.parametrize("args", [(-1, 3), (0, 0), (0, -2), (True, 3), (0, True), (0, 1.5)])
def test_counter_rejects_invalid_state(args):
    with pytest.raises(ValueError, match="FAILURE_COUNTER_INVALID"):
        FailureCounter(*args)


def test_counter_rejects_non_enum_kind():
    with pytest.raises(TypeError, match="OUTCOME_KIND_INVALID"):
        FailureCounter().advance("TIMEOUT")  # type: ignore[arg-type]
