# ERP_MCP Architecture

**Version:** 1.0  
**Date:** 2026-10-05  
**Status:** FROZEN FOR IMPLEMENTATION

## 1. Architecture principles

1. **Control plane and data planes are separate.**
2. **Read-only 1C MVP is a hard boundary.**
3. **Behavior-first routing beats version-name assumptions.**
4. **Reuse mature 1C protocol implementations.**
5. **Source/company authorization is evaluated before adapter execution.**
6. **Raw accounting data is not a new persistent data lake.**
7. **Accounting semantics are profile-driven and evidence-backed.**
8. **One broken customer source must not take down the gateway.**
9. **No direct internal 1C SQL integration.**
10. **Future ERP/Ferma adapters reuse control-plane services, not 1C assumptions.**

## 2. System context

```text
┌─────────────────────────────────────────────────────────────────┐
│                           AI clients                            │
│ ChatGPT / approved MCP clients / future enterprise assistants  │
└───────────────────────────────┬─────────────────────────────────┘
                                │ OAuth bearer + HTTPS/MCP
                                v
┌─────────────────────────────────────────────────────────────────┐
│                       ERP_MCP CONTROL PLANE                     │
│                                                                 │
│ AuthN/AuthZ │ Registry │ Company scope │ Policy │ Audit │ Limits│
│ Capability router │ Semantic layer │ Provenance │ Observability │
└───────────────┬───────────────────────┬─────────────────────────┘
                │ normalized            │ fallback/legacy
                │ read contract         │ normalized read contract
                v                       v
      ┌──────────────────┐    ┌──────────────────────────────┐
      │ OData V3 plane   │    │ Extension/COM/legacy planes  │
      │ approved MIT     │    │ isolated by adapter boundary │
      │ upstream engine  │    │                              │
      └─────────┬────────┘    └─────────────┬────────────────┘
                │                           │
                └────────────┬──────────────┘
                             v
                   ┌─────────────────┐
                   │ 1C information  │
                   │ bases / servers │
                   └─────────────────┘

Control-plane dependencies:
  PostgreSQL | Redis | OAuth/OIDC IdP | Secret provider | OTel backend
```

## 3. Container view

### 3.1 MCP Gateway / Control Plane

Responsibilities:
- MCP transport/resource-server behavior;
- identity extraction;
- source/company authorization;
- policy/limit enforcement;
- capability routing;
- semantic tool orchestration;
- normalized provenance;
- append-only audit.

Must not:
- contain broad 1C write APIs;
- store 1C passwords directly;
- become a full duplicate OData implementation.

### 3.2 PostgreSQL

Authoritative for:
- source registry;
- company scopes;
- grants/policies;
- capability evidence;
- semantic profiles/mappings;
- audit;
- reconciliation evidence.

Not authoritative for:
- current 1C accounting facts.

### 3.3 Redis

Used for:
- cross-replica rate limiting;
- optional short-lived coordination/cache state where failure semantics are defined.

Redis is not the source of truth for grants/audit.

### 3.4 Secret Provider

Holds:
- 1C technical-user credentials;
- adapter/bridge credentials where needed;
- service secrets.

Registry stores references only.

### 3.5 Modern OData Data Plane

Preferred implementation source:
- pinned `hacker-cb/1c-odata`;
- packages `@1c-odata/client` and `@1c-odata/metadata`.

Responsibilities:
- OData v3 wire behavior;
- EDMX metadata;
- query/filter builder;
- entity reads;
- register virtual tables;
- type conversion;
- bounded result shaping.

ERP_MCP wraps it through a narrow read-only internal contract.

### 3.6 Extension/COM Data Plane

Preferred source:
- pinned MIT `mcp-rsv-data` behavior.

Use for:
- local/unpublished bases;
- native-query fallback;
- Windows COM connection scenarios.

Run isolated from the main Python process when appropriate.

### 3.7 Legacy 8.2 Data Plane

Optional/demand-driven:
- isolated process/service;
- GPL code does not enter ERP_MCP core;
- narrow read-only contract only.

### 3.8 Semantic Layer

Consumes normalized adapter operations and produces transport-independent domain results.

It owns:
- per-configuration mappings;
- canonical concepts;
- aggregation/orchestration;
- reconciliation provenance.

It must not:
- bypass source/company ACL;
- infer universal account/register semantics without a validated profile.

## 4. Trust boundaries

### TB-1 Client → ERP_MCP

Threats:
- forged identity;
- prompt/tool injection;
- oversized requests;
- arbitrary source enumeration.

Controls:
- OAuth validation;
- schema validation;
- registered IDs only;
- request/body limits;
- deny-by-default authorization.

### TB-2 ERP_MCP → Registry/Policy DB

Controls:
- runtime read-only registry grants;
- separate admin/migration credentials;
- parameterized SQL;
- append-only audit permissions.

### TB-3 ERP_MCP → Secret Provider

Controls:
- server-side secret resolution;
- no secret return to model;
- least-privilege service identity;
- rotation without changing source IDs.

### TB-4 Control Plane → Data Plane

Controls:
- authenticated/private internal channel where distributed;
- narrow operation allowlist;
- source endpoint supplied by control plane only;
- deadlines/byte/row/concurrency budget;
- correlation/provenance.

### TB-5 Data Plane → 1C

Controls:
- registered endpoint;
- TLS/private networking;
- read-only technical user;
- no redirects to arbitrary hosts;
- GET/read-only native query boundaries;
- source-specific circuit breaker.

## 5. Request sequence

