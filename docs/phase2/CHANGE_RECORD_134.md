# Change record 134 — validate checkpoint scope field types

## Goal and scope

Close the remaining CR133 reliability MINOR where an exact `CheckpointRecord` could contain malformed non-string scope fields with custom comparison/truth behavior. Such a value must become a structured `CHECKPOINT_INVALID` result rather than escaping from preflight. This is local diagnostic hardening only.

## Changes

- Require tenant and company scope fields on both the request and checkpoint record to be exact strings before comparing them.
- Keep scope-field access and equality evaluation inside the guarded block; malformed values return `NOT_READY/CHECKPOINT_INVALID`.
- Add focused functional and local module-boundary E2E cases using malformed exact `CheckpointRecord` instances.
- Regenerated the document registry after CR133; registry generation found 200 tracked paths and zero local-only paths.

## Affected paths and contracts

- `src/business_ai_gateway/phase2/change_ledger/lifecycle.py`
- `tests/phase2/test_s13_lifecycle_preflight.py`
- `tests/phase2/test_s13_lifecycle_preflight_e2e.py`
- `governance/DOCUMENT_REGISTRY.md`

## Verification evidence

- Functional-test-reviewer ran `& .\.venv\Scripts\python.exe tests/phase2/test_s13_lifecycle_preflight.py`: **PASS, 14 tests**, Python 3.14.3. Tested Git blobs: lifecycle `c4fa485d257b5042bdea3b11f1578b9c2c027e14`; functional file `21c7b0cb20272f7b7f97910a2eea46d8c64d84ee`.
- E2E-runner ran `$env:PYTHONPATH='src'; & .\.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s13_lifecycle_preflight_e2e.py`: **PASS, 10 tests in 0.52s**, Python 3.14.3. SHA-256: lifecycle `48CCBEBE6C9C743BC718B3AEE7291AB279CFBACD0F306A35AEA72E6ED3261F28`; E2E file `B216E6701093FC4A1E2B214B364C4071C18C087FAFAB4A1A9174A522A73BA9AC`.
- Evidence is local module-boundary only, using doubles and in-memory checkpoint storage; it does not prove PostgreSQL, external-provider, cross-process, or 1C behavior.
- CR133 exact-head code/security reviews found no B/M and confirmed prior subclass findings were fixed. Reliability review found only this malformed exact-record scope MINOR, fixed by CR134. Exact CR134 re-review and GPT review remain pending.
- No production/shared database or migration activation occurred. No push/deployment/manifest change occurred.

## Ownership and remaining acceptance

- The operator remains accountable for delegated project closure; GPT/Codex executes local engineering.
- `functional-test-reviewer` owns/executed functional scenarios; `e2e-runner` owns/executed local module-boundary E2E scenarios.
- Exact-head targeted code/reliability/security re-review and fresh GPT approval remain required before push.
- Formal S13 remains `NOT_STARTED/NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; Release 2 remains `NO-GO`; production authorization remains `NONE`. Full S13 needs shared mutation/physical-dispatch fencing, S12 suffix inspection, bounded fenced recovery-to-READY, service integration, and qualified provider/signer anti-rollback/custody evidence. The cooperative cancellation timeout remains unsuitable as a strict production startup-liveness guarantee without transport deadlines.
