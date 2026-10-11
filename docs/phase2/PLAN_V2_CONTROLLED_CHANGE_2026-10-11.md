# ERP_MCP v2 closure plan: controlled change and reconciliation (S11-S19, gate G8)

Date: 2026-10-11. Revision 5. Status: APPROVED by GPT-PM on 2026-10-11 as the planning baseline for S11-S19 (revision 2 REJECT with 20 findings, revision 3 REJECT with 3 MAJOR, revision 4 REJECT with 1 MAJOR regression, revision 5 APPROVE; sha256 of the reviewed text 303974518dd7dfdcdff7b281450abfecbfc0552be2892bdf7c62ce0dede497fe, this status line being the only later difference, see commit 1c7cb9a for the reviewed bytes). Authorized: S11 documentation and planning only. NOT authorized: the S12 interface freeze, code, push, deployment, production writes. G8 NOT_PASSED, C1 NOT_REACHED, Release 2 NO-GO. Language: English (durable record); the operator copy is `reports/PHASE2_V2_CLOSURE_PLAN_2026-10-11.ru.html`.

## 0. Revision note and GPT-PM decisions

Revision 5 (after the GPT-PM verification round on revision 4 of 2026-10-11: R3-01, R3-02, R3-03 closed; one MAJOR regression with no BLOCKER — R4-01: forced termination of the 1C session is conditional in CT3 but unconditional in S14, S18 and CT15). Revision 5 corrects only R4-01 and its direct references: the expiry of the hard deadline only starts a determination of call completion (observation first); a forced termination of the 1C session is allowed only if CT14 established its safety for that channel and base type; otherwise the call stays `POSSIBLY_EXECUTING`, base mutations are held, reads are allowed, an alert and triage follow; a deadline alone never yields `PROVEN_FINISHED` (CT3, CT15, S14, S18, E34, E44). The other findings are not reopened. Revision 4 closed R3-01–R3-03; revision 3 (after the REJECT of revision 2: 8 BLOCKER, 12 MAJOR) introduced the contracts CT1–CT15, the invariant I15 and the scenarios up to E47; the section 10 item 2 decisions (D1–D3) were approved. The finding → change map and the residual risk of replacing mutation tests are in section 17.

GPT-PM decisions of 2026-10-11 (settle only section 10 item 2; they authorize no development, production change or deployment):

| ID | Decision | Verdict |
| --- | --- | --- |
| D1 | Draft by default; posting is a separate operation with independent authorization, a re-check of the current document state and a new approval. | APPROVE |
| D2 | The v2.0 catalogue: purchase document creation, a contract update by a field allow-list, post/unpost. Excluded: payments, bank transfers, deletion, bulk operations; the sales reference is removed; posting and unposting are approved individually and narrowly. | APPROVE WITH CONDITIONS (conditions met in rev 3) |
| D3 | The write service stays private; public exposure is not a workaround for ChatGPT/Claude connectivity; any remote-access architecture is a separate security and operator decision; network isolation complements, not replaces, authentication and authorization. | APPROVE |

## 1. Scope decision and the gap

Operator decision of 2026-10-11: «read-only was phase 1». Phase 2 / version 2 must change 1C data on request from ChatGPT or Claude («add this invoice», «update this contract») and be able to reconcile the result. This is the core outcome of version 2, not an extension.

The recorded Phase 2 scope has no writes: R2-REQ-15 says «no business writes», the S1–S10 connectors are read-only, side_effect_boundary admits only READ, capture_permit knows only READ_SNAPSHOT. So «all 48 stories» do not cover what the operator needs: the story catalogue has no story that changes data. This plan adds it as a new program S11–S19 and a new gate G8; the old gates G0–G7 stay.

## 2. What closure means

| Level | Name | Meaning | Owner |
| --- | --- | --- | --- |
| C1 | Engineering closure (ENGINEERING_COMPLETE) | v2 works end to end on the disposable lanes: request → proposal → policy check → approval → apply → verify → reconcile → rollback, with audit and a kill switch. Sprints S11–S19 closed, G8 passed on the lanes (machine verification, not accountant attestation), GPT-PM APPROVE. **ENGINEERING_COMPLETE is not PRODUCTION_READY**: it only means the engineering acceptance scope was satisfied in the documented test environment. The status is kept in four separate fields: `engineering_status`, `gate_status`, `external_evidence_status`, `production_authorization`. | The agent assembles the evidence; GPT-PM approves; operator decisions only from the «Dependencies» section. |
| C2 | Gate closure with external evidence | G3 (accountant attestation), G4 (Drive), G5 (UAT), G6 (production write canary), G7 (release). | The operator, the accountant, the product owner. The agent prepares the bundles and runs the passes. |
| C3 | Production | `PRODUCTION_GO` signed by the operator and production writes enabled under a separate permission (default OFF). | Only the operator. |

## 3. Facts, unknowns and hypotheses

- **FACT** v1 has 24 read-only tools (the Claude tool list); the 1C reader was qualified: writes are denied (`PASS_WRITE_DENIED` in the native-report manifests).
- **FACT** 1C OData can technically write; v1 read-only is enforced by the ERP_MCP contract and the 1C user rights (DECISIONS_AND_SOURCES_RU.md).
- **FACT** Today (2026-10-11) on a disposable clone a document edit and repost was made through COM under the copy admin; the result was visible through both gateways and the reconciliation found exactly one difference. This proves the «write → read → reconcile» mechanics, not a product path: the write was a manual experiment.
- **FACT** Host Ivan has no 1C client license: COM does not work there, while OData through the Apache web extension serves reads. OData writes on Ivan are untested.
- **FACT** Reuse in R2 is **partial** (checked against the code by the review): `aliases` resolves only `SupplierEntity` by exact reference, not by name; `workbench_review` is reconciliation discrepancy cards, not change-approval cards; `jobs_api` is a decision model, not a server (sessions, CSRF and actors are fakes, every job kind maps to a READ operation); `reconciliation` is a six-column per-account trial-balance calculation; `audit_gate` keeps known request ids in process memory; `capture_permit` is bound to one concrete request (params digest and requester) and its store is process-local. They are patterns and code sources, not ready parts.
- **FACT** Missing: any module that creates or changes 1C data; a write mode in the permit; an apply bound to an approval; a kill switch (there is none anywhere in `src`); extraction from PDF/images; MCP write tools.
- **FACT** Operator constraints: staging is forbidden; production writes need a separate permission; deletion and real-money actions are operator-only.
- **FACT** GPT-PM review of revision 2 (2026-10-11): REJECT — REQUEST_CHANGES; 8 BLOCKER, 12 MAJOR, 8 MINOR/INFO. The reviewer had no repository access: its statements about existing R2 code are marked UNKNOWN (they are not defects); revision 3 obliges S11 to produce a source-evidence inventory before any component is reused.
- **DECISION** A fallback path may reduce scope but never silently weakens a mandatory security, verification or authorization invariant (GPT-PM). Incomplete v1 read-back blocks the affected operation types; it does not weaken verification.
- **UNKNOWN** What exactly v1 can read back to verify a write (contract fields, document lines, movements by registrar) has not been inventoried. The inventory and its gaps are an S11 task.
- **HYPOTHESIS** H1: 1C can be written through the standard OData (create and post a document) without a client license, under a narrow account. Proved by a spike in S11.

## 4. Target behaviour

1. **Request**: The user writes in ChatGPT/Claude: «add this invoice» (with a file) or «update contract X». The model calls the `change_propose` tool.
2. **Proposal**: A typed **ChangeProposal** from the operation catalogue is built from the text and file; entities (counterparty, contract, items) are resolved with a confidence; ambiguity → a clarifying question, not a guess. The digest includes the immutable scope tuple (tenant, company, base, organization) and the target object's version; the caller is an authenticated principal (CT1).
3. **Validation**: Schema, business rules and policy: company and user rights, limits, closed period, duplicates. Result: VALIDATED or a safe refusal.
4. **Preview**: The server (not the model) builds the preview only from what it knows for certain: fields before/after, totals, the digest. Postings are not promised in advance: 1C computes them only on posting.
5. **Approval**: An independent **person** (not an account) approves on a separate page, not in the chat (maker-checker); a policy is allowed on the test lane only. The approval is not a bearer token: it is a ledger record bound to the operation, target, company, immutable proposal version, preview digest, target version and an expiry; a change to any of these voids it.
6. **Apply**: The caller requests execution; the executor checks that the **current** caller is entitled to request this very approval (knowing a change id grants nothing); re-checks expiry, digest, target version, scope, the standing grant (window, budget), period, rights, the kill switch and the target class; writes the audit; under the single writer of the base creates a **draft** with the marker in the same 1C write. Posting is a separate proposal with its own approval (CT7).
7. **Verify**: Read after write: the document exists, fields and totals equal the expectation; after posting the document's own movements (by registrar) match the operation's rule table. A mismatch → FAILED_VERIFY and an alert, not «success».
8. **Reconcile**: Three kinds (see below): expectation↔fact, base↔base, ledger↔1C.
9. **Rollback**: A separate proposal with its own lifecycle and approval: unpost, correct, or issue a compensating document (CT7). This is not «restoring history»: the earlier financial history is not promised to be restorable. With dependent documents, a closed period or externally consumed numbers an automatic rollback is forbidden and ends as `ROLLBACK_REFUSED`. No hard delete; marking for deletion only after the operator's ruling (the «deletion» class).

States (the taxonomy is contract CT10; the full transition table with guards and initiators is an S12 deliverable):

- Main: `PROPOSED → VALIDATED → APPROVED → APPLYING → APPLIED → VERIFIED   (APPLIED = the effect is known to exist; for a create it is a draft)`
- Unknown outcome: `APPLYING → APPLY_UNKNOWN → [trusted, complete observation AND reader-health proof AND call_ownership = PROVEN_FINISHED (CT3)] → APPLIED | FAILED_APPLY (= confirmed not applied only); call_ownership = POSSIBLY_EXECUTING holds all base mutations; unresolved past the maximum age → TRIAGE_REQUIRED (a human)`
- Posting: `Post, unpost and compensate are SEPARATE changes: each runs its own PROPOSED … VERIFIED machine (an unknown outcome is the same APPLY_UNKNOWN handling) and links to its parent change; there is no POST_* branch inside the parent.`
- Other: REJECTED · EXPIRED_QUEUED (expired before any effect; proven by an unclaimed ledger claim) · FAILED_VERIFY with effect_known = true | false → (retry verify | a rollback change) · ROLLBACK_REFUSED (lifecycle outcome of a rollback change; the original document is untouched). A timeout or an expiry NEVER turns an unknown committed outcome into a failure; an expiry reaching APPLYING is evaluated at the next effect boundary, never mid-write.

Examples:

- **«Add this invoice» + a supplier file**: Field extraction with a confidence → counterparty and contract resolved (or a question) → a «Purchase receipt» draft → preview (fields, totals) → approval on a separate page → draft written with the marker → fields verified → (on a separate approval) posting → the document's own movements verified → reconciliation.
- **«Update the EVDTRANS contract: valid until 2027-12-31»**: A single contract found → «before/after» preview for the changed fields only, with the contract's version → approval → apply → if the contract was edited by hand between preview and apply, the apply is refused → fields read back → ledger.
- **«Revert the last change»**: A new rollback proposal (unpost and neutralise), its own approval, its own verification. If unposting is impossible (dependent documents, a closed period) the rollback ends with an honest refusal.
- **«Delete all August documents» / «pay the invoice»**: Refused: deletion and real money are outside the v2.0 catalogue (operator-only). The model gets a safe refusal and no write-port call is made.

