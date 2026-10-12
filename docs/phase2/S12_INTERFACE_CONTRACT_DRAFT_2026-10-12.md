# S12 interface contract draft: governed purchase-receipt write (2026-10-12, revision 2)

Status: DRAFT of the S12 preparatory design (documents only). It authors the actual interfaces that the plan's contracts CT1-CT15 require; it freezes nothing and approves no code. Authority: GPT-PM S11 exit verdict of 2026-10-12 (preparatory design authorized, formal S12 entry pending the operator person id, interface freeze needs its own review). Scope: purchase receipt create, post, unpost on COM / file base, measured shape only (CT14 record). Unresolved inputs are explicit and are never filled with invented values: operator person id (D10), checkpoint host and signer (D9), write-service host (D4 detail), OB-01, OB-15.

Revision 2 corrects the independent security review (8 findings: 1 BLOCKER for freeze, 7 MAJOR) and the independent reliability review (10 findings: 1 BLOCKER, 9 MAJOR) in one batch. Reviewer claims were checked against the draft text and the plan; every finding below that is marked "reviewer" is a reviewer claim that the draft text confirms, not a measurement.

## 1. Vocabulary and identities

- `tenant`, `company` (organization in 1C), `base_fingerprint` (authenticated infobase id plus epoch, CT4), `scope` = the tuple (tenant, company, base_fingerprint); the scope tuple is immutable for the life of a change (I15).
- `person_id`: the trusted registry identity of a human; several accounts of one person are one person. `principal`: the authenticated OAuth subject of a session; mapped to a person only by the registry, never by caller arguments (CT1).
- `change_id`: UUID of one immutable proposal. `request_id`: the client-supplied idempotency token. `logical_key` = (requester principal, change kind, scope tuple, request_id). `payload_digest` = SHA-256 of the canonical payload plus the target version (CT2).
- `auth_epoch`: the live authorization epoch (S11-C): a monotone number per (tenant, company) that changes on any change of entitlement, role grant, source or target-registry status. A change records the `epoch_dependencies` it actually relies on (requester entitlement, approver entitlement, source status, target-registry status); only a change to one of those voids it (R-10).
- `hold`: a durable row (base, cause, change_id, opened_at, released_at, release_evidence) with cause in {CALL_OWNERSHIP, ANCHOR_GAP, FAILED_VERIFY_HALT, RLC_UNCLEAN}. "Base in hold" means at least one unreleased row exists. Holds are not a stored dimension of a change (R-01).

## 2. Caller classes and endpoints (security F1)

Every ledger operation is reachable only through a closed endpoint matrix. Identities are derived by the service from the authenticated token and the principal registry; no identity field (requester, approver, operator, signer) is ever accepted as a request argument.

| Caller class | Authenticated by | Operations it may invoke | Never |
| --- | --- | --- | --- |
| requester (human via ChatGPT/Claude) | OAuth subject mapped to a person by the registry | `propose`, `validate`, `claim`, `begin_apply` (own changes only), `read_status` | `approve`, `resolve_unknown`, `verify`, `kill_switch`, `operator_resolve`, any `budget_*` |
| approver (human) | OAuth subject mapped to a registered approver person, MFA-level claim, entitled at the live epoch | `approve`, `reject`, `read_status` | everything the requester does on a change he approves |
| operator (D10: the operator person, test-lane auto-approval is a separate visible rule) | operator credential, separate from approver sessions | `kill_switch`, `operator_resolve`, `release_hold`, `budget_admin` | `approve` of a change that he proposed |
| writer process | service identity of the write host, mTLS plus apply-ticket | `complete`, observation reads, `record_call` | `propose`, `approve`, `claim`, `kill_switch` |
| recovery/verification worker | service identity, separate from the writer | `recover_sweep`, `resolve_unknown`, `verify` | any 1C mutation; any approval |
| auditor | read-only credential | `read_status`, `read_evidence` | every mutation |

