"""Phase 2 sprint S8 / E2 (R2-US-040, TC118-TC120): the auditor's timeline view model.

Offline, unwired, in-memory, synchronous. A pure function turns existing immutable records (``RunLedger``
runs, ``AttestationStore`` history, ``EventLedger`` events, a ``MatrixResult``) into a frozen view that
a future UI must render verbatim. Nothing here is authoritative and nothing here can set a status:

* Two time axes are two different types. ``KnownTimeLabel`` (label ``KNOWN_AT``) is when the system
  recorded or knew a fact; ``EffectiveTimeLabel`` (label ``EFFECTIVE_AT``) is source-effective validity.
  A missing effective time is the explicit ``EFFECTIVE_UNKNOWN`` label - never filled from the known
  time, the observed time or "now". An entry has no single ambiguous "date" field. Every timestamp is an
  exact ``datetime`` whose tzinfo is the UTC singleton.
* ``Applicability`` is computed by one fixed rule and ``is_green`` is the only green predicate. Only
  ``LIVE_CURRENT`` is green; it needs ALL of: the run is the ledger's CURRENT run and PASS; its
  attestation passes ``AttestationStore.check_current`` (the gate; the historical as-of query is never
  used) and was signed at or before the injected clock; the matrix covers the viewer's company; the run is
  inside the injected freshness window on the injected clock; the revision is the policy's current
  revision; the source is not paused; and no newer GAP / SOURCE_UNAVAILABLE / ATTESTATION_REVOKED event of
  the viewer's company is known at the injected clock (events carry no run key, so the rule is company-wide
  and fail-closed). Any missing or unusable input downgrades to a NAMED non-green value, never to a
  default green.
* Scope is enforced here, not by a renderer, with ONE identity rule (``scope_relation``): a subject, feed
  or claim is the viewer's only if its tenant and company are exactly (``type(x) is str`` and ``==``) the
  viewer's; a casefold/NFKC variant is foreign and is never read. Foreign rows are dropped BEFORE any read
  or validation and leave only the opaque ``hidden_by_scope`` flag (no count, no id, no name), set only for
  another company of the SAME tenant (a row of another tenant leaves no trace at all). Foreign data can
  never change what the viewer sees or make a build fail. A stale scope epoch gives a ``SafeError`` and no
  view; ``render_guard`` re-checks the epoch immediately before disclosure and re-verifies the digest.
* Attestations are shown only when a ``RunBinding`` of the viewer's own runs references them (they carry no
  company, so the binding is the only proof of ownership); unreferenced or foreign ones are never emitted.

Public functions never raise: hostile input (wrong or lying types, naive timestamps, forged
``object.__new__`` instances, recursive/huge values) gives a fixed ``SafeError``; a fault of an injected
provider (ledger, attestation store, event ledger, clock) is ``INTERNAL_REFUSED``, never the viewer's
``INPUT_INVALID``. No caller text is echoed into any outward value. Authority is ``EVALUATION_ONLY``; the
data are scripted/offline when produced over fakes. KNOWN GAPS: the freshness window, source-paused flag,
current revision and scope epochs are injected facts, not read from a real source; attestations are
tenant-scoped (they carry no company); a revoked attestation stays REVOKED even at an earlier injected clock
(``check_current`` takes no time and a regressed clock must not resurrect it); matrix rows hold only
normalised scope keys, so the matrix match is by ``scope_key``.

This module also owns the helpers shared with ``coverage_view`` (public: ``Refuse``, ``guard``,
``provider``, ``check_epoch``, ``scope_relation``, ``scoped_matrix``, ``matrix_digest`` ...).
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, NoReturn

from ._identity import clean_identity, exact_text, scope_key, stable_key
from .comparison_snapshot import ComparisonState, RunLedger, RunRecord, RunView, canonical_digest
from .evidence_attestation import Attestation, AttestationStore
from .temporal import EventKind, EventLedger, ModelEvent
from .validation_coverage import CoverageCode, CoverageStatus, MatrixResult, MatrixRow
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
    "OTHER", "OWN", "SIBLING",
    "Applicability", "ApplicabilityPolicy", "ApplicabilityReason", "EffectiveTimeLabel", "EntryKind",
    "EventFeed", "KnownTimeLabel", "Refuse", "RunBinding", "ScopeAuthority", "ScopedMatrix",
    "TimelineEntry", "TimelineSubject", "TimelineView", "build_timeline", "check_epoch", "digest_ok",
    "guard", "is_green", "matrix_digest", "provider", "provider_invalid", "render_guard", "scope_relation",
    "scoped_matrix", "text_ok", "utc_exact", "viewer_and_epoch",
]

KNOWN_AT_LABEL: Final = "KNOWN_AT"
EFFECTIVE_AT_LABEL: Final = "EFFECTIVE_AT"
EFFECTIVE_UNKNOWN_LABEL: Final = "EFFECTIVE_UNKNOWN"
HISTORICAL_LABEL: Final = "historical, not current"
BASIS: Final = "offline in-memory view over scripted records; EVALUATION_ONLY, not native PASS or validation"
OWN: Final = "OWN"  # exactly the viewer's (tenant, company)
SIBLING: Final = "SIBLING"  # another company of the viewer's tenant: dropped, opaque flag only
OTHER: Final = "OTHER"  # anything else, including another tenant: dropped, no trace at all
_HEX: Final = re.compile(r"[0-9a-f]{64}")
_MAX_WINDOW: Final = 10 * 365 * 24 * 3600
_MAX_EPOCH: Final = 2**63 - 1
_BLOCKING_EVENTS: Final = frozenset({EventKind.GAP, EventKind.SOURCE_UNAVAILABLE, EventKind.ATTESTATION_REVOKED})


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


# ------------------------------------------------------------------ shared helpers (public)
class Refuse(Exception):
    def __init__(self, code: ReasonCode) -> None:
        super().__init__(code.value)
        self.code = code


def provider_invalid() -> NoReturn:
    """An injected provider returned something malformed: the fault is not the viewer's."""
    raise Refuse(ReasonCode.INTERNAL_REFUSED)


