# Change record: refine the S13 scope-fence implementation design

Date: 2026-10-22  
Scope: S13 database lock-order design; documentation only.

## What changed

- Added `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md` with the selected two-layer database design: a shared per-scope mutation fence plus canonical internal lock ordering, followed later by an exclusive recovery fence.
- Linked the design from `S13_WRITER_BOUNDARY_CLAIM_AND_RECOVERY_CONTRACT_2026-10-17.md` and clarified that the helper must be explicit and volatile rather than embedded in stable `assert_scope`.
- Recorded the direct design review under PM Bridge request `875580c2-0610-452c-bf74-678f455bf59e`, reply `cecff738-6524-4a08-8636-7c48575aaef5`: a shared fence alone does not prevent ordinary mutators from deadlocking under existing row/advisory inversions.

## Why

The existing S13 source inventory identifies mutation paths, conflicting local lock orders, and no proven all-path recovery order. The stable scope assertion is also used by read helpers. The new note makes the chosen fence boundary and the remaining work explicit before authoring an additive migration.

## Contracts and limits

- Normal mutators must acquire the same per-scope transaction advisory lock in shared mode before any other advisory/row/conflict lock; recovery later takes the matching exclusive lock first.
- Before that fence, perform only non-locking identity validation to derive its key; authoritative scope/lifecycle/epoch/admission checks run while holding the fence, avoiding stale pre-fence admission decisions.
- Internal lock ordering still must be normalized, including `validate`, event-trigger order, key-material locks, recovery helpers, and UPSERT conflict paths.
- A PostgreSQL fence does not span a physical COM call. The Ivan private writer still needs clone evidence for stable call-ID idempotency, stale-epoch rejection, outcome lookup, and a quiescence barrier.
- The local disposable database has no `change_ledger` schema; S13 effective grants remain `NOT_VERIFIED` there.
- This change does not modify SQL, apply a migration, qualify a runtime, enable recovery/`READY`, or authorize a shared/production write.

## Verification state

- Compared the design note to the source-final grant/lock inventory, mutation-fence coverage map, existing S13 contract, and the correlated GPT-PM design review.
- Read-only database-reviewer pass: suitable to commit as implementation direction; no BLOCKER or MAJOR findings. MINOR implementation follow-up before migration: define stable scope-to-advisory-key derivation, timeout configuration and SQLSTATE-to-refusal mapping, and prove coverage for every granted mutator/helper/trigger/conflict path. Role: `database-reviewer`; model: role default GPT-6 Luna; reasoning effort: not exposed in the returned agent metadata.
- GPT-PM first review (request `3dbd167c-1ce0-45fe-8d8c-7192419cedb8`, patch SHA-256 `530C6F065330927EE751C21E6E8ABE139555BDDD7624A6B76D2F3A36FE89358D`): APPROVE for one local documentation commit; 0 BLOCKER, 0 MAJOR, 1 MINOR. Finding: clarify that pre-fence work is only non-locking scope-key derivation and authoritative admission checks happen under the fence. This revision makes that distinction explicit; the new exact patch is awaiting GPT-PM review.
- No tests, checks, builds, CI, migrations, database writes, COM calls, or service actions were run for this documentation change.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Next: complete the exact grant/helper/trigger/conflict coverage map, then implement only the reviewed additive database-fence migration. Keep recovery and lifecycle `NOT_READY` until test-role and COM-clone evidence is complete.
