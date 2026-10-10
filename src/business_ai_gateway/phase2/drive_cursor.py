"""Phase 2 (S7/E2) durable, fail-closed Drive cursor record over the existing cursor CAS port.

Offline reference module. It owns the *cursor record* (one canonical JSON text stored as the
``cursor_value`` of ``CursorOutboxPort``) and the rules around it. It never reads Drive and never
decides what a page contains; ``drive_baseline.py`` does that and calls ``commit`` here so a page and
its cursor advance are committed together through ``commit_cursor_page`` with the job lease fence.

Record states: ``UNINITIALIZED`` -> ``BASELINING`` -> ``CATCHING_UP`` -> ``LIVE`` plus the fail-closed
states ``GAP``, ``AUTH_REQUIRED`` and ``RESNAPSHOT_REQUIRED``. A fail-closed state is never cleared by
this module: leaving it is only possible through ``reset`` (an explicit fresh snapshot, driven by
``drive_baseline`` and ``ResnapshotTracker.complete``).

Rules
- Namespaces ``account:<id>`` / ``drive:<id>`` are part of the cursor key, of every outbox event id and
  of the stored record, so identical raw file ids never collide and one namespace never reads another's
  cursor. Keys are length-prefixed (no separator ambiguity).
- No regular Drive-cursor expiry is invented: the recovery triggers are a missing / empty / corrupted
  cursor, an identity or corpus change versus the record, a changed scope epoch, a lost token (404), a
  repeated / regressing / missing continuation token, an unknown change kind and unverified membership.
- Exact types everywhere (``type(x) is ...``); tokens and ids are preserved byte-exact; hostile input
  yields a fixed refusal and never raises out of a public async method. Only fixed codes leave this
  module; nothing the caller supplied is echoed.
- Pure stdlib + the Phase 2 ports; no Release 1 / httpx / requests / socket import.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from uuid import UUID

from .drive_port import DrivePortIdentity, is_valid_opaque_id, is_valid_scope_epoch
from .ports import (
    CommitResult,
    CursorOutboxPort,
    CursorView,
    PortError,
    Scope,
    event_digest,
    jsonb_text,
)
from .resnapshot import ResnapshotReason, ResnapshotTracker

__all__ = [
    "SEEN_MAX",
    "CursorLoad",
    "CursorReason",
    "CursorRecord",
    "CursorState",
    "DriveCorpus",
    "DriveCursorStore",
    "DriveLease",
    "StoreCommit",
    "build_event",
    "cursor_key",
    "dedup_key",
    "fail_closed_state",
    "is_allowed_transition",
    "tracker_reason",
]

SEEN_MAX = 16
_MAX_RECORD_CHARS = 16_384
_RECORD_VERSION = 1


class CursorState(StrEnum):
    UNINITIALIZED = "UNINITIALIZED"
    BASELINING = "BASELINING"
    CATCHING_UP = "CATCHING_UP"
    LIVE = "LIVE"
    GAP = "GAP"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RESNAPSHOT_REQUIRED = "RESNAPSHOT_REQUIRED"


class CursorReason(StrEnum):
    """Every fixed outward reason code of the baseline/cursor layer (never provider text)."""

    # recovery triggers (resnapshot)
    CURSOR_MISSING = "CURSOR_MISSING"
    CURSOR_EMPTY = "CURSOR_EMPTY"
    CURSOR_CORRUPT = "CURSOR_CORRUPT"
    IDENTITY_CHANGED = "IDENTITY_CHANGED"
    CORPUS_CHANGED = "CORPUS_CHANGED"
    SCOPE_EPOCH_CHANGED = "SCOPE_EPOCH_CHANGED"
    TOKEN_NOT_FOUND = "TOKEN_NOT_FOUND"
    # recovery triggers (gap)
    TOKEN_REPEATED = "TOKEN_REPEATED"
    TOKEN_REGRESSED = "TOKEN_REGRESSED"
    TOKEN_MISSING = "TOKEN_MISSING"
    UNKNOWN_CHANGE_KIND = "UNKNOWN_CHANGE_KIND"
    MEMBERSHIP_UNVERIFIED = "MEMBERSHIP_UNVERIFIED"
    PAGE_INVALID = "PAGE_INVALID"
    # auth
    AUTH_INVALID_GRANT = "AUTH_INVALID_GRANT"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    # run-level
    INCREMENTAL_BLOCKED = "INCREMENTAL_BLOCKED"
    PAGE_LIMIT = "PAGE_LIMIT"
    ROW_LIMIT = "ROW_LIMIT"
    START_TOKEN_INVALID = "START_TOKEN_INVALID"
    START_TOKEN_ORDER = "START_TOKEN_ORDER"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL = "INTERNAL"
    # commit-level
    LEASE_LOST = "LEASE_LOST"
    SCOPE_REVOKED = "SCOPE_REVOKED"
    STALE_CURSOR = "STALE_CURSOR"
    COMMIT_CONFLICT = "COMMIT_CONFLICT"
    INVALID_BATCH = "INVALID_BATCH"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    # port-level
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    PORT_UNEXPECTED = "PORT_UNEXPECTED"
    PORT_FAILURE = "PORT_FAILURE"


_RESNAPSHOT_REASONS = frozenset({
    CursorReason.CURSOR_MISSING, CursorReason.CURSOR_EMPTY, CursorReason.CURSOR_CORRUPT,
    CursorReason.IDENTITY_CHANGED, CursorReason.CORPUS_CHANGED, CursorReason.SCOPE_EPOCH_CHANGED,
    CursorReason.TOKEN_NOT_FOUND, CursorReason.SCOPE_REVOKED,
})
_GAP_REASONS = frozenset({
    CursorReason.TOKEN_REPEATED, CursorReason.TOKEN_REGRESSED, CursorReason.TOKEN_MISSING,
    CursorReason.UNKNOWN_CHANGE_KIND, CursorReason.MEMBERSHIP_UNVERIFIED, CursorReason.PAGE_INVALID,
})
_BLOCKED_STATES = frozenset({
    CursorState.GAP, CursorState.AUTH_REQUIRED, CursorState.RESNAPSHOT_REQUIRED})


def fail_closed_state(reason: CursorReason) -> CursorState:
    """GAP for page-chain problems, RESNAPSHOT_REQUIRED for a lost/foreign/changed cursor."""
    return CursorState.RESNAPSHOT_REQUIRED if reason in _RESNAPSHOT_REASONS else CursorState.GAP


def tracker_reason(reason: CursorReason) -> ResnapshotReason:
    if reason is CursorReason.CURSOR_MISSING:
        return ResnapshotReason.CURSOR_MISSING
    if reason in (CursorReason.SCOPE_EPOCH_CHANGED, CursorReason.SCOPE_REVOKED):
        return ResnapshotReason.SCOPE_EPOCH_CHANGED
    return ResnapshotReason.CURSOR_LOST


_NORMAL = {
    CursorState.UNINITIALIZED: {CursorState.BASELINING},
    CursorState.BASELINING: {CursorState.BASELINING, CursorState.CATCHING_UP},
    CursorState.CATCHING_UP: {CursorState.CATCHING_UP, CursorState.LIVE},
    CursorState.LIVE: {CursorState.LIVE, CursorState.CATCHING_UP},
}


def is_allowed_transition(old: object, new: object) -> bool:
    """Normal-flow transition table. Any state may enter a fail-closed state; a fail-closed state is
    never left through this table (only ``DriveCursorStore.reset`` restarts from a fresh snapshot)."""
    if type(old) is not CursorState or type(new) is not CursorState:
        return False
    if new in _BLOCKED_STATES:
        return True
    return new in _NORMAL.get(old, ())


# --- keys ---------------------------------------------------------------------------------------


def _enc(prefix: str, *parts: str) -> str:
    return prefix + "".join(f"|{len(p)}:{p}" for p in parts)


def cursor_key(identity: DrivePortIdentity) -> str:
    """Cursor-port ``connection_id`` for one (namespace, tenant, connection); length-prefixed."""
    return _enc("drivecur1", identity.namespace, identity.tenant, identity.connection_id)


def dedup_key(namespace: str, kind: str, change_id: str) -> str:
    """Outbox ``event_id``: carries the namespace, so equal change ids in two namespaces never collide."""
    return _enc("drivechg1", namespace, kind, change_id)


def build_event(identity: DrivePortIdentity, kind: str, change_id: str,
                **fields: str | None | list[str]) -> dict[str, Any]:
    """One outbox event with its SQL-compatible digest. ``fields`` values: str / None / list of str."""
    event: dict[str, Any] = {
        "event_id": dedup_key(identity.namespace, kind, change_id),
        "event_kind": kind,
        "namespace": identity.namespace,
        "tenant": identity.tenant,
        "connection_id": identity.connection_id,
        "change_id": change_id,
    }
    event.update(fields)
    event["digest"] = event_digest(event)
    return event


# --- value types --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriveCorpus:
    """Declared corpus: optional shared-drive id and the root folder ids (at least one root)."""

    drive_id: str | None
    root_folder_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.drive_id is not None and not is_valid_opaque_id(self.drive_id):
            raise ValueError("DRIVE_CORPUS_INVALID")
        roots = self.root_folder_ids
        if (
            type(roots) is not tuple
            or not 0 < len(roots) <= 1000
            or any(not is_valid_opaque_id(r) for r in roots)
            or len(set(roots)) != len(roots)
        ):
            raise ValueError("DRIVE_CORPUS_INVALID")

    @property
    def fingerprint(self) -> str:
        text = jsonb_text({"drive_id": self.drive_id, "roots": sorted(self.root_folder_ids)})
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DriveLease:
    """The durable caller's job lease (``acquire_job`` result) used as the commit fence."""

    actor: str
    scope: Scope
    job_id: UUID
    worker: str
    fence: int
    expected_epoch: int

    def __post_init__(self) -> None:
        scope = self.scope
        if (
            type(self.actor) is not str or not self.actor
            or type(scope) is not Scope
            or type(scope.tenant_id) is not str or not scope.tenant_id
            or type(scope.source_id) is not str or not scope.source_id
            or type(self.job_id) is not UUID
            or type(self.worker) is not str or not self.worker
            or type(self.fence) is not int or self.fence < 0
            or not is_valid_scope_epoch(self.expected_epoch)
        ):
            raise ValueError("DRIVE_LEASE_INVALID")


