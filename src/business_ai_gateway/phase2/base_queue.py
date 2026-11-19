"""Candidate per-base queue contract for the S18 reliability work.

This is an in-process reference model only. It does not provide durable or
cross-process exclusion and is not wired to a 1C writer or runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from uuid import UUID

from .change.types import CallOwnership, Execution, is_identity_text

__all__ = [
    "BaseQueueRefused", "BaseWorkQueue", "QueueWork", "QueueWorkKind",
]

MAX_QUEUED_PER_BASE = 20


class QueueWorkKind(StrEnum):
    """The two lanes covered by CT15: read-back verification and mutations."""

    VERIFY_READ = "VERIFY_READ"
    MUTATION = "MUTATION"


class BaseQueueRefused(RuntimeError):
    """Stable refusal codes for fail-closed admission and scheduling."""

    INVALID_BASE = "INVALID_BASE"
    INVALID_WORK = "INVALID_WORK"
    DUPLICATE_WORK = "DUPLICATE_WORK"
    QUEUE_FULL = "QUEUE_FULL"
    ADMISSION_CLOSED = "ADMISSION_CLOSED"
    TARGET_NOT_PROVEN_FINISHED = "TARGET_NOT_PROVEN_FINISHED"
    TARGET_OUTCOME_NOT_TERMINAL = "TARGET_OUTCOME_NOT_TERMINAL"
    TARGET_WORK_ACTIVE = "TARGET_WORK_ACTIVE"
    WORK_NOT_IN_FLIGHT = "WORK_NOT_IN_FLIGHT"
    TARGET_NOT_UNRESOLVED = "TARGET_NOT_UNRESOLVED"
    TARGET_WORK_NOT_IN_FLIGHT = "TARGET_WORK_NOT_IN_FLIGHT"


@dataclass(frozen=True, slots=True)
class QueueWork:
    """Bounded scheduler metadata; payloads stay in their owning subsystem."""

    work_id: UUID
    target_id: str
    kind: QueueWorkKind


class BaseWorkQueue:
    """Thread-safe, single-process queue policy for one trusted base identity.

    Verification reads are selected before mutations. A possibly executing call
    holds every mutation for this base while verification reads continue. Once
    completion is proven, only that unresolved target remains parked.
    """

    __slots__ = (
        "_base_id", "_lock", "_pending", "_in_flight", "_sequence",
        "_ownership", "_admission_closed",
    )

    def __init__(self, base_id: str) -> None:
        if not is_identity_text(base_id):
            raise BaseQueueRefused(BaseQueueRefused.INVALID_BASE)
        self._base_id = base_id
        self._lock = RLock()
        self._pending: dict[UUID, tuple[int, QueueWork]] = {}
        self._in_flight: dict[UUID, QueueWork] = {}
        self._sequence = 0
        self._ownership: dict[str, CallOwnership] = {}
        self._admission_closed = False

    @property
    def base_id(self) -> str:
        return self._base_id

    @property
    def queued_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._in_flight)

    @property
    def admission_closed(self) -> bool:
        with self._lock:
            return self._admission_closed

    @property
    def is_drained(self) -> bool:
        """True only when pending and active work are both empty."""
        with self._lock:
            return not self._pending and not self._in_flight

    def enqueue(self, work_id: UUID, target_id: str, kind: QueueWorkKind) -> QueueWork:
        """Admit work up to the fixed CT15 capacity; overflow is never evicted."""
        if (type(work_id) is not UUID or not is_identity_text(target_id)
                or type(kind) is not QueueWorkKind):
            raise BaseQueueRefused(BaseQueueRefused.INVALID_WORK)
        with self._lock:
            if self._admission_closed:
                raise BaseQueueRefused(BaseQueueRefused.ADMISSION_CLOSED)
            if work_id in self._pending or work_id in self._in_flight:
                raise BaseQueueRefused(BaseQueueRefused.DUPLICATE_WORK)
            if len(self._pending) >= MAX_QUEUED_PER_BASE:
                raise BaseQueueRefused(BaseQueueRefused.QUEUE_FULL)
            work = QueueWork(work_id, target_id, kind)
            self._sequence += 1
            self._pending[work_id] = (self._sequence, work)
            return work

    def mark_unknown(self, target_id: str, ownership: CallOwnership) -> None:
        """Record an unresolved outcome; only proven completion narrows parking."""
        if (not is_identity_text(target_id) or type(ownership) is not CallOwnership
                or ownership is CallOwnership.NONE):
            raise BaseQueueRefused(BaseQueueRefused.INVALID_WORK)
        with self._lock:
            if not any(work.target_id == target_id for work in self._in_flight.values()):
                raise BaseQueueRefused(BaseQueueRefused.TARGET_WORK_NOT_IN_FLIGHT)
            self._ownership[target_id] = ownership

    def prove_finished(self, target_id: str) -> None:
        """Move POSSIBLY_EXECUTING to target-only parking on positive completion proof."""
        if not is_identity_text(target_id):
            raise BaseQueueRefused(BaseQueueRefused.INVALID_WORK)
        with self._lock:
            if target_id not in self._ownership:
                raise BaseQueueRefused(BaseQueueRefused.TARGET_NOT_UNRESOLVED)
            self._ownership[target_id] = CallOwnership.PROVEN_FINISHED

    def resolve_target(self, target_id: str, *, execution: Execution) -> None:
        """Unpark after the coordinator supplies a terminal outcome and finished ownership.

        ``execution`` is trusted coordinator state, not evidence independently checked here.
        A finished call with unresolved effect remains parked to prevent duplicate dispatch.
        """
        if not is_identity_text(target_id):
            raise BaseQueueRefused(BaseQueueRefused.INVALID_WORK)
        if type(execution) is not Execution or execution not in {
                Execution.APPLIED, Execution.FAILED_APPLY}:
            raise BaseQueueRefused(BaseQueueRefused.TARGET_OUTCOME_NOT_TERMINAL)
        with self._lock:
            if self._ownership.get(target_id) is not CallOwnership.PROVEN_FINISHED:
                raise BaseQueueRefused(BaseQueueRefused.TARGET_NOT_PROVEN_FINISHED)
            if any(work.target_id == target_id for work in self._in_flight.values()):
                raise BaseQueueRefused(BaseQueueRefused.TARGET_WORK_ACTIVE)
            del self._ownership[target_id]

    def next_ready(self) -> QueueWork | None:
        """Claim the oldest eligible item, preferring verification reads over mutations."""
        with self._lock:
            ready: list[tuple[int, int, QueueWork]] = []
            base_held = any(owner is CallOwnership.POSSIBLY_EXECUTING
                            for owner in self._ownership.values())
            parked = {target for target, owner in self._ownership.items()
                      if owner is CallOwnership.PROVEN_FINISHED}
            active_targets = {work.target_id for work in self._in_flight.values()}
            for work_id, (sequence, work) in self._pending.items():
                if work.target_id in active_targets:
                    continue
                if work.kind is QueueWorkKind.MUTATION and (
                        base_held or work.target_id in parked):
                    continue
                priority = 0 if work.kind is QueueWorkKind.VERIFY_READ else 1
                ready.append((priority, sequence, work))
            if not ready:
                return None
            _, _, chosen = min(ready, key=lambda item: (item[0], item[1]))
            del self._pending[chosen.work_id]
            self._in_flight[chosen.work_id] = chosen
            return chosen

    def complete(self, work_id: UUID) -> None:
        """Release only an item that was previously claimed from this queue."""
        with self._lock:
            if work_id not in self._in_flight:
                raise BaseQueueRefused(BaseQueueRefused.WORK_NOT_IN_FLIGHT)
            del self._in_flight[work_id]

    def begin_shutdown(self) -> None:
        """Close admission while allowing ready work to drain; never cancels active work."""
        with self._lock:
            self._admission_closed = True

    def unresolved_targets(self) -> tuple[tuple[str, CallOwnership], ...]:
        """Return a stable diagnostic snapshot without weakening holds."""
        with self._lock:
            return tuple(sorted(self._ownership.items()))
