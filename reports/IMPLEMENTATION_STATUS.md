# ERP_MCP implementation status

Last updated: 2026-10-06

## Current authoritative state

- Active delivery branch: `phase/p4-inventory-movements` at `f4340b38945c783a357ce19caa3f34c49d7fdcd0`.
- PR #1 is merged. Draft PRs #2–#8 remain open; PR #8 carries the current P4 follow-up and is
  stacked on the P9 evidence-gate branch. No PR has been self-approved or merged by this agent.
- Hosted run `37415224776` on this head passed both jobs: PostgreSQL migrations, privilege checker,
  full pytest and pip-audit; pinned OData upstream tests and non-root sidecar image smoke. The
  preceding run `37415093193` exposed the SQL key-parameter type bug and its OData job passed.
- Latest local checks on `f85b716`: pytest `123 passed, 7 skipped`; Ruff, Bandit, compileall,
  pip-audit, scenario validation (12 synthetic scenarios), and `git diff --check` passed. The seven
  skipped checks require the hosted PostgreSQL privilege-test database.
- P4 now includes inventory movements, bounded accounting posting rows, cash movements, and
  persistent source-specific negative capability evidence. No unconfirmed EntitySet/property name
  is guessed; missing evidence denies with `CAPABILITY_UNSUPPORTED`.
- New local D7 hardening adds bounded metadata/capability cache freshness and invalidates cached
  fingerprints on source endpoint/credential-reference changes. Hosted run `37415523392` passed on
  this head: Python/PostgreSQL `125 passed, 1 skipped`; upstream client `428 passed, 1 skipped`,
  metadata `53 passed`, sidecar image smoke and pip-audit passed.
- Pilot validator remains `NOT_READY`; native 1C reconciliation has not been run. This is not a
  production-ready declaration. The historical bootstrap chronology below is retained as a log,
  not as the current branch/PR status.
- PR #1 is merged. Draft implementation PRs #2–#9 remain open for user review; no PR has been
  self-approved or merged.
- P4 follow-up PR #8 code head `f4340b3` passed hosted CI `37415523392`, including metadata cache
  expiry/drift regression, PostgreSQL capability evidence persistence, pinned upstream tests and
  non-root image smoke.
- D10 ACL follow-up PR #9 code head `6356005` passed hosted CI `37415897249`, including three-source
  company/group isolation and same-process source add/revoke PostgreSQL integration. A later
  documentation-only commit updates the report and is undergoing normal branch CI.
- Pilot validator remains `NOT_READY`; native 1C accounting reconciliation and target deployment
  evidence are unavailable. No production readiness claim is made.
- Bootstrap chronology below is retained as historical execution log, not current branch/PR status.

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

- Current implementation phase: P6 isolated RSV bridge boundary; P1/P4/P5 residual gates remain open.
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
- Capability-rule implementation batch (published as `e964e32`; hosted Python/database job passed,
  OData upstream job queued): migration 005
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
- Hosted run `37372360593` on `e964e32` has its Python/database/security job PASS and
  `odata-upstream` queued; duplicate run `37372364831` is still queued. The upstream job remains a
  gate.
- P4 semantic profile foundation is published in commit `25228d6`: pinned Aprovodka preset
  identities are advisory only; migration 006 stores source/company-scoped profiles and mappings
  with upstream and metadata/capability/profile fingerprints. Runtime role is read-only. Ten
  distinct passing native-report reconciliation cases permit `VALIDATED`; metadata fingerprint
  drift atomically marks validated profiles `STALE`. Local full suite `73 passed, 6 skipped`;
  disposable PostgreSQL migrations 001–006, privilege checker and integration suite `5 passed`;
  Ruff/compileall/Bandit pass. No canonical semantic tools or real native reconciliation are claimed.
- Hosted run `37373981422` on `5d8172e` passed both `test` and `odata-upstream`, including the
  capability-rule and migration-006/profile-foundation code in its tested ancestry. Earlier
  duplicate runs were superseded/cancelled by the newer same-branch workflow.
