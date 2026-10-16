# Change record 071 — resolve G1-B07 concurrency coverage scope

## What changed

- Updated the G1 evidence plan's candidate map and minimal runtime proposal to include separate head-promotion CAS, conflicting cursor-page commit, and identical-page replay scenarios.
- Resolved the prior scope question using the G1-B07 backlog acceptance wording, which expressly calls for concurrent workers, compare-and-swap (CAS), stale fencing, and replay to prove pass/fail.
- Refreshed the SDLC checkpoint and decision log. No gate status was changed.

## Why

The functional-test reviewer had left these concurrency cases for gate-level disposition. The accepted backlog wording already establishes the relevant invariants, so the test plan can map them now instead of leaving an avoidable ambiguity. Including each race separately keeps evidence tied to distinct outcomes: one winner for head promotion, one winner for conflicting cursor advancement, and exactly-once behavior for an identical page replay.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/sdlc/STATE.md`
- `core/DECISION_LOG.md`
- `docs/phase2/CHANGE_RECORD_071.md`

## Verification state

- Read-only comparison against the G1-B07 backlog acceptance wording; no tests, checks, database operations, container operations, migrations, or legal verification were run.
- The added cases are required runtime candidates; all results remain `NOT_RUN` under the project pytest prohibition.
- G1 remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO`.
- Documentation registry was not regenerated because `docs/phase2/S10_RELEASE_HANDOFF.md` documents that its generator includes local branch/worktree state and can make a machine-specific registry diff.