_KEYS = frozenset({"v", "state", "ns", "tenant", "conn", "corpus", "epoch", "token", "pos",
                   "seen", "reason"})


def _hex64(value: object) -> bool:
    return (
        type(value) is str and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


@dataclass(frozen=True, slots=True)
class CursorRecord:
    state: CursorState
    namespace: str
    tenant: str
    connection_id: str
    corpus: str
    epoch: int
    token: str | None = None
    pos: str | None = None
    seen: tuple[str, ...] = ()
    reason: CursorReason | None = None

    def __post_init__(self) -> None:
        bad = ValueError("DRIVE_CURSOR_RECORD_INVALID")
        ns = self.namespace
        if (
            type(self.state) is not CursorState
            or not is_valid_opaque_id(ns)
            or not (ns.startswith(("account:", "drive:")) and ns.split(":", 1)[1])
            or not is_valid_opaque_id(self.tenant)
            or not is_valid_opaque_id(self.connection_id)
            or not _hex64(self.corpus)
            or not is_valid_scope_epoch(self.epoch)
            or (self.token is not None and not is_valid_opaque_id(self.token))
            or (self.pos is not None and not is_valid_opaque_id(self.pos))
            or type(self.seen) is not tuple
            or len(self.seen) > SEEN_MAX
            or any(not is_valid_opaque_id(s) for s in self.seen)
            or (self.reason is not None and type(self.reason) is not CursorReason)
        ):
            raise bad
        s = self.state
        if s is CursorState.UNINITIALIZED and (self.token or self.pos or self.seen or self.reason):
            raise bad
        if s in (CursorState.BASELINING, CursorState.CATCHING_UP, CursorState.LIVE):
            if self.token is None or self.reason is not None:
                raise bad
            if s is not CursorState.BASELINING and self.pos is not None:
                raise bad
        if s in (CursorState.GAP, CursorState.RESNAPSHOT_REQUIRED) and self.reason is None:
            raise bad

    def encode(self) -> str:
        return json.dumps(
            {
                "v": _RECORD_VERSION, "state": self.state.value, "ns": self.namespace,
                "tenant": self.tenant, "conn": self.connection_id, "corpus": self.corpus,
                "epoch": self.epoch, "token": self.token, "pos": self.pos,
                "seen": list(self.seen),
                "reason": None if self.reason is None else self.reason.value,
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )

    @classmethod
    def decode(cls, text: object) -> CursorRecord | None:
        """Strict parse: ``None`` for anything that is not byte-for-byte a canonical record."""
        if type(text) is not str or not text or len(text) > _MAX_RECORD_CHARS:
            return None
        try:
            raw = json.loads(text, parse_constant=_reject_constant)
            if type(raw) is not dict or set(raw) != _KEYS:
                return None
            if type(raw["v"]) is not int or raw["v"] != _RECORD_VERSION:
                return None
            if type(raw["state"]) is not str or type(raw["seen"]) is not list:
                return None
            reason = raw["reason"]
            if reason is not None and type(reason) is not str:
                return None
            record = cls(
                state=CursorState(raw["state"]), namespace=raw["ns"], tenant=raw["tenant"],
                connection_id=raw["conn"], corpus=raw["corpus"], epoch=raw["epoch"],
                token=raw["token"], pos=raw["pos"], seen=tuple(raw["seen"]),
                reason=None if reason is None else CursorReason(reason),
            )
        except (ValueError, TypeError, RecursionError, KeyError):
            return None
        return record if record.encode() == text else None

    def advance_seen(self) -> tuple[str, ...]:
        """``seen`` after leaving the current token (bounded, oldest dropped)."""
        if self.token is None:
            return self.seen
        return (self.seen + (self.token,))[-SEEN_MAX:]

    def evolve(self, **changes: Any) -> CursorRecord:
        return replace(self, **changes)


def _reject_constant(_name: str) -> None:
    raise ValueError("NON_FINITE")


@dataclass(frozen=True, slots=True)
class CursorLoad:
    """Result of reading the cursor. ``usable`` only for a valid, non-blocked record."""

    usable: bool
    state: CursorState | None
    reason: CursorReason | None
    record: CursorRecord | None = None
    version: int | None = None
    raw_value: str | None = None


@dataclass(frozen=True, slots=True)
class StoreCommit:
    ok: bool
    replayed: bool
    version: int | None
    reason: CursorReason | None


_COMMIT_REASONS = {
    "STALE_JOB_FENCE": CursorReason.LEASE_LOST,
    "SCOPE_REVOKED": CursorReason.SCOPE_REVOKED,
    "CONFLICTING_PAGE_REPLAY": CursorReason.COMMIT_CONFLICT,
    "CONFLICTING_EVENT_DIGEST": CursorReason.COMMIT_CONFLICT,
    "STALE_CURSOR_OR_SCOPE": CursorReason.STALE_CURSOR,
    "CURSOR_NOT_FOUND": CursorReason.CURSOR_MISSING,
    "INVALID_CURSOR_BATCH": CursorReason.INVALID_BATCH,
    "INVALID_OUTBOX_EVENT": CursorReason.INVALID_BATCH,
    "UNSUPPORTED_JSONB_VALUE": CursorReason.INVALID_BATCH,
    "INVALID_ARGUMENT": CursorReason.INVALID_BATCH,
}


def _commit_reason(code: object) -> CursorReason:
    if type(code) is str:
        return _COMMIT_REASONS.get(code, CursorReason.PORT_FAILURE)
    return CursorReason.PORT_FAILURE


def _valid_ctx(identity: object, corpus: object, drive_epoch: object, lease: object) -> bool:
    return (
        type(identity) is DrivePortIdentity
        and type(corpus) is DriveCorpus
        and is_valid_scope_epoch(drive_epoch)
        and type(lease) is DriveLease
    )


class DriveCursorStore:
    """Cursor record persistence + fail-closed bookkeeping (``ResnapshotTracker``)."""

    def __init__(self, cursors: CursorOutboxPort, tracker: ResnapshotTracker) -> None:
        if type(tracker) is not ResnapshotTracker:
            raise ValueError("TRACKER_REQUIRED")
        self._cursors = cursors
        self._tracker = tracker

    @property
    def tracker(self) -> ResnapshotTracker:
        return self._tracker

    @staticmethod
    def cursor_key(identity: DrivePortIdentity) -> str:
        return cursor_key(identity)

    @staticmethod
    def fresh_record(identity: DrivePortIdentity, corpus: DriveCorpus,
                     drive_epoch: int) -> CursorRecord:
        return CursorRecord(
            state=CursorState.UNINITIALIZED, namespace=identity.namespace, tenant=identity.tenant,
            connection_id=identity.connection_id, corpus=corpus.fingerprint, epoch=drive_epoch)

    # -- reads ---------------------------------------------------------------------------------

    async def load(self, identity: DrivePortIdentity, corpus: DriveCorpus, drive_epoch: int,
                   lease: DriveLease, *, record_requirement: bool = True) -> CursorLoad:
        """Read and validate the cursor; every failure is fail-closed and recorded in the tracker
        (unless ``record_requirement`` is False, used while a fresh snapshot is in progress)."""
        if not _valid_ctx(identity, corpus, drive_epoch, lease):
            return CursorLoad(False, None, CursorReason.INVALID_REQUEST)
        key = cursor_key(identity)
        try:
            view = await self._cursors.get_cursor(lease.actor, lease.scope, key)
        except PortError:
            return CursorLoad(False, None, CursorReason.PORT_FAILURE)

        def closed(reason: CursorReason, version: int | None = None, raw: str | None = None):
            if record_requirement:
                self._tracker.require(key, tracker_reason(reason), lease.expected_epoch)
            return CursorLoad(False, fail_closed_state(reason), reason, None, version, raw)

        if view is None:
            return closed(CursorReason.CURSOR_MISSING)
        if (
            type(view) is not CursorView
            or view.connection_id != key
            or type(view.version) is not int
            or type(view.cursor_value) is not str
        ):
            return closed(CursorReason.CURSOR_CORRUPT)
        version, raw = view.version, view.cursor_value
        if raw == "":
            return closed(CursorReason.CURSOR_EMPTY, version, raw)
        record = CursorRecord.decode(raw)
        if record is None:
            return closed(CursorReason.CURSOR_CORRUPT, version, raw)
        if (
            record.namespace != identity.namespace
            or record.tenant != identity.tenant
            or record.connection_id != identity.connection_id
        ):
            return closed(CursorReason.IDENTITY_CHANGED, version, raw)
        if record.corpus != corpus.fingerprint:
            return closed(CursorReason.CORPUS_CHANGED, version, raw)
        if record.epoch != drive_epoch or view.scope_epoch != lease.expected_epoch:
            return closed(CursorReason.SCOPE_EPOCH_CHANGED, version, raw)
        if record.state in _BLOCKED_STATES:
            if record_requirement and record.state is not CursorState.AUTH_REQUIRED:
                reason = record.reason or CursorReason.PAGE_INVALID
                self._tracker.require(key, tracker_reason(reason), lease.expected_epoch)
            return CursorLoad(False, record.state, record.reason, record, version, raw)
        return CursorLoad(True, record.state, None, record, version, raw)

    # -- writes --------------------------------------------------------------------------------

    async def initialize(self, identity: DrivePortIdentity, corpus: DriveCorpus, drive_epoch: int,
                         lease: DriveLease) -> CursorLoad:
        """Create the cursor in UNINITIALIZED if absent (idempotent), then load it. Never resets an
        existing cursor."""
        if not _valid_ctx(identity, corpus, drive_epoch, lease):
            return CursorLoad(False, None, CursorReason.INVALID_REQUEST)
        record = self.fresh_record(identity, corpus, drive_epoch)
        try:
            await self._cursors.create_cursor(
                lease.actor, lease.scope, cursor_key(identity), record.encode())
        except PortError:
            return CursorLoad(False, None, CursorReason.PORT_FAILURE)
        return await self.load(identity, corpus, drive_epoch, lease)

    async def commit(self, identity: DrivePortIdentity, lease: DriveLease, load: CursorLoad,
                     new_record: CursorRecord, events: list[dict[str, Any]]) -> StoreCommit:
        """Commit the page events and the cursor advance together (all-or-nothing, lease fenced)."""
        if (
            type(identity) is not DrivePortIdentity or type(lease) is not DriveLease
            or type(load) is not CursorLoad or not load.usable or load.record is None
            or load.version is None or load.raw_value is None
            or type(new_record) is not CursorRecord or type(events) is not list
        ):
            return StoreCommit(False, False, None, CursorReason.INVALID_REQUEST)
        if not is_allowed_transition(load.record.state, new_record.state):
            return StoreCommit(False, False, None, CursorReason.INVALID_TRANSITION)
        return await self._commit_raw(
            identity, lease, load.raw_value, load.version, new_record.encode(), events)

    async def reset(self, identity: DrivePortIdentity, corpus: DriveCorpus, drive_epoch: int,
                    lease: DriveLease, load: CursorLoad) -> CursorLoad:
        """Explicit fresh-snapshot restart: overwrite whatever is stored (even a corrupt value) with a
        new UNINITIALIZED record, CAS-guarded and lease-fenced. The only way out of a blocked state."""
        if not _valid_ctx(identity, corpus, drive_epoch, lease) or type(load) is not CursorLoad:
            return CursorLoad(False, None, CursorReason.INVALID_REQUEST)
        if load.version is None or load.raw_value is None:
            return await self.initialize(identity, corpus, drive_epoch, lease)
        new = self.fresh_record(identity, corpus, drive_epoch)
        result = await self._commit_raw(
            identity, lease, load.raw_value, load.version, new.encode(), [])
        if not result.ok or result.version is None:
            return CursorLoad(False, None, result.reason or CursorReason.PORT_FAILURE)
        return CursorLoad(True, new.state, None, new, result.version, new.encode())

    async def fail_closed(self, identity: DrivePortIdentity, lease: DriveLease, load: CursorLoad,
                          reason: CursorReason) -> bool:
        """Record a fail-closed condition: tracker first (always), then persist the GAP /
        RESNAPSHOT_REQUIRED marker when the stored record is valid. Returns True when persisted."""
        if type(reason) is not CursorReason:
            reason = CursorReason.PAGE_INVALID
        self._tracker.require(cursor_key(identity), tracker_reason(reason), lease.expected_epoch)
        if type(load) is not CursorLoad or not load.usable or load.record is None:
            return False
        marked = load.record.evolve(state=fail_closed_state(reason), reason=reason)
        result = await self.commit(identity, lease, load, marked, [])
        return result.ok

    async def _commit_raw(self, identity: DrivePortIdentity, lease: DriveLease, prior_value: str,
                          prior_version: int, new_value: str,
                          events: list[dict[str, Any]]) -> StoreCommit:
        try:
            result = await self._cursors.commit_cursor_page(
                lease.actor, lease.scope, cursor_key(identity), lease.job_id, lease.worker,
                lease.fence, prior_value, prior_version, lease.expected_epoch, new_value, events)
        except PortError as exc:
            return StoreCommit(False, False, None, _commit_reason(exc.code))
        if type(result) is not CommitResult or type(result.version) is not int:
            return StoreCommit(False, False, None, CursorReason.PORT_FAILURE)
        return StoreCommit(True, result.replayed is True, result.version, None)
