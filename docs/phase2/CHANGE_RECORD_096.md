# Change record 096 — refresh registry after G1 report reconciliation

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after `CHANGE_RECORD_095.md` became part of the local `main` history.
- The refreshed inventory includes 158 tracked Markdown paths and no untracked Markdown paths in attached worktrees at generation time.

## Why

The registry had been generated while record 095 was still untracked, so it listed that path as local-only. Once record 095 was committed, the registry needed to move it into the tracked-document index.

## Decisions and scope

- Generator: `node scripts/build_document_registry.mjs`.
- Scanned refs at generation time: local `main` at `0dec6ec5e783c7917c705a80795ea3dcc75a611f`, remote `origin/main` at `13b8ee2e067fcd70158b74dc36307d0dfb3332aa`, and two attached agent-worktree refs.
- This updates the Markdown inventory only. It changes no source code, tests, database state, formal gate, release authorization, or production state.
- `.claude/` remains unrelated and untouched.

## Review and verification state

- Registry generation completed: 158 tracked paths, 0 local-only paths.
- The bilingual report `--check` passed after the report edits.
- No tests, builds, lint, CI, migrations, database operations, or production actions were run.
- No push was performed; any later push requires a fresh exact-head PM decision.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_095.md`
- `docs/phase2/CHANGE_RECORD_096.md`

## Acceptance

- Registry indexes the committed G1 report reconciliation and records the generated counts.
- Report formatting check passed and the formal G1/S13/release/production statuses remain distinct and unchanged.