## 5. Safety invariants (with the scenarios and the direct falsification path at the enforcement boundary)

| ID | Rule | Falsified by | Direct falsification at the boundary |
| --- | --- | --- | --- |
| I1 | The v1 gateway stays read-only. Writes are a separate service, a separate OAuth audience (`onec:write`) and a separate 1C account with minimal rights; a read token cannot write and a write token is not accepted by v1; the 1C account rights are verified in fact, not from documentation. | E5, E17, E32 | At the write port and in 1C itself: a write attempt by the account outside the allowed objects, a wrong audience, scope escalation, principal substitution. |
| I2 | The model never passes raw OData/COM/SQL. Every field is a typed catalogue value, nested structures included; the server builds the write; there is no interpreter over user data (formulas, templates, serialized commands). | E7, E15, E27, E40, E42 | A schema validator at proposal intake and a port that rejects non-catalogue fields; negative tests with nested payloads and serialized commands. |
| I3 | An approval is a ledger record bound to the operation, target, company, immutable proposal version, preview digest, target version, approving person and expiry; it is not a bearer token. A change to any of these, or revocation of the approver's rights or session, voids the approval. | E2, E4, E6, E20, E23, E24, E32, E34, E39 | The target version is compared at write time inside the writer (compare-and-write, CT3), not only at dequeue; the executor checks the current caller's entitlement to that approval. |
| I4 | The approver is a **person** (person id) not equal to the requester; two accounts of one person are one person. There is no `approve` tool on the model surface; direct calls to the approval service, identity substitution and a forged session are rejected; the only exception is an explicit test-lane policy visible in the audit. | E5, E29, E32, E39 | Direct approval-API calls, a second account of the same person, a forged session, CSRF; not merely the absence of a tool from the list. |
| I5 | Audit before effect: if the audit record or the external checkpoint before the effect fails there is no write (fail closed). The ledger is the single owner of state; its integrity is confirmed by signed checkpoints outside the DB administrator's trust boundary (CT5). | E13, E18, E25, E31, E36 | Independent 1C observation: no effect when the sink fails; a recomputed chain and a restore to an older valid copy are detected by an external checkpoint or cause SAFE_HOLD. |
| I6 | Draft by default. Posting, unposting and compensation are separate changes with their own approval, current document version, a business-state digest and allowed effects; everything is re-checked immediately before execution. | E1, E10, E14, E26, E37 | An edit of the draft after the post approval → refusal; the document state is checked in 1C independently of the ledger. |
| I7 | The intent, the logical request key and the canonical payload digest are fixed before the effect (the digest is immutable under the key). A retry or crash never creates a second effect. On an unknown outcome the state is `APPLY_UNKNOWN`, resolved only by a trusted, complete observation with a reader-health proof; «not found» from an unreliable read is not proof of absence; unresolved → `TRIAGE_REQUIRED` (a human). No blind retry; the same logical request key with a different payload digest → `IDEMPOTENCY_CONFLICT`. | E2, E3, E18, E19, E21, E22, E25, E28, E33, E34, E44, E45 | An independent 1C before/after snapshot (document count, target version); fault injection around the real commit; repeated recovery cycles. |
| I8 | File content is data, not instructions and not authority: it does not select the company, the operation, the authority or the approval status. Processing runs in an isolated environment with size and decompression limits, without outbound connections, without executing formulas or external references. | E7, E27, E40 | Observing the parser's real I/O and network attempts; digest equality alone is not sufficient. |
| I9 | A standing write grant (window, budget, company, source) lives in the ledger and is shared across processes; default OFF; budget reservation is transactional with the claim and survives an unknown outcome; the fail-closed kill switch has defined modes (CT9). | E6, E11, E24, E38, E41, E44 | Parallel reservations at the budget boundary: the aggregate admitted never exceeds the grant; the kill switch fires at every mutation boundary and during a call. |
| I10 | The v2.0 catalogue has no hard delete and no payment/money operations, **nor fields and effects that initiate them**: classification is by fields, object types and effects, not by operation names (CT8). | E15, E42 | Attempts to update bank details, payment terms, a deletion flag; indirect payment triggers on posting; nested and disguised payloads; checking the real movements by register. |
| I11 | Success = a verified fact: against an independent versioned expectation (CT6) and the document's own movements (compared as multisets); changes in the managed scope without a marker are detected in both directions (R-c). A write that has not passed verification is not complete. | E1, E2, E9, E10, E12, E22, E25, E26, E37, E43 | Distortions in the target base from the enumerated set (this is data, not code): no false VERIFIED; oracle independence is structural (the verifier does not import the preview/normalization code). |
| I12 | The target class is determined by the authenticated 1C base identity (fingerprint), not by a host name or a caller-supplied environment label. A disposable clone — by the test-lane policy; **staging — always DENY**; production — default DENY, then an explicit operator permission for the G6 canary and a separate enablement after all gates and `PRODUCTION_GO`, carrying base, company, operation, limit, expiry and purpose (CT4). The port itself enforces. | E16, E35 | A matrix: environment-label spoofing, a stale permission, a wrong fingerprint, a revoked permission, a signed canary; staging is always rejected. |
| I13 | Write credentials (1C, OAuth, approver tokens) live only in protected storage; access, rotation and revocation are defined; they are absent from logs, error responses and artifacts. | E30 | A check of the runtime store, of log and error redaction, rotation and revocation; the repository scan is only a complement. |
| I14 | The write endpoint is not published on the public tunnel and is not reachable indirectly (proxy, redirect, SSRF); network isolation complements authentication and authorization and does not replace them (D3). | E16, E17, E35 | A route check, an indirect-entry check through a proxy/redirect, and a deployment check in the target topology. |
| I15 | Tenant, company, base identity and organization are an immutable part of the proposal, approval, grant, queue claim, audit and port call; they are verified from the trusted context at every boundary; the port checks them against its own configured base and the account's rights. | E1, E6, E32 | A negative matrix: 2 tenants × 2 companies × distinct bases; overlapping numbers; an altered queue payload; a base-identity mismatch after a restore; refusal at both the service and the port. |

## 6. Components and reuse (honest)

| Component | Responsibility | Reuse / pattern | New / change |
| --- | --- | --- | --- |
| Change catalogue & schemas | Typed v2.0 operations (purchase document creation, a contract update by a field allow-list, post/unpost), field allow-lists, normalization, a digest including the scope and the target version, a per-operation rule table (expected own movements and permitted registers). No sales, payments, deletion or bulk operations. | pattern: `connector_sdk` (envelope), `_identity` | New |
| Principal & authorization registry | A trusted mapping: ChatGPT/Claude identity → application principal → person (person id) → rights, companies, roles, 1C account; checking the caller's entitlement to execute a specific approval; session and role revocation; fail-closed when the IdP is unavailable (CT1). | pattern: `workbench_session` (fakes), `jobs_api` (decision model) | New |
| Entity resolution | Counterparty, contract, item, organization — resolution within the company scope; ambiguity → a question; the result is a scoped reference, not a «similar name». | `aliases` (`SupplierEntity` only, exact reference), `taxonomy` | Extend: contracts, items, name search with human confirmation |
| Document intake | PDF/image/xlsx/csv → fields with per-field provenance and confidence; an isolated environment (CT11); mandatory human review of material financial fields regardless of confidence. | `safe_parser` (xlsx/csv), `drive_*`, `artifact_vault` | New: PDF/image extraction, isolation |
| Policy & grant | Rights, limits, closed periods, duplicates; a standing grant (window, budget by accounting unit, company) separate from approval; a kill switch with modes (CT9); re-validation at dequeue. | patterns: `capture_permit` (per request), `side_effect_boundary` (READ only), `backend_budget` | New: the grant, a WRITE/POST evaluator, the kill switch, budget semantics |
| Approval service | An approval page with a server-built preview; the approver identity separate from the chat; maker-checker by person; binding to operation, target, company, proposal version, digest, target version and expiry; web protections (CT12). | pattern: `workbench_review` (discrepancy cards), `workbench_session` | New |
| Change ledger (PostgreSQL) | The single owner of state and audit: changes, digests, approvals, idempotency keys, receipts, markers, base fingerprint, grant reservations, per-target locks; roles/RLS; hash chain; intent, state transition, claim and budget reservation in one transaction. | pattern: `db/phase2` (roles, RLS, fence, outbox), `audit_gate` (in memory) | New: the change schema and migration |
| Audit anchor & signer | Signed checkpoints (chain head + sequence number) in an external append-only store outside the DB administrator's trust boundary; a signer separate from the DB; a check at startup and after a restore; SAFE_HOLD on a mismatch or unavailability (CT5). | pattern: `release_rollback`, `restore_verify` | New |
| 1C write port | A narrow write port: a single writer per base; the scope tuple and target class are checked against the configured base; the marker in the same 1C write; compare-and-write on the target version; draft, post/unpost; implementations: OData (H1), COM (licensed lane), fallback — a configuration extension with an HTTP service. The fence does not exist inside 1C; exclusivity comes from the port and the per-target lock table (CT3). | `ports` | New |
| Verifier & reconciler | Expectation↔fact by fields and the document's own movements (multisets); base↔base with an expected difference set; ledger↔1C in both directions; an independent versioned oracle (CT6). | pattern: `reconciliation`, `posted_receipts`, the test-lane MCP | Extend: reading documents and movements by registrar (v1 inventory in S11) |
| MCP/LLM surface | Tools `change_propose / status / apply / verify / rollback_propose` with «not read-only» annotations, structured outputs, one registry of safe error codes; no `approve`; a write OAuth audience. | pattern: `safe_errors`, `jobs_api` (decision model) | New: the write server (test lane first) |
| Ops | A bounded per-base queue with per-target locking; limits; kill switch; alerts; a supervisor with restart; recovery; runbooks split into routine and requiring new approval. | pattern: `alert_rules`, `delivery_replay`, `restore_verify`, `release_rollback` | Adapt and add write rules |

## 7. Three reconciliations

| ID | Kind | What | Where used |
| --- | --- | --- | --- |
| R-a | Expectation ↔ fact (after every write and every post) | Fields and totals — with the approved preview; after posting — the document's own movements (by registrar) — with independent versioned expectations for **every** G8 operation (rounding, VAT, currency, organization, period, movement multiplicity), not for one known document only. The expectation code is logically independent of the preview, normalization and write-serialization code (the verifier does not import them). Comparison is by movement multisets. | Mandatory for VERIFIED |
| R-b | Base ↔ base (reference A against target B) | The change is applied on B; the A↔B reconciliation must show exactly the expected difference set (document ref, N movement lines, balance delta). The comparison is canonical on a **multiset** (identical repeated rows are not collapsed); pre-existing unrelated A/B differences are captured as a baseline and neither mask nor imitate the change's effect; anything extra or missing is red. | Lanes and G8 acceptance |
| R-c | Change ledger ↔ 1C, in both directions (at startup, after a restore, periodically) | Direction 1: every verified write is still there and unmodified (by marker and content hash, not by marker presence alone). Direction 2: the managed scope has no untracked changes — a document without a marker, an edit that left the marker unchanged, a missing movement: the baseline, the inventory cursor, scan coverage, the treatment of a missing marker and recovery after a restore are defined. A ledger older or newer than 1C is detected; while the reconciliation is not clean, applies are blocked. | Operations |

