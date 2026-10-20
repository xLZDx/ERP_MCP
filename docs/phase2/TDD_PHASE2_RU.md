# ERP_MCP Phase 2 — Living Model Registry, Connectors and Native Reconciliation

**Version 0.1 · October 8, 2026 · DRAFT FOR REVIEW.** This is a technical design document, **not** authorization to implement, deploy, or access production.

Related documents: `PLAN_PHASE2_RU.md`, `STORIES_PHASE2_RU.md`, `TEST_PLAN_PHASE2_RU.md`, `NATIVE_REPORT_PROTOCOL_RU.md`, and `DECISIONS_AND_SOURCES_RU.md`.

The portable specification package includes 28 requirements, 48 stories, 144 acceptance cases, Gherkin, YAML catalogs, JSON Schemas, and specification/L0 tests.

## 1. Release 1 / Release 2 Boundary

Release 1 remains subject to its existing frozen scope. This design does **not** claim R1 has been released, waive native-report acceptance gates, or change existing migrations and permissions. Security and accuracy defects in the current R1 path must be corrected in R1; they cannot be made acceptable merely by moving them into an R2 backlog.

Phase 2 proposes a reusable connector framework, continuous discovery, taxonomy/LDM/PDM, bitemporal history, targeted impact analysis for schema drift, provenance/attestation, native-report capture, automated reconciliation and a discrepancy workbench.

The operator authorized **designing** the ability to obtain native standard 1C reports in development and retain that capability for production. This is **not** an active permit to access production, execute EPF, copy a source database or grant new rights. Production capture requires an authorization bound to the exact source/company, procedure, time window and budget.

The central design change: A genuine standard 1C report does **not** become synthetic solely because its generation is automated. But procedure qualification, original-byte provenance, numeric equality and accountant approval remain **independent verifications**. Historical reporting-engine exports may not be retroactively relabeled as native UI evidence.

## 2. Goals, Terminology and Non-Goals

**PDM (Physical Data Model):** Published objects, fields, types, keys, relationships and operations of an authorized 1C interface. This is **not** direct access to 1C's internal SQL tables.

**LDM (Logical Data Model):** Versioned model of business concepts, relationships, contracts and source mappings.

**Drive catalog:** Files, revisions and evidence; it is not a physical accounting database.

**Observed:** What a source allowed the system to observe. **Accepted:** Which model version was approved under a policy. **Validated:** Which exact semantic operations have independent supporting evidence.

**Goals:** Current observed and accepted source maps; history of changes and decisions; verifiable mapping provenance; genuine native 1C reports; repeatable row-level and total-level reconciliation; precise explanations for `BLOCKED`; persistent access boundaries.

**Non-goals:** Arbitrary shell, BSL, COM or SQL from MCP; creating/posting/deleting records in 1C; unrestricted replication of all 1C data to PostgreSQL; automatic LLM approval; copying every PDCC connector without review; promising support for 1,000 active accounting queries merely because a maximum-session setting exists.

## 3. Historical Baseline at Draft Preparation

The existing Phase 2 backlog, `AGENTS.md`, `DOCUMENT_INDEX.md`, `NATIVE_REPORT_CAPTURE_RUNBOOK.md`, and `LOAD_TEST_REPORT.md` were reviewed. The working tree contained unrelated staged/unstaged changes. The last short SHA read was `4a21a01`, previously `1294b42` in conversation. This was a moving worktree, **not attestation of a deployed build**.

R1 already contained source/company registry, OAuth/ACL, PostgreSQL/Redis, capabilities, metadata fingerprints, semantic profiles/mappings/events, read-only OData and selected authorized COM routes.

The native report runbook records that some trial balances and account cards require an interactive form and produce `EMPTY`/`UNAVAILABLE` through external COM connections. Therefore, `COMConnector` availability does **not** prove that a specific report can be generated through COM. Use the standard UI procedure or report `UNSUPPORTED`; empty output is not a zero balance.

## 4. Functional Requirements

