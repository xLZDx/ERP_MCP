# S13 startup and restore lifecycle design

**Status:** proposed local synthetic implementation; formal S13 entry remains `NOT_STARTED` / `NOT_APPROVED`.

## Goal

Connect the existing PostgreSQL ledger integrity, external checkpoint, and bounded-recovery functions to an explicit service startup/restore admission sequence. A worker must not accept effectful work until the chain is verified, the local head is compared with an authenticated checkpoint outside the database trust boundary, and bounded recovery is complete.

## Current behavior and constraints

- `SqlChangeLedger.invoke()` opens one database transaction per SQL function and commits before returning. Lifecycle sequencing therefore crosses committed transaction boundaries and must remain fail-closed if any step fails.
- `SqlChangeLedger.verify_chain()`, `check_anchor()`, `recover_sweep()` and `recover_sweep_params()` are thin wrappers. No application startup, reconnect, or restore caller currently coordinates them.
- `CheckpointSink` supports `write()` and `read_back()` only. Startup cannot discover a newer anchor from this interface. `InMemoryCheckpointSink`, `FakeSigner`, and `FakeVerifier` are TEST ONLY; `DispatchGate` refuses them for permits.
- Existing SQL routines and migrations are prototypes. This design does not treat them as formal S13 acceptance, production readiness, or an authorization to enable real writes.

## Options and decision

1. **Provider-neutral lifecycle coordinator and `latest(scope)` sink capability (recommended):** implement and test orchestration against the existing protocol, with only TEST adapters. Defer selection and qualification of an external provider and signer/key custody to the separately recorded S11 decision.
2. **Select and integrate a concrete external storage provider now:** this could advance deployed acceptance but would bind the project to an unrecorded service, account, network, retention policy, and key boundary.

Decision for local engineering: use option 1. It allows local fail-closed lifecycle code without inventing an external account or claiming that an in-memory sink meets CT5. Before formal S13 completion, the external provider, signer, custody owner, authenticated latest read, and retention/immutability evidence must be resolved and qualified.

## Design

Add a small `change_ledger.lifecycle` coordinator with an explicit per-scope readiness result. The service composition calls it on cold start, database reconnect, and after restore; no web framework, scheduler, or production app lifecycle is invented because none exists in this repository. The caller keeps admission disabled until the coordinator returns READY.

The sink protocol gains a read-only `latest(scope) -> CheckpointRecord | None` operation. The TEST-only in-memory implementation returns the greatest stored sequence for the exact tenant/company scope. The lifecycle coordinator:

1. Calls `verify_chain()` first. A failed or unavailable result keeps the scope unready and does not call `check_anchor()`; the SQL routine can append an `ANCHOR_GAP` event, so do not mutate a chain already known invalid.
2. Reads the newest record from the independent sink and authenticates its signature using the configured verifier. It compares sequence and hash with the local ledger using `check_anchor()`. Missing, stale, mismatched, unauthenticated, or unavailable external evidence keeps admission disabled and preserves/declares the applicable hold.
3. Runs the bounded JSON `recover_sweep_params()` routine only after chain and anchor checks pass. Any failure, eligible remaining work, unresolved item, or non-STOP safety condition keeps the scope unready; the legacy integer sweep result is insufficient for readiness.
4. Re-runs `verify_chain()` after recovery. If recovery appended events, writes a checkpoint for the resulting head, reads it back, verifies its signature and exact content, and records the checkpoint through the dedicated checkpoint role. Any failure keeps admission disabled.
5. Returns READY only after all applicable steps pass. A later reconnect/restore invalidates prior readiness and repeats the sequence. No recovery failure is converted into success, no write is retried, and no database transaction is held across sink I/O.

Genesis handling stays conservative: a non-empty ledger with no external anchor is unready. Provisioning an initial anchor is a separately authorized bootstrap operation, not an implicit startup side effect. An empty scope may become ready only under an explicit, tested genesis policy; otherwise it stays unready until provisioned.

## State ownership and failure behavior

- The PostgreSQL ledger owns transactional change state; the external store owns its independently retained checkpoint history; the signer/verifier boundary authenticates checkpoint content.
- The coordinator owns only the process-local readiness decision. It does not clear database holds, authorize a write, or release `SAFE_HOLD` by itself.
- Checkpoint read/authentication failure, invalid chain, anchor mismatch, recovery error, unresolved work, or post-recovery checkpoint failure yields NOT_READY and zero downstream writer calls.
- Concurrency remains fenced by the existing SQL scope locks and kill-switch routines. Startup orchestration is serialized per service/scope; no long-running DB transaction spans external I/O.

## Rollout and rollback

The implementation remains unwired library code until a real service composition exists. Existing `DispatchGate` behavior stays fail-closed and TEST doubles remain rejected. Rollback removes the coordinator call and protocol addition; no prior migration is edited and no data migration is needed. Formal enablement requires a qualified external sink and signer, a deployment-specific bootstrap plan, and independent restore/custody evidence.

## Acceptance and test handoff

After all S13 local coding is complete, `functional-test-reviewer` and `e2e-runner` own focused PostgreSQL scenarios mapped to V2-S13-01..05 and E13/E18/E25/E31/E32/E36/E38. Lifecycle cases must assert exact call order and zero writer calls for invalid chain, stale/missing/forged anchor, sink outage, incomplete recovery, and post-recovery checkpoint failure; a valid older local chain paired with a newer seeded TEST anchor must remain unready. Include multi-process database locking, dump/restore and tenant/company isolation in the story-mapped suites. A TEST sink proves orchestration only; report real provider/key custody and production startup evidence as `NOT_RUN` with exact dependency.

Then database-reviewer reviews migration/transaction/RLS/restore implications; reliability-reviewer reviews restart/reconnect and readiness failure handling; security-reviewer reviews signer and trust-boundary claims. Do not claim formal S13 passage from local synthetic tests.

## Unknowns and dependencies

- External checkpoint provider, authenticated latest-record API, immutable retention guarantees, signer implementation, key custody, and responsible service owner are not established in canonical records.
- The deployment service composition and readiness/admission hook do not exist in this repository. Integration cannot be claimed until that service is identified.
- The safe genesis/bootstrap operation needs an explicit contract before any real environment is initialized.
- The S13 nonce/record lock-order MINOR and deterministic contention scenario remain deferred to S18 per the existing ruling.
