# Phase 2 evidence matrix

Single source for exact SHAs, run results and superseded records. Other status documents link here instead of repeating results. Append a row per measured run; never edit a past row except to mark it superseded.

Environment of all rows: Windows, `D:\Repo\ERP_MCP-phase2`, project venv, no CI (operator decision 2026-10-08). PostgreSQL: disposable docker container `erp-phase2-test-pg` (postgres:16-alpine, 127.0.0.1:55712, no volume), isolated from the Release 1 containers.

| Date | Tree / SHA | Command | Result | Status | Superseded by |
| --- | --- | --- | --- | --- | --- |
| 2026-10-08 | 9b4fc0c (checkpoint) | `pytest -q tests/phase2` | 133 passed | historical | row below |
| 2026-10-08 | worktree on 9b4fc0c, before commit 02bad1c | `pytest -q tests/phase2` | 310 passed, 20 skipped, exit 0 | measured | - |
| 2026-10-08 | worktree on 9b4fc0c | `ruff check src/business_ai_gateway/phase2 tests/phase2`, `compileall` | exit 0 | measured | - |
| 2026-10-08 | worktree before e71d4ff | `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` | 16 passed, 4 failed (wrong test expectations) | measured | next row |
| 2026-10-08 | worktree before e71d4ff | same, after test fixes | 20 passed | measured | - |
| 2026-10-08 | a8b5b4d (head under GPT-PM review) | `pytest -q tests/phase2` | 310 passed, 20 skipped, exit 0 | measured | - |
| 2026-10-08 | a8b5b4d | GPT-PM adversarial sweep | REJECT: 3 BLOCKER, 5 MAJOR | review | remediation batch |
| 2026-10-08 | worktree on a8b5b4d with the GPT-PM remediation batch (committed as the next commit) | `pytest -q tests/phase2` | 326 passed, 25 skipped, exit 0 | measured | - |
| 2026-10-08 | same tree | `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` on erp-phase2-test-pg | 25 passed | measured | - |
| 2026-10-08 | same tree | `ruff check src/business_ai_gateway/phase2 tests/phase2` | exit 0 | measured | - |
| 2026-10-08 | d3c3f60 | GPT-PM verification round | 7 of 8 FIXED, MAJOR-02 PARTIAL, VERDICT REJECT for push | review | next rows |
| 2026-10-08 | worktree on d3c3f60 with the MAJOR-02 revoke-barrier fix (committed as the next commit) | `pytest -q tests/phase2` | 326 passed, 49 skipped, exit 0 | measured | - |
| 2026-10-08 | same tree | `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` on erp-phase2-test-pg | 49 passed (24 new two-session revoke cases) | measured | - |
| 2026-10-08 | same tree | `ruff check src/business_ai_gateway/phase2 tests/phase2` | exit 0 | measured | - |
| 2026-10-08 | worktree on 8ff065f + G1 exit tests (committed as the next commit) | `pytest -q tests/phase2` | 326 passed, 65 skipped, exit 0 | measured | - |
| 2026-10-08 | same tree | `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` on erp-phase2-test-pg | 65 passed (16 new: restore 1, crash 5, guard mutations 10) | measured | - |
| 2026-10-08 | same tree | `ruff check src/business_ai_gateway/phase2 tests/phase2` | exit 0 | measured | - |
| 2026-10-08 | 9b4fc0c | six local Sonnet reviews + verification round | findings in DECISION_LOG.md D-001 | review | - |
| 2026-10-09 | a00d16a + remediation batch (committed as the next commit) | `pytest -q tests/phase2` | 904 passed, 217 skipped, exit 0 | measured | - |
| 2026-10-09 | same tree | `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` on erp-phase2-test-pg | 217 passed, exit 0 (65 G1 + 115 S1-S4 contract + 37 review additions) | measured | - |
| 2026-10-09 | same tree | `ruff check src/business_ai_gateway/phase2 tests/phase2` | All checks passed | measured | - |
| 2026-10-09 | a00d16a | four narrow reviewers (test adequacy, python, silent failure, reliability) | 0 BLOCKER, MAJORs fixed in one batch (D-009) | review | rows above |
| 2026-10-09 | d1f87bc + verification fixes (committed as the next commit) | `pytest -q tests/phase2` | 950 passed, 219 skipped, exit 0 | measured | - |
| 2026-10-09 | same tree | `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` on erp-phase2-test-pg | 219 passed, exit 0 | measured | - |
| 2026-10-09 | same tree | `ruff check src/business_ai_gateway/phase2 tests/phase2` | All checks passed | measured | - |
| 2026-10-09 | d1f87bc | verification round (regressions, test adequacy) | 0 BLOCKER, MAJORs fixed in one batch (D-010) | review | rows above |
| 2026-10-09 | 58edae1 (code head; evidence rows ride in the next doc-only commit) | `pytest -q tests/phase2` | 1030 passed, 219 skipped, exit 0 | measured | - |
| 2026-10-09 | 58edae1 | `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` on erp-phase2-test-pg (clean tree, head verified) | 219 passed, exit 0 | measured | - |
| 2026-10-09 | 58edae1 | `ruff check src/business_ai_gateway/phase2 tests/phase2` | All checks passed | measured | - |
| 2026-10-09 | 94e2605 | narrow code-reviewer on resnapshot / resume_revalidated / fairness tests | 0 BLOCKER, 2 MAJOR fixed in 58edae1 (D-013), mutation-checked | review | rows above |

## Guard mutation table (RED = guard removed in a throwaway database lets the forbidden action through; GREEN = baseline refuses it)

| Guard | Mutation | Mutant | Baseline |
| --- | --- | --- | --- |
| observations immutability trigger | DROP TRIGGER observations_immutable | RED | GREEN |
| outbox TRUNCATE guard | DROP TRIGGER outbox_no_truncate | RED | GREEN |
| observations TRUNCATE guard (FK closure) | drop every *no_truncate trigger | RED | GREEN |
| commit_cursor_page job fence | remove j_fence IS DISTINCT FROM p_fence | RED | GREEN |
| finish_job fence | remove fence=token from the UPDATE | RED | GREEN |
| living.recheck_scope_locked | empty the helper body | RED | GREEN |
| page-replay digest (CONFLICTING_PAGE_REPLAY) | remove the digest comparison | RED | GREEN |
| outbox claim_generation fence | remove the generation check | RED | GREEN |
| trusted-reviewer check in promote_head | remove the reviewer check | RED | GREEN |

Backup/restore: `pg_dump -Fc` of a populated database restored with `pg_restore --exit-on-error` into a second throwaway database; row digests of every living table, functions (prosecdef, proconfig, ACL, owner), policies, constraints, indexes, triggers, heads and sequences identical; a 40-item behaviour battery (immutability, role denials, bitemporal reads, cross-tenant and GUC-spoof denial, replays) gives identical outcomes. Crash: pg_terminate_backend (3 scenarios, no recovery cycle) and SIGKILL of the serving backend with postmaster crash recovery (2 scenarios); committed data survives, interrupted work leaves nothing, replay applies once. Not covered: a kill timed inside the instant of COMMIT, plain-format or -n living dumps, a PostgreSQL version matrix.
Not run (explicit): capacity 30/50/100/150 sources, mutation check of guards outside the table above, Release 1 regression, full-repo pytest/ruff, GitHub CI.

Statements elsewhere that SQL was "never executed" or PostgreSQL tests "NOT_RUN" describe 9b4fc0c and are superseded by the rows above.
