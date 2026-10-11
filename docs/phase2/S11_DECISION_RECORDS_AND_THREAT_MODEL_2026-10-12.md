# S11 decision records and threat model (2026-10-12)

Status: DRAFT for GPT-PM review. Baseline: `PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` revision 5 (contracts CT1-CT15 are binding there and are not restated here). Evidence inputs: `S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md` (sections 1-5) and `CT14_FEASIBILITY_SPIKE_2026-10-12.md`. Nothing here approves the S12 interface freeze, code, push or any production write. No test, CI or mutation run.

## 1. Settlement of the four review requirements (S11-A..D)

| Id | Decision | Where it lands | Acceptance (checked in G8 evidence) |
| --- | --- | --- | --- |
| S11-A read/write boundary | Two independent authorization paths. The legacy READ path (`side_effect_boundary.evaluate`, `capture_permit`, `jobs_api`, `connector_sdk` capture) is not extended: it stays deny-by-default for every non-READ class and takes no write grant as input. The governed write path is a new component with its own trusted context (the signed approval and grant records of CT1/CT13) and its own entry points; it never calls the READ evaluator to obtain permission and the READ path never reads a change record. | New write-authorization evaluator (S12), new write port (S13); old modules untouched. | A proposed WRITE/POST stays denied through every legacy entry point even when an approved change exists; the READ regression set stays unchanged. |
| S11-B audit phases are not write finality | The audit gate keeps INTENT/COMPLETION as audit persistence only. Write finality lives in the CT10 execution state machine in a durable ledger. Mapping: INTENT acknowledged -> execution `NOT_STARTED` becomes `APPLYING` only after the call-ownership row is committed; `COMPLETION` success -> never sets VERIFIED; `EFFECT_FAILED` from a raised effect -> `APPLY_UNKNOWN` (not `FAILED_APPLY`) unless a 1C read gives `CONFIRMED_NOT_APPLIED`; `COMPLETION_PENDING` obligations and request ids are persisted in the ledger (today they are memory-only and lost on restart); `DUPLICATE_SUPPRESSED` maps to the idempotency receipt, never to an effect state. | New durable ledger tables (S12); `audit_gate` reused as a code pattern only. | A lost completion acknowledgement, a failed effect, an unknown 1C outcome and a duplicate request leave four distinguishable durable states, and none of them reads as VERIFIED. |
| S11-C live authorization epoch | A change carries the authorization epoch at proposal, approval and claim. At queue claim and again immediately before the effect, under the writer lock, the executor re-reads the live epoch (requester and approver entitlement, role grants, source/base status, target-registry entry) and refuses on any change. The DB pattern is reused (`acquire_job` compares the epoch under the source row lock; `role_scope` changes bump it); because DB jobs have no company dimension, the write ledger adds `company_id` to the epoch scope. The 1C base fingerprint epoch is a separate value. | Ledger claim function (S12); writer pre-effect check (S13). | Entitlement change, a revoked requester or approver, a replaced source or base epoch between proposal, approval, dequeue and execution each refuse before any write. |
| S11-D separate evidence types | Four distinct evidence records, none convertible into another: document-field evidence, registrar-movement evidence, 1C state-version evidence (the data version token) and authorization receipts. VERIFIED needs field plus movement plus version evidence read back from 1C after the effect; a six-column `MATCH`, an `ORIGINAL_INTACT` card or an audit acknowledgement is not evidence for it. Movement evidence is a multiset keyed by registrar over every register with a recorder (the clone showed two registers for a purchase receipt). | New evidence types and verifier (S15-S16); `reconciliation` six-column stays a read-side comparison. | A six-column MATCH or an acknowledgement alone never yields VERIFIED; a missing evidence type yields `NOT_VERIFIED`. |

## 2. Decision records for CT1-CT15: code anchors and measured facts

For each contract: what exists (FACT from the inventory or spike), what must be new, and the open dependency. "Reuse" means pattern unless stated.

