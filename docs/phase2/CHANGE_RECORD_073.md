# Change record 073 — clarify G1 runtime evidence scope

## What changed

- Defined “runtime evidence” in the G1 evidence plan as exact-revision observations from focused acceptance scenarios in a disposable PostgreSQL environment.
- Linked the requirement to the G1 acceptance behaviors that need execution evidence, including concurrency/CAS, termination during explicit COMMIT and distinct-cluster restore.
- Clarified that this is a G1 gate requirement, not a general prerequisite for local work, and that deployed grants, authenticated identities and capacity disposition need separate evidence.
- Added the clarification to the G1 backlog and SDLC Verify checkpoint without changing any gate state.

## Why

The prior status report used “mandatory runtime evidence” without explaining either its scope or its source. The controlled-change plan includes kill-inside-COMMIT and separate-cluster restore in G1's original exit criteria, while the G1 backlog defines negative-behavior and concurrency acceptance. Source review alone cannot establish those observed database outcomes. The wording now distinguishes that requirement from unrelated development work and from external deployment evidence.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/sdlc/STATE.md`
- `core/DECISION_LOG.md`
- `docs/phase2/CHANGE_RECORD_073.md`

## Verification state

- Compared against G1 in `docs/phase2/PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` and the current G1 backlog; no tests, checks, database operations, container operations, migrations, or legal verification were run.
- Required focused execution remains `NOT_RUN` because workspace rules prohibit pytest; no bypass was attempted.
- G1 remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO`.
