# ERP_MCP Observability and SRE Contract

**Version:** 1.0  
**Date:** 2026-10-05

## 1. Objectives

Operators must be able to answer:
- Is the gateway healthy?
- Is authorization/policy working?
- Which source/adapter is failing?
- Is latency in ERP_MCP or 1C?
- Are users being rate-limited/denied?
- Did schema/capability drift occur?
- Which release/adapter produced a result?
- Can the service be rolled back safely?

## 2. Structured logs

Every request log should include:
- timestamp;
- request/correlation ID;
- operation/tool;
- outcome/status;
- subject fingerprint or approved stable identifier;
- client ID;
- source/company IDs when authorized;
- adapter kind/version;
- duration;
- rows/bytes/truncated;
- error code.

Must not include:
- passwords/tokens;
- raw Authorization headers;
- secret references where unnecessary;
- full raw accounting payloads;
- unredacted sensitive free text by default.

## 3. Metrics

### Gateway

- requests total by tool/outcome;
- request duration;
- active requests;
- authentication failures;
- authorization denies;
- rate-limit events;
- response bytes/rows/truncation;
- internal errors.

### Registry/data stores

- DB pool usage/wait;
- DB errors;
- Redis errors/latency;
- audit insert failures.

### Source/adapter

- source requests;
- source latency;
- source failures by class;
- timeouts/retries;
- circuit state;
- adapter process health;
- capability refresh/drift;
- metadata fingerprint change.

### Semantic

- tool executions by semantic profile;
- reconciliation status in validation environments;
- profile-unvalidated blocks/warnings.

## 4. Traces

Trace spans should cover:

```text
mcp.request
  auth.verify
  acl.resolve
  rate.check
  capability.route
  secret.resolve
  adapter.call
    upstream.1c
  semantic.transform
  audit.append
```

Sensitive query values should be omitted/redacted; fingerprints can correlate repeated shapes.

## 5. Health/readiness

### Liveness

Process/event loop responsive.

### Readiness

Requires mandatory control dependencies needed for safe request processing.

A single customer 1C source being down must not make the whole service unready.

### Source health

Separate source-specific diagnostic state.

## 6. Service objectives

Initial production objectives must be set from measured pilot data. Before measurements, use
engineering objectives rather than false guarantees.

Minimum release expectations:
- no unbounded request duration;
- all operations have explicit deadline;
- healthy-source availability is not coupled to unrelated failed sources;
- authorization/audit critical failures fail safely.

After pilot, record approved SLOs here with measurement method and error budget.

## 7. Alert classes

### P1 / critical

Examples:
- auth validation globally broken;
- audit writes failing while requests would otherwise proceed;
- widespread unauthorized access indication;
- secret leakage indication;
- production write path detected.

### P2 / high

- DB/Redis unavailable;
- high gateway 5xx;
- multiple source circuits open;
- adapter crash loop;
- severe latency saturation.

### P3 / source/customer

- one source unavailable;
- credential expiry;
- schema drift;
- semantic profile invalidated.

## 8. Runbooks

Required before production GO:
- gateway not ready;
- DB unavailable/restore;
- Redis failure;
- IdP/JWKS failure;
- source 401/403;
- source timeout/5xx;
- secret rotation;
- schema drift;
- adapter crash;
- COM reconnect;
- audit investigation;
- rollback;
- source onboarding/offboarding.

## 9. Rollback

A deployment rollback must restore:
- application version;
- compatible schema/application combination;
- adapter versions;
- configuration.

A rollback must not silently restore revoked user access or old credentials.

Database destructive rollback is never assumed; use forward-compatible migrations or backup/PITR
under explicit governance.

## 10. Backup/restore

Durable assets:
- PostgreSQL registry/policy/audit/reconciliation data;
- IdP configuration;
- secret store metadata/versions;
- deployment configuration;
- semantic profiles.

Require a restore drill before production GO.

## 11. Capacity management

Track:
- number of active sources/companies;
- metadata size;
- audit growth;
- request concurrency;
- adapter/process count;
- cross-company fan-out;
- 1C-specific throttling.

Capacity increase must preserve bounded concurrency. “150 companies” does not mean “150 simultaneous
unbounded queries”.
