# Change record 064 — map candidate G1 focused test files

## What changed

- Added a source-observed candidate file map to `G1_EVIDENCE_PACKET_PLAN.md`, separating static preflight from PostgreSQL integration, multi-process concurrency, Docker crash/restore, capacity smoke, and mutation evidence.
- Updated the SDLC Verify checkpoint to link this map, distinguish the exact code-review HEAD from the repository documentation baseline, and state that the authorized test-agent review must confirm minimal criterion coverage before any future run.

## Why

G1 had multiple focused test modules, but the evidence packet did not identify them by environment boundary. The map gives the future functional-test reviewer concrete candidates while making clear that filenames/docstrings are not runtime results and that a small capacity smoke test is not production capacity evidence.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_064.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`

## Verification state

- Read test module docstrings only; no test or static preflight was executed.
- No PostgreSQL, Docker, migration, or live identity operation was performed.
- Runtime remains `NOT_RUN`; G1 remains `NOT_PASSED`; production authorization remains `NONE`.
