[Reading 68 lines from start (total: 68 lines, 0 remaining)]

# Risk status

## Scope freeze checkpoint — 2026-10-06

Operator scope freeze is active. Current candidate: PR #11 Draft/mergeable,
HEAD `65883a5a83fbb369cbd32e5e31af3041f9d7c515`; CI `37446049853` SUCCESS; Production GO NO-GO.

New frozen-scope risk rows are R-31–R-35:
- scope creep;
- malicious/mis-scoped external evidence;
- private reference artifact leakage;
- Ferma oracle/actual correlation false-green;
- test-only write boundary leakage.

No risk acceptance is inferred. Deferred write/legacy/production ERP-Ferma lanes remain deferred.

## Current authoritative checkpoint — 2026-10-06

Last hosted candidate baseline: `b6df856ef518a5a972f2a8141fb87cbdc0432ea8`, PR #11 Draft, CI `37425137186` PASS. Current local uncommitted work is not represented in that CI. Focused security tests (15) pass, including no raw audit query persistence and sanitized upstream errors.

Still OPEN: R-04 SSRF/DNS rebinding/effective egress restriction (critical); R-05 end-to-end secret/log/trace leak and production rotation; R-09 clean dependency/image vulnerability results and provenance (pending scan); R-13 full controlled load proof; R-17/R-18 dependency failure matrix; accounting reconciliation risks R-01/R-23. Synthetic tests are not production evidence. Production GO remains NO-GO and no risk acceptance is inferred.

Assessed: 2026-10-06. Source register: `docs/RISK_REGISTER.md`.

## Current integrated assessment

Candidate code `4683586` plus current drill follow-up: 138 Python/PostgreSQL tests PASS, 1 real-1C skip; migrations/privileges
and security/dependency checks pass. R-06 company isolation and R-08 audit outcomes now have
multi-source/lifecycle and success/deny/error append-only evidence from #9/#10 in this candidate.
R-02 includes metadata/capability TTL and source endpoint/credential-reference invalidation.
R-17 Redis fail-closed test is implemented; broader dependency failure injection remains open.
R-09 pinned upstream tests/image build pass; universal locks/SBOM/audit remain local work.
R-12: official v1.3.0 CFE artifact exists and hash is verified; compiled source/rights/company
audit and real COM smoke remain unverified. Release tag differs from approved source pin.
R-01/R-23 native accounting reconciliation, R-04 deployment egress, production R-05/R-26 secret
rotation, R-13/R-28 capacity, R-18 production PITR and R-22 fan-out remain open. File-secret
rotation behavior is now covered by a synthetic unit test; ACL list authorization correctness was
load-exercised at 30/50/100/150 sources, but noisy local latency is not a capacity claim. No risk
acceptance is inferred.
All independent software/drill work will precede any external-only stopping decision.

R-18 application-level backup/restore is now partially mitigated: disposable PostgreSQL 16 drill
passed on `4683586` with exact per-table row fingerprints after fresh-instance restore, runtime
readiness, privilege checker and seven registry integration tests. Production PITR/retention and
deployment rollback remain open.

## Historical controls (superseded where updated above)

| Risk | Status | Current control/evidence | Remaining action |
|---|---|---|---|
| R-01 / R-23 accounting meaning and universal presets | OPEN — critical | Reconciliation/profile gates documented | Implement semantic profiles and reconcile real 1C cases before approval |
| R-02 configuration/schema drift invalidates mappings | PARTIALLY MITIGATED | Sticky metadata fingerprint drift state, expected-fingerprint admin acknowledgement and `onec_read` fail-closed gate passed CI 37358947196; validated semantic profiles auto-stale on fingerprint change and operator lifecycle events are append-only | Reconcile affected native-report cases before revalidation; record operator identity for metadata-drift acknowledgement |
| R-03 write path exposure | MITIGATED IN CORE / OPEN FOR FUTURE ADAPTERS | Python transport only GET/HEAD; pinned sidecar routes only upstream query/key/count/register read methods and rejects mutation-shaped operations/method names in tests | Continue adapter inventory/static checks; zero-write proof against actual 1C |
| R-04 SSRF | OPEN — critical | Registry IDs, URL/path validation, redirects off | DNS/egress and real deployment checks |
| R-05 secret leakage | OPEN — critical | Secret references/providers; production env provider rejected | End-to-end leak and rotation evidence |
| R-06 company authorization leak | PARTIALLY MITIGATED | Company FK and scoped allow/deny grants; company-only grants blocked from unscoped reads; deny precedence, inaccessible enumeration and immediate revocation passed PostgreSQL CI run 37355876333 | Enforce company filter in business-data adapter; add cross-source isolation |
| R-07 runtime DB policy escalation | PARTIALLY MITIGATED | CI created roles, verified table privileges, and passed registry/audit DML checks using `SET LOCAL ROLE business_ai_app` (run 37356701516); admin-role positive/negative DML passed PostgreSQL CI run 37357432914 | production provisioning runbook |
| R-19 IdP/JWKS outage blocks valid users | PARTIALLY MITIGATED | JWT verifier fails closed on JWKS error; negative test added | Add bounded network timeout/cache behavior and live IdP failure test |
| R-08 audit tampering | PARTIALLY MITIGATED | Append-only trigger, table grants and CI privilege checker; `Audit.write` inserted an error event as runtime role and UPDATE/DELETE were denied in PostgreSQL CI run 37357024926 | Exercise remaining audit paths and ensure all request outcomes persist complete provenance |
| R-09 unstable upstream API | PARTIALLY MITIGATED | Runtime sidecar builds exact MIT upstream SHA; client suite and wrapper contract pass locally; response checks exact SHA | Hosted CI, metadata/register parity and monitor/upstream upgrade procedure |
| R-10 license contamination | MITIGATED BY POLICY | Copyleft isolation docs and vendor tests | Preserve policy on future adapter intake |
| R-13 slow 1C query overload | PARTIALLY MITIGATED | Sidecar timeout, pre-parser response cap, output bytes/rows, per-source concurrency and circuit breaker | Load/capacity test and telemetry |
| R-17 Redis failure removes rate protection | OPEN — high | Readiness pings Redis at startup | Explicit outage behavior and fault-injection tests |
| R-18 DB failure prevents safe auth/audit | PARTIALLY MITIGATED | Readiness and request dependencies fail closed by design | DB outage integration/failure-injection proof |
| R-22 partial fan-out corruption | NOT STARTED | No cross-company aggregate exposed | Preserve partial failures when semantic fan-out is introduced |
| R-25 unsupported production claim | MITIGATED IN STATUS REPORTING | This work uses DEV READY and explicit gate matrix | Keep exact evidence and readiness label updated |

Critical/high risks remain open; production readiness is not claimed.

[executed on device: Razer (a39db190-4797-4348-a6cc-1ff255947613)]