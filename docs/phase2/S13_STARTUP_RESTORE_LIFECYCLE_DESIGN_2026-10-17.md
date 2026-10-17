# S13 startup and restore lifecycle design

**Status:** revised after independent security/reliability review; staged fail-closed fence primitives are implemented locally under CR130. CR131 adds a read-only checkpoint preflight and test-sink latest lookup, but deliberately cannot return READY. It does not provide complete S13 lifecycle acceptance. Formal S13 entry remains `NOT_STARTED` / `NOT_APPROVED`.

## Goal

Connect the existing PostgreSQL ledger integrity, external checkpoint, and bounded-recovery functions to an explicit service startup/restore admission sequence. A worker must not accept effectful work until the chain is verified, the local head is compared with an authenticated checkpoint outside the database trust boundary, and bounded recovery is complete.

## Current behavior and constraints

- `SqlChangeLedger.invoke()` opens one database transaction per SQL function and commits before returning. Lifecycle sequencing therefore crosses committed transaction boundaries and must remain fail-closed if any step fails.
- `SqlChangeLedger.verify_chain()`, `check_anchor()`, `recover_sweep()` and `recover_sweep_params()` are thin wrappers. No application startup, reconnect, or restore caller currently coordinates them.
- `CheckpointSink` supports `write()`, `read_back()`, and `latest(scope)`. The latest contract requires an exact-scope, authenticated, anti-rollback provider result; `InMemoryCheckpointSink.latest()` only selects the highest sequence in its TEST ONLY memory store. `FakeSigner` and `FakeVerifier` are TEST ONLY; `DispatchGate` refuses them for permits.
- `LifecycleCoordinator.preflight()` verifies the ledger chain, reads and validates the latest checkpoint signature and scope, then returns `NOT_READY/SHARED_FENCE_UNAVAILABLE`. It is diagnostic only: it does not inspect the ordered suffix, recover rows, acquire a cross-process fence, or authorize dispatch.
- Existing SQL routines and migrations are prototypes. This design does not treat them as formal S13 acceptance, production readiness, or an authorization to enable real writes.

## Options and decision

1. **Additive shared-fence database contract plus provider-neutral coordinator (recommended local engineering):** inventory and fence all mutation/permit/dispatch paths, add monotonic lifecycle epoch and suffix query, then implement orchestration against TEST adapters. Defer selection and qualification of an external provider and signer/key custody to the separately recorded S11 decision.
2. **Defer S13 lifecycle source work until a deployed service and external checkpoint contract exist:** this avoids building an unwired adapter but leaves the startup/restore defect unresolved in the local prototype.

Decision for local engineering: use option 1. CR130 implements only the preparatory database fence primitives. They intentionally have no READY transition because complete mutation-path coverage, suffix classification, and an authenticated anti-rollback provider are not established. A coordinator by itself remains insufficient. This does not invent an external account or claim that an in-memory sink meets CT5. Before formal S13 completion, the external provider, signer, custody owner, authenticated anti-rollback latest read, and retention/immutability evidence must be resolved and qualified.

## Design

Add a small `change_ledger.lifecycle` coordinator with an explicit per-scope readiness result. The current preflight is not wired to a service composition; no web framework, scheduler, or production app lifecycle is invented because none exists in this repository. Admission remains disabled because this implementation has no READY-producing path.

The sink protocol gains a read-only `latest(scope) -> CheckpointRecord | None` operation. The TEST-only in-memory implementation returns the greatest stored sequence for the exact tenant/company scope. The lifecycle coordinator:

1. Before taking the verification snapshot, obtain a cross-process per-scope admission fence that conflicts with every ledger mutation and dispatch transition. The fence must account for already-issued/in-flight dispatch permits, survive stale-process races, have bounded acquisition, and be released on every exit; losing its owning DB session invalidates readiness. The current per-process flag and migration 020 sweep lock do **not** provide this guarantee. CR131 does not acquire this fence and therefore cannot return READY.
2. Call `verify_chain()`. A failed or unavailable result keeps the scope unready and does not call `check_anchor()`; the SQL routine can append an `ANCHOR_GAP` event, so do not mutate a chain already known invalid.
3. Read the provider-authenticated, anti-rollback latest record and validate signature plus exact `tenant_id`/`company_id` equality with `Scope` before any SQL call that can mutate state. A signature alone does not prove latestness. If the provider cannot prove monotonic latest history (or equivalent anti-rollback consistency), remain NOT_READY.
4. Confirm the checkpoint is an exact ancestor `(seq, head_hash)` in this scope. `check_anchor()` only checks membership and may append an `ANCHOR_GAP`; it does not prove latestness or classify later events. Query/classify the ordered suffix after the checkpoint against the explicit S12 checkpoint policy: T10, T13 and observation reads may remain in the tail only where their complete transition/evidence state matches the contract; any effect, authorization, terminal, hold, or other checkpoint-required event makes the scope NOT_READY. Do not require checkpoint equality with the current head: S12 §9 explicitly allows these resolution/observation events to be included in the next checkpoint. Missing anchor, ledger behind anchor, invalid chain, disallowed tail, wrong scope, or unavailable evidence stays fail-closed.
5. Run bounded JSON `recover_sweep_params()` only after the fenced chain/anchor/suffix checks pass. Any error, eligible remaining work, unresolved item, or non-STOP safety condition keeps the scope unready; the legacy integer sweep result is insufficient. Re-run chain and suffix checks after recovery against the same authenticated latest record. If recovery creates a checkpoint-required event, write/read-back/authenticate and record a new checkpoint before admission.
6. Return READY only while the shared fence remains valid and every check passes. A later reconnect/restore invalidates prior readiness and repeats the sequence. Fence loss, verifier/provider failure, timeout, or retry exhaustion yields structured NOT_READY with reason and last-attempt metadata. No failure is converted to success; retries are bounded with backoff; no database transaction is held across sink I/O.

