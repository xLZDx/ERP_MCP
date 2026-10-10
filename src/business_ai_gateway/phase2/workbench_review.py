"""Phase 2 sprint S8 E1 (R2-US-039): discrepancy cards, original-number integrity, review log, safe rerun.

Offline, unwired, in-memory. A ``DiscrepancyCard`` is a DERIVED, frozen view of one differing measure
of one recorded run. It carries the numbers exactly as the ``RunLedger`` stored them (exact
``Decimal``), the delta ``gateway - native`` computed in a fixed exact context (a precision overflow
is a per-card fixed note with ``delta=None``, never a rounded delta and never a failure of the other
cards), a fragment reference into the frozen snapshot, the owner from an injected directory
(``OWNER_UNASSIGNED`` when unmapped, never guessed) and an ``original_digest`` over the run's
immutable record. ``verify_original`` recomputes everything from the ledger.

Company boundary: every public entry point takes an injected ``OwnershipPort`` (keyword, required) and
refuses ``NOT_IN_SCOPE`` BEFORE any ledger read when the viewer's company does not own the
comparison key / run id / snapshot id / source id. A foreign reference and an unknown one produce the
IDENTICAL refusal (no existence oracle). The epoch authority is also required: ``current_epoch`` is a
zero-argument callable returning the live scope epoch; it is read at the start and again immediately
before data is returned or a run is committed (TOCTOU), and a mismatch is ``SCOPE_EPOCH_STALE``.

Nothing here can change a number or a verdict: no public function accepts numbers, states or
verdicts from the caller. The ``ReviewLog`` is append-only text annotation keyed by run id. New
evidence is a NEW run: ``check_rerun`` (pure validation, creates nothing) and ``commit_rerun``
(reader + run + annotation) are separable steps; ``request_rerun`` is the one-call wrapper. The
earlier run is never edited.

Public functions never raise: any refusal is a ``SafeError`` (fixed reason code + next action, no
caller input echoed). Authority is ``EVALUATION_ONLY``.

Honest limits (narrow guarantee of ``verify_original``): the ``RunLedger`` stores measure keys and
totals only. ``ORIGINAL_INTACT`` means "this card equals what the ledger recorded for that run" and is
returned for RUN_LEDGER cards, and for COMPARISON-basis cards only when they are recomputable from the
ledger (a totals row, ``row_key is None``, whose numbers equal the ledger's). Row-level numbers supplied
through ``comparison=`` are bound to the run (the measure set must equal the run's differing measures)
but are caller-supplied and NOT recomputable: ``verify_original`` returns ``ORIGINAL_UNVERIFIABLE`` for
them, never ``ORIGINAL_INTACT``. Digests bind the numeric VALUE (the canonical encoder normalises
``10.10`` and ``10.1`` to the same text), not the display scale. The ``card_digest`` is an unkeyed
self-consistency check (it detects edits, it is not a signature). Source pause/revoke and actor
authorization (design decision 12) belong to the jobs API, not here.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Final

from ._identity import canonical_guid, exact_text
from .comparison_snapshot import (
    _EXACT,
    ComparisonSnapshotError,
    ComparisonState,
    RunLedger,
    RunRecord,
    SideRead,
    SnapshotStore,
    canonical_digest,
)
from .reconciliation import Comparison, Difference
from .reconciliation import ComparisonState as ReconState
from .workbench_types import (
    AUTHORITY,
    AnnotationKind,
    ReasonCode,
    SafeError,
    ViewerScope,
    is_valid_directory,
    is_valid_scope,
    safe_error,
)

__all__ = [
    "BASIS_COMPARISON", "BASIS_RUN_LEDGER", "MAX_LOG_ENTRIES", "MAX_RUN_ENTRIES", "MAX_TENANT_ENTRIES",
    "RUN_STATE_NO_RUN", "AnnotationEntry", "CardsResult", "DiscrepancyCard", "FragmentRef", "RerunOutcome",
    "RerunPlan", "ReviewLog", "build_cards", "check_rerun", "commit_rerun", "request_override",
    "request_rerun", "verify_original",
]

BASIS_RUN_LEDGER: Final = "RUN_LEDGER"
BASIS_COMPARISON: Final = "COMPARISON"
RUN_STATE_NO_RUN: Final = "NO_RUN"
MAX_RUN_ENTRIES: Final = 200  # annotations per (tenant, run)
MAX_TENANT_ENTRIES: Final = 2000  # annotations per tenant
MAX_LOG_ENTRIES: Final = 50_000  # small global ceiling above the per-tenant quotas
MAX_NOTE_CHARS: Final = 500
MAX_CARDS: Final = 10_000
_MAX_EXPONENT: Final = 100
_BAD_NOTE_CATEGORIES: Final = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp", "Zs"})
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_STATUSES: Final = frozenset({"CURRENT", "LATEST_ATTEMPT", "SUPERSEDED"})
_RUN_STATES: Final = frozenset({RUN_STATE_NO_RUN, "PASS", "FAIL", "INCONCLUSIVE"})
_ADJUSTMENT_WORDS: Final = frozenset({"ADJUSTMENT", "ADJUST", "OVERRIDE", "CORRECTION", "SET_NUMBERS"})
_RERUN_NOTE: Final = "rerun requested"


class _Refuse(Exception):
    """Internal control flow only; converted to a ``SafeError`` at every public boundary."""

    def __init__(self, code: ReasonCode) -> None:
        super().__init__(code.value)
        self.code = code


# --------------------------------------------------------------------------------------------------
# small validators (exact types; subclasses and lookalikes are refused)

def _txt(value: object) -> str:
    if type(value) is not str or value == "" or exact_text(value) != value:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    return value


def _note_ok(text: str) -> bool:
    """Bounded single-line free text. Unlike identities, mixed scripts (RU + Latin) are allowed."""
    if len(text) > MAX_NOTE_CHARS:
        return False
    for ch in text:
        if ch != " " and unicodedata.category(ch) in _BAD_NOTE_CATEGORIES:
            return False
    return text == "" or any(unicodedata.category(ch)[0] in "LNP" for ch in text)


def _dec_ok(value: object) -> bool:
    return type(value) is Decimal and value.is_finite() and abs(value.adjusted()) <= _MAX_EXPONENT


def _dec_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if not _dec_ok(value):  # NaN / Inf / exponent beyond the ledger's bound: a fixed input refusal
        raise _Refuse(ReasonCode.INPUT_INVALID)
    return value  # type: ignore[return-value]


def _same(a: object, b: object) -> bool:
    """Value equality for exact Decimals / None only; a lying ``__eq__`` subclass never matches."""
    if a is None or b is None:
        return a is None and b is None
    return type(a) is Decimal and type(b) is Decimal and a.is_finite() and b.is_finite() and a == b


class _Epoch:
    """The required epoch authority: a callable returning the live epoch; never skipped, never trusted."""

    def __init__(self, source: object) -> None:
        if not callable(source):
            raise _Refuse(ReasonCode.INPUT_INVALID)
        self._source = source

    def check(self, viewer: ViewerScope) -> None:
        try:
            live = self._source()  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
            raise _Refuse(ReasonCode.DEPENDENCY_FAILED) from None
        if type(live) is not int:
            raise _Refuse(ReasonCode.DEPENDENCY_FAILED)
        if live != viewer.scope_epoch:
            raise _Refuse(ReasonCode.SCOPE_EPOCH_STALE)


class _Scope:
    """Viewer + ownership port + epoch authority; the company boundary gate."""

    def __init__(self, viewer: object, ownership: object, current_epoch: object) -> None:
        self.viewer = _need_viewer(viewer)
        owns = getattr(ownership, "owns", None)
        if ownership is None or isinstance(ownership, (str, bytes, int)) or not callable(owns):
            raise _Refuse(ReasonCode.INPUT_INVALID)
        self._owns = owns
        self.epoch = _Epoch(current_epoch)

    def gate(self, tenant: str, refs: tuple[tuple[str, str], ...]) -> None:
        """Tenant, then epoch, then ownership of every reference: BEFORE any ledger read."""
        if tenant != self.viewer.tenant_id:
            raise _Refuse(ReasonCode.NOT_IN_SCOPE)
        self.epoch.check(self.viewer)
        for kind, ref in refs:
            try:
                answer = self._owns(self.viewer.tenant_id, self.viewer.company_id, kind, ref)
            except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
                raise _Refuse(ReasonCode.DEPENDENCY_FAILED) from None
            if answer is not True:  # foreign and unknown are indistinguishable by construction
                raise _Refuse(ReasonCode.NOT_IN_SCOPE)

    def recheck_epoch(self) -> None:
        self.epoch.check(self.viewer)


def _need_viewer(viewer: object) -> ViewerScope:
    if not is_valid_scope(viewer):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    return viewer  # type: ignore[return-value]


def _need_ledger(ledger: object) -> RunLedger:
    if type(ledger) is not RunLedger:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    try:
        ledger.get("probe", "probe")  # a forged object.__new__ instance has no state
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        raise _Refuse(ReasonCode.INPUT_INVALID) from None
    return ledger


def _need_store(store: object) -> SnapshotStore:
    if type(store) is not SnapshotStore:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    try:
        store.get("probe", "probe")
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        raise _Refuse(ReasonCode.INPUT_INVALID) from None
    return store


def _row_part(value: object) -> str:
    if type(value) is not str:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    return _txt(canonical_guid(value) or value)


def _delta(native: Decimal | None, gateway: Decimal | None) -> tuple[Decimal | None, ReasonCode | None]:
    """``gateway - native`` exactly, or ``(None, DELTA_PRECISION_EXCEEDED)`` for this card only."""
    if native is None or gateway is None:
        return None, None
    try:
        with localcontext(_EXACT):
            result = gateway - native
    except ArithmeticError:
        return None, ReasonCode.DELTA_PRECISION_EXCEEDED
    if not _dec_ok(result):
        return None, ReasonCode.DELTA_PRECISION_EXCEEDED
    return result, None


def _run_digest(run: RunRecord) -> str:
    return canonical_digest({
        "tenant": run.tenant_id, "run_id": run.run_id, "snapshot_digest": run.snapshot_digest,
        "native": run.native_values, "gateway": run.gateway_values,
    })


# --------------------------------------------------------------------------------------------------
# cards

@dataclass(frozen=True, slots=True)
class FragmentRef:
    """A reference into the frozen snapshot: never the raw document."""

    snapshot_digest: str
    row_key: tuple[str, str] | None
    measure: str

    def __post_init__(self) -> None:
        if (type(self.snapshot_digest) is not str or _HEX64.fullmatch(self.snapshot_digest) is None
                or type(self.measure) is not str or not self.measure
                or not (self.row_key is None or (type(self.row_key) is tuple and len(self.row_key) == 2
                                                 and all(type(p) is str and p for p in self.row_key)))):
            raise ValueError("FRAGMENT_INVALID")

    def __repr__(self) -> str:
        return "FragmentRef(<redacted>)"


def _opt_code(value: object) -> bool:
    return value is None or type(value) is ReasonCode


@dataclass(frozen=True, slots=True)
class DiscrepancyCard:
    tenant_id: str
    run_id: str
    comparison_key: str
    run_status: str
    basis: str
    measure: str
    row_key: tuple[str, str] | None
    row_detail: ReasonCode | None
    fragment: FragmentRef
    native: Decimal | None
    gateway: Decimal | None
    delta: Decimal | None
    delta_note: ReasonCode | None
    owner_id: str | None
    owner_note: ReasonCode | None
    original_digest: str
    card_digest: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        texts = (self.tenant_id, self.run_id, self.comparison_key, self.measure)
        if (not all(type(t) is str and t for t in texts)
                or type(self.run_status) is not str or self.run_status not in _STATUSES
                or type(self.basis) is not str or self.basis not in (BASIS_RUN_LEDGER, BASIS_COMPARISON)
                or type(self.fragment) is not FragmentRef
                or not (self.row_key is None or (type(self.row_key) is tuple and len(self.row_key) == 2
                                                 and all(type(p) is str and p for p in self.row_key)))
                or not _opt_code(self.row_detail) or not _opt_code(self.owner_note)
                or not _opt_code(self.delta_note)
                or not (self.owner_id is None or (type(self.owner_id) is str and self.owner_id))
                or type(self.original_digest) is not str or _HEX64.fullmatch(self.original_digest) is None
                or type(self.card_digest) is not str or _HEX64.fullmatch(self.card_digest) is None
                or type(self.authority) is not str or self.authority != AUTHORITY
                or not all(v is None or _dec_ok(v) for v in (self.native, self.gateway, self.delta))):
            raise ValueError("CARD_INVALID")

    def __repr__(self) -> str:
        return "DiscrepancyCard(<redacted>)"


@dataclass(frozen=True, slots=True)
class CardsResult:
    """Cards plus the run they came from: 'no run', PASS, INCONCLUSIVE and FAIL stay distinguishable."""

    run_id: str | None
    run_state: str  # NO_RUN | PASS | FAIL | INCONCLUSIVE
    run_status: str | None  # CURRENT | LATEST_ATTEMPT | SUPERSEDED | None for NO_RUN
    cards: tuple[DiscrepancyCard, ...]
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        if (type(self.run_state) is not str or self.run_state not in _RUN_STATES
                or not (self.run_status is None or (type(self.run_status) is str and self.run_status in _STATUSES))
                or not (self.run_id is None or (type(self.run_id) is str and self.run_id))
                or type(self.cards) is not tuple or not all(type(c) is DiscrepancyCard for c in self.cards)
                or (self.run_state == RUN_STATE_NO_RUN) != (self.run_id is None)
                or (self.run_state != "FAIL" and self.cards)
                or type(self.authority) is not str or self.authority != AUTHORITY):
            raise ValueError("CARDS_RESULT_INVALID")

    def __repr__(self) -> str:
        return "CardsResult(<redacted>)"


def _card_digest(card: DiscrepancyCard) -> str:
    return canonical_digest({
        "tenant": card.tenant_id, "run_id": card.run_id, "comparison_key": card.comparison_key,
        "run_status": card.run_status, "basis": card.basis, "original": card.original_digest,
        "measure": card.measure, "row_key": None if card.row_key is None else list(card.row_key),
        "row_detail": None if card.row_detail is None else card.row_detail.value,
        "native": card.native, "gateway": card.gateway, "delta": card.delta,
        "delta_note": None if card.delta_note is None else card.delta_note.value,
        "owner_id": card.owner_id,
        "owner_note": None if card.owner_note is None else card.owner_note.value,
    })


_Row = tuple[tuple[str, str] | None, str, Decimal | None, Decimal | None]


def _validate_comparison(comparison: object) -> tuple[_Row, ...]:
    if type(comparison) is not Comparison:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    try:
        state, diffs = comparison.state, comparison.differences
    except AttributeError:  # forged object.__new__ instance
        raise _Refuse(ReasonCode.INPUT_INVALID) from None
    if type(state) is not ReconState or type(diffs) is not tuple or len(diffs) > MAX_CARDS:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    rows = []
    seen: set[tuple[tuple[str, str] | None, str]] = set()
    for diff in diffs:
        if type(diff) is not Difference:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        key = diff.row_key
        if key is not None:
            if type(key) is not tuple or len(key) != 2:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            key = (_row_part(key[0]), _row_part(key[1]))
        row = (key, _txt(diff.measure), _dec_or_none(diff.expected), _dec_or_none(diff.actual))
        if (row[0], row[1]) in seen:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        seen.add((row[0], row[1]))
        rows.append(row)
    return tuple(rows)


def _status_of(led: RunLedger, tenant: str, key: str, run_id: str) -> str:
    status = next((v.status for v in led.list_runs(tenant, key) if v.record.run_id == run_id), None)
    if type(status) is not str or status not in _STATUSES:
        raise _Refuse(ReasonCode.INTERNAL_REFUSED)
    return status


def _build_cards(ledger: object, tenant: object, comparison_key: object, owners: object, viewer: object,
                 source_id: object, run_id: object, comparison: object, ownership: object,
                 current_epoch: object) -> CardsResult:
    led = _need_ledger(ledger)
    tenant_t, key, source = _txt(tenant), _txt(comparison_key), _txt(source_id)
    scope = _Scope(viewer, ownership, current_epoch)
    if not is_valid_directory(owners):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    wanted = None if run_id is None else _txt(run_id)
    parsed = None if comparison is None else _validate_comparison(comparison)
    refs = (("comparison_key", key), ("source_id", source))
    scope.gate(tenant_t, refs if wanted is None else (*refs, ("run_id", wanted)))
    view = scope.viewer
    if wanted is None:
        run = led.current(tenant_t, key)
        if run is None:
            views = led.list_runs(tenant_t, key)
            scope.recheck_epoch()
            if not views:
                return CardsResult(None, RUN_STATE_NO_RUN, None, ())
            head = views[-1].record  # only inconclusive attempts exist
            return CardsResult(head.run_id, head.state.value, _status_of(led, tenant_t, key, head.run_id), ())
    else:
        run = led.get(tenant_t, wanted)
        if run is None or run.comparison_key != key:
            raise _Refuse(ReasonCode.NOT_IN_SCOPE)  # same answer as an unknown run: no existence leak
    status = _status_of(led, tenant_t, key, run.run_id)
    if run.state is not ComparisonState.FAIL:
        if parsed:
            raise _Refuse(ReasonCode.INPUT_INVALID)  # differences for a run that did not FAIL
        scope.recheck_epoch()
        return CardsResult(run.run_id, run.state.value, status, ())
    owner = owners.owner_for(tenant_t, view.company_id, source)  # type: ignore[attr-defined]
    original = _run_digest(run)
    if parsed is not None:
        if not parsed:
            raise _Refuse(ReasonCode.INPUT_INVALID)  # a FAIL run cannot be explained by "no differences"
        if {m for _, m, _, _ in parsed} != set(run.differences):
            raise _Refuse(ReasonCode.INPUT_INVALID)  # the comparison must be this run's, measure for measure
        items = [(rk, m, e, a, None, BASIS_COMPARISON) for rk, m, e, a in parsed]
    else:
        nmap, gmap = dict(run.native_values), dict(run.gateway_values)
        items = [(None, m, nmap.get(m), gmap.get(m), ReasonCode.ROW_DETAIL_UNAVAILABLE, BASIS_RUN_LEDGER)
                 for m in run.differences]
    cards = []
    for row_key, measure, native, gateway, detail, basis in items:
        delta, note = _delta(native, gateway)
        base = DiscrepancyCard(
            tenant_t, run.run_id, key, status, basis, measure, row_key, detail,
            FragmentRef(run.snapshot_digest, row_key, measure), native, gateway, delta, note, owner,
            None if owner is not None else ReasonCode.OWNER_UNASSIGNED, original, "0" * 64)
        cards.append(replace(base, card_digest=_card_digest(base)))
    scope.recheck_epoch()  # TOCTOU: nothing is returned for a scope that moved while we read
    return CardsResult(run.run_id, run.state.value, status, tuple(cards))


def build_cards(ledger: object, tenant: object, comparison_key: object, owners: object, viewer: object, *,
                source_id: object, ownership: object, current_epoch: object, run_id: object = None,
                comparison: object = None) -> CardsResult | SafeError:
    """Cards for the differing measures of the CURRENT decisive run (or of ``run_id``).

    The result states whether a run exists and which state it has (``NO_RUN``/``PASS``/``INCONCLUSIVE``
    carry no cards but are distinguishable from each other and from ``FAIL``).
    """
    try:
        return _build_cards(ledger, tenant, comparison_key, owners, viewer, source_id, run_id, comparison,
                            ownership, current_epoch)
    except _Refuse as refusal:
        return safe_error(refusal.code)
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        return safe_error(ReasonCode.INTERNAL_REFUSED)


_CARD_FIELDS: Final = (
    "tenant_id", "run_id", "comparison_key", "run_status", "basis", "measure", "row_key", "row_detail",
    "fragment", "native", "gateway", "delta", "delta_note", "owner_id", "owner_note", "original_digest",
    "card_digest", "authority",
)


def _rebuilt(card: object) -> DiscrepancyCard | None:
    """A validated copy of a possibly forged card, or None when it is not a well-formed card."""
    if type(card) is not DiscrepancyCard:
        return None
    try:
        return DiscrepancyCard(*(getattr(card, name) for name in _CARD_FIELDS))
    except Exception:  # noqa: BLE001 - forged instance (missing slots / bad values) is simply not a card
        return None


def _verify(card: object, ledger: object, viewer: object, ownership: object, current_epoch: object) -> ReasonCode:
    c = _rebuilt(card)
    if c is None:
        return ReasonCode.ORIGINAL_TAMPERED
    scope = _Scope(viewer, ownership, current_epoch)
    try:
        led = _need_ledger(ledger)
    except _Refuse:
        raise _Refuse(ReasonCode.INTERNAL_REFUSED) from None
    scope.gate(c.tenant_id, (("comparison_key", c.comparison_key), ("run_id", c.run_id)))
    run = led.get(c.tenant_id, c.run_id)
    if run is None or run.comparison_key != c.comparison_key or run.state is not ComparisonState.FAIL:
        return ReasonCode.ORIGINAL_TAMPERED
    if c.original_digest != _run_digest(run) or c.card_digest != _card_digest(c):
        return ReasonCode.ORIGINAL_TAMPERED
    frag = c.fragment
    if frag.snapshot_digest != run.snapshot_digest or frag.measure != c.measure or frag.row_key != c.row_key:
        return ReasonCode.ORIGINAL_TAMPERED
    delta, note = _delta(c.native, c.gateway)
    if not _same(c.delta, delta) or c.delta_note is not note:
        return ReasonCode.ORIGINAL_TAMPERED
    if c.measure not in run.differences:
        return ReasonCode.ORIGINAL_TAMPERED
    nmap, gmap = dict(run.native_values), dict(run.gateway_values)
    recorded_equal = _same(c.native, nmap.get(c.measure)) and _same(c.gateway, gmap.get(c.measure))
    if c.basis == BASIS_RUN_LEDGER:
        if c.row_key is not None or c.row_detail is not ReasonCode.ROW_DETAIL_UNAVAILABLE or not recorded_equal:
            return ReasonCode.ORIGINAL_TAMPERED
        scope.recheck_epoch()
        return ReasonCode.ORIGINAL_INTACT
    if c.row_detail is not None:
        return ReasonCode.ORIGINAL_TAMPERED
    scope.recheck_epoch()
    # COMPARISON basis: only a totals row that equals the ledger's own numbers can be recomputed
    if c.row_key is None and recorded_equal:
        return ReasonCode.ORIGINAL_INTACT
    return ReasonCode.ORIGINAL_UNVERIFIABLE


def verify_original(card: object, ledger: object, viewer: object, *, ownership: object,
                    current_epoch: object) -> ReasonCode:
    """Does the card still equal what the ledger recorded?

    Returns ``ORIGINAL_INTACT`` only when the card's numbers are recomputed from the ledger (RUN_LEDGER
    cards; COMPARISON totals rows equal to the ledger's). ``ORIGINAL_UNVERIFIABLE`` for caller-supplied
    row numbers that the ledger cannot confirm. ``ORIGINAL_TAMPERED`` for a malformed or contradicted card.
    ``NOT_IN_SCOPE`` (identical for foreign and unknown references), ``SCOPE_EPOCH_STALE`` and
    ``INPUT_INVALID`` are scope refusals; ``INTERNAL_REFUSED`` / ``DEPENDENCY_FAILED`` mean the check
    itself could not run - a ledger failure is never reported as tampering.
    """
    try:
        return _verify(card, ledger, viewer, ownership, current_epoch)
    except _Refuse as refusal:
        return refusal.code
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        return ReasonCode.INTERNAL_REFUSED


def request_override(*_args: object, **_kwargs: object) -> SafeError:
    """Any request to adjust, override or re-total original numbers is refused, whatever it carries.

    The answer does not depend on any argument (no data is read), so it cannot be an existence oracle.
    """
    return safe_error(ReasonCode.ORIGINAL_NUMBERS_IMMUTABLE)


# --------------------------------------------------------------------------------------------------
# review log

@dataclass(frozen=True, slots=True)
class AnnotationEntry:
    seq: int  # per-tenant sequence: never reveals other tenants' volume
    tenant_id: str
    run_id: str
    actor_id: str
    kind: AnnotationKind
    text: str
    assignee: str | None
    related_run_id: str | None
    recorded_at: datetime
    authority: str = AUTHORITY

    def __repr__(self) -> str:
        return "AnnotationEntry(<redacted>)"


class _Reservation:
    """One reserved annotation slot (tenant, run). Consumed by ``_append`` or returned by ``_release``."""

    __slots__ = ("live", "run_id", "tenant")

    def __init__(self, tenant: str, run_id: str) -> None:
        self.tenant, self.run_id, self.live = tenant, run_id, True


class ReviewLog:
    """Append-only annotations keyed by (tenant, run id). Never touches, hides or re-totals numbers.

    Quotas are per run and per tenant (one tenant filling its quota never blocks another tenant), with
    a small global ceiling above them.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None, *, max_per_run: int = MAX_RUN_ENTRIES,
                 max_per_tenant: int = MAX_TENANT_ENTRIES, max_total: int = MAX_LOG_ENTRIES) -> None:
        for cap in (max_per_run, max_per_tenant, max_total):
            if type(cap) is not int or cap < 1:
                raise ValueError("REVIEW_LOG_INVALID")
        self._clock = clock
        self._max_run, self._max_tenant, self._max_total = max_per_run, max_per_tenant, max_total
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], list[AnnotationEntry]] = {}
        self._tenant_count: dict[str, int] = {}
        self._count = 0
        self._pending: dict[tuple[str, str], tuple[str, str, str, str, str]] = {}  # (tenant, previous run) ->
        # (new run id, comparison key, snapshot id, snapshot digest, actor) of a run awaiting its audit entry
        self._res_total = 0  # reserved-but-unwritten slots count against every quota
        self._res_tenant: dict[str, int] = {}
        self._res_run: dict[tuple[str, str], int] = {}

    def _now(self) -> datetime:
        try:
            value = datetime.now(UTC) if self._clock is None else self._clock()
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
            return value.astimezone(UTC)
        except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
            raise _Refuse(ReasonCode.INTERNAL_REFUSED) from None

    def _room(self, tenant: str, run_id: str) -> bool:
        return (self._count + self._res_total < self._max_total
                and self._tenant_count.get(tenant, 0) + self._res_tenant.get(tenant, 0) < self._max_tenant
                and len(self._entries.get((tenant, run_id), ())) + self._res_run.get((tenant, run_id), 0)
                < self._max_run)

    def _has_room(self, tenant: str, run_id: str) -> bool:
        with self._lock:
            return self._room(tenant, run_id)

    def _pending_get(self, tenant: str, prev_id: str) -> tuple[str, str, str, str, str] | None:
        with self._lock:
            return self._pending.get((tenant, prev_id))

    def _pending_set(self, tenant: str, prev_id: str,
                     record: tuple[str, str, str, str, str] | None) -> None:
        with self._lock:
            if record is None:
                self._pending.pop((tenant, prev_id), None)
            else:
                self._pending[(tenant, prev_id)] = record

    def _reserve(self, tenant: str, run_id: str) -> _Reservation | None:
        """Atomically take one slot for a later ``_append``; ``None`` when no room (nothing is held)."""
        with self._lock:
            if not self._room(tenant, run_id):
                return None
            self._res_total += 1
            self._res_tenant[tenant] = self._res_tenant.get(tenant, 0) + 1
            self._res_run[(tenant, run_id)] = self._res_run.get((tenant, run_id), 0) + 1
            return _Reservation(tenant, run_id)

    def _drop(self, reservation: _Reservation) -> bool:
        """Give a live reservation back (caller holds the lock). ``False`` when it was already consumed."""
        if not reservation.live:
            return False
        reservation.live = False
        self._res_total -= 1
        tenant, key = reservation.tenant, (reservation.tenant, reservation.run_id)
        for table, k in ((self._res_tenant, tenant), (self._res_run, key)):
            left = table.get(k, 0) - 1
            if left > 0:
                table[k] = left
            else:
                table.pop(k, None)
        return True

    def _release(self, reservation: _Reservation) -> None:
        with self._lock:
            self._drop(reservation)

    def _append(self, tenant: str, run_id: str, actor_id: str, kind: AnnotationKind, text: str,
                assignee: str | None, related: str | None, at: datetime,
                reservation: _Reservation | None = None) -> AnnotationEntry | None:
        with self._lock:
            if kind is AnnotationKind.RERUN_REQUESTED and related is not None:
                for known in self._entries.get((tenant, run_id), ()):
                    if known.kind is kind and known.related_run_id == related:
                        if reservation is not None:
                            self._drop(reservation)
                        return known  # the same operation (one audit entry per created run), never a duplicate
            if reservation is not None:
                if (type(reservation) is not _Reservation or reservation.tenant != tenant
                        or reservation.run_id != run_id or not self._drop(reservation)):
                    return None
            elif not self._room(tenant, run_id):
                return None
            self._count += 1
            seq = self._tenant_count.get(tenant, 0) + 1
            self._tenant_count[tenant] = seq
            entry = AnnotationEntry(seq, tenant, run_id, actor_id, kind, text, assignee, related, at)
            self._entries.setdefault((tenant, run_id), []).append(entry)
            return entry

    def add(self, ledger: object, viewer: object, tenant: object, run_id: object, kind: object,
            text: object = "", *, actor_id: object, ownership: object, current_epoch: object,
            assignee: object = None) -> AnnotationEntry | SafeError:
        try:
            return self._add(ledger, viewer, tenant, run_id, kind, text, assignee, actor_id, ownership,
                             current_epoch)
        except _Refuse as refusal:
            return safe_error(refusal.code)
        except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
            return safe_error(ReasonCode.INTERNAL_REFUSED)

    def _add(self, ledger: object, viewer: object, tenant: object, run_id: object, kind: object,
             text: object, assignee: object, actor_id: object, ownership: object,
             current_epoch: object) -> AnnotationEntry:
        led = _need_ledger(ledger)
        scope = _Scope(viewer, ownership, current_epoch)
        tenant_t, run_t, actor = _txt(tenant), _txt(run_id), _txt(actor_id)
        scope.gate(tenant_t, (("run_id", run_t),))
        if led.get(tenant_t, run_t) is None:
            raise _Refuse(ReasonCode.NOT_IN_SCOPE)
        if type(kind) is str and kind.strip().upper() in _ADJUSTMENT_WORDS:
            raise _Refuse(ReasonCode.ORIGINAL_NUMBERS_IMMUTABLE)
        if type(kind) is not AnnotationKind or kind is AnnotationKind.RERUN_REQUESTED:
            raise _Refuse(ReasonCode.ANNOTATION_INVALID)  # RERUN_REQUESTED is written only by commit_rerun
        if type(text) is not str or (text == "" and kind is AnnotationKind.NOTE) or not _note_ok(text):
            raise _Refuse(ReasonCode.ANNOTATION_INVALID)
        if kind is AnnotationKind.ASSIGNED:
            if type(assignee) is not str or assignee == "" or exact_text(assignee) != assignee:
                raise _Refuse(ReasonCode.ANNOTATION_INVALID)
        elif assignee is not None:
            raise _Refuse(ReasonCode.ANNOTATION_INVALID)
        at = self._now()
        scope.recheck_epoch()  # TOCTOU: nothing is written for a scope that moved
        entry = self._append(tenant_t, run_t, actor, kind, text, assignee, None, at)  # type: ignore[arg-type]
        if entry is None:
            raise _Refuse(ReasonCode.RATE_LIMITED)
        return entry

    def entries(self, viewer: object, tenant: object, run_id: object, *, ownership: object,
                current_epoch: object) -> tuple[AnnotationEntry, ...] | SafeError:
        try:
            scope = _Scope(viewer, ownership, current_epoch)
            tenant_t, run_t = _txt(tenant), _txt(run_id)
            scope.gate(tenant_t, (("run_id", run_t),))
            with self._lock:
                found = tuple(self._entries.get((tenant_t, run_t), ()))
            scope.recheck_epoch()  # TOCTOU: no data for a scope that moved while we read
            return found
        except _Refuse as refusal:
            return safe_error(refusal.code)
        except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
            return safe_error(ReasonCode.INTERNAL_REFUSED)


