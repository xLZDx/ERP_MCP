# ERP_MCP Phase 2 — S0–S10 Plan and G0–G7 Gates

**Version 0.1 · October 8, 2026 · DRAFT.** This is an engineering dependency sequence, **not** a calendar commitment or a record of completed implementation. Durations should be estimated after inventory and technical spikes. Requirements come from `TDD_PHASE2_RU.md`, stories from `STORIES_PHASE2_RU.md`, and acceptance tests from `TEST_PLAN_PHASE2_RU.md` and the extended catalog of 144 cases.

## 1. Two Work Tracks

**Release 1 (R1):** Close the existing security, accuracy, native-evidence, and release gates. Do not delay R1 for universal connectors or the temporal database. An R1 defect cannot be reclassified as a future R2 capability.

**Release 2 (R2):** Require a separately agreed scope, staged feature flags, and independent release gates. Production capture must ship **OFF by default**. A development PASS does not authorize production use.

## 2. Sprints

| Sprint | Expected outcome | Dependencies and exit criteria |
| --- | --- | --- |
| **S0** | R1 baseline, source/identity ownership, PDCC/ERP/Ferma inventory, proposed ADRs, native report feasibility | G0 scope, architecture, and security; no unverified donor may be declared ready |
| **S1** | Connector contract, dedicated source OAuth, secret references, scope/epoch, job and idempotency envelope | Contract unit/integration tests; no arbitrary target or write operation |
| **S2** | PostgreSQL events, history and projections; scoped FKs, RLS and roles; leases, fencing, outbox and cursors | G1 real database negative role/transaction/replay tests |
| **S3** | 1C baseline, canonical hashes, partial/outage/coverage semantics, adaptive scheduler and physical-backend budget | G2a whitespace invariance, failure is not drift, no capacity bypass through source aliases |
| **S4** | Taxonomy/LDM candidates, dependency graph, observed/accepted model, CAS and timeline API | G2 known/unknown impact; promotion mechanics may use synthetic evidence for tests, but genuine acceptance requires G3 |
| **S5** | Manual native UI export, qualified UI automation in development, capture permits, original artifact store and parser isolation | G3a genuine UI baseline, report identity and parameters, no business-data writes |
| **S6** | Optional engine qualification, independent attestation, evaluation runner, all six account 521.1 totals, accounting-based AP, purchases contracts | G3 independent native+MCP proof and coverage; a missing register must not be invented |
| **S7** | Least-privilege Drive proof of concept, baseline plus changes/revisions/moves/revocation, authentication expiry | G4 real new-file permission scope; polling works without relying on a webhook |
| **S8** | Workbench explanations, history and coverage, job/read APIs, safe rerun | G5 real user/admin UAT and current evidence validity after revocation |
| **S9** | Capacity, chaos, audit, restore, retention, R1 compatibility and migration rehearsal | Pre-G6 actual workload measurements, fault alarms and reproducible recovery |
| **S10** | Source-specific production canary **only under separate authorization**, exact-HEAD R2 release bundle | G6/G7 approved recipe, identity, time window, budget, native correctness and formal acceptance |

**FOLLOW-ON:** Additional PDCC providers, push webhooks, TimescaleDB and advanced anomaly proposals. An inventory and connector SDK are required, but that does not make every provider supported. Never transfer the Ferma test seeder into production.

## 3. Release Gates

**G0 — Product scope and architecture:** Product owner, architecture, and security approve scope, ADRs, threat model, R1 boundary and source inventory. A request for documentation does not itself authorize implementation.

**G1 — Database and security:** Verify real PostgreSQL roles, row-level security, foreign keys, leases, fencing, cursors, outbox and replay. Mocks are insufficient.

**G2 — Metadata and domain:** Complete canonical corpus; separation of observed and accepted models; conservative denial for unknown impact; no AI-driven automatic promotion.

**G3 — Independent accounting evidence:** Accountant and verifier confirm authentic report bytes and provenance, qualified procedure/configuration, source consistency, six totals and underlying rows, operation coverage and attestation. Ten passing JSON comparisons are insufficient.

**G4 — Drive source permissions:** Source owner and security prove narrow Drive access; shared-drive membership, revoke, token and revision tests.

