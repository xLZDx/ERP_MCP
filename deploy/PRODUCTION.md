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
   +-- HTTPS --> 1C OData
```

Do not expose 1C OData directly to AI clients.

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
