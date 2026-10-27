# Change record 329 — correct barrier acknowledgement composite field access

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator by explicit delegation; executor: Codex.
- Candidate migration 027 and related test/doc files were already untracked in the shared worktree;
  earlier origin is not attributed. This increment fixes four nested composite-field references
  exposed by the new `S13-BARRIER-ACK-SERVICE-BINDING-01` runtime test.
- No configured database, host, COM, key, staging, commit, or push operation occurred.

## Defect and change

The first disposable PostgreSQL execution of
`private_writer_register_barrier_ack_v1` failed with `missing FROM-clause entry for table "scope"`
before reaching the new service-binding guard. The function used `p_ack.scope.tenant_id` and
`p_ack.scope.company_id` in four SQL expressions; PostgreSQL interpreted the nested field reference
as a relation-qualified name in that context. Each was changed to the explicit composite-field
form `(p_ack.scope).tenant_id` / `(p_ack.scope).company_id`.

The finding is a source/runtime defect in the previously unexecuted acknowledgement path, not a
test-fixture correction. The test owner is re-running the exact routine against a fresh owned
PostgreSQL 16 cluster to confirm the fix and continue the binding acceptance.

## Verification state

- Candidate migration 027 SHA-256 after this correction:
  `69FBAEA9018D6738416F8F20E7055F4503392F6551B0EA7CB8DD3A62F07DBAC4`.
- The functional-test reviewer ran `uv run pytest -q tests/phase2/test_s13_barrier_ack_sql.py`:
  **3 passed in 25.70s**. Test SHA-256:
  `74724C930C3CD9C6FC27B942A4F6748F1CD38B213DCFD2A7B8841C1C551F23A5`. The initial exact-hash
  invocation exposed `missing FROM-clause entry for table "scope"`; after correction, the module
  passed, including active/missing/mismatched/revoked binding checks, no-row refusal, and a static
  binding-before-trust/advisory ordering assertion.
- Full successful acknowledgement insertion and both concurrent registration/revocation orders
  remain `NOT_RUN`; a fully populated signed acknowledgement/barrier fixture is still being
  explored by the functional-test reviewer. No test was run by the primary session.
- Prior 38-test candidate evidence applies to the earlier migration hash and does not qualify this
  corrected source. The configured lane still lacks `change_ledger` and candidate runtime roles.

## Next steps

1. Functional-test reviewer: confirm the corrected nested-composite call, active/mismatched/revoked
   service-binding behavior, no-write refusals, and lock ordering on an invocation-owned disposable
   PostgreSQL 16 cluster.
2. Database and security reviewers: review the final exact migration hash and the binding lock
   against trust-revision, advisory, resource and revocation order after test completion.
3. Codex: retain the routine's default-denied ACL; do not infer that this source fix enables the
   evidence-ingest role or qualifies a physical COM writer.
