# ERP_MCP Phase 2 — Test Strategy, Scenario Catalog and UAT

**Version 0.1 · October 8, 2026 · DRAFT.**

The complete local list of IDs and acceptance criteria is in `STORIES_PHASE2_RU.md`. Extended Given/When/Then steps, YAML catalogs and Gherkin are included in the portable companion package.

**Historical checkpoint:** All 144 product acceptance scenarios were `NOT_RUN` at the original specification stage. Isolated specification-integrity checks did not change those statuses. Later evidence must be assessed against the actual Git HEAD and test executions.

## 1. Verification Levels and Independence

| Level | What executes | What it proves |
| --- | --- | --- |
| **SPEC/L0** | JSON Schemas, fixtures, cross-links, dependency DAG and arithmetic counterexamples | Specification consistency, **not** implementation |
| **UNIT/L1** | Real canonicalizers, serializers, policy checks and bounded parsers | Local code and negative branches, **not** native reconciliation |
| **INTEGRATION/L2** | Disposable real PostgreSQL, grants/RLS/FKs, leases/outbox, Redis and sandbox provider | Transaction and authorization boundaries |
| **FUNCTIONAL/L3** | MCP, adapter, approved development/reference 1C, and original native export | Genuine scoped capture/compare chain |
| **QUALIFICATION/L4** | Manual UI versus qualified UI automation or standard engine on the same copy | Source-specific report procedure and configuration |
| **PROD/UAT** | Explicitly permitted canary company with independent approval | Source-specific acceptance, **not** universal compatibility |

Expected results must not be generated from the same MCP result under examination. Negative tests deliberately vary scope, modify original bytes, forge a PASS, expire permissions or simulate failures. A positive case alone is insufficient.

## 2. Companion Test Execution

Running `python -m pytest -q tests` from the **portable specification package directory** executes only offline SPEC/L0 tests without network, Windows, 1C, secrets or application imports. These cover schemas, requirement/story/test references, catalog completeness and a synthetic counterexample where financial errors compensate.

`acceptance/phase2.feature` contains 144 scenarios. Executing them requires **real step definitions and a scoped product adapter**. An unconditional success step or string search in a configuration is not a valid implementation. Every Then must assert observable product, database, source, or evidence-workflow behavior.

A missing adapter, environment, authorization, or native artifact produces `BLOCKED` or `NOT_RUN` and prevents gate PASS. The companion `validation_report.json` applies **only** to SPEC/L0.

## 3. Test Data

The synthetic corpus includes at least two tenants, three companies, identical supplier names across company scopes, multiple contracts with opposing debits and credits, posted/unposted/deleted purchase receipts, zero/negative/rounded amounts, different currencies/time zones, three schema versions, partial pages, late events, moves/shortcuts/revisions, and revocation.

The real reference corpus requires an approved database copy and configuration identity, original native artifacts and a manifest. Financial figures from the chat are `USER_SUPPLIED_NOT_ATTESTED`, **not** golden test fixtures. Never commit private financial lines or secrets to Git. Ten copies of one comparison are not ten independent cases.

Reset/write probes are permitted only through a separately approved test harness targeting an authorized disposable environment. Never use `reset.ps1`, `DROP`, `TRUNCATE`, or exploratory writes against a real/production database. Changing pytest test paths is not a way to bypass permission restrictions on operational scripts or secrets.

## 4. Test Suites

### Authorization and Contracts — TC001–018, TC121–123

Implementation note (S8, TC121-123): an offline decision layer `jobs_api.py` exists; see the S8 paragraph in the status notes at the end of this file (IMPLEMENTED_UNVERIFIED).

Verify the R1/R2 boundary, exact build, and donor inventory. Typed source IDs; arbitrary URLs, SQL and shell commands rejected **before dispatch**. Cross-tenant FK/API/RLS denials. Company-only access does not grant global metadata. Check the authorization epoch before fetch and again before disclosure. Validate secret startup, rotation, missing-pair preflight and no credential leakage through logs, argv or artifacts. Job annotations, CSRF and idempotency must be correct; raw COM/DC cannot bypass denial.

