# Phase 2 — Тест-стратегия, каталог сценариев и UAT

Версия 0.1 · 08.10.2026 · DRAFT.

Полный локальный перечень IDs и критериев: STORIES_PHASE2_RU.md. Расширенные Given/When/Then, YAML и Gherkin включены в сопровождающий переносимый пакет. Все 144 product acceptance scenarios имеют статус NOT_RUN. Изолированные проверки целостности спецификации выполняются отдельно и не меняют эти статусы.

## 1. Уровни и независимость

| Уровень | Что исполняется | Что доказывает |
|---|---|---|
| SPEC/L0 | Schemas, fixtures, crosslinks, DAG зависимостей, арифметические контрпримеры | Проверяемость спецификации, не наличие продукта |
| UNIT/L1 | Реальные canonicalizers, serializers, policy и parser budgets | Локальный код и negative branches, не native reconciliation |
| INTEGRATION/L2 | Настоящая disposable PostgreSQL, grants/RLS/FKs, leases/outbox, Redis и sandbox provider | Транзакционные и ролевые границы |
| FUNCTIONAL/L3 | MCP + adapter + разрешённая dev/reference 1С + native export | Реальная scoped цепочка capture/compare |
| QUALIFICATION/L4 | Manual UI против UI automation/qualified engine на одной копии | Конкретный report recipe и configuration |
| PROD/UAT | Явно разрешённая canary company с независимым утверждением | Source-specific acceptance, не blanket поддержка всех баз |

Ожидаемые значения не получаются из самого MCP result. Negative tests намеренно используют неверный scope, изменённые bytes, фиктивный PASS, expired permission и ошибки источника. Positive test alone недостаточен.

## 2. Как использовать companion tests

`python -m pytest -q tests` в каталоге переносимого пакета выполняет только SPEC/L0 без сети, Windows, 1С, секретов или импорта продукта. Проверяются схемы, ссылки между требованиями/историями/тестами, completeness каталогов и синтетический пример компенсирующих финансовых ошибок.

`acceptance/phase2.feature` содержит 144 сценария. Для их исполнения нужны настоящие step definitions и scoped product adapter. Нельзя реализовать шаг как безусловный success или проверку строки в конфигурации. Каждое Then должно утверждать наблюдаемое поведение продукта, БД, источника или evidence workflow.

Отсутствующий adapter, environment, разрешение или native evidence даёт BLOCKED/NOT_RUN и запрещает gate PASS. Файл validation_report.json сопровождающего пакета относится только к SPEC/L0.

## 3. Test data

Synthetic corpus: минимум два tenants, три companies, одинаковые имена поставщиков, несколько договоров с opposing debit/credit, posted/unposted/deleted receipts, нулевые/отрицательные/округлённые суммы, различные currencies/timezones, три версии схемы, partial pages, late events, moves/shortcuts/revisions/revoke.

Real reference corpus: утверждённая copy/config identity, native original artifacts и manifest. Цифры из переписки имеют статус USER_SUPPLIED_NOT_ATTESTED и не являются golden fixtures. Точные денежные строки и secrets не добавлять в Git. Десять копий одного comparison не считаются десятью независимыми cases.

Reset/write probes разрешаются только отдельному test harness на disposable target с явным разрешением. `reset.ps1`, DROP/TRUNCATE и пробные записи на real/prod запрещены. Не использовать изменение pytest testpaths как обход полномочий для operational script/secret access.

## 4. Наборы тестов

### Auth и contracts: TC001–018, TC121–123

Проверить R1/R2 boundary, exact build и donor inventory. Typed source IDs; arbitrary URL/SQL/command отказ до dispatch. Cross-tenant FK/API/RLS denial, company-only не получает source-wide metadata. Scope epoch проверяется до fetch и disclosure. Secret startup/rotation, missing pair preflight, отсутствие пароля/токена в логах, argv и artifacts. Job annotations, CSRF и idempotency правильны; отказ не обходится через raw COM/DC.

