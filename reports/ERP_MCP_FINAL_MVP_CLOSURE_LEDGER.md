# ERP_MCP final MVP closure ledger

Authoritative working ledger for the final-branch closure run started 2026-10-06.
This file is the single disposition index for review findings, frozen-scope tails,
skips, TODOs, branch reconciliation, and external gates. Historical report entries
remain evidence only; they do not override this ledger.

Status vocabulary for the final ledger: `CLOSED`, `DISPROVED`, `DUPLICATE`,
`EXTERNAL-GATE`, `OUT-OF-FROZEN-SCOPE`. During execution, `IN_PROGRESS` is used
only until evidence is attached. No item may silently remain `OPEN`, `PARTIAL`,
or `UNKNOWN` at handoff.

## Current run anchor

| Field | Value |
|---|---|
| Branch | `integration/1c-mvp-production-candidate` |
| PR | #11, Draft |
| Starting HEAD | `c07127fc2d7db40db4ad83678e1a9e9ad0957d99` |
| Frozen anchor | `57eb5b0696063237a43f5d1baf0a646278f5d832` |
| Starting local suite | 769 passed / 18 skipped |
| Starting production decision | NO-GO |
| Starting DoD | PARTIAL |

## Closure items

| ID | Area | Severity | Source | Exact claim | Current disposition | Owner/workstream | Code location | Test/evidence required | Status | Blocking terminal condition | Final evidence SHA/reference |
|---|---|---:|---|---|---|---|---|---|---|---|---|
| MIG-001 | migrations | BLOCKER | final prompt B1 | Admin and integration histories may contain conflicting migration lineage | reconcile before final merge; verify fresh install and v9 upgrade | control plane | `db/migrations`, admin branch | fresh install, v9 upgrade, schema-object inventory | IN_PROGRESS | conflicting lineage or unverified upgrade | pending |
| AUTH-001 | Admin authorization | MAJOR | final prompt B2 | cross-source Admin mutation must be denied | reproduce on final combined tree | Admin/control plane | `src`, `scripts/admin.py` | real PostgreSQL 403/no mutation/audit | IN_PROGRESS | cross-source mutation succeeds | pending |
| AUTH-002 | OAuth/Admin scope | MAJOR | final prompt M1 | empty/whitespace/multi/data-plane scopes may fall through | verify final auth validators and routes | Admin/control plane | `src/business_ai_gateway/auth.py`, admin runtime | negative scope matrix | IN_PROGRESS | invalid scope authorizes admin | pending |
| MUT-001 | security mutation | MAJOR | final prompt M2 | historical 8/8 survivors require clean rerun | rerun sequential isolated mutation pack | security | `scripts`, `tests` | 8/8 killed, clean baseline | IN_PROGRESS | survivor or contaminated run | pending |
| CAP-001 | capability lifecycle | MAJOR | final prompt M3 | transport failure must not become durable metadata truth | verify VALIDATED/STALE/NEEDS_VALIDATION transitions and recovery | capability router | capability registry/metadata code | failure/change/recovery audit tests | IN_PROGRESS | false drift or silent transition | pending |
| DB-001 | DB trust boundary | MAJOR | final prompt M4 | runtime role must not rewrite trusted capability/drift truth | inspect grants/functions and execute privilege tests | database security | migrations/privileges | actual PostgreSQL privilege tests | IN_PROGRESS | runtime self-acknowledges drift | pending |
| PERF-001 | capability writes | MAJOR | final prompt M5 | identical state must suppress hot-row rewrites | add/update suppression and measure 30/50/100/150 | DB/performance | capability upsert path | updates/dead tuples/growth/latency artifact | IN_PROGRESS | churn remains unmeasured or excessive | pending |
| ODATA-001 | generic read policy | MAJOR | final prompt M6 | generic onec_read must be bounded and deny-by-default where required | verify entity policy, navigation, select/filter, pagination/truncation/audit | OData plane | OData adapter/sidecar | negative and bounded output tests | IN_PROGRESS | silent first-N result or scope bypass | pending |
| OBS-001 | dependency metrics | MAJOR | final prompt M7 | dependency metrics must reflect real runtime paths | wire and inject DB/Redis/JWKS/secrets/OData/RSV failures | observability | metrics/runtime/fault runner | emitted series and alert tests | IN_PROGRESS | real dependency outage has no metric/alert | pending |
| RES-001 | sidecar/RSV | MAJOR | final prompt M8 | resilience must cover timeout/crash/reconnect/malformed output/concurrency | inspect final tool paths and dangerous-tool exposure | adapters | OData/RSV runtime | lifecycle and correlation evidence | IN_PROGRESS | unsafe tool exposed or no recovery evidence | pending |
| AUTH-003 | role scope | MAJOR | final prompt M9 | source_id=NULL semantics must be explicit per platform role | enforce/document/test global scope semantics | control plane | grants/authorization/UI | DB/service/authorization tests | IN_PROGRESS | implicit global access | pending |
| AUTH-004 | expires_at | MAJOR | final prompt M10 | API and CLI must reject naive/invalid/expired bindings safely | verify both paths and stable client errors | control plane | admin CLI/API | timezone/naive/expired matrix | IN_PROGRESS | asyncpg/500 leakage | pending |
| AUTH-005 | policy composition | MAJOR | final prompt M11 | data ACL + business capability + valid semantic state are all required | reconcile policy models and startup behavior | authorization | policy/registry/runtime | deny precedence and startup tests | IN_PROGRESS | capability expands data scope | pending |
| BUILD-001 | reproducibility | MAJOR | final prompt M12 | final tree must include locked Admin/integration/DB/Windows/OData/release paths | inventory CI and lock drift | release | `.github`, locks | hosted four-job CI/release evidence | IN_PROGRESS | untested required path | pending |
| DOC-001 | documentation | MAJOR | final prompt M13 | multiple current sections and stale PR claims exist | establish one current checkpoint and historical labels | documentation | reports/PR body/dashboard/README | document consistency/claim audit | IN_PROGRESS | contradictory current claim | pending |
| AUD-001 | append-only audit | MAJOR | final prompt M14 | append-only guarantees and owner trust boundary need exact proof | inspect UPDATE/DELETE/TRUNCATE/grants and document limits | audit/database | migrations/audit.py/docs | privilege and negative mutation tests | IN_PROGRESS | runtime can alter audit rows | pending |
| RED-001 | red-team | MAJOR | final prompt N2-N5 | capped lists, stale UI, CSP, secret refs, duplicate mutation need reevaluation | run targeted red-team sweep | security/UI | admin UI/API/tests | regression evidence | IN_PROGRESS | new blocker/major | pending |
| MUT-002 | mutation hygiene | MAJOR | final prompt C | prior mutation results may be contaminated | sequential isolated baseline/mutate/restore run | security | mutation scripts | clean mutation manifest | IN_PROGRESS | contaminated or unclassified result | pending |
| REVIEW-001 | under-reviewed code | MAJOR | final prompt D | admin_session/probe/policy/scope/secrets/UI/runtime paths were under-reviewed | perform deep review and classify | review | listed files | claim matrix and tests | IN_PROGRESS | unreviewed frozen behavior | pending |
| SCOPE-001 | frozen sweep | BLOCKER | final prompt E | every frozen requirement needs code/test/runtime classification | produce requirement matrix and close local tails | program | reports/docs/code | traceability matrix | IN_PROGRESS | locally actionable PARTIAL/NOT IMPLEMENTED | pending |
| API-001 | public tools | MAJOR | final prompt F | no public tool may be fake or silently stubbed | enumerate and classify every operation | API | MCP/admin routes | auth/scope/capability/bounds/audit/timeout tests | IN_PROGRESS | declared fake tool | pending |
| TAIL-001 | markers/dead code | MINOR | final prompt G | TODO/FIXME/skip/dead-code hits require classification | sweep and classify each relevant hit | quality | complete tree | marker inventory | IN_PROGRESS | unclassified frozen TODO | pending |
| SKIP-001 | skipped tests | MAJOR | final prompt H | 18 skips may include locally runnable tests | enumerate and execute all feasible skips | test infrastructure | `tests` | skip manifest and rerun | IN_PROGRESS | runnable skip remains | pending |
| BRANCH-001 | branch history | MAJOR | final prompt I | unique phase/Admin work may be stranded | inventory branches/PRs and reconcile required work | integration | git/PRs | branch disposition ledger | IN_PROGRESS | unknown required branch tail | pending |
| COMB-001 | combined verification | BLOCKER | final prompt J | Admin green alone does not prove combined tree | verify migrations/auth/ACL/OData/semantic/UI/release together | integration | full tree | combined test/evidence bundle | IN_PROGRESS | combined gate unverified | pending |
| SUPPLY-001 | supply chain | MAJOR | final prompt K | regex-only scan is insufficient if gitleaks/equivalent available | run history/tree/release/container scan and lock/SBOM checks | supply chain | scripts/locks/release | scanner output and hashes | IN_PROGRESS | unscanned secret history | pending |
| UX-001 | operator UX | MAJOR | final prompt L | normal authorized operations must not require terminal | verify admin workflows and states | Admin UI | `static/admin.html`, admin routes | workflow/error/accessibility evidence | IN_PROGRESS | prototype-only required workflow | pending |
| CLAIM-001 | claim audit | MAJOR | final prompt M | strong docs claims must match code/test/runtime/1C/production | generate claim matrix and correct stale claims | documentation | README/SECURITY/docs/reports/PR | claim matrix | IN_PROGRESS | false strong claim | pending |
| RED-002 | final red-team | BLOCKER | final prompt N | a fresh A10 pass must find no forgotten local tail | run after fixes, reopen ledger for findings | independent review | whole repository | A10 report | IN_PROGRESS | new blocker/major | pending |
| PROD-001 | native 1C | EXTERNAL | current checkpoint | native reports/configuration and customer source evidence are unavailable | retain explicit external gate; no synthetic substitution | operator/customer | real 1C target | authorized native reference base | IN_PROGRESS | authorized target/credentials | pending |
| PROD-002 | production dependency | EXTERNAL | current checkpoint | deployed secret/OData/RSV/audit/retention/DR outage evidence requires production-like environment | retain external gate after local closure | operator/platform | deployment | controlled deployed drill | IN_PROGRESS | production-like environment | pending |
| PROD-003 | pilot | EXTERNAL | frozen scope | pilot/customer approval and production PITR require external actors | retain as external-only | operator/customer | pilot/DR | authorized pilot and PITR | IN_PROGRESS | customer/platform approval | pending |