- P4 operator lifecycle is published in `5f7061d`: `scripts/semantic_profiles.py` creates candidate profile
  versions, adds mappings, validates or retires them; each action is append-only logged by migration
  007. Validation checks exact metadata/capability fingerprints and current register dependencies,
  plus >=10 distinct passing native-report references. Local suite `74 passed, 7 skipped`;
  disposable PostgreSQL 001–007/privilege checker/integration `6 passed`; Ruff/compileall/Bandit pass.
  Pip-audit reports no known vulnerabilities. Hosted run `37375030150` passed both CI jobs. Real
  configuration-specific semantics remain unvalidated.
- P4 semantic read tools are in draft PR #2; inventory movements are in follow-up draft PR #8,
  stacked on P9 because real native reconciliation remains an external gate. Migration 008
  adds auditable explicit mapping confirmation and stales validated profiles after direct mapping
  edits; migration 009 records the semantic profile fingerprint in audit events. The new
  `accounting_balance_and_turnovers`, `sales_documents`, `purchase_documents`, `inventory_balance`,
  `bank_balance`, `receivable_balance`, `payable_balance` and `inventory_movements` authorize the exact
  company first, load only validated company-scoped mappings, check current capabilities, compose
  company filters from reviewed mappings plus registry external references, and normalize canonical
  fields. Cash movement reads also require an exact source/company profile, live metadata and
  operator-confirmed direction literals. Sales/purchase document support passed hosted CI
  `37380789434`; inventory passed `37381909454`; bank passed `37382615109`. Current local full suite
  is 123 passed / 7 skipped;
  disposable PostgreSQL 16 migrations 001–009/privilege policy pass, integration 6/6, Ruff,
  compileall, Bandit and pip-audit pass. P4 follow-up PR #8 head `63d97d3` passed both hosted CI jobs
  in run `37387649827`. A/R and A/P tools expose point-in-time mapped
  balances only, not aging. Inventory movement rows are now source/company profile-mapped, timezone
  normalized, signed using confirmed Receipt/Expense literals, and denied if live metadata lacks the
  exact EntitySet. The profile-gated `accounting_posting_rows` listing checks the exact register and
  all selected/company fields against live metadata; it is not a complete trace or native report.
  Cash movement support and source-profile persistence of semantic capability denials are implemented
  locally but have not yet passed hosted CI. AR/AP aging,
  tax, posting amount semantics/full trace, and real native-report reconciliation remain open.
- P5 L1 testbed work is on `phase/p5-real1c-testbed`, stacked on P4 in draft PR #3. Fake1C loads a
  versioned deterministic seed including inventory and cash movement records and exposes semantic
  read fixture EntitySets; twelve scenario invariants are machine-checked, and synthetic results are
  explicitly barred from native-1C reconciliation evidence. Latest local suite: 121 passed, 7
  skipped; hosted CI run `37383877277` passed
  both jobs. Real L2/L3 seed import, snapshots and native reports remain external integration work.
- P6 is in progress on `phase/p6-rsv-bridge-boundary`, stacked on P5 in draft PR #4. The pinned
  MIT bridge is launched via the MCP SDK stdio client with one source-ID-bound config, a reviewed
  tool inventory, ping-only health/restart semantics and sanitized failures. Windows ACL/runbook
  added. No generic native query is proxied; company-scoped data routing and a real Windows/COM
  smoke remain open gates. Hosted CI run `37384482140` passed both jobs.
- P7 legacy 8.2 is deliberately deferred in draft PR #5: repository review found no named 8.2
  target or customer requirement. The GPL toolkit remains isolated-only; do not deploy it or
  copy/link it into core without a concrete target and a fresh license/security review. Hosted CI
  run `37384584340` passed both jobs.
- P8 protected HTTP metrics is in progress on `phase/p8-protected-http-metrics`, stacked on P7.
  It adds optional bearer-protected request counters, in-flight gauge and latency histograms with
  bounded labels. Hosted CI run `37384949997` passed both jobs. Full logs/traces/source telemetry,
  load tests, SBOM/deployment evidence and restore drills remain open.
- P9 is in progress on `phase/p9-pilot-evidence-gate`, stacked on P8. A strict privacy-safe
  evidence manifest and CI validator are added; the committed template is `NOT_READY` and the
  `--require-go` gate fails until exact-release artifacts and human approvals are verified.
  Production IdP, live 1C/native reports, target load/restore drills, real pilot users and release
  authority are not present in this environment.
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
