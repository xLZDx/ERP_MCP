"""Validate JSON emitted by synthetic load drills without setting capacity guarantees."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("performance evidence requires results")
    if any(not isinstance(item, dict) for item in results):
        raise TypeError("performance result must be an object")
    sizes = [item.get("registered_sources") for item in results]
    if any(type(size) is not int or size <= 0 for size in sizes):
        raise ValueError("registered source sizes must be positive and ordered")
    if sizes != sorted(set(sizes)):
        raise ValueError("registered source sizes must be positive and ordered")
    for item in results:
        if not isinstance(item, dict):
            raise TypeError("performance result must be an object")
        for key in ("elapsed_ms", "batch_p95_ms", "throughput_sources_per_second"):
            if type(item.get(key)) not in (int, float) or not math.isfinite(item[key]) or item[key] < 0:
                raise ValueError(f"performance result field {key} is invalid")
        if payload.get("schema_version") == 2:
            if payload.get("mode") != "measured_synthetic_fanout" or payload.get("clock") != "time.perf_counter":
                raise ValueError("measured evidence requires the actual measurement method")
            for key in ("p50_ms", "p95_ms", "p99_ms"):
                if type(item.get(key)) not in (int, float) or not math.isfinite(item[key]) or item[key] < 0:
                    raise ValueError("measured percentiles must be finite")
            if not item["p50_ms"] <= item["p95_ms"] <= item["p99_ms"]:
                raise ValueError("measured percentiles must be ordered")
            if type(item.get("sample_count")) is not int or item["sample_count"] < 1:
                raise ValueError("measurement requires actual samples")
            if item.get("fanout_isolated") is not True or item["peak_concurrency"] > item["concurrency"]:
                raise ValueError("fan-out isolation/concurrency proof failed")
    return {
        "sizes": sizes,
        "max_sources": max(sizes),
        "real_1c_called": payload.get("real_1c_called", False),
        "capacity_decision": "EVIDENCE_ONLY_NOT_SIGNOFF",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(json.loads(args.evidence.read_text(encoding="utf-8"))), indent=2))


if __name__ == "__main__":
    main()
