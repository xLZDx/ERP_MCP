# Upstream intake — pinned 2026-10-05

No upstream source code is vendored in the baseline commit yet. This file pins the sources
approved for selective intake and defines how they may be used.

| Upstream | Pinned SHA | License | Intake |
|---|---|---|---|
| evilbruce666/1c-odata-mcp | dc6b6a1358c7e65e3cfb45c22e8157d1479ab71e | MIT | PRIMARY 1C read/data-plane reference; selectively port read-only analytics and tests |
| theYahia/WWmcp (servers/aprovodka) | 7b62c90e1fe74324605dc28d76f195200bb97252 | MIT | OData 3.0/register virtual-table logic and tests |
| ruslan-hut/onec-mcp | 0e536c2ef30d13f2f414bd05ec559e6eff5416a9 | MIT | Admin/tenant registry UX and multi-database patterns |
| cuongdev/mcp-gateway | 5a51d5a743c6df0e6762c1f4cb331f373dd96a54 | MIT | OIDC/RBAC/rate-limit/observability/control-plane patterns |
| feenlace/mcp-1c | 71b8ca4e3036cd35444ee93db5bd66f29718243b | MIT | Phase 1.5 SELECT-only native query fallback reference |
| ROCTUP/1c-mcp-toolkit | current review only | GPL-3.0 | REFERENCE ONLY unless kept as a separate GPL service |

## Intake rules

1. Production artifact contains no write-side 1C implementation.
2. MIT-derived code must preserve copyright/license notices.
3. GPL code must not be copied into this codebase without an explicit license decision.
4. Every imported module must cite upstream repo + pinned SHA in its file header or a
   machine-readable provenance manifest.
5. Upstream tests are preferred when porting algorithms.
6. Russian-chart-of-accounts assumptions are not treated as universal truth. Client/accounting
   semantics are verified against the real 1C configuration and reports.
