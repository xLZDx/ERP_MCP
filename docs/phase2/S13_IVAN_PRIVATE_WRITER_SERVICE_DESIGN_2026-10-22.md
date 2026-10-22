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

Admission uses a new additive, versioned S13 contract; it does not edit migrations 022–024 in place or assume that the preparatory lifecycle API can enter recovery. Under the candidate serial-mutex design below, the new database transaction must acquire the global mutation mutex nonblocking before row locks, compare the requested epoch with the durable active epoch for the scope, validate the full immutable identity and approved dispatch state, and atomically insert the unique accepted-call row. A duplicate identical identity reads that row; a reused call ID with any differing field fails closed. The transaction commits before COM is entered.

The accepted-call record binds a non-reusable service process instance, host boot/service identity, optional 1C session instance, scope, target, operation, epoch, payload digest, dispatch CAS identity, monotonic state, and evidence references. It is append-only or otherwise monotonic. Its uniqueness and all foreign-key scope bindings are database enforced. A local process cache is never the idempotency source of truth.

### Physical invocation and result

Only the process that wins durable admission may invoke COM, and only once. Before entry it persists an invocation-stage transition tied to its process instance. The call result and signed receipt are committed through the S12 evidence path. A process crash or communication error after the invocation may have started leaves an unresolved call; a subsequent process may query and reconcile it but may not call COM again.

The outcome API returns a closed typed status such as `NOT_ACCEPTED`, `ACCEPTED_NOT_INVOKED`, `POSSIBLY_EXECUTING`, or `TERMINAL_WITH_EVIDENCE`, with the immutable call tuple and evidence reference. It returns no caller-controlled “success” flag. `ACCEPTED_NOT_INVOKED` is terminal only when a durable process-bound guard proves the mutating COM method was never entered. Terminal effect claims additionally require the S12 receipt, independent verification, and any required completion proof.

### Quiescence barrier

`fence_scope(scope, new_epoch, barrier_id)` is idempotent by `barrier_id`. Its linearization point is the transaction that holds the same nonblocking global mutation mutex as call acceptance, advances the durable epoch for the requested scope, and snapshots the complete set/watermark of calls admitted at older epochs. Calls submitted later with an older epoch are rejected. Calls already admitted remain owned and are not cancelled by the barrier.

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

### Candidate common-order and barrier protocol (design proposal; not implemented or qualified)

Use one private singleton row in a new internal mutation-mutex table for **all** `change_ledger` mutation and recovery transactions as the conservative first implementation. This intentionally serializes ledger writes across bases. The schema must constrain the singleton key to one fixed value with a primary key, insert exactly one row during bootstrap, and revoke runtime delete/truncate/table access. The acquisition function must fail closed if it selects no row; an absent row must never be treated as a successful lock. Acquire it first with `SELECT ... FOR UPDATE NOWAIT`; if another transaction holds it, fail immediately with the stable `MUTATION_BUSY` refusal rather than block while the caller may hold a prior advisory or row lock. Unlike an advisory lock key, the mutex row is not available to runtime roles through PostgreSQL's PUBLIC advisory-lock functions. Revoke direct table access and expose lock acquisition only through hardened API/trigger functions. This avoids relying on a guessed per-scope key to order the source inventory's global unique-index conflicts, including `ON CONFLICT` waits. The throughput cost is accepted only as a qualification hypothesis for this low-volume writer; measure it before any `READY` transition.

Every mutating API, recovery sweep, and kill-switch transition must lock the mutex row at function entry with `FOR UPDATE NOWAIT`, before any ledger row/advisory lock, epoch check, or mutating statement. If acquisition fails, return a fixed `MUTATION_BUSY` refusal immediately; the function cannot roll back its caller's transaction. Therefore the private service must execute each operation in a fresh top-level transaction on a dedicated connection, and on `MUTATION_BUSY` or any SQL error it must issue a full transaction `ROLLBACK`, discard that transaction context, and never catch the error inside a savepoint or continue/commit the transaction. It must not acquire advisory or ledger locks before starting this transaction. This prevents the caller from retaining earlier locks while waiting for another writer. The same full-rollback contract applies to the five-second timeout for other row/advisory locks. The API must not be callable by a general application role that can choose a different transaction protocol. This fail-fast rule also applies to every nested helper that can be called without an already-held mutex. A forward migration would revoke runtime-role direct DML and legacy mutator grants, expose only guarded entrypoints, and add a statement-level mutation guard to every ledger table. The guard takes the same mutex row with `FOR UPDATE NOWAIT` as a fail-closed backstop: if another writer owns it, reject the statement immediately instead of waiting while any earlier lock may be held. The guard does not excuse an API that takes row locks before entering the mutex; only the full grant/API audit can establish that order. A lock failure never clears admission/barrier holds or fabricates an outcome. No public/read role receives an entrypoint or mutex authority. Owner/admin maintenance is a separate quiesced operation and is not counted as an application writer.

