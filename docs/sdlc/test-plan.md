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

## S17-01 untrusted-file parser boundary

Use `tests/phase2/test_safe_parser.py` for the existing parser boundary; the assigned functional-test-reviewer owns additions and runs these named cases only after all S17 stories are coded. Keep the evidence split between parser behavior and the later S17-05 upload/workbench integration.

- Oversized XLSX and CSV input is rejected before parser/materialization entry. Before `zipfile` can materialize `ZipInfo` objects, preflight the selected EOCD central-directory byte range, count its fixed-size entry headers, and require that count to equal the ordinary EOCD total count and remain within `max_members`. Continue preflighting when the per-disk count or central-directory offset is a ZIP64 sentinel, because the total count and `size_cd` still identify the bounded scan. Include a hostile archive whose EOCD count is under the limit while `size_cd` spans more entries (including an EOCD-shaped signature in a comment); it must be rejected before `infolist()` materialization. Exercise ordinary EOCD size/count plus ZIP64 sentinel disk-count/offset fields without a ZIP64 locator to confirm preflight still rejects an oversized directory. A ZIP64 locator exactly 20 bytes before the EOCD may cause `zipfile` to override ordinary EOCD fields; total-count `0xFFFF`, central-directory-size `0xFFFFFFFF`, or that locator keeps the documented stdlib fallback limitation explicit.
- XLSX decompression/member/total/ratio, XML depth/node, row/cell/text and deadline limits return fixed `BOUND_EXCEEDED` with no partial sheets. Hostile/malformed package parts return fixed denial codes without echoing source content.
- Formula cells are not evaluated and formula text is not returned from XLSX; CSV formula-looking text stays literal and is never evaluated by this parser. External relationships/content types are denied; no URL, file, socket or other external target is opened or fetched.
- Exercise isolated XLSX timeout/child failure and memory-cap setup. POSIX uses `RLIMIT_AS`; Windows uses the Job Object per-process memory cap. If the applicable cap cannot be established, parsing must fail closed (`BOUND_MEMORY`) instead of continuing unbounded. Do not skip Windows memory-cap evidence on the obsolete claim that Windows has no cap.
- These tests prove the byte-parser contract only. They do not prove an upload endpoint, browser flow, Office safety, OS sandboxing, changed privileges, or workbench integration.

## S17-02 extraction and field provenance

The assigned functional-test-reviewer owns these named cases after all S17 story code is complete; do not run them before then. Keep S17-02 extraction-contract evidence separate from S17-05 workbench integration and H3 accuracy evidence.

- XLSX/CSV nonblank cell candidates retain the source byte SHA-256, file kind, one-based row and column, and XLSX sheet identity where present. A manually assigned field label remains tied to the same cell provenance.
- Malformed parser result shapes, invalid caller field-label mappings, missing source bytes, or candidate-count overflow fail closed without returning a partial candidate set or a proposal.
- Partially initialized slotted `ParseResult`, `ParseStats`, or `SheetValues` objects with missing fields return the fixed `MALFORMED_PARSE_RESULT` refusal; no `AttributeError` escapes.
- Every extracted candidate starts `REVIEW_REQUIRED`; parsing or exact text extraction never means business approval.
- For the measured explicit `includes_vat` rule, exact same-currency decimal values produce `MATCH_REVIEW` or `MISMATCH_REVIEW` (`false`: sum lines plus explicitly supplied VAT; `true`: sum lines). Both outcomes require review and `proposal_allowed` stays false. Use independent synthetic values and the recorded CT14 example `20 + 1.82 = 21.82`; do not infer VAT from a rate or apply rounding/tolerance.
- Exercise the largest supported component count and amount precision in both `includes_vat` modes. The sum must remain exact beyond Python's default `Decimal` context precision; a false match caused by implicit context rounding is a failure. This is a named case for the assigned reviewer, not a test run in this implementation pass.
- Mixed currencies, unknown `includes_vat`, discounts, credit notes, unsupported rounding/precision or other undefined accounting shapes remain `UNCOMPUTABLE_REVIEW`; no unsupported proposal or guessed tolerance is emitted.
- PDF/image input before qualified H3 extraction returns manual-review-only status and cannot produce a proposal or bypass human review.

