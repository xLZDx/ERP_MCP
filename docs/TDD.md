# Technical Design Document — ERP_MCP 1C-first Production MVP

**Version:** 1.0  
**Date:** 2026-10-05  
**Status:** FROZEN FOR IMPLEMENTATION

## 1. Purpose

ERP_MCP provides a production-grade, read-only AI integration layer for many 1C information bases.
It presents a safe MCP surface to authorized AI clients while isolating authentication, policy,
source routing, secrets, audit and accounting semantics from the underlying 1C transport.

The first production scope is 1C. ERP and Ferma reuse the same control plane later.

## 2. Problem statement

One AI user may need access to tens or hundreds of 1C companies. Company access changes regularly,
different customers may run different 1C platform/configuration versions, and some bases expose
standard OData while others require an extension, HTTP service or local COM bridge.

The system must:
- add/revoke company access without code changes or application restart;
- never expose arbitrary target URLs or credentials to the model;
- remain read-only even when an upstream library contains write support;
- detect actual source capabilities instead of guessing from configuration names;
- provide accounting answers that can be reconciled against native 1C reports;
- reuse mature open-source 1C protocol implementations rather than creating a new protocol stack.

## 3. Goals

### G-01 Production-safe remote MCP

Expose a Streamable HTTP MCP resource protected by OAuth/OIDC, with per-request identity,
authorization and audit.

### G-02 Multi-company source control

Support at least 150 active 1C sources per operator/principal as the initial design target, with
source/grant changes effective without service restart.

### G-03 Version/configuration tolerance

Use behavior-first capability negotiation to route sources to the safest compatible read transport.

### G-04 Read-only accounting access

Provide metadata, bounded entity reads, entity lookup/count and register virtual-table queries,
then semantic accounting tools such as AR/AP, sales, purchases, cash, inventory, VAT and account
turnovers.

### G-05 Evidence-based correctness

No semantic accounting tool is production-approved until its representative outputs are reconciled
against native 1C reports/UI on a real test base.

### G-06 Reusable common control plane

Identity, ACL, source registry, audit, limits, secrets and observability must be reusable by future
ERP/Ferma adapters without weakening their native authorization boundaries.

## 4. Non-goals for 1C MVP

The MVP does **not**:
- create/update/delete/post/unpost 1C objects;
- expose arbitrary 1C code execution;
- expose raw administrator credentials;
- emulate internal 1C SQL tables;
- build a new general-purpose OData v3 implementation when a licensed mature implementation exists;
- guarantee universal support for every private/custom 1C installation without capability evidence;
- persist a general-purpose copy/data lake of business transactions.

## 5. Hard invariants

1. **READ-ONLY HARD BOUNDARY:** no production tool can mutate 1C.
2. **FAIL-CLOSED:** production does not start without mandatory auth, state and secret dependencies.
3. AI requests address only a registered `source_id` / `company_id`, never an arbitrary host.
4. Source credentials never enter model-visible context, audit payloads or command-line arguments.
5. Runtime identity comes from a validated bearer token, not caller-supplied principal text.
6. Authorization is evaluated server-side for every source access.
7. Raw business payloads are not retained by default.
8. Audit is append-only from the runtime role.
9. Capability routing is based on observed endpoint behavior; version strings are evidence, not authority.
10. Direct access to internal 1C DB tables is prohibited.
11. Upstream/copyleft license constraints are enforced before source intake.
12. ERP/Ferma adapters must preserve their own tenant/org/oracle boundaries.

## 6. Functional requirements

### FR-A Identity and access

- Validate token signature, issuer, audience, expiry and required scopes.
- Resolve subject, client and optional group claims.
- Support subject and group grants.
- Support immediate grant revocation without restart.
- Deny disabled/expired sources and grants.

### FR-B Source registry

Each source has:
- stable source ID;
- project/kind;
- display name;
- endpoint reference;
- secret references;
- enabled/read-only state;
- tags;
- entity allow/deny policy;
- optional platform hint;
- fallback adapter configuration.

