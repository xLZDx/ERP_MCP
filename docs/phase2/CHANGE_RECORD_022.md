# Change record 022 — migration 017 regression setup

## What changed

Adjusted the focused migration 017 tests to install the receipt marker on a CLAIMED, not APPLYING, generation before
releasing and reclaiming it. Corrected the cross-role key test to first register a key under a normal role and then assert
that registering the same key as `receipt_role` fails.

## Why

The independent run of the new migration 017 test file had two failures and two passes. One setup attempted claim release
after entering APPLYING; the other asserted rejection on the initial single-role key registration instead of on the
cross-role reuse.

## Contracts and paths

The test now follows the existing claim lifecycle and checks the intended receipt-key uniqueness boundary without
weakening migration behavior.

## Verification state

The initial failing run is recorded as 2 failed, 2 passed on commit 60a5b7e. The corrected file passed 4/4 independently
after change 023. See the final verification summary in `CHANGE_RECORD_018.md`.
