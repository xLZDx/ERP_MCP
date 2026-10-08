# ERP_MCP — Phase 2: Living Model Registry, Connectors и Native Reconciliation

Версия 0.1 · 08.10.2026 · DRAFT FOR REVIEW.
Статус: проектное ТДД, не разрешение на реализацию/развёртывание или доступ в production.
Связанные документы: PLAN_PHASE2_RU.md, STORIES_PHASE2_RU.md, TEST_PLAN_PHASE2_RU.md, NATIVE_REPORT_PROTOCOL_RU.md, DECISIONS_AND_SOURCES_RU.md.
Расширенный переносимый пакет сопровождает эти документы: 28 требований, 48 историй, 144 acceptance cases, Gherkin, YAML-каталоги, JSON Schemas и SPEC/L0 tests.

## 1. Граница R1/R2

Release 1 остаётся в действующем frozen scope. Эти документы не объявляют R1 выпущенным, не отменяют существующие native-report gates, не меняют миграции и полномочия. Дефекты безопасности/достоверности текущего R1 пути исправляются в R1; они не превращаются в допустимые ограничения просто переносом в R2.

Phase 2 добавляет reusable connector framework, continuous discovery, taxonomy/LDM/PDM, bitemporal history, точечное влияние drift, provenance/attestation, native report capture, автоматическую сверку и discrepancy workbench.

Оператор согласовал проектирование возможности получать штатные отчёты из приложения 1С для dev и сохранить эту возможность для prod. Это не текущий permit на вход в production, запуск EPF, копирование базы или выдачу новых прав. Включение prod capture привязано к конкретной базе/компании, recipe, времени и бюджету.

Главное изменение в R2: настоящий штатный отчёт 1С не становится синтетическим только потому, что его запуск автоматизирован. Но квалификация способа, происхождение оригинала, совпадение чисел и бухгалтерское утверждение — независимые проверки. Старые engine reports не переименовываются в native UI evidence и не валидируются задним числом.

## 2. Цели, термины, нецели

PDM — физико-прикладная модель разрешённого интерфейса: опубликованные объекты 1С, поля, типы, ключи, связи и операции. Это не прямое чтение внутренних SQL-таблиц 1С.
LDM — версионируемая логическая модель бизнес-понятий, отношений, контрактов и соответствий источникам.
Drive catalog — модель файлов/ревизий/доказательств, а не физическая бухгалтерская БД.
Observed — что источник позволил наблюдать; accepted — какая версия принята по policy; validated — какие конкретные семантические операции подтверждены доказательствами.

Цели: актуальная наблюдаемая/принятая карта источников; история изменений и решений; проверяемое происхождение каждого mapping; штатные отчёты 1С; воспроизводимая сверка по строкам/итогам; точное объяснение BLOCKED; сохранение ограничений доступа.

Вне scope: произвольный shell/BSL/COM/SQL из MCP; записи/проведение/удаление в 1С; unrestricted replication всех данных в Postgres; автоматическое утверждение LLM; blanket импорт всех коннекторов PDCC без аудита; обещание 1000 активных бухгалтерских запросов по max_sessions.

## 3. Базовое состояние

Перечитаны существующий Phase 2 backlog, AGENTS, DOCUMENT_INDEX, NATIVE_REPORT_CAPTURE_RUNBOOK и LOAD_TEST_REPORT. Рабочее дерево имеет сторонние staged/unstaged изменения. Последний прочитанный короткий SHA — 4a21a01; ранее в переписке был 1294b42. Это moving working tree, не аттестация deployed build.

R1 уже имеет source/company registry, OAuth/ACL, PostgreSQL/Redis, capabilities, metadata fingerprint, semantic profiles/mappings/events, read-only OData и отдельные разрешённые COM routes.

Нативный runbook сообщает: некоторые ОСВ/карточки счёта требуют interactive form и через внешнее соединение дают EMPTY/UNAVAILABLE. Поэтому наличие COMConnector не доказывает доступность конкретного отчёта через COM. В этом случае нужен штатный UI recipe, а пустой результат не трактуется как нулевой баланс.

## 4. Функциональные требования

