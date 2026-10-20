# Change record 094 — index the reconciled G1 status documents

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after the G1 push/status reconciliation records 092 and 093 were added.
- The registry now contains 156 tracked Markdown paths and 0 local-only paths, including `CHANGE_RECORD_092.md` and `CHANGE_RECORD_093.md`.

## Why

The active G1 status-document reconciliation introduced tracked Markdown records after the prior inventory refresh. The index must reflect the current branch and attached worktree document paths.

## Decisions and scope

- Generator: `node scripts/build_document_registry.mjs`.
- Scanned refs at generation time: local `main` at `baecdd66391c459594800873d6559f8b24c42c28`, remote `origin/main` at `17900345c88237290c498d73b6f8849c265351d1`, and two attached agent-worktree refs.
- This update is a generated documentation inventory only. It changes no code, tests, database state, G1 gate status, Release 2 status, or production authorization.
- `.claude/` is unrelated and remains untouched.

## Review and verification state

- Registry generation completed: 156 tracked Markdown paths, 0 local-only paths.
- No tests, builds, lint, CI, migrations, database operations, or production actions were run.
- No push was performed. This and later documentation HEADs need fresh exact-head PM approval before any push.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_092.md`
- `docs/phase2/CHANGE_RECORD_093.md`
- `docs/phase2/CHANGE_RECORD_094.md`

## Acceptance

- Registry indexes the newly reconciled active status documents and their change records.
- Generated path counts match the generator output.
- Formal G1/release/production statuses remain unchanged.