### PDM, LDM and Temporal Semantics — TC019–048

Verify complete baseline/coverage, namespace-qualified IDs, and a canonicalizer that ignores semantically irrelevant XML formatting while detecting type/scale/key/navigation/function changes. Partial results, errors and narrowed ACLs cannot imply object removal. Recovery never increases trust automatically.

Check SQL append-only privileges, replay, both time axes, unknown effective dates, late corrections and gaps. A–B–A changes between polls without history API are not invented. Candidate aliases and taxonomy edges are scoped; ambiguities require a human decision. Unknown dependency graphs deny conservatively. Accepted-head changes require CAS; incompatible rollback cannot silently clear drift.

### Scheduler and Cursor Safety — TC049–060

Two workers on the same source must have at most one valid lease/fence. A worker that has lost its lease cannot publish. Crash before page commit must allow lossless, duplicate-free replay. Cursor/outbox/result writes are transactional. The same event ID with different bytes is a conflict.

Budgets apply to the **physical backend** across source aliases and replicas. Verify bounded queueing, foreground/background fairness, isolation of poisoned sources, and fresh scope/cursor validation before resume.

### Native Capture and Parser — TC061–081

Verify original UI report, headers/settings/totals, exact source and company. Partial screenshots cannot prove a complete report. Editing an XLSX artifact requires a new revision/digest. Manual and automated UI capture must be equivalent. Unknown modal/selector or wrong database must fail without guessed clicks.

Qualified standard-engine reports must retain genuine provenance. Empty COM output is not zero and cannot justify relabeling an internally generated query as native. Untrusted EPF content is rejected.

Production capture defaults OFF. Enforce permit scope, expiry and idempotency conflicts. Prove the absence of business writes, including coverage of technical side effects. Private immutable artifacts must genuinely exist. Parser isolation never evaluates macros, formulas or external entities; zip bombs, memory and time budgets are bounded, and truncated results cannot count as PASS.

### Independent Evidence and Finance — TC082–102

Require original bytes, digest, origin, scope and a real attestation foreign key. The signer must be independently authenticated; uploaders, connectors and a JSON `signed_by` field cannot confer `VALIDATED`. Revocation ends current applicability while preserving history.

The candidate runner outputs only `EVALUATION_ONLY`, never a public validation bypass. Canonical tools can be replayed after qualified approval.

Compare **all six** report aggregates and underlying rows. Equal closing net balances with incorrect openings/turnovers must produce `MISMATCH`. Contract debit/credit sides must not be hidden by netting. Accounting-based AP requires an explicit qualified strategy; a missing settlement register cannot be invented and balances alone do not prove aging.

Posted MOLDRETAIL purchases must be checked for company, supplier, deletion state and complete pagination. Differing snapshots or cutoffs yield `INCONCLUSIVE`; a backdated correction creates a new run. Ten arbitrary evidence IDs do not establish coverage. Approving purchases does not enable AP or modify R1 validation.

### Google Drive — TC103–114

Prove actual OAuth/file/folder/shared-drive scope and behavior for newly created child files. An application-level folder filter **is not** OAuth permission isolation if the token is broad.

Acquire the start token before baseline capture; perform catch-up and persist a durable cursor. Separate account/drive namespaces. Lost cursor leads to controlled resnapshot and a declared gap.

Test revisions, moves, shortcuts and revocation against **current** access scope. Viewer/read-only may not include revision history; do not grant writer access or mutate `keepForever` to make a test pass. `invalid_grant` yields `AUTH_REQUIRED` and an alert. Duplicate or out-of-order webhooks are hints only; polling must function without watch.

### Workbench, Production, Operations and Release — TC115–144

The workbench links discrepancies to fragments, rows, owners and deltas. Original numbers are immutable, and reruns produce new records. Timelines distinguish known/effective and historical/current states. Safe errors reveal no foreign IDs or secrets.

Production canary requires a separate permit: a development PASS is not production approval. The kill switch controls only owned jobs.

