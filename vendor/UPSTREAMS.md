# Upstream intake — pinned 2026-10-05

This repository keeps selected upstreams as read-only references and provenance anchors.
They are not runtime dependencies unless a later intake commit explicitly ports code.

## Primary intake set

| Upstream | Pinned SHA | License | Role |
|---|---|---|---|
| evilbruce666/1c-odata-mcp | dc6b6a1358c7e65e3cfb45c22e8157d1479ab71e | MIT | 1C read/analytics tool semantics, multi-base patterns |
| hacker-cb/1c-odata | cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5 | MIT | Mature OData v3 client, dynamic metadata, query/register/wire-format behavior |
| prepod2003/mcp-rsv-data | 76fed8e6e16833fee1514969841b8d9a61c7c152 | MIT | Read-only 1C extension + HTTP/COM bridge, metadata/query fallback |
| theYahia/WWmcp (servers/aprovodka) | 7b62c90e1fe74324605dc28d76f195200bb97252 | MIT | Accounting/accumulation register virtual-table logic |
| feenlace/mcp-1c | 71b8ca4e3036cd35444ee93db5bd66f29718243b | MIT | Native 1C query/metadata HTTP-extension fallback for modern 8.3 |
| Romandredan/odata1c-gate | 265e438a038a371058f7c30fac7d450c0df2dbcc | MIT | PII tokenization, per-base policy and production gateway patterns |
| pyrfor/onec-odata-mcp | 97a7f257416004a080639787c3a7760479d1b03b | MIT | Compact read-only OData query-builder/MCP patterns |
| kilylabs/odata-1c | 93b7ff7dda00dc9071b6dc844ca939583c1d5336 | MIT | Historical OData behavior/compatibility reference |
| ruslan-hut/onec-mcp | 0e536c2ef30d13f2f414bd05ec559e6eff5416a9 | MIT | Admin/tenant registry UX and multi-database patterns |
| cuongdev/mcp-gateway | 5a51d5a743c6df0e6762c1f4cb331f373dd96a54 | MIT | OIDC/RBAC/rate-limit/observability patterns |

## Compatibility-only / isolated references

| Upstream | Pinned SHA | License | Rule |
|---|---|---|---|
| ROCTUP/1c-mcp-toolkit | fe12903af7a367a9d67dd055c13f4b59bb59d83c | GPL-3.0 | Supports 1C 8.2.13+; separate-service/reference only |
| umanets/1c77-rest-api | 6bad0859b35128cd706355211d23581edbba53aa | no verified license | 1C 7.7 COM→REST reference only; do not copy |
| vladimir-kharin/1c_mcp | 362f5928bac7d4e51a2825f712f512f4e0469c17 | README says MIT; license file not verified | Native-in-1C MCP framework reference until licensing is confirmed |

## Discovery source

`Untru/1c-mcp` @ `b94b0498df9a604e48912f21a9509352b6aba4a3` is used as the current
catalog of 1C MCP projects. It is a discovery source, not a runtime dependency.

## Intake rules

1. Production 1C data path remains read-only.
2. Prefer importing tested algorithms over reimplementing OData/register edge cases.
3. MIT-derived code must preserve copyright/license notices.
4. GPL code is not copied into this codebase. If used, it stays behind a separate process/service boundary.
5. No-license projects are reference-only.
6. Every imported module must carry upstream repo + pinned SHA provenance.
7. Upstream write APIs are ignored/removed for the production artifact.
8. Configuration-specific accounting assumptions are never treated as universal truth.
9. Upstream tests should be ported with the algorithm whenever practical.
