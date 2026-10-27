# Change Record 311 — constrain new budget NaN rows

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 PostgreSQL candidate migration 027.
- Acceptance: S13 durable rejection of new/updated special-value budget rows while legacy rows remain diagnosable.
- State: source-only candidate; no SQL parse, tests/checks/build/CI, migration, database operation,
  staging, commit, or push ran in this change.

## Finding and change

The previous source correction rejected non-finite values at the budget API boundary and made
`budget_precheck` fail closed for persisted legacy values. The underlying table definitions still
did not prevent a different granted or owner-context write path from storing `NaN` directly.

Candidate migration 027 now adds `grants_amount_limit_not_nan`,
`change_budget_amount_not_nan`, and `reservations_amount_not_nan` as `NOT VALID` checks. They reject
new and modified `NaN` values without scanning or asserting validity of pre-existing rows. Existing
invalid rows therefore remain visible; the budget precheck is still required to fail closed until
an authorized repair. The checks do not substitute for scoped routine authorization or
effective-grant inspection.

The `budget_precheck` explicitly refuses both a non-finite sum of other reserved/consumed
reservation amounts and a non-finite consumed-POST amount returned by `amount_consumed` for the
current target. PostgreSQL numeric NaN compares above finite numbers, so downstream arithmetic
currently also fails the amount ceiling; the explicit check gives both aggregate paths the same
stable refusal before relying on that comparison behavior. Each legacy NaN reservation therefore
fails with the stable budget refusal before any new reservation, record, token, or event change.

Qualification now requires all three checks to appear as `convalidated=false`, rejects a new
`NaN` insert and a no-op update of each seeded legacy `NaN` row, accepts a finite repair subject to
the normal authorization contract, and confirms each untouched legacy monetary source produces
`BUDGET_EXCEEDED` with no unrelated state/event delta.

## Evidence and limits

- Source: `db/phase2/027_private_writer_admission_schema.sql`, named constraints and explicit
  legacy-aggregate checks in the replacement `budget_precheck` definition.
- Candidate migration SHA-256: `47983E7958BB2C48C978B324CD2587D7165F835CDBCC1AACBB2A2213D99E2293`.
- Qualification: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`,
  `S13-BUDGET-LEGACY-NAN-CONSTRAINT-01`.
- PostgreSQL numeric special-value semantics are documented at
  https://www.postgresql.org/docs/16/datatype-numeric.html.
- PostgreSQL 16 documents that a `NOT VALID` check skips the legacy-row scan but is still enforced
  on subsequent inserts and updates: https://www.postgresql.org/docs/16/sql-altertable.html.
- No parser, test, database operation, migration, or runtime qualification was run. Effective
  grants remain `NOT_MEASURABLE` until candidate installation in the approved disposable database.
- A current-turn read-only `database-reviewer` source pass checked the exact candidate hash above
  and found no actionable BLOCKER/MAJOR in the NaN/infinity predicates, refusal order, preserved
  budget behavior, or `NOT VALID` constraint semantics. No SQL parser, test, migration, or database
  action ran; reviewer model/effort metadata were not exposed. This remains a source conclusion,
  not installation, grant, or runtime evidence.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — add three `NOT VALID` constraints and
  explicitly refuse non-finite legacy reservation aggregates and `amount_consumed` results.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — define explicit
  legacy-row, catalog-state, insert/update refusal, repair, and fail-closed acceptance.
- `docs/phase2/OPERATOR_BACKLOG.md` — record this source-only defense and the deferred qualification.