`complete`, `resolve_unknown` and `verify` accept evidence records only from the writer or the worker identity; a requester-class token calling them is refused with `NOT_ENTITLED`. Approval requires an attested record (section 4, `approve`): a one-time nonce issued to the approver's authenticated session and consumed once; a nonce is bound to (change_id, digests, expiry) and its state goes ISSUED then CONSUMED or EXPIRED. Evidence records (field, movement, version, authorization receipt) are produced by the verifier identity, carry its signature over (change_id, evidence kind, content hash, observed_at), and the ledger refuses an unsigned or wrongly bound record.

## 3. ChangeProposal (typed, purchase receipt only)

Common envelope (all kinds): `change_id`, `kind` in {CREATE_DRAFT, UPDATE_DRAFT, POST, UNPOST}, `scope`, `requester_principal` and `requester_person_id` (server-derived from the token, section 2), `request_id`, `parent_change_id` (null for CREATE_DRAFT; the applied and VERIFIED draft change for POST; the VERIFIED post change for UNPOST), `target_ref` (null for create), `target_version` (null for create), `payload` (kind-specific), `payload_digest`, `preview_digest`, `auth_epoch_at_proposal`, `epoch_dependencies`, `created_at` (UTC), `expires_at` (UTC), `reason` (free text, never an authority).

CREATE_DRAFT payload (all fields typed, no free-form keys, unknown keys refused, I2): `organization_ref`, `counterparty_ref`, `contract_ref`, `supplier_document_number`, `supplier_document_date`, `currency`, `lines[]` each {`item_ref`, `quantity` (decimal string), `price` (decimal string), `vat_rate_code`, `amount` (decimal string)}, `comment` (text, stored verbatim and never evaluated), optional `duplicate_override` {`duplicate_of_change_or_ref`, `justification`} (R-07; honored only when the approver binds it explicitly, section 4). The measured shape is the only admitted shape; any other combination of line kinds, VAT mixes or currencies is refused with `SHAPE_NOT_QUALIFIED` until its own measured fixtures exist (operation rule table).
UPDATE_DRAFT payload: the same fields as a full replacement of the draft, plus `expected_target_version`; a partial or free-form patch is not allowed. If a business-key field changes (supplier number, date, counterparty, contract) the same duplicate re-check and key lock as CREATE_DRAFT apply (R-07).
POST and UNPOST payload: empty; they carry `target_ref`, `target_version`, `business_state_digest` (fields, lines, totals, dependents set, period status) and `allowed_effects`.

`allowed_effects` is server-derived, never caller-supplied (security F2): the service computes the permitted register set from the operation rule table for the kind and shape, shows it in the preview, and it becomes part of the signed digest. A caller-supplied `allowed_effects` is refused with `SCHEMA_INVALID`.

Rules: references are resolved only inside the scope (a ref from another company or base is refused before any write, TM18); numeric fields are decimal strings, never floats; the canonical form sorts keys and normalizes decimals. The approval digest covers: change_id, kind, scope, payload, target_ref, target_version, `business_state_digest`, server-derived `allowed_effects`, the operation rule table version, `epoch_dependencies`, `parent_change_id`, `duplicate_override` and `expires_at` (security F3).

## 4. States (CT10) and legal transitions

Dimensions stored as one record with attributes: `lifecycle` {PROPOSED, VALIDATED, REJECTED, EXPIRED_QUEUED, DUPLICATE_PARKED}, `authorization` {NONE, APPROVED, CLAIMED, VOIDED, REVOKED, EXPIRED}, `execution` {NOT_STARTED, APPLYING, APPLY_UNKNOWN, APPLIED, FAILED_APPLY, TRIAGE_REQUIRED, ROLLBACK_REFUSED}, `verification` {NOT_VERIFIED, VERIFIED, FAILED_VERIFY}, `call_ownership` {NONE, PROVEN_FINISHED, POSSIBLY_EXECUTING}, `effect_known` {YES, NO, UNKNOWN} (FAILED_VERIFY only), `reservation` {NONE, RESERVED, CONSUMED, RELEASED}.

