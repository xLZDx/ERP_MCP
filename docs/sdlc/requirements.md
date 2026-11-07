# ERP_MCP Phase 2 Finisher Requirements

Sprint: beea27520b33

## Goal and scope

Complete the explicitly authorized Phase 2 finisher queue recorded in the operator's Phase 2 finisher brief and the repository's S12/S15/S16 plans. Work order: close S12/S13 follow-ups, complete the S16 rev. 2 requirements, collect final-head test and external-lane evidence, and report each gate from observed evidence. S17–S19 work is conditional on the approved scope records and is not silently included in this sprint.

## Evidence categories

### FACT

- The S12 amendment defines 39 Python refusal codes and states that SQL still emits `BUDGET_EXCEEDED` for an exhausted grant, has no parity test, and lacks real producers for period and exhausted-budget evidence (`docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md`, “Contract status” and “Backward compatibility”).
- S12 requires `period_observed_open` to be positively established; a closed period maps to `PERIOD_CLOSED`, while absent observation fails closed (`docs/phase2/CHANGE_RECORD_398.md`, “Changes”). A real-data producer is still listed as open in that record.
- The S12/S13 follow-up record lists the missing SQL migration, real producers, G3 in-flight list/status, and unrerun slow SQL/E2E and S15 suites (`docs/phase2/CHANGE_RECORD_398.md`, “Still open”; `docs/phase2/CHANGE_RECORD_399.md`, “Contract status”).
- S16 rev. 2 defines an unwired, fake-backed approval channel and MCP surface, depends on S15, and explicitly forbids production binding, deployment, COM writes, and enabling the writer (`docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, §§2–5).
- S16 rev. 2 requires an S16-owned decision core, apply-time revalidation, positive authentication on the private listener, `VerifyPort` behavior including `UNSUPPORTED_SHAPE` for POST/UNPOST, and `rollback_propose` behavior (`docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, §§5.1–5.4, E16-3, E16-4).
- Approval nonce and `preview_digest` are issued by `ApprovalService`/`ChangeService`; the preview must render the canonical bytes covered by the digest (`docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, §5.3).
- The rev. 2 plan leaves S12/S13 and S15 formal acceptance unknown/not accepted, and requires fake-level evidence to remain distinct from real integration evidence (`docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, §§2–4, 7–9).
- Project workflow assigns functional and E2E test authoring/execution to `functional-test-reviewer` and `e2e-runner`, after all sprint coding is complete (`D:\Repo\AGENTS.md`, “Test ownership”; `D:\Repo\ERP_MCP\AGENTS.md`, “Verification”).

### ASSUMPTION

- “Final head” means the exact candidate head after all in-scope implementation commits; the two test agents must record that hash with their commands and results. This follows the project’s exact-head evidence requirement (`D:\Repo\AGENTS.md`, “Operator development and reviewer rules”).
- The user’s ordered finisher brief authorizes the S12/S13 follow-ups and S16 rev. 2 within the named safety boundaries; it does not authorize production binding or real POST/UNPOST.

### UNKNOWN

- Formal S12/S13/S15 acceptance after the latest source and evidence reconciliation. Existing planning/status documents contain dated claims, but they are not current acceptance evidence by themselves.
- Whether the named ERP connector and watchdog lane are reachable and restart correctly in the present environment; this requires live evidence.
- Whether S17–S19 have approved, current scope sufficient to begin implementation after this queue.

## Requirements

