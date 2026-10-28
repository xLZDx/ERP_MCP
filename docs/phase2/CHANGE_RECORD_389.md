# Change Record 389 - S15 tests adapted and extended after the review fixes

## Ownership and scope

- Date: 2026-10-28. Tests written and run by the functional-test-reviewer agent; committed by the coordinator. Follows CR-388.
- Changes `tests/phase2/test_s15_*.py`, `tests/phase2/_s15_fixtures.py` and one line of `src/erp_mcp_s15/verifier.py`.

## Changes

- Old tests that pinned the previous behaviour were adapted without weakening; new tests cover every behaviour changed in CR-388
  (stale report after restore, gate expiry, strict writer flag, unknown/PENDING/duplicate ledger statuses, found-by-marker, lookup cap,
  READ_ERROR isolation, strict own-date, typing_checked, item validation, required control coverage).
- The vacuous baseline test (two fresh objects compared) was replaced by tests that can fail.
- Source fix found by the tests: a TYPING_DIVERGENCE result reported typing_checked=True; it now reports False.

## Verification state

- Agent-run, project interpreter: 713 passed over the six s15 test files (42 failed before adaptation, as expected); ruff clean.
  Reconcile file re-run three more times for thread-test stability. No mutation runs.
- Known minor, not changed: when a run's CLEAN report is discarded by the epoch check, the runner status accessor still shows it as the last
  report; the gate itself stays blocked. Control coverage is judged by control-id prefix.
- Synthetic fixtures and fakes only; real 1C, S13 ledger and deferred scenarios NOT_RUN. Re-review of the fixes and GPT-PM review: NOT_RUN.
