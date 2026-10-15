# Change record 032 — decision record registry refresh

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after adding the correlated GPT-PM decision record for S14-R02.
- Included the new change record in the tracked-document inventory.

## Why

The document registry should expose the durable approval correlation and avoid leaving the S14 review record undiscoverable.

## Contracts and paths

Documentation maintenance only; no source, tests, runtime behavior, or project gates changed.

Affected paths: `governance/DOCUMENT_REGISTRY.md`.

## Verification state

The generator scanned four refs after commit `b603e0cee2d67775f357539692bb83a6aa277451` and reported 89 tracked Markdown paths with no local-only Markdown files. This record is committed together with the registry update, bringing the inventory to 90 tracked paths. The generator is run again after commit to confirm the checked-in file matches the resulting inventory.
