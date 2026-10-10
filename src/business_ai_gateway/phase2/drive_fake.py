"""Phase 2 (S7/E1) scripted in-memory fake of the read-only ``DrivePort`` (see drive_port.py).

Test support only: no network, no clock, no randomness, no write method. Everything the fake returns
was scripted by the test through the ``script_*`` / ``set_*`` / ``force_*`` methods.

Order of work inside every port call (documented because tests rely on it):
1. the method name is appended to the call log and the counters move (even when the call fails);
2. arguments are validated: a non-``DrivePortIdentity`` identity -> ``AUTH_REQUIRED``, a bad scope
   epoch type -> ``SCOPE_EPOCH_STALE``, a bad token / file id -> ``NOT_FOUND`` (never any other exception);
3. a forced error for this method (see ``force_error``) is raised;
4. the scope epoch is compared with the fake's *current* epoch (``set_scope_epoch``): a different
   value -> ``SCOPE_EPOCH_STALE``;
5. the scripted behaviour runs; 6. in ``finally``, hooks scheduled with ``run_after_calls(n, hook)`` fire
   once when the total call count reaches ``n`` (so they influence the *next* calls).

Every raised error is a ``DrivePortError`` with a fixed code; scripted provider text is dropped.
Scripts are global to the fake instance: use one instance per namespace to model several namespaces.
"""
from __future__ import annotations

from collections.abc import Callable

from .drive_changes import DriveChange
from .drive_port import (
    ChangesPage,
    DriveErrorCode,
    DrivePortError,
    DrivePortIdentity,
    FileMeta,
    RevisionMeta,
    StartToken,
    is_valid_opaque_id,
    is_valid_scope_epoch,
)

__all__ = ["METHODS", "FakeDrivePort"]

METHODS = ("get_start_page_token", "list_changes", "get_file_meta", "list_revisions")


