# Architecture — 1C-first

```text
MCP client
   |
   | OAuth 2.1 bearer
   v
ERP_MCP /mcp
   |
   +-- JWT issuer/audience/scope validation
   +-- PostgreSQL source registry + subject/group ACL
   +-- Redis rate limit
   +-- immutable PostgreSQL audit
   +-- secret provider
   |
   v
registered source_id
   |
   v
1C OData HTTPS (GET/HEAD only)
```

The first production adapter is 1C. ERP and Ferma reuse the control plane later but do not
weaken the 1C MVP scope.

## Day-1 tools

- system_status
- sources_list
- source_health
- onec_metadata_summary
- onec_find_entities
- onec_read

## Next semantic layer

After profiling the real configuration, add read-only accounting tools for sales, purchases,
cash, inventory, AR/AP, VAT, account turnover and document postings. Exact mappings are
configuration-specific and must be reconciled against 1C reports.
