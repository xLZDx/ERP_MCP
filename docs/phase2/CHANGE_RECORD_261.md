# Change Record 261 — reject the zero recovery run identifier

## What changed

- The additive migration-027 recovery-sweep core now rejects the all-zero UUID for its caller-preallocated `p_run_id` with the existing stable `SCHEMA_INVALID` refusal.
- The check runs before the ID enters the namespace-6 fence plan or is inserted into `sweep_runs`.

## Why

The recovery run identifier is the globally fenced identity of the final `sweep_runs` row. Accepting the zero UUID would let a sentinel value masquerade as a caller-allocated run identity. The normal adapter generates a random UUID, but the database boundary should enforce the same nonzero identifier contract for every caller.

## Scope and compatibility

- Candidate-only change in uninstalled `db/phase2/027_private_writer_admission_schema.sql`.
- No migration was installed; no grants, runtime routes, database contents, or existing history were changed.

## Verification state

- Migration SHA-256 before this edit: `FAA44FC42E9C2D4008F868CF5531CDDE4FB6FDD94B1236421DC7F6E35134547F`.
- Migration SHA-256 after this edit: `0FA7451D1AB424EB857CF5E4F11833C89F6502C4906F6789AAE76FD439B6AA21`.
- Source inspection only. No SQL parser, tests, checks, build, CI, migration, database operation, COM call, staging, commit, or push was run. The explicit run-ID conflict and replay scenarios remain `NOT_RUN`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. Next: complete static recovery/helper/trigger/FK closure, then have the database reviewer inspect the exact candidate before functional and E2E qualification on the approved disposable schema.
