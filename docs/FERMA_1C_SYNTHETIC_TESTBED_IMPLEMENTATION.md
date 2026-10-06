# Ferma → 1C Synthetic Testbed & Reconciliation — Implementation Blueprint

**Status:** PROPOSED IMPLEMENTATION BLUEPRINT
**Date:** 2026-10-06
**Scope:** ERP_MCP P5 real-1C reconciliation, P6 COM/extension test boundary, future legacy test lanes
**Primary repos:** `ERP_MCP` and `ERP-Virtual-Economy-Digital-Business-Universe` (Ferma)
**Normative precedence:** this document is supporting architecture. It MUST NOT weaken SECURITY.md,
GOVERNANCE.md, accepted ADRs, TDD.md, ARCHITECTURE.md, DATA_MODEL.md, INTEGRATION.md or
DEFINITION_OF_DONE.md.

---

## 1. Executive decision

ERP_MCP MUST NOT build a second synthetic-business-data generator.

Ferma already owns the reusable pieces required to create reproducible business worlds:

- deterministic simulation and seeded randomness;
- logical business time;
- deterministic identities;
- canonical companies, products, locations and relationships;
- canonical economic events;
- N-tier company/supply-chain generation;
- payment/settlement flows;
- credit notes and partial invoicing;
- inventory movement/return scenarios;
- independent expected/oracle projection;
- ERP command and observation port separation;
- evidence/reproduction concepts.

ERP_MCP will reuse those capabilities through a **test-only integration boundary**.

The target architecture is:

```text
                     FERMA
          deterministic synthetic universe
                      |
          canonical scenario package
                      |
          +-----------+--------------------+
          |                                |
          v                                v
   Ferma independent                 1C Test Seeder
        Oracle                     (WRITE, TEST ONLY)
          |                                |
          |                                v
          |                        real 1C test base
          |                                |
          |                 +--------------+-------------+
          |                 |                            |
          |                 v                            v
          |          Native 1C reports             ERP_MCP runtime
          |          / observations                READ-ONLY only
          |                 |                            |
          +-----------------+-------------+--------------+
                                          |
                                          v
                                Reconciliation Harness
                                          |
                                          v
                                  immutable evidence
```

The production ERP_MCP gateway remains read-only.

The write-capable 1C seeder exists only to construct disposable synthetic test bases. It is not a
production adapter, is not reachable from MCP clients, and is not packaged into the production
runtime.

---

## 2. Why this architecture

### 2.1 Avoid correlated false green

Expected results MUST NOT be derived from the system under test.

Ferma ADR-002 establishes deterministic simulation. Ferma ADR-004 establishes logical simulation
time. Ferma ADR-012 separates:

- business-level ERP commands;
- read-only ERP observation;
- the independent oracle.

Ferma's test-data/harness contract explicitly prohibits reading ERP results into the oracle or
adjusting the oracle when the ERP disagrees.

ERP_MCP must preserve that separation.

### 2.2 Test real 1C behavior, not our own emulation

The synthetic data is delivered as normal 1C business documents and processed by normal 1C posting
logic.

The seeder MUST NOT populate accounting registers or internal SQL tables directly merely to make an
expected balance appear.

Required shape:

```text
Ferma business fact
      |
      v
configuration-specific 1C business document
      |
      v
Записать()/Провести() in disposable test base
      |
      v
native 1C posting logic
      |
      +--> registers / accounting state
      |
      +--> native report
```

This is what makes the reconciliation meaningful.

### 2.3 Preserve ERP_MCP production security

Production policy remains:

- source/company authorization before adapter execution;
- no production write API;
- no direct internal 1C SQL;
- fixed registered targets only;
- secrets resolved server-side;
- fail closed;
- bounded execution;
- raw accounting payload not retained by default.

The test seeder is a separate trust boundary with separate credentials and separate entry points.

---

## 3. Source-derived foundations

### 3.1 ERP_MCP foundations

Existing ERP_MCP architecture already defines:

- read-only 1C MVP as a hard boundary;
- P5 as real 1C testbed/native-report reconciliation;
- P6 as isolated extension/COM fallback;
- future Ferma integration without allowing live ERP/1C observations into expected/oracle
  computation;
- source != company;
- profile-driven accounting semantics;
- reconciliation cases/runs as durable correctness evidence.

### 3.2 Ferma foundations

Existing Ferma implementation/docs provide:

- deterministic seeded simulation;
- logical simulation clock;
- context-derived deterministic IDs;
- canonical master data/events;
- company-chain generation;
- independent oracle;
- business-level ERP command contracts;
- read-only observation contracts;
- explicit partial-delivery/mismatch semantics;
- reproduction provenance: source/profile/mapping/generator/seed/scenario/company/tick.

