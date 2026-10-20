# Change record 021 — repair scenario target fixture

## What changed

Updated the failed-POST repair SQL scenario to use the registered `base-1` target fixture.

## Why

The independent rerun after change 020 passed 13 of 14 E2E scenarios. The remaining repair scenario was rejected at
proposal because its synthetic base fingerprint was not present in the ledger target registry.

## Contracts and paths

This corrects test data setup only. It does not relax target registration or effect authorization.

## Verification state

The failing run is recorded as 13 passed, 1 failed on commit 8115d62. The corrected `test_simulation_e2e_sql.py` later
passed 14/14 independently. See the final verification summary in `CHANGE_RECORD_018.md`.