CLAIMED is a stored state with a claim TTL (default 120 s) and its own exit (reliability R-02). Locks held per state are listed in section 7.

| # | From | Event | Guard (all must hold, re-read live) | To | Notes |
| --- | --- | --- | --- | --- | --- |
| T1 | (none) | propose | schema valid, scope resolved, requester entitled, logical_key unused or same digest, epoch read | PROPOSED | same logical_key with other digest: `IDEMPOTENCY_CONFLICT`; same digest: return the earlier receipt |
| T2 | PROPOSED | validate | preview built server-side, business key checked, budget pre-check, shape qualified, allowed_effects derived | VALIDATED | a business-key collision without an override moves to DUPLICATE_PARKED (terminal for this change; a new proposal with `duplicate_override` is the only way on) |
| T3 | PROPOSED, VALIDATED, APPROVED | reject or expire | approver reject, or `expires_at` passed (sweep-driven) | REJECTED, EXPIRED_QUEUED, authorization = EXPIRED | terminal, no effect possible, no reservation |
| T4 | VALIDATED | approve | approver person differs from requester person, nonce consumed (section 2), approval binds the digest set of section 3, approver entitled at this epoch | authorization = APPROVED | approval is a ledger record bound to the nonce, not a flag set by the caller; test-lane auto-approval is a distinct approval type shown in audit (D10) |
| T5 | APPROVED | claim | caller is the requester, approval unexpired, epoch dependencies unchanged, kill switch off (STOP_ADMIT and above refuse), base not in hold, parent change VERIFIED (POST, UNPOST), scope tuple and target class equal the approved ones, (base, target) lock and (base, business-key-hash) lock free, writer lease for the base free, budget RESERVED, all in one transaction | authorization = CLAIMED, execution = NOT_STARTED | the claim token is bound to (change_id, scope, digest set, claim epoch) and is single use; the same token replayed returns the same result |
| T5x | CLAIMED | release_claim | claim TTL expired, or a T6 guard failed before any call | authorization = APPROVED (or EXPIRED when the approval expired), locks, lease and reservation released | sweep-driven and idempotent (W4) |
| T6 | CLAIMED | begin_apply | one atomic section under the base writer lock: epoch dependencies equal the claim epoch, kill switch off, no unreleased hold, approval unexpired, target version equals the approved version, base fingerprint authenticated by connecting, dependents set and period status equal the digest, then: intent-to-apply event appended, checkpoint obtained for that event, then the APPLYING event and the call-ownership row committed BEFORE the call | APPLYING | order of three steps (R-04): intent event + checkpoint, then APPLYING + ownership row, then send. A failed checkpoint rolls back to T5x state: no call, no unknown, approval survives. The same token returns the same apply ticket (idempotent re-fetch) |
| T7 | APPLYING | call returned success | the write returned a result to the writer | APPLIED, call_ownership = PROVEN_FINISHED, reservation = CONSUMED | verification due |
| T8 | APPLYING | writer refused before or during the call | classified by the writer's refusal code: definite no-state-change (`WRITE_REFUSED`, `STALE_VERSION`, `DUPLICATE_SUSPECTED`) vs transient (`LOCK_BUSY`) | definite: FAILED_APPLY, reservation = RELEASED, locks released; transient: back to APPROVED with a durable attempt counter (max 5, exponential interval with jitter, 15 min window), then the definite path | a transient refusal never burns the approval before the bound is hit; only with CONFIRMED_NOT_APPLIED |
| T9 | APPLYING | timeout, lost connection, writer crash, ambiguous error | none of T7 or T8 proven | APPLY_UNKNOWN; if the call returned a result the call_ownership is PROVEN_FINISHED (no base hold), otherwise POSSIBLY_EXECUTING and a CALL_OWNERSHIP hold on the base | target lock kept; reservation kept. A returned-but-ambiguous error parks only the target (CT3, CT15) |
| T10 | APPLY_UNKNOWN | resolve: found | reader-health proof, settle period, complete observation, AND the effect identity of section 5 holds | APPLIED, reservation = CONSUMED | requires an actual 1C read; identity ambiguity routes to TRIAGE_REQUIRED, never to APPLIED |
| T11 | APPLY_UNKNOWN | resolve: absent | reader-health proof, settle period, complete observation, AND call_ownership = PROVEN_FINISHED proven by observation (not by a deadline) | FAILED_APPLY (CONFIRMED_NOT_APPLIED), reservation = RELEASED, locks released | a missing marker alone never qualifies |
| T12 | APPLY_UNKNOWN | age limit | 5 attempts (durable counter, interval 3 min with jitter) over 15 minutes without resolution | TRIAGE_REQUIRED | alert to a human within 60 s; reservation and hold kept until T16 |
| T13 | APPLIED | verify | independent read of fields, registrar movements (multiset over every register with a recorder) and version token matches the oracle and the operation rule table | verification = VERIFIED, locks released | a six-column match or an audit acknowledgement is never evidence; verification has a retry bound of 3 attempts and an owner (the worker) |
| T14 | APPLIED | verify fails | unexpected or missing movement, field or version | FAILED_VERIFY, effect_known recorded, FAILED_VERIFY_HALT hold | alert; the reservation stays CONSUMED (the effect exists). `effect_known = NO` means "no effect observed after APPLIED was recorded" and routes to T17 for operator attestation, never to a silent refund |
| T15 | NOT_STARTED, CLAIMED (pre-APPLYING) | revoke | session or role revoked, approver revoked, a listed epoch dependency changed | authorization = VOIDED or REVOKED, execution refused, locks and reservation released | a new approval is needed; unrelated epoch changes do not void |
| T16 | TRIAGE_REQUIRED | operator_resolve | signed operator event with evidence class ATTESTED_FINISHED, ATTESTED_ABSENT or ATTESTED_PRESENT; the operator is not the change's requester or approver | ATTESTED_PRESENT: APPLIED (reservation CONSUMED); ATTESTED_ABSENT or ATTESTED_FINISHED-without-effect: FAILED_APPLY (reservation RELEASED); CALL_OWNERSHIP hold released | the only exit from TRIAGE_REQUIRED; operator-only; the event is hash-chained and checkpointed |
| T17 | FAILED_VERIFY | retry_verify or rollback | retry verify (bound 3), or an UNPOST change (its own chain) claimable during FAILED_VERIFY_HALT because a repair never needs the halt cleared; operator attestation for `effect_known = NO` | VERIFIED, or a new UNPOST chain, or FAILED_VERIFY closed by operator | observation reads are always allowed under any hold |
| T18 | APPLIED (POST/UNPOST precondition fails) | rollback refused | dependents exist or the period is closed, detected inside the writer lock | execution = ROLLBACK_REFUSED, the document unchanged | `ROLLBACK_REFUSED` is a lifecycle outcome, terminal for this change |

