# Risk status

Assessed: 2026-10-05. Source register: `docs/RISK_REGISTER.md`.

| Risk | Status | Current control/evidence | Remaining action |
|---|---|---|---|
| R-01 / R-23 accounting meaning and universal presets | OPEN — critical | Reconciliation/profile gates documented | Implement semantic profiles and reconcile real 1C cases before approval |
| R-02 configuration/schema drift invalidates mappings | PARTIALLY MITIGATED | Sticky metadata fingerprint drift state and explicit expected-fingerprint acknowledgement implemented locally | Confirm migration/lifecycle tests in CI; add profile invalidation/retest and auditable operator identity |
| R-03 write path exposure | MITIGATED IN CORE / OPEN FOR FUTURE ADAPTERS | Current Python client only GET/HEAD; structural test | Recheck every upstream/sidecar and mutation-negative tests |
| R-04 SSRF | OPEN — critical | Registry IDs, URL/path validation, redirects off | DNS/egress and real deployment checks |
| R-05 secret leakage | OPEN — critical | Secret references/providers; production env provider rejected | End-to-end leak and rotation evidence |
| R-06 company authorization leak | PARTIALLY MITIGATED | Company FK and scoped allow/deny grants; company-only grants blocked from unscoped reads; deny precedence, inaccessible enumeration and immediate revocation passed PostgreSQL CI run 37355876333 | Enforce company filter in business-data adapter; add cross-source isolation |
| R-07 runtime DB policy escalation | PARTIALLY MITIGATED | CI created roles, verified table privileges, and passed registry/audit DML checks using `SET LOCAL ROLE business_ai_app` (run 37356701516); admin-role positive/negative DML passed PostgreSQL CI run 37357432914 | production provisioning runbook |
| R-19 IdP/JWKS outage blocks valid users | PARTIALLY MITIGATED | JWT verifier fails closed on JWKS error; negative test added | Add bounded network timeout/cache behavior and live IdP failure test |
| R-08 audit tampering | PARTIALLY MITIGATED | Append-only trigger, table grants and CI privilege checker; `Audit.write` inserted an error event as runtime role and UPDATE/DELETE were denied in PostgreSQL CI run 37357024926 | Exercise remaining audit paths and ensure all request outcomes persist complete provenance |
| R-09 unstable upstream API | OPEN — high | Exact SHA/license intake documented | Integrate exact pin, lock and parity tests |
| R-10 license contamination | MITIGATED BY POLICY | Copyleft isolation docs and vendor tests | Preserve policy on future adapter intake |
| R-13 slow 1C query overload | OPEN — high | Basic timeout/row/response/rate settings | Sidecar limits, per-source concurrency, load evidence |
| R-17 Redis failure removes rate protection | OPEN — high | Readiness pings Redis at startup | Explicit outage behavior and fault-injection tests |
| R-18 DB failure prevents safe auth/audit | PARTIALLY MITIGATED | Readiness and request dependencies fail closed by design | DB outage integration/failure-injection proof |
| R-22 partial fan-out corruption | NOT STARTED | No cross-company aggregate exposed | Preserve partial failures when semantic fan-out is introduced |
| R-25 unsupported production claim | MITIGATED IN STATUS REPORTING | This work uses DEV READY and explicit gate matrix | Keep exact evidence and readiness label updated |

Critical/high risks remain open; production readiness is not claimed.
