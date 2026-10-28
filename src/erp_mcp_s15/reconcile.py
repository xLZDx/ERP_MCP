"""Bidirectional ledger<->1C check (S15, E15-4) as pure logic over injected interfaces.

The ledger and the 1C lookup are injected ports (fakes in S15: S12/S13 are not accepted, so this
is delivered against fakes and the affected acceptance rows stay NOT_RUN against the real ledger).
This module never writes to 1C and never resends a change: an unknown outcome is only classified
by a change-id marker lookup. The "applies blocked" gate is inert while the writer is disabled.
Output is machine verified, not accountant attested. Persisted reconciliation state is not
implemented (UNKNOWN until S13 is checked); the gate state is in memory only.

Port contract: both ports are synchronous and MUST enforce their own timeout (a port call that
can hang is a defect of the port, not of this module). A timeout must surface as an exception or
as an incomplete listing; the check then reports INCONCLUSIVE and never CLEAN.
The 1C listing must be scoped and complete over ALL documents of the reconciled document types
(supplier receipt) in the declared population, marked or not. The port declares that population
(``population_scope``, ``enumerates_unmarked``) and the caller states the scope it requires; a
marker-index-only reader cannot see an unmarked out-of-band document and is INCONCLUSIVE
(POPULATION_NOT_ESTABLISHED), never CLEAN.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
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
    "LedgerStatus",
    "OneCDocument",
    "OneCListing",
    "OneCLookupPort",
    "ReconcileStatus",
    "ReconciliationReport",
    "ReconciliationRunner",
    "RunnerStatus",
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
    """Closed set of ledger statuses; any other value is an UNKNOWN_LEDGER_STATUS finding."""

    APPLIED = "APPLIED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    PENDING = "PENDING"
    ALL = frozenset({APPLIED, UNKNOWN_OUTCOME, PENDING})


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
    from the current content by the lookup port (hash definition is UNKNOWN, plan A10).
    An empty-string ``change_id`` or ``marker_hash`` counts as unmarked."""

    document_ref: str
    change_id: str | None
    marker_hash: str | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class OneCListing:
    """``population_scope`` names the enumerated population (e.g. the document type and company
    scope); ``enumerates_unmarked`` is True only when unmarked documents are enumerated too."""

    complete: bool
    documents: tuple[OneCDocument, ...] = ()
    population_scope: str = field(kw_only=True)
    enumerates_unmarked: bool = field(kw_only=True)


class LedgerPort(Protocol):
    def list_changes(self) -> LedgerListing:
        """List every ledger change. The implementation MUST enforce its own timeout and raise
        (or return ``complete=False``) instead of blocking; the result is then INCONCLUSIVE."""


class OneCLookupPort(Protocol):
    def list_documents(self) -> OneCListing:
        """List ALL 1C documents of the reconciled document types (supplier receipt) in the
        declared population, marked or not, and declare that population in the result
        (``population_scope``, ``enumerates_unmarked=True``). A marker-index-only listing must
        not claim ``enumerates_unmarked``. The implementation MUST enforce its own timeout and
        raise (or return ``complete=False``) instead of blocking."""

    def find_by_change_id(self, change_id: str) -> OneCDocument | None:
        """Marker lookup for one change id (read-only). MUST enforce its own timeout; the number
        of calls per run is capped by ``max_unknown_lookups``."""


@dataclass(frozen=True, slots=True)
class Finding:
    """kind: LEDGER_MISSING_IN_1C, UNMARKED_DOCUMENT, ORPHAN_MARKER, MARKER_HASH_MISMATCH,
    CONTENT_CHANGED, DUPLICATE_MARKER, UNRESOLVED_UNKNOWN_OUTCOME, NEEDS_LEDGER_RESOLUTION,
    UNKNOWN_LEDGER_STATUS, LEDGER_STATE_SKEW, DUPLICATE_LEDGER_CHANGE, EMPTY_LEDGER_HASH,
    FOUND_NOT_IN_LISTING."""

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
    # Why the run is INCONCLUSIVE: PORT_ERROR:<ExceptionType>, LISTING_INCOMPLETE,
    # MALFORMED_ELEMENT, POPULATION_NOT_ESTABLISHED, STALE_EPOCH, LOOKUP_CAP_EXCEEDED,
    # RUNNER_ERROR:<ExceptionType>,
    # INTERNAL_ERROR:<ExceptionType>. Class names and codes only, never values.
    reason: str = ""


