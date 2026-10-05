# ERP_MCP Integration Contract

**Version:** 1.0  
**Date:** 2026-10-05

## 1. Purpose

Define stable boundaries between:
- MCP clients and ERP_MCP;
- ERP_MCP control plane and data-plane adapters;
- adapters and 1C;
- future ERP/Ferma adapters.

Transport implementations may change; this contract is the stable product boundary.

## 2. External MCP contract

The public MCP surface is semantic and policy-controlled.

Initial system/source tools:
- `system_status`;
- `sources_list`;
- `source_health`;
- `onec_capabilities`;
- `onec_metadata_summary`;
- `onec_find_entities`.

Generic raw read tools may exist for controlled diagnostics/development, but production user value
should increasingly flow through semantic tools.

Public tools must never accept:
- arbitrary URL/host;
- secret value;
- SQL;
- arbitrary executable 1C code;
- write/mutation operation.

## 3. Internal adapter contract

All data planes implement a normalized read-only contract.

### 3.1 Adapter context

Every operation receives server-generated context:

```json
{
  "request_id": "uuid",
  "source_id": "stable-id",
  "company_id": "optional-scope",
  "deadline_ms": 30000,
  "row_limit": 200,
  "byte_limit": 5000000,
  "principal_fingerprint": "non-secret",
  "policy_version": "..."
}
```

The adapter must not authorize based on model-provided identity.

### 3.2 Required operations

#### `health`

Returns adapter/source health without business data.

#### `capabilities`

Returns observed capabilities and fingerprints.

#### `metadata.search`

Inputs:
- search text/pattern;
- kinds;
- limit.

#### `metadata.describe`

Inputs:
- entity/register identifier.

#### `entity.query`

Inputs:
- entity set;
- typed/validated filter representation where supported;
- select;
- expand;
- order;
- page.

Raw filter escape hatches must remain policy-controlled and bounded.

#### `entity.get`

Inputs:
- entity set;
- key;
- projection.

#### `entity.count`

Inputs:
- entity set;
- bounded filter.

#### `register.query`

Inputs:
- register;
- virtual table;
- period/range;
- dimensions;
- condition;
- bounded projection/page.

Supported virtual-table names are capability-driven.

### 3.3 Optional operation

#### `native_query.read`

Allowed only on an explicitly approved adapter that guarantees read-only execution.

Requirements:
- SELECT/ВЫБРАТЬ-only equivalent validation;
- no arbitrary server-side code;
- timeout/row/byte caps;
- audit fingerprint;
- source/company ACL already established.

## 4. Adapter response envelope

```json
{
  "request_id": "uuid",
  "source_id": "source-001",
  "company_id": "company-001",
  "adapter": {
    "kind": "ODATA_V3",
    "version": "0.6.0",
    "upstream_sha": "..."
  },
  "metadata_fingerprint": "sha256...",
  "operation": "register.query",
  "data": [],
  "page": {
    "returned": 20,
    "has_more": false,
    "truncated": false
  },
  "warnings": [],
  "timing": {
    "upstream_ms": 120
  }
}
```

Errors use stable codes, not raw stack traces.

## 5. Stable error classes

Minimum:
- `AUTH_DENIED`;
- `SOURCE_DENIED`;
- `SOURCE_DISABLED`;
- `SOURCE_UNAVAILABLE`;
- `CAPABILITY_UNSUPPORTED`;
- `SCHEMA_DRIFT`;
- `QUERY_INVALID`;
- `QUERY_TOO_COMPLEX`;
- `RATE_LIMITED`;
- `TIMEOUT`;
- `RESPONSE_TOO_LARGE`;
- `ADAPTER_UNAVAILABLE`;
- `SECRET_UNAVAILABLE`;
- `UPSTREAM_ERROR`;
- `SEMANTIC_PROFILE_UNVALIDATED`.

Do not expose secret-bearing upstream error text.

## 6. Modern OData integration

Preferred path:
- exact pinned `@1c-odata/client`;
- exact pinned `@1c-odata/metadata`;
- wrapper exposes only required reads.

Use upstream behavior/tests for:
- literals/filters;
- DateTime/timezone;
- Int64;
- ValueStorage;
- pagination;
- metadata;
- register virtual tables;
- error mapping.

Do not expose upstream write methods through the wrapper.

## 7. mcp-rsv-data integration

Preferred fallback mode:
- run bridge/extension as an isolated adapter;
- treat it as a data plane, not as a second public authorization gateway;
- keep ERP_MCP as the authority for user/source/company policy;
- configure a read-only tool allowlist;
- authenticate/protect the internal channel.

COM bridge credentials/config never become model-visible.

## 8. Legacy 8.2 integration

If business requires 8.2:
- deploy the GPL adapter as a separate service;
- define a minimal read-only HTTP/MCP/internal protocol;
- do not copy/link GPL source into ERP_MCP core;
- do not let the legacy service administer ERP_MCP grants/secrets;
- normalize its response to the standard adapter envelope.

## 9. 1C onboarding handshake

For a new source:

1. Create source with secret references.
2. Validate endpoint policy.
3. Resolve credentials server-side.
4. Probe health.
5. Fetch metadata/capabilities.
6. Select adapter binding.
7. Discover companies/organizations.
8. Create/verify company scopes.
9. Attach semantic profile or mark semantic tools unavailable.
10. Grant principal/group access.
11. Run onboarding smoke/reconciliation.
12. Mark source `ACTIVE`.

A source with an unvalidated semantic profile may support metadata/raw diagnostics but not claim
validated accounting semantics.

## 10. Source offboarding

- revoke grants first;
- disable source;
- revoke/rotate source credentials;
- preserve required audit/reconciliation evidence;
- remove resources only under explicit destructive-action approval and retention policy.

## 11. Future ERP integration

Internal operations should map to ERP-authorized read/reporting APIs.

Requirements:
- signed tenant/org scope;
- RLS preserved;
- no generic unrestricted Postgres read account;
- same normalized provenance/audit envelope.

## 12. Future Ferma integration

Expose:
- universe/scenario/run metadata;
- expected/actual observations;
- comparator divergences;
- lineage/explanations.

Do not expose an adapter path that lets live 1C/ERP data alter Ferma expected/oracle computation.
