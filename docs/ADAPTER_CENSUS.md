# 1C adapter census — reuse before rewrite

Date: 2026-10-05.

The GitHub survey confirms that the adapter problem is already substantially solved in open
source. ERP_MCP should stay an orchestration/security layer and reuse mature transport/query
logic instead of creating another 1C client from zero.

## Routing matrix

| 1C family | Preferred route | Existing implementation to reuse | Decision |
|---|---|---|---|
| 8.3.8+ with standard OData | OData JSON v3 | hacker-cb/1c-odata, evilbruce666/1c-odata-mcp, aprovodka, pyrfor/onec-odata-mcp | REUSE |
| 8.3.5–8.3.7 with OData | capability probe + old OData/Atom compatibility | hacker-cb/1c-odata + historical OData clients as regression references | REUSE + thin normalization |
| modern 8.3 without sufficient OData | HTTP-extension/native 1C query | prepod2003/mcp-rsv-data, feenlace/mcp-1c, vladimir-kharin/1c_mcp patterns | REUSE |
| 8.2.13+ | in-1C bridge / HTTP service | ROCTUP/1c-mcp-toolkit explicitly advertises 8.2.13+ | ISOLATED GPL SERVICE / REFERENCE |
| local unpublished 8.3 base | COM bridge to extension | prepod2003/mcp-rsv-data uses V83.COMConnector | REUSE |
| 7.7 | 32-bit Windows COM→REST bridge | umanets/1c77-rest-api | REFERENCE ONLY; license unresolved |
| arbitrary/custom config | live metadata + query adapter | mcp-rsv-data, hacker-cb/1c-odata, aprovodka | REUSE |

## Primary findings

### hacker-cb/1c-odata

MIT. Dedicated 1C OData 3.0 implementation with:
- runtime `$metadata` discovery;
- dynamic client without generated files;
- filter/query builder;
- register helpers;
- DateTime / Int64 / ValueStorage shaping;
- connection probe that accepts JSON and Atom service documents;
- metadata cache/snapshots;
- an MCP package on top of the same client.

**Decision:** use this as the primary source for OData wire/query behavior rather than expanding
our Python client from scratch.

### aprovodka

MIT. Already covers:
- catalogs and documents;
- all four register kinds;
- accounting-register virtual tables;
- balances / turnovers / balance-and-turnovers;
- ext-dimensions;
- change tracking;
- presets for common 1C configurations.

**Decision:** port read-side algorithms and their tests; do not port the write surface.

### mcp-rsv-data

MIT. Solves a transport boundary that our OData adapter does not:
- read-only design;
- 1C extension;
- HTTP-service mode;
- local Windows COM bridge;
- metadata/structure/query tools;
- native 1C query execution;
- respects 1C user permissions;
- anonymization.

**Decision:** preferred source for fallback/bridge behavior. Do not invent another COM bridge.

### ROCTUP/1c-mcp-toolkit

The repository explicitly documents compatibility with **1C:Enterprise 8.2.13+ / 8.3.25** and
contains compatibility-oriented code for old platform behavior.

License is GPL-3.0.

**Decision:** no source copying into ERP_MCP. If 8.2 support is required, keep it behind a separate
process/service boundary or independently implement only the documented protocol contract.

### 1C 7.7

`umanets/1c77-rest-api` demonstrates:
- Windows 32-bit;
- 1C 7.7 through COM/winax;
- REST façade.

No verified license was found.

**Decision:** architectural/reference evidence only.

## Historical clients

Old OData libraries are valuable regression evidence because they encode quirks from earlier 1C
deployments. In particular `kilylabs/odata-1c` (MIT, 2016) and related clients cover query,
filter, expand, paging and CRUD shapes. We use them as compatibility references, not as the runtime
stack.

## What ERP_MCP still owns

Open source does not replace our control plane:

- OAuth/OIDC and MCP resource identity;
- PostgreSQL source registry;
- subject/group → company ACL;
- secret-manager boundary;
- immutable audit;
- rate limits;
- capability fingerprint and adapter routing;
- policy-enforced read-only surface;
- accounting reconciliation gates;
- ERP/Ferma adapter boundaries.

## Reuse-before-rewrite gate

Before writing any new 1C transport/query feature:

1. Check `vendor/UPSTREAMS.md` and this census.
2. Inspect the pinned upstream implementation and tests.
3. Reuse/port when the license permits.
4. Write original code only for the remaining gap.
5. Add a regression fixture proving why the upstream implementation was insufficient.

This is a project rule, not a suggestion.