## 8. Sprints S11-S19

### S11 Foundations, contracts and feasibility (size L)

Goal: Decisions, threat model, the binding contracts CT1–CT15, a source-evidence inventory of the code, test design and a binary feasibility gate for the write and read-back channel. Nothing of S12–S19 starts before these documents are approved.

Deliverables:
- Scope decision record (v2 includes writes) and a replacement for R2-REQ-15 for v2; the G0 inputs for OB-01/OB-15 (scope rebaseline, donor inventory)
- Threat model: file injection, confused deputy, approval TOCTOU, replay, over-privilege, wrong company/closed period, public tunnel, secrets, leakage through the preview, ledger tampering and rollback, bypass through indirect effects; detectable and undetectable adversaries are named explicitly
- **The contracts CT1–CT15** (section 16) as decision records with the accepted content and acceptance scenarios; a **GPT-PM review of the threat model and the security and recovery contracts** before the S12 interface is frozen
- A source-evidence inventory: every claim about existing R2 modules (aliases, workbench_review, jobs_api, reconciliation, audit_gate, capture_permit, side_effect_boundary, absence of a kill switch) is checked against the code before anything is reused
- Operation catalogue v0 from real clone metadata (purchase document, contract, post/unpost), contract field allow-lists, canonical business keys, a per-operation rule table (expected movements and permitted registers), a glossary (the user-level «purchase invoice» = a concrete 1C document type)
- **The CT14 feasibility gate**: a «capability × channel × operation» matrix (draft, modify, post, unpost, read-back of fields/lines/movements/version, an atomic marker, an exclusive lock/CAS, no payment effects) on a clone and on Ivan, with measured evidence and a pass rule
- The v1 read-back inventory (what can be read back; gaps → S15 work or a read extension; incomplete read-back blocks the affected operation types)
- Decisions: the marker field, numbering, topology (the write-service host, the target base, access without a public tunnel), limit/period/time-zone semantics (UTC in the ledger, explicit conversion), approval TTL versus the maximum queue wait, the external checkpoint store and the signer (CT5)
- A machine-readable gate manifest (a dependency DAG, section 9) and a closure validator; a status ledger with four fields (`engineering_status`, `gate_status`, `external_evidence_status`, `production_authorization`)
- H3: N, X, the evaluation set and the rule for counting a «corrected field» are fixed in advance; TDD, sprint plan, stories and DoD; an «invariant → scenario → failing assertion at the enforcement boundary» matrix; test coverage from `functional-test-reviewer` and `e2e-runner` (if the operator allows agent runs)

Exit criteria: Documents approved by GPT-PM; the CT14 matrix is filled: every mandatory capability is SUPPORTED for at least one channel in the target deployment, or the scope is narrowed, or a fallback channel is approved by a separate decision; the evidence inventory is complete; the operator's ruling on rollback by marking for deletion is requested. The S12 interface is not frozen before this.

Depends on: —. Operator input: The ruling on marking for deletion (the «deletion» class — operator only); decisions 2–3 of section 10

### S12 Change model, policy, ledger interface (size L)

Goal: Offline reference: proposals, the state taxonomy, policy and grant, approval, idempotency; the ledger interface is frozen after the GPT-PM review of the authorization and recovery contract.

Deliverables:
- `ChangeProposal`, operation schemas, normalization and a digest including the scope tuple and the target object version; separate proposal kinds for post, unpost, correction and compensation (CT7)
- The taxonomy and the full transition table per CT10: a guard and an initiator for every transition, event ids, idempotent handlers, proof conditions for terminal states; a single apply point; the ledger as the single owner of state
- The identity and authorization model (CT1), the principal registry, the approval as a ledger record, the «person ≠ requester» rule, re-checking roles at dequeue and before the effect
- **The ledger interface is frozen** after the GPT-PM review of the authorization and recovery contract; S13 and S14 use it. The interface includes the per-target lock table (CT3) and the grant reservations (CT13)
- Policy engine: rights, limits, periods, duplicates by the canonical business key; the standing grant and budget semantics (CT13); re-validation at dequeue (expiry, digest, target version, scope, period, rights, grant, target class CT4)
- The kill switch per CT9 (three modes; an unavailable store → STOP_EFFECTS); a new side-effect-boundary evaluator for the WRITE/POST classes; regression: the READ-only guarantees are unchanged
- One registry of safe error codes; a crash-window matrix (intent → audit → write → response → ledger → verify → post) with the expected state at each point

Exit criteria: Offline tests refuse where they must (E4, E5, E6, E11, E13, E14, E15, E20, E23, E24, E29, E32, E38, E41, E45); model-based transition tests: every illegal transition is rejected, every crash/resume path is checked, an unknown outcome never becomes a failure from a timeout or an expiry; the READ-only regression is green; GPT-PM APPROVE.

Depends on: S11. Operator input: Approver identities (decision 4 of section 10)

### S13 Change ledger in PostgreSQL and the audit anchor (size M)

Goal: A durable store at G1 level; the outcome survives any crash; independent audit integrity.

Deliverables:
- Change-schema migration; roles without direct DML; RLS by tenant/company; a hash chain; UPDATE/DELETE denied on ledger rows
- Intent, state transition, queue claim, budget reservation and target lock in one transaction; an apply claim does not burn attempts on a crash and moves to APPLY_UNKNOWN, not to a terminal FAILED; the lease is renewed while a call is in flight; the fence is checked before each 1C call (the fence does not exist inside 1C itself)
- Signed checkpoints and the signer (CT5): written before the effect, checked at startup and after a restore, SAFE_HOLD, ANCHOR_GAP, key rotation
- A base fingerprint (identity and epoch) per apply; refusal on a mismatch; the target registry and environment permissions (CT4)
- A startup recovery sweep over every APPLYING and APPLY_UNKNOWN; `pg_dump`/`pg_restore` restore, chain and anchor verification, the «ledger older/newer than 1C» skew case

Exit criteria: Integration tests on a disposable PostgreSQL are green: the crash-window matrix at ledger level, the restore skew, a recomputed chain and a restore to an old valid copy detected by the anchor or SAFE_HOLD (E18, E25, E36, part of E38 — parallel reservations); the `test_g1_crash`/`test_g1_concurrency_mp`/`test_g1_restore` harness is reused.

Depends on: S12 (interface frozen); parallel with S14. Operator input: The external checkpoint store (an S11 decision)

### S14 1C write port (size L)

Goal: Real writes on disposable clones, drafts first; a single writer; an atomic marker; compare-and-write; the unknown outcome.

Deliverables:
- `OneCWritePort` + an implementation for the channel from the CT14 gate; a COM writer for the licensed lane; a dedicated 1C account with minimal rights, the rights verified in fact
- The CT2 protocol: the marker in the same 1C write; the marker lookup and the write inside the single writer; the target lock until a resolved outcome; compare-and-write on the target version with an exclusive object lock (CT3); operations without an atomic marker or without locking are not admitted through this channel
- Call ownership (CT3): a ledger record before sending; the hard call deadline starts an attempt to determine completion (observation), and forced termination of the 1C session is allowed only if CT14 established its safety for that channel and base type (otherwise POSSIBLY_EXECUTING, base mutations held, reads, triage); tests for a hung call surviving a client disconnect, under both CT14 outcomes
- APPLY_UNKNOWN: resolution under the conditions (a)–(d) of CT2, a maximum age and TRIAGE_REQUIRED; no blind retry
- Checking the scope tuple and the target class against the configured base at the port itself; refusal outside the allowed classes (CT4); the effect check by register (CT8)
- Draft creation, posting, unposting — each as a separate change (CT7); one atomic 1C write per change; no hard delete
- 1C error taxonomy, bounded retries, a posting time budget, read priority for verification; measuring file-base locking: an OData write + a COM session + reads + a human
- Proof that the read token cannot write and the write token is rejected by the v1 gateway

Exit criteria: On a clone: create, read back, post, unpost; a retry and parallel applies → one document; a lost response after commit and an unreadable marker → APPLY_UNKNOWN without a blind retry; a race with a human, an OData client, a COM session and a second writer never yields VERIFIED on a lost update; a 1C error → a refusal with no partial write (E3, E17, E18, E19, E21, E22, E28, E33, E34, E35, E42).

Depends on: S12 (ledger interface frozen); the CT14 gate. Operator input: A licensed lane for COM (exists); the channel on Ivan follows the CT14 result

### S15 Verification and reconciliation (size L)

Goal: Expectation↔fact, base↔base, ledger↔1C in both directions, an independent oracle, negative controls.

Deliverables:
- Verifier R-a: read after write through v1 (per the S11 inventory); postings — against the document's own movements (registrar) and the operation rule table, multiset comparison; the balance baseline is captured at apply time under the writer lock
- An independent versioned oracle for **every** G8 operation (CT6); the verifier is structurally independent of the preview and normalization code (an import-graph check)
- A↔B reconciliation with an expected difference set, as multisets, with a baseline of unrelated differences (R-b), built on the test-lane MCP
- R-c in both directions by marker and content hash: at startup, after a restore and periodically; a document without a marker, an edit that left the marker unchanged, a missing movement; applies blocked until the reconciliation is clean (depends on S13)
- An enumerated data-level negative-control set: wrong account, wrong counterparty, wrong period, a missing movement line, swapped Dt/Kt, a distorted amount, an extra document, a duplicated identical movement row

Exit criteria: Every control of the enumerated set is detected; no false VERIFIED; the G8 label: «machine verified, not accountant attested» (E1, E2, E9, E10, E12, E25, E26, E37, E43); GPT-PM APPROVE.

Depends on: S13 (R-c), S14. Operator input: —

### S16 Independent approval channel and MCP surface (size L)

Goal: First the approval channel with web-application protection, then the tools for ChatGPT and Claude.

Deliverables:
- The approval page per CT12: a server-built preview from ledger and 1C data; an immutable preview version; CSRF, CSP, output encoding, a one-time nonce, approver sessions isolated from chat principals; IdP login; chat text never enters the preview
- The principal and target registries in working form (CT1, CT4); credentials only in protected storage, rotation and revocation (I13)
- Tools `change_propose / status / apply / verify / rollback_propose`; `approve` is not on the model-facing surface; «not read-only» annotations; safe errors by the single code registry
- Writes only on a private network; the write tools are not exposed on the public tunnel; indirect routes (proxy, redirect) are checked (D3)
- Proof for ChatGPT and Claude is a recorded tool-call replay; real client runs are marked NOT_RUN unless performed

Exit criteria: E1, E2, E4, E5, E17, E29, E32, E39 pass on the lanes through the **full approval path** (not just the absence of a tool); spoofed chat text does not change the preview; GPT-PM APPROVE.

Depends on: S12, S15. Operator input: The IdP choice for approvers (decision 5 of section 10; the test IdP is fit for the lanes only)

### S17 Document intake and workbench (size L)

Goal: Extraction from files in an isolated environment, entity resolution, a change list, reminders, UAT scripts.