| ID | Требование |
|---|---|
| R2-REQ-01 | Сохранить R1/R2 boundary, staged rollout и exact-build evidence |
| R2-REQ-02 | Один source registry; tenant/company/source/field ACL и server-side IDs |
| R2-REQ-03 | Read-only connector SDK; отдельная авторизация самого источника |
| R2-REQ-04 | Audit/pin/license/portability PDCC, ERP и Ferma |
| R2-REQ-05 | Baseline/incremental discovery с доказанной coverage |
| R2-REQ-06 | Canonical object/field/operation hashes отдельно от raw provenance hash |
| R2-REQ-07 | Независимые observed/accepted версии и решения |
| R2-REQ-08 | Версионируемая taxonomy/LDM, typed edges, aliases и confidence |
| R2-REQ-09 | Bitemporal history, unknown effective time, gaps и replay |
| R2-REQ-10 | Dependency impact; unknown impact — fail-closed |
| R2-REQ-11 | Durable jobs, fencing, cursor/outbox, бюджеты и backpressure |
| R2-REQ-12 | Drive scope PoC, baseline/change feed, revisions/membership/revoke |
| R2-REQ-13 | Manual native UI capture и qualified UI automation |
| R2-REQ-14 | Qualified standard-engine/batch capture только где поддержано |
| R2-REQ-15 | Раздельные dev/prod permissions, default OFF prod, no business writes |
| R2-REQ-16 | Provenance, независимость oracle, private evidence и attestation |
| R2-REQ-17 | Parser sandbox, no active content, privacy/retention |
| R2-REQ-18 | Decimal/currency/timezone/cutoff/rows deterministic reconciliation |
| R2-REQ-19 | Native 521.1: шесть колонок, expanded balance и аналитики |
| R2-REQ-20 | Posted MOLDRETAIL purchases: identity/filters/fields/completeness |
| R2-REQ-21 | Validation policy по operation, evidence FKs, independent approval |
| R2-REQ-22 | Discrepancy workbench, coverage, lineage и safe explanation |
| R2-REQ-23 | Capacity по маршрутам, backend-wide budgets и измерения |
| R2-REQ-24 | Fault/lag/audit alerts, recovery и restore evidence |
| R2-REQ-25 | Expand/switch/contract, R1 compatibility и safe rollback |
| R2-REQ-26 | Safe read/job APIs, idempotency/CSRF/annotations |
| R2-REQ-27 | Multi-account и отзыв доступа без утечек через cache/index |
| R2-REQ-28 | Reproducible acceptance bundle и честные NOT_RUN/BLOCKED |

## 5. Архитектура

ChatGPT/Claude/Admin UI -> OAuth+ACL+audit -> ERP_MCP query API -> accepted projections -> live source adapters.
Control API -> durable jobs -> Discovery/Connector workers -> OBSERVED registry.
Control API -> Capture Broker -> isolated approved 1C UI/engine runner -> private evidence store -> sandbox parser -> independent verification -> deterministic reconciliation -> accounting approval -> scoped accepted model.

Четыре независимых контура: пользовательское чтение; управление/наблюдение; запуск приложения 1С; evidence/attestation. MCP никогда не получает универсальный Windows executor. Query path не выполняет полный scan или promotion: при обязательной просроченной проверке возвращает safe refusal и может поставить bounded refresh-job только при отдельном разрешении.

## 6. Роли

COMPANY_READER: результаты/модели своей компании, без source-wide metadata автоматически.
CONNECTION_ADMIN: источники, scope, secret refs, revoke; не бухгалтерское утверждение.
DISCOVERY_WORKER: append OBSERVED/events/cursors; не ACCEPTED/VALIDATED.
CAPTURE_OPERATOR/WORKER: утверждённый recipe в разрешённой среде; не admin 1С и не произвольная программа.
EVIDENCE_VERIFIER: проверка происхождения/целостности/параметров.
RECONCILER: детерминированные comparison results, не источник expected values.
ACCOUNTING_APPROVER: независимая подпись конкретного evidence scope.
MODEL_APPROVER: принятие версии по policy+FK evidence+CAS.
AUDITOR: только разрешённый исторический доступ.

Auth identity берётся из проверенного контекста, не из signed_by в JSON. В prod uploader/capture identity не может сама утвердить свой отчёт. DB роли физически отражают разделение обязанностей. Runtime не обслуживает пользователя от owner/superuser/BYPASSRLS.

## 7. Connector contract и lifecycle

Lifecycle: DRAFT -> AUTH_PENDING -> SCOPED -> PROBING -> ACTIVE; отдельные DEGRADED/AUTH_REQUIRED/PAUSED/REVOKED/RETIRED.
SDK: validateConnection, discoverScopes, capabilities, baseline, changes, fetchMetadata, fetchRevision, health, pause, revoke. Optional capabilities объявляются честно. Нет changes capability — SNAPSHOT_ONLY, не выдуманная лента событий.

Обязательный envelope: schema/adapter version, tenant/connection/source/company scope, observation_id, observed_at, coverage, complete, source_revision_basis, cursor_before/after, objects/events, warnings, provenance digest. IDs определяются registry; arbitrary target URL запрещён. Provider credentials не наследуются от ChatGPT OAuth.

