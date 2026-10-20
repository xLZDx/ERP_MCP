# Change record 122 — finalize document registry after S12 commit

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after the S12 implementation and reconciled documentation were committed as `8f430a4def949ec20b975b706bdc2239e030b0d9`.
- Recorded this registry-only follow-up so the S12 Markdown artifacts and their paths are discoverable in the inventory.

## Why

The registry generator inventories committed paths across refs plus untracked Markdown paths. Once CR120, CR121 and the S12 freeze were committed, their paths moved from local-only entries into the git-backed inventory; the registry needed a new snapshot.

## Affected paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_122.md`

## Verification state

- Ran the authorized documentation generator: `node scripts/build_document_registry.mjs`.
- No tests, checks, builds, database commands or migrations were run for this documentation-only follow-up.
- Registry generation reflects the current worktree inventory before this record's commit; the current main commit and `origin/main` were observed separately. The unrelated `.claude/` directory remains untouched.

## Delivery

This record is committed with the registry update. It does not change source, formal gate state, GPT approval status, or push authorization.
