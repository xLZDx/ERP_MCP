# Admin Control Center — current branch status

Branch: `feature/admin-control-center-implementation`
Worktree: `D:\Repo\ERP_MCP-admin-control-center`
Admin start SHA: `dff4c81d18e645fed64aed50d148ab8df9109f66`
Integration baseline: `672fec4efae10949df0185c98e44b07b57ca45f3`
Previous hosted candidate: `da13f3af996df3801e0c12a6ba8b3c1c06e6a834`; CI run `37504428513` is in progress. It fixes the restore-drill issue from run `37502940204`.

## Verified Admin scope

- Migration lineage preserves integration migrations 001–009 and adds Admin migrations 010–013 with immutable name/checksum identity and pre-DDL rejection of unknown, ahead-of-code, gapped, and ambiguous legacy histories.
- Disposable PostgreSQL acceptance covered fresh 001–013, integration v9 upgrade, legacy Admin v11 refusal without mutation, v14 refusal without mutation, and old Admin v8/v9 refusal without ledger mutation. Privilege policy passed.
- Real ASGI/PostgreSQL/Redis B2 exercised all seven required cross-source mutation routes; each returned 403 with unchanged target/policy state and no successful mutation audit.
- All eight required security mutants were killed by targeted tests.
- OAuth scope validation, explicit platform/source role scope, expiry API/CLI handling, exact-ID authorization, and company deny policy have regression coverage.
- Admin UI browser contract passed for navigation, retry/idempotency, CSRF, escaping, dialog focus, narrow layout, and 200% zoom. Same-origin external JS permits `script-src 'self'`.
- Locked dependency install, Ruff, compileall, migration validation, report-reference validation, and pip-audit passed. Bandit follows the repository CI command `uv run --locked bandit -q -r src`; repository-wide default Bandit also reports existing low/medium findings in scripts, with no high findings.

## Latest observed full-suite run

After integrating integration tip `672fec4` and fixing restore-drill migration execution, `uv run --locked pytest -q` against disposable PostgreSQL/Redis completed **1127 passed, 6 skipped** in 170.08s. Six skips are environment-gated external evidence/integration fixtures; Admin PostgreSQL/Redis B2 ran rather than skipped. Playwright Admin UI browser contract passed on the merged tree. `pip-audit` found no known vulnerabilities.

## Review consensus

Local Luna-medium second-round reviewers: security confirmed the remediations; database confirmed migration and privilege gates; architecture confirmed CI/browser/B2 coverage, reviewed the restore-drill fix, and found an adjacent capability-registry drill import regression. That caller now uses the identity-aware runner; its import smoke check passes. No remaining Admin-specific blocker was reported. Runtime checks were independently run locally against disposable services.

## Readiness

Admin Control Center: **NOT READY pending green CI on the final pushed SHA.**
Production decision remains **NO-GO**. No main merge or production action is authorized or performed.
