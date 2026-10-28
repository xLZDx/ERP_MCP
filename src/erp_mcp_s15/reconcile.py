"""Bidirectional ledger<->1C check (S15, E15-4) as pure logic over injected interfaces.

The ledger and the 1C lookup are injected ports (fakes in S15: S12/S13 are not accepted, so this
is delivered against fakes and the affected acceptance rows stay NOT_RUN against the real ledger).
This module never writes to 1C and never resends a change: an unknown outcome is only classified
by a change-id marker lookup. The "applies blocked" gate is inert while the writer is disabled.
Output is machine verified, not accountant attested. Persisted reconciliation state is not
implemented (UNKNOWN until S13 is checked); the gate state is in memory only.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .labels import LABEL_MACHINE_VERIFIED

__all__ = [
    "ApplyBlockedError",
    "ApplyGate",
    "Finding",
    "LedgerChange",
    "LedgerListing",
    "LedgerPort",
    "OneCDocument",
    "OneCListing",
    "OneCLookupPort",
    "ReconcileStatus",
    "ReconciliationReport",
    "ReconciliationRunner",
    "Trigger",
    "reconcile",
]


class Trigger(str, Enum):
    STARTUP = "startup"
    AFTER_RESTORE = "after_restore"
    PERIODIC = "periodic"


class ReconcileStatus(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    INCONCLUSIVE = "INCONCLUSIVE"


class LedgerStatus:
    APPLIED = "APPLIED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class LedgerChange:
    change_id: str
    expected_hash: str
    status: str  # a LedgerStatus constant


@dataclass(frozen=True, slots=True)
class LedgerListing:
    complete: bool
    changes: tuple[LedgerChange, ...] = ()


@dataclass(frozen=True, slots=True)
class OneCDocument:
    """A 1C document as read: ``marker_hash`` is the stored marker, ``content_hash`` is computed
    from the current content by the lookup port (hash definition is UNKNOWN, plan A10)."""

    document_ref: str
    change_id: str | None
    marker_hash: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class OneCListing:
    complete: bool
    documents: tuple[OneCDocument, ...] = ()


class LedgerPort(Protocol):
    def list_changes(self) -> LedgerListing: ...


class OneCLookupPort(Protocol):
    def list_documents(self) -> OneCListing: ...

    def find_by_change_id(self, change_id: str) -> OneCDocument | None: ...


@dataclass(frozen=True, slots=True)
class Finding:
    """kind: LEDGER_MISSING_IN_1C, UNMARKED_DOCUMENT, ORPHAN_MARKER, MARKER_HASH_MISMATCH,
    CONTENT_CHANGED, DUPLICATE_MARKER, UNRESOLVED_UNKNOWN_OUTCOME."""

    kind: str
    change_id: str | None = None
    document_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    trigger: Trigger
    status: ReconcileStatus
    findings: tuple[Finding, ...] = ()
    # change id -> FOUND_BY_MARKER / NOT_FOUND_BY_MARKER / LOOKUP_FAILED (no resend ever).
    unknown_outcomes: tuple[tuple[str, str], ...] = ()
    label: str = LABEL_MACHINE_VERIFIED


def _classify_unknown(onec: OneCLookupPort, change: LedgerChange
                      ) -> tuple[str, OneCDocument | None]:
    try:
        found = onec.find_by_change_id(change.change_id)
    except Exception:  # noqa: BLE001 - a failed lookup is not evidence of absence
        return "LOOKUP_FAILED", None
    return ("FOUND_BY_MARKER", found) if found is not None else ("NOT_FOUND_BY_MARKER", None)


def reconcile(trigger: Trigger, ledger: LedgerPort, onec: OneCLookupPort
              ) -> ReconciliationReport:
    """One full two-direction pass; incomplete or failed reads give INCONCLUSIVE, not CLEAN."""
    try:
        led = ledger.list_changes()
        docs = onec.list_documents()
    except Exception:  # noqa: BLE001 - fail closed
        return ReconciliationReport(trigger, ReconcileStatus.INCONCLUSIVE)
    if (type(led) is not LedgerListing or led.complete is not True
            or type(docs) is not OneCListing or docs.complete is not True):
        return ReconciliationReport(trigger, ReconcileStatus.INCONCLUSIVE)
    findings: list[Finding] = []
    unknown: list[tuple[str, str]] = []
    incomplete = False
    by_change: dict[str, list[OneCDocument]] = {}
    for doc in docs.documents:
        if doc.change_id is None or doc.marker_hash is None:
            findings.append(Finding("UNMARKED_DOCUMENT", None, doc.document_ref))
        else:
            by_change.setdefault(doc.change_id, []).append(doc)
    known = {c.change_id: c for c in led.changes}
    # 1C -> ledger.
    for change_id, items in by_change.items():
        for doc in items:
            change = known.get(change_id)
            if change is None:
                findings.append(Finding("ORPHAN_MARKER", change_id, doc.document_ref))
                continue
            if doc.marker_hash != change.expected_hash:
                findings.append(Finding("MARKER_HASH_MISMATCH", change_id, doc.document_ref))
            elif doc.content_hash != doc.marker_hash:
                findings.append(Finding("CONTENT_CHANGED", change_id, doc.document_ref))
        if len(items) > 1:
            findings.append(Finding("DUPLICATE_MARKER", change_id, None))
    # Ledger -> 1C.
    for change in led.changes:
        if change.status == LedgerStatus.APPLIED and change.change_id not in by_change:
            findings.append(Finding("LEDGER_MISSING_IN_1C", change.change_id))
        elif change.status == LedgerStatus.UNKNOWN_OUTCOME:
            outcome, _ = _classify_unknown(onec, change)
            unknown.append((change.change_id, outcome))
            if outcome == "LOOKUP_FAILED":
                incomplete = True
            elif outcome == "NOT_FOUND_BY_MARKER":
                findings.append(Finding("UNRESOLVED_UNKNOWN_OUTCOME", change.change_id))
    if findings:
        status = ReconcileStatus.DIRTY
    elif incomplete:
        status = ReconcileStatus.INCONCLUSIVE
    else:
        status = ReconcileStatus.CLEAN
    return ReconciliationReport(trigger, status, tuple(findings), tuple(unknown))


class ApplyBlockedError(Exception):
    """Raised on a write path only, never elsewhere."""


class ApplyGate:
    """Blocks applies until a clean run; inert (never blocks) while the writer is disabled.

    The gate starts blocked (fail closed) and is re-blocked by a restore. Only a CLEAN report
    unblocks it; DIRTY and INCONCLUSIVE keep it blocked. Non-write paths must not consult it.
    """

    def __init__(self, writer_enabled: Callable[[], bool]) -> None:
        self._writer_enabled = writer_enabled
        self._blocked = True

    def mark_restore(self) -> None:
        self._blocked = True

    def record(self, report: ReconciliationReport) -> None:
        self._blocked = report.status is not ReconcileStatus.CLEAN

    def applies_blocked(self) -> bool:
        return bool(self._writer_enabled()) and self._blocked

    def ensure_apply_allowed(self) -> None:
        if self.applies_blocked():
            raise ApplyBlockedError("RECONCILIATION_NOT_CLEAN")


class ReconciliationRunner:
    """Runs the check at startup, after a restore and periodically; feeds the apply gate."""

    def __init__(self, ledger: LedgerPort, onec: OneCLookupPort, gate: ApplyGate,
                 interval_seconds: float) -> None:
        if not interval_seconds > 0:
            raise ValueError("RECONCILE_INTERVAL_INVALID")
        self._ledger = ledger
        self._onec = onec
        self._gate = gate
        self._interval = interval_seconds
        self._last_run: float | None = None

    def run(self, trigger: Trigger, now: float | None = None) -> ReconciliationReport:
        if trigger is Trigger.AFTER_RESTORE:
            self._gate.mark_restore()
        report = reconcile(trigger, self._ledger, self._onec)
        self._gate.record(report)
        if now is not None:
            self._last_run = now
        return report

    def tick(self, now: float) -> ReconciliationReport | None:
        """Periodic entry point: runs when the interval has elapsed since the last run."""
        if self._last_run is not None and now - self._last_run < self._interval:
            return None
        return self.run(Trigger.PERIODIC, now)
