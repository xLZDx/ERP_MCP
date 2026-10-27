# S13 ranked anchor-gap and unclean-restart hold candidates

## Change

Added `private_writer_open_hold_v1` and flag-gated `declare_anchor_gap_v1` /
`declare_unclean_restart_v1` routes to migration 027 and `SqlChangeLedger`. The helper creates a
bounded affected-base plan, preallocates each global `hold_id`, locks those IDs in namespace 6,
then acquires the exact legacy namespace-3 hold key before target/hold row work. It caps a
whole-scope operation at 200 target/open-hold rows, locks sorted target parents before existing
hold children, revalidates the target and eligible-base sets, inserts explicit IDs, and appends the
source event only when at least one hold opens. The helper and wrappers have no application grants
and explicit revokes; existing adapter methods retain legacy default routing and have no fallback
when the candidate flag is enabled.

## Why

The existing helper acquires namespace 3 and performs broad hold mutation using database-generated
global IDs without a shared scope fence or a precomputed lock set. The additive helper brings the
affected rows and global IDs into the S13 plan while bounding transaction work.

## Affected contracts and files

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`

## Verification and limitations

Manual source inspection only. No SQL parse, test/check/build/CI, migration, database operation,
COM call, staging, commit or push ran. Candidate review remains outstanding; helper/wrappers are
uninstalled and ungranted, effective privileges are `NOT_VERIFIED`, and
`S13-OPEN-HOLD-RANK-01` is `NOT_RUN`. The candidate's 200-row cap and source cutover need disposable
qualification; no runtime claim is made.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: database-reviewer role.
- Later behavior qualification: functional-test-reviewer and e2e-runner after coding closes.
- Push/PR requires fresh GPT-PM approval correlated to the exact final code head.
