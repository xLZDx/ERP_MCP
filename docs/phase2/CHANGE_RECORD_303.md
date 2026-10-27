# Change Record 303 — refuse stale lease generations before child locks

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer.
- Acceptance: `S13-LEASE-RENEW-RANK-01`.
- State: source-only candidate; the edited routine has not yet received a post-change review or disposable SQL qualification.

## Finding and change

The qualification contract requires an unequal requested generation, including NULL, to return
`TICKET_SUPERSEDED` before execution-state, permit, or lease refusal. The function already used
`IS DISTINCT FROM`, but evaluated it only after acquiring `FOR UPDATE` locks on the permit and
lease rows. An existing permit from an older generation could therefore delay a request that the
contract already classifies as superseded.

Migration 027 now locks the scoped parent record, rechecks caller scope, and compares the requested
generation with the locked record before taking child permit or lease row locks. Matching
generations continue through the existing child lock order, frozen-snapshot comparison, execution
state and permit checks, lease update, and single event append. The early refusal performs no
resource update or event append.

An independent bounded source review of the pre-change routine identified the wait-before-refusal
ordering problem and recommended this minimal sequence. A second source-only review of the current
diff confirmed parent lock → scope recheck → generation refusal → permit lock → lease lock → frozen
snapshot comparison, with no DML before the comparison. Matching-generation stale-plan checks
remain intact. Both reviews used the configured `gpt-6-luna` model; exact reasoning effort was not
exposed by the launch results. Neither review parsed or ran SQL.

## Evidence and limits

The acceptance is documented in
`docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` under
`S13-LEASE-RENEW-RANK-01`. The candidate is
`change_ledger.renew_writer_lease_v1` in
`db/phase2/027_private_writer_admission_schema.sql`.

No SQL parser, test, migration, database mutation, grant change, COM call, staging, commit, or push
was performed for this change. Migration 027 remains an uninstalled and ungranted candidate;
effective privileges are `NOT_MEASURABLE` on the inspected database. Disposable qualification must
compare row and event state for NULL and existing-but-stale generations and retain the valid-match
renewal and stale-plan cases.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — move generation refusal ahead of permit and lease row locks.
- `docs/phase2/CHANGE_RECORD_303.md` — this linked change detail.
