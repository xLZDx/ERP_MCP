# S13 sweep policy writer candidate

## Change

Added source-only `change_ledger.set_sweep_policy_v1` to migration 027, registered the legacy and
candidate function signatures in the SQL adapter specification, and exposed
`SqlChangeLedger.set_sweep_policy` with an explicit S13 flag-on route. The candidate is revoked
from `PUBLIC` and all named application/private roles.

## Why

The operator policy writer reads/locks a row, merges parameters, performs a scope-key UPSERT and
appends an event. It needs same-scope fencing and lifecycle validation before relation-row work.

## Contract and decisions

- Preserve operator-only authorization and the final migration-012 key/range validation, including
  `verify_min_tick_seconds` and integer checks for attempt parameters.
- Take namespace 7 and the lifecycle row before selecting the policy row `FOR UPDATE`; perform the
  same merge and UPSERT, then append `SWEEP_POLICY_SET` as the last ledger mutation.
- Retain legacy routing as default. Candidate routing is explicit, has no fallback, and remains
  unusable by application roles until all-path cutover and race qualification are complete.

## Verification state

Only source edits performed during this continuation are attributed to this turn; the checkout
already contained unrelated dirty files and staged entries. The new SQL body and adapter signature/
route were read after editing. No SQL parse, test, check, migration, database/COM operation, staging,
commit or push ran. Effective grants are `NOT_VERIFIED`; `S13-SWEEP-POLICY-RANK-01` is `NOT_RUN`;
source review remains pending.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Next action

Continue the remaining S13 writer, trigger, effective-ACL and disposable-race closure. Do not
grant or enable this candidate before that work is reviewed.