At-least-once delivery + idempotent ingest: dedup по scoped provider object/revision/event. Повтор ID с иными bytes — conflict/quarantine. Cursor фиксируется после durable page/events/outbox в одной транзакции. Отзыв scope увеличивает epoch; before fetch и before disclosure обязательная reauthorization. Pause останавливает новые jobs, history не маскируется под live.

## 8. Постоянные LDM/PDM updates

1. При подключении снять разрешённый baseline с coverage. Для event API: стартовый token до baseline, затем догнать changes и разрешить гонки.
2. Проверять дешёвый change signal только если он поддержан и квалифицирован. HEAD/etag/304 не считаются дешёвыми или достоверными без измерения. Иначе полный metadata scan по source budget/окну.
3. Ошибка, partial page, revoked visibility не равны удалению объектов или новой схеме.
4. Сохранить raw SHA-256 для происхождения; отдельный canonical structural hash с versioned canonicalizer.
5. Canonical identity включает namespace, types/precision/scale/nullability, keys, nav/cardinality, enum members и supported operation signatures. Сортировать только семантически незначимый порядок. Short-name collisions не объединяются.
6. OBSERVED snapshot + object-level diff -> полный impact closure accepted dependencies.
7. LDM changes создаются как CANDIDATE. Неизвестное влияние блокирует зависимые operations консервативно. Accepted head публикует отдельная роль по policy и expected_previous_head.
8. Source data changes отслеживаются отдельно: backdated posting может изменить прошлый баланс при неизменной схеме. Нужен новый comparison/run/current applicability, не fake schema drift.

Polling не гарантирует все промежуточные изменения: A->B->A между polls без provider history не восстановить. Показывать SNAPSHOT_ONLY/HISTORY_GAP, interval наблюдений и unknown effective time. Не получать запрещённый direct SQL CDC ради обещания полноты.

## 9. Observed/accepted и состояния

Независимые оси: connectivity, observation_freshness, schema_acceptance, mapping_validation, evidence_validity, data_consistency.

Fresh accepted + validated operation + authorized source -> live read.
Source unavailable -> error live read; историческая карта остаётся с датой и ACL.
Non-impacting change -> продолжение только при доказанной полноте dependencies и заранее разрешённой compatible policy; default approval.
Affected/unknown change -> blocked affected operations, при неполном graph допустима более широкая безопасная блокировка.
Новый artifact -> UNATTESTED; numeric comparison возможен как диагностика, не business PASS.
Same numbers + unproven cutoff/currency -> INCONCLUSIVE.
Новая revision -> historical PASS по прежним immutable bytes сохраняется; применимость к latest снимается.

Автоматическое структурное принятие не подтверждает новую финансовую формулу. LLM не может CONFIRM/VALIDATE ни tool call, ни текстом документа.

## 10. PostgreSQL / Time DB

Стартовая модель совместима с PostgreSQL 16. TimescaleDB optional после benchmark, не обязательная зависимость. Time DB означает bitemporal capabilities.

Новые сущности: connector_instances; memberships; jobs/leases/cursors/outbox; schema_snapshots/object_versions; accepted_heads; logical_concepts/aliases/edges; model_events; capture_recipes/jobs; evidence_artifacts/revisions/attestations; comparison_runs/items/issues; validation_policies/bindings. Existing sources/companies/capabilities/semantic profiles переиспользуются.

Event fields: immutable event_id, schema_version, tenant/source/company, aggregate sequence, event_type, observed_at, recorded_at, source_event_at, effective_from/to nullable, effective_time_basis, source revision, actor, policy, correlation/causation, payload digest, supersedes.

recorded_at — когда узнала система; valid time — когда действовало в источнике, если известно. Unknown effective time не заполняется polling timestamp. Исправления append-only с supersedes; current projections пересобираемы. Запросы AS KNOWN AT и AS EFFECTIVE AT различаются.

Composite keys/FKs/RLS изолируют tenant/company. Большие оригиналы находятся в private versioned store, в Postgres refs/hashes/minimal approved aggregates. Runtime reader не может писать accepted/model evidence. SECURITY DEFINER commands проверяют scope/аргументы/search_path/EXECUTE. Append-only не защищает от DB superuser сам по себе; критичный audit anchor экспортируется в отдельно защищённое хранилище.

## 11. Scheduler и capacity

