# ERP_MCP implementation gap analysis

Assessment date: 2026-10-05  
Implementation assessed through CI-tested commit `77a12389dd3e437ef54c173d6581232bcad8cff8`
(the following status-report commit is documentation-only).
Branch: `bootstrap/1c-day1-production`  
Method: code/schema/tests/documents inspected against `docs/MASTER_PLAN.md`,
`docs/DEFINITION_OF_DONE.md`, and `docs/REQUIREMENTS_TRACEABILITY.md`.

Status meanings: **DONE** means implementation and required evidence both exist; **PARTIAL** means
some implementation exists but closure evidence or requirements are missing; **NOT STARTED** means
no meaningful implementation exists; **BLOCKED_EXTERNAL** means the specific remaining proof needs
an external/operator-controlled environment. A planned feature is not counted as done because its
contract is documented.

## Bootstrap snapshot

- `origin/main`: `a6bb75294578067fb23792f4dd2ceb8f17ddf673`; this commit has been merged into the
  implementation branch to resolve the README conflict before merge.
- Working HEAD at latest verified implementation: `77a12389dd3e437ef54c173d6581232bcad8cff8`.
- PR #1: OPEN, `bootstrap/1c-day1-production` → `main`.
- CI: runs `37356469102` and `37356471488` passed after main synchronization; commit `1590b89` passed
  run `37356701516`; implementation `da7a25ea453e776d5f46cdefee9673e244ca2d94` passed run
  `37357024926` (`44 passed, 1 skipped`), including PostgreSQL company ACL, runtime-role DML and
  `Audit.write` provenance round-trip. Current implementation `77a12389dd3e437ef54c173d6581232bcad8cff8`
  passed run `37357432914` (`45 passed, 1 skipped`), including admin-role positive/negative SQL.
- No additional worktrees were listed. Existing workspace instruction files were preserved.
- Local source and migration files show a small FastAPI/MCP control-plane prototype, PostgreSQL
  registry/grants/audit, Redis rate limits, file/env/GCP secrets, Fake1C, and a JSON/Atom OData probe
  and basic read client. `onec_http_query` currently fails explicitly; ERP/Ferma adapters are
  placeholders.
- Local Python dependencies, DB/Redis runtime state, and real 1C availability have not yet been
  established.

## Master Plan P0–P9

| Phase | Status | Existing implementation/evidence | Missing work, tests, or evidence | DoD |
|---|---|---|---|---|
| P0 Documentation freeze | PARTIAL | Normative v1.0 package, index, six ADRs, traceability, package test; root command center now copied | Reconcile the supplied copy with the in-repo generated command center; documentation test suite and current HEAD CI evidence | D0, D1 |
| P1 Control plane | PARTIAL | Auth, registry, audit, rate-limit and secret-provider modules; migrations 001–003; company upsert/scoped allow-deny grants; company list/resolve; audit provenance fields; versioned migration runner; CI DB privilege checker; RSA JWT positive/negative and Redis fail-closed tests; CI 37357432914 green; PostgreSQL company ACL, runtime/admin-role DML and audit writer provenance round-trip passed | company-aware business query adapter; audit success/denial-path provenance tests; production role/runbook evidence; Redis outage integration proof | D2–D6, D10–D11, D14 |
| P2 Capability router | PARTIAL | `compatibility.py`, live metadata probe, JSON/Atom detection, SHA fingerprint and persistence; Fake1C JSON/Atom | Normalized adapter bindings; fallback/COM/legacy routes; drift lifecycle and adapter SHA; deterministic unsupported/fallback/drift tests | D7 |
| P3 Modern OData data plane | NOT STARTED | Lightweight Python GET/HEAD client and bounded generic read | Integrate pinned `hacker-cb/1c-odata` sidecar; typed query, get/count/register contract; response shaping/cancellation/concurrency/circuit breaker; locks, upstream parity and container integration tests | D1, D5–D8, D13–D14, D16 |
| P4 Semantic accounting | NOT STARTED | Documentation and candidate upstream inventory only | Company/adapter/semantic/reconciliation schema; profile lifecycle; transport-neutral semantic tools and provenance; deterministic synthetic business cases | D8–D9, D11 |
| P5 Real 1C and reconciliation | PARTIAL | L1 Fake1C, optional integration-test stub, seed/snapshot specs and 10 scenario definitions | Executable deterministic seed/snapshot workflow and captured results; no actual L2/L3 connection or native-report reconciliation evidence recorded | D7–D10, D18 |
| P6 Extension/COM fallback | NOT STARTED | Pinned MIT upstream and documented isolation plan | Isolated adapter/service, authenticated internal contract, health/reconnect, read allowlist, Windows runbook and contract tests | D5–D8, D12, D14, D16–D17 |
| P7 Legacy 8.2 | DEFERRED_NOT_REQUIRED_FOR_MODERN_MVP | GPL project identified and isolation rule documented; no current 8.2 target known | No work until a real target requires it; verify target requirement during onboarding | D7 if applicable |
| P8 Production hardening | PARTIAL | Basic `/healthz`/`/readyz`, container, settings limits, source HTTP retries, simple runtime dependency checks | Structured logs/correlation/metrics/traces; circuit breaker; load/performance/fan-out; SBOM and image/dependency scans; backup/restore; operational runbooks and drills | D1, D12–D17 |
| P9 Pilot and GO | NOT STARTED | Acceptance gates and deployment contract documented; no pilot evidence in repository | Complete local implementation first; then determine target IdP/secrets/network/1C/users and gather audit, reconciliation and pilot evidence | D0–D18 |

