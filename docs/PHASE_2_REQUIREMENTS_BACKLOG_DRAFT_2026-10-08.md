# ERP_MCP — Release 1 boundary / Phase 2 requirements backlog (DRAFT)

Date: 2026-10-08
Operator direction: Release 1 remains frozen; Phase 2 requirements and ideas are collected, not implemented.
Status: DESIGN BACKLOG ONLY. NOT a release approval, production GO, governance rebaseline, migration or permission change.
Normative documents unchanged: SECURITY.md; docs/SCOPE_FREEZE_BASELINE_2026-10-06.md; docs/GOVERNANCE.md; docs/DEFINITION_OF_DONE.md.

## A. Release decision

R1 remains the accepted frozen read-only 1C/DAD product. Existing source/company ACL, read-only OData/approved COM, semantic tools, native 1C report reconciliation, P5 real reference and Ferma oracle test lane, audits, operations, existing Admin Control Center and mandatory release gates remain R1 responsibilities. R1 is scope-frozen but NOT accepted as released/production GO. Fixing proven security and correctness defects in an existing R1 path does not add a new product feature.

R2 IDEA ONLY: reusable connector framework, always-on discovery, PDM/LDM living registry, ontology/taxonomy, bitemporal history, per-object drift graph, automated evidence collection, continuous reconciliation, reconciliation exception workbench and enhanced Admin design.

Do not implement R2 inside R1, do not promote deferred lanes without explicit operator rebaseline, and do not weaken existing reconciliation requirements merely because future R2 automation is planned.

## B. Independent review: evidence and correction

Evidence markers: CODE = independently inspected in accessible local tree; LEGACY CLAIM = needs rerun on final release head; PROVIDER = verified in provider docs; DESIGN = recommendation, not measured implementation.

B1 (CODE, R2): There is already an accepted semantic profile lifecycle. A scanner may append OBSERVED snapshots automatically but never silently replace ACCEPTED models or set VALIDATED. Unaffected changes can be eligible for promotion only under a future approved impact/acceptance policy.

B2 (CODE, split R1/R2): compatibility.py SHA-256 hashes raw XML bytes. db/migrations/006_semantic_profiles.sql invalidates all VALIDATED profiles for a changed whole-source fingerprint. R2 needs canonical object/field hashes, dependency-specific invalidation and change events. The separate historic assertion "one timeout installs metadata-error:... fingerprint" is NOT confirmed against current tree: compatibility.py sets a failed observation to None, migration 014 retains last fingerprint and emits NEEDS_VALIDATION. Add R1 fault-injection regression to verify DB-deployed behavior; do not mislabel the historical defect as definitely current.

B3 (CODE, R1 correctness/security): migration 006 bag.native_reconciliation_evidence_valid validates count >=10, PASS, nonempty case IDs/report refs and uniqueness, NOT file authenticity. semantic.py validate_native_reconciliation_evidence similarly checks shape, and scripts/semantic_profiles.py validate persists a fingerprint of input JSON; this alone does not prove reports existed or amounts matched. R1 must close a fail-open evidence acceptance gap before production: authorized immutable evidence pointers, actual digest/existence/source/company/period verification, independent approved attestation or refusal. R2 is allowed to automate collection, but a connector cannot certify or set VALIDATED. Do not fabricate 10 reports.

M1 (DESIGN, R2): full 1C metadata every 15 minutes per source is unproven and potentially too expensive. Budgeted adaptive poll, backoff+jitter, maintenance windows, advisory locks, concurrency caps, source fairness, load tests.
M2 (LEGACY CLAIM, R1 verify/R2 design): migration 014 REVOKES INSERT/UPDATE of source_capabilities from business_ai_app, grants evidence_json update and execute on SECURITY DEFINER bag.record_capability_observation. Test effective roles on actual DB, authorization of function arguments/source ID and inability to forge STABLE. R2 separates writer, acceptor, reader database roles. Do not repeat old "business_ai_app can directly UPDATE drift_status" claim without post-014 repro.
M3 (DESIGN, R2): content-addressed dedup and entity-level deltas, archive/retention.
M4 (PROVIDER, R2): Drive file-level scope is NOT proven sufficient to auto-read future children of an arbitrary user-selected folder. Test exact scope and identity. changes.getStartPageToken/list track state and require durable per-user/shared-drive cursors. changes.watch requires public valid HTTPS receiver, has expiring channels, pushes hints not data. OAuth Testing non-profile authorization/refresh tokens expire in 7 days. Keys should not be casually provisioned; evaluate approved keyless workload federation and actual Drive resource permissions.
M5 (DESIGN, R1 security for existing ingestion, R2 automation): untrusted PDF/XLSX content sandbox, decompression and parser limits, no macro/external formulas/URLs, injection defense, redact PII, avoid raw document caches by default.
M6 (DESIGN, R2): distinguish SOURCE_UNAVAILABLE / STALE_OBSERVATION / DRIFTED / ACCEPTED_STALE / UNATTESTED / VALIDATED per operation, with explicit freshness contracts; no guesses/zero for missing data.
M7 (LEGACY CLAIM, R1): alleged broken existing alerts must be reproduced by fault injection before closing existing release hardening. R2 adds worker lag, cursor freshness and bad-source quarantine metrics.
M8 (LEGACY CLAIM, R1): alleged 7/8 existing Admin mutation guards and schema conflicts need exact-head tests/repro, correction if confirmed; add R2 connector/Rescan admin mutations only after control-plane is safe.
Minor (R2): Decimal / FX / timezone / closed fiscal period policies; operator-only business mapping confirmation; idempotency, dead letters, quotas; source and company scope.

