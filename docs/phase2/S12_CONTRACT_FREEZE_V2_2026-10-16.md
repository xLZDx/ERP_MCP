# S12 Contract Freeze v2.0 — governed purchase receipt write

**Status:** GPT approved the initial engineering scope on 2026-10-16. This revision adds an implementation clarification requiring the independent read-back target/version to match the signed writer receipt; that clarification is awaiting exact-revision GPT review. Neither approval closes the formal S12 gate, authorizes a real 1C write, approves deployment, or changes any G0–G8 status.  
**Authority:** Initial scope: correlated GPT project-owner ruling `d289d167-b1f2-43d7-a17a-e01891748eb3`, reply `0d9e7e0e-9792-4b8a-8c77-b1af5fd6af72`, on source HEAD `1ec73879ade35b112c428c9885b55c46452aa7df`; APPROVE — OPTION A. Receipt-to-read-back consistency clarification: pending fresh GPT review of the resulting exact source/document revision.  
**Scope:** one qualified `ПоступлениеТоваровУслуг` shape and the operations `CREATE_DRAFT`, `POST`, `UNPOST`, through a future private COM adapter on a licensed host. This is a design contract only. No production or live 1C connection is in scope.

## 1. Frozen operation scope

| Operation/feature | v2.0 decision | Constraint |
|---|---|---|
| `CREATE_DRAFT` | IN | Creates the one qualified receipt shape as unposted. |
| `POST` | IN | Requires a separately approved, previously created and independently verified draft. |
| `UNPOST` | IN | Requires a separately approved, previously verified post; rechecks dependents, period state and operation rules. |
| `UPDATE_DRAFT` | OUT | Requires a later scope decision and its own acceptance. |
| Contract update and OData writes | OUT | Existing read capability is unaffected. |
| Forced session termination | DENIED | Never a recovery method for an unresolved call. |
| Another target during an unresolved physical call | DENIED | Base-wide call-ownership hold remains until completion is proven. |
| Google Drive intake | OUT | Keep `drive_intake_enabled=false`; formal G4 scope/waiver record remains separate. |

The measured CT14 evidence is from a disposable file-base clone. It does not establish client-server or production topology behavior, universal register movement counts, signer custody, or permission to operate a real base.

## 2. Trust boundaries and evidence types

The prototype's canonical JSON hash and synthetic writer receipt prove only what the simulator accepted. Migration 018's receipt requirement is opt-in, and a CT14 marker can be changed through an API writer. Neither a marker's presence nor absence proves application or non-application. A JSON digest does not prove which COM properties were assigned or persisted.

v2.0 requires two independent signed records with different signers and purposes, plus a separately typed `CompletionProof` record for physical-call completion. None can substitute for another, and completion is never inferred from timeout, a missing receipt, or `call_returned=false` alone.

### 2.0 Canonical signed bytes

All three evidence records use closed, versioned JSON schemas and the same serialization rules as `S12-APPROVAL-2`: UTF-8; keys sorted lexicographically; compact `,` and `:` separators; ASCII-only JSON with non-ASCII encoded using the standard JSON backslash-u escape; no floating-point values; decimals represented as canonical strings; timestamps encoded exactly as UTC RFC 3339 `YYYY-MM-DDTHH:MM:SS.ffffffZ` (six fractional digits; no leap-second form); every nullable field present as explicit JSON `null`; reject duplicate keys, unknown fields, invalid Unicode, and noncanonical encodings. The field lists below are the complete required v1 schemas, including explicit nullable fields. A contract or field-semantics change requires a new record version.

Each record uses two deterministic, non-circular byte strings. First, `digest_preimage` is the domain-separation prefix followed by canonical UTF-8 JSON of the complete envelope excluding both its signature field and its digest field (`signed_payload_digest` or `canonical_evidence_digest`). Compute lowercase hexadecimal `record_digest = SHA-256(digest_preimage)`. Second, `signature_preimage` is the same prefix followed by canonical UTF-8 JSON of the complete envelope including the computed digest and excluding only the signature field. The signer computes Ed25519 over `signature_preimage`. The receiver recomputes both byte strings, digest and signature; mismatch rejects the record.

