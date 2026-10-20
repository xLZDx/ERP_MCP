# Change record 066 — clarify required restore and crash-recovery candidates

## What changed

- Marked the distinct-cluster restore scenario explicitly as the required G1-B08 candidate and the same-cluster scenario as supplemental only.
- Listed both parameter values (`page`, `ingest`) for the supplemental SIGKILL recovery scenario and kept the observed explicit-COMMIT case as the required candidate for that documented gap.
- Recorded the read-only reviewer follow-up and updated the SDLC Verify artifact index.

## Why

The functional-test-reviewer confirmed the criterion-to-scenario table substantially addressed the prior mapping gaps, then identified ambiguity in the restore row and omission of the crash-recovery parameter values. This edit makes those boundaries explicit without claiming test execution or deciding unresolved gate scope.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_066.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`

## Verification state

- Read-only follow-up by `functional-test-reviewer` (GPT-6 Luna, low effort) confirmed prior substantive findings addressed and identified the two clarifications above.
- No tests, checks, builds, migrations, databases, PostgreSQL, Docker, or identity operations were run.
- G1 remains `NOT_PASSED`; runtime remains `NOT_RUN`; production authorization remains `NONE`.
