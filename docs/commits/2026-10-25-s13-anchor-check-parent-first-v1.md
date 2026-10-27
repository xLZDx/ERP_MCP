# S13 parent-first anchor-check candidate

## Change

Added `change_ledger.check_anchor_v1` to migration 027 and an opt-in no-fallback worker route in
`SqlChangeLedger.check_anchor`. The candidate validates the legacy external-head format and
preserves the matching-head no-op. For a mismatch it plans all target and open `ANCHOR_GAP` hold
rows, preallocates IDs for missing holds, and caps the combined target/open-hold set at 200. It
acquires sorted global hold IDs, then the exact namespace-3 legacy hold identity, locks target
parents before open-hold rows, and revalidates those snapshots. It acquires the namespace-1 event
chain identity last, rechecks the external head, then updates older open holds, inserts missing
holds with explicit IDs and appends the legacy event.

The exact candidate signature is revoked from `PUBLIC` and all named application/private roles.
Legacy routing remains the default; candidate routing fails closed without a v1 function/grant.

## Why

The legacy entry can update/open many holds and generates global hold IDs during its row work. The
candidate makes the affected row/ID set explicit and bounded while respecting the schema-derived
parent-first and advisory-lock ranks.

## Affected contracts and files

- `db/phase2/027_private_writer_admission_schema.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`

## Verification and limitations

Manual source inspection only. No SQL parse, test/check/build/CI, migration, database operation,
COM call, staging, commit or push ran. The candidate is uninstalled/ungranted and source review is
outstanding; effective privileges are `NOT_VERIFIED` and `S13-ANCHOR-CHECK-RANK-01` is `NOT_RUN`.
This does not prove installed ACLs or runtime lock order.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later source grant/order review: database-reviewer role.
- Later behavior qualification: functional-test-reviewer and e2e-runner after coding closes.
- Push/PR requires fresh GPT-PM approval correlated to the exact final code head.