Capacity reports must distinguish sessions from active clients and source counts from physical backends. Denied/unvalidated profile requests do not count as business throughput. Measure background interference. Audit unavailability must block a transaction before its effect and actually trigger/recover an alert. Worker/provider failures must not lose or duplicate publications.

Expand/shadow rollout preserves R1; rollback cannot resurrect revoked grants. Restore verification includes artifact hashes, foreign keys, accepted heads and attestations. Exports require masking, tenant isolation and spreadsheet-formula safety. Honor legal holds; no unauthorized deletion. Additional donors need pin/licensing qualification. The exact-head release manifest cannot present `NOT_RUN` as PASS.

## 5. Load-Test Matrix

Before load testing, pin hardware, deployment, build, configuration, dataset, workload and qualified tools.

Test across:
- **Sources:** 30, 50, 100, 150.
- **Active clients:** 1, 5, 10, 20, 50, 100.
- **Sessions (independently):** 50, 100, 500, 1,000.
- **Backends:** One or multiple physical backends; cold/warm; metadata, documents, balances, native report capture; discovery enabled/disabled.

Start with short steps, then 2-hour and 8-hour soak tests at a stable qualified load.

A real 1C backend may be load-tested only with a separately approved scope, time window, budget and stop criteria. Measure business reads/s, p50/p95/p99, queue and connection-pool wait, source busy/timeout rates, RSS/CPU, actual 1C user latency, audit/cursor lag, and missed/duplicate events.

**Configuration limits are not capacity evidence.** Stop when approved latency thresholds, sustained errors, saturation, unsafe side effects, or resource budgets are exceeded.

Proposed targets, **not measured guarantees**: warm metadata p95 no more than 500 ms; enqueue p95 no more than 500 ms; foreground p95 increase under background load no more than 20%. Actual SLOs require qualification on the chosen environment. Report failed ACL/profile requests separately.

## 6. Normal User UAT

| ID | Required scenario |
| --- | --- |
| UAT-U01 | View own company's status and a safe explanation for `BLOCKED` |
| UAT-U02 | Posted MOLDRETAIL receipts: dates, document numbers, amounts, currencies, complete pagination and native journal |
| UAT-U03 | Account 521.1 trial balance: all six measures, contracts, expanded/net views, native provenance, currency and time zone |
| UAT-U04 | Historical timeline with explicit known/effective time axis selection |
| UAT-U05 | Access to another company or arbitrary SQL/COM command is denied |
| UAT-U06 | Mid-job revocation prevents disclosures from caches and artifact URLs |

## 7. Administrator and Accountant UAT

| ID | Required scenario |
| --- | --- |
| UAT-A01 | Connection, scope, secret reference, budget and preflight |
| UAT-A02 | Observed → diff → impact → accepted; LLM is not an approver |
| UAT-A03 | Native UI baseline and qualified recipe on a disposable source copy |
| UAT-A04 | Independent attestation; fake/duplicated ten-case evidence rejected |
| UAT-A05 | Drive report, revision, move and revoke; current applicability separated from history |
| UAT-A06 | Production OFF by default, time-bound permit, canary, revocation and kill switch |
| UAT-A07 | A failure fires a real alert and recovery clears it correctly |
| UAT-A08 | Restore/rollback without reset of a real source and without reinstating revoked access |

## 8. Test Evidence and Exit Conditions

Every actual result must record:
- Test-case ID and `PASS`/`FAIL`/`BLOCKED`/`NOT_RUN`.
- Exact build, configuration, procedure, and step-definition hash.
- Environment, source/company, start/end times.
- **Actually executed assertions** and sanitized artifact references/hashes.
- Correlation ID, scope and authorization basis.
- Reviewer/approver and recorded deviations.

Planned expected results must never be confused with actual outcomes.

Gate PASS requires all mandatory cases to have executed successfully, no unresolved correctness/security discrepancy, and the required independent approvals. Specification tests **do not replace** product acceptance.

**No production or native 1C tests were performed by the initial design package itself.** Later test evidence must always be reported with its own exact Git HEAD and measured environment.

