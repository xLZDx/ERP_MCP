# Local simulated `OneCWritePort` design

Date: 2026-10-17. Status: GPT-PM approved for local implementation only; formal S14 remains open.

## Goal

Provide a test-lane implementation of the existing `OneCWritePort` protocol over `SimulatedOneC` so protocol consumers can exercise the frozen receipt operations (`CREATE_DRAFT`, `POST`, `UNPOST`) against a deterministic in-memory clone. This slice must not be represented as CT14, real 1C, production writer, or S14 acceptance evidence.

## Non-goals

- No COM/OData/network integration, production identity, key custody, database ledger, or deployment.
- No production authorization semantics for synthetic tickets or permits.
- No `UPDATE_DRAFT`, hard delete, payment operation, automatic retry, or `VERIFIED` claim.
- No change to the existing `SyntheticDispatchCoordinator` / `ReferenceWriter` path or formal gate manifest.

## Design

Options considered:

1. Leave `NonOperationalWritePort` as the only protocol implementation and continue using the separate synthetic dispatch coordinator. This avoids introducing a second synthetic contract but does not exercise protocol consumers.
2. Add an explicitly named `SimulatedOneCWritePort` in the simulation package, backed only by `SimulatedOneC`, with test-only ticket/permit validation and explicit operation allowlisting. Choose option 2 only as a non-gating local engineering aid; it does not change formal acceptance.

The adapter owns no ledger state or production signing keys. `SyntheticPermitAuthority` uses an explicitly supplied TEST-only fixture key and checks ticket and permit identity/generation/call binding, expiry, allowed operation, and simulator identity. `digest_set_hash` is bound to the existing canonical `payload_digest(payload, target_version)` contract; the adapter validates it before invocation and the clone independently repeats the check under its mutation lock. Each clone instance binds permanently to one tenant/company/organization tuple. Base authentication compares the ticket fingerprint to the simulator's current fingerprint. `CREATE_DRAFT`, `POST`, and `UNPOST` map to the clone's existing operations and return only synthetic TEST result data. `UPDATE_DRAFT` refuses before invoking the clone. The clone owns the atomic base/scope/organization/version checks, expiry admission check, and call-ID registry; replay or conflicting reuse of a call ID is refused before a second mutation. `SimulatedOneC` remains the sole state owner and failure injector.

The adapter uses a simulation-specific error/result type for refusal and uncertain outcomes. It must never construct or return `FailureEvidence` as if a synthetic result were writer-signed, and no caller may promote it to a production T8/T9 decision. Timeouts and crashes after dispatch are reported as unknown outcomes without a retry; no clone ground-truth oracle is exposed through the port. The adapter's successful result shape must make lane `TEST` and synthetic marker explicit.

## Failure modes

- Ticket, permit, scope, operation, fingerprint, payload digest, target, or expected-version mismatch: fail before clone mutation.
- Permit expires while waiting for clone admission: reject under the clone lock before reserving the call ID or mutating.
- Replayed or conflicting call ID: reject under the clone lock without a second effect.
- Clone refusal before write: return a simulation-only refusal with a stable code; it is not signed no-effect proof.
- Timeout or crash after call begins: return/raise an unknown outcome; never retry automatically.
- Unsupported operation or malformed payload: refuse before calling the clone.
- Adapter/clone identity mismatch: fail closed; do not silently substitute another clone.

## Rollout and rollback

The class is opt-in and imported only by simulation/test-lane code. No runtime composition root selects it. Rollback is removal of the new simulation module and its tests; there is no data migration or persisted state. The existing non-operational port remains unchanged.

## Test plan

After all in-scope coding is complete, `functional-test-reviewer` and `e2e-runner` own focused protocol tests for binding/scope/fingerprint/digest/target/version/expiry denials, cross-scope adapter rejection, each allowed operation, replay/conflicting call IDs, explicit `UPDATE_DRAFT` refusal, pre-write refusal, timeout, crash-before-write, crash-after-write, no retries, and clone-state oracles confined to tests. Tests assert this is synthetic `TEST` evidence only and the completion classifier returns `CALL_UNKNOWN`. CT14 and licensed COM evidence stay `NOT_RUN` unless supplied by the authorized lane.

## Unknowns and acceptance boundary

