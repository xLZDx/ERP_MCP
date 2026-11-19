"""Focused contract coverage for the S18-06 rights-matrix read boundary."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from business_ai_gateway.phase2.rights_matrix_drift import (
    ApprovedRightsBaseline,
    ObservedRightsSnapshot,
    RightGrant,
    RightsAvailability,
    RightsDifferenceKind,
    RightsMatrixInputError,
    RightsMatrixStatus,
    compare_rights,
    iter_rights_periodically,
    scan_rights_once,
)


NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def grant(principal: str, object_id: str, privilege: str) -> RightGrant:
    return RightGrant(principal, object_id, privilege)


def baseline(grants: tuple[RightGrant, ...]) -> ApprovedRightsBaseline:
    return ApprovedRightsBaseline("source-a", "base-a", "approval-17", NOW, grants)


def snapshot(
    grants: tuple[RightGrant, ...], *, source_id: str = "source-a", base_id: str = "base-a",
    availability: RightsAvailability = RightsAvailability.COMPLETE,
) -> ObservedRightsSnapshot:
    return ObservedRightsSnapshot(
        source_id, base_id, "snapshot-29", NOW, availability, grants)


def test_complete_snapshot_reports_added_removed_and_changed_in_stable_order():
    approved = baseline((
        grant("alice", "catalog", "READ"),
        grant("bob", "payment", "READ"),
        grant("bob", "payment", "WRITE"),
        grant("carol", "register", "READ"),
    ))
    current = snapshot((
        grant("alice", "catalog", "READ"),
        grant("alice", "catalog", "WRITE"),
        grant("bob", "payment", "WRITE"),
        grant("dana", "report", "READ"),
    ))

    result = compare_rights(approved, current)

    assert result.status is RightsMatrixStatus.COMPARABLE
    assert result.reason is None
    assert [
        (d.kind, d.principal_id, d.object_id, d.prior_privileges, d.observed_privileges)
        for d in result.differences
    ] == [
        (RightsDifferenceKind.CHANGED, "alice", "catalog", ("READ",), ("READ", "WRITE")),
        (RightsDifferenceKind.CHANGED, "bob", "payment", ("READ", "WRITE"), ("WRITE",)),
        (RightsDifferenceKind.REMOVED, "carol", "register", ("READ",), ()),
        (RightsDifferenceKind.ADDED, "dana", "report", (), ("READ",)),
    ]


@pytest.mark.parametrize("scope", [
    {"source_id": "source-b", "base_id": "base-a"},
    {"source_id": "source-a", "base_id": "base-b"},
])
def test_scope_mismatch_is_not_comparable_and_never_infers_removed_grants(scope):
    approved = baseline((grant("alice", "catalog", "READ"),))
    current = snapshot((), **scope)

    result = compare_rights(approved, current)

    assert result.status is RightsMatrixStatus.NOT_COMPARABLE
    assert result.reason == "SCOPE_MISMATCH"
    assert result.differences == ()


@pytest.mark.parametrize("availability", [
    RightsAvailability.INCOMPLETE,
    RightsAvailability.UNAVAILABLE,
    RightsAvailability.ACCESS_DENIED,
])
def test_non_complete_snapshot_never_produces_drift_or_inferred_removal(availability):
    approved = baseline((grant("alice", "catalog", "READ"),))
    current = snapshot((), availability=availability)

    result = compare_rights(approved, current)

    assert result.status is RightsMatrixStatus.NOT_COMPARABLE
    assert result.reason == availability.value
    assert result.differences == ()


def test_reader_receives_only_exact_source_and_base_and_returns_drift():
    expected = snapshot((grant("alice", "catalog", "WRITE"),))

    class Reader:
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def read_current(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return expected

    reader = Reader()
    approved = baseline((grant("alice", "catalog", "READ"),))

    result = scan_rights_once(approved, reader)

    assert reader.calls == [(("source-a", "base-a"), {})]
    assert result.status is RightsMatrixStatus.COMPARABLE
    assert [(d.kind, d.prior_privileges, d.observed_privileges) for d in result.differences] == [
        (RightsDifferenceKind.CHANGED, ("READ",), ("WRITE",)),
    ]


@pytest.mark.parametrize("reader, reason", [
    (type("RaisingReader", (), {"read_current": lambda self, *_: (_ for _ in ()).throw(
        RuntimeError("private credential or source payload"))})(), "READ_FAILED"),
    (type("MalformedReader", (), {"read_current": lambda self, *_: {
        "source_id": "source-a", "base_id": "base-a", "grants": []}})(), "SNAPSHOT_INVALID"),
])
def test_reader_errors_are_sanitized_and_never_report_removals(reader, reason):
    approved = baseline((grant("alice", "catalog", "READ"),))

    result = scan_rights_once(approved, reader)

    assert result.status is RightsMatrixStatus.NOT_COMPARABLE
    assert result.reason == reason
    assert result.differences == ()
    assert result.approval_ref == "approval-17"
    assert result.snapshot_ref is None
    assert "private credential" not in repr(result)


def test_periodic_scans_are_ordered_sequential_and_use_the_requested_interval():
    order: list[str] = []
    stop = {"requested": False}

    class Reader:
        active = False
        calls = 0

        def read_current(self, source_id: str, base_id: str) -> ObservedRightsSnapshot:
            assert not self.active
            self.active = True
            self.calls += 1
            order.append(f"read:{self.calls}:{source_id}:{base_id}")
            self.active = False
            return snapshot((grant("alice", "catalog", "READ"),))

    reader = Reader()

    def sleep(seconds: float) -> None:
        assert not reader.active
        order.append(f"sleep:{seconds}")

    scans = iter_rights_periodically(
        baseline(()), reader, 30, should_stop=lambda: stop["requested"], sleep=sleep)

    first = next(scans)
    order.append("consume:1")
    second = next(scans)
    order.append("consume:2")
    stop["requested"] = True
    with pytest.raises(StopIteration):
        next(scans)

    assert first.status is RightsMatrixStatus.COMPARABLE
    assert second.status is RightsMatrixStatus.COMPARABLE
    assert reader.calls == 2
    assert order == [
        "read:1:source-a:base-a", "consume:1", "sleep:30.0",
        "read:2:source-a:base-a", "consume:2",
    ]


def test_periodic_stop_before_first_scan_performs_no_read_or_sleep():
    class Reader:
        calls = 0

        def read_current(self, source_id: str, base_id: str) -> ObservedRightsSnapshot:
            self.calls += 1
            return snapshot(())

    reader = Reader()
    sleeps: list[float] = []
    scans = iter_rights_periodically(
        baseline(()), reader, 10, should_stop=lambda: True, sleep=sleeps.append)

    with pytest.raises(StopIteration):
        next(scans)

    assert reader.calls == 0
    assert sleeps == []


def test_periodic_stop_after_scan_yields_result_then_stops_without_sleep():
    state = {"stop": False}

    class Reader:
        calls = 0

        def read_current(self, source_id: str, base_id: str) -> ObservedRightsSnapshot:
            self.calls += 1
            state["stop"] = True
            return snapshot(())

    reader = Reader()
    sleeps: list[float] = []
    scans = iter_rights_periodically(
        baseline(()), reader, 10, should_stop=lambda: state["stop"], sleep=sleeps.append)

    result = next(scans)
    assert result.status is RightsMatrixStatus.COMPARABLE
    with pytest.raises(StopIteration):
        next(scans)

    assert reader.calls == 1
    assert sleeps == []


@pytest.mark.parametrize("interval", [
    True, False, float("nan"), float("inf"), float("-inf"), 0.099, 86_400.001,
])
def test_periodic_interval_rejects_bool_nonfinite_and_out_of_range_values(interval):
    scans = iter_rights_periodically(
        baseline(()), object(), interval, should_stop=lambda: True, sleep=lambda _: None)

    with pytest.raises(RightsMatrixInputError) as refusal:
        next(scans)

    assert str(refusal.value) == RightsMatrixInputError.INVALID_SCAN_INTERVAL


@pytest.mark.parametrize("interval", [0.1, 86_400])
def test_periodic_interval_accepts_both_inclusive_bounds(interval):
    class Reader:
        def read_current(self, source_id: str, base_id: str) -> ObservedRightsSnapshot:
            return snapshot(())

    state = {"stop": False}
    scans = iter_rights_periodically(
        baseline(()), Reader(), interval,
        should_stop=lambda: state["stop"], sleep=lambda _: state.__setitem__("stop", True))

    assert next(scans).status is RightsMatrixStatus.COMPARABLE
    with pytest.raises(StopIteration):
        next(scans)


def test_periodic_should_stop_and_sleep_callback_errors_propagate_unchanged():
    reader_calls: list[str] = []

    class Reader:
        def read_current(self, source_id: str, base_id: str) -> ObservedRightsSnapshot:
            reader_calls.append("read")
            return snapshot(())

    stop_error = RuntimeError("stop callback detail")
    stopped = iter_rights_periodically(
        baseline(()), Reader(), 5,
        should_stop=lambda: (_ for _ in ()).throw(stop_error), sleep=lambda _: None)
    with pytest.raises(RuntimeError) as stop_failure:
        next(stopped)
    assert stop_failure.value is stop_error
    assert reader_calls == []

    sleep_error = RuntimeError("sleep callback detail")
    state = {"stop": False}
    scans = iter_rights_periodically(
        baseline(()), Reader(), 5, should_stop=lambda: state["stop"],
        sleep=lambda _: (_ for _ in ()).throw(sleep_error))
    assert next(scans).status is RightsMatrixStatus.COMPARABLE
    with pytest.raises(RuntimeError) as sleep_failure:
        next(scans)
    assert sleep_failure.value is sleep_error
    assert reader_calls == ["read"]


def test_closing_periodic_generator_after_yield_stops_without_another_scan_or_sleep():
    class Reader:
        calls = 0

        def read_current(self, source_id: str, base_id: str) -> ObservedRightsSnapshot:
            self.calls += 1
            return snapshot(())

    reader = Reader()
    sleeps: list[float] = []
    scans = iter_rights_periodically(
        baseline(()), reader, 5, should_stop=lambda: False, sleep=sleeps.append)

    assert next(scans).status is RightsMatrixStatus.COMPARABLE
    scans.close()

    with pytest.raises(StopIteration):
        next(scans)
    assert reader.calls == 1
    assert sleeps == []
