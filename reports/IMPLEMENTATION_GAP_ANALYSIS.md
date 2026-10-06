
# ERP_MCP implementation gap analysis

## Private normalized evidence storage — 2026-10-06

EVID-1/D11/D4: private append-only local normalized evidence provider implements new outside-Git protected stores, opaque references, exclusive file creation, fsync and final manifest commit marker. Existing approved bounded CSV parser reused for all 14 classes; native formats/URLs/decompression NOT enabled. Reopen binds independently pinned manifest/document SHA, exact source/company/config/profile and retention approval. Actual disk/NTFS permissions, Everyone file-ACL widening rejection, owned junction rejection, hardlink/traversal/tamper/oversize/orphan/no-overwrite controls PASS. Shared permission verifier is read-only on existing objects; RSV ACL behavior retained. Internal reader requires OAuth scope/current company ACL/rate/durable access receipt before filesystem; completion/error audit and bounded deadline; background timed-out thread remains read-only. 91 focused store/OS/evidence tests PASS (45 store, 8 RSV privacy, 38 normalized evidence); runtime/testbed Bandit and Ruff PASS. Parent 98dabc3 CI 37490159346 FOUR jobs PASS (tested merge ae49662738357246a88f26e4ce7c82539f1f932f). Full current suite 607 passed/17 skipped; combined Windows privacy/bridge/wire/store suite 81 passed/zero skips; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render/release gates PASS. Own hosted verification pending. Receipt index/operator ingest/runtime wiring, production volume identity/retention/DR, native parsers and frozen DAD/Ferma/native/fault/deployment remain OPEN; no WORM/PITR/native acceptance inferred. Production NO-GO; DoD PARTIAL; PR #11 Draft.

## DAD six internal checks — 2026-10-06

DAD-1/D9/D11: internal DAD-SMALL-01..04 arithmetic engine implemented over bounded typed facts, exact approved versioned source/company/configuration/semantic/metadata profiles and selectors. No universal account numbers, query engine or register naming guesses. Negative quantity/value, gross no-movement, contract/document/currency cross balances and complete continuous daily cash checks. Invalid, truncated, stale, duplicate or wrong-grain facts never PASS; unconfirmed profile CAPABILITY_UNSUPPORTED. DAD-SMALL-05/06 reuse existing provenance-bound normalized Z/terminal comparator; missing evidence EVIDENCE_REQUIRED, mismatches enumerate hashed findings. 122 focused DAD/evidence tests PASS, including 46 small-check contracts. Source collectors, runtime ACL/audit exposure, real profiles/native acceptance remain OPEN; no native approval/level upgrade. Normative coverage table now distinguishes internal PARTIAL from native OPEN; 34-source offline copies synchronized. Audit parent f84e84b CI 37489215259 FOUR jobs PASS; tested merge 99f38d53b64fc7fe417897ac638da0282b79f474. Current full suite 562 passed/17 skipped; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render and release preflight gates PASS. Own CI pending. Frozen invoice/month-close/statements/tax/aging/evidence storage/Ferma/native/fault/deployment work remains OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

## Durable pre-dispatch audit — 2026-10-06

FR-F1/D11: source/company ACL and rate checks precede durable ACCESS_AUTHORIZED receipt; adapter, secrets and capability calls occur only after append succeeds. Receipt and completion share the transport request context; receipt does not count business success. Every real Audit append failure, including completion, is normalized to AUDIT_UNAVAILABLE with provider context suppressed; cancellation propagates. 52 focused tests PASS with actual migrated disposable PostgreSQL app role: receipt observed inside adapter, two correlated rows with NULL raw query, readonly append failure prevents adapter dispatch and drives audit alert metrics. Direct SDK test explicitly establishes transport request context. Invalid metric policy rejected before INSERT. Normative data/SRE docs and 34-document offline render synchronized. Parent e462941 CI 37487651656 all four jobs PASS (tested merge 1905d0a6adfa8241d0ae700713c9e39cd0fb0613). Current full suite 516 passed/17 skipped; Ruff, runtime/testbed Bandit, compileall, release preflight, 12 synthetic scenarios, checkpoint/report/source-render gates PASS. Downloaded parent release bundle exact head/merge plus four image/SBOM and five test summary hashes verified; bundle SHA256 9102f3ca99ee35ec69244b467c1297860783d60b0d4a5295e6b4c4ef655bb32c. Own hosted run pending. Remaining frozen DAD/Ferma/native/fault/deployment/evidence storage/ACL/parsers remain locally OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

