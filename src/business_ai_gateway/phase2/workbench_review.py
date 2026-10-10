"""Phase 2 sprint S8 E1 (R2-US-039): discrepancy cards, original-number integrity, review log, safe rerun.

Offline, unwired, in-memory. A ``DiscrepancyCard`` is a DERIVED, frozen view of one differing measure
of one recorded run. It carries the numbers exactly as the ``RunLedger`` stored them (exact
``Decimal``), the delta ``gateway - native`` computed in a fixed exact context (precision overflow is
a fixed refusal, never a rounded delta), a fragment reference into the frozen snapshot, the owner
from an injected directory (``OWNER_UNASSIGNED`` when unmapped, never guessed) and an
``original_digest`` over the run's immutable record. ``verify_original`` recomputes everything from
the ledger.

Nothing here can change a number or a verdict: no public function accepts numbers, states or
verdicts from the caller. The ``ReviewLog`` is append-only text annotation keyed by run id. New
evidence is a NEW run: ``request_rerun`` takes typed ids plus an injected reader (the source of the
numbers) and delegates to ``RunLedger.run(..., rerun_of=...)``; the earlier run is never edited.

Public functions never raise: any refusal is a ``SafeError`` (fixed reason code + next action, no
caller input echoed). Authority is ``EVALUATION_ONLY``. Honest limits: the ``RunLedger`` stores
measure keys only, so row detail exists only through the explicit ``comparison=`` adapter (numbers of
those cards are self-consistent and bound to the run, not recomputable from the ledger), the
correlation id is the fixed default until the caller re-wraps it, and source pause/revoke and actor
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
    "BASIS_COMPARISON", "BASIS_RUN_LEDGER", "MAX_LOG_ENTRIES", "AnnotationEntry", "DiscrepancyCard",
    "FragmentRef", "RerunOutcome", "ReviewLog", "build_cards", "request_override", "request_rerun",
    "verify_original",
]

BASIS_RUN_LEDGER: Final = "RUN_LEDGER"
BASIS_COMPARISON: Final = "COMPARISON"
MAX_LOG_ENTRIES: Final = 1000
MAX_NOTE_CHARS: Final = 500
_BAD_NOTE_CATEGORIES: Final = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp", "Zs"})
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_STATUSES: Final = frozenset({"CURRENT", "LATEST_ATTEMPT", "SUPERSEDED"})
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


def _dec_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise _Refuse(ReasonCode.INPUT_INVALID)
    return value


def _same(a: object, b: object) -> bool:
    """Value equality for exact Decimals / None only; a lying ``__eq__`` subclass never matches."""
    if a is None or b is None:
        return a is None and b is None
    return type(a) is Decimal and type(b) is Decimal and a.is_finite() and b.is_finite() and a == b


def _check_epoch(viewer: ViewerScope, current_epoch: object) -> None:
    if current_epoch is None:
        return
    if type(current_epoch) is not int:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    if current_epoch != viewer.scope_epoch:
        raise _Refuse(ReasonCode.SCOPE_EPOCH_STALE)


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


def _delta(native: Decimal | None, gateway: Decimal | None) -> Decimal | None:
    if native is None or gateway is None:
        return None
    try:
        with localcontext(_EXACT):
            return gateway - native
    except ArithmeticError:
        raise _Refuse(ReasonCode.DELTA_PRECISION_EXCEEDED) from None


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
    owner_id: str | None
    owner_note: ReasonCode | None
    original_digest: str
    card_digest: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        texts = (self.tenant_id, self.run_id, self.comparison_key, self.measure)
        if (not all(type(t) is str and t for t in texts) or self.run_status not in _STATUSES
                or self.basis not in (BASIS_RUN_LEDGER, BASIS_COMPARISON)
                or type(self.fragment) is not FragmentRef
                or not (self.row_detail is None or type(self.row_detail) is ReasonCode)
                or not (self.owner_note is None or type(self.owner_note) is ReasonCode)
                or not (self.owner_id is None or (type(self.owner_id) is str and self.owner_id))
                or type(self.original_digest) is not str or _HEX64.fullmatch(self.original_digest) is None
                or type(self.card_digest) is not str or _HEX64.fullmatch(self.card_digest) is None
                or self.authority != AUTHORITY
                or not all(v is None or type(v) is Decimal for v in (self.native, self.gateway, self.delta))):
            raise ValueError("CARD_INVALID")


def _card_digest(card: DiscrepancyCard) -> str:
    return canonical_digest({
        "original": card.original_digest, "measure": card.measure,
        "row_key": None if card.row_key is None else list(card.row_key),
        "native": card.native, "gateway": card.gateway, "delta": card.delta,
    })


def _validate_comparison(comparison: object) -> tuple[ReconState, tuple[tuple[
        tuple[str, str] | None, str, Decimal | None, Decimal | None], ...]]:
    if type(comparison) is not Comparison:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    try:
        state, diffs = comparison.state, comparison.differences
    except AttributeError:  # forged object.__new__ instance
        raise _Refuse(ReasonCode.INPUT_INVALID) from None
    if type(state) is not ReconState or type(diffs) is not tuple:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    rows = []
    for diff in diffs:
        if type(diff) is not Difference:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        key = diff.row_key
        if key is not None:
            if type(key) is not tuple or len(key) != 2:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            key = (_row_part(key[0]), _row_part(key[1]))
        rows.append((key, _txt(diff.measure), _dec_or_none(diff.expected), _dec_or_none(diff.actual)))
    return state, tuple(rows)


def _build_cards(ledger: object, tenant: object, comparison_key: object, owners: object, viewer: object,
                 source_id: object, run_id: object, comparison: object,
                 current_epoch: object) -> tuple[DiscrepancyCard, ...]:
    led = _need_ledger(ledger)
    tenant_t, key, source = _txt(tenant), _txt(comparison_key), _txt(source_id)
    view = _need_viewer(viewer)
    if not is_valid_directory(owners):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    wanted = None if run_id is None else _txt(run_id)
    parsed = None if comparison is None else _validate_comparison(comparison)
    if tenant_t != view.tenant_id:
        raise _Refuse(ReasonCode.NOT_IN_SCOPE)
    _check_epoch(view, current_epoch)
    if wanted is None:
        run = led.current(tenant_t, key)
        if run is None:
            return ()
    else:
        run = led.get(tenant_t, wanted)
        if run is None or run.comparison_key != key:
            raise _Refuse(ReasonCode.NOT_IN_SCOPE)  # same answer as an unknown run: no existence leak
    status = next((v.status for v in led.list_runs(tenant_t, key) if v.record.run_id == run.run_id), None)
    if status not in _STATUSES:
        raise _Refuse(ReasonCode.INTERNAL_REFUSED)
    if run.state is not ComparisonState.FAIL:
        if parsed is not None and parsed[1]:
            raise _Refuse(ReasonCode.INPUT_INVALID)  # differences for a run that did not FAIL
        return ()
    owner = owners.owner_for(tenant_t, view.company_id, source)  # type: ignore[attr-defined]
    original = _run_digest(run)
    if parsed is not None:
        if not parsed[1]:
            raise _Refuse(ReasonCode.INPUT_INVALID)  # a FAIL run cannot be explained by "no differences"
        items = [(rk, m, e, a, None, BASIS_COMPARISON) for rk, m, e, a in parsed[1]]
    else:
        nmap, gmap = dict(run.native_values), dict(run.gateway_values)
        items = [(None, m, nmap.get(m), gmap.get(m), ReasonCode.ROW_DETAIL_UNAVAILABLE, BASIS_RUN_LEDGER)
                 for m in run.differences]
    cards = []
    for row_key, measure, native, gateway, detail, basis in items:
        base = DiscrepancyCard(
            tenant_t, run.run_id, key, status, basis, measure, row_key, detail,
            FragmentRef(run.snapshot_digest, row_key, measure), native, gateway, _delta(native, gateway),
            owner, None if owner is not None else ReasonCode.OWNER_UNASSIGNED, original, "0" * 64)
        cards.append(_with_digest(base))
    return tuple(cards)


def _with_digest(card: DiscrepancyCard) -> DiscrepancyCard:
    return replace(card, card_digest=_card_digest(card))


def build_cards(ledger: object, tenant: object, comparison_key: object, owners: object, viewer: object, *,
                source_id: object, run_id: object = None, comparison: object = None,
                current_epoch: object = None) -> tuple[DiscrepancyCard, ...] | SafeError:
    """Cards for the differing measures of the CURRENT decisive run (or of ``run_id``); ``()`` if none."""
    try:
        return _build_cards(ledger, tenant, comparison_key, owners, viewer, source_id, run_id, comparison,
                            current_epoch)
    except _Refuse as refusal:
        return safe_error(refusal.code)
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        return safe_error(ReasonCode.INTERNAL_REFUSED)


def _verify(card: object, ledger: object) -> bool:
    if type(card) is not DiscrepancyCard:
        return False
    led = _need_ledger(ledger)
    # re-run the constructor checks on a possibly forged instance (object.__new__ + __setattr__)
    DiscrepancyCard(card.tenant_id, card.run_id, card.comparison_key, card.run_status, card.basis,
                    card.measure, card.row_key, card.row_detail, card.fragment, card.native, card.gateway,
                    card.delta, card.owner_id, card.owner_note, card.original_digest, card.card_digest,
                    card.authority)
    run = led.get(card.tenant_id, card.run_id)
    if run is None or run.comparison_key != card.comparison_key or run.state is not ComparisonState.FAIL:
        return False
    if card.original_digest != _run_digest(run) or card.card_digest != _card_digest(card):
        return False
    frag = card.fragment
    if (frag.snapshot_digest != run.snapshot_digest or frag.measure != card.measure
            or frag.row_key != card.row_key):
        return False
    if not _same(card.delta, _delta(card.native, card.gateway)):
        return False
    if card.basis == BASIS_RUN_LEDGER:
        if (card.row_key is not None or card.row_detail is not ReasonCode.ROW_DETAIL_UNAVAILABLE
                or card.measure not in run.differences):
            return False
        return (_same(card.native, dict(run.native_values).get(card.measure))
                and _same(card.gateway, dict(run.gateway_values).get(card.measure)))
    return True  # COMPARISON basis: bound to the run and self-consistent; its numbers are not in the ledger


def verify_original(card: object, ledger: object) -> ReasonCode:
    """``ORIGINAL_INTACT`` only when the card still equals what the ledger recorded; everything else tampered."""
    try:
        return ReasonCode.ORIGINAL_INTACT if _verify(card, ledger) else ReasonCode.ORIGINAL_TAMPERED
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        return ReasonCode.ORIGINAL_TAMPERED


def request_override(*_args: object, **_kwargs: object) -> SafeError:
    """Any request to adjust, override or re-total original numbers is refused, whatever it carries."""
    return safe_error(ReasonCode.ORIGINAL_NUMBERS_IMMUTABLE)


# --------------------------------------------------------------------------------------------------
# review log

@dataclass(frozen=True, slots=True)
class AnnotationEntry:
    seq: int
    tenant_id: str
    run_id: str
    kind: AnnotationKind
    text: str
    assignee: str | None
    related_run_id: str | None
    recorded_at: datetime
    authority: str = AUTHORITY


class ReviewLog:
    """Append-only annotations keyed by (tenant, run id). Never touches, hides or re-totals numbers."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str], list[AnnotationEntry]] = {}
        self._count = 0

    def _now(self) -> datetime:
        try:
            value = datetime.now(UTC) if self._clock is None else self._clock()
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
            return value.astimezone(UTC)
        except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
            raise _Refuse(ReasonCode.INTERNAL_REFUSED) from None

    def _has_room(self) -> bool:
        with self._lock:
            return self._count < MAX_LOG_ENTRIES

    def _append(self, tenant: str, run_id: str, kind: AnnotationKind, text: str, assignee: str | None,
                related: str | None, at: datetime) -> AnnotationEntry | None:
        with self._lock:
            if self._count >= MAX_LOG_ENTRIES:
                return None
            self._count += 1
            entry = AnnotationEntry(self._count, tenant, run_id, kind, text, assignee, related, at)
            self._entries.setdefault((tenant, run_id), []).append(entry)
            return entry

    def add(self, ledger: object, viewer: object, tenant: object, run_id: object, kind: object,
            text: object = "", *, assignee: object = None,
            current_epoch: object = None) -> AnnotationEntry | SafeError:
        try:
            return self._add(ledger, viewer, tenant, run_id, kind, text, assignee, current_epoch)
        except _Refuse as refusal:
            return safe_error(refusal.code)
        except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
            return safe_error(ReasonCode.INTERNAL_REFUSED)

    def _add(self, ledger: object, viewer: object, tenant: object, run_id: object, kind: object,
             text: object, assignee: object, current_epoch: object) -> AnnotationEntry:
        led = _need_ledger(ledger)
        view = _need_viewer(viewer)
        tenant_t, run_t = _txt(tenant), _txt(run_id)
        if tenant_t != view.tenant_id:
            raise _Refuse(ReasonCode.NOT_IN_SCOPE)
        _check_epoch(view, current_epoch)
        if led.get(tenant_t, run_t) is None:
            raise _Refuse(ReasonCode.NOT_IN_SCOPE)
        if type(kind) is str and kind.strip().upper() in _ADJUSTMENT_WORDS:
            raise _Refuse(ReasonCode.ORIGINAL_NUMBERS_IMMUTABLE)
        if type(kind) is not AnnotationKind or kind is AnnotationKind.RERUN_REQUESTED:
            raise _Refuse(ReasonCode.ANNOTATION_INVALID)  # RERUN_REQUESTED is written only by request_rerun
        if type(text) is not str or (text == "" and kind is AnnotationKind.NOTE) or not _note_ok(text):
            raise _Refuse(ReasonCode.ANNOTATION_INVALID)
        if kind is AnnotationKind.ASSIGNED:
            if type(assignee) is not str or assignee == "" or exact_text(assignee) != assignee:
                raise _Refuse(ReasonCode.ANNOTATION_INVALID)
        elif assignee is not None:
            raise _Refuse(ReasonCode.ANNOTATION_INVALID)
        at = self._now()
        entry = self._append(tenant_t, run_t, kind, text, assignee, None, at)  # type: ignore[arg-type]
        if entry is None:
            raise _Refuse(ReasonCode.RATE_LIMITED)
        return entry

    def entries(self, viewer: object, tenant: object, run_id: object, *,
                current_epoch: object = None) -> tuple[AnnotationEntry, ...] | SafeError:
        try:
            view = _need_viewer(viewer)
            tenant_t, run_t = _txt(tenant), _txt(run_id)
            if tenant_t != view.tenant_id:
                raise _Refuse(ReasonCode.NOT_IN_SCOPE)
            _check_epoch(view, current_epoch)
            with self._lock:
                return tuple(self._entries.get((tenant_t, run_t), ()))
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