Deliverables:
- The untrusted-file boundary (CT11): limits, parser isolation, no outbound connections, formulas and external references are not evaluated, per-field provenance; material financial fields are always reviewed by a human
- Extraction from xlsx/csv and PDF/images with a confidence; cross-checks against confidently wrong extraction
- Entity resolution: extend `aliases` to contracts and items, name search with human confirmation; a clarification protocol; resolution only within the company scope
- A corpus of injections and hostile files: an instruction in a field, in a hidden layer, in a filename, in an xlsx formula/comment, external references, decompression bombs, malformed, oversized and password-protected files, «post to another counterparty», numerically valid but deliberately wrong invoices
- Intake from a Drive folder (S7) as a source of proposals — only if the operator approves the access scheme (otherwise G4 is not required)
- A list of pending/applied/failed changes, retry, rollback; reminders and a task queue; UAT scripts for the operator and the accountant

Exit criteria: The corpus yields either a digest equal to the clean variant's digest or no proposal, and **no prohibited I/O, network attempt or authority change** (E27, E40, E7); low confidence and material fields yield no proposal without a human step; for H3 the share of fields corrected by a human is measured on the fixed set; until H3 is proven the supported E1 path is xlsx/csv and manual entry, PDF is best effort.

Depends on: S16. Operator input: **The UI-scope decision** (deferred by the operator as B4); the Drive decision (decision 6)

### S18 Reliability and independent security verification (size M)

Goal: Queue load and liveness, chaos, alerts, recovery; an independent review of the implemented architecture against the S11 threat model.

Deliverables:
- A bounded per-base queue with per-target locking (CT15): an unresolved APPLY_UNKNOWN parks only its own target with PROVEN_FINISHED and holds base mutations with POSSIBLY_EXECUTING (CT3); verification read priority; a posting time budget; shutdown with drain
- Chaos along the matrix: a kill in every crash window, network loss, a restart of 1C/Apache/gateway/PostgreSQL, two executor processes — no duplicates, no loss; the kill switch at every mutation boundary and during a blocking call
- Alert rules: oldest queued age, APPLYING age, APPLY_UNKNOWN and TRIAGE_REQUIRED counts, kill-switch state, drift, ledger and checkpoint write failures, write-attempt rate; a scheduled tick; delivery to a human when local logs fail; a supervisor with restart (the host processes must not die with a session)
- Quantified SLOs, timeouts, retry limits and a per-step failure table (the CT15 initial targets refined by measurement)
- R1 compatibility, migration rehearsal, time zones at the period-close boundary; runbooks split into routine procedures and actions needing a new approval
- An independent security review of the implemented architecture (the `security-reviewer` role or GPT-PM) against the S11 threat model; this is **not the first** substantive security review: it verifies the implementation of the contracts accepted in S11 and S12. The file-intake boundary is reviewed after S17 closes

Exit criteria: The quantified SLOs are met; the per-step failure table is filled; a forced failure reaches a human from telemetry alone; safety, liveness and alert delivery are confirmed (E41, E44); all BLOCKER/MAJOR are closed in one batch.

Depends on: S13, S14, S15, S16 (parallel with S17; the intake review after S17). Operator input: —

### S19 Release candidate, G8 acceptance, C1 closure (size S)

Goal: An exact-head manifest, G8 acceptance on the lanes, a full GPT-PM sweep, handover of the operator steps.

Deliverables:
- An exact-head manifest: code, configuration, schemas, recipes, check results; every sprint produces its own exact-head evidence manifest
- G8 acceptance on lanes A/B: all active golden scenarios (E1–E47 except the reserved E8) observed at the right boundary
- The gate-closure validator driven by the manifest (E46): it refuses missing predecessors and unapproved waivers
- A residual-risk record for the operator: the replacement of mutation tests by reasoning, structural independence and data was accepted by GPT-PM at plan level and is not equivalent to measured mutation coverage (section 17.3); the residual is shown in the G8 evidence and in the operator decision record
- Current documents: story ledger, evidence matrix, registry, runbooks; the four-field status ledger updated
- A production write-canary recipe (window, budget, one low-risk operation, rollback) — for the operator's signature

Exit criteria: G8 PASS on the lanes (machine verification), GPT-PM APPROVE on the exact head → C1 reached: ENGINEERING_COMPLETE (not PRODUCTION_READY). From here only external evidence (C2) and the signature (C3).

Depends on: S17, S18. Operator input: Signature of the canary recipe (operator)

Critical path: S11 → S12 → (S13 ‖ S14) → S15 → S16 → (S17 ‖ S18) → S19 [G8 is evaluated here, then C1] → G6-pre → G6 → G7 → PRODUCTION_GO.   G6 needs G3, G5, G6-pre, G8 (+G4 only when Drive intake is enabled); G3 waits for G2/OB-10/OB-11 and runs in parallel with the sprints; G6-pre also needs G1; S15 also depends on S13 for R-c; the S18 intake review comes after S17.

## 9. Gates

Gates form a dependency DAG (a machine-readable manifest and a closure validator are S11/S19 deliverables). Status in this table is the plan status, not a gate result: no gate has passed.

| Gate | Name | Status | Closure evidence / note | Predecessors |
| --- | --- | --- | --- | --- |
| G0 | Scope and architecture | S11 supplies evidence; closed after GPT-PM approval and the operator's recorded decisions (OB-01, OB-15) | The v2 scope decision record + threat model + R1 boundary + donor inventory | — |
| G1 | Database and security | the original G1 tails remain; S13 adds evidence for the change schema | G1 passes only on its original exit criteria (capacity, kill inside COMMIT, restore into another cluster) **and** with change-schema evidence at G1 level; the S13 evidence is not a substitute | G0 |
| G2 | Metadata/domain | depends on OB-10 (an external operator decision) | G8 needs only the operation catalogue from clone metadata (S11); G2 itself — authenticated source-wide observation (OB-10) — is needed for G6 | G0 |
| G3 | Accountant attestation | external, OB-11 | Needed for reads (the profile) and for verifying written postings in production; G8 does not replace it | G2 |
| G4 | Drive | CONDITIONAL: required only if Drive intake is enabled (decision 6, OB-12) | If Drive intake is not enabled, G4 is marked NOT_APPLICABLE through an approved waiver in the gate manifest (it never closes otherwise); G4 is on the critical path only when intake is enabled | G0 |
| G5 | UAT | needs the UI scope | Approval channel (S16), workbench (S17); UAT by the operator and the accountant | S16, S17 |
| G8 | **New:** controlled-change acceptance | evaluated in S19 | All active golden scenarios (E1–E47 without E8) PASS on A/B with falsifiable assertions at the right boundary (a before/after snapshot of the target base, the number of write-port calls, the refusal code in the ledger, independent 1C observation); the negative set: zero unauthorized writes; every write with audit-before-effect and a receipt; the enumerated negative-control set is detected; the kill switch, recovery and the audit anchor were exercised; the «invariant → scenario» matrix is complete. Label: «machine verified, not accountant attested». **G8 implies PASS of none of G0, G1, G2, G3, G5, G6-pre, G6, G7.** | G0 PASS, CT14, S12–S18 |
| G6-pre | Operational readiness | after G1 and G8 | Its own acceptance contract: actual workload metrics on real infrastructure, alarms firing on faults, repeatable recovery; the S9 modules are not evidence | G1, G8 |
| G6 | Production canary | after G3, G5, G6-pre, G8 and the operator's signed permission | A production write canary — only under a signed permission (CT4: base, company, operation, limit, expiry, purpose); staging is forbidden; capacity, chaos, recovery in the production class | G3, G5, G6-pre, G8 |
| G7 | Release | last | Exact-head manifest, all applicable gates PASS (G4 if enabled), the operator's `PRODUCTION_GO` | G0–G3, G5, G6 (+G4), G8 |

## 10. Dependencies in time order

| # | When | What | Who |
| --- | --- | --- | --- |
| 1 | Now (long lead) | OB-11: arrange the independent accountant for the export and attestation of the native 521.1 report (August 2026). Without it G3 and everything after it stalls. It does not depend on any sprint. | operator |
| 2 | Before the end of S11 | **Settled by GPT-PM on 2026-10-11** (D1–D3): draft by default, posting separate; the v2.0 catalogue (purchase document, a contract update by an allow-list, post/unpost; no payments, deletion, bulk operations, sales); a private topology. Left for S11: the concrete topology (the write-service host, the target base, an access path without a public tunnel) and the external audit-checkpoint store. | GPT-PM on review; the operator may veto |
| 3 | Before the end of S11 | Rollback by marking for deletion: this is the «deletion» class (operator only). Without a ruling the rollback is limited to unposting and correction (CT7). | operator only |
| 4 | Before S12 starts | Who approves changes (approver identities and their person ids) and whether an auto-policy is allowed on the test lane only. | operator |
| 5 | Before S16 | The IdP for approvers: the test IdP is fit for the lanes only; production needs a real one. | operator |
| 6 | Before S17 | The UI scope (a minimal approval page is recommended); the Drive decision: is `drive.readonly` (whole Drive) acceptable for invoice intake, otherwise intake only through chat upload and G4 becomes NOT_APPLICABLE. | operator (B4) |
| 7 | After S19 | A target-registry entry and the signed canary permission (base, company, operation, amount limit, expiry, purpose), the window, the rollback owner; then `PRODUCTION_GO`. | operator only |
| 8 | Before G0 and G2 close | OB-01 (scope rebaseline / explicit permission for an isolated prototype), OB-15 (approval of the donor and license inventory) — for G0; OB-10 (real 1C source access and the capture permit for `onec-818ha-reference`) — for G2. Definitions: `docs/phase2/OPERATOR_BACKLOG.md`. | operator |

