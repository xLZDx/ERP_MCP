# Change record 029 — S14-R02 synthetic verification evidence

## What changed

- Added focused SQL coverage for the separate typed approval digest and canonical wire SHA, signed digest substitution refusal, receipt acceptance and replay, verification-row immutability, noncanonical JSON refusal, and legacy rows with unknown wire bytes.
- Added migration 018 to the shared phase 2 test harness and dump/restore migration list.
- Updated the combined SQL/clone E2E scenarios to forward and verify the actual `SimulatedOneC` receipt instead of constructing a second ledger-form receipt.
- Recorded runtime evidence and remaining review gates in the simulation plan, operator backlog, and decision log.
- Refreshed the document registry after the S14 design and implementation record were added.

## Why

Migration 018 changes a dispatch authorization boundary. Its accepted prototype claim requires evidence that SQL stores the wire digest independently, refuses a correctly signed receipt for another digest, and accepts the actual clone receipt over the canonical bytes. Dump/restore also needs to cover the new schema and function definitions.

## Contracts and paths

The tests cover only the non-gating synthetic lane. They do not authorize or qualify a real COM adapter, real 1C clone, identities, signer custody, staging, production, or any G0-G8 / Release 2 gate. Migration 018 ran only inside throwaway databases on the dedicated local PostgreSQL 16 test container.

Affected paths: `tests/phase2/_pg_harness.py`, `tests/phase2/test_change_ledger_dump_restore.py`, `tests/phase2/test_s14_wire_receipt_sql.py`, `tests/phase2/test_simulation_e2e_sql.py`, `docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`, `docs/phase2/OPERATOR_BACKLOG.md`, `core/DECISION_LOG.md`, and `governance/DOCUMENT_REGISTRY.md`.

## Verification state

- Functional SQL and dump/restore: **9 passed** in 152.71 seconds, exit code 0.
- Combined simulated clone-to-ledger E2E: **15 passed** in 117.37 seconds, exit code 0.
- Runtime: Python 3.12, PostgreSQL 16 disposable container; asyncpg 0.32.0, pytest 9.1.1, pytest-asyncio 1.4.0.
- Independent database-reviewer (GPT-6 Luna, medium) reviewed migration 018 and the related test diff; no BLOCKER, MAJOR, MINOR, or INFO findings.
- No full suite, lint, typecheck, build, CI, or standalone migration-verification script was run.
- Exact-range GPT-PM review remains pending; no push has occurred.
