"""Phase 2 bitemporal model-event draft: immutable observation history.

This is an offline in-memory reference model for integration tests. Not a
durable database, distributed ledger or authority to accept semantic profiles.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class EventKind(StrEnum):
    OBSERVED = "OBSERVED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    GAP = "GAP"
    ATTESTATION_REVOKED = "ATTESTATION_REVOKED"


def _timestamp(value: datetime | None, label: str, *, required: bool = True) -> datetime | None:
    if value is None:
        if required:
            raise ValueError(label.upper() + "_REQUIRED")
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(label + "_MUST_HAVE_TIMEZONE")
    return value.astimezone(UTC)


def _valid_digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


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
    supersedes_event_id: str | None = None

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.event_id, self.tenant_id, self.source_id, self.object_id, self.revision_id
        )):
            raise ValueError("INVALID_EVENT_IDENTITY")
        if not isinstance(self.kind, EventKind):
            raise TypeError("INVALID_EVENT_KIND")
        for attr in ("recorded_at", "observed_at"):
            object.__setattr__(self, attr, _timestamp(getattr(self, attr), attr))
        object.__setattr__(self, "source_effective_at",
                           _timestamp(self.source_effective_at, "source_effective_at",
                                      required=False))
        if self.observed_at > self.recorded_at:
            raise ValueError("OBSERVATION_AFTER_RECORDING")
        if self.kind == EventKind.OBSERVED:
            if not _valid_digest(self.digest):
                raise ValueError("OBSERVATION_DIGEST_REQUIRED")
        elif self.digest is not None and not isinstance(self.digest, str):
            raise ValueError("EVENT_DIGEST_INVALID")
        if self.supersedes_event_id is not None:
            if not isinstance(self.supersedes_event_id, str) or not self.supersedes_event_id.strip():
                raise ValueError("SUPERSEDES_INVALID")
            if self.supersedes_event_id == self.event_id:
                raise ValueError("SUPERSEDES_SELF")


class EventLedger:
    """Pure reference reducer. Persistence will require database constraints."""

    def __init__(self, tenant_id: str, source_id: str):
        if not tenant_id or not source_id:
            raise ValueError("INVALID_LEDGER_SCOPE")
        self.tenant_id, self.source_id = tenant_id, source_id
        self._events: dict[str, ModelEvent] = {}
        self._revision_digests: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def append(self, event: ModelEvent) -> bool:
        if event.tenant_id != self.tenant_id or event.source_id != self.source_id:
            raise ValueError("EVENT_SCOPE_MISMATCH")
        with self._lock:
            prior = self._events.get(event.event_id)
            if prior is not None:
                if prior != event:
                    raise ValueError("CONFLICTING_EVENT_ID")
                return False
            if event.supersedes_event_id is not None:
                target = self._events.get(event.supersedes_event_id)
                if target is None:
                    raise ValueError("SUPERSEDES_UNKNOWN_EVENT")
                if target.object_id != event.object_id:
                    raise ValueError("SUPERSEDES_OBJECT_MISMATCH")
            revision_key = (event.object_id, event.revision_id)
            if event.kind == EventKind.OBSERVED:
                known = self._revision_digests.get(revision_key)
                if known is not None and known != event.digest:
                    raise ValueError("CONFLICTING_REVISION_DIGEST")
                self._revision_digests[revision_key] = event.digest
            self._events[event.event_id] = event
            return True

    @property
    def events(self) -> tuple[ModelEvent, ...]:
        with self._lock:
            snapshot = tuple(self._events.values())
        return tuple(sorted(snapshot, key=lambda e: (e.recorded_at, e.event_id)))

    def as_known_at(self, cutoff: datetime) -> dict[str, ModelEvent]:
        """Latest OBSERVED event per object as known by cutoff.

        Head order: observed_at, then recorded_at, then event_id, among events
        with recorded_at <= cutoff. GAP / SOURCE_UNAVAILABLE / ATTESTATION_REVOKED
        never displace the head; read them through status_at / revoked_revisions.
        A head may be a revoked revision: use as_known_at_with_revocation to see the flag.
        """
        return {obj: ev for obj, (ev, _) in self.as_known_at_with_revocation(cutoff).items()}

    def as_known_at_with_revocation(
        self, cutoff: datetime
    ) -> dict[str, tuple[ModelEvent, bool]]:
        """Like as_known_at, but each head carries `revoked` (never served silently)."""
        limit = _timestamp(cutoff, "knowledge_cutoff")
        heads: dict[str, ModelEvent] = {}
        for event in self.events:
            if event.recorded_at > limit or event.kind != EventKind.OBSERVED:
                continue
            prev = heads.get(event.object_id)
            if prev is None or (event.observed_at, event.recorded_at, event.event_id) > (
                prev.observed_at, prev.recorded_at, prev.event_id
            ):
                heads[event.object_id] = event
        revoked = self.revoked_revisions(limit)
        return {obj: (ev, (ev.object_id, ev.revision_id) in revoked) for obj, ev in heads.items()}

    def status_at(self, known_at: datetime) -> dict[str, ModelEvent]:
        """Latest non-OBSERVED availability/status event per object by cutoff.

        ATTESTATION_REVOKED is sticky: a later GAP / SOURCE_UNAVAILABLE reports the
        object's availability but never hides the revocation (see revocation_status_at).
        """
        limit = _timestamp(known_at, "knowledge_cutoff")
        status: dict[str, ModelEvent] = {}
        for event in self.events:  # already ordered by (recorded_at, event_id)
            if event.recorded_at > limit:
                break
            if event.kind == EventKind.OBSERVED:
                continue
            prev = status.get(event.object_id)
            if prev is not None and prev.kind == EventKind.ATTESTATION_REVOKED                     and event.kind != EventKind.ATTESTATION_REVOKED:
                continue
            status[event.object_id] = event
        return status

    def revocation_status_at(self, known_at: datetime) -> dict[str, ModelEvent]:
        """Latest ATTESTATION_REVOKED event per object by cutoff, regardless of later GAPs."""
        limit = _timestamp(known_at, "knowledge_cutoff")
        revoked: dict[str, ModelEvent] = {}
        for event in self.events:
            if event.recorded_at > limit:
                break
            if event.kind == EventKind.ATTESTATION_REVOKED:
                revoked[event.object_id] = event
        return revoked

    def revoked_revisions(self, known_at: datetime) -> frozenset[tuple[str, str]]:
        """(object_id, revision_id) pairs whose attestation was revoked by known_at.

        A revocation is effective in every slice with recorded_at <= known_at,
        regardless of any source_effective_at it carries.
        """
        limit = _timestamp(known_at, "knowledge_cutoff")
        return frozenset(
            (e.object_id, e.revision_id) for e in self.events
            if e.kind == EventKind.ATTESTATION_REVOKED and e.recorded_at <= limit
        )

    def as_effective_at(self, valid_at: datetime, known_at: datetime) -> dict[str, ModelEvent]:
        """Known source-effective facts; unknown valid time is NOT invented.

        A polling observation has no implicit effective time; only OBSERVED events
        with independently supplied source_effective_at participate. A head whose
        revision was revoked (as known at known_at) is withheld, not replaced by
        an older revision.
        """
        valid, known = _timestamp(valid_at, "valid_cutoff"), _timestamp(known_at, "knowledge_cutoff")
        matched: dict[str, ModelEvent] = {}
        for event in self.events:
            if (event.kind != EventKind.OBSERVED or event.recorded_at > known
                    or event.source_effective_at is None
                    or event.source_effective_at > valid):
                continue
            prev = matched.get(event.object_id)
            if prev is None or (event.source_effective_at, event.recorded_at, event.event_id) > (
                prev.source_effective_at, prev.recorded_at, prev.event_id
            ):
                matched[event.object_id] = event
        revoked = self.revoked_revisions(known)
        return {obj: ev for obj, ev in matched.items()
                if (ev.object_id, ev.revision_id) not in revoked}

    def history_gaps(self, known_at: datetime) -> tuple[ModelEvent, ...]:
        limit = _timestamp(known_at, "knowledge_cutoff")
        return tuple(e for e in self.events if e.kind == EventKind.GAP and e.recorded_at <= limit)
