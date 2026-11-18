# S16 approval channel and MCP surface - sprint plan (draft, rev 2) - 2026-10-28

Rev 2 applies the findings of two independent reviews; see section 14 "Review resolutions".

Status: DRAFT planning artifact. It does not alter `governance/GATE_MANIFEST.json`, pass any gate, qualify or enable the writer, or authorize
any COM write, deployment or production activity. Nothing below is implemented unless a cited change record says so.

Evidence labels used throughout: FACT (read in a cited file or in code at the time of writing), INFERENCE (reasoned from facts, to be confirmed),
UNKNOWN (no source found in the files read).

## 1. Authority and sources

- Sprint and story IDs: `S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md` section 3 (FACT: line "S16 | V2-S16-01 .. V2-S16-05 | approval page,
  registries and secrets, MCP surface, private-network exposure, recorded tool-call replay"). The register line carries names only. The numbered
  pairing used below (01 approval page, 02 registries and secrets, 03 MCP surface, 04 private-network exposure, 05 recorded replay) is given
  explicitly, with the same numbers, in `S11_TEST_DESIGN_PACKAGE_2026-10-12.md` section C (S16 row) and is consistent with the register order (FACT).
- Scope text: `S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md` (S16 row) and `PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` section "S16"
  (deliverables and exit criteria), CT12 (approval-page protection), invariants I4, I12, I13, I14, decision D3 (private-network-only writes) and the
  scenario table E1..E47.
- Contract freeze: `S12_CONTRACT_FREEZE_V2_2026-10-16.md` (operation scope, trust boundaries, identity registry, evidence types).
- Threat model: `S11_DECISION_RECORDS_AND_THREAT_MODEL_2026-10-12.md` (trust boundary T1 chat client to MCP surface, T5 approver browser to approval
  service; TM3 self-approval, TM4 approval replay or CSRF).
- Execution plan: `AUTONOMOUS_EXECUTION_PLAN_2026-10-21.md`, work package WP8 (S16 approval channel and MCP surface; depends on WP7 = S15).
- Entry code read for interfaces: `src/business_ai_gateway/phase2/change/` (`proposal.py`, `errors.py`, `types.py`, `killswitch.py`,
  `trust_registry.py`), `src/business_ai_gateway/phase2/safe_errors.py`, `src/erp_mcp_private_writer/private_ingress.py`,
  `src/business_ai_gateway/admin_session.py`, `src/erp_mcp_s15/`.
- Read in rev 2: `S12_APPROVAL_DIGEST_2_SPEC.md`, `src/erp_mcp_s15/verifier.py`, `change/errors.py`, `change/types.py`, `change/policy.py`,
  `change/transitions.py` (transition names only), `src/erp_mcp_private_writer/private_ingress.py` (the only `private_ingress*.py` file).
- Not re-read for this plan: the S12 SQL ledger internals, the gate manifest, the S15 change records.

### 1.1 Discrepancies between sources (recorded, not silently resolved)

1. Scenario lists differ. PLAN_V2 S16 exit criteria: E1, E2, E4, E5, E17, E29, E32, E39. The 2026-10-17 map and the test-package focused-test list:
   E39, E29, E5, E4, E16, E14, E30, E32 (plus tools/list and direct-call assertions). This plan uses the union (section 8). See open question Q1.
2. E2 (contract update) is in the PLAN_V2 S16 exit list, but the S12 freeze lists contract update as OUT and the 2026-10-17 map excludes it from the
   v2.0 write catalogue. The same conflict was decided for S15 on 2026-10-27 (deferred, PLAN_V2 not amended). S16 follows that decision: E2 is DEFERRED.

Notes (wording only, not discrepancies):

- Register says "recorded tool-call replay", the map says "recorded client replay"; the tool is `rollback_propose` in the plan deliverables.
- The register line has names only, so the story descriptions in section 6 come from the map and test package (FACT).

## 2. Hard constraints (apply to every story)

1. S12 (change model, policy, ledger interface) and S13 (PostgreSQL ledger and anchor) are NOT formally accepted (FACT: S12 freeze status text records
   REVISE reviews on 2026-10-23; S13 acceptance state after 2026-10-17 is UNKNOWN). S16 is therefore specified as pure logic over injected ports,
   tested with fakes, exactly as S15 is. Where a real S12/S13 module exists in the tree (for example `ChangeProposal`, `approval_digest`, `ErrorCode`),
   S16 consumes it as a value/contract, not as proof that S12 is accepted.
2. Nothing in S16 is wired into any gateway, ASGI app, listener or process manager. The production binding set stays empty. No new route is registered
   on the R1 gateway.
3. The S14 writer stays UNQUALIFIED and disabled. S16 never calls the COM write port; the `apply` tool logic ends at a fake apply port.
4. The `approve` action is never exposed on the model-facing tool surface. The model-facing surface is exactly: propose, status, apply, verify,
   rollback_propose. Approval exists only as an operation of the separate approval service reached by an approver browser session.
5. Writes are private-network-only. Proxy, redirect and public-tunnel bypass routes are denied (I12, I14, D3).
6. The approval page is a server-generated immutable preview in an isolated approver session with a one-use nonce and CSRF, CSP, output-encoding and
   framing protections (CT12). Chat text never enters the preview.
7. The identity provider (IdP) used on the lanes is a TEST IdP only. The production IdP is an external operator decision (PLAN_V2 section 10,
   decision 5) and is out of scope.
8. Real ChatGPT and Claude client runs are NOT_RUN unless observed and recorded with evidence.
9. All text committed is English. No tests are run by the coordinator; per the project workflow the test-owning agents write and run them after code
   is complete.

## 3. Entry state (FACT unless marked)

- S15 verification code exists as `src/erp_mcp_s15/` (verifier, oracle, A-to-B compare, reconcile, negative controls; not wired into any gateway). The
  S15 plan is a draft; S15 formal acceptance is UNKNOWN. The S16 `verify` tool consumes S15 only through a port (section 5).
- S12-level value types exist: `ChangeProposal` (frozen dataclass with scope tuple, kind, payload digest, preview digest, expiry), the approval digest
  `S12-APPROVAL-2` (`approval_canonical_text` / `approval_digest`, which includes `approval_nonce` and `preview_digest`), the single error-code
  registry `ErrorCode` with `NextAction` and `render`, lifecycle/authorization/execution/verification enums, the kill-switch evaluator, and
  `TrustedIdentityRegistry` for signer identities. Their acceptance status is not established by this plan.
- `private_ingress.py` already implements a loopback-only request check that rejects `Forwarded`, `X-Real-IP` and `X-Forwarded-*` headers and
  requires a single `Host` equal to the server socket address. It is a reusable pattern for E16 (INFERENCE: pattern, not an S16 deliverable).
- `admin_session.py` and `workbench_session.py` provide session and cookie patterns in the existing gateway. Whether they are reused for approver
  sessions is an open design choice (Q6). CT12 requires approver sessions isolated from chat principals, so a shared session store would not satisfy it
  by itself.
- No module implementing an MCP change-tool surface, an approval page or a secret store was found by file-name search of `src/` (INFERENCE from a
  name search, not a content audit). S16 is new code.
- The S14 executor is not wired; the production binding set is empty; the writer is UNQUALIFIED and disabled (FACT per S15 plan section 2).

## 4. Dependencies, order and fallback

- Upstream per the map: S12 and S15. Per the execution plan: WP7 (S15) before WP8.
- Fallback (in force now): S12/S13/S15 are not accepted, so S16 is delivered against fakes of the ledger/change service, verifier and clock, and is
  recorded as such. Acceptance rows that need the real ledger or real client stay NOT_RUN. S16 is not closed as fully accepted in that case.
- Epic order: E16-2 (principal and target registries, secrets: the approver identity and person-id data the page needs) -> E16-1 (approval page) ->
  E16-3 (MCP tools) -> E16-4 (private-network exposure) -> E16-5 (recorded replay, needs the tools). E16-4 may start after E16-3 interfaces exist.
  PLAN_V2 says "first the approval channel, then the tools": E16-2 only supplies data to the channel and does not change that ordering of the
  user-visible deliverables.

## 5. Goal, non-goals and ports

Goal: the independent approval channel with web-application protection, then the model-facing tool surface, such that the full approval path
(propose, preview, approver decision, apply, verify) works over fakes and a spoofed "approved" chat text changes neither state nor preview.

Non-goals and explicitly out of scope:

- Production identity and the production IdP choice; real SSO configuration.
- Real client replay: real ChatGPT or Claude sessions, real connectors, real tunnels (NOT_RUN unless observed).
- UI/accessibility user acceptance testing (UAT) with real approvers; the UX and a11y expert review of the page states is in scope, user UAT is not.
- Deployment of any kind (FORBIDDEN): no service install, no listener on a real interface, no tunnel, no gateway registration.
- Enabling the writer, any COM write, 1C real-base activity, post/unpost on a real base, contract update (E2), Drive intake, document intake (S17),
  gates G1-G7, and the independent security review of the implementation (S18).

### 5.1 S16-owned decision core (decisions live in S16, fakes only store)

The following decisions are made by an S16-owned core (pure functions or a small class with no I/O of its own), never by a fake and never by the
page or tool handlers:

- approver independence (approver person id differs from requester person id; two accounts of one person are one person);
- nonce single-use and nonce binding (to the approval session and to the approver person);
- binding of a decision to digest, preview version, change id, scope tuple (including base fingerprint) and expiry;
- token-class check (a read-scope token, a chat/model principal token or a wrong-audience token never reaches an approval or write decision);
- apply-time re-validation (section 5.2).

Fakes provide only persistence (read/write of records), the clock and randomness. Required test (a "permissive store" test): a store fake that
returns whatever it is asked for, accepts any nonce, reports every principal as independent and never marks anything consumed is plugged in; the core
still refuses self-approval, nonce replay, digest/version/expiry mismatch and wrong token class. The observable value that would differ if the core
delegated to the store: those calls would succeed.

### 5.2 Apply-time re-validation and claim-once

At apply the core re-reads and re-checks, in this order, before any apply-port call: kill switch (`KillSubject`/`evaluate`, FACT in `killswitch.py`),
authenticated target base fingerprint equals the approved scope, principal epoch and `epoch_dependencies` unchanged (`EPOCH_CHANGED`), approver still
live (not revoked, not removed; an approval by a since-revoked approver is refused `APPROVAL_VOIDED`), approval not expired (`APPROVAL_EXPIRED`),
digest recomputed from the stored canonical text equals the approved digest (`DIGEST_MISMATCH`), target version unchanged (`STALE_VERSION`).
An approval granted for base X and presented for base Y is refused (`SCOPE_MISMATCH`). Claim is once-only: a test fires N parallel apply calls for one
approved change and asserts exactly one claim and at most one apply-port call (the others get the existing state or a refusal such as
`TICKET_SUPERSEDED`/`CLAIM_EXPIRED`; exact code per the S12 CLAIM transition). Concurrency is exercised with a thread-based harness over the
in-memory store; the real database claim stays NOT_RUN until S13 is accepted.

### 5.3 Issuance ownership

Issuance of `approval_nonce` and `preview_digest` belongs to ApprovalService/ChangeService (S12-APPROVAL-2 binds both inside the digest;
FACT: spec section 3 and `approval_canonical_text`). The approval page only renders what the service returns and submits the decision; it cannot
choose, alter or recompute the nonce, digest or version. The rendered preview is produced from the same canonical bytes the digest covers (the stored
canonical approval text), not from a second serialization.

Port approach (INFERENCE: names are proposals, to be fixed in the design step; each is a Protocol with an in-memory fake, like S15's `ReceiptReader`):

| Port | Purpose | Fake behavior needed |
|---|---|---|
| ChangeServicePort | propose, read state, claim/apply, request rollback proposal; issues `preview_digest`; returns `ErrorCode` refusals | deterministic state machine incl. stale version, digest change, expiry; persistence only for decisions listed in 5.1 |
| ApprovalServicePort | issues the nonce; records an approver decision after the core accepts it | persistence only |
| PrincipalRegistryPort / TargetRegistryPort | principals (requester vs approver, person id), targets (tenant/company/organization/base fingerprint, target class) | revocation and epoch change |
| SecretStorePort | write-credential storage, rotation, revocation | rotate/revoke; records every read |
| TestIdPPort | approver login for lanes only | issues, expires and revokes sessions |
| VerifyPort | adapter over the S15 `verify_receipt` / `VerificationResult` (section 6, E16-3) | fixed outcomes, INCONCLUSIVE |
| Clock, NonceSource | time and randomness | injectable |
| RouteProbePort | resolves a target URL/route and reports address class, redirects, proxy use | public, private, redirecting, proxy-routed cases |
| ToolCallRecorder | records tool-call transcripts for replay | in-memory |

### 5.4 Fidelity of the fakes to S12

A conformance test drives the ChangeService fake and the real S12 transition model (`change/transitions.py`: APPROVE, REJECT, CLAIM, and the caller
matrix in `change/policy.py`) with the same inputs and asserts the same resulting lifecycle/authorization state or refusal code for the S16-relevant
sequences (propose, validate, approve, reject, expire, claim, repeated claim, approval by requester class). A fake that diverges fails the test. The
real S12 model is consumed as a contract only; its acceptance is not asserted.

## 6. Epics and stories

Story IDs are the register's. Each acceptance criterion is a testable assertion; open questions are kept separate (section 10). Scenario IDs (E..)
refer to the plan's scenario table; their plain meaning is given in the coverage map (section 8).

### Epic E16-2 Principal and target registries, secrets (V2-S16-02: who may act, which bases are targets, where credentials live)

Order note: built first because the page and tools resolve identities and targets through it.
Assertions:
1. A principal record distinguishes requester principal from approver, and carries a person id; two accounts of one person resolve to one person
   (I4, E5). Test: approve with a second account of the requester's person, expect refusal `APPROVER_NOT_INDEPENDENT` and zero apply-port calls.
2. A target not in the target registry, or whose class is not allowed on the lane, is refused with `TARGET_REJECTED`; a spoofed environment label in the
   request does not select a target (E16).
3. Credentials are read only through SecretStorePort. No secret value appears in any repository file, log line, error response or recorded artifact
   (E30). Tests: scan of the tracked source tree for secret-shaped literals; capture of logs/errors/artifacts from a failure run.
4. After rotation the old credential is rejected; after revocation the credential and any session derived from it are rejected (E30).
5. A read-scope token cannot perform a write; a write token on the wrong audience or for a foreign principal is rejected (E5, E17 token side). The
   token-class check is made by the S16 core (5.1). The tool-surface part of these assertions is exercised once E16-3 exists (the registry-level
   part can run earlier).
6. Registry unavailability or an unknown/revoked principal fails closed with a safe code.
7. No tool response, log line or recorded artifact contains a nonce, a CSRF token or a session id (scan of captured outputs from success and failure
   runs).
Design-step item (not a criterion): the model-client transport and how a model-client principal is authenticated on the tool surface (Q12).
Open: where the registries persist (Q5); how this relates to the S12 `TrustedIdentityRegistry` (that registry covers signer identities, not
human approvers; INFERENCE).

### Epic E16-1 Approval page (V2-S16-01: server-built immutable preview, nonce, CSRF/CSP/framing, isolated approver sessions)

Assertions:
1. The preview is generated by the server from ledger/change-service data and 1C-side data supplied through ports. A preview rendered from chat text,
   or a chat message claiming approval, changes neither the preview nor the authorization state (E29, spoofed-chat-text case).
2. The preview carries an immutable version and digest (the S12 approval digest, including `preview_digest` and the nonce). Submitting a decision with
   a different version or digest is refused: `DIGEST_MISMATCH` or `STALE_VERSION`; a proposal replaced concurrently makes the older page stale (E4, E39).
3. Nonce: single use. A second submission with the same nonce is refused `APPROVAL_NONCE_INVALID` and does not change authorization state (E39).
4. CSRF: a state-changing request without a valid CSRF token, or with one from another session, is refused (E39).
5. Output encoding: a stored-XSS payload in every preview field (the XSS fixture) is rendered inert; test asserts encoded output for each field and
   the absence of an executable context.
6. Headers and cookie: the page response sets a restrictive CSP and framing denial (`frame-ancestors`/equivalent), and the session cookie is
   httpOnly, SameSite and has a short lifetime (CT12 extras). Exact values are an open question (Q3); the test asserts presence and the chosen values.
7. Session isolation: an approver session cannot be created or used from a chat principal; a chat principal's token on the approval endpoint is
   refused (E29, E39). Cookie scope is separate from any chat/admin cookie.
8. Authorization is checked on every request: unauthorized preview retrieval (no session, wrong person, requester viewing own approval) is refused (E39).
9. Session revocation takes effect on the next request (E39).
10. Re-authentication is required to approve. Posting and amounts above the registered threshold require a second confirmation (CT12, Q3). Preview and decision use the same confirmation rule. Invalid thresholds and stale targets refuse preview before issuing a decision reference.
11. Every approval or refusal appends an audit record; an invalid approval changes no authorization state (E39 invariant).
12. Direct calls to the approval service with the author's token are refused by the service itself, not merely hidden from a tool list (E29, I4).
13. Nonce and digest are issued by ApprovalService/ChangeService (5.3). Test: a page handler given a tampered nonce, digest or version cannot make
    the core accept it; the page cannot alter the digest.
14. The preview shown is rendered from the same canonical bytes the digest covers. Test: the digest recomputed from the rendered source text equals
    the approved digest; a preview field differing from the canonical text is a defect caught by this test.
15. The nonce is bound to the approver session and person: a nonce issued to session S1/person P1 is refused for S2 or P2
    (`APPROVAL_NONCE_INVALID`). The request's approval ticket must match the decision binding before any attempt to consume the reference.
16. The preview page response carries `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
17. Every state-changing POST checks `Origin`/`Referer` against the approval origin; missing or foreign values are refused, in addition to the CSRF token.
18. Nonce, CSRF token and session id never appear in logs, tool responses or audit records (audit carries digests, per spec section 4 item 5).
19. Approval form receive is bounded by bytes and ASGI message count; an empty-chunk flood, malformed event or non-boolean `more_body` is refused
    before `submit_decision` is called.
Open: whether the page is server-rendered HTML only or includes scripts (affects CSP); a11y requirements (Q3, Q4).

### 2026-11-18 bounded approval-page evidence and remaining contracts

The isolated page and core fixtures cover canonical rendered bytes, an independently recomputed displayed digest, script-text escaping, one-use references, cross-session and expiry denials, direct requester denial, revocation before the next preview and decision, cross-origin and CSRF refusal, and bounded body receive. The preview and decision share a confirmation rule. The implementation requires a fresh re-authentication proof whose SHA-256 digest binds the exact decision reference; the core accepts ages from zero through five minutes and refuses missing, stale, future or cross-decision proof before recording APPROVE. The TestIdP issues only synthetic proof after checking its TEST credential authority; REJECT is unchanged. At clean exact HEAD `8ef18c9cfefe5046c4ec4a0fdc7f2fa69dea66b0` (report/document-only commits after code/test commit `9ad472dc28f01af81fb332fa3252c7e4138800ad`), the assigned functional-test-reviewer ran the two named core/page modules: 89 passed in 1.06s, no skips or warnings; `ledger.py verify` recorded PASS. This evidence is synthetic only. End-to-end session cookie issuance and a real authenticated IdP/session adapter remain qualification items.

For the decision audit, distinguish the atomic domain receipt from the audit event. The current change-store contract consumes the reference and nonce with the persisted decision. Extend that atomic operation to include the final-decision audit record before treating it as durable acceptance evidence. A rejected decision attempt needs an append-only refusal record with a safe reason code and a digest-based correlation, while leaving authorization and reference state intact. Neither audit record should serialize raw references, session identifiers, CSRF values or the entire domain receipt. Verify database failure and commit-with-lost-response outcomes against the same atomic decision and audit pair.

For canonical decision POST requests refused before the core, record the refusal at the producing layer. Trust only a closed reason code and server-side time, with no request details. Keep calls that reached the core separate so a refusal or committed outcome produces its existing core audit record exactly once. Database-backed atomicity and an authenticated session adapter remain separate operational evidence.

### Epic E16-3 MCP tools (V2-S16-03: propose, status, apply, verify, rollback_propose; no approve; safe errors)

Assertions:
0. The model-surface allowlist is derived from `change/policy.py` (FACT: `CALLER_MATRIX[REQUESTER]` = PROPOSE, VALIDATE, CLAIM, RELEASE_CLAIM,
   BEGIN_APPLY, READ_STATUS; APPROVE and REJECT belong to the APPROVER class only). Test: the derived set of tool-reachable ledger operations equals
   the set implied by the five tools, and APPROVE/REJECT are in none of them. Mapping of tools to operations is a design-step item: propose =
   PROPOSE/VALIDATE, apply = CLAIM/BEGIN_APPLY, status = READ_STATUS; `verify` and `rollback_propose` have no requester-class operation of their
   own (VERIFY is a RECOVERY_WORKER operation; rollback is a PROPOSE of an admitted kind), so their mapping is open (Q13).
1. `tools/list` returns exactly the five tools and their names equal the set derived in item 0. No tool named or aliased
   approve/approval/authorize/confirm exists (E29).
2. Direct-call assertion: invoking an unlisted name (`approve` and variants) on the tool endpoint returns a safe "unknown tool" error and changes no state.
   A direct call to the approval service with a tool-surface token is refused (not merely absent from the list).
3. Each tool carries a "not read-only" annotation as required by the plan. A test enumerates annotations from the list response.
4. `propose` validates through the S12 proposal parser; the server derives allowed effects; caller-supplied effects, authority or approval status are
   ignored or refused. `apply` without a valid approval for the exact digest refuses (E4, E14).
5. `apply` for POST with only the draft approval, after a draft edit, with an expired grant, or replaying an approval is refused and leaves the
   document unposted in the fake (E14). A POST needs its own approval.
6. `verify` goes through VerifyPort, which is defined against the S15 types (FACT: `erp_mcp_s15/verifier.py`). Input: a document reference, an
   `ExpectedReceipt`, an `OperationShape` (optionally `writer_declared_types`, `writer_unverified_paths`). Output: a `VerificationResult` (status,
   oracle version, label, findings, unverified paths, `typing_checked`). The tool passes the status through unchanged; it never upgrades
   INCONCLUSIVE, MISMATCH, TYPING_DIVERGENCE, PARTIAL_UNVERIFIED or UNSUPPORTED_SHAPE to success, and keeps the label "machine verified, not
   accountant attested".
6a. Only the CREATE_DRAFT one-line receipt shape (`SUPPORTED_SHAPE`) is verifiable. For POST and UNPOST (and any other shape) the verifier returns
    `UNSUPPORTED_SHAPE`. Pass-through test: `verify` for a POST change and for an UNPOST change returns `UNSUPPORTED_SHAPE` unchanged and does not move
    the change to VERIFIED. Consequence recorded (INFERENCE): in S16 a POST or UNPOST change cannot reach VERIFIED through S15; this limits the
    real-world closure of E1/E14 beyond the draft step and is carried as NOT_RUN/limitation.
7. `rollback_propose` only creates a new proposal; it neither applies nor approves. Mapping per prior operation against the S12 freeze (FACT:
   `ChangeKind` has CREATE_DRAFT, UPDATE_DRAFT, POST, UNPOST; the freeze admits CREATE_DRAFT, POST, UNPOST; no hard delete exists):
   - rollback of CREATE_DRAFT: no admitted kind exists (no delete, no mark-for-deletion in v2.0). Result: refusal `ROLLBACK_REFUSED`; no proposal
     is created. Test asserts this refusal case.
   - rollback of POST: a new proposal of kind UNPOST with its own approval; `parent_change_id` = the POST change, `target_ref`, `target_version` and
     `business_state_digest` taken from the current observed state, as `ChangeProposal` requires for non-draft kinds. The UNPOST needs its own
     approval and is never inferred from the POST approval; parent not VERIFIED gives `PARENT_NOT_VERIFIED`.
   - rollback of UNPOST: not mapped by the freeze (a POST requires a verified draft; INFERENCE) and treated as `ROLLBACK_REFUSED` pending Q14.
   - `repair_for` stays `null` in S16; repair kinds are not admitted in the v2.0 slice (INFERENCE from the freeze) and the field is a digest field only.
8. Every refusal uses the single error-code registry (`ErrorCode`) via the safe-error renderer. No raw exception text, stack, secret or internal
   identifier leaves the surface. Test: fault-inject each port and inspect responses.
9. The kill switch (`KillSubject`) is honored: with the switch active, propose/apply are refused with `KILL_SWITCH_ACTIVE`; read-side `status` keeps
   working per the evaluator table.
10. Cross-company: a principal entitled to company A cannot propose, view or apply for company B (E32).
11. Apply-time kill switch: a kill switch turned on after approval and before apply refuses the apply (`KILL_SWITCH_ACTIVE`) with zero apply-port
    calls; the other apply-time re-validations (5.2) are asserted through the `apply` tool: changed base fingerprint, principal epoch change,
    revoked approver, base X approval applied to base Y, and parallel apply calls claiming once.
12. Aggregate MCP argument bounds: nested arguments exceeding the 64 KiB traversal budget, invalid UTF-8 strings, non-finite floats, excessive
    depth/node count, or forbidden identity/effect keys are rejected with a safe schema error before any service method is called.
13. Apply-time requester revalidation refuses malformed principal-registry results (wrong record type, non-boolean revocation state, empty or
    mismatched person identity, invalid/stale epoch, or non-boolean dependency-current result) before claim or apply-port execution.
14. The explicit `register_tool` adapter publishes exactly the five tool names and their complete JSON Schemas from the immutable manifest;
    transport context is passed separately and absent from `inputSchema`. Signature-derived adapters that cannot preserve the exact schema or reject
    undeclared arguments are refused before partial registration. Full binding to the gateway's high-level MCPServer is not established by this task;
    it requires a separate low-level integration design that preserves authenticated context. The focused adapter contract passed 15 tests on
    2026-11-15; this is synthetic adapter evidence, not gateway/runtime acceptance.
Resolved for S16 on 2026-11-18: the immutable tool manifest fixes tool schemas, and all five change tools—including read-only `status` and `verify`—remain private-only. No public/tunnel change-tool exposure is implemented or claimed.

### Epic E16-4 Private-network exposure (V2-S16-04: private-network-only writes, proxy/redirect/SSRF check)

Assertions:
1. The write-capable tool set and the approval service are registered only on a private-listener configuration object. A public/tunnel
   configuration object yields a surface with no change tools (E16).
2. The write port target check refuses a target outside the allowed lanes (staging/production host, public address) by itself, independent of the
   request label (E16).
3. Requests carrying `Forwarded`, `X-Real-IP` or `X-Forwarded-*` headers, with multiple or mismatched `Host`, are refused on the private surface
   (pattern of `private_ingress.py`; INFERENCE as to reuse).
4. RouteProbePort cases: a target that redirects (3xx) to a public address, a proxy-routed target, a hostname resolving to a public address, and a
   DNS answer changing between check and use are each refused (SSRF/redirect/proxy bypass). Redirects are never followed on write calls.
5. A route check enumerates all declared routes and asserts no public or indirect route reaches a write tool.
6. All checks run over fakes; no listener, tunnel or real network call is made by the tests.
7. Positive authentication on every request: the private listener requires a valid approver session (approval service) or a write-audience token
   (tool surface) on every request. Network origin alone never authenticates (FACT: the `private_ingress.py` loopback check is an address check;
   it is not sufficient as authentication). Test: a request from a loopback origin with a rewritten `Host`, no proxy headers and no credential is
   refused; the same request with a valid credential but a foreign Origin/Referer on an approval POST is refused.
8. A `CHAT_WRITE` principal with missing/empty identity fields, invalid epoch/MFA types, a non-TEST lane, or malformed/non-TEST scope is refused
   before the downstream MCP tool app is called.
Resolved for this sprint on 2026-11-18: no S16 change tool is exposed on a public tunnel; the default allowed network is loopback, with additional private ranges only when explicitly configured in the private listener object. The listener factory still does not bind or start a network listener.

### Epic E16-5 Recorded tool-call replay (V2-S16-05: ChatGPT and Claude transcripts replayed; real runs NOT_RUN)

Assertions:
1. Recorded tool-call transcripts for ChatGPT-shaped and Claude-shaped clients (list, propose, status, apply, verify, rollback_propose) replay
   through the tool surface and produce the expected responses; a transcript step calling `approve` is refused.
2. Each transcript fixture is labelled with its provenance: observed from a real client, or hand-authored in the client's request shape. Real-client
   observation is NOT_RUN unless an evidence file exists (Q8). Hand-authored fixtures are never described as client proof.
3. The full approval journey runs end to end over fakes in a single test: propose, preview page, approver login (test IdP), approval, apply, verify.
4. Spoofed chat text ("approved", "the approver said yes") embedded in a replayed transcript changes neither preview nor state.
5. Replay is deterministic: the same transcript against the same fake state gives the same responses (clock and nonce injected).
Plain limitation: this epic proves surface behavior against recorded shapes only; it says nothing about connector behavior, authentication
handshakes, timeouts or schema caching of any real client.

## 7. Deferred and blocked scenarios

- E2 (contract update): DEFERRED, outside v2.0 scope (section 1.1 item 2). Recorded NOT_RUN with this reason; not passed.
- E1 (invoice to draft to verify to post to A-B reconciliation): S16 covers the approval-path legs over fakes (draft approval, separate post
  approval). The real-1C post step and the A-B comparison stay NOT_RUN/DEFERRED as in S15 (no post/unpost evidence on a clone).
- E17 (write token on the v1 gateway, 1C-side denial): the token and audience parts are covered over fakes in E16-2; the part "denied by 1C itself" is
  NOT_RUN (needs a real least-privilege account).
- Real client runs, real IdP, deployment, UAT: NOT_RUN or out of scope as listed in section 5.

## 8. Requirements-derived test coverage map

Status of every row at the time of this plan: NOT_WRITTEN / NOT_RUN. "Fake" = in-memory ports, no network, no 1C.

| Req | Scenario (plain meaning) | Stories | Assertion | Data source |
|---|---|---|---|---|
| I3, I4 | E39 approval page attacks: direct API calls, CSRF, stale page, concurrent proposal replacement, session revocation, stored XSS in a preview field, unauthorized preview retrieval, nonce replay | 01, 02 | each invalid approval fails; authorization state unchanged | fakes; XSS fixture |
| I3, I4 | Valid approval decision POST returns the bound success response after service persistence | 01 | the canonical ticket UUID is available on POST as well as GET; success response is emitted only for a matching `ApprovalDecision` | fake ASGI receive/service |
| I4 | Service returns an unknown/malformed refusal code while a custom error renderer is configured | 03 | renderer receives only a registered `ErrorCode`; unknown values become `AUDIT_UNAVAILABLE`; response contains no raw service value | service fake and capturing renderer |
| I4 | E39 CT12 extras: framing denial, cookie flags, re-authentication, second confirmation for post/large amounts | 01 | headers/flags present; extra confirmation enforced | fakes |
| I4 | E29 author session calls an approval tool; spoofed "approved" chat text; direct approval-service call with the author's token | 01, 03 | no approve tool; service refuses direct call; chat text changes nothing | fakes |
| I1, I4 | E5 self-approval (also via second account of same person); read token attempts a write | 02, 03 | refused with safe code; zero apply-port calls | fakes |
| I3 | E4 approver rejects, approval expired, digest changed after approval, stale-version direct call | 01, 03 | zero apply calls; approver rejection ends in lifecycle `REJECTED` (a lifecycle outcome, not an error code); refusal codes `APPROVAL_EXPIRED`, `DIGEST_MISMATCH`, `STALE_VERSION` (all verified in `change/errors.py`) | fakes; conformance to S12 REJECT/APPROVE (5.4) |
| I4 | Decision core independence: permissive store | 01, 02, 03 | core refuses self-approval, replay, digest/version/expiry mismatch, wrong token class even when the store allows all | permissive-store fake (5.1) |
| I3, I4, I6 | Apply-time re-validation and claim-once: fingerprint, epoch, approver liveness, base X vs Y, parallel apply, kill switch | 03 | each refused with zero apply calls; exactly one claim under parallel calls | fakes, thread harness (5.2) |
| I3, I4, I6 | Decision/apply-time requester registry returns malformed principal/lane/role/revocation/person/epoch/dependency state | 03 | safe refusal before decision persistence, claim, or apply; zero apply-port calls | malformed principal-registry fake |
| I3, I4, I6 | Target/principal registry returns malformed `allowed`, independence, or epoch-dependency result; claim store returns a malformed claim token/error | 02, 03 | exact typed positive values required; refuse before approval consumption or apply-port call; release a claim if refusal occurs before `BEGIN_APPLY` | malformed registry/store fakes |
| I3, I4, I6 | Change store read raises or returns a malformed/mismatched receipt before claim, during repeat handling, after `claim_once`, or after `BEGIN_APPLY` persistence | 03 | fixed refusal and never call the apply port; release a known claim only before `BEGIN_APPLY`; after `BEGIN_APPLY`, retain the claim and durable in-progress anchor for recovery | failure-injecting store fake |
| I3, I4, I6 | Approval, snapshot, or requester expiry is observed after durable `BEGIN_APPLY` | 03 | return `APPROVAL_EXPIRED`, retain the consumed claim and `APPLYING` anchor for recovery, and do not issue the apply call or attempt the S12 `EXPIRE` transition (which is only valid before execution starts) | clock-advancing store fake and zero-call apply-port assertion |
| I3, I4, I6 | Apply port returns an exact `ApplyReceipt` class with a mismatched change ID or malformed status, correlation ID, or document reference | 03 | return fixed `APPLY_UNKNOWN`; do not persist or expose the malformed result because the call may already have crossed the apply boundary | malformed apply-port fake |
| I3, I4, I6 | Apply-result persistence is a no-op, raises, or reads back a mismatched `DomainReceipt` after the apply port may have executed | 03 | return fixed `APPLY_UNKNOWN`; do not report success or establish a verification anchor, and never retry the apply port | failure-injecting apply-store fake |
| I3, I4, CT12 | Approval authenticator returns malformed approver identity/role/epoch/scope, or POST returns a malformed/unbound `ApprovalDecision` | 01 | refuse malformed sessions before service dispatch; show success only for an exact, self-consistent decision bound to ticket, requested action, approver, session, scope, digest shapes, and live expiry | malformed authenticator/service fakes |
| I3, I4 | Status store read raises, returns a non-receipt, or receipt validation raises/returns a malformed refusal code | 03 | fixed `AUDIT_UNAVAILABLE`; never serialize or disclose the malformed stored value | failure-injecting status store fake |
| I3, I4, I6 | Expire/verify store read raises or returns a non-receipt; expiration read-back fails after save | 03 | fixed `AUDIT_UNAVAILABLE`; absent record remains `REF_OUT_OF_SCOPE`; no malformed receipt is returned and a saved expiration transition is not rolled back | failure-injecting store fake |
| I3, I4, I6 | Expiration or pre-`BEGIN_APPLY` release read-back returns a different receipt with a matching lifecycle record | 03 | fixed `AUDIT_UNAVAILABLE`; preserve original receipt identity and do not report the transition as successful | mismatched read-back store fake |
| I3, I4 | Direct verify call carries a non-UUID change ID or non-string document reference | 03 | fixed `SCHEMA_INVALID` before any store read or verifier call | malformed verify request fake |
| I12, I14 | Private listener positive authentication; loopback origin with rewritten Host and no credential | 04 | refused; Origin/Referer check on approval POSTs | fakes |
| I12, I14 | Private ingress receives malformed or oversized decimal `Content-Length` text | 04 | malformed values receive a fixed refusal; oversized values receive 413 before downstream dispatch and without unbounded integer parsing | fake ASGI scope/receive and downstream-call counter |
| I12, I14 | Private ingress origin explicitly configures port `0` | 04 | reject configuration; do not treat the invalid explicit port as the default HTTPS port | config-construction case |
| I12, I14 | Private ingress receives a non-dict ASGI scope object | 04 | fixed schema refusal before reading scope fields, authentication, or downstream dispatch | malformed ASGI scope fixture |
| I4 | No nonce, CSRF token or session id in responses/logs; no-store and no-referrer on the preview page | 01, 02 | scans and header assertions pass | captured outputs |
| I4 | Approval form ASGI framing: empty-message flood, malformed event, invalid `more_body`, byte overflow including one oversized chunk | 01 | bounded safe refusal before the oversized chunk is appended; zero `submit_decision` calls | fake ASGI receive/service |
| I4 | Approval form carries a malformed or out-of-bounds `decision_ref` or a non-canonical CSRF token | 01 | fixed schema refusal before `submit_decision`; zero approval-service calls | malformed form/service-call counter |
| I4 | malformed ASGI scope headers container (for example `headers=None`) or non-byte header entries | 01 | fixed schema refusal; no exception escapes and no approval service call occurs | malformed ASGI scope fixture |
| I4 | ASGI app receives a non-dict scope object | 01 | fixed schema refusal before reading scope fields or calling the authenticator/service | malformed ASGI scope fixture |
| I3, I4 | Approval service returns an oversized/control-bearing or invalid-Unicode confirmation phrase, or display metadata contains an unpaired surrogate | 01 | invalid confirmation phrase is refused; unsafe display metadata becomes a fixed placeholder; no HTML encoding crash or approval decision submission | malformed `DecisionPage` service fake |
| plan S16 | verify pass-through incl. POST/UNPOST `UNSUPPORTED_SHAPE`; rollback_propose per prior operation | 03 | status unchanged; CREATE_DRAFT rollback `ROLLBACK_REFUSED`; POST rollback = UNPOST proposal | S15 verifier (real code, fake reader); fakes |
| fidelity | fakes versus real S12 transitions APPROVE, REJECT, CLAIM | 01, 03 | same state or refusal code | real S12 model, fakes (5.4) |
| I6 | E14 post with only the draft approval; draft edit after post approval; expired grant; approval replay | 03, 01 | refused; document stays unposted in the fake | fakes |
| I12, I14 | E16 write port aimed outside allowed lanes; spoofed environment label; write endpoint on public tunnel or behind proxy | 04, 02 | port refuses; no public/indirect route (route check incl. proxy/redirect) | fakes, RouteProbePort |
| I13 | E30 secret store, logs, errors, artifacts, rotation, revocation, repository scan | 02 | no secrets in repo/logs/errors; old credentials fail | tracked-tree scan; fault-run captures |
| I3, I4 | E32 cross-company: principal of company A against company B | 03, 02 | refused for propose, view, apply | fakes |
| I1, I14 | E17 token side: wrong audience, read token on write service, foreign principal | 02, 03 | rejected; 1C-side denial NOT_RUN | fakes |
| I6, I11 | E1 approval-path legs (draft approval, separate post approval) | 01, 03, 05 | full journey over fakes; real post NOT_RUN | fakes |
| I3, I7, I11 | E2 contract update | - | DEFERRED (section 7) | none |
| map S16 row | tools/list plus direct-call assertion | 03 | exactly five tools; unlisted name refused | fakes |
| plan S16 | aggregate argument validation: oversized nested values, escape-heavy strings, invalid Unicode, non-finite numbers and forbidden keys | 03 | bounded representation before rendering; safe schema error; zero service calls | fakes |
| map S16 row | full approval journey and spoofed-chat-text negative case | 01, 03, 05 | journey passes; spoofed text no effect | fakes, transcripts |
| plan S16 | tool annotations "not read-only" | 03 | annotations present on the list | fakes |
| plan S16 | safe errors from the single code registry | 03 | every refusal is an `ErrorCode`; no internals leaked | fault injection on ports |
| plan S16 | propose/status/apply service returns malformed public result fields | 03 | serializer rejects malformed types, unbounded/control text, invalid digest/version/expiry; fixed `AUDIT_UNAVAILABLE` and no malformed value in the tool response | malformed service-result fakes |
| plan S16 | receipt/target validators throw or return an unregistered refusal during approval/apply, including after durable `BEGIN_APPLY` | 01, 03 | fixed registered refusal; after `BEGIN_APPLY`, retain the claim/anchor and make zero apply-port calls | fault-injected validator ports |
| plan S16 | approval store read-back is missing, malformed, identity-mismatched, or differs in decision/S12 transition after nonce consumption | 01, 03 | return `AUDIT_UNAVAILABLE`; do not report success or update process-local anchors; leave durable state for reconciliation | fault-injected decision store |
| plan S16 | recorded replay for ChatGPT and Claude shapes | 05 | replay matches expected; provenance labelled; real run NOT_RUN | transcript fixtures |
| plan S16 | private network, proxy/redirect/SSRF | 04 | each bypass case refused | fakes, RouteProbePort |
| plan S16 | kill switch honored by tools | 03 | propose/apply refused when active | fake switch reading |

Routing per the project workflow: code first; then `functional-test-reviewer` and `e2e-runner` write and run the complete set per epic and once
more at the end; the coordinator runs no tests. No mutation runs and no deliberately broken implementations: for each negative case the test notes
the observable value that would differ if the guard were off.

## 9. Definition of Done

1. Stories V2-S16-01..05 have code over ports and fakes; per-epic functional tests are written and fully run by the test-owning agents, with exact
   head, commands and results recorded.
2. Every E39 attack case and every CT12 extra fails closed without changing authorization state; the XSS fixture is inert in every preview field.
3. `tools/list` shows exactly propose/status/apply/verify/rollback_propose; the approve action is absent and direct calls to it are refused by the
   service; spoofed chat text changes neither preview nor state.
4. Private-network checks pass for proxy, redirect, public-address and tunnel cases; no listener or real network call exists in the tests.
5. Secret handling (E30) passes on the fake store and the tracked-tree scan.
6. The full approval journey passes end to end over fakes; replay fixtures carry provenance labels.
7. E2 is DEFERRED; the real-1C legs of E1 and E17, real client runs, real IdP, UAT and deployment are recorded NOT_RUN or out of scope, not passed.
8. Evidence separates fake-level results from NOT_RUN items. No production-readiness claim; nothing is described as wired or deployed.
9. Reviews on the exact final diff leave no BLOCKER/MAJOR: security-reviewer, architect, code-reviewer, product-ux-reviewer and a11y-architect
   (page states), silent-failure-hunter (false-approval and false-success paths), reliability-reviewer (fail-closed behavior under port failure).
   GPT-PM APPROVE on the exact head before push/PR.
10. One PR; each commit carries a change record and a lessons-log entry.
11. Writer stays UNQUALIFIED and disabled; production binding set stays empty; no gateway wiring.
12. The permissive-store test, the apply-time re-validation and parallel-claim tests, the positive-authentication test and the fake-versus-S12
    conformance test (sections 5.1, 5.2, 5.4, E16-4) pass.

## 10. Risks

| Risk | Effect | Mitigation in plan |
|---|---|---|
| Fakes diverge from the real S12/S13 behavior (not accepted) | S16 passes against a wrong contract | consume real value types where they exist; record fake-based status; re-run when S12/S13 are accepted |
| "Hidden, not enforced" approve | tool list looks clean while the service accepts model tokens | direct-call assertions on the service (E29), not only on `tools/list` |
| Session isolation weaker than CT12 asks | low-trust principal controls an approver session | separate cookie scope and store; explicit cross-use tests |
| Hand-authored transcripts mistaken for client proof | false confidence about ChatGPT/Claude | mandatory provenance label; real runs NOT_RUN |
| Preview built from caller-supplied data | spoofed content approved | preview built only from ledger/ports; spoof test |
| Scope creep into deployment or IdP | breaks the no-deployment constraint | non-goals in section 5 |

## 11. Rollout, rollback and migration

- Rollout: test code and library modules only; nothing is registered anywhere. No migration, no schema change.
- Rollback: reverting the sprint commits restores the S15 state. Because nothing is wired, no runtime rollback step exists.
- If a later change persists registries or nonces, it follows expand/contract and is a separate decision (Q5).

## 12. Open questions (each with a recommended default)

| # | Question | Recommended default |
|---|---|---|
| Q1 | Which scenario list governs: PLAN_V2 exit (E1, E2, E4, E5, E17, E29, E32, E39) or map (E39, E29, E5, E4, E16, E14, E30, E32)? | Union of both, with E2 DEFERRED and the 1C-side parts of E1/E17 NOT_RUN. |
| Q2 | Are `status` and `verify` write tools for exposure purposes (D3), and are they annotated read-only? | RESOLVED 2026-11-18: all five change tools are private-network-only; `status`/`verify` are read-only in behavior but not exposed publicly in this sprint. |
| Q3 | Concrete values: session lifetime, nonce lifetime, CSP policy text, cookie attributes, amount threshold for second confirmation. | Choose the strictest practical values in the design step and keep them as named constants asserted by tests; the amount threshold stays a registry value, not hard-coded. |
| Q4 | Is the page pure server-rendered HTML (no scripts)? | Yes: no inline or external scripts, `script-src 'none'`, which also simplifies CSP and a11y review. |
| Q5 | Where do principal/target registries and nonce state persist? | In-memory fakes in S16; persistence decided after S13 is accepted. |
| Q6 | Reuse `admin_session.py`/`workbench_session.py` for approver sessions? | Do not share a store; reuse only patterns. Approver sessions use a separate store and cookie scope. |
| Q7 | Definition of "private network": loopback only, or RFC 1918/ULA ranges? | RESOLVED 2026-11-18: loopback by default; allow only explicitly configured private ranges, as in `private_ingress.py`. |
| Q8 | Is any recorded real-client transcript available? | No: ship hand-authored shape fixtures labelled "not observed"; real runs NOT_RUN. |
| Q9 | New package name and location? | `src/erp_mcp_s16/`, mirroring `src/erp_mcp_s15/`; no import from the writer. |
| Q10 | Is the S15 verifier accepted enough to be the `verify` backend? | Use it only through VerifyPort with a fake; claim nothing about real verification. |
| Q12 | Model-client transport and how a model-client principal is authenticated on the tool surface (design-step item). | Decide in the design step before code; the core accepts only a typed, already-authenticated principal and token class, and never trusts a principal name in a request body. |
| Q13 | Mapping of `verify` and `rollback_propose` to ledger operations (requester class has no VERIFY and no rollback operation). | `verify` = a read through VerifyPort plus READ_STATUS; `rollback_propose` = PROPOSE of an admitted kind; confirm with the S12 owners. |
| Q14 | Rollback of an UNPOST. | Refuse with `ROLLBACK_REFUSED` in v2.0. |

Backlog note (not an open question, not a blocker): the production IdP choice and the approver identities are operator-owned items. They stay in
the closure backlog; S16 uses the test IdP only.

UNKNOWN items carried: S12 and S13 formal acceptance state; S15 acceptance state; production IdP and approver identities; fixture and owner for any
real-client observation; the value of any numeric limit in Q3.

## 14. Review resolutions (rev 2; finding -> change)

Security review:
1. MAJOR, decision logic could live in fakes -> section 5.1 (S16-owned core; fakes only persistence/clock/randomness; permissive-store test); DoD item 12.
2. MAJOR, apply-time re-validation, claim-once, preview/digest bytes, base X vs Y -> section 5.2, 5.3 (preview from the canonical bytes), E16-1
   item 14, E16-3 item 11; coverage rows added.
3. MAJOR, private listener auth and Origin/Referer -> E16-4 item 7, E16-1 item 17.
4. MINOR, secrets in output, caching and referrer headers, nonce binding -> E16-2 item 7, E16-1 items 15, 16, 18.
5. MINOR, transport and principal authentication -> design-step item in E16-2 and open question Q12.

Architecture review:
1. MAJOR, VerifyPort against `VerificationResult`, POST/UNPOST `UNSUPPORTED_SHAPE` -> E16-3 items 6 and 6a (FACT: `verify_receipt` returns
   `UNSUPPORTED_SHAPE` unless the shape is the one-line CREATE_DRAFT receipt).
2. MAJOR, `rollback_propose` mapping -> E16-3 item 7; open questions Q13, Q14.
3. MAJOR, issuance of nonce and `preview_digest` -> section 5.3; E16-1 item 13.
4. MAJOR, E4 row used REJECTED as a code -> coverage row corrected: REJECTED is a lifecycle outcome; `APPROVAL_EXPIRED`, `DIGEST_MISMATCH`,
   `STALE_VERSION` are verified `ErrorCode` members.
5. Allowlist from `policy.py` -> E16-3 item 0.
6. Token assertions depend on E16-3 -> E16-2 item 5.
7. Apply-time kill switch -> section 5.2 and E16-3 item 11.
Also: fakes-versus-S12 conformance check -> section 5.4; discrepancies 3 and 4 demoted to notes in 1.1; Q11 moved to a backlog note in section 12.

## 13. Reviewers for this document

- architect (port boundaries, independence from the writer, fallback honesty).
- security-reviewer (CT12 coverage, approve-not-on-surface, private-network and secrets assertions).
- functional-test-reviewer and e2e-runner (testability of each assertion and the coverage map).
- product-ux-reviewer and a11y-architect (approval page states and requirements, no UAT claim).
- silent-failure-hunter (false-approval and false-success paths).
- doc-updater (consistency with the register and map after S12/S15 acceptance).
