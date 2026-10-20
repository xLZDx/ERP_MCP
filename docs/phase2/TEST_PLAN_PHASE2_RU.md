# ERP_MCP Phase 2 — Test Strategy, Scenario Catalog and UAT

**Version 0.1 · October 8, 2026 · DRAFT.**

The complete local list of IDs and acceptance criteria is in `STORIES_PHASE2_RU.md`. Extended Given/When/Then steps, YAML catalogs and Gherkin are included in the portable companion package.

**Historical checkpoint:** All 144 product acceptance scenarios were `NOT_RUN` at the original specification stage. Isolated specification-integrity checks did not change those statuses. Later evidence must be assessed against the actual Git HEAD and test executions.

## 1. Verification Levels and Independence

| Level | What executes | What it proves |
| --- | --- | --- |
| **SPEC/L0** | JSON Schemas, fixtures, cross-links, dependency DAG and arithmetic counterexamples | Specification consistency, **not** implementation |
| **UNIT/L1** | Real canonicalizers, serializers, policy checks and bounded parsers | Local code and negative branches, **not** native reconciliation |
| **INTEGRATION/L2** | Disposable real PostgreSQL, grants/RLS/FKs, leases/outbox, Redis and sandbox provider | Transaction and authorization boundaries |
| **FUNCTIONAL/L3** | MCP, adapter, approved development/reference 1C, and original native export | Genuine scoped capture/compare chain |
| **QUALIFICATION/L4** | Manual UI versus qualified UI automation or standard engine on the same copy | Source-specific report procedure and configuration |
| **PROD/UAT** | Explicitly permitted canary company with independent approval | Source-specific acceptance, **not** universal compatibility |

Expected results must not be generated from the same MCP result under examination. Negative tests deliberately vary scope, modify original bytes, forge a PASS, expire permissions or simulate failures. A positive case alone is insufficient.

## 2. Companion Test Execution

Running `python -m pytest -q tests` from the **portable specification package directory** executes only offline SPEC/L0 tests without network, Windows, 1C, secrets or application imports. These cover schemas, requirement/story/test references, catalog completeness and a synthetic counterexample where financial errors compensate.

`acceptance/phase2.feature` contains 144 scenarios. Executing them requires **real step definitions and a scoped product adapter**. An unconditional success step or string search in a configuration is not a valid implementation. Every Then must assert observable product, database, source, or evidence-workflow behavior.

A missing adapter, environment, authorization, or native artifact produces `BLOCKED` or `NOT_RUN` and prevents gate PASS. The companion `validation_report.json` applies **only** to SPEC/L0.

## 3. Test Data

The synthetic corpus includes at least two tenants, three companies, identical supplier names across company scopes, multiple contracts with opposing debits and credits, posted/unposted/deleted purchase receipts, zero/negative/rounded amounts, different currencies/time zones, three schema versions, partial pages, late events, moves/shortcuts/revisions, and revocation.

The real reference corpus requires an approved database copy and configuration identity, original native artifacts and a manifest. Financial figures from the chat are `USER_SUPPLIED_NOT_ATTESTED`, **not** golden test fixtures. Never commit private financial lines or secrets to Git. Ten copies of one comparison are not ten independent cases.

Reset/write probes are permitted only through a separately approved test harness targeting an authorized disposable environment. Never use `reset.ps1`, `DROP`, `TRUNCATE`, or exploratory writes against a real/production database. Changing pytest test paths is not a way to bypass permission restrictions on operational scripts or secrets.

## 4. Test Suites

### Authorization and Contracts — TC001–018, TC121–123

Verify the R1/R2 boundary, exact build, and donor inventory. Typed source IDs; arbitrary URLs, SQL and shell commands rejected **before dispatch**. Cross-tenant FK/API/RLS denials. Company-only access does not grant global metadata. Check the authorization epoch before fetch and again before disclosure. Validate secret startup, rotation, missing-pair preflight and no credential leakage through logs, argv or artifacts. Job annotations, CSRF and idempotency must be correct; raw COM/DC cannot bypass denial.

