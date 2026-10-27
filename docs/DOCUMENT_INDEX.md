# ERP_MCP — Normative Documentation Index

**Baseline:** v1.1 — operator scope freeze
**Date:** 2026-10-06
**Status:** FROZEN — NO NEW SCOPE UNTIL CURRENT COMMITTED SCOPE CLOSES
**Scope:** frozen read-only 1C/DAD delivery baseline; recorded deferred lanes stay deferred until explicit rebaseline

Interactive view: [ERP_MCP Engineering Command Center](ERP_MCP_ENGINEERING_COMMAND_CENTER.html).

Current implementation evidence: [execution log](../reports/EXECUTION_LOG.md),
[status](../reports/IMPLEMENTATION_STATUS.md), [gap analysis](../reports/IMPLEMENTATION_GAP_ANALYSIS.md),
[DoD status](../reports/DOD_STATUS.md), [risk status](../reports/RISK_STATUS.md), and
[Admin Control Center status](../reports/ADMIN_CONTROL_CENTER_STATUS.md).

Machine-readable current snapshot: [engineering checkpoint](../reports/CURRENT_ENGINEERING_CHECKPOINT.json).
CI checks its implementation-content fingerprint against all six report/dashboard markers;
historical freeze/CI references remain historical, not automatic proof for changed code.

The implementation fingerprint also includes the isolated `testbed/` code; changing an exporter,
target guard or comparator without refreshing status evidence fails the same consistency gate.

