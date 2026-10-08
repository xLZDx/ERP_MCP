"""Phase 2 resnapshot tracking: the consumer of ``RESNAPSHOT_REQUIRED`` and resume revalidation.

Pure logic with injected dependencies (ledger / cursor ports passed to ``revalidate``); no I/O of its
own and no clock. A connection that is *required* must not run incremental capture until a complete
snapshot taken under the CURRENT scope epoch has been accepted.

Rules
- ``require`` is idempotent and the first reason wins: a later reason never replaces it.
- ``observe_decision``: a ``DriftDecision`` carrying ``RESNAPSHOT_REQUIRED`` requires the connection
  with reason ``CURSOR_LOST``.
- ``complete`` clears ONLY for ``OK_COMPLETE`` taken at ``epoch == current_epoch``. ``OK_PARTIAL``,
  failures and ``SCHEMA_CHANGED`` (no hash semantics are verified here) never clear; a complete
  snapshot taken under an older epoch never clears.
- ``revalidate`` (used on resume) compares the live ``ledger.scope_epoch`` with the epoch recorded
  when the scheduler state was persisted, and checks each cursor exists. A revoked / not granted /
  permission-denied scope raises ``ResnapshotBlocked`` and requires nothing (all-or-nothing: the
  decisions are collected first and applied only if no connection was blocked). Any other
  ``PortError`` propagates.
- ``import_state`` MERGES: an import never clears or rewrites a requirement that is already pending.

KNOWN LIMITATION (A-B-A): the tracker compares the live epoch only with the epoch it was given as
``recorded_epoch``. If the scope epoch moves 1 -> 2 -> 1 (it is monotonic in the real ledger, but a
restored/rebased store or a recorded value that was itself stale could return to the same number),
an equality check cannot see the intermediate change and reports nothing. Detecting that needs a
monotonic epoch (the ledger guarantees ``+1`` per change) or an additional fence token; this module
does not claim to.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .drift import CaptureOutcomeKind, DriftDecision, DriftEventKind
from .ports import CursorOutboxPort, LedgerPort, PortError, Scope

__all__ = ["ResnapshotBlocked", "ResnapshotReason", "ResnapshotState", "ResnapshotTracker"]

_BLOCK_CODES: Final = frozenset({"SCOPE_REVOKED", "SCOPE_NOT_GRANTED", "PERMISSION_DENIED"})
_INVALID: Final = "RESNAPSHOT_STATE_INVALID"


class ResnapshotReason(StrEnum):
    CURSOR_LOST = "CURSOR_LOST"
    CURSOR_MISSING = "CURSOR_MISSING"
    SCOPE_EPOCH_CHANGED = "SCOPE_EPOCH_CHANGED"
    OPERATOR = "OPERATOR"


class ResnapshotBlocked(Exception):
    """The scope is revoked / not granted / denied: nothing can be revalidated. Fixed code only."""

    def __init__(self) -> None:
        super().__init__("RESNAPSHOT_BLOCKED")
        self.code = "RESNAPSHOT_BLOCKED"


@dataclass(frozen=True, slots=True)
class ResnapshotState:
    """Persistable snapshot: ``(connection_id, reason, recorded_epoch)`` per required connection."""
    required: tuple[tuple[str, ResnapshotReason, int], ...] = ()


def _check_id(connection_id: object) -> None:
    if type(connection_id) is not str or not connection_id.strip():
        raise ValueError("CONNECTION_ID_INVALID")


def _check_epoch(epoch: object) -> None:
    if type(epoch) is not int or epoch < 0:
        raise ValueError("EPOCH_INVALID")


class ResnapshotTracker:
    def __init__(self, state: ResnapshotState | None = None) -> None:
        self._required: dict[str, tuple[ResnapshotReason, int]] = {}
        if state is not None:
            self.import_state(state)

    # ------------------------------------------------------------------ queries
    def is_required(self, connection_id: str) -> bool:
        return connection_id in self._required

    def incremental_allowed(self, connection_id: str) -> bool:
        return connection_id not in self._required

    def reason(self, connection_id: str) -> ResnapshotReason | None:
        entry = self._required.get(connection_id)
        return None if entry is None else entry[0]

    def required_connections(self) -> tuple[str, ...]:
        return tuple(sorted(self._required))

    # ------------------------------------------------------------------ mutation
    def require(self, connection_id: str, reason: ResnapshotReason, epoch: int) -> None:
        _check_id(connection_id)
        if not isinstance(reason, ResnapshotReason):
            raise TypeError("RESNAPSHOT_REASON_INVALID")
        _check_epoch(epoch)
        self._required.setdefault(connection_id, (reason, epoch))  # first reason wins

    def observe_decision(self, connection_id: str, decision: DriftDecision, epoch: int) -> bool:
        """True when this decision requires (or keeps requiring) a resnapshot."""
        if not isinstance(decision, DriftDecision):
            raise TypeError("DECISION_REQUIRED")
        if DriftEventKind.RESNAPSHOT_REQUIRED in decision.events:
            self.require(connection_id, ResnapshotReason.CURSOR_LOST, epoch)
            return True
        return False

    def complete(self, connection_id: str, outcome_kind: CaptureOutcomeKind, epoch: int,
                 current_epoch: int) -> bool:
        """Clear the requirement for a complete snapshot at the current epoch; True when cleared."""
        _check_id(connection_id)
        if not isinstance(outcome_kind, CaptureOutcomeKind):
            raise TypeError("OUTCOME_KIND_INVALID")
        _check_epoch(epoch)
        _check_epoch(current_epoch)
        if connection_id not in self._required:
            return False
        if outcome_kind is not CaptureOutcomeKind.OK_COMPLETE or epoch != current_epoch:
            return False
        del self._required[connection_id]
        return True

    async def revalidate(self, ledger: LedgerPort, cursors: CursorOutboxPort, actor: str,
                         scope: Scope, connection_ids: Iterable[str],
                         recorded_epoch: int) -> tuple[str, ...]:
        """Revalidate after a restart/resume; returns the connections now required (sorted)."""
        _check_epoch(recorded_epoch)
        ids = tuple(connection_ids)
        for connection_id in ids:
            _check_id(connection_id)
        found: dict[str, ResnapshotReason] = {}
        try:
            live = await ledger.scope_epoch(scope)
            epoch_changed = type(live) is not int or live != recorded_epoch
            for connection_id in ids:
                # Always read the cursor: that call is what reveals a revoked / denied scope.
                cursor = await cursors.get_cursor(actor, scope, connection_id)
                if epoch_changed:
                    found[connection_id] = ResnapshotReason.SCOPE_EPOCH_CHANGED
                elif cursor is None:
                    found[connection_id] = ResnapshotReason.CURSOR_MISSING
        except PortError as exc:
            if exc.code in _BLOCK_CODES:
                raise ResnapshotBlocked from None
            raise
        for connection_id, reason in found.items():
            self.require(connection_id, reason, recorded_epoch)
        return tuple(sorted(c for c in set(ids) if c in self._required))

    # ------------------------------------------------------------------ persistence
    def export_state(self) -> ResnapshotState:
        return ResnapshotState(tuple(
            (c, r, e) for c, (r, e) in sorted(self._required.items())))

    def import_state(self, state: ResnapshotState) -> None:
        """Validate completely, then MERGE: pending requirements are never cleared or rewritten."""
        if not isinstance(state, ResnapshotState):
            raise ValueError(_INVALID)  # noqa: TRY004 - fixed code contract is ValueError
        try:
            entries = tuple(state.required)
        except TypeError:
            raise ValueError(_INVALID) from None
        seen: set[str] = set()
        for entry in entries:
            if type(entry) is not tuple or len(entry) != 3:
                raise ValueError(_INVALID)
            connection_id, reason, epoch = entry
            if (type(connection_id) is not str or not connection_id.strip()
                    or connection_id in seen or not isinstance(reason, ResnapshotReason)
                    or type(epoch) is not int or epoch < 0):
                raise ValueError(_INVALID)
            seen.add(connection_id)
        for connection_id, reason, epoch in entries:
            self._required.setdefault(connection_id, (reason, epoch))