_LEDGER_CODES: Final = {
    "RERUN_TARGET_ALREADY_SUPERSEDED": ReasonCode.RERUN_TARGET_STALE,
    "RERUN_REQUIRED": ReasonCode.RERUN_TARGET_STALE,
    "RERUN_TARGET_UNKNOWN": ReasonCode.RERUN_TARGET_UNKNOWN,
}


def _request_rerun(ledger: object, store: object, review_log: object, viewer: object, tenant: object,
                   comparison_key: object, previous_run_id: object, new_snapshot_id: object, reader: object,
                   current_epoch: object) -> RerunOutcome:
    led, snaps = _need_ledger(ledger), _need_store(store)
    if type(review_log) is not ReviewLog or not callable(reader):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    view = _need_viewer(viewer)
    tenant_t, key = _txt(tenant), _txt(comparison_key)
    prev_id, snap_id = _txt(previous_run_id), _txt(new_snapshot_id)
    if tenant_t != view.tenant_id:
        raise _Refuse(ReasonCode.NOT_IN_SCOPE)
    _check_epoch(view, current_epoch)
    prev = led.get(tenant_t, prev_id)
    if prev is None or prev.comparison_key != key:
        raise _Refuse(ReasonCode.RERUN_TARGET_UNKNOWN)
    views = led.list_runs(tenant_t, key)
    if not views or views[-1].record.run_id != prev.run_id:
        raise _Refuse(ReasonCode.RERUN_TARGET_STALE)
    snap = snaps.get(tenant_t, snap_id)
    if snap is None:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    if snap.snapshot_id == prev.snapshot_id or snap.digest == prev.snapshot_digest:
        raise _Refuse(ReasonCode.NO_NEW_EVIDENCE)
    if not review_log._has_room():
        raise _Refuse(ReasonCode.RATE_LIMITED)
    at = review_log._now()  # read before the run exists: a broken clock must not leave a run unannotated
    try:
        pair = reader(tenant_t, snap.snapshot_id)  # type: ignore[operator]
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        raise _Refuse(ReasonCode.INTERNAL_REFUSED) from None
    if type(pair) is not tuple or len(pair) != 2 or not all(type(p) is SideRead for p in pair):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    try:
        record = led.run(tenant_t, key, pair[0], pair[1], snapshot_id=snap.snapshot_id, rerun_of=prev.run_id)
    except ComparisonSnapshotError as err:
        raise _Refuse(_LEDGER_CODES.get(err.code, ReasonCode.INPUT_INVALID)) from None
    entry = review_log._append(tenant_t, prev.run_id, AnnotationKind.RERUN_REQUESTED, _RERUN_NOTE, None,
                               record.run_id, at)
    current = led.current(tenant_t, key)
    return RerunOutcome(prev.run_id, record.run_id, record.state.value,
                        None if current is None else current.run_id, entry is not None)


def request_rerun(ledger: object, store: object, review_log: object, viewer: object, tenant: object,
                  comparison_key: object, previous_run_id: object, new_snapshot_id: object, reader: object, *,
                  current_epoch: object = None) -> RerunOutcome | SafeError:
    """New evidence -> a NEW run chained to the head; numbers come from ``reader``, never from the caller."""
    try:
        return _request_rerun(ledger, store, review_log, viewer, tenant, comparison_key, previous_run_id,
                              new_snapshot_id, reader, current_epoch)
    except _Refuse as refusal:
        return safe_error(refusal.code)
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal, never raise
        return safe_error(ReasonCode.INTERNAL_REFUSED)

