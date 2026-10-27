# Change Record 254 — Align T16 hold-list validation

Date: 2026-10-25  
Status: source-only; qualification not run.

## Why

The T16 recovery coordinator accepted an empty `checkpoint_hold_ids` list if the checkpoint
response also reported only the call-owned hold. The two existing upstream contracts reject an
empty ANCHOR_GAP hold list: `CheckpointCoordinator.checkpoint_operator_resolution` in
`src/business_ai_gateway/phase2/change_ledger/checkpoint.py` requires a non-empty list before
checkpoint signing/release, and `SqlChangeLedger.operator_resolve_s13` in
`src/business_ai_gateway/phase2/change_ledger/sql_ledger.py` rejects an empty list returned from
the S13 transition. T16 must preserve that same fail-closed contract before it can accept the
checkpoint result and terminalize the private-writer call.

## Change

- `src/erp_mcp_private_writer/t16_recovery.py` now rejects an empty `checkpoint_hold_ids` list
  during the typed resolution-response validation, before comparing released hold IDs or calling
  `record_recovered_terminal`.
- The check follows the exact-list type guard, so malformed non-list values still fail through the
  existing sanitized `T16_CHECKPOINT_RESULT_INVALID` path.

## Evidence and verification

- Manual source comparison: `checkpoint.py` requires `type(hold_ids_raw) is list or not hold_ids_raw`
  to be false; `sql_ledger.py` applies the same non-empty-list contract to
  `checkpoint_hold_ids`.
- Current `t16_recovery.py` SHA-256: `48AC6F637266DF17A6F035C566B0F9043F5E3B588BA78E235F8FCFB18531928F`.
- Tests/checks, SQL parsing, migration, database operation, COM operation, staging, commit, and push:
  `NOT_RUN`.

## Acceptance follow-up

After coding closes, functional/E2E qualification must include empty, missing, malformed, duplicate,
and valid non-empty hold-list responses, with proof that invalid results do not call
`record_recovered_terminal`. The Python specialist review remains pending.