def _inconclusive(trigger: Trigger, reason: str,
                  findings: tuple[Finding, ...] = (),
                  unknown: tuple[tuple[str, str], ...] = ()) -> ReconciliationReport:
    return ReconciliationReport(trigger, ReconcileStatus.INCONCLUSIVE, findings, unknown,
                                reason=reason)


def _is_text(value: object, *, optional: bool = False) -> bool:
    return type(value) is str or (optional and value is None)


def _elements_valid(led: LedgerListing, docs: OneCListing) -> bool:
    if (not isinstance(led.changes, (tuple, list))
            or not isinstance(docs.documents, (tuple, list))):
        return False
    for c in led.changes:
        if (type(c) is not LedgerChange or not _is_text(c.change_id) or not c.change_id
                or not _is_text(c.expected_hash) or not _is_text(c.status)):
            return False
    for d in docs.documents:
        if (type(d) is not OneCDocument or not _is_text(d.document_ref)
                or not _is_text(d.change_id, optional=True)
                or not _is_text(d.marker_hash, optional=True) or not _is_text(d.content_hash)):
            return False
    return True


def _is_marked(doc: OneCDocument) -> bool:
    return bool(doc.change_id) and bool(doc.marker_hash)


def _hash_findings(doc: OneCDocument, change: LedgerChange, change_id: str,
                   findings: list[Finding]) -> None:
    if not change.expected_hash:
        return  # reported as EMPTY_LEDGER_HASH; an empty hash never counts as a match
    if doc.marker_hash != change.expected_hash:
        findings.append(Finding("MARKER_HASH_MISMATCH", change_id, doc.document_ref))
    elif doc.content_hash != doc.marker_hash:
        findings.append(Finding("CONTENT_CHANGED", change_id, doc.document_ref))


def _resolve_unknown(onec: OneCLookupPort, change: LedgerChange,
                     by_change: dict[str, list[OneCDocument]], findings: list[Finding]
                     ) -> tuple[str, str]:
    """Marker lookup for one UNKNOWN_OUTCOME row; returns (outcome, failure reason)."""
    cid = change.change_id
    try:
        found = onec.find_by_change_id(cid)
    except Exception as exc:  # noqa: BLE001 - a failed lookup is not evidence of absence
        return "LOOKUP_FAILED", f"PORT_ERROR:{type(exc).__name__}"
    if found is None:
        findings.append(Finding("UNRESOLVED_UNKNOWN_OUTCOME", cid))
        return "NOT_FOUND_BY_MARKER", ""
    if (type(found) is not OneCDocument or not _is_text(found.document_ref)
            or not _is_text(found.marker_hash, optional=True)
            or not _is_text(found.content_hash) or found.change_id != cid):
        return "LOOKUP_FAILED", "MALFORMED_ELEMENT"
    if not any(d.document_ref == found.document_ref for d in by_change.get(cid, ())):
        # Present by marker lookup but absent from the (complete) listing: check it anyway.
        findings.append(Finding("FOUND_NOT_IN_LISTING", cid, found.document_ref))
        if not _is_marked(found):
            findings.append(Finding("UNMARKED_DOCUMENT", cid, found.document_ref))
        else:
            _hash_findings(found, change, cid, findings)
    # The document exists but the ledger still says UNKNOWN_OUTCOME: stay non-CLEAN until the
    # ledger records the resolution.
    findings.append(Finding("NEEDS_LEDGER_RESOLUTION", cid, found.document_ref))
    return "FOUND_BY_MARKER", ""


