# Change record 038 — distinguish post-write receipt persistence uncertainty

## What changed

- Added `ReceiptPersistenceUnknown` for SQL receipt-persistence exceptions after the clone returned
  `APPLIED_VERIFIED`.
- The exception carries the verified `WriteOutcome`, preserving the clone receipt for reconciliation,
  and uses a fixed public error code.
- Cancellation during the SQL wait is surfaced as `ReceiptPersistenceCancelled`, which remains an
  `asyncio.CancelledError` while carrying the verified outcome.
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
`PYTHONPATH=src python -m unittest tests.phase2.test_synthetic_dispatch -v`: 7/7 passed for the first
typed implementation, including SQL receipt-persistence failure. A subsequent code review found that
the cancellation path suppressed asyncio cancellation. The final adjustment uses
`ReceiptPersistenceCancelled`, which remains an `asyncio.CancelledError` and carries the outcome. The
functional reviewer reran the file after that adjustment: 7/7 passed, including assertions for
cancellation type, stable code, identical verified outcome and one writer call. PostgreSQL E2E was
not rerun because the wrapper sequence did not change. Focused independent re-review and exact-head
GPT-PM review remain pending.
