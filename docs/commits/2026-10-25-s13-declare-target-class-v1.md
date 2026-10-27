# S13 target class writer candidate

## Change

Added source-only `change_ledger.declare_target_class_v1` in migration 027 and an explicit
flag-on route for `SqlChangeLedger.declare_target_class`. The candidate is revoked from `PUBLIC`
and all named application/private roles. Legacy route remains the default.

## Why

Target classification affects an authorized record and reads mutable target-registry state. It
must serialize with registration/enforcement and lifecycle transitions before the record row is
locked or updated.

## Contract and decisions

- Preserve normalized non-NULL class validation, requester ownership, authorization `NONE`,
  `PROPOSED`/`VALIDATED` state, and `assert_target_effect` refusal behavior.
- Take namespace 7 and validate the lifecycle row, then namespace-6 record identity before locking
  the record; recheck scope and target effect before DML.
- Update the record and append one `TARGET_CLASS_DECLARED` event as the final ledger mutation.
- Do not take namespace 2 because this function rejects a NULL normalized class and does not read
  the kill switch in the accepted path. Keep this candidate ungranted until registry writers and
  effective ACLs are qualified together.

## Verification state

Only the current continuation's edits are attributed to this turn; the checkout was already dirty.
The candidate SQL and adapter route were read after editing. No SQL parse, test, check, migration,
database/COM operation, staging, commit or push ran. Effective grants are `NOT_VERIFIED`; the path's
fence race remains `NOT_RUN`; source review is pending.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Next action

Continue the all-path target-registration/classification lock review and mapped disposable race
qualification after coding is complete. Keep the candidate default-off and ungranted.
