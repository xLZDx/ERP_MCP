# ERP_MCP Phase 2 — Data and API Contracts: TDD Clarification

**October 8, 2026 · v0.1 · DRAFT FOR REVIEW.** This is a design proposal, not an executed database migration or a list of currently available MCP tools.

## 1. Data Groups

| Group | Proposed entities | Boundary |
| --- | --- | --- |
| **Connections** | `connector_instances`, `scope_memberships`, `provider_principals` | Reuse existing source/company authority; store secret references, **not** secret values |
| **Jobs** | `jobs`, `leases`, `cursors`, `outbox` | Scope, idempotency and parameter digest; fencing; atomic page/cursor/outbox |
| **Physical Data Model (PDM)** | `snapshots`, object/field/relation versions | Keep raw and canonical hashes separate; pin canonicalizer version and coverage |
| **Accepted state** | `accepted_heads`, `acceptance_events` | CAS, independent actor/policy/evidence; scanner is **not** the approver |
| **Logical Data Model (LDM)** | `concepts`, `aliases`, typed/dependency edges | Stable IDs; source/company scope; provenance, confidence and owner |
| **Time** | Immutable `model_events`, current projections | Known/effective time, corrections, supersedes, gaps, deterministic replay |
| **Capture** | `recipes`, `qualifications`, `execution_permits`, `job_events` | Source/config/report/variant/executor hash; mode, time window and budget |
| **Evidence** | `artifacts`, `revisions`, origin checks, `attestations` | Private immutable bytes, actual digest, authenticated signer, scoped foreign keys |
| **Reconciliation** | `runs`, `measures`, row links, discrepancies | Exact scope/cutoff/model/parser/recipe/policy pin; numerical vs business acceptance |
| **Validation** | `policies`, operation bindings, evidence claims | Actual evidence foreign keys and coverage; no arbitrary JSON `VALIDATED` flag |

Source-wide PDM may be stored once, but company projections expose only the authorized subset. A global metadata observation does **not** grant company-scoped readers source-wide access. Capture/financial jobs must be bound to an exact company.

Composite keys, foreign keys, RLS and runtime reauthorization protect APIs, job queues, caches, blob storage and historical views.

## 2. Temporal Database

Registry-recorded time is assigned by the server at the **authoritative commit boundary**, not trusted from a client-supplied timestamp. Source-effective time is recorded only when a source marker or its semantics are evidenced; otherwise it remains `NULL`. The time at which polling occurred must not be presented as the effective date of a change.

`AS KNOWN AT K` reconstructs what was known at knowledge time K. `AS EFFECTIVE AT V` with knowledge cutoff K reconstructs the effective state at V as it was understood by K. A late correction appends a new event with `supersedes`, never rewrites the previous history.

If polling sees A → B → A but no source history exposes the intermediate B, its precise occurrence is unknown. Report an appropriate gap/coverage limitation instead of inventing events.

## 3. API Contracts

**Connection registration and source OAuth:** Separate from ChatGPT OAuth.

**Enqueue rescan/report/reconciliation:** These are control-plane mutations requiring idempotency, CSRF protection and audit. A read-only source does **not** make job submission an immutable/read-only action.

**Read model/changes/job/result:** Require current scoped authorization plus the selected observed/accepted/version/time query. Possession of historical evidence is not perpetual authorization to disclose it.

**Request report:** Bind `recipe_id`, version/hash, source/company, permit reference, `scope_epoch`, typed parameters and private output policy. Forbid `command`, `sql`, `bsl`, `epf_bytes`, `arbitrary_url`, `password`, `connection_string`, and `force_validate`.

**Attest and accept:** Privileged commands with independently authenticated identity, exact artifact revision, claims and policy, real evidence foreign keys, and `expected_previous_head`. No public endpoint may simply write a `VALIDATED` status.

**Pause and revoke:** Scoped mutation with a reason, idempotency, epoch update and outbox cancellation. Revocation **before disclosure** blocks returning even an already computed result. Rollback never restores revoked grants.

## 4. Four JSON Schemas in the Companion Archive

- `schemas/model_event.schema.json`: `OBSERVED` event, nullable effective time, source/company scope level, coverage and gaps.
- `schemas/capture_request.schema.json`: typed request, recipe and permit, development/staging/production modes, safe parameters.
- `schemas/native_manifest.schema.json`: original artifact, source/recipe, evidence class and authority, parameters, hashes, completeness and attestation.
- `schemas/reconciliation_result.schema.json`: evidence/actual/model/policy references, Decimal values serialized as strings, numeric result separated from approval.

These were provided in the original chat archive and were **not automatically extracted on Windows** at the design checkpoint. Examples are synthetic. JSON Schema compliance does **not** establish authentic report provenance, a valid permit, or real authorization.

## 5. Where Each Claim Is Verified

| Claim | Authoritative verification |
| --- | --- |
| IDs, digests and Decimal representation | JSON Schema plus database contracts |
| Scope | Foreign keys, RLS, registry lookup and **current grants** |
| Permit | Actual policy, authorization epoch, time window and backend budget |
| Native report origin | Original bytes and qualified source/reporting procedure |
| Independent signer | Verified identity and separation of duties, **not** an untrusted JSON `signed_by` field |
| `MATCH` | Deterministic all-six-column and row-level computation under proven scope/cutoff/completeness |
| Production permission | Separate source-specific authorization and proof that capture has no business-data write effects |

Source fetch must not hold a long database transaction. Ingestion atomically writes a page, its events, cursor and outbox. Promotion transactionally validates the current head, evidence, policy and CAS. Every disclosure revalidates **current** access rights.

Append-only storage is not automatically protected from a database superuser. Audit anchors and privileged-role governance are separate security requirements.

## 6. Drive-Specific Clarification

The reviewed documentation for Drive `changes.list` states that page tokens **do not expire**. Do not confuse them with OAuth refresh tokens. Recovery tests should cover cursor loss, corruption, a change in identity or authorized corpus, not an invented periodic Drive cursor expiry.

Primary reference: [Drive changes.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list).

Read-only/Viewer access does not guarantee revision-history API access. Never increase permissions or mutate `keepForever` merely to download historical revisions. Capture only genuinely accessible current bytes in a private immutable store and label their evidence basis and coverage honestly.

**Historical PASS and applicability to the latest revision are distinct states.**
