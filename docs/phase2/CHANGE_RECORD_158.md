# Change record 158 — reconcile CR157 publication and refresh registry

Date: 2026-10-17. Status: documentation-only follow-up; no source, test, database or production behavior changed.

## What changed and why

- Updated CR157 to record its exact-head GPT-PM approval and verified publication, replacing the now-stale “review and push pending” next action.
- Regenerated `governance/DOCUMENT_REGISTRY.md` from published HEAD `71f72f5e52783753b797f12384d5970c6184589d`; this adds CR157 to the published document index and resolves the remaining freshness gap for that record.

## Evidence

- CR157 exact-head review request `ca1ab3ac-11fe-4b65-9bdf-f9fc8198cbe8` returned `APPROVE PUSH` for HEAD `71f72f5e52783753b797f12384d5970c6184589d`, based on `4f0f422bf6af091eacbb3f1028fbcd92358c6f8d`.
- Push of `71f72f5e52783753b797f12384d5970c6184589d` completed; `git ls-remote origin refs/heads/main` confirmed the same SHA.
- `node scripts/build_document_registry.mjs` completed at published HEAD `71f72f5e52783753b797f12384d5970c6184589d`. It scanned local `main` and `origin/main` at that SHA and the two agent worktree refs `dd819a4a85ff16ecedb0efcaf8e52911076682b8` and `f03852476d66c61c552c66fcb994ad25611d5d57`. Output: 231 tracked Markdown paths, 0 local-only paths.
- No tests, build, database operation, migration, real 1C/CT14 action, release or production operation was run for this documentation change.

## Project acceptance status

| Criterion | State | Remaining acceptance / dependency | Owner and next step |
|---|---|---|---|
| CR157 registry freshness | Complete locally; publication evidence recorded | None for this correction | GPT/Codex completed the exact review and push record |
| G0 | Narrow `PASSED`; unchanged | No expansion of prior narrow approval | Preserve the accepted scope |
| G1–G8 | `NOT_PASSED` | Gate-specific evidence remains, including target infrastructure, source access, accountant attestation, UAT, operations and full controlled-change acceptance | Respective external lanes; several responsible people are not named. Obtain the evidence listed in the gate packet |
| S13 / R-01 / R-03 | Formal work remains open | S13 needs the actual writer/service boundary and recovery-safe fencing; R-01 needs receipt enforcement evidence there; R-03 needs deployed key/custody provenance | Licensed writer/service and key-custody owners are not named. Identify them and supply the missing evidence |
| Formal S14 / Release 2 | S14 `OPEN`; Release 2 `NO-GO`; production authorization `NONE` | S14 requires CT14-qualified channel evidence; release requires all predecessors and separate production authorization | Channel owner is not identified; production authorization remains reserved to the operator |

## Affected paths and next action

- `docs/phase2/CHANGE_RECORD_157.md`
- `governance/DOCUMENT_REGISTRY.md` (generated)
- `docs/phase2/CHANGE_RECORD_158.md`

This change record covers the local documentation update. Further project closure requires the external evidence and decisions summarized above; it does not authorize a gate transition or production action.
