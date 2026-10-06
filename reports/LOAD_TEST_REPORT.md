# Measured engineering load evidence — 2026-10-06

Frozen requirements: NFR-P2 / D13. Production capacity: NOT APPROVED.

Production Database pool + FanoutExecutor, fixed readonly PostgreSQL transactions, synthetic
source callbacks, three repetitions per size. Newly created disposable container retained;
no existing data touched, no 1C call, no credentials/identities in the artifact. Scanner PASS.
Private local artifact: `D:/Temp/erp-pool-performance-20261006b.json`.
SHA-256: `944e538d7dd844805169c3207c3e05162a0d6e9770b7f5661d2756c05e45704e`.

| Sources | Acquisition samples | p50 ms | p95 ms | p99 ms | Peak connections | Initial pool size |
| --- | --- | --- | --- | --- | --- | --- |
| 30 | 87 | 8.519 | 1162.508 | 1183.657 | 10 | 1 |
| 50 | 147 | 5.863 | 32.406 | 44.411 | 10 | 10 |
| 100 | 297 | 10.938 | 27.246 | 38.545 | 10 | 10 |
| 150 | 447 | 13.713 | 43.037 | 55.246 | 10 | 10 |

Acquisition includes connection creation/growth, not only saturated queue wait. The cold first
size is NOT comparable to the warmed later sizes as a scaling curve. Nearest-rank percentiles
are measured, not a latency formula. Artifact also records transaction/source/batch distributions,
Python tracemalloc peak (not process RSS), fully idle pool after execution, actual denial isolation
and explicit failure outcomes. All transactions readonly, denied-source adapter calls zero.

18 focused tests PASS against a real disposable PostgreSQL instance (17 validators + 1 actual
runtime-pool measurement test). Synthetic validators are not themselves measurement evidence.
CI separately executes the actual runner and uploads its scanned artifact at the tested revision.
Pilot/heterogeneous native 1C capacity, process/container RSS, deployment pool metrics, sustainable
throughput/SLOs and full transport fault scenarios remain OPEN. No L2/L3 or production GO inferred.