Both offline Command Center copies embed all 31 required normative sources plus the three existing
supporting sources through `python -m scripts.sync_dashboard_documents`. The current phase-status
overlay is preserved independently of normative Master Plan content. CI checks source hashes AND
exact sanitized renderer output; editing a source, refreshing a hash alone, changing an embedded
body, missing/duplicated cards or mismatching copies fails. Regenerate after normative edits, then
run `python -m scripts.sync_dashboard_documents --check`. No browser CDN/fetch is needed.
Renderer is dev-only [Python-Markdown 3.11](https://pypi.org/project/Markdown/3.11/), BSD-3-Clause,
locked in uv; production runtime dependency lock is unchanged. Raw HTML, active URL schemes and
tracking images are not activated by documentation embedding.

Legacy copied reading/device tool envelopes are omitted from presentation, not from immutable
freeze sources: their complete original source hash is still checked. Generated report shells
must not publish the engineer's device identity or put diagnostic text before the HTML doctype.

This directory is the normative engineering contract for ERP_MCP. Implementation must follow these
documents. A code change that conflicts with the baseline requires an explicit architecture/governance
change first.

## Document precedence

When documents conflict, use this order:

1. `SECURITY.md` — security invariants and trust boundaries.
2. `docs/GOVERNANCE.md` — change authority, review and evidence rules.
3. `docs/SCOPE_FREEZE_BASELINE_2026-10-06.md` — operator-approved committed/deferred scope and rebaseline barrier.
4. `docs/adr/` — accepted architecture decisions.
5. `docs/TDD.md` — product/technical requirements.
6. `docs/ARCHITECTURE.md` — system/component/deployment architecture.
7. `docs/DATA_MODEL.md` — control-plane and semantic data contracts.
8. `docs/INTEGRATION.md` — adapter and external-system integration contracts.
9. `docs/DEFINITION_OF_DONE.md` — release acceptance.
10. `docs/MASTER_PLAN.md` — execution order and milestones.
11. Supporting documents: DAD coverage, Ferma testbed blueprint, compatibility, test strategy, SRE/observability, risks and vendor intake.

No lower-precedence document may silently weaken a higher-precedence invariant.

## Core package

| Document | Purpose |
|---|---|
| [Scope Freeze Baseline](SCOPE_FREEZE_BASELINE_2026-10-06.md) | Operator-approved current scope, anti-scope-creep rule, committed vs deferred lanes and freeze-release barrier |
| [TDD](TDD.md) | Technical Design Document: goals, requirements, constraints, invariants |
| [Master Plan](MASTER_PLAN.md) | Delivery phases, gates, dependencies and exit criteria |
| [Data Model](DATA_MODEL.md) | PostgreSQL control-plane schema and canonical semantic model |
| [Governance](GOVERNANCE.md) | Change classes, review rules, evidence, licensing and destructive-action policy |
| [Definition of Done](DEFINITION_OF_DONE.md) | Product, security, accounting and operations release gates |
| [Architecture](ARCHITECTURE.md) | Context, containers, components, trust boundaries and deployment |
| [Integration](INTEGRATION.md) | Internal adapter contract and external integration rules |
| [Pinned OData sidecar contract](ADAPTER_CONTRACT_ODATA_SIDECAR.md) | Private ERP_MCP ↔ pinned OData sidecar API and source-capability rules |
| [RSV Data bridge runbook](runbooks/RSV_DATA_BRIDGE.md) | Isolated Windows/COM sidecar setup, source binding, ACL and recovery boundaries |
| [Semantic profiles and presets](SEMANTIC_PROFILES.md) | Candidate preset, source/company profile lifecycle, validation evidence and operator CLI |
| [Native 1C report capture runbook](NATIVE_REPORT_CAPTURE_RUNBOOK.md) | Evidence classes, the ten proposed native report cases, capture/hash/record procedure and the read-only engine-report generator (PROPOSED until accountant approval) |
| [Test Strategy](TEST_STRATEGY.md) | L1/L2/L3 verification, security, load and reconciliation |
| [Manual QA environment and acceptance guide](QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md) | Windows L1 setup and separate manual data-plane user/Admin suites, with all 12 synthetic scenario IDs |
| [Manual acceptance — simple user](MANUAL_ACCEPTANCE_USER.md) | Step-by-step owner acceptance pack for a non-admin data-plane identity (U cases, SC01-SC12 spot checks) |
| [Manual acceptance — Admin Control Center](MANUAL_ACCEPTANCE_ADMIN.md) | Step-by-step owner acceptance pack for Admin identities and roles (A cases), separate credentials from the user pack |
| [E2E acceptance contract (frozen)](E2E_ACCEPTANCE_CONTRACT.md) | Frozen U01-U18 data-plane and A01-A54 Admin automated/manual acceptance matrix with actor, expected, negative, evidence and external gates |
| [Local E2E environment](E2E_ENVIRONMENT.md) | Disposable localhost-only environment: compose, test IdP, seed modes, reset/fault scripts and e2e fixtures |
| [Functional Tester autonomous assignment](FUNCTIONAL_TESTER_AUTONOMOUS_PROMPT.md) | Task prompt and deliverable contract for executable black-box tests of the scenario pack |
| [SC08 duplicate-counterparty detection contract](SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md) | Frozen read-only detection semantics for SC08 (fields, normalisation, grouping, two-phase company scope, truncation, schema, privacy, mutation matrix) under the 2026-10-07 operator rebaseline |
| [Functional Tester report SC01-SC12](../reports/FUNCTIONAL_TESTER_SC01_SC12.md) | Black-box SC01-SC12 results on the exact candidate code (synthetic L1), skip/xfail dispositions, upstream traffic and hygiene scan |
| [Branch and merge readiness](../reports/BRANCH_MERGE_READINESS.md) | Branch/PR inventory and post-acceptance merge sequence |
| [Observability & SRE](OBSERVABILITY_SRE.md) | Signals, SLO objectives, alerts, runbooks and rollback |
| [Pilot evidence gate](PILOT_EVIDENCE_GATE.md) | P9 evidence manifest, validation contract and production GO conditions |
| [Risk Register](RISK_REGISTER.md) | Principal technical, accounting, security, licensing and operational risks |
| [Threat Model](THREAT_MODEL.md) | Assets, trust threats, STRIDE controls and residual risk |
| [Admin Control Center](admin-control-center/README.md) | Browser control-plane design, implementation contract and operator runbook |
| [Requirements Traceability](REQUIREMENTS_TRACEABILITY.md) | Requirement → design → DoD/evidence mapping |

## Existing normative/supporting documents

- [S12/S13 disposable qualification prerequisites](phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md) — entry conditions, acceptance-mapped COM fixture/STA/result, PostgreSQL deadline/lock-error, registry/replay/global-ID/grant scenarios including `S13-TOKEN-RANK-01`, `S13-COUNTER-RANK-01`, `S13-BUDGET-RANK-01`, `S13-BEGIN-APPLY-IDENTITY-01`, `S13-BEGIN-APPLY-LOCK-CALL-ID-01`, `S13-PROPOSE-RANK-01`, `S13-CHECKPOINT-ORDER-01`, `S13-DISPATCH-REQUIREMENT-01`, `S13-PHYSICAL-AUTHORITY-DISPATCH-01`, `S13-RECOVERY-ROWS-01`, `S13-UNIQUE-ARBITRATION-01`, `S13-OBSERVE-REPLAY-01`, `S13-EVIDENCE-REPLAY-01`, `S13-VERIFY-EVIDENCE-ID-01`, `S13-VERIFY-PAYLOAD-ID-01`, `S13-INVOCATION-CONTEXT-BINDING-01`, `S13-RECEIPT-LOOKUP-KEY-SHAPE-01`, `S13-TRUSTED-VALIDATION-TIME-01`, `S13-FK-RESOURCE-OWNER-SCOPE-01`, `S13-LEGACY-MUTATOR-CUTOVER-ACL-01` and `WP5-JSON-DECODER-01`, exact evidence and test-owner contract for disposable qualification; does not approve a migration or enable admission.
- [WP2 effective-grants recheck](phase2/artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-22.md) — read-only disposable PostgreSQL role/grant evidence, including the current continuation's direct control-role retry; does not measure S13 grants because `change_ledger` is absent.
- [WP2 effective-grants recheck — 2026-10-26](phase2/artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-26.md) — current read-only PostgreSQL catalog evidence; S13 grants remain `NOT_MEASURABLE` because the candidate schema and routines are absent.
- [WP0 access and source recheck — 2026-10-24](phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md) — current SSH, local/remote MCP auth and listener observations, credential-file ACL remediation, and bounded COM diagnostics; no writer qualification or S13 grants are claimed.
- [WP0 Ivan stack status — 2026-10-26](phase2/artifacts/WP0_IVAN_STACK_STATUS_2026-10-26.md) — strict SSH status, local listener/OData-denial observations, authenticated source health, and a value-hidden two-copy read; no restart, native 1C PASS, writer, current COM license, or grant claim.
- [WP0/WP2 current-turn recheck — 2026-10-26](phase2/artifacts/WP0_WP2_CURRENT_TURN_RECHECK_2026-10-26.md) — read-only Ivan stack, local ERP MCP source health, and disposable PostgreSQL catalog evidence from this turn; S13 grants remain not measurable.
- [Autonomous engineering checkpoint — 2026-10-24](../reports/ERP_MCP_AUTONOMOUS_CHECKPOINT_2026-10-24.ru.html) — bilingual acceptance matrix and evidence-based next-step handoff; intermediate status, not project completion.
- [S13 PostgreSQL admission schema design](phase2/S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md) — proposed durable admission/barrier contract and versioned SQL type/signature surface; no schema or routines are asserted installed.
- [S13 evidence registration context boundary](phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md) — exact verifier, attempt-context, trusted-clock and build-provenance requirements before evidence registration can be composed; includes strict trust-snapshot JSON decoding; no registrar is enabled.
- [S13 Python UUID contract](phase2/S13_PYTHON_UUID_CONTRACT_2026-10-25.md) — shared canonical/nonzero UUID predicates and process-instance version/variant rules across Python admission, evidence, trust and storage boundaries; source-only and not runtime-qualified.
- [Change record 172 — S13 cosign entries](phase2/CHANGE_RECORD_172.md) — ungranted versioned T16 and anchor-gap cosign candidates, exact replay identities, parent locking and qualification state.
- [Change record 173 — S13 witnessed failed-verification closure](phase2/CHANGE_RECORD_173.md) — revoked T17 candidate and opt-in adapter route; FK-SCC/runtime qualification remains open.
- [Change record 174 — S13 checkpoint permit-signature attachment](phase2/CHANGE_RECORD_174.md) — revoked candidate and opt-in adapter route; deployed grants and lifecycle/key-revocation qualification remain open.
- [Change record 175 — T16 witness cosign for entered conditional conflict](phase2/CHANGE_RECORD_175.md) — ungranted nonterminal cosign extension; operator resolution and disposable qualification remain open.
- [Change record 176 — typed S13 operator-resolution adapter contract](phase2/CHANGE_RECORD_176.md) — historical adapter-only snapshot; its open items were advanced in change record 177 but remain unqualified.
- [Change record 177 — T16 checkpoint holds and replay](phase2/CHANGE_RECORD_177.md) — candidate T16 event/checkpoint/hold continuation, fail-closed replay, and remaining runtime qualification gaps.
- [Change record 178 — private writer composition and outcome evidence](phase2/CHANGE_RECORD_178.md) — dependency wiring and typed S12 outcome-bundle registration, without listener startup or runtime qualification.
- [Change record 178 — private writer composition root](phase2/CHANGE_RECORD_178.md) — explicit private-process dependency wiring, without listener startup or runtime qualification.
- [Change record 179 — S12 COM manifest digest primitives](phase2/CHANGE_RECORD_179.md) — deterministic value-minimizing property and operation manifest digests; does not supply or qualify the clone crosswalk.
- [Change record 180 — unique Windows service SID for writer mutex](phase2/CHANGE_RECORD_180.md) — fail-closed mutex-principal validation; Windows behavior remains untested.
- [Change record 181 — private writer JWT caller policy](phase2/CHANGE_RECORD_181.md) — verifier-backed private audience, write scope, and explicit client allowlist; no listener is wired.
- [Change record 182 — loopback private writer ingress](phase2/CHANGE_RECORD_182.md) — bounded authenticated dispatch/lookup ASGI adapter; socket binding and runtime qualification remain open.
- [Change record 183 — exact private writer caller scope](phase2/CHANGE_RECORD_183.md) — exact client-to-ledger/base grants and separate dispatch verification vs historical lookup authorization; provisioning and qualification remain open.
- [Change record 276 — S13 legacy fence-check cutover](phase2/CHANGE_RECORD_276.md) — candidate revokes the point-in-time writer preflight and blocks its S13 adapter route; effective grants and recovery-race qualification remain open.
- [Change record 281 — prevent cross-base call-ID lookup disclosure](phase2/CHANGE_RECORD_281.md) — candidate exact-call and barrier lookups return base-scoped absent results without revealing foreign-base existence; SQL/runtime qualification remains open.
- [Change record 282 — bound S12 envelope decoder structure](phase2/CHANGE_RECORD_282.md) — evidence-envelope preflight counts object keys and values under a lower structural-node budget before JSON allocation; parser resource qualification remains open.
- [Change record 283 — bound private-writer JSON structure before decoding](phase2/CHANGE_RECORD_283.md) — shared preflight bounds S12 evidence and private-ingress JSON trees before allocation; functional/E2E boundary qualification remains open.
- [Change record 284 — revalidate the bounded stale-revocation prefix](phase2/CHANGE_RECORD_284.md) — fixes candidate snapshot comparison for budget-limited S13 recovery batches; SQL review and disposable qualification remain open.
- [Change record 285 — preserve combined recovery stage rank](phase2/CHANGE_RECORD_285.md) — explicitly orders bounded S13 recovery arrays by the documented retry ranks; SQL review and disposable qualification remain open.
- [Change record 286 — close lifecycle-fence and scope revalidation gaps](phase2/CHANGE_RECORD_286.md) — nine S13 paths require lifecycle rows and 15 role-scope mutation routes recheck after lifecycle locking; SQL review and disposable qualification remain open.
- [S13 Ivan private writer service design](phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md) — private licensed-lane writer boundary, serving-epoch and barrier-replay contract, including the process-local fatal-latch/terminal-mutation ordering; SQL, listener, and operational COM behavior remain unimplemented or unverified.
- [S13 source grant and lock inventory](phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md) — source-derived API/grant/lock map, qualification cross-references and explicit unresolved proof gaps; not evidence of installed grants or a complete wait graph.
- [S13 scope-fence implementation design](phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md) — source-wide mutation/recovery lock order and crosswalk with dated candidate progress; migration 027 remains uninstalled and the design is not runtime proof.
- [1C compatibility](COMPATIBILITY.md)
- [Adapter census](ADAPTER_CENSUS.md)
- [Adapter intake plan](ADAPTER_INTAKE_PLAN.md)
- [MVP scope](MVP_SCOPE.md)
- [Production deployment contract](../deploy/PRODUCTION.md)
- [Security model](../SECURITY.md)
- [Vendor sources](../vendor/UPSTREAMS.md)
- [Machine-readable vendor intake](../vendor/intake.json)
- [Testbed](../testbed/README.md)
- [Ferma → 1C Synthetic Testbed & Reconciliation — Implementation Blueprint](FERMA_1C_SYNTHETIC_TESTBED_IMPLEMENTATION.md) — proposed supporting implementation plan for deterministic Ferma-driven real-1C L2 reconciliation; does not override higher-precedence invariants.
- [DAD 1C MCP Requirements & Scenario Coverage](DAD_1C_MCP_REQUIREMENTS_COVERAGE.md) — audited source-of-problem, link/material inventory, full scenario lanes, current implementation gaps and DAD acceptance priorities.

## Architecture decisions

- [ADR-0001 — Read-only 1C production MVP](adr/ADR-0001-read-only-mvp.md)
- [ADR-0002 — Separate control plane and 1C data planes](adr/ADR-0002-control-data-plane.md)
- [ADR-0003 — Reuse-before-rewrite](adr/ADR-0003-reuse-before-rewrite.md)
- [ADR-0004 — Behavior-first capability routing](adr/ADR-0004-capability-routing.md)
- [ADR-0005 — No direct 1C SQL integration](adr/ADR-0005-no-direct-1c-sql.md)
- [ADR-0006 — Copyleft adapter isolation](adr/ADR-0006-copyleft-isolation.md)
- [ADR-0007 — Admin Control Center boundary and authorization](adr/ADR-0007-admin-control-center.md)
- [ADR-0008 — Hybrid OData + COM analytics balance route](adr/ADR-0008-hybrid-odata-com-analytics-balance.md)
- [ADR-0009 — Isolated private writer for disposable 1C qualification](adr/ADR-0009-private-test-writer.md)

## Change rule

A change to any invariant marked **MUST**, **MUST NOT**, **HARD BOUNDARY** or **FAIL-CLOSED**
requires:
- an ADR or amendment;
- explicit impact analysis;
- tests/evidence for the new behavior;
- update to affected documents;
- governance approval before implementation is treated as complete.

Documentation is part of the product. A release with stale normative documents is not Done.

### Scope-freeze rule

While `SCOPE_FREEZE_BASELINE_2026-10-06.md` is active, every new issue/PR/task must cite the
existing frozen requirement/gate it closes. A task without such a trace is scope expansion and is
blocked until explicit operator rebaseline. Security/defect/DoD-evidence work required to complete
an existing frozen requirement is scope-preserving.
- [Change record 287 — hold serving authority across private-writer dispatch](phase2/CHANGE_RECORD_287.md) — extends the base-scoped OS mutex across admitted COM calls and cancellation cleanup; two-process disposable qualification remains not run.
- [Change record 288 — keep serving mutex ownership off the event-loop thread](phase2/CHANGE_RECORD_288.md) — dedicated owner thread, thread-independent logical lease, and close refusal while active; Windows cross-process qualification remains not run.
- [Change record 289 — drain private-writer operations before runtime close](phase2/CHANGE_RECORD_289.md) — bounded dispatch/barrier drain, COM close, then mutex close; runtime shutdown acceptance remains not run.
- [Change record 290 — bound the complete private-writer close sequence](phase2/CHANGE_RECORD_290.md) — one close deadline and serialized retryable runtime close; timeout and concurrency acceptance remains not run.
- [Change record 291 — drain accepted control operations during runtime shutdown](phase2/CHANGE_RECORD_291.md) — drains accepted startup recovery/barriers, blocks readiness reopening and rejects new control work after shutdown; race acceptance remains not run.
- [Change record 292 — keep Windows mutex waits off the service event loop](phase2/CHANGE_RECORD_292.md) — awaitable authority acquire/release/close and fail-closed cancellation; Windows responsiveness acceptance remains not run.
- [Change record 293 — make mutex owner-thread close single-flight](phase2/CHANGE_RECORD_293.md) — preserves one close command across repeated cancellation/retry; Windows cancellation acceptance remains not run.
- [Change record 294 — bind private ingress to prepared runtime lifecycle](phase2/CHANGE_RECORD_294.md) — refuses unprepared ASGI startup and drains runtime after listener shutdown; host lifecycle acceptance remains not run.
- [Change record 295 — require runtime ownership for every private ingress factory](phase2/CHANGE_RECORD_295.md) — removes the lifecycle-free app-construction path; factory and shutdown acceptance remains not run.
- [Change record 296 — reject mismatched resource FK owners before row locking](phase2/CHANGE_RECORD_296.md) — validates selected FK owner scope/base across nine candidate paths; disposable acceptance remains not run.
- [Change record 297 — bound revoke-stale resource plans](phase2/CHANGE_RECORD_297.md) — caps frozen/revalidated resource rows and uses a total target lock order; recovery qualification remains not run.
- [Change record 298 — align hold plans to target registry identity](phase2/CHANGE_RECORD_298.md) — deduplicates new holds by base and separates target-parent identity from target-lock references; qualification remains not run.
- [Change record 299 — bound combined anchor-check row plans](phase2/CHANGE_RECORD_299.md) — enforces the aggregate target/open-hold plan limit and stable refusal class; qualification remains not run.
- [Change record 300 — revalidate release-claim mutation preconditions](phase2/CHANGE_RECORD_300.md) — refuses stale parents and absent/non-owned target locks before mutation while preserving exact replay; qualification remains not run.
- [Change record 301 — preserve idempotent kill-switch OFF](phase2/CHANGE_RECORD_301.md) — makes an already-OFF request a no-write/no-event return while keeping stopped-mode recovery fail-closed; qualification remains not run.
- [Change record 302 — make lease-generation comparison null-safe](phase2/CHANGE_RECORD_302.md) — classifies a NULL generation as `TICKET_SUPERSEDED` before permit checks; qualification remains not run.
- [Change record 303 — refuse stale lease generations before child locks](phase2/CHANGE_RECORD_303.md) — reviewed source order returns `TICKET_SUPERSEDED` before child locks; disposable SQL qualification remains not run.
- [Change record 304 — reduce bounded trust-payload preflight overhead](phase2/CHANGE_RECORD_304.md) — expanded offline decoder acceptance: 20 tests and 54 subtests passed; full WP5 signer/trust acceptance remains open.
- [Change record 305 — add safe DPAPI signer-key provisioning primitive](phase2/CHANGE_RECORD_305.md) — mocked provisioning acceptance passed; real Ivan-host provisioning, identity/scope registration and signer qualification remain open.
- [Change record 306 — repair and qualify candidate S13 admission SQL](phase2/CHANGE_RECORD_306.md) — migration 027 parses in a disposable cluster and three mapped SQL scenarios pass; full S13 qualification and effective installed grants remain open.
- [Change record 307 — normalize private-writer ACLs across the candidate schema](phase2/CHANGE_RECORD_307.md) — current-hash source reviews found no actionable ACL finding; seeded-role qualification and effective installed grants remain open.
