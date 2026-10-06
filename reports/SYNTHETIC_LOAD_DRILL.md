# Synthetic ACL load drill

Assessed 2026-10-06 against the local PostgreSQL 16 candidate database. This drill invokes only
`Registry.list_allowed`; it does not call an adapter, sidecar, or 1C. It creates 150 synthetic
source/company pairs, grows the principal's grant set through 30/50/100/150, and runs 32 concurrent
authorization-list requests at each size through the configured 10-connection application pool.
Each stage has three warm-up calls. The script removes only its uniquely named synthetic rows.

| Allowed sources | Requests | Wall time | Mean latency | p95 latency | Result |
|---:|---:|---:|---:|---:|---|
| 30 | 32 | 2301.95 ms | 543.17 ms | 2288.88 ms | PASS |
| 50 | 32 | 41.36 ms | 23.99 ms | 37.09 ms | PASS |
| 100 | 32 | 65.00 ms | 38.45 ms | 61.43 ms | PASS |
| 150 | 32 | 87.09 ms | 52.03 ms | 80.07 ms | PASS |

The 30-source stage has a large unexplained outlier despite warm-up and is not a capacity claim.
The later stages show expected increasing query cost, but this small shared local environment is
not a production benchmark. No SLO/throughput target has been established. Repeat under a controlled
deployment-like host with representative data, query mix, and telemetry before capacity sign-off.

The same correctness/concurrency drill runs in CI as `scripts/acl_load_drill.py`.
