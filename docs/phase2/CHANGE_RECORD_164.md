# Change record 164 — record CR163 publication and refresh the registry

Date: 2026-10-17. Status: documentation-only publication reconciliation and registry refresh; no source, test, database, or gate behavior changed.

## What changed and why

- Updated `docs/sdlc/STATE.md` to record the published CR163 baseline and its exact-head approval/push, while retaining the unchanged formal project acceptance state.
- Updated `docs/phase2/CHANGE_RECORD_163.md` with its actual GPT-PM approval and verified publication.
- Regenerated `governance/DOCUMENT_REGISTRY.md` from published HEAD `85a179455365dcfadd01f827feb1304cec7fe006`, adding CR163 to the indexed documentation baseline.

CR163's registry snapshot preceded its publication and omitted CR163. This follow-up refreshes the inventory from the published branch and records the completed approval/push. The registry is a snapshot of the explicitly listed baseline; this accompanying CR164 record documents the snapshot update and is not part of the earlier scanned ref.

## Affected paths

- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_163.md`
- `docs/phase2/CHANGE_RECORD_164.md`
- `governance/DOCUMENT_REGISTRY.md` (generated)

## Evidence and limits

- CR163 exact-head GPT-PM review: request `8b0b481a-b3ef-4e67-941f-4fcd993cf51b`; `APPROVE PUSH` for `85a179455365dcfadd01f827feb1304cec7fe006`.
- Normal fast-forward push advanced `origin/main` from `48e9971da1d0ffb9d21d6b3a7a0037fa16982df9` to `85a179455365dcfadd01f827feb1304cec7fe006`; the remote ref was read back at the exact HEAD.
- Registry generator: `node scripts/build_document_registry.mjs`; scanned local and remote `main` at `85a179455365dcfadd01f827feb1304cec7fe006`, plus worktree refs `dd819a4a85ff16ecedb0efcaf8e52911076682b8` and `f03852476d66c61c552c66fcb994ad25611d5d57`.
- Generator result: 237 tracked Markdown paths and 0 local-only paths; CR163 is included in this baseline.
- No tests, build, database operation, migration, CI, 1C/CT14 activity, or release/production operation was run for this documentation change.
- This update does not alter G0–G8, CT14, S12–S19, R-01/R-03, Release 2, or production authorization.
- Exact-head GPT-PM review is required before publishing this commit.