No part of this blueprint should duplicate those concepts in ERP_MCP unless a transport-neutral
artifact contract is required between repositories.

---

## 4. Repository ownership and boundaries

### 4.1 Ferma owns

Ferma remains authoritative for:

- synthetic economy profiles;
- deterministic generation;
- canonical companies/products/locations/relationships;
- canonical business events;
- logical business time;
- independent expected/oracle projections;
- scenario semantics;
- generator version and scenario provenance.

ERP_MCP MUST NOT fork or copy Ferma generator/oracle logic.

### 4.2 ERP_MCP owns

ERP_MCP owns:

- the real 1C testbed lifecycle;
- source/configuration capability discovery;
- 1C semantic profiles;
- Ferma-canonical → concrete-1C mapping profiles;
- test-only 1C command/seeding adapter;
- production read-only 1C observation path;
- native 1C report capture;
- ERP_MCP semantic result capture;
- reconciliation evidence storage;
- source/company authorization tests;
- capability and metadata fingerprints.

### 4.3 Cross-repo coupling rule

Do not make production ERP_MCP import Ferma Python modules at runtime.

Use one of these in priority order:

1. versioned scenario-package artifact;
2. pinned Ferma CLI/subprocess in CI/testbed;
3. development-only Python dependency if and only if isolated from production packaging.

The long-term preferred boundary is a versioned scenario package.

---

## 5. Scenario package contract

Create a stable artifact format, for example:

```text
ferma-scenario-v1/
  manifest.json
  master-data.jsonl
  events.jsonl
  expected/
    positions.jsonl
    correspondences.jsonl
    inventory.jsonl
  checksums.sha256
```

### 5.1 Manifest

Minimum fields:

```json
{
  "schema_version": "ferma-1c-scenario/v1",
  "scenario_id": "bp3-reconciliation-v1",
  "run_id": "...",
  "universe_id": "...",
  "master_seed": 123456,
  "generator_version": "...",
  "ferma_commit": "...",
  "profile_id": "...",
  "profile_digest": "sha256:...",
  "logical_clock_epoch": "...",
  "mapping_contract_version": "1",
  "created_at_wall_clock": "...",
  "semantic_digest": "sha256:..."
}
```

Wall clock is metadata only and MUST NOT affect economic output.

### 5.2 Master-data records

Use Ferma canonical IDs. At minimum:

- companies;
- products;
- locations;
- currencies;
- units of measure;
- relationships;
- employees when the scenario requires them.

### 5.3 Event records

Reuse canonical event schemas. The package MUST contain business facts, not expected ERP-derived
answers.

Examples:

- trade;
- payment/settlement instruction;
- credit note;
- partial invoice;
- inventory movement;
- inventory return;
- other future canonical business facts.

### 5.4 Expected records

Oracle output belongs in a separate expected namespace/file.

The seed adapter MUST NOT read expected output when creating 1C documents.

This separation should be mechanically testable.

---

## 6. Three independent result planes

A reconciliation run has three logically different views.

### Plane A — Ferma economic oracle

Purpose:

- independent economic expectation;
- cross-company obligations;
- inventory and settlement invariants;
- deterministic scenario truth.

It does not know how 1C implements a report or chart of accounts.

### Plane B — native 1C observation

Purpose:

- configuration-specific actual behavior;
- standard report results;
- posted-document identities;
- native register/accounting consequences.

For ERP_MCP accounting correctness, this is the primary source-specific reference.

### Plane C — ERP_MCP result

Purpose:

- prove that ERP_MCP reads/interprets the same 1C state correctly;
- prove company isolation, routing and semantic mappings;
- prove provenance, limits and failure behavior.

### Required comparison rules

For a source-specific semantic tool:

```text
ERP_MCP result == native 1C result
```

is mandatory within declared tolerances.

Where a Ferma economic concept maps cleanly to the native report:

```text
Ferma Oracle == native 1C scoped economic invariant
```

is also required.

A mismatch MUST remain visible. Never modify the oracle/profile automatically to make a run green.

---

## 7. Test levels

### L1 — Fake1C / contract tests

Fast CI.

Proves:

- routing;
- ACL;
- serialization;
- bounds;
- negative capability behavior;
- adapter failure semantics.

Does not prove real 1C accounting correctness.

### L2 — Ferma → real 1C synthetic testbed

Required for MVP semantic validation.

Proves:

