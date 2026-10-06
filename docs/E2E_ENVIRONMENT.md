# Local E2E environment (disposable, localhost-only)

Snapshot: 2026-10-07. Automates sections 2 and 4 of
[QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md](QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md). Synthetic
Fake1C evidence only; this is never native 1C reconciliation. No real credentials: every secret
is generated randomly per environment and stored only in the git-ignored `.e2e/` directory.

## Architecture

| Component | How it runs | Host port (127.0.0.1 only) |
|---|---|---|
| PostgreSQL 16 | compose project `erpmcp-e2e` (`compose.e2e.yml`), volume `erpmcp-e2e-pgdata` | 15432 |
| Redis 7 (password) | same compose project, no persistence | 16379 |
| Fake1C | host process, `uvicorn testbed.fake1c.app:app` | 18766 |
| Test IdP | host process, `python -m testbed.idp` (`testbed/idp/`) | 18080 |
| Gateway + Admin UI | host process, `uvicorn business_ai_gateway.app:app` | 18000 (`/mcp`, `/admin/`) |

Gateway, Fake1C and the IdP run from the worktree venv so the issuer/audience URLs are identical
for the browser and the gateway (all `http://127.0.0.1:<port>`) and outages are injected by
stopping a process. The production gateway container image is already built and scanned in CI.
Processes log to `.e2e/logs/`, PIDs in `.e2e/pids/`, access logs are disabled (OIDC codes appear
in query strings).

Prerequisites: Docker Desktop (Linux containers), `uv`, PowerShell 5.1 or 7. The first `up.ps1`
creates `.venv` with `uv sync --locked --all-groups --extra dev`. Browser tests need Playwright
Chromium (`.venv\Scripts\python.exe -m playwright install chromium`).

Do not capture script output through a pipe that waits for EOF (for example `| tail`): the
detached service processes inherit the console handles. Redirect to a file instead.

## Commands (run from the worktree root)

```powershell
scripts\e2e\up.ps1 -Seed baseline        # idempotent: secrets, compose, roles, migrate (v14), verify, seed, processes
scripts\e2e\status.ps1 [-Json]           # per-component health, versions, schema version, bind addresses; exit 1 if unhealthy
scripts\e2e\test.ps1 -Suite smoke        # smoke | user | admin | all; -Skip <marker,...>; -PytestArgs ...
scripts\e2e\reset.ps1 [-Seed <mode>]     # drop schema, flush Redis, re-migrate, re-seed, restart gateway+IdP; same secrets
scripts\e2e\fault.ps1 -Component fake1c|redis|postgres|idp|gateway -Action stop|start|restart
scripts\e2e\open-user-client.ps1 [-NoLaunch] [-ShowToken]
scripts\e2e\down.ps1 [-Purge]            # -Purge also removes the volume and .e2e/
. .e2e\env.ps1                           # load BAG_* / E2E_DIR into the current shell (contains secrets)
```

`test.ps1` sets `ERP_MCP_E2E_NO_SKIP=1`. Plain `pytest` auto-skips `tests/e2e` only when
`.e2e/env.json` is absent and that variable is unset.

## Seed modes (`-Seed`)

- `bootstrap-only`: exactly one platform administrator binding, subject `platform_admin`, role
  `PLATFORM_ADMIN`, created with `scripts/admin.py platform-role-add` over
  `BAG_ADMIN_DATABASE_URL`.
- `baseline` (default): bootstrap-only plus source `fake1c-e2e`
  (`http://127.0.0.1:18766/odata/standard.odata`, secrets from env `FAKE1C_USERNAME`/`FAKE1C_PASSWORD`),
  companies `00000000-0000-0000-0000-000000000001` (default) and `...0002`, a subject grant for
  `user_company_one` on company one and a group grant for `erp-company-two-readers` on company
  two. Nothing for `user_no_access`.
- `none`: empty schema (no administrator; Admin API denies everyone).