## Implementation Status Notes S6b-S9 (from the phase2 branch)

<!-- Carried over verbatim from origin/phase2/living-model-connectors-reconciliation; this status text is not yet translated to English. -->

S6b (offline fixtures, IMPLEMENTED_UNVERIFIED, не PASS на реальных данных): TC091-093 - `ap_account_strategy.py`: ledger strategy QUALIFIED только когда каждый заявленный input есть в описании источника; отсутствующий settlements register - ABSENT (не исключение, без баланса и aging, без fallback); один balance - BALANCE_ONLY, aging NOT_AVAILABLE; aging только из open items с document date и due date на КАЖДОЙ строке, buckets точно равны open total. TC094-096 - `posted_receipts.py`: retriever принимает `PurchaseScope` + direction RECEIPT + supplier `Reference`, проверяет запрос и alias (RESOLVED только по точной namespaced ссылке в company scope) до любого fetch, листает страницы через порт `fetch_page` и считает исключения по причинам; COMPLETE только при terminal page, непрерывной цепочке токенов, отсутствии дублей doc_ref, неизменном snapshot_ref и в пределах MAX_PAGES/MAX_ROWS; `assess_receipts` возвращает три независимых вердикта (completeness / correctness / discrepancy). Тесты: `test_ap_account_strategy.py` (217), `test_posted_receipts.py` (117), `test_posted_receipts_pagination.py` (73), `test_posted_receipts_assessment.py` (71), `test_s6b_boundaries.py` (7, AST: нет Release 1/network/file/DB). NOT_RUN: реальный 1C read grant для 818HA, реальный постраничный источник и его page-size/token поведение, реальные MOLDRETAIL receipts и native journal (UAT-U02), аттестация бухгалтера (G3), реальные байты native отчётов, валидация маппинга accounting register 818HA, открытие capability `ap.account_based`, wiring в runtime/Release 1, persistence, Release 1 regression, CI, mutation runs.

S7 (offline fixtures, IMPLEMENTED_UNVERIFIED, не PASS на реальном Google; G4 остаётся открытым): TC103-105 - `drive_scope.py` + `drive_oauth.py`: narrow grant плюс scripted in-scope read даёт PROVEN с basis, файл вне corpus отказан, пустой/неразрешённый corpus ничего не доказывает; ребёнок, созданный после grant, PROVEN только по scripted observation (fake, скрывающий новых детей, даёт NOT_PROVEN/DENIED); broad grant даёт claim BROAD с isolation APPLICATION_FILTER_ONLY, ярлык folder isolation отказан, без риск-метки BROAD_ACCEPTED нельзя продолжать; consent ERP_MCP-owned (token чужого store недостижим, replayed/foreign/expired state отказан). TC106-108 - `drive_baseline.py` + `drive_cursor.py`: порядок getStartPageToken -> persist -> baseline -> catch-up -> LIVE проверяется call log; namespaces `account:<id>`/`drive:<id>` не пересекаются; потерянный/пустой/повреждённый/чужой cursor, repeated/regressed token, unknown change kind дают GAP/RESNAPSHOT_REQUIRED и не очищаются автоматически; page и cursor all-or-nothing, stale fence ничего не коммитит. TC109-111 - `drive_revisions.py` + `drive_membership.py`: новая revision даёт UNATTESTED, старый PASS становится PASS_HISTORICAL; forbidden history даёт HISTORY_UNAVAILABLE / CURRENT_ONLY без write-вызовов; move/shortcut вне corpus и неразрешённый parent дают SCOPE_ESCAPE_DENIED без раскрытия; удаление даёт tombstone без угаданной замены; revoke перепроверяется до disclosure. TC112-114 - `drive_auth_state.py`: invalid_grant / revoke дают AUTH_REQUIRED, один alert на переход, port calls заблокированы fail-closed, cursor не двигается; expired-but-refreshable не AUTH_REQUIRED; hint только планирует poll (дубликаты и out-of-order схлопываются, чужой канал игнорируется, данные игнорируются); polling даёт тот же результат без hints и без watch. Тесты: `test_drive_port_fake.py` (108), `test_drive_oauth.py` (110), `test_drive_scope.py` (116), `test_drive_baseline.py` (53), `test_drive_cursor.py` (56), `test_drive_revisions.py` (48), `test_drive_membership.py` (42), `test_drive_auth_state.py` (41), `test_drive_hints.py` (16), `test_s7_boundaries.py` (50, AST: нет Release 1/PDCC/network/DB/env/file I/O/drive_http, port read-only, нет real token/scope URL); baseline/cursor счётчики as of drafting. NOT_RUN: реальная регистрация Google OAuth client, реальные access/refresh tokens и обмен, реальная папка/shared drive и поведение narrow scope на новых children (G4), реальные quotas/429/403, реальные changes.list токены, watch channels и webhook endpoint, реальная revision history для Viewer, доставка alert, PostgreSQL для S7, wiring в runtime/Release 1, CI, mutation runs.

