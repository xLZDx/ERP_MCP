# Admin Control Center — current branch status

Branch: `feature/admin-control-center-implementation`
Worktree: `D:\Repo\ERP_MCP-admin-control-center`
Admin start SHA: `dff4c81d18e645fed64aed50d148ab8df9109f66`
Integration baseline: `c07127fc2d7db40db4ad83678e1a9e9ad0957d99`
Final Admin SHA: `f15bac2cf7fba861352719ab9f17bf2ed7f28486`.
Hosted CI run `37510077711` passed all four jobs (test, Windows privacy, OData upstream, release-evidence) on the final merged tree. Earlier runs `37509438929`, `37507319003`, `37504428513`, and `37504580327` also passed their respective final corrections.

## Verified Admin scope

- Migration lineage preserves integration migrations 001–009 and adds Admin migrations 010–013 with immutable name/checksum identity and pre-DDL rejection of unknown, ahead-of-code, gapped, and ambiguous legacy histories.
- Disposable PostgreSQL acceptance covered fresh 001–014, integration v9 upgrade, legacy Admin v11 refusal without mutation, future v15 refusal without mutation, and old Admin v8/v9 refusal without ledger mutation. Privilege policy passed for the pre-observation-boundary Admin branch; the combined v14 privilege rerun is part of the current closure CI.
- Real ASGI/PostgreSQL/Redis B2 exercised all seven required cross-source mutation routes; each returned 403 with unchanged target/policy state and no successful mutation audit.
- All eight required security mutants were killed by targeted tests.
- OAuth scope validation, explicit platform/source role scope, expiry API/CLI handling, exact-ID authorization, and company deny policy have regression coverage.
- Admin UI browser contract passed for navigation, retry/idempotency, CSRF, escaping, dialog focus, narrow layout, and 200% zoom. Same-origin external JS permits `script-src 'self'`.
- Locked dependency install, Ruff, compileall, migration validation, report-reference validation, and pip-audit passed. Bandit follows the repository CI command `uv run --locked bandit -q -r src`; repository-wide default Bandit also reports existing low/medium findings in scripts, with no high findings.

## Latest observed full-suite run

Before the final integration-only update, `uv run --locked pytest -q` against disposable PostgreSQL/Redis completed **1127 passed, 6 skipped** in 170.08s. The subsequent Windows run after integration added 1149 passed and 6 skipped but hit 6 local `STATUS_INSUFFICIENT_RESOURCES` subprocess failures; hosted CI for the exact final SHA passed its full test job. Six skips are environment-gated external evidence/integration fixtures. Admin PostgreSQL/Redis B2 ran rather than skipped. Playwright Admin UI browser contract passed. `pip-audit` found no known vulnerabilities.

## Review consensus

Local Luna-medium second-round reviewers: security confirmed the remediations; database confirmed migration and privilege gates; architecture confirmed CI/browser/B2 coverage, reviewed the restore-drill fix, and found an adjacent capability-registry drill import regression. That caller now uses the identity-aware runner; its import smoke check passes. No remaining Admin-specific blocker was reported. Runtime checks were independently run locally against disposable services.

## Readiness

Admin Control Center: **READY for merge review.**
Production decision remains **NO-GO**. No main merge or production action is authorized or performed.
