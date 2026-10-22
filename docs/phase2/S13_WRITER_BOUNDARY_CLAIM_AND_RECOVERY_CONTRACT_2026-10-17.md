# S13 writer-boundary claim and recovery contract

Date: 2026-10-17; ownership and implementation direction superseded by the operator decision of 2026-10-22. Status: proposed contract for local implementation; no runtime writer qualification or S13 approval is established.

## Goal

Define the missing protocol between the PostgreSQL ledger, a dispatching service, and the physical writer before any recovery path can leave `NOT_READY`. The protocol must distinguish a call that never crossed the writer boundary from one that may still be executing or whose result is unknown. It must prevent stale dispatch claims and make crash recovery idempotent without holding a database transaction across external I/O.

## Non-goals

- This document does not implement the protocol, authorize a real 1C call, select a licensed channel, qualify CT14, or enable startup admission.
- It does not infer that a timeout, expired lease, process death, or lost connection means the physical call stopped or had no effect.
- It does not add a lifecycle `READY` transition or revise the formal G0–G8 gate status.

## Options and decision

1. Hold a PostgreSQL transaction and lifecycle-row lock across the physical call. Reject: it violates the accepted no-database-transaction-across-I/O constraint, creates unbounded lock/resource risk, and still cannot prove what the external system did after a connection loss.
2. Use only a database epoch check immediately before the external call. Reject as insufficient: the check transaction ends before the call, leaving a race in which recovery can advance the epoch before or during physical execution.
3. Preserve the S12 dispatch sequence and bind it to a writer-side fencing/idempotency boundary plus an explicit quiescence/outcome query. The operator selected this implementation direction on 2026-10-22: a private COM write service on Ivan's licensed lane, first against the `818HA_p2diff` clone, bound to loopback/Tailscale and never the public tunnel. This does **not** add a second authorization claim: S12 commits APPLYING plus the call-ownership row, writes and reads back the signed checkpoint, then issues the permit; the writer validates the permit/checkpoint and performs the existing `PERMITTED → DISPATCHED` compare-and-set (CAS) on the ledger before physical I/O. That committed `call_id`/generation/epoch tuple is the single-use dispatch claim. The physical writer must fence/deduplicate it by stable call ID and epoch. Recovery blocks new database dispatch CAS operations, then establishes a writer-side acceptance barrier and resolves all claims accepted before that barrier. If the boundary cannot prove a call terminal, the scope remains `NOT_READY`. The selected host/channel does not yet prove these semantics; clone qualification must do so before admission can be enabled.

Option 3 is the operator-selected direction for local implementation, not an approval to enable admission. It is viable only if the selected COM channel supports atomic single-use dispatch by the existing S12 call identity, stale-epoch fencing plus lookup by stable call identity, and a linearizable recovery barrier. Those capabilities remain `NOT_VERIFIED` until the disposable-clone qualification produces evidence.

## Required contract

### Dispatch claim

- After the S12 APPLYING/call-ownership checkpoint has been written and read back and the generation-bound permit has been issued, the writer's short ledger transaction checks tenant/company scope, active lifecycle epoch, generation, permit and call identity, operation, target, expected version and performs the existing `PERMITTED → DISPATCHED` CAS. The CAS and audit event are one atomic ledger commit; a new table/state must not duplicate or replace this S12 invariant.
- The existing stable `call_id`, `change_id`, generation, scope, target, operation, epoch and approved payload digest form the single-use dispatch identity. Database constraints must make that identity immutable and idempotent, with an appropriate uniqueness key for `call_id` in scope. If the client loses the commit response, a retry with the identical identity must return/read the existing dispatch result; a conflicting identity is refused. A retry never creates a new call.
- Physical I/O may begin only after the CAS commit. The writer passes the same identity and epoch to the physical boundary. The database CAS alone cannot close the CAS-to-acceptance race; a prior database-only epoch check is insufficient.
- The writer boundary atomically accepts each call ID once, rejects stale epochs, and exposes an authoritative status/receipt lookup keyed by the same identity. A repeat with the identical immutable identity is idempotent and returns the original call status without another effect; reuse of a call ID with any conflicting identity is refused. If the selected channel cannot enforce these semantics, admission remains disabled for that channel.