S8 (offline fixtures, IMPLEMENTED_UNVERIFIED; G5 user/admin UAT остаётся operator-owned, NOT_STARTED/OPEN): TC115-117 - `workbench_review.py`: карточка discrepancy из `RunLedger` с exact `Decimal` native/gateway/delta (delta = gateway - native, переполнение точности даёт DELTA_PRECISION_EXCEEDED без карточки), fragment ref (snapshot_digest, row_key, measure), owner из injected directory или OWNER_UNASSIGNED, key-only differences дают ROW_DETAIL_UNAVAILABLE; `original_digest` и `verify_original` дают ORIGINAL_INTACT / ORIGINAL_TAMPERED, попытка override - ORIGINAL_NUMBERS_IMMUTABLE, `ReviewLog` append-only и не трогает числа; `request_rerun` создаёт новый run через `RunLedger.run(rerun_of=...)` (NO_NEW_EVIDENCE, RERUN_TARGET_STALE, RERUN_TARGET_UNKNOWN, NOT_IN_SCOPE). TC118-120 - `timeline_view.py` + `coverage_view.py`: отдельные `KnownTimeLabel` и `EffectiveTimeLabel`, EFFECTIVE_UNKNOWN вместо подстановки известного времени; `Applicability` LIVE_CURRENT / HISTORICAL_PASS / REVOKED / UNATTESTED / INCONCLUSIVE / FAIL / NOT_COVERED / UNKNOWN, `is_green` истинна только для LIVE_CURRENT (CURRENT run + `check_current` + полный coverage + свежесть + source не paused); чужие записи и evidence отбрасываются, остаётся только opaque HIDDEN_BY_SCOPE (без счётчика и id), stale epoch даёт SCOPE_EPOCH_STALE. TC121-123 - `safe_errors.py` + `jobs_api.py`: `SafeError` (reason_code, next_action, correlation_id) из закрытых enum, fixed message table, poison strings не попадают в output и `repr`; annotation table `ENDPOINTS` (ENQUEUE_JOB, RERUN, PAUSE_SOURCE, REVOKE_ATTESTATION - mutating, READ_JOB, READ_RESULT - read-only); порядок проверок session -> CSRF -> scope/epoch -> boundary -> idempotency -> dispatch; CSRF_REJECTED = 403 без dispatch и без idempotency record; тот же key + тот же digest = replay, другой digest = 409 IDEMPOTENCY_CONFLICT; отказ boundary (WRITE/POST/DELETE/RESET/ADMIN/UNCLASSIFIED) не обходится регистром, пробелами, lookalike или другим channel label, dispatcher call log = 0, в сигнатурах нет channel/command/query/sql/raw. Тесты: `test_workbench_types.py` (66), `test_workbench_review.py` (128), `test_timeline_view.py` (204), `test_coverage_view.py` (197), `test_safe_errors.py` (61), `test_jobs_api.py` (67), `test_jobs_api_bypass.py` (59), `test_workbench_session.py` (E4, 28 as of drafting, may still change), `test_s8_boundaries.py` (51, AST: нет Release 1/PDCC/network/DB/web framework/COM/1C/drive_http/env/file I/O, нет free-form command/query/sql/raw/channel в сигнатурах и request types, annotation table покрывает каждую decision function, нет real-shaped token). NOT_RUN: реальный UI (HTML/JS), browser и accessibility checks, G5 user/admin UAT, реальные HTTP server/cookies/CSRF/session/RBAC, PostgreSQL для jobs/idempotency/refusal (`JobQueuePort` не вызывается), реальные 1C COM/DC, load/capacity, alert delivery, wiring в runtime/Release 1, CI, mutation runs.

