# Change record 065 — map G1 criteria to concrete test scenarios

## What changed

- Replaced the candidate test-file inventory in `G1_EVIDENCE_PACKET_PLAN.md` with a criterion-to-scenario map covering isolation, runtime privileges, approver/evidence boundary, server time, concurrency/replay, observed COMMIT termination, distinct-cluster restore, capacity smoke, static preflight and mutation evidence.
- Added required/supplemental classifications, what each result can support, and explicit limits on what it cannot prove.
- Updated the SDLC Verify checkpoint to record the reviewer pass and the remaining need for authorized test-agent selection.

## Why

The read-only `functional-test-reviewer` pass (GPT-6 Luna, low effort) found the earlier file list insufficient for minimal test selection: it lacked exact criterion-to-scenario links, left concurrency's gate role unclear, and could blur fixture grants with deployed role evidence. This revision maps observed test names while reserving disputed minimal-set decisions for the authorized test and gate reviewers.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_065.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`

## Verification state

- Read-only agent review and source inspection of module docstrings/test names only.
- No test, check, build, migration, database, PostgreSQL, Docker or identity operation was run.
- The map is a candidate for authorized test-agent selection, not test execution evidence. Runtime is `NOT_RUN`; G1 is `NOT_PASSED`; production authorization is `NONE`.