| ID | Testable requirement | Source | Priority |
|---|---|---|---|
| REQ-001 | The SQL refusal-code registry shall expose `PERIOD_CLOSED` and `GRANT_EXHAUSTED` such that its canonical set matches the Python registry of 39 codes; the exhausted-grant SQL path shall return `GRANT_EXHAUSTED` wherever that distinction is representable. A parity test shall compare both registries and exercise the exhausted-budget path. Any remaining inexpressible Python-only cases shall be enumerated in the associated change record. | Finisher brief; `docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md`; `docs/phase2/CHANGE_RECORD_398.md` | P1 |
| REQ-002 | A real-data period producer shall populate the S12 period evidence from one authenticated observation of the target accounting period. It shall set the open/closed evidence consistently from that observation; closed maps to `PERIOD_CLOSED`, and missing, contradictory, stale, unauthenticated, or otherwise unproven evidence shall not authorize apply. | Finisher brief; `docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md`, “Review resolutions”; `docs/phase2/CHANGE_RECORD_398.md` | P1 |
| REQ-003 | A real-data budget producer shall feed `BudgetCheck.EXHAUSTED` when the observed grant has no remaining amount and a positive amount is requested. It shall preserve `BUDGET_EXCEEDED` for other budget refusals as specified by the S12 amendment. | Finisher brief; `docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md`, items 2–3 | P1 |
| REQ-004 | The operator-facing S12/S13 interface shall expose a list of in-flight changes and a status function sufficient to identify each listed change’s current status; returned values shall come from the relevant ledger/service state rather than a test-only fixture. | Finisher brief (G3); `docs/phase2/CHANGE_RECORD_398.md`, “Still open” | P1 |
| REQ-005 | At the final implementation head, the required slow SQL/E2E suites and S15 suites shall be authored/executed by the assigned test agents and reported with exact head, command, result, skips, and limitations. A missing runtime dependency shall be `NOT_RUN` with the observed dependency/error; historical results shall not be reported as current-head proof. | Finisher brief; `docs/phase2/CHANGE_RECORD_398.md`; `docs/phase2/S15_SPRINT_PLAN_2026-10-27.md`, §9; `D:\Repo\AGENTS.md`, “Test ownership” | P1 |
| REQ-006 | S12/S13 acceptance status shall be promoted only when the required acceptance evidence exists and is reconciled against the current gate manifest; otherwise the report shall state the exact unmet evidence and preserve the non-accepted status. | Finisher brief; `docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md`; `governance/GATE_MANIFEST.json` | P1 |
| REQ-007 | S16 decision rules shall reside in the S16 core and remain correct when backing stores are permissive; persistence, clock, and randomness may be supplied through ports/fakes. Apply shall revalidate the base fingerprint, principal epoch, approver validity, target/base binding, kill switch, and claim-once behavior at application time. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, §§5.1–5.2 and review resolutions §14 | P1 |
| REQ-008 | The approval flow shall obtain nonce and `preview_digest` from `ApprovalService`/`ChangeService`; the displayed preview shall be rendered from the same canonical bytes covered by the digest, and replay or tampering shall not produce an accepted decision. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, §5.3 and E16-1 | P1 |
| REQ-009 | The private listener shall require valid positive authentication on every request; loopback/network origin alone shall not authenticate. Foreign `Origin`/`Referer`, proxy-forwarding headers, mismatched host, public target, redirect, proxy route, or DNS rebinding path shall fail closed without invoking the apply port. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, E16-4 | P1 |
| REQ-010 | The model-facing tool list shall contain exactly five tools—`propose`, `status`, `apply`, `verify`, and `rollback_propose`—and shall expose no approval action or alias. Direct attempts to invoke an approval action shall be safely refused without changing state. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, E16-3 | P1 |
| REQ-011 | `verify` shall pass through S15 verifier outcomes unchanged; POST and UNPOST shapes shall return `UNSUPPORTED_SHAPE` and shall not transition the change to `VERIFIED`. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, E16-3 items 6–6a | P1 |
| REQ-012 | `rollback_propose` shall create a separate UNPOST proposal for rollback of a verified POST, requiring its own approval and current observed target state; rollback of CREATE_DRAFT and UNPOST shall be refused with `ROLLBACK_REFUSED`. It shall never apply or approve a rollback itself. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, E16-3 item 7 and Q14 | P1 |
| REQ-013 | S16 refusal responses shall use the shared safe error registry and shall not disclose raw exception text, stack traces, secrets, or internal identifiers; model-supplied approval claims shall not alter preview or state. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, E16-3, E16-5 | P1 |
| REQ-014 | The ERP_MCP_REAL1 connector reachability check shall report the observed endpoint/operation, timestamp, and result without exposing credentials; unavailable access shall be recorded with the exact error as `NOT_RUN` or failed, not inferred from prior status. | Finisher brief; connector reachability check | P1 |
| REQ-015 | The watchdog restart check shall stop exactly one in-scope lane component once, observe that the configured autostart mechanism restarts that same component, and record before/after process or service evidence. It shall not be described as passed if the component does not restart or the observation is unavailable. | Finisher brief; watchdog restart check | P1 |
| REQ-016 | Throughout this sprint, the private writer shall remain `UNQUALIFIED` and disabled, the production binding set shall remain empty, and no real 1C POST/UNPOST, deployment, production action, or real-money action shall be performed. | Finisher brief; `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`, §2; `D:\Repo\ERP_MCP\AGENTS.md`, “Hard limits” | P0 |
| REQ-017 | S17–S19 implementation shall start only to the extent explicitly covered by current approved scope records after the S12/S13/S15/S16 queue is reconciled; every item without such scope shall be reported as deferred, not assumed authorized by this finisher brief. | Finisher brief; `docs/phase2/S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md` | P1 |

