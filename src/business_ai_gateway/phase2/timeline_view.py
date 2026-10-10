"""Phase 2 sprint S8 / E2 (R2-US-040, TC118-TC120): the auditor's timeline view model.

Offline, unwired, in-memory, synchronous. A pure function turns existing immutable records (``RunLedger``
runs, ``AttestationStore`` history, ``EventLedger`` events, a ``MatrixResult``) into a frozen view that
a future UI must render verbatim. Nothing here is authoritative and nothing here can set a status:

* Two time axes are two different types. ``KnownTimeLabel`` (label ``KNOWN_AT``) is when the system
  recorded or knew a fact; ``EffectiveTimeLabel`` (label ``EFFECTIVE_AT``) is source-effective validity.
  A missing effective time is the explicit ``EFFECTIVE_UNKNOWN`` label - never filled from the known
  time, the observed time or "now". An entry has no single ambiguous "date" field.
* ``Applicability`` is computed by one fixed rule and ``is_green`` is the only green predicate. Only
  ``LIVE_CURRENT`` is green; it needs ALL of: the run is the ledger's CURRENT run and PASS; its
  attestation passes ``AttestationStore.check_current`` (the gate; the historical as-of query is never
  used); the matrix covers the viewer's company; the run is inside the injected freshness window on the
  injected clock; the revision is the policy's current revision; the source is not paused. Any missing or
  unusable input downgrades to a NAMED non-green value, never to a default green.
* Scope is enforced here, not by a renderer: rows of other companies are dropped and leave only the
  opaque ``hidden_by_scope`` flag (no count, no id, no name). A stale scope epoch gives a ``SafeError``
  and no view; ``render_guard`` re-checks the epoch immediately before disclosure.

Public functions never raise: hostile input (wrong or lying types, naive timestamps, forged
``object.__new__`` instances, recursive/huge values) gives a fixed ``SafeError``. No caller text is echoed
into any outward value. Authority is ``EVALUATION_ONLY``; the data are scripted/offline when produced over
fakes. KNOWN GAPS: the freshness window, source-paused flag, current revision and scope epochs are injected
facts, not read from a real source; attestations are tenant-scoped (they carry no company).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from ._identity import exact_text, scope_key
from .comparison_snapshot import ComparisonState, RunLedger, RunRecord, RunView, canonical_digest
from .evidence_attestation import AttestationStore
from .temporal import EventKind, EventLedger
from .validation_coverage import CoverageStatus, MatrixResult, MatrixRow, _matrix_digest
from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    ReasonCode,
    SafeError,
    ViewerScope,
    is_valid_scope,
    safe_error,
)

__all__ = [
    "BASIS", "EFFECTIVE_AT_LABEL", "EFFECTIVE_UNKNOWN_LABEL", "HISTORICAL_LABEL", "KNOWN_AT_LABEL",
    "Applicability", "ApplicabilityPolicy", "ApplicabilityReason", "EffectiveTimeLabel", "EntryKind",
    "EventFeed", "KnownTimeLabel", "RunBinding", "ScopeAuthority", "TimelineEntry", "TimelineSubject",
    "TimelineView", "build_timeline", "is_green", "render_guard",
]

KNOWN_AT_LABEL: Final = "KNOWN_AT"
EFFECTIVE_AT_LABEL: Final = "EFFECTIVE_AT"
EFFECTIVE_UNKNOWN_LABEL: Final = "EFFECTIVE_UNKNOWN"
HISTORICAL_LABEL: Final = "historical, not current"
BASIS: Final = "offline in-memory view over scripted records; EVALUATION_ONLY, not native PASS or validation"
_HEX: Final = re.compile(r"[0-9a-f]{64}")
_MAX_WINDOW: Final = 10 * 365 * 24 * 3600
_MAX_EPOCH: Final = 2**63 - 1
_UTC0: Final = timedelta(0)


class EntryKind(StrEnum):
    RUN = "RUN"
    ATTESTATION = "ATTESTATION"
    EVENT = "EVENT"


class Applicability(StrEnum):
    LIVE_CURRENT = "LIVE_CURRENT"
    HISTORICAL_PASS = "HISTORICAL_PASS"
    REVOKED = "REVOKED"
    UNATTESTED = "UNATTESTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAIL = "FAIL"
    NOT_COVERED = "NOT_COVERED"
    UNKNOWN = "UNKNOWN"


class ApplicabilityReason(StrEnum):
    SUPERSEDED_BY_RUN = "SUPERSEDED_BY_RUN"
    REVISION_CHANGED = "REVISION_CHANGED"
    ATTESTATION_REVOKED = "ATTESTATION_REVOKED"
    STALE = "STALE"
    SOURCE_PAUSED = "SOURCE_PAUSED"
    NOT_COVERED = "NOT_COVERED"
    ATTESTATION_MISSING = "ATTESTATION_MISSING"
    ATTESTATION_NOT_CURRENT = "ATTESTATION_NOT_CURRENT"
    RUN_FAILED = "RUN_FAILED"
    RUN_INCONCLUSIVE = "RUN_INCONCLUSIVE"
    INPUT_UNKNOWN = "INPUT_UNKNOWN"
    EVIDENCE_ROW = "EVIDENCE_ROW"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    HISTORY_GAP = "HISTORY_GAP"


_LABEL_TEXT: Final = {
    Applicability.LIVE_CURRENT: "live, current",
    Applicability.HISTORICAL_PASS: HISTORICAL_LABEL,
    Applicability.REVOKED: "attestation revoked",
    Applicability.UNATTESTED: "not attested",
    Applicability.INCONCLUSIVE: "inconclusive",
    Applicability.FAIL: "failed",
    Applicability.NOT_COVERED: "not covered",
    Applicability.UNKNOWN: "unknown",
}


class _Refuse(Exception):
    def __init__(self, code: ReasonCode) -> None:
        super().__init__(code.value)
        self.code = code


def _text_ok(value: object) -> bool:
    return type(value) is str and value != "" and exact_text(value) == value


def _digest_ok(value: object) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _utc_exact(value: object) -> bool:
    try:
        return (type(value) is datetime and value.tzinfo is not None and value.utcoffset() == _UTC0)
    except Exception:  # noqa: BLE001 - hostile tzinfo
        return False


def _flatten(value: object) -> datetime | None:
    """Exact aware-UTC copy of an aware datetime (subclasses are rebuilt from fields), else None."""
    try:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            return None
        moved = value.astimezone(UTC)
        return datetime(moved.year, moved.month, moved.day, moved.hour, moved.minute, moved.second,
                        moved.microsecond, tzinfo=UTC)
    except Exception:  # noqa: BLE001 - OverflowError near min/max, hostile tzinfo
        return None


def _clock_now(clock: object) -> datetime:
    """Strict: only an exact aware ``datetime`` from a callable clock is accepted."""
    if not callable(clock):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    try:
        raw = clock()
    except Exception:  # noqa: BLE001 - the exception text is never surfaced
        raise _Refuse(ReasonCode.INPUT_INVALID) from None
    if type(raw) is not datetime:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    moved = _flatten(raw)
    if moved is None:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    return moved


# ------------------------------------------------------------------ labels
@dataclass(frozen=True, slots=True)
class KnownTimeLabel:
    """When the system recorded or knew the fact (known axis)."""

    at: datetime
    label: str = KNOWN_AT_LABEL

    def __post_init__(self) -> None:
        if not _utc_exact(self.at) or self.label != KNOWN_AT_LABEL or type(self.label) is not str:
            raise ValueError("TIME_LABEL_INVALID")


@dataclass(frozen=True, slots=True)
class EffectiveTimeLabel:
    """Source-effective validity (effective axis); ``at`` is None exactly when the label says unknown."""

    at: datetime | None
    label: str
    reason: ReasonCode | None

    def __post_init__(self) -> None:
        known = (_utc_exact(self.at) and type(self.label) is str and self.label == EFFECTIVE_AT_LABEL
                 and self.reason is None)
        unknown = (self.at is None and type(self.label) is str and self.label == EFFECTIVE_UNKNOWN_LABEL
                   and type(self.reason) is ReasonCode and self.reason is ReasonCode.EFFECTIVE_UNKNOWN)
        if not (known or unknown):
            raise ValueError("TIME_LABEL_INVALID")

    @classmethod
    def at_time(cls, at: datetime) -> EffectiveTimeLabel:
        return cls(at, EFFECTIVE_AT_LABEL, None)

    @classmethod
    def unknown(cls) -> EffectiveTimeLabel:
        return cls(None, EFFECTIVE_UNKNOWN_LABEL, ReasonCode.EFFECTIVE_UNKNOWN)


# ------------------------------------------------------------------ entries and the green predicate
@dataclass(frozen=True, slots=True)
class TimelineEntry:
    kind: EntryKind
    ref_id: str
    known: KnownTimeLabel
    effective: EffectiveTimeLabel
    applicability: Applicability
    reason: ApplicabilityReason | None
    label_text: str
    gap: bool
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        live = type(self.applicability) is Applicability and self.applicability is Applicability.LIVE_CURRENT
        if (type(self.kind) is not EntryKind or not _text_ok(self.ref_id)
                or type(self.known) is not KnownTimeLabel or type(self.effective) is not EffectiveTimeLabel
                or type(self.applicability) is not Applicability
                or (self.reason is not None and type(self.reason) is not ApplicabilityReason)
                or (live and self.reason is not None) or (not live and self.reason is None)
                or not _text_ok(self.label_text) or len(self.label_text) > 128
                or type(self.gap) is not bool or type(self.authority) is not str
                or self.authority != AUTHORITY):
            raise ValueError("TIMELINE_ENTRY_INVALID")


def is_green(entry: object) -> bool:
    """The single green predicate: True only for a well-formed RUN entry that is ``LIVE_CURRENT``."""
    if type(entry) is not TimelineEntry:
        return False
    try:
        return (type(entry.applicability) is Applicability
                and entry.applicability is Applicability.LIVE_CURRENT and entry.reason is None
                and entry.kind is EntryKind.RUN and type(entry.known) is KnownTimeLabel
                and type(entry.effective) is EffectiveTimeLabel and entry.authority == AUTHORITY)
    except AttributeError:  # forged object.__new__ instance: slots never set
        return False


def _known_key(entry: TimelineEntry) -> tuple[datetime, str, str]:
    return (entry.known.at, entry.kind.value, entry.ref_id)


@dataclass(frozen=True, slots=True)
class TimelineView:
    tenant_id: str
    company_id: str
    scope_epoch: int
    generated_at: datetime
    entries: tuple[TimelineEntry, ...]
    hidden_by_scope: bool
    digest: str
    authority: str = AUTHORITY
    basis: str = BASIS

    def __post_init__(self) -> None:
        if (not _text_ok(self.tenant_id) or not _text_ok(self.company_id)
                or type(self.scope_epoch) is not int or not 0 <= self.scope_epoch <= _MAX_EPOCH
                or not _utc_exact(self.generated_at) or type(self.entries) is not tuple
                or any(type(e) is not TimelineEntry for e in self.entries)
                or type(self.hidden_by_scope) is not bool or not _digest_ok(self.digest)
                or self.authority != AUTHORITY or self.basis != BASIS):
            raise ValueError("TIMELINE_VIEW_INVALID")

    def by_known(self) -> tuple[TimelineEntry, ...]:
        """Entries on the known axis (when the system knew), oldest first."""
        return tuple(sorted(self.entries, key=_known_key))

    def by_effective(self) -> tuple[TimelineEntry, ...]:
        """Entries on the effective axis; entries with unknown effective time come last, in known order."""
        dated = [e for e in self.entries if e.effective.at is not None]
        undated = [e for e in self.entries if e.effective.at is None]
        dated.sort(key=lambda e: (e.effective.at, *_known_key(e)))
        undated.sort(key=_known_key)
        return tuple(dated + undated)


# ------------------------------------------------------------------ caller-supplied inputs
@dataclass(frozen=True, slots=True)
class RunBinding:
    """What one run's PASS claims to rest on: an attestation id plus the exact revision/policy it covers."""

    run_id: str
    attestation_id: str | None
    revision_digest: str
    policy_version: str
    policy_digest: str

    def __post_init__(self) -> None:
        if (not _text_ok(self.run_id) or (self.attestation_id is not None and not _text_ok(self.attestation_id))
                or not _digest_ok(self.revision_digest) or not _text_ok(self.policy_version)
                or not _digest_ok(self.policy_digest)):
            raise ValueError("RUN_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class TimelineSubject:
    """One comparison key owned by one (tenant, company), with the bindings of its runs."""

    tenant_id: str
    company_id: str
    comparison_key: str
    bindings: tuple[RunBinding, ...]

    def __post_init__(self) -> None:
        if (not _text_ok(self.tenant_id) or not _text_ok(self.company_id) or not _text_ok(self.comparison_key)
                or type(self.bindings) is not tuple or any(type(b) is not RunBinding for b in self.bindings)):
            raise ValueError("TIMELINE_SUBJECT_INVALID")


@dataclass(frozen=True, slots=True)
class EventFeed:
    """An ``EventLedger`` owned by one (tenant, company)."""

    tenant_id: str
    company_id: str
    ledger: EventLedger

    def __post_init__(self) -> None:
        if (not _text_ok(self.tenant_id) or not _text_ok(self.company_id)
                or type(self.ledger) is not EventLedger):
            raise ValueError("EVENT_FEED_INVALID")


@dataclass(frozen=True, slots=True)
class ApplicabilityPolicy:
    """Injected facts: freshness window, the current revision and whether the source is paused (None=unknown)."""

    freshness_seconds: int
    current_revision_digest: str | None
    source_paused: bool | None

    def __post_init__(self) -> None:
        if (type(self.freshness_seconds) is not int or not 0 <= self.freshness_seconds <= _MAX_WINDOW
                or (self.current_revision_digest is not None and not _digest_ok(self.current_revision_digest))
                or (self.source_paused is not None and type(self.source_paused) is not bool)):
            raise ValueError("APPLICABILITY_POLICY_INVALID")


@dataclass(frozen=True, slots=True)
class ScopeAuthority:
    """Live read of the CURRENT epoch of a (tenant, company); anything unusable counts as stale."""

    lookup: Callable[[str, str], object]

    def __post_init__(self) -> None:
        if not callable(self.lookup):
            raise ValueError("SCOPE_AUTHORITY_INVALID")  # noqa: TRY004 - fixed-code constructor convention

    def current_epoch(self, tenant_id: object, company_id: object) -> int | None:
        try:
            value = self.lookup(tenant_id, company_id)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - the exception text is never surfaced
            return None
        if type(value) is int and 0 <= value <= _MAX_EPOCH:
            return value
        return None


def _check_epoch(viewer: ViewerScope, authority: ScopeAuthority) -> None:
    if type(authority) is not ScopeAuthority:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    current = authority.current_epoch(viewer.tenant_id, viewer.company_id)
    if current is None or current != viewer.scope_epoch:
        raise _Refuse(ReasonCode.SCOPE_EPOCH_STALE)


def _guard(fn: Callable[[], object], correlation_id: object) -> object:
    """Run ``fn``; any failure becomes a fixed ``SafeError`` (never an echo, never an exception)."""
    try:
        return fn()
    except _Refuse as refusal:
        return safe_error(refusal.code, correlation_id)
    except (AttributeError, TypeError, ValueError, KeyError):
        return safe_error(ReasonCode.INPUT_INVALID, correlation_id)
    except Exception:  # noqa: BLE001 - includes RecursionError/MemoryError-like failures
        return safe_error(ReasonCode.INTERNAL_REFUSED, correlation_id)


# ------------------------------------------------------------------ applicability rule
def _in_scope_coverage(matrix: object, vkey: tuple[str, str]) -> bool | None:
    """True/False for the viewer's company, None when the matrix itself is unusable (never guessed)."""
    try:
        if (type(matrix) is not MatrixResult or type(matrix.status) is not CoverageStatus
                or type(matrix.rows) is not tuple or type(matrix.uncovered) is not tuple
                or type(matrix.non_pass) is not tuple or type(matrix.digest) is not str):
            return None
        if matrix.status is CoverageStatus.REFUSED:
            return False
        if any(type(r) is not MatrixRow for r in matrix.rows) or matrix.digest != _matrix_digest(matrix.rows):
            return None
        mine = [r for r in matrix.rows if r.scope == vkey]
        if not mine:
            return False
        return all(r.evidence_ids and not r.non_pass_ids and r.claim_id not in matrix.uncovered for r in mine)
    except Exception:  # noqa: BLE001 - forged or hostile matrix: unknown, never covered
        return None


def _decide_run(view: RunView, binding: RunBinding | None, att: AttestationStore,
                policy: ApplicabilityPolicy, covered: bool | None, now: datetime,
                ) -> tuple[Applicability, ApplicabilityReason | None]:
    rec: RunRecord = view.record
    A, R = Applicability, ApplicabilityReason
    if rec.state is ComparisonState.FAIL:
        return A.FAIL, R.RUN_FAILED
    if rec.state is ComparisonState.INCONCLUSIVE:
        return A.INCONCLUSIVE, R.RUN_INCONCLUSIVE
    if rec.state is not ComparisonState.PASS or view.status not in ("CURRENT", "SUPERSEDED"):
        return A.UNKNOWN, R.INPUT_UNKNOWN
    check = None
    if binding is not None and binding.attestation_id is not None:
        check = att.check_current(binding.attestation_id, rec.tenant_id, binding.revision_digest,
                                  binding.policy_version, binding.policy_digest)
    if check is not None and check.code == "REVOKED":
        return A.REVOKED, R.ATTESTATION_REVOKED  # history kept, current applicability removed
    if view.status == "SUPERSEDED":
        return A.HISTORICAL_PASS, R.SUPERSEDED_BY_RUN
    recorded = _flatten(rec.recorded_at)
    if recorded is None or now < recorded:
        return A.UNKNOWN, R.INPUT_UNKNOWN  # inconsistent clock: never guess
    if check is None:
        return A.UNATTESTED, R.ATTESTATION_MISSING
    if not check.valid or check.code != "VALID":
        return A.UNATTESTED, R.ATTESTATION_NOT_CURRENT
    if policy.current_revision_digest is None:
        return A.UNKNOWN, R.INPUT_UNKNOWN
    if policy.current_revision_digest != binding.revision_digest:  # type: ignore[union-attr]
        return A.HISTORICAL_PASS, R.REVISION_CHANGED
    if covered is None:
        return A.UNKNOWN, R.INPUT_UNKNOWN
    if not covered:
        return A.NOT_COVERED, R.NOT_COVERED
    if now - recorded > timedelta(seconds=policy.freshness_seconds):
        return A.HISTORICAL_PASS, R.STALE
    if policy.source_paused is None:
        return A.UNKNOWN, R.INPUT_UNKNOWN
    if policy.source_paused:
        return A.HISTORICAL_PASS, R.SOURCE_PAUSED
    return A.LIVE_CURRENT, None


def _entry(kind: EntryKind, ref: str, known: datetime, effective: EffectiveTimeLabel,
           applic: Applicability, reason: ApplicabilityReason | None, text: str | None = None,
           gap: bool = False) -> TimelineEntry:
    return TimelineEntry(kind, ref, KnownTimeLabel(known), effective, applic, reason,
                         text or _LABEL_TEXT[applic], gap)


def _run_entries(ledger: RunLedger, att: AttestationStore, sub: TimelineSubject, policy: ApplicabilityPolicy,
                 covered: bool | None, now: datetime) -> list[TimelineEntry]:
    by_run: dict[str, RunBinding] = {}
    for binding in sub.bindings:
        if binding.run_id in by_run:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        by_run[binding.run_id] = binding
    out = []
    views = ledger.list_runs(sub.tenant_id, sub.comparison_key)
    if type(views) is not tuple:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    for view in views:
        if type(view) is not RunView or type(view.record) is not RunRecord:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        known = _flatten(view.record.recorded_at)
        if known is None:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        try:
            applic, reason = _decide_run(view, by_run.get(view.record.run_id), att, policy, covered, now)
        except Exception:  # noqa: BLE001 - any failure in the rule is UNKNOWN, never green
            applic, reason = Applicability.UNKNOWN, ApplicabilityReason.INPUT_UNKNOWN
        out.append(_entry(EntryKind.RUN, view.record.run_id, known, EffectiveTimeLabel.unknown(),
                          applic, reason))
    return out


def _attestation_entries(att: AttestationStore, tenant_id: str) -> list[TimelineEntry]:
    out = []
    items = att.history(tenant_id)
    if type(items) is not tuple:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    for item in items:
        signed = _flatten(item.signed_at)
        if signed is None:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        if item.revoked_at is not None:
            out.append(_entry(EntryKind.ATTESTATION, item.attestation_id, signed, EffectiveTimeLabel.unknown(),
                              Applicability.REVOKED, ApplicabilityReason.ATTESTATION_REVOKED))
        else:  # an attestation is evidence for a run verdict, never a verdict of its own
            out.append(_entry(EntryKind.ATTESTATION, item.attestation_id, signed, EffectiveTimeLabel.unknown(),
                              Applicability.UNKNOWN, ApplicabilityReason.EVIDENCE_ROW, "evidence record"))
    return out


def _event_entries(feed: EventFeed, now: datetime) -> list[TimelineEntry]:
    out = []
    for ev in feed.ledger.events:
        known = _flatten(ev.recorded_at)
        if known is None:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        if known > now:
            continue  # not yet known at the injected clock
        eff = ev.source_effective_at
        effective = EffectiveTimeLabel.unknown()  # never copied from recorded/observed time
        if eff is not None:
            flat = _flatten(eff)
            if flat is None:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            effective = EffectiveTimeLabel.at_time(flat)
        if ev.kind is EventKind.ATTESTATION_REVOKED:
            out.append(_entry(EntryKind.EVENT, ev.event_id, known, effective, Applicability.REVOKED,
                              ApplicabilityReason.ATTESTATION_REVOKED))
        elif ev.kind is EventKind.GAP:
            out.append(_entry(EntryKind.EVENT, ev.event_id, known, effective, Applicability.UNKNOWN,
                              ApplicabilityReason.HISTORY_GAP, "gap in history", True))
        elif ev.kind is EventKind.SOURCE_UNAVAILABLE:
            out.append(_entry(EntryKind.EVENT, ev.event_id, known, effective, Applicability.UNKNOWN,
                              ApplicabilityReason.HISTORY_GAP, "source unavailable", True))
        else:
            out.append(_entry(EntryKind.EVENT, ev.event_id, known, effective, Applicability.UNKNOWN,
                              ApplicabilityReason.OBSERVATION_ONLY, "observation, not a verdict"))
    return out


def _entry_digest_row(e: TimelineEntry) -> list[object]:
    return [e.kind.value, e.ref_id, e.known.at, e.effective.at, e.applicability.value,
            None if e.reason is None else e.reason.value, e.label_text, e.gap]


def build_timeline(
    viewer: object,
    authority: object,
    ledger: object,
    attestations: object,
    subjects: object,
    feeds: object,
    matrix: object,
    policy: object,
    clock: object,
    *,
    correlation_id: object = DEFAULT_CORRELATION_ID,
) -> TimelineView | SafeError:
    """Build the auditor timeline for ``viewer`` at the injected ``clock``; never raises, never default-green."""
    def run() -> TimelineView:
        if not is_valid_scope(viewer):
            raise _Refuse(ReasonCode.INPUT_INVALID)
        _check_epoch(viewer, authority)  # type: ignore[arg-type,union-attr]
        now = _clock_now(clock)
        if (type(ledger) is not RunLedger or type(attestations) is not AttestationStore
                or type(subjects) is not tuple or type(feeds) is not tuple
                or type(policy) is not ApplicabilityPolicy):
            raise _Refuse(ReasonCode.INPUT_INVALID)
        ApplicabilityPolicy(policy.freshness_seconds, policy.current_revision_digest, policy.source_paused)
        vkey = scope_key(viewer.tenant_id, viewer.company_id)
        covered = _in_scope_coverage(matrix, vkey) if vkey is not None else None
        hidden = False
        entries: list[TimelineEntry] = []
        seen: set[tuple[str, str, str]] = set()
        for sub in subjects:
            if type(sub) is not TimelineSubject:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            TimelineSubject(sub.tenant_id, sub.company_id, sub.comparison_key, sub.bindings)
            for b in sub.bindings:
                RunBinding(b.run_id, b.attestation_id, b.revision_digest, b.policy_version, b.policy_digest)
            if scope_key(sub.tenant_id, sub.company_id) != vkey:
                hidden = True  # dropped; nothing about it is read, counted or named
                continue
            ident = (sub.tenant_id, sub.company_id, sub.comparison_key)
            if ident in seen:
                continue
            seen.add(ident)
            entries.extend(_run_entries(ledger, attestations, sub, policy, covered, now))
        for feed in feeds:
            if type(feed) is not EventFeed:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            EventFeed(feed.tenant_id, feed.company_id, feed.ledger)
            if scope_key(feed.tenant_id, feed.company_id) != vkey:
                hidden = True
                continue
            entries.extend(_event_entries(feed, now))
        entries.extend(_attestation_entries(attestations, viewer.tenant_id))
        entries.sort(key=_known_key)
        digest = canonical_digest({
            "v": 1, "tenant": viewer.tenant_id, "company": viewer.company_id, "epoch": viewer.scope_epoch,
            "at": now, "hidden": hidden, "entries": [_entry_digest_row(e) for e in entries]})
        view = TimelineView(viewer.tenant_id, viewer.company_id, viewer.scope_epoch, now, tuple(entries),
                            hidden, digest)
        _check_epoch(viewer, authority)  # type: ignore[arg-type]  # re-check immediately before disclosure
        return view

    return _guard(run, correlation_id)  # type: ignore[return-value]


def render_guard(view: object, authority: object, *, correlation_id: object = DEFAULT_CORRELATION_ID,
                 ) -> TimelineView | SafeError:
    """Re-verify the viewer's scope epoch right before a built view is disclosed (revoke-before-disclosure)."""
    def run() -> TimelineView:
        if type(view) is not TimelineView:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        viewer = ViewerScope(view.tenant_id, view.company_id, view.scope_epoch)
        TimelineView(view.tenant_id, view.company_id, view.scope_epoch, view.generated_at, view.entries,
                     view.hidden_by_scope, view.digest, view.authority, view.basis)
        _check_epoch(viewer, authority)  # type: ignore[arg-type]
        return view

    return _guard(run, correlation_id)  # type: ignore[return-value]
