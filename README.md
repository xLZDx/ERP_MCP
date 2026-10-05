# ERP_MCP

**Production-grade Business AI / MCP gateway — 1C first.**

Current priority is a production read-only connection from AI clients to many 1C databases.
The same control plane later accepts ERP and Ferma adapters without redesigning identity, ACL,
secrets, audit or observability.

## Day-1 production contract

Production is fail-closed:

- OAuth/OIDC bearer identity per MCP request;
- issuer + audience + required-scope validation;
- PostgreSQL source registry and subject/group ACL;
- Redis cross-replica rate limiting;
- mounted/GCP secret provider; env secrets forbidden in production;
- immutable PostgreSQL audit;
- registered `source_id` only — AI cannot supply arbitrary URLs;
- 1C HTTPS in production;
- redirects disabled;
- live `$metadata` validation;
- source-level EntitySet allow/deny rules;
- central row/filter/timeout/response limits;
- GET/HEAD-only 1C transport;
- no write tools in the production artifact;
- health/readiness endpoints;
- non-root container;
- explicit DB migration/admin/runtime privilege split.

See [SECURITY.md](SECURITY.md) and [deploy/PRODUCTION.md](deploy/PRODUCTION.md).

## MCP tools in the first baseline

- `system_status`
- `sources_list`
- `source_health`
- `onec_metadata_summary`
- `onec_find_entities`
- `onec_read`

The first semantic accounting tools (AR/AP, sales, purchases, cash, inventory, VAT,
account turnover and document postings) are added only after profiling the actual client
configuration and reconciling numbers with 1C reports.

## Open-source intake

Pinned upstreams and license rules are in [vendor/UPSTREAMS.md](vendor/UPSTREAMS.md).

Primary sources:
- `evilbruce666/1c-odata-mcp` — MIT, primary 1C read/analytics engine reference;
- `theYahia/WWmcp/servers/aprovodka` — MIT, register/OData 3.0 logic;
- `ruslan-hut/onec-mcp` — MIT, multi-database/admin patterns;
- `cuongdev/mcp-gateway` — MIT, production gateway/security patterns;
- `feenlace/mcp-1c` — MIT, future SELECT-only native-query fallback;
- `ROCTUP/1c-mcp-toolkit` — GPL-3.0, reference-only unless isolated separately.

## Development

```bash
cp .env.development.example .env
docker compose -f compose.development.yml up -d
pip install -e ".[dev]"
python scripts/migrate.py
pytest
uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port 8000
```

## First 1C source

After migrations, register an OData source with secret references:

```bash
python scripts/admin.py source-upsert \
  --source-id company-001 \
  --display-name "Company 001" \
  --base-url https://1c.example.com/base/odata/standard.odata \
  --username-secret onec-company-001-user \
  --password-secret onec-company-001-password
```

Then grant a validated OAuth subject:

```bash
python scripts/admin.py grant-add \
  --principal <oauth-subject> \
  --source-id company-001
```

Revocation requires no application restart.

## Definition of MVP done

The codebase being production-shaped is not enough. The environment gets GO only after
[all acceptance gates](docs/MVP_SCOPE.md) pass, including independent reconciliation of at least
10 representative accountant questions against 1C UI/reports on a test copy.
