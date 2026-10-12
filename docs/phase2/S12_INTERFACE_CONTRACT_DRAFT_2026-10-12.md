# S12 interface contract draft: governed purchase-receipt write (2026-10-12, revision 3)

Status: DRAFT of the S12 preparatory design (documents only). It authors the actual interfaces that the plan's contracts CT1-CT15 require; it freezes nothing and approves no code. Authority: GPT-PM S11 exit verdict of 2026-10-12 (preparatory design authorized, formal S12 entry pending the operator person id, interface freeze needs its own review). Scope: purchase receipt create, post, unpost on COM / file base, measured shape only (CT14 record). Unresolved inputs are explicit and are never filled with invented values: operator person id (D10), checkpoint host and signer (D9), write-service host (D4 detail), OB-01, OB-15.

Revision 3 corrects the GPT-PM pre-freeze review of revision 2 (2 BLOCKER S12-B01..B02, 10 MAJOR S12-M01..M10) in one batch; it keeps the revision 2 corrections of the independent security review (8 findings: 1 BLOCKER for freeze, 7 MAJOR) and the independent reliability review (10 findings: 1 BLOCKER, 9 MAJOR) in one batch. Reviewer claims were checked against the draft text and the plan; every finding below that is marked "reviewer" is a reviewer claim that the draft text confirms, not a measurement.

## 1. Vocabulary and identities

