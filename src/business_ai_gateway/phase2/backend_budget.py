"""Phase 2 bounded, physical-backend concurrency budget (single-process reference).

No I/O, credentials or dynamic endpoints. Production requires a distributed
atomic backend and authorization of physical backend identity.
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections import OrderedDict, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from uuid import UUID


class BackendCapacityError(RuntimeError):
    """Capacity or untrusted backend identity denies a request."""


class WorkClass(StrEnum):
    """Trusted admission class; CAPTURE/WRITER share the background fairness lane."""

    INTERACTIVE = "INTERACTIVE"
    BACKGROUND = "BACKGROUND"
    CAPTURE = "CAPTURE"
    WRITER = "WRITER"


_BACKEND_ID = re.compile(r"[a-z0-9](?:[a-z0-9._:-]{0,253}[a-z0-9])?")


def _canonical_backend(raw: str) -> str:
    """NFKC, casefold, strip whitespace and one trailing DNS dot."""
    value = unicodedata.normalize("NFKC", raw).strip().casefold()
    value = unicodedata.normalize("NFKC", value)  # casefold may re-compose
    return value.removesuffix(".")


@dataclass(frozen=True, slots=True)
class BackendId:
    """Opaque, normalized physical-backend identity (NFKC + casefold + strip, ASCII charset).

    Build with BackendId.normalize(raw). The constructor refuses a value that is
    not already normalized so aliases ("DB-1", " db-1 ") cannot create separate
    per-backend counters.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")
        if self.value != _canonical_backend(self.value):
            raise BackendCapacityError("BACKEND_ID_NOT_NORMALIZED")
        if not _BACKEND_ID.fullmatch(self.value):
            raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")

    @classmethod
    def normalize(cls, raw: object) -> BackendId:
        if not isinstance(raw, str) or not raw.strip():
            raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")
        return cls(_canonical_backend(raw))

    def __repr__(self) -> str:
        return "BackendId(" + repr(self.value) + ")"


