# Next-sprint preparation — S17–S19

**Purpose:** record the smallest actionable scope for work after the current `beea27520b33`
finisher sprint. This is a planning artifact. It does not accept a story, pass a gate, or claim
runtime evidence.

## Scope decision

The current operator direction authorizes continuing through the remaining stages within the
accepted scope (GO-1 through GO-4, as relayed in the current task). The repository's approved
planning baseline already defines S17–S19: `docs/phase2/PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md`
revision 5, `docs/phase2/S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md`, and the
canonical IDs in `docs/phase2/S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md` §3.
Therefore no new scope approval or intermediate GPT-PM gate is needed to prepare or start work
inside those existing boundaries. The original finisher brief's S16-only scope bounded that
sprint; it does not cancel the later stages authorized by the current direction.

Use dependency order for implementation: S17, then S18, then S19. The plan allows S18 to overlap
S17 after S13–S16, but this preparation recommends sequential sprint slices to keep one PR per
sprint and to complete S17's intake security review before S19 acceptance. This is sequencing,
not added approval.

## Evidence snapshot and limits

| Item | State | Evidence | Remaining acceptance / dependency | Owner and next action |
|---|---|---|---|---|
| S12/S13/S15 formal acceptance | Not accepted by this artifact; reconcile from current gate evidence | `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md` §§2–4 says upstream formal acceptance is absent/unknown; `CHANGE_RECORD_403.md` says SQL/source work is implemented but database/runtime evidence is `NOT_RUN` | Use current exact-head test and review evidence against `governance/GATE_MANIFEST.json`; do not infer acceptance from source | Codex: reconcile evidence at current sprint close |
| S16 code slice | Implemented in source; tests/reviews and acceptance remain pending | `docs/phase2/CHANGE_RECORD_404.md`, `405.md`, and `406.md`; `src/erp_mcp_s16/` contains the isolated core, approval page, five tools, and inert ingress | Current sprint phase-7 tests/reviews and required final GPT-PM exact-head approval; no listener, production binding, or real 1C activity is evidenced | Codex: finish current sprint closure; GPT-PM: required final exact-head review |
| Manifest sprint states | Stale relative to implementation records; not acceptance | `governance/GATE_MANIFEST.json` still labels S12 `IN_PROGRESS` and S13–S19 `NOT_STARTED` with null evidence; CR403–406 record later implementation work but explicitly do not claim acceptance | Keep formal manifest status unchanged until evidence is reconciled and any authorized manifest update is supported | Codex: reconcile after current required evidence; never promote from code records alone |
| S17–S19 implementation landscape | **Partial reusable components exist; stories are not thereby delivered** | S17: `src/business_ai_gateway/phase2/safe_parser.py` exposes bounded values-only `parse_workbook`/`parse_csv` and `run_isolated`; `aliases.py` has scoped `AliasResolver`; `workbench_session.py` has in-memory cards/annotate/rerun/enqueue. S18: `scheduler.py`/`ports.py` define `SourceScheduler`/`JobQueuePort`; `alert_rules.py` has `AlertEngine`/`deliver_events`. S19: `scripts/validate_gate_manifest.mjs` already validates schema-2 manifest structure, evidence digests, predecessor DAG and waivers. | Integrate only where contracts fit; close the gaps below and provide each sprint's tests, reviews and evidence. Existing modules are offline/evaluation-only where stated; none alone proves the planned story accepted. | Codex: reuse and extend the listed components; do not rebuild an existing validator or treat existing source as acceptance |

`S16_SPRINT_PLAN` §5 explicitly excludes S17 from S16. That is a sprint boundary, not a
cancellation of S17's separately listed, approved scope. GO-1 through GO-4 are taken from the
current task direction; their underlying correlated records were not present in the cited
repository evidence, so this artifact does not claim to have independently verified those
responses.

| Sprint | Plain-language outcome | Planning state | Evidence / completed preparation | Remaining acceptance | Dependency or blocker | Recommended next action / owner |
|---|---|---|---|---|---|---|
| S17 | Uploaded-document intake and reviewed workbench | **SELECTED for next sprint; scope ready** | Existing S17 row and six canonical story IDs in the 2026-10-17 map and S11 register; reusable parser, resolver and workbench facade noted below | Assemble upload-to-provenance-to-human-review flow; address platform containment gap; complete exact-head functional/E2E, security, UX/a11y, and H3 evidence | S16 source phase must close before intake integration; current S16 acceptance evidence remains in the current sprint | Start after current sprint gate; Codex |
| S18 | Queue reliability, recovery, alerts, measured service objectives, security and rights drift | **CARRIED; approved scope, later sprint** | Existing S18 row and six story IDs in the map/register; per-source scheduler and in-memory alert engine exist | Build per-base capacity-20 queue/parking and independently delivered human alerts; measure/review required lane behavior; add rights-matrix drift read | Depends on S13–S16 contracts/evidence; call termination remains conditional on exact CT14 evidence | Prepare after S17 code is complete; Codex |
| S19 | Release evidence, gate G8, engineering-complete C1 | **CARRIED; approved scope, final sprint** | Existing S19 row and five story IDs in the map/register; schema-2 validator already handles DAG/digests/waivers | Reuse validator; add exact-head evidence binding and invariant-to-passing-boundary matrix completeness; reconcile 46 active scenarios and reviews | Depends on S17, S18 and earlier sprint evidence; missing lane evidence stays `NOT_RUN` | Begin after S17/S18 evidence; Codex; GPT-PM owns final exact-head approval |

