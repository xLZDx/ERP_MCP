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
- Serialize all scoped sweeps with one transaction advisory lock acquired before candidate selection. The same lock is held from the `OFF` attempt through its final state check and switch update, so a standalone worker cannot make the report stale.
- Have each sweep report add `run_id`, per-stage selected counts, `has_more_eligible`, `has_unresolved`, and `failed_count`. Do not infer completion from the size of the original candidate arrays: later stages can create new eligible or unresolved state (for example, T9 can change `APPLYING` to `APPLY_UNKNOWN` after the T12 selection phase). After all stages finish, run a final scope-locked query using the same stage predicates to count currently eligible recovery work. `has_more_eligible` is true when any such row remains, including a conservative full-batch retry. Separately, `has_unresolved` covers `APPLYING`, `APPLY_UNKNOWN`, `APPLIED/NOT_VERIFIED`, and active holds for unresolved call ownership, failed verification, or anchor gaps, including items whose retry time has not arrived. This distinction prevents “not due yet” from being treated as “resolved.”
- On an `OFF` request from a stopped mode, capture the JSON report. If the current report has a failure, any scoped `sweep_failures` row remains, `has_more_eligible` is true, or `has_unresolved` is true, do not update `kill_switch_state`; append a hash-chained `KILL_SWITCH` event containing retained mode, requested mode, blocked outcome, run ID, the two booleans, and counts; return the retained mode. Do not raise for this expected partial result, because the transaction must commit successful item progress and failure evidence.
- Define failure-row cleanup by stage and require a confirmed processing outcome. T5x/T6c/T6r/T9/T3/VOID/GAP clear only after their intended state transition or a confirmed terminal state. `REVOKE_STALE` clears only after `revoke_core` returns a terminal revoked/voided result. T12 clears only after a durable resolve-attempt event, a terminal triage transition, or a confirmed non-`APPLY_UNKNOWN` state. VERIFY clears only after a durable verification attempt or terminal state transition, not merely because an item was selected. GAP_BOUND clears only after the closed `ANCHOR_GAP` counter and bound-exceeded audit event are both persisted. A failure remains if a stage was only inspected or not yet due.
- If no failure or additional work remains, write `OFF` and append the normal mode-change event. Invalid mode/scope and unexpected top-level database errors retain their existing refusal/rollback behavior; rollback leaves the prior stopped mode intact.
- Keep detailed error evidence in the scoped `sweep_failures` records. The event stores counts and correlation only, not raw SQL error text or payloads. The caller can retry the same `OFF` request after repair or after another bounded batch.

## Failure, concurrency, and rollback

Per-item exceptions remain isolated by the existing subtransactions. Successful work, failed-item counters/events, the sweep run, and the retained switch mode commit together when the function returns normally. A top-level error aborts the transaction and leaves the old stopped mode in force. The new sweep lock serializes standalone workers with the kill-switch recovery attempt so a concurrent sweep cannot make its completion report stale. The `OFF` condition is exactly: current failures = 0, scoped failure rows = 0, `has_more_eligible = false`, and `has_unresolved = false`.

The function does not prove that a real external write has finished merely because a database sweep is clear. S13 remains a synthetic prototype; external writer fencing and reconciliation stay separate requirements.

Migration 020 is additive and transactional. Do not edit migrations 006 or 008. If a post-commit correction is needed, use a forward migration; reverting to the current unconditional `OFF` behavior would reopen the failure path.

## Acceptance and verification plan

After all in-scope coding is complete, `functional-test-reviewer` and `e2e-runner` own the focused disposable-PostgreSQL test design and execution:

1. Clean STOP-to-OFF returns `OFF` and records a completed sweep.
2. A poisoned eligible item returns the retained STOP mode; the STOP row is unchanged; successful items and failure counters/events commit. Repair then retry; the failure clears on successful handling and only then may the mode become `OFF`.
3. More eligible claims/permits than one configured batch keeps the switch stopped; repeated requests drain bounded work. Include `REVOKE` approvals.
4. A T9 transition to `APPLY_UNKNOWN` later in the same sweep makes `has_unresolved` true; a T12/VERIFY item waiting for its next attempt remains unresolved even when not currently eligible.
5. A prior failure row is not cleared by mere selection or inspection; prove retry success for each cleanup family, including `REVOKE_STALE` and `GAP_BOUND`.
6. Repeated OFF after success is idempotent; invalid modes/scopes and non-operator access retain existing behavior; both sweep API signatures and grants remain compatible.
7. Concurrent recovery calls serialize, retain lock order, and cannot produce a false completion result.

The `database-reviewer` then reviews the completed migration, lock interactions, RLS/grants, failure persistence, and runtime evidence. No test or runtime evidence is claimed here.

## Unknowns and remaining dependencies

Formal S13 entry remains unapproved; the documented real 1C writer/pre-image source, deployed identity and key custody, external checkpoint service, scheduler/alerting, and deployment evidence remain external or separately scoped dependencies. This local fix addresses only the source-level kill-switch re-enable failure and bounded-work gap.
