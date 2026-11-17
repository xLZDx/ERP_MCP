# Phase 2 Finisher Technical Design Handoff

Sprint: `beea27520b33`  
Status: implementation handoff; this document does not claim code completion, runtime evidence, upstream acceptance, or qualification.

## Purpose and controlling documents

This handoff links the accepted finisher requirements to the settled design and code boundaries. It does not duplicate the detailed S12/S13 contracts or S16 rev. 2 plan. Read these together:

- [Requirements](requirements.md) — REQ-001–REQ-017 and evidence limitations.
- [Backlog](backlog.md) — stories and acceptance criteria.
- [Integration design](design.md) — data flow, failure behavior, ownership and sprint decisions.
- [Code design](code-design.md) — proposed package boundaries and interfaces.
- [Approval UI specification](ui-spec.md) — page states and interaction contract.
- [S16 sprint plan rev. 2](../phase2/S16_SPRINT_PLAN_2026-10-28.md) and [S12 contract amendment](../phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md) — controlling domain contracts.

The sprint scope is S12/S13 follow-ups, S16 rev. 2 fake-backed code, and the explicit connector/watchdog evidence requests in the requirements. S17–S19 are conditional on separate current authorization. S12/S13/S15 formal acceptance remains unverified until evidence is reconciled with the current gate manifest.

## Requirement to story to acceptance

| Requirements | Story / intent | Acceptance evidence |
|---|---|---|
| REQ-001–003 | S1.1–S1.2: SQL refusal vocabulary and exhausted-grant mapping; safe period and budget evidence | Migration 028 catalog parity (39 canonical codes), exhausted-budget branch behavior, and source/ledger-derived evidence. A period result must come from one authenticated, scoped, fresh observation; missing, contradictory, stale, or unauthenticated observations fail closed. |
| REQ-004 | S1.3: current in-flight list and status | Values read through the scoped ledger/service boundary, including status-by-ID; no test fixture or process cache as authority. |
| REQ-005–006 | Final evidence and acceptance reconciliation | Assigned test agents report exact final revision, commands, results, skips, and limitations; acceptance is promoted only against required evidence and the current gate manifest. Historical runs are not current-head proof. |
| REQ-007–009, REQ-013 | S2.1–S2.2: isolated approval core and immutable approval page | Core-owned authorization, replay and apply-time checks; service-issued nonce/digest; exact canonical preview bytes; positive authentication and safe refusals. Permissive fakes cannot bypass core policy. |
| REQ-010–012 | S2.3: model tool surface, verification, and rollback proposal | Exactly five model-facing tools; S15 verification passthrough; POST/UNPOST unsupported; rollback creates a separately approved UNPOST proposal only for a verified POST and never applies it. |
| REQ-014–015 | Explicit external evidence checks | Record observed connector operation/endpoint, time and result without credentials; watchdog evidence must show the same component before and after restart. Unavailable observations are `NOT_RUN` with exact error. |
| REQ-016–017 | Safety boundary and conditional future work | Writer remains `UNQUALIFIED` and disabled; no production binding, deployment, real 1C POST/UNPOST, production action, or real-money action. Later sprint work requires its own approved scope. |

`functional-test-reviewer` and `e2e-runner` own required test authoring and execution after in-scope coding is complete. Their linked test-plan documents provide the case-level map; this TDD records acceptance boundaries, not test execution. No test result is claimed here.

## Design and interfaces

### S12/S13

- The PostgreSQL ledger remains authoritative for reservations, grant accounting, lifecycle, audit, list and status. Existing scoped routines and transaction/locking behavior remain in force.
- SQL migration 028 is additive and versioned; it mirrors the canonical Python refusal vocabulary and distinguishes zero/non-positive remaining grant from other budget refusals where the SQL contract permits.
- A period producer must consume a configured, source-qualified, read-only 1C operation and construct a typed snapshot binding source, company/tenant, period, authenticated source identity, observation time, and version/fingerprint. No repository evidence currently establishes a qualified period endpoint or query. Until such a source contract is evidenced, the producer is unavailable/unproven and cannot supply positive-open evidence. Do not report a real-data producer as qualified or infer period state from dates or fixtures.
- Budget evidence is derived from scoped grant, reservation and consumption state. The ledger performs the final atomic recheck; a snapshot alone cannot authorize apply.
- List/status reads use the scoped ledger/service adapter. A list row and later status query are independent observations.

### S16

- `src/erp_mcp_s16/` owns decision policy. Injected ports provide persistence, clock, randomness, target inspection, verification and atomic claim. Fakes may store/return state but cannot own authorization decisions.
- Keep S16 isolated from gateway and writer composition. Do not register tools, import S16 into the gateway/writer, start a listener, add a production binding, or add S16 persistence/schema in this slice.
- The model-facing contract is exactly `propose`, `status`, `apply`, `verify`, and `rollback_propose`; approval is a separate private approver path, never a model tool or alias. The boundary supplies a typed authenticated principal; request fields do not establish identity or authority.
- ApprovalService/ChangeService issues nonce and preview digest. The page renders the exact canonical bytes covered by the digest. Core validation binds decision to person/session, nonce, digest, version, scope and expiry, then rechecks base fingerprint, principal epoch, approver validity, target/base binding, kill switch and claim-once immediately before the apply port.
- For this handoff, use a 15-minute approver session lifetime and a 5-minute single-use approval nonce. This session value supersedes the 10-minute proposal in the earlier S16 Q3 design table; the 5-minute nonce matches it. CSRF remains session-bound, single-use and generated with at least 256 bits of secure randomness.
- Any amount threshold is a named policy-registry value, never a UI constant. If the required threshold entry is missing or unavailable, reject the approval decision safely; do not silently disable confirmation or invent a numeric threshold. POST always requires typed confirmation; other operations require it when the policy threshold says so.
- `verify` passes S15 results through unchanged; POST/UNPOST remain `UNSUPPORTED_SHAPE`. Rollback of a verified POST creates a separate UNPOST proposal with its own approval and current target observation. CREATE_DRAFT and UNPOST rollback are refused.

## Failure behavior, rollout and rollback

Failures at source authentication, scope/freshness/version checks, ledger reads, registries, identity/revocation, token class, origin/host/proxy checks, canonical digest comparison, nonce/CSRF replay, expiry, threshold policy lookup, or atomic claim must fail closed before any apply-port invocation. Public errors use the shared safe error registry; raw exceptions, credentials, nonce, CSRF tokens, session identifiers and internal diagnostics do not enter responses or artifacts.

Migration 028 follows the existing ordered migration process. Before it is applied, migration 027 is the rollback point; after application, correction is by a forward migration, not history deletion or rewrite. S16 is unwired library code with no persistence or listener, so its code rollback is a revert/removal of that isolated slice; no runtime cutover or data migration is part of this scope. These are design instructions, not evidence that migration, deployment, or rollback has occurred.

## Non-negotiable limits and open evidence

The private writer stays disabled and `UNQUALIFIED`; production bindings stay empty. No production deployment, real COM write, real 1C POST/UNPOST, or real-money action is authorized. Real-client transcripts, production IdP, UAT and deployment evidence remain out of scope unless separately authorized. A fixture or client-shaped transcript is not observed connector evidence. Any unavailable connector, source, runtime or test dependency must be reported as `NOT_RUN` or `UNKNOWN` with its exact observed error; do not upgrade design or source presence to runtime proof.

## Completion record

This document is a design handoff only. Track implementation, manual review, runtime proof, formal upstream acceptance and external-lane evidence separately in the sprint records. The acceptance owner must reconcile the exact final revision and evidence against the applicable gate manifest before making any acceptance claim.