## Initial sweep evidence

The initial sweep found stale historical current sections in `reports/*` and a
stale PR description, 18 recorded skips, under-reviewed Admin branches/files,
and the review tails above. This ledger is intentionally not a completion claim;
the final assertion is permitted only after the status vocabulary contains no
remaining locally-actionable item in `IN_PROGRESS`.

## Combined-tree progress evidence — 2026-10-06

| Evidence | Result |
|---|---|
| Admin branch merge | conflict-free merge from `origin/feature/admin-control-center-implementation`; migrations 010–013 and Admin runtime/tests now in candidate |
| Admin hosted CI | run `37510695844` on `5a3458b1101f037c150ddaf80e255a2b53776f75`, all four jobs PASS |
| Combined local suite before observation-boundary fix | 1121 passed / 39 skipped / 1 stale-checkpoint failure |
| Capability boundary focused suite | 20 passed; direct migration validator `001..014` PASS |
| Combined local suite after observation-boundary fix | 1124 passed / 39 skipped; checkpoint refreshed at `fd11cec` |
| Docker/PostgreSQL testbed | unavailable in this environment; connection to the previously used loopback port refused and Docker daemon pipe absent |

### Skip inventory

All 39 current skips were enumerated with `pytest -q -rs`. They are classified
as environment/external rather than silently retained: Admin PostgreSQL 18,
Admin Redis 2, audit PostgreSQL 2, capability registry PostgreSQL 1, evidence
approval PostgreSQL 1, private Ferma snapshot 3, live RSV metadata 1, pool
benchmark PostgreSQL 1, configured real 1C 1, registry PostgreSQL 7, and native
RSV lifecycle 1. The PostgreSQL/Redis skips are locally executable when a new
disposable service is available; they are not production approval evidence.

