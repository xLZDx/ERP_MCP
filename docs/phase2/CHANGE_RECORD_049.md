# Change record 049 — assemble the G0 evidence index

## What changed

- Added an exact-head, SHA-256-bound index for G0 scope, architecture, R1-boundary and donor/license evidence.
- Linked the index from the current G0–G8 closure matrix and stated the exact decision requested from the gate reviewer.
- Preserved all gate and production authorization states.

## Why

The G0 matrix identified the evidence index as the remaining local documentation step. The source artifacts and operator decisions exist, but were not assembled into one reviewable exact-head package. The index makes the available evidence, limitations and named OB-15 deployment deferrals explicit.

## Contracts and paths

- `docs/phase2/G0_EVIDENCE_INDEX_2026-10-15.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`
- This record

No executable source, SQL, test, key, manifest gate state, or runtime authorization changed.

## Verification state

- Artifact hashes were computed from the exact source files at HEAD `63c347441d84ad646a43519efa8d21399ac8949c`.
- No tests or migrations run. The document registry generator ran for the new records.
- G0 remains NOT_PASSED pending gate-specific review; production authorization remains NONE.
- Exact-range GPT-PM review is required before push.