## C. Phase 2 system principles

1. Source Connectors authenticate to 1C/Drive/Gmail/Slack and other explicitly permitted providers separately from ChatGPT OAuth to ERP_MCP. Provider secrets never belong in prompts or ChatGPT connector grants by assumption.
2. The scanner runs in its own bounded worker. Observation is not trust. Accepted models are version-pinned.
3. PDM maps actual permitted 1C OData/metadata-sidecar structures, never reads 1C internal SQL. LDM models business concepts. A Drive document repository is an evidence catalog, not a physical accounting database.
4. PostgreSQL stores observed and accepted snapshots, hashes, taxonomy edges, evidence refs, sync cursors, diffs, validation events and minimal aggregates; do not clone unrestricted business data into Postgres.
5. The "time DB" must be bitemporal first: transaction-time (when ERP_MCP learned a fact) and valid/source-effective time (when it was true at source). Events append only. Support AS KNOWN AT and AS EFFECTIVE AT replay, supersession, out-of-order changes and gaps. Choose vanilla PostgreSQL partitions initially; adopt TimescaleDB only after data volume/performance proof.
6. Stable taxonomy: tenant, connection, source, company, domain, concept, object, attribute, party, contract, document, report, evidence. Typed links include MAPS_TO, DEPENDS_ON, OBSERVED_IN, VERIFIED_BY, SUPERSEDES and RECONCILES_WITH. Each edge tracks source, scope, confidence, owner, time validity, version, permissions and multilingual aliases. AI suggestions remain CANDIDATE.
7. Every semantic tool pins exact accepted PDM/LDM version and dependency edges; only non-impacting changes may be eligible for automatic promotion under explicit policy, never automatic accounting attestation.
8. Evidence states: DISCOVERED, QUARANTINED, UNATTESTED, VERIFIED_ORIGIN, RECONCILED, ATTESTED, REVOKED, with independent actor signatures and append-only lifecycle. A Drive revision invalidates obsolete evidence/attestation, not unrelated reports. Connector DB role cannot write VALIDATED.
9. Reconciliation preserves Decimal, base/document currency, FX/rate provenance, fiscal period, as-of boundaries and time zones; truncation / unconfirmed opening balances / partial scope -> INCONCLUSIVE. Three planes when applicable: native 1C, ERP_MCP normalized, independent Ferma oracle in test-only lane.
10. Any new write-back to 1C, Drive or accounting system remains outside read-only design and requires explicit future authorization.

## D. Ranked R2 candidate epics

R2-001 P0 — Connector inventory and portable SDK contract. Audit PDCC adapters and dependencies, rights, license, scopes, data sensitivity and error behavior. Reuse patterns; never wholesale deploy without security review.
R2-002 P0 — Immutable observed schema snapshots: normalized entity/field/relationship fingerprints + versioned accepted head.
R2-003 P0 — Continuous discovery scheduler: adaptive poll, backoff, budgets, per-source distributed lock, dead-letter and resumable backfills.
R2-004 P0 — PDM/LDM taxonomy and semantic dependency graph with stable IDs, multilingual labels and source-specific ontology crosswalks.
R2-005 P0 — Bitemporal event ledger in PostgreSQL with provenance, content-addressed entity histories, change playback, retention and archival.
R2-006 P0 — Impact-aware drift governance: observed/accepted diff, dependency closure, risk-class approvals, no blanket invalidation for non-impacting changes.
R2-007 P0 — Evidence provenance/attestation and immutable manifest references. Separately ensure the current R1 evidence gate is safe.
R2-008 P1 — 1C read-only native report export/verification adapter under approved boundary.
R2-009 P1 — Google Drive evidence connector proof of concept: per-file scope vs shared-folder access, future new-files test, revision tracking, shared drive, token expiry and independent authorization.
R2-010 P1 — Three-plane automated reconciliation for one real source/company and independent proof: start account 521.1 and purchase receipts, then generalize.
R2-011 P1 — Reconciliation discrepancy workbench, accountant review workflow, approval/rejection, owner/SLA and audit trail.
R2-012 P1 — Data contract canaries, alias/identity resolution for counterparties/contracts with no automatic merging of identities.
R2-013 P1 — User/Admin living model UI: source health, observed vs accepted, PDM/LDM diagram, time travel, dependency blast radius, missing evidence, alerts and gated Rescan.
R2-014 P1 — Field-/tenant-/company-level access, PII redaction, data residency, data minimization, policy enforcement, parser sandbox and DLP.
R2-015 P1 — Freshness SLO/monitoring and fault proof: change lag, token expiry, cursor invalid, source overload, corrupted evidence, restoration.
R2-016 P2 — Additional PDCC-derived Gmail/Slack/Telegram connectors only for approved evidence scenarios and with verified ownership/scopes; avoid personal corpus creep.
R2-017 P2 — Webhook/push optimization only after polling correctness and HTTPS receiver threat model.
R2-018 P2 — Reconciliation coverage map, automated data quality checks, anomaly detection with human-approved rules; no AI self-approval.
R2-019 P2 — Tamper-evident evidence export manifests and reproducible run bundles for audit, with appropriate private storage/retention.
R2-020 P2 — Release-safe semantic promotion: canary comparison across old/new mappings, version rollback, break-glass diagnostics without weakening production assertions.

