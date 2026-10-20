# Change record 070 — record the proposed minimum G1 runtime set

## What changed

- Added the read-only functional-test-reviewer proposal for a minimal focused runtime set to `G1_EVIDENCE_PACKET_PLAN.md`, linked to G1-B04 through G1-B08 criteria.
- Recorded supplemental/excluded candidates and the unresolved gate-scope question for concurrent head promotion and cursor-page commits.
- Updated the SDLC Verify checkpoint with the proposed-set review and its limits.

## Why

The prior candidate map was ready for test-agent selection, but the Verify phase could advance further without executing tests by getting an actual functional-test reviewer to propose the smallest falsifiable set. The proposal keeps deployed identity, effective role mapping, capacity disposition and gate-specific approval as separate evidence, and does not decide gate authority questions.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_070.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`

## Verification state

- Read-only proposal by `functional-test-reviewer` (GPT-6 Luna, low effort); no tests/checks or runtime operations were executed.
- All proposed results remain `NOT_RUN`. The minimum set is a test-planning recommendation, not gate approval.
- G1 remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO`.
