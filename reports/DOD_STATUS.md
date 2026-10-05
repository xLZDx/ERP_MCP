# Definition of Done status

Assessed against working changes at HEAD `3be80d981da03820e0b5bdc38dfd18fc7d26b070`.

`PARTIAL` means some implementation exists but mandatory evidence/behavior remains open. `NOT
STARTED` is used where implementation is still required before external evidence is relevant.

| Gate | Status | Current evidence / open work |
|---|---|---|
| D0 Documentation | PARTIAL | Normative set and requirements traceability exist; gap/status files created; implementation docs updated; command center carries progress through current HEAD. Close against exact release. |
| D1 Build/dependencies | PARTIAL | At HEAD, local Ruff, compileall, Bandit, pip-audit pass; 42 tests pass/2 skip locally (PostgreSQL test needs CI DB). CI 37355876333 passed all workflow steps on current HEAD; pytest reports 43 passed/1 skipped. |
| D2 Authentication | PARTIAL | RSA JWT positive/negative tests cover signature, issuer, audience, expiry, scope, subject and JWKS failure; framework-level resource-server behavior and live IdP evidence remain. |
| D3 Authorization | PARTIAL | Source subject/group ACL remains; company scope and deny precedence added; CI confirmed PostgreSQL role grants. PostgreSQL ACL test covering enumeration, unscoped denial, deny precedence and live revocation passed in run 37355876333. End-to-end company data reads intentionally not exposed. |
| D4 Secrets | PARTIAL | File/GCP abstractions and production env-secret prohibition exist; rotation and leakage evidence remain. |
| D5 Read-only | PARTIAL | GET/HEAD-only client; mutation/sidecar inventory evidence incomplete. |
| D6 SSRF/transport | PARTIAL | Registered source, HTTPS production and redirect/path checks exist; DNS rebinding/egress proof incomplete. |
| D7 Compatibility | PARTIAL | JSON/Atom probe and persisted fingerprint exist; drift lifecycle/fallback bindings incomplete. |
| D8 Data plane | PARTIAL | Basic read path only; approved upstream sidecar operations and parity tests remain. |
| D9 Accounting | NOT STARTED | Semantic layer not implemented; native 1C reconciliation not applicable yet. |
| D10 Multi-company | PARTIAL | Company table and scoped grants/list/resolve exist; transaction-isolated PostgreSQL ACL integration test passed in CI; three-source tests and bounded fan-out remain. |
| D11 Audit/provenance | PARTIAL | Append-only schema extended for request/company/adapter/policy/fingerprint/bytes/truncation; end-to-end field persistence and DB immutability tests remain. |
| D12 Observability | NOT STARTED | Normative contract only. |
| D13 Performance | PARTIAL | Basic response/row/timeout/rate bounds exist; load and capacity evidence absent. |
| D14 Resilience | PARTIAL | Readiness and idempotent GET retries exist; Redis semantics, circuit breaking and failure injection remain. |
| D15 Backup/restore | PARTIAL | Contract documented; automation and restore drill remain. |
| D16 Deployment | PARTIAL | Dockerfile and production contract exist; hardened production deployment evidence absent. |
| D17 Operations | NOT STARTED | Runbooks and ownership remain. |
| D18 Pilot | NOT STARTED | Local implementation and semantic gates remain before pilot evidence. |

No gate is declared PASS solely because normative documentation exists.
