# Change record 159 — refresh registry after CR158 publication

Date: 2026-10-17. Status: documentation-only registry refresh; no source or test behavior changed.

## What changed and why

- Regenerated `governance/DOCUMENT_REGISTRY.md` from the current published HEAD, `b605ca71459b05c5cb34e011c74d47e721a5875a`, so it includes CR158. This is the follow-up to the previous registry refresh and keeps the index aligned with the published documentation set.

## Evidence

- Before generation, local `main` and `origin/main` both resolved to `b605ca71459b05c5cb34e011c74d47e721a5875a`.
- `node scripts/build_document_registry.mjs` completed and scanned four refs: local `main` and `origin/main` at `b605ca71459b05c5cb34e011c74d47e721a5875a`, plus agent worktree refs `dd819a4a85ff16ecedb0efcaf8e52911076682b8` and `f03852476d66c61c552c66fcb994ad25611d5d57`.
- Generator result: 232 tracked Markdown paths and 0 local-only paths. The registry now lists CR158.
- No tests, build, database operation, migration, real 1C/CT14 action, release or production operation was run for this documentation change.

## Project acceptance status

| Criterion | State | Remaining acceptance / dependency | Owner and next step |
|---|---|---|---|
| CR158 registry freshness | Complete locally; included by this generation | This registry snapshot reflects published HEAD `b605ca7` | GPT/Codex completed the local regeneration; obtain exact-head GPT review before publication |
| G0 | Narrow `PASSED`; unchanged | No scope expansion | Preserve the approved boundary |
| G1–G8 | `NOT_PASSED` | Gate-specific external evidence remains, including deployed DB/identity, source access, accountant report, UAT, operations, and controlled-change acceptance | Respective external lanes; people are not named in the canonical records. Obtain the lane evidence |
| S13 / R-01 / R-03 | Formal work remains open | S13 writer boundary/recovery evidence, R-01 receipt enforcement, and R-03 deployed key/custody provenance | Licensed writer/service and key-custody owners are not identified. Identify them and provide the evidence |
| Formal S14 / Release 2 | S14 `OPEN`; Release 2 `NO-GO`; production authorization `NONE` | S14 needs CT14-qualified channel evidence; release needs all predecessor gates and separate authorization | Channel owner is not named; production authorization remains operator-reserved |

## Affected paths and next action

- `governance/DOCUMENT_REGISTRY.md` (generated)
- `docs/phase2/CHANGE_RECORD_159.md`

This change record documents the local registry refresh. The remaining project closure criteria require external evidence and decisions listed above; this update does not change gate or production status. Obtain exact-head GPT-PM review before pushing this documentation-only commit.
