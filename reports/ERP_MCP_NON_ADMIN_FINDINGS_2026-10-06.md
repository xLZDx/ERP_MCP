# ERP_MCP — NON-ADMIN FINDINGS BACKLOG

Date: 2026-10-06

Purpose: preserve all findings that do NOT belong to feature/admin-control-center-implementation.
Admin findings are being remediated separately.

## Current ownership rule

Do not fix these items in the Admin branch unless a minimal compatibility change is strictly required.

Primary future workstreams:
1. integration/core remediation
2. runtime/adapters/SRE hardening
3. docs/governance cleanup
4. real 1C assurance/testbed
5. production/release hardening

---

# P0/P1 — Integration/Core remediation

## CORE-01 — metadata transport failure mutates persistent semantic truth
Severity: MAJOR
Status: OPEN

Observed behavior:
- transient $metadata failure can be persisted as a synthetic metadata-error fingerprint;
- source drift becomes DRIFTED;
- VALIDATED semantic profile becomes STALE;
- recovery of metadata does not automatically restore the semantic profile;
- invalidation/recovery lifecycle lacks complete auditable state transition.

Required remediation:
- do not turn transport failure into a durable metadata fingerprint;
- distinguish UNKNOWN/UNREACHABLE from actual schema change;
- define recovery path for STALE profiles;
- audit drift/invalidation/recovery;
- add PostgreSQL integration tests.

## CORE-02 — runtime DB role can update source_capabilities/drift
Severity: MAJOR / production security architecture
Status: OPEN

Observed:
business_ai_app can UPDATE bag.source_capabilities, including drift-related state.

Risk:
compromised runtime can mutate state used to gate semantic correctness.

Required:
- narrow column-level grants or SECURITY DEFINER function with exact contract;
- runtime cannot self-acknowledge or rewrite trusted drift truth;
- startup/CI privilege assertions;
- reconcile SECURITY.md with actual grants.

## CORE-03 — source_capabilities hot-row write churn
Severity: MINOR to MAJOR depending on scale
Status: OPEN

Observed:
identical capability saves still perform UPDATE; repeated calls cause MVCC churn.

Required:
- UPDATE only when values are DISTINCT;
- separate volatile observation timestamps from durable capability truth where appropriate;
- benchmark 30/50/100/150 source portfolios;
- measure dead tuples/index/table growth.

## CORE-04 — generic onec_read policy too broad
Severity: MAJOR
Status: OPEN

Important correction:
company-only grant -> cross-company onec_read exploit was disproved.

Remaining issues:
- generic onec_read is source-wide;
- empty entity allowlist is broad/default-allow;
- expand/select/navigation access is not fully governed by entity policy;
- pagination/truncation semantics are not always explicit.

Required:
- explicit deny-by-default or governed allow policy;
- validate navigation/expand targets;
- explicit has_more/truncated/page semantics;
- keep generic read source-wide, never guess company property.

## CORE-05 — missing/weak behavior tests
Severity: MAJOR test gap
Status: OPEN

Clean mutation passes showed gaps around:
- grant expires_at enforcement;
- source host validation;
- rate-limit threshold behavior.
Some additional mutation results were inconclusive due concurrent scratch changes.

Required:
- clean sequential mutation run;
- targeted behavioral tests;
- no incidental kills from git/checkpoint tests.

---

# P1/P2 — Runtime / Adapters / SRE

## SRE-01 — dependency metrics not wired to all real paths
Severity: MAJOR
Status: OPEN

record_dependency coverage is incomplete for:
- 1C
- sidecar
- RSV
- Redis
- JWKS / auth dependencies

Required:
- instrument real call sites;
- test real failure series;
- verify alerts from runtime metrics, not manually synthesized series.

## SRE-02 — audit failure alert semantics
Severity: MAJOR
Status: OPEN/PARTIAL

Audit insert failure metric exists in newer code, but alert behavior must be verified against first-real-failure time series and sustained error cases.

Required:
- runtime failure injection;
- promtool tests matching emitted series;
- alert receiver evidence later in deployment.

## SRE-03 — OData sidecar resilience
Severity: MAJOR
Status: OPEN

Review concerns:
- breaker error classification should not penalize expected client/policy errors;
- request correlation/logging incomplete;
- shared bearer model;
- credential/cache identity boundaries need review;
- real tool-path concurrency/fanout must be proven.

