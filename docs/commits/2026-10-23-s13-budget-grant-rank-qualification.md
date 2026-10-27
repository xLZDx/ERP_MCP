# S13 Budget-Grant Parent-Rank Qualification Mapping

## Change

Mapped the `claim`/`declare_budget` parent-child lock-order candidate to disposable qualification
scenario `S13-BUDGET-RANK-01`. The scenario covers grant mutation contention, non-locking-plan
revalidation, namespace-6 IDs, schema-derived `grants → records SCC → budget/reservation children`
order, global grant-ID collision refusal, and no-partial-state assertions.

## Why

Current `claim` and `declare_budget` paths lock the record before grant and child relation work.
The candidate FK graph requires the grant parent before the records SCC and both parent sets before
budget/reservation children. `budget_admin`/`budget_revoke` mutate the grant independently and must
join the same applicable fence/identity order. This is a source-order mismatch, not a reproduced
deadlock.

## Affected contracts and paths

- `db/phase2/004_change_ledger.sql:350-363` — grant/reservation FK definitions.
- `db/phase2/008_change_hardening_b.sql:52-56,159-179,608-665` — budget child DDL and current functions.
- `db/phase2/009_approval_digest_2.sql:472-552` — current `claim` path.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md` — candidate parent-first order.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md` — source map and scenario reference.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — acceptance scenario.

## Verification state

Static source/document inspection only. No tests, checks, builds, migrations, database mutations,
service restarts, or runtime contention scenarios were run. The candidate order is unimplemented and
unqualified; S13 remains open.

## Ownership and next action

Operator: accountable task owner. Codex: executor. Functional/E2E roles own the later scenario
implementation and execution after all coding is complete; the database reviewer owns the later
independent database review. Next: reconcile every remaining granted entry, trigger and unique
conflict path with the candidate rank before freezing source and starting the assigned test phase.
