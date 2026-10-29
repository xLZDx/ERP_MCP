# Change record 404 — S16 isolated approval and decision core

**Date:** 2026-10-29  
**Scope:** fake-backed ERP_MCP S16 library core only  
**Status:** source implemented; acceptance and runtime evidence `NOT_RUN`  
**Story trace:** S2.1–S2.3 / REQ-007–REQ-013, REQ-016; S16 rev. 2 §§2, 5.1–5.4  
**Implementation owner:** Codex  
**Independent test owner:** `functional-test-reviewer` and `e2e-runner`, after all sprint source is complete  
**Final exact-head approval owner:** GPT-PM, after test evidence and specialist review

## What changed

Added the isolated `src/erp_mcp_s16/` package in the core ownership slice: typed contracts,
policy orchestration, proposal/approval services, registries and in-memory fakes. Added no
gateway registration, writer import, route binding, listener, database schema, persistence adapter,
COM path, or production wiring. S16 depends on S12 proposal/error/policy/transition contracts and
S15 verification value types only.

The package provides five service operations: `propose`, `status`, `apply`, `verify`, and
`rollback_propose`. Approval is a separate `ApprovalService` flow and is not a model operation.
Authenticated principals carry a typed token class, role set, person identity, scope, epoch,
expiry, and an MFA assertion for approver sessions. The fake TestIdP issues isolated approver
sessions with 15-minute idle and absolute limits; raw session CSRF material remains server-side.

`ChangeService` generates the canonical preview once, computes its SHA-256 digest, then builds the
S12 approval envelope with the raw nonce and that digest. The preview byte sequence excludes the
nonce and digest and is stored unchanged. Only the nonce digest is stored separately. An opaque
decision reference binds the preview, scope, version, person, principal, session, CSRF verifier,
nonce digest, and expiry. Decision POST consumption and persistence of the decision plus resulting
S12 record use one atomic store operation. The core independently rejects self-approval and
same-person aliases, stale or mismatched bindings, replay, wrong token class, expired or revoked
principals, and invalid digest/version/scope state.

Apply re-reads the kill switch, target fingerprint and version, requester epoch dependencies,
approver role/revocation/epoch, approval expiry, canonical preview and S12 approval digest before
claiming. It runs the S12 `CLAIM` transition before calling `claim_once`; a process-local lock and
core-owned per-change latch permit at most one apply-port call across threads using one core.
An apply-port exception is returned as `APPLY_UNKNOWN` and is not retried. The in-memory store's
claim is an atomic compare-and-set for same-process fake behavior; it is not database or
cross-process evidence.

S12 `apply_transition` and caller policy are invoked for `PROPOSE`, `VALIDATE`, `APPROVE`,
`REJECT`, `EXPIRE`, and `CLAIM`. S12 lifecycle and authorization dimensions are retained on each
domain receipt. The fake proposal adapter requires target-fixture evidence for allowed operation
shape and free business key; it does not treat unknown key state as free. `verify` derives the
expected S15 receipt values and operation shape from the stored proposal, ignores caller-supplied
expected values and shape, and returns the S15 result unchanged. POST/UNPOST therefore stay
`UNSUPPORTED_SHAPE` through the S15 port. Rollback proposals are restricted to a verified POST,
produce a separate UNPOST proposal, and do not approve or apply it.

## Contracts and public service signatures

The UI-owned page/tool/ingress modules integrate against these core-owned APIs:

```python
ChangeService(core, store, proposal_port, nonce_source, clock)
ChangeService.propose(requester, raw_request, *, now=None) -> Result[PreviewSnapshot]
ChangeService.status(requester, change_id) -> Result[DomainReceipt]
ChangeService.apply(requester, change_id, *, now=None) -> Result[ApplyReceipt]
ChangeService.verify(requester, request: VerifyRequest) -> Result[VerificationResult]
ChangeService.rollback_propose(requester, change_id, *, now=None) -> Result[PreviewSnapshot]

ApprovalService(core, store, nonce_source, clock, *, origin)
ApprovalService.open_preview(approver, session, ticket, *, now=None) -> Result[DecisionPage]
ApprovalService.submit_decision(
    approver, session, decision_ref, decision, *, confirmation_text, origin, referer, now=None
) -> Result[ApprovalDecision]
```

