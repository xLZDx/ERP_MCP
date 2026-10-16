# Change record 111 — refresh registry after S13 addendum decision

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` to include change record 110 and the revised S13 addendum status.

## Why

The generated inventory must index the durable sequencing decision before focused S13 verification begins.

## Scope and decisions

- Generated output only; no runtime or gate state changed.
- Regenerate with `node scripts/build_document_registry.mjs`, never by hand.

## Verification state

- Earlier refresh after CR110 completed: `node scripts/build_document_registry.mjs` exited 0, scanning 4 refs and writing 175 tracked paths plus 2 local-only paths. Later R-03/S13 evidence records were indexed in the final refresh recorded in CR117.
- Tests, database commands, and migrations: `NOT_RUN`.

## Affected paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_111.md`