### PDM, LDM и время: TC019–048

Full baseline и coverage; namespace-qualified IDs; равнозначный XML formatting не создаёт structural drift. Type/scale/key/navigation/function changes дают diff. Partial/error/ACL narrowing не означают удаление объектов. Recovery не повышает trust автоматически. Append-only SQL privileges, replay, две оси времени, unknown effective time, late corrections и gaps. A→B→A между polls без history API не выдумывается. Candidate aliases/edges scoped; ambiguity требует решения человека. Неполный dependency graph — conservative denial. Accepted head использует CAS; incompatible rollback не снимает drift.

### Scheduler: TC049–060

Два workers одного source получают не более одного действительного lease/fence. Старый worker после expiry не публикует результат. Crash before page commit вызывает безопасный replay, без потерь/дубликатов. Cursor/outbox/result транзакционны. Один ID с разными bytes — conflict. Budget физической базы общий для source aliases и replicas. Queue bounded; foreground/background fairness; poison source изолирован; pause/reconnect повторно проверяет scope/cursor.

### Native capture: TC061–081

UI original, header/settings/totals, правильная база и организация. Partial screenshot не доказывает полный отчёт. Edited XLSX требует новой revision/digest. Manual/automated UI equivalence. Unknown modal/selector или wrong base вызывают отказ. Qualified standard engine сохраняет provenance; пустой COM результат не ноль и не повод выдать собственный query как native. Untrusted EPF denied. Prod default OFF, expiry/scope permit, idempotency conflict. No business writes с явной coverage технических effects. Private immutable artifacts должны реально существовать. Sandbox не исполняет macros/formulas/entities; zip-bomb, memory и timeout bounded; truncated result не PASS.

### Evidence и финансы: TC082–102

Actual bytes + digest + origin + scope + attestation FK. Независимый authenticated signer; uploader/connector/JSON signed_by не дают VALIDATED. Revocation снимает current applicability, но сохраняет историю. Candidate runner выдаёт EVALUATION_ONLY без public bypass; после approval повторяется canonical tool.

Сверять шесть колонок и строки. Одинаковый closing net при разных opening/turnover должен дать MISMATCH. Expanded debit/credit по договорам не скрываются netting. Explicit account-based AP strategy; отсутствующий register не выдумывается. Balance alone не доказывает aging. Posted purchases MOLDRETAIL проверяются по company/supplier/deletion/pagination. Разные snapshots/cutoff — INCONCLUSIVE. Backdated correction — новый run. Десять arbitrary IDs не заменяют coverage; отдельная purchases policy не открывает AP и не меняет R1.

S6b (offline fixtures, IMPLEMENTED_UNVERIFIED, не PASS на реальных данных): TC091-093 - `ap_account_strategy.py`: ledger strategy QUALIFIED только когда каждый заявленный input есть в описании источника; отсутствующий settlements register - ABSENT (не исключение, без баланса и aging, без fallback); один balance - BALANCE_ONLY, aging NOT_AVAILABLE; aging только из open items с document date и due date на КАЖДОЙ строке, buckets точно равны open total. TC094-096 - `posted_receipts.py`: retriever принимает `PurchaseScope` + direction RECEIPT + supplier `Reference`, проверяет запрос и alias (RESOLVED только по точной namespaced ссылке в company scope) до любого fetch, листает страницы через порт `fetch_page` и считает исключения по причинам; COMPLETE только при terminal page, непрерывной цепочке токенов, отсутствии дублей doc_ref, неизменном snapshot_ref и в пределах MAX_PAGES/MAX_ROWS; `assess_receipts` возвращает три независимых вердикта (completeness / correctness / discrepancy). Тесты: `test_ap_account_strategy.py` (217), `test_posted_receipts.py` (117), `test_posted_receipts_pagination.py` (73), `test_posted_receipts_assessment.py` (71), `test_s6b_boundaries.py` (7, AST: нет Release 1/network/file/DB). NOT_RUN: реальный 1C read grant для 818HA, реальный постраничный источник и его page-size/token поведение, реальные MOLDRETAIL receipts и native journal (UAT-U02), аттестация бухгалтера (G3), реальные байты native отчётов, валидация маппинга accounting register 818HA, открытие capability `ap.account_based`, wiring в runtime/Release 1, persistence, Release 1 regression, CI, mutation runs.

