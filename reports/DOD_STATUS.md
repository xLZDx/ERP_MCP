# Definition of Done status

Assessed 2026-10-06 against merged PR #1 (`8481c0e`) and local P4 work on
`phase/p4-semantic-accounting`. P4 changes are not yet hosted-CI verified.

`PARTIAL` means some implementation exists but mandatory evidence/behavior remains open. `NOT
STARTED` is used where implementation is still required before external evidence is relevant.

| Gate | Status | Current evidence / open work |
|---|---|---|
| D0 Documentation | PARTIAL | Normative set and requirements traceability exist; gap/status files created; implementation docs updated; command center carries progress through current HEAD. Close against exact release. |
| D1 Build/dependencies | PARTIAL | Current local Python suite: 67 passed/5 skipped; Ruff/compileall/Bandit pass. Exact pinned OData client 428 passed/1 skipped; metadata 53/53; sidecar 11/11; PostgreSQL integration 4/4; rebuilt image health smoke passed as UID 10001 with no published ports. Hosted CI for this batch pending. |
| D2 Authentication | PARTIAL | RSA JWT positive/negative tests cover signature, issuer, audience, expiry, scope, subject and JWKS failure; framework-level resource-server behavior and live IdP evidence remain. |
| D3 Authorization | PARTIAL | Source subject/group ACL remains; company scope and deny precedence added; CI confirmed PostgreSQL role grants. PostgreSQL ACL and runtime-role tests passed in runs 37355876333/37356701516. Admin-role positive/negative DML test passed CI run 37357432914. End-to-end company data reads intentionally not exposed. |
| D4 Secrets | PARTIAL | File/GCP abstractions and production env-secret prohibition exist; rotation and leakage evidence remain. |
| D5 Read-only | PARTIAL | Python transport remains GET/HEAD-only; sidecar exposes only upstream GET-backed query/key/count/register methods; mutation-shaped operation/method rejection covered by sidecar tests. Other adapter inventory and external zero-write proof remain. |
| D6 SSRF/transport | PARTIAL | Registered source, exact host:port allowlist in sidecar, production HTTPS, bearer hop and redirect/path checks; DNS rebinding/egress proof incomplete. |
| D7 Compatibility | PARTIAL | Existing JSON/Atom fingerprint/drift controls remain; migration 005 persists per-source register capability evidence. Exact-source metadata evidence gates method use; stale/missing confirmation denies. Hosted CI for this batch pending. |
| D8 Data plane | PARTIAL | Internal sidecar contract is documented and tested; pinned upstream routing implements query/key/count/constrained register reads; live register capability is revalidated before operation; DrCr unsupported negative and confirmed positive fixtures pass. First company-scoped canonical register-read path now gates on exact profile/capability. Hosted CI and real-source behavior remain. |
| D9 Accounting | PARTIAL | Source/company profile lifecycle requires explicit `CONFIRMED`/`HIGH` mapping, current capability/schema fingerprints and ten passing native-report cases; migration 008 stales a validated profile after mapping edits; migration 009 adds profile fingerprint to audit. A mapping-driven account balance/turnovers tool normalizes seven fields and has positive/negative no-dispatch tests. Other canonical tools and real native reconciliation remain. |
| D10 Multi-company | PARTIAL | Company table and scoped grants/list/resolve exist; transaction-isolated PostgreSQL ACL integration test passed in CI; three-source tests and bounded fan-out remain. |
| D11 Audit/provenance | PARTIAL | Append-only schema extended for request/company/adapter/policy/fingerprint/bytes/truncation; runtime-role `Audit.write` round-trip and update/delete denials passed CI 37357024926; MCP handler tests for success, ACL denial, Redis outage denial and adapter failure passed CI 37360482223. New SDK middleware assigns one context-isolated correlation UUID per inbound MCP message and reuses it for its audit writes; production persistence/trace propagation and complete provenance remain. |
| D12 Observability | NOT STARTED | Normative contract only. |
| D13 Performance | PARTIAL | Sidecar adds response/row/request/time/per-source concurrency bounds; load and capacity evidence absent. |
| D14 Resilience | PARTIAL | Sidecar timeout, disconnect abort and per-source circuit breaker tested locally; Redis fail-closed evidence in CI 37361430688. Broader gateway/data-plane fault injection remains. |
| D15 Backup/restore | PARTIAL | Contract documented; automation and restore drill remain. |
| D16 Deployment | PARTIAL | Rebuilt sidecar image starts healthy as UID 10001 with no published port; production HTTPS/token/allowlist contract documented. Hosted CI, SBOM/scans and deployment evidence remain. |
| D17 Operations | NOT STARTED | Runbooks and ownership remain. |
| D18 Pilot | NOT STARTED | Local implementation and semantic gates remain before pilot evidence. |

No gate is declared PASS solely because normative documentation exists.
