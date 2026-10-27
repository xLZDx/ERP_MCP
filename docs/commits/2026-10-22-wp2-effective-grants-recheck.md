# Change record: record effective PostgreSQL grants and correct the WP0 claim

Date: 2026-10-22  
Scope: one read-only effective-grants recheck on the disposable PostgreSQL endpoint and a durable evidence addendum.

## What changed

- Added `docs/phase2/artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-22.md` with point-in-time role attributes, table and function privileges, query scope, evidence limits, and next actions.
- Corrected the WP0 working draft's all-seven routine claim and CT14 feasibility-spike path. It now distinguishes the 15-base-table RLS scan from the 17-relation grant query.
- Recorded that five of seven inspected `bag` routines have effective `EXECUTE` for app/admin/control; the two trigger functions do not. `record_capability_observation(...)` is effective through `PUBLIC EXECUTE` in this database.
- Recorded that the disposable schema has migration versions 1–14 and lacks version 15, so its effective rights do not match the grant boundary declared by migration 015 and `scripts/verify_schema.py`.
- Explicitly superseded the pre-existing all-seven sentence in the mutable WP0 working draft without overwriting its other pending edits.
- Kept `change_ledger` grants **NOT_VERIFIED** because the schema is absent in the inspected database.

## Why

The requested acceptance is effective grants, not intended grants. The per-role read-only queries show that the inspected database does not satisfy the grant boundary declared in migration 015. A separate addendum preserves that observed environment drift while avoiding unrelated pending changes to the WP0 artifact.

## Verification and limits

- Actual agent role: `database-reviewer`; read-only PostgreSQL review in the repository context. Model/effort override: none specified at launch.
- Endpoint: host loopback port `18432`; observed database: `business_ai`. Connection material was loaded only in process through `LaneEnv.load()` and `asyncpg`; no DSN, secret, or row data was emitted.
- Role attributes, memberships, grants, function ACL entries, and migration-version aggregates were queried in `readonly=True` transactions. No business-table rows were queried. The source migration and verifier were read to reconcile measured privileges with the intended boundary; no migration, test, or file write was performed.
- The exact query timestamp was not recorded. The report uses only the host-context date.
- No effective grants after migration 015 were measured; the schema was not modified.
- `CT14Писатель` rights remain clone evidence from `testlane/onec_extension/STATUS.md` and `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` sections 4 and 7, not live Ivan-host rights.
- The existing WP0 transport-verification section was retained; its origin was not re-verified as part of the grant audit.
- No migration, scanner, test, build, CI, COM call, service restart, push, or PR was performed.
- GPT-PM exact-patch review: pending.
