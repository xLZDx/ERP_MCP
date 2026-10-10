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
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any
from uuid import UUID

from ._identity import canonical_guid
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
    "MAX_EVENTS_PER_COMMIT",
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
# The cursor port (SQL ``jsonb_array_length > 1000``, fake alike) refuses a bigger batch for good; a page
# whose events exceed it is refused with the fixed non-retryable PAGE_TOO_LARGE, never retried forever.
MAX_EVENTS_PER_COMMIT = 1000
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
    PAGE_TOO_LARGE = "PAGE_TOO_LARGE"
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


_RESERVED_EVENT_KEYS = frozenset({
    "event_id", "event_kind", "namespace", "tenant", "connection_id", "change_id", "digest"})


def _event_value_ok(value: object) -> bool:
    return (
        value is None or type(value) is str
        or (type(value) is list and all(type(v) is str for v in value))
    )


def build_event(identity: DrivePortIdentity, kind: str, change_id: str,
                **fields: str | None | list[str]) -> dict[str, Any]:
    """One outbox event with its SQL-compatible digest. ``fields`` values: str / None / list of str.

    A reserved key (``event_id``, ``event_kind``, ``namespace``, ``tenant``, ``connection_id``,
    ``change_id``, ``digest``) or any other value type raises ``ValueError("DRIVE_EVENT_INVALID")``
    (fixed code, nothing echoed): the caller cannot overwrite what the module derives.
    """
    if (
        type(identity) is not DrivePortIdentity
        or not is_valid_opaque_id(kind)
        or not is_valid_opaque_id(change_id)
        or any(k in _RESERVED_EVENT_KEYS or not _event_value_ok(v) for k, v in fields.items())
    ):
        raise ValueError("DRIVE_EVENT_INVALID")
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
# Schema v2 = v1 + ``snap``: the ORIGINAL snapshot-generation marker (``ResnapshotTracker.begin_snapshot``)
# of a fresh snapshot. A record without a marker is still encoded and decoded as v1 (compatible).
_KEYS_V2 = _KEYS | {"snap"}
_RECORD_VERSION_SNAP = 2
_MAX_RECEIPTS = 4_096
_MAX_SNAP = 2**(128 + 32) - 1  # 128-bit tracker generation << 32 | order token


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
    # Opaque provider tokens are redacted from the repr.
    token: str | None = field(default=None, repr=False)
    pos: str | None = field(default=None, repr=False)
    seen: tuple[str, ...] = field(default=(), repr=False)
    reason: CursorReason | None = None
    # Original snapshot-generation marker of a fresh snapshot (None: not a fresh snapshot / legacy).
    snap: int | None = None

    def __post_init__(self) -> None:
        bad = ValueError("DRIVE_CURSOR_RECORD_INVALID")
        if self.snap is not None and (
            type(self.snap) is not int or not 0 <= self.snap <= _MAX_SNAP
            or self.state is CursorState.UNINITIALIZED
        ):
            raise bad
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
        body: dict[str, Any] = {
            "v": _RECORD_VERSION, "state": self.state.value, "ns": self.namespace,
            "tenant": self.tenant, "conn": self.connection_id, "corpus": self.corpus,
            "epoch": self.epoch, "token": self.token, "pos": self.pos,
            "seen": list(self.seen),
            "reason": None if self.reason is None else self.reason.value,
        }
        if self.snap is not None:
            body["v"] = _RECORD_VERSION_SNAP
            body["snap"] = self.snap
        return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @classmethod
    def decode(cls, text: object) -> CursorRecord | None:
        """Strict parse: ``None`` for anything that is not byte-for-byte a canonical record."""
        if type(text) is not str or not text or len(text) > _MAX_RECORD_CHARS:
            return None
        try:
            raw = json.loads(text, parse_constant=_reject_constant)
            if type(raw) is not dict or type(raw.get("v")) is not int:
                return None
            if raw["v"] == _RECORD_VERSION:
                if set(raw) != _KEYS:
                    return None
            elif raw["v"] != _RECORD_VERSION_SNAP or set(raw) != _KEYS_V2 or raw["snap"] is None:
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
                snap=raw.get("snap"),
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
    raw_value: str | None = field(default=None, repr=False)  # holds opaque tokens: never printed
    # Allow-listed port error code (exact ``str`` from ``_SAFE_PORT_CODES``) that caused a
    # PORT_FAILURE / lease-loss load; None for every other code. Never caller / provider text.
    port_code: str | None = None