| ID | Requirement |
| --- | --- |
| R2-REQ-01 | Preserve R1/R2 isolation, staged deployment and exact-build evidence |
| R2-REQ-02 | One authoritative source registry, tenant/company/source/field ACLs and server-controlled IDs |
| R2-REQ-03 | Read-only connector SDK with separate source-specific authorization |
| R2-REQ-04 | Audit, pin, license-review and portability qualification of PDCC, ERP and Ferma donors |
| R2-REQ-05 | Baseline and incremental discovery with verifiable coverage |
| R2-REQ-06 | Canonical object/field/operation hashes separately from raw provenance hash |
| R2-REQ-07 | Distinct observed/accepted versions and independent approval decisions |
| R2-REQ-08 | Versioned taxonomy/LDM, typed edges, aliases and confidence |
| R2-REQ-09 | Bitemporal history, unknown effective time, gaps and replay |
| R2-REQ-10 | Dependency impact analysis; unknown impact fails closed |
| R2-REQ-11 | Durable jobs, fencing, cursors/outbox, capacity budgets and backpressure |
| R2-REQ-12 | Drive scope proof, baseline/change feed, revisions, memberships and revocation |
| R2-REQ-13 | Manual native UI capture and qualified UI automation |
| R2-REQ-14 | Qualified standard-engine/batch capture only where supported |
| R2-REQ-15 | Separate development/production permissions, production default OFF, no business writes |
| R2-REQ-16 | Provenance, independent oracle, private evidence and attestation |
| R2-REQ-17 | Isolated parser, no active content, privacy and retention |
| R2-REQ-18 | Deterministic reconciliation using Decimal, currency, time zone, cutoff and rows |
| R2-REQ-19 | Native account 521.1: six columns, expanded balances and analytics |
| R2-REQ-20 | Posted MOLDRETAIL purchases: identity, filters, fields and completeness |
| R2-REQ-21 | Per-operation validation policies, evidence foreign keys and independent approval |
| R2-REQ-22 | Discrepancy workbench, coverage, lineage and safe explanations |
| R2-REQ-23 | Route-specific capacity, physical-backend budgets and measured performance |
| R2-REQ-24 | Fault, lag and audit alarms; recovery and restore evidence |
| R2-REQ-25 | Expand/switch/contract strategy, R1 compatibility and safe rollback |
| R2-REQ-26 | Safe read/job APIs, idempotency, CSRF and annotations |
| R2-REQ-27 | Multiple accounts and revocation without cache/index disclosure |
| R2-REQ-28 | Reproducible acceptance bundle and truthful `NOT_RUN`/`BLOCKED` |

## 5. Architecture

```text
ChatGPT / Claude / Admin UI
    → OAuth + ACL + audit
    → ERP_MCP query API
    → accepted projections
    → live authorized source adapters

Control API → durable jobs → discovery/connector workers → OBSERVED registry

Control API → Capture Broker → isolated approved native 1C UI/engine runner
    → private evidence store → isolated parser → independent verification
    → deterministic reconciliation → accountant approval
    → scoped accepted model
```

There are **four distinct control paths**: user reads, administration/observation, 1C application execution, and evidence/attestation. MCP never receives a universal Windows command executor.

A query request must not perform a complete scan or promote a model. If a mandatory freshness check is overdue, return a safe refusal. A bounded refresh job may be queued **only under separate authorization**.

## 6. Roles and Separation of Duties

- **COMPANY_READER:** Reads authorized company results/models; no automatic source-wide metadata rights.
- **CONNECTION_ADMIN:** Manages sources, scope, secret references and revoke; not accounting approval.
- **DISCOVERY_WORKER:** Appends OBSERVED events and cursors, not ACCEPTED/VALIDATED state.
- **CAPTURE_OPERATOR/WORKER:** Runs a qualified procedure in an approved environment; neither 1C administrator nor arbitrary-code executor.
- **EVIDENCE_VERIFIER:** Checks source, byte integrity and report parameters.
- **RECONCILER:** Computes deterministic comparisons but does not supply authoritative expected values.
- **ACCOUNTING_APPROVER:** Independently signs evidence for an exact accounting scope.
- **MODEL_APPROVER:** Accepts a model revision through policy, evidence FKs and CAS.
- **AUDITOR:** Reads only authorized historical evidence.

