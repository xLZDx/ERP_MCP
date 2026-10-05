# ERP_MCP Data Model

**Version:** 1.0  
**Date:** 2026-10-05  
**Principle:** persist control/provenance, not an uncontrolled copy of accounting data

## 1. Data domains

ERP_MCP separates four data domains:

1. **Control plane** — sources, companies, access, policies, adapter bindings.
2. **Capability/schema** — metadata fingerprints, adapter capabilities, schema drift.
3. **Semantic configuration** — per-configuration mappings from canonical concepts to 1C objects.
4. **Evidence/audit** — immutable access audit and accounting reconciliation evidence.

Raw operational accounting facts are read through source adapters and are **not persisted by default**.

## 2. Identity model

### Principal

External identity from OAuth/OIDC:
- subject;
- client ID;
- groups;
- scopes;
- claims used only by approved policy rules.

Principals are not provisioned by AI tool calls.

## 3. Source model

### `sources`

Represents a technical integration endpoint/base.

Core fields:
- `source_id` — stable internal ID;
- `project` — `onec|erp|ferma`;
- `kind` — logical adapter/source kind;
- `display_name`;
- `base_url` or server-side endpoint reference;
- `username_secret_ref`;
- `password_secret_ref`;
- `read_only`;
- `enabled`;
- `tags[]`;
- entity allow/deny patterns;
- optional platform version hint;
- fallback kind/endpoint;
- created/updated timestamps.

Secret values never appear here.

### Source vs Company

A source is a technical base/endpoint. A company/organization is a business scope. One 1C base may
contain one or many organizations. They must not be conflated.

## 4. Company model

Implemented in schema migration 003 as `bag.companies`.

Recommended fields:
- `company_id UUID PK`;
- `source_id FK`;
- `external_ref` — source-local organization key;
- `display_name`;
- `legal_name` optional;
- `country_code` optional;
- `tax_id_fingerprint` optional, never required for routing;
- `enabled`;
- `is_default`;
- `metadata JSONB` for non-sensitive descriptors;
- timestamps.

Unique:
- `(source_id, external_ref)`.

The gateway returns business data only within authorized source/company scope.

## 5. Access model

`access_grants` supports source scope and optional company scope. Schema migration 003 adds
`company_id` and an `effect` (`allow` or `deny`). Company rows are keyed independently from the
technical source and constrained to that source by a composite foreign key.

The model supports:
- principal kind: subject/group;
- principal ID;
- source ID;
- optional company ID;
- capability/tool scope;
- expiry;
- revocation;
- allow/deny effect, with matching active deny taking precedence;
- grant provenance/actor.

Semantics:
- missing grant = deny;
- company-specific grant is narrower than source-wide grant;
- deny policy overrides allow;
- revoked/expired grant is immediately ineffective.

Company-scoped grants are not accepted as authorization for generic unscoped OData reads. Those
operations require an active source-wide grant. Company-scoped data operations remain unavailable
until an adapter operation can enforce and test the company boundary end-to-end.

## 6. Adapter binding

Planned table: `adapter_bindings`.

Fields:
- `binding_id UUID`;
- `source_id`;
- `adapter_kind`;
- `adapter_version`;
- `upstream_repo` / pinned SHA when applicable;
- `endpoint_ref`;
- `enabled`;
- priority;
- policy JSON;
- last health state/time.

This allows OData, extension/COM and isolated legacy routes without mutating the source identity.

## 7. Capability model

Existing `source_capabilities` stores:
- discovery time;
- metadata fingerprint;
- platform hint/version;
- compatibility status;
- adapter profile;
- metadata/JSON/Atom flags;
- expand support;
- entity count;
- evidence JSON.

Migration 005 adds `register_capabilities_json`, a per-source profile of register EntitySets and
operation evidence. A capability entry records availability, the evidence source, exact function
import/entity-set binding, HTTP method, discovery time and metadata fingerprint. Negative evidence
is retained too; a runtime/API method list alone never grants availability. Any metadata fingerprint
change replaces the evidence profile and retains the existing sticky drift gate.

Migration 004 additionally stores:
- previous metadata fingerprint;
- drift status (`UNKNOWN`, `STABLE`, `DRIFTED`);
- drift detection and acknowledgement timestamps.

The first observation establishes a stable baseline. A changed fingerprint sets a sticky `DRIFTED`
state and retains the prior fingerprint; identical subsequent probes do not silently clear it.
An operator may acknowledge only the current fingerprint through the admin command. A new change
invalidates that acknowledgement. Capability responses expose the drift state; `onec_read` fails
closed until acknowledgement, and capability/read audit events record `METADATA_DRIFTED` while the
drift is active.

Remaining target extensions:
- capability schema version;
- adapter version/SHA;
- service-document fingerprint;
- supported register virtual-table set;
- max verified URL/query behavior;
- last-success and last-failure timestamps;

