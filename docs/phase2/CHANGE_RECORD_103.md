# Change record 103 — document registry refresh for S13 design

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` to index the S13 kill-switch recovery design and its design change record.
- Added this record for the registry-refresh commit.

## Why

The repository's generated Markdown index should surface the new durable S13 design and its independent review basis.

## Scope and decisions

- Documentation inventory only. The design remains proposed and awaits a PM ruling before migration 020 implementation.
- No application or SQL source, tests, database, or formal gate state changed.

## Verification state

- Ran `node scripts/build_document_registry.mjs` after the S13 design commit and after adding this record.
- No tests, SQL checks, database commands, or migrations were run.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md`
- `docs/phase2/CHANGE_RECORD_102.md`
- `docs/phase2/CHANGE_RECORD_103.md`
