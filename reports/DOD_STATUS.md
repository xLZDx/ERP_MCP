# Definition of Done status

Assessed against implementation commit `133f640b565e2032748125d58cd65e30d75e52ec` and CI run
`37361430688` (`57 passed, 1 skipped`).

`PARTIAL` means some implementation exists but mandatory evidence/behavior remains open. `NOT
STARTED` is used where implementation is still required before external evidence is relevant.

| Gate | Status | Current evidence / open work |
|---|---|---|
| D0 Documentation | PARTIAL | Normative set and requirements traceability exist; gap/status files created; implementation docs updated; command center carries progress through current HEAD. Close against exact release. |
| D1 Build/dependencies | PARTIAL | Local Ruff and pytest pass; current local suite is 53 passed/5 skipped (PostgreSQL tests need CI DB). CI 37361430688 passed all workflow steps; pytest reports 57 passed/1 skipped. |
| D2 Authentication | PARTIAL | RSA JWT positive/negative tests cover signature, issuer, audience, expiry, scope, subject and JWKS failure; framework-level resource-server behavior and live IdP evidence remain. |
| D3 Authorization | PARTIAL | Source subject/group ACL remains; company scope and deny precedence added; CI confirmed PostgreSQL role grants. PostgreSQL ACL and runtime-role tests passed in runs 37355876333/37356701516. Admin-role positive/negative DML test passed CI run 37357432914. End-to-end company data reads intentionally not exposed. |
| D4 Secrets | PARTIAL | File/GCP abstractions and production env-secret prohibition exist; rotation and leakage evidence remain. |
| D5 Read-only | PARTIAL | GET/HEAD-only client; mutation/sidecar inventory evidence incomplete. |
| D6 SSRF/transport | PARTIAL | Registered source, HTTPS production and redirect/path checks exist; DNS rebinding/egress proof incomplete. |
| D7 Compatibility | PARTIAL | JSON/Atom probe and persisted fingerprint exist; sticky drift/ack lifecycle and read fail-closed gate passed CI 37358947196; unsupported behavior, explicit-only fallback selection and fail-closed no-network behavior for the unimplemented fallback passed CI 37360919808. Fallback bindings remain incomplete. |
| D8 Data plane | PARTIAL | Basic read path only; approved upstream sidecar operations and parity tests remain. |
| D9 Accounting | NOT STARTED | Semantic layer not implemented; native 1C reconciliation not applicable yet. |
| D10 Multi-company | PARTIAL | Company table and scoped grants/list/resolve exist; transaction-isolated PostgreSQL ACL integration test passed in CI; three-source tests and bounded fan-out remain. |
| D11 Audit/provenance | PARTIAL | Append-only schema extended for request/company/adapter/policy/fingerprint/bytes/truncation; runtime-role `Audit.write` round-trip and update/delete denials passed CI 37357024926; MCP handler tests for success, ACL denial, Redis outage denial and adapter failure passed CI 37360482223. Company/request correlation and complete production provenance remain. |
| D12 Observability | NOT STARTED | Normative contract only. |
| D13 Performance | PARTIAL | Basic response/row/timeout/rate bounds exist; load and capacity evidence absent. |
| D14 Resilience | PARTIAL | Readiness and idempotent GET retries exist; fake Redis failure plus real Redis-client TCP outage both fail closed and passed CI 37361430688. Server-level Redis outage injection, circuit breaking and broader failure injection remain. |
| D15 Backup/restore | PARTIAL | Contract documented; automation and restore drill remain. |
| D16 Deployment | PARTIAL | Dockerfile and production contract exist; hardened production deployment evidence absent. |
| D17 Operations | NOT STARTED | Runbooks and ownership remain. |
| D18 Pilot | NOT STARTED | Local implementation and semantic gates remain before pilot evidence. |

No gate is declared PASS solely because normative documentation exists.