## Actual default-budget RSV stdout proof — 2026-10-06

Pre-parser wire bounds now implemented without another bridge/framing/parser: per-stream private
SDK wrapper, 5 MB line/10 MB total/64 frames, owned receive pipe closes, fixed sanitized error.
Concurrent non-RSV sessions unchanged. 36 focused contracts and 19 executed lifecycle harness
cases PASS, zero skips; actual native metadata lifecycle 1 PASS. Saved descriptor fixes SDK handler
stdout diversion in adversarial fixture; default 6 MB floods/valid oversized JSON prove guard
rejection and parser-spy exclusion, not timeout-only evidence. Malformed injection now actually
reaches SDK validation. Coupling to locked SDK seam is documented/tested in both platforms.
Native engine crash/zero-write snapshots/native accounting, full DAD/Ferma/fault/deployment and
external evidence storage/ACL/parsers remain open; whole P6/production scope not inferred closed.

## Shared hardened actual-case evidence reader — 2026-10-06

JUnit helper no longer trusts suite-declared positive totals and no longer uses unsafe XML parsing.
Shared bounded defused reader, actual testcase outcomes, blocking negative signals, sanitized
malformed/spawn paths and no-overwrite summary output implemented. ACL proof survives real -O;
SQL identifier guard tested. 49 focused PASS; real harness reruns 11/10/47/1 zero skips, four
mutants killed, five artifacts scanned. Script scan 38→35 findings; 5 medium contexts classified
with controls in SCRIPT_SECURITY_TRIAGE.md, not suppressed. Parent 0eb66fd CI 37481295210 four jobs
PASS; fresh batch full/hosted verification pending. Whole frozen scope is NOT closed.

## Offline normative document synchronization — 2026-10-06

All 31 required normative + 3 supporting documents now embed from current registered source files
with exact source/render checks; status overlay retained, raw HTML/active URLs/images blocked,
offline normative anchors and code operators preserved. Legacy copied reading/device wrappers
removed from report/dashboard shells; immutable freeze source preserved and hashed, wrapper lines
omitted only in presentation. 14 focused tests PASS; dev dependency audit no known vulnerabilities;
runtime dependency lock unchanged. Old 1.0 embedded normative snapshots are replaced, not asserted
current by a new top-level status string. Expanded scripts Bandit scan: 38 findings / 6 medium,
triage OPEN; runtime/testbed/new-renderer scan PASS. Native/DAD/Ferma/fault/deployment work OPEN.

## Actual isolated Ferma package exporter — 2026-10-06

The exporter gap is implemented for two existing pinned Ferma scenarios, not the full frozen matrix.
Direct committed generator + independent oracle + actual policy/integrity/transitive boundary;
source digest checked twice, cache poisoning/unknown code refused. 47 executed contracts PASS,
zero skips; private scanner-safe evidence SHA-256
`cd0c2ab633f97c358a8b9baf9b748a20661ad5dc0e39ca715c0c9b10765e5c8a`.
Actual 4/9-event packages retained privately; no source/artifacts published. Ferma source changes
left untouched. Native source identities/time-axis policy remain distinct from package hashing.
Current test-plane code is bound by report fingerprint; Phase map now distinguishes latest verified
HEAD/CI from historical freeze anchors. Full matrix, exact mappings/seeder/native/gateway observers,
L2, complete DAD/evidence storage/ACL/parser/fault/deployment work remain locally actionable/OPEN.

## Real audit signal and fixed label/trace boundaries — 2026-10-06

NFR-O1/D12/D11: arbitrary alphanumeric tool identifiers no longer create metric series; fixed
registered-tool allowlist is AST-tested. Trace names/attributes, HTTP statuses and dependency
durations are bounded. Audit only emits original outcome after INSERT; error/cancellation emits
existing critical audit alert selector and never a false success. Real runtime-role PostgreSQL
success/readonly-failure tests PASS, synthetic append-only audit rows retained; 26 focused PASS,
full local 455 PASS/13 SKIP. Pinned promtool lint/format/pending/firing/resolution PASS. Parent
bebc223 CI 37475685751 all four jobs PASS. Receiver delivery, full fault/deployment/DAD/Ferma/native
evidence storage/ACL/parser and stdout pre-parser gates remain OPEN; no production GO inferred.

