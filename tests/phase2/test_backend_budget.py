"""Physical backend budget tests: isolated reference, not distributed lease."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from business_ai_gateway.phase2.backend_budget import (
    BackendCapacityError,
    PhysicalBackendBudget,
)


def test_aliases_share_same_backend_capacity():
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=2)
    with budget.reserve(trusted_backend_id="physical-1"):
        with (pytest.raises(BackendCapacityError, match="CAPACITY"),
              budget.reserve(trusted_backend_id="physical-1")):
            pass
        with budget.reserve(trusted_backend_id="physical-2"):
            assert budget.active_total == 2
    assert budget.active_total == 0


def test_capacity_released_even_after_crash():
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=1)
    with (pytest.raises(RuntimeError, match="crash"),
          budget.reserve(trusted_backend_id="physical-1")):
        raise RuntimeError("crash")
    with budget.reserve(trusted_backend_id="physical-1"):
        assert budget.active_total == 1
    assert budget.active_total == 0


def test_unknown_backend_denied():
    budget = PhysicalBackendBudget(per_backend_limit=1, total_limit=1)
    with (pytest.raises(BackendCapacityError, match="IDENTITY"),
          budget.reserve(trusted_backend_id="")):
        pass


def test_invalid_configuration_denied():
    with pytest.raises(ValueError):
        PhysicalBackendBudget(per_backend_limit=2, total_limit=1)


def test_concurrent_reservations_do_not_exceed_limit():
    budget = PhysicalBackendBudget(per_backend_limit=2, total_limit=2)
    barrier = Barrier(12)

    def attempt(_: int) -> bool:
        barrier.wait()
        try:
            with budget.reserve(trusted_backend_id="physical-1"):
                return True
        except BackendCapacityError:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        result = list(pool.map(attempt, range(12)))
    assert len(result) == 12
    assert budget.active_total == 0
