"""Single-threaded COM lane for the private licensed writer process.

This module owns only COM apartment and local queue lifetime. It does not implement
the S12 writer port, authorize a call, sign receipts, or prove physical completion.
Those responsibilities stay with the injected writer adapter and durable S12/S13
evidence path.
"""

from __future__ import annotations

import asyncio
import math
import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")
_STOP = object()
_MAX_RESULT_NODES = 16_384
_MAX_RESULT_TUPLE_ITEMS = 4_096
_MAX_RESULT_DEPTH = 16
_MAX_RESULT_TEXT_CHARS = 262_144
_MAX_RESULT_BYTES = 1_048_576
_MAX_RESULT_INT_BITS = 8_192
_MAX_RESULT_TOTAL_BYTES = 2_097_152
_SAFE_STARTUP_ERROR_CODES = frozenset({
    "COM_LANE_ARCHITECTURE_UNSUPPORTED",
    "COM_ACTIVATION_FAILED",
    "COM_CONNECTION_CONFIGURATION_FAILED",
    "COM_CONNECT_FAILED",
    "COM_BASE_FINGERPRINT_UNAVAILABLE",
    "COM_BASE_FINGERPRINT_MISMATCH",
    "COM_BASE_USER_UNAVAILABLE",
    "COM_BASE_USER_MISMATCH",
})


