# Change record 028 — S14 synthetic wire-receipt binding

## What changed

- Added migration `db/phase2/018_wire_payload_receipt.sql`. It preserves the approved typed-payload digest and records a separate SHA-256 for canonical JSON bytes before dispatch.
- Changed receipt validation and the APPLIED trigger to compare the clone-signed digest against the immutable per-generation wire digest.
- Kept historical verification rows without byte evidence as `NULL`; they are not backfilled or treated as proof.
- Updated the SQL ledger port docstring, added the S14 design record, and recorded implementation state and acceptance limits in the simulation plan and operator backlog.

## Why

The S13 combined synthetic scenario disclosed that the clone signed SHA-256 of received wire bytes while the ledger compared
that value with migration 009's typed-payload digest. The earlier scenario created a second ledger-form receipt to bridge
the difference. S14 now has a fail-closed prototype design that verifies canonical payload text, hashes the exact bytes
the simulated clone receives, and accepts only the clone's receipt over that hash.

## Contracts and paths

The authorization digest remains unchanged. Migration 018 extends the immutable
`change_ledger.change_dispatch_verifications` record with `wire_payload_sha256`, requires it for a current-generation
dispatch, and validates receipt and APPLIED state against it. Non-canonical JSON is refused. NULL POST/UNPOST payloads
use the exact `{}` representation. Prior rows have unknown byte provenance and remain NULL. Receipt requirement remains
opt-in as the separately recorded R-01 limitation.

Affected paths: `db/phase2/018_wire_payload_receipt.sql`,
`src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`,
`docs/phase2/S14_WIRE_RECEIPT_DESIGN_2026-10-15.md`,
`docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`, and
`docs/phase2/OPERATOR_BACKLOG.md`.

## Verification state

Implementation is **NOT_RUN / UNVERIFIED** at this record. Migration 018 has not been applied. Focused tests, database
review, E2E review and exact-range GPT-PM review have not yet run. No real 1C, staging, production, or release gate was
touched. The design and implementation apply only to the non-gating synthetic lane.
