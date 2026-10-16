# Change record 100 — document registry refresh

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after committing the R-03 Ed25519 new-action design and its change record.
- Added this record so the registry refresh has a dedicated linked detail file in the same commit.

## Why

The generated inventory must expose the newly committed design and preserve the repository's per-commit change-record convention.

## Scope and decisions

- Documentation inventory only; no source code, SQL, tests, database, or gate state changed.
- The R-03 design remains proposed for a non-gating prototype and awaits its requested PM design ruling before implementation.

## Verification state

- Ran `node scripts/build_document_registry.mjs` after the design commit and again after adding this record.
- No tests, builds, migrations, database queries, or production operations were run.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/R03_ED25519_NEW_ACTION_DESIGN.md`
- `docs/phase2/CHANGE_RECORD_099.md`
- `docs/phase2/CHANGE_RECORD_100.md`
