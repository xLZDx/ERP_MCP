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
- Evidence: batches so far (A01-A54) collect cleanly and are ruff-clean; executed next against the live environment.
- 2026-10-07 acceptance: clean up/status/smoke/reset/smoke/up/fault/down all executed; service launch changed to cmd.exe ShellExecute so callers reading output pipes do not hang. check_document_consistency reports a stale engineering checkpoint (implementation fingerprint covers scripts/tests/testbed); refresh is left to the integrator after merge.
- Finding (live run 1, 62 passed / 20 failed): Admin UI inline onclick handlers are blocked by the page CSP script-src self, so Create grant, Sign out, dialog Submit/Cancel and Retry do nothing in a real browser; tests isolate this in test_A45_ui_actions_are_not_blocked_by_the_page_csp and open dialogs programmatically for other rows.
- Finding: profile validation cannot succeed locally without register-capability evidence (no sidecar): CAPABILITY_UNSUPPORTED; validation-success tests report this as an environment limitation.
- Evidence (live, seed bootstrap-only, two consecutive full runs from a reset environment): 76 passed / 12 failed / 12 deselected(smoke) in 459s and 528s with an identical failure set; every failure is a strict product-defect or environment-limitation test (audit gaps A01/A03/A16, broken metadata accepted A39, inline onclick blocked by CSP A45/A49, focus loss A46, same-dialog retry 409 A50, no register-capability evidence A06/A40).
