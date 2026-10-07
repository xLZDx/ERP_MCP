# ERP_MCP manual QA environment and acceptance guide

Snapshot: 2026-10-06. Target candidate: `integration/1c-mvp-production-candidate`.
This guide prepares local synthetic L1 testing and two separate manual suites.
Fake1C evidence is synthetic contract evidence; it is never native 1C reconciliation.
Automated setup of sections 2 and 4: see [E2E_ENVIRONMENT.md](E2E_ENVIRONMENT.md).

**Update 2026-10-07 (code evidence `8283403`).** The disposable environment, test-only OIDC IdP and
identities are now provisioned by `scripts/e2e/up.ps1` (see E2E_ENVIRONMENT.md). The two manual suites
have dedicated step-by-step packs: [MANUAL_ACCEPTANCE_USER.md](MANUAL_ACCEPTANCE_USER.md) and
[MANUAL_ACCEPTANCE_ADMIN.md](MANUAL_ACCEPTANCE_ADMIN.md). The automated equivalents pass locally
(User U01-U18 52, Admin A01-A54 87 + 1 declared EXTERNAL-GATE skip, Functional Tester SC01-SC12
73 passed / 3 skipped / 2 xfailed); owner manual acceptance remains PENDING and none of this is
native 1C or production evidence.

## 1. What is ready and what is needed

- L1: checked-in Fake1C seed and 12 scenario contracts; local development mode can use
  the fixed `development-local` principal.
- Database: local PostgreSQL and Redis from `compose.development.yml`.
- Admin UI manual login: needs a non-production OIDC test client issuing a distinct Admin
  audience/scope, a test user with an explicitly bootstrapped platform role, and a test
  `business_ai_control_api` credential. These are not checked into the repository.
- L2: needs a real, disposable file-mode 1C base and synthetic account; no Fake1C result
  substitutes for this level.
- L3: requires an approved server-mode environment and production-like dependencies.

Never enter customer data or production credentials into this local environment.
Do not expose its Postgres/Redis/Fake1C ports beyond the workstation.

## 2. Local L1 setup (PowerShell, Windows)

Run from the repository root. Prerequisites: Git, Docker Desktop with Linux containers,
Python 3.12+, `uv`, and Node.js only if using the optional MCP Inspector.

1. Select the prepared candidate and inspect the tree:

   ```powershell
   Set-Location D:\Repo\ERP_MCP-integration-candidate
   git status --short
   git switch integration/1c-mvp-production-candidate
   git pull --ff-only origin integration/1c-mvp-production-candidate
   ```

   Stop if `git status --short` shows changes you did not make or do not recognize.

2. Install locked dependencies and make a private development env file:

   ```powershell
   uv sync --locked --all-groups
   Copy-Item .env.development.example .env
   ```

   `.env` is ignored by Git. Keep all local-only secrets there or in the current
   PowerShell process; never paste them into tickets or commit them.

3. Start disposable local services:

   ```powershell
   docker compose -f compose.development.yml up -d postgres redis
   docker compose -f compose.development.yml ps
   ```

   Wait until both services report healthy. This file publishes ports on the local
   workstation for developer use. Do not use it on a shared or production host.

4. Create local login roles before applying migrations. Change the three sample
   passwords to unique random local values and keep the same values for the DSNs in
   step 5. The container's initial `business_ai` account is the local database owner.

   ```powershell
   docker compose -f compose.development.yml exec postgres psql -U business_ai -d business_ai -c "CREATE ROLE business_ai_app LOGIN PASSWORD 'LOCAL_ONLY_APP_PASSWORD'; CREATE ROLE business_ai_admin LOGIN PASSWORD 'LOCAL_ONLY_ADMIN_PASSWORD'; CREATE ROLE business_ai_control_api LOGIN PASSWORD 'LOCAL_ONLY_CONTROL_PASSWORD';"
   ```

   If these roles already exist in this disposable database, do not rerun `CREATE ROLE`;
   inspect them and rotate only through a controlled local procedure.