Everything else (other roles, further sources, grants) is created through `/admin/`. Changing the
mode of an existing environment requires `reset.ps1 -Seed <mode>`. The Admin source probe allowlist
is only `127.0.0.1:18766` (CIDR `127.0.0.1/32`), so other hosts/ports stay rejected.

## Identities (passwords are only in `.e2e/credentials.json`)

| sub = username | groups | Intended use |
|---|---|---|
| user_company_one | erp-company-one-readers | data plane, subject grant on company one |
| user_company_two | erp-company-two-readers | data plane, group grant on company two |
| user_no_access | none | data plane denial |
| platform_admin | erp-platform-admins | bootstrapped PLATFORM_ADMIN |
| source_admin | erp-source-admins | create roles via Admin E2E |
| access_admin | erp-access-admins | idem |
| profile_admin | erp-profile-admins | idem |
| auditor | erp-auditors | idem |
| admin_no_role | none | Admin denial (no binding) |

ERP_MCP is not an identity-provider admin system: users and groups exist only in the disposable
IdP, ERP_MCP binds subjects/groups to roles and grants.

## Test IdP contract

Issuer `http://127.0.0.1:18080/realms/erp-mcp-test`; discovery at
`<issuer>/.well-known/openid-configuration` (also RFC 8414 paths). RS256, `kid` = RFC 7638
thumbprint, key persisted in `.e2e/idp-signing-key.pem`. Authorization code flow requires PKCE
S256, `state`, and `nonce` with `openid`; `redirect_uri` is exact-match. Clients:

- `erp-mcp-admin-e2e` (confidential): audience `http://127.0.0.1:18000/admin`, scopes
  `openid profile erp_mcp:admin`, callback `http://127.0.0.1:18000/admin/callback`.
- `erp-mcp-data-e2e` (public, PKCE): audience `http://127.0.0.1:18000/mcp`, scopes
  `openid profile onec:read`, callback `http://127.0.0.1:18080/e2e/callback`.
- `erp-mcp-headless-e2e` (confidential, secret in `.e2e/secrets.json`): password grant for tests.

Tokens carry `iss sub aud exp iat nbf jti scope client_id azp sid auth_time acr groups`.
`acr` is `urn:local-test:basic`, or `urn:local-test:step-up` when `acr_values` asks for it and the
user re-authenticated; `prompt=login`, `max_age` and a missing step-up ACR force re-login.
Refresh tokens rotate (in memory; an IdP restart invalidates them). Logout:
`<issuer>/protocol/openid-connect/logout` (`id_token_hint`, registered
`post_logout_redirect_uri`). Login form fields: `#username`, `#password`, `#login-submit`.

Headless minting: `POST <issuer>/protocol/openid-connect/token` with `grant_type=password`,
`client_id`, `client_secret`, `username`, `password`, `scope`, `audience`, plus test-only `acr`,
`auth_age` (seconds in the past for `auth_time`) and `ttl` (token lifetime in seconds, <= 0
gives an already expired token). The `tests/e2e/conftest.py` fixture `idp.token(...)` wraps it.

## Test scaffolding

`tests/e2e/conftest.py` fixtures: `e2e_env`, `idp`, `mcp_client` (real MCP Streamable HTTP),
`tool_payload`, `admin_http` (cookie/CSRF aware, real OIDC redirect flow without a browser),
`admin_browser` (Playwright page signed in through the IdP UI; sync tests only), `db`
(admin/control role reads). Markers: `e2e`, `smoke`, `user`, `admin`.

## Troubleshooting

- `port ... held by a foreign listener`: another program uses one of 15432/16379/18080/18000/18766.
  Existing sibling containers (5432, 6379, 55432, 13080, 13089, 1483, 1486, 53461) are never touched.
- Service did not start: read `.e2e/logs/<component>.err.log`.
- `seed mode ... run reset.ps1`: `up.ps1 -Seed` differs from the stored mode.
- Gateway not ready: check `fault`-stopped Postgres/Redis (`status.ps1`), then `fault.ps1 ... -Action start`.
- Start over: `down.ps1 -Purge` then `up.ps1`.
