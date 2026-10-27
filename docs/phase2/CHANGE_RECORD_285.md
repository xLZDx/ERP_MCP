# Change Record 285 — preserve combined recovery stage rank

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP S13 combined recovery in migration 027.
- Acceptance: `S13-RECOVERY-AGGREGATE-BUDGET-01`, with an explicit ordered-array regression addendum in the disposable qualification prerequisites.
- State: SQL source candidate only. No SQL parse, test/check, migration, database operation, build, CI, staging, commit or push ran.

## Baseline and finding

Migration 027 was already an untracked candidate before this turn; its recorded turn-start SHA-256
was `A99638E2B907919D11A63A6E8EBDD3D745CC83CFA12FBD54FA5E1D103DBA4DC2`. This record does not
claim authorship of the inherited migration.

The combined T3, T9, VOID and nonce-expiry selectors sorted each limited subquery by its retry rank,
but then used `array_agg` without an aggregate `ORDER BY`. The resulting arrays feed `FOREACH`
per-item loops and downstream planned identities. SQL does not guarantee that an outer aggregate
preserves the order of its input subquery, so the selected prefix could be applied in a different
order from the documented retry policy.

The candidate now carries each selector's ordering fields through the bounded subquery and places an
explicit order inside the aggregate: T3 and VOID by failure count, creation time and change ID; T9
by failure count, update time and change ID; expired nonces by expiry time and nonce. This keeps the
array consumed by each loop aligned with the chosen prefix and makes the ordering requirement
explicit at the aggregation boundary.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`, `private_writer_recover_sweep_core_v1`: add
  explicit aggregate input ordering for c_t3, c_t9, c_void and c_nonce.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`:
  `S13-RECOVERY-AGGREGATE-BUDGET-01` requires rank retention in selected arrays and item/event
  outcomes.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`: records the source-only finding and
  deferred qualification.
- `docs/DOCUMENT_INDEX.md`: links this record.

Post-change SHA-256 after this turn's S13 changes: migration 027 `0B67136F873BC617FB61F4AC2497E6FC1FE8F4353347C9416CFD4441E3E56CA0`;
qualification prerequisites `55C7FDC67ACB7ABE9BA8C1B623E6F259FA7503BE693E5670F3EE262FF424E903`;
continuation prompt `B3DE9B4A11F3310586AC7BC33D2CF57BF96FB6DEB3394D3CD2AF79057E4D1575`;
document index `9D872F4765C803A9A6502FB913CBEB0D3E363F4A640DF5041DAD322DBCADF915`.

## Review, qualification and rollout

This source has not been parsed, independently reviewed or runtime-qualified. After coding closes,
`database-reviewer` should inspect the function's lock/FK/effect graph and serial ordering. The
`functional-test-reviewer` owns mixed-stage rank and exact outcome assertions; `e2e-runner` owns
repeated passes that prove bounded progress. Keep migration 027 uninstalled and candidate grants
disabled until source review, disposable qualification and effective-grant measurement pass. Do
not infer runtime ordering from the SQL source alone.