5. Set role-specific DSNs and synthetic Fake1C credentials in this PowerShell window.
   Replace the sample passwords with those created above:

   ```powershell
   $env:BAG_ENVIRONMENT = 'development'
   $env:BAG_DATABASE_URL = 'postgresql://business_ai_app:LOCAL_ONLY_APP_PASSWORD@localhost:5432/business_ai'
   $env:BAG_MIGRATION_DATABASE_URL = 'postgresql://business_ai:business_ai@localhost:5432/business_ai'
   $env:BAG_ADMIN_DATABASE_URL = 'postgresql://business_ai_admin:LOCAL_ONLY_ADMIN_PASSWORD@localhost:5432/business_ai'
   $env:BAG_ADMIN_CONTROL_DATABASE_URL = 'postgresql://business_ai_control_api:LOCAL_ONLY_CONTROL_PASSWORD@localhost:5432/business_ai'
   $env:BAG_REDIS_URL = 'redis://localhost:6379/0'
   $env:FAKE1C_USERNAME = 'synthetic-user'
   $env:FAKE1C_PASSWORD = 'synthetic-password'
   ```

   These DSNs are intentionally local only. The migration connection uses the owner;
   the gateway uses the least-privilege runtime login. Admin web mutations use the
   dedicated control API login.

6. Apply and inspect migrations:

   ```powershell
   uv run --locked python scripts/migrate.py
   uv run --locked python scripts/verify_schema.py
   uv run --locked python scripts/check_db_privileges.py
   ```

   Expected schema is version 14. Fix any role/grant failures before continuing.

7. Start Fake1C in its own PowerShell window:

   ```powershell
   Set-Location D:\Repo\ERP_MCP-integration-candidate
   uv run --locked uvicorn testbed.fake1c.app:app --host 127.0.0.1 --port 8766
   ```

   Verify that `http://127.0.0.1:8766/odata/standard.odata/$metadata` returns XML.
   The service reads the deterministic fixture at `testbed/fake1c/fixtures/seed.json`.

8. Register the synthetic source, company, and development-user grant from another
   PowerShell window. Use `business_ai_admin` credentials through
   `BAG_ADMIN_DATABASE_URL` for these CLI setup commands:

   ```powershell
   Set-Location D:\Repo\ERP_MCP-integration-candidate
   $env:BAG_ADMIN_DATABASE_URL = 'postgresql://business_ai_admin:LOCAL_ONLY_ADMIN_PASSWORD@localhost:5432/business_ai'
   uv run --locked python scripts/admin.py source-upsert --source-id fake1c-local --display-name 'Fake1C synthetic' --base-url 'http://127.0.0.1:8766/odata/standard.odata' --username-secret FAKE1C_USERNAME --password-secret FAKE1C_PASSWORD --allow 'Catalog_*' 'Document_*' 'AccumulationRegister_*'
   uv run --locked python scripts/admin.py company-upsert --company-id 00000000-0000-0000-0000-000000000001 --source-id fake1c-local --external-ref 00000000-0000-0000-0000-000000000001 --display-name 'Synthetic organization one' --default
   uv run --locked python scripts/admin.py company-upsert --company-id 00000000-0000-0000-0000-000000000002 --source-id fake1c-local --external-ref 00000000-0000-0000-0000-000000000002 --display-name 'Synthetic organization two'
   uv run --locked python scripts/admin.py grant-add --kind subject --principal development-local --source-id fake1c-local
   ```

9. Start the gateway in another PowerShell window with `BAG_DATABASE_URL` set to the
   `business_ai_app` DSN from step 5:

   ```powershell
   Set-Location D:\Repo\ERP_MCP-integration-candidate
   $env:BAG_ENVIRONMENT = 'development'
   $env:BAG_DATABASE_URL = 'postgresql://business_ai_app:LOCAL_ONLY_APP_PASSWORD@localhost:5432/business_ai'
   $env:BAG_ADMIN_DATABASE_URL = 'postgresql://business_ai_admin:LOCAL_ONLY_ADMIN_PASSWORD@localhost:5432/business_ai'
   $env:BAG_ADMIN_CONTROL_DATABASE_URL = 'postgresql://business_ai_control_api:LOCAL_ONLY_CONTROL_PASSWORD@localhost:5432/business_ai'
   $env:BAG_REDIS_URL = 'redis://localhost:6379/0'
   $env:FAKE1C_USERNAME = 'synthetic-user'
   $env:FAKE1C_PASSWORD = 'synthetic-password'
   $env:BAG_OAUTH_ENABLED = 'false'
   $env:BAG_ADMIN_API_ENABLED = 'false'
   $env:BAG_ADMIN_UI_ENABLED = 'false'
   $env:BAG_ADMIN_MUTATIONS_ENABLED = 'false'
   $env:BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED = 'false'
   uv run --locked uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port 8000
   ```

   Check `http://127.0.0.1:8000/healthz` and `/readyz`; expected HTTP 200 and
   `{"status":"ready"}`. The local dev identity is fixed to `development-local`.
   It is not suitable for testing OAuth or production authorization.

