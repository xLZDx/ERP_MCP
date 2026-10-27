# S13 dispatch receipt writer candidate

## Change

Added source-only `change_ledger.record_dispatch_receipt_v1` in migration 027 and an explicit
`SqlChangeLedger` route used only when the candidate schema flag is enabled. The adapter allocates
the receipt UUID before invoking the SQL transaction. The new SQL signature is explicitly
revoked from `PUBLIC` and every named application/private role.

## Why

The legacy receipt entry locks a record before receipt-ID/conflict arbitration and its replay
comparison omits `signer_key_id`. The accepted candidate contract requires ranked scope/global-ID
fences, exact immutable replay identity and no aliasing between two valid scoped key IDs that
share key material.

## Contract and decisions

- Preserve input validation, requester-or-writer authorization, current generation, `APPLYING`
  state, dispatched permit lookup, active receipt-role `ED25519` verification, and equality with
  the verified wire payload digest.
- Take namespace 7 and validate the lifecycle row before namespace-6
  `record-change-id:v1:<uuid>` and `dispatch-receipt-id:v1:<uuid>` locks, then lock the record and
  inspect receipt state.
- Exact replay requires the same dispatch ID, received digest, version, signer key ID and
  signature. Changed identity refuses with `RECEIPT_IDENTITY_CONFLICT` / `P0001` before receipt or
  event DML, and does not disclose the existing receipt ID.
- Preserve `recorded_by` as first-writer provenance. Exact replay returns the stored immutable ID
  without a duplicate event. New inserts use the adapter-preallocated ID and append one event.
- Keep the candidate ungranted and default-off until verifier, permit, record and receipt paths
  plus their legacy ACLs are reviewed and qualified as one graph.

## Verification state

This record documents source edits performed during the current continuation; the rest of the
checkout was already dirty. The targeted source was inspected after the edits. No SQL parse, test,
check, migration, database operation, COM operation, staging, commit or push ran. Effective grants
are `NOT_VERIFIED`; runtime qualification is `NOT_RUN`; the new candidate still needs source
review. This is not a runtime cutover.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Next action

Finish the full receipt/permit/generation-trigger lock graph and read-only source ACL review.
Do not grant the entry or enable its selector before coding and disposable qualification are
complete.
