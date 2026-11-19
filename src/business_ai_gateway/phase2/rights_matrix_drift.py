"""Pure comparison of approved and observed rights-matrix snapshots.

The caller owns source authentication, snapshot completeness, approval authority,
and provenance validation. This module performs no source reads or grant changes.
"""
from __future__ import annotations

import inspect
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable, Iterator, Protocol

from ._identity import clean_identity
from .ops_types import is_aware_datetime, is_identity_text

__all__ = [
    "ApprovedRightsBaseline", "ObservedRightsSnapshot", "RightsAvailability",
    "RightsDifference", "RightsDifferenceKind", "RightsMatrixInputError",
    "RightsMatrixStatus", "RightsMatrixDriftResult", "RightsMatrixReaderPort", "RightGrant",
    "compare_rights", "iter_rights_periodically", "scan_rights_once",
]

MAX_RIGHTS_ROWS = 10_000
MAX_SCOPE_ID_CHARS = 256
MAX_REFERENCE_CHARS = 256
MAX_PRINCIPAL_CHARS = 256
MAX_OBJECT_CHARS = 256
MAX_PRIVILEGE_CHARS = 64
MIN_SCAN_INTERVAL_SECONDS = 0.1
MAX_SCAN_INTERVAL_SECONDS = 86_400.0
_PRIVILEGE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z", re.ASCII)


class RightsMatrixInputError(ValueError):
    """Stable validation failures for malformed caller-supplied snapshots."""

    INVALID_GRANT = "INVALID_GRANT"
    DUPLICATE_GRANT = "DUPLICATE_GRANT"
    INVALID_SCOPE = "INVALID_SCOPE"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_AVAILABILITY = "INVALID_AVAILABILITY"
    ROW_LIMIT_EXCEEDED = "ROW_LIMIT_EXCEEDED"
    INVALID_SNAPSHOT = "INVALID_SNAPSHOT"
    INVALID_SCAN_INTERVAL = "INVALID_SCAN_INTERVAL"
    INVALID_PERIODIC_CONTROL = "INVALID_PERIODIC_CONTROL"


class RightsAvailability(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"
    ACCESS_DENIED = "ACCESS_DENIED"


class RightsMatrixStatus(StrEnum):
    COMPARABLE = "COMPARABLE"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class RightsDifferenceKind(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"


@dataclass(frozen=True, slots=True)
class RightGrant:
    """One privilege granted to a normalized principal on a normalized object."""

    principal_id: str
    object_id: str
    privilege: str

    def __post_init__(self) -> None:
        principal = clean_identity(self.principal_id)
        object_id = clean_identity(self.object_id)
        if (type(self.principal_id) is not str or len(self.principal_id) > MAX_PRINCIPAL_CHARS
                or not principal or type(self.object_id) is not str
                or len(self.object_id) > MAX_OBJECT_CHARS or not object_id
                or type(self.privilege) is not str or not self.privilege
                or len(self.privilege) > MAX_PRIVILEGE_CHARS
                or not self.privilege.isascii()
                or not _PRIVILEGE.fullmatch(self.privilege.upper())):
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_GRANT)
        object.__setattr__(self, "principal_id", principal)
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "privilege", self.privilege.upper())


def _validate_scope(source_id: object, base_id: object) -> None:
    if (not is_identity_text(source_id) or len(source_id) > MAX_SCOPE_ID_CHARS
            or not is_identity_text(base_id) or len(base_id) > MAX_SCOPE_ID_CHARS):
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SCOPE)


def _validate_reference(value: object) -> None:
    if not is_identity_text(value) or len(value) > MAX_REFERENCE_CHARS:
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_REFERENCE)


def _normalize_grants(value: object) -> tuple[RightGrant, ...]:
    if type(value) is not tuple:
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SNAPSHOT)
    if len(value) > MAX_RIGHTS_ROWS:
        raise RightsMatrixInputError(RightsMatrixInputError.ROW_LIMIT_EXCEEDED)
    normalized: list[RightGrant] = []
    seen: set[tuple[str, str, str]] = set()
    for grant in value:
        if type(grant) is not RightGrant:
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_GRANT)
        # Reconstruct to reject forged/uninitialized frozen instances at this boundary.
        try:
            checked = RightGrant(grant.principal_id, grant.object_id, grant.privilege)
        except (AttributeError, TypeError, ValueError):
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_GRANT) from None
        key = (checked.principal_id, checked.object_id, checked.privilege)
        if key in seen:
            raise RightsMatrixInputError(RightsMatrixInputError.DUPLICATE_GRANT)
        seen.add(key)
        normalized.append(checked)
    return tuple(sorted(normalized, key=lambda row: (
        row.principal_id, row.object_id, row.privilege)))