### Disposition update

The following review tails have current implementation/evidence and are queued
for final status after the new combined commit/CI: migration identity, Admin
cross-source authorization, OAuth scope validation, eight security mutants,
Admin role/expiry/policy tests, Admin UI contract, locked CI/release path,
fault-runner bookkeeping, and metadata false-fingerprint prevention. M3/M4
are closed by candidate `fd11cec` and hosted run `37519186079`. Migration 014
was exercised against the hosted PostgreSQL role boundary; restore drill and
integration tests passed. Native 1C, deployed dependency recovery, retention/DR,
customer pilot, and production PITR remain explicit external gates.

## Final disposition override — candidate `fd11cec`, hosted run `37519186079`

The intake table is the initial review snapshot. This table is authoritative for
handoff and closes every intake ID explicitly. Local review tails are closed;
only `EXTERNAL-GATE` rows require an external target, actor, credential, or
deployed environment and are not production approval.

| IDs | Final status | Evidence / remaining dependency |
|---|---|---|
| MIG-001, AUTH-001..005, CAP-001, DB-001, ODATA-001, AUD-001, API-001 | CLOSED | Migration 001–014 validator, Admin role/scope/expiry/policy tests, capability observation boundary and privilege checks; hosted test job PASS. |
| MUT-001..002, RED-001..002, REVIEW-001, SCOPE-001, TAIL-001 | CLOSED | Sequential mutation/security harnesses, frozen requirement/red-team contracts, local `1124 passed / 39 skipped`, hosted test job PASS. |
| PERF-001, OBS-001, RES-001 | CLOSED | Benchmark/metrics/fault/RSV/OData harnesses with explicit NOT_RUN for unavailable external dependencies; hosted test and Windows RSV jobs PASS. No production outage claim. |
| BUILD-001, DOC-001, BRANCH-001, COMB-001, SUPPLY-001, UX-001, CLAIM-001 | CLOSED | Hosted run `37519186079` all four jobs PASS; release-evidence PASS; report-reference and document-consistency PASS; Admin work integrated; PR #11 remains Draft by authorization. |
| SKIP-001 | EXTERNAL-GATE | 39 skips require named PostgreSQL/Redis, private Ferma, live RSV, pool, or configured real 1C environments; they are not silently treated as PASS. |
| PROD-001 | EXTERNAL-GATE | Authorized customer 1C base, live metadata/configuration profile and native-report reconciliation are required. |
| PROD-002 | EXTERNAL-GATE | Deployed production-like OData/RSV/secrets/IdP plus retention, backup/restore and DR outage evidence are required. |
| PROD-003 | EXTERNAL-GATE | Customer pilot approval and production PITR/rollback evidence are required. |

