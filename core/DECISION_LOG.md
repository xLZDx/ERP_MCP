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

## 2026-10-07 - Admin E2E suite A01-A54 (branch e2e/admin-flows)

- Decision: the Admin suite runs on seed mode bootstrap-only; source, companies, role bindings and grants are created through /admin/ by the `world` fixture (tests/e2e/admin/admin_support.py). The suite fails loudly (never skips) when the environment is not pristine.
- Decision: contract rows whose evidence the product does not currently produce (login/logout audit rows for A01, audit trail for 401 denials in A03/A04) are asserted strictly in their own tests so a failure is visible and classified, not weakened.
- Evidence: batches so far (A01-A37, A42) collect cleanly and are ruff-clean; not yet executed against the environment (lane A owns the ports).
- 2026-10-07 acceptance: clean up/status/smoke/reset/smoke/up/fault/down all executed; service launch changed to cmd.exe ShellExecute so callers reading output pipes do not hang. check_document_consistency reports a stale engineering checkpoint (implementation fingerprint covers scripts/tests/testbed); refresh is left to the integrator after merge.
