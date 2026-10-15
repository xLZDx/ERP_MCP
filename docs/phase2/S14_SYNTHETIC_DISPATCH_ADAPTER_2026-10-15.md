# S14 synthetic dispatch adapter

Date: 2026-10-15. Status: implementation contract for the NON-GATING synthetic lane.

## Goal

Give the existing SQL receipt scenario a reusable coordinator that makes its dispatch order explicit:
require a clone receipt, verify canonical payload text against the ledger approval, record the dispatch
call, send the exact encoded bytes through `ReferenceWriter`, and persist only the clone-produced
receipt. The coordinator is a synthetic test-lane adapter, not an implementation of `OneCWritePort`.

## Contract

- Inputs are already-issued `change_id`, `generation`, and `call_id`, plus operation, typed payload,
  target, and expected version. These identifiers carry no authorization meaning by themselves.
- The ledger remains the authority for approval/digest verification and dispatch state. The adapter
  does not issue approvals, claims, permits, tickets, or signatures.
- Before the writer call, the adapter requires receipt recording for this generation, asks the ledger
  to verify the canonical payload representation, and records the supplied call ID. Any ledger
  refusal prevents the write.
- The adapter derives the exact bytes with the existing `encode_payload`, sends those bytes and their
  SHA-256 through `ReferenceWriter`, and records the returned clone receipt only for
  `APPLIED_VERIFIED`. It never fabricates or replaces a receipt.
- Timeout, crash, tamper, invalid receipt, and refusal outcomes are returned as non-success unchanged;
  there is no automatic retry or completion transition. Recovery and completion stay with their
  existing ledger workflows.
- The adapter only accepts a ledger interface that exposes the scoped SQL functions. No real 1C,
  network transport, `OneCWritePort`, production credential, or release-gate evidence is added.

## Implementation state

Implemented in `synthetic_dispatch.py` with scoped `SqlChangeLedger` wrappers for the existing
receipt functions. The functional contract tests pass 5/5; the PostgreSQL 16 synthetic E2E file passes
18/18, including wrapper-driven success and unknown-crash outcomes. Independent specialist review
and exact-head GPT-PM review remain pending.

## Acceptance

1. The new coordinator calls the ledger gates in order and does not call the writer after any gate
   refuses.
2. The bytes sent equal the existing canonical serializer output; the ledger gets matching canonical
   text and the writer receives its SHA-256.
3. The exact clone-produced receipt is passed to the ledger after verified success; every other writer
   outcome remains non-success and does not create a receipt or trigger a retry.
4. `SqlChangeLedger` exposes scoped wrappers for the receipt requirement and receipt recording SQL
   functions without changing their SQL contracts or caller classes.
5. Functional and end-to-end reviewers add focused tests after all code is complete. **PASS** —
   `test_synthetic_dispatch.py` 5/5 and `test_simulation_e2e_sql.py` 18/18 on disposable PostgreSQL
   16; specialist review and exact-head GPT-PM review are still pending.

## Limits

This contract does not close R-01 or establish real call ownership, checkpoint durability, unknown-call
resolution, real 1C behavior, identity/key custody, G0-G8, formal S13 entry, staging, production, or
Release 2. Receipt enforcement remains opt-in outside scenarios that explicitly request it.