| Record | Exact prefix |
|---|---|
| `DispatchReceipt` | `ERP_MCP_R2:S12:DISPATCH-RECEIPT:v1` followed by one LF byte |
| `OutcomeEvidence` | `ERP_MCP_R2:S12:OUTCOME-EVIDENCE:v1` followed by one LF byte |
| `CompletionProof` | `ERP_MCP_R2:S12:COMPLETION-PROOF:v1` followed by one LF byte |

The envelope includes and therefore signs its version, scope, all authorization/call or observation claims, signer key ID, key version, role and algorithm. No caller-selected serialization, detached unsigned metadata, or algorithm fallback is accepted. Approval and evidence digests remain distinct domains.

### 2.0.1 Scope-bound identity registry

At verification time, a trusted registry must map `(key_id, key_version)` to an authenticated writer, verifier or completion-supervisor service identity; authenticated host identity; Ed25519 public key; one purpose/role; allowed tenant/company/organization/base scope; validity interval; revocation status; and rotation history. The v1 purpose mapping is exact: `DispatchReceipt` and `WRITER_CALL_RETURNED` use `writer_receipt`; `OutcomeEvidence` uses `verification_worker`; `INDEPENDENT_SESSION_AND_PROCESS_CLOSED` uses `completion_supervisor`; checkpoint signing retains its separate `checkpoint_signer` identity. Writer, verifier, completion-supervisor and checkpoint roles have separate keys and authorities. A completion-supervisor identity is additionally host-scoped to the exact writer host/service it may observe and may attest process/session closure only; it has no 1C mutation, approval, or outcome-verification authority. The verifier checks the registry record against both the signed envelope and expected scope. `writer_service_id`, `writer_host_id`, `verifier_service_id`, `verifier_host_id` and `key_version` are not trusted merely because they are signed. The trusted host supervisor also attests the writer process instance: `writer_process_instance_id` is a cryptographically random, non-reusable service-start UUID bound to the authenticated host boot UUID, service instance, OS process ID and process creation time. A PID alone is never a process identity. Process-instance binding is authenticated by the supervisor identity registered for that host. Runtime registry/supervisor unavailability or an unknown, revoked or mismatched identity fails closed. Actual registry provenance and custody remain external qualification requirements under R-03.

### 2.1 `DispatchReceipt` — trusted writer attestation

The writer signs a durable, immutable, versioned receipt. The following are the complete required v1 fields; no unlisted field is accepted:

- **Scope and target:** `receipt_version`, `tenant_id`, `company_id`, `organization_ref`, authenticated `base_fingerprint`, `target_class`, nullable-by-operation `expected_target_ref` and `expected_pre_version`.
- **Authorization:** `change_id`, `request_id`, `claim_generation`, `approval_digest_version`, `approval_digest`, `auth_epoch`, `permit_id`, `permit_digest`.
- **Physical call:** `receipt_id`, `call_id`, `dispatch_generation`, `dispatch_cas_id`, `writer_service_id`, `writer_host_id`, `writer_process_instance_id`, nullable `onec_session_id`, nullable `onec_session_instance_id`, `operation_kind`, `started_at`, `write_invocation_stage`, `call_returned`, nullable `returned_at`, `result_class`, nullable returned target/version, nullable `no_effect_evidence_digest`, and nullable bounded `error_family`.
- **Mapping/configuration:** `mapping_version`, `configuration_fingerprint`, `approved_payload_digest`, `mapped_property_manifest_sha256`, and `COM_operation_manifest_sha256`.
- **Signature:** `signer_key_id`, `key_version`, `signer_role=writer_receipt`, `algorithm=Ed25519`, `signed_payload_digest`, and signature.

