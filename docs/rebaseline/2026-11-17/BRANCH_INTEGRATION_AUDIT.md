# Branch integration audit

Evidence date: 2026-11-17. All counts below were observed by the Git explorer.

| Reference | Observed state |
|---|---|
| Remote main | `7c1f69cf51b16d3849772fdb1e32015b17cb1aa7` (fetched and ls-remote agree) |
| Local main | `4dfceeddb071a63e7d8f815e7c276555de6d2375`: 0 ahead, 113 behind remote main |
| Active checkout | `240070b029ac020e895e9f84eb4bd02dd36b2e03`: 87 ahead, 9 behind remote main |
| Local branches | 63: 9 ancestor tips of origin/main, 54 non-ancestor tips |
| Remote refs | 40 |
| Worktrees | 47 |
| Original dirty root | 79 tracked changed paths, 2,209 untracked paths |

The active checkout's upstream divergence (59 ahead/70 behind) concerns a
different remote branch and must not be confused with origin/main divergence.

## Open PRs

| PR | Head | Base | Disposition |
|---|---|---|---|
| 58 | `9bd6d3840437a811db4f3f8ad7e12619e102c57b` | `codex/v2-s12-01-20261108` | Preserve; stacked on S12 |
| 54 | `2629aa2a20f6e40641a5ece7de42a1587a2748a1` | main | Reconcile S12 against current main |
| 42 | `3b2bd0acb5a061f798c288b7671c9639f89e1269` | autonomous branch | Preserve S0 compatibility delta |
| 41 | `900a3d060c648b9a809a6b7094adb430fb60f0bd` | main | Inspect actual GitHub base/head refs before integration; local tip differs |

PR facts were read via authenticated gh. None is assumed approved for the
current integration. `origin/pr-57` is not an open PR; state still needs checking.

## Integration order

1. Preserve dirty root changes and all refs externally (completed by coordinator).
2. Create an integration scratch checkout from fetched origin/main; do not merge
   into the dirty working checkout or overwrite stale local main.
3. Reconcile the autonomous branch's 87 unique commits and the 79 changed
   tracked paths, plus selected untracked implementation files. Group changes by
   requirement and compare patch equivalence before choosing cherry-pick or merge.
4. Reconcile S0 compatibility and S12 PRs, then S13 stacked PR. Preserve accepted
   bounded changes and resolve conflicts against current code, not old reports.
5. Compare all remaining non-ancestor tips by patch identity and file differences;
   retain rescue/archive/snapshot refs until their unique content is classified.
6. Route integrated code for review and permitted focused verification, obtain
   exact-head GPT-PM approval, push a single integration PR and merge that head.
7. Refresh main, then remove only branches/worktrees whose work is proven integrated.

## Cleanup classes

`BRANCH_INVENTORY.json` records every branch's SHA and ancestry/counts against
origin/main. PROTECTED means main/master/HEAD, never delete. MERGED_REVIEW_WORKTREE
means ancestry is proven but worktree contents and remote counterpart still need
checking. RETAIN_RECONCILE means unique ancestry exists, not necessarily unique
patches; it cannot be deleted on ancestry alone.

The nine merged local tips include main, archive/ERP_MCP-phase2-4-af2f36a1,
backlog/2026-10-21-final, codex/s11-lf-pointer-fix-20261109,
feature/admin-control-center-implementation, feature/chatgpt-mcp-integration,
integrate/2026-10-20, integration/1c-mvp-production-candidate and
phase/p6-rsv-bridge-boundary. Main is never a deletion candidate.

GitHub automatic merged-head deletion is now enabled and read back as true.
Local post-merge already invokes worktree_gc.py. Broader cleanup must verify
clean tracked/untracked state, classify ignored output, check process users and
outward junctions, and confirm main ancestry before deletion.

## Coverage limits

No patch-equivalence sweep for all 54 non-ancestor branches, per-worktree
cleanliness/process/junction proof or integration merge has completed yet.
No old branch/worktree was deleted. Branch inventory is a preparation artifact,
not evidence that all historical work has reached main.


## Completed follow-up measurements

PATCH_EQUIVALENCE.json now contains successful git-cherry comparisons for all 63 local branches; twelve have zero unique non-merge patches. WORKTREE_STATES.json covers all 47 original worktrees, with 19 dirty and 28 tracked/untracked clean. Process, ignored-file and outward-junction checks are still required before cleanup. PR57 was independently read as MERGED into main at 7c1f69c. These newer measurements supersede the earlier missing-sweep notes above.

Prepared integration checkout: D:/tmp/scratch_worktrees/erp-rebaseline-main-20261117, branch codex/rebaseline-main-20261117, based on origin/main 7c1f69c. This adds a 48th worktree after the preserved inventory. A read-only merge-tree preview of origin/main and 240070b returned exit 0; it excludes all uncommitted root changes and is not a completed integration merge. Detailed preview output stays outside Git.


## Main ref synchronization

After preservation and ancestry verification, git fetch origin main:main
fast-forwarded local main from 4dfceed to 7c1f69c. Both local main and origin/main
now resolve to 7c1f69cf51b16d3849772fdb1e32015b17cb1aa7. Historical inventory
rows retain the before-state intentionally. The prepared integration worktree
was clean before its subsequently recorded removal; the dirty root branch was not switched or merged.

S6/S8 PR merge commits 98b7405,5672c9c,e2ebf0e are present on the remote
integration branch but not origin/main. Their historical merge reports are true
for that line; this is a consolidation gap, not proof their work never existed.
TASK_EVIDENCE.json records main/integration reachability per recorded commit.


2026-11-17 cleanup follow-up: removed the empty prepared scratch worktree
D:/tmp/scratch_worktrees/erp-rebaseline-main-20261117 and deleted its temporary
codex/rebaseline-main-20261117 branch with git branch -d. Its tip was exactly
origin/main; ancestry verified, tracked/untracked status empty, no reparse points,
and no observable process cwd in the target. Process cwd could not be read for
198 protected/inaccessible processes; no such process was identified as using
the target. Git removal completed successfully. Main/master were retained.
The integration plan remains prepared; no code integration candidate was merged.
