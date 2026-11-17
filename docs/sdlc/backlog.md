# Phase 2 Finisher Backlog

Sprint: `beea27520b33`

## Sprint goal

Complete the authorized S12/S13 follow-ups and S16 rev. 2 fake-backed approval/tool slice, then collect exact-final-head test and lane evidence and reconcile each acceptance claim against its controlling records. Keep the private writer `UNQUALIFIED` and disabled, the production binding set empty, and perform no real 1C POST/UNPOST, deployment, or production action.

Scope authority: `docs/sdlc/requirements.md` (REQ-001–REQ-017), the Phase 2 finisher brief, and `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md` rev. 2. This backlog plans work; it is not implementation, test, review, runtime, or acceptance evidence.

## Prioritization rule

Order by (1) safety and contract risk, (2) explicit finisher-brief order, and (3) dependency. Close SQL parity and real S12/S13 evidence producers plus operator observability first; implement S16 only against fakes and the rev. 2 boundaries; finish with the required post-code test, lane-evidence, and acceptance reconciliation. One sprint has one PR. No S17–S19 implementation enters this sprint unless an existing approved scope record explicitly covers it after this queue; GPT-PM adjudicates that scope at the handoff. No extra approval gate is inferred.

## Definition of Ready

A story is ready when it traces to listed REQ IDs, has falsifiable numbered Given/When/Then criteria, has the cited design/contract input, and its dependencies and safety boundaries are known. All stories below meet documentary DoR from the supplied requirements and S16 rev. 2 plan. Runtime availability and upstream formal acceptance are evidence dependencies, not reasons to omit ready code work. The S16 story must remain fake-backed if S12/S13/S15 are not formally accepted.

## Prioritized epics and sprint stories

### E1 — S12/S13 contract parity and real evidence

**Priority:** P1; first in execution order. **Trace:** REQ-001–REQ-004, REQ-006, REQ-016.

#### S1.1 — Align SQL refusal codes and exhausted-grant outcome

**Trace:** REQ-001. **Depends on:** current Python refusal registry and SQL migration chain (last documented migration 027 in the finisher brief).

- **AC-1 (parity):** Given the canonical Python set of 39 refusal codes, when migration 028 is applied and the parity check is run, then the SQL registry matches the canonical set and includes `PERIOD_CLOSED` and `GRANT_EXHAUSTED`.
- **AC-2 (budget):** Given an exhausted grant and a positive requested amount, when the SQL budget path evaluates it, then it returns `GRANT_EXHAUSTED`; other budget refusals retain `BUDGET_EXCEEDED` where specified by the S12 amendment.
- **AC-3 (limits):** Given Python refusal cases SQL cannot express, when the change record is prepared, then each limitation is named there and no parity claim hides it.

#### S1.2 — Produce period and exhausted-budget evidence from real data

**Trace:** REQ-002–REQ-003. **Depends on:** S1.1 contract outcome definitions and the existing S12 producer interfaces.

- **AC-1 (period):** Given one authenticated observation of the target accounting period, when period evidence is produced, then it reflects that observation; a closed period yields `PERIOD_CLOSED`.
- **AC-2 (fail closed):** Given missing, contradictory, stale, unauthenticated, or otherwise unproven period evidence, when apply eligibility is evaluated, then the producer does not authorize apply.
- **AC-3 (budget):** Given an observed grant with no remaining amount and a positive requested amount, when the budget producer evaluates it, then it feeds `BudgetCheck.EXHAUSTED` while preserving the distinct other-refusal mapping.

#### S1.3 — Expose in-flight changes and current status

**Trace:** REQ-004. **Depends on:** the relevant S12/S13 ledger/service state.

- **AC-1 (list):** Given changes currently recorded as in flight, when the operator requests the in-flight list, then each listed change is derived from the relevant ledger/service state.
- **AC-2 (status):** Given an identifier returned by that list, when the operator requests its status, then the function reports that change's current recorded status and does not substitute a test-only fixture.

**Scope note:** this is the G3 in-flight list/status follow-up named in the finisher brief and REQ-004. “G3” here does not mean an accountant approval gate; no such gate is added by this backlog.

### E2 — S16 rev. 2 isolated approval channel and tool contract

**Priority:** P1; follows E1's contract work, but remains pure decision logic over injected ports and fakes unless upstream acceptance is evidenced. **Trace:** REQ-007–REQ-013, REQ-016. **Plan:** `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, especially §§2, 4–5 and E16-1 through E16-5.

#### S2.1 — Put approval decisions in the S16 core

**Trace:** REQ-007–REQ-008. **Depends on:** S12 value/transition contracts; fake-backed ports per rev. 2 when upstream formal acceptance remains absent or unknown.