Required:
- classify 4xx/policy errors separately;
- request_id structured logs;
- credential-sensitive cache identity;
- prove per-source concurrency in actual tool path;
- failure/recovery tests.

## SRE-04 — RSV process control
Severity: MAJOR
Status: OPEN

Required:
- process concurrency bound;
- global deadline/budget;
- lifecycle/reconnect tests;
- verify config output redaction;
- no query/execute_query/reveal exposure through ERP_MCP;
- secret DACL and process environment review.

---

# P1 — Documentation / Governance

## DOC-01 — multiple competing current checkpoints
Severity: MAJOR documentation integrity
Status: OPEN

Required:
- one clearly current authoritative status section;
- historical snapshots explicitly historical;
- remove contradictory D-gate/PASS claims.

## DOC-02 — device/tool-output/local-path leakage
Severity: MAJOR hygiene
Status: OPEN

Observed in prior review:
device-id/tool execution text and D:/Temp style local references in tracked docs.

Required:
- remove operational leakage where not evidence-required;
- preserve hashes/portable references instead.

## DOC-03 — SECURITY.md privilege mismatch
Severity: MAJOR
Status: OPEN

Docs claim runtime role stricter than actual source_capabilities grants.

Required:
fix implementation first, then docs.

## DOC-04 — README/tool/upstream drift
Severity: MINOR/MAJOR
Status: OPEN

Required:
- accurate upstream names;
- accurate tool inventory;
- v1.0/v1.1/current baseline consistency.

---

# P2 — Real 1C Assurance / Test Environment

## 1C-01 — native reconciliation
Severity: PRODUCTION GATE
Status: OPEN

Current evidence at independent review:
0 recorded native-report reconciliations out of required >=10 for a production semantic profile.

Required:
- >=10 representative accountant questions;
- native 1C report expected values;
- exact source/company/profile/metadata fingerprint;
- attributable evidence;
- discrepancies explained/resolved, never waived.

## 1C-02 — real OData handshake
Severity: PRODUCTION GATE
Status: OPEN

Required:
- actual test-base OData endpoint;
- live $metadata;
- metadata fingerprint;
- capability discovery;
- bounded read smoke;
- zero-write proof.

## 1C-03 — real-reference disposable test base
Severity: REQUIRED TESTBED
Status: PREPARATION CAN START NOW

Target:
- immutable source archive/hash;
- disposable clone only;
- separate test credentials;
- source environment inventory;
- known-correct period;
- known-error period if available;
- native reports inventory.

## 1C-04 — Ferma controlled synthetic track
Severity: REQUIRED ASSURANCE
Status: PARTIAL/OPEN

Required:
- scenario package;
- independent oracle;
- test-only seeder;
- real 1C posting in disposable synthetic base;
- native observer;
- ERP_MCP observer;
- three-plane reconciliation.

## 1C-05 — zero-write evidence
Severity: PRODUCTION GATE
Status: OPEN

Required:
- prove ERP_MCP production path never writes to 1C;
- transport/API evidence;
- test technical user permissions;
- write attempts denied.

---

# P3 — Production / Release

## REL-01 — registry publication identity
Status: OPEN

Need actual published OCI registry manifest digest, not only local/config digest.

## REL-02 — signing / attestation / provenance
Status: OPEN

Need approved signing/attestation/provenance process for the released artifact.

## REL-03 — PITR / rollback
Status: OPEN

Need target-environment backup/PITR and rollback rehearsal.

## REL-04 — SLO / burn-rate / up-absent alerts
Status: OPEN

Need production SLOs and alerting beyond basic rules.

## REL-05 — append-only audit TRUNCATE protection
Status: OPEN

Owner-level TRUNCATE remains a governance/DB-hardening consideration.

## REL-06 — idempotency retention / cleanup
Status: OPEN

Define retention/cleanup without violating auditability.

## REL-07 — production pilot
Status: OPEN

Controlled customer/source set, real accountant questions, audit review, zero writes, reconciliation monitoring.

---

# Recommended execution order after Admin

1. Finish Admin remediation and make Admin merge-ready.
2. Restack/merge Admin into integration only after migration lineage is safe.
3. Create integration-core-remediation branch on unified tree.
4. Fix CORE-01..05.
5. Create runtime-sre-hardening branch for SRE-01..04.
6. Clean docs/governance in bounded commits.
7. Run real 1C assurance on prepared disposable test environment.
8. Close production/release gates last.

Production GO remains false until real native accounting correctness and release/deployment evidence are complete.
