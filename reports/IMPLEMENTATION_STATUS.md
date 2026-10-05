# ERP_MCP implementation status

Last updated: 2026-10-05

## Bootstrap

- Repository: `https://github.com/xLZDx/ERP_MCP`
- Local path: `D:\Repo\ERP_MCP`
- Active branch: `bootstrap/1c-day1-production`
- Base: `origin/main` at `a6bb75294578067fb23792f4dd2ceb8f17ddf673`
- Implementation assessed through CI-tested commit `e3b1a17d026d15d0b4fe147d27649fef2c396912`
  (includes current `origin/main`).
- PR: [#1 — Bootstrap 1C Day-1 production MCP gateway](https://github.com/xLZDx/ERP_MCP/pull/1), OPEN
- Worktrees: only `D:/Repo/ERP_MCP`
- Existing local additions from workspace setup: `AGENTS.md`, `CLAUDE.md`, `CODEX.md`,
  `CONTRIBUTING.md`, `SKILLS.md`; preserved.

## Delivery status

- Current implementation phase: P3 pinned OData sidecar integration; P1 residual gates remain open.
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
- CI run `37358444084` passed migration 004 and the PostgreSQL sticky-drift/admin-ack lifecycle:
  `47 passed, 1 skipped`. The additional `onec_read` fail-closed gate is implemented locally and
  passed in CI run `37358947196` on `6af970d`: `49 passed, 1 skipped` across the full workflow.
- The pinned `hacker-cb/1c-odata` reference submodule is now initialized read-only at
  `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5` for the upcoming P3 reuse/integration work; no
  upstream code has been copied or modified.
- Added deterministic compatibility tests for both unsupported metadata discovery and explicit
  fallback selection. Targeted verification: Ruff passed; `tests/test_compatibility.py` passed
  (`4 passed`); the full hosted CI result is recorded below.
- CI run `37359877826` on `3c5cb6a` passed all workflow steps, including PostgreSQL migrations and
  privilege checks, Ruff, Bandit, compileall, pytest (`51 passed, 1 skipped`) and pip-audit.
- Added MCP-handler audit tests for success, ACL denial, Redis/rate-limit failure and adapter
  failure. All four pass locally; the suite verifies an ACL/Redis denial is persisted before any
  call reaches the 1C adapter. CI run `37360482223` passed on `7b29ab0`, including pytest
  (`55 passed, 1 skipped`) and every security/database workflow step.
- Added a P2 negative route test proving the configured-but-unimplemented HTTP/query fallback
  raises explicitly without making any network call. Full local checks: Ruff passed; pytest
  `52 passed, 5 skipped`; CI run `37360919808` passed on `e3b1a17`, including pytest
  (`56 passed, 1 skipped`) and the full workflow.
- Added a real Redis-client TCP outage test using a reserved local port; the rate limiter surfaces
  Redis connection/timeout errors rather than granting unmetered access. Local full suite: Ruff
  passed; `53 passed, 5 skipped`. CI run `37361430688` passed on `133f640`, including PostgreSQL
  checks, and pytest reported `57 passed, 1 skipped`.
- Validated the exact `hacker-cb/1c-odata` pin in an ephemeral Node 24.18.0 container: client and
  metadata packages built; client unit tests `428 passed, 1 skipped`; metadata unit tests `53 passed`.
  Added a dedicated CI job for this upstream preflight; its result is pending on the current change.
- P3 sidecar batch: added an isolated Node 24.18 sidecar built directly from pinned OData client
  SHA `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`, with query/keyed-get/count and constrained
  register reads, source host:port allowlisting, bearer authentication, request/response and row
  limits, timeout, per-source concurrency/circuit breaker, abort-on-disconnect and provenance.
  Python Settings/Runtime route detected JSON OData reads to it when paired source credentials are
  available; Atom/anonymous reads stay on the existing GET-only Python path. Register methods are
  checked against live per-EntitySet GET FunctionImports using the pinned metadata parser, and
  unconfirmed methods fail before the data request. Python suite: `61 passed, 5 skipped`; Ruff,
  compileall, Bandit and diff check pass. Sidecar tests: `9/9`, pinned client suite: `428 passed, 1
  skipped`, metadata suite: `53 passed`; Docker image builds and starts healthy as UID 10001 with no
  published port. Hosted CI with the new image smoke step is pending. This closes substantial P3
  implementation but not real-source parity, accounting semantics, company-scoped data reads, or
  production readiness.
- P3 batch is committed locally as `df492e2` on `bootstrap/1c-day1-production`. A fresh local
  CI-equivalent image smoke passed: health endpoint healthy, UID 10001, and no published ports.
  Push initially failed during a transient DNS outage, then succeeded; branch head `11337fe` is on
  the remote PR. Hosted CI run `37369006566`: gateway test job passed including migrations,
  privileges, pytest and pip-audit; `odata-upstream` remains queued on GitHub runners.
- P1 audit correlation: MCP server middleware now creates one context-local UUID per inbound
  message; `Audit.write` reuses it unless a caller explicitly supplies an ID. A regression test
  verifies same-request sharing and cross-request isolation, and confirms middleware registration.
  Local suite: `63 passed, 5 skipped`; Ruff, compileall and Bandit pass. Committed as `8cb1da9`
  and pushed with branch head `11337fe`; hosted `odata-upstream` CI is queued.
- Mandatory reuse audit re-read `docs/ADAPTER_CENSUS.md`, `docs/ADAPTER_INTAKE_PLAN.md`,
  `vendor/UPSTREAMS.md`, `vendor/intake.json`, ADR-0003 and inspected exact pinned OData register/key
  APIs and tests, Aprovodka read-side register/accounting sources, mcp-rsv-data COM/serve boundary,
  and GPL toolkit isolation boundary. The unsupported/unconfirmed `DrCrTurnover(s)` path is rejected;
  no second COM bridge or GPL-derived code is introduced.
- Capability-rule implementation batch (local evidence, not yet hosted-CI tested): migration 005
  persists a per-source register capability profile; both Python adapter and Node sidecar fail
  closed unless the exact source/register/method is confirmed by current metadata evidence. The
  sidecar revalidates its short-lived live-metadata profile immediately before invocation and
  returns `CAPABILITY_UNSUPPORTED` without guessing alternate names. Positive and negative
  DrCrTurnovers fixtures, internal request/response contract tests, and migration persistence tests
  are in place. Local verification: Python `67 passed, 5 skipped`; sidecar `11/11`; pinned upstream
  client `428 passed, 1 skipped`; pinned metadata `53 passed`; PostgreSQL integration `4 passed`;
  Ruff, compileall, Bandit and diff checks pass. Fresh image rebuild and runtime smoke pass at UID
  10001 with no published ports (`/healthz` 200). Upstream protocol implementation remains
  unchanged.
- Current batch is not yet on the remote branch. Previous hosted run `37369006566` has gateway
  PASS but the upstream job was queued; fresh hosted results are required for this capability batch.
- Next: verify full audit provenance on success/denial paths (the CI round-trip currently exercises
  one error event), and implement company-scoped authorization through an actual business-data
  adapter without weakening existing fail-closed behavior.
- First unresolved gates: P1 / D3, D11, D14 — end-to-end company-filtered data access, complete
  persisted audit contract across all request outcomes, and Redis failure behavior in integration
  remain open.
- Local checks before the route-selection tests: 45 passed, 5 skipped; after route tests: 47 passed,
  5 skipped; after audit-handler tests: 51 passed, 5 skipped; latest local suite: 52 passed, 5 skipped
  (PostgreSQL-only tests skip
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
