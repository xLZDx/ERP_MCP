# S13 budget grant writers: fenced candidates

## Change

Added additive, ungranted `change_ledger.budget_admin_v1`, `budget_revoke_v1`, and `declare_budget_v1` candidates to `db/phase2/027_private_writer_admission_schema.sql`, with opt-in no-fallback routes for the corresponding `SqlChangeLedger` methods in `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`. The operator candidates retain legacy signatures/results and serialize `grant_id` after namespace 7 and the early lifecycle-row lock. The requester declaration candidate snapshots complete grant/record rows, takes both namespace-6 IDs, locks grant before record, compares the full snapshots and returns `LOCK_PLAN_STALE` if either changed before child DML, then upserts the child budget. The routines preserve legacy authorization, state/currency checks, event payloads and return values for unchanged source-defined paths.

## Why

The legacy routines can lock or insert the globally keyed `grants.grant_id` before reaching the shared event/lifecycle boundary; `declare_budget` also locks the record before the grant parent. The candidates add the global grant-ID fence before row work and place grant before record in the declaration path, without changing the legacy default routes or enabling candidate ACLs.

## Scope and compatibility

- The change is additive source only; legacy routing remains the default and candidate routing requires the existing private-writer schema flag.
- The candidate has no application `GRANT EXECUTE`; `PUBLIC` and all named application/private roles are explicitly revoked.
- No historical migration, existing grant, data, public MCP contract, COM boundary, or production operation changed.
- A mixed legacy/v1 explicit-ID first-insert race does not share the candidate advisory fence while legacy EXECUTE remains reachable. Keep these candidates ungranted and the flag off until callers and exact ACLs are cut over atomically.
- This does not close `claim` or the full `claim`/`declare_budget`/grant-operation serialization proof; that parent/child family remains incomplete.

## Verification state

- Focused actual `database-reviewer` source passes found no BLOCKER/MAJOR in budget admin/revoke behavior or the full-row declaration-plan comparison; reviewer model/effort was unavailable.
- Manual source inspection only. No SQL parse, tests, checks, build, CI, migration, database query/write, or COM call ran.
- Current whole-file migration 027 SHA-256: `3BC38F63C69C592E11FDD5C5EA783C814911834154EDB399EDA5ECD464DD2926`.
- `S13-BUDGET-ADMIN-01` and `S13-BUDGET-DECLARE-01` remain `NOT_RUN`; effective grants remain `NOT_VERIFIED`.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: database-reviewer role.
- Later behavior qualification: functional-test-reviewer and e2e-runner after all in-scope coding completes.
- Push/PR requires fresh GPT-PM approval correlated to the exact final code head.