Identity must come from a **verified authentication context**, not `signed_by` in JSON. A production uploader/capture identity cannot approve its own report. Database roles must physically enforce separation of duties. The runtime must never serve ordinary users as a database owner, superuser or BYPASSRLS role.

## 7. Connector Contract and Lifecycle

Lifecycle: `DRAFT → AUTH_PENDING → SCOPED → PROBING → ACTIVE`, plus distinct `DEGRADED`, `AUTH_REQUIRED`, `PAUSED`, `REVOKED` and `RETIRED` states.

Connector SDK functions: `validateConnection`, `discoverScopes`, `capabilities`, `baseline`, `changes`, `fetchMetadata`, `fetchRevision`, `health`, `pause`, `revoke`.

Optional capabilities must be declared honestly. If a source does not support change feeds, classify it `SNAPSHOT_ONLY`; do not fabricate an event stream.

Required event envelope: schema/adapter version, tenant/connection/source/company scope, `observation_id`, `observed_at`, coverage/completeness, source revision basis, cursor before/after, objects/events, warnings and provenance digest. Registry-controlled IDs are mandatory; arbitrary target URLs are forbidden. Source-provider credentials must not be inherited from ChatGPT OAuth.

Delivery is at least once with idempotent ingestion, deduplicated by scoped provider object/revision/event. Reusing the same ID with different bytes produces conflict and quarantine. Cursor advancement occurs **only after** durable page, event and outbox writes in one transaction.

Revocation increments the scope epoch. Reauthorize before fetch and again before disclosure. Pause prevents new jobs; historical records must not be presented as current/live.

## 8. Ongoing LDM/PDM Updates

1. On connection, obtain an authorized baseline and record coverage. For event APIs, acquire a start token **before** baseline and catch up with change events, resolving race windows.
2. Use a cheap change signal only when supported and qualified. `HEAD`, ETag and HTTP 304 are neither automatically cheap nor authoritative without measurement. Otherwise perform a full metadata scan within source budget/window.
3. Errors, partial pages and revoked visibility do **not** imply deleted objects or a new schema.
4. Retain raw SHA-256 for provenance and a separately versioned canonical structural hash.
5. Canonical identity includes namespace, types, precision, scale, nullability, keys, navigation/cardinality, enum members and supported operation signatures. Normalize order only where it is semantically irrelevant. Do not merge objects with colliding short names.
6. Record an OBSERVED snapshot and object-level diff, then calculate full impact closure across accepted dependencies.
7. Create LDM changes as **CANDIDATE**. Unknown impact blocks dependent operations conservatively. Only the independent model-approver role can publish accepted heads according to policy and `expected_previous_head`.
8. Track **data changes** separately from schema changes: a backdated accounting posting may alter a previous balance without changing schema. That requires a new comparison/run and applicability check, not fake schema drift.

Polling cannot reconstruct every intermediate change. A–B–A between polls without provider history cannot prove that B existed. Report `SNAPSHOT_ONLY`/`HISTORY_GAP`, observation intervals and unknown effective time; never access forbidden direct SQL CDC merely to promise completeness.

## 9. Observed, Accepted and Validation States

Independent axes: `connectivity`, `observation_freshness`, `schema_acceptance`, `mapping_validation`, `evidence_validity`, and `data_consistency`.

- **Fresh accepted + validated operation + currently authorized source:** Live read may proceed.
- **Source unavailable:** Live reads fail safely; dated historical model remains accessible only under current ACL.
- **Non-impacting change:** Continued operation is permitted only when dependency coverage is proven and a compatible policy was already approved; do not invent new approval.
- **Affected or unknown change:** Block affected operations, possibly more broadly when the dependency graph is incomplete.
- **New artifact:** `UNATTESTED`. Numerical comparison may be a diagnostic, never an automatic business PASS.
- **Same numbers, unproven cutoff/currency:** `INCONCLUSIVE`.
- **New revision:** Preserve the historical PASS of old immutable bytes; revoke its applicability to the latest version.