A capability record is evidence, not a static promise.

## 8. Metadata/schema model

Do not store every raw source row.

Optional cached schema tables:
- `metadata_snapshots`:
  - snapshot ID;
  - source ID;
  - SHA-256;
  - adapter/profile version;
  - fetched at;
  - compressed/raw metadata object or blob reference;
- `metadata_entities`:
  - snapshot ID;
  - entity set;
  - entity type/kind;
  - property/nav-property summary.

Cache is disposable; source remains authoritative.

## 9. Semantic profile

### `semantic_profiles`

Defines configuration-aware accounting meaning.

Migration 006 implements per-source and optional per-company profiles with pinned preset
provenance, schema/capability/profile fingerprints, version, lifecycle state, JSON profile content,
and validation evidence. A profile is usable only for its exact source/company and unchanged,
acknowledged metadata. `VALIDATED` requires at least ten recorded passing native-report
reconciliation cases with unique case IDs and report references (database constraint plus runtime
eligibility check). Runtime role may read profiles/mappings; only the admin role may create or
update them. A narrow database trigger marks validated profiles stale when their source metadata
fingerprint changes. Preset catalog entries from Aprovodka are candidate hints, not validated
mappings.

Fields:
- `profile_id UUID`;
- source/configuration selector;
- profile name/version;
- metadata fingerprint applicability;
- status: draft/validated/retired;
- created/validated by;
- timestamps.

### `semantic_mappings`

Maps canonical concepts to source-specific implementation:
- concept: `receivable`, `payable`, `sales`, `cash`, `inventory`, `vat`, etc.;
- entity/register/account references;
- dimensions/resources;
- filter/template;
- applicability predicates;
- provenance/upstream/reference;
- confidence/status.

Mappings are versioned through their owning profile. They remain `CANDIDATE` until source-specific
metadata and semantic evidence confirms them; a preset name or upstream `verified` label alone does
not enable a 1C operation.

### `semantic_profile_events`

Migration 007 adds an append-only operator lifecycle log for profile creation, mapping additions,
validation and retirement. Runtime can read events; the admin role may append but cannot update or
delete them.

Never assume account 62/60/51/etc. globally. Those may be preset candidates only.

## 10. Reconciliation model

### `reconciliation_cases`

- case ID;
- semantic tool/domain;
- scenario/question;
- source/company/profile;
- expected/native report reference;
- tolerances/rules;
- required evidence.

### `reconciliation_runs`

- run ID;
- case ID;
- commit SHA;
- source capability/metadata fingerprint;
- semantic profile version;
- adapter version/SHA;
- input period/parameters fingerprint;
- result fingerprint/summary;
- native result/evidence reference;
- status: PASS/FAIL/INCONCLUSIVE;
- discrepancy;
- timestamp.

This is the correctness evidence for production accounting semantics.

## 11. Audit model

Existing `audit_events` is append-only.

Migration 003 adds the initial request/correlation and adapter provenance fields:
- request ID;
- company ID;
- adapter kind/version and upstream SHA;
- policy and metadata fingerprints;
- response bytes and truncation.

Target fields:
- event ID/time;
- request/correlation ID;
- subject/client;
- tool/operation;
- source/company;
- adapter/profile;
- policy version;
- query fingerprint;
- capability/metadata fingerprint;
- outcome;
- rows/bytes/truncated flag;
- duration;
- detail/error code.

Do not persist secrets or raw accounting payloads.

## 12. Operational state

Optional:
- `source_health` current state or time-series in observability backend;
- `circuit_state`;
- `adapter_lease/state` only if required by deployment topology.

Do not turn PostgreSQL into a metrics backend when OTel/Prometheus-equivalent is available.

## 13. Canonical semantic result envelope

Every data-plane result should normalize to:

```json
{
  "source_id": "company-base-001",
  "company_id": "optional-company-scope",
  "adapter_profile": "ODATA_V3",
  "metadata_fingerprint": "sha256...",
  "operation": "register.query",
  "data": [],
  "page": {
    "offset": 0,
    "limit": 200,
    "returned": 20,
    "has_more": false,
    "truncated": false
  },
  "warnings": [],
  "provenance": {
    "adapter_version": "...",
    "semantic_profile": "..."
  }
}
```

The semantic layer may return richer domain shapes, but provenance must not be lost.

## 14. Data lifecycle

- registry/policy state: durable, backed up;
- secrets: external secret provider;
- metadata/cache: recreatable;
- audit: durable append-only subject to deployment retention policy;
- raw accounting result: request-scoped by default;
- reconciliation evidence: durable for release/governance evidence;
- synthetic test data: repository/testbed only, never copied from customers.

Any automatic deletion/retention policy must be explicitly defined and approved before production.