## S17-03 company-scoped entity resolution

The assigned functional-test-reviewer owns these named cases after all S17 story code is complete; do not run them before then. Keep identity resolution separate from proposal authorization and preserve the exact source-cell provenance through every result.

- Register same-named entities in two companies and resolve each under its selected `AliasScope`; candidates and queue items must contain only IDs from that exact tenant/company scope.
- A name-only unique suggestion remains `UNMATCHED_REVIEW`; display-name similarity must not become a resolved entity. A missing entity produces `MANUAL_MAPPING_REQUIRED`, preserves provenance and cannot authorize a proposal.
- Multiple in-scope name matches produce `AMBIGUOUS_REVIEW` with the complete scoped candidate set and a stable queue item. No candidate is selected automatically.
- A valid explicit HUMAN choice for an ambiguity is recorded through the existing resolver; invalid/non-human approvers, out-of-set choices, foreign-scope queue items, conflicting replay choices, and missing reason fail closed.
- An exact namespaced reference may identify one in-scope candidate, but intake still returns `MATCH_REVIEW_REQUIRED`; every result has `proposal_allowed == false`.
- Malformed scope, extracted value, provenance, reference or resolver failure returns a fixed refusal without echoing extracted text or exception details.
- Incomplete slotted `ExtractedValue` and `IntakeEntityResolution` instances fail closed with the same fixed refusal; no missing-field exception escapes the adapter.
- This adapter does not authenticate the asserted human identity, persist alias decisions, create proposals, or call 1C; those remain outside this bounded in-memory story.

## S17-04 hostile-file corpus and per-file oracle

The assigned functional-test-reviewer and e2e-runner own these named cases after all S17 story code is complete; do not run them before then. The source-derived per-file outcomes below replace the older vacuous “clean digest or no proposal” oracle for the current parser path. `safe_parser.py` is a resource-limited parser process, not a sandbox: its intended parser child may run, but uploaded content must not cause another process, privilege change, filesystem write or network connection.

| Case | Input | Required parser/intake outcome | Positive twin / boundary |
|---|---|---|---|
| H-01 | Clean supported CSV and XLSX | Parser `OK`; extraction is non-empty `REVIEW_REQUIRED`; each value carries source SHA-256 and source coordinates; `proposal_allowed == false`. | Required positive twin for the hostile inputs below. |
| H-02 | XLSX formula cell | Formula is not evaluated and formula text is not returned; cached value or `None` may be present and remains review-required. | Clean literal cell with the same visible scalar stays literal and review-required. |
| H-03 | CSV cell beginning with `=`, `+`, `-`, `@`, tab or carriage return | Parser preserves the text as literal data and records the leading-formula counter; extraction remains review-required and cannot authorize a proposal. | Same string in an ordinary text field is preserved after UTF-8 decoding. |
| H-04 | XLSX external relationship/link, embedded object or connection part | `DENIED` with fixed `EXTERNAL_LINK`; no sheets or partial extraction. | Clean twin without the external part parses normally. |
| H-05 | Macro-enabled package, VBA project or macro sheet | `DENIED` with fixed `MACRO_PRESENT`; no sheets or partial extraction. | Clean `.xlsx` twin parses normally. |
| H-06 | ZIP member with traversal/absolute/drive-qualified path | `DENIED` with fixed `PATH_TRAVERSAL_MEMBER`; parser never extracts the member to disk. | Clean package member path parses normally. |
| H-07 | Encrypted ZIP member | `DENIED` with fixed `ENCRYPTED_MEMBER`; no partial extraction. | Unencrypted twin parses normally. |
| H-08a | Member exceeds configured uncompressed member limit | `DENIED` with fixed `MEMBER_TOO_LARGE`; no partial sheets. | Same document below the limit parses normally. |
| H-08b | Compression ratio or total decompression exceeds configured ratio/total bound | `DENIED` with fixed `ZIP_BOMB_RATIO`; no partial sheets. | Same content under the configured bound parses normally. |
| H-09 | Malformed XML or package structure | Fixed denial (`MALFORMED_XML`, `UNSUPPORTED_FORMAT`, or `NOT_A_ZIP` according to the failing boundary); no source bytes or parser exception text in output. | Minimal valid package with equivalent ordinary cell data parses normally. |
| H-10 | Hidden worksheet/row/column content | XLSX parser returns `DENIED` with fixed `HIDDEN_CONTENT`, no sheets and no partial extraction. Malformed visibility metadata returns fixed `MALFORMED_XML`. | Visible clean twin confirms the ordinary extraction path. |
| H-11 | Hostile uploaded filename | Not a parser input: `safe_parser` accepts bytes, not a path or filename. Do not claim filename traversal is covered here; S17-05 must keep filename handling inert and never use a supplied name as a filesystem path. | Ordinary filename and hostile-name metadata must produce the same byte-parser result. |
| H-12 | Canary listener and sentinel outside the parser process | E2E observation records zero outbound connections and an unchanged sentinel; no content-triggered process or privilege change. The parser's own bounded XLSX child is expected and is not sandbox evidence. | H-01 positive twin still yields non-empty review-only extraction. |

