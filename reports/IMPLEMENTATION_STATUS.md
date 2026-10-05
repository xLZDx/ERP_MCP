# ERP_MCP implementation status

Last updated: 2026-10-05

## Bootstrap

- Repository: `https://github.com/xLZDx/ERP_MCP`
- Local path: `D:\Repo\ERP_MCP`
- Active branch: `bootstrap/1c-day1-production`
- Base: `origin/main` at `a6bb75294578067fb23792f4dd2ceb8f17ddf673`
- Implementation assessed through CI-tested commit `77a12389dd3e437ef54c173d6581232bcad8cff8`
  (includes current `origin/main`; subsequent status-report commit is documentation-only)
- PR: [#1 — Bootstrap 1C Day-1 production MCP gateway](https://github.com/xLZDx/ERP_MCP/pull/1), OPEN
- Worktrees: only `D:/Repo/ERP_MCP`
- Existing local additions from workspace setup: `AGENTS.md`, `CLAUDE.md`, `CODEX.md`,
  `CONTRIBUTING.md`, `SKILLS.md`; preserved.

## Delivery status

- Current implementation phase: P2 capability-router drift lifecycle; P1 residual gates remain open.
- Completed: repository state recovered; origin fetched; local branch fast-forwarded; supplied
  engineering command center copied to repository root; normative package rechecked; P0–P9 and
  D0–D18 initial gap analysis written; additive company-scope/audit schema and control-plane work
  implemented with admin commands, scoped list/resolve methods, migration-history guard and CI DB
  privilege checker.
- Completed this batch: JWT security-negative tests; company ACL precedence and revocation
  PostgreSQL integration test; CI import-path correction.
- CI run `37355521467` on `1912314c055c4253bca38424f08393178f25c774` passed all workflow steps,
  including fresh PostgreSQL migrations, actual role privilege checker, pytest and pip-audit.
- CI run `37355876333` passed on HEAD `3be80d981da03820e0b5bdc38dfd18fc7d26b070`, including the
  new PostgreSQL-backed registry ACL test: `43 passed, 1 skipped`.
- Current branch includes the later `main` README update; both resulting CI runs passed
  (`37356469102`, `37356471488`). CI run `37356701516` on `1590b89` passed the runtime-role SQL
  integration test and the full workflow: `44 passed, 1 skipped`.
- CI run `37357024926` on `da7a25ea453e776d5f46cdefee9673e244ca2d94` passed the real
  `Audit.write` → PostgreSQL provenance round-trip under `business_ai_app`: `44 passed, 1 skipped`.
- CI run `37357432914` passed for the PostgreSQL `business_ai_admin` transaction test, proving
  allowed source/company/grant management and denied audit insertion/source deletion:
  `45 passed, 1 skipped` across the workflow.
- Next: verify full audit provenance on success/denial paths (the CI round-trip currently exercises
  one error event), and implement company-scoped authorization through an actual business-data
  adapter without weakening existing fail-closed behavior.
- First unresolved gates: P1 / D3, D11, D14 — end-to-end company-filtered data access, complete
  persisted audit contract across all request outcomes, and Redis failure behavior in integration
  remain open.
- Local checks for the latest implementation changes: 42 passed, 4 skipped (PostgreSQL-only tests skip
  without the CI DB URL);
  Ruff, compileall, Bandit, pip-audit and `git diff --check` pass.
- Previous CI collection failure `37355290036` on `3acd006` is superseded by green import-path fix
  run `37355521467`; latest earlier success remains `37349236860`.
- Local environment: isolated `.venv` installed from `.[dev]`; Python, GitHub CLI and Docker engine
  available. Existing containers/databases were left untouched.
- Real 1C evidence: none recorded. L2/L3 availability not yet determined.
- External blockers: production IdP/secrets/deployment and real 1C pilot evidence remain unverified.
- PR #1 had diverged from the updated `origin/main` by its README change; the latest main commit
  `a6bb75294578067fb23792f4dd2ceb8f17ddf673` has now been merged locally into the branch to resolve
  the PR conflict. The merge commit is pushed after report synchronization; merge itself remains
  intentionally unperformed.
- Readiness: `DEV READY` for the implemented bootstrap/control-plane scope only; no production claim.
