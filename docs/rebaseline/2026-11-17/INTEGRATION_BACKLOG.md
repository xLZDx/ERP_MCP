# Main integration and cleanup backlog

This is a preparation plan, not permission to discard unknown work.
Origin/main baseline: 7c1f69cf51b16d3849772fdb1e32015b17cb1aa7.

## Ordered batches

| Batch | Scope | Exit evidence |
|---|---|---|
| I-01 | Preserve all dirty root and linked-worktree changes | External immutable backup/manifests; every changed file assigned an integration disposition |
| I-02 | Reconcile current autonomous branch and S0 compatibility | 87 root-only commits and dirty deltas compared against current main; conflicts reviewed |
| I-03 | S12 then stacked S13 PR54/58 | Dependency order and exact tree defined; source/test/contract conflicts resolved |
| I-04 | S14 private writer / S15 / S16 candidate work | Source-to-story coverage, package separation A-01, updated design and bounded qualification evidence |
| I-05 | Residual historical branches | Each unique patch assigned integrate/retain/archive, with no unique work lost |
| I-06 | Integrate approved candidate | Exact-head review/test evidence and GPT-PM approval; merge without rewriting history |
| I-07 | Cleanup and steady-state main | Remote merged-head deletion enabled; main refreshed; local merged clean scratch copies removed only after process/junction/ignored-file inspection |

## Audit results available now

Patch equivalence was measured for all 63 local branches using git cherry against
origin/main: all comparisons succeeded, twelve tips have zero unique non-merge
patches. This does not prove a branch with unique merge resolutions is disposable.
Nine local tips are main ancestors; main remains permanently protected.

All 47 registered worktrees were inspected for tracked and untracked status:
19 dirty, 28 clean in that limited sense. No status command failed. Ignored files,
running processes and external junctions remain separate cleanup conditions.
WORKTREE_STATES.json records every path and changed-file list. Preserve the
19 dirty trees before any corresponding branch disposal.

PR57 is MERGED into main at 7c1f69c (gh pr view, 2026-11-17). The origin/pr-57
helper ref is not itself proof that its current contents should be removed.

## Steady-state branch lifecycle

One short-lived codex branch and PR per reviewed sprint, based on updated main.
No direct development in main, no rewrite/force push. Merge only the reviewed
head. GitHub deleteBranchOnMerge=true removes eligible remote head branches.
After observing MERGED, refresh main and invoke local merged-worktree cleanup;
delete a local sprint branch with git branch -d only when no worktree uses it
and its ancestry is integrated. Never delete main/master. A GitHub-side merge
does not run a local hook; the shipping procedure must perform the local update.

Existing .harness-tools/githooks/post-merge calls worktree_gc.py. It skips dirty
or ignored-content worktrees; cleanup skips must be recorded, not hidden.
Do not install a scheduled cleanup job: operator disabled periodic local checks.

## Architecture fixes for I-04

- A-01 MAJOR: isolate private writer from production package discovery.
- A-02 MINOR: label S10 handoff historical and point to current architecture.
- A-03 MINOR: disambiguate environment and gateway mode metadata without
  silently changing a compatibility contract.

## Confirmed gateway concurrency fix before I-02 integration

G-01: migration 016 record_capability_observation holds a transaction-scoped
per-source advisory lock but deletes all observations for that source before
inserting the current request (lines 129-155). The observer returns from this
DB operation before making the separate acceptor HTTP call (observer service
lines 228-260). Two different request IDs can interleave A-record, B-record,
A-accept; B deletes A's pending observation and A fails provenance acceptance.
Several ordinary read tools refresh capabilities through this route. This is
a confirmed source-level availability race, not a tested runtime outcome or
authorization bypass. Preserve multiple pending source/request observations
or design a reservation across acceptance; require an explicit two-request,
retry and crash-between-record/acceptance scenario before integration approval.

The network await inside the outer admin DB transaction is pre-existing in
origin/main; record bounded-timeout/pool-pressure behavior as an inherited risk,
not a newly introduced dirty-diff defect. No product fix was made in this audit.

No integration merge or deletion has been performed by this rebaseline pass.


## Additional adapter/testbed and S15/S16 follow-ups

- AT-01: capability-semantic 422 refusals must not increment the sidecar upstream circuit counter; verify valid reads remain available after repeated unsupported-capability requests.
- AT-02: exporter must stage/validate before publishing its final output; interruption/retry must not leave an unretryable final destination. Preserve existing outputs.
- S15: implement and qualify concrete authenticated reader/full-population ports; pure logic and historical synthetic passes already exist and must not be rewritten as absent.
- S16: implement/qualify durable atomic ChangeStore and cross-process restart/replay guarantees; bounded process-local fake-backed acceptance remains preserved.

Details and inspected paths: ADAPTERS_TESTBED_AUDIT.md and S15_S16_AUDIT.md.
