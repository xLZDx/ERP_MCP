# Change record 132 — bounded S13 checkpoint preflight dependencies

## Goal and scope

Address review findings against CR131's diagnostic lifecycle preflight. Provider waits must be bounded and returned as stable fail-closed outcomes; malformed checkpoint provider values must not escape as untyped exceptions. This remains preparatory local engineering and does not pass formal S13 or any release gate.

## Changes

- Added a finite, positive per-dependency timeout to `LifecycleCoordinator`, defaulting to five seconds. It bounds the ledger chain verification and checkpoint `latest()` awaits independently.
- A ledger timeout maps to `NOT_READY/CHAIN_UNAVAILABLE`; a checkpoint timeout maps to `NOT_READY/CHECKPOINT_UNAVAILABLE`. Normal task cancellation still propagates.
- Reject malformed checkpoint result objects and Boolean sequence values as `CHECKPOINT_INVALID`.
- Added functional and local module-boundary E2E scenarios for malformed records and both timeout paths, including no checkpoint read after chain timeout and timeout parameter validation.

## Affected paths and contracts

- `src/business_ai_gateway/phase2/change_ledger/lifecycle.py`
- `tests/phase2/test_s13_lifecycle_preflight.py`
- `tests/phase2/test_s13_lifecycle_preflight_e2e.py`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/sdlc/STATE.md`

## Verification evidence

- Functional-test-reviewer ran `& .\.venv\Scripts\python.exe tests/phase2/test_s13_lifecycle_preflight.py`: **PASS, 11 tests**, Python 3.14.3. Tested Git blobs: lifecycle `25d23ac521f21c4c79c371ca0dfe648e6da3cbe6`; functional file `ce0be28ff94da9d8d05a0b1165ef13f10003d11c`.
- E2E-runner ran `$env:PYTHONPATH='src'; & .\.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s13_lifecycle_preflight_e2e.py`: **PASS, 7 tests in 1.18s**, Python 3.14.3. Tested source SHA-256 `4A1FCE2DF0354C9B895572C2AB2D1CED90B6FB0159DBD3532D23F30C9A0FACF2`; E2E file SHA-256 `088392D5106BE6A7706E274CA82965C244B7DF9AFF9D39E6BA22022AB0B41005`.
- E2E evidence is local module-boundary coverage using asynchronous port doubles and in-memory checkpoint storage; it does not prove PostgreSQL, external checkpoint provider, cross-process, or 1C behavior.
- Code, security, and reliability targeted re-reviews and exact-head GPT review are pending. The preceding 63890d2 reliability review's two MAJOR findings are addressed in source; no re-review claim is made here.
- No shared or production database was used, and migration 022 remains unapplied outside the local disposable-test evidence recorded in CR130. No push, deployment, or manifest gate update was performed.

## Ownership and remaining acceptance

- The operator remains accountable for delegated project closure; GPT/Codex executes the local engineering scope.
- `functional-test-reviewer` owns functional scenarios and `e2e-runner` owns module-boundary E2E scenarios. They executed the commands above.
- Relevant specialist roles: code, reliability, and security review; database review has already found no database-specific finding for CR131, and CR132 changes no SQL or schema.
- Keep formal S13 `NOT_STARTED/NOT_APPROVED`, G1–G8 `NOT_PASSED`, Release 2 `NO-GO`, and production authorization `NONE`. Full S13 acceptance still requires shared mutation/physical-dispatch fencing, S12 suffix inspection, bounded recovery-to-READY, service integration, and qualified provider/signer anti-rollback and custody evidence.
