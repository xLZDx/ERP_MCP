# Change record 043 — refresh registry after Markdown review corrections

## What changed

- Regenerated the Markdown document registry after the S14-R03 status correction records became tracked and temporary review attachments were removed.

## Why

The prior registry generation occurred before the review attachments were removed and reflected the pre-commit inventory. This refresh records the current repository documentation inventory without transient PM review files.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- This record

No executable source, schema, tests, release gates, or runtime authorization changed.

## Verification state

- Registry generated with `node scripts/build_document_registry.mjs`.
- No tests or automated checks run; this is a documentation-only inventory refresh.
- Requires exact-range GPT-PM approval before push.
