# S12 interface contract draft: governed purchase-receipt write (2026-10-12)

Status: DRAFT of the S12 preparatory design (documents only). It authors the actual interfaces that the plan's contracts CT1-CT15 require; it freezes nothing and approves no code. Authority: GPT-PM S11 exit verdict of 2026-10-12 (preparatory design authorized, formal S12 entry pending the operator person id, interface freeze needs its own review). Scope: purchase receipt create, post, unpost on COM / file base, measured shape only (CT14 record). Unresolved inputs are explicit and are never filled with invented values: operator person id (D10), checkpoint host and signer (D9), write-service host (D4 detail), OB-01, OB-15.

## 1. Vocabulary and identities

- `tenant`, `company` (organization in 1C), `base_fingerprint` (authenticated infobase id plus epoch, CT4), `scope` = the tuple (tenant, company, base_fingerprint); the scope tuple is immutable for the life of a change (I15).
- `person_id`: the trusted registry identity of a human; several accounts of one person are one person. `principal`: the authenticated OAuth subject of a session; mapped to a person only by the registry, never by caller arguments (CT1).
- `change_id`: UUID of one immutable proposal. `request_id`: the client-supplied idempotency token. `logical_key` = (requester principal, change kind, scope tuple, request_id). `payload_digest` = SHA-256 of the canonical payload plus the target version (CT2).
- `auth_epoch`: the live authorization epoch (S11-C): a monotone number per (tenant, company) that changes on any change of entitlement, role grant, source or target-registry status.

## 2. ChangeProposal (typed, purchase receipt only)

