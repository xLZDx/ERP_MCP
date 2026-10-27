# S13 lifecycle-trigger cutover reconciliation

## Change

Reconciled the S13 lifecycle cutover design across the source-final inventory, implementation
design and disposable qualification prerequisites. The cutover now consistently keeps the current
row-locking guards during additive qualification, then drops
`events_lifecycle_fence_guard` and `dispatch_permit_lifecycle_guard` only after all runtime
mutators use versioned entries and legacy mutation/direct-table rights are denied. Versioned
entries own early lifecycle/epoch validation and permit-epoch stamping; the triggers are not
retained as non-locking assertions.

The source inventory and qualification also now define the compatibility boundary for
`lifecycle_writer_epoch`: retain its legacy writer grant only while old callers remain during the
additive phase; at coordinated cutover revoke EXECUTE from `writer_role` and every other effective
runtime principal. The candidate must show no versioned entry/helper call to the point-in-time
reader and must measure inherited/effective privileges. Repository search found only the generic
adapter wrapper and historical migration tests, with no private-writer/COM caller.

## Why

A full S13 map review found contradictory acceptance wording: one paragraph dropped the lifecycle
triggers while another required them to remain as assertions. It also identified that the
writer-granted `lifecycle_writer_epoch` takes a lifecycle-row `FOR SHARE` lock and must be
explicitly classified rather than left as an unqualified runtime preflight.

## Affected contracts and paths

- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`: lifecycle trigger
  correction, granted lifecycle API classification, and trigger cutover acceptance.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`: additive/cutover ordering
  and legacy-reader ACL transition.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: installed trigger,
  entry call-graph and effective ACL evidence required after code completion.
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`: existing generic wrapper remains
  legacy compatibility surface; no change was made to it in this record.

## Decisions and verification state

This is a source/design correction only. The reviewer confirmed that the drop-after-route/ACL
sequence is coherent with migrations 022/024 but left the complete FK-SCC/trigger/unique-conflict
graph open. Repository search is static; it does not establish installed privileges or role
membership. No tests, checks, SQL, migration, database write, COM call, service restart, staging,
commit or push ran. Candidate migration changes remain blocked on full-map closure and review;
disposable qualification remains `NOT_RUN` / `NOT_VERIFIED`.