## Prioritized stories

Priority rule: protect existing security/accounting contracts first, then follow the approved
dependency order, then deliver release-evidence work last. The story IDs and themes below are
canonical; criteria operationalize the approved plans without adding a new feature.

### Sprint S17 — document intake and workbench

**Goal:** provide a bounded, reviewable path from uploaded XLSX/CSV or manual entry to a proposed
change, retaining source provenance and company scope. No Drive integration.

| Story | Trace and readiness | Numbered acceptance criteria (Given / When / Then) | Dependency / owner |
|---|---|---|---|
| V2-S17-01 — untrusted-file boundary | Ready from S17 map, CT11 and S11 test design | 1. Given an uploaded file over the configured size or decompression limit, when parsing is requested, then it is rejected before unbounded extraction. 2. Given a file containing formulas, external references, or an outbound-I/O trigger, when parsed, then no formula is evaluated, no external content is fetched, and no authority or target is changed. | Start after S16 code phase closes; Codex implements, test agents verify |
| V2-S17-02 — extraction | Ready; retain the frozen extraction cross-check cases | 1. Given supported XLSX/CSV input, when extracted, then each material value retains field-level source provenance. 2. Given totals whose lines plus VAT disagree with the stated total, when cross-checked, then the mismatch is surfaced for review and no unsupported proposal is emitted. 3. Given PDF/image input before H3 qualifies, when processed, then it is best-effort and cannot bypass review. | S17-01; Codex |
| V2-S17-03 — entity resolution | Ready; company scope and human confirmation are explicit | 1. Given same-named entities in different companies, when a user resolves a name, then candidates are restricted to the selected company. 2. Given an ambiguous or unmatched entity, when a proposal is prepared, then human confirmation is required and ambiguity is preserved. | S17-02; Codex |
| V2-S17-04 — hostile corpus | Ready; use E7/E27/E40 and S11 corpus | 1. Given each hostile corpus case, when ingestion runs, then it yields a safe rejection or a clean digest without prohibited I/O, privilege change, or unreviewed material-field approval. | S17-01/02; Codex implements, functional-test-reviewer and e2e-runner own tests |
| V2-S17-05 — workbench | Ready; limited to the approved upload/manual-entry workbench | 1. Given a parsed candidate, when the user reviews it, then provenance, material-field review, and unresolved items are visible before proposal. 2. Given a failed or retried item, when the user opens the change list, then current status and retry/rollback-proposal affordances reflect service state and do not approve or apply a change. | S16 service APIs; Codex; UX/a11y specialists for changed UI |
| V2-S17-06 — H3 measurement | Ready; frozen H3 definitions remain authoritative | 1. Given the fixed H3 evaluation set of N=30, when measured using the frozen counting rule, then the reported corrected-material-field rate is X≤10%. 2. Given any confidently wrong material field, when a result is evaluated, then it cannot pass without human review. | S17-02/04; Codex coordinates evidence; no acceptance from synthetic-only results where plan requires lane evidence |

**Sprint DoD:** required functional/E2E corpus and extraction cases on exact head; intake-specific
security review after implementation; UX/a11y review for workbench changes; H3 evidence reported
with the frozen denominator and counting rule. Real accountant/user UAT remains gate G5 evidence,
not an inferred pass.

#### Minimal S17 implementation queue from current source

