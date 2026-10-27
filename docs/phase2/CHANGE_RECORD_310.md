# Change Record 310 — reject non-finite PostgreSQL budget values

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 PostgreSQL candidate migration 027.
- Acceptance: S13 budget declaration, administration, and precheck behavior.
- State: source-only candidate; no SQL parse, tests/checks/build/CI, migration, database operation,
  staging, commit, or push ran in this change.

## Finding and change

The candidate checked new monetary inputs with `IS NULL` and `< 0`. PostgreSQL 16 treats numeric
`NaN` as greater than every ordinary numeric value, so the nonnegative predicate does not refuse
it. The existing monetary column check `amount >= 0` is not sufficient to exclude `NaN`.

`budget_admin_v1` now refuses `NaN`, `Infinity`, and `-Infinity` for `p_amount_limit`, and
`declare_budget_v1` does the same for `p_amount`, using PostgreSQL's canonical numeric text after
case-folding. Both checks precede namespace 7 and later ranked locks. The declaration keeps the
legacy namespace-2 switch gate ahead of validation.

The migration also replaces the current `budget_precheck` body with the existing source behavior
plus an explicit fail-closed check for non-finite values in stored `change_budget.amount` or
`grants.amount_limit`. Without this guard, a legacy NaN grant ceiling could compare above every
finite reservation and bypass the amount limit. No other budget arithmetic or refusal ordering
was intentionally changed. The candidate remains uninstalled and unqualified.

## Evidence and limits

- Source: `db/phase2/027_private_writer_admission_schema.sql`, `budget_admin_v1`,
  `declare_budget_v1`, and the candidate replacement for `budget_precheck`.
- Candidate migration SHA-256 at this source edit: `C0981F23928E052CF27D9F3AA9DCCFEC3A0B08FE0BCC8170CB93787754DD02D8`.
- Acceptance: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`,
  “2026-10-26 budget special-value refusal”.
- PostgreSQL 16 documents numeric `NaN`, `Infinity`, and `-Infinity`, and specifies that NaN sorts
  greater than non-NaN values: https://www.postgresql.org/docs/16/datatype-numeric.html.
- A bounded read-only `code-reviewer` pass examined the new numeric predicates and the replacement
  `budget_precheck` against migration 008. It found no actionable issue in predicate semantics,
  refusal order, preserved lookup/arithmetic, function security/search path, ownership, or ACL
  preservation. No parser, test, or database operation was run. The launch result did not expose
  the reviewer's resolved model or reasoning effort.
- Qualification must require `SCHEMA_INVALID` before namespace-7/row locks for new special-value
  inputs and `BUDGET_EXCEEDED` for seeded legacy special-value rows, with no grant, budget,
  reservation, record, token, or event-head change. It remains `NOT_RUN`.
- This source edit does not prove candidate migration parsing, effective grants, or runtime behavior.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — reject new non-finite budget numerics and
  fail closed on non-finite stored values.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — add exact
  source-derived refusal and no-state-delta acceptance.
- `docs/phase2/OPERATOR_BACKLOG.md` — record the finding and deferred qualification.
