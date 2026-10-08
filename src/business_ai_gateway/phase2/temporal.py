"""Phase 2 bitemporal model-event draft: immutable observation history.

This is an offline in-memory reference model for integration tests. Not a
durable database, distributed ledger or authority to accept semantic profiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class EventKind(StrEnum):
    OBSERVED = "OBSERVED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    GAP = "GAP"
    ATTESTATION_REVOKED = "ATTESTATION_REVOKED"


def _timestamp(value: datetime | None, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(label + "_MUST_HAVE_TIMEZONE")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ModelEvent:
    event_id: str
    tenant_id: str
    source_id: str
    object_id: str
    revision_id: str
    kind: EventKind
    recorded_at: datetime
    observed_at: datetime
    source_effective_at: datetime | None = None
    digest: str | None = None
    source_revision: str | None = None

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.event_id, self.tenant_id, self.source_id, self.object_id, self.revision_id
        )):
            raise ValueError("INVALID_EVENT_IDENTITY")
        if not isinstance(self.kind, EventKind):
            raise TypeError("INVALID_EVENT_KIND")
        for attr in ("recorded_at", "observed_at", "source_effective_at"):
            object.__setattr__(self, attr, _timestamp(getattr(self, attr), attr))
        if self.observed_at > self.recorded_at:
            raise ValueError("OBSERVATION_AFTER_RECORDING")
        if self.kind == EventKind.OBSERVED and (
            self.digest is None or len(self.digest) != 64
            or any(c not in "0123456789abcdef" for c in self.digest)
        ):
            raise ValueError("OBSERVATION_DIGEST_REQUIRED")


class EventLedger:
    """Pure reference reducer. Persistence will require database constraints."""

    def __init__(self, tenant_id: str, source_id: str):
        if not tenant_id or not source_id:
            raise ValueError("INVALID_LEDGER_SCOPE")
        self.tenant_id, self.source_id = tenant_id, source_id
        self._events: dict[str, ModelEvent] = {}

    def append(self, event: ModelEvent) -> bool:
        if event.tenant_id != self.tenant_id or event.source_id != self.source_id:
            raise ValueError("EVENT_SCOPE_MISMATCH")
        prior = self._events.get(event.event_id)
        if prior is not None:
            if prior != event:
                raise ValueError("CONFLICTING_EVENT_ID")
            return False
        self._events[event.event_id] = event
        return True

    @property
    def events(self) -> tuple[ModelEvent, ...]:
        return tuple(sorted(self._events.values(), key=lambda e: (e.recorded_at, e.event_id)))

    def as_known_at(self, cutoff: datetime) -> dict[str, ModelEvent]:
        """One latest witnessed event per object as known to the system by cutoff."""
        limit = _timestamp(cutoff, "knowledge_cutoff")
        values = {}
        for event in self.events:
            if event.recorded_at > limit:
                break
            values[event.object_id] = event
        return values

    def as_effective_at(self, valid_at: datetime, known_at: datetime) -> dict[str, ModelEvent]:
        """Known source-effective facts; unknown valid time is NOT invented.

        A polling observation has no implicit effective time; only events with
        independently supplied source_effective_at participate.
        """
        valid, known = _timestamp(valid_at, "valid_cutoff"), _timestamp(known_at, "knowledge_cutoff")
        matched: dict[str, ModelEvent] = {}
        for event in self.events:
            if (event.recorded_at > known or event.source_effective_at is None
                    or event.source_effective_at > valid):
                continue
            prev = matched.get(event.object_id)
            if prev is None or (event.source_effective_at, event.recorded_at, event.event_id) > (
                prev.source_effective_at, prev.recorded_at, prev.event_id
            ):
                matched[event.object_id] = event
        return matched

    def history_gaps(self, known_at: datetime) -> tuple[ModelEvent, ...]:
        limit = _timestamp(known_at, "knowledge_cutoff")
        return tuple(e for e in self.events if e.kind == EventKind.GAP and e.recorded_at <= limit)
