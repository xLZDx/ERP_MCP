# Change Record 391 - S15 tests for the GPT-PM gate fixes

## Ownership and scope

- Date: 2026-10-28. Tests written and run by the functional-test-reviewer agent; committed by the coordinator. Follows CR-390.
- Changes `tests/phase2/test_s15_reconcile.py`, `test_s15_ab_compare.py`, `test_s15_negative_controls.py`.

## Changes

- Population scope: a marker-index-only reader with an unmarked out-of-band document gives INCONCLUSIVE, never CLEAN; a full-population
  reader gives DIRTY; scope mismatch, empty, non-str and truthy-but-not-True flags are all INCONCLUSIVE.
- Lane independence: identical names, aliases, unknown identities and baseline provenance mismatches are INCONCLUSIVE; MATCH needs two
  distinct identities with matching provenance.
- Stale epoch reported as INCONCLUSIVE `STALE_EPOCH`; CLEAN age measured from before the reads; epoch required on `record`;
  exact canonical control coverage.

## Verification state

- Agent-run, project interpreter: 899 passed over the s15 test files, ruff clean on tests and source; no source bug found; no mutation runs.
- Synthetic fixtures and fakes only; real 1C and S13 ledger NOT_RUN. GPT-PM re-verification of the two MAJOR fixes: NOT_RUN at the time of writing.