Within that serialized transaction, use this deterministic order and sort multiple IDs/keys lexicographically before taking same-class locks:

1. Private ledger mutation-mutex singleton row (first and held only through the PostgreSQL transaction).
2. Writer-admission/barrier singleton and scope epoch rows; compare the caller's epoch and scope while holding these locks.
3. Intent, approval/permit, dispatch-attempt, and call-identity rows.
4. Change/record rows, then business-key rows and any old/new key hashes.
5. Reservations, target/key locks, budgets, leases, recovery counters, and kill-switch state.
6. Verifier/writer key-registry rows, then receipts, outcomes, completion proofs, observations, and policy/state rows.
7. Event-chain advisory lock and append last. Existing trigger ordering must be changed or wrapped so no path requests the lifecycle fence after taking the event-chain lock.

Unique-index conflict arbitration is covered by the first mutex: every transaction that can create or change a row participating in a listed unique index must enter through the guarded path before touching that index. The inventory's reservation, permit, recovery-counter, evidence, receipt, policy/state, observation, and registry conflict targets must each be mapped to that rule. The mutex is not a substitute for revoking bypass DML, verifying installed privileges, or testing the complete mutation/trigger graph. Any unguarded owner path, unknown mutation table, cross-database writer, or lock taken before the mutex keeps the design unqualified and lifecycle `NOT_READY`.

For linearizable quiescence, the database admission state is authoritative and shares the same mutex. A call is accepted only when one transaction verifies the current epoch/admission-open state and inserts the immutable call identity plus accepted epoch; commit makes that admission durable. Before entering COM, the writer commits a `DISPATCHING` transition under the same mutex. Barrier close takes the mutex, closes admission and advances the epoch atomically, then commits. A dispatch transition committed before close is outstanding work that the barrier must wait to finish; any transition after close is rejected. An accepted call with no `DISPATCHING` transition must be cancelled with durable proof that COM was never entered; absent that proof it remains unresolved under the hold. Distinguish `CLOSED_WITH_HOLD` (admission is closed, but one or more earlier calls are unresolved) from `QUIESCED` (every earlier accepted call has a durable terminal outcome with the required evidence, no call remains unresolved, and the barrier may be reported ready). Closing the barrier is not quiescence and never advances lifecycle readiness. COM runs outside PostgreSQL transactions. On restart, the service reads the durable barrier and unresolved calls before accepting traffic; uncertainty fails closed. A service-local durable journal may accelerate recovery but cannot override database admission or outcome state.

The serial-mutex choice is deliberately more conservative than a per-base lock hierarchy. It reduces concurrency but gives unique-conflict waits one common root while the deployed grant/trigger inventory is incomplete. Database and reliability reviewers must verify that the private row and guard cover every source-final granted API, trigger, direct-DML path and recovery helper, and that the service enforces one fresh top-level transaction plus full rollback on every refusal/error, before this proposal can support additive migration or qualification.

## Implementation sequence

