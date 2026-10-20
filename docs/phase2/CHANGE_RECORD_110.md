# Change record 110 — proceed with source-backed S13 hold refinement

## What changed

- Clarified that the pending PM addendum review for `RLC_UNCLEAN` does not block focused verification of the non-gating S13 prototype.
- Kept formal S13 approval and the final exact-head review as separate gates.

## Why

Migration 004's check constraint is the source of truth for the four permitted hold causes. Treating any active permitted cause, including `RLC_UNCLEAN`, as unresolved is a conservative fail-closed condition: it can retain a stop mode until the hold is explicitly cleared, but cannot enable effects while the hold remains active. This ordinary technical refinement is delegated and can be verified without waiting for a separate design decision.

## Decision and scope

- Proceed with focused tests for migration 020 using the complete four-cause active-hold set.
- Keep the PM addendum request outstanding for the final exact-head review.
- Do not mark formal S13, G1–G8, or Release 2 passed; no production authorization is implied.

## Verification state

- This record is a sequencing decision, not runtime evidence.
- S13 focused tests, database specialist review, and final exact-head PM approval: pending.

## Affected paths

- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md`
- `docs/phase2/CHANGE_RECORD_107.md`
- `docs/phase2/CHANGE_RECORD_108.md`
- `db/phase2/004_change_ledger.sql`
- `db/phase2/020_kill_switch_recovery_guard.sql`
