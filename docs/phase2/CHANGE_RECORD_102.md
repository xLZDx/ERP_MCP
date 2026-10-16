# Change record 102 — S13 kill-switch recovery design

## What changed

- Added `S13_KILL_SWITCH_RECOVERY_DESIGN.md`, comparing bounded retry with in-call draining and specifying the recommended bounded, retryable kill-switch behavior.
- Recorded two independent source-level reviews: `reliability-reviewer` and `database-reviewer`; both identified that caught item failures and a full bounded batch must retain the stopped mode.

## Why

Migration 008's sweep returns per-item failures and processes bounded batches, while `kill_switch(..., 'OFF')` currently discards the result and writes OFF. The design prevents effects from resuming until both item failures and possible batch backlog are resolved, while preserving transaction evidence and the existing API shapes.

## Decisions and scope

- Recommended one bounded sweep per call, serialized by a scope-specific recovery lock; retries use a new call/transaction.
- Proposed migration 020 after R-03 migration 019. No code, test, SQL, database, gate, or production configuration was changed by this record.
- Requested a separate PM design ruling before implementing migration 020. Formal S13/G1–G8 status is unchanged.

## Review and verification state

- `reliability-reviewer` and `database-reviewer` provided read-only design reviews at source HEAD `82390985404c2eba8eae5e913524876b7800a6ac`.
- Tests, SQL checks, database commands, and migrations: `NOT_RUN`.
- Acceptance scenarios are assigned to `functional-test-reviewer` and `e2e-runner` only after the full coding scope is complete; a database reviewer will review the final migration and evidence.

## Contracts and paths

- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md`
- `db/phase2/006_change_sweeps.sql`
- `db/phase2/008_change_hardening_b.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
