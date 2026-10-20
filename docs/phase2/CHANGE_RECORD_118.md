# Change record 118 — regenerate the document registry for the final evidence set

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after commit `28d390b` added CR111, CR114, CR117, and the S13 reliability backlog note.
- Updated CR117 with the final generator result.

## Why

The registry generator reads committed repository paths. Running it after the evidence records were committed makes the final index include those records and their linked design note.

## Verification state

- `node scripts/build_document_registry.mjs`: exit 0; scanned 4 refs and wrote 182 tracked paths plus 1 local-only path (this pending CR118 record). The generated inventory includes committed CR111, CR114, and CR117.
- No tests, database commands, or migrations are part of this documentation-only update.

## Affected paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_117.md`
- `docs/phase2/CHANGE_RECORD_118.md`
