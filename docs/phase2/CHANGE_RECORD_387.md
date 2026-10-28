# Change Record 387 - S15 functional tests

## Ownership and scope

- Date: 2026-10-28. Tests written and run by the functional-test-reviewer agent; committed by the coordinator.
- Adds `tests/phase2/test_s15_{oracle,verifier,negative_controls,ab_compare,reconcile,import_graph}.py` and `tests/phase2/_s15_fixtures.py`
  for the code of CR-386.

## Verification state

- Agent-run with the project interpreter: 322 passed, 0 failed, 0 skipped over the six test files; ruff clean on the tests; source and tests ASCII.
  No mutation runs. Source was not changed; no defect was found by the tests.
- Synthetic fixtures and fakes only. NOT_RUN: real 1C, S13 ledger, test-lane MCP, E2, E10, E26, E37, E1 post step, real-1C movement read,
  persisted reconciliation state (not implemented), E25 'repeat of E3' line (needs the real ledger).
- Two negative-control tests call private helpers to prove each control is red for its intended reason; a rename needs a test update.
- Specialist reviews and GPT-PM review: NOT_RUN.