### Drive: TC103–114

Проверить фактический OAuth/file/folder/shared-drive scope и доступ к новым children. Application folder filter не назвать OAuth isolation широкого токена. Start token до baseline, затем catch-up и durable cursor. Separate account/drive namespaces. Lost cursor вызывает controlled resnapshot/gap. Revision/move/shortcut/revoke проверяют текущий scope. Viewer/readonly не обязан иметь revision history: нельзя выдать writer/keepForever mutation ради теста. Token invalid_grant даёт AUTH_REQUIRED и алерт. Webhook duplicate/out-of-order — только hint; polling работает без watch.

S7 (offline fixtures, IMPLEMENTED_UNVERIFIED, не PASS на реальном Google; G4 остаётся открытым): TC103-105 - `drive_scope.py` + `drive_oauth.py`: narrow grant плюс scripted in-scope read даёт PROVEN с basis, файл вне corpus отказан, пустой/неразрешённый corpus ничего не доказывает; ребёнок, созданный после grant, PROVEN только по scripted observation (fake, скрывающий новых детей, даёт NOT_PROVEN/DENIED); broad grant даёт claim BROAD с isolation APPLICATION_FILTER_ONLY, ярлык folder isolation отказан, без риск-метки BROAD_ACCEPTED нельзя продолжать; consent ERP_MCP-owned (token чужого store недостижим, replayed/foreign/expired state отказан). TC106-108 - `drive_baseline.py` + `drive_cursor.py`: порядок getStartPageToken -> persist -> baseline -> catch-up -> LIVE проверяется call log; namespaces `account:<id>`/`drive:<id>` не пересекаются; потерянный/пустой/повреждённый/чужой cursor, repeated/regressed token, unknown change kind дают GAP/RESNAPSHOT_REQUIRED и не очищаются автоматически; page и cursor all-or-nothing, stale fence ничего не коммитит. TC109-111 - `drive_revisions.py` + `drive_membership.py`: новая revision даёт UNATTESTED, старый PASS становится PASS_HISTORICAL; forbidden history даёт HISTORY_UNAVAILABLE / CURRENT_ONLY без write-вызовов; move/shortcut вне corpus и неразрешённый parent дают SCOPE_ESCAPE_DENIED без раскрытия; удаление даёт tombstone без угаданной замены; revoke перепроверяется до disclosure. TC112-114 - `drive_auth_state.py`: invalid_grant / revoke дают AUTH_REQUIRED, один alert на переход, port calls заблокированы fail-closed, cursor не двигается; expired-but-refreshable не AUTH_REQUIRED; hint только планирует poll (дубликаты и out-of-order схлопываются, чужой канал игнорируется, данные игнорируются); polling даёт тот же результат без hints и без watch. Тесты: `test_drive_port_fake.py` (108), `test_drive_oauth.py` (110), `test_drive_scope.py` (116), `test_drive_baseline.py` (53), `test_drive_cursor.py` (56), `test_drive_revisions.py` (48), `test_drive_membership.py` (42), `test_drive_auth_state.py` (41), `test_drive_hints.py` (16), `test_s7_boundaries.py` (50, AST: нет Release 1/PDCC/network/DB/env/file I/O/drive_http, port read-only, нет real token/scope URL); baseline/cursor счётчики as of drafting. NOT_RUN: реальная регистрация Google OAuth client, реальные access/refresh tokens и обмен, реальная папка/shared drive и поведение narrow scope на новых children (G4), реальные quotas/429/403, реальные changes.list токены, watch channels и webhook endpoint, реальная revision history для Viewer, доставка alert, PostgreSQL для S7, wiring в runtime/Release 1, CI, mutation runs.

