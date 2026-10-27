# S13 lifecycle-row lock-rank reconciliation

## Goal

Make migration-027 candidate lock acquisition match the accepted protocol in `S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, §§“Canonical advisory rank” and “Complete lock-plan contract”: namespace 2 when required, namespace 8 for private-base operations, namespace 7, the single early lifecycle-row lock, verifier-material locks, namespace 5 when required, sorted namespace-6 identities, namespaces 3–4, remaining FK-ranked relation rows, and namespace 1 event-chain work last.

## Non-goals

This does not claim a complete writer graph, effective privilege closure, deadlock freedom, installed migration, or runtime qualification. It does not enable the adapter flag, add candidate grants, change legacy routes, or change the physical COM boundary.

## Design and decision

Two orders were considered:

1. Acquire global namespace-6 identities before the lifecycle row. This shortens the time holding the lifecycle row but conflicts with the accepted contract's lifecycle-first exception and can let a transaction take later-ranked work without the lifecycle state fence.
2. Acquire the lifecycle row immediately after namespace 7, then every remaining ranked advisory identity before any other relation row. **Chosen:** preserve the existing accepted design and update candidate code/qualification to match it.

The bounded, non-locking plan and candidate IDs are prepared first. Private-writer paths take namespace 8 before namespace 7. The lifecycle row is then locked and validated in the next statement. Verifier material and sorted global IDs follow while that row remains held; all other relation rows and unique arbitration follow the advisory plan. The lifecycle row is the sole early relation-row exception. The changed candidate functions in migration 027 include evidence registration, barrier acknowledgement, barrier open/finalize, registry approval/revocation, and other namespace-6 writers. Direct verifier revocation reads key material before locking and updates only that observed immutable identity.

## Failure modes

An incomplete or changed lock plan must fail as `LOCK_PLAN_STALE` before DML; wrong lifecycle state/epoch refuses before candidate writes. A missing-key revocation remains a no-op if registration occurs after its non-locking observation. Advisory collisions may add serialization; durable constraints remain authoritative. Source order alone cannot prove behavior or safety for unreviewed legacy callers.

## Rollout and rollback

This is source-only in an explicitly revoked additive migration. Keep the schema uninstalled, candidate EXECUTE grants absent, legacy routes default, and the feature flag off. Revert only through a reviewed local change before any install; no migration or runtime rollback is needed because none is authorized here. Do not push/PR without fresh GPT-PM approval for the exact final code head.

## Test and evidence plan

After all coding closes, `functional-test-reviewer` and `e2e-runner` must execute the mapped S13 lock-rank scenarios, including verifier registration/approval/revocation, evidence registration/revocation, barrier creation/ack/finalization, stale-plan refusal, no-partial-state, and complete row/event order. Then obtain the relevant database/reliability/security reviews. For this change, only manual source inspection and an in-memory text-order scan were performed; no SQL parse, tests, checks, migration, database access, or COM call ran.

## Unknowns and ownership

Installed effective grants, the full reachable legacy/candidate lock graph, disposable runtime races, and the actual transaction boundary remain `NOT_VERIFIED`/`NOT_RUN`. Accountable task owner: operator; executor: Codex. The `database-reviewer` role owns later privilege/lock review, while `functional-test-reviewer` and `e2e-runner` own the later mapped behavior scenarios.
