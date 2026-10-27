# Change Record 271 — target-lock and writer-lease owner scope

## Ownership and state

- Date: 2026-10-25.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: the private runtime stack is Ivan's `ERP_MCP_Ivan_Stack` scheduled task, as recorded in `artifacts/REMOTE_1C_HOST_STACK_2026-10-11.md`; canonical individual ownership of the migration source is not established here.
- State: source implementation and disposable qualification contract updated; independent source review found no actionable finding in scope; runtime qualification not run.

## Change and reason

Migration `db/phase2/027_private_writer_admission_schema.sql` adds the private helper
`private_writer_assert_target_lease_owner_scope_v1`. It fails closed with `LOCK_PLAN_STALE` if any
`target_locks` or `writer_leases` row owned by the selected change has a tenant, company, or base
that differs from that change's frozen record. The check runs for the unlocked plan and repeats after
the namespace-6 owner fence, before namespace-4/resource row locks or state-changing DML, in:

- `resolve_unknown_v2`;
- `operator_resolve_v1`;
- `claim_v1`;
- `release_claim_v1`;
- `revoke_change_v1`;
- bounded `revoke_stale_v1`;
- `retry_verify_v1`;
- the shared T6c/T6r recovery permit;
- `private_writer_recovery_t5x_v1`;
- `cancel_permit_v1`;
- `operator_close_failed_verify_v1`; and
- `renew_writer_lease_v1`.

In `004_change_ledger.sql:259-278`, each resource owner foreign key references only the globally
unique `records(change_id)`; it does not enforce equality of tenant, company, or base. A malformed
owned row can therefore be omitted by scope-filtered resource lookup/cleanup or be planned under a
different resource identity. The additional preflight and post-fence check make that state refuse
before the scoped function relies on the resource snapshot.

## Acceptance and evidence boundary

- Disposable criterion: `S13-TARGET-LEASE-OWNER-SCOPE-01` in
  `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`. It covers all three mismatched
  scope fields for both resource relations, all twelve paths, post-owner-fence recheck, and atomic
  refusal for a mixed bounded recovery batch. Execution remains `NOT_RUN`.
- Source inventory: `S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`, addendum dated
  2026-10-25.
- Candidate source SHA-256: `B53A1D71418B1405191F7B0097FB19CB0FA33FA0D08824DC5234F29B2792F9EE`.
- Independent review: actual `code-reviewer` agent, read-only; no actionable source finding across
  the helper, all 12 pre/post-fence paths, and the row-access coverage audit. Exact model/effort
  metadata was not exposed in the follow-up result and is therefore not claimed. No SQL parser,
  test, check, build, database query, migration, install, grant inspection, or runtime operation was
  performed for this change.
- Effective privileges remain `NOT_VERIFIED`; migration 027 remains uninstalled/ungranted.

## Next gate

Continue the remaining S13 implementation in dependency order. After all in-scope code is complete,
delegate functional and E2E qualification to their required test-owner roles. Those agents own test
authoring and execution; Codex checks the resulting evidence against the acceptance matrix.