class FakeDrivePort:
    def __init__(self, *, scope_epoch: int = 0, start_page_token: str = "START-1") -> None:
        if not is_valid_scope_epoch(scope_epoch):
            raise ValueError("SCOPE_EPOCH_INVALID")
        self._epoch = scope_epoch
        self._start = StartToken(start_page_token)
        self._pages: dict[str, ChangesPage] = {}
        self._files: dict[str, FileMeta] = {}
        self._revisions: dict[str, tuple[RevisionMeta, ...]] = {}
        self._new_children: set[str] = set()
        self._forced: list[dict] = []
        self._hooks: list[tuple[int, Callable[[FakeDrivePort], None]]] = []
        self._log: list[str] = []
        self._counts: dict[str, int] = dict.fromkeys(METHODS, 0)
        self.hide_new_children = False
        self.history_forbidden = False

    # --- scripting ------------------------------------------------------------------------------

    def set_scope_epoch(self, scope_epoch: int) -> None:
        """Change the fake's current epoch; calls made with another epoch raise SCOPE_EPOCH_STALE."""
        if not is_valid_scope_epoch(scope_epoch):
            raise ValueError("SCOPE_EPOCH_INVALID")
        self._epoch = scope_epoch

    @property
    def scope_epoch(self) -> int:
        return self._epoch

    def script_start_token(self, token: str) -> None:
        self._start = StartToken(token)

    def script_page(
        self,
        page_token: str,
        changes: tuple[DriveChange, ...] = (),
        *,
        next_page_token: str | None = None,
        new_start_page_token: str | None = None,
    ) -> None:
        """Script the page returned for ``page_token`` (replaces an earlier script for it)."""
        if not is_valid_opaque_id(page_token):
            raise ValueError("DRIVE_PAGE_TOKEN_INVALID")
        self._pages[page_token] = ChangesPage(changes, next_page_token, new_start_page_token)

    def set_file(self, meta: FileMeta, *, new_child: bool = False) -> None:
        """Script file metadata. ``new_child=True`` marks a file created after the grant (see hide_new_children)."""
        if type(meta) is not FileMeta:
            raise ValueError("DRIVE_FILE_META_INVALID")
        self._files[meta.file_id] = meta
        if new_child:
            self._new_children.add(meta.file_id)
        else:
            self._new_children.discard(meta.file_id)

    def remove_file(self, file_id: str) -> None:
        self._files.pop(file_id, None)
        self._new_children.discard(file_id)

    def set_revisions(self, file_id: str, revisions: tuple[RevisionMeta, ...]) -> None:
        if (
            not is_valid_opaque_id(file_id)
            or type(revisions) is not tuple
            or any(type(r) is not RevisionMeta for r in revisions)
        ):
            raise ValueError("DRIVE_REVISION_INVALID")
        self._revisions[file_id] = revisions

    def force_error(
        self,
        method: str,
        code: DriveErrorCode,
        *,
        times: int | None = 1,
        after: int = 0,
    ) -> None:
        """Make ``method`` raise ``DrivePortError(code)``: skip the first ``after`` calls of that method,
        then fail ``times`` calls (``None`` = every later call)."""
        if (
            method not in METHODS
            or type(code) is not DriveErrorCode
            or (times is not None and (type(times) is not int or times < 1))
            or type(after) is not int
            or after < 0
        ):
            raise ValueError("FORCED_ERROR_INVALID")
        self._forced.append({"method": method, "code": code, "times": times, "skip": after})

    def force_provider_response(
        self, method: str, status: int, body_text: str = "", *, times: int | None = 1, after: int = 0
    ) -> None:
        """Model a provider HTTP failure. Only the mapped fixed code survives; ``body_text`` is discarded.

        400/401 with ``invalid_grant`` in the text -> INVALID_GRANT, 401 -> AUTH_REQUIRED, 403 ->
        FORBIDDEN_HISTORY, 404 -> NOT_FOUND, 429 -> RATE_LIMITED, anything else -> TRANSIENT.
        """
        if type(status) is not int or type(body_text) is not str:
            raise ValueError("FORCED_ERROR_INVALID")
        grant = "invalid_grant" in body_text
        if status in (400, 401) and grant:
            code = DriveErrorCode.INVALID_GRANT
        elif status == 401:
            code = DriveErrorCode.AUTH_REQUIRED
        elif status == 403:
            code = DriveErrorCode.FORBIDDEN_HISTORY
        elif status == 404:
            code = DriveErrorCode.NOT_FOUND
        elif status == 429:
            code = DriveErrorCode.RATE_LIMITED
        else:
            code = DriveErrorCode.TRANSIENT
        self.force_error(method, code, times=times, after=after)

    def clear_forced_errors(self) -> None:
        self._forced.clear()

    def run_after_calls(self, n: int, hook: Callable[[FakeDrivePort], None]) -> None:
        """Invoke ``hook(fake)`` once, right after the call that makes the total call count equal ``n``
        (use it to script changes between calls)."""
        if type(n) is not int or n < 1 or not callable(hook):
            raise ValueError("HOOK_INVALID")
        self._hooks.append((n, hook))

    # --- observation ----------------------------------------------------------------------------

    @property
    def call_log(self) -> tuple[str, ...]:
        """Method names in call order (failed calls included)."""
        return tuple(self._log)

    @property
    def call_count(self) -> int:
        return len(self._log)

    def count(self, method: str) -> int:
        return self._counts.get(method, 0)

    # --- DrivePort ------------------------------------------------------------------------------

    async def get_start_page_token(self, identity: DrivePortIdentity, scope_epoch: int) -> StartToken:
        with self._call("get_start_page_token", identity, scope_epoch):
            return self._start

    async def list_changes(
        self, identity: DrivePortIdentity, scope_epoch: int, page_token: str
    ) -> ChangesPage:
        with self._call("list_changes", identity, scope_epoch):
            if not is_valid_opaque_id(page_token) or page_token not in self._pages:
                raise DrivePortError(DriveErrorCode.NOT_FOUND)
            page = self._pages[page_token]
            if self.hide_new_children:
                visible = tuple(c for c in page.changes if c.file_id not in self._new_children)
                if len(visible) != len(page.changes):
                    return ChangesPage(visible, page.next_page_token, page.new_start_page_token)
            return page

    async def get_file_meta(
        self, identity: DrivePortIdentity, scope_epoch: int, file_id: str
    ) -> FileMeta:
        with self._call("get_file_meta", identity, scope_epoch):
            if not is_valid_opaque_id(file_id) or file_id not in self._files:
                raise DrivePortError(DriveErrorCode.NOT_FOUND)
            if self.hide_new_children and file_id in self._new_children:
                raise DrivePortError(DriveErrorCode.NOT_FOUND)
            return self._files[file_id]

    async def list_revisions(
        self, identity: DrivePortIdentity, scope_epoch: int, file_id: str
    ) -> tuple[RevisionMeta, ...]:
        with self._call("list_revisions", identity, scope_epoch):
            if not is_valid_opaque_id(file_id) or file_id not in self._files:
                raise DrivePortError(DriveErrorCode.NOT_FOUND)
            if self.hide_new_children and file_id in self._new_children:
                raise DrivePortError(DriveErrorCode.NOT_FOUND)
            if self.history_forbidden:
                raise DrivePortError(DriveErrorCode.FORBIDDEN_HISTORY)
            return self._revisions.get(file_id, ())

    # --- internals ------------------------------------------------------------------------------

    def _call(self, method: str, identity: object, scope_epoch: object) -> _CallGuard:
        return _CallGuard(self, method, identity, scope_epoch)

    def _enter(self, method: str, identity: object, scope_epoch: object) -> None:
        self._log.append(method)
        self._counts[method] += 1
        if type(identity) is not DrivePortIdentity:
            raise DrivePortError(DriveErrorCode.AUTH_REQUIRED)
        if not is_valid_scope_epoch(scope_epoch):
            raise DrivePortError(DriveErrorCode.SCOPE_EPOCH_STALE)
        for entry in self._forced:
            if entry["method"] != method:
                continue
            if entry["skip"] > 0:
                entry["skip"] -= 1
                continue
            if entry["times"] is None:
                raise DrivePortError(entry["code"])
            if entry["times"] > 0:
                entry["times"] -= 1
                raise DrivePortError(entry["code"])
        if scope_epoch != self._epoch:
            raise DrivePortError(DriveErrorCode.SCOPE_EPOCH_STALE)

    def _exit(self) -> None:
        total = len(self._log)
        due = [h for h in self._hooks if h[0] == total]
        self._hooks = [h for h in self._hooks if h[0] != total]
        for _, hook in due:
            hook(self)


class _CallGuard:
    """Context manager: runs the entry checks, and the post-call hooks even when the call failed."""

    __slots__ = ("_fake",)

    def __init__(self, fake: FakeDrivePort, method: str, identity: object, scope_epoch: object):
        self._fake = fake
        try:
            fake._enter(method, identity, scope_epoch)
        except BaseException:
            fake._exit()
            raise

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        self._fake._exit()