## Profile-class binding and malformed-result privacy — 2026-10-06

EVID-1/DAD-5 evidence revalidation now binds the complete immutable parser-profile snapshot to
class/version/parser/scope and recomputed approved fingerprint. Detached approved hashes cannot
authorize relabeled evidence. DAD free-text/non-string levels are rejected/null, never echoed.
76 focused tests PASS, full local 435 PASS/12 SKIP; static/security/docs gates PASS. Native
authenticity/parsers/storage/runtime ACL/audit and complete business/Ferma/deployment gates OPEN.

## Executed disposable native metadata lifecycle — 2026-10-06

P6 real bridge crash + fresh COM reconnect now has executed proof using the unchanged audited
binary, production client/SDK and protected ephemeral configs. 1 native test PASS, zero skips;
private evidence `D:/Temp/erp-rsv-native-lifecycle-20261006a.json`, SHA-256
`31c489a41797e3bcdf580ef8a539f7b9c672ab16d5fca5a37d855d86ffe668c0`; scanner PASS.
Only test-created bridge handles killed, no native engine/business queries/customer target.
Full ordinary suite 422 PASS/12 SKIP; native opt-in executed separately. Parent 75c362d CI
37474490200 four jobs PASS, real hosted pool artifact validated. Zero-write snapshot, native
engine crash, stdout pre-parser bound and full DAD/Ferma/evidence/deployment remain separate gaps.

## Actual pool benchmark and assembled artifact — 2026-10-06

NFR-P2/D13 real PostgreSQL acquisition/read/source/batch distributions measured with the production
pool and fan-out executor for 30/50/100/150 synthetic sources. Readonly/ten-connection ceiling/
denial and failure isolation verified. 18 focused tests with actual DB PASS; full local 422/11.
Cold connection growth and Python-only allocation memory are explicitly labeled, no capacity GO.
Parent d755ebc CI 37473881846 all FOUR jobs PASS. Downloaded assembled evidence hash checks PASS:
two image/SBOM/provenance pairs, five actual summaries, exact tested merge 504b48692b4749910ecb16b8e9892d3657b789c0.
Registry publication/native closure remain unproven; package explicitly NO-GO/PARTIAL. Full native
DAD/Ferma/evidence parsers/storage/runtime ACL/audit/fault/deployment work remains locally actionable.

## Current DAD comparison checkpoint — 2026-10-06

Versioned normalized Z/terminal/bank comparisons now enforce exact source/company/configuration/
semantic scope, approved rule/parser fingerprints and independent complete observation planes.
33 focused tests and full local suite 405 passed/10 skipped; lint/security/checkpoint gates PASS.
This does not close native parsers, evidence storage, runtime ACL/audit tools, account selectors,
native observers, full month-close packs or Ferma seeding. Latest hosted 2affa6f / 37470166429:
three prerequisite jobs PASS, release assembly FAIL due to checkout-local Trivy cache. The cache
location is corrected without weakening clean-worktree provenance; corrected hosted run pending.
Production NO-GO, DoD PARTIAL, PR #11 Draft. Independent local engineering remains actionable.

## Persisted registry CLI follow-up — 2026-10-06

FR-C1/C2 registry diagnostics: all five CLI commands implemented against bounded repeatable read-only DB snapshots; aggregate output, exact source/profile/fingerprint freshness and drift checks, exact-register diff, safe private export outside Git/no overwrite. Diagnostic SUPPORTED does not grant runtime authorization; no OData/COM/probe calls. 22 focused tests PASS plus 1 executed test on a NEW PostgreSQL instance (5 snapshots readonly=on), including DrCr negative/positive, stale/drift and oversized profiles. Prior first drill failed because its synthetic seed used the unconfirmed default drift state; corrected fixture then actual DB PASS. Hosted e7898f2 / run 37461088241 BOTH jobs PASS. Current full local suite 341 passed, 10 skipped; separate actual PostgreSQL contract 1/1 PASS. Ruff/Bandit/documentation gates PASS; hosted CLI batch awaits its own run. DAD/native evidence/Ferma/deployment gates remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

