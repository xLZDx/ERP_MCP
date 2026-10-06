# ERP_MCP Test and Verification Strategy

**Version:** 1.1
**Date:** 2026-10-06

## 1. Verification principle

Correct transport behavior and correct accounting meaning are separate verification problems.

A release must verify:
1. control-plane security;
2. adapter/protocol behavior;
3. source compatibility;
4. accounting semantic correctness;
5. DAD rule/evidence correctness for frozen business-assurance scope;
6. operations/resilience.

The active scope freeze also requires every new test/work item to trace to an existing frozen
requirement/gate; tests do not create new product scope by themselves.

## 2. Test pyramid

### L0 — static/governance

- Ruff/lint;
- compile/type checks;
- Bandit/security static checks;
- dependency vulnerability scan;
- vendor/license intake tests;
- documentation/reference consistency where automatable.

### L1 — unit and deterministic Fake1C

Mandatory on every PR:
- auth/settings fail-closed;
- source URL/policy;
- secrets path handling;
- metadata parsing;
- capability routing;
- JSON/Atom normalization;
- adapter envelope validation;
- rate/audit helpers;
- vendor policy.

Fake1C must remain read-only.

### L1.5 — upstream parity/contract

For reused OData/register logic:
- run/port applicable upstream tests;
- preserve exact pinned upstream version;
- add our wrapper contract tests;
- verify no write operation is surfaced.

Examples:
- query builder validation;
- filter escaping;
- OData v3 literal/date handling;
- register virtual tables;
- byte/row truncation.

### L2-A — Ferma controlled synthetic on real 1C

Purpose: controlled completeness and independent expected/oracle.

Verify:
- deterministic Ferma package/profile/seed/scenario digest;
- test-only seeder target guard and idempotency;
- normal 1C business-document posting;
- real metadata/capability/register behavior;
- native 1C observations;
- normal read-only ERP_MCP observations;
- independent oracle comparison;
- multi-company and rare edge cases.

### L2-B — private real-reference 1C

Purpose: real configuration fidelity and known-error regression.

Use an immutable private golden source and disposable read-only clone.

Verify:
- exact platform/configuration/extensions;
- metadata fingerprint;
- capability profile;
- OData/COM parity where available;
- source-specific semantic mappings;
- native 1C reports;
- accountant-selected DAD checks;
- private invoice/evidence regression cases.

Do not commit raw reference data/credentials/private source links.

Every L2 run captures:
- test level;
- platform/configuration;
- extensions;
- metadata fingerprint;
- reference/synthetic artifact digest;
- code/adapters SHA;
- semantic/rule-pack version;
- evidence fingerprints.

### L3 — server-mode production parity

Same business scenarios against server-mode deployment and production-like networking/auth.

Verify:
- concurrency;
- timeouts;
- connection pool;
- long-running register behavior;
- network failures;
- load.

## 3. Security tests

Mandatory negative cases:
- missing/invalid/expired token;
- wrong issuer/audience/scope;
- inaccessible source ID;
- revoked grant;
- disabled source;
- arbitrary URL attempt;
- redirect attempt;
- oversized body/response;
- secret leakage checks;
- write verb/path attempt;
- mutation operation attempt through sidecar;
- audit mutation attempt;
- runtime DB privilege escalation attempt.

## 4. Adapter tests

Each adapter implementation must pass the same normalized contract suite:
- health;
- capabilities;
- metadata search/describe;
- query;
- get;
- count;
- register query where supported;
- timeout;
- cancellation;
- truncation;
- source-scoped error normalization.

Capability-unsupported operations must fail explicitly, not silently degrade to incorrect data.

## 5. Accounting reconciliation

Minimum release set: 10 representative scenarios.

Each case contains:
- business question;
- parameters/period;
- semantic profile;
- source/company;
- native 1C report/UI method;
- expected values;
- tolerance;
- ERP_MCP result;
- PASS/FAIL/INCONCLUSIVE;
- evidence artifact/reference.