class PhysicalBackendBudget:
    def __init__(self, *, per_backend_limit: int, total_limit: int,
                 max_waiters_per_backend: int = 1024, max_waiters_total: int = 4096,
                 waiter_ttl_seconds: float = 300.0) -> None:
        if (type(per_backend_limit) is not int or type(total_limit) is not int
                or not 1 <= per_backend_limit <= total_limit):
            raise ValueError("INVALID_BUDGET")
        if (type(max_waiters_per_backend) is not int or not 1 <= max_waiters_per_backend <= 100_000
                or type(max_waiters_total) is not int or not 1 <= max_waiters_total <= 100_000
                or isinstance(waiter_ttl_seconds, bool)
                or not isinstance(waiter_ttl_seconds, (int, float))
                or not 0 < waiter_ttl_seconds <= 86_400):
            raise ValueError("INVALID_WAITER_POLICY")
        self.per_backend_limit = per_backend_limit
        self.total_limit = total_limit
        self.max_waiters_per_backend = max_waiters_per_backend
        self.max_waiters_total = max_waiters_total
        self.waiter_ttl_seconds = float(waiter_ttl_seconds)
        self._lock = Lock()
        self._active: dict[str, int] = defaultdict(int)
        self._total = 0
        # Ordered by first deferral; retries retain their original place until expiry.
        self._waiters: dict[str, OrderedDict[str, tuple[bool, float]]] = {}
        self._last_granted_interactive: dict[str, bool] = {}

    def _expire_waiters(self, key: str, now: float) -> OrderedDict[str, tuple[bool, float]]:
        queue = self._waiters.get(key)
        if queue is None:
            return OrderedDict()
        expired = [identity for identity, (_, created) in queue.items()
                   if now - created >= self.waiter_ttl_seconds]
        for identity in expired:
            del queue[identity]
        if not queue:
            self._waiters.pop(key, None)
            self._last_granted_interactive.pop(key, None)
        return queue

    def _expire_all_waiters(self, now: float) -> None:
        """Prune every backend before enforcing the global waiter bound."""
        for key in tuple(self._waiters):
            self._expire_waiters(key, now)

    def cancel_waiter(self, *, trusted_backend_id: BackendId, waiter_id: object) -> None:
        """Remove a deferred caller that has been cancelled or reached a terminal state."""
        if type(trusted_backend_id) is not BackendId:
            raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")
        identity = self._identity(waiter_id)
        if identity is None:
            raise BackendCapacityError("BACKEND_WAITER_ID_INVALID")
        key = trusted_backend_id.value
        with self._lock:
            queue = self._expire_waiters(key, time.monotonic())
            queue.pop(identity, None)
            if not queue:
                self._waiters.pop(key, None)
                self._last_granted_interactive.pop(key, None)

    @staticmethod
    def _identity(value: object) -> str | None:
        if isinstance(value, UUID):
            return str(value)
        if (type(value) is str and value and value == value.strip()
                and len(value) <= 200 and value.isprintable()):
            return value
        if value is None:
            return None
        raise BackendCapacityError("BACKEND_WAITER_ID_INVALID")

    @staticmethod
    def _select_interactive(queue: OrderedDict[str, tuple[bool, float]],
                            last: bool | None) -> bool:
        classes = {interactive for interactive, _ in queue.values()}
        if len(classes) == 1:
            return next(iter(classes))
        # Initial tie goes to interactive; subsequent contested grants alternate.
        return not last if last is not None else True

    @contextmanager
    def reserve(self, *, trusted_backend_id: BackendId,
                work_class: WorkClass = WorkClass.BACKGROUND,
                waiter_id: object = None) -> Iterator[None]:
        if type(trusted_backend_id) is not BackendId:
            raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")
        if type(work_class) is not WorkClass:
            raise BackendCapacityError("BACKEND_WORK_CLASS_UNTRUSTED")
        identity = self._identity(waiter_id)
        interactive = work_class is WorkClass.INTERACTIVE
        key = trusted_backend_id.value
        with self._lock:
            now = time.monotonic()
            # The total waiter limit spans backend keys, so stale queues on idle
            # backends must be pruned before counting capacity for this request.
            self._expire_all_waiters(now)
            queue = self._waiters.get(key, OrderedDict())
            ticket = queue.get(identity) if identity is not None else None
            if ticket is not None and ticket[0] is not interactive:
                raise BackendCapacityError("BACKEND_WAITER_CLASS_CHANGED")
            has_capacity = (self._total < self.total_limit
                            and self._active.get(key, 0) < self.per_backend_limit)
            if queue:
                # A caller without a stable identity cannot cut in front of queued work.
                if identity is None:
                    raise BackendCapacityError("BACKEND_CAPACITY_EXCEEDED")
                if ticket is None:
                    if self._wait_queue_full(queue):
                        raise BackendCapacityError("BACKEND_WAIT_QUEUE_FULL")
                    queue[identity] = (interactive, time.monotonic())
                    self._waiters[key] = queue
                    raise BackendCapacityError("BACKEND_CAPACITY_EXCEEDED")
                turn = self._select_interactive(
                    queue, self._last_granted_interactive.get(key))
                first = next((waiter for waiter, (lane, _) in queue.items() if lane is turn), None)
                if not has_capacity or identity != first:
                    raise BackendCapacityError("BACKEND_CAPACITY_EXCEEDED")
                del queue[identity]
                self._last_granted_interactive[key] = interactive
            elif not has_capacity:
                if identity is not None:
                    if self._wait_queue_full(queue):
                        raise BackendCapacityError("BACKEND_WAIT_QUEUE_FULL")
                    queue[identity] = (interactive, time.monotonic())
                    self._waiters[key] = queue
                raise BackendCapacityError("BACKEND_CAPACITY_EXCEEDED")
            else:
                if queue:
                    self._last_granted_interactive[key] = interactive
            if not queue:
                self._waiters.pop(key, None)
                self._last_granted_interactive.pop(key, None)
            if not has_capacity:
                raise BackendCapacityError("BACKEND_CAPACITY_EXCEEDED")
            self._active[key] += 1
            self._total += 1
        try:
            yield
        finally:
            with self._lock:
                self._total -= 1
                self._active[key] -= 1
                if not self._active[key]:
                    del self._active[key]
                self._expire_waiters(key, time.monotonic())

    def _wait_queue_full(self, queue: OrderedDict[str, tuple[bool, float]]) -> bool:
        return (len(queue) >= self.max_waiters_per_backend
                or sum(len(waiters) for waiters in self._waiters.values()) >= self.max_waiters_total)

    @property
    def active_total(self) -> int:
        with self._lock:
            return self._total