- real 1C document posting;
- real metadata/capabilities;
- real reports;
- real COM/OData behavior;
- ERP_MCP reconciliation;
- company isolation on deterministic synthetic businesses.

### L3 — pilot/target evidence

Real controlled customer/target environment.

Proves:

- real configuration behavior;
- production identity/network/secrets;
- target-specific report reconciliation;
- operational readiness.

L2 cannot be called L3. L3 cannot be fabricated from synthetic evidence.

---

## 8. Local 1C environment already established

Current local engineering evidence as of 2026-10-06:

- 1C:Enterprise 8.3.27.2342 x64 full platform installed per-user;
- Community/Developer License active;
- `V83.COMConnector` creates and connects;
- COM registered per-user;
- disposable `RSVDataAudit` infobase exists;
- RSV Data v1.3.0 installed and active;
- COM bridge diag/ping PASS;
- MCP initialize/tools/list/config/describe PASS;
- RSVData CFE exported to XML/BSL and audited.

This environment is useful for P6 bridge/security testing.

It is **not** the accounting reconciliation base.

Create a separate test base, e.g.:

```text
D:\ERP_MCP_Testbed\1c\bases\AccountingSynthetic
```

with a real licensed/demo accounting configuration.

---

## 9. RSV Data policy after live audit

The live audit found:

- anonymization writes stable-token records to `RSVData_КартаАнонимизации`;
- privileged mode is used around anonymization/token-map operations;
- `reveal` uses a shared token map without ERP_MCP principal/company isolation;
- `execute_query` accepts arbitrary 1C query text;
- returned-row limiting does not bound the cost of the upstream arbitrary query itself;
- the extension does not inject an immutable ERP_MCP company predicate.

Therefore current production disposition is:

| RSV capability | ERP_MCP disposition |
|---|---|
| ping | ALLOW behind ACL |
| config | metadata-only ALLOW candidate |
| describe | metadata-only ALLOW candidate |
| get_structure | metadata-only ALLOW candidate |
| help | metadata-only ALLOW candidate |
| query | DENY by default |
| execute_query | DENY |
| reveal | HARD DENY |
| direct upstream HTTP MCP to AI | DENY |

The synthetic test seeder does not change this production policy.

---

## 10. First target 1C configuration

Choose one exact supported configuration as the first L2 target.

Recommended first target:

- modern 1C 8.3.27 platform;
- a legally obtained development/demo/test accounting configuration;
- exact configuration name/version recorded;
- metadata fingerprint recorded.

Do not claim BP3 mappings until the actual target configuration is identified and fingerprinted.

The `RSVDataAudit` empty configuration must not be used as accounting evidence.

---

## 11. 1C mapping profile

Create a versioned test mapping profile for each concrete configuration.

Example logical structure:

```yaml
profile_id: onec-bp3-ferma-v1
configuration:
  name: ...
  version: ...
  metadata_fingerprint: sha256:...

master_data:
  company:
    ferma: CanonicalCompany
    onec: Справочник/Организации mapping
  party:
    ...
  product:
    ...
  location:
    ...
  currency:
    ...

commands:
  trade:
    seller_leg: ...
    buyer_leg: ...
  settlement: ...
  credit_note: ...
  partial_invoice: ...
  inventory_movement: ...
  inventory_return: ...

native_reports:
  receivable: ...
  payable: ...
  sales: ...
  inventory_balance: ...
  inventory_movement: ...
  cash: ...
  account_turnover: ...
```

The exact 1C object names MUST come from live metadata/profile evidence, not guesses.

Mapping profile lifecycle:

```text
DRAFT
  -> metadata confirmed
  -> command mapping tested
  -> native report mapping tested
  -> >= required reconciliation cases PASS
  -> VALIDATED
```

A metadata fingerprint change makes the profile stale until revalidated.

---

## 12. Test-only 1C command/seeding adapter

### 12.1 Hard boundary

The seeder is WRITE-CAPABLE BY DESIGN and therefore MUST be isolated from production runtime.

Suggested location:

```text
testbed/ferma_onec/
  package.py
  mapping.py
  seeder.py
  idempotency.py
  lifecycle.py
  cli.py
```

Alternative: a separate test-only package/workspace.

### 12.2 Mandatory safeguards

The seeder MUST refuse execution unless all are true:

- target explicitly marked `environment=SYNTHETIC_TEST`;
- target path/ID is allowlisted;
- production marker is absent;
- synthetic-base marker is present;
- scenario manifest validates;
- mapping profile matches metadata fingerprint;
- run_id is present;
- operator/test authorization is explicit;
- no customer source ID is allowed.

Recommended base marker:

