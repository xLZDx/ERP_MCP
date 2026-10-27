# S13 dispatch payload verification candidate

## Change

Added source-only `change_ledger.verify_dispatch_payload_v1` in migration 027 and the explicit
flag-on adapter route. `SqlChangeLedger.verify_dispatch_payload` now allocates `verification_id`
before invoking the transaction when the private-writer schema flag is enabled. The candidate
signature is revoked from `PUBLIC` and all named application/private roles.

## Why

The legacy verifier takes the record row before arbitrating the globally generated verification
ID. The S13 plan requires that identity to be fixed and prelocked before row work while retaining
the exact lookup-only replay and canonical payload contract.

## Contract and decisions

- Preserve the existing requester-or-writer entitlement, current generation, `CLAIMED`/`APPLYING`
  state, current approval check, JSON object/canonical-byte rules and approved payload digest.
- Take namespace 7 and validate lifecycle before namespace-6 `record-change-id` and
  preallocated `dispatch-verification-id`, then lock and revalidate the record.
- An exact existing non-NULL wire digest is lookup-only and adds no row/event. A different digest
  remains `DIGEST_MISMATCH`. A new row stores exactly the adapter-supplied ID and appends one
  `DISPATCH_PAYLOAD_VERIFIED` event.
- Keep the candidate ungranted and default-off. It is not a migration cutover; legacy ACLs remain.

## Verification state

The source was edited in a previously dirty checkout; prior dirty work is not attributed to this
continuation. The targeted function and adapter route were inspected after the edits. No SQL parse,
test, check, migration, database or COM operation, staging, commit or push ran. Effective grants
are `NOT_VERIFIED`; qualification is `NOT_RUN`; source review of this new delta is pending.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Next action

Complete candidate source and lock/trigger review as part of the full S13 graph, then run the
mapped disposable ID/replay qualification after all sprint coding is complete.
