# Change record 063 — reconcile the SDLC checkpoint head

## What changed

- Updated `docs/sdlc/STATE.md` to distinguish the repository HEAD at checkpoint update start (`765dc66527a97e750a69e400ad0855cc299e814a`) from the exact G1 code HEAD reviewed by GPT-PM (`17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`).
- Linked the G1 evidence packet plan change record in the Verify-phase artifact table.

## Why

The checkpoint still showed an older repository baseline after later documentation commits. Recording the current repository baseline and the separately reviewed code HEAD avoids implying that later documentation-only commits were included in the static code review.

## Contracts and paths

- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_063.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`

## Verification state

- Read-only `git rev-parse HEAD` confirmed the recorded repository baseline before this documentation change.
- No tests, checks, builds, migrations, database, PostgreSQL, or Docker operations were run.
- Gate and runtime statuses are unchanged: G1 `NOT_PASSED`, runtime `NOT_RUN`, production authorization `NONE`.
