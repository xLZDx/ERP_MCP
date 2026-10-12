"""Phase 2 drift classification: separates source failure from structural drift.

Pure functions over (capture outcome, previous accepted structural hash). Only a
COMPLETE successful capture whose structural hash differs from the accepted hash can
yield STRUCTURAL_DRIFT. Timeouts, outages, denied access, lost cursors and partial
scans are failures or gaps: they never yield drift, never advance the accepted hash and
never permit marking objects as removed.

Consecutive-failure counting is a separate value (FailureCounter) that feeds an
escalation flag; it is never part of, and never mutates, the drift decision's hash.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .temporal import EventKind

_HASH = re.compile(r"^[0-9a-f]{64}$")


class CaptureOutcomeKind(StrEnum):
    OK_COMPLETE = "OK_COMPLETE"
    OK_PARTIAL = "OK_PARTIAL"
    TIMEOUT = "TIMEOUT"
    OUTAGE = "OUTAGE"
    ACCESS_DENIED = "ACCESS_DENIED"
    CURSOR_LOST = "CURSOR_LOST"
    # A complete capture whose connector flagged a schema change; the hash decides.
    SCHEMA_CHANGED = "SCHEMA_CHANGED"


class DriftEventKind(StrEnum):
    GAP = EventKind.GAP.value
    SOURCE_UNAVAILABLE = EventKind.SOURCE_UNAVAILABLE.value
    ACCESS_DENIED = "ACCESS_DENIED"
    RESNAPSHOT_REQUIRED = "RESNAPSHOT_REQUIRED"
    STRUCTURAL_DRIFT = "STRUCTURAL_DRIFT"


_FAILURES = frozenset({
    CaptureOutcomeKind.TIMEOUT, CaptureOutcomeKind.OUTAGE,
    CaptureOutcomeKind.ACCESS_DENIED, CaptureOutcomeKind.CURSOR_LOST,
})
_HASH_BEARING = frozenset({CaptureOutcomeKind.OK_COMPLETE, CaptureOutcomeKind.SCHEMA_CHANGED})
_EVENT_FOR = {
    CaptureOutcomeKind.OK_PARTIAL: DriftEventKind.GAP,
    CaptureOutcomeKind.TIMEOUT: DriftEventKind.SOURCE_UNAVAILABLE,
    CaptureOutcomeKind.OUTAGE: DriftEventKind.SOURCE_UNAVAILABLE,
    CaptureOutcomeKind.ACCESS_DENIED: DriftEventKind.ACCESS_DENIED,
    CaptureOutcomeKind.CURSOR_LOST: DriftEventKind.RESNAPSHOT_REQUIRED,
}


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    kind: CaptureOutcomeKind
    structural_hash: str | None = None  # only for OK_COMPLETE / SCHEMA_CHANGED

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CaptureOutcomeKind):
            raise TypeError("OUTCOME_KIND_INVALID")
        if self.kind in _HASH_BEARING:
            if self.structural_hash is not None and not _valid_hash(self.structural_hash):
                raise ValueError("STRUCTURAL_HASH_INVALID")
        elif self.structural_hash is not None:
            raise ValueError("HASH_NOT_ALLOWED_FOR_INCOMPLETE_OUTCOME")


@dataclass(frozen=True, slots=True)
class DriftDecision:
    events: tuple[DriftEventKind, ...]
    accepted_hash: str | None  # hash to keep as the accepted baseline after this outcome
    baseline_established: bool = False
    # Removal inference is allowed only after a complete successful capture.
    removal_permitted: bool = False
    # Newly observed hash awaiting promotion. Set only together with STRUCTURAL_DRIFT;
    # classify() never advances accepted_hash on drift, only an explicit promotion does,
    # so a lost event/persist cannot make the drift vanish on the next identical capture.
    candidate_hash: str | None = None


def classify(outcome: CaptureOutcome, previous_accepted_hash: str | None) -> DriftDecision:
    """Map one capture outcome to drift events. Pure; does not touch failure counting."""
    if not isinstance(outcome, CaptureOutcome):
        raise TypeError("OUTCOME_REQUIRED")
    if previous_accepted_hash is not None and not _valid_hash(previous_accepted_hash):
        raise ValueError("PREVIOUS_HASH_INVALID")
    kind = outcome.kind
    if kind not in _HASH_BEARING:
        # Failure, outage or partial scan: keep baseline untouched, no drift, no removal.
        return DriftDecision((_EVENT_FOR[kind],), previous_accepted_hash)
    current = outcome.structural_hash
    if current is None:
        # A claimed complete capture without a hash cannot be compared: re-snapshot.
        return DriftDecision((DriftEventKind.RESNAPSHOT_REQUIRED,), previous_accepted_hash)
    if previous_accepted_hash is None:
        return DriftDecision((), current, baseline_established=True, removal_permitted=True)
    if current != previous_accepted_hash:
        return DriftDecision((DriftEventKind.STRUCTURAL_DRIFT,), previous_accepted_hash,
                             removal_permitted=True, candidate_hash=current)
    return DriftDecision((), previous_accepted_hash, removal_permitted=True)


@dataclass(frozen=True, slots=True)
class FailureCounter:
    consecutive_failures: int = 0
    threshold: int = 3

    def __post_init__(self) -> None:
        if (type(self.threshold) is not int or self.threshold < 1
                or type(self.consecutive_failures) is not int or self.consecutive_failures < 0):
            raise ValueError("FAILURE_COUNTER_INVALID")

    @property
    def escalate(self) -> bool:
        return self.consecutive_failures >= self.threshold

    def advance(self, kind: CaptureOutcomeKind) -> FailureCounter:
        """Failures increment; a successful complete capture resets; a partial scan is neutral."""
        if not isinstance(kind, CaptureOutcomeKind):
            raise TypeError("OUTCOME_KIND_INVALID")
        if kind in _FAILURES:
            return FailureCounter(self.consecutive_failures + 1, self.threshold)
        if kind in _HASH_BEARING:
            return FailureCounter(0, self.threshold)
        return self
