"""Deterministic dependency fault-injection matrix contract.

The runner validates the expected fail-closed response classes. Deployment harnesses can map the
case IDs to real container/process outages without changing the policy contract.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureCase:
    case_id: str
    dependency: str
    expected_status: int
    expected_error: str
    must_not_leak: tuple[str, ...] = ()


FAILURE_MATRIX = (
    FailureCase("db-down", "database", 503, "not-ready"),
    FailureCase("redis-down", "redis", 503, "not-ready"),
    FailureCase("jwks-down", "jwks", 401, "authentication-failed"),
    FailureCase("secret-provider-down", "secrets", 500, "sanitized-error"),
    FailureCase("odata-timeout", "odata_sidecar", 500, "SOURCE_TIMEOUT"),
    FailureCase("rsv-crash", "rsv_bridge", 500, "upstream bridge operation failed"),
)


def validate_matrix() -> tuple[FailureCase, ...]:
    ids = [case.case_id for case in FAILURE_MATRIX]
    if len(ids) != len(set(ids)):
        raise ValueError("failure case IDs must be unique")
    if any(case.expected_status < 400 for case in FAILURE_MATRIX):
        raise ValueError("dependency failures must fail closed")
    return FAILURE_MATRIX


def main() -> None:
    cases = validate_matrix()
    print(f"dependency failure matrix: {len(cases)} cases; contract PASS")
    for case in cases:
        print(f"{case.case_id}: {case.dependency} -> {case.expected_status} {case.expected_error}")


if __name__ == "__main__":
    main()
