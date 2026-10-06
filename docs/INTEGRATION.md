# ERP_MCP Integration Contract

**Version:** 1.1
**Date:** 2026-10-06
**Scope:** frozen; see `SCOPE_FREEZE_BASELINE_2026-10-06.md`

## 1. Purpose

Define stable boundaries between:
- MCP clients and ERP_MCP;
- ERP_MCP control plane and data-plane adapters;
- adapters and 1C;
- future ERP/Ferma adapters.

Transport implementations may change; this contract is the stable product boundary.

During the active scope freeze, new integration families are not added. Only integrations required
to close already frozen requirements may be implemented.

## 2. External MCP contract

The public MCP surface is semantic and policy-controlled.

Initial system/source tools:
- `system_status`;
- `sources_list`;
- `source_health`;
- `companies_list` (returns only organizations covered by the caller's active grants);
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


## 13. External Evidence integration contract

The External Evidence Plane is read-only and exists only for evidence classes already required by
frozen DAD scenarios.

Allowed ingress:
- operator/user upload through an approved bounded interface;
- approved authenticated connector;
- approved private import path.

Forbidden:
- model-supplied arbitrary URL fetch;
- evidence content changing authorization/policy;
- automatic mutation of 1C based solely on parsed evidence;
- raw private evidence committed to Git/public CI.

Every evidence object carries:
- evidence ID/class;
- source/company association;
- SHA-256/content fingerprint;
- parser/version;
- provenance/time/period;
- retention/access classification;
- parse warnings.

Missing or unparseable required evidence returns `EVIDENCE_REQUIRED` or `INCONCLUSIVE`.

## 14. DAD rule-engine integration

DAD assurance tools consume only:

1. validated semantic 1C results;
2. approved external evidence refs;
3. versioned rule packs.

They MUST NOT expose arbitrary model-generated native queries.

The engine returns stable status:
`PASS|FINDING|INCONCLUSIVE|EVIDENCE_REQUIRED|CAPABILITY_UNSUPPORTED|ERROR`.

Tax/payroll/legal rule families preserve human-review flags and effective-date/jurisdiction
provenance.

### 14.1 Normalized evidence provider / operator runbook

`external_evidence_manifest(source_id, company_id, evidence_id)` is read-only and returns ONLY a
safe manifest. It accepts no path, fetch URL, digest, parser profile, retention policy or approval
from the model. Gateway OAuth scope, current source/company ACL, rate check and durable access
receipt precede filesystem reads. Completion records parser fingerprint/count, never raw facts.
Disabled provider returns `CAPABILITY_UNSUPPORTED`; missing/cross-scope/expired entries return
`EVIDENCE_REQUIRED`; stale/corrupt input cannot PASS. `business_acceptance=NOT_EVALUATED`.

Configure all three SERVER-ONLY settings together; default is disabled:

```text
BAG_EVIDENCE_STORE_ROOT=<absolute protected private store outside Git>
BAG_EVIDENCE_APPROVAL_INDEX=<absolute protected private index file outside Git>
BAG_EVIDENCE_APPROVAL_SHA256=<operator-approved exact file SHA-256>
```

Index schema v1 is bounded to 512 KB/64 entries: exact schemas, duplicate JSON keys, receipt/profile
hashes, source/company scope, UTC approval windows and retention IDs are validated. Protected file
permissions and pinned SHA are rechecked BEFORE AND AFTER blob reading. Updated files are not
silently approved or served from a cached authorization snapshot. Pin rotation requires explicit
operator approval and server restart. This static receipt index requires no new SQL migration.

Operator intake (never a public MCP write tool):

1. Create a new owned store with `PrivateEvidenceStore.create` on an approved private volume.
   Preserve its actual directory for server configuration; never alter a general/user root.
2. Obtain explicit source/company parser and storage-retention approval. Prepare only normalized
   `text/csv` and an exact `EvidenceParserProfile` JSON snapshot, with pinned input/profile hashes.
   Both files stay outside Git and must pass private-file OS permission checks. Do NOT rename
   PDF/XML/ZIP to CSV or claim native validation from a normalized exchange.
3. Execute the explicit operator command (all paths/identities remain private):

```text
python -m scripts.evidence_intake --store-root <private-store> --input <private.csv>
  --input-sha256 <approved-sha> --profile <private-profile.json> --profile-sha256 <approved-sha>
  --retention-policy-id <approved-policy> --approved-from <UTC-RFC3339>
  --approved-until <UTC-RFC3339> --approval-output <new-file-in-private-store>
```

To add an artifact, pass `--existing-index` and `--existing-index-sha256`, with a NEW output file.
Existing index/files are preserved, never overwritten. Only hashes/counts/opaque IDs are printed.
Configure the returned approval SHA explicitly; never accept an approval digest from model input.

4. Rehearse authorized manifest reading and denied source/company, stale index, tamper and audit
   outage. Publish only safe hashes/audit correlations, not private paths/raw documents, in CI.

Approval windows bound READ AUTHORIZATION, not legal retention/destruction guarantees. No deletion
or retention scheduler exists; expired/orphan data needs approved operator handling, not automatic
destructive cleanup. Real-data ingestion remains gated on the approved storage retention policy.
Manifest wiring/operator normalized intake are implemented; native parsers, real semantics/native
reconciliation, deployed volume identity, retention and backup/restore remain OPEN.

## 15. Test-only 1C seeder boundary

The Ferma→1C seeder is WRITE-CAPABLE **only in the test plane**.

It must:
- run outside production MCP routes;
- require an explicit synthetic/test target marker;
- refuse production source IDs;
- use separate test-only credentials;
- create normal configuration-native business documents;
- never write internal 1C SQL/register tables directly just to manufacture expected results;
- be idempotent per scenario/run/event;
- emit write receipts/provenance.

Production packages/routes must not expose this seeder.

## 16. Real-reference base integration

The private `REFERENCE_TEST_BASE_A` is handled only as a test/evidence target:

- immutable golden source;
- disposable RO clone for discovery/reconciliation;
- optional separate disposable RW clone for isolated test-only write experiments;
- hashes/fingerprints in public reports, not raw data/credentials/private links.

The golden source is never used for mutation tests.