The DB-backed capability CLI gap is implemented/locally verified, not a production approval.
Remaining locally actionable scope includes assembled release artifacts/test counts, complete
dependency/audit drills, native evidence parsers/storage/ACL, DAD rule packs and Ferma seeding/
observer integration. Native reconciliation, real-reference acquisition and deployment proof
retain their own gates. No terminal operator-only blocker is declared while this work remains.

## Verified recovery checkpoint — 2026-10-06

Documentation gate (SCOPE-1, D0/D18): current snapshot is bound to implementation content, not old PASS strings. Source drift, a stale report marker, refreshed JSON without refreshed reports and unequal HTML copies fail CI. Ten focused tests and full local suite 288 passed, 9 skipped. Parent implementation c59f07096a1b08c27c33554c29638d4922fe8621 passed BOTH hosted jobs in run 37459728181; the new checkpoint gate awaits its own hosted run. Native accounting/Ferma/DAD/deployment gates remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

Socket-time egress pinning, production path/redirect regressions and actual SDK subprocess
recovery/rotation are implemented. Still locally actionable: remaining dependency/audit drills,
DB-backed capability CLI integration, release assembly, external evidence/DAD rules, Ferma
export/seeder/native observer integration. Native COM lifecycle/Windows DACL and deployed firewall
proof have separate unclosed gates; none is closed by the 288-test local result.

## Current recovery assessment — 2026-10-06

P5 intake, exact synthetic-target guard and independent observation comparator now exist under
testbed/ferma_onec, excluded from production. 22 contract tests pass. Remaining P5 work is actual
Ferma artifact production, exact 1C document/report mappings, seeding, native/gateway observations
and L2 execution. These are not closed by fixture agreement.

Verified implementation `dbeafc8d2afb72de07b794bed926f6ed8cecdb06`, CI `37455962411` PASS;
freeze `57eb5b0696063237a43f5d1baf0a646278f5d832`. Forty-four traceability rows are
inventoried by `scripts/frozen_requirement_matrix.py` with explicit open/deferred status.
Formula-generated benchmarks and hard-coded harness PASS values were discovered and are invalid
closure evidence. Replacement measurements, executable contracts/mutations and scanner tests
advance D0/D4/D13/D14; they do not close the complete gates. Actual Docker DB/Redis outage and
recovery passed (503 then 200, sanitized). Remaining engineering includes DAD/external evidence,
Ferma test integration, semantics, transport hardening, real adapter lifecycle and deployment
rehearsals. These are locally actionable gaps, not operator-only blockers. Production GO: NO-GO.
Promtool lint/firing/resolution/text format validation now passes locally; deployed alert delivery
is separate and still open.

Assessment date: 2026-10-06

## Scope freeze checkpoint — 2026-10-06

Further product-scope additions are frozen. Gap analysis is now measured only against
`docs/SCOPE_FREEZE_BASELINE_2026-10-06.md`; new feature/scenario/adapter/integration families are
not accepted without explicit operator rebaseline.

Code checkpoint at freeze: PR #11 Draft/mergeable, code HEAD `65883a5a83fbb369cbd32e5e31af3041f9d7c515`; hosted CI
`37446049853` SUCCESS; exact scope baseline commit `57eb5b0696063237a43f5d1baf0a646278f5d832`. Later scope-preserving commits may advance PR HEAD without changing frozen scope. Production GO remains NO-GO.

Newly frozen implementation gaps now include the already accepted DAD read-only scope:
- private real-reference restore/fingerprint/native reconciliation;
- Ferma controlled-synthetic scenario/oracle/seeder path;
- six accountant-selected checks;
- invoice/e-factura reconciliation;
- DAD month-close rule packs;
- P&L/CF/BS;
- External Evidence Plane and accepted bank/Z/terminal/customs/CCAC/tax/payroll precheck families.

These are current scope, not future additions.

## Current authoritative checkpoint — 2026-10-06

The latest committed candidate is `b6df856ef518a5a972f2a8141fb87cbdc0432ea8` on `integration/1c-mvp-production-candidate`; PR #11 remains Draft and the hosted run `37425137186` passed its then-current code. A subsequent uncommitted local batch is not covered by that run. Current local batch evidence: Python `146 passed, 8 skipped`; Ruff/Bandit/compileall/pip-audit pass; sidecar contracts 11/11; pinned Chainguard final images pass Trivy on UNKNOWN through CRITICAL with no suppressions; synthetic fan-out portfolio exercise passes; synthetic AR/AP bucket contract exists without source wiring.

