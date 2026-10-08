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
| 2026-10-08 | 9b4fc0c | six local Sonnet reviews + verification round | findings in DECISION_LOG.md D-001 | review | - |

Not run (explicit): backup/restore, kill -9 mid-page crash test, capacity 30/50/100/150 sources, mutation check of every guard, Release 1 regression, full-repo pytest/ruff, GitHub CI.

Statements elsewhere that SQL was "never executed" or PostgreSQL tests "NOT_RUN" describe 9b4fc0c and are superseded by the rows above.