The property manifest hashes the normalized ordered assignments prepared for COM (1C property, type, value or value digest), including write mode, property-setting method, and tabular-section changes. The operation manifest binds the selected method/write mode, target, and expected version. The receipt attests what the authenticated writer prepared and observed at its boundary; it does not independently prove persisted 1C state.

For the post-CAS refusal case in §3.1, the signed `DispatchReceipt` is the stage-proof record: `write_invocation_stage=NOT_INVOKED`, `result_class=PRE_WRITE_NO_EFFECT`, `call_returned=false`, null return fields, and a non-null operation-specific `no_effect_evidence_digest`. For every other result class this field is explicit null. Its signature binds `dispatch_cas_id`, `writer_process_instance_id`, exact 1C session instance when available, scope, generation and call. The invocation guard must persist a one-way “COM method not entered” fact for that process instance/call before this receipt is committed. This receipt is mandatory to take T8 after CAS; if it or the guard evidence is missing, not durable, or disagrees, the state remains `APPLY_UNKNOWN` with the hold. Pre-CAS refusal remains `PRE_DISPATCH` and creates no dispatch receipt.

### 2.2 `OutcomeEvidence` — independent read-only verifier

The verifier uses a separate service/host identity, Ed25519 key, and read-only authority. It must not receive the writer key, perform COM mutations, confirm success from a marker, or reuse the writer's transformation/mapping implementation as its oracle. The following are the complete required v1 fields; no unlisted field is accepted:

- **Correlation:** `evidence_version`, scope tuple, `change_id`, `claim_generation`, `call_id`, nullable `dispatch_receipt_id`, and `approval_digest`.
- **Verifier identity:** `verifier_service_id`, `verifier_host_id`, `signer_key_id`, `key_version`, `algorithm=Ed25519`, `role=verification_worker`.
- **Observation:** `observed_at`, `read_session_id`, `target_ref`, pre/observed version tokens, document posting state, canonical field snapshot digest, and canonical lines digest.
- **All movements:** complete normalized multiset of register movements, registrar, versioned register catalogue, count and digest by register, and total `movement_multiset_digest`.
- **Comparison and attribution:** expected/observed effect digests, field and movement matches, version relation, reader health, observation completeness, effect presence/identity, completion proof class, attribution result and evidence reference, and explicit uncertainty list.
- **Signature:** canonical evidence digest and verifier signature.

For `CREATE_DRAFT`, `OutcomeEvidence.pre_version` is null and `target_ref`/`observed_version` from the independent read-back must equal the writer receipt's returned target/version; the receipt's `expected_target_ref` and `expected_pre_version` are both null. For `POST` and `UNPOST`, the approved pre-image `target_ref` and `pre_version` are required and non-null; absence fails closed. The independent read-back must name that exact target, and its observed version must equal the writer receipt's returned version while differing from the approved pre-version. The verifier compares these observed tokens; it does not predict a specific new token. The expected movement multiset is defined by an independently maintained, versioned operation-rule matrix for the qualified document shape. CT14's observed movements do not justify a universal fixed movement count. Draft creation expects an unposted document and no unexpected registrar movements; posting expects the qualified posted state and complete allowed movements; unposting expects the unposted state and the qualified treatment of prior movements.

### 2.3 Completion proof

`CompletionProof` is a separate signed record with required fields `proof_version`, `completion_proof_id`, full scope tuple, `change_id`, `claim_generation`, `dispatch_generation`, `dispatch_cas_id`, `call_id`, `operation_kind`, `writer_process_instance_id`, nullable `onec_session_instance_id`, `proof_class`, `source_service_id`, `source_host_id`, `source_process_instance_id`, nullable `source_session_instance_id`, nullable `observed_session_instance_id`, `evidence_ref`, `evidence_digest`, `observed_at`, `signer_key_id`, `key_version`, `signer_role`, `algorithm`, `canonical_evidence_digest`, and `signature`; nullable fields are explicit JSON null. `writer_process_instance_id` and `onec_session_instance_id` identify the process/session whose call completion is claimed; `source_*` fields identify the process/service/host/session signing the proof; `observed_session_instance_id` records the exact 1C session observed by a supervisor. `source_session_instance_id` identifies the source service's own session and is not interchangeable with the observed 1C session.

