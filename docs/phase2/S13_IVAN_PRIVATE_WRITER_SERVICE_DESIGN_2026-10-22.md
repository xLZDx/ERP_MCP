# S13 private writer service design for Ivan's licensed lane

Date: 2026-10-22  
Status: operator-authorized engineering design; implementation and runtime qualification remain open.  
Accountable task owner: operator. Technical owner of the Ivan host/connection boundary: the Ivan stack (`ERP_MCP_Ivan_Stack`), as recorded in `artifacts/REMOTE_1C_HOST_STACK_2026-10-11.md`. Codex is the delegated executor.

## Decision and scope

Build the S13 physical writer boundary as a separate private service on Ivan's licensed Windows lane, beginning with a disposable clone of `818HA_p2diff`. It must be reachable only through loopback or an authenticated, ACL-restricted Tailscale path; it must never be exposed through the public MCP tunnel. The service provides durable call-ID idempotency, rejects stale epochs at admission, offers authoritative outcome lookup by the immutable call identity, and implements a quiescence barrier that is serialized with admission. It does not add write methods to the public/read-only gateway.

This decision authorizes local implementation and qualification on disposable copies. It does not authorize deployment, writes to any live company base, or a claim that the current COM channel already supplies the required atomicity. Production authorization remains `NONE`; S13 and release gates remain open until their recorded acceptance evidence exists.

## Contract inherited from S12

The service is downstream of the frozen S12 contract in `S12_CONTRACT_FREEZE_V2_2026-10-16.md` and `S13_WRITER_BOUNDARY_CLAIM_AND_RECOVERY_CONTRACT_2026-10-17.md`:

1. The ledger durably commits the one-time `PERMITTED -> DISPATCHED` CAS and its audit event before physical I/O. The immutable identity includes the full scope tuple, `change_id`, generation, `call_id`, operation, target, epoch, and approved payload digest.
2. The service accepts a call ID at most once. An identical retry returns existing status; a conflicting identity or stale epoch is refused. An accepted call is never reissued to COM after timeout, disconnect, response loss, or restart.
3. The service's outcome lookup is authoritative only for its own durable accepted-call journal and bound service instance. It cannot claim that an effect occurred or did not occur based only on a marker, timeout, missing row, process exit, or absent response.
4. Recovery serializes a scope-wide epoch advance with new call acceptance, rejects delayed requests from older epochs, and enumerates calls accepted before the barrier. Every enumerated call must have independently established terminal evidence before readiness can advance. Any unknown, queued, or possibly executing call leaves the scope held and `NOT_READY`.
5. No PostgreSQL transaction or row lock spans checkpoint-provider I/O or COM. The application gateway remains read-only; only this separate private service may own the licensed COM write identity.

The S12 signed `DispatchReceipt`, independent `OutcomeEvidence`, `CompletionProof`, canonical payload rules, and operation scope remain distinct requirements. This design does not replace them with the service journal or the 1C marker attributes.

## Service boundary and ownership

The service is a separate process and deployment unit from the existing MCP gateway and `testlane.phase2_mcp` comparison server. Its only initial target is an isolated copy of `818HA_p2diff`; it must authenticate the base and verify its configured fingerprint before accepting any write-capable request. It uses the least-privilege `CT14Писатель` account and the already approved COM route. OData writes, public-tunnel ingress, administrator credentials, hard deletion, and writes to the immutable data template are out of scope.

The Ivan stack is the technical owner of host execution and the private connection boundary. This does not establish a separately named human service contact. The operator remains accountable for the delegated task. Database, security, reliability, functional-test, and E2E roles retain their review/test responsibilities; role names are not people.

## Admission, idempotency, lookup, and barrier

### Durable admission

Admission uses a new additive, versioned S13 contract; it does not edit migrations 022–024 in place or assume that the preparatory lifecycle API can enter recovery. Before the per-scope fence, the transaction may perform only non-locking identity validation needed to derive the canonical fence key. It then acquires the shared per-scope transaction fence before any other advisory lock, row lock, or conflict-arbitrating write. While holding that fence it performs the authoritative scope, lifecycle, epoch, admission, and approved-dispatch checks, then atomically inserts the unique accepted-call row using the reviewed internal lock order. A duplicate identical identity reads that row; a reused call ID with any differing field fails closed. The transaction commits before COM is entered.