10. Connect an MCP client to `http://127.0.0.1:8000/mcp`. For a temporary local
    browser client, run the MCP Inspector in a separate terminal using the project's
    current supported Inspector release and select Streamable HTTP. Keep its listener
    bound to localhost. Confirm the server lists tools before running User Suite A.

## 3. User manual suite (data-plane user)

Use only the local `development-local` identity for this suite. Do not use Admin routes
or setup credentials while recording user results. Save a result row for each case:
`Case | PASS/FAIL/BLOCKED | observed result | request/correlation ID | notes`.

1. **U01 — Discovery:** call `system_status`, `sources_list`, `companies_list`,
   `source_health`, `onec_capabilities`, `onec_metadata_summary`, and
   `onec_find_entities`. Confirm the registered Fake1C source is listed and the live
   metadata lists only the synthetic fixture entities.
2. **U02 — Bounded raw read:** call `onec_read` on `Document_Sales`, requesting only
   `Ref_Key`, `Number`, `Posted`, and `Amount`, with a small `top`. Confirm the two
   synthetic sales rows and no unrelated fields.
3. **U03 — Read-only boundary:** try a write verb through a direct OData URL only if
   the client exposes an explicit safe negative-test facility. Expect rejection and
   verify Fake1C data is unchanged. Never submit a mutation tool to the ERP_MCP server.
4. **U04 — Unsupported entity:** request a nonexistent entity through `onec_read`.
   Expect a sanitized unsupported/error response; no guessed alternative entity name
   should be queried.
5. **U05 — Source ACL denial:** ask the operator to revoke the exact
   `development-local`/`fake1c-local` grant. Repeat source discovery/read, expect denial
   before any Fake1C request; then have the operator re-add the grant.
6. **U06 — Company isolation:** with company-aware tools enabled by an approved
   validated synthetic profile, query organization one and organization two separately.
   Verify rows do not cross companies. Without that profile, expect
   `CAPABILITY_UNSUPPORTED`/profile denial and mark the case BLOCKED for the profile,
   not PASS.
7. **U07 — Scenario contracts:** check each of the 12 scenario invariants in
   `testbed/scenarios/accounting_scenarios.json` against the synthetic case result or
   the test report from the Functional Tester. The required IDs are listed in section 5.
   Synthetic fixture values do not establish real accounting correctness.
8. **U08 — Bounded results:** request more than the allowed row/response limit using
   safe read-only inputs. Confirm the response is bounded and explicitly signals
   truncation/limit behavior if the contract specifies it.
9. **U09 — Recovery:** stop Fake1C, repeat a safe read and record the sanitized failure;
   restart Fake1C and repeat. Confirm service recovers without restarting the gateway.
10. **U10 — Audit:** with operator assistance, inspect audit evidence for success,
    denied, unsupported, and upstream-error cases. Confirm caller/source/tool/outcome
    are present and tokens, credentials, and accounting payloads are absent.

## 4. Admin manual suite (different identity and permission set)

This suite requires a non-production OIDC provider. Use a dedicated Admin client with
an Admin audience different from the MCP data audience, `erp_mcp:admin` scope, local
callback URI, test subjects/groups, and the configured step-up ACR for role changes.
The test IdP and client credentials are environment-specific and are not stored here.
Do not run this suite with the development-local gateway from step 9. Stop it with
Ctrl+C, then start a separate gateway process in a new PowerShell window after replacing
the placeholders below with the test IdP's registered values:

```powershell
Set-Location D:\Repo\ERP_MCP-integration-candidate
$env:BAG_ENVIRONMENT = 'development'
$env:BAG_DATABASE_URL = 'postgresql://business_ai_app:LOCAL_ONLY_APP_PASSWORD@localhost:5432/business_ai'
$env:BAG_ADMIN_DATABASE_URL = 'postgresql://business_ai_admin:LOCAL_ONLY_ADMIN_PASSWORD@localhost:5432/business_ai'
$env:BAG_ADMIN_CONTROL_DATABASE_URL = 'postgresql://business_ai_control_api:LOCAL_ONLY_CONTROL_PASSWORD@localhost:5432/business_ai'
$env:BAG_REDIS_URL = 'redis://localhost:6379/0'
$env:BAG_PUBLIC_MCP_URL = 'http://127.0.0.1:8000/mcp'
$env:BAG_OAUTH_ENABLED = 'true'
$env:BAG_OAUTH_ISSUER = 'http://127.0.0.1:8080/realms/erp-mcp-test'
$env:BAG_OAUTH_AUDIENCE = 'http://127.0.0.1:8000/mcp'
$env:BAG_OAUTH_JWKS_URL = 'http://127.0.0.1:8080/realms/erp-mcp-test/protocol/openid-connect/certs'
$env:BAG_ADMIN_API_ENABLED = 'true'
$env:BAG_ADMIN_UI_ENABLED = 'true'
$env:BAG_ADMIN_MUTATIONS_ENABLED = 'true'
$env:BAG_ADMIN_OAUTH_AUDIENCE = 'http://127.0.0.1:8000/admin'
$env:BAG_ADMIN_OAUTH_REQUIRED_SCOPE = 'erp_mcp:admin'
$env:BAG_ADMIN_OIDC_AUTHORIZATION_URL = 'http://127.0.0.1:8080/realms/erp-mcp-test/protocol/openid-connect/auth'
$env:BAG_ADMIN_OIDC_TOKEN_URL = 'http://127.0.0.1:8080/realms/erp-mcp-test/protocol/openid-connect/token'
$env:BAG_ADMIN_OIDC_CLIENT_ID = 'erp-mcp-admin-test'
$env:BAG_ADMIN_OIDC_CLIENT_SECRET = '<test-only-client-secret-if-required>'
$env:BAG_ADMIN_OIDC_REDIRECT_URI = 'http://127.0.0.1:8000/admin/callback'
$env:BAG_ADMIN_STEP_UP_ACR_VALUES = 'urn:local-test:step-up'
$env:BAG_ADMIN_SOURCE_ALLOWED_HOSTS = '127.0.0.1:8766'
$env:BAG_SECRET_PROVIDER = 'env'
$env:FAKE1C_USERNAME = 'synthetic-user'
$env:FAKE1C_PASSWORD = 'synthetic-password'
uv run --locked uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port 8000
```

The example issuer, audience and ACR are placeholders; they only work if the test IdP
is configured to issue them. The Admin API requires the distinct audience and scope;
the browser flow also requires correct issuer, authorization/token endpoints, client
and callback registration. The IdP must issue signed step-up `acr` and recent
`auth_time` claims for sensitive platform-role changes. Keep client secrets in the
PowerShell process or a private local secret store, never in committed files. Enable
mutations only after the dedicated control API login role and exact test host allowlist
are provisioned.
Bootstrap one local test `PLATFORM_ADMIN` and one test `SOURCE_ADMIN` bound only to
`fake1c-local`; create separate `ACCESS_ADMIN`, `PROFILE_ADMIN`, `AUDITOR`, and no-role
users/groups if the IdP/operator permits. Keep production tenants and identities out.
Use `BAG_ADMIN_DATABASE_URL` and the operator CLI to create the initial local test
binding only after migration/privilege verification, for example:

```powershell
uv run --locked python scripts/admin.py platform-role-add --kind subject --principal '<test-admin-subject-from-idp>' --role PLATFORM_ADMIN --created-by local-test-owner --reason 'Disposable local functional test setup'
```

Capture the returned binding ID for teardown. Revoke that exact binding after testing;
do not use broad SQL deletes or reuse a production administrator.

Run the following through `/admin/` in a browser, not via CLI, except setup and evidence
inspection. Record expected/actual HTTP status, UI state, request ID, and audit event ID.

1. **A01 — Login and session:** sign in as test Admin; verify `/admin/v1/me` returns the
   intended subject/role. Sign out and verify the old cookie cannot load protected data.
2. **A02 — Unauthorized identity:** try no session, expired session, wrong audience,
   wrong scope, and a data-plane-only user. Expect denial and no Admin data exposure.
3. **A03 — Role separation:** verify PLATFORM_ADMIN access; SOURCE_ADMIN is limited to
   its exact source; ACCESS_ADMIN manages only grants; PROFILE_ADMIN manages profiles;
   AUDITOR is read-only; no-role is denied. Try cross-source object IDs and confirm no
   mutation side effect.