```text
ERP_MCP_SYNTHETIC_TESTBED_V1
```

stored in a test-only configuration object/file or control-plane registration.

### 12.3 Credentials

Use a dedicated write-capable **test seeder credential**.

Never reuse it for:

- ERP_MCP production reads;
- the read-only observation adapter;
- native report observation.

Observation credentials should be unable to write.

### 12.4 Commands are business-level

Implement Ferma business facts as configuration-native 1C documents.

Never expose generic test APIs such as:

- insert arbitrary register row;
- insert GL entry;
- execute arbitrary BSL;
- arbitrary object mutation.

No direct internal 1C SQL.

### 12.5 Idempotency

Every seeded business action has a stable key derived from:

```text
scenario_id + run_id + canonical event_id + leg/role
```

Store/recognize the external identity in a test-safe configuration-specific way.

Repeating the same seed run MUST NOT create duplicate economic effects.

---

## 13. Master-data seeding

Create deterministic mappings for:

- Ferma company → 1C organization;
- Ferma counterparty relationship → 1C counterparty/partner;
- Ferma product → 1C nomenclature/item;
- Ferma location → warehouse/location;
- Ferma currency → currency;
- UOM → unit of measure;
- employees only for scenarios that require them.

Use stable synthetic names that include canonical IDs where safe.

Example:

```text
FERMA_CO_BAKERY__CO-BAKERY
FERMA_CO_RETAIL__CO-RETAIL
FERMA_SKU_BREAD__PROD-BREAD
```

Do not use real company/person names.

---

## 14. Business-event seeding

### 14.1 Trade

Input facts:

- seller;
- buyer;
- product;
- quantity;
- unit price;
- currency;
- business date;
- payment terms.

The 1C adapter chooses the correct configuration-native sales/purchase documents.

Do not pass an expected AR/AP total if the ERP should compute it from quantity and price.

### 14.2 Settlement

Input is a payment intention/scope, not an already-derived accounting answer.

The adapter:

1. identifies the correct posted obligation(s);
2. creates the appropriate payment/cash/bank business document;
3. posts it;
4. records resulting external document identity.

### 14.3 Credit note / correction

Map to the configuration-native correction/return/adjustment document supported by the target.

Preserve explicit original-trade identity.

### 14.4 Partial invoicing

Seed the partial business fact, not a fabricated full invoice total.

Verify cumulative and per-instalment correspondence independently.

### 14.5 Inventory movement and return

Use warehouse/business documents.

Never directly manufacture accumulation-register balances.

---

## 15. Native 1C observation adapter

This adapter is read-only.

Suggested location:

```text
testbed/ferma_onec/
  native_observer.py
  report_profiles/
  report_export.py
```

It MUST NOT import seeder write helpers.

### 15.1 Observation types

At minimum:

- posted document identity/status;
- AR;
- AP;
- sales/turnover;
- inventory balance;
- inventory movement;
- cash/bank position;
- account turnover/balance where required;
- per-document correspondence.

### 15.2 Native reports must be independent

Do not implement “native result” by calling the same ERP_MCP semantic function being tested.

Use configuration-native reports/report APIs or another independent native observation path.

If a standard report cannot be automated reliably, use a configuration-specific read-only
observation with independently reviewed mapping, and mark the evidence class accordingly.

---

## 16. ERP_MCP observation path

ERP_MCP is exercised exactly as a client would exercise it:

```text
OAuth/test principal
   -> source/company ACL
   -> capability router
   -> OData/approved adapter
   -> semantic profile
   -> normalized result/provenance
```

Do not bypass gateway authorization in L2 reconciliation.

Capture:

- source_id;
- company_id;
- principal;
- operation/tool;
- adapter profile/version;
- metadata fingerprint;
- semantic profile fingerprint;
- rows/bytes/truncated;
- warnings;
- request/correlation IDs.

---

## 17. Reconciliation harness

Create:

```text
testbed/ferma_onec/reconcile.py
```

or equivalent.

One run should perform:

1. verify scenario package;
2. verify test target marker;
3. verify metadata/profile fingerprint;
4. reset/create disposable base when requested;
5. seed master data;
6. seed business events;
7. confirm posting receipts;
8. capture native 1C observations;
9. capture ERP_MCP observations;
10. load Ferma expected/oracle evidence;
11. compare;
12. write immutable evidence manifest;
13. fail non-zero on mismatch/inconclusive mandatory case.

Never silently retry a mismatch until it turns green.

Retries are transport recovery evidence and must remain visible.

---

## 18. Reconciliation case model