# --------------------------------------------------------------------------------------------------
# rerun

@dataclass(frozen=True, slots=True)
class RerunOutcome:
    previous_run_id: str
    new_run_id: str
    new_run_state: str
    current_run_id: str | None
    annotated: bool
    authority: str = AUTHORITY


@dataclass(frozen=True, slots=True)
class RerunPlan:
    """The validated, effect-free result of ``check_rerun``; ``commit_rerun`` re-validates it before acting."""

    tenant_id: str
    company_id: str
    scope_epoch: int
    comparison_key: str
    previous_run_id: str
    snapshot_id: str
    snapshot_digest: str
    authority: str = AUTHORITY


_LEDGER_CODES: Final = {
    "RERUN_TARGET_ALREADY_SUPERSEDED": ReasonCode.RERUN_TARGET_STALE,
    "RERUN_REQUIRED": ReasonCode.RERUN_TARGET_STALE,
    "RERUN_TARGET_UNKNOWN": ReasonCode.RERUN_TARGET_UNKNOWN,
}


def _plan(led: RunLedger, snaps: SnapshotStore, review_log: object, scope: _Scope, tenant: str, key: str,
          prev_id: str, snap_id: str) -> RerunPlan:
    scope.gate(tenant, (("comparison_key", key), ("run_id", prev_id), ("snapshot_id", snap_id)))
    prev = led.get(tenant, prev_id)
    if prev is None or prev.comparison_key != key:
        raise _Refuse(ReasonCode.RERUN_TARGET_UNKNOWN)
    views = led.list_runs(tenant, key)
    if not views or views[-1].record.run_id != prev.run_id:
        # The one exception to "previous run must be the chain head": a run this very request already created
        # whose audit entry is still missing (recovery). Still pure; commit_rerun re-verifies run, actor, digest.
        pending = review_log._pending_get(tenant, prev_id)  # type: ignore[attr-defined]
        recoverable = (pending is not None and pending[1] == key and pending[2] == snap_id
                       and views and views[-1].record.run_id == pending[0]
                       and views[-1].record.supersedes == prev_id)
        if not recoverable:
            raise _Refuse(ReasonCode.RERUN_TARGET_STALE)
    snap = snaps.get(tenant, snap_id)
    if snap is None:
        raise _Refuse(ReasonCode.NOT_FOUND)
    if snap.snapshot_id == prev.snapshot_id or snap.digest == prev.snapshot_digest:
        raise _Refuse(ReasonCode.NO_NEW_EVIDENCE)
    if not review_log._has_room(tenant, prev.run_id):  # type: ignore[attr-defined]
        raise _Refuse(ReasonCode.RATE_LIMITED)
    view = scope.viewer
    return RerunPlan(tenant, view.company_id, view.scope_epoch, key, prev.run_id, snap.snapshot_id, snap.digest)


