# S13 T12 first-pass isolation

## Change

In `db/phase2/027_private_writer_admission_schema.sql`, a successful first T12 pass now creates
the RESOLVE counter and stops before attempt/window processing, even when the event-derived
deadline is already due. It increments `changed` once for that initialization, emits no
`RESOLVE_ATTEMPT`, does not increment attempts, and clears an older T12 failure row after the
successful initialization. The next recovery sweep may perform the first attempt or triage.

## Why

The selector admits an `APPLY_UNKNOWN` item without a RESOLVE counter. For old records,
`started + due_in` can already be at or before the frozen `p_now`. Without an explicit first-pass
boundary, the same invocation initializes and immediately attempts or triages, violating
`S13-RECOVERY-T12-RANK-01`'s counter-initialization scenario. The original code also cleared the
T12 failure row only after an attempt/triage, unlike the legacy stage, which clears it after any
successful item processing.

## Affected contracts and paths

- `change_ledger.private_writer_recovery_t12_v1`
- T12 selection and run accounting in `change_ledger.private_writer_recover_sweep_core_v1`
- `S13-RECOVERY-T12-RANK-01` in `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- Legacy comparison: `db/phase2/008_change_hardening_b.sql`, T12 stage cleanup and attempt count

## Decision and ownership

Keep counter initialization distinct from an actual RESOLVE attempt. The first pass is a successful
state change (`changed=1`) but produces no attempt event; retry timing and triage are evaluated on a
later sweep. Preserve failure-row cleanup on every successful stage pass while allowing the
subtransaction exception path to roll it back before recording one new failure.

Accountable task owner: operator. Executor: Codex. Candidate SQL technical owner is not established
by the inspected project records.

## Verification state

Actual read-only `/root/recovery_event_sink_review` passes identified the overdue-first-attempt
MAJOR at the T12 initialization boundary and confirmed the successful T12 failure-row cleanup
matches legacy behavior. The first source correction gated the main attempt branch; a focused
follow-up found the separate outer window-triage branch, which was gated as well. The final
follow-up confirmed both gates close the MAJOR and the counter initialization, attempt count,
event outcome, and failure rollback/cleanup now align with §662 and the legacy cleanup behavior.
Reviewer model and effort metadata are `UNKNOWN`. Migration 027 SHA-256 at the T12 checkpoint:
`C29006394CD0431D213AC193AA64828286CB6B5B2AFA2EE2FBDA10C9B2CAEAAB`.

This remains source-only. No SQL parser, test, check, build, CI, migration, database write, COM,
staging, commit or push ran. `S13-RECOVERY-T12-RANK-01`, effective runtime grants and disposable
qualification remain `NOT_RUN` or `NOT_MEASURABLE` as recorded in the linked qualification and
WP2 evidence.

## Next step

Finish source/trigger/FK/effect closure. Then have the functional-test and E2E roles qualify the
T12 first-pass, later-attempt, window and attempt-limit cases in the authorized disposable schema.
