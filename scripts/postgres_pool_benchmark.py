"""Measured synthetic fan-out against the actual runtime PostgreSQL pool; never capacity signoff."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
import tracemalloc
import uuid
from pathlib import Path

from business_ai_gateway.db import Database
from business_ai_gateway.fanout import FanoutExecutor
from scripts.performance_benchmark import SIZES, percentile
from scripts.postgres_restore_drill import new_postgres


def distribution(samples: list[float]) -> dict:
    return {"samples": len(samples), "p50_ms": percentile(samples, .50),
            "p95_ms": percentile(samples, .95), "p99_ms": percentile(samples, .99)}


def validate(evidence: dict) -> None:
    if (type(evidence.get("schema_version")) is not int or evidence.get("schema_version") != 1
            or evidence.get("mode") != "measured_synthetic_postgres_pool"
            or evidence.get("real_1c_called") is not False
            or evidence.get("capacity_decision") != "EVIDENCE_ONLY_NOT_SIGNOFF"):
        raise ValueError("POOL_EVIDENCE_SCHEMA_INVALID")
    rows = evidence.get("results")
    if not isinstance(rows, list) or [row.get("registered_sources") for row in rows] != list(SIZES):
        raise ValueError("POOL_EVIDENCE_SIZES_INVALID")
    for row in rows:
        repetitions = row.get("repetitions")
        if (type(repetitions) is not int or not 1 <= repetitions <= 10
                or row.get("pool_max_size") != 10 or row.get("fanout_concurrency") != 16
                or type(row.get("peak_acquired_connections")) is not int
                or not 1 <= row["peak_acquired_connections"] <= 10
                or type(row.get("pool_size_after")) is not int
                or not 1 <= row["pool_size_after"] <= 10
                or type(row.get("pool_idle_after")) is not int
                or row.get("pool_idle_after") != row["pool_size_after"]
                or row.get("all_transactions_readonly") is not True
                or row.get("fanout_isolated") is not True
                or type(row.get("denied_adapter_calls")) is not int or row["denied_adapter_calls"] != 0
                or type(row.get("python_peak_allocated_bytes")) is not int
                or row["python_peak_allocated_bytes"] <= 0):
            raise ValueError("POOL_EVIDENCE_CONTRACT_INVALID")
        for name in ("pool_acquire", "readonly_transaction", "source_total", "batch"):
            item = row.get(name, {})
            expected = repetitions if name == "batch" else repetitions * (row["registered_sources"] - 1)
            values = [item.get(key) for key in ("p50_ms", "p95_ms", "p99_ms")]
            if (type(item.get("samples")) is not int or item["samples"] != expected
                    or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                           for value in values) or values != sorted(values)):
                raise ValueError("POOL_EVIDENCE_MEASUREMENTS_INVALID")


async def measure(database: Database, size: int, *, repetitions: int = 3) -> dict:
    if size not in SIZES or type(repetitions) is not int or not 1 <= repetitions <= 10:
        raise ValueError("POOL_BENCHMARK_LIMIT")
    pool = database.require_pool()
    pool_size_before = pool.get_size()
    executor = FanoutExecutor(max_sources=size, global_concurrency=16,
                             per_source_concurrency=1, deadline_seconds=30,
                             per_source_timeout_seconds=10)
    targets = [(f"pool-synthetic-{index}", uuid.UUID(int=index + 1)) for index in range(size)]
    waits, reads, totals, batches = [], [], [], []
    active = peak = 0
    dispatched = set()
    readonly = []

    async def authorize(source_id, _company):
        if source_id == "pool-synthetic-0":
            raise PermissionError("synthetic denied")
        return source_id

    async def fetch(source_id):
        nonlocal active, peak
        dispatched.add(source_id)
        started = time.perf_counter()
        try:
            async with pool.acquire(timeout=10) as connection:
                acquired = time.perf_counter()
                waits.append((acquired - started) * 1000)
                active += 1
                peak = max(peak, active)
                try:
                    async with connection.transaction(readonly=True):
                        readonly.append(await connection.fetchval("SHOW transaction_read_only") == "on")
                        # Fixed test-only SQL. No source data, identifiers or user-authored query.
                        await connection.execute("SELECT pg_sleep(0.003)")
                    reads.append((time.perf_counter() - acquired) * 1000)
                finally:
                    active -= 1
            if source_id == "pool-synthetic-1":
                raise ConnectionError("synthetic source failure after read")
            return [{"synthetic": True}]
        finally:
            totals.append((time.perf_counter() - started) * 1000)

    outcomes = []
    tracemalloc.start()
    try:
        for _ in range(repetitions):
            started = time.perf_counter()
            outcomes.append(await executor.run(targets, authorize=authorize, fetch=fetch))
            batches.append((time.perf_counter() - started) * 1000)
        _, memory_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    expected = (size - 1) * repetitions
    isolated = ("pool-synthetic-0" not in dispatched and all(
        result["successful_sources"] == size - 2 and result["failed_sources"] == 2
        and {failure["error_code"] for failure in result["failures"]} == {"ACCESS_DENIED", "SOURCE_ERROR"}
        for result in outcomes))
    if (not isolated or not readonly or not all(readonly) or len(readonly) != expected
            or any(len(samples) != expected for samples in (waits, reads, totals))
            or not 1 <= peak <= pool.get_max_size() or active):
        raise RuntimeError("POOL_BENCHMARK_CONTRACT_FAILED")
    return {"registered_sources": size, "repetitions": repetitions,
            "fanout_concurrency": 16, "pool_max_size": pool.get_max_size(),
            "peak_acquired_connections": peak, "pool_size_after": pool.get_size(),
            "pool_size_before": pool_size_before,
            "pool_idle_after": pool.get_idle_size(), "pool_acquire": distribution(waits),
            "readonly_transaction": distribution(reads), "source_total": distribution(totals),
            "batch": distribution(batches), "python_peak_allocated_bytes": memory_peak,
            "denied_adapter_calls": 0, "fanout_isolated": isolated,
            "all_transactions_readonly": True}


async def run() -> dict:
    container = f"erp-pool-{uuid.uuid4().hex[:12]}"
    dsn = await new_postgres(container)
    database = Database(dsn)
    await database.start()
    try:
        results = [await measure(database, size) for size in SIZES]
    finally:
        await database.close()
    evidence = {"schema_version": 1, "mode": "measured_synthetic_postgres_pool",
            "clock": "time.perf_counter", "executor": "business_ai_gateway.fanout.FanoutExecutor",
            "pool_factory": "business_ai_gateway.db.Database", "results": results,
            "container": container, "container_retained": True, "existing_data_touched": False,
            "real_1c_called": False, "new_disposable_database": True,
            "pool_acquire_includes_connection_growth": True,
            "python_memory_is_not_process_rss": True, "capacity_decision": "EVIDENCE_ONLY_NOT_SIGNOFF"}
    validate(evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        evidence = asyncio.run(run())
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - CLI suppresses DSN/provider exception contents
        raise SystemExit("POOL_BENCHMARK_FAILED: private diagnostics withheld") from None
    print("PostgreSQL pool benchmark: PASS; new disposable container retained")


if __name__ == "__main__":
    main()
