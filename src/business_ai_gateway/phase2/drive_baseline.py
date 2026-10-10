"""Phase 2 (S7/E2) start-token-first Drive baseline + catch-up orchestrator (offline reference).

Fixed order, asserted by the call log in the tests::

    get_start_page_token -> persist the token (cursor CAS) -> baseline listing -> catch-up from the
    persisted token until a terminal ``new_start_page_token`` -> LIVE

so a change made while the baseline was being listed is not lost (TC106). Page tokens are opaque exact
strings, never normalised.

Contracts reused, not copied
- every page (baseline or changes) is projected through ``drive_changes.DriveChangeProjector``;
  the cursor advance is exactly ``PreparedDriveBatch.committable_cursor()`` (an unknown change kind
  therefore never advances the cursor);
- the page events and the cursor record are committed in ONE ``commit_cursor_page`` call with the job
  lease fence (``DriveLease``): all-or-nothing, a stale fence or a lost lease commits nothing;
- every fail-closed condition goes through ``ResnapshotTracker.require`` (``DriveCursorStore``) and is
  never cleared here except by an explicit fresh snapshot (``DriveRunMode.RESNAPSHOT_*``) that reaches
  LIVE and then ``ResnapshotTracker.complete``.

Bounded: ``BaselineLimits`` caps pages and rows per run; hitting a limit is the fixed non-complete
outcome ``LIMIT_REACHED`` (never LIVE) and the run is resumable from the committed cursor.

The baseline listing is injected (``BaselineLister``): the read-only ``DrivePort`` has no file-listing
method. Hostile input yields a fixed refusal; nothing a caller or provider supplied is echoed.
Pure stdlib + Phase 2 modules; no Release 1 / httpx / requests / socket import.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from .drift import CaptureOutcomeKind
from .drive_changes import (
    DriveChange,
    DriveChangeKind,
    DriveChangeProjector,
    DrivePage,
    EvidenceCandidate,
    PreparedDriveBatch,
    TombstoneCandidate,
)
from .drive_cursor import (
    CursorLoad,
    CursorReason,
    CursorRecord,
    CursorState,
    DriveCorpus,
    DriveCursorStore,
    DriveLease,
    build_event,
    cursor_key,
    fail_closed_state,
    tracker_reason,
)
from .drive_port import (
    MAX_LIST_ITEMS,
    ChangesPage,
    DriveErrorCode,
    DrivePort,
    DrivePortError,
    DrivePortIdentity,
    StartToken,
    is_valid_opaque_id,
    is_valid_scope_epoch,
)

__all__ = [
    "BaselineItem",
    "BaselineLimits",
    "BaselineLister",
    "BaselineOutcome",
    "BaselinePage",
    "BaselineRequest",
    "BaselineResult",
    "DriveBaseline",
    "DriveRunMode",
    "check_baseline_order",
]

_MAX_LIMIT = 1_000_000
# Cap of the re-qualification folder ids reported in one result (the durable DRIVE_REQUALIFY events
# carry the full set; the result only says ``requalify_truncated``).
_MAX_REQUALIFY = 100_000


class BaselineOutcome(StrEnum):
    LIVE = "LIVE"                              # complete: terminal new_start_page_token reached
    LIMIT_REACHED = "LIMIT_REACHED"            # non-complete, resumable
    BLOCKED = "BLOCKED"                        # incremental path blocked (resnapshot required)
    GAP = "GAP"
    RESNAPSHOT_REQUIRED = "RESNAPSHOT_REQUIRED"
    AUTH_REQUIRED = "AUTH_REQUIRED"            # cursor untouched
    LEASE_LOST = "LEASE_LOST"                  # nothing committed by the failed step
    CONFLICT = "CONFLICT"                      # same page id, different digest
    RETRYABLE = "RETRYABLE"                    # transient; nothing committed by the failed step
    REFUSED = "REFUSED"


class DriveRunMode(StrEnum):
    # First baseline, resume or poll. An ABSENT cursor is a first run: it is created (UNINITIALIZED)
    # and never marks the tracker; a corrupt / empty / foreign cursor or a pending requirement blocks.
    # Detecting a cursor that was deleted after it existed is ``ResnapshotTracker.revalidate``'s job.
    INCREMENTAL = "INCREMENTAL"
    RESNAPSHOT_START = "RESNAPSHOT_START"      # explicit fresh snapshot: overwrite the cursor
    RESNAPSHOT_CONTINUE = "RESNAPSHOT_CONTINUE"  # resume an interrupted fresh snapshot


# --- request / listing value types --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineLimits:
    max_pages: int = 1000
    max_rows: int = 100_000

    def __post_init__(self) -> None:
        for value in (self.max_pages, self.max_rows):
            if type(value) is not int or not 1 <= value <= _MAX_LIMIT:
                raise ValueError("BASELINE_LIMITS_INVALID")


@dataclass(frozen=True, slots=True)
class BaselineItem:
    file_id: str
    revision_id: str | None = None
    mime_type: str | None = None
    parents: tuple[str, ...] = ()
    drive_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not is_valid_opaque_id(self.file_id)
            or any(v is not None and not is_valid_opaque_id(v)
                   for v in (self.revision_id, self.mime_type, self.drive_id))
            or type(self.parents) is not tuple
            or len(self.parents) > MAX_LIST_ITEMS
            or any(not is_valid_opaque_id(p) for p in self.parents)
        ):
            raise ValueError("BASELINE_ITEM_INVALID")


@dataclass(frozen=True, slots=True)
class BaselinePage:
    items: tuple[BaselineItem, ...]
    next_position: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.items) is not tuple
            or len(self.items) > MAX_LIST_ITEMS
            or any(type(i) is not BaselineItem for i in self.items)
            or (self.next_position is not None and not is_valid_opaque_id(self.next_position))
        ):
            raise ValueError("BASELINE_PAGE_INVALID")


class BaselineLister(Protocol):
    """Injected baseline listing: ``position`` is None for the first page, then the opaque
    ``next_position`` of the previous page. May raise ``DrivePortError`` (fixed codes)."""

    async def list_page(
        self, identity: DrivePortIdentity, scope_epoch: int, position: str | None
    ) -> BaselinePage: ...


@dataclass(frozen=True, slots=True)
class BaselineRequest:
    identity: DrivePortIdentity
    corpus: DriveCorpus
    drive_epoch: int
    lease: DriveLease
    scope_allowed: Callable[[str], bool | None]
    lister: BaselineLister
    limits: BaselineLimits = field(default_factory=BaselineLimits)
    # Optional observer of the port + lister call order (used for the TC106 order guard).
    call_log: Callable[[], Sequence[str]] | None = None

    def __post_init__(self) -> None:
        try:
            valid = (
                type(self.identity) is DrivePortIdentity
                and type(self.corpus) is DriveCorpus
                and is_valid_scope_epoch(self.drive_epoch)
                and type(self.lease) is DriveLease
                and callable(self.scope_allowed)
                and callable(getattr(self.lister, "list_page", None))
                and type(self.limits) is BaselineLimits
                and (self.call_log is None or callable(self.call_log))
            )
            is_async = valid and _is_async_callable(self.scope_allowed)
        except Exception:  # noqa: BLE001 - hostile attribute access: fixed code, no echo
            raise ValueError("BASELINE_REQUEST_INVALID") from None
        if not valid:
            raise ValueError("BASELINE_REQUEST_INVALID")
        if is_async:
            raise ValueError("BASELINE_SCOPE_CALLBACK_ASYNC")


@dataclass(frozen=True, slots=True)
class BaselineResult:
    outcome: BaselineOutcome
    reason: CursorReason | None
    state: CursorState | None
    complete: bool
    pages: int
    rows: int
    candidates: tuple[EvidenceCandidate, ...] = ()
    tombstones: tuple[TombstoneCandidate, ...] = ()
    denied_changes: int = 0
    requalify_folder_ids: tuple[str, ...] = ()
    trace: tuple[str, ...] = ()
    snapshot_cleared: bool = False
    cursor_marked: bool = False
    # The cursor is durably LIVE but ``ResnapshotTracker.complete`` raised: the requirement is NOT cleared.
    clear_failed: bool = False
    # More re-qualification folders existed than ``_MAX_REQUALIFY`` (the events carry them all).
    requalify_truncated: bool = False


def _is_async_callable(fn: object) -> bool:
    """True for a coroutine function / awaitable / object whose ``__call__`` is ``async def``."""
    return (
        inspect.iscoroutinefunction(fn) or inspect.isawaitable(fn)
        or inspect.iscoroutinefunction(getattr(fn, "__call__", None))  # noqa: B004
    )


def check_baseline_order(call_log: object) -> bool:
    """True iff ``get_start_page_token`` was called and no baseline listing / changes call precedes it.

    Pure and total: anything that is not a sequence of strings is False.
    """
    try:
        names = tuple(call_log)  # type: ignore[call-overload]
        if any(type(n) is not str for n in names) or "get_start_page_token" not in names:
            return False
        first = names.index("get_start_page_token")
        return not any(n in ("baseline_list", "list_changes") for n in names[:first])
    except Exception:  # noqa: BLE001 - a hostile iterable is simply not a valid call log
        return False


# --- orchestrator -------------------------------------------------------------------------------


class _Stop(Exception):
    def __init__(self, outcome: BaselineOutcome, reason: CursorReason | None,
                 state: CursorState | None = None) -> None:
        super().__init__("STOP")
        self.outcome, self.reason, self.state = outcome, reason, state


@dataclass(slots=True)
class _Ctx:
    request: BaselineRequest
    mode: DriveRunMode
    key: str
    load: CursorLoad
    snap_token: int | None
    pages: int = 0
    rows: int = 0
    started_here: bool = False
    marked: bool = False
    clear_failed: bool = False
    candidates: list[EvidenceCandidate] = field(default_factory=list)
    tombstones: list[TombstoneCandidate] = field(default_factory=list)
    denied: int = 0
    requalify: list[str] = field(default_factory=list)
    requalify_seen: set[str] = field(default_factory=set)
    requalify_truncated: bool = False
    trace: list[str] = field(default_factory=list)
    seen_tokens: set[str] = field(default_factory=set)
    seen_positions: set[str] = field(default_factory=set)


def _tri(fn: Callable[[str], bool | None]) -> Callable[[str], bool | None]:
    def scope_allowed(file_id: str) -> bool | None:
        try:
            value = fn(file_id)
            if inspect.isawaitable(value):  # an async callback is never awaited: close it, fail closed
                close = getattr(value, "close", None)
                if callable(close):
                    close()
                return None
        except Exception:  # noqa: BLE001 - an unknown membership is fail-closed, never an echo
            return None
        return value if type(value) is bool else None

    return scope_allowed


class DriveBaseline:
    def __init__(self, port: DrivePort, store: DriveCursorStore) -> None:
        if type(store) is not DriveCursorStore:
            raise ValueError("DRIVE_STORE_REQUIRED")
        self._port = port
        self._store = store

    async def run(self, request: BaselineRequest,
                  mode: DriveRunMode = DriveRunMode.INCREMENTAL) -> BaselineResult:
        """One bounded run. Never raises (``CancelledError`` excepted): every failure is a fixed result."""
        if type(request) is not BaselineRequest or type(mode) is not DriveRunMode:
            return _refusal(CursorReason.INVALID_REQUEST)
        ctx: _Ctx | None = None
        try:
            ctx = await self._open(request, mode)
            await self._drive(ctx)
            cleared = False
            if mode is not DriveRunMode.INCREMENTAL and ctx.snap_token is not None:
                epoch = request.lease.expected_epoch
                try:
                    cleared = self._store.tracker.complete(
                        ctx.key, CaptureOutcomeKind.OK_COMPLETE, epoch, epoch,
                        snapshot_token=ctx.snap_token) is True
                except Exception:  # noqa: BLE001 - cursor already durably LIVE: flag, don't refuse
                    ctx.clear_failed = True
            ctx.trace.append("LIVE")
            return _result(ctx, BaselineOutcome.LIVE, None, CursorState.LIVE, cleared)
        except _Stop as stop:
            return _result(ctx, stop.outcome, stop.reason, stop.state) if ctx else _refusal(
                stop.reason or CursorReason.INTERNAL, stop.outcome, stop.state)
        except Exception:  # noqa: BLE001 - hostile input/collaborator: fixed refusal, no echo
            return _result(ctx, BaselineOutcome.REFUSED, CursorReason.INTERNAL, None) if ctx \
                else _refusal(CursorReason.INTERNAL)

    # -- setup ---------------------------------------------------------------------------------

    async def _open(self, request: BaselineRequest, mode: DriveRunMode) -> _Ctx:
        store, tracker = self._store, self._store.tracker
        key = cursor_key(request.identity)
        resnap = mode is not DriveRunMode.INCREMENTAL
        if not resnap and tracker.is_required(key):
            raise _Stop(BaselineOutcome.BLOCKED, CursorReason.INCREMENTAL_BLOCKED,
                        CursorState.RESNAPSHOT_REQUIRED)
        snap = tracker.begin_snapshot() if resnap else None
        args = (request.identity, request.corpus, request.drive_epoch, request.lease)
        if resnap:
            load = await store.load(*args, record_requirement=False)
        else:
            # An absent cursor is a first run: create it (never marks the tracker); every other
            # failure (corrupt / empty / foreign / epoch ...) is recorded by the store as before.
            load = await store.initialize(*args)
        if mode is DriveRunMode.RESNAPSHOT_START:
            if load.version is None and load.reason is not CursorReason.CURSOR_MISSING:
                raise _from_load(load)  # a failed read must not be "reset" over an unknown value
            load = await store.reset(*args, load)
        if not load.usable:
            raise _from_load(load)
        if mode is DriveRunMode.RESNAPSHOT_CONTINUE and load.record is not None and (
            load.record.state not in (
                CursorState.UNINITIALIZED, CursorState.BASELINING, CursorState.CATCHING_UP)
        ):
            raise _Stop(BaselineOutcome.BLOCKED, CursorReason.INCREMENTAL_BLOCKED, load.state)
        if mode is DriveRunMode.RESNAPSHOT_CONTINUE and load.record is not None \
                and load.record.state is not CursorState.UNINITIALIZED:
            # Resume under the ORIGINAL snapshot-generation marker persisted when the baseline started,
            # so a requirement recorded since then is never cleared by this older snapshot. A missing
            # or foreign (ahead of this tracker's order) marker cannot be trusted: restart from a
            # genuinely new snapshot instead of continuing.
            marker = tracker.token_from_marker(load.record.snap)
            if marker is not None and marker <= snap:  # type: ignore[operator]
                snap = marker
            else:
                load = await store.reset(*args, load)
                if not load.usable:
                    raise _from_load(load)
        return _Ctx(request, mode, key, load, snap)

    async def _drive(self, ctx: _Ctx) -> None:
        while True:
            state = ctx.load.record.state  # type: ignore[union-attr]
            if state is CursorState.UNINITIALIZED:
                await self._start(ctx)
            elif state is CursorState.BASELINING:
                await self._baseline_page(ctx)
            elif await self._catchup_page(ctx):
                return

    # -- steps ---------------------------------------------------------------------------------

    async def _start(self, ctx: _Ctx) -> None:
        req = ctx.request
        ctx.trace.append("START_TOKEN")
        try:
            start = await self._port.get_start_page_token(req.identity, req.drive_epoch)
        except DrivePortError as exc:
            await self._port_failure(ctx, exc.code, token_call=False)
            raise  # unreachable: _port_failure always raises
        ctx.started_here = True
        if type(start) is not StartToken or not is_valid_opaque_id(start.token):
            raise _Stop(BaselineOutcome.REFUSED, CursorReason.START_TOKEN_INVALID)
        rec: CursorRecord = ctx.load.record  # type: ignore[assignment]
        await self._commit(ctx, rec.evolve(
            state=CursorState.BASELINING, token=start.token, pos=None, seen=(),
            snap=None if ctx.snap_token is None
            else self._store.tracker.persistent_marker(ctx.snap_token)), [])
        ctx.trace.append("TOKEN_PERSISTED")

    async def _baseline_page(self, ctx: _Ctx) -> None:
        req, rec = ctx.request, ctx.load.record
        assert rec is not None and rec.token is not None
        self._check_limits(ctx, pages_only=True)
        self._check_order(ctx)
        try:
            page = await req.lister.list_page(req.identity, req.drive_epoch, rec.pos)
        except DrivePortError as exc:
            await self._port_failure(ctx, exc.code, token_call=False)
            raise
        self._check_order(ctx)
        if type(page) is not BaselinePage:
            await self._close(ctx, CursorReason.PAGE_INVALID)
        nxt = page.next_position
        if nxt is not None and (nxt == rec.pos or nxt in ctx.seen_positions):
            await self._close(ctx, CursorReason.TOKEN_REPEATED)
        if rec.pos is not None:
            ctx.seen_positions.add(rec.pos)
        self._check_limits(ctx, adding=len(page.items))
        start_token = rec.token
        changes = tuple(
            DriveChange(
                change_id=f"baseline|{len(start_token)}:{start_token}|{i.file_id}",
                file_id=i.file_id, revision_id=i.revision_id, kind=DriveChangeKind.UPSERT,
                drive_id=i.drive_id, mime_type=i.mime_type, parents=i.parents)
            for i in page.items)
        try:
            drive_page = DrivePage(
                requested_page_token=start_token, changes=changes, next_page_token=nxt,
                new_start_page_token=start_token if nxt is None else None)
        except ValueError:
            await self._close(ctx, CursorReason.PAGE_INVALID)
        prepared = await self._prepare(ctx, drive_page, start_token)
        # A baseline lists the corpus. A scope-refused item is always counted as denied. In a first
        # (INCREMENTAL) baseline nothing was captured before, so no tombstone is made. In a fresh
        # snapshot (RESNAPSHOT_*) the file may have been captured earlier and left the scope while the
        # cursor was lost: it gets a MEMBERSHIP_CHANGED tombstone event, committed with this page
        # (hence before ``snapshot_cleared`` can ever be reported).
        resnap = ctx.mode is not DriveRunMode.INCREMENTAL
        denied = prepared.denied_changes + len(prepared.tombstones)
        events = [
            build_event(req.identity, "DRIVE_CANDIDATE", c.change_id, file_id=c.file_id,
                        revision_id=c.revision_id, status=c.status)
            for c in prepared.candidates]
        if resnap:
            events += [
                build_event(req.identity, "DRIVE_TOMBSTONE", t.change_id, file_id=t.file_id,
                            revision_id=t.revision_id, reason=t.reason, status=t.status)
                for t in prepared.tombstones]
        new_state = CursorState.BASELINING if nxt is not None else CursorState.CATCHING_UP
        await self._commit(ctx, rec.evolve(state=new_state, pos=nxt), events)
        ctx.pages += 1
        ctx.rows += len(page.items)
        ctx.denied += denied
        ctx.candidates.extend(prepared.candidates)
        if resnap:
            ctx.tombstones.extend(prepared.tombstones)
        ctx.trace.append("BASELINE_PAGE")
        if nxt is None:
            ctx.trace.append("BASELINE_DONE")

    async def _catchup_page(self, ctx: _Ctx) -> bool:
        """One ``changes.list`` page from the persisted token. True once the terminal page is applied."""
        req, rec = ctx.request, ctx.load.record
        assert rec is not None and rec.token is not None
        self._check_limits(ctx, pages_only=True)
        token = rec.token
        ctx.seen_tokens.add(token)
        try:
            page = await self._port.list_changes(req.identity, req.drive_epoch, token)
        except DrivePortError as exc:
            await self._port_failure(ctx, exc.code, token_call=True)
            raise
        self._check_order(ctx)
        if type(page) is not ChangesPage:
            missing = (getattr(page, "next_page_token", 1) is None
                       and getattr(page, "new_start_page_token", 1) is None)
            await self._close(ctx, CursorReason.TOKEN_MISSING if missing
                              else CursorReason.PAGE_INVALID)
        nxt, new_start = page.next_page_token, page.new_start_page_token
        terminal = nxt is None
        proposed = new_start if terminal else nxt
        assert proposed is not None
        history = ctx.seen_tokens | set(rec.seen)
        if proposed == token:
            if not terminal or page.changes:
                await self._close(ctx, CursorReason.TOKEN_REPEATED)
            # No changes since the stored token: the poll is complete, the token stays.
            if rec.state is not CursorState.LIVE:
                await self._commit(ctx, rec.evolve(state=CursorState.LIVE), [])
            ctx.pages += 1
            ctx.trace.append("CATCHUP_PAGE")
            return True
        if proposed in history:
            await self._close(ctx, CursorReason.TOKEN_REGRESSED)
        self._check_limits(ctx, adding=len(page.changes))
        prepared = await self._prepare(ctx, page.to_drive_page(token), token)
        if prepared.unknown_changes > 0 or prepared.requires_gap_or_pause:
            await self._close(ctx, CursorReason.UNKNOWN_CHANGE_KIND)
        advance = prepared.committable_cursor()
        if advance != proposed:  # the projector's view of the cursor must match the page
            await self._close(ctx, CursorReason.PAGE_INVALID)
        events = page_events(req.identity, prepared, token)
        new_state = CursorState.LIVE if terminal else CursorState.CATCHING_UP
        await self._commit(ctx, rec.evolve(
            state=new_state, token=advance, seen=rec.advance_seen()), events)
        ctx.pages += 1
        ctx.rows += len(page.changes)
        ctx.denied += prepared.denied_changes
        ctx.candidates.extend(prepared.candidates)
        ctx.tombstones.extend(prepared.tombstones)
        for folder in prepared.requalify_folder_ids:
            if folder in ctx.requalify_seen:
                continue
            if len(ctx.requalify) >= _MAX_REQUALIFY:
                ctx.requalify_truncated = True
                break
            ctx.requalify_seen.add(folder)
            ctx.requalify.append(folder)
        ctx.trace.append("CATCHUP_PAGE")
        return terminal

    # -- helpers -------------------------------------------------------------------------------

    async def _prepare(self, ctx: _Ctx, page: DrivePage, stored: str) -> PreparedDriveBatch:
        req = ctx.request
        # The corpus decides the drive filter (also for an ``account:`` namespace); a ``drive:``
        # namespace without a corpus drive id falls back to its own drive id.
        drive_id = req.corpus.drive_id
        if drive_id is None and req.identity.kind == "drive":
            drive_id = req.identity.namespace_id
        projector = DriveChangeProjector(
            connection_id=req.identity.connection_id, drive_id=drive_id,
            file_scope_allowed=_tri(req.scope_allowed))
        try:
            return projector.prepare(page, stored_cursor=stored)
        except ValueError as exc:
            unverified = exc.args == ("FOLDER_MEMBERSHIP_UNVERIFIED",)
            await self._close(ctx, CursorReason.MEMBERSHIP_UNVERIFIED if unverified
                              else CursorReason.PAGE_INVALID)
            raise  # unreachable

    def _check_limits(self, ctx: _Ctx, *, pages_only: bool = False, adding: int = 0) -> None:
        limits = ctx.request.limits
        state = ctx.load.record.state if ctx.load.record else None
        if pages_only and ctx.pages >= limits.max_pages:
            raise _Stop(BaselineOutcome.LIMIT_REACHED, CursorReason.PAGE_LIMIT, state)
        # The first page of a run is always allowed (a page larger than max_rows would otherwise
        # never be committed and the run would livelock): the row limit is soft by one page.
        if adding and ctx.rows > 0 and ctx.rows + adding > limits.max_rows:
            raise _Stop(BaselineOutcome.LIMIT_REACHED, CursorReason.ROW_LIMIT, state)

    def _check_order(self, ctx: _Ctx) -> None:
        provider = ctx.request.call_log
        if provider is None or not ctx.started_here:
            return
        if not check_baseline_order(provider()):
            raise _Stop(BaselineOutcome.REFUSED, CursorReason.START_TOKEN_ORDER,
                        ctx.load.record.state if ctx.load.record else None)

    async def _commit(self, ctx: _Ctx, new_record: CursorRecord, events: list[dict[str, Any]]) -> None:
        req = ctx.request
        result = await self._store.commit(req.identity, req.lease, ctx.load, new_record, events)
        if not result.ok or result.version is None:
            raise await self._commit_stop(ctx, result.reason or CursorReason.PORT_FAILURE)
        ctx.load = CursorLoad(True, new_record.state, None, new_record, result.version,
                              new_record.encode())

    async def _commit_stop(self, ctx: _Ctx, reason: CursorReason) -> _Stop:
        state = ctx.load.record.state if ctx.load.record else None
        if reason is CursorReason.LEASE_LOST:
            return _Stop(BaselineOutcome.LEASE_LOST, reason, state)
        if reason in (CursorReason.SCOPE_REVOKED, CursorReason.CURSOR_MISSING):
            await self._close_quiet(ctx, reason)
            return _Stop(BaselineOutcome.RESNAPSHOT_REQUIRED, reason,
                         CursorState.RESNAPSHOT_REQUIRED)
        if reason is CursorReason.COMMIT_CONFLICT:
            return _Stop(BaselineOutcome.CONFLICT, reason, state)
        if reason in (CursorReason.STALE_CURSOR, CursorReason.PORT_FAILURE):
            return _Stop(BaselineOutcome.RETRYABLE, reason, state)
        return _Stop(BaselineOutcome.REFUSED, reason, state)

    async def _close_quiet(self, ctx: _Ctx, reason: CursorReason) -> None:
        """Tracker only (the lease/scope is already unusable, so a marker commit would fail)."""
        self._store.tracker.require(
            ctx.key, tracker_reason(reason), ctx.request.lease.expected_epoch)

    async def _close(self, ctx: _Ctx, reason: CursorReason) -> None:
        """Fail closed: tracker + persisted GAP/RESNAPSHOT_REQUIRED marker; always raises."""
        req = ctx.request
        state = fail_closed_state(reason)
        ctx.marked = await self._store.fail_closed(req.identity, req.lease, ctx.load, reason)
        outcome = (BaselineOutcome.GAP if state is CursorState.GAP
                   else BaselineOutcome.RESNAPSHOT_REQUIRED)
        raise _Stop(outcome, reason, state)

    async def _port_failure(self, ctx: _Ctx, code: DriveErrorCode, *, token_call: bool) -> None:
        state = ctx.load.record.state if ctx.load.record else None
        if code in (DriveErrorCode.INVALID_GRANT, DriveErrorCode.AUTH_REQUIRED):
            reason = (CursorReason.AUTH_INVALID_GRANT if code is DriveErrorCode.INVALID_GRANT
                      else CursorReason.AUTH_REQUIRED)
            raise _Stop(BaselineOutcome.AUTH_REQUIRED, reason, CursorState.AUTH_REQUIRED)
        if code is DriveErrorCode.SCOPE_EPOCH_STALE:
            await self._close(ctx, CursorReason.SCOPE_EPOCH_CHANGED)
        if code is DriveErrorCode.NOT_FOUND and token_call:
            await self._close(ctx, CursorReason.TOKEN_NOT_FOUND)
        if code is DriveErrorCode.RATE_LIMITED:
            raise _Stop(BaselineOutcome.RETRYABLE, CursorReason.RATE_LIMITED, state)
        if code is DriveErrorCode.TRANSIENT:
            raise _Stop(BaselineOutcome.RETRYABLE, CursorReason.TRANSIENT, state)
        raise _Stop(BaselineOutcome.REFUSED, CursorReason.PORT_UNEXPECTED, state)


def page_events(identity: DrivePortIdentity, prepared: PreparedDriveBatch,
                 requested_token: str) -> list[dict[str, Any]]:
    events = [
        build_event(identity, "DRIVE_CANDIDATE", c.change_id, file_id=c.file_id,
                    revision_id=c.revision_id, status=c.status)
        for c in prepared.candidates]
    events += [
        build_event(identity, "DRIVE_TOMBSTONE", t.change_id, file_id=t.file_id,
                    revision_id=t.revision_id, reason=t.reason, status=t.status)
        for t in prepared.tombstones]
    if prepared.requalify_folder_ids:
        events.append(build_event(
            identity, "DRIVE_REQUALIFY", requested_token,
            folder_ids=list(prepared.requalify_folder_ids)))
    return events


def _from_load(load: CursorLoad) -> _Stop:
    state, reason = load.state, load.reason
    if state is CursorState.GAP:
        return _Stop(BaselineOutcome.GAP, reason, state)
    if state is CursorState.RESNAPSHOT_REQUIRED:
        return _Stop(BaselineOutcome.RESNAPSHOT_REQUIRED, reason, state)
    if state is CursorState.AUTH_REQUIRED:
        return _Stop(BaselineOutcome.AUTH_REQUIRED, reason, state)
    if reason is CursorReason.INVALID_REQUEST:
        return _Stop(BaselineOutcome.REFUSED, reason, None)
    if reason is CursorReason.LEASE_LOST:
        return _Stop(BaselineOutcome.LEASE_LOST, reason, None)
    if reason is CursorReason.COMMIT_CONFLICT:
        return _Stop(BaselineOutcome.CONFLICT, reason, None)
    return _Stop(BaselineOutcome.RETRYABLE, reason or CursorReason.PORT_FAILURE, None)


def _refusal(reason: CursorReason, outcome: BaselineOutcome = BaselineOutcome.REFUSED,
             state: CursorState | None = None) -> BaselineResult:
    return BaselineResult(outcome, reason, state, False, 0, 0)


def _result(ctx: _Ctx | None, outcome: BaselineOutcome, reason: CursorReason | None,
            state: CursorState | None, cleared: bool = False) -> BaselineResult:
    assert ctx is not None
    return BaselineResult(
        outcome=outcome, reason=reason, state=state,
        complete=outcome is BaselineOutcome.LIVE, pages=ctx.pages, rows=ctx.rows,
        candidates=tuple(ctx.candidates), tombstones=tuple(ctx.tombstones),
        denied_changes=ctx.denied, requalify_folder_ids=tuple(ctx.requalify),
        trace=tuple(ctx.trace), snapshot_cleared=cleared, cursor_marked=ctx.marked,
        clear_failed=ctx.clear_failed, requalify_truncated=ctx.requalify_truncated)
