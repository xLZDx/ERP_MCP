# Change Record 296 — reject mismatched resource FK owners before row locking

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer on the Ivan stack.
- Acceptance: `S13-FK-RESOURCE-OWNER-SCOPE-01` and `S13-CLAIM-PARENT-RANK-01`.
- State: source-only candidate change. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Baseline and finding

The legacy schema defines `target_locks`, `key_locks`, and `writer_leases` with a foreign key from `owner_change_id` to the globally unique `records(change_id)` (`db/phase2/004_change_ledger.sql`, lock definitions). The foreign key does not encode tenant, company, or base fingerprint.

`claim_v1`, `release_claim_v1`, `revoke_change_v1`, `retry_verify_v1`, `private_writer_recovery_permit_v1`, `private_writer_recovery_t5x_v1`, `cancel_permit_v1`, `operator_close_failed_verify_v1`, and `operator_resolve_v1` freeze or inspect selected resource rows whose `owner_change_id` is a FK to `records(change_id)`. The FK does not encode tenant, company, or base. Several later record-lock loops filter by tenant/company; `claim_v1` and `cancel_permit_v1` did not refuse an omitted selected owner, while `retry_verify_v1` did not include its selected target-lock owner in the global-ID/parent-lock plan. A same-scope owner with a mismatched base also violates the resource-to-record identity invariant. Existing owner-scope checks cover rows owned by the selected change, not every selected competing target/key/lease row; the operator-resolution follow-up now explicitly checks its selected target and lease owner before release or handback. The target registry is one row per base (primary key in `db/phase2/004_change_ledger.sql`), while target-lock rows carry `target_ref`; namespace-4 target identities therefore come from the frozen target-lock plan, alongside frozen business-key identities, not from target-registry rows.

## Change

Added the revoked helper `private_writer_assert_planned_resource_owner_scope_v1`. After the namespace-6 identity fences and before namespace-4/resource locks, the affected routines now refuse with `LOCK_PLAN_STALE` if any planned record ID is absent/out of scope, or a selected target/key/lease owner is absent from the parent plan or does not match the resource row's tenant, company, and base fingerprint. `retry_verify_v1` now includes selected target-lock owners in sorted namespace-6 fences and locks the complete parent-record set before target-lock rows. `operator_close_failed_verify_v1` applies the same parent/target lock-owner check to its cosign-close plan. A follow-up source pass also applies the exact selected target/lease check to `operator_resolve_v1` before namespace-3/4 locks and resource release/handback. That path's single sorted namespace-4 set includes the frozen target-lock and business-key lock identities using the same keys as their competing claim paths. Its target/key/lease plans now cap collection at 201 rows and reject above 200 before locking; post-fence target/key child locks are likewise capped at 201 and changed snapshots refuse. The lifecycle row is checked only after namespace-3/4 advisory acquisition. Existing locked snapshot comparison still rejects plan changes after namespace-4 arbitration.

Added `S13-FK-RESOURCE-OWNER-SCOPE-01` to the disposable qualification prerequisites. It covers all nine entry points, cross-scope and cross-base owner fixtures, sorted parent-before-child ordering, refusal before resource relation-row locks, and zero state/event delta. Runtime acceptance remains `NOT_RUN`.

## Affected paths and contracts

- `db/phase2/027_private_writer_admission_schema.sql` — add the revoked owner-scope helper and apply it to the nine reviewed resource-owner paths; extend retry-verification's global-ID and parent-row plan.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — define the source and later disposable acceptance boundary.

## Verification state

Manual source inspection only. The candidate migration was not parsed, installed, granted, or executed. No DB operation, tests, checks, build, COM call, stage, commit, or push occurred. Effective privileges remain `NOT_VERIFIED`; the claim scenarios remain `NOT_RUN`. This change does not establish a production writer or physical transaction boundary.