Reuse ERP_MCP's `reconciliation_cases` and `reconciliation_runs` concepts.

Each case includes:

- case_id;
- scenario_id/version;
- Ferma seed;
- company;
- semantic domain;
- source/config version;
- mapping/profile version;
- metadata fingerprint;
- native report/reference;
- comparison rule;
- tolerance;
- required evidence class.

Each run includes:

- commit SHA;
- Ferma commit;
- generator version;
- scenario digest;
- mapping digest;
- 1C platform/config version;
- adapter version/SHA;
- semantic profile fingerprint;
- native result fingerprint;
- ERP_MCP result fingerprint;
- Ferma expected fingerprint;
- PASS/FAIL/INCONCLUSIVE;
- discrepancy;
- evidence paths.

---

## 19. Initial scenario matrix

Do not stop at ten hand-written rows. Use Ferma deterministic generation plus named golden cases.

Minimum explicit golden cases:

| ID | Scenario | Primary proof |
|---|---|---|
| F1C-001 | simple seller trade | sales + AR |
| F1C-002 | buyer leg | AP |
| F1C-003 | full settlement | AR/AP close |
| F1C-004 | partial settlement | remaining obligation |
| F1C-005 | multiple open obligations | correct scope |
| F1C-006 | partial invoice | per-instalment correspondence |
| F1C-007 | credit note | corrected obligation |
| F1C-008 | inventory receipt/movement | stock change |
| F1C-009 | inventory return | reversal/correlation |
| F1C-010 | repeated same party, multiple trades | no aggregate false green |
| F1C-011 | three-company chain | cross-company consistency |
| F1C-012 | fan-in | independent supplier attribution |
| F1C-013 | fan-out | independent buyer attribution |
| F1C-014 | backdated logical business date | period attribution |
| F1C-015 | duplicate delivery/idempotency | one economic effect |
| F1C-016 | one failed leg | explicit partial mismatch |
| F1C-017 | unposted/failed document | excluded/not falsely reconciled |
| F1C-018 | same-name parties | identity not display-name based |
| F1C-019 | multi-company shared product/party | company isolation |
| F1C-020 | metadata/profile mismatch | fail closed |

Additional generated runs should vary:

- seed;
- number of companies;
- network topology;
- quantities/prices;
- logical dates;
- settlement order;
- source/company grouping.

---

## 20. Company-isolation test design

Company isolation is a first-class L2 security test.

Generate intentionally confusing data:

```text
ORG-A:
  shared-looking customer
  SKU-X
  receivable 1000

ORG-B:
  same/similar customer name
  SKU-X
  receivable 5000
```

Request:

```text
principal -> source S -> company ORG-A
```

Expected ERP_MCP result is only ORG-A scope.

Adversarial tests:

- caller asks for ORG-B in filter;
- caller omits organization filter;
- query attempts cross-company join;
- aggregate would be correct only if A+B are summed;
- same-name counterparty ambiguity;
- revoked company grant;
- source allowed but company denied;
- fan-out with one denied company.

All must fail closed or explicitly return per-company scoped results.

No failed/denied company may be silently omitted from a combined total.

---

## 21. Ferma oracle independence enforcement

Mechanically enforce:

- oracle package cannot import ERP_MCP adapter;
- oracle package cannot import 1C seeder;
- scenario package expected files are not visible to seeder code;
- seeder cannot read native report output;
- native observer cannot write;
- comparator receives expected and actual as separate inputs.

Add architecture tests for import boundaries.

This is as important as ordinary unit tests.

---

## 22. Reproducibility

Given:

```text
Ferma commit
generator version
profile digest
mapping version
master seed
scenario version
logical clock
1C configuration/version
ERP_MCP commit
semantic profile fingerprint
```

the same semantic test run must be reproducible.

Store a semantic digest.

Do not require irrelevant byte identity for logs/timestamps.

---

## 23. Reset and lifecycle

Provide CLI:

```text
python -m testbed.ferma_onec generate --scenario bp3-v1 --seed 123456
python -m testbed.ferma_onec reset    --target AccountingSynthetic
python -m testbed.ferma_onec seed     --package <artifact>
python -m testbed.ferma_onec observe-native
python -m testbed.ferma_onec observe-erp-mcp
python -m testbed.ferma_onec reconcile
python -m testbed.ferma_onec run-all
```

Reset must operate only on disposable synthetic targets.

Deletion/recreation of any non-test target remains prohibited.

---

## 24. Evidence layout

Recommended:

```text
D:\ERP_MCP_Testbed\runs\<run_id>\
  manifest.json
  scenario/
  seed/
    receipts.jsonl
    failures.jsonl
  native/
    reports/
    observations.jsonl
  erp_mcp/
    responses.jsonl
    audit_refs.jsonl
  oracle/
    expected.jsonl
  reconciliation/
    cases.jsonl
    summary.json
  checksums.sha256
```

Do not put proprietary 1C distributions/configuration binaries or client data in Git.

Repository reports contain only bounded evidence summaries/hashes/references.

---

## 25. CI model

### Pull-request CI

Always:

- L1 Fake1C tests;
- scenario-package schema tests;
- deterministic generation tests;
- mapping/profile unit tests;
- comparator tests;
- architecture independence tests.

### Self-hosted Windows CI

When 1C testbed runner is available:

- L2 base prepare/reset;
- seed golden package;
- COM/OData smoke;
- native observations;
- ERP_MCP observations;
- mandatory golden reconciliation cases;
- cleanup/snapshot restore.

### Scheduled/nightly

Run broader seed matrix:

- multiple seeds;
- 30/50/100/150 registered-source control-plane scenarios;
- larger company networks;
- failure injection;
- metadata drift;
- bridge restart;
- source timeout.

Synthetic throughput is not automatically production capacity evidence.

---

## 26. Test-only write safety

The test seeder is an explicit exception to production read-only because it is outside production.

Required controls:

- separate executable/module;
- separate credentials;
- separate target registry;
- synthetic-target marker;
- deny production source IDs;
- no MCP exposure;
- no gateway route;
- run_id on every write receipt;
- idempotency;
- complete test audit;
- disposable base backup/snapshot before destructive reset.

Production package/tests should verify the seeder is absent or unreachable.

---

## 27. Secrets

Never place 1C username/password in:

- scenario package;
- Git;
- logs;
- command-line arguments;
- model-visible output.

For local testbed:

- use secret file/provider boundary;
- restrict ACL to current test user/service;
- pass credential references to wrapper;
- scrub environment/process output.

The upstream RSV bridge plaintext config behavior is not acceptable as the production secret source.

---

## 28. Modern 8.3 adapter priority

For production/business reads:

1. confirmed modern OData path where supported;
2. approved semantic mapping;
3. source/company-scoped bounded operations;
4. P6 only for explicitly approved fallback capabilities.

The presence of COM does not make COM the preferred production path.

Capability evidence is authoritative, not version labels alone.

---

## 29. Legacy 8.2 / 7.7 strategy

Legacy support must not block modern MVP.

### 29.1 8.2

Canonical runtime test lane:

```text
ERP_MCP
   -> isolated legacy82 adapter
   -> dedicated Windows VM
   -> exact 8.2 platform/config
```

Properties:

- separate machine/VM snapshot;
- exact version recorded;
- isolated bridge/service;
- narrow read-only contract;
- no GPL code in ERP_MCP core;
- independent capability probe;
- no shared COM registration assumptions with modern host.

Windows containers may be researched as an optimization, but are not the baseline because old
installers, COM registration and host/container Windows-version coupling reduce reproducibility.

### 29.2 7.7

Two lanes:

```text
LEGACY_77_FILE_PARSER
  containerized parser/reference path
  no proprietary runtime required where feasible

LEGACY_77_RUNTIME
  isolated compatible Windows/x86 VM
  only when actual 7.7 runtime behavior is required
```

Do not claim runtime equivalence from file parsing alone.

### 29.3 Common legacy contract

Legacy adapters must normalize to the same internal read envelope as modern sources.

The AI/client should not branch on version.

The capability router chooses the adapter.

---

## 30. Docker use

Docker is appropriate for:

- ERP_MCP gateway;
- PostgreSQL/Redis/local IdP;
- modern OData sidecar;
- test orchestration;
- parsers;
- legacy wrapper APIs.

Do not make “1C runtime must run inside Docker” a requirement.

Real legacy Windows 1C runtime belongs in an isolated VM unless a proven, reproducible Windows
container lane is established for the exact version.

Do not publish proprietary 1C binaries in public container registries.

---

## 31. Failure-injection matrix for L2

Mandatory cases:

- COM bridge process killed;
- bridge restart;
- 1C process unavailable;
- source timeout;
- malformed bridge response;
- metadata fingerprint changed;
- wrong mapping profile;
- seeder duplicate replay;
- one trade leg fails;
- one company denied by ACL;
- native report unavailable;
- observation credential attempts write;
- secret missing/revoked.

Expected behavior must be explicit: FAIL, INCONCLUSIVE, source-scoped partial, or retryable transport
failure. Never silently convert failure into PASS.

