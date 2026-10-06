# Definition of Done status

Assessed 2026-10-06 on integrated code `d05c620`, combining main `8481c0e`,
the #2–#8 stack and independent #9/#10 follow-ups. PRs remain Draft on GitHub.
Local Python/PostgreSQL: 132 passed, 1 skipped (real 1C). Migrations 001–009,
role checker, Ruff, compileall, Bandit, 12 synthetic scenarios and pip-audit pass.
Pinned client: 428 passed/1 skipped; metadata: 53 passed; wrapper/image build pass.
Container runtime smoke and hosted integrated checks are recorded separately when complete.

PARTIAL means remaining implementation or target-environment evidence prevents gate closure.
No production gate is promoted solely by synthetic tests.

| Gate | Status | Implemented / verified | Remaining work |
|---|---|---|---|
| D0 Documentation | PARTIAL | Normative package, PR integration matrix, provenance/audit report | Reconcile all final reports, exact release/evidence links |
| D1 Build/dependencies | PARTIAL | Combined Python/PG, upstream and static checks pass; pip upgraded to audited 26.2.1 | Universal exact lock, SBOM, Node audit/image scan and hosted combined checks |
| D2 Authentication | PARTIAL | JWT issuer/audience/signature/expiry/scope/JWKS-failure tests | Rotation/cache/timeouts, framework-level auth and target IdP evidence |
| D3 Authorization | PARTIAL | Company deny/allow, runtime/admin privileges, multi-source ACL add/revoke | Full fan-out/cross-adapter scope; target deployment evidence |
| D4 Secrets | PARTIAL | Reference-only registry, production ENV rejection, path escape denial | Rotation/credential isolation/leak drill and production provider |
| D5 Read-only | PARTIAL | Read-only sidecar, mutation-negative contract; RSV ping-only | CFE call-path audit, real zero-write proof |
| D6 SSRF/transport | PARTIAL | Registry endpoints, allowlist, redirects/HTTPS/path checks | DNS rebinding/egress, deployment TLS/private route evidence |
| D7 Compatibility | PARTIAL | Per-source positive/negative register/semantic evidence, sticky drift, bounded TTL | Real capability handshakes; audited fallback behavior |
| D8 Data plane | PARTIAL | Query/key/count/register wrapper/upstream tests | Real smoke/parity, fallback normalized read route and failure coverage |
| D9 Accounting | PARTIAL | Profile-gated documents/balances/movements/posting rows; synthetic invariants | Aging/verified tax/profile contracts, >=10 real native-report reconciliations |
| D10 Multi-company | PARTIAL | Three-source ACL lifecycle integration passes | Bounded fan-out/failure isolation, 30/50/100/150-source load and live heterogeneous sources |
| D11 Audit/provenance | PARTIAL | Success/deny/error runtime-role round-trip and UPDATE/DELETE denial | Integrated telemetry/trace propagation, leakage and deployed audit review |
| D12 Observability | PARTIAL | Protected bounded HTTP metrics | Structured logs/spans, operation/dependency metrics, alerts/runbooks |
| D13 Performance | PARTIAL | Request/row/byte/time/per-source limits | Synthetic load measurements, global/fan-out limits, real capacity evidence |
| D14 Resilience | PARTIAL | Readiness, Redis fail-closed, sidecar timeout/circuit tests | Full DB/Redis/JWKS/secrets/upstream/process failure matrix |
| D15 Restore/rollback | PARTIAL | Normative contract | Disposable backup/restore drill, prior-schema migration, rollback automation/runbook; production PITR |
| D16 Deployment | PARTIAL | Non-root sidecar build, fail-closed settings | Reproducible deployment/supply-chain smoke, target network/identity/secrets |
| D17 Operations | PARTIAL | RSV and pilot runbooks | Complete incident/onboarding/rotation/drift/audit procedures and named owner |
| D18 Pilot | PARTIAL | Strict evidence manifest/validator returns NOT_READY | Real pilot, owner approval, exact release production evidence |

P7 is explicitly demand-driven/deferred; P10 is outside modern 1C MVP.
Locally actionable work remains, so Terminal B has NOT been reached.
