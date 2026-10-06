# ERP_MCP — Normative Documentation Index

**Baseline:** v1.0  
**Date:** 2026-10-05  
**Status:** FROZEN FOR IMPLEMENTATION  
**Scope:** 1C-first production MVP with future ERP/Ferma adapter boundaries

Interactive view: [ERP_MCP Engineering Command Center](ERP_MCP_ENGINEERING_COMMAND_CENTER.html).

Current implementation evidence: [execution log](../reports/EXECUTION_LOG.md),
[status](../reports/IMPLEMENTATION_STATUS.md), [gap analysis](../reports/IMPLEMENTATION_GAP_ANALYSIS.md),
[DoD status](../reports/DOD_STATUS.md), [risk status](../reports/RISK_STATUS.md), and
[Admin Control Center status](../reports/ADMIN_CONTROL_CENTER_STATUS.md).

This directory is the normative engineering contract for ERP_MCP. Implementation must follow these
documents. A code change that conflicts with the baseline requires an explicit architecture/governance
change first.

## Document precedence

When documents conflict, use this order:

1. `SECURITY.md` — security invariants and trust boundaries.
2. `docs/GOVERNANCE.md` — change authority, review and evidence rules.
3. `docs/adr/` — accepted architecture decisions.
4. `docs/TDD.md` — product/technical requirements.
5. `docs/ARCHITECTURE.md` — system/component/deployment architecture.
6. `docs/DATA_MODEL.md` — control-plane and semantic data contracts.
7. `docs/INTEGRATION.md` — adapter and external-system integration contracts.
8. `docs/DEFINITION_OF_DONE.md` — release acceptance.
9. `docs/MASTER_PLAN.md` — execution order and milestones.
10. Supporting documents: compatibility, test strategy, SRE/observability, risks and vendor intake.

No lower-precedence document may silently weaken a higher-precedence invariant.

## Core package

| Document | Purpose |
|---|---|
| [TDD](TDD.md) | Technical Design Document: goals, requirements, constraints, invariants |
| [Master Plan](MASTER_PLAN.md) | Delivery phases, gates, dependencies and exit criteria |
| [Data Model](DATA_MODEL.md) | PostgreSQL control-plane schema and canonical semantic model |
| [Governance](GOVERNANCE.md) | Change classes, review rules, evidence, licensing and destructive-action policy |
| [Definition of Done](DEFINITION_OF_DONE.md) | Product, security, accounting and operations release gates |
| [Architecture](ARCHITECTURE.md) | Context, containers, components, trust boundaries and deployment |
| [Integration](INTEGRATION.md) | Internal adapter contract and external integration rules |
| [Pinned OData sidecar contract](ADAPTER_CONTRACT_ODATA_SIDECAR.md) | Private ERP_MCP ↔ pinned OData sidecar API and source-capability rules |
| [Semantic profiles and presets](SEMANTIC_PROFILES.md) | Candidate preset, source/company profile lifecycle, validation evidence and operator CLI |
| [Test Strategy](TEST_STRATEGY.md) | L1/L2/L3 verification, security, load and reconciliation |
| [Observability & SRE](OBSERVABILITY_SRE.md) | Signals, SLO objectives, alerts, runbooks and rollback |
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