def _population_established(docs: OneCListing, required_scope: object) -> bool:
    return (docs.enumerates_unmarked is True and type(docs.population_scope) is str
            and bool(docs.population_scope) and type(required_scope) is str
            and bool(required_scope) and docs.population_scope == required_scope)


def _reconcile(trigger: Trigger, ledger: LedgerPort, onec: OneCLookupPort,
               max_unknown_lookups: int, required_scope: str) -> ReconciliationReport:
    try:
        led = ledger.list_changes()
        docs = onec.list_documents()
    except Exception as exc:  # noqa: BLE001 - fail closed
        return _inconclusive(trigger, f"PORT_ERROR:{type(exc).__name__}")
    if type(led) is not LedgerListing or type(docs) is not OneCListing:
        return _inconclusive(trigger, "MALFORMED_ELEMENT")
    if led.complete is not True or docs.complete is not True:
        return _inconclusive(trigger, "LISTING_INCOMPLETE")
    if not _population_established(docs, required_scope):
        return _inconclusive(trigger, "POPULATION_NOT_ESTABLISHED")
    if not _elements_valid(led, docs):
        return _inconclusive(trigger, "MALFORMED_ELEMENT")
    findings: list[Finding] = []
    unknown: list[tuple[str, str]] = []
    reason = ""
    by_change: dict[str, list[OneCDocument]] = {}
    for doc in docs.documents:
        if not _is_marked(doc):
            findings.append(Finding("UNMARKED_DOCUMENT", None, doc.document_ref))
        else:
            by_change.setdefault(doc.change_id, []).append(doc)  # type: ignore[arg-type]
    for change_id, n in Counter(c.change_id for c in led.changes).items():
        if n > 1:
            findings.append(Finding("DUPLICATE_LEDGER_CHANGE", change_id))
    known: dict[str, LedgerChange] = {}
    for c in led.changes:
        known.setdefault(c.change_id, c)
    # 1C -> ledger.
    for change_id, items in by_change.items():
        for doc in items:
            change = known.get(change_id)
            if change is None:
                findings.append(Finding("ORPHAN_MARKER", change_id, doc.document_ref))
                continue
            _hash_findings(doc, change, change_id, findings)
        if len(items) > 1:
            findings.append(Finding("DUPLICATE_MARKER", change_id, None))
    # Ledger -> 1C.
    lookups = 0
    for change in led.changes:
        cid = change.change_id
        if not change.expected_hash:
            findings.append(Finding("EMPTY_LEDGER_HASH", cid))
        if change.status not in LedgerStatus.ALL:
            findings.append(Finding("UNKNOWN_LEDGER_STATUS", cid))
        elif change.status == LedgerStatus.APPLIED:
            if cid not in by_change:
                findings.append(Finding("LEDGER_MISSING_IN_1C", cid))
        elif change.status == LedgerStatus.UNKNOWN_OUTCOME:
            lookups += 1
            if lookups > max_unknown_lookups:
                return _inconclusive(trigger, "LOOKUP_CAP_EXCEEDED", tuple(findings),
                                     tuple(unknown))
            outcome, why = _resolve_unknown(onec, change, by_change, findings)
            unknown.append((cid, outcome))
            if outcome == "LOOKUP_FAILED" and not reason:
                reason = why
        elif cid in by_change:  # PENDING: 1C shows a document the ledger has not recorded
            findings.append(Finding("LEDGER_STATE_SKEW", cid, by_change[cid][0].document_ref))
    if findings:
        status = ReconcileStatus.DIRTY
    elif reason:
        status = ReconcileStatus.INCONCLUSIVE
    else:
        status = ReconcileStatus.CLEAN
    return ReconciliationReport(trigger, status, tuple(findings), tuple(unknown), reason=reason)


