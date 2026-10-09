# Phase 2 capacity drill (S4b E5)

Status: MEASUREMENT on a disposable local container. Not a capacity guarantee, not the G1 exit decision.
Code head at measurement: measured on a working tree on top of 70f7cf7 (the drill code at that time is identical to the committed drill in 223a30f; later review fixes to the script - deadlines, redaction, local-host guard, --keep-db/--events, p99 gating - were NOT part of the measured runs and do not change the measured operations).

## Method

`scripts/phase2_capacity_drill.py --sources N --workers M --pages P --out file.json`

1. Creates a throwaway database (`tests/phase2/_pg_harness.throwaway_db`, migrations 001-003, no seed) and drops it afterwards.
2. Inserts N sources (tenant `A`, `d0000`..), one `living_worker` role_scope per source, one cursor (`conn`, value `p0`) and one job per source (untimed setup).
3. Starts M worker OS processes (separate Python interpreters; DSN passed only through the environment). Each connects, prints READY and blocks on stdin; the parent releases all with one write each (start barrier), so wall time covers only the work.
4. Sources are partitioned round-robin across workers. Per source a worker runs: `acquire_job` -> `commit_cursor_page` x P (2 deterministic events per page, digests matching the in-database recomputation) -> `finish_job(SUCCEEDED)`. Every call is one transaction with `SET LOCAL ROLE living_worker` + `living.set_scope`; latency is wall time of that transaction (client side, includes the round trips).
5. The parent samples `pg_stat_activity` about every 0.1 s (sampling spacing is approximate) for backends waiting on a Lock, then recounts in the database, including the expected distinct event-id set per source.
6. Safety: the worker phase has a deadline (120 s + 0.5 s x sources x pages); on timeout, an EOF on a worker's start barrier, or any parent failure the workers are killed and reaped, and the exit code is non-zero. The DSN, its password and user are redacted from stored errors and output. Non-local DSN hosts are refused with no override, and BEFORE any database is created the cluster behind the DSN must have the same `pg_control_system().system_identifier` as the container `erp-phase2-test-pg` (fail closed, exit 2; a different local PostgreSQL such as Release 1's is refused); every worker re-checks the identifier handed over by the parent (exit 4 otherwise). `--keep-db --db-name g1x_...` keeps the database for an independent recount (the caller drops it); `--events` sets events per page.

Parameters for all rows: workers=8, pages=3, events_per_page=2, lease 120 s.

## Environment

Single local docker `postgres:16-alpine` container (`erp-phase2-test-pg`, 127.0.0.1:55712), Windows 11 host, Python 3.14.3, asyncpg. Client processes and the database share one machine. Not production, no network hop, no tuning.

## Results (informational single noisy runs; raw JSON not committed)

Sample counts per operation: 30 / 50 / 100 / 150 (one acquire, one finish per source; P x sources commits = 90 / 150 / 300 / 450). The p99 column is the maximum of the sample for counts below 100 (the script now emits `p99_ms: null` below 100 samples) and is only a rough percentile at 100-450.

| Sources | Operations | Wall s | ops/s | pages/s | acquire p50/p95/p99 ms | commit p50/p95/p99 ms | finish p50/p95/p99 ms | Errors | Lock waiters seen (samples with a waiter / samples taken, ~100 ms spacing) |
|---|---|---|---|---|---|---|---|---|---|
| 30 | 150 | 1.088 | 137.93 | 82.76 | 46.6 / 127.6 / 132.0 | 35.2 / 91.1 / 109.9 | 31.5 / 64.6 / 76.0 | 0 | 0 of 8 |
| 50 | 250 | 3.443 | 72.60 | 43.56 | 89.7 / 155.2 / 234.1 | 69.1 / 217.3 / 307.2 | 78.4 / 226.8 / 283.5 | 0 | 0 of 25 |
| 100 | 500 | 6.756 | 74.01 | 44.41 | 64.9 / 180.1 / 1370.6 | 66.0 / 220.6 / 1316.9 | 66.5 / 181.2 / 256.1 | 0 | 0 of 43 |
| 150 | 750 | 5.174 | 144.95 | 86.97 | 43.7 / 88.2 / 247.3 | 43.8 / 93.2 / 144.7 | 44.4 / 75.9 / 119.1 | 0 | 0 of 44 |

Each row is ONE run (no repetition). Throughput is not monotonic in N (100 sources was slower than 150): the runs are noisy single samples on a shared desktop host with other workloads (docker, antivirus, other sessions), and p99 at N=100 includes ~1.3-1.5 s outliers. No conclusion about scaling should be drawn from the ordering of rows.

## Invariants checked (database recount after every run, all true in all four runs)

- pages committed: `sum(cursors.version)` == N x P (90 / 150 / 300 / 450) and every cursor is at version P with value `pP`
- outbox rows == N x P x 2 (180 / 300 / 600 / 900) and `count(DISTINCT event_id)` equals the row count (no duplicates)
- the expected distinct event-id set per source (`dNNNN-pP-eE`) is present, not just the totals
- all N jobs `SUCCEEDED`, `fence = 1` and `attempt = 1` for every job, no job still holding a lease (no fence violation in this disjoint-source run; double acquisition is NOT exercised here - same-job acquisition races are covered only by `tests/phase2/test_g1_concurrency_mp.py`, not by the drill)
- worker error count == 0 (every SQL error and every non-zero worker exit is recorded)
- the script exits 0 only if all of the above hold; `tests/phase2/test_g1_capacity_smoke.py` re-derives the expected numbers independently at 5 sources / 2 workers / 3 pages.

## What this does NOT prove

- Not a production capacity guarantee: one container on a developer Windows host, default Postgres settings, no concurrent real workload.
- Not a multi-host or networked test; no latency across a real network, no connection pooler, no replica.
- Sources are disjoint across workers, so this drill does NOT exercise same-source contention (that is covered separately by `tests/phase2/test_g1_concurrency_mp.py`); "no lock waiter seen in K samples at ~100 ms spacing" (K = 8 / 25 / 43 / 44 here) says nothing about contended sources and does not prove that no lock wait happened between samples.
- Single run per size, no warm-up, no confidence intervals; percentiles at these sample counts (30-450 per operation) are coarse, p99 is essentially the max.
- Only 3 pages of 2 events per source: not a test of large pages, long histories, outbox publishing, retention, vacuum or table growth.
- Not the G1 exit decision. That belongs to the gate review, which also requires the other G1 evidence.
