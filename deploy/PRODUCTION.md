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

## Release gate

Before first production enablement:
- CI green;
- unauthenticated/wrong issuer/audience/scope requests denied;
- revoked grants effective without restart;
- writable source rejected;
- arbitrary URL target impossible;
- response-size/rate limits verified;
- ten representative accounting questions reconciled with 1C UI/reports.
