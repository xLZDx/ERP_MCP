# Change record: document registry refresh after WP0 prompt commit

## Summary and reason

Regenerated the Git-ref-only document registry after commit `3bd4b126377b23a513a77da445ff29f4935147be`
added the operator's autonomous prompt bundle and WP0 evidence. The earlier snapshot was made
before those documents became tracked and therefore did not enumerate them.

## Affected paths

- `governance/DOCUMENT_REGISTRY.md` — generated snapshot now records 46 refs and 432 tracked
  Markdown paths; local-only files remain `NOT_ENUMERATED`.
- `core/LESSONS_LOG.md` — records the sequence lesson to regenerate after new files are
  committed.
- `docs/commits/2026-10-22-document-registry-refresh.md` — this linked change record.

## Verification state

Command: `node scripts/build_document_registry.mjs --exclude-local-only`.
Result: exit 0; `scanned 46 refs`; `wrote governance/DOCUMENT_REGISTRY.md: 432 tracked paths;
local-only NOT_ENUMERATED.` The captured ref for the active branch was the first prompt-bundle
commit above. The generator was not run in `--check` mode. No tests, CI, build, or migrations
were run for this documentation change.

This commit contains only the generated registry and its record/lesson entry. It is local and
does not authorize push/PR; publication still waits for GPT-PM approval of the exact final head.
