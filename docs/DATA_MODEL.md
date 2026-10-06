# ERP_MCP Data Model

**Version:** 1.1
**Date:** 2026-10-06
**Principle:** persist control/provenance, not an uncontrolled copy of accounting data

## 1. Data domains

ERP_MCP separates six data domains:

1. **Control plane** — sources, companies, access, policies, adapter bindings.
2. **Capability/schema** — metadata fingerprints, adapter capabilities, schema drift.
3. **Semantic configuration** — per-configuration mappings from canonical concepts to 1C objects.
4. **Evidence/audit** — immutable access audit and accounting reconciliation evidence.
5. **External evidence metadata** — fingerprint/provenance/reference for approved read-only evidence
   required by frozen DAD scenarios; raw private documents remain outside the control database by
   default.
6. **Business-assurance rules** — versioned DAD rule packs/applicability/evidence requirements.

The active scope freeze is governed by `SCOPE_FREEZE_BASELINE_2026-10-06.md`; no new persistent
domain is introduced without explicit rebaseline.

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
change replaces the register-operation profile and retains the existing sticky drift gate. The
`evidence_json.semantic_capabilities` object separately records negative evidence for exact
semantic concept/EntitySet/expected-property mappings (absent EntitySet or properties); entries are
metadata-fingerprint-scoped, contain schema names only, and are preserved by capability refreshes.
Entries from an older metadata fingerprint are historical and cannot authorize a read.

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
Migration 008 adds an operator-confirmed `CONFIRMED`/`HIGH` state with evidence refs and an
append-only `MAPPING_CONFIRMED` event. Profile validation fails while any mapping remains a candidate.
The first canonical account-turnover mapping binds one exact `AccountingRegister_*` method, an
operator-reviewed company dimension/type, and seven source property names projected to canonical
output keys. Runtime use still requires matching source/company, current acknowledged metadata,
validated profile evidence and a positive live capability for that exact register method.

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
- status: PASS/FAIL/INCONCLUSIVE/EVIDENCE_REQUIRED/CAPABILITY_UNSUPPORTED;
- external/native/oracle evidence references as applicable;
- test level: L1/L2-A/L2-B/L3;
- discrepancy;
- timestamp.

This is the correctness evidence for production accounting semantics.

### 10A. External evidence metadata

Recommended logical entity: `external_evidence_refs`.

Fields:
- evidence ID;
- source/company association;
- evidence class (invoice, bank_statement, z_report, terminal_report, tax_filing, tax_receipt,
  customs_ccac, payroll_source, contract, reconciliation_act, other already-frozen class);
- private blob/object reference, never public URL from the model;
- SHA-256/content fingerprint;
- MIME/type/parser version;
- source/provenance;
- business period/date;
- ingest time;
- retention/access classification;
- parse status/warnings.

Raw private evidence is not copied into Git/public CI or ordinary audit rows.

Internal implementation foundation: `external_evidence.py` accepts only bounded uploaded bytes in
`external-normalized-csv-v1` (exact headers `key,date,currency,amount`). It requires the exact
source/company/configuration/semantic-profile/period/currency/timezone scope, a server-confirmed
parser-profile fingerprint, approved retention-policy ID and opaque `private:` blob reference.
All frozen evidence classes share this normalized interchange contract; this does NOT prove
native bank/Z/terminal/PDF/tax/payroll format support. Empty/missing requirements raise
`EVIDENCE_REQUIRED`; unconfirmed/cross-scope inputs are rejected or `EVIDENCE_INCONCLUSIVE`.
Manifest output contains hashes/counts only and always retains human review. Parser performs no
URL/file fetch, blob storage, 1C writes or business PASS. Private storage, ACL/audit upload endpoints,
native parsers, retention administration and DAD rule integration remain separate open gates.

The immutable normalized evidence retains its exact `EvidenceParserProfile` snapshot. Reuse gates
recompute the approved profile fingerprint and bind class/version/parser/scope, not just membership
of a detached fingerprint string. Relabeling bank evidence as Z evidence, changing profile scope
or version, missing profile snapshots, malformed document digests and untyped envelopes cannot pass.
This is profile-binding validation, not proof of native-document authenticity or signature validity.

### 10B. DAD rule-pack model

Recommended logical entities:

`dad_rule_packs`
- pack ID/version;
- jurisdiction/effective period where applicable;
- configuration/company/activity applicability;
- status: draft/validated/retired;
- provenance/owner.

`dad_rules`
- rule ID;
- pack ID/version;
- semantic inputs;
- account/dimension selector;
- condition/comparison;
- required evidence classes;
- severity;
- explanation/remediation;
- human-review requirement;
- native-report/reconciliation reference.

A rule cannot silently become universal across configurations/companies.

Internal comparison implementation: `dad_rules.py` binds immutable rule/pack/version/effective
period/tolerance/class/concept to an exact EvidenceScope and server-approved rule fingerprint.
It separately requires confirmed semantic scope and confirmed external parser profile. Missing,
unconfirmed, cross-company/currency/period, incomplete, ambiguous and same-artifact-plane inputs
cannot yield PASS. Findings contain opaque key hashes/reason codes, never raw identifiers/amounts.
Exact bounded Decimal comparisons preserve micro-units; input evidence level is retained and
native approval is never inferred. This is a normalized comparison foundation for Z/terminal/
bank-style inputs, not native format validation or universal account rules. Runtime tool/ACL/audit
integration, configured account selectors, native observers and full month-close packs remain open.

Only bounded known evidence-level identifiers may enter result envelopes. Malformed/free-text/
non-string evidence levels are returned as null and rejected, including early unconfirmed-rule
paths; raw document or credential-like text is never echoed through this field.

### 10C. Testbed/reference provenance

Reference/oracle artifacts are tracked by references and hashes, not copied into the public DB model:

- real-reference base alias + archive SHA/configuration fingerprint;
- Ferma commit/generator/profile/seed/scenario digest;
- synthetic-base marker;
- native observer/result digest;
- ERP_MCP result digest.

Test-only write credentials/seeder state are never valid production source credentials.

## 11. Audit model

Existing `audit_events` is append-only.

Migration 003 adds the initial request/correlation and adapter provenance fields:
- request ID;
- company ID;
- adapter kind/version and upstream SHA;
- policy and metadata fingerprints;
- response bytes and truncation.

Migration 009 adds the semantic profile fingerprint so canonical-tool audit events identify the
exact mapping profile used for a read.

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
- synthetic test data: repository/testbed only, never copied from customers;
- private real-reference 1C archives/backups: private testbed storage only, immutable golden source;
- external evidence raw documents: approved private storage/retention only; repository stores at most
  safe metadata/hashes/aliases;
- Ferma expected/oracle artifacts: isolated from 1C/ERP_MCP actual computation inputs.

Any automatic deletion/retention policy must be explicitly defined and approved before production.
