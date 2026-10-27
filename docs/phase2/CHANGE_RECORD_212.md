# Change Record 212 — refuse whole-scope S13 hold fan-out

## What changed

- The shared candidate hold writer now rejects a null base with `SCHEMA_INVALID` before transaction guards, scope locks, or table reads.
- Its target and existence plan are now always filtered to the single supplied base; the unreachable whole-scope predicates were removed.
- Existing open holds are lookup-only: after the exact legacy namespace-3 fence, the helper revalidates whether any open hold remains and returns `0` without locking every historical hold row. This preserves idempotent no-op behavior when the hold history is large while keeping creation/release serialized at the required cutover boundary.
- `S13-OPEN-HOLD-RANK-01` now specifies the one-base contract and the pre-lock null refusal instead of a capped whole-scope fan-out.

## Why

The accepted S13 design requires each versioned hold operation to affect one physical base per transaction. The candidate still accepted `p_base=NULL`, which allowed a bounded but cross-base fan-out and contradicted that contract. The legacy route remains a separate compatibility path; this correction only changes the ungranted candidate.

## Evidence and verification state

- Changed code: candidate-only `db/phase2/027_private_writer_admission_schema.sql`, helper `private_writer_open_hold_v1` used by `declare_anchor_gap_v1` and `declare_unclean_restart_v1`.
- Candidate migration SHA-256 after this change: `0E0CFE3446C411F8F10BD433CF77AC20E9A070B128E54B7676CB20A6D92E8F1A`.
- Changed qualification contract: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, `S13-OPEN-HOLD-RANK-01`.
- Source inspection only. No SQL parse, tests/checks/build, migration, database operation, staging, commit or push was run. Candidate stays uninstalled/ungranted; qualification remains `NOT_RUN` and effective grants remain `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue source closure and complete coordinated hold-writer ACL cutover; after coding closes, have database review cover the shared helper and trigger/unique-conflict graph, then have functional/E2E roles verify null refusal before locks, named missing-base behavior, lookup-only replay with large hold history, and one-event creation in the approved disposable database.
