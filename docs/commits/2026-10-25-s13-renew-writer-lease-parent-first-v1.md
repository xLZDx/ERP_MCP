# S13 parent-first writer-lease renewal candidate

## Change

Added `change_ledger.renew_writer_lease_v1` to migration 027 and an opt-in no-fallback
`renew_writer_lease_s13` route. It freezes the scoped record, dispatch permit and lease after the
scope/lifecycle fences; acquires the global record identity; locks record before permit and lease;
and checks the complete locked snapshots before applying the legacy TTL/generation/permit/state
contract. Successful renewal extends the lease, increments `renew_count`, and appends one
`LEASE_RENEWED` event. The exact candidate signature is revoked from `PUBLIC` and all named
application/private roles.

## Why

The legacy writer-lease mutation begins by locking `records` and only later reaches permit and
lease state without a shared versioned scope fence. This additive candidate provides a bounded,
revalidated parent-first entry while preserving the legacy route until coordinated cutover.

## Affected contracts and files

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`

## Verification and limitations

Manual source inspection only. No SQL parse, test/check/build/CI, migration, database operation,
COM call, staging, commit or push ran. Candidate review remains outstanding; the function is
uninstalled/ungranted, effective privileges are `NOT_VERIFIED`, and
`S13-LEASE-RENEW-RANK-01` is `NOT_RUN`. S13 source-wide cutover and runtime behavior are not
established.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: database-reviewer role.
- Later behavior qualification: functional-test-reviewer and e2e-runner after coding closes.
- Push/PR requires fresh GPT-PM approval correlated to the exact final code head.