---

## 32. Accounting semantics and limits

Do not infer universal accounting rules solely from Ferma.

Ferma provides independent economic expectations.

1C configuration-specific semantics still require:

- exact metadata;
- source-specific semantic mapping;
- native-report reconciliation;
- validated profile.

Tax/VAT and other jurisdiction-specific semantics are out of scope until both:

1. the canonical scenario/oracle expresses the required business facts; and
2. the 1C native report mapping is validated.

Do not invent tax correctness from generic trade data.

---

## 33. Native-report validation rule

A semantic profile cannot become `VALIDATED` merely because:

- a preset exists;
- Fake1C passes;
- Ferma oracle passes;
- one COM/OData query returns plausible values.

It requires the project-defined minimum count of passing native-report reconciliation cases for the
exact source/configuration/profile fingerprint.

Every report reference must be reproducible and attributable.

---

## 34. Proposed implementation structure

ERP_MCP:

```text
testbed/
  ferma_onec/
    __init__.py
    schema.py
    package_loader.py
    target_guard.py
    mapping.py
    seeder.py
    receipts.py
    native_observer.py
    erp_mcp_observer.py
    reconcile.py
    evidence.py
    cli.py
    profiles/
      <first-1c-config>.yaml
    scenarios/
      golden_cases.yaml

tests/
  test_ferma_package_contract.py
  test_ferma_onec_target_guard.py
  test_ferma_onec_mapping.py
  test_ferma_onec_idempotency.py
  test_ferma_onec_oracle_independence.py
  test_ferma_onec_company_isolation.py
  test_ferma_onec_reconciliation.py
```

Ferma:

prefer adding/exporting only the minimal scenario-package builder if no stable artifact command
exists already.

Do not duplicate the ERP_MCP-specific 1C mapping in Ferma unless Ferma governance explicitly
chooses 1C as a native ERP adapter implementation.

---

## 35. Work packages

### WP-0 — architecture freeze

Deliver:

- this blueprint reviewed;
- ADR/governance decision if required;
- ownership boundaries;
- first target configuration identified.

Exit: no ambiguity over oracle/seeder/observer ownership.

### WP-1 — Ferma scenario package

Deliver:

- v1 schema;
- deterministic export;
- manifest/checksum;
- golden package;
- replay test.

Exit: same seed/profile/version -> same semantic digest.

### WP-2 — 1C test target guard

Deliver:

- synthetic marker;
- allowlisted base;
- production refusal;
- separate secret reference;
- lifecycle CLI.

Exit: seeder cannot address production source.

### WP-3 — master-data mapper

Deliver:

- companies;
- parties;
- products;
- locations;
- currency/UOM;
- deterministic external identity.

Exit: idempotent repeated seed.

### WP-4 — business command adapter

Deliver incrementally:

1. seller trade;
2. buyer trade;
3. settlement;
4. credit note;
5. partial invoice;
6. inventory movement;
7. inventory return.

Exit: normal 1C posting only; no direct register/SQL writes.

### WP-5 — native observer

Deliver:

- exact report mappings;
- posted-document identity;
- AR/AP;
- inventory;
- cash/bank;
- turnover/balance where supported.

Exit: read credential cannot write.

### WP-6 — ERP_MCP observer

Deliver:

- real gateway path;
- OAuth/test principal;
- source/company ACL;
- provenance capture.

Exit: no direct adapter bypass in reconciliation.

### WP-7 — comparator/evidence

Deliver:

- three-plane comparison;
- mismatch model;
- evidence manifest;
- non-zero failure exit;
- reconciliation DB integration.

### WP-8 — company-isolation adversarial suite

Deliver all tests in §20.

Exit: no cross-company leak on golden matrix.

### WP-9 — scale and failure injection

Deliver:

- larger Ferma networks;
- bridge/source failures;
- retries visible;
- bounded execution.

### WP-10 — legacy lanes

Only after demand/modern closure:

- 8.2 VM lane;
- 7.7 parser lane;
- optional 7.7 runtime VM.

---

## 36. Definition of Done for this blueprint

### Engineering-complete L2 foundation

- Ferma package is deterministic and versioned;
- seeder writes only to marked synthetic test target;
- writes are business-level and idempotent;
- native observer is read-only;
- ERP_MCP observation goes through gateway/ACL;
- oracle independence is mechanically tested;
- first target 1C configuration fingerprint is pinned;
- >=20 named golden scenarios exist;
- required project minimum native-report reconciliation cases pass;
- same-name/cross-company adversarial cases pass;
- evidence contains all provenance required for replay;
- no production credential/data enters artifacts;
- reset/replay works from clean base.