Automatic structural acceptance does **not** validate a new financial formula. An LLM cannot confirm or validate through either a tool call or a document phrase.

## 10. PostgreSQL and Temporal Database

Initial model: PostgreSQL 16 compatible. TimescaleDB is optional after benchmarking and is **not** mandatory. “Time DB” means bitemporal capabilities.

Proposed entities: `connector_instances`, memberships, jobs/leases/cursors/outbox, `schema_snapshots`, object versions, accepted heads, logical concepts/aliases/edges, model events, capture recipes/jobs, evidence artifacts/revisions/attestations, comparison runs/items/issues and validation policies/bindings. Reuse existing R1 sources/companies/capabilities/semantic profiles where authority permits.

Event fields: immutable event ID, schema version, tenant/source/company, aggregate sequence, event type, observed time, registry-recorded time, source event time, nullable effective range, evidence basis for effective time, source revision, actor, policy, correlation/causation, payload digest and `supersedes`.

`recorded_at` describes when the registry learned a fact. Effective/valid time describes when it applied at the source, **if known**. Never fill unknown effective time using the poll timestamp. Corrections append events with `supersedes`; current projections can be rebuilt. `AS KNOWN AT` and `AS EFFECTIVE AT` answer distinct questions.

Composite keys, foreign keys and RLS isolate tenants/companies. Store large original bytes in private versioned storage; PostgreSQL stores references, hashes and minimal permitted aggregates. The runtime reader cannot write accepted-model or evidence records. `SECURITY DEFINER` commands must verify scope, arguments, `search_path`, and EXECUTE privileges.

Append-only storage does not automatically constrain a database superuser. Export critical audit anchors to separately protected storage.

## 11. Scheduler and Capacity

Use durable per-source leases and monotonically increasing fencing tokens. A worker whose lease expires must not commit. Long external source calls must **not** hold open a database transaction/connection.

Bound queues and enforce per-tenant, physical-backend, source and workload-class budgets, fairness, jitter/backoff, circuit breakers and quarantine. Multiple source aliases for the same real database and different service replicas must share a **physical-backend** budget.

Interactive reads take priority over discovery/capture, while background work retains a guaranteed minimal budget. Conservative initial design: one capture per backend and one writer per source; other limits must be no greater than those actually qualified for the target.

R1 settings such as 1,000 sessions, DB pool 10, sidecar 4 and fanout 20/2 apply to different layers and **do not establish throughput capacity**.

Test grid: 30/50/100/150 sources; 1/5/10/20/50/100 active clients; separately 50/100/500/1,000 sessions; single/multiple physical backends; cold/warm; discovery off/on; metadata/documents/balances/capture; two-hour and eight-hour soak.

Measure p50/p95/p99, RPS, error classes, connection/queue wait, CPU/RSS, actual 1C user latency and audit/cursor lag. Profile refusals must not count as business throughput.

**Proposed unmeasured targets:** Warm metadata p95 ≤500 ms; enqueue p95 ≤500 ms; background impact on equivalent foreground p95 ≤20%. Approve actual SLOs, hardware and stop criteria **before** load testing.

## 12. Native Report Capture

Support manual standard UI intake, qualified UI automation and qualified standard reporting-engine/batch paths.

A recipe pins source/config/platform/report object/variant, executor/selectors, typed parameter schema, output format, hashes, secret references, budget, permissions and qualification. Input is `recipe_id` plus typed scope and permit, **never** arbitrary command, BSL, SQL or EPF.

UI procedure: verify application process/database/company, set and read back parameters, open standard report, wait until complete, verify headers and full coverage, export original, hash and ingest. Unknown dialog/selector/wrong source must fail. A filesystem-only DC or test runner does not prove UI automation capability.

