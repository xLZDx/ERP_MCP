# Change record 119 — regenerate the registry after the final evidence records

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after commit `7fc239f` committed CR111, CR114, CR117, and the S13 reliability follow-up.

## Why

The earlier CR118 registry run correctly recorded its then-local-only status. This final run uses the committed history so the index reflects the repository state before this registry-update commit.

## Verification state

- Command: `node scripts/build_document_registry.mjs` — exit 0; scanned 4 refs and wrote 183 tracked paths with no local-only Markdown paths.
- No tests, database commands, or migrations were part of this documentation update.

## Affected paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_119.md`
