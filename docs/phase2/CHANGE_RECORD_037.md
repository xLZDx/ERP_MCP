# Change record 037 — S14-R03 focused tests and evidence

## What changed

- Added functional tests for the synthetic coordinator's ordering, fail-closed gates, exact bytes,
  receipt forwarding, and no-retry unknown outcomes.
- Added PostgreSQL end-to-end scenarios using `SyntheticDispatchCoordinator` and `SqlChangeLedger`.
- Updated the S14 plan, adapter contract, backlog and decision log with exact test evidence and limits.
- Refreshed the generated document registry.

## Why

The implementation needs evidence at both its local coordinator boundary and its real SQL/clone
integration boundary. The tests ensure that only verified clone receipts reach SQL and that ambiguous
write outcomes remain unresolved without a retry or completion.

## Contracts and paths

Affected paths: `tests/phase2/test_synthetic_dispatch.py`,
`tests/phase2/test_simulation_e2e_sql.py`, `docs/phase2/S14_SYNTHETIC_DISPATCH_ADAPTER_2026-10-15.md`,
`docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`, `docs/phase2/OPERATOR_BACKLOG.md`,
`core/DECISION_LOG.md`, and `governance/DOCUMENT_REGISTRY.md`.

The E2E test DB was disposable PostgreSQL 16; it is not release evidence. It confirmed the clone's
actual receipt key, byte digest and version are recorded before APPLIED. Crash-before/after-write
cases remained APPLYING with no receipt and exactly one clone attempt. The test-owned disposable
container remains running because its cleanup command was rejected before execution; no existing
container was touched.

## Verification state

- Functional reviewer: `PYTHONPATH=src python -m unittest tests.phase2.test_synthetic_dispatch -v` —
  5/5 passed.
- E2E runner: `python -m pytest tests/phase2/test_simulation_e2e_sql.py -q` on disposable PostgreSQL
  16 — 18/18 passed in 109.77s. The agent's actual invocation used the dedicated temporary venv.
- Initial E2E run: 17 passed, 1 failed due to missing test registration of the clone's actual key ID;
  only the fixture was corrected and the focused file was rerun successfully.
- Specialist review, exact-head GPT-PM review, push: pending.
- No prohibited broad checks were run.
