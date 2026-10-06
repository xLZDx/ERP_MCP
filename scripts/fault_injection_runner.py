"""Executed regression evidence with explicit unverified coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .execute_evidence_tests import execute
except ImportError:
    from execute_evidence_tests import execute

DEPENDENCIES = ("postgres", "redis", "jwks", "odata", "rsv")


def run() -> dict[str, object]:
    paths = ["tests/test_health_routes.py", "tests/test_auth_jwks_http.py"]
    result = execute(paths)
    result["real_1c_called"] = False
    result["not_covered"] = ["JWKS_container_stop_restart", "secret_provider_OData_container_faults", "audit_event_recovery"]
    result["coverage"] = "readiness_and_real_HTTP_JWKS_timeout_TTL_outage_401_recovery"
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
