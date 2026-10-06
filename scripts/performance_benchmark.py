"""Measure the production fan-out executor against synthetic read callbacks."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
import tracemalloc
from pathlib import Path
from uuid import UUID

from business_ai_gateway.fanout import FanoutExecutor

SIZES = (30, 50, 100, 150)


def percentile(values: list[float], fraction: float) -> float:
    if not values or not 0 <= fraction <= 1:
        raise ValueError("percentile requires samples and a fraction in [0, 1]")
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


async def measure(size: int, repetitions: int, concurrency: int) -> dict[str, object]:
    executor = FanoutExecutor(max_sources=size, global_concurrency=concurrency,
                             per_source_concurrency=1, deadline_seconds=10,
                             per_source_timeout_seconds=1)
    targets = [(f"synthetic-{index}", UUID(int=index + 1)) for index in range(size)]
    active = peak = 0
    dispatched: set[str] = set()
    timings: list[float] = []
    batches: list[float] = []

    async def authorize(source_id: str, _company: UUID) -> str:
        if source_id == "synthetic-0":
            raise PermissionError("fixture deny")
        return source_id

    async def fetch(source_id: str) -> list[dict[str, str]]:
        nonlocal active, peak
        dispatched.add(source_id)
        active += 1
        peak = max(peak, active)
        started = time.perf_counter()
        try:
            await asyncio.sleep(0.001)
            if source_id == "synthetic-1":
                raise ConnectionError("fixture outage")
            return [{"id": source_id}]
        finally:
            timings.append((time.perf_counter() - started) * 1000)
            active -= 1

    tracemalloc.start()
    try:
        started = time.perf_counter()
        outcomes = []
        for _ in range(repetitions):
            batch_started = time.perf_counter()
            outcomes.append(await executor.run(targets, authorize=authorize, fetch=fetch))
            batches.append((time.perf_counter() - batch_started) * 1000)
        elapsed = (time.perf_counter() - started) * 1000
        _, memory_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    isolated = all(item["successful_sources"] == size - 2 and item["failed_sources"] == 2
                   for item in outcomes) and "synthetic-0" not in dispatched
    if not isolated or peak > concurrency:
        raise RuntimeError("production executor violated isolation or concurrency")
    return {
        "registered_sources": size, "repetitions": repetitions,
        "sample_count": len(timings), "concurrency": concurrency,
        "peak_concurrency": peak, "elapsed_ms": elapsed,
        "batch_p95_ms": percentile(batches, 0.95),
        "p50_ms": percentile(timings, 0.50), "p95_ms": percentile(timings, 0.95),
        "p99_ms": percentile(timings, 0.99),
        "python_peak_allocated_bytes": memory_peak,
        "pool_wait_ms": None, "pool_wait_status": "NOT_MEASURED_NO_DATABASE_IN_THIS_RUN",
        "fanout_isolated": isolated,
        "throughput_sources_per_second": size * repetitions / (elapsed / 1000),
    }


async def run_async(repetitions: int = 3, concurrency: int = 16) -> dict[str, object]:
    if repetitions < 1 or concurrency < 1:
        raise ValueError("repetitions and concurrency must be positive")
    return {
        "schema_version": 2, "mode": "measured_synthetic_fanout",
        "clock": "time.perf_counter", "executor": "business_ai_gateway.fanout.FanoutExecutor",
        "real_1c_called": False,
        "results": [await measure(size, repetitions, concurrency) for size in SIZES],
        "capacity_decision": "EVIDENCE_ONLY_NOT_SIGNOFF",
    }


def run() -> dict[str, object]:
    return asyncio.run(run_async())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(run(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"measured fan-out evidence: {args.output}")


if __name__ == "__main__":
    main()
