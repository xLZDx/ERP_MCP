# G6 / G6-pre: one read-only canary pass and a bounded workload measurement (2026-10-10)

Operator decisions (2026-10-10): one canary pass is allowed (the read-only recipe below was confirmed with "GO"); the operator allowed a measurement run for the G6-pre workload metrics; staging is forbidden. Neither is a gate pass. This document records exactly what was run and what it does and does not prove.

## What was exercised

- Target: the local real-1C lane gateway `http://127.0.0.1:21000/mcp` (Release 1 gateway code, tool surface read-only) over the source `onec-818ha-reference`, which is a copy of the 818 HA base kept on this machine (reference copy dated 2026-09-15 in the lane manifests). It is a local test copy, not staging and not the live production database. Nothing in Release 2 code (`business_ai_gateway.phase2`) was involved: R2 modules are unwired and in-memory.
- Identity: the test user `auditor`, scope `onec:read`, token re-issued the same day with the operator-owned lane helper.
- Writes: none. Raw results were written only to a private directory outside git (`D:\ERP_MCP_Testbed\real1c_e2e\private_evidence\r2_canary_20261010\`). No amounts, counterparty names or secrets are in this document.

## Canary recipe (as run)

| Item | Value |
| --- | --- |
| Source / company | `onec-818ha-reference` / company "818 HA SRL (real reference org)" (pinned by id) |
| User / scope | `auditor` / `onec:read`, read-only |
| Window | at most 25 minutes of wall time; actual 37 seconds |
| Budget | at most 12 calls; actual 9; concurrency 1 |
| Kill switch | the script aborts when the budget or the window is exhausted; rollback = stop the script, nothing was written |
| Calls | `system_status`, `source_health`, `companies_list`, then twice each: `accounting_balance_by_analytics` (as of 2026-08-31), `accounting_balance_and_turnovers` (2026-08-01..2026-08-31), `payable_balance` (2026-08) |

## Canary result

| Check | Result |
| --- | --- |
| `system_status`, `source_health`, `companies_list` | succeeded (HTTP 200, no tool error); two companies returned |
| `accounting_balance_by_analytics`, `accounting_balance_and_turnovers`, `payable_balance` | all six calls returned a tool error; the two repeats of each tool returned identical digests (the failure is deterministic) |
| Cause (gateway log, read-only) | `SemanticProfileUnavailable`: no validated `payable.balance` profile and no validated `account.balance_and_turnovers` profile exists for this exact source/company. The gateway fails closed until a profile is validated, and validation needs native-report evidence passed by an accountant (G3). The outward error text is the opaque "Error executing tool ..." instead of a structured code; that is the Release 1 defect described in issue #37. |
| Conclusion | The live read path for health and company discovery works. The business reads are blocked by design until G3 produces a validated profile, so the canary could not read any ledger data and proves nothing about reconciliation. |

## Workload measurement (G6-pre input, read-only, local lane)

Sessions: one MCP session per worker thread. Latency in seconds, `err` = tool errors or client timeouts (40 s).

| Phase | Calls | Workers | err | p50 | p95 | max | calls/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `companies_list` | 24 | 1 | 0 | 0.124 | 0.320 | 0.854 | 5.3 |
| `companies_list` | 24 | 2 | 0 | 0.083 | 0.736 | 0.763 | 10.6 |
| `companies_list` | 24 | 4 | 0 | 0.195 | 0.540 | 0.543 | 15.6 |
| `companies_list` | 24 | 8 | 0 | 0.529 | 1.231 | 1.275 | 12.2 |
| `source_health` | 8 | 1 | 0 | 1.735 | 4.526 | 4.526 | 0.5 |
| fail-closed `payable_balance` | 6 | 1 | 6 (expected) | 4.647 | 24.384 | 24.384 | 0.1 |
| fail-closed `payable_balance` | 12 | 4 | 12 (expected) | 22.04 | 40.0 | 40.0 | 0.2 |
| `source_health` on fixture "down" | 3 | 1 | 0 | 6.503 | 8.98 | 8.98 | 0.2 |
| `source_health` on fixture "drift/slow" | 3 | 1 | 0 | 1.826 | 1.884 | 1.884 | 0.6 |

Observations (measured, one machine, one run, small samples): light reads scale to 8 workers without errors; the first `source_health` after idle took about 30 seconds; the fail-closed business-read path is slow (about 4.6 s alone) and, with 4 concurrent callers, reaches the 40-second client timeout, so contention on that path is a risk to measure again after profiles exist. One earlier attempt that shared a single session between two threads hung until timeout; the client was changed to one session per thread, which suggests a session is serialized, but this was not investigated.

## What this does not prove

- No R2 code ran on live data; R2 is not wired to any source. The R2 capacity grid, interference budget and alert rules were not fed these samples.
- No fault alarm was fired and recovered. The "down" and "drift" lane sources answered `source_health` calls without a tool error; whether their payload reports the fault was not interpreted.
- No ledger data was read, so there is no reconciliation or correctness result.
- The measurement is a small, single-run sample on the operator machine, not a production-representative workload, not repeated, and without variance statistics.
- No staging environment was used (forbidden). G6-pre and G6 stay NOT PASSED; G3 is the prerequisite for any business read.