## 11. Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Injection through invoice content («post to another counterparty») and hostile files | Critical | I2, I8, CT11: typed fields, a file is data with no authority, an isolated parser without a network, a human reviews material fields; a corpus in G8. |
| The model, or the same person through another account, approves (confused deputy, self-approval) | Critical | I4, CT1, CT12: the approver is a person, a separate channel and session, `approve` off the model surface, the executor checks the current caller's entitlement. |
| An unknown write outcome → a duplicate or a false failure | Critical | I7, CT2, CT10: APPLY_UNKNOWN, an atomic marker, resolution by a reader-health proof, FAILED_APPLY only on confirmed non-application, TRIAGE_REQUIRED. |
| Competing writers outside our control (a human, another client, background jobs); a lease expiring during a call | Critical | CT3: the target lock until a resolved outcome, compare-and-write inside 1C, race detection by read-back and R-c, refusal of an operation where that is impossible; serializability is not claimed. |
| Ledger tampering or rollback by a privileged DB administrator | High | I5, CT5: signed external checkpoints, SAFE_HOLD; the detection limits are stated. |
| A write into staging or production without permission; environment-label spoofing | Critical | I12, CT4: the target class by the authenticated base fingerprint, staging always DENY, production only under a signed single-purpose permission; the port enforces. |
| A cross-company or cross-tenant write, a wrong base, a wrong organization | Critical | I15, CT1, CT4: an immutable scope tuple at every boundary, a check at the port, narrow 1C accounts, a negative matrix. |
| Posting a document changed after approval; a rollback that damages dependent data | High | I6, CT7: separate proposals with their own document version and digest, re-checked before execution, ROLLBACK_REFUSED, no promise to restore history. |
| Indirect execution of the forbidden (money, deletion) through an allowed operation or a posting side effect | Critical | I10, CT8: classification by fields, types and effects; a document type admitted by proven registers; a movement check after posting. |
| The preview promises postings 1C has not computed yet; a false VERIFIED from a shared wrong rule | High | I11, CT6: the preview covers fields and totals; postings are checked against the document's own movements and an independent versioned oracle, multisets, structural verifier independence. |
| Lost update: the target was edited by hand between preview and apply | High | I3, CT3: the target version in the digest and compare-and-write inside the write (E23). |
| Aggregate limits exceeded by individually valid requests | High | I9, CT13: reservations transactional with the claim, an unknown outcome keeps the reservation, boundary and parallel tests (E38). |
| Wrong recognition of counterparty/contract/amount, including confidently wrong | High | Material fields are always reviewed by a human, cross-checks, a clarifying question instead of a guess, the R-a verification. |
| A write into a closed period, the wrong time zone | High | Server-side policy re-checked at apply and before the effect, UTC in the ledger with explicit conversion, boundary tests (E6, E24). |
| Ledger/1C skew after a restore of either side | High | A base fingerprint per apply, R-c in both directions at startup and after a restore, applies blocked until the reconciliation is clean (E25). |
| A 1C file base dislikes concurrent writes; one bad item blocks the queue; an endless APPLY_UNKNOWN | Medium | CT15: a single writer, a bounded queue, parking only its own target, a maximum unknown-outcome age and TRIAGE_REQUIRED, locking measurements; for production a client-server variant is a G6 condition. |
| No write channel without a client license on Ivan; the chosen path is not deployable in the target topology | Medium | CT14: a binary feasibility gate in S11, S12 is not frozen without SUPPORTED mandatory capabilities; a fallback channel is a separate decision. |
| A public tunnel to a write endpoint; leaked write secrets; a flaw in the approval-page protection | High | I13, I14, CT12: writes only on a private network (D3), protected secret storage, CSRF/CSP/sessions, a security review of the implementation in S18. |
| No native attestation (G3) for posting verification | High for production | On the lanes the verification is machine-only (label `native_reconciliation=NOT_RUN` and «not accountant attested»); production only after G3. |
| Host processes die with a session; an alert does not reach a human; logs stay green while the delivery channel is dead | High | A supervisor with restart, a scheduled tick, delivery to a human independent of local logs, a forced failure in S18. |
| A security-contract defect found late, after the interface is frozen | High | A GPT-PM review of the threat model in S11 and of the authorization and recovery contract before the S12 interface is frozen; S18 verifies the implementation, not the original design. |

## 12. Golden scenarios (G8) with falsifiable assertions

Layer U = offline unit (existing `tests/phase2` style, no lane needed); L = lanes A/B. Negative scenarios on lanes assert a before/after snapshot of B (document count, movement count, balance), zero write-port calls and the refusal code in the ledger. The existing READ-only guarantees stay under regression after WRITE/POST classes are added.

- The right observation boundary. In a unit test «zero write-port calls» is valuable; in a lane test it is not enough for scenarios about a process crash, an out-of-band writer or an indirect effect — those need independent 1C before/after evidence.
- Negative controls are on data, not on code. For every critical rule there is a concrete data or input distortion that the assertion must reject (E9, E12, E43, the E27/E40 corpus); mutation runs and deliberately broken implementations are banned by the operator (decision of 2026-10-09), so every assertion is justified in writing: which observable value would differ if the guard were switched off.
- The scenario manifest is honest: E1–E47 hold 46 active scenarios (E8 is reserved and not counted); the G8 report never says «47/47».

| ID | Scenario | Falsifying assertion | Invariants | Layer |
| --- | --- | --- | --- | --- |
| E1 | Invoice (xlsx/csv, PDF per the H3 outcome) → draft → approval → verify → post (separate approval) → A↔B reconciliation | The A↔B differences equal the expected multiset (document ref, N movement lines, balance delta); fields, company and organization equal the independent oracle; an extra or missing item → red | I6, I11, I15 | L |
| E2 | Contract update → before/after preview → write → fields after read-back | Read-back fields equal the approved «after»; the other contract fields are unchanged (a before/after snapshot); exactly one provenance row was appended, earlier markers intact | I3, I7, I11 | L |
| E3 | The same request and the same apply repeated: the same key; the same business key with a different idempotency key; a replay after a restore; the same logical request key with a different payload digest | The document count in B does not grow; the repeat returns the earlier receipt or `DUPLICATE_SUSPECTED`; the same logical request key with a different payload digest → `IDEMPOTENCY_CONFLICT` | I7 | U+L |
| E4 | Approver rejects / approval expired / digest changed after approval / a direct approval-service call with a stale version | Zero write-port calls; the B snapshot is unchanged; the ledger holds the code REJECTED/EXPIRED/DIGEST_MISMATCH/STALE_VERSION | I3 | U+L |
| E5 | Self-approval (including through a second account of the same person); a read token attempts a write | Refused with a safe code; zero port calls; the B snapshot is unchanged | I1, I4 | U+L |
| E6 | Another company/organization, a closed period, a limit — parametrized: amount = limit, limit+0.01, 0, negative, rounding; the first/last day of a closed period; a time-zone offset crossing the period boundary; contract currency ≠ document currency; VAT 0%/20%/mixed; a total ≠ lines+VAT; the aggregate budget and concurrent reservations | Each parameter yields the expected decision (allowed / refused with a code); on refusal zero port calls and an unchanged snapshot; the aggregate admitted never exceeds the budget | I3, I9, I15 | U |
| E7 | File injection: the operation, the target and the limits do not change | The proposal digest equals the digest of the clean variant of the same file **and** no prohibited I/O, network attempt or outbound data was observed in the parser's isolated environment | I2, I8 | U |
| E8 | RESERVED (superseded by E18); not counted among the active scenarios | See E18 | — | — |
| E9 | A distortion in the target base: wrong amount, account, counterparty, period, a missing movement line, swapped Dt/Kt, an extra document, a duplicated identical movement row | Every distortion of the enumerated set is detected by the independent oracle and the multiset comparison (red); no false VERIFIED | I11 | L |
| E10 | Rollback: unpost; correct a draft; rollback of a posted document; rollback after a later edit | The effect is neutralised by the document's own movements; the approved post-state is defined and checked; no «balance as before» claim (consumed numbers are acceptable); the impossible → `ROLLBACK_REFUSED` | I6, I11 | L |
| E11 | Kill switch on / off / its store unavailable | On or unavailable → zero new writes; off → the write applies; an in-flight apply reaches a terminal state/APPLY_UNKNOWN; reads for outcome determination stay available | I9 | U+L |
| E12 | An out-of-band edit before and after verification: a document without a marker, an edit that left the marker unchanged | R-c records the drift by marker and content hash in both directions; applies are blocked until the reconciliation is clean | I11 | L |
| E13 | The audit sink raises; the checkpoint store fails | Zero write-port calls **and** the independent B snapshot is unchanged; the state is not APPLIED | I5 | U+L |
| E14 | A post apply with only the draft approval; a draft edit after the post approval; an expired grant; an approval replay | Refused; the document stays unposted (checked in B) | I6 | U+L |
| E15 | «Delete August documents» / «pay the invoice» | A catalogue refusal; zero write-port calls (indirect paths — E42) | I2, I10 | U |
| E16 | The write port aimed outside the allowed lanes (a staging/production host); a spoofed environment label; a write endpoint on the public tunnel or behind a proxy | The port itself refuses; there is no public or indirect route to the write tools (route check, including proxy/redirect) | I12, I14 | U |
| E17 | A write token on the v1 gateway; a read token on the write service; a wrong audience; a foreign principal; a write by the 1C account outside the allowed objects | All rejected (audience/scope/1C rights); the attempt outside the allowed objects is denied by 1C itself | I1, I14 | U+L |
| E18 | The crash-window matrix: before audit / after audit before write / after write before ledger / after post; an unreadable marker; a commit/response race; two executor processes | In each window after recovery: one document or a safe retry; no duplicate; the state is right; the independent 1C snapshot confirms | I5, I7 | L |
| E19 | Two concurrent applies of one approved change; a lease expiry while the first call is still executing; a non-cooperating writer; simultaneous creates with different request ids but the same business key before any target ref exists | Exactly one document in B; a successor does not write until the predecessor's outcome is resolved; the second create gets `DUPLICATE_SUSPECTED` (or the earlier receipt for the same logical key) | I7 | L |
| E20 | A race: approve, a change of the proposal, a revocation of rights and a role change at the same time | Only the variant whose digest was approved by a currently entitled approver applies; the others are rejected; a revocation voids the approval | I3 | U |
| E21 | A timeout/drop after the 1C commit (the response is lost) | APPLY_UNKNOWN → after a reader-health proof and a complete observation → APPLIED; one document; no blind retry occurred | I7 | L |
| E22 | A 1C error on line N of M | No document created, or created whole (observed at the 1C persistence boundary); no partial draft | I7, I11 | L |
| E23 | The target was edited by hand between preview and apply, including inside the compare-and-write interval | The apply is rejected on the target version; the B snapshot is not changed by our write | I3 | U+L |
| E24 | An apply after the expiry, a period closed meanwhile, or the grant window/budget ended — while queued and while running | While queued: refused EXPIRED/PERIOD_CLOSED/GRANT_EXHAUSTED, zero port calls; while running: the current atomic write completes, the reservation is consumed, no new steps | I3, I9 | U |
| E25 | Skew after a restore: the ledger older or newer than 1C; a valid but old chain | Applies are blocked until R-c and the anchor check are clean; a repeat of E3 does not return a receipt for a nonexistent document | I5, I7, I11 | L |
| E26 | A rollback cannot be done (dependent documents, a closed period) | An explicit `ROLLBACK_REFUSED` with a reason (distinct from FAILED_VERIFY); the original document is not damaged (a before/after snapshot) | I6, I11 | L |
| E27 | Injection corpus: a field, a hidden layer, a filename, an xlsx formula/comment; malformed, oversized, password-protected; low confidence | For each item the digest = the clean variant's digest or no proposal; no prohibited I/O in the isolated environment; low confidence and material fields yield no proposal without a human step | I2, I8 | U |
| E28 | A business duplicate (base, organization, counterparty, contract, number, date, kind, currency) with a different idempotency key; legitimate similar documents; a deliberately separate document; parallel creates with different request ids | A true duplicate → `DUPLICATE_SUSPECTED`, the document count in B does not grow; legitimate similar documents (another organization/currency/kind/supplier) are NOT refused; a deliberately separate one passes only as a separate proposal with a reason and an approval | I7 | U+L |
| E29 | The author session calls an approval tool; spoofed «approved» text in the chat; a direct call to the approval service with the author's token | There is no `approve` tool on the model surface; the direct call is rejected by the service; chat text changes neither the state nor the preview | I4 | U+L |
| E30 | A check of the runtime secret store, logs, error responses and artifacts; rotation and revocation; a repository scan | No write secrets in the repository, logs or error responses; credentials only in protected storage; after rotation and revocation the old ones do not work | I13 | U+L |
| E31 | A tampered ledger row / a broken hash chain | Detected by the chain check; applies are blocked (coherent tampering — E36) | I5 | U |
| E32 | A user and company matrix: 2 users in a tenant, 2 companies in a tenant, a second tenant; cross-execution, impersonation, self-approval via a second account, approval replay, revoked credentials, a removed role, an IdP outage; overlapping supplier/contract/invoice numbers, a mixed-source file, an altered queue payload, a base-identity mismatch after a restore | Every unauthorized attempt is denied **before** the port is invoked (zero calls) and at the port itself; no cross-company reads or writes | I1, I3, I4, I15 | U+L |
| E33 | The apply protocol under faults: an unreadable marker (the reader is down), the same logical request key with a different payload digest, an interrupted contract update, a removed or overwritten marker, repeated recovery cycles | No duplicates, no falsely final failure or success; absence from an unreliable read is not treated as non-application; the same logical request key with a different payload digest → IDEMPOTENCY_CONFLICT | I7 | L |
| E34 | Competition with non-cooperating writers: a human in 1C, an OData client, a COM session and two application processes against one contract and one invoice; a lease expiry while 1C is executing; a hung 1C call surviving a client disconnect; a restarted executor; a queued write to a different target; both CT14 outcomes: forced session termination safe / unsafe or unsupported | No lost update and no duplicate is classified as VERIFIED; CONFLICT is recorded, dependent changes are parked; a write to another target does not proceed while call ownership is unresolved (`POSSIBLY_EXECUTING`), and progress resumes after completion is proven; with unsafe or unsupported forced termination none occurs and the base stays held until completion is proven by observation; the test runs on real 1C locking semantics, not on mocked ledger locks | I3, I7 | L |
| E35 | A target matrix: valid/invalid target identities, label spoofing, a stale permission, a wrong fingerprint, a revoked authorization, a signed canary permission | Staging is always rejected; production is allowed only for the exact authorized phase and scope; the decision is made by the port | I12, I14 | U |
| E36 | The audit anchor: tampered rows with a recomputed local chain, a restore to an older valid copy, an altered receipt, a replayed audit event, a key rotation, an unavailable checkpoint store | Every deviation is detected by an external checkpoint or causes SAFE_HOLD; an unavailable store → no new effects; history is not backfilled | I5 | U+L |
| E37 | Stale post/unpost: a draft edit after the post approval, a change of the posting-period settings, dependent documents, a closed period, a race of unposting with another editor | Every stale or unsafe operation is refused without modifying the target; permitted corrections are verified independently | I6, I11 | L |
| E38 | Budget races: parallel reservations at the boundary, mixed currencies, the same/different key, a rollback after a completed apply, a grant expiring during a call, a failed attempt whose effect was actually committed; the chain create→post→unpost, a contract update, an independent posting of a pre-existing draft — all at exact limit boundaries | The aggregate admitted never exceeds the grant; the reservations and cumulative totals of all three limits are checked after every operation against the CT13 matrix; an unknown outcome keeps its reservation until independent resolution | I9 | U+L |
| E39 | The approval page: direct API calls, CSRF, a stale-page submission, a concurrent proposal replacement, a session revocation, a stored XSS in a preview field, an unauthorized preview retrieval, a nonce replay | Every invalid approval fails without changing the authorization state | I3, I4 | L |
| E40 | Hostile files: malicious formulas, external references, embedded instructions, decompression bombs, parser failures, ambiguous entities, numerically valid but deliberately incorrect invoices | No prohibited I/O or authority change; correct escalation to a human; parser resources stay bounded | I2, I8 | U |
| E41 | Kill switch at the boundaries: activation immediately before each mutation boundary and during a blocked 1C call; an unavailable store | No new mutation begins; the in-flight uncertainty is recorded; read-only recovery is available; the operator has a list of in-flight and unresolved changes | I9 | L |
| E42 | Effect-level exclusions: updating bank details, payment terms, a deletion flag; indirect payment triggers on posting; nested payloads; disguised operations | A refusal at the schema boundary and a check of the actual 1C effects: no movements in cash/bank/payment registers arise; the forbidden is unreachable indirectly | I2, I10 | U+L |
| E43 | R-c and multisets: an unmarked document; a duplicated identical movement row; an edit without a marker change; an unrelated baseline A/B difference | All errors are detected and classified correctly; false verification is prevented; the baseline difference neither masks nor imitates the effect | I11 | L |
| E44 | Liveness: a permanent APPLY_UNKNOWN with a finished and with a possibly executing call, a hung 1C call with a write to another target queued (with safe and with unsafe/unsupported forced session termination per CT14), read contention, an alert-delivery failure while logs are green, repeated restarts, a queue overflow | With `PROVEN_FINISHED` an unresolved outcome parks only its own target, with `POSSIBLY_EXECUTING` base mutations are held while reads continue and progress resumes once ownership is resolved; with unsafe or unsupported forced termination none occurs and the base stays held until completion is proven; reads do not starve writes; an undelivered alert is detected; resources stay bounded; an overflow → a refusal code | I7, I9 | L |
| E45 | Model-based state tests: every illegal transition, every crash/resume path, status reporting | Every illegal transition is rejected; an unknown committed outcome never becomes a confirmed failure through a timeout or an expiry; reporting distinguishes all outcomes | I7 | U |
| E46 | The manifest-driven gate-closure validator: missing predecessors, unapproved waivers, Drive on/off, missing accountant evidence, missing G6-pre evidence | The validator refuses in every listed case and accepts the valid configurations | — | U |
| E47 | The CT14 feasibility record: enumerated capabilities, measured evidence, deployment assumptions, alternatives | An unsupported mandatory capability blocks the dependent implementation until the contract or scope is revised | — | U |

