# Change record 130 — staged S13 lifecycle fence primitives

## Goal and decision

Add an optional, additive PostgreSQL lifecycle fence foundation without claiming S13 readiness. The complete startup/restore coordinator, authenticated anti-rollback checkpoint provider, READY transition, deployment composition point, and proof of every non-event mutation path do not exist. The safe local decision is to keep existing 001–021 scopes in `LEGACY` compatibility mode and make an explicitly started recovery permanently fail closed until a separately reviewed lifecycle implementation can prove readiness.

## Changes

- Added `db/phase2/022_lifecycle_epoch_fence.sql` with durable per-scope lifecycle state and monotonic epoch; recovery entry; unresolved-call count; permit epoch binding; and guards on dispatch permits and event inserts. `LEGACY` preserves pre-022 behavior. After explicit `RECOVERING`, event writes and dispatch permit changes are refused. There is intentionally no transition to `READY`.
- Added opt-in SQL function definitions and wrappers to `SqlChangeLedger`, outside the baseline `SPEC` map. The lifecycle fence is disabled by default; enabling it requires a `READY` result, which this migration cannot produce.
- Added an optional trailing `lifecycle_epoch` field to `DispatchPermit`, preserving its existing nine positional arguments.
- Recorded this as preparatory source work only. Formal S13 and G0–G8 statuses do not change.

## Affected contracts and paths

- `db/phase2/022_lifecycle_epoch_fence.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `src/business_ai_gateway/phase2/change_ledger/write_port.py`
- `docs/phase2/S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/sdlc/STATE.md`

## Verification state and limitations

- Implemented locally and tested by the required test agents on a disposable PostgreSQL container; this proves only the staged database primitives.
- `functional-test-reviewer` ran `$env:ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS = '1'; .\.venv\Scripts\python.exe tests/phase2/test_s13_migration022.py`: **PASS**. It verified LEGACY compatibility, authorization/scope rejection, unresolved-call count, epoch 1→2, permit identity plus persisted-epoch binding, refusal of a stale permit, event/permit refusal in RECOVERING, and reconnect persistence. Container `r2-s13-dump-258179eb3e4b-a`; migration SHA-256 `d477ece7db5375c61a6aad16670ccb947bbba795ddb34533188db662f66b2375`; test SHA-256 `e7aa15a8f3bd1cd874aab2de31d5da2c4979026bcf2dfb3ee4446b942a664b`.
- `e2e-runner` ran `.venv\Scripts\python.exe -u tests\phase2\test_s13_migration022_e2e.py`: **PASS, 2 focused journeys**. It verified separate-connection/reconnect fencing, scope isolation, unresolved-call handling, refusal of an event mutation and a distinct payload-verified dispatch, and stale permit rejection after a READY/epoch=2 state was injected only inside the disposable fixture. Container `r2-s13-dump-080668a5c22b-a`; migration SHA-256 `d477ece7db5375c61a6aad16670ccb947bbba795ddb34533188db662f66b2375`; E2E SHA-256 `e90a6031f675bfbea55df07a6b57801e233608268f22a818aabf75619a9b7629`.
- Fresh code review found no BLOCKER/MAJOR in the staged primitives after permit binding was added. Fresh DB review found no DB BLOCKER/MAJOR; it confirmed ownership, grants, scope filtering and row-lock serialization by source inspection. Security review found no new reachable bypass within the staged repository boundary.
- Reliability review identified MAJOR deployment gates: `lifecycle_begin_recovery` is callable by `worker_role` and permanently fences a scope because READY is absent; an already-admitted dispatch can outlive recovery start because the writer boundary is not integrated; and fence-row lock waits are not bounded here. These do not block the explicitly local-only preparatory scope, but prohibit applying/activating 022 in a shared/live environment and prevent S13 closure.
- Both runs used dirty worktree base HEAD `104b93a38a4767bb4dbbeaada4f83356003f17ae`; exact changed-file hashes above identify the tested content. Harness cleanup completed for both owned containers.
- No migration was applied to a shared or production database. No broad suite, CI, build, or general check was run.
- Documentation registry generator `node scripts/build_document_registry.mjs` was run before test execution; it exited without printed output. The registry will be refreshed after this change record update.
- Read-only source inspection found existing database test journeys explicitly apply migration ranges 001–007 or 001–021; no automatic 022 loader was found under `src/` or `scripts/`.
- The event trigger fences event-producing mutations and the permit trigger fences permit insert/update. Complete coverage of every state-only mutation and the physical writer call boundary is not yet proven. The writer-epoch API is now bound to scope, `change_id`, generation, and the epoch stored on that permit, but it has no real service caller in this repository and its transaction ends before an external call.
- Applying `lifecycle_begin_recovery` leaves a scope in `RECOVERING` indefinitely. Do not invoke it in a live or shared environment until the reviewed recovery-to-READY implementation and recovery procedure exist. No production use is authorized or claimed.

## Ownership and next actions

- Task accountability: operator delegated local project closure to GPT/Codex; GPT/Codex executes.
- Test ownership: `functional-test-reviewer` and `e2e-runner` must derive and run disposable-database scenarios after coding is complete.
- Database, security, and reliability lanes must review the final tested diff for lock ordering, RLS, complete mutation coverage, failure behavior, and stale-writer fencing.
- Next: retain this migration as unapplied local prototype; do not activate its worker recovery function in a shared/live database. Request exact-head GPT review before any push. Continue S13 only after designing and reviewing a safe recovery-to-READY coordinator, complete mutation coverage, bounded lock/retry behavior, and an actual writer/service admission protocol. S13 remains open until these and the external anti-rollback checkpoint requirements are met.
