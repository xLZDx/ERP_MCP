from copy import deepcopy

import pytest

from scripts.performance_benchmark import percentile, run
from scripts.validate_performance_evidence import validate


def test_benchmark_executes_production_executor_and_records_measurements():
    evidence = run()
    assert validate(evidence)["sizes"] == [30, 50, 100, 150]
    for row in evidence["results"]:
        assert row["sample_count"] == (row["registered_sources"] - 1) * row["repetitions"]
        assert 1 <= row["peak_concurrency"] <= row["concurrency"]
        assert row["python_peak_allocated_bytes"] > 0
        assert row["pool_wait_ms"] is None
    bad = deepcopy(evidence)
    bad["results"][0]["peak_concurrency"] = 999
    with pytest.raises(ValueError, match="concurrency"):
        validate(bad)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), True, -1])
def test_performance_validator_rejects_non_measurements(bad_value):
    with pytest.raises(ValueError):
        validate({"results": [{"registered_sources": 30, "elapsed_ms": bad_value,
                              "batch_p95_ms": 1, "throughput_sources_per_second": 1}]})


def test_nearest_rank_percentile_uses_tail_for_p99():
    assert percentile(list(range(1, 21)), 0.99) == 20