### PDM, LDM and Temporal Semantics — TC019–048

Verify complete baseline/coverage, namespace-qualified IDs, and a canonicalizer that ignores semantically irrelevant XML formatting while detecting type/scale/key/navigation/function changes. Partial results, errors and narrowed ACLs cannot imply object removal. Recovery never increases trust automatically.

Check SQL append-only privileges, replay, both time axes, unknown effective dates, late corrections and gaps. A–B–A changes between polls without history API are not invented. Candidate aliases and taxonomy edges are scoped; ambiguities require a human decision. Unknown dependency graphs deny conservatively. Accepted-head changes require CAS; incompatible rollback cannot silently clear drift.

### Scheduler and Cursor Safety — TC049–060

Two workers on the same source must have at most one valid lease/fence. A worker that has lost its lease cannot publish. Crash before page commit must allow lossless, duplicate-free replay. Cursor/outbox/result writes are transactional. The same event ID with different bytes is a conflict.

Budgets apply to the **physical backend** across source aliases and replicas. Verify bounded queueing, foreground/background fairness, isolation of poisoned sources, and fresh scope/cursor validation before resume.

### Native Capture and Parser — TC061–081

Verify original UI report, headers/settings/totals, exact source and company. Partial screenshots cannot prove a complete report. Editing an XLSX artifact requires a new revision/digest. Manual and automated UI capture must be equivalent. Unknown modal/selector or wrong database must fail without guessed clicks.

Qualified standard-engine reports must retain genuine provenance. Empty COM output is not zero and cannot justify relabeling an internally generated query as native. Untrusted EPF content is rejected.

Production capture defaults OFF. Enforce permit scope, expiry and idempotency conflicts. Prove the absence of business writes, including coverage of technical side effects. Private immutable artifacts must genuinely exist. Parser isolation never evaluates macros, formulas or external entities; zip bombs, memory and time budgets are bounded, and truncated results cannot count as PASS.

### Independent Evidence and Finance — TC082–102

Require original bytes, digest, origin, scope and a real attestation foreign key. The signer must be independently authenticated; uploaders, connectors and a JSON `signed_by` field cannot confer `VALIDATED`. Revocation ends current applicability while preserving history.

The candidate runner outputs only `EVALUATION_ONLY`, never a public validation bypass. Canonical tools can be replayed after qualified approval.

Compare **all six** report aggregates and underlying rows. Equal closing net balances with incorrect openings/turnovers must produce `MISMATCH`. Contract debit/credit sides must not be hidden by netting. Accounting-based AP requires an explicit qualified strategy; a missing settlement register cannot be invented and balances alone do not prove aging.

Posted MOLDRETAIL purchases must be checked for company, supplier, deletion state and complete pagination. Differing snapshots or cutoffs yield `INCONCLUSIVE`; a backdated correction creates a new run. Ten arbitrary evidence IDs do not establish coverage. Approving purchases does not enable AP or modify R1 validation.

### Google Drive — TC103–114

Prove actual OAuth/file/folder/shared-drive scope and behavior for newly created child files. An application-level folder filter **is not** OAuth permission isolation if the token is broad.

Acquire the start token before baseline capture; perform catch-up and persist a durable cursor. Separate account/drive namespaces. Lost cursor leads to controlled resnapshot and a declared gap.

Test revisions, moves, shortcuts and revocation against **current** access scope. Viewer/read-only may not include revision history; do not grant writer access or mutate `keepForever` to make a test pass. `invalid_grant` yields `AUTH_REQUIRED` and an alert. Duplicate or out-of-order webhooks are hints only; polling must function without watch.

### Workbench, Production, Operations and Release — TC115–144

The workbench links discrepancies to fragments, rows, owners and deltas. Original numbers are immutable, and reruns produce new records. Timelines distinguish known/effective and historical/current states. Safe errors reveal no foreign IDs or secrets.

Production canary requires a separate permit: a development PASS is not production approval. The kill switch controls only owned jobs.

