# Change record 061 — reconcile G1 engineering state and SDLC checkpoint

## What changed

- Changed G1 `engineering_status` from `NOT_STARTED` to `IN_PROGRESS` in `governance/GATE_MANIFEST.json` to reflect the already-authored focused crash/restore scenarios and static review.
- Clarified in the G1 backlog and S14 gate packet that engineering is in progress while the G1 gate remains `NOT_PASSED` and runtime remains `NOT_RUN`.
- Created `docs/sdlc/STATE.md` as required by the explicitly invoked `sdlc-orchestrator` skill. It records the current Verify phase, artifacts, actual agent/review evidence, and the runtime prohibition.

## Why

The gate manifest still said engineering had not started, contradicting committed G1 scenarios and static review. Updating only the engineering activity state avoids implying external evidence, gate acceptance, or production authorization. The SDLC state file did not exist, so the requested workflow had no phase checkpoint.

## Contracts and paths

- `governance/GATE_MANIFEST.json`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/sdlc/STATE.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`

## Verification state

- Reviewed current manifest schema definition and confirmed `IN_PROGRESS` is an allowed engineering status. The manifest validator was not run.
- No tests, checks, builds, migrations, database, PostgreSQL, or Docker operations were run.
- G1 remains `NOT_PASSED`; runtime remains `NOT_RUN`; production authorization remains `NONE`; Release 2 remains `NO-GO`.
