# Decision log

## 2026-10-06 - Disposable local E2E environment (branch e2e/local-environment)

- Decision: gateway, Fake1C and the test IdP run as host processes (uvicorn from the worktree
  venv); only PostgreSQL 16 and Redis 7 run in compose project `erpmcp-e2e`. Rationale: identical
  issuer/audience URLs for browser and gateway, trivial stop/start fault injection; the
  production gateway image is already built and scanned in CI.
- Decision: secrets are generated randomly once under the git-ignored `.e2e/`; the test IdP is
  the only place identities live. ERP_MCP gained no user-creation path and no 1C write path.
- Evidence: see docs/E2E_ENVIRONMENT.md and the commit history of this branch.
