[Reading 275 lines from start (total: 275 lines, 0 remaining)]

# ERP_MCP Scope Freeze Baseline — 2026-10-06

**Status:** FROZEN
**Operator decision:** no new product scope is added until the currently committed scope is implemented and its mandatory evidence is closed.
**Code checkpoint at freeze:** PR #11 branch `integration/1c-mvp-production-candidate`, remote HEAD `65883a5a83fbb369cbd32e5e31af3041f9d7c515`.
**Documentation baseline:** this freeze includes the current normative package plus `DAD_1C_MCP_REQUIREMENTS_COVERAGE.md` and `FERMA_1C_SYNTHETIC_TESTBED_IMPLEMENTATION.md`.
**Exact freeze commit:** pending documentation commit; until then this file and the referenced working-tree documents define the operator-approved baseline.

## 1. Freeze rule

Until the freeze is explicitly lifted/rebaselined by the operator:

- no new product feature family;
- no new business scenario family;
- no new adapter family;
- no new external-system integration;
- no new write capability;
- no new legacy target/version commitment;
- no speculative “nice to have”;
- no scope expansion merely because an upstream library exposes more functionality.

Allowed work is limited to:

1. implementing requirements already present in this baseline;
2. fixing defects/regressions in accepted scope;
3. security, privacy, compliance and license remediation;
4. tests, observability, runbooks, migration/rollback and evidence required by existing DoD;
5. source/configuration-specific mappings needed to complete an already accepted semantic capability;
6. external evidence adapters required by already accepted DAD scenarios;
7. refactoring necessary to complete current scope without changing externally promised behavior;
8. clarification/correction of documentation when it does not add a new product capability.

A discovered dependency that is strictly necessary to satisfy an existing frozen requirement is a
**scope-preserving dependency**, not a new feature. It must be traced to the existing requirement ID.

## 2. Rebaseline authority

Only an explicit operator decision may:

- add a new requirement/scenario family;
- promote a deferred lane into committed execution scope;
- add a new protocol/adapter family;
- expand the production write surface;
- relax a frozen security/read-only invariant.

A rebaseline must update:

- this file/version;
- GOVERNANCE.md;
- MASTER_PLAN.md;
- TDD.md;
- REQUIREMENTS_TRACEABILITY.md;
- DEFINITION_OF_DONE.md when gates change;
- risk/threat model when applicable;
- Engineering Command Center.

## 3. Committed/current execution scope

The freeze applies to the complete read-only 1C/DAD delivery scope already accepted as of this date.

### 3.1 Control plane

- OAuth/OIDC authentication;
- subject/group identity;
- source/company ACL;
- 30–150+ source/company operational target;
- add/revoke without restart/deploy;
- source registry;
- secret references/providers;
- rate/row/byte/time/concurrency limits;
- append-only audit/provenance;
- source/company-scoped operator administration;
- onboarding/offboarding;
- profile/capability drift recovery.

### 3.2 Modern 1C data plane

- capability-first routing;
- exact metadata/configuration fingerprints;
- pinned OData implementation reuse;
- bounded read operations;
- deterministic unsupported behavior;
- OData/COM parity where both are approved/available;
- no direct internal 1C SQL.

### 3.3 Semantic accounting

Current accepted semantic surface includes:

- company discovery;
- account balance/turnovers;
- accounting posting rows/trace foundation;
- sales/purchase documents;
- inventory balance;
- inventory movements;
- cash movements;
- bank balance;
- receivable/payable balances;
- AR/AP aging with real-profile wiring;
- configuration-specific VAT/tax views only when validated;
- source-specific profile lifecycle and native-report reconciliation.

### 3.4 DAD business-assurance layer

Already accepted scenarios are frozen into scope:

- the six accountant-selected small checks;
- invoice/e-factura read-only reconciliation;
- DAD month-close rule packs;
- P&L;
- Cash Flow;
- Balance Sheet;
- tax declaration prechecks (VAT/IPC/VEN) with external evidence/human review;
- payroll prechecks with source documents/human review;
- bank statement reconciliation;
- Z-report reconciliation;
- payment-terminal reconciliation;
- customs/CCAC reconciliation;
- reconciliation-act read/compare workflow;
- missing-evidence semantics: PASS/FINDING/INCONCLUSIVE/EVIDENCE_REQUIRED/CAPABILITY_UNSUPPORTED/ERROR.

### 3.5 External Evidence Plane

Frozen requirements include read-only ingestion/normalization/provenance for evidence already required
by accepted DAD scenarios:

- invoice/e-factura documents;
- bank statements;
- Z reports;
- terminal reports;
- customs/CCAC evidence;
- filed tax declarations and receipts;
- payroll source documents;
- contracts/statutory supporting documents;
- reconciliation acts.

This is not a generic document-management product. New evidence classes require rebaseline unless
they are necessary to satisfy an already listed rule family.