COM standard reporting is allowed only when the specific standard report actually works and has been qualified against UI output. `EMPTY` is not zero. `/Execute` may launch a previously reviewed and pinned processing artifact, not arbitrary code. No administrator fallback, disabling safe mode, or replacing native evidence with custom queries.

The job API changes **its own control-plane state**, so idempotency, CSRF, audit and accurate mutating-operation annotations remain mandatory even when the external 1C source is read-only.

## 13. Development and Production Security

Development uses an approved disposable copy, independent credentials and development-level evidence. Do not copy production credentials. Write probes and Ferma seeding belong only to a separately approved test harness, never a report recipe.

Production capture is **OFF by default**. Enabling it requires owner/security/operations approval tied to the exact source/company, procedure/version/hash, time window, expiry, per-invocation/backend budget, private output destination, verified permissions and qualification on an approved copy.

Permission to run a report is **not** accounting approval of its values.

Standard reports execute 1C configuration code. A read-only account may still cause service-level settings/log writes. Qualify explicit **no-business-write** permissions and technical side-effect coverage; do not promise byte-identical production databases.

Unverified side effects deny automated production capture. Authorized manual export or an approved copy may be used instead. No production write probes or `reset.ps1`, no termination of other processes, and no restarting gateways merely to generate reports.

## 14. Evidence and Attestation

A hash proves byte equality, **not provenance**. Every original starts as `UNATTESTED` until source/origin verification.

Required manifest: source/database/configuration; report/variant; company; period/time zone/currency/units; grouping/expanded balances/filters; snapshot/cutoff; actor/runner/recipe; capture timestamps; byte hash/size/media/parser; completeness; classification and retention.

R2 native-eligible candidates include genuine manual UI, qualified automated UI, or a qualified standard engine proven equivalent to UI. A synthetic generator, custom COM query or value derived from MCP does not gain native evidence authority automatically. Connectors may create `UNATTESTED` references but never PASS or `VALIDATED`.

A numerical verifier computes `MATCH`, `MISMATCH`, or `INCONCLUSIVE`. An independent accountant approves `ATTESTED`; a model approver binds usable mappings to exact source/company/operation/model/policy/evidence foreign keys. JSON actor fields and ten arbitrary test IDs do not replace real sign-off, completeness or bytes.

**Bootstrap:** A private evaluation runner may execute pinned candidate mappings on an authorized disposable copy with `EVALUATION_ONLY` output. It is neither a public profile bypass nor arbitrary SQL nor grounds to enable production. Only independent native comparison and approval can lead to accepted mappings and a canonical MCP replay.

## 15. Account 521.1 and Purchases Reconciliation

For company 818HA and August 2026, the account 521.1 trial balance requires **six separate totals**: opening debit/credit, turnover debit/credit, closing debit/credit. Also verify all counterparty/contract rows and coverage.

Net-liability `credit - debit` and net continuity are useful supplementary checks, **not substitutes for six-column comparison**. Equal closing values do not rule out incorrect opening/turnover amounts. Conversation-supplied figures are not verified golden truth; a second genuine set of figures was not independently established in this initial design. Actual financial details remain private rather than new Git fixtures.

The canonical local period is `[2026-08-01 00:00, 2026-09-01 00:00)` in a **verified source time zone**. Wire-end semantics are qualified per adapter; never hardcode a universal `23:59:59Z`.

Unknown currency must not be assumed to be MDL. Use Decimal and a pinned tolerance policy. Snapshot/cutoff must match; concurrent or backdated changes yield `INCONCLUSIVE` or a new run.

The existing native runbook reports that the current payable mapping expected a settlement register not found in 818HA. Ten reports cannot create that missing register. Instead, qualify an **explicit accounting-based AP strategy** through accounting analytics. An account balance alone cannot establish aging or due dates.

**Purchases contract:** Exact company and supplier identity, `Posted`, `DeletionMark`, dates, document number, amount/currency, header/rows and complete pagination. Do not automatically join by a supplier's name alone.

R2 may introduce a separate structural document-validation policy after governance approval, but cannot silently waive the R1 blanket gate. Purchases validation does not enable AP or aging.

