# S13 stale-epoch recovery eligibility report

## Change

Migration candidate `db/phase2/027_private_writer_admission_schema.sql` no longer raises
`RECOVERY_NOT_READY` when stale-epoch records are the sole remaining eligible item in a direct
`recover_sweep_v1` call. It permits that API to write its zero-work `sweep_runs` row and return
`has_more_eligible=true`. `kill_switch_v1(OFF)` still rejects the same blocked report with
`RECOVERY_NOT_READY` before appending deferred sweep/kill-switch events; the exception rolls back
the nested run row too. The independent `revoke_stale_v1` operation remains responsible for the
revocation and still uses no sweep run ID.

## Why

The explicit `S13-RECOVERY-ELIGIBILITY-REPORT-01` criterion requires a successful no-op sweep for
one stale-epoch approved/claimed record, followed by `has_more_eligible=false` after restoring the
recorded epoch dependencies. The previous generic guard rejected the first report before a run row
could be recorded. A source review then found that reusing this report inside `kill_switch_v1(OFF)`
would persist a blocked run/event contrary to the separate no-effect refusal contract; the wrapper
now raises before those deferred events and lets the top-level transaction roll back. The nearby
quiescent/VOID acceptance text incorrectly classified this separate stale-epoch queue as
unsupported recovery work; that contract wording is narrowed in
`docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`.

## Affected contracts and paths

- `change_ledger.private_writer_recover_sweep_core_v1`
- `change_ledger.private_writer_recovery_has_eligible_v1`
- `change_ledger.revoke_stale_v1`
- `change_ledger.kill_switch_v1`
- `SqlChangeLedger.recover_sweep` (`src/business_ai_gateway/phase2/change_ledger/sql_ledger.py:527-533`) preallocates the run UUID passed to the S13 SQL entry; the candidate report echoes it.
- S13 recovery quiescent-run and eligibility-report acceptance criteria

## Decision and ownership

Keep eligibility reporting separate from the mutation owner. A stale epoch is observable work, but
the no-run-ID `revoke_stale_v1` is the operation that changes authorization state.

Accountable task owner: operator. Executor: Codex. Technical owner of the ledger contract: not
established by the inspected source records.

## Verification state

Static source/acceptance comparison and a read-only source reviewer found the report/kill-switch
interaction; the direct sweep and OFF wrapper now have separate outcomes. The same reviewer
confirmed the MAJOR acceptance mismatch is closed: the blocked OFF path raises before state/event
writes, and the uncaught exception rolls back the nested run row. Reviewer model/effort metadata
were unavailable (`UNKNOWN`). Source anchors: `private_writer_recovery_has_eligible_v1` at
`027:6085-6090`, the direct-sweep comment/selection block at `027:7540-7545`, the OFF refusal at
`027:5860-5861`, and final sweep-run insertion at `027:7837`. The actual source-review agent was
`/root/recovery_event_sink_review`. The candidate remains unparsed, uninstalled and unqualified. The
stale-only and restored-dependency runtime scenarios are `NOT_RUN`; effective
PostgreSQL grants remain `NOT_MEASURABLE` on the inspected disposable database because
`change_ledger` and candidate roles are absent. No test/check, parser, migration, database write,
COM action, staging, commit or push was run for this change.

Current candidate SHA-256: `2023A9657F6CAB4FA22A434F8654108FAE9BE710DA435FE5E1A6126ABF2FAAA0`.

## Next step

Finish the remaining source/trigger/FK/effect closure, then have the functional-test and E2E roles
qualify `S13-RECOVERY-ELIGIBILITY-REPORT-01` in the authorized disposable database. Do not enable
the candidate route or revoke legacy grants before the coordinated cutover gate.
