# Decision log

## 2026-10-06 - Disposable local E2E environment (branch e2e/local-environment)

- Decision: gateway, Fake1C and the test IdP run as host processes (uvicorn from the worktree
  venv); only PostgreSQL 16 and Redis 7 run in compose project `erpmcp-e2e`. Rationale: identical
  issuer/audience URLs for browser and gateway, trivial stop/start fault injection; the
  production gateway image is already built and scanned in CI.
- Decision: secrets are generated randomly once under the git-ignored `.e2e/`; the test IdP is
  the only place identities live. ERP_MCP gained no user-creation path and no 1C write path.
- Evidence: see docs/E2E_ENVIRONMENT.md and the commit history of this branch.

## 2026-10-07 - E2E test scaffolding

- Decision: tests/e2e is auto-skipped only when .e2e/env.json is absent and ERP_MCP_E2E_NO_SKIP is unset; scripts/e2e/test.ps1 sets it so a missing environment is an error.
- Evidence: 12 smoke tests green against the live environment (tests/e2e/test_smoke_environment.py).

## 2026-10-07 - Data-plane User E2E suite U01-U18 (branch e2e/user-flows)

- Decision: Fake1C (testbed/fake1c/app.py) now records every request (method, path, user agent,
  numeric $top/$skip, credentials-present flag; no header values) at `/__ft__/requests`, the same
  shape as the Functional Tester recorder, so U04/U06/U11/U13/U14 can prove "only GET/HEAD" and
  "no upstream request on denial". The fake also honours `$select`/`$skip` like real OData.
- Finding (needs GPT-PM contract clarification): the baseline seed grants UC1 a company-one grant
  only, but source-level tools (source_health, onec_*) require a source-wide grant in the registry
  (`g.company_id IS NULL`), and a source-wide grant also covers company two. U02-U04/U11-U14 therefore
  run under a temporary source-wide grant created/revoked through the Admin API; U05-U10 use the
  baseline company-scoped grants. The denial under the company-only grant is asserted explicitly.
- Evidence: collect-only and ruff clean; not yet executed (environment owned by lane A).
- U05-U10 written under the baseline seed. Company row-content assertions skip with the explicit reason `BLOCKED-no-validated-semantic-profile` (a validated profile needs native reconciliation evidence, intentionally not faked); access decisions are proven by the `ACCESS_AUTHORIZED` audit receipt and the Fake1C request log. U08 removes the group at the IdP by editing the git-ignored `.e2e/idp-config.json` and restarting the test IdP, restoring the original bytes in `finally`.
- U11-U18 written. Outage rows (U14-U16) use scripts/e2e/fault.ps1 inside `outage()` whose `finally` always restarts the component; recovery is polled on an observable condition (a successful call), the gateway is never restarted. Observed contract recorded in the tests: with Redis down the rate-limited source/company tools fail closed while system_status/sources_list (no limiter) keep working; onec_read bounds rows by clamping `$top` to max_rows and exposes no truncation flag. U18 runs `pytest tests/functional` with FT_* wired from .e2e/env.json, or skips with `FT-suite-not-merged`.
- Lint-only follow-up: removed an unused noqa in testbed/fake1c/app.py (ruff RUF100).
- 2026-10-07 acceptance: clean up/status/smoke/reset/smoke/up/fault/down all executed; service launch changed to cmd.exe ShellExecute so callers reading output pipes do not hang. check_document_consistency reports a stale engineering checkpoint (implementation fingerprint covers scripts/tests/testbed); refresh is left to the integrator after merge.