4. **A04 — CSRF and browser token storage:** reject missing/invalid CSRF on cookie
   mutations; confirm session cookie is HttpOnly/Secure as configured and no access or
   refresh token is persisted in localStorage/sessionStorage.
5. **A05 — Source onboarding:** use the local Fake1C URL only when the test deployment's
   explicit development host allowlist permits loopback. Probe, inspect safe capability
   summary, then register the source. Reject URL userinfo, disallowed host, redirect,
   and secret-provider failure. Confirm credentials never appear in response or audit.
6. **A06 — Companies:** register both synthetic companies against the same source.
   Reject a company whose `source_id` does not match; verify duplicate external reference
   behavior is documented and deterministic.
7. **A07 — Grant lifecycle:** create a narrow test grant, replay the same idempotency key,
   then retry with a different payload and expect conflict. Revoke by exact grant ID and
   row version; stale version conflicts; runtime denial takes effect without restart.
8. **A08 — Policy composition:** verify data ACL, required business capability and
   validated source/company profile are each necessary. Explicit deny wins; unknown
   capability fails closed; role assignment cannot widen source/company ACL.
9. **A09 — Metadata/profile lifecycle:** refresh source metadata; confirm missing or
   failed metadata does not invent a fingerprint; unconfirmed register methods fail
   closed; stale acknowledgement/profile validation is rejected. Never guess register
   names or invoke unconfirmed virtual tables.
10. **A10 — Audit and least privilege:** inspect admin audit for actor, client, action,
    target, reason, request/idempotency key and safe outcome. Confirm neither app nor
    control API can update/delete audit history, and no token/secret/raw accounting rows
    are recorded.
11. **A11 — UI states and accessibility:** test keyboard navigation/focus, labels,
    200% zoom, narrow viewport, loading/empty/error/forbidden/conflict/stale states.
    Ensure status is not conveyed by color alone.
12. **A12 — Recovery:** take PostgreSQL, Redis, IdP/JWKS, secret provider, and Fake1C
    out of service one at a time only in the disposable test environment. Confirm clear
    fail-closed behavior, bounded response time, audit/metrics where specified, and
    recovery after the dependency returns.

Do not enable business capability enforcement or test semantic-profile validation using
fake native reports. These require a separately reviewed fixture profile for synthetic
contract testing; production profiles require ten passing native report references.

## 5. Scenario inventory for Functional Tester

All entries are declared synthetic contracts. Tester should author executable
black-box tests and map each to a user-visible tool/result where one exists. If no current
tool can represent a scenario, report `NOT IMPLEMENTED` and propose the smallest suitable
test harness; do not fabricate an API or mark it passed using arithmetic alone.

| ID | Scenario | Expected invariant |
|---|---|---|
| SC01 | `ar-overdue-30d` | `0 <= overdue_30d <= open_balance` |
| SC02 | `partial-payment` | `invoice_total - payments_applied = open_balance > 0` |
| SC03 | `overpayment` | invoice open is zero; unapplied advance remains positive and separate |
| SC04 | `unposted-document` | unposted document produces zero movements |
| SC05 | `return` | receipt quantity minus return equals on-hand quantity |
| SC06 | `vat-mixed` | standard plus exempt base equals total; treatments remain distinct |
| SC07 | `backdated-document` | document date maps to the correct accounting period |
| SC08 | `duplicate-counterparty` | two duplicate candidates; zero automatic merges |
| SC09 | `cash-bank` | cash and bank balances remain separate and sum to combined balance |
| SC10 | `account-turnover` | opening debit + debit turnover - credit turnover = closing debit |
| SC11 | `inventory-receipt-expense` | signed expense is negative; receipt minus expense = net quantity |
| SC12 | `cash-receipt-expense` | signed expense is negative; receipt minus expense = net amount |

## 6. Stop conditions and evidence handoff

Stop a case immediately if a request attempts a 1C write, crosses a company/source
boundary, exposes a credential/token, guesses an unsupported capability, or changes a
non-disposable database. Mark it FAIL, capture request/correlation ID and sanitized
evidence, and notify the owner.

Attach two distinct result sheets (User and Admin), tested commit SHA, environment
versions, Fake1C seed ID, migration version, role used, timestamps, and any blocked
external dependency. Redact tokens, passwords, company/customer names, and financial
payloads. Only the customer-approved L2/L3 reconciliation owner may mark native reports
PASS.