### Recovery and terminal evidence

- Recovery durably changes the scope to `RECOVERING` and advances the database's desired fencing epoch while fencing creation of new claims under the same per-scope ordering protocol. The epoch is not writer-visible/enforced until the writer boundary acknowledges installation in the next step.
- The DB epoch row is the desired epoch authority; the physical writer maintains the highest epoch it has installed. Recovery then invokes an idempotent writer-boundary `fence_scope(scope, new_epoch)` barrier. The writer serializes this barrier with call acceptance: it atomically installs the new minimum epoch, rejects any delayed/unconsumed old-epoch claim, and returns a monotonic acknowledgment bound to scope/new epoch plus a complete watermark or set of calls accepted before the barrier. A recovery/writer race is linearized at this writer-side operation; recovery may not treat DB state alone as proof the writer observed the epoch.
- After the barrier, recovery queries each pre-barrier accepted call by stable `call_id` and epoch. Only independently verifiable, monotonic evidence that a call was rejected before acceptance/no effect or completed with a correctly bound receipt and required read-back is terminal for admission. An operator disposition may close an administrative case while preserving uncertainty, but it is not terminal for admission and does not clear a required hold. A call absent from a non-authoritative/non-monotonic lookup, or a lookup that cannot cover delayed submissions and queued/in-flight work, is unresolved.
- `POSSIBLY_EXECUTING`, missing status, timeout, stale service connection, process death, and an expired lease remain unresolved. They never authorize a retry or `READY`.
- A crash after entering `RECOVERING` resumes from durable recovery progress containing the fence epoch, writer barrier identity/acknowledgment, accepted-call watermark, and each call's lookup result plus verified terminal-evidence reference/digest. Updates are append-only or otherwise monotonic. Expiry alone never clears recovery state. Recovery can finish only after a second atomic check confirms the epoch is unchanged, every mutation/dispatch path participated, every pre-fence claim is terminal under the contract, the checkpoint is current, and the writer barrier proves no earlier-epoch call remains queued or in flight.
- A new active epoch invalidates every old **unconsumed** claim at the physical writer boundary. A call already accepted by the writer cannot be revoked; it remains tracked until independently terminal. The writer boundary enforces epoch installation at the physical call edge; merely checking it in a prior PostgreSQL transaction leaves a race.

### Transaction and lock rules

- No PostgreSQL transaction remains open across checkpoint-provider I/O or a physical writer call.
- The candidate SQL lock hierarchy must be reviewed against S12 revision 6 and migration 008: acquire a new per-scope shared/exclusive transaction advisory fence first, then all other named namespace advisory locks in a canonical order, all **before** row locks; then lock claim tokens in stable order, records in stable order (repair record before parent), secondary permit/claim/lock/lease/hold/epoch rows, and the event-chain advisory lock last. A code path holding the chain lock must not wait for rows. This is a design candidate, not an approved replacement for the existing S12 order; a source-wide review must prove the new fence is acquired before row locks on every path while preserving chain-last/no-row-wait-after-chain invariants. If that cannot be demonstrated, redesign the protocol before implementation.
- Every mutator, permit/dispatch CAS, and recovery transition must participate in the same scoped fence with a bounded wait. The physical writer barrier is a separate required step and is not provided by a transaction advisory lock.
- A recovery timeout, lock timeout, provider failure, or writer-status failure leaves the scope fail-closed and emits an observable reason. No automatic recovery reset occurs.
- The design must enumerate all table mutations, SQL APIs/triggers, and physical call entry points; a trigger inventory alone is insufficient if any direct table or service path bypasses it.

