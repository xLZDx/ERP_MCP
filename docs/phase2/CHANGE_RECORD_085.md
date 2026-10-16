# Change record 085 — refresh the generated document registry

## What changed

- Added the registry output generated after `CHANGE_RECORD_084.md` was committed.
- The generated inventory includes the newly committed record 084 and reports 147 tracked Markdown paths with no local-only paths.
- Kept this generated artifact update in a separate commit because the registry generator inventories Git refs; it cannot include a new record in its branch inventory until that record is committed.

## Why

The first registry generation ran before record 084 was part of the main branch, so its output represented the worktree state rather than the newly committed document inventory. A post-commit generation corrected the registry. This follow-up record explains why the generated registry is delivered separately from the substantive documentation reconciliation.

## Decisions and scope

- Registry generation command: `node scripts/build_document_registry.mjs`.
- The generator scanned `main` at `5fdda0d454662f78ee12a65f310a83951f8a0f7c`, two attached worktree refs, and `origin/main`.
- This record documents that refresh; as with other generated inventories, it becomes part of the registry's Git-ref inventory at the next registry generation after this commit.
- No source code, test, database, migration, or production state is changed.
- `.claude/` and all unrelated worktree changes are preserved.

## Review and verification state

- Registry generation completed successfully and reported 147 tracked paths and 0 local-only paths.
- No tests, checks, builds, migrations, database operations or production actions were run.
- No push was performed.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_085.md`

## Acceptance

- The committed registry reflects a successful post-084 generation.
- The reason for separating this generated-artifact commit from the G1 reconciliation commit is recorded.
- No unrelated worktree path is included.
