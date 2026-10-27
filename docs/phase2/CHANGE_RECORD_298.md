# Change Record 298 — align hold plans to target registry identity

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer.
- Acceptance: `S13-OPEN-HOLD-RANK-01` and `S13-ANCHOR-CHECK-RANK-01`.
- State: source-only candidate. Manual source inspection only; no tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Finding and change

The canonical target registry in `db/phase2/004_change_ledger.sql` has one row per `(tenant_id,company_id,base_fingerprint)`. Target-specific references belong to `target_locks`, not `targets`. The candidate migration’s hold paths need to enumerate and lock the target parent by its actual primary key, while creating at most one new hold for each distinct base without an open hold.

Migration 027 now uses `base_fingerprint` as the target-parent snapshot and lock order in `private_writer_open_hold_v1` and `check_anchor_v1`. Both paths enumerate eligible rows from the one-per-base primary-key registry and preallocate exactly one new hold ID per eligible base. After namespace-3 arbitration, `private_writer_open_hold_v1` now skips a base for which a serialized peer already created the same open hold, preserving the source routine's return `0`/no-event behavior; a newly eligible base without a planned/fenced ID still refuses stale. In `operator_resolve_v1`, the active-target parent snapshot likewise records the actual one-row-per-base identity; namespace-4 advisory identities come from the frozen target-lock and key-lock rows, rather than a nonexistent `targets.target_ref`. In `revoke_stale_v1`, target-parent snapshots and locks follow `(base_fingerprint)` while target-lock snapshots and locks retain `(base_fingerprint,target_ref)`.

## Acceptance and evidence boundary

Extend `S13-OPEN-HOLD-RANK-01` and `S13-ANCHOR-CHECK-RANK-01` to require one planned hold ID for every eligible one-per-base registry row and none for a base that already has its open hold. Race two declarations from an initially unheld base: the first opens one hold/event; the serialized peer returns `0` and adds neither. Change target status/epoch and membership between plan and row lock; require exact snapshot comparison and refusal before DML. For `S13-REVOKE-STALE-BATCH-RANK-01`, seed multiple target-lock references for one base and require total target-lock ordering, while checking the registry row by base only. Runtime qualification remains `NOT_RUN`.

No SQL parser, migration, ACL installation, database operation, tests, checks, build, or COM operation ran. Effective privileges remain `NOT_VERIFIED`; the candidate functions remain uninstalled/ungranted. This source change does not establish the operational writer or transaction boundary.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — correct target-parent identity and make hold generation follow the target registry's one-row-per-base primary key in `private_writer_open_hold_v1` and `check_anchor_v1`; align `operator_resolve_v1` and `revoke_stale_v1` with the target table’s actual key.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — add duplicate-base and target-lock-vs-target-parent acceptance.
- `docs/phase2/CHANGE_RECORD_296.md` and `CHANGE_RECORD_297.md` — correct target identity descriptions against the canonical DDL.