### 3.6 P5 test and assurance

The frozen assurance strategy is dual-track:

**P5-A Real Reference**
- private `REFERENCE_TEST_BASE_A`;
- immutable golden source;
- disposable RO clone;
- optional separate disposable RW clone for test-only historical/future write validation;
- exact configuration/platform/metadata fingerprint;
- real known-error regression;
- invoice corpus reconciliation;
- native 1C reports.

**P5-B Ferma Controlled Synthetic**
- deterministic scenario package;
- independent expected/oracle;
- test-only 1C seeder;
- real 1C posting;
- native observer;
- normal read-only ERP_MCP observer;
- three-plane reconciliation;
- controlled multi-company/edge-case/scale coverage.

L1 Fake1C remains mandatory for fast CI. L3 remains controlled target/pilot evidence.

### 3.7 P6 COM/extension fallback

Frozen P6 policy:

- local 1C 8.3.27.2342/COM engineering environment is valid P6 evidence;
- metadata-only RSV boundary may be expanded only within the audited allowlist;
- `query` stays denied by default until zero-write + company-scope proof;
- `execute_query` stays denied;
- `reveal` stays hard denied;
- generic upstream RSV HTTP MCP is never exposed directly to AI;
- credentials must be secret-ref bound;
- reconnect/timeout/crash/failure evidence remains required.

### 3.8 Production hardening and pilot

- dependency lock/SBOM/provenance;
- vulnerability/license gates;
- SSRF/DNS-to-connect/egress controls;
- structured logs/metrics/traces;
- failure-injection matrix;
- load/capacity evidence;
- Postgres backup/restore/PITR;
- deployment and application rollback;
- secret rotation;
- runbooks/on-call ownership;
- controlled pilot;
- exact release evidence and approval.

## 4. Recorded deferred lanes — frozen but not promoted

These items already exist in project history, therefore they are preserved but are **not part of the
current completion barrier unless separately activated by explicit operator decision or concrete
target demand**.

### 4.1 Legacy 8.2

- isolated Windows VM/service;
- exact target version/configuration;
- GPL boundary/license review;
- narrow normalized read-only contract.

No concrete target -> no implementation expansion.

### 4.2 Legacy 7.7

- containerized parser/reference route where sufficient;
- isolated compatible Windows/x86 VM only if actual runtime behavior is required.

No concrete target -> no implementation expansion.

### 4.3 Future production write plane

Historical/test evidence exists for invoice writes, and future ideas include:

- invoice creation/editing;
- payment creation;
- SFS/cash-register posting.

These remain deferred and **must not be introduced into the current production read-only MCP**.
Promotion requires an explicit new governance/security baseline.

### 4.4 Production ERP/Ferma adapters

The common control plane may be reused later, but production ERP/Ferma adapter expansion remains
deferred. Ferma is active now only as the independent test/oracle lane described in P5-B.

## 5. Current position at freeze

At freeze time:

- PR #11 is Draft and mergeable;
- remote candidate HEAD is `65883a5a83fbb369cbd32e5e31af3041f9d7c515`;
- hosted CI run `37446049853` completed successfully on this head;
- current code already has substantial control-plane, OData, semantic, Fake1C, ACL/load,
  audit/provenance, supply-chain and operational-hardening evidence;
- local 1C 8.3.27.2342 + Community/Developer License + `V83.COMConnector` works;
- official RSV Data v1.3.0 was installed in a disposable base, exported/audited and metadata smoke
  succeeded;
- the private DAD source materials were reviewed and all evidenced scenarios were assigned to an
  explicit delivery lane;
- a real-reference test base is available privately but still requires local acquisition,
  immutable hashing/restoration and systematic L2 validation;
- Production GO is false.

## 6. Completion barrier that releases the freeze

The operator may lift/rebaseline the freeze only after the **committed/current execution scope** has
reached its required closure state:

1. frozen requirement traceability is complete;
2. all implemented read-only semantic claims are validated against required real/native evidence;
3. P5-A real-reference and P5-B Ferma controlled-synthetic acceptance are complete for frozen
   scenario families;
4. DAD R0–R7 read-only scope is implemented to its declared acceptance level;
5. D0–D18 mandatory production gates are green for the target release/environment, or any
   environment-only items are explicitly separated into PILOT/PRODUCTION evidence without leaving
   locally actionable engineering unfinished;
6. no blocker/high risk is silently deferred;
7. frozen docs and Engineering Command Center match the exact release evidence.

Deferred lanes in §4 do not block this completion barrier unless the operator explicitly promotes
one of them into committed scope.

## 7. Anti-scope-creep review question

Every new issue/PR/task must answer:

> Which existing frozen requirement ID/gate does this close?

If there is no answer, the work is scope expansion and must wait for explicit rebaseline.

[executed on device: Razer (a39db190-4797-4348-a6cc-1ff255947613)]