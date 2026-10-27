# S13 versioned epoch-dependency route

## Change

Added additive SQL candidate `change_ledger.add_epoch_dependency_v1(text,text,uuid,text)` in
`db/phase2/027_private_writer_admission_schema.sql` and
opt-in adapter routing in `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`.
Expanded the S13 source design and disposable qualification requirements and updated the
continuation backlog.

## Why

The legacy operation mutates `records.epoch_dependencies` and appends an event but enters without
the candidate common scope/lifecycle/global-ID fence. A versioned route lets qualification exercise
the agreed ordering while preserving the legacy default and leaving the all-path cutover gate
closed.

## Contract and decisions

- Preserve the legacy 1–200 character key bound, requester ownership, `authorization_state='NONE'`
  and `PROPOSED`/`VALIDATED` state requirements.
- Exact key replay returns the unchanged JSON without reading `epoch_value`, updating the record,
  or appending another event.
- A new key uses the epoch value read after candidate fences, updates only the scoped record and
  `updated_at`, appends one `EPOCH_DEPENDENCY_ADDED` event, and returns the merged JSON.
- Candidate acquisition order is namespace 2 shared, namespace 7 scope, lifecycle row `FOR SHARE`,
  namespace 6 global record-ID key, then the record row. Scope is rechecked after record lock.
- Missing/change-ID-null maps to `CHANGE_NOT_FOUND` after key validation, preserving the existing
  source behavior. Missing/`NOT_READY`/`RECOVERING` lifecycle refuses; `LEGACY` remains compatible.
- The candidate entry currently has no application `EXECUTE` grant. A read-only reviewer found
  that the fresh epoch read can race legacy `bump_epoch`, direct principal/target registration, or
  `approve_registry_change` applying those registry cores, because those current paths can update the
  same epoch values without namespace 7. Migration 027 now explicitly revokes the entry from
  `requester_role` as well as the other named roles and grants it to no application identity. The
  adapter selector remains explicit, but flag-on fails closed at PostgreSQL ACL until all conflicting
  epoch writers join the common fence, the race is qualified, and the coordinated grant/cutover is
  accepted. Shared candidate entry helpers remain revoked from application roles; no installed
  privileges are inferred.

## Verification state and limits

This is source-only and has not been SQL-parsed, installed, or runtime-qualified. The read-only
code/database reviews found the missing epoch-writer serialization and ACL-gate gap; the source and
documentation correction received a focused follow-up with no remaining finding in that slice. No
tests, checks, build, CI, migration, database write, staging,
commit, or push ran. Exact grant measurement remains `NOT_VERIFIED` because the disposable
PostgreSQL lane lacks the `change_ledger` schema and S13 roles. S13 epoch/replay/race qualification
remains `NOT_RUN`; it is blocked until all epoch-writer paths are fenced and candidate ACL cutover is
authorized. The additive candidate does not remove the legacy bypass.

## 2026-10-25 ACL and epoch-writer correction

Read-only code and database reviews found that legacy `bump_epoch`, direct principal/target
registration, and approval-applied registry cores could race the v1 epoch snapshot. Migration 027
now revokes the entry from `requester_role` and grants it to no application role; the adapter's
explicit flag therefore fails closed at the SQL ACL until all four writers are fenced/cut over and
the collision/race acceptance passes. The qualification, design and source-final grant inventory
were aligned to this gate. A follow-up code review identified a stale design sentence claiming the
requester grant remained; it was corrected and the focused follow-up found no remaining contradiction.
No SQL parsing, tests, migration, database, staging, commit or push was run.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`