def _check_rerun(ledger: object, store: object, review_log: object, viewer: object, tenant: object,
                 comparison_key: object, previous_run_id: object, new_snapshot_id: object, ownership: object,
                 current_epoch: object) -> RerunPlan:
    led, snaps = _need_ledger(ledger), _need_store(store)
    if type(review_log) is not ReviewLog:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    scope = _Scope(viewer, ownership, current_epoch)
    tenant_t, key = _txt(tenant), _txt(comparison_key)
    prev_id, snap_id = _txt(previous_run_id), _txt(new_snapshot_id)
    return _plan(led, snaps, review_log, scope, tenant_t, key, prev_id, snap_id)


def check_rerun(ledger: object, store: object, review_log: object, viewer: object, tenant: object,
                comparison_key: object, previous_run_id: object, new_snapshot_id: object, *, ownership: object,
                current_epoch: object) -> RerunPlan | SafeError:
    """Pure validation step: scope, ownership, epoch, chain head, new evidence, quota. Creates nothing.

    The reader is never called and no run or annotation exists afterwards; a jobs API can run this
    synchronously and dispatch ``commit_rerun`` later.
    """
    try:
        return _check_rerun(ledger, store, review_log, viewer, tenant, comparison_key, previous_run_id,
                            new_snapshot_id, ownership, current_epoch)
    except _Refuse as refusal:
        return safe_error(refusal.code)
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        return safe_error(ReasonCode.INTERNAL_REFUSED)


