# Change record 036 — synthetic dispatch coordinator implementation

## What changed

- Added `SyntheticDispatchCoordinator` to sequence receipt requirement, canonical payload verification,
  call registration, one `ReferenceWriter` call, and persistence of its unchanged receipt.
- Added scoped `SqlChangeLedger` port wrappers for the existing `require_dispatch_receipt` and
  `record_dispatch_receipt` SQL functions and registered them in `SPEC` with existing ACL classes.
- Added explicit exceptions for false ledger payload/call gates; neither can proceed to the writer.

## Why

The combined synthetic end-to-end scenario duplicated the safe ledger-to-clone choreography. This
coordinator makes that sequence reusable while keeping authorization and wire-digest validation in
SQL and receipt signature verification in `ReferenceWriter`.

## Contracts and paths

Affected paths: `src/business_ai_gateway/phase2/simulation/synthetic_dispatch.py`,
`src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`, and
`docs/phase2/S14_SYNTHETIC_DISPATCH_ADAPTER_2026-10-15.md`.

It accepts existing IDs but does not mint approval, claims, permits, tickets or signatures. It does
not complete changes or retry. Unknown writer outcomes pass through; receipts are persisted only for
`APPLIED_VERIFIED`. It is synthetic-lane code and does not implement `OneCWritePort`.

## Verification state

No tests or checks were run during coding. Focused tests must be authored and executed by the functional
and E2E reviewer agents after coding is complete. Specialist review, GPT-PM exact-head approval and
push remain pending.
