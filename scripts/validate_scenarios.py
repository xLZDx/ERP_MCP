"""Validate deterministic synthetic accounting scenarios and their reconciliation state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "testbed" / "fake1c" / "fixtures" / "seed.json"
SCENARIO_PATH = ROOT / "testbed" / "scenarios" / "accounting_scenarios.json"


def _value(fixture: dict[str, Any], key: str) -> Any:
    value = fixture.get(key)
    if value is None:
        raise ValueError(f"scenario fixture is missing {key}")
    return value


def _check(fixture: dict[str, Any], check: dict[str, Any]) -> None:
    op = check.get("op")
    if op == "equals":
        actual = _value(fixture, check["path"])
        if type(actual) is not type(check["value"]) or actual != check["value"]:
            raise ValueError(f"expected {check['path']} to equal {check['value']!r}")
    elif op in {"at_least", "at_most", "greater_than"}:
        actual = _value(fixture, check["path"])
        target = _value(fixture, check["value_path"]) if "value_path" in check else check["value"]
        valid = {
            "at_least": actual >= target,
            "at_most": actual <= target,
            "greater_than": actual > target,
        }[op]
        if not valid:
            raise ValueError(f"scenario check failed: {actual!r} {op} {target!r}")
    elif op == "subtract_equals":
        if _value(fixture, check["left"]) - _value(fixture, check["right"]) != _value(
            fixture, check["expected"]
        ):
            raise ValueError("scenario subtraction invariant failed")
    elif op == "sum_equals":
        if sum(_value(fixture, key) for key in check["paths"]) != _value(
            fixture, check["expected"]
        ):
            raise ValueError("scenario sum invariant failed")
    elif op == "date_month_equals_period":
        date_value = _value(fixture, check["date"])
        period_value = _value(fixture, check["period"])
        if date_value[:7] != period_value:
            raise ValueError("document date does not match its accounting period")
    elif op == "opening_plus_debit_minus_credit_equals_closing":
        expected = (
            _value(fixture, check["opening"])
            + _value(fixture, check["debit"])
            - _value(fixture, check["credit"])
        )
        if expected != _value(fixture, check["closing"]):
            raise ValueError("account turnover equation does not reconcile")
    else:
        raise ValueError(f"unsupported scenario check operation: {op!r}")


def validate_scenario_suite(
    seed_path: Path = SEED_PATH, scenario_path: Path = SCENARIO_PATH
) -> tuple[int, str]:
    seed_bytes = seed_path.read_bytes()
    seed = json.loads(seed_bytes)
    scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))
    if scenarios.get("schema_version") != 2 or seed.get("schema_version") != 1:
        raise ValueError("unsupported seed/scenario schema version")
    if scenarios.get("seed_id") != seed.get("seed_id"):
        raise ValueError("scenario suite references a different synthetic seed")
    fixtures = seed.get("scenario_fixtures")
    rows = scenarios.get("scenarios")
    if not isinstance(fixtures, dict) or not isinstance(rows, list) or len(rows) < 10:
        raise ValueError("at least ten deterministic scenario fixtures are required")
    scenario_ids = [row.get("id") for row in rows]
    if any(not isinstance(item, str) or not item for item in scenario_ids):
        raise ValueError("every scenario requires a stable ID")
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("scenario IDs must be unique")
    for scenario in rows:
        scenario_id = scenario["id"]
        if not scenario.get("question") or not scenario.get("expected_class"):
            raise ValueError(f"scenario {scenario_id} is missing its question/class")
        fixture_id = scenario.get("fixture_id")
        fixture = fixtures.get(fixture_id)
        if not isinstance(fixture, dict):
            raise TypeError(f"scenario {scenario_id} has no deterministic seed fixture")
        checks = scenario.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError(f"scenario {scenario_id} has no executable expected checks")
        for check in checks:
            _check(fixture, check)
        reconciliation = scenario.get("native_reconciliation", {})
        if reconciliation != {"status": "NOT_RUN", "report_ref": None}:
            raise ValueError(
                f"synthetic scenario {scenario_id} must not claim native 1C reconciliation evidence"
            )
    fingerprint = hashlib.sha256(
        json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return len(rows), f"sha256:{fingerprint}"


def main() -> None:
    count, fingerprint = validate_scenario_suite()
    print(f"validated {count} deterministic synthetic scenarios; seed {fingerprint}")
    print("native 1C reconciliation: NOT RUN (synthetic checks are not promotion evidence)")


if __name__ == "__main__":
    main()