The accepted-call record binds a non-reusable service process instance, host boot/service identity, optional 1C session instance, scope, target, operation, epoch, payload digest, dispatch CAS identity, monotonic state, and evidence references. It is append-only or otherwise monotonic. Its uniqueness and all foreign-key scope bindings are database enforced. A local process cache is never the idempotency source of truth.

### Physical invocation and result

Only the process that wins durable admission may invoke COM, and only once. Before entry it persists an invocation-stage transition tied to its process instance. The call result and signed receipt are committed through the S12 evidence path. A process crash or communication error after the invocation may have started leaves an unresolved call; a subsequent process may query and reconcile it but may not call COM again.

The outcome API returns a closed typed status such as `NOT_ACCEPTED`, `ACCEPTED_NOT_INVOKED`, `POSSIBLY_EXECUTING`, or `TERMINAL_WITH_EVIDENCE`, with the immutable call tuple and evidence reference. It returns no caller-controlled “success” flag. `ACCEPTED_NOT_INVOKED` is terminal only when a durable process-bound guard proves the mutating COM method was never entered. Terminal effect claims additionally require the S12 receipt, independent verification, and any required completion proof.

### Quiescence barrier

`fence_scope(scope, new_epoch, barrier_id)` is idempotent by `barrier_id`. Its linearization point is the transaction that acquires the exclusive counterpart of the same per-scope transaction fence, advances the durable epoch for the requested scope, and snapshots the complete set/watermark of calls admitted at older epochs. Calls submitted later with an older epoch are rejected. Calls already admitted remain owned and are not cancelled by the barrier.

The service waits only within an explicit bounded request deadline for eligible calls to become terminal. The response identifies the epoch, barrier, and complete pre-barrier accepted-call set/watermark; it never omits a call because of pagination or a local cache. If the result set is too large, the journal is unavailable, or any call remains queued/in flight/unknown, return a non-ready result and retain the hold. A timeout does not make a call terminal. Repeating the same barrier ID returns the same durable barrier record and monotonic progress.

### Persistence and restart

PostgreSQL is authoritative for scope epochs, accepted call identities, barrier records, and durable state/evidence references. COM work occurs outside database transactions. A restart reloads unresolved calls and refuses new admission for affected scopes until recovery re-establishes the writer barrier and resolves each call. PID, task state, connection close, and process death alone do not prove that the 1C operation stopped or had no effect. No lease-expiry shortcut may clear a hold.

## Lock, grant, and migration constraints

The 2026-10-22 source-final inventory (`S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`) identifies that source grants are not effective installed-grant evidence and reports an event-trigger order in which `events_chain` can acquire the chain advisory lock before the lifecycle row lock. It also finds that lifecycle triggers/API coverage do not establish one shared fence across all mutations, permits, and physical dispatch.

Therefore:

- Do not activate migrations 022–024 or treat `lifecycle_writer_epoch()` as a physical writer fence.
- Do not add a migration or `READY` transition until the full mutator, grant, trigger, row/advisory lock, unique-conflict arbitration, and writer-entrypoint map has a reviewed common ordering and every path participates.
- Preserve the event-chain lock as the last named lock; no path may wait for a row or scope fence while holding it. Reconcile the current trigger ordering before defining the additive migration.
- Keep the new service unavailable to application/read roles. Effective installed PostgreSQL grants must be read and recorded on the disposable database after migration qualification; source `GRANT` statements alone are not evidence.
- Keep five-second bounded lock acquisition/restoration behavior from migrations 023–024 when designing later additive paths; any changed bound or order requires explicit reliability review.

The current local disposable PostgreSQL instance was inspected read-only by the database-reviewer: it has no `change_ledger` schema, no matching grants or functions, and the connected admin role is highly privileged. This is source-independent evidence about that instance only; it does not establish grants on Ivan's host or any production database. No migration was applied for this design.

### Selected common-order and barrier protocol (design proposal; not implemented or qualified)

The selected direction is a shared per-scope transaction fence for ordinary scoped mutations and an exclusive acquisition of the same fence for recovery/barrier transitions, paired with a canonical internal lock order. This supersedes the earlier serial-singleton-mutex candidate in this document; do not implement the singleton-row proposal or its global `MUTATION_BUSY` behavior. The selection follows the correlated PM Bridge design review `875580c2-0610-452c-bf74-678f455bf59e` / `cecff738-6524-4a08-8636-7c48575aaef5` and is refined in `S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`.