Per-file results must record case ID, exact input hash, parser status/code, extraction state/count, proposal-disabled result, and E2E I/O/sentinel observations where applicable. Do not compare only the clean digest: an implementation that ignores every file must fail H-01.

## S17-05 authenticated workbench preview

The assigned functional-test-reviewer and e2e-runner own these named cases after all S17 story code is complete; do not run them before then.

- `/admin/v1/intake/preview` and `/admin/v1/intake/manual-preview` authenticate through the existing Admin API, enforce browser CSRF, require a source-scoped platform role and a currently active business allow grant for the exact company, and treat a matching active deny as authoritative. Unauthenticated, foreign-source, disabled-company, no-allow, and explicit-deny cases return a fixed refusal before consuming request bytes.
- The upload route accepts bounded raw bytes only; hostile filename/path metadata is never sent by the browser and is not an API input. Content length and streamed body limits are both enforced. XLSX/CSV candidates retain exact digest and one-based coordinates; PDF/image remain manual-review-only. Access is rechecked after parsing, and a revoked/expired grant prevents disclosure.
- Manual preview accepts only an ordered bounded array of exact `{key,value}` string objects. Invalid shapes, unsafe key syntax, oversized input and excessive fields fail closed. Blank values yield no candidate; all returned values remain `REVIEW_REQUIRED`, `UNCLASSIFIED`, and proposal/apply disabled.
- Browser cases cover source/company selection, file bytes-only submission, manual preview, safe escaped rendering, status announcement, retry as a new request, and fixed error copy. No proposal, approval, write tool, or 1C operation may be reachable from either preview route.
- `WorkbenchSession.intake_preview` rejects invalid/foreign/expired sessions before parsing and returns the same scoped refusal contract as other workbench reads. A parse refusal has no partial fields.
- A successful supported-file preview lists each extracted value with its exact source hash, format and one-based source coordinates; every field is review-required and its materiality is explicitly `UNCLASSIFIED` until a human classifies it.
- `manual_preview` is also behind the same entitlement/session gate, bounds field count and text, derives a stable digest from the ordered exact field pairs, and returns one-based field provenance; blank entries create no candidate and every nonblank value remains review-required.
- Configured entity-field mappings use only the server-injected company-scoped `AliasResolver`; ambiguous and unmatched fields stay visible with candidate/suggestion state, and missing directory configuration is explicit. A field from another scope is refused.
- Until a persistent runtime directory is injected, both preview responses report `entity_directory.state=NOT_CONFIGURED` and `code=ENTITY_DIRECTORY_NOT_CONFIGURED`; the browser says no matches or suggestions were applied and must not infer an entity from a raw field label.
- PDF/image and other unsupported uploaded inputs remain manual-review-only; filenames are not accepted by the parser API and no Drive/source URL is fetched.
- Every preview has `proposal_allowed == false` and `apply_allowed == false`; no approve/apply/write tool or 1C call is reachable from the preview operation.
- Default object representations for review cards and fields must not disclose extracted values, sheet names, field labels, or entity suggestions; the explicit UI/API fields remain available only through the authenticated review flow.
- Existing `cards`, `read_job`, and `read_result` endpoints must continue to report authoritative current service state after failure/retry. The Admin Control Center change-status page must load only the selected company's bounded in-flight list, support previous/next pages, allow an explicit GET-only retry after a list error, and show the minimized detail fields; changing company while a request is pending must not display the previous company's result. Empty, unconfigured, denied, and unavailable states must be announced and recoverable. Keyboard users must reach the company selector, paging and row detail controls; at 200% zoom the status table remains horizontally scrollable without hiding the selected-company label. Ledger retry and rollback-proposal operations remain outside this read-only slice and are not implemented here.
- Source-to-ledger tenant binding and company-to-ledger company identity are nullable for legacy records and may be assigned only by a global `PLATFORM_ADMIN` with recent step-up. Both bindings are one-way/immutable through their audited endpoints and use expected row version plus idempotency. The ledger scope is resolved only by joining the registered enabled source and exact enabled company; neither key is read from request payloads during ledger queries. Unbound source/company, source-scoped admin, stale version, and attempted reassignment fail closed; the existing exact company authorization is still required before any ledger result is disclosed.
- `GET /admin/v1/companies/{company_id}/changes` uses only the configured durable S16 `SqlChangeLedger.list_inflight` reader, with `limit` 1–100 and `offset` 0–10,000; it exposes only the SQL status projection, not tenant/company keys, payloads, or approval digests. `GET /admin/v1/companies/{company_id}/changes/{change_id}` uses the minimized `operator_status` projection. Both require a source-scoped Admin role and the current exact-company allow grant, with deny taking precedence; authorization is rechecked after the ledger read before response. Missing bindings/foreign company return the same fixed not-found refusal; unconfigured ledger returns a fixed service-unavailable code. No retry, approval, rollback, writer, or 1C call is reachable from these read routes.
- The company UUID is resolved against the enabled Admin registry row; the route never accepts a caller-supplied source, tenant, or ledger-company key. The current source role and exact-company allow/deny result are both required before ledger scope is returned and are both reloaded after the ledger read. Cases must include an unrelated source-scoped Admin, a source-role binding revoked during the ledger read, and a deny that appears or the company mapping that changes during the ledger read; each returns a fixed refusal and no ledger fields.
- The Admin “Change status” page reads `change_ledger` records only; it must not call those rows `living.jobs` jobs. The current `living.jobs` key is `(tenant_id, source_id, job_id)` without `company_id`; a source may serve multiple registered companies. Do not list those queue rows in a company page. A future company job list requires a persisted job-to-company association (or a reviewed company-scoped projection), least-privilege read function, exact-company authorization before and after the read, and tests proving cross-company denial. Existing `read_job` is a known-ID user-session contract over `JobRecord`, not a production Admin list service.