## E. Recommended sequencing and acceptance proof

F0 — Governance, connector contract, PDCC/ERP/Ferma inventory, threat model, R2 baseline and R1 closure verification.
F1 — 1C-only discovery worker, observed PDM, canonical hashes, bitemporal registry, load and outage negative tests.
F2 — Taxonomy/LDM candidate links, dependency diff and accepted promotion; user can see why a tool is blocked.
F3 — One independent real 1C 521.1 reconciled workflow with attested source report. Never use a fabricated native PASS.
F4 — Drive connector experiment: if drive.file cannot read new files in selected folder, choose another explicit controlled model; use changes.list polling, not push first. UNATTESTED files alone never unlock an accounting profile.
F5 — Automated reconciliation engine + exception UI + detailed history + chaos/restore/retention tests.
F6 — More PDCC connectors only after scope, customer need and connector audit.

Acceptance examples:
- XML whitespace/reordering with identical semantic structure does not create a breaking drift.
- Field rename impacts only mappings depending on that field, and those tools fail closed.
- One DB writer per source across replica crashes, replay and backfill.
- Source down => accepted version retained historically, no fictitious new schema.
- Edited Drive report revision revokes previous evidence linkage and triggers re-review.
- AI cannot set CONFIRMED/VALIDATED via an untrusted prompt or file.
- MOLDRETAIL purchase_documents traces posted state and company/counterparty filters exactly.
- 521.1 reconciliation pins amount, debit/credit, currency, date, account, counterparty/contract and real native report source.
- Cross-company and source-wide metadata negative ACL tests.
- Release 1 behavior remains unchanged until Phase 2 feature flags are explicitly promoted.

## F. What is ACTUALLY reusable in local repositories (observed, not assumed)

PDCC: D:\Repo\Personal_Decision_Command_Center\services\gmail-connector\src\history-runtime.ts contains Gmail history cursor, recovery and idempotency integration. services\slack-connector\src\index.ts implements Slack event signature checking. host\telegram-connector exists. A full reusable Google Drive service was not confirmed in inspected PDCC services. Inventory the rest before saying "all connectors" already exist.

ERP_MCP Ferma: testbed\ferma_onec\reconcile.py independently compares native, actual and optional oracle observations, returns INCONCLUSIVE on incomplete measurements and pins tolerance fingerprint. Reuse contract, not any test-only write seeding in production.

ERP: D:\Repo\ERP\docs\architecture\R12_TEST_DATA_PLATFORM_TDD.md contains determinism and accounting verification concepts. workers\reconciliation-jobs has a .gitkeep placeholder only; do not claim implementation there.

## G. Decisions to collect (NOT blockers to R1 closure)

- What is the connector classification: evidence-only B2B, also personal workspaces, or both with strict account isolation?
- Read-only 1C report provenance and independent evidence attestation method, exact human role, required native report families.
- Whether a non-breaking observed schema change can auto-promote under a preapproved machine policy. Default: no.
- How long to retain observed vs accepted metadata and event history, by client/company/data class.
- Scope and source of truth for taxonomy: customer-specific concepts vs shared canonical concepts, RU/EN aliases.
- How to authenticate Drive long-lived on-prem server without broad permissions or JSON keys.
- Whether Google drive.file allows observing newly created files under selected folder (PoC mandatory).
- Which providers have mature connectors already in PDCC and pass legal/security portability review.
- Accounting correctness contracts: month-close, accrual, FX policy, treatment of advances, VAT and settlement matching.
- Data residency, PII, encryption at rest, audit exports and source revocation semantics.
- Exact throughput and source-load budgets for 30–150 sources.

This document is a DRAFT backlog only; no normative freeze, application code, schemas, security policy or tests have been changed by drafting it.