Local work still in scope: hosted lock/image/SBOM/provenance verification; structured logs/traces and dependency metrics; failure injection; DNS-rebinding-safe network egress; deployment/rollback/runbooks; integration of synthetic AR/AP fixtures with an evidence-gated semantic profile. External proof remains real 1C source metadata/configuration and native-report reconciliation, production IdP/network/secrets, and Windows COM runtime/operator release authority. Do not mark these gates DONE from synthetic fixtures. Production GO is NO-GO.

## Current integration gaps

Integration from main `8481c0e` includes the #2–#8 stack plus independent #9/#10 tests.
Full combined checks remain PENDING. Remaining locally actionable work: reproducible supply-chain
checks, semantic aging/tax profile contracts, structured telemetry/traces, bounded fan-out/load,
fault injection, PostgreSQL restore drill, secret rotation and operational automation.
RSV v1.3.0 built CFE is available according to the supplied artifact pin; acquisition/hash/audit
and local 1C discovery are pending, not an assumed external blocker. Native 1C/customer production
evidence cannot be substituted with Fake1C. Production GO remains false.

## Historical assessment and phase detail
Current implementation is tracked as Draft PRs #2–#8 after PR #1 merged. Working branch
`phase/p4-inventory-movements` is at `f4340b38945c783a357ce19caa3f34c49d7fdcd0`; hosted run
`37415523392` passed both `test` (including PostgreSQL runtime-role evidence persistence) and
`odata-upstream` (including non-root image smoke and the metadata cache-expiry regression). P4 now includes profile-gated inventory
movements, posting rows, cash movements, and
persistent negative capability evidence. The report below retains historical phase evidence and is
being progressively reconciled; the current implementation status is authoritative for latest P4.
Current delivery is tracked in Draft PRs #2–#9 (PR #1 merged). Latest implementation heads:
P4 follow-up `f4340b3` passed hosted run `37415523392`; D10 multi-source ACL follow-up
`6356005` passed hosted run `37415897249`. Report rows below are phase-level status, not a claim that
the stacked draft PRs are already in `main`. Bootstrap snapshot below is historical context.

Implementation assessed through CI-tested commit `de035247d61a6f166434d449dd69cb2a9dfe418e`;
hosted CI run `37375751454` passed gateway/database and pinned OData jobs.
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
- Working HEAD at latest verified implementation: `133f640b565e2032748125d58cd65e30d75e52ec`.
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
- Local `.venv`, Python, GitHub CLI and Docker are available; local service/database state was not
  modified. Pinned `hacker-cb/1c-odata` source is initialized at the exact intake SHA for P3 review.
  No actual 1C endpoint/pilot evidence is available.

## Master Plan P0–P9