Hold release conditions (R-01): CALL_OWNERSHIP is released by T10/T11/T16 or by proof that the 1C session ended; ANCHOR_GAP when the checkpoint store accepts the missing head again and the head chain is verified; FAILED_VERIFY_HALT by T17; RLC_UNCLEAN by the S13 resume procedure. A hold blocks claim and begin_apply of any other mutation; observation reads, `operator_resolve`, `release_hold`, `kill_switch` and repair UNPOST are allowed.

Forbidden transitions (tested against a literal list, E45): FAILED_APPLY from a timeout; APPLY_UNKNOWN to APPLIED without a 1C read; APPLIED to VERIFIED without T13; any transition out of REJECTED, EXPIRED_QUEUED, DUPLICATE_PARKED, ROLLBACK_REFUSED or FAILED_APPLY except a new proposal; VERIFIED to anything. POST and UNPOST are separate changes with their own chains; posting needs its own approval and a re-check of the document version, dependents and period under the writer lock immediately before the effect (CT7).

## 5. Effect identity for unknown-outcome resolution (reliability R-05)

The marker is never evidence (section 9). Resolution of APPLY_UNKNOWN requires the observed state to be reachable only through this change:

- CREATE_DRAFT: a document with the canonical business key AND content hash equal to the approved payload AND an unreferenced pre-image (no document with that key existed at begin_apply, recorded in the intent event). A matching key with a different content hash goes to TRIAGE_REQUIRED.
- UPDATE_DRAFT: content hash of the full payload equals the approved payload, and the pre-image hash recorded at begin_apply differs from it. Otherwise TRIAGE_REQUIRED.
- POST: the document is posted AND the movement multiset equals the expected multiset AND the document's version token differs from the pre-image token. A human post inside the settle window cannot be told apart from ours by observation alone, so a POST resolution additionally requires that no other session wrote the document inside the window (checked through the platform's change log if available; if not available the result is TRIAGE_REQUIRED).
- UNPOST: the document is not posted AND the movement set is empty AND the pre-image version differs. Same human-edit rule as POST.

