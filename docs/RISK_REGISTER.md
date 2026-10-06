# ERP_MCP Risk Register

**Version:** 1.1
**Date:** 2026-10-06

Ratings: Probability (P) / Impact (I): Low, Medium, High, Critical.

| ID | Risk | P | I | Primary mitigation | Closure evidence |
|---|---|---:|---:|---|---|
| R-01 | Correct transport, wrong accounting meaning | High | Critical | semantic profiles + native 1C reconciliation | >=10 cases PASS |
| R-02 | Configuration/schema drift invalidates mappings | High | High | metadata fingerprint + profile invalidation/retest | drift test/evidence |
| R-03 | Write capability leaks from upstream library | Medium | Critical | narrow read-only wrapper/tool inventory tests | mutation-negative suite |
| R-04 | Arbitrary URL/SSRF through tool args/config | Medium | Critical | server-side source registry, URL policy, redirect protection | security tests |
| R-05 | Credential/token leakage to model/logs | Medium | Critical | secret refs/provider, redaction, log policy | leak tests/log review |
| R-06 | Cross-company authorization leak | Medium | Critical | source/company ACL, deny-first policy, negative tests | isolation suite |
| R-07 | Runtime DB role can alter policy | Low | Critical | separate owner/admin/runtime roles | privilege test |
| R-08 | Audit can be modified/deleted | Low | High | append-only trigger/privileges | mutation test |
| R-09 | Upstream dependency/API instability (0.x) | High | High | exact pin, wrapper contract, parity tests | upgrade gate |
| R-10 | GPL/AGPL/license contamination | Medium | High | intake manifest + CI license modes + isolation | vendor-policy tests |
| R-11 | Old 1C unsupported in production | Medium | High | capability routing + isolated fallback | source handshake |
| R-12 | COM bridge operational fragility | Medium | High | isolated Windows service, health/reconnect/runbook | fail/reconnect test |
| R-13 | 1C slow query overload | High | High | query/row/byte/timeout/concurrency caps, register aggregation | load tests |
| R-14 | Long OData URL/filter failures | Medium | Medium | typed builder, get-by-key, batching limits | upstream parity tests |
| R-15 | Date/timezone conversion changes numbers/periods | Medium | High | explicit source timezone/profile and upstream date tests | boundary tests |
| R-16 | Large ValueStorage/text blows result budget | Medium | High | field/response byte caps, projection guidance | size tests |
| R-17 | Redis outage removes rate protection | Low | High | defined fail-safe/closed mode | failure injection |
| R-18 | Postgres outage prevents safe authorization/audit | Low | Critical | readiness/fail closed, backups/PITR | fail/restore test |
| R-19 | IdP/JWKS outage blocks valid users | Medium | High | cache/timeout/runbook, no insecure bypass | failure test |
| R-20 | Audit volume/storage growth | Medium | Medium | metrics, partition/retention design after policy approval | capacity plan |
| R-21 | Public repository receives real 1C data | Low | Critical | synthetic-only policy, secret/data scans | CI/review |
| R-22 | Source failure poisons cross-company aggregate | Medium | High | partial-failure envelope, no silent omission | fan-out test |
| R-23 | Semantic preset mistaken for universal mapping | High | Critical | presets are candidates; validation required | profile status gate |
| R-24 | Direct 1C SQL integration bypasses semantics/rights | Low | Critical | ADR/prohibition/code review | architecture gate |
| R-25 | Production called ready based only on unit tests | Medium | Critical | DoD status levels + reconciliation/pilot gates | release evidence |
| R-26 | Secret rotation breaks many sources simultaneously | Medium | High | staged rotation, source health, rollback | rotation drill |
| R-27 | Adapter compromise accesses more sources than required | Low | Critical | per-source credentials/scoping, network isolation | threat review |
| R-28 | Unbounded 150-company fan-out exhausts 1C/gateway | Medium | High | explicit fan-out cap/batching/concurrency budget | load test |
| R-29 | Migration changes privilege/isolation semantics | Low | Critical | migration governance + previous-version CI | migration evidence |
| R-30 | Legacy adapter returns inconsistent normalized shape | Medium | High | common adapter contract suite | contract suite |
| R-31 | Scope creep prevents completion of already accepted MVP/DAD scope | High | High | active operator scope freeze; every task traces to frozen requirement/gate | scope-freeze review |
| R-32 | External evidence document injects instructions or is associated with wrong company | Medium | Critical | untrusted-data handling, bounded parser, fingerprint/provenance, explicit source/company binding | evidence-plane security tests |
| R-33 | Private real-reference 1C/customer artifacts leak into public repo/CI | Low | Critical | private storage, aliases/hashes only, pre-commit/review scan | public/private evidence review |
| R-34 | Ferma oracle becomes correlated with 1C/ERP_MCP actual and creates false green | Medium | Critical | import/data-flow isolation, seeder cannot read expected results, independent observers | oracle-independence architecture tests |
| R-35 | Test-only write seeder or historical R/W helper becomes reachable from production MCP | Low | Critical | separate package/credential/target marker, production inventory negative tests | production tool/package inventory test |

## Risk acceptance

A Critical/High risk cannot be silently deferred.

For production GO it must be:
- mitigated with evidence; or
- explicitly accepted by the owner with scope, expiry/review date and compensating controls.

Risk acceptance does not override a non-waivable security/read-only invariant.