@dataclass(frozen=True, slots=True)
class ApprovedRightsBaseline:
    """Caller-approved baseline. ``approval_ref`` is provenance, not verified authority here."""

    source_id: str
    base_id: str
    approval_ref: str
    approved_at: datetime
    grants: tuple[RightGrant, ...]

    def __post_init__(self) -> None:
        _validate_scope(self.source_id, self.base_id)
        _validate_reference(self.approval_ref)
        if not is_aware_datetime(self.approved_at):
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_TIMESTAMP)
        object.__setattr__(self, "grants", _normalize_grants(self.grants))


@dataclass(frozen=True, slots=True)
class ObservedRightsSnapshot:
    """Caller-supplied current snapshot; completeness and source trust remain caller-owned."""

    source_id: str
    base_id: str
    snapshot_ref: str
    observed_at: datetime
    availability: RightsAvailability
    grants: tuple[RightGrant, ...]

    def __post_init__(self) -> None:
        _validate_scope(self.source_id, self.base_id)
        _validate_reference(self.snapshot_ref)
        if not is_aware_datetime(self.observed_at):
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_TIMESTAMP)
        if type(self.availability) is not RightsAvailability:
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_AVAILABILITY)
        object.__setattr__(self, "grants", _normalize_grants(self.grants))


class RightsMatrixReaderPort(Protocol):
    """Read-only source boundary; authentication and adapter configuration belong to the caller."""

    def read_current(self, source_id: str, base_id: str) -> ObservedRightsSnapshot: ...


@dataclass(frozen=True, slots=True)
class RightsDifference:
    kind: RightsDifferenceKind
    principal_id: str
    object_id: str
    prior_privileges: tuple[str, ...]
    observed_privileges: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RightsMatrixDriftResult:
    status: RightsMatrixStatus
    reason: str | None
    differences: tuple[RightsDifference, ...]
    approval_ref: str | None
    snapshot_ref: str | None


def _group(grants: tuple[RightGrant, ...]) -> dict[tuple[str, str], tuple[str, ...]]:
    groups: dict[tuple[str, str], set[str]] = {}
    for grant in grants:
        groups.setdefault((grant.principal_id, grant.object_id), set()).add(grant.privilege)
    return {key: tuple(sorted(privileges)) for key, privileges in groups.items()}


def compare_rights(baseline: ApprovedRightsBaseline,
                   observed: ObservedRightsSnapshot) -> RightsMatrixDriftResult:
    """Compare exact trusted scopes; only complete snapshots can imply removals.

    Trust in the approved baseline, current-source authentication, completeness and
    both provenance references is supplied by the caller and is not cryptographically
    verified by this pure function.
    """
    if type(baseline) is not ApprovedRightsBaseline or type(observed) is not ObservedRightsSnapshot:
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SNAPSHOT)
    try:
        baseline = ApprovedRightsBaseline(
            baseline.source_id, baseline.base_id, baseline.approval_ref,
            baseline.approved_at, baseline.grants)
        observed = ObservedRightsSnapshot(
            observed.source_id, observed.base_id, observed.snapshot_ref,
            observed.observed_at, observed.availability, observed.grants)
    except (AttributeError, TypeError, ValueError):
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SNAPSHOT) from None
    reason: str | None = None
    if baseline.source_id != observed.source_id or baseline.base_id != observed.base_id:
        reason = "SCOPE_MISMATCH"
    elif observed.availability is not RightsAvailability.COMPLETE:
        reason = observed.availability.value
    if reason is not None:
        return RightsMatrixDriftResult(
            RightsMatrixStatus.NOT_COMPARABLE, reason, (), baseline.approval_ref, observed.snapshot_ref)

    prior, current = _group(baseline.grants), _group(observed.grants)
    differences: list[RightsDifference] = []
    for principal_id, object_id in sorted(prior.keys() | current.keys()):
        key = (principal_id, object_id)
        before, after = prior.get(key, ()), current.get(key, ())
        if not before:
            kind = RightsDifferenceKind.ADDED
        elif not after:
            kind = RightsDifferenceKind.REMOVED
        elif before != after:
            kind = RightsDifferenceKind.CHANGED
        else:
            continue
        differences.append(RightsDifference(kind, principal_id, object_id, before, after))
    return RightsMatrixDriftResult(
        RightsMatrixStatus.COMPARABLE, None, tuple(differences),
        baseline.approval_ref, observed.snapshot_ref)