Suggested/frozen domains include:
- receivable/payable aging;
- partial payment;
- overpayment/advance;
- unposted document;
- returns/credit notes;
- VAT treatment where validated;
- backdated document;
- duplicate/same-name counterparty anomaly;
- cash vs bank;
- opening/turnover/closing balance;
- accountant-selected 211/217/221/523/224/521/241 checks;
- invoice/PDF mismatch classes;
- production-cost/month-close rules;
- P&L/CF/BS once mapped;
- external-evidence reconciliations returning explicit evidence states.

## 6. Schema drift tests

When metadata fingerprint changes:
- detect drift;
- compare affected entities/properties/registers;
- invalidate/review semantic profile where required;
- rerun impacted reconciliation cases.

Do not keep using a semantic profile silently after incompatible drift.

## 7. Multi-company tests

- distinct principals with disjoint companies;
- group-based grants;
- one source containing multiple companies;
- source-wide vs company-specific grant;
- revocation;
- one source failure in a fan-out;
- bounded fan-out and partial-failure envelope.

## 8. Performance/load

Measure, do not guess.

Record:
- gateway overhead;
- end-to-end latency;
- p50/p95/p99;
- throughput;
- DB/Redis pool saturation;
- adapter concurrency;
- 1C response behavior;
- memory/CPU;
- response truncation frequency.

Test workloads:
- metadata-heavy;
- small entity reads;
- register aggregation;
- cross-company fan-out;
- failing/slow source.

## 9. Resilience/failure injection

At minimum:
- Postgres down;
- Redis down;
- secret provider failure;
- IdP/JWKS failure;
- 1C timeout;
- 1C 401/403;
- 1C 429/5xx;
- malformed metadata;
- schema drift;
- adapter process crash;
- COM disconnect/reconnect.

Expected behavior must be documented and asserted.

## 10. Evidence quality

A test claim must identify:
- exact commit SHA;
- exact dependency/adapter versions;
- environment;
- source/snapshot;
- metadata fingerprint if relevant;
- command/run ID;
- result.

Screenshots/manual statements alone are supporting evidence, not a substitute for machine-checkable
test output where automation is possible.

## 11. Test data policy

- no production/customer data in repository/public CI;
- synthetic identities and transactions only;
- secrets supplied out-of-band;
- snapshots with licensed 1C binaries/data are not committed publicly;
- private real-reference artifacts remain in private/local testbed storage and are referred to by
  safe aliases/hashes;
- test-only write credentials are separate from read-only observation credentials;
- Ferma expected/oracle artifacts are not input to the seeder or actual-side computation.

## 12. Release regression

Before production GO:
- complete CI;
- L2 accounting suite;
- L3 smoke/load subset;
- security negative suite;
- migration/restore evidence;
- source onboarding/offboarding smoke.

No unresolved FAIL can be reclassified as PASS without a documented corrected expectation or code fix.

## Admin Control Center verification extension

Mandatory automated coverage includes distinct admin OAuth audience/scope negatives; OIDC state/nonce/PKCE and opaque-session tests; cookie CSRF enforcement and no browser token persistence; platform-role/source-boundary tests; exact-ID revoke, optimistic concurrency and idempotency; append-only admin audit and least-privilege business_ai_control_api; source-probe host/CIDR negative cases; source/company registration separation; business role/capability deny precedence; and company-aware read denial before adapter with validated live-metadata scope mapping.

The Admin Control Center branch also runs the entire existing baseline suite to prove the extension does not weaken the read-only 1C data plane.

The role matrix exercises every restricted lifecycle endpoint across five platform roles and
no role, plus delegated boundaries. PostgreSQL tests use the control role for replay/conflict,
concurrent requests, exact revoke, role/capability lifecycle, 151-company explanation and
privilege rejection. `python scripts/verify_admin_ui.py` runs in CI with synthetic same-origin
APIs: retry identity, CSRF, navigation, escaping, dialog focus, narrow layout, 200% zoom and
disabled enforcement/step-up controls. It does not replace a real IdP/1C pilot.

CI enables disposable Redis for real ASGI/OIDC callback routes, opaque sessions, CSRF, grant
write/replay and logout. The IdP endpoint/keys are synthetic; DB, Redis and routing are real.
Negatives additionally cover key removal after JWKS TTL, malformed/overage groups, delegated
connection repointing, numeric company-ID coercion, encoded/oversized responses and profile
invalidation after connection changes.
