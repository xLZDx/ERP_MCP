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

Configure `BAG_SOURCE_HOST_ALLOWLIST` on the gateway as a comma-separated list of exact source
hostnames (no scheme, port, wildcard, or path), synchronized with `ONEC_ALLOWED_HOSTS`. Production
source registration/lookups fail closed for any hostname not on this list. This hostname check does
not prevent DNS rebinding: the production network must separately restrict gateway and sidecar
egress to approved 1C address ranges, and release evidence must demonstrate that DNS resolution
cannot redirect an approved hostname to an unapproved destination at connect time. On-premises
private addresses are supported only when explicitly allowlisted and permitted by network policy.

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
- exact source host allowlist enforced and DNS-rebinding/egress controls evidenced;
- response-size/rate limits verified;
- ten representative accounting questions reconciled with 1C UI/reports.

Recovery must follow [the rollback and restore runbook](ROLLBACK.md). No in-place database restore
or destructive recovery is authorized by this document; production rehearsals and named operator
approval remain required evidence.