1. **`WRITER_CALL_RETURNED`:** the exact registry-authenticated writer process attests that its COM mutating invocation returned, binding `call_id`, `dispatch_generation`, non-reusable `writer_process_instance_id`, service/host, 1C session instance, operation and return boundary. Require `signer_role=writer_receipt` and validate `source_process_instance_id == writer_process_instance_id == DispatchReceipt.writer_process_instance_id` (or the dispatch-attempt process binding when the receipt is not yet durable); `source_service_id` and `source_host_id` must also equal the writer service and host bound to that attempt. Where a 1C session instance is available, `observed_session_instance_id` must equal it. This class proves completion only for the exact COM method and topology qualified to have no deferred server-side application after return. It does not by itself prove the effect or its attribution; CT14 does not establish this property for client-server topology.
2. **`INDEPENDENT_SESSION_AND_PROCESS_CLOSED`:** an independently registry-authenticated host/session supervisor attests that the exact writer `writer_process_instance_id` and corresponding `onec_session_instance_id` are closed and that the platform can no longer execute or resume that invocation. Here `source_*` identifies the supervisor, and must validate to a registered `completion_supervisor` service/key/process identity with `signer_role=completion_supervisor`; it is intentionally distinct from the writer. `observed_session_instance_id` must equal the 1C session instance bound to the call when available. The signed evidence reference identifies the supervisor's authoritative closure observation for the exact writer process/session instances. A host process exit alone, a recyclable PID, a client disconnect, or a timeout is insufficient.

Each proof signs its proof class, source identity, evidence reference/digest, observed time, operation, non-reusable writer process/session instances, supervisor process identity where applicable, and common scope/change/generation/CAS/call binding. The ledger accepts it only after registry and signature validation. If neither class can be established, retain `APPLY_UNKNOWN`, `POSSIBLY_EXECUTING`, locks, reservation and base-wide hold. A complete read-back does not prove completion. Forced termination is prohibited. If the platform cannot distinguish failure before write from an already-started call, classify it as `POST_START_UNKNOWN`.

## 3. State, retry, and fencing rules

| Observed boundary | Classification and ledger behavior | Retry/hold rule |
|---|---|---|
| No permit or `DISPATCHED` compare-and-set (CAS) | `PRE_DISPATCH`; cancellation is safe only with durable proof that dispatch was impossible. | No physical call occurred. |
| COM validation refuses before mutating `Write`, with signed stage proof and operation-specific no-effect evidence | `PRE_WRITE_NO_EFFECT`. | T8 may release reservations and locks under the frozen transition rules. A refusal code alone is insufficient. |
| Timeout, disconnect, cancellation, crash or unclassified error after write may have started | `POST_START_UNKNOWN`; ledger enters `APPLY_UNKNOWN`, call ownership `POSSIBLY_EXECUTING`. | Do not retry. Keep target/base locks, lease and reservations; retain base-wide hold pending completion and reconciliation. |
| Writer reports success but receipt persistence/SQL acknowledgment is lost | `RECEIPT_PERSISTENCE_UNKNOWN`. | Do not issue another physical call; recover evidence or reconcile. |
| Receipt exists, independent verification is pending | `APPLIED` only with sufficient writer completion/result evidence; remains `NOT_VERIFIED`. | Maintain target exclusivity until independent read-back. |
| Full observation shows no effect but physical completion is unproven | `APPLY_UNKNOWN`. | Do not release base hold or permit a new dispatch. Missing marker/row or elapsed deadline is not proof of absence. |
| Effect exists but cannot be attributed to this `call_id` | `TRIAGE_REQUIRED`; attribution remains unproven. | No automatic `PROVEN` attribution. Any exceptional resolution requires the separately governed two-person path. |

