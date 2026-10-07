# Dependency failure matrix runbook

The contract is defined by `scripts/dependency_failure_matrix.py`. In the isolated harness from
`deploy/fault-injection.compose.yml`, stop one dependency at a time and collect:

1. HTTP status and sanitized error body;
2. readiness state;
3. audit outcome and correlation ID;
4. dependency metric outcome;
5. recovery after dependency restart.

Expected behavior is fail-closed for every case. No test may use production URLs, credentials,
customer data or a direct 1C connection.
