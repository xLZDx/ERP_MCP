# Change record 096 — refresh registry after G1 report reconciliation

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after `CHANGE_RECORD_095.md` became part of the local `main` history.
- At the recorded generation time, the refreshed inventory had 158 tracked Markdown paths and 0 local-only Markdown paths in attached worktrees.
- The current checked-in registry snapshot has 158 tracked Markdown paths and 1 local-only Markdown path: this self-referential `CHANGE_RECORD_096.md` entry.

## Why

The registry had been generated while record 095 was still untracked, so it listed that path as local-only. Once record 095 was committed, the registry needed to move it into the tracked-document index.

## Decisions and scope

- Generator: `node scripts/build_document_registry.mjs`.
- Scanned refs at generation time: local `main` at `0dec6ec5e783c7917c705a80795ea3dcc75a611f`, remote `origin/main` at `13b8ee2e067fcd70158b74dc36307d0dfb3332aa`, and two attached agent-worktree refs.
- This updates the Markdown inventory only. It changes no source code, tests, database state, formal gate, release authorization, or production state.
- `.claude/` remains unrelated and untouched.

## Review and verification state

- Historical generator output at the generation time recorded above: 158 tracked paths, 0 local-only paths.
- Current checked-in `governance/DOCUMENT_REGISTRY.md` snapshot: 158 tracked paths, 1 local-only path, namely this self-referential `CHANGE_RECORD_096.md` entry. These are different snapshots; the current registry does not report 0 local-only paths.
- The bilingual report `--check` passed after the report edits.
- No tests, builds, lint, CI, migrations, database operations, or production actions were run.
- No push was performed; any later push requires a fresh exact-head PM decision.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_095.md`
- `docs/phase2/CHANGE_RECORD_096.md`

## Acceptance

- Registry indexes the committed G1 report reconciliation. The recorded generation counts describe that run; the current checked-in snapshot separately includes this self-referential record as its one local-only path.
- Report formatting check passed and the formal G1/S13/release/production statuses remain distinct and unchanged.