Genesis handling stays conservative: a non-empty ledger with no external anchor is unready. Provisioning an initial anchor is a separately authorized bootstrap operation, not an implicit startup side effect. An empty scope may become ready only under an explicit, tested genesis policy; otherwise it stays unready until provisioned.

## State ownership and failure behavior

- The PostgreSQL ledger owns transactional change state; the external store owns its independently retained checkpoint history; the signer/verifier boundary authenticates checkpoint content.
- The coordinator owns the process-local readiness decision and a lease on a shared per-scope fence. It does not clear database holds, authorize a write, or release `SAFE_HOLD` by itself.
- Checkpoint read/authentication failure, invalid chain, anchor mismatch, recovery error, unresolved work, or post-recovery checkpoint failure yields NOT_READY and zero downstream writer calls.
- Concurrency is **not yet proven fenced**. Existing SQL scope locks and the migration 020 recovery advisory lock do not couple all writers, dispatch transitions, and startup verification. The implementation design must identify one shared fence protocol and enumerate every mutation/dispatch path that honors it, including crash release, stale-process fencing, and in-flight calls. Until a database review confirms full coverage, the coordinator must remain NOT_READY; a per-process mutex/readiness flag is not an acceptable substitute. No long-running DB transaction may span external I/O.

## Required shared-fence contract before implementation

The database reviewer found no existing lock that can provide this lifecycle boundary. The smallest safe contract to design is an additive per-scope lifecycle state with a monotonically increasing fencing epoch:

1. Startup/recovery atomically transitions the scope to `RECOVERING` under the exclusive per-scope fence and increments the epoch. All ledger mutations, permit issuance, and dispatch compare-and-set paths must participate in the same scope fence within their short transaction and refuse while recovery is active.
2. The writer checks the current lifecycle epoch in the same transaction as the immediate pre-call dispatch CAS. A stale process or cached permit from an older epoch cannot call the external writer. Session loss invalidates cached readiness.
3. Recovery holds the durable `RECOVERING` state across short transactions and sink I/O without holding an open database transaction. It must not declare READY while any possibly executing call or unresolved `APPLYING`/`APPLY_UNKNOWN`/`CALL_OWNERSHIP` state lacks independent completion evidence; the fence does not cancel a physical call already sent.
4. Add a read-only ordered suffix query/result and classify every event after the authenticated checkpoint ancestor under S12 §9 with its associated transition/evidence state. Recheck epoch, chain, suffix, recovery report, and unresolved-call state atomically before transitioning to READY.
5. Inventory every relevant SQL mutation/API and physical dispatch edge; database review must confirm complete coverage. Recovery fencing and ordinary writes must have explicit lock order, bounded waits, crash recovery, and observable NOT_READY causes. Existing `chain`, `sweep`, and kill-switch locks alone are insufficient.

This is a design boundary, not an already accepted SQL implementation. It will require additive migration/API work and new database-focused story coverage. Do not start a coordinator that can return READY before this contract is reviewed and represented in the implementation scope.

## Rollout and rollback

The implementation remains unwired library code until a real service composition exists. Existing `DispatchGate` behavior stays fail-closed and TEST doubles remain rejected. Rollback removes the coordinator call and protocol addition; no prior migration is edited and no data migration is needed. Formal enablement requires a qualified external sink and signer, a deployment-specific bootstrap plan, and independent restore/custody evidence.

## Acceptance and test handoff

After all S13 local coding is complete, `functional-test-reviewer` and `e2e-runner` own focused PostgreSQL scenarios mapped to V2-S13-01..05 and E13/E18/E25/E31/E32/E36/E38. Lifecycle cases must assert exact call order and zero writer calls for invalid chain, stale/missing/forged anchor, anti-rollback failure, wrong tenant/company, disallowed uncheckpointed suffix, sink outage, incomplete recovery, post-recovery checkpoint failure, fence contention/loss, stale process, and in-flight dispatch. Verify the explicitly allowed S12 tail is accepted only when every event is allowed and its transition evidence is consistent. Include multi-process locking, dump/restore and tenant/company isolation in the story-mapped suites. A TEST sink proves orchestration only; report real provider/key custody and production startup evidence as `NOT_RUN` with exact dependency.

Then database-reviewer reviews migration/transaction/RLS/restore implications; reliability-reviewer reviews restart/reconnect and readiness failure handling; security-reviewer reviews signer and trust-boundary claims. Do not claim formal S13 passage from local synthetic tests.

## Unknowns and dependencies

- External checkpoint provider, authenticated latest-record API, immutable retention guarantees, signer implementation, key custody, and responsible service owner are not established in canonical records.
- The deployment service composition and readiness/admission hook do not exist in this repository. Integration cannot be claimed until that service is identified.
- No shared lifecycle/admission fence currently couples the complete set of SQL mutation and physical dispatch paths. CR131 implements only a read-only preflight; identify and review the additive DB/API contract before implementing a READY-producing coordinator.
- The sink protocol and provider contract do not yet establish authenticated anti-rollback `latest(scope)` semantics. A valid signature on an old record cannot prove the external store was not rolled back.
- The safe genesis/bootstrap operation needs an explicit contract before any real environment is initialized.
- The S13 nonce/record lock-order MINOR and deterministic contention scenario remain deferred to S18 per the existing ruling.
