# S13 design: keep kill switch active until recovery completes

Date: 2026-10-16. Status: proposed for the non-gating S13 prototype; no implementation or formal S13 approval is implied.

## Goal and non-goals

When an operator requests `OFF`, retain the existing stopped mode if recovery has a failed item, unresolved prior sweep failure, or more eligible work than the current bounded batch processed. Preserve successful recovery work and its failure evidence so the operator can repair the cause and retry.

This does not establish a production scheduler, guarantee external 1C outcomes, close the concurrent external-write/check-then-call race, or promote S13/G1–G8. It does not change key custody, identity, or deployment configuration.

## Current behavior and evidence

Migration 008's `recover_sweep(text,text,jsonb)` selects at most `batch_size` rows per stage (default 100, maximum 500), catches individual failures, records them in `sweep_failures` and returns a JSON report containing `FAILED`. It records each run in `sweep_runs`, whose `run_id` can correlate an attempt. The current `kill_switch(text,text,text)` ignores the report and writes `OFF` unconditionally, despite the migration 006 comment that a failing sweep keeps the switch on. Relevant source: `db/phase2/008_change_hardening_b.sql` (`recover_sweep`, `sweep_item_failed`, `kill_switch`) and `db/phase2/006_change_sweeps.sql` (`sweep_runs`, prior behavior comment).

The Python port expects the existing `kill_switch -> text`, JSON sweep -> `jsonb`, and compatibility sweep -> `integer` signatures. Each port call owns a transaction. Independent reliability and database reviews agree that both caught failures and work left by a full batch must prevent clearing the switch.

## Options and decision

1. **One bounded attempt per call (recommended):** run one sweep; retain the stopped mode if the report contains failures, unresolved failure rows, or a full batch indicating more work may remain. A repeated `OFF` request retries in a new transaction. This keeps transaction size bounded and preserves current API signatures.
2. **Drain multiple batches inside one call:** repeat until recovery reports no work. This may hold locks and the caller transaction for an unbounded duration as backlog grows; reject for this prototype.

## Design

- Add migration `020_kill_switch_recovery_guard.sql`, requiring recorded migrations 001–019. Migration 019 is the separate R-03 Ed25519 prototype change.
- Preserve all existing SQL and Python signatures, return types, and role grants.
- Serialize recovery sweeps with a scope-specific transaction advisory lock in `recover_sweep(text,text,jsonb)`. The kill-switch path keeps its existing kill-switch lock, then acquires the sweep lock; standalone sweep calls acquire only the sweep lock. No code on the sweep path may acquire the kill-switch lock, preserving one lock order.
- Have each sweep report add `run_id`, per-stage selected counts, `has_more`, and current `failed_count`. Derive `has_more` from the candidate batches selected by the existing bounded stage queries: if any selected batch reaches `batch_size`, treat more work as possible. This is conservative: an exactly full final batch may require one harmless retry before `OFF` is accepted.
- On an `OFF` request from a stopped mode, capture the JSON report. If it reports a failure, `has_more`, or any unresolved row remains in scoped `sweep_failures`, do not update `kill_switch_state`; append a hash-chained `KILL_SWITCH` event containing the retained mode, requested mode, blocked outcome, run ID, and counts; return the retained mode. Do not raise for this expected partial result, because the transaction must commit successful item progress and failure evidence.
- If no failure or additional work remains, write `OFF` and append the normal mode-change event. Invalid mode/scope and unexpected top-level database errors retain their existing refusal/rollback behavior; rollback leaves the prior stopped mode intact.
- Keep detailed error evidence in the scoped `sweep_failures` records. The event stores counts and correlation only, not raw SQL error text or payloads. The caller can retry the same `OFF` request after repair or after another bounded batch.

## Failure, concurrency, and rollback

Per-item exceptions remain isolated by the existing subtransactions. Successful work, failed-item counters/events, the sweep run, and the retained switch mode commit together when the function returns normally. A top-level error aborts the transaction and leaves the old stopped mode in force. The new sweep lock serializes standalone workers with the kill-switch recovery attempt so a concurrent sweep cannot make its completion report stale.

The function does not prove that a real external write has finished merely because a database sweep is clear. S13 remains a synthetic prototype; external writer fencing and reconciliation stay separate requirements.

Migration 020 is additive and transactional. Do not edit migrations 006 or 008. If a post-commit correction is needed, use a forward migration; reverting to the current unconditional `OFF` behavior would reopen the failure path.

## Acceptance and verification plan

After all in-scope coding is complete, `functional-test-reviewer` and `e2e-runner` own the focused disposable-PostgreSQL test design and execution:

1. Clean STOP-to-OFF returns `OFF` and records a completed sweep.
2. A poisoned eligible item returns the retained STOP mode; the STOP row is unchanged; successful items and failure counters/events commit. Repair then retry; the failure clears on successful handling and only then may the mode become `OFF`.
3. More eligible claims/permits than one configured batch keeps the switch stopped; repeated requests drain bounded work and clear the switch only after a non-full clean batch. Include `REVOKE` approvals.
4. Repeated OFF after success is idempotent; invalid modes/scopes and non-operator access retain existing behavior; both sweep API signatures and grants remain compatible.
5. Concurrent recovery calls serialize, retain lock order, and cannot produce a false completion result.

The `database-reviewer` then reviews the completed migration, lock interactions, RLS/grants, failure persistence, and runtime evidence. No test or runtime evidence is claimed here.

## Unknowns and remaining dependencies

Formal S13 entry remains unapproved; the documented real 1C writer/pre-image source, deployed identity and key custody, external checkpoint service, scheduler/alerting, and deployment evidence remain external or separately scoped dependencies. This local fix addresses only the source-level kill-switch re-enable failure and bounded-work gap.
