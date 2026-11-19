# S18 SLO Baseline and Failure Table

Status: **measurement NOT_RUN**. This document defines the evidence format and records the
approved initial CT15 targets. It does not claim that a test lane, real 1C call, human alert
delivery, or production workload has been measured.

## Measurement rules

Every result must name the exact code head, run ID, date, workload, test-lane/environment,
command or measurement source, raw sample count, calculation, result, and limitations. A missing
approved-lane run stays `NOT_RUN`; an initial design target is not an observed SLO. Do not fill
numeric values from estimates or synthetic logic tests. No production traffic or real-money
operation is part of S18.

## Candidate service objectives and current evidence

| Objective | Approved basis | Measurement definition | Current result | Limit / next evidence |
|---|---|---|---|---|
| Per-base queue bound | CT15 initial target: 20 queued items; overflow must be refused | Maximum pending items per base and overflow outcome under the named workload | `NOT_RUN` | S18-01 functional test; distinguish pending queue slots from active work |
| Enqueue latency | No numeric SLO approved | p50/p95/p99 from accepted enqueue request to admission result; report refusals separately | `NOT_RUN` | Select an approved test-lane workload before measurement |
| Verification-read priority | CT15: verification reads precede new writes | Queue wait time by work class under a declared mixed workload; also report maximum write wait | `NOT_RUN` | S18-01/S18-02 workload; priority must not be presented as a starvation guarantee |
| Unknown call resolution | CT15 initial target: at most 5 attempts over 15 minutes before `TRIAGE_REQUIRED` | Attempts and elapsed time from first unknown outcome to terminal resolution or triage | `NOT_RUN` | Requires approved recovery-lane evidence; a timeout alone is not completion proof |
| Write-call deadline | CT15 initial limits: 120 s for write calls and 300 s for posting | Wall duration to deadline observation; separately record time to proven completion | `NOT_RUN` | Deadline expiry starts ownership investigation; it does not prove `PROVEN_FINISHED` |
| Alert receipt | CT15 initial target: human alert within 60 s | Time from alert condition/event creation to independent recipient acknowledgement; record delivery failure separately | `NOT_RUN` | No configured real recipient or human-receipt evidence is present |
| Operator triage | CT15 initial target: one business day | Elapsed time from `TRIAGE_REQUIRED` alert to recorded human disposition | `NOT_RUN` | Requires an approved operational owner and a measured test-lane run |
| Shutdown drain | CT15 requires queue drain; no numeric SLO approved | Time from admission close to drained state; report timeout, pending work, and active work separately | `NOT_RUN` | Exercise restart/shutdown cases in S18-02; never force-terminate an unqualified 1C session |
| Restart recovery | S18-02 requires safe persisted recovery or a held state | Compare pre-crash persisted inventory with recovered state for each named crash window | `NOT_RUN` | One disposable-PostgreSQL empty-inventory startup case passed; pending-call and process-restart windows remain untested |

## Failure table

| Step / failure | Required safe behavior | Evidence source | State |
|---|---|---|---|
| Queue already has 20 pending items | Refuse the new item with a stable overflow result; do not evict accepted work | S18-01 named functional scenario | `NOT_RUN` |
| Call ownership is `POSSIBLY_EXECUTING` | Hold all base mutations; permit verification reads; do not infer completion from a deadline or lease expiry | CT3/CT15 mapped crash/recovery scenario | `NOT_RUN` |
| Call ownership becomes `PROVEN_FINISHED` but outcome remains unknown | Keep only that target parked until the coordinator supplies terminal `APPLIED` or `FAILED_APPLY` state | S18-01 named functional scenario | `NOT_RUN` |
| Startup recovery inventory is absent, malformed, or incomplete | Keep dispatch closed or fail startup; do not report readiness | S18-02 durable restart scenario | `NOT_RUN` |
| New startup sees an empty persisted recovery inventory | Persist the new service epoch and return its matching readiness reference; this does not establish process/COM readiness or exercise dispatch | `tests/phase2/test_s18_startup_recovery_e2e.py` on HEAD `f4d24d52`; `1 passed, 14 warnings in 55.57s` | `PASS` — bounded synthetic PostgreSQL state-transition only |
| Alert sink is absent or fails | Keep event visible and undelivered; return explicit dependency/delivery failure; do not claim human receipt | Alert delivery scenario with an independent sink boundary | `NOT_RUN` |
| Supervised component exits | Observe exit, restart only the same configured component within the fixed restart bound, and return sanitized lifecycle evidence | S18-03 test-lane supervisor scenario | `NOT_RUN` |
| CT14 has not qualified forced termination for the exact channel/base | Leave forced termination disabled; retain `POSSIBLY_EXECUTING` hold and record that branch as `NOT_RUN` | CT14 capability record plus S18-02 lane evidence | `NOT_RUN` |
| Shutdown drain deadline expires | Fail stopped, preserve unresolved ownership/holds, and report the timeout; do not claim a drained state | S18-02 shutdown/restart scenario | `NOT_RUN` |

## Run record template

```text
status: NOT_RUN
head:
run_id:
date_utc:
workload:
environment_and_lane:
command_or_measurement_source:
sample_count:
metric_and_calculation:
result:
failure_or_refusal_counts:
limitations:
reviewer:
```

## Contract references

- `docs/phase2/PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md`, CT3 and CT15.
- `docs/sdlc/next-sprint-preparation.md`, S18-02 through S18-04 and S18 Sprint DoD.
- `docs/DEFINITION_OF_DONE.md` and `docs/TEST_STRATEGY.md` for integration-evidence limits.