For every governed operation, the server sets a mandatory receipt policy by operation type; callers cannot opt out. The durable dispatch intent and requirement are server-authoritative and atomically bound to the allowed state transition. Scope `(tenant, company, organization, base_fingerprint)` binds approval, target, permit, call, receipt and outcome evidence; any mismatch fails closed.

Every `claim_generation` has one permitted `call_id`. Ledger CAS `PERMITTED → DISPATCHED` is durably recorded before invoking COM. A duplicate request for that call returns the existing state/evidence and never invokes COM again. A new generation cannot bypass an unresolved earlier physical call. A post-start error, unresolved result or missing receipt never becomes `FAILED_APPLY` merely because a deadline passed.

In the local in-memory fixture, interruption after `DISPATCHED` but before the writer-invocation counter is consumed recovers to `APPLY_UNKNOWN` with the base hold retained and invocation count zero. The fixture has no signed supervisor no-invocation event or API to release that hold; it deliberately leaves resolution to a future qualified recovery path. This fail-closed terminal state is not production recovery evidence.

`APPLIED` requires sufficient writer completion/result evidence plus the required `DispatchReceipt`; `VERIFIED` requires separate independent `OutcomeEvidence`. Writer receipt, verifier evidence and checkpoint signing use separate Ed25519 identities. Key purpose, version, role, scope and signer are checked. Receipt/audit persistence failure after the physical call fails closed and preserves the unresolved hold.

## 4. Schema and migration boundary

Migrations 016–021 are checksum-recorded prototype history and are not edited or treated as production-ready. The current synthetic receipt guard is not the v2.0 enforcement contract. Any future trusted COM implementation requires additive, versioned schema selected after inspecting the then-current migration registry; do not assume a migration number in advance. It must represent:

1. durable dispatch intent and server-owned per-operation receipt policy;
2. immutable signed `DispatchReceipt` and its mapping/call manifest;
3. independent signed `OutcomeEvidence` and `CompletionProof` linked to the same scope, generation and `call_id`;
4. execution fencing, fail-closed audit transitions and immutable linkage between expected and observed effects.

No production database migration is authorized by this freeze. Prototype schema work, if separately accepted, remains isolated and additive.

## 5. Acceptance matrix for local engineering

These criteria guide later local fake-port implementation and the designated test agents. They are not runtime evidence and do not close a gate by themselves.

| Contract item | Required falsifiable evidence | State after this document |
|---|---|---|
| Frozen envelope, digest and mapping | Closed versioned field list; canonical bytes; mapping manifest; cross-language fixtures. | Synthetic canonical encoding/signature helpers and focused evidence tests recorded in CR121; cross-language interoperability remains unverified. |
| Dispatch uniqueness and fencing | Concurrent calls, stale generation, CAS winner, crash windows, and no second fake-port call. | Process-local synthetic concurrency and single-call behavior covered by the prior E2E run in CR121; cross-process/database fencing remains unimplemented. |
| PRE_WRITE versus unknown | Inject failures before/after call start, lost acknowledgment and receipt-persistence failure. | Synthetic unknown/hold and recovery cases recorded in CR121. MAJOR-01 showed reconciliation could replace retained evidence; CR123 records 7/7 focused functional and 1/1 E2E regression cases passing on the local in-memory fix. |
| Independent outcome | Field, line, version and all-register checks; reject extra/missing movements and marker manipulation. | Synthetic operation/state/version/target matching and contradiction cases recorded in CR121; independently qualified 1C observations and full register adapter remain open. |
| Cryptographic separation | Wrong-role/purpose/key, cross-tenant, invalid-signature, stale/recycled process-instance, wrong dispatch-CAS and writer-versus-supervisor identity cases; role ACL behavior. | Synthetic signature, role, attempt, and permit binding evidence recorded in CR121; deployed identity registry, key custody, and database role ACL qualification remain open. |
| Synthetic end-to-end | Approval → permit → one dispatch → writer evidence → verifier evidence → correct terminal state. | Prior local synthetic E2E 20/20 recorded in CR121; candidate `7c26c0c` was rejected for push due to evidence replacement. CR123 records the fix and passing 1/1 focused E2E scenario; fresh review and exact-head push decision remain pending. |
| Real COM qualification | Licensed authenticated host, service identity, mapping, independent read-back and effective grants; qualify that `WRITER_CALL_RETURNED` means no deferred application for the exact method/topology, or disable that proof class there. | External environment and identity evidence open; not part of local freeze. |

