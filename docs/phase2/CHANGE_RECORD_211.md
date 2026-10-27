# Change Record 211 — bound anchor reconciliation by planned effects

## What changed

- `check_anchor_v1` now applies the 200-row target limit independently from the 200-row hold-mutation plan limit.
- The frozen hold plan now includes only open `ANCHOR_GAP` rows that the legacy predicate would actually update (`ext_seq IS NULL OR ext_seq < p_ext_seq`). Those same rows are fenced, locked, revalidated, and updated.
- The pre-DML effect cap is the number of planned hold updates plus planned missing-target inserts. An over-cap target or effect plan returns `NOT_ACCEPTED` before any hold mutation or event append.

## Why

The previous precheck rejected work based on `target_count + open_hold_count`, even when the actual DML plan was within the specified bound. It also counted open holds whose external sequence was already current or newer and which the legacy update predicate would not modify. This conflicted with `S13-CHECK-ANCHOR-BOUND-01` and could block valid bounded reconciliation.

## Evidence and verification state

- Changed source: candidate-only `db/phase2/027_private_writer_admission_schema.sql`, `change_ledger.check_anchor_v1`.
- Candidate migration SHA-256 after this change: `F724B38CCC80C408F38A7C78E0FB487D78C98F2632179F2B6BDD14BE89395945`.
- Source inspection only. No SQL parsing, tests/checks/build, migration, database operation, staging, commit or push was run. The candidate remains uninstalled and ungranted; `S13-CHECK-ANCHOR-BOUND-01` remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after coding closes, have the database reviewer inspect the full candidate lock/trigger/unique-conflict graph and have functional/E2E roles qualify the 200-target and 200-effect boundaries, stale holds on inactive bases, and pre-DML over-cap refusal in the approved disposable database.
