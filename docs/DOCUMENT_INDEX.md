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