Candidate `7c26c0c` received exact-head GPT review request `e16939f8-9a6f-4c82-a75c-feb6a594a909`; the decision was REJECT for one local synthetic MAJOR: reconciliation could replace previously attached `DispatchReceipt` or `CompletionProof`. CR123 records the evidence-immutability fix, passing focused functional 7/7 and E2E 1/1 results, and independent code/reliability reviews with no BLOCKER/MAJOR. This rejection does not revoke the approved design artifact; push remains blocked until a fresh exact-head decision.

The accepted design DoD is: both evidence contracts and their distinct signers are normative; mandatory receipt policy and all post-start crash windows are defined; v2.0 exclusions are explicit; required acceptance scenarios and external dependencies are recorded; independent design, database and security reviews have no open BLOCKER/MAJOR. This closes only the local design artifact, not formal S12 qualification.

### 3.1 Authorization freshness at the last pre-COM boundary

The authenticated writer revalidates the current operation kind, exact scope, target version, `change_id`, claim generation, one-time approval and approver/requester entitlement dependencies, approval expiry, permit validity/signature, key validity/revocation, and kill-switch state immediately before the durable `PERMITTED → DISPATCHED` CAS. It repeats the authority/permit/kill-switch check immediately before invoking COM. Any mismatch, revocation, expiry, or unavailable authoritative source prevents the COM call. An undispatched permit is invalidated when any bound entitlement dependency or authority epoch changes. The CAS records an authorized dispatch attempt before the physical call; it does not itself prove that COM was entered.

If the final pre-call check refuses after the CAS, the change may take the inherited T8 `PRE_WRITE_NO_EFFECT` path only through the signed `DispatchReceipt` variant defined in §2.1, bound to the exact CAS/process/session and proving the COM mutating method was never entered; the per-call writer guard must prove no second invocation can run. The refusal receipt, terminal no-effect state and audit event commit atomically; only then may the locks, lease and reservation be released. If that proof is unavailable, malformed, or not durably recorded (including a writer crash after CAS), the outcome is `APPLY_UNKNOWN` and the base-wide hold remains. This is the narrowly scoped no-effect exception to the rule that a committed `DISPATCHED` CAS cannot be cancelled by T6c; it does not permit retry under the same call or generation. The narrow revocation race after the final check is an explicit system limitation; no atomicity between an external identity provider and a physical COM operation is claimed.

### 3.2 Relational and transaction invariants

The eventual additive schema must enforce, rather than merely document, these composite relationships. Every key contains the immutable `(tenant_id, company_id, organization_ref, base_fingerprint, change_id, claim_generation, call_id)` scope where applicable; permit/intent rows may use the prefix that exists before call assignment, with a unique parent key for the final `call_id` binding.