def _is_plain_result(value: Any) -> bool:
    pending = [(value, 0)]
    visited = 0
    total_bytes = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if visited > _MAX_RESULT_NODES:
            return False
        if type(item) in (type(None), bool):
            total_bytes += 1
            if total_bytes > _MAX_RESULT_TOTAL_BYTES:
                return False
            continue
        if type(item) is float and math.isfinite(item):
            total_bytes += 8
            if total_bytes > _MAX_RESULT_TOTAL_BYTES:
                return False
            continue
        if type(item) is int and item.bit_length() <= _MAX_RESULT_INT_BITS:
            total_bytes += max(1, (item.bit_length() + 7) // 8)
            if total_bytes > _MAX_RESULT_TOTAL_BYTES:
                return False
            continue
        if type(item) is str and len(item) <= _MAX_RESULT_TEXT_CHARS:
            total_bytes += len(item) * 4  # Upper bound; avoid encoding oversized totals.
            if total_bytes > _MAX_RESULT_TOTAL_BYTES:
                return False
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return False
            continue
        if type(item) is bytes and len(item) <= _MAX_RESULT_BYTES:
            total_bytes += len(item)
            if total_bytes > _MAX_RESULT_TOTAL_BYTES:
                return False
            continue
        if (type(item) is tuple and depth < _MAX_RESULT_DEPTH
                and len(item) <= _MAX_RESULT_TUPLE_ITEMS):
            pending.extend((child, depth + 1) for child in item)
            continue
        return False
    if total_bytes > _MAX_RESULT_TOTAL_BYTES:
        return False
    return True


class ComLaneState(StrEnum):
    NEW = "NEW"
    STARTING = "STARTING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class ComLaneError(RuntimeError):
    """Stable COM-lane error; never includes connector or business data."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        self.code = code
        self.outcome_unknown = outcome_unknown
        super().__init__(code)


@dataclass(frozen=True)
class _Invocation(Generic[T]):
    operation: Callable[[Any], T]
    result: Future[T]


class ComStaLane:
    """Own one COM connection on one STA thread and admit at most one call at a time.

    ``initialize_sta`` and ``uninitialize_sta`` must initialize and release the
    Windows STA apartment on the calling thread. ``connect`` is called
    on that same thread and must return a connection whose methods remain confined
    to it. Operations must return exact primitive values or bounded tuples of them
    (at most 16,384 visited nodes, 16 tuple levels, 4,096 items per tuple, a 2 MiB
    cumulative scalar budget, and bounded text, bytes and integer sizes), never COM
    proxies or custom objects.

    Cancellation of an awaiting invocation does not cancel an accepted COM call.
    Cancellation during startup requests worker cleanup before propagating. Calling
    ``close_after_drain`` closes local admission, then waits for accepted work and
    connection cleanup. This is a local queue barrier only; a trusted writer
    acknowledgement still requires the separate process/key attestation contract.
    """

    __slots__ = (
        "_connect", "_disconnect", "_initialize_sta", "_uninitialize_sta", "_lock",
        "_queue", "_state", "_in_flight", "_ready", "_closed", "_thread",
    )

    _CONFIGURATION_FIELDS = frozenset({
        "_connect", "_disconnect", "_initialize_sta", "_uninitialize_sta",
        "_lock", "_queue", "_ready", "_closed",
    })
    _LIFECYCLE_FIELDS = frozenset({"_state", "_in_flight", "_thread"})
    _STATE_TRANSITIONS = frozenset({
        (ComLaneState.NEW, ComLaneState.STARTING),
        (ComLaneState.NEW, ComLaneState.CLOSED),
        (ComLaneState.STARTING, ComLaneState.OPEN),
        (ComLaneState.STARTING, ComLaneState.CLOSING),
        (ComLaneState.STARTING, ComLaneState.FAILED),
        (ComLaneState.OPEN, ComLaneState.CLOSING),
        (ComLaneState.OPEN, ComLaneState.FAILED),
        (ComLaneState.CLOSING, ComLaneState.CLOSED),
        (ComLaneState.CLOSING, ComLaneState.FAILED),
    })

    def __setattr__(self, name: str, value: object) -> None:
        if (name == "_CONFIGURATION_FIELDS"
                or name == "_LIFECYCLE_FIELDS"
                or (name in type(self)._CONFIGURATION_FIELDS and hasattr(self, name))
                or (name in type(self)._LIFECYCLE_FIELDS and hasattr(self, name))):
            raise AttributeError("COM_LANE_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if (name in (type(self)._CONFIGURATION_FIELDS | type(self)._LIFECYCLE_FIELDS)
                or name in ("_CONFIGURATION_FIELDS", "_LIFECYCLE_FIELDS")):
            raise AttributeError("COM_LANE_CONFIGURATION_IMMUTABLE")
        object.__delattr__(self, name)

    def _set_lifecycle_field(self, name: str, value: object) -> None:
        """Update worker-owned state without exposing ordinary attribute mutation."""
        if name not in type(self)._LIFECYCLE_FIELDS:
            raise AttributeError("COM_LANE_CONFIGURATION_IMMUTABLE")
        current = getattr(self, name)
        if name == "_state":
            if (type(value) is not ComLaneState
                    or (current is not value
                        and (current, value) not in type(self)._STATE_TRANSITIONS)):
                raise RuntimeError("COM_LANE_LIFECYCLE_TRANSITION_INVALID")
        elif name == "_in_flight":
            if type(current) is not bool or type(value) is not bool or current is value:
                raise RuntimeError("COM_LANE_LIFECYCLE_TRANSITION_INVALID")
        elif (current is not None or type(value) is not threading.Thread):
            raise RuntimeError("COM_LANE_LIFECYCLE_TRANSITION_INVALID")
        object.__setattr__(self, name, value)

    def __init__(self, *, connect: Callable[[], Any], disconnect: Callable[[Any], None],
                 initialize_sta: Callable[[], None],
                 uninitialize_sta: Callable[[], None]) -> None:
        if any(not callable(item) for item in
               (connect, disconnect, initialize_sta, uninitialize_sta)):
            raise ValueError("COM_LANE_CONFIGURATION_INVALID")
        self._connect = connect
        self._disconnect = disconnect
        self._initialize_sta = initialize_sta
        self._uninitialize_sta = uninitialize_sta
        self._lock = threading.Lock()
        # The queue is unbounded internally so shutdown can always enqueue its
        # sentinel without creating a helper thread. Public admission remains
        # bounded to one accepted invocation by _in_flight under _lock.
        self._queue: queue.Queue[_Invocation[Any] | object] = queue.Queue()
        self._state = ComLaneState.NEW
        self._in_flight = False
        self._ready: Future[None] = Future()
        self._closed: Future[None] = Future()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> ComLaneState:
        with self._lock:
            return self._state

    async def start(self) -> None:
        with self._lock:
            if self._state is ComLaneState.NEW:
                self._set_lifecycle_field("_state", ComLaneState.STARTING)
                self._set_lifecycle_field("_thread", threading.Thread(
                    target=self._run,
                    name="erp-mcp-private-com-sta",
                    daemon=False,
                ))
                try:
                    self._thread.start()
                except Exception:
                    self._set_lifecycle_field("_state", ComLaneState.FAILED)
                    self._ready.set_exception(ComLaneError("COM_LANE_START_FAILED"))
                    self._closed.set_exception(ComLaneError("COM_LANE_START_FAILED"))
                    raise ComLaneError("COM_LANE_START_FAILED") from None
            elif self._state not in (ComLaneState.STARTING, ComLaneState.OPEN):
                raise ComLaneError("COM_LANE_NOT_OPEN")
            ready = self._ready
        try:
            await asyncio.shield(asyncio.wrap_future(ready))
        except asyncio.CancelledError:
            # Do not leave a non-daemon COM worker alive after its owner abandons
            # startup. Cleanup continues on the worker thread; cancellation is kept.
            self._request_close()
            raise
        except ComLaneError:
            raise
        except Exception:
            raise ComLaneError("COM_LANE_START_FAILED") from None

    async def invoke(self, operation: Callable[[Any], T]) -> T:
        if not callable(operation):
            raise ComLaneError("COM_OPERATION_INVALID")
        result: Future[T] = Future()
        with self._lock:
            if self._state is not ComLaneState.OPEN:
                raise ComLaneError("COM_LANE_NOT_OPEN")
            if self._in_flight:
                raise ComLaneError("COM_LANE_BUSY")
            self._set_lifecycle_field("_in_flight", True)
            try:
                self._queue.put_nowait(_Invocation(operation, result))
            except queue.Full:
                self._set_lifecycle_field("_in_flight", False)
                raise ComLaneError("COM_LANE_BUSY") from None
        try:
            return await asyncio.shield(asyncio.wrap_future(result))
        except asyncio.CancelledError:
            raise
        except ComLaneError:
            raise
        except Exception:
            raise ComLaneError("COM_OUTCOME_UNKNOWN", outcome_unknown=True) from None

    async def close_after_drain(self) -> None:
        """Reject new work and wait until the connection and apartment are released."""
        closed = self._request_close()
        try:
            await asyncio.shield(asyncio.wrap_future(closed))
        except ComLaneError:
            raise
        except Exception:
            raise ComLaneError("COM_LANE_CLOSE_FAILED", outcome_unknown=True) from None

    def _request_close(self) -> Future[None]:
        """Synchronously close admission and enqueue cleanup behind accepted work."""
        with self._lock:
            if self._state is ComLaneState.NEW:
                self._set_lifecycle_field("_state", ComLaneState.CLOSED)
                self._ready.set_exception(ComLaneError("COM_LANE_CLOSED"))
                self._closed.set_result(None)
            elif self._state in (ComLaneState.STARTING, ComLaneState.OPEN):
                self._set_lifecycle_field("_state", ComLaneState.CLOSING)
                self._queue.put_nowait(_STOP)
            return self._closed

    def _run(self) -> None:
        session: Any = None
        apartment_initialized = False
        lane_failed = False
        cleanup_failed = False
        try:
            self._initialize_sta()
            apartment_initialized = True
            session = self._connect()
            if session is None:
                raise RuntimeError
            with self._lock:
                if self._state is ComLaneState.STARTING:
                    self._set_lifecycle_field("_state", ComLaneState.OPEN)
                    self._ready.set_result(None)
                elif self._state is ComLaneState.CLOSING:
                    self._ready.set_exception(ComLaneError("COM_LANE_CLOSED"))
        except ComLaneError as exc:
            lane_failed = True
            # Preserve only the small, fixed startup taxonomy. A dependency may
            # raise ComLaneError with arbitrary text, which must never reach the
            # service boundary.
            code = (
                exc.code if type(exc.code) is str and exc.code in _SAFE_STARTUP_ERROR_CODES
                else "COM_LANE_START_FAILED"
            )
            with self._lock:
                self._set_lifecycle_field("_state", ComLaneState.FAILED)
                if not self._ready.done():
                    self._ready.set_exception(ComLaneError(code))
        except BaseException:
            lane_failed = True
            with self._lock:
                self._set_lifecycle_field("_state", ComLaneState.FAILED)
                if not self._ready.done():
                    self._ready.set_exception(ComLaneError("COM_LANE_START_FAILED"))

        if not lane_failed:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    break
                assert isinstance(item, _Invocation)
                try:
                    value = item.operation(session)
                    if not _is_plain_result(value):
                        raise RuntimeError
                except BaseException:
                    # Even process-control exceptions in an injected worker callback must
                    # settle the accepted call as unknown and continue through STA cleanup.
                    lane_failed = True
                    if not item.result.done():
                        item.result.set_exception(
                            ComLaneError("COM_OUTCOME_UNKNOWN", outcome_unknown=True)
                        )
                    with self._lock:
                        self._set_lifecycle_field("_state", ComLaneState.FAILED)
                    break
                else:
                    if not item.result.done():
                        item.result.set_result(value)
                finally:
                    with self._lock:
                        self._set_lifecycle_field("_in_flight", False)

        try:
            if session is not None:
                self._disconnect(session)
        except BaseException:
            cleanup_failed = True
        finally:
            if apartment_initialized:
                try:
                    self._uninitialize_sta()
                except BaseException:
                    cleanup_failed = True

        with self._lock:
            if cleanup_failed:
                self._set_lifecycle_field("_state", ComLaneState.FAILED)
            elif not lane_failed:
                self._set_lifecycle_field("_state", ComLaneState.CLOSED)
            if not self._ready.done():
                self._ready.set_exception(ComLaneError("COM_LANE_START_FAILED"))
            if not self._closed.done():
                if cleanup_failed:
                    self._closed.set_exception(ComLaneError("COM_LANE_CLOSE_FAILED"))
                else:
                    self._closed.set_result(None)
