# ERP_MCP Master Plan

**Version:** 1.1
**Date:** 2026-10-06
**Execution mode:** SCOPE-FROZEN, gated, evidence-driven, reuse-before-rewrite

## North star

Deliver a production-ready read-only 1C MCP gateway that can safely serve a changing portfolio of
30–150+ companies, tolerate heterogeneous 1C deployments, and produce accounting answers that are
reconcilable with native 1C reports.

## Active scope freeze

The operator froze further scope additions on 2026-10-06. The authoritative frozen backlog and
completion barrier are defined in `SCOPE_FREEZE_BASELINE_2026-10-06.md`.

No new feature/scenario/adapter/integration family may enter execution until the current committed
scope closes or the operator explicitly rebaselines it. Existing deferred lanes remain recorded but
do not become active by implication.

Current committed scope includes the read-only control/data/semantic plane, DAD business-assurance
rules, External Evidence Plane, dual P5 assurance (real reference + Ferma synthetic), P6 audited
fallback, production hardening and pilot evidence.

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
mapping gates. `receivable_balance` and `payable_balance` expose point-in-time mapped balances, not
aging. `inventory_movements` now reads exact live-metadata register record sets through the pinned
OData sidecar only after a validated source/company profile maps timezone, company field, record
types and positive quantity encoding. `cash_movements` uses the same read-only path only after a
validated source/company profile confirms the exact register, fields, timezone and receipt/expense
literals; upstream presets provide no universal cash-register candidate. `accounting_posting_rows`
is a bounded listing, not a full trace. AR/AP aging, cash-flow reconciliation, tax and complete
posting semantics remain unavailable pending configuration-specific profiles and native reports.

SC08 `duplicate-counterparty` is promoted into the current execution scope by the explicit operator
rebaseline of 2026-10-07 (`docs/SCOPE_FREEZE_BASELINE_2026-10-06.md` §8.1) as exactly one read-only
tool, `counterparty_duplicate_candidates` (`accounting.read`, no migration, no merge/write, no tax-id
matching, synthetic L1 evidence only, never native reconciliation). Semantics are frozen in
[SC08 contract](SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md). Deferred lanes are unchanged and production
stays NO-GO.

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

## P5 — Real 1C testbed & assurance

L1: Fake1C mandatory in CI.

L2 is split into two complementary frozen tracks.

### P5-A — Real Reference

Use the private `REFERENCE_TEST_BASE_A` as a real configuration/known-error regression corpus:

- immutable golden source artifact + SHA-256;
- disposable read-only restored clone;
- exact platform/configuration/metadata fingerprint;
- capability discovery and OData/COM parity where supported;
- native-report inventory and reconciliation;
- accountant-selected DAD checks;
- private invoice/evidence regression corpus;
- no mutation of the golden/reference copy.

### P5-B — Ferma Controlled Synthetic

Use Ferma as the deterministic scenario/oracle owner:

- versioned scenario package;
- independent expected/oracle;
- test-only business-document seeder;
- real 1C posting in a marked disposable synthetic base;
- native observer;
- normal read-only ERP_MCP observer;
- controlled multi-company, edge-case and scale scenarios;
- three-plane reconciliation.

L3: controlled target/server-mode production-parity environment.

Exit:
- >=10 mandatory native-report cases for each production semantic profile, with the broader frozen
  DAD scenario matrix represented at its declared acceptance level;
- real-reference known-error cases remain detectable;
- Ferma oracle independence is mechanically preserved;
- discrepancies are explained/resolved, never waived into PASS.

## P6 — Local/extension/COM fallback

Use approved MIT bridge patterns, preferably `mcp-rsv-data`.

Current implementation status: the local Windows/COM environment is no longer unavailable.
1C 8.3.27.2342 x64 + Community/Developer License + `V83.COMConnector` works in a disposable
engineering environment. Official RSV Data v1.3.0 was installed, exported to XML/BSL and audited;
live metadata operations succeeded.

Production policy remains deliberately narrow:

- metadata allowlist: ping/config/describe/get_structure/help behind ERP_MCP ACL;
- `query`: DENY by default until zero-write + immutable company-scope proof;
- `execute_query`: DENY;
- `reveal`: HARD DENY;
- direct upstream RSV MCP exposure to AI: DENY.

P6 still requires secret-ref binding, lifecycle/reconnect/failure evidence and normalized adapter
contract closure.

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

This phase is demand-driven. No concrete 1C 8.2 target or customer requirement is currently recorded,
so P7 is explicitly deferred for the modern MVP; there is no GPL adapter deployment in this phase.
Reopen only when onboarding identifies a real 8.2.13+ target and owner. Then perform license and
isolation review before integration.

If required:
- keep GPL implementation/service isolated;
- define narrow read-only boundary;
- document license obligations;
- run compatibility/test suite.

No business requirement -> phase remains not started and does not block modern MVP.

Legacy 7.7 follows the same demand gate: prefer an isolated parser/reference lane where sufficient;
use a compatible Windows/x86 VM only when actual 7.7 runtime behavior is required. Do not install a
matrix of old runtimes on the modern 8.3 host.

## P8 — Production hardening

Current implementation status: protected aggregate HTTP metrics are implemented as an initial
slice. Full structured logs/traces, saturation and source metrics, backup/restore drill, image/SBOM
scans, and real deployment evidence remain open.

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

Current implementation status: privacy-safe pilot evidence template and fail-closed validator are
implemented. The checked-in template is `NOT_READY`; no live pilot evidence is claimed. Real
environment evidence and accountable release approval remain external gates.

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

Ferma production adapter:
- remains a future adapter boundary after the 1C MVP;
- read oracle/observer/comparator outputs;
- never let ERP/1C data contaminate expected/oracle calculation.

This does not defer Ferma's already accepted P5-B test/oracle role; P5-B is active committed test
scope, not a production Ferma adapter.

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

During the active scope freeze, every implementation task must cite an existing frozen
requirement/gate. Work that cannot do so waits for explicit operator rebaseline.