| CT | Existing anchor | New in S12-S16 | Measured fact / open item |
| --- | --- | --- | --- |
| CT1 identity, approval | `_identity.same_person`, `is_empty_1c_ref` (code); `003` separate approver with digest-bound attestation and role-change epoch bump (pattern); `aliases` trusts a caller-asserted HUMAN approver (must not be reused as authority) | principal registry, approval ledger, write-audience token check | Approver identities, IdP: operator-owned, needed before S12. |
| CT2 apply protocol | `audit_gate` INTENT before effect, sink failure means zero effects (code); `living.*` unique idempotency identity (pattern) | durable intent ledger, logical request key vs payload digest, create lock by business key, marker in the same write | Marker feasibility measured: a document attribute is written in the same write (SUPPORTED), but the comment field is user-editable; update path for a catalogue uses the tabular part `ДополнительныеРеквизиты` as an append-only provenance row candidate (NOT yet written). |
| CT3 concurrency | `acquire_job` fence and lease (pattern) | per-target lock table, call-ownership rows, hold scopes | Native optimistic lock rejects a stale write (SUPPORTED); cross-session exclusive lock SUPPORTED on a file base; two concurrent writers succeeded (small sample); forced termination NOT attempted and stays DENIED; client-server lock behaviour not measured. |
| CT4 target classes | `living.sources.status` and `scope_epoch` (pattern) | signed target registry by base fingerprint | Staging DENY and production default DENY are operator decisions; canary signature operator-owned. |
| CT5 audit integrity | `comparison_snapshot.canonical_digest` (code); immutable ledgers in `001` (pattern) | hash chain, external signed checkpoints, startup head check | External append-only store host and key custody: operator-owned. |
| CT6 oracle | `reconciliation` six-column (read-side only, not a multiset) | independent expectation fixtures, multiset R-b, bidirectional R-c, structural import-graph check | Multiset by registrar proven readable (accounting plus VAT accumulation rows for a receipt). Accountant sign-off OB-11 is open. |
| CT7 posting, unposting | none | separate proposals for post, unpost, correction | Post and unpost measured on the clone (movements 0 -> 2 -> 0, marker survives). Rollback by marking for deletion is operator-only and forbidden meanwhile. |
| CT8 effects not names | `side_effect_boundary` class names (pattern only) | allow-list from metadata, posting-effects rule table | Purchase receipt posting wrote only `Хозрасчетный` (2 rows) and `НДСПредъявленный` (1 row), no payment, bank or cash register (clone, one document type). Contract catalogue attributes measured; allow-list candidates are `СрокДействия` and `Комментарий`; excluded as payment-driving: `УстановленСрокОплаты`, `СрокОплаты`, `ВалютаВзаиморасчетов`, `ВидВзаиморасчетов`, `РасчетыВУсловныхЕдиницах`, `ОплатаВВалюте`, `ПорядокРегистрацииСчетовФактурНаАванс...`, the deletion mark and the owner. Final list needs the S11 posting-on-clone proof for each admitted type. |
| CT9 kill switch | none (search found no mechanism); nearest anchors `sources.status`, `SourceStateMachine`, deny-wins in `OperatorAuthorityPort` | durable switch store with STOP_ADMIT, STOP_EFFECTS, REVOKE; unavailable store means STOP_EFFECTS | The R1 "kill switch" is a profile re-verify command, not a write stop. |
| CT10 states and codes | `OpsReason`/`NextAction` closed enums with import-time guards (code) | execution/verification state machine and a write refusal registry | The new codes must be new enum members; `safe_errors` tables are tied to workbench codes and need extension. |
| CT11 untrusted files | `safe_parser` (code, isolated run, fixed codes); `connector_sdk` key/value scanner (code) | extraction provenance, human review of financial fields | Windows memory bound is not enforced by the parser (documented limit). |
| CT12 approval page | none | web approval surface | UI scope and Drive: operator-owned. |
| CT13 grant budget | `capture_permit` use accounting consumes immediately (pattern, differs) | RESERVED/CONSUMED/RELEASED grant ledger with `amount_consumed(document, grant)` | None measured. |
| CT14 feasibility | `testlane/tools/edit_purchase_on_clone.py` pattern | capability matrix gate | See the spike record. Open: forced termination, narrow rights, OData writes, client-server locks, larger concurrency. |
| CT15 liveness | `PhysicalBackendBudget` pattern | queue bound, deadlines, drain | Targets are initial numbers; measured values need the S16 workload. |

## 3. Operation catalogue v0 (candidates from real metadata)

| Operation | Channel (measured) | Status |
| --- | --- | --- |
| Create purchase receipt draft with marker | COM on a licensed host, clone | feasible; marker field choice open (comment is user-editable) |
| Post / unpost purchase receipt | COM, clone | feasible; effects limited to the registers above for this type |
| Update contract: `СрокДействия`, `Комментарий` | COM; only metadata read so far | candidate; the write is NOT yet measured, and no document-style marker exists for a catalogue (use `ДополнительныеРеквизиты`, unmeasured) |
| Any OData write | Ivan | UNSUPPORTED until measured; Ivan has no client license |

