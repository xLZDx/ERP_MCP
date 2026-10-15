# Change record 035 — S14 synthetic dispatch adapter contract

## What changed

- Added the implementation contract for a reusable synthetic dispatch coordinator.
- Recorded the next S14 slice in the simulation plan and backlog.
- Added the decision and explicit trust-boundary limits to the decision log.

## Why

The combined SQL scenario currently spells out ledger gating, canonical payload verification, the
clone write and receipt persistence inline. A narrowly scoped coordinator can make this already-tested
sequence reusable while keeping SQL as the authority and preserving unknown outcomes.

## Contracts and paths

Affected paths: `docs/phase2/S14_SYNTHETIC_DISPATCH_ADAPTER_2026-10-15.md`,
`docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`, `docs/phase2/OPERATOR_BACKLOG.md`, and
`core/DECISION_LOG.md`.

No runtime code, SQL migration, or tests changed in this documentation-first commit. The coordinator
will accept existing IDs but will not mint authorization artifacts, retry writes, complete a change,
or implement the real `OneCWritePort`.

## Verification state

Documentation-only; no tests or checks run. The runtime implementation, focused functional/E2E
evidence, specialist review, GPT-PM exact-head review and push remain pending.
