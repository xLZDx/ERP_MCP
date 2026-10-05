# ERP_MCP implementation status

Last updated: 2026-10-05

## Bootstrap

- Repository: `https://github.com/xLZDx/ERP_MCP`
- Local path: `D:\Repo\ERP_MCP`
- Active branch: `bootstrap/1c-day1-production`
- Base: `origin/main` at `a6bb75294578067fb23792f4dd2ceb8f17ddf673`
- Working HEAD: `e60ce7c73fb2474b672e020e17d5d88e4f86bf35` (includes current `origin/main`)
- PR: [#1 — Bootstrap 1C Day-1 production MCP gateway](https://github.com/xLZDx/ERP_MCP/pull/1), OPEN
- Worktrees: only `D:/Repo/ERP_MCP`
- Existing local additions from workspace setup: `AGENTS.md`, `CLAUDE.md`, `CODEX.md`,
  `CONTRIBUTING.md`, `SKILLS.md`; preserved.

## Delivery status

- Current phase: P1 control-plane closure.
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
- Next: close remaining P1 evidence, especially runtime-role connection-level tests, audit
  immutability/provenance integration, and scoped enforcement in an actual business-data adapter.
- First unresolved gates: P1 / D3, D11 — runtime-role behavior, end-to-end company-filtered data
  access, and persisted audit contract are not fully proven against the normative model.
- Local checks at HEAD: 42 passed, 2 skipped (PostgreSQL-only test skips without the CI DB URL);
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