Canonical business key for a purchase receipt: base fingerprint, organization, counterparty, contract, supplier number and date (a year filter is mandatory because numbers repeat across years), kind, currency. A contract key: base, organization, counterparty, contract number and date.

## 4. Threat model

Trust boundaries: (T1) chat client/model -> MCP surface; (T2) MCP surface -> ledger/queue; (T3) ledger -> writer (the only holder of 1C write credentials); (T4) writer -> 1C base; (T5) approver browser -> approval service; (T6) uploaded files -> parser; (T7) DB administrator -> ledger; (T8) operator -> kill switch and target registry.

| Id | Threat (STRIDE) | Boundary | Control (contract) | Residual risk, stated |
| --- | --- | --- | --- | --- |
| TM1 | Prompt injection via a file makes the model request an unintended change (T, E) | T1/T6 | content never selects company, operation or authority; human review of material fields; the model cannot approve (CT11, CT1) | a plausible but wrong value approved by a careless human |
| TM2 | Forged or confused caller identity; knowing a change id (S, E) | T1/T2 | principal from the token only; apply checks requester == caller; no delegation in v2.0 (CT1) | compromised IdP |
| TM3 | Requester approves own change; two accounts of one person (E) | T5 | approver person id differs from requester person id (CT1) | collusion of two people |
| TM4 | Approval replay or CSRF on the approval page (S, T) | T5 | nonce, CSRF, immutable preview digest, session isolation (CT12) | approver endpoint compromise |
| TM5 | Retry or duplicate creates a second document (T) | T2/T4 | logical key vs payload digest, create lock by business key, recheck inside the writer (CT2) | a human creating the same document directly in 1C (detected by R-c, not prevented) |
| TM6 | Timeout leaves an unknown outcome, then a blind retry double-posts (T) | T4 | `APPLY_UNKNOWN`, call ownership, hold scopes, no `FAILED_APPLY` from a timeout (CT2, CT3) | a hung 1C call that cannot be proven finished: holds the base until triage |
| TM7 | Concurrent human edit between approval and write (T) | T4 | native version-mismatch refusal on write; compare-and-write on the approved target version (CT3) | edits made outside the managed scope after the check, before the commit: inside one atomic 1C write the platform lock covers it; across documents not claimed |
| TM8 | Authorization changes between approval and effect (E) | T3 | live epoch re-read at claim and before the effect (S11-C) | the window between the last re-read and the commit of the single 1C write |
| TM9 | Ledger rewritten or restored by a DB administrator (T, R) | T7 | signed external checkpoints, head check at startup (CT5) | tampering between two checkpoints; an adversary with administrator rights and the signer key |
| TM10 | Kill switch store unavailable or an in-flight call commits after the stop (D) | T8/T4 | unavailable store means STOP_EFFECTS; in-flight call limit stated (CT9) | a call already running in 1C may commit |
| TM11 | A posting writes to payment registers or creates payment documents (T) | T4 | effects rule table, post-effect movement check, halt on unexpected registers (CT8) | document types other than the measured receipt are unproven |
| TM12 | Marker removed or edited by a user (T, R) | T4 | R-c hash detection; markers append-only; comment-field marker treated as a hint, not proof (CT2, CT6) | detection is after the fact |
| TM13 | Budget exhaustion races (grant overspend) (T) | T2 | transactional reservation at claim; matrix of CT13 | none measured yet |
| TM14 | Writer credentials leak (I, E) | T3 | writer is the only holder; private topology; DPAPI-class secret storage; no credentials in logs, errors or ledger | host compromise |
| TM15 | Forced 1C session termination corrupts a file base (D, T) | T4 | forced termination DENIED until CT14 proves it safe (CT3) | holds instead of recovers: the base waits for triage |
| TM16 | Legacy READ path abused to carry a write (E) | T1 | S11-A two paths; READ evaluator stays deny-by-default | none beyond implementation errors |
| TM17 | Staging or an unregistered base receives a write (E) | T4 | target identity by fingerprint, staging DENY, unknown DENY (CT4) | operator error in the target registry |

## 5. What this record does not close

- It is a design record; it freezes no interface and approves no code. The S12 freeze needs the GPT-PM review of this file and the open operator-owned items (approver identities, IdP, external checkpoint store, UI scope, canary signature, OB-11, OB-01/OB-10/OB-15).
- Not measured, therefore not decided: forced termination, narrow rights, OData writes, client-server lock behaviour, the contract-update write and its marker, document types other than the purchase receipt.
- Not read: the R1 gateway write surface, `evidence_attestation`, `release_migration`, `backend_budget`, `ports`, other `drive_*` modules, `scripts/` and config content.