Durable per-source lease + monotonic fencing token. Старый worker после expiry не может commit. Долгие source calls не удерживают DB transaction/connection. Queue bounded; per-tenant/backend/source/class budgets, fair scheduling, jitter/backoff/circuit breaker/quarantine. Несколько source IDs одной базы и replicas делят физический backend budget.

Interactive reads приоритетнее discovery/capture, но background имеет гарантированный минимальный budget. Conservative проектный старт: capture=1 на backend, writer=1 на source; прочие лимиты не выше target-qualified значений. Значения R1 (1000 sessions, DB pool 10, sidecar 4, fan-out 20/2) — разные слои, не гарантированная capacity.

План тестов: 30/50/100/150 sources; 1/5/10/20/50/100 active clients; отдельно 50/100/500/1000 sessions; один/many physical backends; cold/warm; discovery off/on; metadata/documents/balance/capture; 2h/8h soak. Метрики p50/p95/p99/RPS/error classes/pool wait/queue/CPU/RSS/1C user latency/audit-cursor lag. Быстрые profile refusals не считаются business throughput.

Предлагаемые targets, не измеренный результат: warm metadata p95<=500ms, enqueue p95<=500ms, background interference<=20% p95 при одинаковой нагрузке. Конкретные SLO/stop criteria/hardware утверждаются до нагрузки.

## 12. Native report capture

Поддержать manual UI import, qualified UI automation и qualified standard-engine/batch. Recipe pin: source/config/platform/report object/variant/executor/selector/parameter schema/output format/hash/secret refs/budget/permission/qualification. Вход — recipe_id+typed scope+permit, не command/BSL/sql/arbitrary EPF.

UI: проверить process/base/company, установить и прочитать параметры, открыть штатный отчёт, дождаться завершения, проверить header/fullness, экспортировать original, ingest/hash. Unknown dialog/selector/wrong source -> fail. Отсутствующий UI tool означает ручной baseline или зарегистрированный executor, не возможность через DC filesystem/test runner.

COM standard report допускается только если конкретный отчёт работает и квалифицирован против UI. EMPTY не является нулём. /Execute — optional route для заранее проверенного pinned processing artifact, не произвольный код. Никакого admin fallback, отключения safe mode или подстановки собственного запроса как native oracle.

Job API изменяет собственную control plane: idempotency/CSRF/audit и корректные mutating annotations обязательны, хотя источники читаются read-only.

## 13. Dev/prod безопасность

Dev — разрешённая disposable copy, отдельные credentials и evidence authority; production секреты не копируются. Probes записей и Ferma seeding только отдельный явно разрешённый test harness, не report recipe.

Prod capability default OFF. Enablement: owner+security/ops, source/company, recipe/version/hash, window/expiry, invocation/backend budgets, private output destination, verified permission set и qualification на копии. Разрешение на исполнение не равно бухгалтерскому утверждению.

Штатный report выполняет код конфигурации; читатель может иметь технические записи (логи/settings). Требуются no-business-write rights/contract/qualification и explicit coverage, не обещание byte-identical всей prod базы. Непроверенные side effects -> prod recipe denied; возможен ручной экспорт уполномоченным пользователем. No write probes/reset.ps1 real/prod; не убивать чужие процессы; не перезапускать gateway ради отчёта.

## 14. Evidence / attestation

Hash доказывает bytes, не происхождение. Каждый оригинал UNATTESTED до origin verification. Manifest: source/base/config, report/variant, company, period/timezone/currency/units, grouping/expanded balance/filters, snapshot/cutoff, actor/runner/recipe, capture times, digest/bytes/media/parser, completeness/classification/retention.

Native eligibility R2: настоящий UI manual; qualified automatic UI; qualified standard-engine equivalent UI. Synthetic generator, custom COM query и результат из самого MCP не получают native authority автоматически. Роль connector пишет UNATTESTED refs, а не PASS/VALIDATED.

Numeric verifier выдаёт MATCH/MISMATCH/INCONCLUSIVE; независимый accounting approver ATTESTED; model approver привязывает usable mapping к exact source/company/operation/model/policy/evidence FKs. JSON actor field и 10 arbitrary case IDs не заменяют подпись/coverage/реальные bytes.

Bootstrap: закрытый validation runner с candidate mapping на разрешённой копии выдаёт EVALUATION_ONLY. Он не public bypass профиля, не arbitrary SQL и не основание включить prod. После native comparison/approval -> accepted mapping -> повтор canonical MCP call.

## 15. Сверка 521.1 / purchases

