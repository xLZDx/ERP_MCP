# S13 duplicate override binding replay candidate

## Change

Added source-only `change_ledger.bind_duplicate_override_v1` to migration 027 and an explicit
flag-on route in `SqlChangeLedger.bind_duplicate_override`. The SQL candidate is revoked from
`PUBLIC` and all named application/private roles. Legacy route remains default.

## Why

The legacy routine appends `OVERRIDE_BOUND` even when `INSERT ... ON CONFLICT DO NOTHING` skips an
already-bound tuple. Exact retry can therefore add another audit event. The S13 candidate must make
exact replay lookup-only and keep an approver's binding immutable.

## Contract and decisions

- Preserve kill-switch-off, independent approver/capability, current `VALIDATED` record with no
  authorization, and the exact current business-key digest checks.
- Take the shared namespace-2 switch fence, then namespace 7/lifecycle and namespace-6
  `record-change-id` before locking the record parent and reading the binding/business-key state.
- An exact prior binding for the same approver is a no-event success. A different digest or
  ambiguous multiple historical bindings for that approver refuses with
  `OVERRIDE_BINDING_CONFLICT` / `P0001`. A new independent approver inserts one binding and appends
  one `OVERRIDE_BOUND` event.
- Do not grant or enable until the competing business-key and override writer paths are fenced,
  reviewed and qualified.

## Verification state

Only the current continuation's source edits are attributed to this turn; the shared checkout was
already dirty. The SQL candidate and adapter route were read after editing. No SQL parse, test,
check, migration, database/COM operation, staging, commit or push ran. Effective grants remain
`NOT_VERIFIED`, replay qualification remains `NOT_RUN`, and source review is pending.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Next action

Continue S13 lock/call-path closure; then complete actual source/ACL review and disposable
qualification. Keep the candidate ungranted until those gates pass.
