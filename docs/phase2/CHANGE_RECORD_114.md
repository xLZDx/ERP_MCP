# Change record 114 — intermediate document registry refresh after the first R-03 and S13 closure pass

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after commits `ffccbc3` (R-03 migration 021 and focused acceptance evidence) and `10f89ba` (S13 migration 020 runtime evidence).
- This was an intermediate generation: later CR115/CR116 added more R-03 coverage records. CR117 records the final refresh and updates CR111.

## Why

The document inventory was refreshed once after the first completed test pass. The final index was regenerated again after subsequent test coverage and review follow-ups.

## Verification state

- `node scripts/build_document_registry.mjs`: exit 0; scanned 4 refs and wrote 178 tracked paths, with no local-only paths.
- No tests, database commands, or migrations are part of this documentation update.

## Affected paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_111.md`
- `docs/phase2/CHANGE_RECORD_114.md`
