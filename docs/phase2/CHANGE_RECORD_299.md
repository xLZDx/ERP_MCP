# Change Record 299 — bound combined anchor-check row plans

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer.
- Acceptance: `S13-ANCHOR-CHECK-RANK-01`.
- State: source-only candidate; manual source inspection only. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Finding and change

`check_anchor_v1` bounded target-parent and hold plans separately, so a plan containing both could exceed the S13 total row budget. Its oversized-target refusals also used `NOT_ACCEPTED`, although the accepted source contract requires `MUTATION_TRANSACTION_INVALID` before ranked row locks and DML.

Migration 027 now counts the combined target-parent snapshot, selected existing open holds, and preallocated new hold IDs against the 200-row bound. All over-limit branches in this candidate routine use `MUTATION_TRANSACTION_INVALID`, including the post-fence target-count recheck. The existing exact snapshots and rank order remain in place.

## Evidence and limits

Source acceptance is specified in `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, section `S13-ANCHOR-CHECK-RANK-01`. The relevant implementation is `db/phase2/027_private_writer_admission_schema.sql`, function `change_ledger.check_anchor_v1`.

This is manual source work, not parsed or runtime-proven. The candidate migration is uninstalled and ungranted; effective privileges are `NOT_VERIFIED` and disposable qualification is `NOT_RUN`. This change does not implement or prove the licensed 1C writer.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — enforce the combined planned-row bound and the required refusal class in `check_anchor_v1`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — specify the precise combined row-budget inputs.
