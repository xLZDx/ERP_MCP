"""Phase 2 (S7/E3) Drive revision tracking and read-only history availability. Offline, no transport.

What this module decides
- ``RevisionTracker.observe``: a new ``revisionId`` of a known file yields a NEW UNATTESTED
  ``EvidenceCandidate`` (the existing drive_changes type). Any earlier attestation of that file stays
  true for its OWN revision only: it is reported as HISTORICAL and is never the verdict of the latest
  revision. Attestation itself lives in ``evidence_attestation.py``; here the caller only reports
  "revision R of file F was attested PASS" through ``record_attested`` (a mark, not an attestation).
- ``list_history``: reads revision ids through ``DrivePort.list_revisions`` (the only port method this
  module ever calls). ``FORBIDDEN_HISTORY`` or an empty/missing list is ``HISTORY_UNAVAILABLE`` with
  coverage ``CURRENT_ONLY`` (Viewer / readonly accounts need not have history). The module has no write,
  permission or keepForever path whatsoever (AST-checked in tests), and its result never carries
  provider text or any hint that a right could be raised.

Release-2 conventions: exact types, fixed outward codes, nothing echoed, ids preserved byte-exact,
hostile input yields a fixed refusal and never raises out of a public method (constructors validate
configuration and raise ``ValueError`` with a fixed code). No Release 1 / httpx / requests / socket.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum

from .drive_changes import EvidenceCandidate
from .drive_port import (
    DriveErrorCode,
    DrivePort,
    DrivePortError,
    DrivePortIdentity,
    RevisionMeta,
    is_valid_opaque_id,
    is_valid_scope_epoch,
)

__all__ = [
    "MAX_REVISIONS_PER_FILE",
    "MAX_TRACKED_FILES",
    "HistoryCoverage",
    "HistoryResult",
    "HistoryStatus",
    "ObservationOutcome",
    "RecordResult",
    "RevisionObservation",
    "RevisionState",
    "RevisionTracker",
    "RevisionVerdict",
    "list_history",
]

MAX_TRACKED_FILES = 100_000
MAX_REVISIONS_PER_FILE = 1_000


class HistoryStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    HISTORY_UNAVAILABLE = "HISTORY_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    CHECK_FAILED = "CHECK_FAILED"


class HistoryCoverage(StrEnum):
    LISTED = "LISTED"  # the ids the provider returned; completeness is not claimed
    CURRENT_ONLY = "CURRENT_ONLY"  # only the current revision can be reasoned about
    NONE = "NONE"


class ObservationOutcome(StrEnum):
    FIRST_SEEN = "FIRST_SEEN"
    NEW_REVISION = "NEW_REVISION"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    REFUSED = "REFUSED"


class RevisionState(StrEnum):
    UNATTESTED = "UNATTESTED"
    PASS_CURRENT = "PASS_CURRENT"
    PASS_HISTORICAL = "PASS_HISTORICAL"
    UNKNOWN = "UNKNOWN"


class RecordResult(StrEnum):
    RECORDED = "RECORDED"
    UNKNOWN_REVISION = "UNKNOWN_REVISION"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True, slots=True)
class HistoryResult:
    status: HistoryStatus
    coverage: HistoryCoverage
    reason: str  # fixed code, never provider text
    revision_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RevisionVerdict:
    state: RevisionState
    # the revision the (PASS) verdict is valid for; None when UNATTESTED/UNKNOWN
    applies_to_revision: str | None
    is_latest: bool


@dataclass(frozen=True, slots=True)
class RevisionObservation:
    outcome: ObservationOutcome
    reason: str
    candidate: EvidenceCandidate | None = None
    # earlier PASS-attested revisions of this file that are HISTORICAL after this observation
    historical_revision_ids: tuple[str, ...] = ()


_REFUSED_INPUT = RevisionObservation(ObservationOutcome.REFUSED, "INVALID_INPUT")


class RevisionTracker:
    """Per (namespace, connection) revision bookkeeping. In-memory, bounded, thread-safe."""

    def __init__(self, identity: DrivePortIdentity) -> None:
        if type(identity) is not DrivePortIdentity:
            raise ValueError("DRIVE_IDENTITY_INVALID")
        self._identity = identity
        self._lock = threading.Lock()
        # file_id -> revision ids in observation order (the last one is the latest)
        self._revisions: dict[str, list[str]] = {}
        self._attested: dict[str, set[str]] = {}

    def observe(self, file_id: object, revision_id: object, change_id: object) -> RevisionObservation:
        try:
            if not (
                is_valid_opaque_id(file_id)
                and is_valid_opaque_id(revision_id)
                and is_valid_opaque_id(change_id)
            ):
                return _REFUSED_INPUT
            with self._lock:
                known = self._revisions.get(file_id)
                if known is None:
                    if len(self._revisions) >= MAX_TRACKED_FILES:
                        return RevisionObservation(ObservationOutcome.REFUSED, "TRACKER_FULL")
                    self._revisions[file_id] = [revision_id]
                    return RevisionObservation(
                        ObservationOutcome.FIRST_SEEN, "FIRST_REVISION", self._candidate(file_id, revision_id, change_id)
                    )
                if known[-1] == revision_id:
                    return RevisionObservation(ObservationOutcome.DUPLICATE, "SAME_AS_LATEST")
                if revision_id in known:
                    # an older revision re-delivered: it can never become "latest" again
                    return RevisionObservation(ObservationOutcome.OUT_OF_ORDER, "OLDER_REVISION_REDELIVERED")
                if len(known) >= MAX_REVISIONS_PER_FILE:
                    return RevisionObservation(ObservationOutcome.REFUSED, "TRACKER_FULL")
                known.append(revision_id)
                historical = tuple(r for r in known[:-1] if r in self._attested.get(file_id, ()))
                return RevisionObservation(
                    ObservationOutcome.NEW_REVISION,
                    "NEW_REVISION_UNATTESTED",
                    self._candidate(file_id, revision_id, change_id),
                    historical,
                )
        except Exception:  # noqa: BLE001 - public boundary: hostile input never raises
            return _REFUSED_INPUT

    def record_attested(self, file_id: object, revision_id: object) -> RecordResult:
        """Mark that revision ``revision_id`` of ``file_id`` has an independent PASS attestation."""
        try:
            if not (is_valid_opaque_id(file_id) and is_valid_opaque_id(revision_id)):
                return RecordResult.INVALID_INPUT
            with self._lock:
                if revision_id not in self._revisions.get(file_id, ()):
                    return RecordResult.UNKNOWN_REVISION
                self._attested.setdefault(file_id, set()).add(revision_id)
                return RecordResult.RECORDED
        except Exception:  # noqa: BLE001
            return RecordResult.INVALID_INPUT

    def verdict(self, file_id: object, revision_id: object) -> RevisionVerdict:
        """Verdict for one revision. A PASS of an older revision is HISTORICAL and never ``is_latest``."""
        unknown = RevisionVerdict(RevisionState.UNKNOWN, None, False)
        try:
            if not (is_valid_opaque_id(file_id) and is_valid_opaque_id(revision_id)):
                return unknown
            with self._lock:
                known = self._revisions.get(file_id)
                if known is None or revision_id not in known:
                    return unknown
                latest = known[-1] == revision_id
                if revision_id not in self._attested.get(file_id, ()):
                    return RevisionVerdict(RevisionState.UNATTESTED, None, latest)
                if latest:
                    return RevisionVerdict(RevisionState.PASS_CURRENT, revision_id, True)
                return RevisionVerdict(RevisionState.PASS_HISTORICAL, revision_id, False)
        except Exception:  # noqa: BLE001
            return unknown

    def latest_verdict(self, file_id: object) -> RevisionVerdict:
        """Verdict of the latest known revision only; an older PASS never leaks into it."""
        try:
            if not is_valid_opaque_id(file_id):
                return RevisionVerdict(RevisionState.UNKNOWN, None, False)
            with self._lock:
                known = self._revisions.get(file_id)
                latest = known[-1] if known else None
            if latest is None:
                return RevisionVerdict(RevisionState.UNKNOWN, None, False)
            return self.verdict(file_id, latest)
        except Exception:  # noqa: BLE001
            return RevisionVerdict(RevisionState.UNKNOWN, None, False)

    def _candidate(self, file_id: str, revision_id: str, change_id: str) -> EvidenceCandidate:
        return EvidenceCandidate(self._identity.connection_id, file_id, revision_id, change_id)


_UNAVAILABLE = HistoryResult(HistoryStatus.HISTORY_UNAVAILABLE, HistoryCoverage.CURRENT_ONLY, "HISTORY_UNAVAILABLE")


async def list_history(
    port: DrivePort, identity: DrivePortIdentity, scope_epoch: object, file_id: object
) -> HistoryResult:
    """Read the revision ids of a file through the read-only port. Never raises, never echoes text."""

    def failed(code: str) -> HistoryResult:
        return HistoryResult(HistoryStatus.CHECK_FAILED, HistoryCoverage.NONE, code)

    try:
        if type(identity) is not DrivePortIdentity or not is_valid_scope_epoch(scope_epoch):
            return failed("INVALID_INPUT")
        if not is_valid_opaque_id(file_id):
            return failed("INVALID_INPUT")
        try:
            revisions = await port.list_revisions(identity, scope_epoch, file_id)  # type: ignore[arg-type]
        except DrivePortError as exc:
            code = exc.code
            if code is DriveErrorCode.FORBIDDEN_HISTORY:
                return _UNAVAILABLE
            if code is DriveErrorCode.NOT_FOUND:
                return HistoryResult(HistoryStatus.NOT_FOUND, HistoryCoverage.NONE, "NOT_FOUND")
            return failed(code.value)
        if type(revisions) is not tuple or len(revisions) == 0:
            return _UNAVAILABLE  # missing/empty list: history cannot be relied upon
        ids: list[str] = []
        for item in revisions:
            if type(item) is not RevisionMeta:
                return failed("REVISION_LIST_INVALID")
            ids.append(item.revision_id)
        if len(set(ids)) != len(ids):
            return failed("REVISION_LIST_INVALID")
        return HistoryResult(HistoryStatus.AVAILABLE, HistoryCoverage.LISTED, "HISTORY_LISTED", tuple(ids))
    except Exception:  # noqa: BLE001 - port bug or hostile object: fail closed with a fixed code
        return failed("TRANSIENT")