def reconcile(trigger: Trigger, ledger: LedgerPort, onec: OneCLookupPort, *,
              required_scope: str, max_unknown_lookups: int = 50) -> ReconciliationReport:
    """One full two-direction pass; incomplete or failed reads give INCONCLUSIVE, not CLEAN.

    Never raises: any failure (port error, malformed element, internal error) is INCONCLUSIVE
    with a ``reason``. More than ``max_unknown_lookups`` UNKNOWN_OUTCOME lookups in one run is
    INCONCLUSIVE with reason LOOKUP_CAP_EXCEEDED. ``required_scope`` is the population the
    caller requires; a listing that does not declare exactly that scope with
    ``enumerates_unmarked=True`` is INCONCLUSIVE with reason POPULATION_NOT_ESTABLISHED.
    """
    try:
        return _reconcile(trigger, ledger, onec, max_unknown_lookups, required_scope)
    except Exception as exc:  # noqa: BLE001 - fail closed
        return _inconclusive(trigger, f"INTERNAL_ERROR:{type(exc).__name__}")


class ApplyBlockedError(Exception):
    """Raised on a write path only, never elsewhere."""


class ApplyGate:
    """Blocks applies until a fresh clean run; inert (never blocks) while the writer is disabled.

    The gate starts blocked (fail closed) and is re-blocked by a restore, which also bumps an
    epoch: a report computed before the latest restore (its captured epoch passed to ``record``)
    is discarded and never unblocks. Only a CLEAN report unblocks, and only for
    ``max_age_seconds`` after it was recorded. ``writer_enabled`` must return exactly ``False``
    to make the gate inert; any other value (True, None, 0, an exception) counts as enabled
    (blocking). Non-write paths must not consult it.
    """

    def __init__(self, writer_enabled: Callable[[], bool], max_age_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not max_age_seconds > 0:
            raise ValueError("GATE_MAX_AGE_INVALID")
        self._writer_enabled = writer_enabled
        self._max_age = max_age_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._blocked = True
        self._epoch = 0
        self._clean_at: float | None = None

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    @property
    def clean_at(self) -> float | None:
        with self._lock:
            return self._clean_at

    def now(self) -> float:
        """Current time on the gate clock (capture it BEFORE a run's reads start)."""
        return self._clock()

    def mark_restore(self) -> None:
        with self._lock:
            self._epoch += 1
            self._blocked = True
            self._clean_at = None

    def record(self, report: ReconciliationReport, epoch: int,
               observed_at: float | None = None) -> bool:
        """Apply ``report``; False when it was computed before the latest restore (discarded).

        ``epoch`` (required) is the gate epoch captured before the report's run started.
        ``observed_at`` is the gate-clock time captured before the run's reads started; a CLEAN
        report ages from it (default: now, only for callers that did not capture it).
        """
        with self._lock:
            if epoch != self._epoch:
                return False
            if report.status is ReconcileStatus.CLEAN:
                self._blocked = False
                self._clean_at = self._clock() if observed_at is None else observed_at
            else:
                self._blocked = True
                self._clean_at = None
            return True

    def _enabled(self) -> bool:
        try:
            enabled = self._writer_enabled()
        except Exception:  # noqa: BLE001 - fail closed
            return True
        return enabled is not False

    def applies_blocked(self) -> bool:
        if not self._enabled():
            return False
        with self._lock:
            if self._blocked or self._clean_at is None:
                return True
            age = self._clock() - self._clean_at
            return age < 0 or age > self._max_age  # stale (or non-monotonic) CLEAN is blocked

    def ensure_apply_allowed(self) -> None:
        if self.applies_blocked():
            raise ApplyBlockedError("RECONCILIATION_NOT_CLEAN")


@dataclass(frozen=True, slots=True)
class RunnerStatus:
    """Read-only runner status; times come from the runner clock."""

    last_report: ReconciliationReport | None
    last_run_at: float | None
    last_clean_at: float | None
    consecutive_non_clean: int


_LOG = logging.getLogger(__name__)


class ReconciliationRunner:
    """Runs the check at startup, after a restore and periodically; feeds the apply gate.

    Runs are serialized by a lock: an overlapping periodic tick is skipped (returns None), an
    explicit ``run`` waits. After a non-CLEAN result the shorter ``retry_interval_seconds``
    applies (default a quarter of the interval).
    """

    def __init__(self, ledger: LedgerPort, onec: OneCLookupPort, gate: ApplyGate,
                 interval_seconds: float, *, required_scope: str,
                 retry_interval_seconds: float | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 max_unknown_lookups: int = 50) -> None:
        if not interval_seconds > 0:
            raise ValueError("RECONCILE_INTERVAL_INVALID")
        if type(required_scope) is not str or not required_scope:
            raise ValueError("RECONCILE_REQUIRED_SCOPE_INVALID")
        retry = interval_seconds / 4 if retry_interval_seconds is None else retry_interval_seconds
        if not retry > 0:
            raise ValueError("RECONCILE_RETRY_INTERVAL_INVALID")
        self._ledger = ledger
        self._onec = onec
        self._gate = gate
        self._interval = interval_seconds
        self._retry = min(retry, interval_seconds)
        self._clock = clock
        self._max_lookups = max_unknown_lookups
        self._required_scope = required_scope
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._last_run: float | None = None
        self._last_clean: float | None = None
        self._last_report: ReconciliationReport | None = None
        self._non_clean = 0
        self._epoch_at_run: int | None = None

    def start(self) -> ReconciliationReport:
        """Startup trigger."""
        return self.run(Trigger.STARTUP)

    def run(self, trigger: Trigger) -> ReconciliationReport:
        if trigger is Trigger.AFTER_RESTORE:
            self._gate.mark_restore()  # before waiting: an in-flight run becomes stale
        with self._run_lock:
            return self._execute(trigger)

    def tick(self) -> ReconciliationReport | None:
        """Periodic entry point: runs when the (retry) interval has elapsed or a restore is
        pending; a backwards clock never suppresses a due tick; overlapping ticks are skipped."""
        now = self._clock()
        with self._state_lock:
            last = self._last_run
            interval = self._retry if self._non_clean > 0 else self._interval
            epoch_seen = self._epoch_at_run
        restore_pending = epoch_seen is None or epoch_seen != self._gate.epoch
        if not restore_pending and last is not None and 0 <= now - last < interval:
            return None
        if not self._run_lock.acquire(blocking=False):
            return None
        try:
            return self._execute(Trigger.PERIODIC)
        finally:
            self._run_lock.release()

    def status(self) -> RunnerStatus:
        with self._state_lock:
            return RunnerStatus(self._last_report, self._last_run, self._last_clean,
                                self._non_clean)

    def _execute(self, trigger: Trigger) -> ReconciliationReport:
        epoch = self._gate.epoch
        observed_at = self._gate.now()  # before any read: CLEAN age counts from here
        try:
            report = reconcile(trigger, self._ledger, self._onec,
                               required_scope=self._required_scope,
                               max_unknown_lookups=self._max_lookups)
        except Exception as exc:  # noqa: BLE001 - fail closed
            report = _inconclusive(trigger, f"RUNNER_ERROR:{type(exc).__name__}")
        try:
            if not self._gate.record(report, epoch, observed_at):
                report = _inconclusive(trigger, "STALE_EPOCH")
        except Exception as exc:  # noqa: BLE001 - the gate keeps its previous state
            report = _inconclusive(trigger, f"RUNNER_ERROR:{type(exc).__name__}")
        ended = self._clock()
        clean = report.status is ReconcileStatus.CLEAN
        with self._state_lock:
            self._last_run = ended
            self._epoch_at_run = epoch
            self._last_report = report
            if clean:
                self._last_clean = ended
                self._non_clean = 0
            else:
                self._non_clean += 1
        _LOG.log(logging.INFO if clean else logging.WARNING,
                 "reconcile run trigger=%s status=%s reason=%s findings=%d",
                 trigger.value, report.status.value, report.reason or "-", len(report.findings))
        return report
