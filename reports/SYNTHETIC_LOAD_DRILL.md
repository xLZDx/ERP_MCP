# Synthetic ACL load drill

## Current bounded fan-out exercise — local synthetic only

The additional `scripts/fanout_load_drill.py` exercises PostgreSQL company ACL → Redis rate-limit
check → pinned OData adapter contract → Fake1C for portfolio sizes 30/50/100/150. Each portfolio
uses batches of at most 16 sources, global concurrency 20 and per-source concurrency 2. In the
latest local run: DB pool peak 10/10 (acquire p50 0.040 ms, p95 13.177 ms), Redis check p50 8.306
ms/p95 16.290 ms; 318 synthetic reads succeeded, 12 expected partial failures (one ACL denial,
one timeout, one malformed result at each portfolio size), and the denied adapter was dispatched
zero times. Measured end-to-end portfolio throughput ranged 29.60–125.96 sources/sec; p95 batch
latency ranged 128.859–180.321 ms. Peak Python traced allocation was 3,231,459 bytes.

These are one shared local host run, not a capacity/SLO claim. Synthetic Fake1C never substitutes
for production source timing or 1C reconciliation. CI re-runs the same correctness/concurrency
exercise after the follow-up is integrated.

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