## Failure matrix

| Failure point | Durable state | Safe response and recovery |
|---|---|---|
| Before S12 checkpoint read-back / permit issuance | No dispatch CAS; no physical call permitted | Retry only the checkpoint/permit protocol under its existing idempotent bounded rules |
| `DISPATCHED` CAS commit response is lost | Existing call ID may already be committed; physical call may not yet have been accepted | Read/idempotently return the existing result for the identical `(scope, call_id, change_id, generation, epoch)` identity; do not rerun the CAS as a fresh dispatch and never create a new call |
| Dispatch committed; worker dies before writer acceptance | DISPATCHED call remains outstanding | Query writer by call ID and epoch; do not infer no effect from worker death |
| Writer accepts; response is lost or times out | Outcome unknown / possibly executing | Do not resend; query the same call ID until independently terminal, otherwise remain held and `NOT_READY` |
| Physical effect completes; receipt response is lost | Call remains unresolved until lookup | Retrieve and verify the receipt/read-back for the same call ID; no second call |
| Recovery begins while call is active or a DISPATCHED request is delayed | Scope is `RECOVERING`; new epoch is durable; writer fence is pending | Linearizable writer barrier rejects delayed old-epoch calls and enumerates accepted ones; resolve each accepted call to terminal state; without barrier acknowledgment, remain `NOT_READY` |
| Service or database reconnects with stale epoch | Old claim is invalid | Physical writer rejects it before effect; service discards cached readiness and re-enters preflight |
| Process crashes during recovery | Durable recovery state, barrier identity and per-call evidence references remain | Resume idempotently from the same fence; no lease-expiry shortcut to active or ready |
| Writer/provider status unavailable | Scope stays fail-closed | Report reason and dependency; no retry of the physical operation and no `READY` |

## Rollout and rollback

Local implementation may proceed using the operator-selected private COM service on Ivan's licensed lane and the `818HA_p2diff` clone as the first target. Before enabling admission, the clone qualification must demonstrate the actual physical call boundary, single-use claim consumption, stable call-ID idempotency, stale-epoch rejection, authoritative outcome lookup and quiescence behavior. A database reviewer must map every SQL mutation and prove lock order/coverage; reliability and security reviewers must review crash windows and trust boundaries. Only after those results may an additive, backward-compatible migration/API change be designed. Do not edit or re-enable migrations 022–024 in place. Rollback must keep dispatch disabled for the new path and preserve claims/evidence; never clear recovery state or replay calls as cleanup.

## Verification plan

After implementation code is complete, `functional-test-reviewer` and `e2e-runner` own mapped tests for duplicate claim, stale epoch, every mutation/CAS path racing recovery, writer acceptance before/after process loss, timeout with and without effect, receipt lookup, unresolved-call hold, recovery restart, bounded lock waits, tenant/company isolation, grants/RLS and dump/restore. Database, reliability and security specialists review the exact implementation head. Until an authorized physical-writer lane is available, its runtime evidence is `NOT_RUN`; a simulator cannot prove physical call quiescence.

## Ownership and open evidence

For delegated local work, the operator is the accountable task owner and Codex executes. The Ivan stack, including scheduled task `ERP_MCP_Ivan_Stack`, is the technical owner of the host/connection boundary; this attribution follows the operator's 2026-10-22 decision and `docs/phase2/artifacts/REMOTE_1C_HOST_STACK_2026-10-11.md`. Test design/execution belongs to `functional-test-reviewer` and `e2e-runner`; SQL/transaction review belongs to `database-reviewer`; failure/restart analysis belongs to `reliability-reviewer`; writer-boundary trust review belongs to `security-reviewer`. The remaining dependency is evidence that the chosen COM boundary satisfies the contract on the disposable clone. Until that is independently qualified, keep admission disabled and lifecycle `NOT_READY`; this decision does not authorize shared ERP writes, the public tunnel, staging, or production.
