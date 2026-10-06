"""Executed fault evidence with explicit coverage and fail-closed plans.

The runner never treats a compose plan as an outage observation.  Local, safely
disposable checks are executed when available; dependency cases that require a
real deployment remain ``NOT_RUN`` until an operator supplies that environment.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

try:
    from .execute_evidence_tests import execute
except ImportError:
    from execute_evidence_tests import execute

DEPENDENCIES = ("postgres", "redis", "jwks", "odata", "rsv")


def _compose_plan(root: Path) -> dict[str, object]:
    compose = root / "deploy" / "fault-injection.compose.yml"
    if not compose.is_file():
        return {"status": "MISSING", "path": str(compose)}
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose), "config", "--quiet"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "NOT_RUN", "reason": type(exc).__name__}
    return {"status": "VALID", "path": str(compose)}


def _planned_cases() -> list[dict[str, object]]:
    return [
        {
            "dependency": dependency,
            "action": f"stop {dependency}; request; start {dependency}; request",
            "expected_failure_status": 503,
            "expected_recovery_status": 200,
            "status": "NOT_RUN",
        }
        for dependency in DEPENDENCIES
    ]


def run() -> dict[str, object]:
    paths = ["tests/test_health_routes.py", "tests/test_auth_jwks_http.py"]
    result = execute(paths)
    result["real_1c_called"] = False
    root = Path(__file__).resolve().parents[1]
    result["compose"] = _compose_plan(root)
    result["planned_cases"] = _planned_cases()
    result["not_covered"] = [
        "JWKS_container_stop_restart",
        "secret_provider_OData_container_faults",
        "audit_event_recovery",
    ]
    result["coverage"] = [
        "readiness_and_real_HTTP_JWKS_timeout_TTL_outage_401_recovery",
        "compose_config_validation",
        "explicit_NOT_RUN_for_unexecuted_dependency_outages",
    ]
    result["cases"] = [{"test_path": path, "passed": result["passed"]} for path in paths]
    return result


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
