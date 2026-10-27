# Change Record 260 — deterministic latest approval selection in writer candidates

## What changed

- Added `approval_id DESC` as a stable tie-breaker after `approved_at DESC` in all three latest-approval selectors in the uninstalled migration-027 candidate.
- Kept the hint and locked re-read in `operator_resolve_v1` on the same ordering so the frozen approval plan is compared against the same canonical row.

## Why

The approval table has a primary key on `approval_id`, but the inspected schema has no uniqueness rule for `(change_id, decision, approved_at)`. A `LIMIT 1` ordered only by `approved_at` therefore does not define which approval is selected when timestamps tie. The additional primary-key ordering makes candidate selection stable and keeps the S13 independence decision tied to a reproducible approval row.

## Scope and compatibility

- Candidate-only change in `db/phase2/027_private_writer_admission_schema.sql`; no installed schema, grant, routing, or runtime behavior was changed.
- The migration remains uninstalled and ungranted. This source-level refinement does not establish effective privileges or transaction behavior.

## Verification state

- Baseline migration SHA-256 before this edit: `2BD2C3B6100B374FD7ECB051DF049CF68BDAAD2643DC101363A32B4FCA5EA845`.
- Candidate migration SHA-256 after this edit: `FAA44FC42E9C2D4008F868CF5531CDDE4FB6FDD94B1236421DC7F6E35134547F`.
- Source inspection confirmed all three latest-approval selectors now order by `approved_at DESC, approval_id DESC`; no SQL parser, tests, checks, build, CI, migration, database call, staging, commit, or push was run.
- S13 operator-resolution race and replay qualification remains `NOT_RUN` under `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. The database reviewer owns the later lock/grant review; the functional and E2E test roles own mapped scenarios after coding is complete. Next: continue source closure, then run the assigned review and qualification sequence on an approved disposable schema. Do not install or grant this candidate before those gates.