`DecisionPage` returns only the opaque reference, exact stored preview bytes, their digest, expiry,
and service-derived typed-confirmation requirements. The confirmation phrase is `CONFIRM CHANGE`
for a POST or an amount-bearing draft whose summed line amount plus VAT exceeds its registered
threshold. A missing threshold for an amount-bearing draft fails closed. The core recomputes this
policy before accepting an approval; a rejected decision does not require the typed phrase.

## Decisions and boundaries

- S16 has in-memory injected state only. No production store or persistence semantics are claimed.
- Approver sessions use a 15-minute idle and absolute limit; approval nonce lifetime is five minutes.
- Session-bound CSRF uses a private server-side verifier; the browser receives only the opaque,
  single-use decision reference. Approval POST requires exact configured origin and same-origin
  referer validation in the service, in addition to core binding validation.
- A GET may persist issuance of an expiring decision-reference binding so the page can render. It
  does not consume the nonce, save a decision, or change S12 lifecycle/authorization.
- `verify` treats the caller's expected values and shape as untrusted. Expected values and operation
  shape derive from the stored proposal; the document reference must match the server-recorded
  apply receipt reference or proposal target reference.
- A required amount threshold is never replaced by a permissive default.
- The target fixture must explicitly mark the business key free and the operation shape qualified
  before fake proposal validation succeeds.
- Cross-process claim atomicity, database transaction equivalence, real IdP/session identity,
  real target observations, real write outcomes, and formal S12/S13/S15 acceptance remain outside
  the evidence provided by this fake-backed source slice.

## Verification and remaining acceptance

| Item | State | Evidence / completed work | Remaining acceptance | Dependency / blocker | Next action and owner |
|---|---|---|---|---|---|
| S2.1 core decisions | Implemented in source; unverified | S16 core contains independent-person, binding, replay, expiry, digest, token, apply revalidation, S12 transition, and one-claim orchestration paths | Falsifying functional tests, including permissive persistence and concurrent apply | Test phase intentionally not started until all sprint source is complete | `functional-test-reviewer` authors/runs mapped cases; Codex fixes valid findings |
| S2.2 approval channel | Implemented in source; unverified | Separate service, isolated session type, opaque reference, private CSRF verifier, typed confirmation, exact origin/referer checks | Browser boundary tests, session/replay/encoding/header evidence | UI-owned `approval_page.py` integration and test-agent evidence | UI implementer completes integration; `e2e-runner` owns browser scenarios |
| S2.3 tool operations | Core service APIs implemented; unverified | Exactly five service operations; safe `ErrorCode` results; S15 passthrough; rollback restriction | Exact MCP manifest/annotations and end-to-end dispatch evidence | UI-owned `tools.py` integration and test-agent evidence | UI implementer completes integration; `functional-test-reviewer` maps tests |
| S12 conformance | Calls added; not proven | Calls to `apply_transition` and `authorize_operation` for S16-relevant transitions | Compare exact state/refusal sequences, including expiry and repeated claim | Required tests not run; S12 acceptance itself is not promoted | Functional test agents run conformance scenarios; Codex records exact results |
| In-memory claim atomicity | Implemented in fake/core; not runtime-proven | Lock-backed fake CAS plus core lock/latch and terminal handling after apply exception | Threaded N-contender test and exact ApplyPort count | Test phase not started | `functional-test-reviewer` runs mapped concurrency case |
| Runtime / production qualification | `NOT_RUN` | No listener, gateway binding, database store, real IdP, production writer or COM path added | Separate authorized operational evidence and accepted upstream contracts | Explicitly outside this S16 slice | Codex owns later evidence reconciliation; GPT-PM adjudicates any contract conflict |

No tests, checks, builds, lint, runtime probes, or migrations were run by this implementation
worker. No claim of runtime success or S16 acceptance is made.

## Ordered next steps

1. Codex completes the remaining S16 UI-owned source and confirms the exact API integration.
2. `functional-test-reviewer` and `e2e-runner` author and execute the REQ-007–REQ-013 mapped tests
   after all S16 sprint coding is complete; record exact head, commands, outcomes, and `NOT_RUN`
   dependencies.
3. Codex fixes valid findings and requests relevant specialist review on the resulting exact diff.
4. GPT-PM reviews the final exact head with test/reviewer evidence before any push or pull request.
