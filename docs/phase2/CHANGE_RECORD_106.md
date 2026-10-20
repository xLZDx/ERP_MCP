# Change record 106 — normalize S13 registry snapshot

## What changed

- Recorded the follow-up normalization of `governance/DOCUMENT_REGISTRY.md` after change record 105 became part of the committed main branch.
- Regenerated the registry so its current inventory reflects the committed S13 design and registry records.

## Why

The first registry refresh was generated while change record 105 was still local-only. After that record was committed, a follow-up refresh was needed to reconcile the generated inventory with the new branch history.

## Scope and decisions

- Documentation index only; no product code, tests, database, migration, or formal gate state changed.
- Migration 020 remains pending the revised PM design ruling.

## Verification state

- Ran `node scripts/build_document_registry.mjs` after change record 105 was committed.
- Tests, SQL checks, database commands, and migrations: `NOT_RUN`.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_105.md`
- `docs/phase2/CHANGE_RECORD_106.md`