| Order | Reuse / gap | Evidence and boundary | Smallest next implementation action | Owner |
|---|---|---|---|---|
| 1 | Reuse `safe_parser.py` value extraction (`parse_workbook`, `parse_csv`) and `run_isolated` process boundary | Current source bounds input before parsing; checks ZIP entry count before `ZipFile` metadata construction (with documented ZIP64 residual); limits decompressed member/total bytes, ratios, rows, cells and text; never evaluates formulas; denies external relationships/content types; runs XLSX in a scrubbed child with bounded JSON and timeout. POSIX uses `RLIMIT_AS`; Windows uses a per-process Job Object memory cap and returns `BOUND_MEMORY` without parsing if it cannot be established. This is a crash/resource boundary, not a sandbox: the child retains caller privileges. `parse_csv` is currently bounded in-process. No application upload caller exists yet. | Keep the parser contract; correct the stale Windows-cap statement; add final S17 named evidence for the Windows Job Object setup/fail-closed path and for no formula evaluation/external fetch. Compose upload/manual entry later through S17-05 without describing this parser as a sandbox. | Codex |
| 2 | Reuse scoped `AliasResolver` and `WorkbenchSession` | `aliases.py:186,237` resolves under `AliasScope`; it is not connected to intake. `workbench_session.py:166,271–317` supplies in-memory `EVALUATION_ONLY` cards, annotation, rerun and enqueue APIs; it is not an assembled upload/provenance flow. | Compose parser output with field provenance, company-scoped entity confirmation, and the existing review/session boundary; keep proposal/apply decisions in S16 service contracts. | Codex |
| 3 | Add only missing end-to-end flow and measured acceptance | S11 test package §C S17 row defines E7/E27/E40, extraction cross-checks, company-overlap case and H3 `N=30`, `X≤10%`; approved S17 map row defines upload/manual entry, no Drive. | Implement upload/manual entry through review and proposal with hostile-file and provenance checks; then run mapped tests/security/UX review and H3 measurement under the test ownership rules. | Codex; test agents; relevant reviewers |

### Sprint S18 — reliability and independent security verification

**Goal:** deliver bounded queueing, recovery, observability and independent review for the approved
test-lane architecture; preserve fail-closed behavior where writer/channel evidence is absent.

| Story | Trace and readiness | Numbered acceptance criteria (Given / When / Then) | Dependency / owner |
|---|---|---|---|
| V2-S18-01 — queue and parking | Ready from S18 map and CT15; target bound 20 | 1. Given 20 queued items for one base, when another is submitted, then overflow is refused safely. 2. Given call ownership is unresolved for a target, when new work arrives, then that target is parked without affecting other bases. 3. Given verification reads and writes compete, when scheduled, then verification-read priority and shutdown drain follow the approved policy. | S13–S16 contracts; Codex |
| V2-S18-02 — chaos and restarts | Ready as test-lane work; target-channel kill safety is conditional | 1. Given each approved crash window, when a component or lane is restarted, then persisted state recovers to the specified safe state or remains held. 2. Given CT14 has not measured safe termination for the exact channel/base, when a call is stuck, then force termination remains disabled and that branch is `NOT_RUN`. | S18-01; Codex prepares; functional/E2E agents own execution |
| V2-S18-03 — alerting and supervision | Ready from approved alert and supervisor scope | 1. Given a forced failure, when local logs are unavailable, then the independent alert delivery path reaches its configured recipient or reports delivery failure. 2. Given a supervised process exits, when the approved test-lane supervisor observes it, then the same component is restarted and the before/after evidence is recorded. | Codex implements; target-lane access is an evidence dependency only |
| V2-S18-04 — measured SLOs and failure table | Ready; no numeric SLO threshold invented here | 1. Given measured approved-lane runs, when the failure table and SLOs are published, then every value names workload, environment, measurement, and limitation. 2. Given no lane measurement exists, when reporting, then the item remains `NOT_RUN`, not a pass. | S18-02/03; Codex |
| V2-S18-05 — independent security review | Ready after S17 intake boundary is implemented | 1. Given the implemented architecture and S11 threat model TM1–TM20, when reviewed, then findings identify reachable actor paths and evidence; valid BLOCKER/MAJOR findings are closed in one focused batch before acceptance. | S17-specific intake review follows S17; Codex coordinates review and fixes |
| V2-S18-06 — rights-matrix drift | Ready from approved periodic read | 1. Given the approved current rights matrix, when the periodic comparison runs, then drift is detected and reported without mutating grants or sources. | Read-only lane/metadata availability; Codex |

**Sprint DoD:** exact-head functional/E2E, measured lane evidence for SLO and alert receipt,
database/reliability/security reviews as applicable, R1 compatibility and migration rehearsal.
External lane unavailability leaves only its dependent evidence `NOT_RUN`; it does not suspend
independent code or documentation preparation.

#### Minimal S18 implementation queue from current source

- Reuse `SourceScheduler` (`scheduler.py:257,367`) and `JobQueuePort` (`ports.py:210`) as a
  per-source lease/job foundation. The current shape is not the approved per-base queue with
  capacity target 20, verification-read priority and cross-job target parking; add that contract
  deliberately rather than relabelling the source scheduler.
- Reuse `AlertEngine` and `deliver_events` (`alert_rules.py:288,487`) for event/rule evaluation.
  Its documented `EVALUATION_ONLY` in-memory sinks are not an independent human delivery path;
  provide and measure the separate delivery boundary and delivery-failure reporting.
