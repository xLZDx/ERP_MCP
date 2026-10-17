# Change record 160 — reconcile SDLC state with published repository head

Date: 2026-10-17. Status: documentation-only reconciliation; no source, test, database, or gate behavior changed.

## What changed and why

- Added a latest repository snapshot to `docs/sdlc/STATE.md` so its current-phase summary distinguishes the published documentation commits from the older S13 test/evidence heads.
- Marked the earlier repository and push references as historical while retaining their gate evidence and limitations.
- Recorded the CR159 exact-head GPT-PM approval and publication, plus the current formal gate/risk state, without changing any gate decision.

The SDLC state file continued to present pre-CR157 repository references as current after the registry maintenance commits had been approved and pushed. This reconciliation makes the current published HEAD explicit and keeps runtime evidence pinned to the source and review heads that actually produced it. During review, the initial draft's runtime-evidence pointer to CR145 was found stale: CR154 is the latest focused local S13 runtime evidence. The state snapshot now cites CR154 and retains its explicit formal-S13 limitations.

## Affected paths

- `docs/sdlc/STATE.md`
- `governance/DOCUMENT_REGISTRY.md` (regenerated after this record was committed)
- `docs/phase2/CHANGE_RECORD_160.md`

## Evidence and limits

- Previous published HEAD: `91c52ef1adc9672f8db465b6ef36fe8d1f2531ff`.
- CR159 exact-head GPT-PM approval: request `1b7bcd36-4632-497f-af85-c341bda444da`; verdict `APPROVE PUSH` for `91c52ef1adc9672f8db465b6ef36fe8d1f2531ff`.
- CR154 records the later local S13 runtime evidence: migrations 001–026, 47 classifier assertions, 14 PostgreSQL groups, disposable PostgreSQL 16 and an E2E scenario. These do not establish formal S13 entry or the missing writer/fence/provider acceptance.
- After CR160 was committed at `2b301ac436f7828bbd1152be087a54f38e0b0596`, `node scripts/build_document_registry.mjs` scanned four refs and generated 234 tracked Markdown paths and 0 local-only paths; the registry now includes CR160.
- CR159 is present on `origin/main`; this update does not alter test results, runtime evidence, G0–G8, S13/S14, R-01/R-03, Release 2, or production authorization.
- No tests, build, database operation, migration, CI, 1C/CT14 activity, or release/production operation was run for this documentation change.
- This change requires a new exact-HEAD GPT-PM review before publication.
