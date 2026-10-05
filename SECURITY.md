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
