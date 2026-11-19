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
    RightsMatrixStatus,
    compare_rights,
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