### Not sufficient for Production GO

L2 synthetic success does not close:

- target customer reconciliation;
- production IdP/secrets/network;
- pilot evidence;
- target-specific tax/legal semantics not represented in the scenario;
- release authority approval.

---

## 37. Non-goals

This work does not:

- turn Ferma into a production ERP_MCP dependency;
- make the production gateway write-capable;
- create a second 1C protocol stack;
- validate every 1C configuration;
- validate VAT/tax automatically;
- make RSVData generic query/reveal production-safe;
- require all old 1C runtimes to be installed now;
- put proprietary 1C binaries in Git or public images.

---

## 38. Immediate next actions

1. Record this design as the working P5 implementation blueprint.
2. Identify/acquire the exact first real accounting configuration for `AccountingSynthetic`.
3. Create the Ferma scenario-package v1 exporter or stable pinned CLI.
4. Create ERP_MCP test-only package loader + synthetic-target guard.
5. Implement only the first master-data + simple trade path.
6. Prove one complete vertical slice:
   Ferma event -> 1C business document -> native report -> ERP_MCP result -> independent comparison.
7. Add buyer/AP side.
8. Add settlement.
9. Expand to credit note/partial invoice/inventory.
10. Build company-isolation adversarial matrix.
11. Only then scale scenario count and legacy variants.

The first milestone is not “generate lots of data”.

The first milestone is one completely reproducible, independently checked vertical slice with
correct evidence boundaries.

---

## 39. Recommended first vertical slice

```text
Ferma:
  2 companies
  1 product
  1 trade
  deterministic quantity/price/date

        |
        v

1C test seeder:
  create/find organizations/parties/product
  create configuration-native sales/purchase documents
  post normally
  return external document IDs

        |
        +------------------------+
        |                        |
        v                        v

Native 1C observer          Ferma Oracle
  AR/AP/report               expected obligation

        |
        v

ERP_MCP:
  same source/company
  validated semantic mapping
  read-only operation

        |
        v

Comparator:
  native vs ERP_MCP: exact/tolerance PASS
  Ferma vs native scoped invariant: PASS
  identities/provenance: PASS
```

Only after this vertical slice is green should the implementation widen.

---

## 40. Final architectural rule

**Ferma tells us what economic world happened.**

**1C decides how that world posts inside the concrete 1C configuration.**

**Native 1C reports tell us what 1C actually believes.**

**ERP_MCP must read and explain that state without crossing authorization boundaries.**

**The oracle, the 1C actual side, and ERP_MCP must remain independent enough that a defect in one
cannot make the others automatically agree.**


---

## 41. DAD source-of-problem coverage amendment

The business source review in `DAD_1C_MCP_REQUIREMENTS_COVERAGE.md` is now a required supporting
input for implementation planning.

It establishes that the final/current DAD priority is the read-only multi-company access/control
problem, while preserving all earlier accounting scenarios in explicit roadmap lanes.

### 41.1 Do not build a universal month-close black box

DAD accountant feedback states that month close is activity/company specific.

Implement a versioned DAD rule-pack layer above validated semantic primitives. Rules require
applicability predicates and explicit evidence dependencies.

### 41.2 Add an External Evidence Plane

Several required scenarios cannot be decided from 1C alone:

- bank statement reconciliation;
- Z/terminal reconciliation;
- customs/CCAC reconciliation;
- VAT/IPC/VEN prechecks;
- invoice PDF reconciliation;
- payroll source-document checks;
- contracts/statutory documents.

External evidence is read-only, fingerprinted, provenance-carrying input. Missing evidence yields
`INCONCLUSIVE/EVIDENCE_REQUIRED`, never a guessed conclusion.

### 41.3 Preserve four delivery lanes

1. current read-only core;
2. read-only DAD semantic/evidence expansion;
3. demand-driven legacy compatibility;
4. future write automation under a separate governance/security model.

The historical invoice/payment/cash-write pilot does not authorize writes in the current gateway.

### 41.4 First DAD acceptance pack

Before attempting the full month-close workbook, implement the accountant-selected six checks:

- account 211 negative quantity/value;
- 211/217 positions with no period movement;
- 221/523 and 224/521 cross-balance anomalies;
- daily negative account-241 cash;
- Z-report vs 1C;
- terminal report vs 1C.

The first four can be built mostly from validated 1C semantic primitives. The latter two require
the external-evidence plane.

Full source mapping, gaps and acceptance criteria are maintained in
`docs/DAD_1C_MCP_REQUIREMENTS_COVERAGE.md`.