## S17-06 frozen H3 measurement

The assigned functional-test-reviewer owns these named cases after all S17 story code is complete; do not run them before then. Use `h3_scorecard.py` only to aggregate a pre-frozen evidence record; its `PASS` is a metric result, not by itself sprint acceptance.

- Require exactly 30 invoices with unique source SHA-256 values and timezone-aware freeze timestamps earlier than extraction start. Duplicate hashes or malformed evidence return a fixed invalid code without document content.
- Count only human semantic corrections to fields marked material; formatting-only changes are not corrections. Compute the ratio by integer counts so exactly 10% passes and any larger ratio fails without rounding.
- Report per-format strata separately. A zero material-field denominator is `NOT_READY`, not a zero correction rate.
- Every material field must have a human-review record regardless of confidence; any unreviewed material field in a qualified test-lane sample fails.
- Any confidently wrong material field approved without human review fails regardless of the aggregate correction rate.
- `SYNTHETIC_ONLY` data or a missing test-lane run id can never produce acceptance; the result remains `NOT_ACCEPTANCE` even if the numeric rate is below 10%.
- The scorecard contains counts, fixed codes and file hashes only; never include invoice values, filenames, credentials or user identities. The evaluation dataset and real/realistic lane evidence must remain external evidence artifacts referenced by hash.

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