| Phase | Status | Existing implementation/evidence | Missing work, tests, or evidence | DoD |
|---|---|---|---|---|
| P0 Documentation freeze | PARTIAL | Normative v1.0 package, index, six ADRs, traceability, package test; root command center now copied | Reconcile the supplied copy with the in-repo generated command center; documentation test suite and current HEAD CI evidence | D0, D1 |
| P1 Control plane | PARTIAL | Auth, registry, audit, rate-limit and secret-provider modules; migrations 001–004; company upsert/scoped allow-deny grants; company list/resolve; audit provenance fields; versioned migration runner; CI DB privilege checker; RSA JWT positive/negative tests; PostgreSQL company ACL, runtime/admin-role DML and audit writer provenance round-trip; MCP handler audit tests cover success, ACL denial, Redis outage denial and adapter failure in CI 37360482223; Redis client TCP outage fails closed in CI 37361430688; per-message audit correlation middleware added locally | company-aware business query adapter; production role/runbook evidence; server-level Redis failure injection | D2–D6, D10–D11, D14 |
| P2 Capability router | PARTIAL | `compatibility.py`, live metadata probe, JSON/Atom detection, SHA fingerprint and persistence; migration 004 drift lifecycle; sticky drift detection/ack; admin acknowledgement by expected fingerprint; `onec_read` fail-closed until ack; Fake1C JSON/Atom; unsupported/explicit-only fallback tests passed CI 37359877826; configured-but-unimplemented fallback fails without network I/O in CI 37360919808 | Normalized adapter bindings; actual read-only fallback/COM/legacy routes; adapter SHA; full route lifecycle tests | D7 |
| P3 Modern OData data plane | PARTIAL | Exact pinned `hacker-cb/1c-odata` sidecar; bounded query/keyed-get/count/register reads; internal adapter contract; per-source register capability profile persisted in migration 005; exact-source live-metadata evidence rechecked before invocation; sidecar 11/11, upstream client `428 passed/1 skipped`, metadata `53 passed`, PostgreSQL `4 passed`; fresh non-root image smoke passed | Hosted CI, production deployment wiring, security scans/SBOM and real-source tests | D1, D5–D8, D13–D14, D16 |
| P4 Semantic accounting | PARTIAL | Pinned Aprovodka hints remain `CANDIDATE_ONLY`; migrations 006–009 and operator CLI require explicit evidence-backed mapping confirmation, exact current capability/schema and ten native-report cases; company-scoped account turnovers, sales/purchases, inventory/bank/ARAP balances, inventory movements, cash movements and bounded accounting posting rows are profile-driven; new movement/posting reads require exact live EntitySet and property metadata | AR/AP aging, tax, cash-flow reconciliation, posting amounts/full trace; deterministic native reconciliation evidence for source-specific movements/posting | D8–D9, D11 |
| P5 Real 1C and reconciliation | PARTIAL | L1 Fake1C serves versioned synthetic seed, including inventory and cash movements; 12 schema-v2 scenarios have executable invariants; L2 snapshot manifest template | Real L2 seed import/snapshot and captured results; no actual L2/L3 connection or native-report reconciliation evidence recorded | D7–D10, D18 |
| P6 Extension/COM fallback | PARTIAL | Pinned MIT bridge launched through MCP SDK stdio; source-ID-bound config path, reviewed upstream tool inventory, ping-only health, sanitized failures, Windows/ACL runbook and fail-closed contract tests | No data tool routing yet: company-scoped query contract/capability evidence, authenticated service deployment, cross-adapter parity, Windows/COM runtime smoke and operations evidence | D5–D8, D12, D14, D16–D17 |
| P7 Legacy 8.2 | DEFERRED_NOT_REQUIRED_FOR_MODERN_MVP | GPL project and isolated-service-only boundary documented; explicit demand gate says no current 8.2 target is recorded | Reopen only for a named 8.2.13+ target; complete license/isolation review and read-only boundary before deployment; never copy/link GPL into core | D7 if applicable |
| P8 Production hardening | PARTIAL | Basic `/healthz`/`/readyz`; opt-in bearer-protected HTTP counters, in-flight gauge and latency histogram with bounded labels; settings limits and source HTTP retries | Hosted verification; structured logs/traces; source/DB/Redis/audit metrics; circuit breaker; load/performance/fan-out; SBOM/image scans; backup/restore and deployment drills | D1, D12–D17 |
| P9 Pilot and GO | PARTIAL | Privacy-safe evidence template, strict manifest validator, CI schema check and negative test prove empty/unverified evidence cannot claim GO | Real target IdP/secrets/network/1C/users, native reports, zero-write/audit review, restore/load drills, user acceptance and release authority evidence | D0–D18 |

P10 ERP/Ferma is outside the current 1C MVP terminal condition and remains reserved.

## DoD D0–D18

