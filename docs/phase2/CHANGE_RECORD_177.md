# Change record 177 — T16 checkpoint holds and replay

## Scope and reason

The S13 T16 path must retain stop-effects protection from the committed operator decision until
its exact event head is externally written, read back, and recorded as a verified REAL checkpoint.
The SQL entry and post-commit continuation also need to recover from a lost response or a partial
hold-release result without changing the decision or releasing an unrelated hold.

## Changes made in this turn

- Added scope-wide `ANCHOR_GAP` hold insertion to candidate
  `change_ledger.operator_resolve_v1`, using the bounded, locked target-base plan and the exact hold
  IDs returned in the immutable `OPERATOR_RESOLVE` event.
- Changed the candidate T16 replay checks to return an exact prior event before requiring open
  holds or rebuilding a now-stale bounded target mutation plan. New T16 decisions still require one
  open call-ownership hold and no existing scope anchor gap.
- Corrected `release_hold_v1` control flow so an unlinked `CALL_OWNERSHIP` hold always fails closed;
  a resolution-linked hold requires the exact event ID and a verified REAL checkpoint for that
  event, while legacy `ANCHOR_GAP` and unclean-restart release rules stay in separate branches.
- Made `record_checkpoint` return an already verified exact signed checkpoint row on retry, while
  still verifying and inserting new signed records under the same-scope fence.
- Added `SqlChangeLedger.operator_resolve_s13`'s explicit schema-mode guard and result validation,
  plus `DispatchGate.resolve_t16_s13` to sequence T16, exact checkpoint/read-back,
  database checkpoint registration, and linked-hold releases.
- Made an ambiguous external checkpoint write recoverable only by reading back the exact expected
  signed record. A mismatch or unavailable read-back leaves database holds in force.

## Decisions and boundaries

- The old boolean T16 route is not used by the new path. Migration 027 keeps the S13 operation
  candidate-only and revoked; this record does not assert callable grants or a deployed cutover.
- `APPLY_UNKNOWN` still needs the private writer's separate `record_recovered_terminal` transition
  after checkpointing. Its database routine requires the exact verified checkpoint before clearing
  the durable physical-base slot.
- The checkpoint sink, trusted active public-key composition, anti-rollback provider guarantee,
  listener/API composition, migration application, disposable qualification, and writer runtime
  are not established by this source change.

## Review and verification state

- Source-only manual review identified and corrected missing anchor-hold insertion, T16 replay
  ordering, checkpoint retry duplication, and `release_hold_v1` branch nesting.
- No tests, checks, SQL parser, build, migration, database query, COM operation, service restart,
  staging, commit, or push was run in this turn. SQL behavior and the resulting Python path remain
  `NOT_RUN` / `NOT_VERIFIED` pending coding completion and the authorized qualification phase.
- Accountable task owner: operator. Executor: Codex. The technical owner of the installed private
  writer stack remains the Ivan stack identified in its existing project record; this source-only
  change does not establish runtime ownership of the checkpoint provider.
