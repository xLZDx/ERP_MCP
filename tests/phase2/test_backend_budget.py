"""Physical backend budget tests: isolated reference, not distributed lease."""
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from business_ai_gateway.phase2.backend_budget import (
    BackendCapacityError,
    BackendId,
    PhysicalBackendBudget,
)


def bid(raw: str) -> BackendId:
    return BackendId.normalize(raw)


def test_same_backend_shares_capacity():
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=2)
    with budget.reserve(trusted_backend_id=bid("physical-1")):
        with (pytest.raises(BackendCapacityError, match="CAPACITY"),
              budget.reserve(trusted_backend_id=bid("physical-1"))):
            pass
        with budget.reserve(trusted_backend_id=bid("physical-2")):
            assert budget.active_total == 2
    assert budget.active_total == 0


@pytest.mark.parametrize("alias", ["PHYSICAL-1", "  physical-1  ", "Physical-1\t", "PHYSICAL-1\n"])
def test_aliases_cannot_bypass_per_backend_limit(alias):
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=3)
    with budget.reserve(trusted_backend_id=bid("physical-1")):
        with (pytest.raises(BackendCapacityError, match="CAPACITY"),
              budget.reserve(trusted_backend_id=bid(alias))):
            pass
        assert budget.active_total == 1
    assert budget.active_total == 0


def test_backend_id_normalizes_strip_and_casefold():
    assert bid("  Straße-DB ").value == "strasse-db"
    assert bid("A") == bid(" a ")


@pytest.mark.parametrize("raw", ["", "   ", None, 7, b"x"])
def test_backend_id_normalize_rejects_blank_or_non_str(raw):
    with pytest.raises(BackendCapacityError, match="IDENTITY"):
        BackendId.normalize(raw)


@pytest.mark.parametrize("raw", [" physical-1", "PHYSICAL-1", "physical-1 "])
def test_backend_id_constructor_rejects_unnormalized_value(raw):
    with pytest.raises(BackendCapacityError, match="NOT_NORMALIZED"):
        BackendId(raw)


@pytest.mark.parametrize("raw", ["physical-1", " PHYSICAL-1 ", "", None])
def test_reserve_rejects_raw_values_that_are_not_backend_id(raw):
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=1)
    with (pytest.raises(BackendCapacityError, match="IDENTITY"),
          budget.reserve(trusted_backend_id=raw)):
        pytest.fail("reservation must not be granted for an unverified identity")
    assert budget.active_total == 0


def test_capacity_released_even_after_crash():
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=1)
    with (pytest.raises(RuntimeError, match="crash"),
          budget.reserve(trusted_backend_id=bid("physical-1"))):
        raise RuntimeError("crash")
    with budget.reserve(trusted_backend_id=bid("physical-1")):
        assert budget.active_total == 1
    assert budget.active_total == 0


def test_total_limit_denies_even_when_per_backend_has_room():
    budget = PhysicalBackendBudget(per_backend_limit=2, total_limit=3)
    with (budget.reserve(trusted_backend_id=bid("a")),
          budget.reserve(trusted_backend_id=bid("a")),
          budget.reserve(trusted_backend_id=bid("b"))):
        assert budget.active_total == 3
        # backend "c" has no use at all, only the total limit can deny it
        with (pytest.raises(BackendCapacityError, match="CAPACITY"),
              budget.reserve(trusted_backend_id=bid("c"))):
            pass
        assert budget.active_total == 3
    assert budget.active_total == 0


def test_invalid_configuration_denied():
    with pytest.raises(ValueError):
        PhysicalBackendBudget(per_backend_limit=2, total_limit=1)


class _YieldingCounters(defaultdict):
    """Widens the check-then-increment window: every read yields the GIL."""

    def get(self, key, default=None):
        value = super().get(key, default)
        time.sleep(0.001)
        return value

    def __getitem__(self, key):
        value = super().__getitem__(key)
        time.sleep(0.001)
        return value


def _instrument(budget: PhysicalBackendBudget) -> PhysicalBackendBudget:
    budget._active = _YieldingCounters(int)
    return budget


def _run_round(per_backend: int, total: int, workers: int) -> tuple[int, int, int]:
    """All workers try to reserve; every granted slot is HELD until all have decided.

    Returns (granted, denied, peak concurrently-held slots as seen by the budget).
    """
    budget = _instrument(PhysicalBackendBudget(per_backend_limit=per_backend, total_limit=total))
    start = Barrier(workers, timeout=10)
    decided = Barrier(workers, timeout=10)  # granted workers wait here INSIDE the reservation
    tally_lock = Lock()
    tally = {"granted": 0, "denied": 0, "peak": 0}

    def attempt(_: int) -> None:
        start.wait()
        try:
            with budget.reserve(trusted_backend_id=bid("physical-1")):
                with tally_lock:
                    tally["granted"] += 1
                decided.wait()
                with tally_lock:
                    tally["peak"] = max(tally["peak"], budget.active_total)
        except BackendCapacityError:
            with tally_lock:
                tally["denied"] += 1
            decided.wait()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(attempt, range(workers)))
    assert budget.active_total == 0
    return tally["granted"], tally["denied"], tally["peak"]


def test_concurrent_reservations_do_not_exceed_limit():
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # widen the check-then-increment race window
    try:
        for _ in range(10):
            granted, denied, peak = _run_round(per_backend=2, total=3, workers=12)
            assert granted == 2  # exactly the per-backend limit, never more
            assert denied == 10  # every other worker was denied
            assert peak <= 2
            assert granted + denied == 12
    finally:
        sys.setswitchinterval(old_interval)


def test_concurrent_total_limit_across_backends():
    budget = _instrument(PhysicalBackendBudget(per_backend_limit=2, total_limit=3))
    workers = 8
    start, decided = Barrier(workers, timeout=10), Barrier(workers, timeout=10)
    results: list[bool] = []
    lock = Lock()

    def attempt(i: int) -> None:
        start.wait()
        try:
            with budget.reserve(trusted_backend_id=bid("backend-" + str(i % 4))):
                with lock:
                    results.append(True)
                decided.wait()
        except BackendCapacityError:
            with lock:
                results.append(False)
            decided.wait()

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(attempt, range(workers)))
    finally:
        sys.setswitchinterval(old_interval)
    assert results.count(True) == 3
    assert results.count(False) == 5
    assert budget.active_total == 0

FULLWIDTH_DB = "\N{FULLWIDTH LATIN CAPITAL LETTER D}\N{FULLWIDTH LATIN CAPITAL LETTER B}-1"


def test_fullwidth_and_trailing_dot_variants_share_one_identity():
    assert bid(FULLWIDTH_DB).value == bid("db-1").value == bid("DB-1.").value
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=3)
    with (budget.reserve(trusted_backend_id=bid("db-1")),
          pytest.raises(BackendCapacityError, match="CAPACITY"),
          budget.reserve(trusted_backend_id=bid(FULLWIDTH_DB))):
        pass


@pytest.mark.parametrize(
    "raw",
    ["db\N{ZERO WIDTH SPACE}-1", "db-1\N{ZERO WIDTH JOINER}", "d b", "db/1",
     "db\N{CYRILLIC SMALL LETTER A}-1", "-db", "."],
)
def test_zero_width_and_unlisted_characters_are_rejected(raw):
    with pytest.raises(BackendCapacityError, match="UNVERIFIED_BACKEND_IDENTITY"):
        bid(raw)


def test_constructor_refuses_non_canonical_value():
    with pytest.raises(BackendCapacityError, match="NOT_NORMALIZED"):
        BackendId(FULLWIDTH_DB)