Common envelope (all kinds): `change_id`, `kind` in {CREATE_DRAFT, UPDATE_DRAFT, POST, UNPOST}, `scope`, `requester_principal`, `requester_person_id`, `request_id`, `parent_change_id` (null for CREATE_DRAFT; the draft's change for POST; the post change for UNPOST), `target_ref` (null for create), `target_version` (null for create), `payload` (kind-specific), `payload_digest`, `preview_digest`, `auth_epoch_at_proposal`, `created_at` (UTC), `expires_at` (UTC), `reason` (free text, never an authority).

CREATE_DRAFT payload (all fields typed, no free-form keys, unknown keys refused, I2): `organization_ref`, `counterparty_ref`, `contract_ref`, `supplier_document_number`, `supplier_document_date`, `currency`, `lines[]` each {`item_ref`, `quantity` (decimal string), `price` (decimal string), `vat_rate_code`, `amount` (decimal string)}, `comment` (text, stored verbatim and never evaluated). The measured shape is the only admitted shape; any other combination of line kinds, VAT mixes or currencies is refused with `SHAPE_NOT_QUALIFIED` until its own measured fixtures exist (operation rule table).
UPDATE_DRAFT payload: the same fields as a full replacement of the draft, plus `expected_target_version`; a partial or free-form patch is not allowed.
POST and UNPOST payload: empty; they carry `target_ref`, `target_version`, and `business_state_digest` (fields, lines, totals), and an `allowed_effects` list naming the permitted registers (CT7).

Rules: references are resolved only inside the scope (a ref from another company or base is refused before any write, TM18); numeric fields are decimal strings, never floats; the canonical form sorts keys and normalizes decimals; the digest covers payload, target version and scope.

## 3. States (CT10) and legal transitions

Dimensions stored as one record with attributes: `lifecycle` {PROPOSED, VALIDATED, REJECTED, EXPIRED_QUEUED}, `authorization` {NONE, APPROVED, VOIDED, REVOKED}, `execution` {NOT_STARTED, APPLYING, APPLY_UNKNOWN, APPLIED, FAILED_APPLY, TRIAGE_REQUIRED}, `verification` {NOT_VERIFIED, VERIFIED, FAILED_VERIFY}, `call_ownership` {NONE, PROVEN_FINISHED, POSSIBLY_EXECUTING}, `effect_known` {YES, NO, UNKNOWN} (FAILED_VERIFY only).

| # | From | Event | Guard (all must hold, re-read live) | To | Notes |
| --- | --- | --- | --- | --- | --- |
| T1 | (none) | propose | schema valid, scope resolved, requester entitled, logical_key unused or same digest, epoch read | PROPOSED | same logical_key with other digest: `IDEMPOTENCY_CONFLICT`; same digest: return the earlier receipt |
| T2 | PROPOSED | validate | preview built server-side, business key checked, budget pre-check, shape qualified | VALIDATED | `DUPLICATE_SUSPECTED` stops here |
| T3 | PROPOSED, VALIDATED | reject or expire | approver reject, or `expires_at` passed | REJECTED, EXPIRED_QUEUED | terminal, no effect possible |
| T4 | VALIDATED | approve | approver person differs from requester person, approval binds change_id, payload_digest, preview_digest, target_version, scope, expiry; approver entitled at this epoch | authorization = APPROVED | approval is a ledger record, not a flag set by the caller |
| T5 | APPROVED | claim | the current caller is the requester, approval unexpired, auth_epoch unchanged for requester and approver, kill switch off, base not in SAFE_HOLD, target lock free, budget RESERVED in the same transaction | execution = NOT_STARTED, claimed | claim and reservation are one transaction |
| T6 | claimed | begin_apply | pre-effect epoch re-read equals the claim epoch, base fingerprint authenticated by connecting, target version equals approved version (update, post, unpost), call-ownership row committed BEFORE the call, checkpoint written | APPLYING | any failed guard refuses with no 1C call and releases the reservation |
| T7 | APPLYING | call returned success | the write returned a result to the writer | APPLIED, call_ownership = PROVEN_FINISHED | budget reservation becomes CONSUMED |
| T8 | APPLYING | call returned a definite 1C refusal with no state change | refusal code proves no write occurred | FAILED_APPLY | only with CONFIRMED_NOT_APPLIED |
| T9 | APPLYING | timeout, lost connection, writer crash, ambiguous error | none of T7 or T8 proven | APPLY_UNKNOWN, call_ownership = POSSIBLY_EXECUTING | target lock kept, base mutations held (SAFE_HOLD), reservation kept |
| T10 | APPLY_UNKNOWN | resolve: found | reader-health proof, settle period, complete observation of the target scope finds the effect | APPLIED | requires an actual 1C read |
| T11 | APPLY_UNKNOWN | resolve: absent | reader-health proof, settle period, complete observation, AND call_ownership = PROVEN_FINISHED proven by observation (not by a deadline) | FAILED_APPLY (CONFIRMED_NOT_APPLIED), reservation released | a missing marker alone never qualifies |
| T12 | APPLY_UNKNOWN | age limit | 5 attempts over 15 minutes without resolution | TRIAGE_REQUIRED | alert to a human within 60 s |
| T13 | APPLIED | verify | independent read of fields, registrar movements (multiset over every register with a recorder) and version token matches the oracle and the operation rule table | verification = VERIFIED | a six-column match or an audit acknowledgement is never evidence |
| T14 | APPLIED | verify fails | unexpected or missing movement, field or version | FAILED_VERIFY, effect_known recorded | alert, base queue halted for unexpected registers |
| T15 | any pre-APPLYING | revoke | session or role revoked, approver revoked, epoch changed | authorization = VOIDED or REVOKED, execution refused | a new approval is needed |

Forbidden transitions (tested against a literal list, E45): FAILED_APPLY from a timeout; APPLY_UNKNOWN to APPLIED without a 1C read; APPLIED to VERIFIED without T13; any transition out of REJECTED, EXPIRED_QUEUED or FAILED_APPLY except a new proposal; VERIFIED to anything. POST and UNPOST are separate changes with their own T1-T14 chains; posting needs its own approval and a re-check of the document version under the writer lock immediately before the effect (CT7); UNPOST of a document with dependent documents or in a closed period is refused with `ROLLBACK_REFUSED`.

## 4. Ledger interface (all operations are transactional and idempotent)

| Operation | Input | Effect | Returns |
| --- | --- | --- | --- |
| `propose` | envelope, payload | T1 in one transaction: logical_key uniqueness, epoch read, event appended | change_id, state, receipt |
| `validate` | change_id | T2, business-key lookup in the ledger, budget pre-check | state or refusal code |
| `approve` / `reject` | change_id, approver principal, payload_digest, preview_digest, target_version | T4 or T3; approver person must differ from requester person; approval record immutable | approval id |
| `claim` | change_id, caller principal | T5: guards, reservation, target lock in one transaction | claim token (single use) |
| `begin_apply` | claim token | T6: pre-effect re-read, call-ownership row {call id, writer process, host, 1C session, start, hard deadline}, checkpoint | apply ticket |
| `complete` | apply ticket, result evidence | T7 or T8 or T9 chosen by the evidence class, never by a caller flag | state |
| `resolve_unknown` | change_id, observation record | T10, T11 or T12 | state |
| `verify` | change_id, verification record | T13 or T14 | state |
| `kill_switch` | mode (STOP_ADMIT, STOP_EFFECTS, REVOKE), operator | durable switch record, checked at claim and before every mutation step; store unavailable means STOP_EFFECTS | switch state, list of in-flight and unresolved changes |
| `budget_reserve`, `budget_consume`, `budget_release` | grant, change_id, amounts | CT13 matrix, RESERVED, CONSUMED, RELEASED, unknown outcome keeps the reservation | reservation |

Every event has an event id; handlers are idempotent; the event log is append-only with a hash chain; before any effect, intent, approval consumption and the APPLYING transition are covered by a signed checkpoint {sequence number, head hash, time} written to the external store (D9), and a checkpoint that cannot be written blocks new effects (CT5). `COMPLETION_PENDING` obligations and request ids are persisted here (S11-B), never held only in memory.

Authorization epoch (S11-C): `claim` and `begin_apply` each re-read the live epoch for requester, approver and (tenant, company); a mismatch refuses before any write. The window after the last re-read is declared, not hidden: a single 1C write is atomic and the platform lock covers its duration.

## 5. Writer (1C write port) contract

One writer per base. The port accepts only an apply ticket. Steps for CREATE_DRAFT: authenticate the base fingerprint by connecting; take the create lock keyed by the hash of the canonical business key; re-check absence of a document with that key and of the marker inside the serialized writer; write the document with the marker attribute set in the same write; read back. For UPDATE_DRAFT, POST, UNPOST: take the exclusive object lock, read the version token, compare with the approved version, write, release. The port never calls forced termination; the call has a hard deadline (120 s, posting 300 s) whose expiry only starts the completion determination (CT3). The write identity is the least-privilege extension role (CT14 record, section 6), never an administrator.

## 6. Error-code registry (new members of the closed enums; safe, constant text)

`SCHEMA_INVALID`, `SHAPE_NOT_QUALIFIED`, `SCOPE_MISMATCH`, `REF_OUT_OF_SCOPE`, `NOT_ENTITLED`, `APPROVER_NOT_INDEPENDENT`, `APPROVAL_MISSING`, `APPROVAL_EXPIRED`, `APPROVAL_VOIDED`, `DIGEST_MISMATCH`, `STALE_VERSION`, `IDEMPOTENCY_CONFLICT`, `DUPLICATE_SUSPECTED`, `EPOCH_CHANGED`, `TARGET_REJECTED` (class or fingerprint), `KILL_SWITCH_ACTIVE`, `BASE_HOLD`, `BUDGET_EXCEEDED`, `CURRENCY_NOT_BUDGETED`, `AUDIT_UNAVAILABLE`, `CHECKPOINT_UNAVAILABLE`, `LOCK_BUSY`, `WRITE_REFUSED`, `APPLY_UNKNOWN`, `TRIAGE_REQUIRED`, `ROLLBACK_REFUSED`, `VERIFY_FAILED`, `MARKER_UNTRUSTED`. Each code has one fixed next action and message (import-time completeness guard as in the existing closed enums); no code echoes payload content, credentials, ids of other tenants or paths.

## 7. Crash-window matrix (expected durable state after a kill at each point)

| Window | Kill point | Expected state on recovery |
| --- | --- | --- |
| W1 | before intent committed | no change exists |
| W2 | intent committed, not approved | PROPOSED or VALIDATED, no reservation |
| W3 | claim transaction in flight | rolled back: no claim, no reservation |
| W4 | claim committed, call-ownership row not committed | claimed, no 1C call possible (the call is never sent before the row commits) |
| W5 | call-ownership row committed, call not sent | APPLYING with POSSIBLY_EXECUTING; resolve by observation: absent plus proven finished leads to FAILED_APPLY |
| W6 | call sent, no response | APPLY_UNKNOWN, POSSIBLY_EXECUTING, base hold |
| W7 | response received, ledger not updated | APPLY_UNKNOWN until observation finds the effect, then APPLIED |
| W8 | APPLIED recorded, verification not run | APPLIED, NOT_VERIFIED, verification re-runs |
| W9 | checkpoint not written | no APPLYING, no effect |

## 8. Evidence contract (S11-D)

Four evidence record types, none convertible into another: field evidence (read-back of typed fields), movement evidence (multiset keyed by registrar over all recorder registers), version evidence (the data version token, compared for equality only), authorization receipt (approval record id, approver, epoch). VERIFIED requires field, movement and version evidence from a read after the effect; expected movements come from the independent oracle and the operation rule table, including an expected empty set for draft, update and unpost. The verifier shares no code with preview, normalization or write serialization (structural import-graph check). The marker is an untrusted label: it is never evidence of application or of non-application.

## 9. Open inputs and what the freeze review will need beyond this draft

Open: D10 person id; D9 host, account and signer; write-service host and the licensed COM host details (D4); OB-01 and OB-15 approvals; the physical ledger schema (S13), the principal registry source and the IdP (S16). This draft will be reviewed by independent specialist agents, corrected, and only then submitted to GPT-PM as the pre-freeze authorization and recovery contract.