- **AC-1 (core ownership):** Given a permissive persistence fake, when self-approval, nonce replay, digest/version/expiry mismatch, or a wrong token class is attempted, then the S16 core refuses it without relying on the fake to enforce the decision.
- **AC-2 (revalidation):** Given an approval and any changed kill switch, target base fingerprint, principal epoch/dependency, approver validity, expiry, canonical digest, or target version, when apply is requested, then the core returns the applicable refusal before calling the apply port.
- **AC-3 (claim once):** Given parallel apply requests for one approved change, when they contend, then at most one claim and one apply-port call occur; the database-backed claim remains NOT_RUN unless S13 acceptance and runtime evidence support it.
- **AC-4 (preview provenance):** Given an approval request, when nonce and `preview_digest` are issued and preview is rendered, then `ApprovalService`/`ChangeService` owns issuance and the display uses the same canonical bytes covered by the digest; caller/model-supplied approval claims cannot alter either.

#### S2.2 — Implement the protected approval page and session boundary

**Trace:** REQ-008–REQ-009, REQ-013. **Depends on:** S2.1 ports and typed authenticated principals; test IdP only.

- **AC-1 (decision):** Given a valid isolated approver session and an unused bound nonce, when the approver accepts or rejects the canonical preview, then the service records only that decision for the bound change, digest, version, scope, person, and expiry.
- **AC-2 (session/response):** Given a chat/model principal, cross-session use, unsafe preview content, or an invalid/replayed request, when the approval page handles it, then it fails closed, keeps secrets and internal details out of output, and applies the plan's session, CSRF, CSP, encoding, framing, caching, and referrer protections.
- **AC-3 (issuance):** Given a displayed preview, when its contents are checked against the approval digest input, then both derive from the service-returned canonical bytes; the page does not mint or recompute nonce/digest/version.

#### S2.3 — Expose exactly the approved five model-facing tools

**Trace:** REQ-010–REQ-013. **Depends on:** S2.1 core and S2.2 service contracts; S15 verifier only through `VerifyPort`.

- **AC-1 (surface):** Given an MCP tools/list request, when the model-facing list is returned, then it contains exactly `propose`, `status`, `apply`, `verify`, and `rollback_propose`, with no `approve` action or alias.
- **AC-2 (direct refusal):** Given a direct attempt to invoke an approval action or a forged approval claim, when the tool surface handles it, then it safely refuses without state change or preview alteration.
- **AC-3 (verify):** Given an S15 verifier outcome, when `verify` runs, then it passes the outcome through unchanged; POST and UNPOST shapes return `UNSUPPORTED_SHAPE` and cannot transition to `VERIFIED`.
- **AC-4 (rollback):** Given a verified POST and its current observed target state, when `rollback_propose` is requested, then it creates a separate UNPOST proposal requiring its own approval; rollback of CREATE_DRAFT or UNPOST returns `ROLLBACK_REFUSED`, and this tool neither approves nor applies it.
- **AC-5 (safe errors):** Given any refusal or internal exception, when a tool response is rendered, then it uses the shared safe error registry and discloses no raw exception, stack trace, secret, or internal identifier.

#### S2.4 — Require positive authentication and private-only ingress

**Trace:** REQ-009–REQ-010, REQ-016. **Depends on:** S2.3 interfaces. **Exposure:** default loopback; explicitly configured private ranges only, per rev. 2 Q7.

- **AC-1 (identity):** Given any request, when the private listener handles it, then a valid positive authenticated principal is required; loopback/network origin alone is not identity.
- **AC-2 (route denial):** Given foreign Origin/Referer, forwarding headers, mismatched Host, public target, redirect, proxy route, or DNS-rebinding path, when the request is checked, then it fails closed before the apply port is invoked.
- **AC-3 (no binding):** Given the completed S16 library/tool slice, when deployment/binding state is inspected, then no gateway/process route is registered and the production binding set remains empty.

### E3 — Final-head verification, external-lane evidence, and truthful closure

**Priority:** P1; starts after all in-scope coding is complete. **Trace:** REQ-005–REQ-006, REQ-014–REQ-017.

#### S3.1 — Run required SQL/E2E and S15 suites at the final implementation head

**Trace:** REQ-005–REQ-006. **Depends on:** S1/S2 coding complete. **Owners:** `functional-test-reviewer` and `e2e-runner` author/execute required tests; Codex coordinates and checks mapping.

- **AC-1 (provenance):** Given the exact candidate final head, when the assigned test agents execute required slow SQL/E2E and S15 suites, then each result records that head, exact command, outcome, skips, and limitations.
- **AC-2 (missing runtime):** Given an unavailable dependency or execution error, when a scenario cannot run, then it is recorded `NOT_RUN` with the observed dependency/error; historical results are not represented as final-head proof.
- **AC-3 (mapping):** Given the test report, when coverage is reconciled, then each result links to the applicable story and gate and covers the story's numbered acceptance criteria.

#### S3.2 — Check ERP_MCP_REAL1 connector reachability and one watchdog restart

