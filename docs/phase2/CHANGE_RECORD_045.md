# Change record 045 — clean change-record formatting

## What changed

- Removed the extra blank line at the end of CHANGE_RECORD_044.md.
- Refreshed the Markdown registry after the packet commit and this follow-up record.

## Why

The staged-diff whitespace review of commit `14ffdec` found one trailing blank line in the new detail record. This documentation-only follow-up keeps the commit record clean without rewriting history.

## Contracts and paths

- `docs/phase2/CHANGE_RECORD_044.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`
- This record

No executable source, schema, tests, gate state, key material, or runtime authorization changed.

## Verification state

- `git diff --check` will be run on this documentation-only delta before commit.
- No tests or migration checks run.
- The combined exact range requires GPT-PM approval before push.
