# Change record 161 — correct S13 evidence pointer and refresh registry

Date: 2026-10-17. Status: documentation-only correction and registry refresh; no source, test, database, or gate behavior changed.

## What changed and why

- Corrected `docs/sdlc/STATE.md` to identify CR154, not CR145, as the latest focused local S13 runtime evidence. The entry states the bounded result and preserves CR154's limitations: formal S13 is not approved, and cross-process writer/fence/provider acceptance remains unproven.
- Corrected `docs/phase2/CHANGE_RECORD_160.md` to record the evidence-pointer correction and the actual registry generation after CR160 was committed.
- Regenerated `governance/DOCUMENT_REGISTRY.md` after CR160 became part of local `main`, so the tracked-document inventory includes CR160.

The documentation reviewer identified the stale pointer in CR160's first committed version. This correction uses the later CR154 evidence and does not broaden its claims or change any gate status.

## Affected paths

- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_160.md`
- `docs/phase2/CHANGE_RECORD_161.md`
- `governance/DOCUMENT_REGISTRY.md` (generated)

## Evidence and limits

- Registry generator: `node scripts/build_document_registry.mjs`.
- Scanned refs: local `main` `2b301ac436f7828bbd1152be087a54f38e0b0596`; worktree refs `dd819a4a85ff16ecedb0efcaf8e52911076682b8` and `f03852476d66c61c552c66fcb994ad25611d5d57`; remote `origin/main` `91c52ef1adc9672f8db465b6ef36fe8d1f2531ff`.
- Generator result: 234 tracked Markdown paths and 0 local-only paths; CR160 is included.
- CR154 records functional and E2E evidence on disposable PostgreSQL 16 and independent DB/security/reliability review; it does not establish formal S13 entry or full mutation/physical-writer, provider, signer, or service-transaction acceptance.
- No tests, build, database operation, migration, CI, 1C/CT14 activity, or release/production operation was run for this documentation change.
- GPT-PM request `6ceaf964-1557-4d3e-bbbc-11b8414c57a2` approved exact HEAD `26be8737353a398ab917b1cf42d14fd258295c61`; the fast-forward push completed, and `origin/main` was verified at that hash. The subsequent registry refresh and status-record update are documented in CR162.