Before the shared fence, perform only non-locking identity validation required to derive the canonical scope key. Acquire the shared fence before any other advisory lock, row lock, or conflict-arbitrating write. While it is held, perform authoritative scope/lifecycle/epoch/admission checks, then take the remaining locks in a reviewed canonical order. Recovery and `fence_scope` acquire the exclusive counterpart before changing recovery state, closing admission, advancing the epoch, or capturing the pre-barrier call set. The exact advisory-key derivation, timeout configuration and stable refusal mapping remain to be specified before migration design.

The source-final inventory must prove coverage for every runtime-granted mutator, delegated helper, trigger-mediated write, recovery stage, kill-switch path, direct-DML route, and unique-conflict arbitration point. A per-scope fence alone does not serialize concurrent mutators with each other and does not order a global unique-index conflict across different scopes. Therefore normalize the internal order and explicitly identify any cross-scope conflict domain; if it cannot be ordered safely under the scoped protocol, redesign before migration. Include `validate` business-key ordering, event-trigger/lifecycle ordering, verifier-key locking, recovery/kill-switch locks, and every `ON CONFLICT` target. Keep the event-chain advisory lock last; no path may wait on a row or another fence while holding it. No migration is authorized until database and reliability review accept the complete path map.

Fence acquisition uses a bounded wait and a stable refusal mapping. On timeout or SQL error, the operation aborts and the service rolls back and discards its fresh top-level transaction; it never catches the error in a savepoint and continues. No failure clears admission/barrier holds or fabricates an outcome. Revoke bypass DML and verify installed privileges; a statement trigger may be defense in depth but cannot repair an API that takes locks before entering the fence. No public/read role receives mutation authority. Owner/admin maintenance is a separate quiesced operation.

For linearizable quiescence, the database admission state is authoritative and participates in the same per-scope fence. A call is accepted only when one transaction holds the shared fence, verifies the current epoch/admission-open state, and inserts the immutable call identity plus accepted epoch; commit makes that admission durable. Before entering COM, the writer commits a `DISPATCHING` transition under the shared fence. Barrier close acquires the exclusive fence, closes admission and advances the epoch atomically, then commits. A dispatch transition committed before close is outstanding work that the barrier must wait to finish; any transition after close is rejected. An accepted call with no `DISPATCHING` transition may be cancelled only with durable proof COM was never entered; otherwise it remains unresolved under the hold. Distinguish `CLOSED_WITH_HOLD` from `QUIESCED`: closing the barrier is not quiescence and never advances lifecycle readiness. COM runs outside PostgreSQL transactions. On restart, the service reads the durable barrier and unresolved calls before accepting traffic; uncertainty fails closed. A service-local journal may accelerate recovery but cannot override database admission or outcome state.

## Implementation sequence

1. Resolve the pending exact-revision clarification in `S12_CONTRACT_FREEZE_V2_2026-10-16.md` and record the S12 disposable-qualification prerequisites; perform no qualification in this step. Retain the read-only regression for the later test phase.
2. Reconcile the complete granted API and trigger/row/advisory lock inventory against the selected per-scope shared/exclusive fence and canonical internal ordering above. The source review specifically identifies the `events_chain`/lifecycle trigger order; `validate` taking its business-key advisory lock after the record row; `declare_business_key`/`bind_duplicate_override` key access; the verifier-key receipt-role advisory lock; and recovery/kill-switch ordering through `recover_sweep`, `revoke_stale`, `A:sweep`, and `A:killswitch`. Include unique-index conflict arbitration and cross-scope conflict domains for reservations, permits, recovery counters, evidence, receipts, policy/state, observations, and registries. Database/reliability review must accept the complete path map before any fence migration is designed.
3. Add an additive schema/API for immutable writer admission, epoch compare-and-accept, outcome lookup, and barrier records. Keep activation disabled until the full-path fence is demonstrated.
4. Implement the separate private service composition with an injected writer port; bind the host identity, base fingerprint, and per-call process/session identity. Do not import it into the public gateway.
5. Implement the S13 service contract against the injected writer port without claiming physical COM qualification. WP5 then adds the signer/receipt registry; WP6 owns the S14 COM adapter on the disposable clone, preserving CT14's qualified operation shape and no-hard-delete rule. Keep the final S12/S13/S14 acceptance explicitly pending until the full WP4–WP8 and WP10 coding sequence is complete and its required qualification evidence exists.
6. Complete all in-scope WP4–WP8 and WP10 code before the test phase. Then `functional-test-reviewer` and `e2e-runner` own the complete story-mapped qualification; their cases cover duplicate/reused IDs, stale epochs, CAS-to-acceptance crashes, response loss, barrier races, restart-before-listener admission, incomplete status sets, no-effect proof, wrong scope/base, permissions, grants/RLS, dump/restore skew, and read-only gateway isolation. For the selected fence, include concurrent shared mutators with adversarial row/advisory ordering, exclusive recovery/barrier races, scope-key isolation, cross-scope unique conflicts, bounded timeout refusal, full transaction rollback, and lock acquisition before any row/conflict lock.
7. After functional/E2E evidence, launch exact-head database, security, reliability, and relevant architecture/code reviews. Fix valid BLOCKER/MAJOR findings before recording any S12/S13/S14 qualification result or final acceptance.
8. Only after those steps may a deployment plan for Ivan's licensed lane be reviewed. This document does not start or restart services, access clone contents, generate host keys, perform COM calls, or deploy the writer.