## 13. Hypotheses and spikes

| ID | Hypothesis | Proof | Fallback |
| --- | --- | --- | --- |
| H1 | A write through the standard OData (create and post) is possible without a client license under a narrow account. | The CT14 feasibility gate in S11: a capability matrix on a clone and on Ivan with a pass rule (create with a marker → read back → post → read movements → unpost; lock/CAS; narrow-account rights). | COM on the licensed lane; a configuration extension with an HTTP service (a separate decision with host and licensing dependencies). A fallback may not weaken the invariants. |
| H2 | A catalogue of 4–5 operations is enough to show the value and close G8. | A business hypothesis: the scenarios cannot refute it; the decision on extending the catalogue is taken by GPT-PM after G8 on operator feedback (an operator/product decision). | Catalogue extension — a separate sprint after G8. |
| H3 | PDF/image extraction gives an acceptable confidence with mandatory human approval. | A set of N real invoices on the lane; metric: the share of fields corrected by a human is at most X; N, X, the evaluation set and the rule for counting a «corrected field» are fixed in S11 **before** measuring. A human reviews material fields in any case. | The supported path: xlsx/csv and manual entry; E1 on that path; PDF is best effort. |
| H4 | v1 can read back everything verification needs (fields, lines, movements by registrar, the object version). | The read-back inventory in S11 (part of CT14). | A v1 read extension (read-only) as part of S15. Incomplete read-back blocks the affected operation types; it does not weaken verification. |

## 14. Non-goals of v2.0

- Payment and bank operations, any real-money action (operator-only); fields and effects that initiate them (CT8).
- Hard deletion, bulk edits and batch import without per-item approval; changes spanning several documents atomically; sales documents.
- Writes to staging (denied unconditionally) and to production — before the operator's separate signed permission and G3/G5/G6-pre/G8.
- Changing the 1C configuration to bypass limits (except an HTTP-service extension approved by a separate decision).
- Delegating execution to another principal; currency conversion in grant budgets; compensating documents (defined, but not in the v2.0 catalogue; v2.0 has only unposting and correction).

## 15. Process

