# Change Record 256 — Abort stale private-writer admission transactions

Date: 2026-10-25  
Status: candidate source-only; SQL parsing and disposable qualification not run.

## Why

The candidate `private_writer_admit_v1` wrapped its final CAS/attempt/slot/event writes in a
PL/pgSQL exception block that converted `unique_violation` and `P0001` into a normal refusal row.
`PostgresAdmissionStore._call_json()` treats a returned row as success, so its transaction context
would commit rather than perform its required top-level rollback. This contradicted the S13
complete-lock-plan requirement that a stale plan or SQL failure abort the fresh transaction and
that a retry recompute its plan in a new transaction.

## Change

- A unique conflict in the final admission write block is translated to the stable
  `LOCK_PLAN_STALE` (`P0001`) domain error and rethrown.
- Existing `P0001` domain errors, including `BASE_CALL_IN_PROGRESS` and `LOCK_PLAN_STALE`, are
  rethrown instead of being converted to a normal decision row.
- The exception now propagates through `PostgresAdmissionStore._transaction()`, whose error path
  rolls back the complete top-level READ COMMITTED transaction. The stable domain codes remain
  handled by `_translate_postgres_error()`.

## Evidence and verification

- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, complete lock-plan contract:
  stale plans abort the fresh transaction; retry starts a new transaction and recomputes the plan.
- The same design's qualification section distinguishes transaction-level stale-plan failure
  from the explicitly planned per-item recovery subtransaction behavior.
- `db/phase2/027_private_writer_admission_schema.sql` baseline SHA-256 before this edit:
  `593EF40044ECEF28C30F6BAB0634CB44F20BB3E8293788EB6EA12E2E9F409834`.
- Candidate SHA-256 after this edit:
  `21EF54B7AFEF75BB2A47500300EE57998991A80A0FA535FFB86F4EA79C65B798`.
- Manual source trace confirmed `_call_json()` returns normally only after the transaction context
  commits, while `_transaction()` rolls back on an exception and maps known `P0001` codes.
- SQL parsing, tests/checks, migration, database operation, staging, commit, and push: `NOT_RUN`.

## Acceptance follow-up

Disposable qualification must force both the unique-conflict and `P0001` branches after planned
admission DML, then prove no row/event/slot delta survives and the same pooled connection is
outside a transaction. The ordinary `BASE_CALL_IN_PROGRESS` service refusal must retain its
stable code. This candidate remains unparsed, uninstalled, and ungranted.