def _commit_rerun(ledger: object, store: object, review_log: object, viewer: object, plan: object,
                  reader: object, actor_id: object, ownership: object, current_epoch: object) -> RerunOutcome:
    led, snaps = _need_ledger(ledger), _need_store(store)
    if type(review_log) is not ReviewLog or not callable(reader) or type(plan) is not RerunPlan:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    scope = _Scope(viewer, ownership, current_epoch)
    actor = _txt(actor_id)
    try:
        fields = (plan.tenant_id, plan.company_id, plan.scope_epoch, plan.comparison_key,
                  plan.previous_run_id, plan.snapshot_id, plan.snapshot_digest)
    except AttributeError:  # forged instance
        raise _Refuse(ReasonCode.INPUT_INVALID) from None
    tenant, company, epoch, key, prev_id, snap_id, digest = fields
    if not (all(type(p) is str and p for p in (tenant, company, key, prev_id, snap_id, digest))
            and type(epoch) is int):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    view = scope.viewer
    if tenant != view.tenant_id or company != view.company_id or epoch != view.scope_epoch:
        raise _Refuse(ReasonCode.NOT_IN_SCOPE)
    pending = review_log._pending_get(tenant, prev_id)
    if pending is not None and pending[1:] == (key, snap_id, digest, actor):
        # A previous attempt of THIS request (same key, snapshot, evidence digest, actor) created the run but
        # its audit append failed. The new run is already the chain head, so a plan would look stale: recovery
        # re-checks tenant, epoch and ownership like any plan, verifies the run really is that request's
        # result, finishes THAT audit and never creates a second run.
        scope.gate(tenant, (("comparison_key", key), ("run_id", prev_id), ("snapshot_id", snap_id)))
        made = led.get(tenant, pending[0])
        if made is not None and made.comparison_key == key and made.supersedes == prev_id                 and made.snapshot_id == snap_id:
            at = review_log._now()
            reservation = review_log._reserve(tenant, prev_id)
            if reservation is None:
                raise _Refuse(ReasonCode.RATE_LIMITED)
            try:
                return _finish_audit(led, review_log, reservation, at, tenant, key, prev_id, pending[0], actor)
            finally:
                review_log._release(reservation)
    fresh = _plan(led, snaps, review_log, scope, tenant, key, prev_id, snap_id)  # the world may have moved
    if fresh.snapshot_digest != digest:
        raise _Refuse(ReasonCode.RERUN_TARGET_STALE)
    at = review_log._now()  # read before the run exists: a broken clock must not leave a run unannotated
    # Reserve the audit slot BEFORE any run exists: the run + annotation pair cannot half-commit.
    reservation = review_log._reserve(tenant, prev_id)
    if reservation is None:
        raise _Refuse(ReasonCode.RATE_LIMITED)
    try:
        return _commit_reserved(led, review_log, scope, reader, reservation, at, tenant, key, prev_id,
                                snap_id, digest, actor)
    finally:
        review_log._release(reservation)  # no-op once consumed by the append