def provider(fn: Callable[..., object], *args: object) -> object:
    """Call ``fn`` (an injected provider, or code over its output); any failure is INTERNAL_REFUSED."""
    try:
        return fn(*args)
    except Refuse:
        raise
    except Exception:  # noqa: BLE001 - the provider's exception text is never surfaced
        raise Refuse(ReasonCode.INTERNAL_REFUSED) from None


def text_ok(value: object) -> bool:
    return type(value) is str and value != "" and exact_text(value) == value


def digest_ok(value: object) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def utc_exact(value: object) -> bool:
    """An exact ``datetime`` whose tzinfo is the UTC singleton (a zero-offset other zone is refused)."""
    return type(value) is datetime and value.tzinfo is UTC


def _flatten(value: object) -> datetime | None:
    """Exact aware-UTC copy of an exact aware ``datetime`` (never a subclass), else None."""
    try:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            return None
        moved = value.astimezone(UTC)
        return datetime(moved.year, moved.month, moved.day, moved.hour, moved.minute, moved.second,
                        moved.microsecond, tzinfo=UTC)
    except Exception:  # noqa: BLE001 - OverflowError near min/max, hostile tzinfo
        return None


def _clock_now(clock: object) -> datetime:
    """Strict: only an exact aware ``datetime`` from a callable clock is accepted."""
    if not callable(clock):
        raise Refuse(ReasonCode.INPUT_INVALID)
    try:
        raw = clock()
    except Exception:  # noqa: BLE001 - the exception text is never surfaced
        raise Refuse(ReasonCode.INTERNAL_REFUSED) from None
    moved = _flatten(raw)
    if moved is None:
        raise Refuse(ReasonCode.INTERNAL_REFUSED)
    return moved


def scope_relation(viewer: ViewerScope, tenant: object, company: object) -> str:
    """The single identity rule: OWN only for exact ``str`` equality of tenant AND company; SIBLING for
    another company (or a casefold/NFKC variant) of the same tenant; OTHER for everything else."""
    try:
        vt, vc = viewer.tenant_id, viewer.company_id
        if not all(type(x) is str for x in (vt, vc, tenant, company)):
            return OTHER
        if tenant == vt and company == vc:
            return OWN
        normal = clean_identity(vt)
        return SIBLING if normal and clean_identity(tenant) == normal else OTHER
    except Exception:  # noqa: BLE001 - hostile viewer object
        return OTHER


