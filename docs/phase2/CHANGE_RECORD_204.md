# Change Record 204 — bound the complete startup recovery inventory

## What changed

- Migration 027's startup-recovery routine now counts pending attempts, open barriers, and every call ID referenced by those barriers while holding the base-writer fence. It refuses above 200 aggregate items before epoch/history/readiness mutation.
- The Python PostgreSQL adapter independently rejects a decoded response above the same bound instead of iterating it into an unbounded startup model.
- The stable refusal code is `STARTUP_RECOVERY_INVENTORY_LIMIT`; no partial inventory is returned or allowed to authorize readiness.
- Added `S13-STARTUP-INVENTORY-BOUND-01` to the qualification prerequisites with the exact 200/201 boundary and rollback evidence.

## Why

The startup function previously aggregated all pending attempts and closed barriers into one JSON result without a total resource bound. A partial result would be unsafe because unseen recovery work could be mistaken for a clean start. The bounded fail-closed result preserves completeness: normal-sized inventories are whole, and oversized inventories leave startup unavailable.

## Evidence and verification state

- Candidate hashes at this checkpoint: `db/phase2/027_private_writer_admission_schema.sql` `AD4D698D23F04608DBD8CB2816B93F23E49D438BBFB370F479FB422E7217EC6F`; `src/erp_mcp_private_writer/postgres_store.py` `40F837809BD9600D9A8BFAF4B0A0E2E637B4DFDDF24073734052F23B0417B9AC`; `src/erp_mcp_private_writer/service.py` `F8DEF4DD4B910AB8894D25665C681D8AF133AFCCB35E9B250F86089345C24CEF`; qualification plan `D356AD6BD740DA6BC24E2B7C4BE262B6A59F73E1B97DFEF23AF08286FA4B37C6`.
- The latest registry contains 110 local-only paths (CR204 and CR205 included), SHA-256 `AC39AD4454D77CD460A846CE4F24611E1D8127D09A5A127398D0A0392A70F815`.
- Static source inspection only. SQL parsing, tests/checks/build, migration, database access, service startup, COM, and disposable qualification were not run. `S13-STARTUP-INVENTORY-BOUND-01` remains `NOT_RUN`.
- These candidate files had pre-existing modifications. This record attributes only the inventory cap, stable refusal mapping, and defense-in-depth adapter bound above to change 204.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after code closure, have the database reviewer inspect the fenced count and rollback contract; then assign exact 200/201 and readiness-refusal scenarios to the functional/E2E roles on the approved disposable database.
