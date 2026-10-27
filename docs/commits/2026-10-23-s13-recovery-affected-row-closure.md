# Change record: map S13 recovery batch affected rows

## Change

Added a static candidate closure for the direct and helper effects reachable from `recover_sweep`
and `revoke_stale`, then linked it to qualification scenario `S13-RECOVERY-ROWS-01`. The map
separates the independently bounded `GAP_BOUND` hold selection from `GAP` record triage and records
the parent records, claim tokens, permits, T9 read-only deadline inputs, possible resource and hold
effects, nonce owners, counter/failure keys, and event effects. It assigns generated `sweep_run_id`
only to `recover_sweep`, whose current source inserts `sweep_runs`; `revoke_stale` has no such row.

## Why

The current source map listed recovery stages and individual conflict families but did not state one
batch-wide affected-row plan. Recovery currently discovers secondary effects in per-stage helpers,
updates expired nonces before the record batch, locks tokens before records, and obtains `run_id`
from the final INSERT default. A candidate static closure is needed before a design freeze can
specify what must be discovered, ranked, and revalidated before DML.

## Affected contracts and paths

- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/DOCUMENT_INDEX.md`
- Current-source references: `db/phase2/020_kill_switch_recovery_guard.sql`,
  `db/phase2/006_change_sweeps.sql`, `db/phase2/008_change_hardening_b.sql`,
  `db/phase2/021_ed25519_consumer_cutover.sql`.

## Decisions and limits

- `S13-RECOVERY-ROWS-01` is a future disposable qualification contract; it remains `NOT_RUN`.
- The mapping is source-derived. It does not claim that any deadlock was reproduced, that the
  candidate lock plan is implemented, or that effective grants/runtime schema were verified.
- No migration was prepared or applied. No database or service was changed.
- No tests, build, CI, migration, or runtime contention exercise were run. `git diff --check` was
  inadvertently executed once during this turn; it emitted only existing LF/CRLF normalization
  warnings for Markdown files and no whitespace-error diagnostics.
- Existing worktree changes were preserved; no stage, commit, or push occurred.

## Verification state

Manual static cross-reference only: the scenario and mapping were compared with the cited recovery
stage/helper source and existing token, nonce, counter, and run-ID candidate contracts. The T9
`call_deadlines` lookup is recorded as read-only, not as a row-lock target. One actual read-only
`code-reviewer` agent pass (GPT-6 Luna, low effort) returned no BLOCKER/MAJOR and one MINOR: its
requested distinction between `recover_sweep`'s run row and `revoke_stale`, and the T9 read-only
deadline input, was applied to the docs. Independent test execution and database/reliability review
remain pending after coding is complete. Do not report runtime qualification from this document.

## Ownership and next action

Operator is accountable for the delegated task; Codex is executor; `functional-test-reviewer` and
`e2e-runner` own the later focused test design/execution. Next, reconcile the remaining granted
mutation/helper/trigger paths against the same frozen affected-row and conflict-key contract before
coding freeze.
