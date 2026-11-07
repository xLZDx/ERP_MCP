---
project: ERP_MCP
as_of: 2026-11-01
active_sprint: FIN
scope: single_sprint
approved_sprints: FIN
operator_approved: true
---
# ERP_MCP - project plan

Source: reports/ERP_MCP_PHASE2_STATUS_2026-10-31.ru.html (snapshot 2026-10-31 22:12 Europe/Chisinau, local HEAD f22fa64, origin tip f23a7af) and docs/sdlc/backlog.md. Sprint FIN is the Phase 2 finisher sprint beea27520b33 (10 ordered stories S1.1-S3.3); its task IDs carry the FIN- prefix to avoid clashing with the program sprints S1-S19. Statuses for other sprints are the last recorded ones; the report does not confirm current per-task status, so no task there is marked ACCEPTED. Release 2 is NO_GO and production authorization is NONE.

## Roadmap
| Sprint | Title | Status | Goal |
|---|---|---|---|
| FIN | Phase 2 finisher backlog (sprint beea27520b33) | ACTIVE | Complete authorized S12/S13 follow-ups and the S16 rev. 2 fake-backed approval/tool slice, then collect exact-final-head evidence and reconcile acceptance. |
| S0 | Baseline | IN_PROGRESS | Baseline. |
| S1 | Connector contracts | APPROVED_PUSHED | Connector contracts. |
| S2 | Ledger and budget | APPROVED_PUSHED | Ledger and budget. |
| S3 | Capture and status | APPROVED_PUSHED | Capture and status. |
| S4 | Concept mapping | APPROVED_PUSHED | Concept mapping. |
| S5 | Capture boundary | APPROVED_PUSHED | Capture boundary. |
| S6 | Accounting workbench | APPROVED_PUSHED | Accounting workbench. |
| S7 | Drive intake | APPROVED_PUSHED | Drive intake. |
| S8 | Review workbench | CLOSED_BOUNDED_SPRINT (3/3 bounded task acceptances; PR #48 merged) | R2-US-039 through R2-US-041 accepted in bounded scope; G5 UAT/runtime acceptance remains separately NOT_RUN/NOT_PASSED. |
| S9 | Operations and recovery | CLOSED_BOUNDED_SPRINT (4/4 task acceptances; PR #49 merged) | R2-US-043 through R2-US-046 accepted in bounded offline scope; G6-pre and live product/runtime acceptance remain separately NOT_RUN/NOT_PASSED. |
| S10 | Release handoff | HANDOFF_NO_APPROVE | Release handoff. |
| FOLLOW_ON | Follow-on | UNCONFIRMED | Follow-on. |
| S11 | Foundations, contracts and feasibility | DONE_SPRINT_LEVEL | Foundations, contracts and feasibility. |
| S12 | Change model and policy | IN_PROGRESS | Change model and policy. |
| S13 | Ledger and audit anchor | GIT_ACTIVITY_NOT_CLOSED | Ledger and audit anchor. |
| S14 | 1C write port | GIT_ACTIVITY_NOT_CLOSED | 1C write port. |
| S15 | Verification and reconciliation | GIT_ACTIVITY_NOT_CLOSED | Verification and reconciliation. |
| S16 | Independent approval and MCP | GIT_ACTIVITY_NOT_CLOSED | Independent approval and MCP. |
| S17 | Document intake and workbench | QUEUED | Document intake and workbench. |
| S18 | Reliability and security | QUEUED | Reliability and security. |
| S19 | Release candidate and acceptance | GIT_ACTIVITY_NOT_CLOSED | Release candidate and acceptance. |

## Sprint FIN - Phase 2 finisher backlog (sprint beea27520b33)
Goal: Complete the authorized S12/S13 follow-ups and the S16 rev. 2 fake-backed approval/tool slice, then collect exact-final-head evidence and reconcile acceptance without any real 1C write or production action.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| FIN-S1.1 | Align SQL refusal codes and exhausted-grant outcome | AC-1 Python/SQL refusal-code parity incl. PERIOD_CLOSED and GRANT_EXHAUSTED; AC-2 exhausted grant returns GRANT_EXHAUSTED; AC-3 SQL limits named. | IN_REVIEW | Pushed to sprint branch, PR #41 open and not merged; AC-1..AC-3 confirmed; 2 tests, DB review without findings; PR text records GPT-PM APPROVE for the exact HEAD, no GitHub review record. | Codex |  | f23a7af |
| FIN-S1.2 | Produce period and exhausted-budget evidence from real data | AC-1 authenticated period observation, closed gives PERIOD_CLOSED; AC-2 fail closed on missing/contradictory/stale/unproven evidence; AC-3 exhausted grant feeds BudgetCheck.EXHAUSTED. | PARTIAL | AC-1 NOT_RUN; AC-2 PASS only on unavailable helper; AC-3 PASS. Period tests 9/9, SQL tests 3/3 on disposable PostgreSQL; GPT-PM PARTIAL ACCEPT, MAJOR-02 open (no trusted integration or real source); sources_list internal error. Candidate uncommitted in isolated worktree on base f23a7af. | Codex; operator restores 1C connector for live check | FIN-S1.1 |  |
| FIN-S1.3 | Expose in-flight changes and current status | AC-1 in-flight list derived from ledger/service state; AC-2 status of a listed ID reports recorded status, no test fixture substitution. | PARTIAL | Code implemented; acceptance not confirmed; no task-ID commits. Needs independent SQL catalog/grants check, tenant-isolation runtime evidence and safe delivery of a separate scope. | Codex; GPT-PM adjudication if needed |  |  |
| FIN-S2.1 | Put approval decisions in the S16 core | AC-1 core refuses self-approval, replay, digest/version/expiry/token mismatch; AC-2 revalidation before apply port; AC-3 claim once; AC-4 service owns preview digest and nonce. | PARTIAL | verify-evidence.md: 75 functional tests on 3af7379; CODE-1/CODE-2 and SEC1 closed; GPT-PM narrowly approved S2.1 delta. Official AF phase-8 result UNRECOGNIZED, no approval artifact; SQL durability claims unproven. | Codex; GPT-PM formal decision | FIN-S1.1 |  |
| FIN-S2.2 | Implement the protected approval page and session boundary | AC-1 decision recorded only for bound change/digest/version/scope; AC-2 fails closed with session, CSRF, CSP, encoding, framing, caching protections; AC-3 preview and digest from service canonical bytes. | PARTIAL | 6 page/ingress tests passed in-process at 3af7379; UI1 closed. Real browser/IdP/UAT NOT_RUN; no formal sprint approval. | Codex; GPT-PM formal adjudication | FIN-S2.1 |  |
| FIN-S2.3 | Expose exactly the approved five model-facing tools | AC-1 tools/list is exactly propose/status/apply/verify/rollback_propose; AC-2 direct approval refused; AC-3 verify passes S15 outcome unchanged; AC-4 rollback creates separate UNPOST proposal; AC-5 safe errors. | PARTIAL | Selected fake-backed tool tests passed at 3af7379 (five-tool registry, safe errors, rollback boundaries). Real chat clients NOT_RUN; final coverage/review and formal approval not recorded. | Codex; GPT-PM formal adjudication | FIN-S2.1, FIN-S2.2 |  |
| FIN-S2.4 | Require positive authentication and private-only ingress | AC-1 authenticated principal required; AC-2 foreign origin/proxy/redirect/rebinding fail closed before apply port; AC-3 production binding set stays empty. | PARTIAL | Ingress selection 6/6 in-process at 3af7379. Live listener, test IdP/browser and deployed binding evidence absent; production bindings empty. | Codex; test agents for live/integration evidence | FIN-S2.3 |  |
| FIN-S3.1 | Run required SQL/E2E and S15 suites at the final implementation head | AC-1 each result records head, command, outcome, skips, limits; AC-2 unavailable scenario recorded NOT_RUN; AC-3 results mapped to stories and gates. | NOT_STARTED | NOT_RUN at final HEAD. Only earlier runs exist: 947 S15 tests on 514d0ab, SQL evidence on 499baa96; not final-head proof. | Codex coordinates; functional-test-reviewer and e2e-runner run tests | FIN-S1.1, FIN-S1.2, FIN-S1.3, FIN-S2.4 |  |
| FIN-S3.2 | Check ERP_MCP_REAL1 connector reachability and one watchdog restart | AC-1 read-only connector probe evidence without credentials; AC-2 one component stopped once with before/after evidence. | NOT_STARTED | NOT_RUN. Last connector probe ended with internal error; no controlled watchdog stop/restart confirmed. | Codex (read-only lane) |  |  |
| FIN-S3.3 | Reconcile acceptance and later-sprint scope | AC-1 S12/S13/S15 gates promoted only with evidence; AC-2 S16 fake evidence kept distinct; AC-3 only explicitly covered S17-S19 items enter later sprints; AC-4 writer UNQUALIFIED, bindings empty, no real POST/UNPOST. | IN_PROGRESS | OPEN: reconciliation not finished. Manifest: Release 2 NO_GO, production authorization NONE, G8 IN_PROGRESS. No full task-ID crosswalk between 48 V1, 46 V2 and 10 finisher tasks. | Codex; GPT-PM adjudicates scope | FIN-S3.1 |  |

## Sprint S0 - Baseline
Goal: Baseline.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-001 | Owner establishes the R1/R2 boundary and baseline | REQ01 (formal); REQ28 related to TC003 evidence; TC001 R1 unchanged; TC002 R1 defects cannot be hidden in the future backlog; TC003 moving HEAD is not reported as deployment evidence | IN_PROGRESS | Historical ledger IN_PROGRESS, current status unconfirmed; Supporting tests passed at 3af73797 (spec catalog 13, mapping/assembly/TC003 7); product TC001-TC003 remain NOT_RUN; GPT-PM read-only APPROVE of the uncommitted delta is not product acceptance | Codex |  |  |
| R2-US-002 | Architect verifies actual PDCC/ERP/Ferma reuse | REQ04; TC004 pin file path/SHA/license; TC005 an empty placeholder is not ready; TC006 donor write APIs are not exposed | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-001 |  |

## Sprint S1 - Connector contracts
Goal: Connector contracts.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-003 | Connector engineer uses a bounded read-only SDK | REQ03,26; TC007 typed scope and provenance; TC008 arbitrary URL/SQL/command denied; TC009 unsupported change feed maps to SNAPSHOT_ONLY | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Connector SDK envelope + fail-closed validation (phase2/connector_sdk.py, S1-S4); no OAuth/secret provider; no real connector | Codex | R2-US-002 |  |
| R2-US-004 | Administrator defines tenant/company membership | REQ02,27; TC010 permitted company read; TC011 cross-tenant FK/API denied; TC012 company-only grant does not authorize global metadata | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Scope epoch/revocation at port level on fake and real SQL (S1-S4); not wired | Codex | R2-US-003 |  |
| R2-US-005 | Owner revokes access without stale disclosures | REQ02,27; TC013 revoke blocks jobs/bumps epoch; TC014 revoke before disclosure denies result; TC015 reconnect never restores revoked grants | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-004 |  |
| R2-US-006 | Operator runs jobs through an approved secret provider | REQ03,15,27; TC016 no secrets in logs/arguments; TC017 missing credential pair fails preflight without gateway shutdown; TC018 rotation uses the new version | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-003 |  |

## Sprint S2 - Ledger and budget
Goal: Ledger and budget.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-010 | Database engineer maintains an immutable temporal ledger | REQ09; TC028 append/projection order; TC029 SQL roles deny UPDATE/DELETE; TC030 identical replay | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; SQL (`db/phase2/001`-`003`) executed on a disposable PostgreSQL 16, 20 integration tests green (see EVIDENCE_MATRIX.md); GPT-PM REJECT of a8b5b4d open (BLOCKER-01..03), no backup/restore or ... | Codex | R2-US-004 |  |
| R2-US-011 | Auditor distinguishes knowledge time and effective time | REQ09; TC031 correct two-time views; TC032 unknown effective time is not replaced by poll timestamp; TC033 late supersession preserves earlier knowledge | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Isolated module only; no product acceptance | Codex | R2-US-010 |  |
| R2-US-017 | SRE prevents simultaneous writers | REQ11; TC049 exactly one lease/fence; TC050 stale worker cannot commit; TC051 crash reclaim without duplicates | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Lease/fence/reap/poison on SQL and scheduler; real multi-process tests on PostgreSQL (S4b); one host only | Codex | R2-US-010 |  |
| R2-US-018 | Connector engineer persists cursor/outbox | REQ11,12; TC052 atomic page/cursor; TC053 crash replay without loss; TC054 same ID with different digest is conflict | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; SQL cursor CAS + outbox exercised on disposable PostgreSQL (NULL batch, replay, digest conflict); GPT-PM BLOCKER-01 (replay with changed batch) open; no publisher/consumer | Codex | R2-US-017 |  |

## Sprint S3 - Capture and status
Goal: Capture and status.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-007 | Integrator obtains an authorized 1C baseline | REQ05; TC019 complete coverage/digests; TC020 direct SQL forbidden; TC021 changing source yields partial/consistency warning | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-003, R2-US-009, R2-US-017 |  |
| R2-US-008 | Data architect distinguishes XML formatting changes from schema drift | REQ06; TC022 whitespace-only structural hash unchanged; TC023 type/scale change causes diff; TC024 namespaces do not collide | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Isolated module only; no product acceptance | Codex | R2-US-010 |  |
| R2-US-009 | Operator preserves accepted truth after scan failure | REQ05,07; TC025 timeout does not create a new schema; TC026 partial scan cannot delete objects; TC027 recovery without false version or automatic trust | IN_PROGRESS | Historical ledger IN_PROGRESS, current status unconfirmed; Failure-vs-drift classification (drift.py) and capture loop (capture_loop.py); PARTIAL completeness path tested; baseline hash in memory only | Codex | R2-US-010 |  |
| R2-US-012 | Auditor sees gaps and completeness | REQ05,09; TC034 SNAPSHOT_ONLY interval; TC035 A–B–A changes are not invented; TC036 lost cursor causes controlled resnapshot and gap | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Cursor-loss resnapshot tracker + resume revalidation + capture loop enforcement (S4/S4b); cursor identity checked (issue 33); not wired | Codex | R2-US-010 |  |
| R2-US-019 | SRE enforces physical-backend budget | REQ11,23; TC055 budget shared across source aliases; TC056 bounded overload; TC057 interactive/background fairness | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Per-backend budget + deferral (scheduler); fairness not guaranteed (no queue/aging) | Codex | R2-US-017 |  |
| R2-US-020 | Operator pauses, reconnects or quarantines a source | REQ03,11,27; TC058 pause prevents new jobs; TC059 poisoned source isolated; TC060 resume rechecks scope/cursor | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Pause/quarantine, state export/import, resume_revalidated (scheduler/resnapshot); caller persists state | Codex | R2-US-005, R2-US-018 |  |

## Sprint S4 - Concept mapping
Goal: Concept mapping.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-013 | Domain engineer creates taxonomy/LDM | REQ08; TC037 scoped candidate edges; TC038 LLM cannot validate; TC039 versioned semantics preserve old links | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; taxonomy.py candidate-only edges, independent approver, versions (S4b); no persistence, no concept accept/reject API | Codex | R2-US-007, R2-US-008 |  |
| R2-US-014 | Accountant distinguishes supplier aliases | REQ08,20,27; TC040 exact scoped reference match; TC041 same name across companies never merges; TC042 ambiguity requires human resolution | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; aliases.py exact scoped resolution + human queue (S4b); in-memory | Codex | R2-US-013 |  |
| R2-US-015 | Architect computes dependency impact closure | REQ10; TC043 affected tool blocked; TC044 unknown graph denied conservatively; TC045 remove/recreate is not a rename | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; Isolated module only; no product acceptance | Codex | R2-US-013 |  |
| R2-US-016 | Model approver updates accepted head with CAS | REQ07,10,21; TC046 evidence plus expected-head commit; TC047 stale reviewer yields conflict (409); TC048 incompatible rollback denied | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; SQL `promote_head` executed on disposable PostgreSQL (integration green); GPT-PM MAJOR-01: attestation evidence authenticity not verified; no service layer | Codex | R2-US-015, R2-US-028 |  |

## Sprint S5 - Capture boundary
Goal: Capture boundary.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-021 | Accountant obtains a manual native UI baseline | REQ13,16,19; TC061 original artifact/manifest is UNATTESTED; TC062 partial screenshot is incomplete; TC063 edited XLSX digest rejected | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-006, R2-US-024, R2-US-026 |  |
| R2-US-022 | Capture operator automates the standard UI | REQ13,15; TC064 manual/UI evidence equivalence; TC065 wrong database denied; TC066 selector/modal drift fails without guessed clicks | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-021, R2-US-025 |  |
| R2-US-024 | Data owner issues a bounded capture permit | REQ15,26; TC070 exact scope/window/mode admission; TC071 production default OFF and expired permit denied; TC072 identical idempotency key with changed parameters returns conflict (409) | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; capture_permit.py (S5): scope/window/mode, prod default OFF, idempotency, owner registry; caller-supplied owners, in-memory | Codex | R2-US-004, R2-US-006 |  |
| R2-US-025 | Security reviewer proves side-effect boundary | REQ15; TC073 no business writes and complete coverage; TC074 administrator/posting rights disqualify; TC075 reset/write probes denied in production | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; side_effect_boundary.py (S5): READ allow-list, rights, prod probes; illustrative registry | Codex | R2-US-024 |  |
| R2-US-026 | Custodian stores private immutable originals | REQ16,17; TC076 opaque artifact version and digest; TC077 nonexistent blob/hash is not evidence; TC078 historical artifact remains subject to current ACL | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; artifact_vault.py (S5): immutable versions, evidence verification, current ACL; in-memory, no real storage | Codex | R2-US-010, R2-US-004 |  |
| R2-US-027 | Security engineer isolates parsers | REQ17; TC079 values-only parsing; TC080 macros/entities/zip bombs denied; TC081 timeout/memory bounded with no partial-data PASS | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; safe_parser.py (S5): values-only xlsx/csv with bounds; Windows child memory bound not enforced; not a sandbox | Codex | R2-US-026 |  |

## Sprint S6 - Accounting workbench
Goal: Accounting workbench.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-0231 | C engineer qualifies standard engine/batch reporting | REQ14,16; TC067 qualified native-object provenance; TC068 empty COM output is not zero; TC069 untrusted EPF denied | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-021, R2-US-025 |  |
| R2-US-028 | Independent accountant signs evidence | REQ16,21; TC082 attestation binds exact revision and policy; TC083 self-signing/fabricated PASS denied; TC084 revocation ends current validity but preserves history | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; c4b13f4: 40 offline tests; caller-asserted identity, not wired into promotion | Codex | R2-US-026, R2-US-027 |  |
| R2-US-029 | Tester compares a candidate without a public bypass | REQ16,18,21; TC085 scoped EVALUATION_ONLY; TC086 unauthorized evaluation runner denied; TC087 canonical replay after acceptance | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; c4b13f4: 86 offline tests; in-memory, READ_SNAPSHOT permit mode | Codex | R2-US-015, R2-US-024, R2-US-027 |  |
| R2-US-030 | Accountant reconciles all six account 521.1 balances and rows | REQ18,19; TC088 all required measures MATCH; TC089 wrong opening/turnover causes MISMATCH despite equal closing balance; TC090 compare contract debit/credit sides separately from netting | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; c4b13f4: six-balance tests and contract netting (TC090); no real 521.1 source bytes | Codex | R2-US-021, R2-US-029 |  |
| R2-US-031 | Domain engineer supports accounting-based AP | REQ18,19,21; TC091 qualified ledger strategy; TC092 missing settlement register never invented; TC093 a balance alone does not establish aging | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S6b code commit: ap_account_strategy.py, 141 offline tests; ledger strategy / ABSENT register / BALANCE_ONLY without aging; fixtures only, no real 818HA source, ap.account_based still refused | Codex | R2-US-030 |  |
| R2-US-032 | Company user sees posted MOLDRETAIL receipts | REQ18,20,21; TC094 correct identity/company/Posted status; TC095 exclude unposted/deleted; TC096 complete pagination and alias proof | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S6b code commit: posted_receipts.py, 122 offline tests (62+36+24) plus comparator; retrieval, alias proof, pagination, three-way assessment over fakes only; no real paginated source or MOLDRETAIL data | Codex | R2-US-014, R2-US-021, R2-US-029 |  |
| R2-US-033 | Auditor compares one consistent data snapshot | REQ18,19; TC097 immutable snapshot proven; TC098 concurrent correction is INCONCLUSIVE; TC099 backdated rerun supersedes without overwrite | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; c4b13f4: 24 offline tests; in-memory snapshots and runs | Codex | R2-US-030 |  |
| R2-US-034 | Product owner defines operation validation | REQ21,28; TC100 claim/evidence coverage; TC101 ten duplicate cases denied; TC102 purchases validation does not enable AP or alter R1 | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; c4b13f4: 37 offline tests; reserved ap.account_based | Codex | R2-US-028, R2-US-030, R2-US-031, R2-US-032 |  |

## Sprint S7 - Drive intake
Goal: Drive intake.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-035 | Drive owner authorizes the actual narrow corpus | REQ12,27; TC103 scoped access proven; TC104 folder/new-child permission proof; TC105 broad OAuth is not claimed to be folder isolation | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S7 code commit: drive_port.py, drive_fake.py, drive_oauth.py, drive_scope.py, 334 offline tests (108+110+116); scoped access, broad-never-isolation, ERP_MCP-owned fake consent over a scripted fake ... | Codex | R2-US-003, R2-US-004, R2-US-026 |  |
| R2-US-036 | Connector engineer updates Drive catalog | REQ12,11; TC106 start token before baseline + catchup; TC107 shared-drive namespaces; TC108 lost cursor causes gap/resnapshot | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S7 code commit: drive_baseline.py, drive_cursor.py, 109 offline tests (53+56, count as of drafting); start-token-first baseline, namespaces, durable fail-closed cursor over the existing cursor CAS ... | Codex | R2-US-018, R2-US-035 |  |
| R2-US-037 | Auditor tracks revisions, moves and revocation | REQ12,16,27; TC109 new revision UNATTESTED while previous PASS remains historical; TC110 shortcut/move cannot escape scope; TC111 deletion does not invent a replacement | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S7 code commit: drive_revisions.py, drive_membership.py, 90 offline tests (48+42); new revision UNATTESTED / old PASS historical, scope escape denied, removal tombstone over fakes only; no real ... | Codex | R2-US-005, R2-US-036 |  |
| R2-US-038 | SRE handles auth expiration and watch notifications | REQ12,24; TC112 invalid grant becomes AUTH_REQUIRED; TC113 notifications are hints only; TC114 polling works without watch | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S7 code commit: drive_auth_state.py, 57 offline tests (41+16); AUTH_REQUIRED on invalid_grant/revoke, hint-only notifications, polling without watch over fakes only; no real Google auth or watch; G4 ... | Codex | R2-US-006, R2-US-036 |  |

## Sprint S8 - Review workbench
Goal: Review workbench.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-039 | Accountant investigates discrepancies | REQ22; TC115 row/fragment/owner/delta; TC116 original numbers immutable; TC117 new evidence creates a new run | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S8 code: workbench_types.py, workbench_review.py, 194 offline tests (66+128); cards with exact delta/owner/fragment, original digest and verify_original, rerun creates a new run, over fakes only; ... | Codex | R2-US-030, R2-US-032, R2-US-034 |  |
| R2-US-040 | Auditor reads timeline and coverage UI | REQ07,09,22; TC118 explicit knowledge/effective-time labels; TC119 historical is not live-green; TC120 diff and evidence remain scoped | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S8 code: timeline_view.py, coverage_view.py, 401 offline tests (204+197); known/effective labels, is_green only for LIVE_CURRENT, scoped diff/evidence with opaque HIDDEN_BY_SCOPE, over fakes only; no ... | Codex | R2-US-011, R2-US-016, R2-US-037 |  |
| R2-US-041 | API engineer exposes jobs and results safely | REQ26,02; TC121 safe reason/annotation; TC122 CSRF/idempotency enforcement (403/409); TC123 raw COM/DC cannot bypass denial | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S8 code: safe_errors.py, jobs_api.py, 187 offline tests (61+67+59); fixed safe errors, endpoint annotations, CSRF/idempotency decisions, refusal not bypassed by respelling, over fakes only; no ... | Codex | R2-US-003, R2-US-024, R2-US-034 |  |

## Sprint S9 - Operations and recovery
Goal: Operations and recovery.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-043 | Performance tester measures capacity | REQ23; TC127 sessions-vs-active grid; TC128 denied profiles excluded from throughput; TC129 background interference and budget | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S9 code: ops_types.py, capacity_model.py, capacity_interference.py, 387 offline tests (107+195+85); sessions vs active clients vs sources vs backends kept as separate axes, refusals never counted as ... | Codex | R2-US-019, R2-US-041 |  |
| R2-US-044 | SRE verifies faults, alerts and recovery | REQ24; TC130 audit failure is fail-closed; TC131 replica/network 429 without duplicates; TC132 alarm fires and resolves | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S9 code: audit_gate.py, delivery_replay.py, alert_rules.py, 176 offline tests (44+48+84); audit-before-effect fail-closed gate, at-least-once delivery with digest de-dup over fake sinks, alert state ... | Codex | R2-US-018, R2-US-020, R2-US-041 |  |
| R2-US-045 | Release engineer deploys R2 without damaging R1 | REQ25; TC133 additive shadow regression; TC134 destructive rollback denied; TC135 switchover rollback never resurrects revoked grants | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S9 code: release_migration.py, release_rollback.py, 304 offline tests (134+126+44 SQL guard); typed step classification, shadow compare by digest, decision-only rollback (executed=False), effective ... | Codex | R2-US-016, R2-US-041 |  |
| R2-US-046 | Privacy/operations owner handles retention and restore | REQ17,24,27; TC136 restored foreign keys/digests/heads; TC137 export masking/tenant/formula safety; TC138 legal hold and no unauthorized deletion | PARTIAL | Historical ledger IMPLEMENTED_UNVERIFIED, current status unconfirmed; S9 code: restore_verify.py, export_safety.py, retention_hold.py, 318 offline tests (118+143+57); restore manifest/FK catalogue/digest/head verification over in-memory rows, export masking/tenant ... | Codex | R2-US-026, R2-US-037, R2-US-045 |  |

## Sprint S10 - Release handoff
Goal: Release handoff.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-042 | Production owner approves qualified canary | REQ15,28; TC124 exact-scope capture/comparison; TC125 dev PASS does not grant production approval; TC126 kill switch owns running jobs | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof; S10 offline closure is ENGINEERING_HANDOFF only (`S10_RELEASE_HANDOFF.md`), canary NOT_RUN pending operator permission and real data | Codex | R2-US-023, R2-US-034, R2-US-043, R2-US-044, R2-US-045 |  |
| R2-US-048 | Release owner accepts exact candidate | REQ01,28; TC142 complete manifest, IDs and actual results; TC143 NOT_RUN cannot become release PASS; TC144 separate user/admin/production UAT | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof; no exact-head release bundle approved (see `S10_RELEASE_HANDOFF.md`), Release 2 NO-GO | Codex | R2-US-042, R2-US-043, R2-US-044, R2-US-045, R2-US-046 |  |

## Sprint FOLLOW_ON - Follow-on
Goal: Follow-on.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| R2-US-047 | Owner enables additional PDCC providers | REQ04,03,27; TC139 adapter contract qualification; TC140 personal corpus expansion denied; TC141 pinned upgrade triggers retesting | NOT_STARTED | Historical ledger NOT_STARTED, current status unconfirmed; No exact-head acceptance proof | Codex | R2-US-002, R2-US-041 |  |

## Sprint S11 - Foundations, contracts and feasibility
Goal: Foundations, contracts and feasibility. Sprint is DONE in the gate manifest; its child task IDs are not enumerated in the report.

## Sprint S12 - Change model and policy
Goal: Change model and policy.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S12-01 | change model and digest | change model and digest; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 contract dependencies |  |
| S12-02 | state taxonomy | state taxonomy; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 contract dependencies |  |
| S12-03 | principal and approval records | principal and approval records; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 contract dependencies |  |
| S12-04 | policy and grants | policy and grants; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 contract dependencies |  |
| S12-05 | kill switch and WRITE/POST evaluator | kill switch and WRITE/POST evaluator; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 contract dependencies |  |
| S12-06 | error-code registry and crash matrix | error-code registry and crash matrix; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 contract dependencies |  |
| S12-07 | CT14 record as data | CT14 record as data; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 contract dependencies |  |

## Sprint S13 - Ledger and audit anchor
Goal: Ledger and audit anchor.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S13-01 | PostgreSQL ledger | PostgreSQL ledger; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 |  |
| S13-02 | transactional claim | transactional claim; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 |  |
| S13-03 | signed checkpoints | signed checkpoints; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 |  |
| S13-04 | fingerprint and target registry | fingerprint and target registry; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 |  |
| S13-05 | recovery sweep | recovery sweep; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12 |  |

## Sprint S14 - 1C write port
Goal: 1C write port.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S14-01 | write port | write port; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S13 |  |
| S14-02 | apply protocol | apply protocol; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S13 |  |
| S14-03 | call ownership and compare-and-write | call ownership and compare-and-write; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S13 |  |
| S14-04 | unknown-outcome resolution | unknown-outcome resolution; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S13 |  |
| S14-05 | draft/post/unpost | draft/post/unpost; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S13 |  |
| S14-06 | least-privilege role | least-privilege role; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S13 |  |
| S14-07 | token separation | token separation; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S13 |  |

## Sprint S15 - Verification and reconciliation
Goal: Verification and reconciliation.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S15-01 | verifier | verifier; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S13, S14 |  |
| S15-02 | independent oracle | independent oracle; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S13, S14 |  |
| S15-03 | A-to-B comparison | A-to-B comparison; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S13, S14 |  |
| S15-04 | bidirectional ledger-to-1C check | bidirectional ledger-to-1C check; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S13, S14 |  |
| S15-05 | negative-control set | negative-control set; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S13, S14 |  |

## Sprint S16 - Independent approval and MCP
Goal: Independent approval and MCP.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S16-01 | approval page | approval page; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S15 |  |
| S16-02 | registries and secrets | registries and secrets; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S15 |  |
| S16-03 | MCP surface | MCP surface; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S15 |  |
| S16-04 | private-network exposure | private-network exposure; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S15 |  |
| S16-05 | recorded tool-call replay | recorded tool-call replay; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S12, S15 |  |

## Sprint S17 - Document intake and workbench
Goal: Document intake and workbench.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S17-01 | untrusted-file boundary | untrusted-file boundary; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S16 |  |
| S17-02 | extraction | extraction; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S16 |  |
| S17-03 | entity resolution | entity resolution; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S16 |  |
| S17-04 | hostile corpus | hostile corpus; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S16 |  |
| S17-05 | workbench | workbench; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S16 |  |
| S17-06 | H3 measurement | H3 measurement; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S16 |  |

## Sprint S18 - Reliability and security
Goal: Reliability and security.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S18-01 | queue and parking | queue and parking; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S13-S16 |  |
| S18-02 | chaos | chaos; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S13-S16 |  |
| S18-03 | alerting | alerting; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S13-S16 |  |
| S18-04 | SLOs | SLOs; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S13-S16 |  |
| S18-05 | security review | security review; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S13-S16 |  |
| S18-06 | rights-matrix drift read | rights-matrix drift read; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | Queued; no task-ID commits | Codex | S13-S16 |  |

## Sprint S19 - Release candidate and acceptance
Goal: Release candidate and acceptance.

| Task | Title | Acceptance | Status | Evidence | Owner | Depends | Commit |
|---|---|---|---|---|---|---|---|
| S19-01 | exact-head manifest | exact-head manifest; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S17, S18 |  |
| S19-02 | closure validator run | closure validator run; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S17, S18 |  |
| S19-03 | matrix completeness | matrix completeness; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S17, S18 |  |
| S19-04 | residual-risk record | residual-risk record; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S17, S18 |  |
| S19-05 | canary recipe | canary recipe; detailed criteria are in the sprint plan/test-design record. | NOT_STARTED | UNKNOWN: sprint-level status only, no task-ID commits or task evidence | Codex | S17, S18 |  |
