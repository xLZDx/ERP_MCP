# Phase 2 Finisher Functional Test Plan

Sprint: `beea27520b33`  
Scope: `docs/sdlc/requirements.md` REQ-001–REQ-017; `docs/sdlc/backlog.md` S1.1–S3.3; S16 rev. 2 in `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`.  
Status: planned only. Tests are not authored or run by this document. Functional and E2E test owners start only after all in-scope coding is complete.

## Test ownership and execution boundary

`functional-test-reviewer` authors and runs focused unit/integration tests; `e2e-runner` owns only scenarios requiring a real integration boundary. Both record exact final commit, commands, outcomes, skips, and limitations, mapped to stories and acceptance criteria. Codex checks traceability and evidence. No test/check/build/full suite is authorized by this plan. Do not claim implementation or runtime proof from this plan.

Use the repository virtual environment and project root (`D:\Repo\ERP_MCP`). Examples below are proposed commands, to run only after coding is complete:

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m pytest -q tests\phase2\test_s12_sql_code_parity.py
.\.venv\Scripts\python.exe -m pytest -q tests\phase2\test_s12_period_producer.py tests\phase2\test_s12_budget_producer.py tests\phase2\test_s13_inflight_status.py
.\.venv\Scripts\python.exe -m pytest -q tests\phase2\test_s16_approval_core.py tests\phase2\test_s16_approval_page.py tests\phase2\test_s16_tools.py tests\phase2\test_s16_private_ingress.py tests\phase2\test_s16_replay.py
```

The SQL parity test path above is a required named test. The other filenames are proposed focused modules; test owners may map them to the actual added/existing module names while preserving every assertion below. Use the approved disposable PostgreSQL/E2E setup for the slow SQL/E2E set and report dependency/setup failure as `NOT_RUN` with its exact observed error. Do not substitute mocked SQL for migration behavior. Do not run production or real-base writes.

## Traceability matrix

| Requirement / story / AC | Falsifiable scenario and required observation | Cheapest proving layer / evidence |
|---|---|---|
| REQ-001 / S1.1 AC-1, AC-3 | Apply migration 028 to disposable PostgreSQL, compare normalized SQL and canonical Python registries (39 entries), assert exact set equality and presence of `PERIOD_CLOSED` and `GRANT_EXHAUSTED`; report Python-only cases explicitly rather than silently excluding them. | SQL integration plus Python registry comparison; `tests/phase2/test_s12_sql_code_parity.py`. Preserve DB/version, command, diff on mismatch, and limitations. |
| REQ-001 / S1.1 AC-2 | Through the real SQL budget path, an exhausted grant plus positive amount returns `GRANT_EXHAUSTED`; non-exhaustion budget refusal retains `BUDGET_EXCEEDED`. Include zero/non-positive request and available-budget boundaries if the contract accepts them, proving no exhaustion misclassification. | Disposable PostgreSQL integration; assert outward code and relevant persisted state. |
| REQ-002 / S1.2 AC-1, AC-2 | Use a producer fed by an authenticated observed period: open observation yields positive open evidence; closed yields `PERIOD_CLOSED`. Independently inject missing, contradictory, stale, unauthenticated, malformed/unknown observation; none can authorize apply. Verify a later valid observation does not retroactively validate a stale one. | Producer/eligibility integration with realistic observation adapter boundary; fakes only for deterministic faults, not as proof of real-data producer qualification. Capture source identity class and observation result without secrets/business payload. |
| REQ-003 / S1.2 AC-3 | A real producer maps observed remaining amount zero plus positive request to `BudgetCheck.EXHAUSTED`; positive remaining amount permits only within budget; other refusal causes preserve their distinct S12 mapping. Test exact boundary (remaining equals request) per contract and negative/zero request behavior. | Producer integration at its observation/decision seam; assert resulting S12 input and final refusal. Qualification claim requires real-data path evidence, not a DTO fixture. |
| REQ-004 / S1.3 AC-1, AC-2 | Seed ledger/service with multiple in-flight and terminal changes; list returns the currently in-flight identities only, and status for each returned ID reflects a state transition made in the underlying service. Unknown ID is safe and does not return a fixture/default status. | Service/ledger integration. Assert ordering only if contract guarantees it; assert source-state changes are reflected. |
| REQ-005 / S3.1 AC-1–AC-3 | At final head execute the required slow SQL/E2E selection and S15 selection named by S12/S13 prerequisite and S15 plan. Link each command/result to the applicable story/gate; record skipped cases and reasons, exact head and environment. | Test-agent run record. These are selected acceptance suites, not a requirement to run the whole repository suite. If the configured disposable DB/E2E dependency is unavailable, record `NOT_RUN` and exact error. |
| REQ-006 / S3.3 AC-1–AC-3 | Evidence reconciliation test/review checks each S12/S13/S15 status against current manifest and exact-head results; absent evidence leaves status unaccepted/unknown. S17–S19 remain deferred absent approved scope. | Evidence/reconciliation review, not a product behavior test; cite manifest and records, never infer acceptance from code/tests alone. |
| REQ-007 / S2.1 AC-1 | Plug in an intentionally permissive persistence store (accepts any write, reports principals independent, never consumes nonce); core still refuses self-approval including a second account for same person, nonce replay, digest/version/expiry mismatch, wrong token class/audience. Assert refusal code/state and zero apply calls. | Core unit test; deterministic injected clock/nonce. This must fail if a decision is moved into store or handler. |
| REQ-007 / S2.1 AC-2 | Starting from a valid approved change, change one apply-time fact per case: kill switch; target fingerprint/base; principal epoch or dependency; approver revoked/removed; expiry; canonical bytes/digest; target version. Apply refuses with contract code before apply port. Include approved base X applied against Y (`SCOPE_MISMATCH`). | Core + fake ports; assert safe refusal, unchanged ledger lifecycle and zero apply calls in every case. Include one positive unchanged case. |
| REQ-007 / S2.1 AC-3 | Concurrent apply requests for one approved change contend at claim-once boundary; exactly one claim succeeds and no more than one apply-port call occurs. Losing callers receive permitted current-state/refusal outcomes. | Deterministic thread barrier against in-memory claim fake; repeat independent test runs without shared state. Database claim remains `NOT_RUN` unless S13 is accepted and disposable runtime evidence is available. |
| REQ-008 / S2.1 AC-4, S2.2 AC-1, AC-3 | Service issues nonce and `preview_digest`; page renders preview from the same stored canonical bytes covered by digest. Alter caller-supplied preview, nonce, digest, version, scope, model text or submitted bytes; mismatch/replay cannot record a decision. Valid accept and reject each bind to change, approver person, scope, digest, version, expiry; prove only the chosen lifecycle transition. | Approval-service/page integration with injected clock/nonce; compare rendered decoded content to canonical service bytes and recomputed digest; assert state/outbound calls. |
| REQ-008 / S2.2 AC-2 | Invalid, expired, replayed, cross-session nonce; chat/model identity; self-approver; CSRF missing/wrong; foreign Origin/Referer; unsafe preview text in each rendered field; stale page; concurrent proposal replacement; revoked session; direct preview retrieval without authorization. Each refuses without authorization-state change. | Page/session integration with test IdP and realistic HTTP request/response boundary. Assert status, safe body, headers, and unchanged state; XSS fixture remains inert. |
| REQ-009 / S2.4 AC-1–AC-2 | Missing/invalid credential on loopback fails; valid positive auth succeeds. Foreign Origin/Referer on approval POST, forwarded/proxy headers, Host mismatch, public target, redirect, proxy route and DNS rebinding are denied before apply port. Include same request with valid credentials to prove origin checks are independent. | Private ingress/request-boundary integration with `RouteProbePort`; no external listener/network call. Assert response and zero apply calls. |
| REQ-010 / S2.3 AC-1–AC-2 | `tools/list` is exactly five names: `propose`, `status`, `apply`, `verify`, `rollback_propose`; no `approve` or alias, annotations mark tools not read-only. Direct `approve` call and forged “approved” claim are refused and leave preview/state unchanged. | Tool protocol serialization/dispatch integration; inspect actual serialized list and invoke dispatch boundary. |
| REQ-011 / S2.3 AC-3 | Verify passes each supported S15 result unchanged. POST and UNPOST `VerificationResult` are `UNSUPPORTED_SHAPE`, never `VERIFIED`; reader error/inconclusive result is not converted to success. | S16 `VerifyPort` integration with real S15 verifier contract and fake reader. Assert returned type/code and lifecycle. |
| REQ-012 / S2.3 AC-4 | Verified POST plus matching current observed target creates a separate UNPOST proposal requiring its own approval; changed/stale target refuses. CREATE_DRAFT rollback and UNPOST rollback return `ROLLBACK_REFUSED`. No path calls approve or apply as part of proposal creation. | Tool/service integration with call-recording ports; assert distinct proposal identity/state and zero approval/apply calls. |
| REQ-013 / S2.3 AC-5 | Inject each safe refusal and an unexpected port exception; response uses registered error code and contains no exception text, stack, secret, nonce, CSRF token, session ID, or internal identifier. Spoofed chat text changes neither response preview nor state. | Tool/page boundary tests with captured response/log/artifact; assert exact safe fields and forbidden-value absence. Include successful response scans too. |
| REQ-014 / S3.2 AC-1 | Read-only ERP_MCP_REAL1 reachability probe records endpoint/operation, timestamp and result without credentials. | External authorized probe evidence, not unit test. Unavailable connector/access is `NOT_RUN` with exact observed error. |
| REQ-015 / S3.2 AC-2 | Stop one named in-scope lane component once; observe same component restarted by configured autostart using before/after process/service identity. | External lane evidence. No inferred PASS from config or prior status; unavailable observation is `NOT_RUN`. |
| REQ-016 / S2.4 AC-3, S3.3 AC-4 | Inspect registration/binding configuration after code: no S16 gateway/process binding, writer still disabled and `UNQUALIFIED`, production binding set empty. Test suite must not invoke COM writer or real POST/UNPOST. | Static/config boundary assertion plus reviewed test inventory; do not run destructive operations. |
| REQ-017 / S3.3 AC-3 | Reconcile any proposed S17–S19 item to explicit approved scope record; uncovered work stays deferred. | Scope-record review owned by GPT-PM; no runtime test. |

## S16 rev. 2 constants and edge coverage

Assert the delegated design decisions at their service boundary: approver session idle and absolute lifetimes **15 minutes**, internal approval nonce lifetime **5 minutes**, threshold configuration **mandatory in the target registry** (test configured boundaries and missing/invalid configuration fail-closed). These instantiate rev. 2 Q3; the numeric values are selected in this sprint, not supplied by rev. 2. Drive time through an injected clock and nonce generation through an injected source; test just-before, exactly-at, and just-after expiration. Browser forms carry only a session-bound opaque single-use decision reference; raw approval nonce and CSRF state stay server-side. Test exact Origin/Referer, reference cross-session/scope/version/digest replay, and atomic consumption. Visible canonical preview bytes hash to preview_digest; the separate internal S12 approval envelope binds that digest and the raw approval nonce.

For all five tools, cover valid authenticated request, invalid identity/token class, foreign tenant/company/base ACL, unknown/revoked target, safe input validation, upstream refusal, unexpected port exception, and repeated request where idempotency/replay applies. Assert externally visible code/state/call count; avoid asserting private helper calls. S16 approval store and route fakes must not be the only source of decision correctness. No test may use a model-supplied URL/SQL/credential or accidentally contact a production endpoint.

## Required final verification selections

The post-code phase must include (a) the specifically required S12 SQL code parity test and exhausted-budget SQL behavior; (b) the finisher brief's required slow SQL/E2E selected set, including the relevant producer/list-status integration paths; and (c) the required selected S15 suites from `docs/phase2/S15_SPRINT_PLAN_2026-10-27.md` §9. Test owners resolve exact existing test paths and run commands from those source documents after implementation. This plan does not expand the requirement to `pytest` without selection or a full repository suite. If exact suite selection conflicts across records, preserve the source and resolve it in the execution report rather than silently choosing a smaller set.

## Evidence record template

For each test or external scenario report:

```text
Sprint: beea27520b33
Story / AC / REQ / gate:
Test ID and plain-language behavior:
Code head (full commit hash):
Environment (Python/OS; disposable DB/E2E identity where relevant):
Exact command:
Result: PASS | FAIL | NOT_RUN
Observed assertion/result or exact dependency/error:
Skipped/xfail cases and reason:
Limitations: fake-backed | disposable integration | real-data producer | external lane
Evidence artifact/path:
```

`PASS` applies only to the stated test boundary. A fake-backed result is not real-data producer, database-claim, real-client, IdP, UAT, deployment, or production evidence. Historical results are not final-head proof. Requirements REQ-014/015 are external evidence, and REQ-006/016/017 are reconciliation/safety constraints, not claims established by a successful unit suite.

## Coverage gaps to close during test execution

1. Confirm exact existing slow SQL/E2E and S15 test selections against the finisher brief, S12/S13 prerequisite, and S15 §9; this plan names categories but does not invent suite filenames.
2. Verify each period/budget test reaches the real-data producer and source qualification boundary. A `PeriodEvidence`/budget DTO constructed directly in a test proves mapping only, not producer qualification.
3. Keep PostgreSQL claim-once `NOT_RUN` unless S13 acceptance plus a supported disposable database run is evidenced. In-memory concurrency does not establish SQL locking behavior.
4. Keep connector, watchdog, real client, production IdP, real 1C POST/UNPOST, deployment, and UAT claims separate from focused tests; record `NOT_RUN` plus exact dependency/error when unavailable.