```text
Client
  | MCP tool call
  v
Gateway/Auth
  | validate identity
  v
ACL/Policy
  | resolve source + company
  v
Rate/Query Budget
  |
  v
Capability Router
  | choose binding/profile
  v
Adapter Data Plane
  | read 1C
  v
Normalizer
  | bounded rows + provenance + warnings
  v
Semantic Layer (when domain tool)
  | map/aggregate
  v
Audit
  |
  v
Client result
```

A denial before adapter execution must not make a source request.

## 6. Capability routing

Desired profiles:

- `ODATA_V3`;
- `EXTENSION_HTTP`;
- `COM_BRIDGE`;
- `LEGACY_82_ISOLATED`;
- `UNSUPPORTED`.

Existing transitional profiles (`ODATA_JSON_V3`, `ODATA_ATOM_V3`, `HTTP_QUERY_FALLBACK`) may
remain during migration but should converge on adapter-binding semantics.

Routing inputs:
- source kind;
- live metadata/service behavior;
- adapter availability/health;
- configuration policy;
- licensing/deployment constraints;
- explicit operator configuration.

Routing never expands permissions.

## 7. Semantic architecture

```text
semantic tool
  ↓
semantic profile
  ↓
canonical operation plan
  ↓
normalized adapter operations
  ↓
1C source
```

Example:

```text
accounts_receivable_aging(company, as_of)
  ↓
profile "BP3-MD-client-A-v2"
  ↓
verified registers/accounts/dimensions
  ↓
register.query / entity.get
  ↓
normalize + aggregate
  ↓
reconciliation/provenance envelope
```

## 8. Multi-company model

Do not equate source and organization.

```text
Principal
  ├── Grant → Source A → Company A1
  │                  └→ Company A2
  └── Grant → Source B → Company B1
```

Cross-company queries:
- require explicit tool/policy support;
- cap fan-out;
- execute independently per source;
- preserve per-source failures;
- never silently omit failures from totals.

## 9. Failure model

### Source failure

Return source-scoped error/warning; do not mark gateway globally unready.

### DB/critical control dependency failure

Readiness fails; do not process requests that cannot be authorized/audited safely.

### Secret provider failure

Fail source request closed.

### Redis failure

Behavior must be configured/tested. For production, rate-limit safety must not silently become
unlimited access.

### Capability drift

Mark/re-discover binding; semantic profile may require revalidation if metadata fingerprint changed.

## 10. Deployment patterns

### Pattern A — private 1C network

Preferred:
- gateway/data-plane inside trusted/private network;
- external MCP exposure through approved HTTPS/tunnel/proxy;
- 1C endpoint remains private.

### Pattern B — hosted/public HTTPS OData

Allowed only with:
- registered fixed endpoint;
- TLS;
- dedicated read-only user;
- network and rate controls.

### Pattern C — Windows COM bridge

- isolated Windows host/process;
- dedicated service account;
- COM bridge health/reconnect;
- no credentials in process arguments/logs;
- private authenticated channel to control plane.

## 11. Future ERP/Ferma boundaries

ERP:
- call ERP reporting/API layer;
- preserve tenant/org RLS and signed scope;
- never connect through an unrestricted DB super-user.

Ferma:
- consume oracle/observer/comparator outputs;
- never feed live ERP/1C results into the expected/oracle computation path.

## 12. Forbidden architectures

- MCP → direct 1C SQL tables;
- model-supplied arbitrary URL → HTTP client;
- one unrestricted DB/1C admin account for every company;
- raw write-capable third-party MCP exposed through our gateway without an allowlist wrapper;
- silent fallback to insecure auth/dev mode;
- global accounting semantics based solely on Russian default chart-of-accounts assumptions;
- GPL/AGPL source copied into core without explicit licensing decision.

## 13. Admin Control Center extension

The browser administration plane is a same-origin UI/BFF layered beside, not inside, the MCP authorization model.

Browser -> OIDC Authorization Code + PKCE -> Admin BFF opaque HttpOnly session -> CSRF + admin audience/scope + platform-role authorization -> /admin/v1.

Read operations use the control-plane read model. Mutations use the separate business_ai_control_api credential. Source probes pass an egress allowlist and remain GET/HEAD-only. Admin audit/idempotency is persisted separately. MCP runtime remains separately authorized by onec:read, data ACL, and optional business capability policy.

Admin platform roles are fixed initial roles: PLATFORM_ADMIN, SOURCE_ADMIN, ACCESS_ADMIN, PROFILE_ADMIN and AUDITOR. They are independent of business roles such as ACCOUNTANT or EXECUTIVE.

Company-aware data access is exposed only through onec_company_read. It resolves the authorized company, checks business capability when enabled, requires acknowledged current metadata, selects a VALIDATED semantic profile/company-scope mapping, verifies the mapped company property in live metadata, then injects the company predicate before adapter execution.

The Admin probe uses a separate four-slot pool with a 45-second deadline and pins an approved
numeric IP with the original Host/TLS identity. Capability refresh uses that approved adapter.
Policy, idempotency outcome and success audit commit together; savepoints retain failed keys
and failure audit without committing failed policy writes. Runtime capability observations
retain the existing restricted runtime DB path and can be refreshed after an audit failure.

Admin lists use bounded offset pagination (default 50, maximum 200) and source filters.
Effective access is queried for one exact principal/source, with at most 200 companies and 50
grant evidence entries per company; all matching grants still determine deny precedence.
Group membership uses verified caller claims or a future trusted directory. Other subjects'
memberships remain unknown. Company navigation expansion is unavailable until separately proven.