The canonical S14 sprint requires the measured purchase-receipt path through a CT14-approved channel, atomic marker enforcement, least privilege, and channel-specific evidence. No such channel/owner is recorded in the current repository. Correlated GPT-PM decision `b5f382b5-86b4-4bc1-9e62-52dc762aad23` returned **GO — LOCAL IMPLEMENTATION ONLY**. Conditions: strict simulation-only validation of synthetic ticket/permit bindings and simulator identity; allow only `CREATE_DRAFT`, `POST`, and `UNPOST`; explicit TEST-only result/error types; no signed `FailureEvidence`, T8/T9 interpretation, hidden clone oracle, production wiring, migration, or formal S14/R-01 closure; and atomic expected-version validation plus mutation under simulator-owned synchronization. This story creates no formal S14 pass and does not close R-01. Accountable task owner: operator; execution owner: GPT/Codex; test owners: functional-test-reviewer and e2e-runner; licensed channel owner: unknown in canonical records.

## Exact simulator identity

An instance label and a deterministic state fingerprint describe configuration and contents. They do not distinguish separately allocated simulators. The TEST permit authority binds to a single live clone instance before issuing permits; the same exact clone can serve multiple adapters with the same fixture key and scope. Per-instance binding does not change the business-state fingerprint, does not appear in results, and has no production authority. Separately allocated or restarted simulations require fresh fixture permits. Verification remains scheduled after local source assembly.


The named verification should confirm that two adapters on the same live clone remain compatible, an unbound authority refuses issuance, and independently allocated clones never share the same TEST permit identity even when their display labels and state fingerprints match. Treat those identity checks as simulation evidence only.


## S14-02 marked receipt draft creation

For the governed TEST port, create the draft and store a private marker carrying the change identity and approved digest in the same clone-owned mutation. Keep the marker on an accepted draft after a simulated response loss or crash. Reject another create for the same marked change while retaining the existing exact-call replay classification. Recheck the canonical receipt business key under the same lock. The clone instance and receipt kind are implicit; compare organization, counterparty, contract, supplier document number and date, and currency. An explicitly approved duplicate override can allow a separate proposal to use the same business key; it cannot bypass the same-change marker. Use the clone's existing TEST data for verification and keep the marker out of public fingerprints, results, and operational evidence. Existing reference-writer behavior and the COM privilege/retention contract stay separate.


When preparing the named tests, use distinct change IDs for distinct proposals and retain a single ID for true same-proposal retries. Keep the ordinary duplicate case separate from the same-marker case, including changed-digest refusal, same-key independent proposals, response loss after creation, and a legitimate document whose contract or currency differs. Verify contents on the TEST clone only.


## S14-03 unresolved invocation holds the TEST base

When a governed clone write crosses the mutation call boundary and its outcome becomes unknown, preserve consumed call identity and latch a base-wide write hold while still owning the clone lock. Refuse otherwise valid new writes through any adapter on that live clone before consuming another call identity. Retain exact call replay/conflict classification and keep read-only inspection available. A definite simulated pre-write refusal does not create a hold. The TEST adapter has no authority to clear an unresolved hold and never forces termination or turns a timeout into finished-call proof. Separate failure-injection cases use separate fixture instances. No operational deadline, worker-process lifecycle, or 1C-session proof follows from a simulated failure.

## S14-04 delayed notifications in offline outcome recovery

The separate governed-write simulation records an unknown outcome only while the dispatch remains unresolved. A delayed notification after a proven pre-invocation handback, a recorded applied result, or verification preserves the existing snapshot. In particular, a delayed notification for a handed-back attempt cannot take the base hold from a newer attempt.

Named verification should hand back an attempt with valid no-invocation evidence, dispatch a second attempt on the same base, then deliver the old unknown notification and verify that a third attempt still encounters the second attempt's hold. Exercise delayed notifications after an applied result and after verification, as well as a genuinely unresolved interruption that retains its hold. Use the existing offline contracts for these scenarios.

## S14-05 distinct approved receipt operations

Once the governed TEST clone admits a call, bind its change identity to the operation, target, expected version, and approved payload digest under the clone write lock. A fresh call identity or generation may carry the same frozen change. A different operation, target, version, or digest requires its own approval identity. Exercise create, post, and unpost with distinct approvals and verify their movement effects against independent expected counts. Include an attempt to reuse an approval for another operation and confirm that the target and registers stay unchanged.

