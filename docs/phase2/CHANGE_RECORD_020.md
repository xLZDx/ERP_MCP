# Change record 020 — end-to-end scenario corrections

## What changed

Corrected three test-harness issues in the synthetic SQL end-to-end scenarios: forward claim options through the shared
success helper, use a registered base fingerprint for anchor-gap setup, and resume kill-switch recovery through a fresh
permit after STOP_EFFECTS cancels the prior one.

## Why

The first independent run of `test_simulation_e2e_sql.py` produced 11 passes and 3 failures in these scenario paths.
Each failure was a test setup or lifecycle expectation; no migration 017 failure was observed.

## Contracts and paths

The corrections preserve the ledger's target registry and kill-switch fencing contracts. A canceled dispatch permit is
not reused after the switch returns to OFF.

## Verification state

After this and the subsequent registered-base correction in change 021, the independent `test_simulation_e2e_sql.py`
run passed 14/14 on commit 60a5b7e. Earlier failures remain recorded in the log for traceability and are superseded by
the later green run.