## Non-functional targets

The approved sources provide no numeric latency, throughput, availability, or recovery-time target for this finisher scope. No new numeric service-level target is introduced here. Existing numeric contract targets remain authoritative where applicable (for example, exactly 39 refusal codes in REQ-001 and exactly five MCP tools in REQ-010).

## Evidence issues to reconcile (not new scope)

- The amendment and change records describe the SQL parity migration and real-data producers as absent, while dated reports may record earlier partial code or tests. Verify current source and exact-head agent evidence before changing a status claim.
- The S16 plan marks S12/S13/S15 formally unaccepted/unknown and says it did not re-read the gate manifest or S15 change records. Reconcile those records before any gate promotion; the plan alone cannot establish current state.
- S16’s scenario sources differ; rev. 2 records the union while deferring E2, and marks real-client, production IdP, UAT, and deployment evidence out of scope or `NOT_RUN`. Preserve these dispositions unless newer authorized evidence changes them.

## Open questions and ownership

No unresolved product choice blocks starting the scoped implementation: S16 rev. 2 already resolves its implementation questions for this slice, including fake-backed persistence, private-listener default, no public approval, transcript provenance, POST/UNPOST unsupported verification, rollback mappings, and typed authenticated principals.

| ID | Open item | Owner | Next action / blocking effect |
|---|---|---|---|
| UNKNOWN-001 | Current formal acceptance of S12, S13, and S15 | Codex | Reconcile current gate manifest, accepted evidence, and exact-head test results before reporting any promotion; blocks only acceptance claims. |
| UNKNOWN-002 | Live ERP_MCP_REAL1 connector reachability result | Codex | Run the authorized read-only reachability probe and preserve its exact result/error; blocks only the connector evidence claim. |
| UNKNOWN-003 | Current watchdog restart outcome and evidence | Codex | Perform the single-component restart check within the authorized lane boundary and record observed result; blocks only the watchdog evidence claim. |
| UNKNOWN-004 | Approved S17–S19 scope after the current queue | GPT-PM | Adjudicate current plan/scope records when the current queue is complete; blocks only work outside the already authorized finisher queue. |

## Traceability and acceptance handoff

Requirements REQ-001–REQ-006 trace to S12/S13; REQ-007–REQ-013 trace to S16 rev. 2; REQ-014–REQ-015 trace to the explicit connector/watchdog checks; REQ-016 records binding safety limits; REQ-017 bounds later sprint work. `functional-test-reviewer` and `e2e-runner` own the required focused and final-head tests after all in-scope coding. GPT-PM owns the single final review on the exact final head; no intermediate PM review is part of this handoff.