Capacity reports must distinguish sessions from active clients and source counts from physical backends. Denied/unvalidated profile requests do not count as business throughput. Measure background interference. Audit unavailability must block a transaction before its effect and actually trigger/recover an alert. Worker/provider failures must not lose or duplicate publications.

Expand/shadow rollout preserves R1; rollback cannot resurrect revoked grants. Restore verification includes artifact hashes, foreign keys, accepted heads and attestations. Exports require masking, tenant isolation and spreadsheet-formula safety. Honor legal holds; no unauthorized deletion. Additional donors need pin/licensing qualification. The exact-head release manifest cannot present `NOT_RUN` as PASS.

## 5. Load-Test Matrix

Before load testing, pin hardware, deployment, build, configuration, dataset, workload and qualified tools.

Test across:
- **Sources:** 30, 50, 100, 150.
- **Active clients:** 1, 5, 10, 20, 50, 100.
- **Sessions (independently):** 50, 100, 500, 1,000.
- **Backends:** One or multiple physical backends; cold/warm; metadata, documents, balances, native report capture; discovery enabled/disabled.

Start with short steps, then 2-hour and 8-hour soak tests at a stable qualified load.

A real 1C backend may be load-tested only with a separately approved scope, time window, budget and stop criteria. Measure business reads/s, p50/p95/p99, queue and connection-pool wait, source busy/timeout rates, RSS/CPU, actual 1C user latency, audit/cursor lag, and missed/duplicate events.

**Configuration limits are not capacity evidence.** Stop when approved latency thresholds, sustained errors, saturation, unsafe side effects, or resource budgets are exceeded.

Proposed targets, **not measured guarantees**: warm metadata p95 no more than 500 ms; enqueue p95 no more than 500 ms; foreground p95 increase under background load no more than 20%. Actual SLOs require qualification on the chosen environment. Report failed ACL/profile requests separately.

## 6. Normal User UAT

| ID | Required scenario |
| --- | --- |
| UAT-U01 | View own company's status and a safe explanation for `BLOCKED` |
| UAT-U02 | Posted MOLDRETAIL receipts: dates, document numbers, amounts, currencies, complete pagination and native journal |
| UAT-U03 | Account 521.1 trial balance: all six measures, contracts, expanded/net views, native provenance, currency and time zone |
| UAT-U04 | Historical timeline with explicit known/effective time axis selection |
| UAT-U05 | Access to another company or arbitrary SQL/COM command is denied |
| UAT-U06 | Mid-job revocation prevents disclosures from caches and artifact URLs |

## 7. Administrator and Accountant UAT

| ID | Required scenario |
| --- | --- |
| UAT-A01 | Connection, scope, secret reference, budget and preflight |
| UAT-A02 | Observed → diff → impact → accepted; LLM is not an approver |
| UAT-A03 | Native UI baseline and qualified recipe on a disposable source copy |
| UAT-A04 | Independent attestation; fake/duplicated ten-case evidence rejected |
| UAT-A05 | Drive report, revision, move and revoke; current applicability separated from history |
| UAT-A06 | Production OFF by default, time-bound permit, canary, revocation and kill switch |
| UAT-A07 | A failure fires a real alert and recovery clears it correctly |
| UAT-A08 | Restore/rollback without reset of a real source and without reinstating revoked access |

## 8. Test Evidence and Exit Conditions

Every actual result must record:
- Test-case ID and `PASS`/`FAIL`/`BLOCKED`/`NOT_RUN`.
- Exact build, configuration, procedure, and step-definition hash.
- Environment, source/company, start/end times.
- **Actually executed assertions** and sanitized artifact references/hashes.
- Correlation ID, scope and authorization basis.
- Reviewer/approver and recorded deviations.

Planned expected results must never be confused with actual outcomes.

Gate PASS requires all mandatory cases to have executed successfully, no unresolved correctness/security discrepancy, and the required independent approvals. Specification tests **do not replace** product acceptance.

**No production or native 1C tests were performed by the initial design package itself.** Later test evidence must always be reported with its own exact Git HEAD and measured environment.
