# ERP_MCP Definition of Done — 1C Production MVP

**Version:** 1.0  
**Date:** 2026-10-05

A production MVP is Done only when **all mandatory gates** pass for the exact release/environment.

## D0 — Documentation and traceability

- normative package is current;
- requirements/ADRs/DoD match implementation;
- PR/release identifies exact commit;
- known deviations/deferred work are listed;
- vendor provenance/license manifest is current.

## D1 — Build and dependency integrity

- clean reproducible build;
- Ruff/lint green;
- compile/type checks green;
- unit/contract tests green;
- dependency vulnerability audit green or explicitly accepted under governance;
- license policy tests green;
- container/image provenance recorded.

## D2 — Authentication

Evidence:
- missing token denied;
- invalid signature denied;
- expired token denied;
- wrong issuer denied;
- wrong audience denied;
- missing required scope denied;
- valid principal/client/groups resolved correctly.

## D3 — Authorization and isolation

- user sees only granted sources/companies;
- group grants work;
- expired/revoked grants deny immediately without restart;
- one principal cannot enumerate inaccessible source IDs;
- runtime DB role cannot create/change grants or source endpoints;
- source/company policy deny overrides allow.

## D4 — Secrets

- no production secrets in Git/history/artifacts/logs;
- production env-secret mode rejected;
- secret provider access is least privilege;
- rotation procedure tested;
- model-visible responses contain no credentials.

## D5 — Read-only guarantee

Mandatory:
- production MCP tool inventory contains no 1C mutation tools;
- internal adapter contract contains no mutation operation;
- modern OData data-plane exposes only approved reads;
- fallback/COM/native-query adapter has explicit read-only allowlist;
- tests prove POST/PUT/PATCH/DELETE or equivalent mutation path is unavailable;
- arbitrary code execution is not exposed.

## D6 — SSRF/transport safety

- caller cannot specify arbitrary host/URL;
- redirects cannot escape registered endpoint policy;
- HTTPS/private transport policy enforced;
- DNS/host protections verified;
- request/response byte and timeout limits verified.

## D7 — Compatibility routing

For each pilot source:
- capability handshake recorded;
- configuration-sensitive register operations have source-specific positive evidence (live metadata,
  safe probe or validated semantic profile); unsupported operations fail with
  `CAPABILITY_UNSUPPORTED` and persist negative evidence;
- metadata fingerprint recorded;
- adapter profile selected deterministically;
- unsupported capabilities fail explicitly;
- schema/capability drift is detectable;
- adapter version/SHA is attributable.

## D8 — Data-plane correctness

For approved operations:
- metadata search/describe;
- bounded query;
- entity-by-key;
- count;
- register query;
- paging/truncation;
- cancellation/timeout;
- retry behavior

all pass contract tests and real-source smoke tests where applicable.

## D9 — Accounting correctness

At least 10 representative accounting scenarios on a real synthetic/test 1C base:
- native 1C report/UI result captured;
- MCP/semantic result captured;
- reconciliation result PASS;
- discrepancy rules/tolerance documented;
- semantic profile and metadata fingerprint recorded.

No unresolved material accounting discrepancy.

## D10 — Multi-company operation

- at least three heterogeneous test sources with distinct ACLs;
- add source without code deploy;
- revoke source/grant without restart;
- source failure does not globally fail healthy sources;
- bounded cross-company operation/fan-out behavior verified;
- target 30–150 company operational workflow documented.

## D11 — Audit and provenance

For success, deny and failure paths:
- audit event exists;
- principal/client/tool/source/company recorded;
- query/result fingerprints/provenance recorded as designed;
- no secret/raw sensitive payload leakage;
- runtime cannot update/delete existing audit rows.

## D12 — Observability

- structured logs;
- request correlation;
- latency/error/rate metrics;
- adapter/source health;
- rate-limit/deny metrics;
- alert thresholds/runbook links;
- no credentials or raw business payloads in standard telemetry.

## D13 — Performance and resource limits

Before GO:
- representative load test completed;
- p50/p95/p99 recorded;
- concurrency and per-source limits validated;
- no unbounded memory/result growth;
- large register/query behavior is capped;
- Redis/Postgres pool behavior under load verified.

Targets are approved from measured results, not guessed.

## D14 — Resilience

- Postgres unavailable -> readiness fails safely;
- Redis unavailable -> defined fail-closed/fail-safe behavior validated;
- one 1C source unavailable -> source-scoped failure;
- retry/circuit breaker behavior tested;
- process restart does not lose authoritative registry/access state.

## D15 — Backup, restore and rollback

- PostgreSQL backup/PITR policy configured;
- restore test performed;
- deployment rollback documented/tested;
- migration rollback/restore path documented;
- source/secret rollback procedures documented;
- no destructive recovery step executed without explicit approval.

## D16 — Production deployment

- production config passes fail-closed validation;
- non-root container;
- TLS/ingress/private connectivity configured;
- DB roles split;
- secret provider configured;
- health/readiness integrated;
- deployment manifest/version pinned.

## D17 — Operations and support

- owner/on-call responsibility defined;
- source onboarding/offboarding runbook;
- secret rotation runbook;
- incident response;
- adapter/source diagnostic procedure;
- capability refresh/schema drift procedure;
- audit investigation procedure.

## D18 — Pilot closure

- controlled pilot users/sources completed;
- no write side effects;
- accounting reconciliation remained valid;
- audit reviewed;
- high/blocker risks closed or explicitly accepted;
- exact production release SHA approved.

## Final terminal condition

**PRODUCTION GO** only when D0–D18 mandatory gates are green for the target environment.

Allowed intermediate labels:
- `DEV READY`
- `INTEGRATION READY`
- `PILOT READY`
- `PRODUCTION GO`

Do not call a release “production-ready” if it has not reached at least `PILOT READY` with all
pre-pilot mandatory gates satisfied.
