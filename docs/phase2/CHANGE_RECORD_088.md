# Change record 088 — refresh the G1 document inventory

## What changed

- Refreshed `governance/DOCUMENT_REGISTRY.md` after `CHANGE_RECORD_087.md` entered the main branch.
- The generated registry now lists 150 tracked Markdown paths and zero local-only paths across the scanned refs.

## Why

The registry generated with change record 087 was produced before that record was committed, so it listed 087 as a local-only path. The post-commit generation makes the inventory reflect the committed G1 evidence update.

## Decisions and scope

- Generator: `node scripts/build_document_registry.mjs`.
- The generator scanned `main` at `6974dd8d3b460348e3eb709ac1849b3c8dae7f4d`, two attached worktree refs (`dd819a4a85ff16ecedb0efcaf8e52911076682b8`, `f03852476d66c61c552c66fcb994ad25611d5d57`), and `origin/main` at `3aba6e37af8d3e5d1d98eb4f5f308e15aec1e3ac`.
- This is a documentation-index refresh only. It does not alter code, tests, database state, gate status, or production authorization.
- The registry indexes tracked Markdown documents on refs and untracked Markdown in attached worktrees; this refresh record itself will be indexed by a later generation after it is committed, avoiding a recursive registry-only cycle.
- `.claude/` remains unrelated and unmodified.

## Review and verification state

- Registry generation completed successfully: 150 tracked paths, 0 local-only paths.
- No tests, checks, builds, migrations, database operations or production actions were run.
- No push was performed.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_087.md`
- `docs/phase2/CHANGE_RECORD_088.md`

## Acceptance

- The registry now lists committed change record 087 under Git documents rather than local-only Markdown.
- Counts and scanned refs are recorded with the generator result.
- No G1 or production gate status is changed.