- One immutable dispatch-intent row and one `call_id` per `(tenant_id, company_id, change_id, claim_generation)`; the intent binds `dispatch_generation` and `operation_kind`. A separate immutable dispatch-attempt/CAS record binds `writer_process_instance_id` and nullable `onec_session_instance_id` before the physical call. Both have unique scope-bound parent keys. A call ID cannot be reused across generations or scopes; process-instance IDs identify one service lifetime and may legitimately bind multiple distinct calls in that lifetime.
- The permit references that exact intent/generation/scope by composite foreign key. The dispatch-attempt/CAS record references the intent and stores the authenticated process/session instance binding. Receipt, outcome and completion-proof records reference that exact attempt and parent tuple with composite foreign keys or equivalent database-enforced constraints; the completion-proof foreign key includes `dispatch_cas_id`. Caller-supplied UUID equality alone is insufficient. The ledger verifies a completion proof's writer process/session instance against exactly one attempt and, when present, the receipt before accepting it.
- At most one immutable `DispatchReceipt` per call tuple. `OutcomeEvidence` and `CompletionProof` are immutable, uniquely identified, and cannot attach to any other scope/generation/call. Evidence may be appended as observations, but a terminal state transition references one exact validated evidence ID.
- A database transition guard prohibits `APPLIED` or `VERIFIED` for a governed operation unless its matching required `DispatchReceipt` exists and is valid. `OutcomeEvidence.dispatch_receipt_id` may be null only while the record remains unresolved (`APPLY_UNKNOWN`/`TRIAGE_REQUIRED`) because no receipt was durably recorded; it cannot support `APPLIED` or `VERIFIED`. Pre-dispatch refusals with proof of no dispatch have no receipt and cannot enter `APPLIED`.
- Receipt policy is derived from the immutable governed operation kind and is not caller-writable. All three v2.0 operations require it; there is no legacy or opt-out path for this operation class.

Dispatch follows the inherited S12 checkpoint order exactly: (1) one database transaction atomically persists `APPLYING`, dispatch intent, mandatory policy, generation/call ownership and pre-image; dispatch remains `NOT_PERMITTED`; (2) write the signed external checkpoint covering that committed head and read it back; (3) issue the generation-bound permit only after successful checkpoint read-back; (4) the writer revalidates authority and atomically commits the `PERMITTED → DISPATCHED` CAS with its audit event; and (5) after the CAS, rechecks authority immediately before invoking COM. The checkpoint covers the intent/ownership head, while the permit binds the subsequent CAS and call identity; no claim is made that the external checkpoint already contains the later CAS. Each database transaction commits before any external checkpoint or COM call as applicable; no database transaction or row lock is held across checkpoint I/O or COM. Receipt/evidence insertion and the associated state/audit transition are atomic within the database. If persistence fails after dispatch, keep the unresolved hold and recover idempotently; never repeat the physical call. Database constraints and triggers fail closed on cross-scope/generation attachment or missing mandatory evidence.

## 6. Explicitly open evidence and gates

This ruling changes no gate or release state: G0 is passed only for its isolated prototype scope; G1–G8 are not passed; Release 2 remains `NO-GO`; production authorization remains `NONE`; R-01 and R-03 remain formally `OPEN`; S12 formal qualification remains open; S13 formal entry remains unapproved. Real COM and production acceptance still require licensed-host, identity, key custody, effective-grant, source, accounting, UAT, operational-capacity and gate-specific authority evidence. These must be recorded as `NOT_RUN`/open with exact dependencies where unavailable; design text, simulated tests, agent review or an exit code of zero cannot be relabeled as runtime `PASS`.

The existing S12 draft revision 6 remains a historical preparatory draft until an explicit reconciliation is reviewed. Its identity derivation, distinct requester/approver rule, one-time nonce, scope binding, epoch dependency, generation fencing, kill-switch and state-transition controls remain in force where they do not conflict with this freeze. The present document supersedes its operation scope only for v2.0 and augments its evidence contracts; it does not waive the earlier authorization controls. Where an inherited detail is not explicitly restated here, the revision 6 contract remains the governing design reference until the reconciliation package links its exact applicable clauses.

## 7. Authority record

GPT project-owner ruling `d289d167-b1f2-43d7-a17a-e01891748eb3` (reply `0d9e7e0e-9792-4b8a-8c77-b1af5fd6af72`) approves OPTION A and the operation scope above. It expressly rejects treating one mixed writer/verifier receipt, marker, JSON hash, success response or timeout as sufficient evidence. It expressly leaves formal gates unchanged and authorizes the next engineering action: record the two versioned evidence contracts, mandatory policy and crash-window/acceptance matrix, then independently review local fake-port scenarios. It does not authorize real COM, production changes or deployment.