- `drift.py` models capture/failure drift, not rights-matrix drift. Add the periodic read-only
  rights comparison specified by V2-S18-06. Measure SLOs only on an observed lane; no target value
  is invented in this preparation.

### Sprint S19 — release candidate, gate G8 and engineering-complete C1

**Goal:** bind engineering evidence to exact revisions and validate the approved acceptance matrix;
prepare a canary recipe only for separate operator authorization.

| Story | Trace and readiness | Numbered acceptance criteria (Given / When / Then) | Dependency / owner |
|---|---|---|---|
| V2-S19-01 — exact-head manifest | Ready from manifest contract | 1. Given every sprint's evidence, when a manifest entry is prepared, then it binds the exact revision and evidence digest and is not advanced from a planning or implementation record alone. | S17/S18 and earlier evidence; Codex |
| V2-S19-02 — gate-closure validator | Ready from E46 | 1. Given a missing predecessor or invalid/unsigned waiver, when validation runs, then closure is refused. 2. Given a valid configuration with complete evidence, when validation runs, then only the contract-defined status is returned. | Codex; required test owner executes acceptance tests |
| V2-S19-03 — invariant matrix completeness | Ready from I1–I15 map and E47 | 1. Given invariants I1–I15 and active golden scenarios, when completeness is checked, then each invariant maps to at least one passing enforcement-boundary assertion. | Prior sprint evidence; Codex |
| V2-S19-04 — residual-risk record | Ready from accepted mutation-test replacement contract | 1. Given all review and test results, when residual risk is recorded, then every open, deferred, blocked, and `NOT_RUN` item retains its factual status and owner. | Exact-head evidence; Codex |
| V2-S19-05 — canary recipe | Ready as a preparation deliverable only | 1. Given engineering evidence is complete, when the recipe is prepared, then it names scope, safeguards, rollback, and required operator signature without executing the canary or implying production authorization. | S17/S18 and earlier gates; Codex prepares, operator alone owns production signature |

**Sprint DoD:** G8 evidence covers 46 active scenarios (E1–E47 except reserved E8), on required
lanes with exact-head tests/reviews and final GPT-PM approval for that head. C1 means
`ENGINEERING_COMPLETE`; it does not pass G1–G7 or authorize production. Unavailable lane evidence
remains explicitly `NOT_RUN`; no canary, production write, or real-money action is included.

#### Minimal S19 implementation queue from current source

- Keep and extend `scripts/validate_gate_manifest.mjs`: it already enforces schema 2, evidence
  digests, mandatory predecessor relationships/DAG and waiver validity. Do not rebuild this
  validator.
- Add exact-head revision binding for the sprint evidence and the S11 I1–I15 to passing
  enforcement-boundary assertion completeness result. `phase2/validation_coverage.py` is a
  capability-validation matrix and is not that invariant-to-boundary acceptance map.
- Reconcile existing manifest states against exact-head evidence; implementation records alone
  do not pass S12–S19 or G8. Preserve every unavailable lane item as `NOT_RUN`.

## Decisions, boundaries, and ordered next actions

- Keep Drive intake disabled; uploaded files and manual entry are S17's approved intake paths.
- Keep the v2.0 write catalogue limited to purchase-receipt draft/create, post, and unpost under
  existing contracts; no contract update, delete/mark-for-deletion, payments, bulk writes, staging,
  or production write is added.
- Keep the private writer `UNQUALIFIED` and disabled until its own evidence supports qualification.
- Do not treat source completion as story acceptance. Functional/E2E agents own required tests;
  Codex reviews coverage and reconciles exact-head outcomes; GPT-PM owns the final exact-head
  approval where required by the established workflow.
- Decisions reserved to the operator remain reserved: deletion, real-money commitments,
  production authorization and any production canary signature. No other routine scope decision is
  escalated by this artifact.

| Order | Action | Owner | Effect / dependency |
|---|---|---|---|
| 1 | Finish current sprint test/review and final approval work without changing this scope note | Codex; test agents; GPT-PM | Current sprint closure evidence; this preparation does not delay it |
| 2 | Start S17 implementation from the six canonical stories and this DoD | Codex | Upload/manual-entry workbench only; no Drive |
| 3 | After S17 code, complete its test and intake-security review evidence; then implement/close S18 | Codex and assigned test/reviewer roles | Test-lane-specific gaps remain `NOT_RUN`; safe local engineering proceeds |
| 4 | After S17/S18 evidence, execute S19 evidence reconciliation and closure work | Codex; GPT-PM for exact-head approval | G8/C1 only if required exact evidence passes |
| 5 | Reserve production/go-live authorization and any production canary decision | Operator | Required only for the separate production action; not a blocker for S17–S19 local engineering |