1. Resolve the pending exact-revision clarification in `S12_CONTRACT_FREEZE_V2_2026-10-16.md` and record the S12 disposable-qualification prerequisites; perform no qualification in this step. Retain the read-only regression for the later test phase.
2. Reconcile the complete granted API and trigger/row/advisory lock inventory against the candidate serial mutex above. The source review specifically identifies the `events_chain`/lifecycle trigger order; `validate` taking its business-key advisory lock after the record row; `declare_business_key`/`bind_duplicate_override` key access; the verifier-key receipt-role advisory lock; and recovery/kill-switch ordering through `recover_sweep`, `revoke_stale`, `A:sweep`, and `A:killswitch`. Include unique-index conflict arbitration and `ON CONFLICT` waits for reservations, permits, recovery counters, evidence, receipts, policy/state, observations, and registries. Database/reliability review must reject or refine the candidate before any fence migration is designed.
3. Add an additive schema/API for immutable writer admission, epoch compare-and-accept, outcome lookup, and barrier records. Keep activation disabled until the full-path fence is demonstrated.
4. Implement the separate private service composition with an injected writer port; bind the host identity, base fingerprint, and per-call process/session identity. Do not import it into the public gateway.
5. Implement the S13 service contract against the injected writer port without claiming physical COM qualification. WP5 then adds the signer/receipt registry; WP6 owns the S14 COM adapter on the disposable clone, preserving CT14's qualified operation shape and no-hard-delete rule. Keep the final S12/S13/S14 acceptance explicitly pending until the full WP4–WP8 and WP10 coding sequence is complete and its required qualification evidence exists.
6. Complete all in-scope WP4–WP8 and WP10 code before the test phase. Then `functional-test-reviewer` and `e2e-runner` own the complete story-mapped qualification; their cases cover duplicate/reused IDs, stale epochs, CAS-to-acceptance crashes, response loss, barrier races, restart-before-listener admission, incomplete status sets, no-effect proof, wrong scope/base, permissions, grants/RLS, dump/restore skew, and read-only gateway isolation. For the serial mutex, include a caller-held prior advisory-lock interleaving: the caller first holds an unrelated transaction advisory lock, then the contender's `SELECT ... FOR UPDATE NOWAIT` on the private singleton mutex row returns `MUTATION_BUSY`; the client rolls back/discards the entire top-level transaction (including its earlier advisory lock), it does not catch and continue in a savepoint, and a subsequent writer can proceed. Also qualify the five-second non-mutex lock timeout and full rollback behavior.
7. After functional/E2E evidence, launch exact-head database, security, reliability, and relevant architecture/code reviews. Fix valid BLOCKER/MAJOR findings before recording any S12/S13/S14 qualification result or final acceptance.
8. Only after those steps may a deployment plan for Ivan's licensed lane be reviewed. This document does not start or restart services, access clone contents, generate host keys, perform COM calls, or deploy the writer.

## Independent design review

An actual architecture review found no contradiction between this design and the operator's writer decision or the inherited S12 contract. Read-only database review confirmed that there is no safe table/trigger-only fence addition on the current source. Follow-up review requires the common-order proof to include `recover_sweep`/`revoke_stale`/`kill_switch` advisory and row-lock chains plus unique-index conflict arbitration, in addition to event-chain, lifecycle, business-key, verifier-key, and granted-API paths. A forward migration may preserve migrations 022–024 unchanged, but must replace or wrap the relevant granted APIs and trigger paths, establish the full global lock order, and align the database epoch with the private service's durable admission/barrier. These source obligations are documented in the review evidence and must be closed before designing an activating migration. Until then, migration 023's recovery refusal and lifecycle `NOT_READY` remain in force.

## Acceptance evidence and current state

| Requirement | State at this design revision | Evidence still required |
|---|---|---|
| Private non-public service boundary | **DECIDED; NOT_IMPLEMENTED** | Exact host binding, authenticated client identity/ACL, process supervision, and public-route isolation review. |
| Stable call-ID idempotency and conflict rejection | **CONTRACTED; NOT_IMPLEMENTED** | Database-enforced unique identity, crash-window functional tests, and exact-head DB review. |
| Stale-epoch rejection | **CONTRACTED; NOT_IMPLEMENTED** | Atomic common-fence participation by every mutation, permit, and dispatch path; independent contention tests. |
| Authoritative lookup | **CONTRACTED; NOT_IMPLEMENTED** | Durable service/ledger state and S12-bound receipt/outcome/completion evidence; restart and response-loss tests. |
| Quiescence barrier | **CONTRACTED; NOT_IMPLEMENTED** | Linearizable admission/barrier race proof, complete pre-barrier enumeration, bounded wait, unresolved-call hold, and cross-process tests. |
| Effective database rights | **NOT_VERIFIED** | Disposable post-migration effective role/membership/table/function privilege capture and DB review. The current inspected DB has no `change_ledger` schema. |
| S13 service contract and S14 physical COM behavior | **S13 CONTRACTED / NOT_IMPLEMENTED; S14 NOT_QUALIFIED** | S13 service-boundary behavior is qualified through the injected writer port in WP4. Physical COM adapter, clone-specific fingerprint, CT14 call behavior, signed receipts, independent read-back, and crash/barrier behavior belong to WP6/S14 and remain for post-coding test agents. |
| S13 readiness/production authority | **NOT_READY / NONE** | Full S13 stories, provider/key custody, complete fence coverage, recovery evidence, exact-head review, and formal gate approval. |

## Change control

This design is additive. It does not revise the S12 state machine, edit migrations already in history, weaken refusal rules, change formal gate status, or enable a real write. Every implementation commit must link a dedicated change record and a `core/LESSONS_LOG.md` entry. Staging deployment and push/PR remain outside this design; local commits follow the repository's exact-diff review gate.