def _commit_reserved(led: RunLedger, review_log: ReviewLog, scope: _Scope, reader: object,
                     reservation: _Reservation, at: datetime, tenant: str, key: str, prev_id: str,
                     snap_id: str, digest: str, actor: str) -> RerunOutcome:
    try:
        pair = reader(tenant, snap_id)  # type: ignore[operator]
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        raise _Refuse(ReasonCode.DEPENDENCY_FAILED) from None
    if type(pair) is not tuple or len(pair) != 2 or not all(type(p) is SideRead for p in pair):
        raise _Refuse(ReasonCode.DEPENDENCY_FAILED)
    scope.recheck_epoch()  # TOCTOU: the reader may have taken long; no run for a scope that moved
    try:
        record = led.run(tenant, key, pair[0], pair[1], snapshot_id=snap_id, rerun_of=prev_id)
    except ComparisonSnapshotError as err:
        raise _Refuse(_LEDGER_CODES.get(err.code, ReasonCode.DEPENDENCY_FAILED)) from None
    review_log._pending_set(tenant, prev_id, (record.run_id, key, snap_id, digest, actor))  # until audited
    return _finish_audit(led, review_log, reservation, at, tenant, key, prev_id, record.run_id, actor)


def _finish_audit(led: RunLedger, review_log: ReviewLog, reservation: _Reservation, at: datetime,
                  tenant: str, key: str, prev_id: str, run_id: str, actor: str) -> RerunOutcome:
    """Append the audit entry for an already created run; one bounded retry, then a recoverable refusal.

    The run is recorded as pending-audit until its entry exists, so a retry of the same rerun finishes the
    audit for THAT run instead of creating another one (see ``_commit_reserved``)."""
    entry = None
    for attempt in range(2):
        try:
            entry = review_log._append(tenant, prev_id, actor, AnnotationKind.RERUN_REQUESTED, _RERUN_NOTE,
                                       None, run_id, at, reservation)
        except Exception:  # noqa: BLE001 - fixed refusal below; the pending marker keeps it recoverable
            entry = None
        if entry is not None:
            break
        if not reservation.live:
            reservation = review_log._reserve(tenant, prev_id)
            if reservation is None:
                break
    if entry is None:
        raise _Refuse(ReasonCode.INTERNAL_REFUSED)  # pending marker stays: retry adopts the run
    review_log._pending_set(tenant, prev_id, None)
    record = led.get(tenant, run_id)
    current = led.current(tenant, key)
    return RerunOutcome(prev_id, run_id, record.state.value,
                        None if current is None else current.run_id, True)


