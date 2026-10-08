"""Phase 2 bounded, physical-backend concurrency budget (single-process reference).

No I/O, credentials or dynamic endpoints. Production requires a distributed
atomic backend and authorization of physical backend identity.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock


class BackendCapacityError(RuntimeError):
    """Capacity or untrusted backend identity denies a request."""


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
    def __init__(self, *, per_backend_limit: int, total_limit: int) -> None:
        if not 1 <= per_backend_limit <= total_limit:
            raise ValueError("INVALID_BUDGET")
        self.per_backend_limit = per_backend_limit
        self.total_limit = total_limit
        self._lock = Lock()
        self._active: dict[str, int] = defaultdict(int)
        self._total = 0

    @contextmanager
    def reserve(self, *, trusted_backend_id: BackendId) -> Iterator[None]:
        if type(trusted_backend_id) is not BackendId:
            raise BackendCapacityError("UNVERIFIED_BACKEND_IDENTITY")
        key = trusted_backend_id.value
        with self._lock:
            if (self._total >= self.total_limit
                    or self._active.get(key, 0) >= self.per_backend_limit):
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

    @property
    def active_total(self) -> int:
        with self._lock:
            return self._total