## Independent design review

An actual architecture review found no contradiction between this design and the operator's writer decision or the inherited S12 contract. Read-only database review confirmed that there is no safe table/trigger-only fence addition on the current source. Follow-up review requires the common-order proof to include `recover_sweep`/`revoke_stale`/`kill_switch` advisory and row-lock chains plus unique-index conflict arbitration, in addition to event-chain, lifecycle, business-key, verifier-key, and granted-API paths. A forward migration may preserve migrations 022–024 unchanged, but must replace or wrap the relevant granted APIs and trigger paths, establish the complete source-wide lock order, and align the database epoch with the private service's durable admission/barrier. These source obligations are documented in the review evidence and must be closed before designing an activating migration. Until then, migration 023's recovery refusal and lifecycle `NOT_READY` remain in force.

## Acceptance evidence and current state

| Requirement | State at this design revision | Evidence still required |
|---|---|---|
| Private non-public service boundary | **DECIDED; NOT_IMPLEMENTED** | Exact host binding, authenticated client identity/ACL, process supervision, and public-route isolation review. |
| Stable call-ID idempotency and conflict rejection | **CONTRACTED; NOT_IMPLEMENTED** | Database-enforced unique identity, crash-window functional tests, and exact-head DB review. |
| Stale-epoch rejection | **CONTRACTED; NOT_IMPLEMENTED** | Atomic common-fence participation by every mutation, permit, and dispatch path; independent contention tests. |
| Authoritative lookup | **CONTRACTED; NOT_IMPLEMENTED** | Durable service/ledger state and S12-bound receipt/outcome/completion evidence; restart and response-loss tests. |
| Quiescence barrier | **CONTRACTED; NOT_IMPLEMENTED** | Linearizable admission/barrier race proof, complete pre-barrier enumeration, bounded wait, unresolved-call hold, and cross-process tests. |
| Effective database rights | **NOT_VERIFIED** | Disposable post-migration effective role/membership/table/function privilege capture and DB review. The current inspected DB has no `change_ledger` schema. |
| S13 service contract and S14 physical COM behavior | **S13 COORDINATOR IMPLEMENTED / NOT_TESTED; S14 NOT_QUALIFIED** | The new private coordinator defines durable-admission, invocation, lookup, and bounded-barrier adapter contracts; no concrete PostgreSQL adapter or listener is wired. Test-agent qualification, transaction-boundary proof, effective grants, physical COM adapter, clone-specific fingerprint, CT14 behavior, signed receipts, independent read-back, and crash/barrier evidence remain open. |
| S13 readiness/production authority | **NOT_READY / NONE** | Full S13 stories, provider/key custody, complete fence coverage, recovery evidence, exact-head review, and formal gate approval. |

## Change control

This design is additive. It does not revise the S12 state machine, edit migrations already in history, weaken refusal rules, change formal gate status, or enable a real write. Every implementation commit must link a dedicated change record and a `core/LESSONS_LOG.md` entry. Staging deployment and push/PR remain outside this design; local commits follow the repository's exact-diff review gate.