**G5 — User and administrator acceptance:** Actual UAT, clear safe explanations of blocked operations, separation of roles and an auditable workbench.

**G6 — Production operations:** Production owner, operations and security approve default-OFF enablement bound to exact source/company/recipe/hash/user, approved time window, expiry, budget, kill switch and copied-environment qualification. Do **not** run test probes against production.

**G7 — Final release:** Release owner approves a manifest pinned to exact commit, configuration, procedure, parser, policy and evidence. Every mandatory test must have actually passed, with no P0/P1 correctness or security blocker. **Skipped is not passed.**

## 4. Parallel Workstreams

- **A:** Contracts and authentication.
- **B:** PostgreSQL and temporal history.
- **C:** 1C capture and reconciliation.
- **D:** Workbench and user interface.
- **E:** Security, functional verification and performance.

Assign a single owner for shared schema and files. Isolated worktrees must not restart someone else's live testbed. Do not launch external AI reviewers without separate authorization; independent review can use authorized local roles and proof-based review.

**Critical path:** G0 → contracts/storage → observed/accepted plus native capture → attestation/comparison → UAT/operations → production qualification.

Drive is **not** required for the first manual native proof for account 521.1 and must not unnecessarily block it.

## 5. Definition of Ready / Definition of Done

**Ready:** Scoped story; requirement/test IDs; source, identity and data authority; capture procedure and contract; dependencies, risks, and rollback. Production additionally requires a valid permit.

**Done:** Code plus tests on the exact candidate, meaningful assertions, relevant integration/security/performance checks, migration/restore rehearsal, documentation and traceability, and independent evidence/approval. The existence of a `.feature` file does **not** mean its scenarios have executed.

When a blocker requires only the operator, record the exact identifier, cause and minimal action, then continue independent tasks. Never bypass MFA, secrets or permissions to work around authentication errors. Never remove a profile or temporarily grant administrator rights just for a demonstration.

## 6. Delivery Slices

**R2-A:** 1C-only Living Registry, temporal data and taxonomy, development manual/UI capture, first comparison. Drive is optional.

**R2-B:** Evidence/attestation, operation policies, qualified engine where supported, Drive polling and workbench. Canonical tools are enabled **only** for their specifically validated scopes.

**R2-C:** Operations, load and disaster recovery; optional approved production capture canary; first externally qualified provider. Other adapters require separate provider-specific test contracts.

## 7. Bounded Technical Spikes

| ID | Feasibility question |
| --- | --- |
| **SP-01** | UI-dependent native trial balance/account card: actual generation and export, without an administrator fallback |
| **SP-02** | Accounting-based accounts payable for 818HA when the settlement register is absent |
| **SP-03** | Drive file, folder and shared-drive grants plus new files; limits of read-only history |
| **SP-04** | Source-effective time and completeness of change history; honest snapshot-only/gap semantics |
| **SP-05** | Side effects of a standard native report and rights of the production reader |
| **SP-06** | Physical-backend capacity sharing across replicas and source aliases |
| **SP-07** | Native formats, parser, currency, time zone and reporting cutoff |

Every spike ends with `SUPPORTED`, `UNSUPPORTED`, or `INCONCLUSIVE` and supporting evidence, not a promise of compatibility with all configurations.

## 8. User Scenario Acceptance

**Normal user:** See authorized company status, posted MOLDRETAIL purchases, all six account 521.1 trial-balance totals and rows, and history. Attempts to access another company or execute raw commands must be denied. Revocation during a job must prevent unauthorized results from being disclosed.

**Administrator/accountant:** Manage source, scope, secrets and budget; inspect observed differences and impact; review native baseline and capture recipe; obtain independent attestation; test Drive changes/revocation; control a permitted production toggle/canary; inspect alarms, restore and rollback.

## 9. What This Initial Plan Did Not Implement

At this initial documentation checkpoint, the plan did **not** modify R1 runtime, migrations, security, or CI; create a branch, commit, push or merge; grant new source access; log into the native 1C application; enable production capture; restart services; execute load; or delete data. The checkpoint consisted of project documents and companion specification tests only.

**This section is historical.** Current implementation and release state must be verified from the actual Git HEAD, measured evidence, approved gates, and decision log, rather than inferred from the initial plan.
