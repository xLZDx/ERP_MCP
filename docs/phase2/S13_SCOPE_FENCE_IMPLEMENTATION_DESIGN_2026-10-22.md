# S13 scope-fence implementation design

Date: 2026-10-22. Status: implementation direction for source work; not migration approval, runtime qualification, or S13 acceptance.

## Goal

Establish one database ordering point between scoped mutators and recovery without holding a PostgreSQL transaction across checkpoint I/O or a COM call. Preserve the operator-selected private Ivan COM boundary and keep lifecycle `NOT_READY` until both database and physical-writer barriers are qualified.

## Constraints and current behavior

- The source-final inventory records conflicting paths: `validate(text,text,uuid)` locks a record before `A:key`; the event trigger sequence can request the chain advisory lock before the lifecycle row; named key-material advisory locks and unique-conflict arbitration also participate in ordering.
- The recovery entry point remains refused by migration 023. Existing source does not prove a global lock order.
- `change_ledger.assert_scope` is declared `STABLE` and is used by stable readers such as `amount_consumed` and the checkpoint-suffix reader. It must remain a scope assertion; adding an advisory lock there would make the stable contract misleading.
- The current disposable database has no `change_ledger` schema. Effective S13 grants are `NOT_VERIFIED` there.

## Options and decision

1. **Shared per-scope fence plus canonical internal lock order — selected.** It excludes recovery from all participating mutations while allowing compatible scoped operations to proceed concurrently. It is viable only if every mutating API and delegated mutation path acquires it first and all internal ordering conflicts are corrected.
2. **Exclusive per-scope fence for every API call.** This is a conservative fallback if source-wide ordering cannot be established, but serializes unrelated writes and readers within a tenant/company and adds unmeasured contention. It still does not fence COM after transaction commit.
3. **Manually place fences without one enforced entry point.** Rejected as the primary approach because omitted helpers, triggers, recovery stages, or future mutation paths can bypass it.

This selection follows the design review correlated to PM Bridge request `875580c2-0610-452c-bf74-678f455bf59e`, reply `cecff738-6524-4a08-8636-7c48575aaef5`. That review explicitly found a shared fence by itself insufficient: shared mutators can still reproduce a row/advisory inversion.

## Design

- Add a dedicated `VOLATILE` mutation-fence primitive. Before the fence, perform only non-locking identity validation needed to derive the canonical scope/fence key. Acquire the per-scope transaction advisory lock in shared mode before any other advisory lock, row lock, or conflict-arbitrating write. While holding it, perform the authoritative scope, lifecycle, epoch, and admission checks; only then may the path acquire its other locks or mutate. Recovery will acquire the same key exclusively before changing recovery state or epoch.
- Do not add lock acquisition to `assert_scope`; stable read APIs remain outside the mutation-fence path. Enumerate every externally granted mutator, delegated leaf, trigger-mediated write, recovery stage, and kill-switch path, and prove each reaches the fence before any competing lock.
- Normalize post-fence ordering: namespace advisory locks in canonical order; claim-token rows; records in stable order; secondary rows; lifecycle row; event-chain advisory lock last. Rewrite the `validate` row-before-`A:key` path and correct event-trigger ordering. Include verifier-key locks and unique-index conflict paths in the source-wide map.
- A shared scope fence does not cover unique conflicts whose key omits tenant/company. The source-final inventory identifies caller-controlled global `records.change_id` (the original PK remains even after the later composite unique constraint); dependent conflict/key domains also carry or reference `change_id` in reservations, budgets, claim tokens, permits, business keys, evidence, receipts, and sweep counters/failures. `propose` is the record creator and takes the ID from its caller. `budget_admin` optionally accepts a caller `grant_id` and locks/creates that global PK. Add namespaced per-key locks for caller-controlled global identifiers after the scope fence and before row/conflict locks: at minimum `change_id`, plus an explicit `grant_id`; record-subject counters/failures reuse the `change_id` key. Acquire multiple IDs in a deterministic sorted order. Scoped keys such as `(tenant_id, company_id, ...)` remain covered by the scope fence when every path participates. Generated surrogate UUIDs remain protected by their unique indexes and do not justify global serialization. Current permits have no unique constraint on `call_id`; the new S13 admission schema must define its call-ID uniqueness domain explicitly.
- Bound fence waits with an explicit database timeout and stable refusal mapping. A timeout aborts the transaction and leaves recovery/admission fail-closed. Do not catch a timeout and continue within the same transaction.
- The database lock ends at transaction completion. The Ivan COM service must independently reject stale epochs, provide authoritative lookup by stable call ID, and complete a linearizable quiescence barrier before recovery can approach `READY`.

## Failure modes and rollback

- Missing fence on any granted path: that path is outside the recovery ordering proof; keep recovery refused.
- Shared fence acquired after a row/advisory lock: lock-order inversion remains; keep the migration unqualified.
- Fence timeout, database disconnect, or lost commit response: report an unknown/failed database operation with no retry of COM and no readiness transition.
- COM call unresolved after the database fence releases: keep the scope held and `NOT_READY`; only the physical boundary can resolve it.
- Rollback is forward-only: leave recovery disabled and dispatch fail-closed. Do not remove claims, clear holds, or replay physical calls as cleanup; do not edit migrations 022–024 in place.

## Rollout and verification plan

Implement an additive migration only after the full API/helper/trigger/conflict map is complete. Do not apply it during coding. After all in-scope code is complete, `functional-test-reviewer` and `e2e-runner` own mapped disposable-PostgreSQL scenarios for every mutator racing recovery, timeouts, lock-order contention, direct grants, tenant/company scope, and dump/restore. Database, reliability, and security reviewers then review the exact tested head. The separately authorized COM-clone qualification must prove physical idempotency, stale-epoch rejection, outcome lookup, and quiescence; SQL evidence cannot substitute for it.

## Remaining dependencies and owners

- Accountable task owner: operator; local executor: Codex.
- SQL lock-order and effective-grant review: database-reviewer; the inspected disposable database lacks `change_ledger`, so S13 effective grants remain `NOT_VERIFIED` until a suitable disposable schema is prepared after coding.
- Required runtime proof: Ivan stack technical owner for the host/connection boundary; Codex implements the private service; no clone qualification has established the physical contract yet.
- `READY` remains prohibited until every SQL path and the independent COM barrier are qualified and all accepted calls have independently terminal evidence.