P10 ERP/Ferma is outside the current 1C MVP terminal condition and remains reserved.

## DoD D0–D18

| Gate | Status | Evidence present | Remaining closure |
|---|---|---|---|
| D0 Documentation/traceability | PARTIAL | Baseline/index/traceability plus this initial gap report | Keep report and command center synchronized; close drift and attach evidence to exact release |
| D1 Build/dependency integrity | PARTIAL | `pyproject.toml`, GitHub CI; CI 37356701516 passed all steps on implementation commit; local Ruff/compileall/Bandit/pip-audit pass | Install locked/reproducible dependencies; license/container evidence; no dependency lock currently established |
| D2 Authentication | PARTIAL | JWT verifier checks signature, issuer, audience, exp/iat/sub/scope; positive/negative RSA tests and JWKS failure test | Framework-level resource-server behavior, bounded cache/network behavior and live IdP evidence |
| D3 Authorization/isolation | PARTIAL | Per-source subject/group and company grants, deny precedence, expiry/revocation filters; company-only grants cannot authorize unscoped source reads; runtime/admin-role DML integration passed CI 37357432914; DB role grants checked in CI | company-filtered business-data adapter; three-source isolation |
| D4 Secrets | PARTIAL | ENV/FILE/GCP provider abstraction; production disallows ENV mode | Secret access/rotation/leak evidence and safer source onboarding/runtime secret handling tests |
| D5 Read-only | PARTIAL | Read client implements GET/HEAD only; one structural test exists | Verify all adapter/tool inventories and fallback boundary with negative mutation tests |
| D6 SSRF/transport | PARTIAL | Registered-source routing, URL/path checks, redirects disabled, production HTTPS settings | DNS/IP rebinding and egress policy proof; redirect and oversized request tests; endpoint validation parity for admin paths |
| D7 Compatibility | PARTIAL | JSON/Atom metadata probe and persisted fingerprint/profile | Drift detection and invalidation; configured fallback route lifecycle and adapter provenance |
| D8 Data-plane correctness | PARTIAL | Basic entity read and Fake1C metadata/entities | Upstream OData engine operations, typed validation, get/count/register, paging/cancel/parity/real-source tests |
| D9 Accounting correctness | NOT STARTED | Scenario catalog and target protocol documented | Implement semantic layer, then reconcile >=10 cases against a real synthetic 1C instance |
| D10 Multi-company | PARTIAL | Distinct company/source registry; scoped allow/deny list/resolve; PostgreSQL ACL integration passed CI 37355876333 | Three-source isolation and bounded fan-out evidence; company-filtered business adapter |
| D11 Audit/provenance | PARTIAL | Append-only trigger; schema fields for request/correlation, company, adapter/profile/policy fingerprints, bytes/truncation; `Audit.write` field persistence and runtime-role append-only assertions passed CI 37357024926 for one error event | Verify success/denied-path field population and all values emitted by tool handlers |
| D12 Observability | NOT STARTED | Contract in docs only | Structured telemetry, metrics/traces/alerts, source health and leakage tests |
| D13 Performance/limits | PARTIAL | Basic HTTP timeout, response byte cap, rows/filter and Redis per-tool rate limit settings | Load test, p50/p95/p99, per-source/principal concurrency, fan-out, pool saturation and memory evidence |
| D14 Resilience | PARTIAL | DB/Redis readiness, selected HTTP retries | Defined Redis outage semantics, source isolation/circuit breaker, secret/IdP/adapter failure injection |
| D15 Backup/restore/rollback | PARTIAL | PostgreSQL backup/PITR and rollback contract in docs | Implement operator automation and run a restore drill in an available DB/deployment environment |
| D16 Production deployment | PARTIAL | Dockerfile, production env template and deployment contract | Hardened image/non-root proof, TLS/proxy/network, actual role/secret setup and deploy smoke |
| D17 Operations/support | NOT STARTED | Operational expectations listed in SRE docs | Actionable runbooks, ownership/on-call and onboarding/offboarding/rotation/drift procedures |
| D18 Pilot closure | NOT STARTED | No pilot artifacts found | Exact release pilot, real users/sources, reconciliation, zero-write and audit review |

## Requirements traceability summary

The requirements matrix already maps FR-A1–FR-F1 and NFR-S1–NFR-P2/COR-1–COR-2/OPS-1–OPS-2 to
design and DoD. The implementation gaps are concentrated in FR-A2 company scope, FR-C2 drift, FR-D2
register reads, FR-E1 semantic tools, FR-F1 full audit provenance, plus NFR-R2/NFR-O1/NFR-O2/NFR-P1
and real evidence for COR-1. P1 company authorization, migration/privilege proof, and audit
provenance are the first software closure targets.

## First implementation target

Start P1 with additive database and test changes for explicit company scopes and complete audit
provenance. Maintain source-wide access compatibility, make company-specific grants narrower, and
preserve append-only audit and current callers. Do not expose company-scoped business reads until
the authorization contract can be enforced end-to-end.

## External evidence to determine after local work

- Real 1C platform/license, synthetic information base and native report/UI access (D9, P5).
- Production IdP, secret provider, DNS/TLS/private network and pilot operators (D2/D4/D16/D18).
- Deployed PostgreSQL backup/PITR and restore target (D15).

No external blocker is terminal while independent software, local tests, automation, and runbooks
remain unfinished.
