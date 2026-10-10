"""Phase 2 (S7/E3) Drive membership re-check: rename / move / shortcut / removal / revoke. Offline.

Membership means "the file's CURRENT parent chain reaches a declared corpus root", resolved through
the read-only ``DrivePort.get_file_meta`` (bounded depth, bounded lookups, cycle-safe). It is never
inferred from a name, size, hash, time or a shortcut.

Verdicts (fixed codes, no content disclosure: a result carries ids and codes only, never a name):
- IN_SCOPE: chain reaches a root (a pure rename keeps the same file id, hence the same object key).
- SCOPE_ESCAPE_DENIED: moved out of the corpus, other drive, shortcut whose target is outside.
- NOT_IN_SCOPE: unresolvable/trashed parent, cycle or depth bound hit, shortcut (never a membership
  proof and never evidence itself; its target is evidence under its own id).
- REMOVED: the file is trashed or no longer readable (NOT_FOUND on the file itself).
- CHECK_FAILED: auth / epoch / rate / transient error; fail closed (not in scope, nothing disclosed).

Pages are projected through the existing ``DriveChangeProjector`` (reused): membership is resolved
first (async), then handed to the projector as a synchronous lookup. Any unverifiable membership or a
scope-epoch change during the page refuses the whole page, so the caller never advances a cursor.
A scope-epoch change (revoke / re-consent) invalidates every cached membership; disclosure needs a
fresh check (``authorize_disclosure``).

Release-2 conventions: exact types, fixed codes, nothing echoed, no Release 1 / httpx / requests /
socket import; hostile input never raises out of a public async method.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from ._identity import stable_key
from .drive_baseline import page_events
from .drive_changes import (
    DriveChange,
    DriveChangeKind,
    DriveChangeProjector,
    DrivePage,
    PreparedDriveBatch,
)
from .drive_cursor import DriveCorpus, DriveCursorStore, events_digest
from .drive_port import (
    MAX_CORPUS_ROOTS,
    DriveErrorCode,
    DrivePort,
    DrivePortError,
    DrivePortIdentity,
    FileMeta,
    is_sound_file_meta,
    is_sound_identity,
    is_valid_opaque_id,
    is_valid_scope_epoch,
)
from .drive_scope import DEFAULT_MAX_CALLS, DEFAULT_MAX_DEPTH, cursor_corpus_parts, graph_reaches

__all__ = [
    "MAX_ANCESTORS_PER_ENTRY",
    "MAX_ANCESTOR_INDEX_ENTRIES",
    "MAX_CACHE_ENTRIES",
    "MAX_CHAIN_DEPTH",
    "MAX_LOOKUPS_PER_CHECK",
    "MAX_LOOKUPS_PER_PAGE",
    "MAX_ROOTS",
    "Corpus",
    "MembershipChecker",
    "MembershipReason",
    "MembershipResult",
    "MembershipVerdict",
    "PagePreparation",
    "PageReason",
    "PageStatus",
    "corpus_from_drive_corpus",
]

# depth / call budget and the root limit are the SAME constants as drive_scope / drive_port
MAX_CHAIN_DEPTH = DEFAULT_MAX_DEPTH
MAX_LOOKUPS_PER_CHECK = DEFAULT_MAX_CALLS
MAX_ROOTS = MAX_CORPUS_ROOTS
MAX_CACHE_ENTRIES = 100_000
MAX_ANCESTORS_PER_ENTRY = 256  # visited ids kept per cached file (a hostile file may list 10,000 parents)
MAX_ANCESTOR_INDEX_ENTRIES = 1_000_000  # total (ancestor, file) pairs of the invalidation index
MAX_LOOKUPS_PER_PAGE = 4_096  # port lookups one prepare_page may spend over all of its changes


class MembershipVerdict(StrEnum):
    IN_SCOPE = "IN_SCOPE"
    SCOPE_ESCAPE_DENIED = "SCOPE_ESCAPE_DENIED"
    NOT_IN_SCOPE = "NOT_IN_SCOPE"
    REMOVED = "REMOVED"
    CHECK_FAILED = "CHECK_FAILED"


class PageStatus(StrEnum):
    PREPARED = "PREPARED"
    REFUSED = "REFUSED"


class MembershipReason(StrEnum):
    IN_CORPUS = "IN_CORPUS"
    DRIVE_MISMATCH = "DRIVE_MISMATCH"
    TRASHED = "TRASHED"
    CYCLE_OR_DEPTH = "CYCLE_OR_DEPTH"
    PARENT_UNRESOLVED = "PARENT_UNRESOLVED"
    OUT_OF_CORPUS = "OUT_OF_CORPUS"
    SHORTCUT_TARGET_UNRESOLVED = "SHORTCUT_TARGET_UNRESOLVED"
    SHORTCUT_TARGET_OUTSIDE = "SHORTCUT_TARGET_OUTSIDE"
    SHORTCUT_NOT_EVIDENCE = "SHORTCUT_NOT_EVIDENCE"
    INVALID_INPUT = "INVALID_INPUT"
    # DriveErrorCode values (fixed port codes)
    NOT_FOUND = "NOT_FOUND"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CREDENTIAL_REJECTED = "INVALID_GRANT"  # value of DriveErrorCode.INVALID_GRANT
    FORBIDDEN_HISTORY = "FORBIDDEN_HISTORY"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    SCOPE_EPOCH_STALE = "SCOPE_EPOCH_STALE"


class PageReason(StrEnum):
    PAGE_PREPARED = "PAGE_PREPARED"
    INVALID_INPUT = "INVALID_INPUT"
    EPOCH_CHANGED_DURING_PAGE = "EPOCH_CHANGED_DURING_PAGE"
    PAGE_MEMBERSHIP_UNVERIFIED = "PAGE_MEMBERSHIP_UNVERIFIED"
    PAGE_CURSOR_MISMATCH = "PAGE_CURSOR_MISMATCH"
    PAGE_PROJECTION_REFUSED = "PAGE_PROJECTION_REFUSED"
    UNKNOWN_CHANGE_KIND = "UNKNOWN_CHANGE_KIND"  # an UNKNOWN change needs a gap/pause, never an advance
    PAGE_LOOKUP_BUDGET_EXCEEDED = "PAGE_LOOKUP_BUDGET_EXCEEDED"


@dataclass(frozen=True, slots=True)
class Corpus:
    """Declared corpus: roots live in exactly one namespace (``account:<id>`` or ``drive:<id>``).

    ``shared_drive_id`` set: every member must carry that drive id; None: members must have no drive id.
    """

    namespace: str
    root_folder_ids: tuple[str, ...]
    shared_drive_id: str | None = None

    def __post_init__(self) -> None:
        # reuse the identity validator for the namespace shape (opaque id + known prefix)
        DrivePortIdentity(self.namespace, "t", "c")
        if (
            type(self.root_folder_ids) is not tuple
            or not 0 < len(self.root_folder_ids) <= MAX_ROOTS
            or not all(is_valid_opaque_id(r) for r in self.root_folder_ids)
        ):
            raise ValueError("CORPUS_ROOTS_INVALID")
        if self.shared_drive_id is not None and not is_valid_opaque_id(self.shared_drive_id):
            raise ValueError("CORPUS_DRIVE_INVALID")


@dataclass(frozen=True, slots=True)
class MembershipResult:
    file_id: str
    verdict: MembershipVerdict
    reason: MembershipReason  # fixed code
    object_key: str  # stable_key(namespace, file_id): identity survives a rename
    # a candidate may be created only for IN_SCOPE non-shortcut files
    candidate_allowed: bool = False

    def __post_init__(self) -> None:
        if type(self.verdict) is not MembershipVerdict or type(self.reason) is not MembershipReason:
            raise ValueError("MEMBERSHIP_REASON_INVALID")


@dataclass(frozen=True, slots=True)
class PagePreparation:
    status: PageStatus
    reason: PageReason
    batch: PreparedDriveBatch | None = None
    results: tuple[MembershipResult, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not PageStatus or type(self.reason) is not PageReason:
            raise ValueError("PAGE_REASON_INVALID")


def corpus_from_drive_corpus(corpus: object, identity: object) -> Corpus:
    """Build the ``Corpus`` of a ``drive_cursor.DriveCorpus`` for ``identity`` (same checks and fixed
    codes as ``drive_scope.declaration_from_drive_corpus``: CORPUS_INVALID / CORPUS_IDENTITY_MISMATCH)."""
    drive_id, roots = cursor_corpus_parts(corpus, identity)
    return Corpus(identity.namespace, roots, drive_id)  # type: ignore[attr-defined]


class _CheckFailedError(Exception):
    def __init__(self, code: MembershipReason) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(slots=True)
class _CacheEntry:
    result: MembershipResult
    epoch: int
    ancestors: frozenset[str]


class MembershipChecker:
    def __init__(
        self, port: DrivePort, identity: DrivePortIdentity, corpus: Corpus, scope_epoch: int,
        *, commit_store: object | None = None,
    ) -> None:
        try:
            sound = (
                is_sound_identity(identity)
                and type(corpus) is Corpus
                and type(corpus.namespace) is str
                and type(corpus.root_folder_ids) is tuple
            )
        except Exception:  # noqa: BLE001 - forged corpus (unset slot)
            sound = False
        if not sound:
            raise ValueError("MEMBERSHIP_CONFIG_INVALID")
        if corpus.namespace != identity.namespace:
            raise ValueError("MEMBERSHIP_NAMESPACE_MISMATCH")
        if not is_valid_scope_epoch(scope_epoch):
            raise ValueError("SCOPE_EPOCH_INVALID")
        self._port = port
        self._identity = identity
        self._corpus = corpus
        self._roots = frozenset(corpus.root_folder_ids)
        self._epoch = scope_epoch
        self._cache: dict[str, _CacheEntry] = {}
        self._by_ancestor: dict[str, set[str]] = {}
        self._index_size = 0  # total (ancestor, file) pairs in _by_ancestor
        # (preparation, roots, epoch, stored cursor) of the last PREPARED page: removed roots it re-qualified; applied only by accept_page
        self._pending_reinstate: tuple[object, frozenset[str], int, str] | None = None
        # the cursor store whose commit receipts count as proof; without one nothing is ever reinstated
        self._commit_store = commit_store if type(commit_store) is DriveCursorStore else None
        self._removed_roots: set[str] = set()  # roots a change feed reported removed/trashed
        self._lookups = 0  # port lookups so far (page budget)

    @property
    def scope_epoch(self) -> int:
        return self._epoch

    # --- epoch / cache ---------------------------------------------------------------------------

    def advance_epoch(self, scope_epoch: object) -> bool:
        """Adopt a new scope epoch (revoke / re-consent). Epochs never go back; every cached
        membership is then stale and re-checked before use. False for a refused value."""
        if not is_valid_scope_epoch(scope_epoch) or scope_epoch < self._epoch:  # type: ignore[operator]
            return False
        self._epoch = scope_epoch  # type: ignore[assignment]
        self._pending_reinstate = None  # a preparation made under an older epoch can never be accepted
        return True

    def cached(self, file_id: object) -> MembershipResult | None:
        """Cached result, only when it was produced under the CURRENT epoch."""
        if not is_valid_opaque_id(file_id):
            return None
        entry = self._cache.get(file_id)  # type: ignore[arg-type]
        return entry.result if entry is not None and entry.epoch == self._epoch else None

    def invalidate(self, file_id: object) -> tuple[str, ...]:
        """Drop the entry of ``file_id`` and of every cached descendant (folder move/removal).
        Returns the dropped file ids so the caller can re-check them."""
        if not is_valid_opaque_id(file_id):
            return ()
        dropped = {file_id}
        dropped |= self._by_ancestor.get(file_id, set())  # type: ignore[arg-type]
        out = []
        for fid in sorted(dropped):  # type: ignore[type-var]
            if self._drop(fid):
                out.append(fid)
        return tuple(out)

    def _drop(self, file_id: str) -> bool:
        entry = self._cache.pop(file_id, None)
        if entry is None:
            return False
        for anc in entry.ancestors:
            members = self._by_ancestor.get(anc)
            if members is not None and file_id in members:
                members.discard(file_id)
                self._index_size -= 1
                if not members:
                    del self._by_ancestor[anc]
        return True

    def _store(self, result: MembershipResult, epoch: int, ancestors: frozenset[str]) -> None:
        if result.verdict is MembershipVerdict.CHECK_FAILED:
            return
        self._drop(result.file_id)
        if result.reason is MembershipReason.CYCLE_OR_DEPTH or len(ancestors) > MAX_ANCESTORS_PER_ENTRY:
            return  # bound hit: the ancestor set is incomplete, so it could not be invalidated reliably
        if (
            len(self._cache) >= MAX_CACHE_ENTRIES
            or self._index_size + len(ancestors) > MAX_ANCESTOR_INDEX_ENTRIES
        ):
            return  # bounded: not cached, still correct (re-resolved next time)
        self._cache[result.file_id] = _CacheEntry(result, epoch, ancestors)
        for anc in ancestors:
            self._by_ancestor.setdefault(anc, set()).add(result.file_id)
            self._index_size += 1

    # --- checks ----------------------------------------------------------------------------------

    async def check(self, file_id: object, *, use_cache: bool = False) -> MembershipResult:
        """Resolve the CURRENT membership of ``file_id`` under the current epoch. Never raises."""
        return await self._check(file_id, use_cache, frozenset())

    async def _check(self, file_id: object, use_cache: bool, provisional: frozenset[str]) -> MembershipResult:
        """``provisional``: removed roots a page under preparation re-qualified. It is an EXPLICIT argument
        (never ambient state, so no other task or child task can inherit it) and a result computed under it
        is never cached."""
        if not is_valid_opaque_id(file_id):
            return MembershipResult(
                "-", MembershipVerdict.CHECK_FAILED, MembershipReason.INVALID_INPUT, self._key("-")
            )
        fid: str = file_id  # type: ignore[assignment]
        if use_cache:
            hit = self.cached(fid)
            if hit is not None:
                return hit
        epoch = self._epoch
        try:
            result, ancestors = await self._resolve(fid, epoch, provisional)
        except _CheckFailedError as exc:
            return MembershipResult(fid, MembershipVerdict.CHECK_FAILED, exc.code, self._key(fid))
        except Exception:  # noqa: BLE001 - port bug / hostile object: fail closed
            return MembershipResult(fid, MembershipVerdict.CHECK_FAILED, MembershipReason.TRANSIENT, self._key(fid))
        if epoch != self._epoch:  # revoked while resolving: nothing may be kept or disclosed
            return MembershipResult(
                fid, MembershipVerdict.CHECK_FAILED, MembershipReason.SCOPE_EPOCH_STALE, self._key(fid)
            )
        if not provisional:
            self._store(result, epoch, ancestors)
        return result

    async def authorize_disclosure(self, file_id: object) -> bool:
        """True only when a FRESH membership check (current metadata and parent chain, current epoch)
        says IN_SCOPE and a candidate is allowed. The cache may select candidates, never disclose: a file
        can be moved out of the corpus before its change notification is processed."""
        result = await self.check(file_id)
        return result.verdict is MembershipVerdict.IN_SCOPE and result.candidate_allowed

    async def recheck_all(self) -> tuple[MembershipResult, ...]:
        """Re-check every cached membership under the current epoch (after revoke / re-consent)."""
        results = []
        for fid in sorted(self._cache):
            results.append(await self.check(fid))
        return tuple(results)

    def _key(self, file_id: str) -> str:
        return stable_key(self._identity.namespace, file_id)

    def _result(
        self, file_id: str, verdict: MembershipVerdict, reason: MembershipReason, allowed: bool = False
    ) -> MembershipResult:
        return MembershipResult(file_id, verdict, reason, self._key(file_id), allowed)

    async def _fetch(self, file_id: str, epoch: int, budget: list[int]) -> FileMeta:
        if budget[0] <= 0:
            raise _BudgetError
        budget[0] -= 1
        self._lookups += 1
        try:
            meta = await self._port.get_file_meta(self._identity, epoch, file_id)
        except DrivePortError as exc:
            if exc.code is DriveErrorCode.NOT_FOUND:
                raise _NotFoundError from None
            raise _CheckFailedError(MembershipReason(exc.code.value)) from None
        if not is_sound_file_meta(meta) or meta.file_id != file_id:
            raise _CheckFailedError(MembershipReason.TRANSIENT)
        return meta

    async def _resolve(
        self, file_id: str, epoch: int, provisional: frozenset[str] = frozenset()
    ) -> tuple[MembershipResult, frozenset[str]]:
        budget = [MAX_LOOKUPS_PER_CHECK]
        none: frozenset[str] = frozenset()
        try:
            meta = await self._fetch(file_id, epoch, budget)
        except _NotFoundError:
            return self._result(file_id, MembershipVerdict.REMOVED, MembershipReason.NOT_FOUND), none
        except _BudgetError:
            return self._result(file_id, MembershipVerdict.NOT_IN_SCOPE, MembershipReason.CYCLE_OR_DEPTH), none
        if meta.trashed:
            return self._result(file_id, MembershipVerdict.REMOVED, MembershipReason.TRASHED), none
        if meta.drive_id != self._corpus.shared_drive_id:
            return self._result(file_id, MembershipVerdict.SCOPE_ESCAPE_DENIED, MembershipReason.DRIVE_MISMATCH), none
        if meta.shortcut_target is not None:
            return await self._resolve_shortcut(file_id, meta.shortcut_target, epoch, budget, provisional)
        outcome, visited = await self._walk(meta, epoch, budget, provisional)
        ancestors = frozenset(visited)
        if outcome == "IN":
            return self._result(file_id, MembershipVerdict.IN_SCOPE, MembershipReason.IN_CORPUS, True), ancestors
        if outcome == "OUT":
            return self._result(file_id, MembershipVerdict.SCOPE_ESCAPE_DENIED, MembershipReason.OUT_OF_CORPUS), ancestors
        if outcome == "FOREIGN":
            return self._result(file_id, MembershipVerdict.SCOPE_ESCAPE_DENIED, MembershipReason.DRIVE_MISMATCH), ancestors
        if outcome == "UNRESOLVED":
            return self._result(file_id, MembershipVerdict.NOT_IN_SCOPE, MembershipReason.PARENT_UNRESOLVED), ancestors
        return self._result(file_id, MembershipVerdict.NOT_IN_SCOPE, MembershipReason.CYCLE_OR_DEPTH), ancestors

    async def _resolve_shortcut(
        self, file_id: str, target: str, epoch: int, budget: list[int], provisional: frozenset[str] = frozenset()
    ) -> tuple[MembershipResult, frozenset[str]]:
        none: frozenset[str] = frozenset()
        try:
            target_meta = await self._fetch(target, epoch, budget)
        except _NotFoundError:
            return self._result(file_id, MembershipVerdict.NOT_IN_SCOPE, MembershipReason.SHORTCUT_TARGET_UNRESOLVED), none
        except _BudgetError:
            return self._result(file_id, MembershipVerdict.NOT_IN_SCOPE, MembershipReason.CYCLE_OR_DEPTH), none
        if target_meta.trashed or target_meta.drive_id != self._corpus.shared_drive_id:
            return self._result(file_id, MembershipVerdict.SCOPE_ESCAPE_DENIED, MembershipReason.SHORTCUT_TARGET_OUTSIDE), none
        outcome, walked = await self._walk(target_meta, epoch, budget, provisional)
        none = frozenset({target, *walked})  # re-check when the target or its chain changes
        if outcome == "IN":
            # a shortcut is never a membership proof nor evidence: the target is evidence under its own id
            return self._result(file_id, MembershipVerdict.NOT_IN_SCOPE, MembershipReason.SHORTCUT_NOT_EVIDENCE), none
        if outcome in ("OUT", "FOREIGN"):
            return self._result(file_id, MembershipVerdict.SCOPE_ESCAPE_DENIED, MembershipReason.SHORTCUT_TARGET_OUTSIDE), none
        return self._result(file_id, MembershipVerdict.NOT_IN_SCOPE, MembershipReason.SHORTCUT_TARGET_UNRESOLVED), none

    async def _walk(
        self, start: FileMeta, epoch: int, budget: list[int], provisional: frozenset[str] = frozenset()
    ) -> tuple[str, set[str]]:
        """Iterative bounded search of the parent graph. Returns (IN|OUT|UNRESOLVED|LIMIT, visited).

        ``visited`` holds every id the walk touched, INCLUDING the declared root it reached, so a change of
        that root invalidates the cached result. A shared ancestor (diamond) is simply already visited; only
        a parent that can reach its own child through the fetched graph is a cycle. A root the change feed
        reported removed/trashed is not a root any more (it is fetched like any other folder).
        """
        visited: set[str] = {start.file_id}
        # A removed root is live again only for the ``provisional`` set the calling prepare_page passes
        # explicitly (no ambient state) and, durably, after accept_page.
        live_roots = (self._roots - self._removed_roots) | (provisional & self._roots)
        if start.file_id in live_roots:
            # the caller already validated this fresh metadata (drive / trashed / shortcut); a root the feed
            # reported removed is reinstated by prepare_page only when this fresh read proves it live
            return "IN", visited
        graph: dict[str, tuple[str, ...]] = {start.file_id: start.parents}
        stack: list[tuple[FileMeta, int]] = [(start, 0)]
        unresolved = False
        limited = False
        foreign = False
        while stack:
            meta, depth = stack.pop()
            for parent in dict.fromkeys(meta.parents):
                if parent in live_roots and parent not in visited:
                    # A declared root is an ancestor like any other: it proves membership only when its
                    # CURRENT metadata is readable, same drive, not trashed and not a shortcut.
                    visited.add(parent)
                    try:
                        root_meta = await self._fetch(parent, epoch, budget)
                    except _NotFoundError:
                        unresolved = True
                        continue
                    except _BudgetError:
                        limited = True
                        continue
                    if root_meta.drive_id != self._corpus.shared_drive_id:
                        foreign = True
                    elif root_meta.trashed or root_meta.shortcut_target is not None:
                        unresolved = True
                    else:
                        return "IN", visited
                    continue
                if parent in visited:
                    if graph_reaches(graph, parent, meta.file_id):
                        limited = True  # real cycle
                    continue
                if depth + 1 >= MAX_CHAIN_DEPTH or budget[0] <= 0 or len(visited) >= MAX_ANCESTORS_PER_ENTRY:
                    limited = True
                    continue
                visited.add(parent)
                try:
                    parent_meta = await self._fetch(parent, epoch, budget)
                except _NotFoundError:
                    unresolved = True
                    continue
                except _BudgetError:
                    limited = True
                    continue
                if parent_meta.drive_id != self._corpus.shared_drive_id:
                    foreign = True  # an ancestor of another drive never links a membership chain
                    continue
                if parent_meta.trashed or parent_meta.shortcut_target is not None:
                    unresolved = True  # a trashed folder / a shortcut is never a link of a membership chain
                    continue
                graph[parent] = parent_meta.parents
                stack.append((parent_meta, depth + 1))
        if limited:  # a bound was hit: the picture is incomplete, which outranks "unresolved"
            return "LIMIT", visited
        if foreign:
            return "FOREIGN", visited
        if unresolved:
            return "UNRESOLVED", visited
        return "OUT", visited

    # --- page projection -------------------------------------------------------------------------

    async def prepare_page(self, page: object, stored_cursor: object) -> PagePreparation:
        """Project one page through ``DriveChangeProjector`` after re-resolving membership.

        Refuses the whole page (no batch, so no cursor to commit) when any membership cannot be
        verified, the epoch changed meanwhile, the page needs more lookups than ``MAX_LOOKUPS_PER_PAGE``,
        it carries an UNKNOWN change (needs a recorded gap / pause, never an advance), or the projector
        rejects the page. Never raises.
        """

        def refused(reason: PageReason, results: tuple[MembershipResult, ...] = ()) -> PagePreparation:
            return PagePreparation(PageStatus.REFUSED, reason, None, results)

        try:
            if type(page) is not DrivePage or not is_valid_opaque_id(stored_cursor):
                return refused(PageReason.INVALID_INPUT)
            self._pending_reinstate = None  # a newer preparation replaces any unaccepted one
            epoch = self._epoch
            for change in page.changes:
                if (
                    type(change) is not DriveChange
                    or type(change.kind) is not DriveChangeKind
                    or type(change.change_id) is not str
                    or type(change.file_id) is not str
                    or (change.drive_id is not None and type(change.drive_id) is not str)
                ):
                    return refused(PageReason.INVALID_INPUT)
            if len({c.change_id for c in page.changes}) != len(page.changes):
                return refused(PageReason.PAGE_PROJECTION_REFUSED)
            # Without a shared drive a change that names a drive is foreign: it is counted as denied and
            # never resolved, never tombstoned, never requalified (no foreign file id leaves this method).
            foreign = [
                c for c in page.changes
                if self._corpus.shared_drive_id is None
                and c.drive_id is not None
                and c.kind is not DriveChangeKind.UNKNOWN
            ]
            foreign_ids = {c.change_id for c in foreign}
            kept = tuple(c for c in page.changes if c.change_id not in foreign_ids)
            changed = [c for c in kept if self._in_drive(c)]
            for change in changed:
                # the changed file and (when it is a folder) all cached descendants are stale
                self.invalidate(change.file_id)
                if change.file_id in self._roots and change.kind is DriveChangeKind.REMOVED:
                    self._removed_roots.add(change.file_id)
            resolved: dict[str, MembershipResult] = {}
            reinstated: set[str] = set()
            spent_from = self._lookups
            for change in changed:
                if change.kind is DriveChangeKind.UPSERT and change.file_id not in resolved:
                    if self._lookups - spent_from >= MAX_LOOKUPS_PER_PAGE:
                        return refused(PageReason.PAGE_LOOKUP_BUDGET_EXCEEDED, tuple(resolved.values()))
                    # Only this explicit re-qualification (fresh metadata of the root itself) can make a removed
                    # root live, and only PROVISIONALLY (this task, this page) until accept_page.
                    requalifying = change.file_id in self._removed_roots
                    seen = reinstated | {change.file_id} if requalifying else reinstated
                    result = await self._check(change.file_id, False, frozenset(seen))
                    resolved[change.file_id] = result
                    if change.file_id in self._roots:
                        if result.verdict is MembershipVerdict.REMOVED:
                            self._removed_roots.add(change.file_id)
                        if requalifying and result.verdict is MembershipVerdict.IN_SCOPE:
                            reinstated.add(change.file_id)
            for change in changed:
                if change.file_id in self._roots:
                    self.invalidate(change.file_id)  # the root state may have changed while resolving
            results = tuple(resolved.values())
            if epoch != self._epoch:
                return refused(PageReason.EPOCH_CHANGED_DURING_PAGE, results)

            def allowed(file_id: str) -> bool | None:
                res = resolved.get(file_id)
                if res is None or res.verdict is MembershipVerdict.CHECK_FAILED:
                    return None
                return res.verdict is MembershipVerdict.IN_SCOPE and res.candidate_allowed

            projector = DriveChangeProjector(
                connection_id=self._identity.connection_id,
                drive_id=self._corpus.shared_drive_id,
                file_scope_allowed=allowed,
            )
            projected = DrivePage(
                page.requested_page_token, kept, page.next_page_token, page.new_start_page_token
            )
            try:
                batch = projector.prepare(projected, stored_cursor=stored_cursor)  # type: ignore[arg-type]
            except ValueError as exc:
                code = str(exc)
                if code == "FOLDER_MEMBERSHIP_UNVERIFIED":
                    return refused(PageReason.PAGE_MEMBERSHIP_UNVERIFIED, results)
                if code == "CURSOR_COMPARE_AND_SWAP_FAILED":
                    return refused(PageReason.PAGE_CURSOR_MISMATCH, results)
                return refused(PageReason.PAGE_PROJECTION_REFUSED, results)
            if batch.unknown_changes > 0 or batch.requires_gap_or_pause:
                return refused(PageReason.UNKNOWN_CHANGE_KIND, results)
            if foreign:
                batch = replace(batch, denied_changes=batch.denied_changes + len(foreign))
            removed = {fid for fid, r in resolved.items() if r.verdict is MembershipVerdict.REMOVED}
            if removed:
                tombs = tuple(
                    replace(t, reason="REMOVED") if t.file_id in removed and t.reason == "MEMBERSHIP_CHANGED" else t
                    for t in batch.tombstones
                )
                batch = replace(batch, tombstones=tombs)
            for fid in batch.requalify_folder_ids:
                self.invalidate(fid)
            prepared = PagePreparation(PageStatus.PREPARED, PageReason.PAGE_PREPARED, batch, results)
            self._pending_reinstate = (prepared, frozenset(reinstated), epoch, stored_cursor) if reinstated else None
            return prepared
        except Exception:  # noqa: BLE001 - public boundary: hostile input never raises
            return refused(PageReason.PAGE_PROJECTION_REFUSED)

    async def accept_page(self, preparation: object, receipt: object) -> bool:
        """Call after the durable cursor commit of ``preparation`` succeeded, passing the
        ``CursorCommitReceipt`` that ``DriveCursorStore.commit`` returned: only now do removed roots the page
        re-qualified become live again.

        Nothing happens (False) for a refused, unknown, replaced, already accepted or stale-epoch preparation,
        or unless the receipt was issued by a ``DriveCursorStore`` for exactly the cursor this preparation's
        batch may commit, under this checker's epoch. A value computed from the preparation is not a receipt."""
        pending = self._pending_reinstate
        if pending is None or pending[0] is not preparation or pending[2] != self._epoch:
            return False
        batch = getattr(preparation, "batch", None)
        store = self._commit_store
        if store is None or batch is None:
            return False
        try:
            token = batch.committable_cursor()
            fingerprint = DriveCorpus(self._corpus.shared_drive_id, tuple(self._corpus.root_folder_ids)).fingerprint
            expected = events_digest(page_events(self._identity, batch, pending[3]))
        except Exception:  # noqa: BLE001 - a batch/corpus that cannot be bound is not acceptable
            return False
        # the receipt must be this bound store's acknowledgment of exactly this page's transaction: this
        # connection and corpus, from the cursor the page was prepared against, to the cursor the batch may
        # commit, carrying exactly this page's events, and still the newest commit of that cursor
        if not await store.receipt_is_current(receipt, self._identity, fingerprint, pending[3], token,
                                              self._epoch, expected):
            return False
        if self._pending_reinstate is not pending or self._epoch != pending[2]:
            return False  # replaced, already accepted or revoked while the backend was being read
        self._pending_reinstate = None
        for fid in pending[1]:
            self._removed_roots.discard(fid)
            self.invalidate(fid)
        return True

    def _in_drive(self, change: DriveChange) -> bool:
        drive = self._corpus.shared_drive_id
        # a removal of unknown origin (no drive id) is treated as ours: its cache entry must be dropped
        # (the projector tombstones it); a provably foreign change stays out
        return (
            drive is None
            or change.drive_id == drive
            or (change.drive_id is None and change.kind is DriveChangeKind.REMOVED)
        )


class _NotFoundError(Exception):
    pass


class _BudgetError(Exception):
    pass