Where identity cannot be established the only exit is TRIAGE_REQUIRED and T16. The version token is compared for equality against the pre-image only; a post-write version is never predicted.

## 6. Ledger interface (all operations are transactional and idempotent)

| Operation | Caller class | Input | Effect | Returns |
| --- | --- | --- | --- | --- |
| `propose` | requester | envelope, payload | T1 in one transaction: logical_key uniqueness, epoch read, event appended | change_id, state, receipt |
| `validate` | requester | change_id | T2, business-key lookup in the ledger, budget pre-check, allowed_effects derivation | state or refusal code |
| `approve` / `reject` | approver | change_id, nonce | T4 or T3; approver person derived from the token and differs from requester person; nonce consumed; approval record immutable and signed | approval id |
| `claim` | requester | change_id | T5: guards, reservation, locks in one transaction | claim token (bound, single use, same token = same result) |
| `release_claim` | sweep / requester | claim token or ttl expiry | T5x | state |
| `begin_apply` | requester or writer on behalf of a token | claim token | T6 as one atomic section; ownership row {call id, writer process, host, 1C session, start, hard deadline, attempt counter}; returns the same ticket on replay | apply ticket |
| `complete` | writer | apply ticket, result evidence | T7 or T8 or T9 chosen by the evidence class, never by a caller flag | state |
| `recover_sweep` | recovery worker | none (ledger-driven, idempotent) | handles expired claims, expired approvals, `hard deadline` expiry in APPLYING, stuck verification; produces T5x, T9, T3, T12, T13 retry | list of changed ids |
| `resolve_unknown` | recovery worker | change_id, observation record (signed) | T10, T11 or T12 | state |
| `operator_resolve` | operator | change_id, evidence class, operator evidence | T16 | state |
| `release_hold` | operator | hold id, release evidence | releases ANCHOR_GAP or RLC_UNCLEAN under the conditions in section 4 | hold state |
| `verify` | recovery/verification worker | change_id, signed verification record | T13 or T14 | state |
| `kill_switch` | operator | mode (STOP_ADMIT, STOP_EFFECTS, REVOKE) | durable switch record independent of the ledger, the checkpoint and the anchor; the writer reads it through an authenticated, checkpointed read before every call; unavailable means STOP_EFFECTS | switch state, list of in-flight and unresolved changes |
| `budget_reserve`, `budget_consume`, `budget_release` | internal only (server-derived) | grant, change_id | CT13 matrix; amounts and the grant are derived from the change, `parent_change` is validated, `amount_consumed(document, grant)` is read in the claim transaction; never callable by any external class | reservation |
| `budget_admin` | operator | grant parameters | CT13 grant management | grant |

