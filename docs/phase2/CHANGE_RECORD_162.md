# Change record 162 — record CR161 publication and refresh the registry

Date: 2026-10-17. Status: documentation-only publication reconciliation and registry refresh; no source, test, database, or gate behavior changed.

## What changed and why

- Updated `docs/sdlc/STATE.md` to record the CR160–CR161 exact-head approval and publication, while clearly treating `26be873` as the published baseline for this follow-up and pointing to later change records for newer updates.
- Updated `docs/phase2/CHANGE_RECORD_161.md` with the actual GPT-PM approval and verified push result, replacing the now-obsolete statement that review was still required.
- Regenerated `governance/DOCUMENT_REGISTRY.md` from published HEAD `26be8737353a398ab917b1cf42d14fd258295c61`, which now includes CR161.

The CR160–CR161 documentation range was approved and published. Its registry was generated before CR161 existed, so one final registry refresh was needed to include the newly published record and eliminate stale approval/push wording.

## Affected paths

- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_161.md`
- `docs/phase2/CHANGE_RECORD_162.md`
- `governance/DOCUMENT_REGISTRY.md` (generated)

## Evidence and limits

- CR160–CR161 exact-head GPT-PM review: request `6ceaf964-1557-4d3e-bbbc-11b8414c57a2`; `APPROVE PUSH` for `26be8737353a398ab917b1cf42d14fd258295c61`.
- Normal fast-forward push advanced `origin/main` from `91c52ef1adc9672f8db465b6ef36fe8d1f2531ff` to `26be8737353a398ab917b1cf42d14fd258295c61`; remote ref was read back at the exact HEAD.
- Registry generator: `node scripts/build_document_registry.mjs`; scanned local and remote `main` at `26be8737353a398ab917b1cf42d14fd258295c61` plus attached worktree refs `dd819a4a85ff16ecedb0efcaf8e52911076682b8` and `f03852476d66c61c552c66fcb994ad25611d5d57`. The expected inventory is 235 tracked Markdown paths and 0 local-only paths.
- No tests, build, database operation, migration, CI, 1C/CT14 activity, or release/production operation was run for this documentation change.
- This update does not alter G0–G8, CT14, S12–S19, R-01/R-03, Release 2, or production authorization; see the project risk/gate and sprint-plan records for remaining acceptance.
- GPT-PM request `eb4ff2e4-9116-4f5c-ac17-71b2311e9d3a` approved exact HEAD `48e9971da1d0ffb9d21d6b3a7a0037fa16982df9`; the normal fast-forward push completed and `origin/main` was read back at that hash. CR163 records the follow-up registry refresh that includes CR162.
