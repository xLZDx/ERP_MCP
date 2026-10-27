# S13 parent-first claim release candidate

## Change

Added `change_ledger.release_claim_v1` to migration 027 and changed `SqlChangeLedger.release_claim`
to select `release_claim_s13` only when the explicit private-writer schema flag is enabled. The
candidate plans the token, scoped record and all resource rows touched by `release_zero_effect`,
prelocks sorted global token/record identities and target/key conflict identities, then locks target
and record parents before the token and child rows. It compares the locked plan before mutation.
The candidate retains requester-or-worker authorization, non-issued token-state replay, repair
target handoff, release-zero-effect behavior, expiry-dependent authorization state, and one
`CLAIM_RELEASED` event. The exact candidate signature is revoked from `PUBLIC` and named
application/private roles; the default legacy route is unchanged.

## Why

The legacy path locks `claim_tokens` before the referenced `records` row. The candidate follows
the accepted parent-first order for the FK graph and freezes helper effects before changing the
token or releasing resources.

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
uninstalled and ungranted, effective privileges are `NOT_VERIFIED`, and
`S13-RELEASE-CLAIM-RANK-01` is `NOT_RUN`. No all-path cutover or runtime deadlock conclusion is
claimed.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: database-reviewer role.
- Later behavior qualification: functional-test-reviewer and e2e-runner after coding closes.
- Push/PR requires fresh GPT-PM approval correlated to the exact final code head.