Kill-switch semantics: STOP_ADMIT refuses `propose`, `validate`, `approve`, `claim`, `begin_apply`; already-claimed changes are released by `release_claim`. STOP_EFFECTS refuses `claim` and `begin_apply`, and the writer aborts before the call when it reads the switch; APPLYING changes follow T9 conservatively. REVOKE additionally voids unclaimed approvals; observation reads needed by `resolve_unknown` remain allowed only under an operator-gated exception recorded in audit. Re-enable runs `recover_sweep` first. The switch engages without a checkpoint. The check for the switch and the call are not atomic; that window is declared (CT9), and the switch is checked inside the same transaction as the APPLYING commit.

Every event has an event id; handlers are idempotent; the event log is append-only with a hash chain. Checkpoint rule (R-04): a signed checkpoint {sequence number, head hash, time} is written to the external store (D9) for the intent-to-apply event before APPLYING and for the approval consumption (T4) and the terminal events T7, T8, T11, T16. Events T10, T13 and observation reads are read-only resolutions and are not required to be checkpointed; they are included in the next checkpoint. A checkpoint that cannot be written blocks new effects (CT5, hold `ANCHOR_GAP`, bounded: at most 15 minutes, then TRIAGE of unresolved items). `COMPLETION_PENDING` obligations and request ids are persisted here (S11-B), never held only in memory.

Authorization epoch (S11-C): `claim` and `begin_apply` each re-read the live epoch dependencies for requester, approver and (tenant, company); a mismatch refuses before any write. The window after the last re-read is declared, not hidden: a single 1C write is atomic and the platform lock covers its duration.

## 7. Writer (1C write port) contract

One writer per base, enforced by a base writer lease taken at T5 and re-checked at T6, held until a terminal or APPLY_UNKNOWN resolution. The port accepts only an apply ticket. Steps for CREATE_DRAFT: authenticate the base fingerprint by connecting; take the create lock keyed by the hash of the canonical business key (already taken at T5 in the ledger; the writer re-takes it as a second defense); re-check absence of a document with that key and of the marker inside the serialized writer; write the document with the marker attribute set in the same write; read back. For UPDATE_DRAFT, POST, UNPOST: take the exclusive object lock, read the version token, compare with the approved version, re-check dependents and period status against the approved `business_state_digest`, write, release. A parent that is not VERIFIED (FAILED_VERIFY, NOT_VERIFIED) is refused at T5. Writer refusals map to `STALE_VERSION`, `LOCK_BUSY`, `DUPLICATE_SUSPECTED`, `ROLLBACK_REFUSED` and `WRITE_REFUSED` and are classified transient or definite at T8. The port never calls forced termination; the call has a hard deadline (120 s, posting 300 s) whose expiry only starts the completion determination (CT3), executed by `recover_sweep`. The write identity is the least-privilege extension role (CT14 record, section 6), never an administrator.

Locks per state: the (base, target), (base, business-key-hash) locks and the writer lease are acquired at T5, kept in CLAIMED, APPLYING, APPLY_UNKNOWN and TRIAGE_REQUIRED, released at T5x, T8-definite, T11, T13, T15, T16 (absent/refused), T18. Reservation transitions are tabulated per event in sections 4 and 8.

## 8. Reservation and budget events (reliability R-08)

| Event | Reservation |
| --- | --- |
| T5 | RESERVED (claim transaction) |
| T5x, T15, T8-definite, T11, T16 (absent) | RELEASED |
| T6 failed guard | RELEASED through T5x |
| T7, T10, T16 (present) | CONSUMED |
| T9, T12 | KEPT |
| T14 | CONSUMED (the effect exists); `effect_known = NO` goes to T17 operator attestation, not an automatic refund |
| POST amount accounting | `amount_consumed(document, grant)` is read inside the claim transaction and only the unconsumed part is reserved |
| window expiry mid-call | reservation stays tied to the call outcome; the window is checked at claim only, as declared in CT13 |

Ledger-wide invariant (for the E-series): reserved plus consumed equals the sum over live states, after a kill at every window.

## 9. Evidence contract (S11-D)

