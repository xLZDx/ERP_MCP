"""Validators are not measurement evidence; the integration case executes real pool reads."""
import os
from copy import deepcopy

import pytest

from business_ai_gateway.db import Database
from scripts.performance_benchmark import SIZES
from scripts.postgres_pool_benchmark import measure, validate


def validation_fixture():
    return {"schema_version": 1, "mode": "measured_synthetic_postgres_pool",
            "real_1c_called": False, "capacity_decision": "EVIDENCE_ONLY_NOT_SIGNOFF",
            "results": [{"registered_sources": size, "repetitions": 1,
                         "pool_max_size": 10, "fanout_concurrency": 16,
                         "peak_acquired_connections": 10, "pool_size_after": 10,
                         "pool_idle_after": 10, "all_transactions_readonly": True,
                         "fanout_isolated": True, "denied_adapter_calls": 0,
                         "python_peak_allocated_bytes": 1000,
                         **{name: {"samples": 1 if name == "batch" else size - 1,
                                   "p50_ms": .1, "p95_ms": .2, "p99_ms": .3}
                            for name in ("pool_acquire", "readonly_transaction", "source_total", "batch")}}
                        for size in SIZES]}


def test_validates_fixture_without_claiming_it_is_measured():
    validate(validation_fixture())


@pytest.mark.parametrize("field,value", [
    ("peak_acquired_connections", 11), ("peak_acquired_connections", True),
    ("pool_max_size", 20), ("pool_idle_after", 1), ("all_transactions_readonly", False),
    ("pool_idle_after", True),
    ("fanout_isolated", False), ("denied_adapter_calls", 1),
    ("python_peak_allocated_bytes", True), ("repetitions", 0),
])
def test_rejects_invalid_pool_contract(field, value):
    evidence = validation_fixture()
    evidence["results"][0][field] = value
    with pytest.raises(ValueError):
        validate(evidence)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1, .01])
def test_rejects_non_measurements_or_reversed_percentiles(value):
    evidence = validation_fixture()
    evidence["results"][0]["pool_acquire"]["p99_ms"] = value
    with pytest.raises(ValueError):
        validate(evidence)


def test_rejects_fabricated_count_or_production_claim():
    for field, value in (("capacity_decision", "GO"), ("real_1c_called", True)):
        evidence = validation_fixture()
        evidence[field] = value
        with pytest.raises(ValueError):
            validate(evidence)
    evidence = validation_fixture()
    evidence["results"][0]["pool_acquire"]["samples"] = 999
    with pytest.raises(ValueError):
        validate(evidence)
    evidence = deepcopy(validation_fixture())
    evidence["results"].pop()
    with pytest.raises(ValueError):
        validate(evidence)


@pytest.mark.skipif(not os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL"), reason="requires disposable PostgreSQL")
async def test_actual_runtime_pool_has_readonly_isolated_measured_samples():
    database = Database(os.environ["BAG_PRIVILEGE_TEST_DATABASE_URL"])
    await database.start()
    try:
        evidence = validation_fixture()
        evidence["results"] = [await measure(database, size, repetitions=1) for size in SIZES]
        validate(evidence)
    finally:
        await database.close()
