# Production deployment contract

## Mandatory external services

- PostgreSQL with backups/PITR.
- Redis or compatible managed Redis.
- OAuth/OIDC IdP issuing JWT access tokens for the MCP resource.
- Secret provider: mounted secret files or GCP Secret Manager.
- Stable HTTPS MCP URL or approved private tunnel.

## Recommended topology

```text
MCP client
   |
OAuth + HTTPS
   |
ERP_MCP gateway (private subnet)
   +-- PostgreSQL
   +-- Redis
   +-- Secret Manager
   +-- private HTTPS + bearer --> pinned read-only OData sidecar
                                      +-- allowlisted HTTPS --> 1C OData
```

Do not expose 1C OData directly to AI clients.

When `BAG_ODATA_SIDECAR_URL` is configured, also inject `BAG_ODATA_SIDECAR_TOKEN` from the
secret manager (at least 32 random bytes) and configure `ONEC_ALLOWED_HOSTS` on the sidecar as an
exact comma-separated allowlist of 1C host authorities (`host` or `host:port`, never `*`). The
gateway sends registered-source URLs and resolved credentials only over the authenticated internal
hop. Production requires HTTPS on that hop. Do not publish the sidecar port outside its private
service network. The sidecar only exposes bounded OData query/count operations; all other routes and
verbs fail closed. A sidecar response is rejected unless its source id and upstream SHA match.

## JWT claims

Required: `iss`, `aud`, `sub`, `iat`, `exp`, and scope `onec:read`.
Optional: `client_id`/`azp`, `groups`.

## Database privilege split

- `BAG_MIGRATION_DATABASE_URL`: schema owner/migrations only.
- `BAG_ADMIN_DATABASE_URL`: source and grant administration.
- `BAG_DATABASE_URL`: runtime read registry/grants and insert audit only.

Register an organization discovered and verified during onboarding, then grant only that scope:

```bash
python scripts/admin.py company-upsert \
  --company-id <stable-uuid> \
  --source-id company-001 \
  --external-ref <source-local-organization-key> \
  --display-name "Organization 001"

python scripts/admin.py grant-add \
  --principal <oauth-subject> \
  --source-id company-001 \
  --company-id <stable-uuid>
```

Company-scoped grants currently authorize organization discovery only. Generic `onec_read` requires
a source-wide grant until a semantic adapter can enforce company scope in the data query. Use
`--effect deny` to add an overriding source/company deny.

## Release gate

Before first production enablement:
- CI green;
- unauthenticated/wrong issuer/audience/scope requests denied;
- revoked grants effective without restart;
- writable source rejected;
- arbitrary URL target impossible;
- response-size/rate limits verified;
- ten representative accounting questions reconciled with 1C UI/reports.

## Admin Control Center production activation

Keep Admin Control Center feature flags disabled until the target IdP and control API credential are configured.

Required settings when enabled include BAG_ADMIN_API_ENABLED, BAG_ADMIN_UI_ENABLED, a distinct BAG_ADMIN_OAUTH_AUDIENCE and BAG_ADMIN_OAUTH_REQUIRED_SCOPE, OIDC authorization/token/client/redirect settings, BAG_ADMIN_CONTROL_DATABASE_URL using business_ai_control_api, and explicit BAG_ADMIN_SOURCE_ALLOWED_HOSTS plus approved CIDRs where used.

Bootstrap the first platform administrator with the separate operator/admin database credential using scripts/admin.py platform-role-add. Enable BAG_ADMIN_MUTATIONS_ENABLED only after the control-API privilege check and source egress policy pass.

Enable BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED only after intended users/groups have assignments; otherwise protected MCP operations fail closed by design.

Rollback is application/config rollback: disable Admin UI/API/mutations/capability enforcement. Migrations 008-011 are additive and may remain inert. Do not drop policy or audit tables during routine rollback.