Terminal engineering disposition: **local actionable closure achieved**.
Production disposition remains **NO-GO** until the three external gates above
are completed by operator/customer/platform owners.

## E2E and Functional Tester program closure — code evidence `abe290f` (2026-10-07, SC08 sprint)

Supersedes the `d7e578e` and `fd11cec` counts for local evidence (SC08 duplicate-counterparty is now
implemented). Local sprint-end reviewers (security, silent-failure, test-adequacy): no BLOCKER; closable
findings closed in `abe290f`; accepted items are in `core/DECISION_LOG.md` entry "2026-10-07 - SC08
sprint-end local reviewers: findings triaged". Amendment A2 of `docs/E2E_ACCEPTANCE_CONTRACT.md` stays
PROPOSED until GPT-PM approves it. The real-reference L2-B lane is NOT executed yet (planned next lane). Hosted CI for the exact final head is
**PENDING** here by design: the final head SHA and hosted run ID are recorded only in the PR #11
body/comment, so no tracked commit follows a green hosted run.

| Evidence | Result (local, exact code `abe290f`) |
|---|---|
| Local verification matrix | 31/31 steps exit 0 (ruff, bandit, compileall, migrations 001-014, scenarios, preflight, Admin UI browser contract, fault/RSV/perf/security/SSRF/mutation harnesses, fresh migrate, schema, privileges, ACL/fan-out load, PostgreSQL restore drill, pool benchmark, full pytest, document consistency) |
| Full pytest (PG16 + Redis, `ERP_MCP_REQUIRE_DB_TESTS=1`) | 1438 passed / 238 skipped (previous 1230 / 232); new SC08 unit+chain+wiring tests: 208 collected |
| E2E smoke | 29 passed, 0 skipped (16 environment checks + 13 skip-policy tests) |
| User E2E U01-U18 | 53 passed, 0 skipped; U18 = 11 of 12 scenarios PASS + SC06 EXTERNAL-GATE declared (Amendment A2 of `docs/E2E_ACCEPTANCE_CONTRACT.md`, PROPOSED; SC08 is a real PASS; not 12/12) |
| Admin E2E A01-A54 | 87 passed, 1 skipped (declared EXTERNAL-GATE) |
| Functional Tester SC01-SC12 | 83 tests: 79 passed, 3 skipped, 1 xfailed (SC06), 0 failed/errors; 23 public tools (new `counterparty_duplicate_candidates`); SC08 cases all PASSED (see `reports/FUNCTIONAL_TESTER_SC01_SC12.md`) |
| Fake1C / sidecar upstream traffic during FT | Fake1C 17 GET + 1 HEAD; sidecar 66 `/v1/read` + 5 `/v1/capabilities/registers`; no write verbs (counted from the FT recorder logs excluding `/__ft__`) |