# ------------------------------------------------------------------ labels
@dataclass(frozen=True, slots=True)
class KnownTimeLabel:
    """When the system recorded or knew the fact (known axis)."""

    at: datetime
    label: str = KNOWN_AT_LABEL

    def __post_init__(self) -> None:
        if not utc_exact(self.at) or type(self.label) is not str or self.label != KNOWN_AT_LABEL:
            raise ValueError("TIME_LABEL_INVALID")


@dataclass(frozen=True, slots=True)
class EffectiveTimeLabel:
    """Source-effective validity (effective axis); ``at`` is None exactly when the label says unknown."""

    at: datetime | None
    label: str
    reason: ReasonCode | None

    def __post_init__(self) -> None:
        known = (utc_exact(self.at) and type(self.label) is str and self.label == EFFECTIVE_AT_LABEL
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
        if (type(self.kind) is not EntryKind or not text_ok(self.ref_id)
                or type(self.known) is not KnownTimeLabel or type(self.effective) is not EffectiveTimeLabel
                or type(self.applicability) is not Applicability
                or (self.reason is not None and type(self.reason) is not ApplicabilityReason)
                or (live and self.reason is not None) or (not live and self.reason is None)
                or not text_ok(self.label_text) or len(self.label_text) > 128
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


def _entry_digest_row(e: TimelineEntry) -> list[object]:
    return [e.kind.value, e.ref_id, e.known.at, e.effective.at, e.applicability.value,
            None if e.reason is None else e.reason.value, e.label_text, e.gap]


def _timeline_digest(tenant_id: str, company_id: str, epoch: int, at: datetime, hidden: bool,
                     entries: tuple[TimelineEntry, ...]) -> str:
    return canonical_digest({
        "v": 1, "tenant": tenant_id, "company": company_id, "epoch": epoch, "at": at, "hidden": hidden,
        "entries": [_entry_digest_row(e) for e in entries]})


def _digest_matches(view: TimelineView) -> bool:
    try:
        return view.digest == _timeline_digest(view.tenant_id, view.company_id, view.scope_epoch,
                                               view.generated_at, view.hidden_by_scope, view.entries)
    except Exception:  # noqa: BLE001 - an entry that cannot be hashed is not a valid view
        return False


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
        if (not text_ok(self.tenant_id) or not text_ok(self.company_id)
                or type(self.scope_epoch) is not int or not 0 <= self.scope_epoch <= _MAX_EPOCH
                or not utc_exact(self.generated_at) or type(self.entries) is not tuple
                or any(type(e) is not TimelineEntry for e in self.entries)
                or type(self.hidden_by_scope) is not bool or not digest_ok(self.digest)
                or type(self.authority) is not str or self.authority != AUTHORITY
                or type(self.basis) is not str or self.basis != BASIS
                or not _digest_matches(self)):
            raise ValueError("TIMELINE_VIEW_INVALID")

    def by_known(self) -> tuple[TimelineEntry, ...]:
        """Entries on the known axis (when the system knew), oldest first."""
        try:
            return tuple(sorted(self.entries, key=_known_key))
        except (TypeError, AttributeError):  # forged entry fields: never a partial order
            raise ValueError("TIMELINE_VIEW_INVALID") from None

    def by_effective(self) -> tuple[TimelineEntry, ...]:
        """Entries on the effective axis; entries with unknown effective time come last, in known order."""
        try:
            dated = [e for e in self.entries if e.effective.at is not None]
            undated = [e for e in self.entries if e.effective.at is None]
            dated.sort(key=lambda e: (e.effective.at, *_known_key(e)))
            undated.sort(key=_known_key)
            return tuple(dated + undated)
        except (TypeError, AttributeError):
            raise ValueError("TIMELINE_VIEW_INVALID") from None


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
        if (not text_ok(self.run_id) or (self.attestation_id is not None and not text_ok(self.attestation_id))
                or not digest_ok(self.revision_digest) or not text_ok(self.policy_version)
                or not digest_ok(self.policy_digest)):
            raise ValueError("RUN_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class TimelineSubject:
    """One comparison key owned by one (tenant, company), with the bindings of its runs."""

    tenant_id: str
    company_id: str
    comparison_key: str
    bindings: tuple[RunBinding, ...]

    def __post_init__(self) -> None:
        if (not text_ok(self.tenant_id) or not text_ok(self.company_id) or not text_ok(self.comparison_key)
                or type(self.bindings) is not tuple or any(type(b) is not RunBinding for b in self.bindings)):
            raise ValueError("TIMELINE_SUBJECT_INVALID")


@dataclass(frozen=True, slots=True)
class EventFeed:
    """An ``EventLedger`` owned by one (tenant, company)."""

    tenant_id: str
    company_id: str
    ledger: EventLedger

    def __post_init__(self) -> None:
        if (not text_ok(self.tenant_id) or not text_ok(self.company_id)
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
                or (self.current_revision_digest is not None and not digest_ok(self.current_revision_digest))
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


def check_epoch(viewer: ViewerScope, authority: object) -> None:
    if type(authority) is not ScopeAuthority:
        raise Refuse(ReasonCode.INPUT_INVALID)
    current = authority.current_epoch(viewer.tenant_id, viewer.company_id)
    if current is None or current != viewer.scope_epoch:
        raise Refuse(ReasonCode.SCOPE_EPOCH_STALE)


def viewer_and_epoch(viewer: object, authority: object) -> ViewerScope:
    """A valid viewer whose scope epoch is current, else a ``Refuse``."""
    if not is_valid_scope(viewer):
        raise Refuse(ReasonCode.INPUT_INVALID)
    check_epoch(viewer, authority)  # type: ignore[arg-type]
    return viewer  # type: ignore[return-value]


def guard(fn: Callable[[], object], correlation_id: object) -> object:
    """Run ``fn``; any failure becomes a fixed ``SafeError`` (never an echo, never an exception)."""
    try:
        return fn()
    except Refuse as refusal:
        return safe_error(refusal.code, correlation_id)
    except (AttributeError, TypeError, ValueError, KeyError):
        return safe_error(ReasonCode.INPUT_INVALID, correlation_id)  # forged/hostile caller argument
    except Exception:  # noqa: BLE001 - includes RecursionError/MemoryError-like failures
        return safe_error(ReasonCode.INTERNAL_REFUSED, correlation_id)


# ------------------------------------------------------------------ matrix (shared with coverage_view)
def _row_key(row: MatrixRow) -> str:
    refs = sorted(zip(row.evidence_ids, row.evidence_digests, row.evidence_sources, strict=False))
    return stable_key(
        row.scope[0], row.scope[1], row.claim_id, row.capability, row.operation,
        *(stable_key(*r) for r in refs), "|", *sorted(row.non_pass_ids),
    )


def matrix_digest(rows: tuple[MatrixRow, ...] | list[MatrixRow]) -> str:
    """Local recomputation of the ``MatrixResult`` digest from its public row fields (same recipe as
    ``validation_coverage``; kept here so no private name is imported across modules)."""
    return hashlib.sha256(stable_key(*sorted(_row_key(r) for r in rows)).encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopedMatrix:
    """What the viewer may use of a matrix: only their own rows, plus the opaque sibling-company flag."""

    status: CoverageStatus
    rows: tuple[MatrixRow, ...]
    hidden: bool
    uncovered: tuple[str, ...]


def _own_row_ok(r: MatrixRow) -> bool:
    return (text_ok(r.claim_id) and type(r.capability) is str and type(r.operation) is str
            and all(type(t) is tuple and all(type(x) is str for x in t)
                    for t in (r.evidence_ids, r.evidence_digests, r.evidence_sources, r.non_pass_ids))
            and len(r.evidence_ids) == len(r.evidence_digests) == len(r.evidence_sources))


def scoped_matrix(matrix: object, viewer: ViewerScope) -> ScopedMatrix:
    """Verify the matrix (types, integrity digest) and keep the viewer's own rows; ``Refuse`` if unusable.

    Matrix rows carry only ``scope_key``-normalised scopes, so the match is by ``scope_key`` (not exact).
    A foreign row is never validated beyond what the integrity digest needs: junk in it cannot change the
    viewer's rows. A REFUSED matrix yields no rows at all (its global reason is never passed on).
    """
    vkey = scope_key(viewer.tenant_id, viewer.company_id)
    if (vkey is None or type(matrix) is not MatrixResult or type(matrix.status) is not CoverageStatus
            or type(matrix.code) is not CoverageCode or type(matrix.rows) is not tuple
            or type(matrix.uncovered) is not tuple or type(matrix.non_pass) is not tuple
            or type(matrix.digest) is not str):
        raise Refuse(ReasonCode.INPUT_INVALID)
    if matrix.status is CoverageStatus.REFUSED:
        return ScopedMatrix(CoverageStatus.REFUSED, (), False, ())
    if any(type(r) is not MatrixRow for r in matrix.rows):
        raise Refuse(ReasonCode.INPUT_INVALID)
    try:
        intact = matrix.digest == matrix_digest(matrix.rows)
    except Exception:  # noqa: BLE001 - unhashable/hostile row content
        intact = False
    if not intact:
        raise Refuse(ReasonCode.INPUT_INVALID)  # tampered rows do not verify
    mine: list[MatrixRow] = []
    hidden = False
    for r in matrix.rows:
        scope = r.scope
        if type(scope) is not tuple or len(scope) != 2 or not all(type(x) is str for x in scope):
            continue  # unidentifiable row: not the viewer's, nothing is said about it
        if scope == vkey:
            if not _own_row_ok(r):
                raise Refuse(ReasonCode.INPUT_INVALID)
            mine.append(r)
        elif scope[0] == vkey[0]:
            hidden = True  # another company of the same tenant
    uncovered = tuple(x for x in matrix.uncovered if type(x) is str)
    return ScopedMatrix(matrix.status, tuple(mine), hidden, uncovered)


# ------------------------------------------------------------------ applicability rule
def _in_scope_coverage(matrix: object, viewer: ViewerScope) -> bool | None:
    """True/False for the viewer's company, None when the matrix itself is unusable (never guessed)."""
    try:
        sm = scoped_matrix(matrix, viewer)
        if sm.status is CoverageStatus.REFUSED or not sm.rows:
            return False
        return all(r.evidence_ids and not r.non_pass_ids and r.claim_id not in sm.uncovered for r in sm.rows)
    except Exception:  # noqa: BLE001 - forged or hostile matrix: unknown, never covered
        return None


def _decide_run(view: RunView, binding: RunBinding | None, att: AttestationStore,
                signed: dict[str, datetime], policy: ApplicabilityPolicy, covered: bool | None,
                now: datetime, event_block: ApplicabilityReason | None,
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
    signed_at = signed.get(binding.attestation_id) if binding is not None and binding.attestation_id else None
    if not check.valid or check.code != "VALID" or signed_at is None or signed_at > now:
        return A.UNATTESTED, R.ATTESTATION_NOT_CURRENT  # unsigned at the injected clock is not current
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
    if event_block is R.ATTESTATION_REVOKED:
        return A.REVOKED, R.ATTESTATION_REVOKED  # a newer revocation event outranks the store check
    if event_block is R.HISTORY_GAP:
        return A.UNKNOWN, R.HISTORY_GAP  # newer gap / source outage: the run may no longer describe the source
    return A.LIVE_CURRENT, None


def _entry(kind: EntryKind, ref: str, known: datetime, effective: EffectiveTimeLabel,
           applic: Applicability, reason: ApplicabilityReason | None, text: str | None = None,
           gap: bool = False) -> TimelineEntry:
    return TimelineEntry(kind, ref, KnownTimeLabel(known), effective, applic, reason,
                         text or _LABEL_TEXT[applic], gap)


def _event_block(marks: list[tuple[datetime, EventKind]], recorded: datetime | None,
                 ) -> ApplicabilityReason | None:
    if recorded is None:
        return None
    newer = {kind for at, kind in marks if at > recorded}
    if EventKind.ATTESTATION_REVOKED in newer:
        return ApplicabilityReason.ATTESTATION_REVOKED
    if newer & {EventKind.GAP, EventKind.SOURCE_UNAVAILABLE}:
        return ApplicabilityReason.HISTORY_GAP
    return None


def _run_entries(ledger: RunLedger, att: AttestationStore, signed: dict[str, datetime], sub: TimelineSubject,
                 policy: ApplicabilityPolicy, covered: bool | None, now: datetime,
                 marks: list[tuple[datetime, EventKind]]) -> tuple[list[TimelineEntry], set[str]]:
    by_run: dict[str, RunBinding] = {}
    for binding in sub.bindings:
        if binding.run_id in by_run:
            raise Refuse(ReasonCode.INPUT_INVALID)
        by_run[binding.run_id] = binding
    out: list[TimelineEntry] = []
    referenced: set[str] = set()
    views = ledger.list_runs(sub.tenant_id, sub.comparison_key)
    if type(views) is not tuple:
        provider_invalid()
    for view in views:
        if type(view) is not RunView or type(view.record) is not RunRecord:
            provider_invalid()
        known = _flatten(view.record.recorded_at)
        if (known is None or view.record.tenant_id != sub.tenant_id
                or view.record.comparison_key != sub.comparison_key):
            provider_invalid()
        binding = by_run.get(view.record.run_id)
        if binding is not None and binding.attestation_id is not None:
            referenced.add(binding.attestation_id)
        try:
            applic, reason = _decide_run(view, binding, att, signed, policy, covered, now,
                                         _event_block(marks, known))
        except Exception:  # noqa: BLE001 - any failure in the rule is UNKNOWN, never green
            applic, reason = Applicability.UNKNOWN, ApplicabilityReason.INPUT_UNKNOWN
        out.append(_entry(EntryKind.RUN, view.record.run_id, known, EffectiveTimeLabel.unknown(),
                          applic, reason))
    return out, referenced


def _attestation_rows(att: AttestationStore, tenant_id: str) -> tuple[Attestation, ...]:
    items = att.history(tenant_id)
    if type(items) is not tuple:
        provider_invalid()
    normal = clean_identity(tenant_id)
    for item in items:
        if type(item) is not Attestation or item.tenant_id != normal or _flatten(item.signed_at) is None:
            provider_invalid()
    return items


def _attestation_entries(items: tuple[Attestation, ...], wanted: set[str], now: datetime,
                         ) -> list[TimelineEntry]:
    out = []
    for item in items:
        if item.attestation_id not in wanted:
            continue  # never emit an attestation no run of the viewer's company references
        signed = _flatten(item.signed_at)
        if signed is None or signed > now:
            continue  # not yet signed at the injected clock
        if item.revoked_at is not None:
            out.append(_entry(EntryKind.ATTESTATION, item.attestation_id, signed, EffectiveTimeLabel.unknown(),
                              Applicability.REVOKED, ApplicabilityReason.ATTESTATION_REVOKED))
        else:  # an attestation is evidence for a run verdict, never a verdict of its own
            out.append(_entry(EntryKind.ATTESTATION, item.attestation_id, signed, EffectiveTimeLabel.unknown(),
                              Applicability.UNKNOWN, ApplicabilityReason.EVIDENCE_ROW, "evidence record"))
    return out


def _event_entries(feed: EventFeed, now: datetime,
                   ) -> tuple[list[TimelineEntry], list[tuple[datetime, EventKind]]]:
    out: list[TimelineEntry] = []
    marks: list[tuple[datetime, EventKind]] = []
    events = feed.ledger.events
    if type(events) is not tuple:
        provider_invalid()
    for ev in events:
        if type(ev) is not ModelEvent or type(ev.kind) is not EventKind:
            provider_invalid()
        known = _flatten(ev.recorded_at)
        if known is None:
            provider_invalid()
        if known > now:
            continue  # not yet known at the injected clock
        eff = ev.source_effective_at
        effective = EffectiveTimeLabel.unknown()  # never copied from recorded/observed time
        if eff is not None:
            flat = _flatten(eff)
            if flat is None:
                provider_invalid()
            effective = EffectiveTimeLabel.at_time(flat)
        if ev.kind in _BLOCKING_EVENTS:
            marks.append((known, ev.kind))
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
    return out, marks


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
            raise Refuse(ReasonCode.INPUT_INVALID)
        check_epoch(viewer, authority)  # type: ignore[arg-type,union-attr]
        now = _clock_now(clock)
        if (type(ledger) is not RunLedger or type(attestations) is not AttestationStore
                or type(subjects) is not tuple or type(feeds) is not tuple
                or type(policy) is not ApplicabilityPolicy):
            raise Refuse(ReasonCode.INPUT_INVALID)
        ApplicabilityPolicy(policy.freshness_seconds, policy.current_revision_digest, policy.source_paused)
        covered = _in_scope_coverage(matrix, viewer)  # type: ignore[arg-type]
        hidden = False
        own_subjects: list[TimelineSubject] = []
        seen: set[str] = set()
        for sub in subjects:
            if type(sub) is not TimelineSubject:
                raise Refuse(ReasonCode.INPUT_INVALID)
            relation = scope_relation(viewer, sub.tenant_id, sub.company_id)  # type: ignore[arg-type]
            if relation != OWN:
                hidden = hidden or relation == SIBLING  # dropped unread and unvalidated
                continue
            TimelineSubject(sub.tenant_id, sub.company_id, sub.comparison_key, sub.bindings)
            for b in sub.bindings:
                RunBinding(b.run_id, b.attestation_id, b.revision_digest, b.policy_version, b.policy_digest)
            if sub.comparison_key not in seen:
                seen.add(sub.comparison_key)
                own_subjects.append(sub)
        entries: list[TimelineEntry] = []
        marks: list[tuple[datetime, EventKind]] = []
        for feed in feeds:
            if type(feed) is not EventFeed:
                raise Refuse(ReasonCode.INPUT_INVALID)
            relation = scope_relation(viewer, feed.tenant_id, feed.company_id)  # type: ignore[arg-type]
            if relation != OWN:
                hidden = hidden or relation == SIBLING
                continue
            EventFeed(feed.tenant_id, feed.company_id, feed.ledger)
            if feed.ledger.tenant_id != feed.tenant_id:
                raise Refuse(ReasonCode.INPUT_INVALID)
            got, new_marks = provider(_event_entries, feed, now)  # type: ignore[misc]
            entries.extend(got)
            marks.extend(new_marks)
        rows = provider(_attestation_rows, attestations, viewer.tenant_id)  # type: ignore[union-attr]
        signed = {a.attestation_id: s for a in rows if (s := _flatten(a.signed_at)) is not None}  # type: ignore[attr-defined]
        wanted: set[str] = set()
        for sub in own_subjects:
            got, refs = provider(_run_entries, ledger, attestations, signed, sub, policy, covered, now,  # type: ignore[misc]
                                 marks)
            entries.extend(got)
            wanted |= refs
        entries.extend(provider(_attestation_entries, rows, wanted, now))  # type: ignore[arg-type]
        entries.sort(key=_known_key)
        digest = _timeline_digest(viewer.tenant_id, viewer.company_id, viewer.scope_epoch, now, hidden,
                                  tuple(entries))  # type: ignore[union-attr]
        view = TimelineView(viewer.tenant_id, viewer.company_id, viewer.scope_epoch, now, tuple(entries),  # type: ignore[union-attr]
                            hidden, digest)
        check_epoch(viewer, authority)  # type: ignore[arg-type]  # re-check immediately before disclosure
        return view

    return guard(run, correlation_id)  # type: ignore[return-value]


def render_guard(view: object, authority: object, *, correlation_id: object = DEFAULT_CORRELATION_ID,
                 ) -> TimelineView | SafeError:
    """Re-verify the digest and the viewer's scope epoch right before a built view is disclosed."""
    def run() -> TimelineView:
        if type(view) is not TimelineView:
            raise Refuse(ReasonCode.INPUT_INVALID)
        viewer = ViewerScope(view.tenant_id, view.company_id, view.scope_epoch)
        TimelineView(view.tenant_id, view.company_id, view.scope_epoch, view.generated_at, view.entries,
                     view.hidden_by_scope, view.digest, view.authority, view.basis)  # recomputes the digest
        check_epoch(viewer, authority)  # type: ignore[arg-type]
        return view

    return guard(run, correlation_id)  # type: ignore[return-value]
