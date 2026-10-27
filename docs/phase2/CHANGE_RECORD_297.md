# Change Record 297 — bound revoke-stale resource snapshots and lock acquisition

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 recovery path.
- Acceptance: `S13-REVOKE-STALE-BATCH-RANK-01`.
- State: source-only candidate. No tests/checks/build/CI, SQL parse/migration, database operation, stage, commit, or push ran.

## Finding and change

`revoke_stale_v1` chooses a batch using conservative lock/effect estimates, but resource-plan aggregation, post-fence child-row lock loops, and snapshot rechecks were not independently capped. A legacy mutation that bypasses namespace 7 could enlarge a frozen plan before those loops. The target registry is unique by `(tenant_id,company_id,base_fingerprint)`; target-lock rows, in contrast, can have distinct `target_ref` values under one base and require the composite order.

Migration 027 now caps the token, target, target-lock, key-lock, reservation, lease, and failure snapshots/rechecks at 201 rows and refuses a planned set above 200 before ranked identity or relation-row locking. Target-registry snapshots and locks use their primary-key order `(base_fingerprint)`; target-lock snapshots and locks use `(base_fingerprint,target_ref)`. Post-fence child-row lock loops are capped at 201; changed plans fail with `LOCK_PLAN_STALE` before the first revoke item can mutate state.

## Acceptance and evidence boundary

The existing `S13-REVOKE-STALE-BATCH-RANK-01` scenario now requires: (1) over-200 snapshots refuse before row locks/DML; (2) a mutation between the frozen snapshot and lock phase acquires no more than 201 rows and returns stale with no batch effects; and (3) multiple target-lock rows for one base lock and compare in `(base_fingerprint,target_ref)` order, while the one-per-base target registry uses its primary-key order. Runtime qualification remains `NOT_RUN`.

Manual source inspection only. Migration 027 remains unparsed, uninstalled and ungranted; effective privileges are `NOT_VERIFIED`. No tests, checks, build, database/COM operation, migration, stage, commit, or push occurred. Preserve the existing 200-row batch ceiling.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — bound `revoke_stale_v1` snapshots, row locks and revalidation; make target lock order total.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — add falsifiable source/runtime acceptance.