def commit_rerun(ledger: object, store: object, review_log: object, viewer: object, plan: object,
                 reader: object, *, actor_id: object, ownership: object,
                 current_epoch: object) -> RerunOutcome | SafeError:
    """Effect step: re-validates ``plan`` against the live world, reads the numbers, creates the run + annotation.

    Numbers come from ``reader`` only. A reader that raises or returns junk is ``DEPENDENCY_FAILED``
    (retry later); an internal defect is ``INTERNAL_REFUSED``; a moved epoch is ``SCOPE_EPOCH_STALE``.
    The epoch is re-read after the reader returns and immediately before the run is committed.
    """
    try:
        return _commit_rerun(ledger, store, review_log, viewer, plan, reader, actor_id, ownership, current_epoch)
    except _Refuse as refusal:
        return safe_error(refusal.code)
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        return safe_error(ReasonCode.INTERNAL_REFUSED)


def request_rerun(ledger: object, store: object, review_log: object, viewer: object, tenant: object,
                  comparison_key: object, previous_run_id: object, new_snapshot_id: object, reader: object, *,
                  actor_id: object, ownership: object, current_epoch: object) -> RerunOutcome | SafeError:
    """One-call wrapper: ``check_rerun`` then ``commit_rerun``. New evidence -> a NEW run chained to the head."""
    plan = check_rerun(ledger, store, review_log, viewer, tenant, comparison_key, previous_run_id,
                       new_snapshot_id, ownership=ownership, current_epoch=current_epoch)
    if type(plan) is not RerunPlan:
        return plan
    return commit_rerun(ledger, store, review_log, viewer, plan, reader, actor_id=actor_id,
                        ownership=ownership, current_epoch=current_epoch)
