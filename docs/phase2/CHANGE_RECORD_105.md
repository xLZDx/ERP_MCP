# Change record 105 — index revised S13 recovery design

## What changed

- Regenerated `governance/DOCUMENT_REGISTRY.md` after the S13 recovery design's PM-driven revision.
- Added this detail record for the registry update commit.

## Why

The index must expose the current design revision and its follow-up review record rather than leaving the revised acceptance and failure contract undiscoverable.

## Scope and decisions

- Documentation inventory only; migration 020 remains unimplemented pending PM approval of the revised design.
- The separate R-03 migration 019 remains local and uncommitted; it is not included in this registry commit.

## Verification state

- Ran `node scripts/build_document_registry.mjs` after the revised design commit and after adding this record.
- Tests, SQL checks, database commands, migrations, and formal gate changes: `NOT_RUN`.

## Contracts and paths

- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md`
- `docs/phase2/CHANGE_RECORD_104.md`
- `docs/phase2/CHANGE_RECORD_105.md`
