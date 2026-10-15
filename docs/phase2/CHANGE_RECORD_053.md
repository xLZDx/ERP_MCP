# Change record 053 — reconcile program-plan gate status

## What changed

- Updated the simulation program plan's current status to G0 `PASSED` and G1–G8 `NOT_PASSED`.
- Marked earlier plan approvals as historical snapshots and added a current-status reconciliation tied to the exact G0 approval and evidence digest.
- Updated the decision log to replace the stale note that the gate validator was pending.
- Regenerated the document registry.

## Why

Post-G0 searches found status claims in the program plan and decision log that predated the gate-specific approval or validator run. They could be read as current. This update preserves the original review history while making current gate state consistent with the manifest.

## Contracts and paths

- `docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`
- This record

No executable source, SQL, test, manifest gate state, or runtime authorization changed.

## Verification state

- Reconciled with G0 approval request `935d6eed-4690-46f6-867f-8085ea38a11d` and the current `governance/GATE_MANIFEST.json`.
- No tests or migrations run. `git diff --check` is to be performed before commit.
- G0 remains PASSED; G1–G8 remain NOT_PASSED; formal S13 remains NOT APPROVED; production authorization remains NONE.
- Exact-range PM review is required before push.