- `tenant`, `company` (the tenant's legal-entity record; it is not assumed to equal the 1C organization), `base_fingerprint` (authenticated infobase id plus epoch, CT4), `scope` = the tuple (tenant, company, organization, base_fingerprint); the scope tuple is immutable for the life of a change (I15). The organization is carried independently through proposal, approval digest, claim token, apply ticket, audit and the port check; for POST and UNPOST it is derived from the authenticated target read at `propose` and bound immutably, and a payload `organization_ref` that differs from the scope organization is refused with `SCOPE_MISMATCH` (S12-M10).
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
| operator (D10: the operator person, test-lane auto-approval is a separate visible rule) | operator credential, separate from approver sessions | `kill_switch`, `release_hold` (only with machine-verified release evidence), `budget_admin`, co-signing `operator_resolve` | `approve` of a change that he proposed; signing `operator_resolve` alone for a change he approved (S12-M05) |
| recovery witness (D10b, OPEN operator input: a second registered person with recovery authority, never the requester or approver of the change) | separate operator-registry identity | co-signing `operator_resolve` | any other operation |
| writer process | service identity of the write host, mTLS plus apply-ticket | `complete`, observation reads, `record_call` | `propose`, `approve`, `claim`, `kill_switch` |
| recovery/verification worker | service identity, separate from the writer | `recover_sweep`, `resolve_unknown`, `verify` | any 1C mutation; any approval |
| auditor | read-only credential | `read_status`, `read_evidence` | every mutation |

`complete`, `resolve_unknown` and `verify` accept evidence records only from the writer or the worker identity; a requester-class token calling them is refused with `NOT_ENTITLED`. Approval requires an attested record (section 4, `approve`): a one-time nonce issued to the approver's authenticated session and consumed once; a nonce is bound to (change_id, digests, expiry) and its state goes ISSUED then CONSUMED or EXPIRED. Evidence records (field, movement, version, authorization receipt) are produced by the verifier identity, carry its signature over (change_id, evidence kind, content hash, observed_at), and the ledger refuses an unsigned or wrongly bound record.

## 3. ChangeProposal (typed, purchase receipt only)

Common envelope (all kinds): `change_id`, `claim_generation` (integer, section 4), `kind` in {CREATE_DRAFT, UPDATE_DRAFT, POST, UNPOST}, `scope`, `requester_principal` and `requester_person_id` (server-derived from the token, section 2), `request_id`, `parent_change_id` (null for CREATE_DRAFT; the applied and VERIFIED draft change for POST; the VERIFIED post change for UNPOST), `target_ref` (null for create), `target_version` (null for create), `payload` (kind-specific), `payload_digest`, `preview_digest`, `auth_epoch_at_proposal`, `epoch_dependencies`, `created_at` (UTC), `expires_at` (UTC), `reason` (free text, never an authority).

CREATE_DRAFT payload (all fields typed, no free-form keys, unknown keys refused, I2): `organization_ref`, `counterparty_ref`, `contract_ref`, `supplier_document_number`, `supplier_document_date`, `currency`, `lines[]` each {`item_ref`, `quantity` (decimal string), `price` (decimal string), `vat_rate_code`, `amount` (decimal string)}, `comment` (text, stored verbatim and never evaluated), optional `duplicate_override` {`duplicate_of_change_or_ref`, `justification`} (R-07; honored only when the approver binds it explicitly, section 4). The measured shape is the only admitted shape; any other combination of line kinds, VAT mixes or currencies is refused with `SHAPE_NOT_QUALIFIED` until its own measured fixtures exist (operation rule table).
UPDATE_DRAFT payload: the same fields as a full replacement of the draft, plus `expected_target_version`; a partial or free-form patch is not allowed. If a business-key field changes (supplier number, date, counterparty, contract) the same duplicate re-check and key lock as CREATE_DRAFT apply (R-07).
POST and UNPOST payload: empty; they carry `target_ref`, `target_version`, `business_state_digest` (fields, lines, totals, dependents set, period status) and `allowed_effects`.

`allowed_effects` is server-derived, never caller-supplied (security F2): the service computes the permitted register set from the operation rule table for the kind and shape, shows it in the preview, and it becomes part of the signed digest. A caller-supplied `allowed_effects` is refused with `SCHEMA_INVALID`.

Rules: references are resolved only inside the scope (a ref from another company or base is refused before any write, TM18); numeric fields are decimal strings, never floats; the canonical form sorts keys and normalizes decimals. The approval digest covers: change_id, kind, scope, payload, target_ref, target_version, `business_state_digest`, server-derived `allowed_effects`, the operation rule table version, `epoch_dependencies`, `parent_change_id`, `duplicate_override` and `expires_at` (security F3).

## 4. States (CT10) and legal transitions

Dimensions stored as one record with attributes: `lifecycle` {PROPOSED, VALIDATED, REJECTED, EXPIRED_QUEUED, DUPLICATE_PARKED}, `authorization` {NONE, APPROVED, CLAIMED, VOIDED, REVOKED, EXPIRED}, `execution` {NOT_STARTED, APPLYING, APPLY_UNKNOWN, APPLIED, FAILED_APPLY, TRIAGE_REQUIRED, ROLLBACK_REFUSED}, `verification` {NOT_VERIFIED, VERIFIED, FAILED_VERIFY}, `call_ownership` {NONE, PROVEN_FINISHED, POSSIBLY_EXECUTING}, `attribution` {NOT_APPLICABLE, PROVEN, UNPROVEN_OPERATOR_ATTESTED}, `effect_known` {YES, NO, UNKNOWN} (FAILED_VERIFY only), `reservation` {NONE, RESERVED, CONSUMED, RELEASED}, `dispatch` {NOT_PERMITTED, PERMITTED, DISPATCHED}.

CLAIMED is a stored state with a claim TTL (default 120 s). Tickets are generation-bound (S12-M09): each successful T5 increments `claim_generation`; the claim token, the apply ticket, the dispatch permit and every `complete` call carry the generation, the ledger fences on it, and an older generation can only read the existing operation status, never authorize an action. Token state is durable: ISSUED, CONSUMED (by `begin_apply`), SUPERSEDED (by release or re-claim), REVOKED. Re-fetch of an apply ticket returns the existing ticket only while the generation is current and `dispatch` is not DISPATCHED; it never creates a second dispatch permit. The call-ownership row carries one `call_id`, and a call is dispatched at most once per `call_id`; a new dispatch after T9 needs a new change.

Protection of the pre-effect state (S12-M01): no 1C call is sent without a dispatch permit. The permit is an event issued only after (1) the APPLYING event and the call-ownership row are committed in one transaction and (2) a signed external checkpoint whose head hash covers that committed head has been written and read back by the ledger. The writer verifies the permit signature, the generation and the checkpoint sequence against the external store itself before it calls. A restored ledger older than the externally anchored head is detected by the head-hash comparison, opens an ANCHOR_GAP hold, and no blind retry is possible because the permit and the `call_id` are anchored.

| # | From | Event | Guard (all must hold, re-read live) | To | Notes |
| --- | --- | --- | --- | --- | --- |
| T1 | (none) | propose | schema valid, scope resolved, requester entitled, logical_key unused or same digest, epoch read | PROPOSED | same logical_key with other digest: `IDEMPOTENCY_CONFLICT`; same digest: return the earlier receipt |
| T2 | PROPOSED | validate | preview built server-side, business key checked, budget pre-check, shape qualified, allowed_effects derived | VALIDATED | a business-key collision without an override moves to DUPLICATE_PARKED (terminal for this change; a new proposal with `duplicate_override` is the only way on) |
| T3 | PROPOSED, VALIDATED, APPROVED | reject or expire | approver reject, or `expires_at` passed (sweep-driven) | REJECTED, EXPIRED_QUEUED, authorization = EXPIRED | terminal, no effect possible, no reservation |
| T4 | VALIDATED | approve | approver person differs from requester person, nonce consumed (section 2), approval binds the digest set of section 3, approver entitled at this epoch | authorization = APPROVED | approval is a ledger record bound to the nonce, not a flag set by the caller; test-lane auto-approval is a distinct approval type shown in audit (D10) |
| T5 | APPROVED | claim | caller is the requester, approval unexpired, epoch dependencies unchanged, kill switch below STOP_ADMIT, no unreleased hold (a repair UNPOST under its own halt is the only exception, T17), parent change VERIFIED (POST, UNPOST), scope tuple (including organization) and target class equal the approved ones, (base, target) lock, (base, business-key-hash) lock and the writer lease free, budget RESERVED, all in one transaction | authorization = CLAIMED, execution = NOT_STARTED, claim_generation + 1 | the claim token is bound to (change_id, generation, scope, digest set, claim epoch) |
| T5x | CLAIMED | release_claim | claim TTL expired, kill switch at STOP_ADMIT or above, or a T6 guard failed before dispatch | authorization = APPROVED (EXPIRED when the approval expired), token SUPERSEDED, target lock, key lock, lease and reservation released | sweep-driven and idempotent (W4) |
| T6 | CLAIMED | begin_apply | one atomic section under the base writer lock: epoch dependencies equal the claim epoch, kill switch off, no unreleased hold, approval unexpired, target version equals the approved version, base fingerprint authenticated by connecting, dependents set and period status equal the digest, then APPLYING event, call-ownership row (pre-image hashes recorded) in one transaction | APPLYING, dispatch = NOT_PERMITTED | the permit is issued by T6p after the checkpoint |
| T6p | APPLYING (dispatch NOT_PERMITTED) | issue permit | checkpoint covering the T6 head written and read back; kill switch off; generation current | dispatch = PERMITTED, then the writer sets DISPATCHED atomically with the call start (ledger event before the call) | checkpoint failure: T6r |
| T6r | APPLYING (dispatch NOT_PERMITTED) | permit not issued | checkpoint unavailable, kill switch, hold, or permit TTL (60 s) elapsed; no call was ever possible | authorization = APPROVED, execution = NOT_STARTED, token SUPERSEDED, locks, lease, reservation released | proof of no dispatch is the absence of a PERMITTED event plus the writer's signed `never_dispatched` record; if that record cannot be obtained, T9 applies |
| T7 | APPLYING (DISPATCHED) | call returned success | the write returned a result to the writer, with typed result evidence | APPLIED, call_ownership = PROVEN_FINISHED, reservation = CONSUMED, attribution = PROVEN | verification due |
| T8 | APPLYING | writer refused before the write | typed failure-stage evidence signed by the writer: stage PRE_WRITE (the writer's own checks ran before the write call was made, or the platform rejected a stale write before committing), with an operation-specific no-effect proof; a refusal code alone is never enough (S12-M02) | FAILED_APPLY (CONFIRMED_NOT_APPLIED); for an UNPOST precondition refusal (dependents, closed period): ROLLBACK_REFUSED on this change (S12-M08); reservation = RELEASED, locks and lease released | transient `LOCK_BUSY` at stage PRE_WRITE: back to APPROVED with a durable attempt counter (max 5, interval 3 min with jitter, 15 min window), then the definite path. The original document's state is never touched by a refused change |
| T9 | APPLYING | timeout, lost connection, writer crash, late or unclassified error, error after the write call started | none of T7 or a proven T8 | APPLY_UNKNOWN; call_ownership = POSSIBLY_EXECUTING and a CALL_OWNERSHIP hold on the base | target lock, lease and reservation kept. A returned-but-ambiguous error (stage after write start) is T9, not T8 |
| T10 | APPLY_UNKNOWN | resolve: found | call_ownership = PROVEN_FINISHED proven independently (section 5, proof class), reader-health proof, settle period, complete observation, AND the effect identity and attribution proof of section 5 | APPLIED, attribution = PROVEN, reservation = CONSUMED, CALL_OWNERSHIP hold released, lease released | an effect that exists but cannot be attributed goes to T12/TRIAGE_REQUIRED, never to APPLIED |
| T11 | APPLY_UNKNOWN | resolve: absent | call_ownership = PROVEN_FINISHED proven independently (section 5, proof class), reader-health proof, settle period, complete healthy observation of the target scope showing absence | FAILED_APPLY (CONFIRMED_NOT_APPLIED), reservation = RELEASED, CALL_OWNERSHIP hold released, locks and lease released | a missing marker alone never qualifies; a deadline never qualifies |
| T12 | APPLY_UNKNOWN | age limit or unattributable effect | 5 attempts (durable counter, interval 3 min with jitter) over 15 minutes without resolution, or an effect present without attribution proof | TRIAGE_REQUIRED | alert to a human within 60 s; hold, lease and reservation kept until T16 |
| T13 | APPLIED | verify | independent read of fields, registrar movements (multiset over every register with a recorder) and version token matches the oracle and the operation rule table | verification = VERIFIED, target lock and key lock released | a six-column match or an audit acknowledgement is never evidence; retry bound 3, owner = the worker |
| T14 | APPLIED | verify fails | unexpected or missing movement, field or version | FAILED_VERIFY, effect_known recorded, FAILED_VERIFY_HALT hold bound to (change_id, target, observed version) | alert; reservation stays CONSUMED (the effect exists); target lock kept; `effect_known = NO` means "nothing observable after APPLIED was recorded" and needs the T16 evidence rules, never a silent refund |
| T15 | NOT_STARTED, CLAIMED (pre-dispatch) | revoke | session or role revoked, approver revoked, a listed epoch dependency changed | authorization = VOIDED or REVOKED, execution refused, locks, lease and reservation released | a new approval is needed; unrelated epoch changes do not void |
| T16 | TRIAGE_REQUIRED | operator_resolve | the SAME machine proofs as T10 or T11 (independent PROVEN_FINISHED proof, healthy complete observation, and for presence the attribution proof or an explicit unattributed marking) are attached as signed verifier records; two-person signature: operator plus recovery witness, neither being the requester, and not the approver unless the other signer is not (S12-M05); the operator can never substitute for physical-completion evidence (S12-B01) | present and attributed: APPLIED; present and unattributed: APPLIED with attribution = UNPROVEN_OPERATOR_ATTESTED (reservation CONSUMED, any later POST on it needs the approver to bind that flag in the digest); absent: FAILED_APPLY (reservation RELEASED); the CALL_OWNERSHIP hold released only with completion proof | an operator may keep the hold indefinitely; without completion proof the event is refused with `COMPLETION_PROOF_MISSING` and nothing is released |
| T17 | FAILED_VERIFY | retry or repair | retry verify (bound 3); or a repair UNPOST under the repair capability below; or closure with operator evidence per T16 | VERIFIED, or a new UNPOST chain, or the FAILED_VERIFY change closed | observation reads are allowed under any hold |

Repair capability (S12-M04): a repair UNPOST names `repair_for` = the failed change; it bypasses only the FAILED_VERIFY_HALT row whose (change_id, target, observed version) equal the repair's, requires a fresh independent approval (approver differs from requester and approves the repair digest including `repair_for`), the current version equal the halt's observed version, and no other unreleased hold of any cause, kill switch off. It never bypasses CALL_OWNERSHIP, ANCHOR_GAP, RLC_UNCLEAN or any STOP mode.

Proof classes for PROVEN_FINISHED (S12-B01): (a) the writer's own signed completion record for this `call_id`; (b) observed end of the 1C session and of the writer process hosting the call (recorded by the worker from the host, not by the writer); (c) forced termination, which stays DISABLED (CT14 item 9). Absent (a) or (b), a hung call with a live process keeps the base held; the operator's manual stop of the licensed COM host is an operator-owned action outside the port and produces proof class (b). No other proof exists.

Hold release conditions (R-01): CALL_OWNERSHIP by T10/T11/T16 (with completion proof); ANCHOR_GAP when the checkpoint store accepts the missing head again and the head chain is verified; FAILED_VERIFY_HALT by T17; RLC_UNCLEAN by the S13 resume procedure. A hold blocks claim and begin_apply of any other mutation; observation reads, `operator_resolve`, `release_hold`, `kill_switch` and the matching repair UNPOST are allowed.

Forbidden transitions (tested against a literal list, E45): FAILED_APPLY from a timeout; APPLY_UNKNOWN to APPLIED or FAILED_APPLY without independent PROVEN_FINISHED; APPLIED to VERIFIED without T13; any transition out of REJECTED, EXPIRED_QUEUED, DUPLICATE_PARKED, ROLLBACK_REFUSED or FAILED_APPLY except a new proposal; VERIFIED to anything. POST and UNPOST are separate changes with their own chains; posting needs its own approval and a re-check of the document version, dependents and period under the writer lock immediately before the effect (CT7).

### 4.1 Consolidated lock, lease, hold and reservation matrix (S12-M03)

Lock kinds: TL = (base, target) lock; KL = (base, business-key-hash) lock; WL = base writer lease; H = holds. State after each transition (A = acquired, K = kept, R = released, - = not involved).

| Transition | TL | KL | WL | Hold effect | Reservation | Proof for the release |
| --- | --- | --- | --- | --- | --- | --- |
| T5 | A | A | A | none | RESERVED | claim transaction |
| T5x, T6r | R | R | R | none | RELEASED | no PERMITTED event, signed `never_dispatched`, or TTL expiry |
| T6, T6p | K | K | K | none | KEPT | - |
| T7 | K | R | R | none | CONSUMED | writer completion record (proof class a) |
| T8 definite, T8 ROLLBACK_REFUSED | R | R | R | none | RELEASED | signed PRE_WRITE stage evidence |
| T9 | K | K | K | open CALL_OWNERSHIP (if POSSIBLY_EXECUTING) | KEPT | - |
| T10 | K | R | R | release CALL_OWNERSHIP | CONSUMED | proof class a or b, attribution proof |
| T11 | R | R | R | release CALL_OWNERSHIP | RELEASED | proof class a or b, healthy complete absence observation |
| T12 | K | K | K | CALL_OWNERSHIP kept | KEPT | - |
| T13 | R | R | - | none | CONSUMED | verification evidence |
| T14 | K | R | - | open FAILED_VERIFY_HALT | CONSUMED | - |
| T15 | R | R | R | none | RELEASED | pre-dispatch only |
| T16 | R on absent, K on present until T13 | R | R | release CALL_OWNERSHIP | RELEASED on absent, CONSUMED on present | completion proof (proof class a or b) |
| T17 retry ok | R | - | - | release FAILED_VERIFY_HALT | KEPT (CONSUMED) | verification evidence |

The writer lease thus covers only the physical call (T5 to completion proof); target exclusivity continues through verification; the base-wide emergency effect is the hold set, not the lease (S12-M03).

## 5. Effect identity and attribution for unknown-outcome resolution (S12-B01, S12-B02, reliability R-05)

An effect that exists is not the same as an effect attributable to this change. The marker is never evidence (section 9), content equality and key equality are never attribution on their own, and T10 and T11 both require independent PROVEN_FINISHED (section 4). Attribution requires, for every kind, BOTH an effect-identity match and an exclusivity proof:

- Exclusivity proof: while the change was claimed, no writer other than this change could write to the target: the writer lease was held, the platform exclusive lock covered the target for the call, and the worker's session snapshot of the base (from the host, taken at begin_apply and at observation) shows no other session with a role able to write the target document class between the pre-image read and the observation. If the platform cannot give that snapshot (CT14 items 10b and 13 are INCONCLUSIVE), exclusivity is UNPROVEN.
- Effect identity: CREATE_DRAFT: a document with the canonical business key AND content hash equal to the approved payload AND an absent pre-image (no document with that key at begin_apply, recorded in the ownership row). UPDATE_DRAFT: content hash equals the approved payload and the pre-image hash differs. POST: the document is posted, the movement multiset equals the expected multiset and the version token differs from the pre-image. UNPOST: the document is not posted, the movement set is empty and the version differs from the pre-image.

If effect identity holds and exclusivity is PROVEN, attribution = PROVEN. If the effect exists but exclusivity is UNPROVEN, T10 is refused and the change goes to T12 (TRIAGE_REQUIRED); T16 can then mark it present with attribution = UNPROVEN_OPERATOR_ATTESTED, which accounts the effect (reservation CONSUMED) without claiming it was this change's call. A key or content mismatch is TRIAGE_REQUIRED. An identical observable state produced by an external writer after the managed call failed is therefore never classified as proven APPLIED. The version token is compared for equality against the pre-image only; a post-write version is never predicted.

## 6. Ledger interface (all operations are transactional and idempotent)

| Operation | Caller class | Input | Effect | Returns |
| --- | --- | --- | --- | --- |
| `propose` | requester | envelope, payload | T1 in one transaction: logical_key uniqueness, epoch read, event appended | change_id, state, receipt |
| `validate` | requester | change_id | T2, business-key lookup in the ledger, budget pre-check, allowed_effects derivation | state or refusal code |
| `approve` / `reject` | approver | change_id, nonce | T4 or T3; approver person derived from the token and differs from requester person; nonce consumed; approval record immutable and signed | approval id |
| `claim` | requester | change_id | T5: guards, reservation, locks in one transaction | claim token (bound, single use, same token = same result) |
| `release_claim` | sweep / requester | claim token or ttl expiry | T5x | state |
| `begin_apply` | requester or writer on behalf of a token | claim token (carries generation) | T6 as one atomic section; ownership row {call id, writer process, host, 1C session, start, hard deadline, attempt counter, pre-image hashes}; a superseded generation gets read-only status; returns the existing ticket on replay only while the generation is current and dispatch is not DISPATCHED | apply ticket |
| `issue_permit` | ledger (internal) | change_id, generation | T6p after the checkpoint covering the T6 head is written and read back; T6r on failure | dispatch permit (signed) |
| `complete` | writer | apply ticket, result evidence | T7 or T8 or T9 chosen by the evidence class, never by a caller flag | state |
| `recover_sweep` | recovery worker | none (ledger-driven, idempotent) | handles expired claims, expired approvals, `hard deadline` expiry in APPLYING, stuck verification; produces T5x, T9, T3, T12, T13 retry | list of changed ids |
| `resolve_unknown` | recovery worker | change_id, observation record (signed) | T10, T11 or T12 | state |
| `operator_resolve` | operator plus recovery witness (two-person) | change_id, verifier-signed completion-proof and observation records | T16; refused with `COMPLETION_PROOF_MISSING` without independent PROVEN_FINISHED proof | state |
| `release_hold` | operator | hold id, machine-verified release evidence | releases ANCHOR_GAP or RLC_UNCLEAN under the conditions in section 4; never CALL_OWNERSHIP without completion proof | hold state |
| `verify` | recovery/verification worker | change_id, signed verification record | T13 or T14 | state |
| `kill_switch` | operator | mode (STOP_ADMIT, STOP_EFFECTS, REVOKE) | durable switch record independent of the ledger, the checkpoint and the anchor; the writer reads it through an authenticated, checkpointed read before every call; unavailable means STOP_EFFECTS | switch state, list of in-flight and unresolved changes |
| `budget_reserve`, `budget_consume`, `budget_release` | internal only (server-derived) | grant, change_id | CT13 matrix; amounts and the grant are derived from the change, `parent_change` is validated, `amount_consumed(document, grant)` is read in the claim transaction; never callable by any external class | reservation |
| `budget_admin` | operator | grant parameters | CT13 grant management | grant |

Kill-switch semantics (S12-M06): modes are ordered STOP_ADMIT < STOP_EFFECTS < REVOKE and each includes the previous. One precedence matrix applies to every operation and in-flight state:

| Operation or state | STOP_ADMIT | STOP_EFFECTS | REVOKE |
| --- | --- | --- | --- |
| propose, validate, approve | refused | refused | refused |
| claim | refused | refused | refused |
| CLAIMED change | released by T5x | released by T5x | released by T5x, approval voided |
| begin_apply, issue_permit | refused | refused | refused |
| APPLYING, dispatch NOT_PERMITTED | T6r | T6r | T6r |
| APPLYING, dispatch PERMITTED, not yet dispatched | the writer reads the switch (authenticated, checkpointed read) and aborts before the call: T6r | same | same |
| APPLYING, DISPATCHED | follows the call: T7/T9, no new call | same | same |
| APPROVED, unclaimed | kept | kept | voided |
| complete, recover_sweep, resolve_unknown, verify (read-only observation) | allowed | allowed | allowed for observation only as an operator-gated exception recorded in audit |
| operator_resolve, release_hold, kill_switch | allowed | allowed | allowed |

Re-enable runs `recover_sweep` first. The switch engages without a checkpoint and is independent of the ledger, the checkpoint and the anchor; an unreadable switch means STOP_EFFECTS. The check for the switch and the call are not atomic; that window is declared (CT9), and the switch is checked inside the permit transaction and again by the writer before the call.

Every event has an event id; handlers are idempotent; the event log is append-only with a hash chain. Checkpoint rule (R-04, S12-M01): a signed checkpoint {sequence number, head hash, time} is written to the external store (D9) and read back for the approval consumption (T4), for the head that contains the APPLYING event and the call-ownership row (T6, before the dispatch permit T6p), and for the terminal events T7, T8, T11, T16. Events T10, T13 and observation reads are read-only resolutions and are not required to be checkpointed; they are included in the next checkpoint. A checkpoint that cannot be written blocks new effects (CT5, hold `ANCHOR_GAP`, bounded: at most 15 minutes, then TRIAGE of unresolved items). `COMPLETION_PENDING` obligations and request ids are persisted here (S11-B), never held only in memory.

Authorization epoch (S11-C): `claim` and `begin_apply` each re-read the live epoch dependencies for requester, approver and (tenant, company); a mismatch refuses before any write. The window after the last re-read is declared, not hidden: a single 1C write is atomic and the platform lock covers its duration.

## 7. Writer (1C write port) contract

One writer per base, enforced by a base writer lease taken at T5 and re-checked at T6, held until a terminal or APPLY_UNKNOWN resolution. The port accepts only an apply ticket. Steps for CREATE_DRAFT: authenticate the base fingerprint by connecting; take the create lock keyed by the hash of the canonical business key (already taken at T5 in the ledger; the writer re-takes it as a second defense); re-check absence of a document with that key and of the marker inside the serialized writer; write the document with the marker attribute set in the same write; read back. For UPDATE_DRAFT, POST, UNPOST: take the exclusive object lock, read the version token, compare with the approved version, re-check dependents and period status against the approved `business_state_digest`, write, release. A parent that is not VERIFIED (FAILED_VERIFY, NOT_VERIFIED) is refused at T5. Writer refusals map to `STALE_VERSION`, `LOCK_BUSY`, `DUPLICATE_SUSPECTED`, `ROLLBACK_REFUSED` and `WRITE_REFUSED`; each carries a typed failure stage (PRE_WRITE or later) signed by the writer, and only PRE_WRITE refusals with an operation-specific no-effect proof are classified at T8; every error after the write call started is T9. The port refuses to call without a valid dispatch permit for the current generation. The port never calls forced termination; the call has a hard deadline (120 s, posting 300 s) whose expiry only starts the completion determination (CT3), executed by `recover_sweep`. The write identity is the least-privilege extension role (CT14 record, section 6), never an administrator.

Locks, lease and holds per transition are in section 4.1; the writer lease covers the physical call only, target exclusivity continues until verification.

## 8. Reservation and budget events (S12-M07, reliability R-08)

Reservation state is a deterministic function of the independently proven effect state, never of an operator-chosen label: RELEASED requires proven no-effect (T5x, T6r, T8 definite with PRE_WRITE evidence, T11 with completion proof, T15, T16 absent with completion proof); CONSUMED requires an effect that exists (T7, T10, T14, T16 present); KEPT while the effect state is unknown (T9, T12). The per-transition table is in section 4.1.

| Case | Accounting |
| --- | --- |
| POST amount | `amount_consumed(document, grant)` is read inside the claim transaction; only the unconsumed part is reserved |
| UNPOST | consumes its own reservation only when its effect exists; its refusal (ROLLBACK_REFUSED) releases it and leaves the original change and its CONSUMED state untouched |
| repair UNPOST or correction after FAILED_VERIFY | its own reservation under its own approval; the failed change stays CONSUMED while its effect exists and is reconciled by `amount_consumed` when the repair is APPLIED |
| retry after FAILED_APPLY | a new proposal, a new reservation; the earlier one is RELEASED |
| grant expiry during a call | the reservation follows the call outcome; the window is checked at claim only (CT13) |
| repeated `operator_resolve` | idempotent per hold; a second resolution cannot change a CONSUMED or RELEASED reservation |

Ledger-wide invariant (for the E-series): reserved plus consumed equals the sum over live states, after a kill at every window and after every T16 path.

## 9. Evidence contract (S11-D)

Four evidence record types, none convertible into another: field evidence (read-back of typed fields), movement evidence (multiset keyed by registrar over all recorder registers), version evidence (the data version token, compared for equality only), authorization receipt (approval record id, approver, epoch). Each record is signed by the verifier identity over (change_id, kind, content hash, observed_at) and the ledger refuses an unsigned or wrongly bound record (section 2). VERIFIED requires field, movement and version evidence from a read after the effect; expected movements come from the independent oracle and the operation rule table, including an expected empty set for draft, update and unpost. The verifier shares no code with preview, normalization or write serialization (structural import-graph check). The marker is an untrusted label: it is never evidence of application or of non-application.

## 10. Error-code registry (new members of the closed enums; safe, constant text)

`SCHEMA_INVALID`, `SHAPE_NOT_QUALIFIED`, `SCOPE_MISMATCH`, `REF_OUT_OF_SCOPE`, `NOT_ENTITLED`, `APPROVER_NOT_INDEPENDENT`, `APPROVAL_MISSING`, `APPROVAL_EXPIRED`, `APPROVAL_VOIDED`, `APPROVAL_NONCE_INVALID`, `COMPLETION_PROOF_MISSING`, `ATTRIBUTION_UNPROVEN`, `PERMIT_MISSING`, `TICKET_SUPERSEDED`, `DIGEST_MISMATCH`, `STALE_VERSION`, `IDEMPOTENCY_CONFLICT`, `DUPLICATE_SUSPECTED`, `EPOCH_CHANGED`, `TARGET_REJECTED` (class or fingerprint), `KILL_SWITCH_ACTIVE`, `BASE_HOLD`, `PARENT_NOT_VERIFIED`, `CLAIM_EXPIRED`, `BUDGET_EXCEEDED`, `CURRENCY_NOT_BUDGETED`, `AUDIT_UNAVAILABLE`, `CHECKPOINT_UNAVAILABLE`, `LOCK_BUSY`, `WRITE_REFUSED`, `APPLY_UNKNOWN`, `TRIAGE_REQUIRED`, `ROLLBACK_REFUSED`, `VERIFY_FAILED`, `MARKER_UNTRUSTED`, `EVIDENCE_UNSIGNED`. Each code has one fixed next action and message (import-time completeness guard as in the existing closed enums); no code echoes payload content, credentials, ids of other tenants or paths.

## 11. Crash-window matrix (expected durable state after a kill, or a ledger restore, at each point)

| Window | Kill point | Expected state on recovery |
| --- | --- | --- |
| W1 | before intent committed | no change exists |
| W2 | intent committed, not approved | PROPOSED or VALIDATED, no reservation |
| W3 | claim transaction in flight | rolled back: no claim, no reservation |
| W4 | claim committed, begin_apply not committed | CLAIMED, no call possible; the TTL elapses and `recover_sweep` runs T5x |
| W5 | APPLYING and ownership row committed, no checkpoint, no permit | dispatch NOT_PERMITTED, no call possible; T6r by the sweep after the permit TTL |
| W5b | checkpoint written, permit not issued or not read by the writer | no call without a permit; T6r or the permit is issued on replay of the same generation |
| W5c | permit issued, writer killed before DISPATCHED | the `call_id` is anchored; if the writer cannot sign `never_dispatched`, T9 (conservative) and CALL_OWNERSHIP hold |
| W6 | call sent, no response | APPLY_UNKNOWN, POSSIBLY_EXECUTING, CALL_OWNERSHIP hold |
| W7 | response received, ledger not updated | APPLY_UNKNOWN until independent completion proof and attribution (section 5); otherwise TRIAGE_REQUIRED |
| W8 | APPLIED recorded, verification not run | APPLIED, NOT_VERIFIED, target lock kept, the worker re-runs verification (bound 3) |
| W9 | checkpoint not written | no permit, no call; T6r |
| W10 | ledger restored to a point before the last external checkpoint | head-hash mismatch, ANCHOR_GAP hold, no dispatch; the anchored `call_id` and permit forbid a blind retry |

## 12. Open inputs and what the freeze review will need beyond this draft

Open: D10 person id; D10b a second registered recovery-witness person (without it T16 stays unavailable and the base stays held, fail closed); D9 host, account and signer; write-service host and the licensed COM host details (D4); OB-01 and OB-15 approvals; the physical ledger schema (S13), the principal registry source and the IdP (S16). Changes in revision 3 beyond the 12 GPT-PM findings are limited to what the findings required; the crash-window rows W5b, W5c and W10 and the permit transitions T6p/T6r are new. Not claimed: that any of this has been measured or tested; the CT14 items 9, 10b and 13 remain INCONCLUSIVE in the spike record, and section 5 relies on that. After this revision GPT-PM is asked for a bounded re-verification of its 12 findings and direct regressions, not another unrelated full sweep.
