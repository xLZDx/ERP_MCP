# Change Record 274 — S13 lifecycle-trigger cutover

## Ownership and state

- Date: 2026-10-25.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: PostgreSQL ledger boundary; canonical individual maintainer is not established.
- State: candidate migration source updated; SQL parsing, migration execution, effective grants,
  and runtime qualification are `NOT_RUN` / `NOT_VERIFIED`.

## Change and reason

Migration 027 now removes the historical `dispatch_permit_lifecycle_guard` and
`events_lifecycle_fence_guard` triggers after installing the versioned caller bridges and
revoking the bypass routes, within the candidate migration's existing transaction. The candidate
also revokes the exact `lifecycle_writer_epoch(text,text,uuid,bigint,bigint)` signature from
`PUBLIC` and every runtime role. It retains `events_chain_guard`, which remains the event-chain
serialization and integrity boundary. This closes the source inventory's lock-order finding:
the old lifecycle row triggers could acquire `lifecycle_fences` only after relation locks and,
for events, after `events_chain_guard` had acquired the final namespace-1 lock.

The change does not edit historical migrations or install migration 027. It is a source candidate
only and is not authorization to enable the S13 feature flag, start a writer listener, or invoke
COM. Qualification `S13-LIFECYCLE-TRIGGER-CUTOVER-01` requires exact installed trigger and effective
privilege state plus proof that all enabled versioned mutations own lifecycle checks before row
locks.

## Evidence and limits

- Source inventory: `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`,
  section “Lifecycle/event trigger lock correction”.
- Historical source: `db/phase2/022_lifecycle_epoch_fence.sql` creates both row triggers and grants
  `lifecycle_writer_epoch` to `writer_role`; `db/phase2/024_restore_caller_lock_timeout.sql`
  restores their lifecycle-row locking behavior.
- Candidate source: `db/phase2/027_private_writer_admission_schema.sql:12022-12036`.
- Candidate SHA-256:
  `B864325AF6480D39EFCBF7E32EFD70A41B5765E0076A46928379CD8B05B8D4C6`.
- `S13-LIFECYCLE-TRIGGER-CUTOVER-01` was added to
  `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`.
- No test, check, build, CI, SQL parser, migration, database operation, COM operation, stage,
  commit, or push was run for this change.

## Remaining acceptance and next step

This change is source-reviewed only by the executor. The full S13 source/review phase remains open;
the candidate is uninstalled and runtime grants are not measured. After coding closure, the
database reviewer must review the exact candidate diff, then the functional/E2E owners can parse
and qualify it on the approved disposable database. Accountable owner: operator; executor: Codex;
database reviewer owns independent database review; no individual reviewer or database service
maintainer is identified in the inspected source records.