S9 (offline fixtures, IMPLEMENTED_UNVERIFIED; G6-pre остаётся NOT_STARTED/OPEN и NOT PASSED, G6 BLOCKED): TC127-129 - `capacity_model.py` + `capacity_interference.py` (общие типы `ops_types.py`): sessions, active clients, source count и backend count - четыре разных типа, "1000 sessions" без active-client измерения отказ (SESSIONS_NOT_ACTIVE_CLIENTS), PROFILE_REFUSED не входит в business throughput и percentiles (REFUSALS_DOMINATE), точные integer-microsecond percentiles (INSUFFICIENT_SAMPLES), `Decimal` interference ratio против параметризованной цели, `plan_budget` не отдаёт background меньше минимума. TC130-132 - `audit_gate.py` (effect вызывается 0 раз при AUDIT_UNAVAILABLE, AUDIT_COMPLETION_PENDING как явное обязательство), `delivery_replay.py` (429/network/duplicate-ack, digest de-dup, EVENT_DIGEST_CONFLICT, STALE_CLAIM, cursor не уходит дальше недоставленного), `alert_rules.py` (один FIRED и один RECOVERED на эпизод, NO_DATA, ALERT_DELIVERY_FAILED). TC133-135 - `release_migration.py` + `release_rollback.py` (классификация шагов ADDITIVE/SWITCH_ONLY/CONTRACT/DESTRUCTIVE/UNCLASSIFIED, R1_UNCHANGED/R1_REGRESSION/SHADOW_DIVERGENCE/SHADOW_INCOMPLETE, rollback только решение с executed=False, grants считаются из CURRENT state, RESURRECTION_BLOCKED); SQL text guard читает только `db/phase2/001..003`. TC136-138 - `restore_verify.py` (manifest, 13 FK edges, digests, heads, sequence, attestations), `export_safety.py` (tenant/company filter, masking, formula neutralization в значениях и заголовках, HIDDEN_BY_SCOPE), `retention_hold.py` (hold, retention, approval, `executed=False`, нет delete path); `g6_pre_readiness.py` перечисляет evidence slots как NOT_RUN и не имеет поля "passed". Тесты (`--co -q`): `test_ops_types.py` (107), `test_capacity_model.py` (195), `test_capacity_interference.py` (85), `test_audit_gate.py` (44), `test_delivery_replay.py` (48), `test_alert_rules.py` (84), `test_release_migration.py` (134), `test_release_rollback.py` (126), `test_release_sql_guard.py` (44), `test_restore_verify.py` (118), `test_export_safety.py` (143), `test_retention_hold.py` (57), `test_g6_pre_readiness.py` (33), `test_s9_boundaries.py` (108), итого 1326; `test_s9_scenarios.py` добавляется E5, count TBD. NOT_RUN: реальная нагрузка на 30/50/100/150 sources и real 1C (G6-pre actual workload metrics), реальный audit sink и alert delivery, chaos/fault injection на реальных процессах, kill -9, выполнение миграций и rollback на PostgreSQL, Release 1 regression, реальный backup/restore и pg restore proof, реальный export, фактическое удаление и retention job, production permit и canary, wiring в runtime/Release 1, CI, mutation runs (operator ban). Release 2 остаётся NO-GO; G1, G4, G5 и G6-pre NOT PASSED. Результаты тестов доказывают только логику decision-функций над scripted inputs.