## 16. Google Drive

Start with `changes.list` polling. Obtain the start token **before** baseline; traverse the approved corpus; consume pages and commit changes atomically with a cursor. Maintain separate account/shared-drive cursor namespaces. Feed and current-state APIs cannot guarantee every intermediate revision.

With per-file `drive.file` access, selecting a folder does not prove access to future children. A real proof of concept must include new files, moves, shortcuts, shared drives and revocation. An application-level filter cannot make a broad OAuth token into a folder-only grant. Service accounts require genuine resource permissions; keyless Workload Identity Federation is a separate infrastructure decision.

Viewer/read-only permissions do not guarantee revision-history access. Do not elevate to writer or mutate `keepForever` just to download history. Where unavailable, save only permitted current exports into immutable storage and report `SNAPSHOT_ONLY`/`GAP`. For dynamic exports, compare before/after revision and bytes hash; an unresolved race denies an exact-revision claim.

External OAuth Testing tokens with additional scopes may need re-consent and `invalid_grant` handling; never build production around the assumption that tokens never expire.

Optional watch notifications require HTTPS, channel/token verification, expiry/renewal and duplicate/out-of-order handling. Notifications are **only hints to fetch**; polling must work without push.

A new revision preserves historical PASS on immutable previous bytes but ends applicability to the latest. Compromised or revoked attestation generates a separate event with tracked dependencies.

## 17. Parser Isolation and Privacy

Isolate parsing from the network; deny DTDs/entities, macros, embedded objects and external links. Enforce ZIP input bytes, entry count, nesting/decompression ratio, time and RSS budgets. Never execute or recalculate formulas. Use trusted cached values only under an approved profile; otherwise require values-only export. OCR is a fallback needing human review and an explicit completeness flag.

Prompt-injection content never obtains new permissions, URLs or SQL execution.

**Initial proposed budgets (not qualified limits):** 25 MiB input, 200 MiB inflated, 10,000 entries, compression ratio 100:1, 60 seconds and 512 MiB RSS. Qualify limits for actual report formats. Exceeded limits cause quarantine/denial, **not truncated PASS**.

New scopes, raw-content sharing, retention and legal holds need policy approval. Deletion requires separate authorization and is **not** part of this design package.

## 18. User Interface and APIs

Proposed screens: Connections, Live Model Diff, Taxonomy, Timeline, Capture, Evidence Inbox, Workbench and Capacity/Health. Display environment, source, company, valid time, known time, model version, freshness and trust explicitly.

A `BLOCKED` response includes a safe `reason_code`, next action and correlation ID, **not** another company's source name, stack trace or secret reference.

Proposed APIs: create connection; enqueue rescan/report/reconciliation; read model/timeline/job/result; attest evidence; CAS-approve model; pause/revoke. Accept only typed IDs, parameter schemas and policy references. Cookie-authenticated administrator mutations require CSRF protection. All controls must be idempotent and audited. No arbitrary JSON `set status VALIDATED` endpoint.

## 19. Migration, Rollback and Acceptance

**Expand:** Add new tables and roles without modifying R1. Start with observed-only shadow capture. Historical imports become `UNATTESTED` provenance; they cannot fabricate a reconstructed history.

Qualify a canary on approved development and Drive corpora and procedures. **Switch per source/company** under a signed policy. Contract/cleanup follows a separate rollback window; no deletion is authorized by this plan.

Rollback restores only a compatible version or feature flag, **never** expired credentials, revoked grants or invalid evidence. When the current live schema is incompatible with an old accepted head, affected operations remain blocked. Restore must verify artifact hashes, foreign keys, event sequences, attestations and current access rights.

Release is permitted only after G0–G7, actually executed mandatory tests, independent native accounting evidence and UAT. Companion SPEC/L0 tests verify the specification, **not** a future running product. At the original design checkpoint, all 144 product acceptance cases were `NOT_RUN`.

**This document remains a design baseline. All current implementation and release claims must be verified on an exact source/configuration HEAD and accepted by the relevant gate owners.**