### UI, prod, operations и release: TC115–144

Workbench связывает mismatch с fragment/строкой/owner; исходные числа immutable; rerun создаёт новую запись. Timeline ясно разделяет known/effective и historical/live. Safe errors без чужих IDs/секретов. Prod canary только с permit, dev PASS не prod approval; kill switch действует только на owned job.

Capacity: sessions отдельно от active clients и source count отдельно от physical backends. Отказы по profile не business throughput. Background interference измеряется. Audit outage блокирует действие до effect; алерт действительно срабатывает и восстанавливается. Worker/provider faults не теряют и не дублируют публикации. Expand/shadow сохраняет R1; rollback не resurrect revoked grants. Restore проверяет artifact hashes/FKs/heads/attestations. Export masking/formula safety; legal hold и no unapproved deletion. Дополнительные donors квалифицируются по pin. Exact release manifest не объявляет NOT_RUN пройденным.

## 5. Нагрузочная матрица

До нагрузки фиксируются hardware/deployment/build/config/dataset, workload и qualified tools. Сетка: 30/50/100/150 sources; 1/5/10/20/50/100 active clients; отдельно 50/100/500/1000 sessions; один/несколько physical backends; cold/warm; metadata/documents/balances/report capture; discovery off/on. Сначала короткие ступени, затем 2h/8h soak на устойчивом уровне.

Real 1С нагружается только с отдельными scope/window/budget/stop criteria. Измерять business reads/sec, p50/p95/p99, queue/pool wait, source busy/timeouts, RSS/CPU, latency пользователей 1С, audit/cursor lag, missed/duplicate events. Config limit не является capacity proof. Останавливать тест при согласованном превышении latency, sustained errors, saturation, unsafe side effects или budget.

Предлагаемые targets, не измеренные гарантии: warm metadata p95 ≤500ms; enqueue p95 ≤500ms; увеличение foreground p95 от background ≤20%. Конкретные SLO подтверждаются на выбранном стенде. Отказавшие ACL/profile requests считаются отдельно.

## 6. UAT обычного пользователя

UAT-U01: статус собственной компании и safe причина BLOCKED.
UAT-U02: posted MOLDRETAIL receipts — dates/number/amount/currency/full pagination и native journal.
UAT-U03: ОСВ521.1 — все шесть показателей, contracts, expanded/net, native provenance, timezone/currency.
UAT-U04: история с явно выбранными known/effective axes.
UAT-U05: чужая компания и arbitrary SQL/COM вызывают отказ.
UAT-U06: revoke mid-job предотвращает выдачу из cache/artifact URL.

## 7. UAT администратора/бухгалтера

UAT-A01: connection/scope/secret reference/budget/preflight.
UAT-A02: observed → diff → impact → accepted; LLM не approver.
UAT-A03: native UI baseline и квалификация recipe на копии.
UAT-A04: independent attestation; fake/duplicate ten cases rejected.
UAT-A05: Drive report/revision/move/revoke; latest applicability отдельно от history.
UAT-A06: prod OFF, time-bound permit, canary, revoke/kill switch.
UAT-A07: отказ вызывает алерт, восстановление снимает его корректно.
UAT-A08: restore/rollback без reset real lane и без возврата отозванных прав.

## 8. Test evidence и exit

Для каждого actual result: testcase_id, PASS/FAIL/BLOCKED/NOT_RUN, exact build/config/recipe/step hash, environment/source/company, start/end, реальные assertions, sanitized artifact refs/SHA, correlation, scope/authority, reviewer/approver и deviations. Planned expected не смешивается с actual.

Gate PASS допускается только после выполнения обязательных cases, отсутствия неразобранных correctness/security mismatches и необходимых независимых approvals. Specification tests не заменяют эту приёмку. Никаких production/native тестов данным пакетом не запускалось.
