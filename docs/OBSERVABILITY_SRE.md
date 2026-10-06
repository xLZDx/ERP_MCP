# ERP_MCP Observability and SRE Contract

**Version:** 1.1
**Date:** 2026-10-06

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

### Semantic / DAD assurance

- tool executions by semantic profile;
- reconciliation status in validation environments;
- profile-unvalidated blocks/warnings;
- DAD rule executions by bounded rule ID/status;
- `PASS|FINDING|INCONCLUSIVE|EVIDENCE_REQUIRED|CAPABILITY_UNSUPPORTED|ERROR` counts;
- external-evidence parser failures/required-missing counts by bounded evidence class;
- reference/Ferma test level in validation evidence, never raw customer identifiers as metric labels.

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
  evidence.resolve      # when required
  dad.rule.evaluate     # when required
  audit.append
```

Sensitive query values should be omitted/redacted; fingerprints can correlate repeated shapes.
The current internal span implementation covers audit append and adapter calls with correlation ID,
duration, fixed semantic attributes and exception type only. It never records credentials, URLs,
query values, source/company IDs or response payloads.

## 5. Health/readiness

### Liveness

Process/event loop responsive.

### Readiness

Requires mandatory control dependencies needed for safe request processing.

A single customer 1C source being down must not make the whole service unready.

### Source health

Separate source-specific diagnostic state.

### Initial HTTP metrics implementation

P8 exposes bounded-cardinality HTTP request counters, in-flight gauge and latency histogram at
`/metrics`. Labels are limited to method, status and a fixed route class; source, company, subject,
tool arguments, URLs, and query values are never labels. The endpoint is disabled (404) unless
`BAG_METRICS_TOKEN` is configured with at least 32 bytes; scrapers send it as a bearer token. The
token must be held in the deployment secret store and rotated independently. Metrics are per-process
and reset on restart; they are not a durable audit or a substitute for database/audit monitoring.
The endpoint also exposes bounded operation and dependency counters. Tool names are restricted to
safe registered names; source IDs, company IDs, URLs, query values and subjects are never labels.

The operation allowlist is fixed to the registered MCP names plus the reserved internal `audit`
append operation; unknown alphanumeric identifiers also map to `other`, not new label series.
CI compares this allowlist to the decorated server tools. Dependency duration sum/count uses only
fixed dependency/outcome labels, rejects non-finite/non-numeric samples, and caps pathological
individual duration samples at one hour to prevent overflow. HTTP status labels accept only integer
100–599; malformed statuses map to 500 without changing downstream response messages. Trace span
names and tool/dependency/adapter/outcome values use fixed allowlists; unknown/free-text values
become `other`, never raw private data.

Audit operation outcomes are emitted AFTER the INSERT completes, not before. Failed or cancelled
append emits the original operation's error, reserved `tool="audit",outcome="error"` and
`dependency="audit",outcome="error"`; failures still propagate, never substitute a successful
answer. This wires the checked-in `ErpMcpAuditAppendErrors` selector to real append failure.
Actual PostgreSQL runtime-role tests verify successful append and readonly-transaction failure;
synthetic audit rows remain append-only/retained. Receiver delivery and complete production fault
rehearsal remain separate gates.

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

The checked-in Prometheus rules are in `deploy/alerts/prometheus.rules.yml`. They intentionally use
only route/status/outcome/tool labels from the bounded metrics contract; source IDs, company IDs,
subjects and query values are excluded.

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

### Measured disposable PostgreSQL pool benchmark

`python -m scripts.postgres_pool_benchmark --output <new-private-file>` creates a NEW loopback-only
PostgreSQL container (retained, never reused/deleted), then uses the production `Database` pool
factory and `FanoutExecutor` for 30/50/100/150 synthetic sources, three repetitions each. It runs
only fixed read-only transactions/`pg_sleep` queries, never registry/accounting data or 1C queries.
Authorization denial prevents acquisition; an independent synthetic source failure is explicit.
Artifacts include separate nearest-rank p50/p95/p99 distributions for pool acquisition, readonly
transaction, source total and batch, measured peak connections and Python allocated-memory peak.
Acquisition includes connection growth (not pure queue wait); the first size starts with a cold
pool, subsequent sizes use the grown pool. Pool sizes before/after distinguish these conditions.
Memory is tracemalloc allocation, NOT process RSS or container memory. Strict count/finite/order/
concurrency/readonly/isolation validation rejects invalid artifacts. CI retains scanned evidence.
This closes the measurement gap, not pilot SLO/production capacity, actual 1C load or DB-pool metrics.


## 12. Scope-freeze observability

Operational dashboards/status reports must distinguish:

- current committed frozen scope;
- completed evidence;
- locally actionable open work;
- external-only evidence blockers;
- recorded deferred lanes.

A deferred lane must never appear as active progress unless explicitly promoted by operator
rebaseline.

Engineering Command Center is a reporting surface, not the authority. Its status must be reconciled
against normative docs and exact CI/release evidence before closure claims.

## 13. Private reference/evidence telemetry

Access receipts (`detail_code=ACCESS_AUTHORIZED`) count successful audit appends, not successful
business operations. Completed-read audit statistics must exclude those receipts and correlate
completion by request ID. A receipt without completion indicates an interrupted/unfinished read;
investigate with the dependency and audit error signals, never convert it to business PASS.
If the pre-dispatch append fails, no adapter call occurs, the existing audit-error alert selector
is incremented and callers receive a sanitized error. Recovery requires restoring durable audit
storage and retrying with a new request; never bypass audit or replay a read as a mutation.

For `REFERENCE_TEST_BASE_A` and private external documents:

- logs use safe aliases/fingerprints, not raw private Drive links or customer identifiers;
- credentials never appear;
- raw document text is excluded from standard telemetry;
- test level and artifact digest are sufficient for evidence correlation;
- test-only write activity on a disposable RW clone must be explicitly labelled as test activity and
  must never be mixed with production read-only metrics.
