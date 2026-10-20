# Change record 133 — harden S13 preflight against hostile provider subclasses

## Goal and scope

Close the remaining malformed-provider MINORs from the CR132 targeted code/security/reliability review. The lifecycle preflight must return stable fail-closed diagnostics even if an adapter returns subclasses that override ordinary mapping or record field behavior. This is local preparatory work only; no formal S13 or release gate changes.

## Changes

- Require the ledger verification response to be an exact built-in `dict` before invoking `.get()`. Malformed mappings now produce `NOT_READY/CHAIN_INVALID` rather than escaping the structured path.
- Require the latest checkpoint value to be an exact `CheckpointRecord`; subclasses with overridden attribute behavior produce `NOT_READY/CHECKPOINT_INVALID` without field access.
- Clarify in the coordinator contract that `asyncio.wait_for` provides cooperative cancellation, not a hard wall-clock bound when an adapter suppresses cancellation. Any future startup-liveness SLA requires transport-level deadlines in the production adapters.
- Added functional and local module-boundary E2E coverage for hostile mapping and checkpoint subclasses.

## Affected paths and contracts

- `src/business_ai_gateway/phase2/change_ledger/lifecycle.py`
- `tests/phase2/test_s13_lifecycle_preflight.py`
- `tests/phase2/test_s13_lifecycle_preflight_e2e.py`
- `governance/DOCUMENT_REGISTRY.md` (regenerated after CR132)
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/sdlc/STATE.md`

## Verification evidence

- Functional-test-reviewer ran `& .\.venv\Scripts\python.exe tests/phase2/test_s13_lifecycle_preflight.py`: **PASS, 13 tests**, Python 3.14.3. Tested Git blobs: lifecycle `cf9b88e127e1dba994af149abfb4572dc26be3eb`; functional file `93d953de9b28cfd6c164dbf35899072b18723253`.
- E2E-runner ran `$env:PYTHONPATH='src'; & .\.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s13_lifecycle_preflight_e2e.py`: **PASS, 9 tests in 0.61s**, Python 3.14.3. SHA-256: lifecycle `F8B8EC95222E391A5D381C9467D3DA0C9E86437DC15BD44FF3528528C5199A30`; E2E file `FFFF222FA60B3FCCC1995F8F1A61DEA8731E0867058AAF6762EE26794F657EB2`.
- These are local module-boundary scenarios with doubles and in-memory state, not PostgreSQL, external-provider, cross-process, or 1C evidence.
- CR132 targeted code, reliability, and security reviews found no BLOCKER/MAJOR; they identified the malformed subclass edge cases fixed here and the cooperative-timeout limitation documented above. Re-review of exact CR133 is pending.
- The registry generator ran after CR132: `node scripts/build_document_registry.mjs`, exit 0; it scanned four refs and wrote 199 tracked paths and zero local-only paths. No shared/production database, migration activation, push, deployment, or manifest change occurred.

## Ownership and remaining acceptance

- The operator remains accountable for delegated project closure; GPT/Codex executes local engineering.
- `functional-test-reviewer` owns and executed the functional scenarios; `e2e-runner` owns and executed the local module-boundary E2E scenarios.
- Exact-head targeted re-review by code/reliability/security roles and a fresh GPT review remain required before push.
- S13 formal entry remains `NOT_STARTED/NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; Release 2 remains `NO-GO`; production authorization remains `NONE`. Full S13 still needs shared mutation/physical-dispatch fencing, S12 suffix inspection, bounded fenced recovery-to-READY, real service composition, and qualified provider/signer anti-rollback and custody evidence. Cooperative cancellation in this generic preflight is not proof of production startup liveness.
