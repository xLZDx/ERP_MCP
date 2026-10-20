# Change record 023 — receipt-marker retry lifecycle

## What changed

Updated the marker carry-forward regression to start APPLYING without an issued dispatch permit, apply the ledger's
expired/unissued-permit recovery transition, and then reclaim at the next generation.

## Why

The independent rerun of the I-file showed that marker registration is only valid in APPLYING, while `release_claim` is
only valid for a CLAIMED/NOT_STARTED token. The correct retry path is `permit_not_issued_internal`, followed by a fresh
claim. This is a test lifecycle correction; migration behavior was not changed.

## Contracts and paths

The scenario now follows the production ledger state transition and asserts that the receipt marker is copied to the
next claim generation by migration 017's trigger.

## Verification state

The preceding run had 1 failed and 3 passed. The corrected `test_change_hardening_i_sql.py` later passed 4/4 independently.
See the final verification summary in `CHANGE_RECORD_018.md`.
