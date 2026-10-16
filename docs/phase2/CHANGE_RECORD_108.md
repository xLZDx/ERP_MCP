# Change record 108 — include every allowed active hold in S13 recovery

## What changed

- Updated the S13 design's `has_unresolved` predicate to include all four active hold causes permitted by migration 004: `CALL_OWNERSHIP`, `FAILED_VERIFY_HALT`, `ANCHOR_GAP`, and `RLC_UNCLEAN`.
- Recorded why an active unclean-restart hold must prevent the kill switch from reaching `OFF`.

## Why

The first design predicate named only three hold causes. Migration 004's `change_ledger.holds.cause` constraint also permits `RLC_UNCLEAN`; omitting it could classify an incomplete restart recovery as resolved. Including it is a conservative refinement of the accepted recovery invariant.

## Decisions and scope

- Preserve the rule that any active unresolved hold blocks OFF.
- No schema or runtime behavior is changed by this design record. Migration 020 implements the predicate; PM confirmation for this refinement is requested before focused test work.
- This record does not claim formal S13 or G1–G8 closure.

## Review and verification state

- Source evidence: `db/phase2/004_change_ledger.sql` constrains `cause` to the four values listed above.
- PM Bridge addendum review: pending.
- Tests, SQL checks, database commands, migration execution, and runtime evidence: `NOT_RUN`.

## Contracts and paths

- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md`
- `db/phase2/004_change_ledger.sql`
- `db/phase2/020_kill_switch_recovery_guard.sql`
