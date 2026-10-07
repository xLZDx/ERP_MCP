"""Execute bounded fan-out mutations and verify independent rejection oracles."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from pathlib import Path
from uuid import UUID

from business_ai_gateway.fanout import FanoutExecutor, FanoutPolicyError

MUTATIONS = {
    "source_limit": ("if len(targets) > self.max_sources:", "if False:"),
    "duplicate_source": ("if len(set(source_ids)) != len(source_ids):", "if False:"),
    "row_limit": ("bounded_rows = rows[: self.max_rows_per_source]", "bounded_rows = rows"),
    "byte_limit": ("if len(encoded) > self.max_bytes_per_source:", "if False:"),
}


async def oracle(kind: str, executor_type: type) -> bool:
    executor = executor_type(max_sources=1, max_rows_per_source=1, max_bytes_per_source=100)
    async def authorize(source, _company):
        return source
    async def fetch(source):
        return [{"source": source}]
    targets = [("a", UUID(int=1)), ("b", UUID(int=2))]
    if kind == "duplicate_source":
        targets = [("a", UUID(int=1)), ("a", UUID(int=2))]
        executor.max_sources = 2
    if kind in {"source_limit", "duplicate_source"}:
        try:
            await executor.run(targets, authorize=authorize, fetch=fetch)
        except FanoutPolicyError as exc:
            expected = "DUPLICATE_SOURCE" if kind == "duplicate_source" else "FANOUT_LIMIT_EXCEEDED"
            return exc.code == expected
        return False
    if kind == "row_limit":
        result = executor._success("a", UUID(int=1), [{"row": 1}, {"row": 2}])
        return len(result.get("data", [])) == 1
    result = executor._success("a", UUID(int=1), {"large": "x" * 200})
    return result.get("error_code") == "SOURCE_RESPONSE_TOO_LARGE"


def run() -> dict[str, object]:
    module = inspect.getmodule(FanoutExecutor)
    if module is None:
        raise RuntimeError("production fan-out module is unavailable")
    source = inspect.getsource(module)
    cases = []
    for name, (before, after) in MUTATIONS.items():
        if source.count(before) != 1:
            raise RuntimeError("mutation location is missing or ambiguous")
        namespace = {"__name__": "_erp_mcp_test_mutant"}
        exec(compile(source.replace(before, after), "<fanout-test-mutant>", "exec"), namespace)  # noqa: S102
        baseline_passed = asyncio.run(oracle(name, FanoutExecutor))
        killed = not asyncio.run(oracle(name, namespace["FanoutExecutor"]))
        cases.append({"name": name, "baseline_passed": baseline_passed,
                      "mutant_killed": killed, "passed": baseline_passed and killed})
    return {"mode": "executed_fanout_mutations", "real_1c_called": False,
            "cases": cases, "passed": all(case["passed"] for case in cases),
            "not_covered": ["capability", "company_scope", "audit", "ssrf"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = run()
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
