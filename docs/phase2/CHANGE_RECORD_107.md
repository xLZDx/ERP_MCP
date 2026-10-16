# Change record 107 — keep the kill switch active through recovery

## What changed

- Added additive migration `db/phase2/020_kill_switch_recovery_guard.sql`, requiring recorded migrations 001–019 and recording version 020 transactionally.
- Preserved `kill_switch(text,text,text) -> text`, both `recover_sweep` signatures, and existing grants.
- Serialized scoped recovery calls with a transaction advisory lock. The kill-switch path keeps lock order kill-switch, then sweep, then existing row/chain order.
- The JSON report adds run ID, per-stage selected counts, current failure count, scoped unresolved failure-row count, and post-stage `has_more_eligible` / `has_unresolved` values while retaining the old report keys. The legacy integer wrapper is unchanged. The unresolved-hold predicate includes all four causes allowed by migration 004: `CALL_OWNERSHIP`, `FAILED_VERIFY_HALT`, `ANCHOR_GAP`, and `RLC_UNCLEAN`.
- `OFF` is written only when current `FAILED` is empty, scoped sweep-failure rows are absent, `has_more_eligible` is false, and `has_unresolved` is false. Otherwise the prior stopped mode is retained; a hash-chained `KILL_SWITCH` event records requested/effective mode, blocked outcome, run ID, and counts; the function returns normally so partial progress and failure evidence commit.
- T12 and VERIFY failure rows no longer clear on inspection or a delayed retry. `REVOKE_STALE` clears only after `revoke_core` returns `REVOKED` or `VOIDED`; `GAP_BOUND` clears only after both the closed bound counter and bound-exceeded event are present.

## Why

Migration 008's bounded sweep records item failures, but the kill-switch path ignored its report and unconditionally wrote `OFF`. The approved S13 design retains the stopped mode until a bounded recovery call establishes that failures, eligible work, unresolved work, and relevant active holds are all absent.

## Approval and scope

- PM approval request correlation: `115ca957-10e5-4efe-ad73-9c4d693d1e3b`.
- Synthetic, non-gating prototype only. No formal S13/G1–G8 closure or production deployment is claimed.
- Design-source refinement: migration 004 permits active `RLC_UNCLEAN` holds in addition to the three causes listed in the initial design predicate. Migration 020 treats an active hold of any of those four causes as unresolved. The added predicate is conservative; PM confirmation is pending before the test phase.
- No real external 1C outcome, scheduler, writer fence, deployed identity/key custody, or live database state is asserted or changed.
- Migrations 006 and 008 are not edited.

## Affected contracts and paths

- `db/phase2/020_kill_switch_recovery_guard.sql`
- `change_ledger.kill_switch(text,text,text) -> text`
- `change_ledger.recover_sweep(text,text,jsonb) -> jsonb`
- `change_ledger.recover_sweep(text,text) -> integer` (wrapper unchanged)
- `change_ledger.revoke_stale(text,text) -> integer`
- Existing scope/RLS, `SECURITY DEFINER`, `search_path`, `ledger_owner`, PUBLIC revoke, and role grants.

## Verification state and remaining uncertainty

- Tests: `NOT_RUN`.
- SQL/static checks: `NOT_RUN`.
- Database commands and migration execution: `NOT_RUN`.
- No runtime behavior is proven. The final eligibility predicates, advisory lock interaction, and stage cleanup need independent database review and focused disposable PostgreSQL evidence.
- A full selected batch conservatively blocks `OFF` for an additional retry, including when the batch held the final eligible work.
