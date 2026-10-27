# Change Record 257 — Acquire admission identity fences before row locks

Date: 2026-10-25  
Status: candidate source-only; SQL parsing and disposable lock qualification not run.

## Why

The complete S13 lock-plan contract requires private-writer paths to take the base and scope
fences, lock and validate the lifecycle row, then acquire the complete namespace-6 global ID set
before other relation-row locks. In candidate migration 027, `private_writer_mark_invoking_v1`
and `private_writer_begin_com_entry_v1` instead locked service bindings and serving fences before
acquiring their call/change/dispatch-CAS namespace-6 fences. `mark_invoking` also locked record,
permit, intent, permit-binding, attempt, and physical-slot rows before those fences. That left an
advisory-vs-row lock inversion against callers which already take namespace 6 before relation rows.

## Change

- Moved each function's complete call-ID, change-ID and dispatch-CAS namespace-6 fence acquisition
  to immediately after its lifecycle-row readiness/epoch check.
- Removed the later acquisitions so no namespace-6 lock is first taken after the service, serving,
  record, permit, intent, attempt, or physical-slot relation rows.
- The functions retain the same identity keys, base/scope fences, conditions, and DML behavior;
  only acquisition order changed.

## Evidence and verification

- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, complete lock-plan contract:
  namespace 8 → namespace 7 → early lifecycle row → namespace-6 IDs → remaining relation rows.
- `db/phase2/027_private_writer_admission_schema.sql`: the two entry functions now acquire all
  three IDs immediately after lifecycle validation and before their first `FOR SHARE`/`FOR UPDATE`
  beyond the lifecycle row.
- Candidate SHA-256 before this edit:
  `21EF54B7AFEF75BB2A47500300EE57998991A80A0FA535FFB86F4EA79C65B798`.
- Candidate SHA-256 after this edit:
  `DE5A078C2F9F196EE117434779C5E0A1E73A7B6936FF1252612AF0E74F3948A3`.
- SQL parsing, tests/checks, migration, database operation, staging, commit, and push: `NOT_RUN`.

## Acceptance follow-up

Disposable database/reliability qualification must force mark-invoking and COM-entry transactions
to contend with namespace-6 owners in reverse logical-ID order. Verify the canonical acquisition
order, bounded completion, stale-plan refusal, and zero state/event delta after an aborted
transaction. The candidate remains unparsed, uninstalled, ungranted, and unqualified.
