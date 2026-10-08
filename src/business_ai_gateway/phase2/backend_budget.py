"""Phase 2 bounded, physical-backend concurrency budget (single-process reference).

No I/O, credentials or dynamic endpoints. Production requires a distributed
atomic backend and authorization of physical backend identity.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock


class BackendCapacityError(RuntimeError):
    """Capacity or untrusted backend identity denies a request."""


class PhysicalBackendBudget:
    def __init__(self, *, per_backend_limit: int, total_limit: int) -> None:
        if not 1 <= per_backend_limit <= total_limit:
            raise ValueError("INVALID_BUDGET")
        self.per_backend_limit = per_backend_limit
        self.total_limit = total_limit
        self._lock = Lock()
        self._active: dict[str, int] = defaultdict(int)
        self._total = 0

    @contextmanager
    def reserve(self, *, trusted_backend_id: str) -> Iterator[None]:
        if not isinstance(trusted_backend_id, str) or not trusted_backend_id.strip():
            raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")
        with self._lock:
            if (self._total >= self.total_limit
                    or self._active[trusted_backend_id] >= self.per_backend_limit):
                raise BackendCapacityError("BACKEND_CAPACITY_EXCEEDED")
            self._active[trusted_backend_id] += 1
            self._total += 1
        try:
            yield
        finally:
            with self._lock:
                self._total -= 1
                self._active[trusted_backend_id] -= 1
                if not self._active[trusted_backend_id]:
                    del self._active[trusted_backend_id]

    @property
    def active_total(self) -> int:
        with self._lock:
            return self._total
