# Change record 039 — exercise cancellation during receipt persistence

## What changed

- Replaced the cancellation injection case with an event-gated ledger fake that suspends during
  `record_dispatch_receipt`.
- The test calls `task.cancel()` while the coordinator awaits SQL and asserts the task remains
  cancelled, raises `ReceiptPersistenceCancelled`, retains the verified outcome/receipt, and makes
  exactly one writer call.
- Recorded the latest focused regression, E2E rerun and review status.

## Why

Python review identified that injecting a `CancelledError` directly into the fake did not prove actual
async task-cancellation lifecycle behavior. This case exercises cancellation while an await is
suspended and verifies both cancellation semantics and reconciliation data.

## Contracts and paths

Affected paths: `tests/phase2/test_synthetic_dispatch.py`, `docs/phase2/CHANGE_RECORD_038.md`,
`docs/phase2/S14_SYNTHETIC_DISPATCH_ADAPTER_2026-10-15.md`,
`docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`, `docs/phase2/OPERATOR_BACKLOG.md`, and
`core/DECISION_LOG.md`.

No production or 1C behavior is asserted. Existing gate statuses remain unchanged.

## Verification state

- Functional reviewer: `PYTHONPATH=src python -m unittest tests.phase2.test_synthetic_dispatch -v` —
  7/7 passed.
- E2E runner at source HEAD `d659788de46e7037db1b83afa6ef2333c534b92d`: focused
  `test_simulation_e2e_sql.py` — 18/18 passed in 94.05s on disposable PostgreSQL 16.
- Python re-review confirmed the cancellation-lifecycle test closes the previous MINOR gap; no
  BLOCKER/MAJOR remained. Exact-head GPT-PM review and push are pending.
