# Change record 038 — distinguish post-write receipt persistence uncertainty

## What changed

- Added `ReceiptPersistenceUnknown` for SQL receipt-persistence exceptions after the clone returned
  `APPLIED_VERIFIED`.
- The exception carries the verified `WriteOutcome`, preserving the clone receipt for reconciliation,
  and uses a fixed public error code.
- Cancellation during the SQL wait is wrapped in the same exception with `interrupted = true`, so the
  verified clone outcome is not discarded at that boundary.
- Clarified that this result must never cause an automatic retry because SQL may have committed before
  its response was lost.

## Why

Python review found that a generic SQL exception after a successful clone write could be mistaken by
the caller as a failure before the write, inviting a duplicate attempt. The coordinator now separates
pre-write ledger failures from post-write receipt persistence uncertainty.

## Contracts and paths

Affected paths: `src/business_ai_gateway/phase2/simulation/synthetic_dispatch.py`,
`docs/phase2/S14_SYNTHETIC_DISPATCH_ADAPTER_2026-10-15.md`,
`docs/phase2/CHANGE_RECORD_036.md`, and `core/DECISION_LOG.md`.

The clone result remains `APPLIED_VERIFIED`; the exception communicates that SQL receipt state is
uncertain. It does not retry, complete, or resolve the transaction. A caller must query/reconcile
the ledger state before any further action.

## Verification state

The pre-fix focused functional (5/5) and PostgreSQL 16 E2E (18/18) evidence is recorded in
`CHANGE_RECORD_037.md`. After the fix, the functional reviewer ran
`PYTHONPATH=src python -m unittest tests.phase2.test_synthetic_dispatch -v`: 7/7 passed, including
SQL receipt-persistence failure and cancellation preservation. The PostgreSQL 16 E2E file was not
rerun because its coverage did not change; focused Python/code re-review and exact-head GPT-PM review
remain pending.
