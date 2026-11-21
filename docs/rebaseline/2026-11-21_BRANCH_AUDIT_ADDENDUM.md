# Branch audit addendum — 2026-11-21

This addendum refreshes the 2026-11-20 branch audit after the RBF follow-up work. The earlier document remains the detailed candidate-by-candidate disposition; this file records the current ref/worktree boundary and fresh pull-request metadata without changing any branch or worktree.

## Ref snapshot

- `docs/rebaseline/2026-11-21_REF_CENSUS.json` records every ref returned by `git for-each-ref refs/heads refs/remotes` before this addendum commit: 102 refs total (68 local branch refs and 34 remote-tracking refs). SHA-256: `53742ded19f3dcd6c5267e949604683af261d25cd18ddf8c9adcf468aa68e3b8`.
- At ref-snapshot time, checkout `codex/rebaseline-status-20261120` was at `b11102849cbc0649ff45bccdc7b8d11a56495f05`, local `main` at `b8a2e2f59c4a054baf409dd2e29428ae64b4fc65`, and `origin/main` at `7916d16ed8da13ee0060fbe4072e173ea5d2bf35`.
- The RBF follow-up commits after the 2026-11-20 audit are classified as current audit/contract-test work, not product changes. Preserve the earlier per-ref patch dispositions; this ref census is a dated snapshot and does not authorize merge or deletion.

## Worktree snapshot

- `docs/rebaseline/2026-11-21_WORKTREE_CENSUS.json` records 45 registered worktrees, 18 dirty trees and 350 dirty path/status entries at its captured boundary. Compared with the 2026-11-20 census, there are zero added and 20 removed path/status tuples; the root checkout decreased from 23 dirty paths to three.
- A post-RBF-01 rescan is recorded in `docs/rebaseline/2026-11-21_WORKTREE_CENSUS_POST_RBF01.json` (SHA-256 `a0510eae6ff13a96a333a02947e79515e524b5a24cf463ddbf0e4a5829aba65`). It again found 45 trees and 18 dirty trees, with 355 dirty entries: five additions and zero removals against the earlier 11/21 scan. All five additions are root audit artifacts (`PROJECT_PLAN.md`, `core/DECISION_LOG.md`, `core/LESSONS_LOG.md`, this addendum and the ref census). The earlier three root entries belonging to the operator (`.gitattributes`, `.github/workflows/ci.yml`, and `reports/S10_RELEASE_EVIDENCE_MANIFEST.json`) remain untouched. The scan ran before writing its own snapshot file, so that file is not included in its own dirty-path list.
- Dirty paths remain owned by their listed worktrees. The census is evidence for triage only; it does not authorize cleanup or imply that a dirty tree is disposable.

The 350 path/status tuples in the first 11/21 scan were a subset of the 370 tuples from the 11/20 audited snapshot (zero additions, 20 removals). The five paths added by this addendum scan are its own root audit updates, so no new non-root dirty content appeared between scans. The prior audit's per-tree and per-candidate mapping remains applicable to all preserved non-root dirty content; the three operator-owned root entries are explicitly preserved above.

The preserved root workflow digest line matches candidate commit `ac97a979f814832fa2af8b22eda1e3a6f9480689`. Its sidecar Dockerfile runtime pin is already present on current `origin/main`; its five TC001 test-file changes only reorder imports. The single workflow config disposition remains as additional queue order 22. The untracked S10-named manifest is resolved as the historical S11 receipt-bound artifact by the exact hash/blob crosswalk in branch-audit review 14; it is not the distinct S10 candidate manifest and does not alter PR #65's accepted source line.

## Pull requests checked on 2026-11-21

- PR #41: `OPEN`, `merged=false`, `mergeable=false`; base `main` at `db30f968728c13ddabad6d6b11d8a9b03592ca63`, head `codex/erp-mcp-autonomous-2026-10-21` at `900a3d060c648b9a809a6b7094adb430fb60f0bd`.
- PR #42: `OPEN`, `merged=false`, `mergeable=false`; base `codex/erp-mcp-autonomous-2026-10-21` at `631e74812c37c4bd3b8c165b3dfb0eaf558cde85`, head `codex/s0-r2-tc001-compat-20261104` at `3b2bd0acb5a061f798c288b7671c9639f89e1269`.
- Both heads remain conflicting candidates whose broad tree diffs must not be merged wholesale. PR #41's bounded S1.1 migration is already present independently on current main. Preserve the refs and continue resolving candidate-specific commits against current source, accepted bounded evidence or backlog.

## Disposition

No refs, branches, pull requests or worktrees were merged, closed, reset or deleted by this refresh. The remaining audit work is criterion-level mapping of the preserved dirty worktree content and any unique branch commits not yet reconciled in `2026-11-20_BRANCH_AUDIT.md`.

## Subsequent rebaseline closeout — 2026-11-21

- GPT-PM approved the RBF-01–06 code/contract package at exact HEAD `2fdf8ee457891166b3d4a58c4741d7ddb1dcf8de`; PR #73 merged to `main` as `b991658159634553a48f7d21d4e0bd9b293aa1a4` after head and mergeability verification. The repository deleted the temporary remote topic ref after merge. The local `codex/rebaseline-status-20261120` branch remains available as an audit ref; no other branches or worktrees were removed.
- The merge did not include the three pre-existing root dirty items: `.gitattributes`, `.github/workflows/ci.yml`, and `reports/S10_RELEASE_EVIDENCE_MANIFEST.json`. They remain unstaged and must not be treated as part of the approved PR.
- RBF-01–06 project status is bounded accepted. RBF-06 evidence remains limited to two sequential disposable-database scenarios; true concurrent requests, retry, and crash-mid-operation behavior are not established.
- PR #41 and #42 remain open/conflicting at their audited historical heads and are not safe whole-tree merge candidates. Continue candidate-specific disposition from the existing audit rather than merge or delete those refs in bulk.

The report renderer was corrected to honor `active_sprint: none` after closeout instead of falling back to a historical ledger sprint. The regenerated dashboard now has no active-sprint task table until the next sprint is planned. This is reporting behavior only; it changes no harness state or product acceptance.
