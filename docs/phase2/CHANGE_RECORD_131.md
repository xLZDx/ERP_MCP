# Change record 131 — S13 checkpoint preflight

## Goal and scope

Add the provider-neutral, read-only S13 preflight allowed by the local engineering decision: discover the latest checkpoint for an exact scope, validate its signed content after ledger-chain verification, and expose a structured result without enabling effectful admission. This is preparatory code only. It must not claim S13 readiness or invoke migration 022's permanent `RECOVERING` transition.

## Changes

- Extended `CheckpointSink` with `latest(scope)`. Its contract requires an implementation to provide the authenticated anti-rollback latest record for that exact scope; a valid signature alone does not prove that a record is latest.
- Implemented deterministic highest-sequence lookup in `InMemoryCheckpointSink` for the exact tenant/company pair. This implementation remains TEST ONLY and is not qualified as durable or anti-rollback storage.
- Added `LifecycleCoordinator.preflight()` and typed result/reason enums. The preflight checks the ledger chain first, then reads and validates the checkpoint scope, shape, and signature. Provider and verifier exceptions map to fixed fail-closed reason codes; their error text is not returned.
- The preflight always returns `NOT_READY`. The source tree still lacks a shared cross-process fence covering every mutation and dispatch path, read-only S12 suffix inspection, bounded fenced recovery, and a reviewed durable `READY` transition. The preflight is not wired to a service lifecycle or `DispatchGate`.
- Corrected the CR130 registry-generator note and S14's stale statement that no S13 functional/E2E evidence existed.

## Affected contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/checkpoint.py`
- `src/business_ai_gateway/phase2/change_ledger/lifecycle.py`
- `docs/phase2/S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/phase2/CHANGE_RECORD_130.md`
- `docs/sdlc/STATE.md`
- `governance/DOCUMENT_REGISTRY.md` (regenerated)

## Verification state and limitations

- Source files were tested from the uncommitted worktree based on HEAD `b9c098cca33cad14b76564f2f230921eacf7fa37`. Current SHA-256: `checkpoint.py` `AF456ED6A69A2937F3AC68B6329C9FCD2FFF7EB7795FA03FE94C472CE95DD71C`; `lifecycle.py` `A7C867807BF8E3CA495C70F629B9AA2D6A68E326B601C94E2ABED6BEFE8109E1`.
- `functional-test-reviewer` ran `& .\.venv\Scripts\python.exe tests/phase2/test_s13_lifecycle_preflight.py`: **PASS, 7 tests** on Python 3.14.3. The scenarios cover exact-scope latest ordering, invalid/raising chain and malformed count short-circuit, provider failure/missing checkpoint, wrong scope, invalid signature/verifier error, and valid preflight remaining NOT_READY. Test Git blob: `ed430fb659fc69a97ad5cdab2b73aed20372bcfd`; raw SHA-256: `91EA3DE9F389D51EA8B21DF5C30237AB466BED525BD557D2ED9AF624AC219FBD`.
- `e2e-runner` ran `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s13_lifecycle_preflight_e2e.py`: **PASS, 5 tests in 0.41s** on Python 3.14.3. This is local in-process module-boundary E2E using an in-memory sink and test doubles; it verifies expected stops and zero checkpoint write/read-back calls. Raw SHA-256: `5575515408F59EFCCF6937D36E093419700F6E6F9A66756C9F818CC52FFDC21B`.
- These scenarios do not prove PostgreSQL behavior, external provider anti-rollback, shared cross-process fencing, S12 suffix classification, physical dispatch admission, or 1C behavior. The prior migration-022 PostgreSQL functional PASS and E2E PASS 2/2 remain exactly as recorded in CR130 and do not test this source implementation.
- No shared or production database was used; migration 022 remains local-only and unapplied to any shared/live database. Specialist review and exact-head GPT approval for CR131 remain pending.
- Documentation registry generation: `node scripts/build_document_registry.mjs` exited 0 and wrote `governance/DOCUMENT_REGISTRY.md` with 197 tracked paths and one local-only path (`docs/phase2/CHANGE_RECORD_131.md`) across the four scanned refs. That local-only listing is expected until this record is committed.

## Ownership and next actions

- Task accountability: the operator delegated local project closure; GPT/Codex executes within the approved prototype scope.
- Test authorship/execution: `functional-test-reviewer` and `e2e-runner` after source coding is complete.
- Specialist review after those results: database, reliability, security, and code reviewers for the affected boundary.
- Next S13 acceptance work: implement and independently review a complete shared fence, read-only checkpoint-ancestor/S12-suffix inspection, bounded recovery and durable readiness transition; integrate at a real service admission boundary only after that boundary exists. Obtain provider anti-rollback and signer/custody evidence separately. Keep formal S13 `NOT_STARTED` / `NOT_APPROVED`, G1–G8 `NOT_PASSED`, Release 2 `NO-GO`, and production authorization `NONE`.
