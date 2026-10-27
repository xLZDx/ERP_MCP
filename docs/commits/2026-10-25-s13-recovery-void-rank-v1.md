# S13 bounded recovery stages: ranked permits, uncertainty, gap and verification

## Change

Extended migration `027_private_writer_admission_schema.sql`'s ungranted `recover_sweep_v1` candidate with one-item T5x claim release and shared T6c/T6r permit recovery, the REVOKE-only `VOID` stage, expired approval-nonce expiry, and the bounded T9 hard-deadline stage. T5x snapshots token, record/resource/related-parent and failure rows, acquires namespace-6 IDs and signed-sorted namespace-4 target/key identities, then revalidates before preserving release-zero-effect and repair-handoff behavior. T6c selects one eligible `PERMITTED` permit using the frozen post-fence time/mode. T6r selects one current-generation `NOT_PERMITTED` permit for an `APPLYING` record only after the latest `APPLYING` event plus permit TTL expires at the same frozen time. The shared helper snapshots all change tokens, permit, record/resource/related-parent and stage-failure rows, acquires namespace-6 IDs and signed-sorted namespace-4 target/key identities, and revalidates before the stage-specific `PERMITTED` or `NOT_PERMITTED → CANCELLED_UNDISPATCHED` CAS. Successful cancellation preserves token supersession, release-zero-effect and repair-parent handoff, applies the frozen record-expiry authorization, clears only the selected stage failure and queues the legacy `PERMIT_CANCELLED` or `PERMIT_NOT_ISSUED` event after the caller-preallocated run row. It bounds token/key-release fanout at 200. All one-item stages return other pending eligibility through `has_more_eligible`. The remaining bounded path snapshots selected T3/VOID/T9 record parents, stage-specific failure rows, expired approval nonce rows/parents, T9 dispatch permits, deadlines and every open CALL_OWNERSHIP hold attached to a selected change or selected base; deduplicates record IDs while fencing every selected failure, nonce, permit and hold identity; acquires namespace 3 after namespace 6 and before selected record/resource row locks; then locks and revalidates the complete bounded set before effects. Multiple related live holds, cross-record holds on a selected base, or a live hold on a different base now refuse with `LOCK_PLAN_STALE` before selected record/resource row locks or DML, avoiding an arbitrary `SELECT INTO` choice and closing the hold membership snapshot. It then applies nonce expiry, T3, VOID and T9 transitions in parent-first relation order. The combined selection is capped at 66 items; the conservative bound of three possible row effects per T3/VOID item, one per nonce, four per T9 item, plus the final run row is at most 199. The function also rejects an event queue larger than the selected event-producing T3/VOID/T9 work. Each successful or failed item queues its event after its row effects; the run row is inserted before queued events are appended in ordinal order. Other currently eligible stages still fail closed.

## Why

The previous candidate refused when its eligible work consisted of an expired/REVOKE T6c permit, a REVOKE-only approval void, expired nonce, or overdue dispatched call. The added bounded paths preserve stage order and the caller-preallocated run identity without enabling a legacy fallback.

## Affected contracts and files

