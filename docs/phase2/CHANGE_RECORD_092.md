# Change record 092 — refresh the G1 document registry

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after adding `CHANGE_RECORD_091.md` and reconciling the G1 push reports.
- The index now lists 154 tracked Markdown paths and 0 local-only paths, including change records 090 and 091.

## Why

The registry is generated from Markdown paths across local and remote branches. The approved-push reconciliation added a new tracked change record, so the index needed to include it.

## Decisions and scope

- Generator: `node scripts/build_document_registry.mjs`.
- The scan included local `main` at `9fb39b2845b99a835e1ebaa864824f86bdbda309`, remote `origin/main` at `17900345c88237290c498d73b6f8849c265351d1`, and the two attached agent-worktree refs present at generation time.
- Registry generation changed documentation inventory only. It does not change code, tests, database state, formal G1 status, Release 2 status, or production authorization.
- `.claude/` remains unrelated and unmodified.

## Review and verification state

- Registry generator completed and reported 154 tracked Markdown paths, 0 local-only paths.
- No tests, builds, lint, CI, migrations, database operations, or production actions were run.
- The resulting documentation HEAD remains local; any push requires fresh exact-head PM approval because the prior decision covered only `17900345c88237290c498d73b6f8849c265351d1`.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_091.md`
- `docs/phase2/CHANGE_RECORD_092.md`

## Acceptance

- The index includes records 090 and 091 and reports the generated inventory count.
- The registry commit has a dedicated change record.
- Formal G1 and production/release statuses remain unchanged.