class CursorCommitReceipt:
    """Opaque acknowledgment handle issued by ``DriveCursorStore.commit`` after a durable commit.

    It carries NO evidence of its own (only a private nonce): what it proves lives in the issuing store's
    registry and is checked through ``DriveCursorStore.receipt_matches``, which binds it to the exact
    connection, prior cursor, committed cursor and epoch. Constructing one elsewhere proves nothing."""

    __slots__ = ("_nonce",)

    def __init__(self, nonce: object) -> None:
        self._nonce = nonce

    def __repr__(self) -> str:
        return "CursorCommitReceipt()"


@dataclass(frozen=True, slots=True)
class StoreCommit:
    ok: bool
    replayed: bool
    version: int | None
    reason: CursorReason | None
    receipt: CursorCommitReceipt | None = None


_COMMIT_REASONS = {
    "STALE_JOB_FENCE": CursorReason.LEASE_LOST,
    "SCOPE_REVOKED": CursorReason.SCOPE_REVOKED,
    "SCOPE_NOT_GRANTED": CursorReason.SCOPE_REVOKED,
    "PERMISSION_DENIED": CursorReason.SCOPE_REVOKED,
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


_PORT_BLOCK_CODES = frozenset({"SCOPE_REVOKED", "SCOPE_NOT_GRANTED", "PERMISSION_DENIED"})


def _port_reason(code: object) -> CursorReason:
    """Reason for a ``PortError`` code outside ``commit_cursor_page`` (exact ``str`` codes only)."""
    if type(code) is str:
        if code in _PORT_BLOCK_CODES:
            return CursorReason.SCOPE_REVOKED
        if code == "STALE_JOB_FENCE":
            return CursorReason.LEASE_LOST
    return CursorReason.PORT_FAILURE


# Fixed outward port codes: the cursor/job port contract (SQL error texts of the cursor, outbox and job
# functions, as raised by the in-memory fake) plus every code mapped above. Anything else is hostile or
# unknown and is never exposed.
_SAFE_PORT_CODES = frozenset({
    *_COMMIT_REASONS, *_PORT_BLOCK_CODES, "STALE_JOB_FENCE",
    "INVALID_LEASE", "INVALID_JOB", "JOB_UNAVAILABLE", "LEASE_EXPIRED", "INVALID_JSON",
    "NAIVE_DATETIME", "UNIQUE_VIOLATION", "CHECK_VIOLATION", "SOURCE_NOT_FOUND", "ROLE_NOT_FOUND",
})


def _exact_code(exc: PortError) -> str | None:
    """The port error code only when it is an exact ``str`` from the fixed allow-list; else None."""
    code = getattr(exc, "code", None)
    return code if type(code) is str and code in _SAFE_PORT_CODES else None


def _canon(value: str) -> str:
    guid = canonical_guid(value)
    return value if guid is None else guid


def _clean_identity(identity: object) -> DrivePortIdentity | None:
    """Rebuild through the validating constructor: a forged / lying object yields ``None``."""
    try:
        if type(identity) is not DrivePortIdentity:
            return None
        return DrivePortIdentity(identity.namespace, identity.tenant, identity.connection_id)
    except Exception:  # noqa: BLE001 - hostile object: fixed refusal
        return None


def _clean_corpus(corpus: object) -> DriveCorpus | None:
    try:
        if type(corpus) is not DriveCorpus:
            return None
        return DriveCorpus(corpus.drive_id, corpus.root_folder_ids)
    except Exception:  # noqa: BLE001
        return None


def _clean_lease(lease: object) -> DriveLease | None:
    try:
        if type(lease) is not DriveLease or type(lease.scope) is not Scope:
            return None
        scope = Scope(lease.scope.tenant_id, lease.scope.source_id)
        return DriveLease(lease.actor, scope, lease.job_id, lease.worker, lease.fence,
                          lease.expected_epoch)
    except Exception:  # noqa: BLE001
        return None


def _clean_record(record: object) -> CursorRecord | None:
    try:
        return replace(record) if type(record) is CursorRecord else None  # type: ignore[type-var]
    except Exception:  # noqa: BLE001
        return None


def _tenant_ok(identity: DrivePortIdentity, lease: DriveLease) -> bool:
    """The lease scope must belong to the identity's tenant (canonical equality)."""
    return _canon(lease.scope.tenant_id) == identity.tenant


def _ident_lease(identity: object, lease: object) -> tuple[DrivePortIdentity, DriveLease] | None:
    ident, lse = _clean_identity(identity), _clean_lease(lease)
    return None if ident is None or lse is None else (ident, lse)


def _ctx(identity: object, corpus: object, drive_epoch: object,
         lease: object) -> tuple[DrivePortIdentity, DriveCorpus, DriveLease] | None:
    ident, corp, lse = _clean_identity(identity), _clean_corpus(corpus), _clean_lease(lease)
    if ident is None or corp is None or lse is None or not is_valid_scope_epoch(drive_epoch):
        return None
    return (ident, corp, lse) if _tenant_ok(ident, lse) else None


class DriveCursorStore:
    """Cursor record persistence + fail-closed bookkeeping (``ResnapshotTracker``).

    Every public async method is total: bad / forged arguments, hostile port results and port
    exceptions become fixed refusals (``asyncio.CancelledError`` is never swallowed).
    """

    def __init__(self, cursors: CursorOutboxPort, tracker: ResnapshotTracker) -> None:
        if type(tracker) is not ResnapshotTracker:
            raise ValueError("TRACKER_REQUIRED")
        self._cursors = cursors
        self._tracker = tracker
        # receipts this store handed out: nonce -> (namespace, tenant, connection, prior token, token, version, epoch)
        self._issued: dict[object, tuple[str, str, str, str | None, str, int, int]] = {}

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

    def _closed(self, key: str, lease: DriveLease, record_requirement: bool, reason: CursorReason,
                version: int | None = None, raw: str | None = None) -> CursorLoad:
        if record_requirement:
            self._tracker.require(key, tracker_reason(reason), lease.expected_epoch)
        return CursorLoad(False, fail_closed_state(reason), reason, None, version, raw)

    def _port_load(self, exc: PortError, key: str, lease: DriveLease,
                   record_requirement: bool) -> CursorLoad:
        code = _exact_code(exc)
        reason = _port_reason(code)
        if reason is CursorReason.SCOPE_REVOKED:  # revoked / not granted / denied: fail closed
            return self._closed(key, lease, record_requirement, reason)
        return CursorLoad(False, None, reason, port_code=code)

    # -- reads ---------------------------------------------------------------------------------

    async def load(self, identity: DrivePortIdentity, corpus: DriveCorpus, drive_epoch: int,
                   lease: DriveLease, *, record_requirement: bool = True) -> CursorLoad:
        """Read and validate the cursor; every failure is fail-closed and recorded in the tracker
        (unless ``record_requirement`` is False, used while a fresh snapshot is in progress)."""
        ctx = _ctx(identity, corpus, drive_epoch, lease)
        if ctx is None:
            return CursorLoad(False, None, CursorReason.INVALID_REQUEST)
        try:
            return await self._load(*ctx, drive_epoch, record_requirement is not False)
        except Exception:  # noqa: BLE001 - hostile port/result: fixed refusal, no echo
            return CursorLoad(False, None, CursorReason.PORT_FAILURE)

    async def _load(self, identity: DrivePortIdentity, corpus: DriveCorpus, lease: DriveLease,
                    drive_epoch: int, record_requirement: bool) -> CursorLoad:
        key = cursor_key(identity)
        try:
            view = await self._cursors.get_cursor(lease.actor, lease.scope, key)
        except PortError as exc:
            return self._port_load(exc, key, lease, record_requirement)

        def closed(reason: CursorReason, version: int | None = None,
                   raw: str | None = None) -> CursorLoad:
            return self._closed(key, lease, record_requirement, reason, version, raw)

        if view is None:
            return closed(CursorReason.CURSOR_MISSING)
        try:  # exact types first, only then any comparison (a lying __eq__ is never consulted)
            well_formed = (
                type(view) is CursorView
                and type(view.connection_id) is str
                and type(view.version) is int
                and type(view.cursor_value) is str
                and type(view.scope_epoch) is int
            )
            well_formed = well_formed and view.connection_id == key
            version, raw, view_epoch = view.version, view.cursor_value, view.scope_epoch
        except Exception:  # noqa: BLE001 - forged view object
            well_formed = False
        if not well_formed:
            return closed(CursorReason.CURSOR_CORRUPT)
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
        if record.epoch != drive_epoch or view_epoch != lease.expected_epoch:
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
        ctx = _ctx(identity, corpus, drive_epoch, lease)
        if ctx is None:
            return CursorLoad(False, None, CursorReason.INVALID_REQUEST)
        ident, corp, lse = ctx
        try:
            record = self.fresh_record(ident, corp, drive_epoch)
            try:
                await self._cursors.create_cursor(
                    lse.actor, lse.scope, cursor_key(ident), record.encode())
            except PortError as exc:
                return self._port_load(exc, cursor_key(ident), lse, True)
        except Exception:  # noqa: BLE001
            return CursorLoad(False, None, CursorReason.PORT_FAILURE)
        return await self.load(ident, corp, drive_epoch, lse)

    async def commit(self, identity: DrivePortIdentity, lease: DriveLease, load: CursorLoad,
                     new_record: CursorRecord, events: list[dict[str, Any]]) -> StoreCommit:
        """Commit the page events and the cursor advance together (all-or-nothing, lease fenced).

        The ``load`` must be internally consistent (its record encodes to its raw value, its state is
        the record's state, it is not a blocked state) and bound to ``identity``; ``new_record`` must
        keep the identity / corpus / epoch of the loaded record. Anything else is refused before any
        port call, so a forged load can never overwrite a stored GAP / RESNAPSHOT marker.
        """
        invalid = StoreCommit(False, False, None, CursorReason.INVALID_REQUEST)
        try:
            ids = _ident_lease(identity, lease)
            if (
                ids is None or type(load) is not CursorLoad or load.usable is not True
                or type(new_record) is not CursorRecord or type(events) is not list
                or any(type(e) is not dict for e in events)
            ):
                return invalid
            ident, lse = ids
            if not _tenant_ok(ident, lse):
                return invalid
            old, new = _clean_record(load.record), _clean_record(new_record)
            version, raw = load.version, load.raw_value
            if (
                old is None or new is None or type(version) is not int or type(raw) is not str
                or old.encode() != raw or load.state is not old.state
                or old.state in _BLOCKED_STATES
                or (old.namespace, old.tenant, old.connection_id)
                != (ident.namespace, ident.tenant, ident.connection_id)
                or (new.namespace, new.tenant, new.connection_id, new.corpus, new.epoch)
                != (old.namespace, old.tenant, old.connection_id, old.corpus, old.epoch)
            ):
                return invalid
            if len(events) > MAX_EVENTS_PER_COMMIT:
                return StoreCommit(False, False, None, CursorReason.PAGE_TOO_LARGE)
            if not is_allowed_transition(old.state, new.state):
                return StoreCommit(False, False, None, CursorReason.INVALID_TRANSITION)
            new_value = new.encode()
        except Exception:  # noqa: BLE001 - forged / hostile arguments
            return invalid
        done = await self._commit_raw(ident, lse, raw, version, new_value, events)
        if done.ok is True and type(done.version) is int and type(new.token) is str:
            nonce = object()
            while len(self._issued) >= _MAX_RECEIPTS:  # bounded: the oldest receipt expires first
                del self._issued[next(iter(self._issued))]
            self._issued[nonce] = (new.namespace, new.tenant, new.connection_id, old.token, new.token,
                                   done.version, new.epoch)
            done = replace(done, receipt=CursorCommitReceipt(nonce))
        return done

    def receipt_matches(self, receipt: object, identity: object, prior_cursor: object, token: object,
                        epoch: object) -> bool:
        """True only when ``receipt`` was issued by THIS store for a commit of exactly this connection
        (namespace, tenant, connection), from ``prior_cursor`` to ``token``, under ``epoch``. Never raises."""
        try:
            if (type(receipt) is not CursorCommitReceipt or type(identity) is not DrivePortIdentity
                    or type(token) is not str or type(epoch) is not int
                    or not (prior_cursor is None or type(prior_cursor) is str)):
                return False
            nonce = receipt._nonce
            if type(nonce) is not object:
                return False
            entry = self._issued.get(nonce)
            if entry is None:
                return False
            namespace, tenant, connection, prior, committed, _version, committed_epoch = entry
            parts = (identity.namespace, identity.tenant, identity.connection_id)
            if any(type(p) is not str for p in parts):
                return False
            return ((namespace, tenant, connection) == parts and prior == prior_cursor
                    and committed == token and committed_epoch == epoch)
        except Exception:  # noqa: BLE001 - a malformed receipt is simply not proof
            return False

    async def reset(self, identity: DrivePortIdentity, corpus: DriveCorpus, drive_epoch: int,
                    lease: DriveLease, load: CursorLoad) -> CursorLoad:
        """Explicit fresh-snapshot restart: overwrite whatever is stored (even a corrupt value) with a
        new UNINITIALIZED record, CAS-guarded and lease-fenced. The only way out of a blocked state."""
        invalid = CursorLoad(False, None, CursorReason.INVALID_REQUEST)
        ctx = _ctx(identity, corpus, drive_epoch, lease)
        if ctx is None or type(load) is not CursorLoad:
            return invalid
        ident, corp, lse = ctx
        try:
            version, raw = load.version, load.raw_value
            if version is None or raw is None:
                return await self.initialize(ident, corp, drive_epoch, lse)
            if type(version) is not int or type(raw) is not str:
                return invalid
            new = self.fresh_record(ident, corp, drive_epoch)
            new_value = new.encode()
        except Exception:  # noqa: BLE001
            return invalid
        result = await self._commit_raw(ident, lse, raw, version, new_value, [])
        if not result.ok or result.version is None:
            reason = result.reason or CursorReason.PORT_FAILURE
            if reason is CursorReason.SCOPE_REVOKED:
                try:
                    return self._closed(cursor_key(ident), lse, True, reason)
                except Exception:  # noqa: BLE001
                    return CursorLoad(False, None, CursorReason.PORT_FAILURE)
            return CursorLoad(False, None, reason)
        return CursorLoad(True, new.state, None, new, result.version, new_value)

    async def fail_closed(self, identity: DrivePortIdentity, lease: DriveLease, load: CursorLoad,
                          reason: CursorReason) -> bool:
        """Record a fail-closed condition: tracker first (always), then persist the GAP /
        RESNAPSHOT_REQUIRED marker when the stored record is valid. Returns True when persisted."""
        try:
            ids = _ident_lease(identity, lease)
            if ids is None:
                return False
            ident, lse = ids
            if type(reason) is not CursorReason:
                reason = CursorReason.PAGE_INVALID
            self._tracker.require(cursor_key(ident), tracker_reason(reason), lse.expected_epoch)
            if not _tenant_ok(ident, lse):
                return False
            if type(load) is not CursorLoad or load.usable is not True:
                return False
            old = _clean_record(load.record)
            if old is None:
                return False
            marked = old.evolve(state=fail_closed_state(reason), reason=reason)
            return (await self.commit(ident, lse, load, marked, [])).ok
        except Exception:  # noqa: BLE001
            return False

    async def _commit_raw(self, identity: DrivePortIdentity, lease: DriveLease, prior_value: str,
                          prior_version: int, new_value: str,
                          events: list[dict[str, Any]]) -> StoreCommit:
        failure = StoreCommit(False, False, None, CursorReason.PORT_FAILURE)
        try:
            result = await self._cursors.commit_cursor_page(
                lease.actor, lease.scope, cursor_key(identity), lease.job_id, lease.worker,
                lease.fence, prior_value, prior_version, lease.expected_epoch, new_value, events)
        except PortError as exc:
            return StoreCommit(False, False, None, _commit_reason(_exact_code(exc)))
        except Exception:  # noqa: BLE001 - hostile port: fixed refusal, no echo
            return failure
        try:
            if type(result) is not CommitResult or type(result.version) is not int:
                return failure
            return StoreCommit(True, result.replayed is True, result.version, None)
        except Exception:  # noqa: BLE001 - forged result object
            return failure