- `db/phase2/027_private_writer_admission_schema.sql`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`

## Verification state

Manual source inspection only; the T5x helper and shared T6c/T6r permit helper are new source-only candidates and have not had independent review. No SQL parse, test, check, build, CI, migration, database operation, COM invocation, staging, commit or push ran. Candidate remains uninstalled/ungranted; effective database grants are `NOT_VERIFIED`. `S13-RECOVERY-T5X-RANK-01`, `S13-RECOVERY-T6C-RANK-01`, `S13-RECOVERY-T6R-RANK-01`, `S13-RECOVERY-VOID-RANK-01`, `S13-NONCE-RANK-01`, `S13-RECOVERY-T9-RANK-01` and the existing recovery scenarios remain `NOT_RUN`. Remaining recovery stages and full trigger/event/row-effect closure are still open.

## Ownership and next action

- Accountable task owner: operator; executor: Codex.
- Later source privilege/order review: database-reviewer role.
- Later focused qualification: functional-test-reviewer and e2e-runner after coding closes.
- Next: manually cross-check every new recovery helper against its legacy branch, then finish recovery-to-READY effect and trigger closure before tests or candidate grants.

## 2026-10-25 current-turn recovery extension

The current source-only candidate now also has isolated T12, GAP_BOUND, GAP and VERIFY paths. T12 snapshots the APPLY_UNKNOWN record, uncertainty event, optional RESOLVE counter and failure row; it queues retry/triage events until after the run row. GAP_BOUND keeps an expired anchor-gap hold open, creates its closed bound counter idempotently and avoids repeating an already recorded announcement. GAP freezes all overdue matching holds and the optional RESOLVE counter before triaging one record. VERIFY freezes the due record/counter/open halt-hold/failure state, acquires the FAILED_VERIFY_HALT cause identity, and queues either an attempt or exhaustion event after the run row; exhaustion preserves APPLIED effect resources and adds the halt hold.

Qualification criteria `S13-RECOVERY-T12-RANK-01`, `S13-RECOVERY-GAP-BOUND-RANK-01`, `S13-RECOVERY-GAP-RANK-01` and `S13-RECOVERY-VERIFY-RANK-01` were added to the disposable prerequisite matrix. All four remain `NOT_RUN`. This continuation received manual source inspection only; it has not received the required independent source review. No SQL parse, test, check, build, CI, migration, database operation, COM invocation, staging, commit or push ran. The migration remains uninstalled and ungranted, and effective runtime grants remain `NOT_VERIFIED`.

Manual exception-path review then found that local PL/pgSQL state survives rollback of a per-item exception subtransaction. In the combined T3/VOID/T9 path, each item now records the queued-event length and `changed` count before the savepoint. Its exception handler restores that prefix/count before recording the stage failure, so a rolled-back success cannot remain in the report or be appended alongside `SWEEP_ITEM_FAILED`. The disposable `Recovery result consistency` criterion already requires injecting this boundary for every candidate stage; it remains `NOT_RUN`. This correction is source-inspected only and does not establish aggregate effect bounds, PostgreSQL parseability, or runtime behavior.

The initial attempt in this continuation to let `kill_switch_v1(OFF)` call the partial recovery routine was withdrawn after reconciling the active acceptance matrix: the OFF transition is fail-closed until the complete recovery/event plan exists, and the eventual private helper must defer all recovery events until after the mode decision. The source therefore retains `RECOVERY_NOT_READY` for OFF from a stopped mode. No helper refactor remains in the candidate.

The disposable fault criterion was sharpened to inject after the success queue/count/ID update but before the T3/VOID/T9 item savepoint exits. Outcomes are keyed by `(stage,subject)`: a failed T3 followed by successful VOID for the same record is an expected cross-stage sequence, not a duplicate result.

Manual review of the one-item T5x helper found the same PostgreSQL PL/pgSQL exception-state issue in its report queue: after a fault occurring after `CLAIM_RELEASED` was queued, its handler appended `SWEEP_ITEM_FAILED` to the surviving local success queue, causing the one-event guard to abort the whole sweep. The T5x catch handler now replaces that queue with the single failure event after the SQL subtransaction rollback. Its acceptance criterion now injects at that exact boundary. This is a source-only correction; runtime fault qualification remains `NOT_RUN`.

Manual routing comparison then found that `recover_sweep_v1` selected the combined T3/VOID/nonce/T9 batch before considering T12, GAP_BOUND, GAP or VERIFY. The documented order places those isolated one-item routes after T5x/T6c/T6r and before batch selection. The candidate now evaluates and returns those routes at that point, retaining the single post-fence timestamp and deferring batch work to the next invocation. A multi-stage route-precedence case was added; it remains `NOT_RUN`, and this change has no parse or runtime evidence.

### 2026-10-25 T6r due-time eligibility correction

Manual review found an unconditional duplicate `APPLYING`/`NOT_PERMITTED` branch in `private_writer_recovery_has_eligible_v1`: it reported T6r eligible before the latest `APPLYING` event plus permit TTL had elapsed. Removed the duplicate. The independent `has_unresolved` result still reports the in-flight record, so this does not relax the fail-closed switch gate; it only allows a zero-work recovery report to distinguish waiting from due work. Added the not-yet-due T6r boundary to `S13-RECOVERY-T6R-RANK-01`. Source-only; qualification remains `NOT_RUN`, with no SQL parse, tests/checks, migration or database operation.