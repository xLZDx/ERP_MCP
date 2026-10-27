# Change Record 301 — preserve idempotent kill-switch OFF

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer.
- Acceptance: `S13-KILL-SWITCH-LEGACY-BRIDGE-01`.
- State: source-only candidate; manual and bounded independent source review found no issue in this function. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Finding and change

The accepted kill-switch contract requires `OFF` when already `OFF` to be an idempotent no-op. `kill_switch_v1` previously fell through to an upsert and event append in that case, which changed the row timestamp and added a `KILL_SWITCH` event despite no state transition.

Migration 027 now returns `OFF` after scope, transaction, operator, input, namespace-2 fence, scope fence, lifecycle lock, and locked-scope recheck have succeeded, but before any state write or event append. `OFF` from a stopped mode still follows the deferred recovery path and retains its fail-closed `RECOVERY_NOT_READY` rollback behavior.

## Evidence and limits

The source acceptance is `S13-KILL-SWITCH-LEGACY-BRIDGE-01` in `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`. The implementation is `change_ledger.kill_switch_v1` in `db/phase2/027_private_writer_admission_schema.sql`.

This is manual source work, not parsed or runtime-proven. Migration 027 is uninstalled and ungranted; effective privileges remain `NOT_MEASURABLE` on the inspected disposable database and qualification remains `NOT_RUN`.

An independent `code-reviewer` agent reviewed `kill_switch_v1` and adjacent renewal/cancellation/release routines. It found no source-level issue in the already-OFF branch. The review was limited to those routines; ACL, races and runtime qualification remain open. Reviewer model is the configured `gpt-6-luna`; exact reasoning effort was not exposed by the launch result.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — return early for the already-OFF state without update or event.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — existing acceptance requires an idempotent no-op; no acceptance weakening was made.