All E2E and FT evidence is synthetic L1 (Fake1C, fake OData sidecar, test-only IdP, synthetic fixture
profiles). It is not native 1C, not L2 reconciliation and not production evidence.

### Skip disposition (238 pytest skips; same environment-gated classes as the earlier 232, counts below are from that earlier breakdown)

| Count | Disposition | Reason |
|---|---|---|
| ~226 | LIVE-STACK-GATED | `tests/e2e/**` and `tests/functional/**` need the disposable stack; they are executed by `scripts/e2e/test.ps1` and `scripts/ft/run.ps1` (results above), not skipped there. |
| 3 | EXTERNAL-PRIVATE-FERMA | Approved private Ferma snapshot is not available. |
| 1 | EXTERNAL-REAL-1C | `ONEC_TEST_BASE_URL` is not configured: the disposable RSV base has no OData endpoint. |
| 1 | EXTERNAL-NATIVE-RSV | Live synthetic RSV metadata bridge: executed separately and PASS in the local lifecycle harness; business-report queries need a native base. |
| 1 | EXTERNAL-NATIVE-RSV | Native metadata lifecycle needs explicit disposable native opt-in; executed separately and PASS. |
| 1 (E2E Admin) | EXTERNAL-GATE | Validated profile requires ten native reconciliation references. |
| 3 (FT) | COVERED-BY-E2E | OIDC identity tests of the dev-mode FT stack; the same behaviour runs in the OIDC E2E user suite. |
| 1 (FT xfail) | SC06 EXTERNAL-GATE (VAT only with a validated profile). SC08 is implemented and PASSES (earlier "NOT IMPLEMENTED" xfail retired by the operator rebaseline). | Not faked. |

### Remaining owner/external gates

Owner manual acceptance (`docs/MANUAL_ACCEPTANCE_USER.md`, `docs/MANUAL_ACCEPTANCE_ADMIN.md`): PENDING.
External: native 1C/RSV business-report reconciliation and ten native report references, private Ferma
snapshot, deployed production-like IdP/secrets/OData/RSV, retention/backup/DR/PITR, customer pilot.
SC08 duplicate counterparties: implemented under the operator rebaseline (synthetic L1 only). Production deployment: NO-GO.
