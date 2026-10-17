# Change record 165 — make document-registry provenance explicit

Date: 2026-10-17. Status: documentation and registry-generator correction; no product behavior, test, database, or gate evidence changed.

## What changed and why

- Updated the registry generator and generated inventory to identify the exact Git refs and commit IDs captured by each inventory, and to state that the result is a point-in-time snapshot.
- Regenerated the registry from local `main` at `29153331028eb50e1dea02b66d2b3defef7be95e`, the two listed agent worktree refs, and `origin/main` at `85a179455365dcfadd01f827feb1304cec7fe006`.
- The inventory has 238 tracked Markdown paths. This change record existed as an untracked Markdown file when the generator ran and is listed in the snapshot's local-only section. Its later commit does not change what refs the snapshot represents.
- This resolves the CR164 review finding that the inventory listed CR164's tracked path count but described itself as a complete current-branch list without identifying the scanned baseline.

## Affected paths

- `scripts/build_document_registry.mjs`
- `governance/DOCUMENT_REGISTRY.md` (generated)
- `docs/phase2/CHANGE_RECORD_165.md`

## Evidence and limits

- CR164 documentation review: `doc-updater` / GPT-6 Luna / bounded review; one MINOR about ambiguous registry scope, no BLOCKER/MAJOR. The finding was resolved by recording point-in-time scope and exact ref IDs.
- Registry generation command: `node scripts/build_document_registry.mjs`; result: 238 tracked paths, 1 local-only Markdown path (`docs/phase2/CHANGE_RECORD_165.md`).
- No tests, checks, builds, database operations, migrations, CI, CT14 activity, or release/production operations were run for this change.
- This update does not change G0–G8, CT14, S12–S19, R-01/R-03, Release 2 status, or production authorization.
- GPT-PM exact-head review is required before publishing this commit. The earlier CR164 request `bb40222d-39f2-4ff5-b179-41a078b71d0c` has no demonstrably completed correlated approval and cannot authorize this later HEAD.
