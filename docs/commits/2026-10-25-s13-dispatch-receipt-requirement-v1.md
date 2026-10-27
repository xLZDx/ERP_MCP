# S13 dispatch receipt requirement candidate

## Change

Added `change_ledger.require_dispatch_receipt_v1` to the source-only additive migration 027 and
an explicit `SqlChangeLedger` flag-on route. The default route remains the legacy function; an
enabled candidate schema resolves the v1 function directly and has no fallback. The new function
is explicitly revoked from `PUBLIC` and every named application/private role.

## Why

The S12 receipt requirement is a writer over the record parent and the
`dispatch_receipt_requirements(change_id,generation)` key. It also races claim-generation carry
behavior and receipt-related writers. The candidate makes this entry join the proposed S13 scope
and global-ID fence contract while preserving the existing first-writer attribution semantics.

## Contract and decisions

- Preserve `assert_scope`, requester-or-writer entitlement, non-NULL identity/generation checks,
  current claim-generation equality, and the `APPLYING` / not-`DISPATCHED` state requirement.
- Take namespace 7, then lock and validate the lifecycle row, then take the namespace-6
  `record-change-id:v1:<uuid>` lock before locking the record and mutating its FK child.
- Preserve `INSERT ... ON CONFLICT(change_id,generation) DO NOTHING`: the first authorized caller
  remains the stored `required_by`; an exact state replay creates no event or replacement row.
- Keep the candidate ungranted and the adapter selector default-off until claim-generation,
  receipt, lifecycle and legacy-grant paths are reviewed and qualified together.

## Verification state

This record documents a source change in the existing dirty checkout; it does not assert that the
current session authored prior dirty content. The targeted adapter and SQL source were inspected
after this edit. No SQL parse, test, check, migration, database operation, COM operation, staging,
commit or push ran. Effective database privileges are `NOT_VERIFIED`; runtime qualification is
`NOT_RUN`; review of this new delta remains pending. The candidate is not a runtime cutover.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Next action

Complete source lock/trigger and effective ACL review for this path as part of the whole S13
candidate set. Do not grant the routine or enable the adapter selector before all conflicting
paths and disposable qualification pass.
