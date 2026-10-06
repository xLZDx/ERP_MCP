"""Validate JSON emitted by synthetic load drills without setting capacity guarantees."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("performance evidence requires results")
    sizes = [item.get("registered_sources") for item in results if isinstance(item, dict)]
    if sizes != sorted(sizes) or any(not isinstance(size, int) or size <= 0 for size in sizes):
        raise ValueError("registered source sizes must be positive and ordered")
    for item in results:
        if not isinstance(item, dict):
            raise TypeError("performance result must be an object")
        for key in ("elapsed_ms", "batch_p95_ms", "throughput_sources_per_second"):
            if not isinstance(item.get(key), (int, float)) or item[key] < 0:
                raise ValueError(f"performance result field {key} is invalid")
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