| Gate | Status | Evidence present | Remaining closure |
|---|---|---|---|
| D0 Documentation/traceability | PARTIAL | Baseline/index/traceability plus this initial gap report | Keep report and command center synchronized; close drift and attach evidence to exact release |
| D1 Build/dependency integrity | PARTIAL | `pyproject.toml`, GitHub CI; CI 37358947196 passed migrations, privilege checker, 49 pytest checks and pip-audit; local Ruff/pytest/compileall/Bandit/pip-audit pass | Install locked/reproducible dependencies; license/container evidence; no dependency lock currently established |
| D2 Authentication | PARTIAL | JWT verifier checks signature, issuer, audience, exp/iat/sub/scope; positive/negative RSA tests and JWKS failure test | Framework-level resource-server behavior, bounded cache/network behavior and live IdP evidence |
| D3 Authorization/isolation | PARTIAL | Per-source subject/group and company grants, deny precedence, expiry/revocation filters; company-only grants cannot authorize unscoped source reads; runtime/admin-role DML integration passed CI 37357432914; DB role grants checked in CI | company-filtered business-data adapter; three-source isolation |
| D4 Secrets | PARTIAL | ENV/FILE/GCP provider abstraction; production disallows ENV mode | Secret access/rotation/leak evidence and safer source onboarding/runtime secret handling tests |
| D5 Read-only | PARTIAL | Python client exposes GET/HEAD only; Node wrapper's operation/method allowlist has negative mutation tests and uses only pinned upstream read APIs | Extend inventory/static enforcement to every adapter and fallback; external zero-write evidence |
| D6 SSRF/transport | PARTIAL | Registered-source routing, URL/path checks, redirects disabled, production HTTPS settings | DNS/IP rebinding and egress policy proof; redirect and oversized request tests; endpoint validation parity for admin paths |
| D7 Compatibility | PARTIAL | JSON/Atom metadata probe; persisted fingerprint, sticky DRIFTED lifecycle/admin acknowledgement and read fail-closed gate passed CI 37358947196; local unsupported/explicit-fallback selection tests pass | Configured fallback route lifecycle, normalized bindings and adapter provenance |
| D8 Data-plane correctness | PARTIAL | Pinned upstream sidecar supports bounded reads; per-source register capability profile is persisted; exact operation rechecked against live metadata before call; DrCr unsupported negative and confirmed positive fixtures; sidecar 11/11, upstream client 428/1 skipped, metadata 53/53, PostgreSQL 4/4 | Hosted CI, company scoping and real-source compatibility |
| D9 Accounting correctness | PARTIAL | Fail-closed profile lifecycle and canonical account-turnover, sales/purchase, inventory/bank/settlement balance, inventory/cash movement and bounded posting-row tools are implemented in draft PRs #2/#8; current P4 hosted tests pass in run 37415523392 | Reconcile >=10 representative cases against native reports on the target synthetic/test 1C base; complete aging/tax/full posting-trace semantics only from confirmed source profiles |
| D10 Multi-company | PARTIAL | Distinct company/source registry; scoped allow/deny list/resolve; hosted PostgreSQL ACL integration passed CI 37355876333 and multi-source subject/group isolation + live source-add/revoke contract passed CI 37415897249 in draft PR #9 | Bounded fan-out evidence; company-filtered business adapter; deployed heterogeneous-source pilot |
| D11 Audit/provenance | PARTIAL | Append-only trigger; schema fields for request/correlation, company, adapter/profile/policy fingerprints, bytes/truncation; runtime-role PostgreSQL round-trip now verifies success/denied/error fields and UPDATE/DELETE denial for each in PR #10, CI 37416120977 | End-to-end MCP provenance on every tool path, operational audit review and production retention/incident evidence |
| D12 Observability | PARTIAL | Protected aggregate HTTP counters, in-flight gauge and latency histogram with bounded labels are implemented in draft PR #6; hosted CI run 37384949997 passed | Structured logs/traces, source/DB/Redis/audit metrics, dashboards/alerts and leakage/load evidence |

| D13 Performance/limits | PARTIAL | Basic HTTP timeout, response byte cap, rows/filter and Redis per-tool rate limit settings | Load test, p50/p95/p99, per-source/principal concurrency, fan-out, pool saturation and memory evidence |
| D14 Resilience | PARTIAL | DB/Redis readiness, selected HTTP retries | Defined Redis outage semantics, source isolation/circuit breaker, secret/IdP/adapter failure injection |
| D15 Backup/restore/rollback | PARTIAL | PostgreSQL backup/PITR and rollback contract in docs | Implement operator automation and run a restore drill in an available DB/deployment environment |
| D16 Production deployment | PARTIAL | Sidecar Docker image builds and passes local health smoke as UID 10001 without published port; production HTTPS/token/host allowlist documented | Hosted CI image smoke, image scan/SBOM, deploy-network/TLS, actual role/secret setup and full gateway deploy smoke |
| D17 Operations/support | PARTIAL | Actionable P6 Windows/COM and P9 evidence-gate runbooks | Named ownership/on-call, full incident/rotation/drift procedures and restore drills |
| D18 Pilot closure | PARTIAL | Privacy-safe evidence manifest and negative CI GO gate; current state explicitly NOT_READY | Exact release pilot, real users/sources, native reconciliation, zero-write/audit review and release approval |

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
