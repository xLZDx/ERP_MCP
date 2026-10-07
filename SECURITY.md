# Security model

ERP_MCP is **read-only by construction** for the 1C Day-1 production MVP.

## Production invariants

- Production refuses auth-disabled mode.
- Production refuses environment-variable secret storage.
- Public MCP URL, issuer and JWKS must use HTTPS.
- MCP OAuth audience must equal the public MCP resource URL.
- 1C sources must have `read_only=true`.
- AI callers can pass only a registered `source_id`, never a host or URL.
- 1C redirects are disabled.
- The 1C transport implements GET/HEAD only; POST/PUT/PATCH/DELETE do not exist.
- EntitySet access is validated against live `$metadata` and source allow/deny policy.
- Company-scoped grants cannot authorize unscoped OData reads; company data operations require an
  adapter path that enforces the selected organization end-to-end.
- Active deny grants override matching allows.
- PostgreSQL audit events are append-only.
- Raw OData filters are not stored in audit by default.
- Runtime DB credentials cannot modify source registry or grants.
- Source credentials never appear in MCP results.
- External evidence is untrusted read-only input; it cannot change authorization/policy or trigger
  production 1C mutation.
- Raw private reference bases/documents/credentials/private Drive links never enter Git/public CI.
- Test-only Ferma/1C seed/write code and credentials are isolated from production MCP routes.
- Missing evidence never authorizes a guessed accounting/tax/payroll PASS.

## 1C service account

Use a dedicated technical user with the minimum read permissions and a restricted OData
composition. Never reuse an administrator account.

## Database privilege split

- `business_ai_owner`: migrations only.
- `business_ai_admin`: source/grant lifecycle.
- `business_ai_app`: runtime SELECT registry/grants + INSERT audit only.

## Network

Prefer placing the gateway near/private to 1C. Do not expose the 1C OData endpoint directly
to AI clients.

## Admin Control Center extension

The Admin Control Center is a distinct control-plane surface and does not inherit permission from the MCP data-plane scope.

Security invariants:
- admin OAuth audience and scope are distinct from the MCP data-plane audience/scope;
- browser sign-in uses OIDC Authorization Code + PKCE, state and nonce;
- the browser receives only an opaque HttpOnly SameSite session cookie; bearer tokens remain server-side in Redis and are revalidated on every admin API request;
- cookie-authenticated POST/PATCH requests require a per-session CSRF token;
- admin sessions cannot outlive the validated admin access-token expiration and also enforce idle/absolute TTLs;
- admin API requests share a subject-level Redis rate budget and fail closed if the limiter dependency is unavailable;
- platform-role create/revoke requires an approved step-up ACR and recent auth_time;
- admin mutations are disabled by default and require a separate business_ai_control_api database credential;
- every mutation requires actor, reason, request ID and idempotency key and writes append-only admin audit;
- exact-ID revocation is used for grants and role/policy assignments;
- source probes are GET/HEAD-only, require an explicit host plus optional CIDR egress allowlist, and connect to a validated numeric IP with the original Host and TLS SNI/certificate name. The probe has its own pool, four concurrent slots and a 45-second total deadline; production also requires network-level egress enforcement;
- secret values never enter Admin UI/API responses, audit events or registry rows;
- platform administration roles, data-scope grants and business capabilities are independent;
- business capability enforcement is fail-closed when enabled and never widens source/company scope;
- generic `onec_read` remains source-scoped. Company-aware access is limited to fixed canonical operations using validated semantic profiles. Admin company-scope mappings are candidate configuration and are not consumed by a runtime read route.

Production startup rejects a control DB session with superuser/owner/operator membership,
schema ownership, role-management rights, DELETE, mutable admin audit or broad drift UPDATE.
OIDC state consumption and session refresh are atomic; concurrent logout cannot recreate a session.
Company-aware reads reject navigation expansion and unbalanced caller-filter delimiters;
current live metadata is refreshed before applying a mapping.

Runtime credentials must also satisfy the app contract without administrative DML/elevated
membership. JWKS uses a five-minute set TTL, no indefinite per-key cache, and a ten-second
fetch deadline. Malformed/distributed-overage group claims deny. Connection/ref changes stale
validated profiles even with identical metadata. Delegated SOURCE_ADMIN cannot repoint
connections/refs. Mutation JSON rejects non-string company IDs and non-integer versions.

Production keeps Admin API/UI/mutations/business-capability enforcement disabled until the environment-specific prerequisites and bootstrap bindings are configured and verified.


## Admin request logging

OIDC authorization codes, state and other callback query parameters must never be written to standard access logs. The gateway image disables Uvicorn access logging; ingress/OTel request telemetry must log a redacted path without the admin callback query string.
