# Change record 090 — refresh the report document inventory

## What changed

- Refreshed `governance/DOCUMENT_REGISTRY.md` after the bilingual G1 local-push report update and `CHANGE_RECORD_089.md` were committed.
- The generated index lists 152 tracked Markdown paths and zero local-only paths across the scanned refs.

## Why

The registry content in commit `441f488` predated the committed report change record. The post-commit generation now includes the report record and updated evidence plan inventory state.

## Decisions and scope

- Generator: `node scripts/build_document_registry.mjs`.
- The generator scanned `main` at `441f488a3e2b063a21e7599ada506a3c113fb6fa`, attached worktree refs `dd819a4a85ff16ecedb0efcaf8e52911076682b8` and `f03852476d66c61c552c66fcb994ad25611d5d57`, and `origin/main` at `3aba6e37af8d3e5d1d98eb4f5f308e15aec1e3ac`.
- This is a generated-document-index update only. It does not change test results, code, database state, gate status or production authorization.
- As with the preceding generated registry records, this change record will be indexed on a later registry generation; no recursive registry-only commit is created.
- `.claude/` remains unrelated and unmodified.

## Review and verification state

- Registry generation completed successfully: 152 tracked paths, 0 local-only paths.
- No tests, builds, lint, CI, migrations, database operations or production actions were run.
- No push was performed.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_089.md`
- `docs/phase2/CHANGE_RECORD_090.md`

## Acceptance

- The index includes the committed report reconciliation record.
- The count and refs correspond to the generator output.
- No G1 or production gate status is changed.
