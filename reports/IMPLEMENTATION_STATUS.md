# ERP_MCP implementation status

Last updated: 2026-10-05

## Bootstrap

- Repository: `https://github.com/xLZDx/ERP_MCP`
- Local path: `D:\Repo\ERP_MCP`
- Active branch: `bootstrap/1c-day1-production`
- Base: `origin/main` at `a6bb75294578067fb23792f4dd2ceb8f17ddf673`
- Working HEAD: `3acd006d5fb116d5ae29236a8d8e8e40f9d74b33` (pytest path fix and status update in progress)
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
- In progress: P1 security-negative tests and CI rerun. CI run `37355290036` passed lint, Bandit,
  compile, migrations and PostgreSQL role privilege checks; pytest collection failed on Linux
  because repository-root imports were not configured. `pyproject.toml` now adds root/src to
  pytest's import path; local clean-environment rerun passes.
- Next: verify fresh-PostgreSQL migrations/role grants, then continue the remaining P1 closure.
- First unresolved gate: P1 / D3, D11 — company-scoped authorization, runtime privileges and audit
  contract are not yet proven against the normative data model.
- Local checks: 42 passed, 1 skipped; Ruff, compileall, Bandit and pip-audit pass. PostgreSQL
  migration/role integration is delegated to CI for this batch.
- CI: latest run for `3acd006` is `37355290036` (failed at pytest collection, PostgreSQL steps passed).
  Awaiting the rerun on the import-path fix. Latest earlier successful run is
  `37349236860` on `c4d5a0e7173c208a4103b9feebe2ab8b26898d68`; later runs on this branch include
  failures before that success.
- Local environment: isolated `.venv` installed from `.[dev]`; Python, GitHub CLI and Docker engine
  available. Existing containers/databases were left untouched.
- Real 1C evidence: none recorded. L2/L3 availability not yet determined.
- External blockers: production IdP/secrets/deployment and real 1C pilot evidence remain unverified.
- Readiness: `DEV READY` for the existing bootstrap code/documentation only; no production claim.
