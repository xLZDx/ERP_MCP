# Change record 086 — reconcile the G1 SDLC state

## What changed

- Reconciled the G1 metadata in `docs/sdlc/STATE.md` to distinguish the restore assertion correction (`69857fd`), the current MAJOR-02 lock-observer code/test head (`a6263e4`), the historical source-level review (`17b6de7`), the 44-path branch review (`c2157e7`), and the documentation baseline before this update (`0800269`).
- Added missing Phase 7 artifact references for change records 082, 084, 085, and this record 086.
- Updated the review count from 40 to 44 paths and scoped the no-BLOCKER/MAJOR result to branch review HEAD `c2157e7`, before later documentation commits.
- Preserved current acceptance: focused local evidence is complete, local push is pending a fresh PM decision, formal G1 remains `NOT_PASSED`, production authorization remains `NONE`, and Release 2 remains `NO-GO`.
- Refreshed `governance/DOCUMENT_REGISTRY.md` against the current branch before this update; the generated index includes record 085.

## Why

The SDLC summary had conflated an earlier source-level review with the later branch review, retained an obsolete 40-path count, and omitted subsequent correction and documentation records. This made its code/test head and evidence lineage ambiguous.

## Decisions and scope

- `17b6de7` is identified only as a historical source-level review.
- `c2157e7` is the final branch-review head for the 44-path no-BLOCKER/MAJOR result; it does not include later documentation commits.
- `a6263e4` is the current code/test head after the lock-observer correction; `0800269` is the documentation baseline before this state reconciliation.
- This is documentation-only. It does not alter code, tests, gate state, or PM approval requirements.
- `.claude/` and unrelated worktree changes are preserved.

## Review and verification state

- Facts reconciled against `G1_EVIDENCE_PACKET_PLAN.md`, S14, change records 082–085, and the branch review result recorded there.
- Registry generation completed with `node scripts/build_document_registry.mjs`; it included record 085 and the prior branch artifacts.
- No tests, checks, builds, migrations, database operations, or production actions were run.
- No push was performed.

## Contracts and paths

- `docs/sdlc/STATE.md`
- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_086.md`

## Acceptance

- The SDLC state distinguishes the source review, branch review, current code/test head, and documentation baseline.
- The 44-path review result is not attributed to documentation commits after `c2157e7`.
- Artifact references include records 082, 084, 085, and 086.
- Local push and formal G1 remain pending as stated; production remains unauthorized.
