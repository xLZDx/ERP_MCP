# S13 Claim-Token Lock-Order Qualification Mapping

## Change

Recorded the source-derived claim-token lock-order mismatch between the final
`complete_lock_busy` function and the recovery batch paths. Added qualification scenario
`S13-TOKEN-RANK-01` across every identified token-first caller: `begin_apply`,
`release_claim_internal`, `cancel_permit`, `permit_not_issued_internal`, `complete_lock_busy`,
`revoke_core`, and both recovery batches. It uses deterministic reversed token UUID/generation
ordering, bounded multi-change recovery, lock-state capture, serial-history assertions, and
no-partial-state checks. After applicable fences and the required early lifecycle-row validation,
the candidate plan must acquire namespace-6 keys for the record and all bounded sweep-counter/
failure identities in actual signed-bigint order before business-row locks. It then locks the parent
record first, followed by all token rows by `token_id ASC`; counter relation rows and secondary
effects follow their FK-component ranks.

## Why

The token table's primary key is `token_id`, while `(change_id,generation)` is a separate unique
constraint. `complete_lock_busy` currently locks by generation; recovery batches lock by token ID.
Those orders are not equivalent. With multiple generations, a reversed UUID ordering can make the
two paths visit shared rows in opposite orders. This establishes a possible wait cycle from source
ordering only; no deadlock has been reproduced.

## Affected contracts and paths

- `db/phase2/004_change_ledger.sql:309-315` — claim-token key definitions.
- `db/phase2/008_change_hardening_b.sql:960-1011` — `complete_lock_busy` current lock/effect order.
- `db/phase2/020_kill_switch_recovery_guard.sql:24,140-142` — recovery batch token and record locks.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md` — source-map finding and candidate order.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — scenario mapping.

## Verification state

Static source inspection only. No tests, checks, builds, migrations, database changes, service
restarts, or runtime contention scenarios were run. The candidate order is not implemented or
qualified. S13 remains blocked on completion of the all-path fence design/source work and subsequent
disposable qualification.

## Ownership and next action

Operator: accountable task owner. Codex: executor. Functional/E2E roles own the later scenario
implementation and execution after coding is complete. Next: continue reconciling all granted
entry paths and trigger/conflict edges against the same FK-derived row order, then freeze the exact
candidate before the authorized disposable qualification phase.
