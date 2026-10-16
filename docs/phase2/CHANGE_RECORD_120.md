# Change record 120 — reconcile current project status and S12 scope

## What changed

Reconciled project documentation to the current branch baseline `1ec73879ade35b112c428c9885b55c46452aa7df`, the GPT owner ruling for autonomous local engineering, and GPT's subsequent S12 Option A approval.

- Updated the README status and verification guidance. Removed broad pytest/full-suite and lint command examples. Clarified that a zero exit code, `NOT_RUN`, or `SKIP` alone is not PASS; PASS needs explicit terminal evidence tied to the exact revision and completed harness.
- Added a current SDLC reconciliation and marked the older G1/R-03 state section as historical. Recorded the next sprint and the S12 contract decision without changing the formal gate manifest.
- Reconciled S14 and the operator backlog: R-01 and R-03 remain formal OPEN risks; R-03 local implementation and focused evidence are complete; S13 local prototype evidence is complete while formal entry remains NOT_STARTED; the reliability MINOR is deferred to S18.
- Updated the G1 evidence plan to remove a stale “PM decision pending” heading and distinguish its historical approved push from current formal G1 acceptance.
- Marked the simulation plan's 2026-10-16 R-03 pre-019/021 inventory as historical and added the current owner ruling and v2.0 scope.
- Added the GPT-approved v2.0 scope to CT14 while preserving its limited disposable-clone evidence and explicitly unmeasured capabilities.
- Updated the R-03 design note to describe migrations 019/021 and recorded test/review outcomes; updated the S13 design note with migration 020 runtime evidence and the S18 deferral.

## Why

Several documents described the older local push baseline `ecd1779`, showed exact-head review as pending, or described the pre-migration-019/021 R-03 consumer gap as current. The README also prescribed broad checks rather than the owner-authorized focused workflow. The new reconciliation makes current local implementation, formal gate state, external evidence gaps, and the S12 contract decision legible without implying that formal risks or release gates have passed.

## Decisions and boundaries

- GPT owner ruling `b4e09308-7ae8-4170-92df-81ae67177bc1` authorizes autonomous local engineering and sets S12 Contract Freeze v2.0 as the next sprint. GPT approved Option A: keep signed `DispatchReceipt` separate from independent signed `OutcomeEvidence`; v2.0 writes are limited to `CREATE_DRAFT`, `POST`, and `UNPOST`.
- Added `S12_CONTRACT_FREEZE_V2_2026-10-16.md` as the local design artifact. PM Bridge request `9f20b7a3-d812-4f3a-8b67-5c3d291dd718` approved its exact SHA-256 `1ab1617dd78cb2e9c067986b61c33d825fa126d1eb87bf098e3571130acdc30d` with 0 BLOCKER/MAJOR/MINOR. Fresh code-architect, database-reviewer and security-reviewer reviews found no BLOCKER/MAJOR. This approves the local engineering contract only; it does not close formal S12 or authorize real COM/production use.
- Reconciled historical S12 revision 6 and `S12_APPROVAL_DIGEST_2_SPEC.md` with the freeze: inherit compatible authorization safeguards, admit only the three v2.0 operation kinds, keep digest domains distinct, and reject reinterpretation of earlier approvals.
- Target scope excludes Drive intake from v2.0, but `governance/GATE_MANIFEST.json` is intentionally unchanged until applicable formal scope/waiver authority is recorded. G4 is not marked passed.
- CT14 remains partial disposable file-clone evidence. OData writes, contract update, forced session termination, and unrelated work during an unresolved call remain outside v2.0 write scope.
- Formal G0–G8 statuses, formal S13 entry, Release 2 NO-GO, R-01/R-03 OPEN status, and production authorization NONE are unchanged. No production, staging, deletion, real-money, or external-account action is authorized here.
- The S13 nonce/record lock-order MINOR and its deterministic contention scenario are deferred to S18; the review found a transient deadlock possibility that aborts a transaction and cannot commit a false OFF result.
- Historical test commands/results remain where needed as provenance. Current evidence semantics require explicit terminal PASS correlated to the exact revision and completed harness; zero exit, `NOT_RUN`, `SKIP`, or missing terminal result alone is not PASS.

## Affected contracts and paths

- `README.md` — project status and owner-authorized verification guidance.
- `docs/sdlc/STATE.md` — current sprint, branch/remote baseline, evidence and formal-state matrix.
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md` — current risk/gate matrix, R-03 evidence, S12 queue, Drive disposition, and push baseline.
- `docs/phase2/OPERATOR_BACKLOG.md` — autonomous S12 queue, risk/evidence status, and historical snapshot boundaries.
- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md` — historical exact-head approval versus still-open formal G1 evidence.
- `docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md` — historical R-03 source inventory and current scope ruling.
- `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` — CT14 limits and v2.0 operation scope.
- `docs/phase2/R03_ED25519_NEW_ACTION_DESIGN.md` — migration 019/021 behavior, evidence and formal limitations.
- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md` — migration 020 implementation evidence and S18 reliability follow-up.
- `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md` — the owner-approved v2.0 design, separate from formal qualification.
- `docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md` and `docs/phase2/S12_APPROVAL_DIGEST_2_SPEC.md` — explicit historical-scope and digest reconciliation.
- `docs/phase2/CHANGE_RECORD_112.md` — clarifies that its historical pending-review note was superseded by later linked DB/security reviews.
- `docs/phase2/CHANGE_RECORD_120.md` — this change record.
- No source code, SQL, migrations, tests, gate manifest, or generated registry file was changed in this documentation reconciliation.

## Verification state

- Documentation reconciliation and S12 design finalization only; no tests, checks, builds, database commands or migrations were run. The generated document registry is regenerated as a separate required documentation step.
- The starting branch and `origin/main` were observed at `1ec73879ade35b112c428c9885b55c46452aa7df`; `.claude/` was unrelated untracked work and was left untouched.
- Earlier runtime results and specialist reviews are reported from CR112–119 and linked source documents; they were not rerun or independently revalidated during this documentation pass.
- The generated document registry is regenerated separately after all Markdown additions in this pass.

## Remaining documentation work

The formal GATE_MANIFEST remains unchanged pending its applicable scope/waiver authority. No human owners are invented where only an engineering lane or authority role is recorded. The SHA approval above refers to the initial freeze only; CR121 records a later receipt-to-read-back consistency clarification that requires fresh exact-revision GPT review.
