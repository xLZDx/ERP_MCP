# S13 GAP_BOUND report ordering

## Change

In migration candidate 027, direct `private_writer_recovery_gap_bound_v1` now appends its queued
bound-announcement or failure event after inserting the caller-identified `sweep_runs` row, then
recomputes `has_more_eligible`. The deferred kill-switch path still returns the event queue to its
outer caller so that caller can finish its state decision before namespace-1 event work.

## Why

GAP_BOUND eligibility includes absence of `ANCHOR_GAP_BOUND_EXCEEDED` for the selected hold. The
helper previously calculated `has_more_eligible` while the selected event was still queued, so a
successful event-only repair could report the same hold as eligible after the current run. That
could cause an unnecessary empty follow-up sweep even though the event append was part of this
transaction.

## Affected contracts and paths

- `change_ledger.private_writer_recovery_gap_bound_v1`
- `change_ledger.private_writer_recovery_has_eligible_v1`
- `change_ledger.private_writer_recover_sweep_core_v1`
- `S13-RECOVERY-GAP-BOUND-RANK-01` in
  `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- Event sink `change_ledger.private_writer_append_queued_events_v1`

## Decision and ownership

For the direct sweep path, preserve row-before-event ordering and calculate the returned eligibility
after queued events are appended. For the deferred kill-switch path, keep the queue deferred until
the parent has completed its state decision. `p_effect_reserve=0` denotes the direct stage call;
the deferred wrapper passes the reserved value 2.

Accountable task owner: operator. Executor: Codex. Candidate SQL technical owner is not established
by the inspected project records.

## Verification state

Source inspection identified the selection predicate and the helper's pre-fix event/report order.
An actual read-only `/root/recovery_event_sink_review` follow-up found no concrete issue: the direct
path appends once after the run row and recomputes eligibility after append; the outer caller's
empty-queue append cannot duplicate it. The reviewer also confirmed the deferred kill-switch path
retains the queue through the state decision and that namespace 1 remains last. Model/effort
metadata are `UNKNOWN`. Current migration 027 SHA-256 at this checkpoint:
`1B5B2D2BAD8DC17CD130D95AB46ED851ACD36C3C7CB3E5B2023B75206EAC0724`.

No SQL parser, test, check, build, CI, migration, database write, COM, staging, commit or push ran.
The candidate remains uninstalled and unqualified; `S13-RECOVERY-GAP-BOUND-RANK-01` remains
`NOT_RUN`.

## Next step

Complete source/trigger/FK/effect closure. After code closure, have the functional-test and E2E roles
qualify first announcement, event-only repair, failure replay, and no-repeated-work outcomes in the
authorized disposable schema.