No secret value is stored in the registry.

### FR-C Capability discovery

For a 1C source:
- fetch and fingerprint metadata when available;
- detect JSON/Atom behavior;
- detect safe register/query features as needed;
- record adapter profile and evidence;
- classify as `SUPPORTED`, `SUPPORTED_WITH_FALLBACK` or `UNSUPPORTED`.

### FR-D Data access

Normalized read operations must include:
- health;
- capability discovery;
- metadata search/describe;
- bounded query/list;
- entity by key;
- count;
- register virtual-table query;
- pagination/truncation evidence.

Native-query fallback is allowed only through an approved read-only adapter and constrained query
contract.

### FR-E Semantic accounting

Semantic tools must be transport-independent. Initial target domains:
- company snapshot;
- sales/purchases;
- cash/bank;
- inventory;
- receivables/payables and aging;
- account turnover/balance;
- document postings/trace;
- VAT/tax summary where the configuration supports a verified mapping;
- anomaly/reconciliation helpers.

Mappings are per semantic profile, not universal hard-coded account numbers.

### FR-F Audit

Record at minimum:
- event ID/time;
- principal subject;
- client ID;
- tool/operation;
- source/company;
- outcome;
- query fingerprint;
- row count;
- duration;
- adapter profile;
- policy/capability version or fingerprint where available;
- error/deny code.

Raw filters/payloads are excluded by default.

## 7. Non-functional requirements

### Security

- HTTPS externally and for production 1C endpoints unless an approved private adapter terminates the
  transport safely.
- DNS-rebinding/SSRF protections.
- no redirect following to arbitrary hosts;
- least-privilege DB roles;
- secret provider boundary;
- dependency/license audit;
- non-root containers;
- bounded request/response sizes and query complexity.

### Reliability

- database and Redis readiness checks;
- one unhealthy 1C source must not make the whole gateway globally unavailable;
- safe retry only for idempotent reads and retryable status classes;
- request cancellation/timeouts;
- source-specific circuit breaking in the data-plane implementation.

### Capacity target

Design target, not yet a measured guarantee:
- >=150 concurrently registered/active client companies for an operator use case;
- horizontal gateway replicas sharing PostgreSQL/Redis;
- bounded per-source and per-principal concurrency;
- no unbounded fan-out across all companies in a single request.

Load-test evidence is required before production GO.

### Privacy/data minimization

- no production credentials in logs;
- no raw accounting data in audit by default;
- optional redaction/anonymization before model return where policy requires;
- no production customer data in public CI/test fixtures.

## 8. Canonical request lifecycle

1. MCP request arrives over HTTPS.
2. OAuth token is validated.
3. Principal/client/groups are established.
4. Tool arguments are schema-validated.
5. Source/company is resolved from server-side registry.
6. ACL and policy are evaluated.
7. Rate/query/fan-out budget is checked.
8. Capability router selects an approved adapter.
9. Secret reference is resolved server-side.
10. Adapter performs bounded read.
11. Response is normalized with provenance/truncation metadata.
12. Audit event is appended.
13. Model receives only the permitted normalized result.

## 9. Primary transport decisions

- Modern OData: reuse `@1c-odata/client` / `@1c-odata/metadata` behavior from the pinned MIT upstream.
- Accounting register semantics: reuse/read-port approved logic/tests from `aprovodka`.
- Local/unpublished/native-query 8.3: reuse isolated `mcp-rsv-data` bridge/extension behavior.
- 8.2.13+: optional isolated GPL service; never copy GPL source into core.
- 7.7: no MVP commitment; reference-only until a real requirement exists.

See adapter census/intake documents.

## 10. Release acceptance summary

Production GO requires all DoD gates, including:
- security and CI green;
- live capability evidence;
- multi-company ACL evidence;
- accounting reconciliation on real 1C;
- load/limit evidence;
- operational runbook and rollback;
- current documentation and provenance.

Implementation completeness without accounting and operational evidence is **not production GO**.