- Development rules v4: documents first (TDD, design, sprint plan, DoD, test coverage from `functional-test-reviewer` and `e2e-runner`), then review to consensus, then the final GPT-PM; one PR per sprint.
- Four distinct levels of checking: (1) coding-time checks — small deterministic local unit tests that rules v4 allow during development; (2) sprint-end checks — independent reviews and tests run through subagents (with the operator's permission) or GPT-PM; (3) CI — not used by the operator's decision; (4) final approval — GPT-PM APPROVE on the exact head and the operator's `PRODUCTION_GO`.
- Security verification starts at the beginning, not in S18: the S11 threat model and the S12 authorization and recovery contract are reviewed by GPT-PM before the interface is frozen; the independent S18 review verifies the **implementation** of those contracts. Every sprint produces an exact-head evidence manifest; a change to approved content voids the corresponding approval.
- Subagents are launched only with the operator's permission for that run (the operator objected on 2026-10-11 to unrequested launches); the default review channel is GPT-PM.
- Mutation runs and deliberately broken implementations are not used (operator decision of 2026-10-09); negative controls are on data; every assertion is justified in writing (section 12 and section 17).
- Push and PR only after GPT-PM APPROVE on the exact head; a new commit voids the approval. A GPT-PM review of the plan authorizes no code, push or production action.
- Real safeguards are never relaxed: platform approvals, deletion, production, money, secrets, tenant isolation. A fallback may reduce scope but never weakens a mandatory invariant.

## 16. S11 binding contracts (CT1-CT15)

Each contract is a decision record fixed in S11 (and reviewed by GPT-PM before the S12 interface freeze where it concerns security, authorization or recovery). The content below is binding: a later sprint may refine it only by a new reviewed revision. Finding ids refer to the GPT-PM review of revision 2.

### CT1 Identity and authorization (answers F-01, F-06)

- The caller is the principal taken from the write-audience OAuth token of the current session; the person (person id), tenant, companies and roles come only from the trusted principal registry, never from tool arguments. Several accounts of one person are one person.
- `apply` is a request for execution, not a carrier of authority: the executor checks that the **current** caller is the requester of the proposal (no delegation in v2.0) and that the approval record exists and matches; knowing a change id grants nothing.
- An approval is a ledger record bound to the operation, target, company, immutable proposal version, preview digest, target version, approving person and expiry; the approving person ≠ the requester (by person id); the approver's role is re-checked at dequeue and before the effect.
- Revoking a session or role voids the approval (a new one is needed); source-token replay is limited by audience, a short expiry and a token id; IdP/registry unavailability is fail-closed, no new effects.

Acceptance: scenarios E32, E4, E5, E29.

### CT2 Apply protocol and unknown outcome (answers F-02, F-10)

- The intent is recorded and committed to the ledger before any effect; there are two different identities. (1) The **logical request key** is stable and independent of payload bytes: (the authenticated requester principal, change kind, scope tuple, the client request id); the MCP surface supplies the request id, a retry within one user request carries the same id. (2) The **canonical payload digest** (payload and target version) is stored immutably under the logical key. A repeated logical key with a different digest → `IDEMPOTENCY_CONFLICT`; with the same digest → the earlier receipt. If the client supplied no request id, a second layer catches the retry: the canonical business key for a create and the target ref + compare-and-write on the version for an update.
- The marker (`change_id` + digest) is written **in the same 1C write** as the effect: a document attribute on create; an appended (append-only) provenance row on update. An operation whose 1C write cannot carry the marker atomically is not part of v2.0 (an S11 result).
- Uniqueness comes from the single writer per base, a unique constraint on the idempotency identity in the ledger and the target lock (CT3); there is no claim that a distributed lease protects anything inside 1C. For an update idempotency is compare-and-write on the target version plus a read of the «after» state; markers are never overwritten, and an operator edit/removal of a marker is detected by R-c (by hash) and blocks applies.
- **Create.** There is no target ref yet, so the create-lock key is derived from the canonical scoped business key (base, organization, counterparty, contract, supplier number and date, kind, currency): a lock (base, hash of the business key). Inside the serialized writer, immediately before the atomic 1C write, the absence of a document with that business key or marker is re-checked. Two creates with different request ids but the same business key are serialized: one gets the effect, the other gets `DUPLICATE_SUSPECTED` (or the earlier receipt if the logical key matched). A uniqueness check outside the serialized create boundary is not a protection.
- An unknown outcome → `APPLY_UNKNOWN`. Resolution requires all of: (a) a reader-health proof (a canary read of a known marker succeeds), (b) a settle period, (c) a complete observation of the target scope, (d) proof that no 1C call of this executor lineage is still executing (call ownership, CT3); the target lock is held until resolution, a lease expiry does not release it. Found → `APPLIED`; absent under (a)–(d) → `CONFIRMED_NOT_APPLIED` → `FAILED_APPLY`/a safe retry; otherwise it stays unknown; past the maximum age (initially 5 attempts over 15 minutes) → `TRIAGE_REQUIRED` (a human). `FAILED_APPLY` is never assigned from a timeout.
- Posting and unposting follow the same rules (CT7): recovery reads the posted flag, the version and the movements by registrar. A ledger recovery table fixes the expected state after a crash at every point (intent, approval, write, response, verification) — an S12 result. Operations made of several 1C writes are outside v2.0.
- Duplicates and keys: for every document type a canonical business key with scope is defined (base, organization, counterparty, contract, supplier number and date, kind, currency). Distinguished: an idempotent retry (same key and digest), a suspected duplicate (same business key, different idempotency key → `DUPLICATE_SUSPECTED`), a deliberately separate document (a new proposal with a reason and its own approval).

Acceptance: scenarios E3, E18, E21, E22, E28, E33.

### CT3 Concurrency model (answers F-03)

- No claim that a fence protects 1C is made: there is none in 1C. Layers: (1) one writer per base and a per-target lock table in the ledger keyed (base, target); (2) the target lock is held from APPLYING until a resolved outcome — a lease expiry hands it to nobody; a successor first resolves the predecessor's outcome per CT2; (3) compare-and-write inside the 1C write: an exclusive 1C object lock, reading the version, comparing with the approved target version, writing, releasing; if a channel cannot do this the capability is UNSUPPORTED and the operation through that channel is ineligible.
- **1C call ownership.** Every write call is recorded in the ledger before it is sent: {call id, writer process and host, 1C session/connection, start, hard deadline}. The expiry of the hard deadline only **starts an attempt to determine whether the call has finished**: observation first (did a result return, the 1C session list, the client process). A forced session termination (cluster administration or the COM client process) is a last resort and is allowed **only if** CT14 established its safety for that channel and base type (the capability «forced session termination is safe» = SUPPORTED, in particular for a file base: residual locks, integrity). Otherwise the call stays `POSSIBLY_EXECUTING`: base mutations are held, only read-only investigation is allowed, an alert and triage follow; there is no forced termination. A call is **proven finished** (`PROVEN_FINISHED`) when (a) it returned a result to the writer, or (b) the termination of the 1C session that issued it is observed (the 1C session list, the client process exit), or (c) — only when CT14 allows forced termination — the deadline passed, the session was terminated by force and the termination was observed. **A deadline alone never establishes PROVEN_FINISHED.** An expired lease, a vanished process or a lost connection are not proof; if completion cannot be proven the state is `POSSIBLY_EXECUTING`: all mutations on the base are held (a per-base SAFE_HOLD), reads continue, an alert is raised, and past the maximum age `TRIAGE_REQUIRED`.
- **Consequence for the queue.** An unknown outcome with `PROVEN_FINISHED` parks only its own target; other targets continue. An unknown outcome with `POSSIBLY_EXECUTING` holds all mutations of the base until call ownership is resolved — unless the measured 1C model (CT14: «concurrent writes to different objects by separate sessions» SUPPORTED) independently proves that an operation on another target cannot conflict. While that capability is not SUPPORTED the hold applies to the whole base.
- Other writers (a human, another client, background jobs): in the managed scope an operational restriction applies (a policy, not a technical guard); detection is R-c and the read after the write; a race → `CONFLICT`, dependent changes are parked, VERIFIED is not assigned; serializability is not claimed.
- If for an operation a race can neither be excluded nor detected, the operation is refused (not «best effort»). The restrictions and their limits are written in the runbook.

Acceptance: scenarios E34, E19, E23.

### CT4 Target classes and environment permissions (answers F-04)

- The target identity is the authenticated 1C base fingerprint (infobase id + epoch + a target-registry entry signed by the operator); host names and environment labels from a request are ignored; an unknown class → DENY.
- **A disposable isolated clone** — writes only under the test-lane policy, a grant and an approval. **Staging** — always DENY (operator decision). **Production** — default DENY; the G6 canary only under a signed operator permission carrying base, company, operation, amount limit, expiry and purpose; general enablement after G3, G5, G8, G6-pre, G6 and `PRODUCTION_GO`.
- Permissions live in the ledger, are signed, single-purpose and expiring; a stale or revoked one is rejected by the port, not only by the policy service.

Acceptance: scenarios E35, E16.

### CT5 Audit integrity (answers F-05)

- An append-only event log; every pre-effect event (intent, approval consumption, APPLYING) is covered by a signed checkpoint {sequence number, head hash, time} written to an external append-only store outside the DB administrator's trust boundary (a separate host/account, write-only rights for the service, the key held by a separate signer, a key id in the record). A checkpoint not written → no new effects (fail-closed); unknown outcomes resolve by reading only.
- At startup and after any restore: the ledger head sequence is ≥ the last checkpoint and contains its hash, otherwise `SAFE_HOLD` (applies blocked, an alert). Anchor unavailability yields a bounded hold; the gap is recorded as an `ANCHOR_GAP` event, history is never backfilled.
- Detected: history rewriting by a DB administrator before the last checkpoint (even with a recomputed chain), a restore to an older valid copy after a checkpoint, a replayed audit event (by sequence number). Not detected, stated openly: tampering with events after the last checkpoint and before the next; an adversary holding both DB administrator rights and the signer key. Key rotation is a signed record; retention, backups and restore are in the runbook.

Acceptance: scenarios E36, E13, E18.

### CT6 Verification oracle (answers F-11)

- Versioned independent expectations for every G8 operation (rounding, VAT, currency, organization, period, movement multiplicity), hand-computed from a real posting of a known document; the verifier does not import the preview, normalization or write-serialization code (a structural import-graph check).
- R-b compares multisets; pre-existing A/B differences are a baseline; R-c checks both directions with a baseline, an inventory cursor and scan coverage.

Acceptance: scenarios E1, E2, E9, E12, E25, E43.

### CT7 Posting, unposting, rollback (answers F-07, F-20)

- Posting, unposting, correction and compensation are separate immutable proposals. Each carries the document reference, the **current** document version, a business-state digest (fields, lines, totals), the allowed effects (expected movements and permitted registers) and its own approval; everything is re-checked under the writer lock immediately before execution.
- Definitions: **unposting** — clearing the posting, the document remains; **correction** — editing a draft; **compensation** — a separate correcting/reversing document (in v2.0 only unposting and correction); «rollback» is a user-level term for the safest of them, without a promise to restore financial history.
- Automatic rollback is forbidden with dependent documents, a closed period, externally consumed identifiers and later edits: `ROLLBACK_REFUSED` with reasons, the document unchanged. A rollback has its own lifecycle, independent of the original operation's verification outcome.

Acceptance: scenarios E37, E10, E14, E26.

### CT8 Effects instead of operation names (answers F-19)

- The contract field allow-list is fixed from real metadata in S11 (candidates: validity end date, description/comment); **excluded**: bank details, payment terms and schedule, settlement fields, the deletion mark and any field that drives cash or bank registers.
- A document type is admitted to posting only if S11 proved from metadata and a posting on a clone that the posting handler writes only to the registers in the rule table (no cash/bank/payment registers and no auto-created payment documents). After posting, movements outside the list → `FAILED_VERIFY` (effect known) + an alert + a halt of the base queue; rollback helpers never set a deletion mark.
- Whatever is unsuitable by its effects is dropped from the catalogue or needs a separate operator permission.

Acceptance: scenarios E42, E15.

### CT9 Kill switch: modes and in-flight operations (answers F-13)

- `STOP_ADMIT` — no new proposals are taken from the queue; `STOP_EFFECTS` (the default emergency mode) — no new mutation step begins, an in-flight call may return, only reads to determine outcomes are permitted, an alert; `REVOKE` — credential revocation by the operator (also blocks reads).
- The kill-switch store unavailable → `STOP_EFFECTS`. Checked at dequeue and before each mutation step. The limitation is stated openly: a call already executing inside 1C may still commit. After a stop the operator sees a list of all in-flight and unresolved changes (APPLYING, APPLY_UNKNOWN, TRIAGE_REQUIRED).

Acceptance: scenarios E41, E11.

### CT10 State taxonomy and error-code registry (answers F-20, M-06)

- Dimensions (stored as one state with attributes): lifecycle (PROPOSED, VALIDATED, REJECTED, EXPIRED_QUEUED), authorization (the approval record: valid/voided/revoked), execution (NOT_STARTED, APPLYING, APPLY_UNKNOWN, APPLIED, FAILED_APPLY, TRIAGE_REQUIRED), verification (NOT_VERIFIED, VERIFIED, FAILED_VERIFY + effect_known), compensation (separate changes with a `compensates` link).
- Rules: terminal states carry proof conditions; a legal transition graph, event ids, idempotent handlers; `FAILED_APPLY` only with `CONFIRMED_NOT_APPLIED`; an expiry reaching APPLYING is evaluated at the next effect boundary; `ROLLBACK_REFUSED` is distinct from `FAILED_VERIFY`; the transitions APPLY_UNKNOWN → APPLIED and APPLIED → VERIFIED require an actual 1C read.
- The `call_ownership` attribute (`PROVEN_FINISHED` \| `POSSIBLY_EXECUTING`) of changes in APPLYING and APPLY_UNKNOWN determines the queue hold scope (CT3, CT15); only an observation per CT3 moves it from `POSSIBLY_EXECUTING` to `PROVEN_FINISHED`.
- One registry of safe error codes for the MCP surface, the ledger, the approval UI and operator alerts.

Acceptance: scenarios E45.

### CT11 Untrusted-file processing boundary (answers F-12)

- Size and decompression limits; the parser in an isolated environment; no outbound connections; formulas and external references are never evaluated or followed; file provenance and per-field extraction provenance; malware handling; the model may not call `apply` on an instruction obtained from a file; content does not select the company, the operation, the authority or the approval status.
- Material financial fields (amount, VAT, counterparty, contract, dates) are always reviewed by a human — regardless of confidence; a confidently wrong extraction is caught by cross-checks (lines and VAT = total, contract terms, currency).

Acceptance: scenarios E40, E27, E7.

### CT12 Approval-page protection (answers F-18)

- Session security (httpOnly, SameSite, a short lifetime, re-authentication for approval), CSRF tokens, authorization checked on every request, an immutable preview version (the page submits the version and digest, the server rejects if the proposal changed), output encoding, CSP and framing denial, a one-time nonce against replay, an approval audit, a second confirmation for posting and for amounts above a threshold.
- Approver sessions are isolated from chat principals: a separate cookie scope, no cross-use; a separate IdP login is not sufficient if a low-trust principal can create or control an approver session.

Acceptance: scenarios E39, E29.

### CT13 Grant budget semantics (answers F-09)

- Unit: the gross document amount including VAT in the document currency, per (grant, company, currency); no cross-currency conversion in v2.0 (a document in a currency without a budget is refused); a separate document-count limit; a half-open window [start, end); an inclusive boundary (amount ≤ remaining is admitted, more is refused).
- **The per-operation accounting matrix.** Three limits per grant: an amount per (company, currency), a count of create/update changes, a count of post/unpost changes. **Document create**: gross amount + 1 to the create/update counter. **Contract update**: 0 amount + 1 to the create/update counter. **Post**: 1 to the post counter and an amount only for the part not yet consumed for this document under this grant (a draft from the change chain — 0; a pre-existing draft — the full gross amount). **Unpost**: 1 to the post counter, 0 amount, no refund. **Re-post** after an unpost: 1 to the counter, 0 amount. **Correction** of a document amount: only the positive delta against the amount already consumed, a decrease refunds nothing. The ledger keeps `amount_consumed(document, grant)`; the chain is defined by the parent link. Approval independence is not weakened and there is no automatic refund on unposting.
- Reservation is transactional with the queue claim: RESERVED → CONSUMED (APPLIED) \| RELEASED (only REJECTED/EXPIRED before any effect or CONFIRMED_NOT_APPLIED); an unknown outcome keeps the reservation; unposting refunds nothing; a window expiring during a call — the call finishes its current atomic write and consumes the reservation, no new reservations.

Acceptance: scenarios E38, E6, E24.

### CT14 The S11 feasibility gate (answers F-15)

- A capability matrix per channel and per operation: draft create, modify, post, unpost, read-back (fields, lines, movements by registrar, object version), an atomic marker, an exclusive lock/CAS, concurrent writes to different objects by separate sessions, listing and forced termination of 1C sessions (including the safety of that for a file base), no payment side effects, behaviour under narrow rights and in the target deployment (Ivan has no client license). Every cell is SUPPORTED/UNSUPPORTED/INCONCLUSIVE with measured evidence.
- A mandatory capability not SUPPORTED → the dependent operation type and the S12 interface freeze for it are blocked; UNSUPPORTED/INCONCLUSIVE never means «proceed with the optimistic design»; a fallback channel needs a separately approved decision with host and licensing dependencies; narrowing scope is allowed, weakening an invariant is not.

Acceptance: scenarios E47.

### CT15 Liveness and operability (answers F-16)

- Initial targets (revised by measurement): the per-base queue is bounded at 20 items with a refusal code on overflow; an unknown outcome with `PROVEN_FINISHED` parks only its own target, with `POSSIBLY_EXECUTING` base mutations are held until call ownership is resolved (CT3); the hard deadline of a write call is initially 120 s (posting 300 s); its expiry only starts a determination of call completion (CT3), and a forced termination of the 1C session happens only if CT14 established its safety, otherwise POSSIBLY_EXECUTING and triage; verification reads take priority over new writes; the maximum unknown-outcome age is 5 attempts over 15 minutes, then `TRIAGE_REQUIRED`; an alert to a human within ≤ 60 s; the operator triage target is one business day; shutdown with queue drain is defined.
- Acceptance: a multi-process workload, slow 1C operations, blocked markers, read contention, repeated restarts, a hung 1C call surviving a client disconnect with a queued write to another target, and an alert-delivery failure — safety, liveness, alert delivery and bounded resource use are verified.

Acceptance: scenarios E44.

## 17. Handling of the GPT-PM review of revision 2

### 17.1 Finding to change map

| ID | Severity | Finding | Where changed |
| --- | --- | --- | --- |
| F-01 | BLOCKER | Identity, authorization and delegation model | CT1; I3, I4, I15; E32, E4, E5, E29; §4 steps 5–6; S11, S12, S16; component «Principal & authorization registry» |
| F-02 | BLOCKER | Atomicity, idempotency and APPLY_UNKNOWN as a complete protocol | CT2, CT10; I7; E3, E18, E21, E22, E33; S14; the §4 states |
| F-03 | BLOCKER | A single writer does not isolate from other 1C writers | CT3; I3, I7; E19, E34; S13/S14 (no claim of a fence in 1C) |
| F-04 | BLOCKER | Staging, production and operator permissions conflict | CT4; I12; E16, E35; the G6/G7 rows in §9; §14 |
| F-05 | BLOCKER | Audit integrity is not established by a hash chain alone | CT5; I5; E31, E36, E13, E25; S13; component «Audit anchor & signer» |
| F-06 | BLOCKER | Tenant/company isolation is not proven through every transition | I15, CT1, CT4; E32, E6; the ledger and 1C write port components |
| F-07 | BLOCKER | Posting and rollback authority can exceed what was approved | CT7; I6; E14, E37, E10, E26; §4 step 9 |
| F-08 | BLOCKER | The G8 evidence matrix does not prove several security invariants | §5 (the «direct falsification at the enforcement boundary» column for I1–I15); E1–E47 rewritten; the harness rules in §12; one part not adopted — §17 |
| F-09 | MAJOR | Exact grant-budget semantics | CT13; I9; E38, E6, E24 |
| F-10 | MAJOR | Duplicate identity and marker storage | CT2 (business keys, append-only marker); E28, E33 |
| F-11 | MAJOR | Verification-oracle independence and a two-directional R-c | CT6; R-a/R-b/R-c in §7; E9, E12, E43; S15; one part not adopted — §17 |
| F-12 | MAJOR | The untrusted-file processing boundary | CT11; I8; E7, E27, E40; S17 |
| F-13 | MAJOR | The kill-switch policy for in-flight operations | CT9; I9; E11, E41 |
| F-14 | MAJOR | Gate dependencies, closure ownership, mandatory paths | §9 (a predecessor graph, G4 conditional, G6-pre separate, G8 replaces no other gate); §10 item 8 (OB-01/10/15); the critical path; C1 (owner and four status fields); the gate manifest and E46 in S11/S19 |
| F-15 | MAJOR | Write/read-back channel feasibility as a binary gate | CT14; S11; E47; H1, H4 |
| F-16 | MAJOR | Scale, liveness and recovery progress | CT15; S18; E44; risks |
| F-17 | MAJOR | Security verification too late in the sprint process | §15 (four levels of checking; GPT-PM review of the S11 threat model and the S12 contract before the freeze; an exact-head manifest per sprint); S11, S12, S18 |
| F-18 | MAJOR | Approval-page protection and preview integrity | CT12; S16; E39, E29 |
| F-19 | MAJOR | Operator-only money/deletion — by effect, not by name | CT8; I10; E15, E42 |
| F-20 | MAJOR | State finality and rollback transitions | CT10; §4 states; E26, E45 |
| M-01 | MINOR | A sales mention in §6 against a purchase-only catalogue | Removed: the «Change catalogue & schemas» component, decision D2, §14 |
| M-02 | MINOR | E8 is a placeholder (30 active of 31) | E8 reserved; E1–E47 = 46 active; the scenario-manifest rule in §12 |
| M-03 | MINOR | Terminology: invoice/receipt/1C document type | S11: a glossary (the user-level term → a concrete 1C document type) |
| M-04 | MINOR | OB-xx abbreviations without definitions | §10 item 8 with a link to `docs/phase2/OPERATOR_BACKLOG.md` |
| M-05 | MINOR | H3 metrics: how a corrected field is counted | H3 and S11: the counting rule and the evaluation set before measuring |
| M-06 | MINOR | A standard safe-error-code taxonomy | CT10; S12 (one registry) |
| M-07 | MINOR | Runbooks: routine procedures vs those needing new approval | S18; the Ops component |
| M-08 | MINOR | The English record is canonical, the Russian is regenerated | Both languages are generated from one data set; the English `.md` is the primary record |

### 17.2 Parts not adopted in their original form

| Finding | Requirement as written | Why not adopted and what replaces it |
| --- | --- | --- |
| F-08 | The acceptance test «a deliberate bypass mutation must make its corresponding test fail» and the global rule «for every critical rule at least one deliberately faulty implementation must be rejected by its assertion». | Mutation runs and breaking a guard to see a test go red are banned by the operator (decision of 2026-10-09), and a review requirement cannot override that. Replacement: (1) every assertion names in writing the observable value that would differ with the guard off; (2) negative controls are data and input distortions (E9, E12, E43, the E27/E40 corpora); (3) structural independence checks (the verifier does not import the preview or normalization code). The residual risk is stated: assertion strength remains a reasoned argument, not a measured kill rate; accepting this residual is the operator's choice. |
| F-11 | The acceptance test «mutate the writer and verifier with the same incorrect tax rule» (a mutation). | The same operator ban. Replacement: oracle independence is secured by construction (expectations hand-computed from a real posting; the verifier imports neither the preview nor the write code — a structural import-graph check) and by data (E9, E43 with distorted amounts and taxes in the target base). |

### 17.3 Residual risk recorded for the operator

- Replacing mutation tests by reasoning, structural independence and data-level negative controls is **not equivalent to measured mutation coverage**.
- Residual risk 1: two logically independent components (for example the preview and the verifier) can embody the same wrong accounting assumption; code independence does not exclude that.
- Residual risk 2: an assertion that looks discriminating may not detect every implementation bypass; assertion strength remains a reasoned argument, not a measured figure.
- Decision: GPT-PM accepted the replacement as sufficient for plan approval and confirmed that mutation runs are not to return (the operator ban stands). The residual must stay visible in the G8 evidence and in the operator decision record (S19); accepting it is the operator's decision.

### 17.4 Verification rounds on revisions 3 and 4 (GPT-PM, 2026-10-11) and the changes they caused

Round on revision 3: 15 of 20 findings closed, three MAJOR left (no BLOCKER); revision 4 changed only these and their direct references. Round on revision 4: R3-01, R3-02, R3-03 closed, one MAJOR regression (R4-01); revision 5 changes only it and its direct references.

| ID | Severity | Finding | Where changed |
| --- | --- | --- | --- |
| R3-01 | MAJOR | Idempotency identity, conflict detection and create locking: a key that includes the digest cannot «match with a different digest»; a new document has no target ref to lock on | CT2 (a logical request key + an immutable canonical digest; a create lock on the canonical business key; a duplicate re-check inside the serialized writer); I7; E3, E19, E28, E33 extended. Closes the remainder of F-02, F-10 |
| R3-02 | MAJOR | Grant accounting is not defined for every operation class (contract update, post, unpost) | CT13 (the accounting matrix: three limits; create, update, post, unpost, re-post, amount correction; `amount_consumed(document, grant)`); E38 extended. Closes the remainder of F-09 |
| R3-03 | MAJOR | A single writer per base conflicts with parking an unknown outcome by target only | CT3 (call ownership, a hard deadline that starts a completion check (forced session termination only when CT14 established its safety, see R4-01), `PROVEN_FINISHED` / `POSSIBLY_EXECUTING`, the consequence for the queue); CT2 condition (d); CT10 (the `call_ownership` attribute); CT14 (two new capabilities); CT15; S14; E19, E34, E44 extended. Closes the remainder of F-03, F-16 |
| R4-01 | MAJOR | A regression of the R3-03 edit: forced termination of the 1C session is conditional in CT3 but unconditional in S14, S18 and CT15 | CT3 (the deadline only starts a determination of completion; forced termination only when CT14 established its safety; a deadline alone is not PROVEN_FINISHED), S14, CT15, S18; E34, E44 extended with both CT14 outcomes |