def scan_rights_once(baseline: ApprovedRightsBaseline,
                     reader: RightsMatrixReaderPort) -> RightsMatrixDriftResult:
    """Read one current snapshot through the caller-configured read-only port and compare it.

    This function does not schedule periodic work. The caller owns scheduling, reader
    authentication and the concrete source adapter; no 1C adapter is configured here.
    Reader exceptions and malformed responses are sanitized and never imply removals.
    """
    try:
        if type(baseline) is not ApprovedRightsBaseline:
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SNAPSHOT)
        trusted_baseline = ApprovedRightsBaseline(
            baseline.source_id, baseline.base_id, baseline.approval_ref,
            baseline.approved_at, baseline.grants)
    except (AttributeError, TypeError, ValueError):
        return RightsMatrixDriftResult(
            RightsMatrixStatus.NOT_COMPARABLE, "BASELINE_INVALID", (), None, None)

    try:
        read_current = getattr(reader, "read_current", None)
        if not callable(read_current):
            raise TypeError("READER_UNAVAILABLE")
        observed = read_current(trusted_baseline.source_id, trusted_baseline.base_id)
    except Exception:  # noqa: BLE001 - source exception text can contain secrets or business data
        return RightsMatrixDriftResult(
            RightsMatrixStatus.NOT_COMPARABLE, "READ_FAILED", (),
            trusted_baseline.approval_ref, None)
    if type(observed) is not ObservedRightsSnapshot:
        return RightsMatrixDriftResult(
            RightsMatrixStatus.NOT_COMPARABLE, "SNAPSHOT_INVALID", (),
            trusted_baseline.approval_ref, None)
    try:
        return compare_rights(trusted_baseline, observed)
    except (AttributeError, TypeError, ValueError):
        return RightsMatrixDriftResult(
            RightsMatrixStatus.NOT_COMPARABLE, "SNAPSHOT_INVALID", (),
            trusted_baseline.approval_ref, None)


def iter_rights_periodically(
    baseline: ApprovedRightsBaseline,
    reader: RightsMatrixReaderPort,
    interval_seconds: int | float,
    *,
    should_stop: Callable[[], bool],
    sleep: Callable[[float], None],
) -> Iterator[RightsMatrixDriftResult]:
    """Yield read-only comparisons sequentially until the caller requests a stop.

    This is a caller-driven scheduling primitive, not a service/runtime integration.
    Each iteration finishes ``scan_rights_once`` before sleeping, so reads never
    overlap. ``sleep`` must be a synchronous callback. The caller owns the source
    adapter, authentication, persistence and reporting. Exceptions from the
    callbacks and generator cancellation propagate.
    A stop request is observed between scans; it cannot interrupt a blocking reader.
    """
    if type(interval_seconds) not in (int, float):
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SCAN_INTERVAL)
    try:
        interval = float(interval_seconds)
    except (OverflowError, ValueError):
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SCAN_INTERVAL) from None
    if (not math.isfinite(interval)
            or not MIN_SCAN_INTERVAL_SECONDS <= interval <= MAX_SCAN_INTERVAL_SECONDS):
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_SCAN_INTERVAL)
    if not callable(should_stop) or not callable(sleep):
        raise RightsMatrixInputError(RightsMatrixInputError.INVALID_PERIODIC_CONTROL)

    while not should_stop():
        yield scan_rights_once(baseline, reader)
        if should_stop():
            return
        sleep_result = sleep(interval)
        if inspect.isawaitable(sleep_result):
            if inspect.iscoroutine(sleep_result):
                sleep_result.close()
            raise RightsMatrixInputError(RightsMatrixInputError.INVALID_PERIODIC_CONTROL)