Four evidence record types, none convertible into another: field evidence (read-back of typed fields), movement evidence (multiset keyed by registrar over all recorder registers), version evidence (the data version token, compared for equality only), authorization receipt (approval record id, approver, epoch). Each record is signed by the verifier identity over (change_id, kind, content hash, observed_at) and the ledger refuses an unsigned or wrongly bound record (section 2). VERIFIED requires field, movement and version evidence from a read after the effect; expected movements come from the independent oracle and the operation rule table, including an expected empty set for draft, update and unpost. The verifier shares no code with preview, normalization or write serialization (structural import-graph check). The marker is an untrusted label: it is never evidence of application or of non-application.

## 10. Error-code registry (new members of the closed enums; safe, constant text)

`SCHEMA_INVALID`, `SHAPE_NOT_QUALIFIED`, `SCOPE_MISMATCH`, `REF_OUT_OF_SCOPE`, `NOT_ENTITLED`, `APPROVER_NOT_INDEPENDENT`, `APPROVAL_MISSING`, `APPROVAL_EXPIRED`, `APPROVAL_VOIDED`, `APPROVAL_NONCE_INVALID`, `DIGEST_MISMATCH`, `STALE_VERSION`, `IDEMPOTENCY_CONFLICT`, `DUPLICATE_SUSPECTED`, `EPOCH_CHANGED`, `TARGET_REJECTED` (class or fingerprint), `KILL_SWITCH_ACTIVE`, `BASE_HOLD`, `PARENT_NOT_VERIFIED`, `CLAIM_EXPIRED`, `BUDGET_EXCEEDED`, `CURRENCY_NOT_BUDGETED`, `AUDIT_UNAVAILABLE`, `CHECKPOINT_UNAVAILABLE`, `LOCK_BUSY`, `WRITE_REFUSED`, `APPLY_UNKNOWN`, `TRIAGE_REQUIRED`, `ROLLBACK_REFUSED`, `VERIFY_FAILED`, `MARKER_UNTRUSTED`, `EVIDENCE_UNSIGNED`. Each code has one fixed next action and message (import-time completeness guard as in the existing closed enums); no code echoes payload content, credentials, ids of other tenants or paths.

## 11. Crash-window matrix (expected durable state after a kill at each point)

| Window | Kill point | Expected state on recovery |
| --- | --- | --- |
| W1 | before intent committed | no change exists |
| W2 | intent committed, not approved | PROPOSED or VALIDATED, no reservation |
| W3 | claim transaction in flight | rolled back: no claim, no reservation |
| W4 | claim committed, intent or ownership row not committed | CLAIMED, no 1C call possible; the claim TTL elapses and `recover_sweep` runs T5x, releasing locks, lease and reservation |
| W5 | ownership row committed, call not sent | APPLYING; `recover_sweep` at the hard deadline moves to APPLY_UNKNOWN (T9) and resolution follows section 5 (absent plus proven finished leads to FAILED_APPLY) |
| W6 | call sent, no response | APPLY_UNKNOWN, POSSIBLY_EXECUTING, CALL_OWNERSHIP hold |
| W7 | response received, ledger not updated | APPLY_UNKNOWN until observation finds the effect (section 5), then APPLIED; otherwise TRIAGE_REQUIRED |
| W8 | APPLIED recorded, verification not run | APPLIED, NOT_VERIFIED, the worker re-runs verification (bound 3) |
| W9 | checkpoint not written | intent event present without APPLYING: rolled back to CLAIMED/APPROVED; no call, no unknown |

## 12. Open inputs and what the freeze review will need beyond this draft

Open: D10 person id; D9 host, account and signer; write-service host and the licensed COM host details (D4); OB-01 and OB-15 approvals; the physical ledger schema (S13), the principal registry source and the IdP (S16). Changes in revision 2 beyond the review findings are limited to what the findings required. Not claimed: that any of this has been measured or tested; the CT14 items 9, 10b and 13 remain INCONCLUSIVE in the spike record, and section 5 relies on that. This revision is submitted to GPT-PM as the pre-freeze authorization and recovery contract.
