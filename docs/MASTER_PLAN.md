# ERP_MCP Master Plan

**Version:** 1.0  
**Date:** 2026-10-05  
**Execution mode:** gated, evidence-driven, reuse-before-rewrite

## North star

Deliver a production-ready read-only 1C MCP gateway that can safely serve a changing portfolio of
30–150+ companies, tolerate heterogeneous 1C deployments, and produce accounting answers that are
reconcilable with native 1C reports.

## Phase map

| Phase | Name | Primary outcome |
|---|---|---|
| P0 | Documentation & decision freeze | Normative TDD/architecture/data/governance/DoD baseline |
| P1 | Control-plane baseline | OAuth, ACL, registry, secrets, audit, limits, migrations |
| P2 | Capability router | Source fingerprinting and deterministic adapter selection |
| P3 | Modern OData data-plane | Mature upstream OData v3 engine integrated read-only |
| P4 | Semantic accounting layer | Stable transport-independent business tools |
| P5 | Real 1C testbed & reconciliation | L2 evidence against native reports |
| P6 | Local/extension/COM fallback | MIT RSV-data based fallback route |
| P7 | Legacy 8.2 route | Optional isolated legacy service if business need exists |
| P8 | Production hardening | load, observability, backup/restore, incident/rollback |
| P9 | Pilot & production GO | controlled customer pilot, closure evidence |
| P10 | ERP/Ferma adapters | reuse common control plane without weakening domain boundaries |

## P0 — Documentation & decision freeze

Deliver:
- DOCUMENT_INDEX;
- TDD;
- architecture;
- data model;
- integration contract;
- governance;
- DoD;
- test strategy;
- SRE/observability;
- risk register;
- ADRs.

Exit:
- documents are internally consistent;
- security and read-only boundaries are explicit;
- no implementation task lacks a target requirement/gate.

## P1 — Control-plane baseline

Current baseline includes much of:
- OAuth/JWT verification;
- PostgreSQL registry/grants/audit;
- Redis rate limiting;
- secret providers;
- health/readiness;
- migrations/admin CLI;
- CI/security scanning.

Remaining closure:
- continue aligning runtime schema with normative data model through explicit migrations;
- add semantic and reconciliation entities when their implementing phase begins;
- prove least-privilege DB roles in integration CI/deployment;
- complete end-to-end correlation/policy-version and adapter provenance in the audit contract.

Exit evidence:
- unauthorized/wrong audience/scope denied;
- revocation works without restart;
- runtime role cannot mutate registry/grants;
- audit mutation denied;
- all control-plane tests green.

## P2 — Capability router

Deliver:
- behavior-first discovery;
- metadata fingerprint;
- route profiles;
- source capability persistence;
- adapter health/state;
- capability refresh/change detection.

Routes:
- ODATA_V3;
- EXTENSION_HTTP;
- COM_BRIDGE;
- LEGACY_82_ISOLATED;
- UNSUPPORTED.

Exit:
- Fake1C profiles verify route selection;
- unsupported source fails explicitly;
- metadata/schema drift is visible and auditable.

## P3 — Modern OData data-plane

Rule: do not reimplement the protocol.

Deliver:
- pin/integrate approved `@1c-odata/client` + metadata engine or equivalent pinned sidecar;
- read-only wrapper/contract;
- per-source register virtual-table capability profile from live metadata/probe/profile evidence;
- deny unconfirmed operations with stable `CAPABILITY_UNSUPPORTED` and persist evidence;
- bounded query/entity/count/register operations;
- output shaping/truncation;
- timeout/cancellation;
- per-source concurrency/circuit breaker;
- upstream test parity for filter, parser, register helpers.

Exit:
- modern 8.3 Fake1C contract green;
- real 8.3 test base metadata/query/register smoke green;
- no write operation exposed through internal adapter contract.

## P4 — Semantic accounting

Initial profile/preset foundation is implemented: Aprovodka's pinned preset inventory is exposed as
`CANDIDATE_ONLY` references; migrations 006–009 store source/company-scoped versioned profiles,
mappings, append-only operator lifecycle events, confirmed-mapping state and profile provenance in
audit. The admin CLI rechecks current metadata/capabilities, requires explicit mapping confirmation
and ten passing native-report cases. Canonical `accounting_balance_and_turnovers`,
`sales_documents`, `purchase_documents` and point-in-time `inventory_balance` tools are implemented
behind these gates; `bank_balance` is also available only with the same exact-source capability and
mapping gates. Other canonical domain tools are not yet implemented.

Deliver canonical tools:
- organization/company discovery;
- sales/purchases;
- bank/cash;
- inventory;
- AR/AP and aging;
- account balances/turnovers;
- document movement/posting trace;
- verified VAT/tax views where configuration mapping exists.

Introduce:
- semantic profiles;
- mapping provenance;
- profile/version fingerprint;
- explicit confidence/warnings.
- source/company ACL before any data request;
- auditable mapping confirmation and canonical field projection.

Exit:
- no semantic tool depends directly on a configuration-specific name outside a profile;
- each tool has deterministic synthetic scenarios and reconciliation specification.

## P5 — Real 1C testbed

L1: Fake1C mandatory in CI.  
L2: real file-mode 1C synthetic base.  
L3: server-mode production-parity environment.

Deliver:
- deterministic synthetic seed;
- snapshot manifest;
- >=10 representative accounting cases;
- expected/native-report evidence;
- configuration/platform fingerprints.

Exit:
- reconciled results documented;
- discrepancies explained/resolved, not waived.

## P6 — Local/extension/COM fallback

Use approved MIT bridge patterns, preferably `mcp-rsv-data`.

Deliver:
- isolated process/service integration;
- no secret leakage;
- read-only operation allowlist;
- health/reconnect;
- Windows/COM operational runbook;
- capability route integration.

Exit:
- same normalized adapter contract passes across OData and COM/extension routes.

## P7 — 8.2 legacy route

This phase is demand-driven.

If required:
- keep GPL implementation/service isolated;
- define narrow read-only boundary;
- document license obligations;
- run compatibility/test suite.

No business requirement -> phase remains not started and does not block modern MVP.

## P8 — Production hardening

Deliver:
- OTel logs/metrics/traces or approved equivalent;
- dashboards/alerts;
- load tests;
- source circuit breaking;
- backup/PITR verification;
- secret rotation drill;
- incident and rollback runbooks;
- dependency/SBOM/license evidence;
- container hardening;
- deployment manifests.

Exit:
- operational DoD passes;
- no unresolved blocker/high risk without explicit owner acceptance.

## P9 — Pilot & GO

Pilot:
- small controlled source set;
- real accounting users/questions;
- audit review;
- zero writes;
- reconciliation monitoring.

Production GO only when `DEFINITION_OF_DONE.md` is fully satisfied.

## P10 — ERP/Ferma expansion

ERP:
- use ERP-authorized reporting/API boundary;
- preserve tenant/org RLS;
- never introduce a super-reader.

Ferma:
- read oracle/observer/comparator outputs;
- never let ERP/1C data contaminate expected/oracle calculation.

## Dependency graph

```text
P0
 ↓
P1 → P2 → P3 → P4 → P5 → P8 → P9
                 ↘
                  P6
                   ↘
                    P7 (only if required)

P1 common control plane → P10 after 1C MVP stabilizes
```

## Execution rule

A phase may overlap another only when:
- its inputs/contracts are already frozen;
- it does not bypass an unmet gate;
- evidence remains attributable to exact commit/configuration versions.

“Code exists” is progress, not closure.
