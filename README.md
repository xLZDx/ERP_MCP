# ERP_MCP

Production-grade Business AI / MCP gateway with **1C-first priority** and reserved adapter boundaries.

The first production milestone is a **read-only 1C analytics gateway**:
- remote MCP over Streamable HTTP;
- OAuth/OIDC resource-server authentication;
- PostgreSQL source registry and ACL;
- Redis rate limiting;
- secret-manager boundary;
- immutable audit;
- multiple 1C databases/companies;
- 1C OData metadata discovery and read-only queries;
- no write tools in the production artifact.

Implementation work is staged on `bootstrap/1c-day1-production`.