**Trace:** REQ-014–REQ-015, REQ-016. **Depends on:** authorized read-only connector probe and the named in-scope lane/autostart mechanism being available. No mutation run is authorized.

- **AC-1 (connector):** Given the configured ERP_MCP_REAL1 connector, when the reachability probe is performed, then evidence records observed endpoint/operation, timestamp, and result without credentials; unavailable access is `NOT_RUN` or failed with its exact error.
- **AC-2 (watchdog):** Given one selected in-scope lane component and the configured autostart mechanism, when that single component is stopped once, then before/after process or service evidence establishes whether the same component restarted; lack of observation or restart is not PASS.

#### S3.3 — Reconcile acceptance and later-sprint scope

**Trace:** REQ-006, REQ-016–REQ-017. **Depends on:** exact-head test/review evidence and current gate/scope records.

- **AC-1 (S12/S13/S15):** Given the current gate manifest, relevant change records, and exact-head evidence, when formal status is reported, then each S12/S13/S15 gate is promoted only with its required evidence; otherwise it remains unaccepted/unknown with the precise missing evidence.
- **AC-2 (S16 fidelity):** Given fake-backed unit/integration evidence and unavailable real-client, IdP, UAT, or deployment evidence, when S16 is reported, then fake evidence remains distinct and excluded items stay `NOT_RUN`/out of scope as appropriate.
- **AC-3 (future work):** Given the approved S17–S19 scope records after this queue is reconciled, when next work is proposed, then only explicitly covered items may enter a later sprint; uncovered items are deferred. GPT-PM owns product-scope adjudication. This dependency does not hold current-sprint work or acceptance evidence hostage.
- **AC-4 (safety):** Given all work and evidence, when sprint closure is reported, then the writer is still `UNQUALIFIED` and disabled, production bindings are empty, and no real POST/UNPOST, deployment, production, or real-money action is claimed or performed.

## Dependency order and sprint boundary

1. E1: S1.1 → S1.2 → S1.3 (the list/status interface may proceed alongside independent producer work once its actual ledger/service boundary is established).
2. E2: S2.1 → S2.2 → S2.3 → S2.4, honoring the S16 rev. 2 ordering and fake-only fallback.
3. Finish all code before E3.1 test authoring/execution, then collect E3.2 lane evidence and complete E3.3 evidence reconciliation. External evidence gaps do not erase completed work; report each affected criterion as `NOT_RUN`, failed, or unaccepted with its exact cause.
4. One PR covers this sprint. Each commit requires its own detailed linked change record in that commit under the project workflow; this planning artifact does not create or claim such records.

## Definition of Done

Accept an individual story only when its numbered ACs have linked, observable evidence. Sprint code closure requires all in-scope code committed with a per-commit change record, mapped functional/E2E evidence from the assigned test agents at the exact final head, relevant review consensus, and final GPT-PM approval for that exact head before any push/PR. Required docs/release notes and gate-manifest/status reconciliation must match actual evidence. Keep implementation, manual review, runtime-proven, and `NOT_RUN` states distinct. No story is accepted by this backlog alone; sprint-end decisions belong in `acceptance.md`.

## Handoff / ownership

| Item | Current planning state | Evidence or remaining acceptance | Dependency / blocker | Owner and next action |
|---|---|---|---|---|
| S1.1–S1.3, S2.1–S2.4 | READY; not implemented or accepted by this artifact | Implement within cited REQ and plan; then mapped test evidence | Normal ordered dependencies above; S16 fakes required if upstream formal acceptance is not evidenced | Codex: execute the scoped queue and preserve commit records |
| S3.1 | PLANNED; not run | Exact-final-head SQL/E2E and S15 commands/results, skips and limitations | Starts only after coding completes | Functional-test-reviewer and e2e-runner: author and execute mapped suites; Codex: reconcile |
| S3.2 | PLANNED; no current-turn live result | Connector probe and one-component restart evidence, or exact `NOT_RUN`/failure | Live lane/connector availability | Codex: collect authorized evidence; operator only if an actual reserved authority/action is required |
| S3.3 | PLANNED; acceptance unknown until reconciled | Current manifest/change-record evidence and later-scope decision | Required evidence records; S17–S19 adjudication applies only to later work | Codex: reconcile current gates; GPT-PM: adjudicate later scope and final exact-head approval |

## Recommended next steps

1. Codex starts E1, preserving the authorized repository and file scope and recording each implementation commit as required.
2. Codex completes E2 against fakes, following S16 rev. 2 hard constraints; do not wire, deploy, or enable the writer.
3. After coding is complete, the two assigned test agents execute E3.1; Codex gathers E3.2 evidence and reconciles E3.3.
4. GPT-PM reviews the complete final PR range on the exact final head; only a recorded approval for that head closes the pre-push gate. Any later code commit requires fresh approval.
