# S13 claim parent-first candidate

## Change

Added `change_ledger.claim_v1` to migration 027 and an opt-in `claim_s13` route in
`SqlChangeLedger.claim`. The adapter allocates the new token UUID before invocation. The SQL
candidate builds a non-locking grant, target, record and resource plan after entry fences, takes
sorted global identities and the candidate's signed-sorted namespace-4 keys, then locks grant and
target parents before the records SCC and child rows. It compares the locked snapshot with the plan
before mutation. Live issued-token replay returns before lifecycle readiness, switch-state and
budget checks and checks the declared grant/amount/count flags without writing another event.

The candidate signature is revoked from `PUBLIC` and all named application/private roles. The
legacy route remains default; selecting S13 has no fallback. An unused pre-plan token read was
removed because the locked current-generation token lookup is the only value used by replay.

## Why

The legacy claim route locks the record before `budget_precheck` locks its grant parent, then writes
reservation, target/key/lease resources and a token. Migration 027's candidate uses the accepted
FK-parent order and freezes the IDs and resource state before row locks, while preserving source
replay semantics.

## Affected contracts and files

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Verification and limitations

Manual source inspection only. No SQL parse, test/check/build/CI, migration, database operation,
COM call, staging, commit or push ran in this change. Candidate source review remains outstanding;
the additive routine is uninstalled and ungranted, effective grants are `NOT_VERIFIED`, and
`S13-CLAIM-PARENT-RANK-01` is `NOT_RUN`. This does not establish source-wide lock closure,
legacy cutover, or the Ivan COM writer transaction boundary.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: database-reviewer role.
- Later behavior qualification: functional-test-reviewer and e2e-runner after coding closes.
- Push/PR requires fresh GPT-PM approval correlated to the exact final code head.