Для 818HA ОСВ 521.1 август2026: отдельно opening Дт/Кт, turnover Дт/Кт, closing Дт/Кт, все строки по counterparty/contract и полнота. Net invariant credit-debit и перенос net полезны, но не заменяют шесть колонок. Совпадение closing не исключает разных opening/turnover: это отдельный тестируемый риск. Набор денежных значений из переписки не является golden truth; наличие второго реального набора здесь независимо не подтверждалось. Денежные детали остаются private, не новые Git fixtures.

Canonical period — локальный полуинтервал [01.08 00:00,01.09 00:00), подтверждённый timezone; wire end semantics квалифицируются per adapter. Не подставлять универсально 23:59:59Z. Currency unknown не считать MDL. Decimal/tolerance policy version обязателен. Snapshot/cutoff must match; concurrent/backdated changes -> INCONCLUSIVE или новый run.

По existing native runbook current payable mapping требует settlement register, которого в 818HA не нашли. Десять отчётов не создают регистр. Нужна явная account-based AP strategy через accounting analytics с отдельным validated mapping. Account balance не доказывает due dates/aging.

Purchases contract: exact company+supplier identity; Posted/DeletionMark/date/number/amount/currency; header/rows; pagination; no auto name-only join. R2 может иметь отдельную policy структурной документной валидации после governance approval, не тихое снятие R1 blanket gate. Поддержка purchases не разблокирует AP/aging.

## 16. Drive

Polling changes.list first. Получить start token до baseline; пройти approved corpus; consume pages; atomic commit+cursor; account/shared-drive cursor namespaces. Feed/current state не гарантируют всех промежуточных версий.

drive.file per-file: выбор папки не доказывает доступ к будущим children. Обязателен PoC new file/move/shortcut/shared-drive/revoke. Более широкий OAuth grant нельзя называть folder-only из-за application filter. Service account требует реальные resource permissions; keyless WIF — separate infrastructure decision.

Viewer/readonly не гарантирует revision history. Не повышать права до writer и не вызывать keepForever update ради архивного download. При недоступной истории сохранить разрешённые current exports в immutable store и явно SNAPSHOT_ONLY/GAP. Dynamic export pin: version before/after и bytes digest; race -> no exact-revision claim.

External OAuth Testing token lifetime с scopes beyond profile требует reconsent/invalid_grant handling; production не строится на «токен вечный». Optional watch: valid HTTPS, channel/token verification, expiry/renewal, duplicate/out-of-order; notification только hint на fetch. Polling сохраняется при отсутствии push.

Новая revision не стирает historical PASS старого immutable artifact, но снимает applicability к latest. Compromise/revoked attestation — отдельное событие с зависимостями.

## 17. Parser/privacy

Sandbox без сети; DTD/entities denied; ZIP bytes/entries/depth/ratio budgets; timeout/RSS; macro/embedded object/external links denied. Формулы не исполняются/пересчитываются; trusted cached values только approved profile, иначе values-only export. OCR — fallback с human check и completeness flag. Prompt injection не получает новых полномочий/URL/SQL.

Начальные parser budgets как targets: input25MiB, inflated200MiB,10000entries,ratio100:1,60s,512MiB RSS. Они квалифицируются под реальные формы; превышение quarantine, не truncated PASS. Новые scopes/raw content sharing/retention/legal hold требуют policy. Удаление отдельно авторизовано, не выполняется этим пакетом.

## 18. UI/API

Connections, Live Model diff, Taxonomy, Timeline, Capture, Evidence Inbox, Workbench, Capacity/Health. Явно: environment/source/company/valid-time/known-time/model version/freshness/trust. BLOCKED имеет safe reason_code, next action, correlation ID; никакого чужого source name/stacktrace/secret ref.

Предлагаемые APIs: create connection; enqueue rescan/report/reconciliation; read model/timeline/job/result; attest evidence; approve model через CAS; pause/revoke. Только типизированные IDs+parameter schema+policy references. Cookie admin mutations с CSRF, все controls idempotent и auditable. Нет API «set status VALIDATED» с произвольным JSON.

## 19. Migration / rollback / приёмка

Expand new tables/roles без изменения R1. Shadow observed-only. Legacy import -> UNATTESTED provenance, не восстановленная выдуманная история. Canary dev+Drive corpus+recipe. Switch per source/company с signed policy. Contract cleanup только отдельно после rollback window; no deletion сейчас.

Rollback возвращает только совместимую version/feature flag, не expired credentials/revoked grants/invalid evidence. При live schema incompatible old head — blocked. Restore проверяет artifact hashes/FKs/event sequences/attestations/current rights.

Выпуск только после G0–G7, mandatory actual tests, native evidence и independent UAT. SPEC/L0 tests пакета проверяют спецификацию, не работу будущего продукта. Все 144 product cases до реализации имеют NOT_RUN.
