# Change record: reconcile S13 advisory namespace allocation with source

Date: 2026-10-22
Scope: append source-backed namespace allocation and the proven kill-switch-to-sweep edge to the S13 source inventory.

## What changed

- Recorded the current namespace assignments for event-chain, kill-switch, hold, and business-key locks from migration 008.
- Recorded that migration 020 already uses namespace 5 for both stale-revoke and sweep recovery.
- Reserved namespace 6 for future global caller-ID locks and namespace 7 for the future scope fence; neither exists in migrations 001–026.
- Made the source-proven `2 → 5` dependency explicit and distinguished it from the unproven later edges in the candidate rank.
- Recorded the current namespace limitation of `lock_ns()` and the need to extend it or define a separate future primitive.
- Preserved recovery refusal and `NOT_READY` while full path coverage and physical-writer qualification remain open.

## Why

The initial S13 proposal assigned the new scope fence to namespace 5. Source inspection found that migration 020 already uses namespace 5 for sweep serialization and that `kill_switch()` holds namespace 2 before calling `recover_sweep()`. This record fixes the source inventory so later implementation work starts from the actual resource allocation and dependency edge.

## Contracts and paths

- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: source evidence, candidate rank, and remaining proof limits.
- `db/phase2/008_change_hardening_b.sql:1512-1521,1541-1550`: current named namespace mapping and kill-switch acquisition.
- `db/phase2/020_kill_switch_recovery_guard.sql:9-15,38-55,451-462`: sweep lock and kill-switch recovery call.
- `core/LESSONS_LOG.md`: source-proven dependency ordering lesson.

## Verification state

- Manually inspected the cited migration definitions read-only.
- No migration, database operation, test, check, build, service, or production path was run or changed.
- Namespace 5/2 source facts are confirmed; the full lock graph and future rank remain **UNPROVEN / NOT_IMPLEMENTED**.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Technical owner of the host/connection: Ivan stack; it does not own the local PostgreSQL migration protocol.
- Next: reconcile each namespace and row/unique-conflict edge against every granted mutator and helper, then obtain database/reliability/security review before migration implementation.
